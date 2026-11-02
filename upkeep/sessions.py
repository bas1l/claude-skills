"""Choose which sessions to process and over which window, and track processed state.

Reads only the metadata of a transcript record (timestamp, working directory, session
id), never its content. The project of a session comes from each record's ``cwd``,
because project folder names are lossy: two different paths can map to one name, and
one path has appeared under two spellings.

State file shape:

    {"schema_version": 2,
     "sessions": {"<folder>/<id>": {"processed_through": "<iso>",
                                    "lines_read": {"<file>": <last line read>},
                                    "pending": {"after": "<iso>", "through": "<iso>",
                                                "lines_after": {...}, "lines_through": {...},
                                                "floor": "<iso>",
                                                "mode": "read", "project_cwd": "<path>"}}}}

``pending`` pins an open window, so an interrupted run resumes the same window instead
of computing a new one. It is cleared when the window completes.

A window is limited by line and not by time, because records are not written in time order: a
queued message is written after records stamped later than itself. ``after`` and ``through`` remain
what they were for the notes: the newest stamp read before the window and at its end. A session
whose records are only late ones has ``through == after``.

Carrying over schema version 1, which held timestamps only. For each file, the lines read are the
run of lines from the start with stamps at or before ``processed_through``. Any line after that run
was certainly written after that read, because every record then on disk was stamped at or before it.
A late record inside that run cannot be told apart, and counts as read, as it did before. A pinned
window is carried over the same way, at both ends; if that changes what it holds, its chunks no longer
match and it is read again by the existing reset.

State is keyed by project folder and id because one session id can exist in two project
folders, as an identical copy or as two different lengths. Each file is tracked on its
own, so a session copied after the start date is read twice.
"""
from __future__ import annotations

import collections
import fnmatch
import glob
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

import transcripts
from config import SessionsConfig

STATE_SCHEMA_VERSION = 2
OLD_STATE_SCHEMA_VERSION = 1
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
class SessionFailure:
    """A session that could not be read. It fails alone, and the others go on."""

    state_key: str
    error: str


@dataclass(frozen=True)
class WorkItem:
    """One session and the window ``after < timestamp <= through`` to process."""

    files: SessionFiles
    after: datetime
    through: datetime
    mode: str
    project_cwd: str
    resumed: bool
    lines: Optional[transcripts.LineWindow] = None


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


def _key_of(path: str, files: SessionFiles) -> str:
    return transcripts.file_key(path, files.main_path)


def count_lines(files: SessionFiles) -> dict[str, int]:
    """The last whole line of each of a session's files."""
    found = {}
    for path in _all_paths(files):
        last = 0
        for last, _ in transcripts.iter_records(path):
            pass
        found[_key_of(path, files)] = last
    return found


def lines_stamped_through(files: SessionFiles, moment: datetime) -> dict[str, int]:
    """For each file, the last line of the run from the start with stamps at or before ``moment``."""
    found = {}
    for path in _all_paths(files):
        reached = 0
        for line_number, record in transcripts.iter_records(path):
            if record["type"] in transcripts.CONVERSATION_RECORD_TYPES:
                if transcripts.parse_timestamp(record["timestamp"]) > moment:
                    break
            reached = line_number
        found[_key_of(path, files)] = reached
    return found


def _has_new_record(files: SessionFiles, lines_read: Mapping[str, int], lines_now: Mapping[str, int], floor: datetime) -> bool:
    """True if a line not read yet holds a conversation record not seen before, past the start date."""
    window = transcripts.LineWindow(lines_read, lines_now, floor)
    seen: set[str] = set()
    for path in _all_paths(files):
        seen.update(transcripts.uuids_read_before(path, lines_read.get(_key_of(path, files), 0)))
    for path in _all_paths(files):
        if transcripts.any_new_record(path, _key_of(path, files), window, seen):
            return True
    return False


def migrate_entry(files: SessionFiles, entry: dict[str, Any], floor: datetime) -> None:
    """Bring one session's state from timestamps to lines. See the module docstring."""
    processed = entry.get("processed_through")
    if processed is not None and "lines_read" not in entry:
        entry["lines_read"] = lines_stamped_through(files, datetime.fromisoformat(processed))
    pending = entry.get("pending")
    if pending is not None and "lines_through" not in pending:
        pending["lines_after"] = lines_stamped_through(files, datetime.fromisoformat(pending["after"]))
        pending["lines_through"] = lines_stamped_through(files, datetime.fromisoformat(pending["through"]))
        pending["floor"] = floor.isoformat()


def _is_under(path: str, prefix: str) -> bool:
    normal_path = os.path.normcase(os.path.normpath(path))
    normal_prefix = os.path.normcase(os.path.normpath(prefix))
    return normal_path == normal_prefix or normal_path.startswith(normal_prefix + os.sep)


def _is_excluded(cwd: str, config: SessionsConfig) -> bool:
    if any(_is_under(cwd, prefix) for prefix in config.excluded_cwd_prefixes):
        return True
    normal_cwd = os.path.normcase(os.path.normpath(cwd))
    return any(fnmatch.fnmatchcase(normal_cwd, os.path.normcase(pattern)) for pattern in config.excluded_cwd_globs)


