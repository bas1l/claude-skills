"""The daily pass: snapshot memories, read every new session window, write notes and counts.

Processes sessions in order, resumed windows first, then oldest first. Sessions that
fail stay unprocessed, so the next run takes them again.

How a run ends:

    ok              everything selected was processed; exit 0
    failed          a session or a memory folder failed, or the run stopped; exit 1
    budget_stopped  the run budget ran out; the rest is listed as backlog; exit 3

What stops a run, and what does not:

    TranscriptFormatError  stops: the transcript format changed, so later sessions would fail too
    ModelCallError         stops: limits, login and network failures repeat for each call
    SchemaError, a window that differs from the one recorded, a call timeout
                           that session only: listed with its id, the others continue

Written under the data folder:

    state/state.json                     processed timestamps and pinned windows
    notes/<date>/<window>/               window.json, counts.json, usage.jsonl, chunk-NNN.json
    counts/<date>/<window>.json          counts by script, including count-only sessions
    logs/usage.jsonl                     one line per model call across runs

``<date>`` is the local date of the end of the window, so a resumed window keeps its folder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence

import extract
import memory_store
import model_call
import schemas
import sessions
import transcripts
from config import Config, load_config

STATUS_OK = "ok"
STATUS_FAILED = "failed"
STATUS_BUDGET_STOPPED = "budget_stopped"
EXIT_CODES = {STATUS_OK: 0, STATUS_FAILED: 1, STATUS_BUDGET_STOPPED: 3}

RESULT_SCHEMA_VERSION = 1
USAGE_FIELDS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")


def state_path(config: Config) -> str:
    return os.path.join(config.paths.data_dir, "state", "state.json")


def init_state(config: Config) -> None:
    """Create the state file once. A missing file is otherwise an error, so that losing
    it cannot silently reprocess every session."""
    path = state_path(config)
    if os.path.exists(path):
        raise FileExistsError(f"state file already exists: {path}")
    sessions.save_state(path, sessions.new_state())


def window_name(item: sessions.WorkItem) -> str:
    """A name stable for a window. State is keyed by folder and id, so the folder is in it."""
    folder_hash = hashlib.sha256(item.files.project_folder.encode("utf-8")).hexdigest()[:8]
    return f"{item.files.session_id}-{folder_hash}-{item.after.strftime('%Y%m%dT%H%M%S%f')}"


def window_date(item: sessions.WorkItem) -> str:
    return item.through.astimezone().strftime("%Y-%m-%d")


def notes_dir_of(item: sessions.WorkItem, config: Config) -> str:
    return os.path.join(config.paths.data_dir, "notes", window_date(item), window_name(item))


def counts_path_of(item: sessions.WorkItem, config: Config) -> str:
    return os.path.join(config.paths.data_dir, "counts", window_date(item), f"{window_name(item)}.json")


@dataclass
class RunTotals:
    """What the model calls of one run used."""

    usage_log_path: str
    run_id: str
    cost_usd: float = 0.0
    calls: int = 0
    model_duration_ms: int = 0
    tokens: dict[str, int] = field(default_factory=lambda: dict.fromkeys(USAGE_FIELDS, 0))

    def wrap(self, call: Callable[..., model_call.ModelResult], session_key: str) -> Callable[..., model_call.ModelResult]:
        """A call that adds to the totals and to the run-wide usage log."""

        def tracked(**kwargs: Any) -> model_call.ModelResult:
            result = call(**kwargs)
            self.cost_usd += result.cost_usd
            self.calls += 1
            self.model_duration_ms += result.duration_ms
            for name in USAGE_FIELDS:
                self.tokens[name] += result.usage[name]
            os.makedirs(os.path.dirname(self.usage_log_path), exist_ok=True)
            with open(self.usage_log_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "run_id": self.run_id,
                    "session": session_key,
                    "usage": result.usage,
                    "model_usage": result.model_usage,
                    "cost_usd": result.cost_usd,
                    "duration_ms": result.duration_ms,
                }, ensure_ascii=False) + "\n")
            return result

        return tracked


def _process_count_only(item: sessions.WorkItem, config: Config, run_id: str) -> int:
    entries = list(
        transcripts.iter_session_entries(item.files.main_path, item.files.subagent_paths, item.after, item.through)
    )
    document, redacted = extract.counts_document(item, entries, config, run_id)
    path = counts_path_of(item, config)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    extract.write_json_atomic(path, document)
    return redacted


def _process_read(
    item: sessions.WorkItem,
    config: Config,
    run_id: str,
    budget_usd: float,
    call: Callable[..., model_call.ModelResult],
) -> dict[str, Any]:
    out_dir = notes_dir_of(item, config)
    summary = extract.extract_window(item, out_dir, config, config.model.extract_model, run_id, budget_usd, call=call)
    path = counts_path_of(item, config)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    shutil.copyfile(os.path.join(out_dir, "counts.json"), path)
    return summary


def _missing_pinned_sessions(state: Mapping[str, Any], discovered: Sequence[sessions.SessionFiles]) -> list[str]:
    """Pinned windows whose transcript is gone: they can never finish, so they are failures."""
    known = {files.state_key for files in discovered}
    return sorted(
        key for key, entry in state["sessions"].items() if entry.get("pending") is not None and key not in known
    )


def run_daily(
    config: Config,
    run_id: str,
    call: Callable[..., model_call.ModelResult] = model_call.call_model,
) -> dict[str, Any]:
    """Run the pass and return its result. Everything written is committed locally at the end."""
    started = time.monotonic()
    message = f"Snapshot of edits by live sessions, upkeep run {run_id}"
    snapshot = memory_store.snapshot_all(config.paths.projects_dir, config.memory, message)

    path = state_path(config)
    state = sessions.load_state(path)
    totals = RunTotals(os.path.join(config.paths.data_dir, "logs", "usage.jsonl"), run_id)
    failed: list[dict[str, str]] = []
    stop_reason: Optional[str] = None
    budget_stopped = False
    backlog: list[str] = []
    selected = 0
    processed_read = 0
    processed_count_only = 0
    notes = 0
    secrets_redacted = 0

    try:
        discovered = sessions.discover_sessions(config.paths.projects_dir)
        failed.extend(
            {"session": key, "error": "a pinned window's transcript is gone"}
            for key in _missing_pinned_sessions(state, discovered)
        )
        work = sessions.select_work(discovered, state, config.sessions)
        work.sort(key=lambda item: (not item.resumed, item.through))
        selected = len(work)
        for position, item in enumerate(work):
            key = item.files.state_key
            remaining = [other.files.state_key for other in work[position:]]
            if item.mode == sessions.MODE_READ and totals.cost_usd >= config.model.run_budget_usd:
                budget_stopped = True
                backlog = remaining
                break
            if not item.resumed:
                sessions.pin_window(state, item)
                sessions.save_state(path, state)
            print(f"[{position + 1}/{len(work)}] {key} {item.mode}", flush=True)
            try:
                if item.mode == sessions.MODE_COUNT_ONLY:
                    secrets_redacted += _process_count_only(item, config, run_id)
                    processed_count_only += 1
                else:
                    summary = _process_read(
                        item, config, run_id, config.model.run_budget_usd - totals.cost_usd, totals.wrap(call, key)
                    )
                    notes += summary["notes"]
                    secrets_redacted += summary["secrets_redacted"]
                    processed_read += 1
            except model_call.BudgetExhaustedError:
                budget_stopped = True
                backlog = remaining
                break
            except (schemas.SchemaError, extract.WindowMismatchError, subprocess.TimeoutExpired) as error:
                failed.append({"session": key, "error": f"{type(error).__name__}: {error}"})
                continue
            sessions.mark_processed(state, item)
            sessions.save_state(path, state)
    except (transcripts.TranscriptFormatError, model_call.ModelCallError) as error:
        stop_reason = f"{type(error).__name__}: {error}"

    if stop_reason is not None or failed or snapshot["errors"]:
        status = STATUS_FAILED
    elif budget_stopped:
        status = STATUS_BUDGET_STOPPED
    else:
        status = STATUS_OK

    data_commit = memory_store.commit_all(config.paths.data_dir, config.memory, f"Daily pass {run_id}: {status}")
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "pass": "daily",
        "run_id": run_id,
        "status": status,
        "stop_reason": stop_reason,
        "budget_stopped": budget_stopped,
        "sessions_selected": selected,
        "sessions_read": processed_read,
        "sessions_count_only": processed_count_only,
        "failed_sessions": failed,
        "backlog_sessions": backlog,
        "notes": notes,
        "secrets_redacted": secrets_redacted,
        "model_calls": totals.calls,
        "tokens": totals.tokens,
        "cost_usd": round(totals.cost_usd, 4),
        "model_duration_ms": totals.model_duration_ms,
        "wall_seconds": round(time.monotonic() - started, 1),
        "memory_snapshot": {
            "created": snapshot[memory_store.RESULT_CREATED],
            "committed": snapshot[memory_store.RESULT_COMMITTED],
            "unchanged": len(snapshot[memory_store.RESULT_UNCHANGED]),
            "empty": len(snapshot[memory_store.RESULT_EMPTY]),
            "errors": snapshot["errors"],
        },
        "data_commit": data_commit,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("run", "init-state"))
    parser.add_argument("--config", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--result-file")
    arguments = parser.parse_args(argv)
    config = load_config(arguments.config)
    if arguments.action == "init-state":
        init_state(config)
        return 0
    if not arguments.run_id or not arguments.result_file:
        raise ValueError("run needs --run-id and --result-file")
    result = run_daily(config, arguments.run_id)
    with open(arguments.result_file, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=1)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=1)
    print()
    return EXIT_CODES[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
