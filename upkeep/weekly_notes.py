"""What the weekly pass reads: finished note windows, counts across sessions, and their source.

Everything here is read-only. A window counts only once it is complete: the state file says
it was processed and all its chunks are on disk. A window whose transcript is gone, or that is
not complete, is listed as skipped and left for a later week.
"""
from __future__ import annotations

import collections
import glob
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence

import render
import schemas
import sessions
import transcripts
from config import Config, WeeklyConfig

_SOURCE_KINDS = transcripts.USER_OWN_KINDS | {transcripts.ASSISTANT_TEXT}
_PROPOSAL_ROUTES = frozenset({"skill", "hook", "mcp", "global_rule", "script_count"})
_PROPOSAL_TYPES = frozenset({"failure", "procedure"})
ONE_MOMENT_ORDER = "one_moment_order"


def folder_hash(project_folder: str) -> str:
    """The short hash of a project folder, as the daily pass puts it in a window's name."""
    return hashlib.sha256(project_folder.encode("utf-8")).hexdigest()[:8]


@dataclass(frozen=True)
class Window:
    key: str
    session_id: str
    project_folder: str
    project_cwd: str
    after: datetime
    through: datetime
    files: sessions.SessionFiles


@dataclass(frozen=True)
class NoteRecord:
    window: Window
    values: Mapping[str, Any]
    items: tuple[Mapping[str, Any], ...]
    source: str
    note_index: int
    last: datetime

    def source_json(self) -> dict[str, Any]:
        return {"notes": self.source, "note_index": self.note_index}


@dataclass(frozen=True)
class FailureCount:
    ref: str
    tool: str
    signature: str
    commands_lost: int
    sessions: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "ref": self.ref, "tool": self.tool, "signature": self.signature,
            "commands_lost": self.commands_lost, "sessions": len(self.sessions),
        }


@dataclass(frozen=True)
class ProcedureCount:
    ref: str
    name: str
    session_id: str
    calls: int


