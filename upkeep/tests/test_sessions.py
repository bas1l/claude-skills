"""Session selection: new, grown, excluded and interrupted sessions."""
from __future__ import annotations

import os

import pytest
from conftest import CWD, SESSION_ID, assistant_text, stamp, write_jsonl

import sessions
import transcripts as t
from config import SessionsConfig

START = t.parse_timestamp("2030-01-01T10:10:00Z")


def session_config(excluded=(), count_only=()):
    return SessionsConfig(start_date=START, excluded_cwd_prefixes=tuple(excluded), count_only_cwd_prefixes=tuple(count_only))


def make_session(root, minutes, folder="F--project", session_id=SESSION_ID, cwd=CWD):
    records = [assistant_text("x", minute=minute) for minute in minutes]
    for record in records:
        record["cwd"] = cwd
        record["sessionId"] = session_id
    path = write_jsonl(root / folder / f"{session_id}.jsonl", records)
    # Fixtures are dated 2030, so the file time must not look older than the records.
    newest_record = t.parse_timestamp(stamp(max(minutes))).timestamp()
    os.utime(path, (newest_record, newest_record))
    return sessions.discover_sessions(str(root))


def test_new_session_is_selected_from_the_start_date(tmp_path):
    files = make_session(tmp_path, [5, 15, 20])
    item, = sessions.select_work(files, sessions.new_state(), session_config())
    assert item.after == START
    assert item.through == t.parse_timestamp(stamp(20))
    assert item.mode == sessions.MODE_READ
    assert item.project_cwd == CWD


def test_session_older_than_the_start_date_is_not_selected(tmp_path):
    files = make_session(tmp_path, [1, 2])
    assert sessions.select_work(files, sessions.new_state(), session_config()) == []


def test_processed_session_with_nothing_new_is_skipped(tmp_path):
    files = make_session(tmp_path, [15])
    state = sessions.new_state()
    item, = sessions.select_work(files, state, session_config())
    sessions.pin_window(state, item)
    sessions.mark_processed(state, item)
    assert sessions.select_work(files, state, session_config()) == []


def test_grown_session_is_selected_from_the_recorded_timestamp(tmp_path):
    files = make_session(tmp_path, [15])
    state = sessions.new_state()
    item, = sessions.select_work(files, state, session_config())
    sessions.pin_window(state, item)
    sessions.mark_processed(state, item)

    files = make_session(tmp_path, [15, 25])
    grown, = sessions.select_work(files, state, session_config())
    assert grown.after == t.parse_timestamp(stamp(15))
    assert grown.through == t.parse_timestamp(stamp(25))


def test_interrupted_session_resumes_the_pinned_window(tmp_path):
    files = make_session(tmp_path, [15])
    state = sessions.new_state()
    item, = sessions.select_work(files, state, session_config())
    sessions.pin_window(state, item)

    files = make_session(tmp_path, [15, 40])
    resumed, = sessions.select_work(files, state, session_config())
    assert resumed.resumed
    assert (resumed.after, resumed.through) == (item.after, item.through)


def test_mark_processed_needs_a_pinned_window(tmp_path):
    files = make_session(tmp_path, [15])
    item, = sessions.select_work(files, sessions.new_state(), session_config())
    with pytest.raises(ValueError, match="never pinned"):
        sessions.mark_processed(sessions.new_state(), item)


def test_excluded_folder_is_skipped_by_its_records_cwd(tmp_path):
    excluded = os.path.normpath("/home/x/.claude/upkeep")
    files = make_session(tmp_path, [15], cwd=os.path.join(excluded, "run"))
    assert sessions.select_work(files, sessions.new_state(), session_config(excluded=[excluded])) == []


def test_excluded_prefix_stops_at_a_path_boundary(tmp_path):
    excluded = os.path.normpath("/home/x/.claude/upkeep")
    files = make_session(tmp_path, [15], cwd=excluded + "-other")
    item, = sessions.select_work(files, sessions.new_state(), session_config(excluded=[excluded]))
    assert item.mode == sessions.MODE_READ


def test_count_only_folder_is_counted_and_not_read(tmp_path):
    brief = os.path.normpath("/home/x/.claude/brief")
    files = make_session(tmp_path, [15], cwd=brief)
    item, = sessions.select_work(files, sessions.new_state(), session_config(count_only=[brief]))
    assert item.mode == sessions.MODE_COUNT_ONLY


def test_project_comes_from_the_record_and_not_the_folder_name(tmp_path):
    real = os.path.normpath("/work/some_name/app")
    files = make_session(tmp_path, [15], folder="F--work-some-name-app", cwd=real)
    item, = sessions.select_work(files, sessions.new_state(), session_config())
    assert item.project_cwd == real


def test_same_id_in_two_folders_is_tracked_apart(tmp_path):
    make_session(tmp_path, [15], folder="F--one")
    files = make_session(tmp_path, [15], folder="F--two")
    assert len(files) == 2
    assert len(sessions.select_work(files, sessions.new_state(), session_config())) == 2
    assert files[0].state_key != files[1].state_key


def test_subagent_files_are_found_including_nested_and_journal_is_not(tmp_path):
    files = make_session(tmp_path, [15])
    base = tmp_path / "F--project" / SESSION_ID / "subagents"
    write_jsonl(base / "agent-a.jsonl", [assistant_text("x", minute=16)])
    write_jsonl(base / "workflows" / "wf_1" / "agent-b.jsonl", [assistant_text("x", minute=17)])
    write_jsonl(base / "workflows" / "wf_1" / "journal.jsonl", [{"type": "started"}])
    found, = sessions.discover_sessions(str(tmp_path))
    assert sorted(os.path.basename(p) for p in found.subagent_paths) == ["agent-a.jsonl", "agent-b.jsonl"]


def test_record_with_a_different_session_id_raises(tmp_path):
    files = make_session(tmp_path, [15])
    write_jsonl(tmp_path / "F--project" / f"{SESSION_ID}.jsonl", [{**assistant_text("x", minute=15), "sessionId": "other"}])
    with pytest.raises(t.TranscriptFormatError, match="sessionId"):
        sessions.read_span(files[0])


def test_missing_projects_folder_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        sessions.discover_sessions(str(tmp_path / "absent"))


def test_state_round_trip_and_wrong_version_raises(tmp_path):
    path = str(tmp_path / "state" / "sessions.json")
    state = sessions.new_state()
    sessions.save_state(path, state)
    assert sessions.load_state(path) == state
    sessions.save_state(path, {"schema_version": 999, "sessions": {}})
    with pytest.raises(ValueError, match="schema_version"):
        sessions.load_state(path)


def test_missing_state_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        sessions.load_state(str(tmp_path / "absent.json"))
