"""Choose which sessions to process and over which window, and track processed state.

Reads only the metadata of a transcript record (timestamp, working directory, session
id), never its content. The project of a session comes from each record's ``cwd``,
because project folder names are lossy: two different paths can map to one name, and
one path has appeared under two spellings.

State file shape:

    {"schema_version": 1,
     "sessions": {"<folder>/<id>": {"processed_through": "<iso>",
                                    "pending": {"after": "<iso>", "through": "<iso>",
                                                "mode": "read", "project_cwd": "<path>"}}}}

``pending`` pins an open window, so an interrupted run resumes the same window instead
of computing a new one. It is cleared when the window completes.

State is keyed by project folder and id because one session id can exist in two project
folders, as an identical copy or as two different lengths. Each file is tracked on its
own, so a session copied after the start date is read twice.
"""
from __future__ import annotations

import collections
import glob
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

import transcripts
from config import SessionsConfig

STATE_SCHEMA_VERSION = 1
MODE_READ = "read"
MODE_COUNT_ONLY = "count_only"


@dataclass(frozen=True)
class SessionFiles:
    project_folder: str
    session_id: str
    main_path: str
    subagent_paths: tuple[str, ...]

    @property
    def state_key(self) -> str:
        return f"{self.project_folder}/{self.session_id}"


@dataclass(frozen=True)
class SessionSpan:
    first: datetime
    last: datetime
    cwd_counts: Mapping[str, int]


@dataclass(frozen=True)
class WorkItem:
    """One session and the window ``after < timestamp <= through`` to process."""

    files: SessionFiles
    after: datetime
    through: datetime
    mode: str
    project_cwd: str
    resumed: bool


def discover_sessions(projects_dir: str) -> list[SessionFiles]:
    """List every session: ``<project>/<id>.jsonl`` and ``<project>/<id>/subagents/**/agent-*.jsonl``."""
    if not os.path.isdir(projects_dir):
        raise FileNotFoundError(f"projects folder not found: {projects_dir}")
    found: list[SessionFiles] = []
    for project in sorted(os.listdir(projects_dir)):
        project_dir = os.path.join(projects_dir, project)
        if not os.path.isdir(project_dir):
            continue
        for name in sorted(os.listdir(project_dir)):
            if not name.endswith(".jsonl"):
                continue
            session_id = name[: -len(".jsonl")]
            pattern = os.path.join(glob.escape(project_dir), glob.escape(session_id), "subagents", "**", "agent-*.jsonl")
            found.append(
                SessionFiles(
                    project_folder=project,
                    session_id=session_id,
                    main_path=os.path.join(project_dir, name),
                    subagent_paths=tuple(sorted(glob.glob(pattern, recursive=True))),
                )
            )
    return found


def _all_paths(files: SessionFiles) -> tuple[str, ...]:
    return (files.main_path, *files.subagent_paths)


def newest_change(files: SessionFiles) -> datetime:
    """The latest modification time across a session's files."""
    return datetime.fromtimestamp(max(os.path.getmtime(path) for path in _all_paths(files)), tz=timezone.utc)


def read_span(files: SessionFiles) -> Optional[SessionSpan]:
    """Timestamps and working directories of a session; None if it holds no conversation yet."""
    first: Optional[datetime] = None
    last: Optional[datetime] = None
    cwd_counts: collections.Counter[str] = collections.Counter()
    for path in _all_paths(files):
        for line_number, record in transcripts.iter_records(path):
            if record["type"] not in transcripts.CONVERSATION_RECORD_TYPES:
                continue
            where = f"{path}:{line_number}"
            if record.get("sessionId") != files.session_id:
                raise transcripts.TranscriptFormatError(f"{where}: sessionId differs from the file's session")
            for key in ("timestamp", "cwd"):
                if key not in record:
                    raise transcripts.TranscriptFormatError(f"{where}: missing field {key!r}")
            timestamp = transcripts.parse_timestamp(record["timestamp"])
            first = timestamp if first is None or timestamp < first else first
            last = timestamp if last is None or timestamp > last else last
            cwd_counts[record["cwd"]] += 1
    if first is None or last is None:
        return None
    return SessionSpan(first=first, last=last, cwd_counts=dict(cwd_counts))