def _read_json(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def load_windows(
    config: Config,
    state: Mapping[str, Any],
    consumed: Mapping[str, str],
    discovered: Sequence[sessions.SessionFiles],
) -> tuple[list[NoteRecord], list[Window], list[dict[str, str]]]:
    """All notes of complete windows not yet consumed: notes, windows, and what was skipped."""
    by_hash = {(files.session_id, folder_hash(files.project_folder)): files for files in discovered}
    notes_root = os.path.join(config.paths.data_dir, "notes")
    records: list[NoteRecord] = []
    windows: list[Window] = []
    skipped: list[dict[str, str]] = []
    for path in sorted(glob.glob(os.path.join(glob.escape(notes_root), "*", "*", "window.json"))):
        directory = os.path.dirname(path)
        key = os.path.relpath(directory, notes_root).replace(os.sep, "/")
        if key in consumed:
            continue
        recorded = _read_json(path)
        session_id = recorded["session_id"]
        name = os.path.basename(directory)
        files = by_hash.get((session_id, name[len(session_id) + 1:][:8]))
        if files is None:
            skipped.append({"window": key, "reason": "its transcript is gone"})
            continue
        through = datetime.fromisoformat(recorded["through"])
        processed = state["sessions"].get(files.state_key, {}).get("processed_through")
        chunk_paths = sorted(glob.glob(os.path.join(glob.escape(directory), "chunk-*.json")))
        if processed is None or datetime.fromisoformat(processed) < through or len(chunk_paths) != len(recorded["chunks"]):
            skipped.append({"window": key, "reason": "the window is not complete"})
            continue
        window = Window(
            key=key,
            session_id=session_id,
            project_folder=files.project_folder,
            project_cwd=recorded["project_cwd"],
            after=datetime.fromisoformat(recorded["after"]),
            through=through,
            files=files,
        )
        windows.append(window)
        for chunk_path in chunk_paths:
            records.extend(_records_of_chunk(chunk_path, window, os.path.dirname(notes_root)))
    return records, windows, skipped


def _records_of_chunk(path: str, window: Window, data_dir: str) -> list[NoteRecord]:
    document = _read_json(path)
    version = document["notes_schema_version"]
    if version not in (schemas.NOTES_SCHEMA_WITHOUT_ITEMS, schemas.NOTES_SCHEMA_VERSION):
        raise ValueError(f"{path}: notes schema version {version!r}")
    relative = os.path.relpath(path, data_dir).replace(os.sep, "/")
    return [
        NoteRecord(
            window=window,
            values=note,
            items=() if version == schemas.NOTES_SCHEMA_WITHOUT_ITEMS else tuple(note["items"]),
            source=relative,
            note_index=index,
            last=datetime.fromisoformat(document["last"]),
        )
        for index, note in enumerate(document["notes"])
    ]


def is_memory_note(record: NoteRecord, config: WeeklyConfig) -> bool:
    """Notes the memory step may draw on. One-moment orders and web text never reach it."""
    note = record.values
    if note["type"] == ONE_MOMENT_ORDER or note["origin_of_point"] in config.memory_excluded_origins:
        return False
    speaks_of_memory = any(
        item["kind"] == "memory" and item["stance"] != schemas.STANCE_NO_BEARING for item in record.items
    )
    return note["memory_candidate"] or note["route"] == "memory" or speaks_of_memory


def is_proposal_note(record: NoteRecord) -> bool:
    note = record.values
    if note["type"] == ONE_MOMENT_ORDER:
        return False
    return note["route"] in _PROPOSAL_ROUTES or note["type"] in _PROPOSAL_TYPES


def aggregate_counts(
    config: Config, consumed: Mapping[str, str]
) -> tuple[list[FailureCount], list[ProcedureCount]]:
    """Across all unconsumed windows, by script: failures ranked by commands lost, then
    procedures at or over the threshold in one session. Only literal error starts are grouped;
    keyword class hints are never counted."""
    counts_root = os.path.join(config.paths.data_dir, "counts")
    lost: collections.Counter[tuple[str, str]] = collections.Counter()
    seen_in: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    procedures: collections.Counter[tuple[str, str]] = collections.Counter()
    for path in sorted(glob.glob(os.path.join(glob.escape(counts_root), "*", "*.json"))):
        key = os.path.relpath(path, counts_root).replace(os.sep, "/")[: -len(".json")]
        if key in consumed:
            continue
        document = _read_json(path)
        session_id = document["session_id"]
        for source in ("main", "subagent"):
            part = document[source]
            for error in part["error_signatures"]:
                failure = (error["tool"], error["signature"])
                lost[failure] += error["count"]
                seen_in[failure].add(session_id)
            for denial in part["denials"]:
                failure = (denial["tool"], f"refused: {denial['kind']}")
                lost[failure] += denial["count"]
                seen_in[failure].add(session_id)
            for hook, count in part["hook_blocks"].items():
                failure = (hook, "blocked by this hook")
                lost[failure] += count
                seen_in[failure].add(session_id)
            for name, count in part["procedures"].items():
                procedures[(session_id, name)] += count
            for name, count in part["tool_calls"].items():
                if name not in config.counts.shell_tools:
                    procedures[(session_id, f"{name}:calls")] += count
    ranked = sorted(lost.items(), key=lambda pair: (-pair[1], pair[0]))
    failures = [
        FailureCount(f"f{position}", tool, signature, count, tuple(sorted(seen_in[(tool, signature)])))
        for position, ((tool, signature), count) in enumerate(ranked, 1)
    ]
    frequent = sorted(
        (pair for pair in procedures.items() if pair[1] >= config.weekly.costly_once_tool_calls),
        key=lambda pair: (-pair[1], pair[0]),
    )
    return failures, [
        ProcedureCount(f"p{position}", name, session_id, count)
        for position, ((session_id, name), count) in enumerate(frequent, 1)
    ]


class SourceStore:
    """The user's messages and the assistant text of each window, read once when first needed."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._entries: dict[str, list[transcripts.Entry]] = {}

    def entries(self, window: Window) -> list[transcripts.Entry]:
        if window.key not in self._entries:
            files = window.files
            self._entries[window.key] = [
                entry
                for entry in transcripts.iter_session_entries(files.main_path, files.subagent_paths, window.after, window.through)
                if entry.kind in _SOURCE_KINDS
            ]
        return self._entries[window.key]

    def exchanges(self, window: Window) -> str:
        return render.render_exchanges(
            self.entries(window), self._config.cuts, self._config.secrets, self._config.weekly.source_assistant_chars
        )


def render_note(ref: str, session_ref: str, record: NoteRecord) -> str:
    """One note as one line of JSON, for a prompt."""
    note = record.values
    return json.dumps(
        {
            "ref": ref,
            "session": session_ref,
            "type": note["type"],
            "what": note["what"],
            "evidence": note["evidence"],
            "endorsement": note["endorsement"],
            "quote": note["endorsement_quote"],
            "quote_check": note["quote_check"],
            "origin": note["origin_of_point"],
            "route": note["route"],
        },
        ensure_ascii=False,
    )


@dataclass(frozen=True)
class MemoryGroup:
    """The notes of one project, or of part of one if it is too large for one call."""

    name: str
    project_folder: str
    records: tuple[NoteRecord, ...]
    windows: tuple[Window, ...]


def memory_groups(records: Sequence[NoteRecord], store: SourceStore, config: WeeklyConfig) -> list[MemoryGroup]:
    """Group memory notes by project. A project over ``group_chars`` of source is split between
    sessions, never inside one, so one session's quotes always travel with its notes."""
    by_project: dict[str, dict[str, list[NoteRecord]]] = {}
    windows: dict[str, Window] = {}
    for record in records:
        if is_memory_note(record, config):
            by_project.setdefault(record.window.project_folder, {}).setdefault(record.window.key, []).append(record)
            windows[record.window.key] = record.window
    groups = []
    for project_folder in sorted(by_project):
        parts: list[list[str]] = [[]]
        size = 0
        for key in sorted(by_project[project_folder]):
            added = len(store.exchanges(windows[key]))
            if parts[-1] and size + added > config.group_chars:
                parts.append([])
                size = 0
            parts[-1].append(key)
            size += added
        for number, keys in enumerate(parts, 1):
            groups.append(MemoryGroup(
                name=f"{folder_hash(project_folder)}-{number}",
                project_folder=project_folder,
                records=tuple(record for key in keys for record in by_project[project_folder][key]),
                windows=tuple(windows[key] for key in keys),
            ))
    return groups


def word_overlap(first: str, second: str) -> float:
    """Shared words over all words, ignoring case. 1 for the same words, 0 for none shared."""
    first_words = set(plain_words(first))
    second_words = set(plain_words(second))
    if not first_words or not second_words:
        return 0.0
    return len(first_words & second_words) / len(first_words | second_words)


def plain_words(text: str) -> list[str]:
    return "".join(character.lower() if character.isalnum() else " " for character in text).split()


def latest_decision_for(
    decisions: Sequence[Mapping[str, Any]],
    scope: str,
    kind: str,
    name: str,
    action: str,
    claim: str,
    overlap: float,
) -> Optional[Mapping[str, Any]]:
    """The latest undo or rejection this would repeat: the same item and action, or wording
    that shares at least ``overlap`` of its words, since a model will not reword the same way."""
    matches = [
        decision
        for decision in decisions
        if decision["scope"] == scope
        and decision["kind"] == kind
        and ((decision["name"] == name and decision["action"] == action) or word_overlap(decision["claim"], claim) >= overlap)
    ]
    return max(matches, key=lambda decision: datetime.fromisoformat(decision["decided_at"])) if matches else None
