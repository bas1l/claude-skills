"""Daily extraction: read one session window, chunk by chunk, into validated notes.

Resumable per chunk: a chunk file is written atomically only after validation, and a
rerun skips chunks already on disk, so an interruption leaves no duplicates and loses
nothing. A rerun whose chunks differ from those recorded raises.

Files in the output folder, each self-describing:

    window.json        the window and the hash of every chunk
    counts.json        counts by script
    usage.jsonl        one line per model call, from model_call
    chunk-NNN.json     validated notes for one chunk
    chunk-NNN.rejected raw reply that failed validation, for reading
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime
from typing import Any, Callable, Mapping, Optional, Sequence

import counts as counts_module
import model_call
import quotes
import render
import schemas
import sessions
import transcripts
from config import Config, load_config

WINDOW_SCHEMA_VERSION = 1
CHUNK_SCHEMA_VERSION = 2
PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", "extract.md")

QUOTE_VERIFIED = "verified"
QUOTE_NOT_FOUND = "not_found"
QUOTE_NONE = "no_quote"


class WindowMismatchError(ValueError):
    """Chunks on disk do not belong to this window, so resuming would mix two readings."""


def write_json_atomic(path: str, document: Mapping[str, Any]) -> None:
    directory = os.path.dirname(path)
    descriptor, temporary = tempfile.mkstemp(dir=directory, prefix=".part-", suffix=".tmp")
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=1)
    os.replace(temporary, path)


def read_prompt() -> str:
    with open(PROMPT_PATH, encoding="utf-8") as handle:
        return handle.read()


def chunk_file_name(number: int) -> str:
    return f"chunk-{number:03d}.json"


def quote_check_of(note: schemas.Note, entries: Sequence[transcripts.Entry]) -> str:
    if note.endorsement not in schemas.ENDORSEMENTS_WITH_QUOTE:
        return QUOTE_NONE
    return QUOTE_VERIFIED if quotes.quote_is_in_user_entries(note.endorsement_quote, entries) else QUOTE_NOT_FOUND


def _check_window_file(path: str, document: Mapping[str, Any]) -> None:
    """On a rerun the chunks must be the ones already recorded; otherwise resuming would mix them."""
    if not os.path.exists(path):
        write_json_atomic(path, document)
        return
    with open(path, encoding="utf-8") as handle:
        existing = json.load(handle)
    if existing != document:
        raise WindowMismatchError(f"{path}: this window's chunks differ from those recorded; refusing to resume")


def _validated_chunk_on_disk(path: str, chunk: render.Chunk) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    if document.get("schema_version") != CHUNK_SCHEMA_VERSION:
        raise WindowMismatchError(f"{path}: chunk schema version {document.get('schema_version')!r}")
    if document.get("chunk_sha256") != chunk.sha256:
        raise WindowMismatchError(f"{path}: chunk hash differs from this window; refusing to resume")
    return document


def redact_value(value: Any, config: Config) -> tuple[Any, int]:
    """A JSON-ready value with secret patterns replaced in every string, and the match count."""
    if isinstance(value, str):
        return render.redact_counted(value, config.secrets)
    if isinstance(value, list):
        pairs = [redact_value(item, config) for item in value]
        return [item for item, _ in pairs], sum(count for _, count in pairs)
    if isinstance(value, dict):
        pairs = {key: redact_value(item, config) for key, item in value.items()}
        return {key: pair[0] for key, pair in pairs.items()}, sum(pair[1] for pair in pairs.values())
    return value, 0


def counts_document(
    item: sessions.WorkItem, entries: Sequence[transcripts.Entry], config: Config, run_id: str
) -> tuple[dict[str, Any], int]:
    """Counts for a window, with secret patterns redacted from error signatures and the like."""
    counted, redacted = redact_value(counts_module.count_entries(entries, config.counts), config)
    return (
        {
            "session_id": item.files.session_id,
            "project_cwd": item.project_cwd,
            "after": item.after.isoformat(),
            "through": item.through.isoformat(),
            "run_id": run_id,
            **counted,
        },
        redacted,
    )


def _usage_summary(result: model_call.ModelResult) -> dict[str, Any]:
    return {
        "usage": result.usage,
        "model_usage": result.model_usage,
        "cost_usd": result.cost_usd,
        "duration_ms": result.duration_ms,
        "num_turns": result.num_turns,
    }


def extract_window(
    item: sessions.WorkItem,
    out_dir: str,
    config: Config,
    model: Optional[str],
    run_id: str,
    budget_usd: float,
    only_chunks: Optional[Sequence[int]] = None,
    call: Callable[..., model_call.ModelResult] = model_call.call_model,
) -> dict[str, Any]:
    """Process one window and return a summary. Raises on any invalid reply or result.

    ``model=None`` uses the session default. ``budget_usd`` limits this call of the
    function; a caller holding a run budget passes what remains.
    """
    if item.mode != sessions.MODE_READ:
        raise ValueError(f"session {item.files.session_id}: mode {item.mode!r} is not for model reading")
    os.makedirs(out_dir, exist_ok=True)

    entries = list(
        transcripts.iter_session_entries(item.files.main_path, item.files.subagent_paths, item.after, item.through)
    )
    counts_doc, counts_redacted = counts_document(item, entries, config, run_id)
    write_json_atomic(os.path.join(out_dir, "counts.json"), counts_doc)
    user_entries = [entry for entry in entries if entry.kind in transcripts.USER_OWN_KINDS]
    rendered = render.render_entries(entries, config.cuts, config.secrets)
    timeline = render.build_timeline(rendered)
    chunks = render.split_into_chunks(rendered, config.chunking.chunk_chars)
    del entries

    _check_window_file(
        os.path.join(out_dir, "window.json"),
        {
            "schema_version": WINDOW_SCHEMA_VERSION,
            "session_id": item.files.session_id,
            "project_cwd": item.project_cwd,
            "after": item.after.isoformat(),
            "through": item.through.isoformat(),
            "chunk_chars": config.chunking.chunk_chars,
            "timeline_chars": len(timeline),
            "rendered_chars": sum(len(entry.text) for entry in rendered),
            "rendered_entries": len(rendered),
            "chunks": [
                {
                    "number": chunk.number,
                    "sha256": chunk.sha256,
                    "chars": len(chunk.entries_text),
                    "entries": chunk.entry_count,
                    "first": chunk.first_timestamp.isoformat(),
                    "last": chunk.last_timestamp.isoformat(),
                }
                for chunk in chunks
            ],
        },
    )

    wanted = set(only_chunks) if only_chunks is not None else {chunk.number for chunk in chunks}
    unknown = wanted - {chunk.number for chunk in chunks}
    if unknown:
        raise ValueError(f"no such chunks: {sorted(unknown)} of {len(chunks)}")

    prompt = read_prompt()
    spent = 0.0
    processed = []
    for chunk in chunks:
        if chunk.number not in wanted:
            continue
        path = os.path.join(out_dir, chunk_file_name(chunk.number))
        if os.path.exists(path):
            processed.append(_validated_chunk_on_disk(path, chunk))
            continue
        result = call(
            prompt=prompt,
            stdin_text=render.chunk_input_text(chunk, timeline),
            tools=(),
            model=model,
            max_budget_usd=budget_usd - spent,
            cwd=config.paths.run_dir,
            claude_exe=config.paths.claude_exe,
            model_config=config.model,
            chunking_config=config.chunking,
            usage_log_path=os.path.join(out_dir, "usage.jsonl"),
        )
        spent += result.cost_usd
        try:
            notes = schemas.parse_notes(result.text)
        except schemas.SchemaError:
            with open(path[: -len(".json")] + ".rejected", "w", encoding="utf-8") as handle:
                handle.write(render.redact_secrets(result.text, config.secrets))
            raise
        # The quote check needs the note as written, so redaction comes after it.
        checked_notes, notes_redacted = redact_value(
            [{**note.to_json(), "quote_check": quote_check_of(note, user_entries)} for note in notes], config
        )
        document = {
            "schema_version": CHUNK_SCHEMA_VERSION,
            "notes_schema_version": schemas.NOTES_SCHEMA_VERSION,
            "run_id": run_id,
            "session_id": item.files.session_id,
            "project_cwd": item.project_cwd,
            "chunk": chunk.number,
            "chunk_total": chunk.total,
            "chunk_sha256": chunk.sha256,
            "first": chunk.first_timestamp.isoformat(),
            "last": chunk.last_timestamp.isoformat(),
            "model_requested": model,
            **_usage_summary(result),
            "secrets_redacted": notes_redacted,
            "notes": checked_notes,
        }
        write_json_atomic(path, document)
        processed.append(document)

    return {
        "session_id": item.files.session_id,
        "chunks_total": len(chunks),
        "chunks_done": sorted(document["chunk"] for document in processed),
        "notes": sum(len(document["notes"]) for document in processed),
        "secrets_redacted": counts_redacted + sum(document["secrets_redacted"] for document in processed),
        "spent_this_call_usd": spent,
    }


def whole_session_item(files: sessions.SessionFiles, config: Config) -> sessions.WorkItem:
    """A window over a whole session, ignoring the start date and state: for trials only."""
    span = sessions.read_span(files)
    if span is None:
        raise ValueError(f"session {files.session_id} holds no conversation")
    mode = sessions.mode_of_cwds(span.cwd_counts, config.sessions)
    if mode != sessions.MODE_READ:
        raise ValueError(f"session {files.session_id} is not read by the model: mode {mode!r}")
    return sessions.WorkItem(
        files=files,
        after=datetime.fromtimestamp(span.first.timestamp() - 1, tz=span.first.tzinfo),
        through=span.last,
        mode=mode,
        project_cwd=sessions.project_of_cwds(span.cwd_counts),
        resumed=False,
    )


def _find_session(session_prefix: str, config: Config) -> sessions.SessionFiles:
    matches = [
        files for files in sessions.discover_sessions(config.paths.projects_dir)
        if files.session_id.startswith(session_prefix)
    ]
    if len(matches) != 1:
        raise ValueError(f"session prefix {session_prefix!r} matches {len(matches)} sessions")
    return matches[0]


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run extraction on one whole session. The daily pass calls ``extract_window`` directly."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, help="session id or unique prefix")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--model", required=True, help="model name, or 'session-default' for no --model flag")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--budget-usd", required=True, type=float)
    parser.add_argument("--chunks", help="comma-separated chunk numbers; all if absent")
    arguments = parser.parse_args(argv)

    config = load_config()
    item = whole_session_item(_find_session(arguments.session, config), config)
    summary = extract_window(
        item,
        arguments.out_dir,
        config,
        None if arguments.model == "session-default" else arguments.model,
        arguments.run_id,
        arguments.budget_usd,
        only_chunks=[int(number) for number in arguments.chunks.split(",")] if arguments.chunks else None,
    )
    json.dump(summary, sys.stdout, indent=1)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