def _is_under(path: str, prefix: str) -> bool:
    normal_path = os.path.normcase(os.path.normpath(path))
    normal_prefix = os.path.normcase(os.path.normpath(prefix))
    return normal_path == normal_prefix or normal_path.startswith(normal_prefix + os.sep)


def mode_of_cwds(cwds: Mapping[str, int], config: SessionsConfig) -> Optional[str]:
    """Return how to treat a session from its working directories; None means excluded.

    A session is excluded or count-only only when every record's directory is, so one
    that moved into a normal project is still read.
    """
    if all(any(_is_under(cwd, prefix) for prefix in config.excluded_cwd_prefixes) for cwd in cwds):
        return None
    if all(any(_is_under(cwd, prefix) for prefix in config.count_only_cwd_prefixes) for cwd in cwds):
        return MODE_COUNT_ONLY
    return MODE_READ


def project_of_cwds(cwds: Mapping[str, int]) -> str:
    """The directory most of a session's records ran in, ties broken by name."""
    return min(cwds, key=lambda cwd: (-cwds[cwd], cwd))


def select_work(files_list: list[SessionFiles], state: Mapping[str, Any], config: SessionsConfig) -> list[WorkItem]:
    """Choose sessions with unprocessed records after the forward-only start date.

    A session with a pinned window is returned first with that window. A session with
    nothing new since its recorded timestamp is skipped.
    """
    known = state["sessions"]
    work: list[WorkItem] = []
    for files in files_list:
        entry = known.get(files.state_key, {})
        pending = entry.get("pending")
        if pending is not None:
            work.append(
                WorkItem(
                    files=files,
                    after=datetime.fromisoformat(pending["after"]),
                    through=datetime.fromisoformat(pending["through"]),
                    mode=pending["mode"],
                    project_cwd=pending["project_cwd"],
                    resumed=True,
                )
            )
            continue
        processed = entry.get("processed_through")
        after = datetime.fromisoformat(processed) if processed is not None else config.start_date
        if newest_change(files) <= after:
            continue
        span = read_span(files)
        if span is None or span.last <= after:
            continue
        mode = mode_of_cwds(span.cwd_counts, config)
        if mode is None:
            continue
        work.append(
            WorkItem(
                files=files,
                after=after,
                through=span.last,
                mode=mode,
                project_cwd=project_of_cwds(span.cwd_counts),
                resumed=False,
            )
        )
    return work


def new_state() -> dict[str, Any]:
    return {"schema_version": STATE_SCHEMA_VERSION, "sessions": {}}


def load_state(path: str) -> dict[str, Any]:
    """Read the state file. A missing file raises; the first run creates it explicitly."""
    with open(path, encoding="utf-8") as handle:
        state = json.load(handle)
    if state.get("schema_version") != STATE_SCHEMA_VERSION:
        raise ValueError(f"state file {path}: schema_version {state.get('schema_version')!r}")
    return state


def save_state(path: str, state: Mapping[str, Any]) -> None:
    """Write the state file atomically, so an interruption cannot leave half a file."""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=directory, prefix=".state-", suffix=".tmp")
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=1, sort_keys=True)
    os.replace(temporary, path)


def pin_window(state: dict[str, Any], item: WorkItem) -> None:
    """Record the window being processed, so a rerun after an interruption reuses it."""
    state["sessions"].setdefault(item.files.state_key, {})["pending"] = {
        "after": item.after.isoformat(),
        "through": item.through.isoformat(),
        "mode": item.mode,
        "project_cwd": item.project_cwd,
    }


def mark_processed(state: dict[str, Any], item: WorkItem) -> None:
    """Record that every message up to ``item.through`` has validated results on disk."""
    entry = state["sessions"].setdefault(item.files.state_key, {})
    if entry.get("pending") is None:
        raise ValueError(f"session {item.files.state_key}: marking a window that was never pinned")
    entry["processed_through"] = item.through.isoformat()
    entry["pending"] = None