def mode_of_cwds(cwds: Mapping[str, int], config: SessionsConfig) -> Optional[str]:
    """Return how to treat a session from its working directories; None means excluded.

    A session is excluded or count-only only when every record's directory is, so one
    that moved into a normal project is still read.
    """
    if all(_is_excluded(cwd, config) for cwd in cwds):
        return None
    if all(any(_is_under(cwd, prefix) for prefix in config.count_only_cwd_prefixes) for cwd in cwds):
        return MODE_COUNT_ONLY
    return MODE_READ


def project_of_cwds(cwds: Mapping[str, int]) -> str:
    """The directory most of a session's records ran in, ties broken by name."""
    return min(cwds, key=lambda cwd: (-cwds[cwd], cwd))


def _pinned_item(files: SessionFiles, pending: Mapping[str, Any]) -> WorkItem:
    return WorkItem(
        files=files,
        after=datetime.fromisoformat(pending["after"]),
        through=datetime.fromisoformat(pending["through"]),
        mode=pending["mode"],
        project_cwd=pending["project_cwd"],
        resumed=True,
        lines=transcripts.LineWindow(pending["lines_after"], pending["lines_through"], datetime.fromisoformat(pending["floor"])),
    )


def _new_item(files: SessionFiles, entry: Mapping[str, Any], config: SessionsConfig) -> Optional[WorkItem]:
    processed = entry.get("processed_through")
    after = datetime.fromisoformat(processed) if processed is not None else config.start_date
    # A late record has a stamp at or before ``after``, but the file changed after the last read,
    # which was at or after ``after``. Hence strictly before.
    if newest_change(files) < after:
        return None
    lines_read = entry.get("lines_read", {})
    lines_now = count_lines(files)
    for key, count in lines_read.items():
        if lines_now.get(key, 0) < count:
            raise transcripts.TranscriptFormatError(f"{files.state_key}: {key} shrank: {count} lines were read and it now has {lines_now.get(key, 0)}")
    if lines_now == lines_read or not _has_new_record(files, lines_read, lines_now, config.start_date):
        return None
    span = read_span(files)
    if span is None:
        return None
    mode = mode_of_cwds(span.cwd_counts, config)
    if mode is None:
        return None
    return WorkItem(
        files=files,
        after=after,
        through=max(after, span.last),
        mode=mode,
        project_cwd=project_of_cwds(span.cwd_counts),
        resumed=False,
        lines=transcripts.LineWindow(lines_read, lines_now, config.start_date),
    )


def select_work(
    files_list: list[SessionFiles], state: dict[str, Any], config: SessionsConfig
) -> tuple[list[WorkItem], list[SessionFailure]]:
    """Choose sessions with unread records after the forward-only start date, and those that could
    not be read. A session with a pinned window comes with that window. Old state is carried over
    here, in ``state``, and the caller saves it."""
    known = state["sessions"]
    work: list[WorkItem] = []
    failures: list[SessionFailure] = []
    for files in files_list:
        try:
            entry = known.get(files.state_key, {})
            migrate_entry(files, entry, config.start_date)
            pending = entry.get("pending")
            item = _pinned_item(files, pending) if pending is not None else _new_item(files, entry, config)
        except transcripts.TranscriptFormatError as error:
            failures.append(SessionFailure(files.state_key, f"{type(error).__name__}: {error}"))
            continue
        if item is not None:
            work.append(item)
    return work, failures


def new_state() -> dict[str, Any]:
    return {"schema_version": STATE_SCHEMA_VERSION, "sessions": {}}


def load_state(path: str) -> dict[str, Any]:
    """Read the state file. A missing file raises; the first run creates it explicitly."""
    with open(path, encoding="utf-8") as handle:
        state = json.load(handle)
    if state.get("schema_version") not in (OLD_STATE_SCHEMA_VERSION, STATE_SCHEMA_VERSION):
        raise ValueError(f"state file {path}: schema_version {state.get('schema_version')!r}")
    # Each entry is carried over when ``select_work`` next reaches it, since that needs its files.
    return {**state, "schema_version": STATE_SCHEMA_VERSION}


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
    if item.lines is None or item.lines.floor is None:
        raise ValueError(f"session {item.files.state_key}: a window to pin must be limited by line, with a floor")
    state["sessions"].setdefault(item.files.state_key, {})["pending"] = {
        "after": item.after.isoformat(),
        "through": item.through.isoformat(),
        "lines_after": dict(item.lines.after),
        "lines_through": dict(item.lines.through),
        "floor": item.lines.floor.isoformat(),
        "mode": item.mode,
        "project_cwd": item.project_cwd,
    }


def mark_processed(state: dict[str, Any], item: WorkItem) -> None:
    """Record that every message up to ``item.through`` has validated results on disk."""
    entry = state["sessions"].setdefault(item.files.state_key, {})
    if entry.get("pending") is None:
        raise ValueError(f"session {item.files.state_key}: marking a window that was never pinned")
    entry["processed_through"] = item.through.isoformat()
    entry["lines_read"] = dict(entry["pending"]["lines_through"])
    entry["pending"] = None
