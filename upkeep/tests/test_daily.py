"""The daily pass on synthetic project trees, with a fake model call."""
from __future__ import annotations

import dataclasses
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from conftest import CWD, SESSION_ID, assistant_text, human, user_with_origin, write_jsonl

import daily
import memory_store
import model_call
import sessions
from config import SessionsConfig

OTHER_ID = "00000000-0000-4000-8000-000000000002"


def note(**overrides):
    values = {
        "type": "preference", "what": "Prefers short reports.", "evidence": "USER-TYPED",
        "memory_candidate": True, "endorsement": "said", "endorsement_quote": "keep it short",
        "origin_of_point": "user", "route": "memory", "confidence": "high",
    }
    values.update(overrides)
    return values


def reply_of(*notes):
    return json.dumps({"notes": list(notes)})


class FakeCall:
    """Replies in order; the last one repeats. Exceptions in the list are raised."""

    def __init__(self, *replies, cost=0.5):
        self.replies = list(replies)
        self.cost = cost
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, BaseException):
            raise reply
        return model_call.ModelResult(
            text=reply,
            usage={"input_tokens": 10, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 5},
            model_usage={"m": {}},
            cost_usd=self.cost,
            duration_ms=100,
            num_turns=1,
            command_line=("claude",),
        )


@pytest.fixture
def tree(config, tmp_path):
    projects = tmp_path / "projects"
    projects.mkdir()
    data = tmp_path / "upkeep"
    data.mkdir()
    run_dir = data / "run"
    run_dir.mkdir()
    built = dataclasses.replace(
        config,
        paths=dataclasses.replace(config.paths, projects_dir=str(projects), data_dir=str(data), run_dir=str(run_dir)),
        sessions=SessionsConfig(
            start_date=datetime(2020, 1, 1, 0, 0, tzinfo=timezone.utc),
            excluded_cwd_prefixes=(str(tmp_path / "excluded"),),
            excluded_cwd_globs=(str(tmp_path / "temp-*"),),
            count_only_cwd_prefixes=(str(tmp_path / "brief"),),
        ),
        memory=dataclasses.replace(config.memory, author_name="Test Author", author_email="test@example.invalid"),
    )
    memory_store.init_upkeep_repo(str(data), built.memory)
    daily.init_state(built)
    return built


def session_path(config, project, session_id):
    return Path(config.paths.projects_dir) / project / f"{session_id}.jsonl"


def touch_after_fixture_times(path):
    """Fixture records are stamped 2030, so the file must look changed after them."""
    stamp = datetime(2031, 1, 1, tzinfo=timezone.utc).timestamp()
    os.utime(path, (stamp, stamp))


def add_session(config, project, session_id, records):
    path = write_jsonl(session_path(config, project, session_id), [{**record, "sessionId": session_id} for record in records])
    touch_after_fixture_times(path)
    return path


def chat(minute=1, text="keep it short"):
    return [human(text, minute), assistant_text("Understood.", minute + 1)]


def notes_on_disk(config):
    found = []
    for directory, _, names in os.walk(os.path.join(config.paths.data_dir, "notes")):
        for name in sorted(names):
            if name.startswith("chunk-") and name.endswith(".json"):
                with open(os.path.join(directory, name), encoding="utf-8") as handle:
                    found.extend(json.load(handle)["notes"])
    return found


def tracked(config):
    return subprocess.run(
        ["git", "-C", config.paths.data_dir, "ls-files"], capture_output=True, encoding="utf-8", check=True
    ).stdout.split()


def state_entries(config):
    return sessions.load_state(daily.state_path(config))["sessions"]


def test_run_writes_notes_counts_state_and_commits(tree):
    add_session(tree, "proj", SESSION_ID, chat())
    result = daily.run_daily(tree, "r1", call=FakeCall(reply_of(note())))

    assert result["status"] == daily.STATUS_OK
    assert (result["sessions_read"], result["notes"], result["model_calls"]) == (1, 1, 1)
    assert result["cost_usd"] == 0.5
    assert result["tokens"]["input_tokens"] == 10
    assert notes_on_disk(tree)[0]["quote_check"] == "verified"
    state = state_entries(tree)[f"proj/{SESSION_ID}"]
    assert state["pending"] is None
    assert state["processed_through"] == "2030-01-01T10:02:00+00:00"
    assert result["data_commit"] == memory_store.RESULT_COMMITTED
    files = tracked(tree)
    assert any(name.startswith("notes/") and name.endswith("chunk-001.json") for name in files)
    assert any(name.startswith("counts/") for name in files)
    assert "state/state.json" in files
    assert os.path.exists(os.path.join(tree.paths.data_dir, "logs", "usage.jsonl"))


def test_second_run_processes_only_what_is_new(tree):
    path = add_session(tree, "proj", SESSION_ID, chat())
    daily.run_daily(tree, "r1", call=FakeCall(reply_of(note())))

    second = FakeCall(reply_of(note()))
    result = daily.run_daily(tree, "r2", call=second)
    assert result["sessions_selected"] == 0
    assert second.calls == []
    assert len(notes_on_disk(tree)) == 1

    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({**human("and one more", 30), "sessionId": SESSION_ID}) + "\n")
    touch_after_fixture_times(path)
    third = FakeCall(reply_of(note(endorsement_quote="and one more")))
    result = daily.run_daily(tree, "r3", call=third)
    assert result["sessions_read"] == 1
    session_part = third.calls[0]["stdin_text"]
    assert "one more" in session_part
    assert "keep it short" not in session_part
    assert len(notes_on_disk(tree)) == 2


def test_interrupted_run_resumes_without_duplicates_or_loss(tree):
    tree = dataclasses.replace(tree, chunking=dataclasses.replace(tree.chunking, chunk_chars=40))
    add_session(tree, "proj", SESSION_ID, [*chat(1, "first message"), *chat(10, "second message")])

    class Killed(BaseException):
        pass

    fake = FakeCall(reply_of(note(endorsement_quote="first message")), Killed(), reply_of())
    with pytest.raises(Killed):
        daily.run_daily(tree, "r1", call=fake)
    assert state_entries(tree)[f"proj/{SESSION_ID}"]["pending"] is not None
    assert len(fake.calls) == 2
    done_first = len(notes_on_disk(tree))
    assert done_first == 1

    resumed = FakeCall(reply_of())
    result = daily.run_daily(tree, "r2", call=resumed)
    assert result["status"] == daily.STATUS_OK
    assert len(resumed.calls) >= 1
    first_chunk_again = [call for call in resumed.calls if "first message</session_part>" in call["stdin_text"]]
    assert first_chunk_again == []
    assert len(notes_on_disk(tree)) == done_first
    assert state_entries(tree)[f"proj/{SESSION_ID}"]["pending"] is None


def test_unknown_origin_stops_run_and_leaves_session_unprocessed(tree):
    add_session(tree, "proj", SESSION_ID, [user_with_origin("from-the-future", "hello", 1)])
    result = daily.run_daily(tree, "r1", call=FakeCall(reply_of()))
    assert result["status"] == daily.STATUS_FAILED
    assert "TranscriptFormatError" in result["stop_reason"]
    assert daily.EXIT_CODES[result["status"]] != 0
    assert "processed_through" not in state_entries(tree)[f"proj/{SESSION_ID}"]


def test_invalid_reply_fails_that_session_and_others_continue(tree):
    add_session(tree, "proj", SESSION_ID, chat(1))
    add_session(tree, "proj", OTHER_ID, chat(20))
    result = daily.run_daily(tree, "r1", call=FakeCall('<invoke name="Bash">', reply_of(note())))

    assert result["status"] == daily.STATUS_FAILED
    assert [item["session"] for item in result["failed_sessions"]] == [f"proj/{SESSION_ID}"]
    assert result["sessions_read"] == 1
    state = state_entries(tree)
    assert "processed_through" not in state[f"proj/{SESSION_ID}"]
    assert state[f"proj/{OTHER_ID}"]["pending"] is None

    retry = daily.run_daily(tree, "r2", call=FakeCall(reply_of()))
    assert retry["status"] == daily.STATUS_OK
    assert retry["sessions_read"] == 1


def test_model_call_error_stops_the_run(tree):
    add_session(tree, "proj", SESSION_ID, chat(1))
    add_session(tree, "proj", OTHER_ID, chat(20))
    fake = FakeCall(model_call.ModelCallError("usage limit reached"))
    result = daily.run_daily(tree, "r1", call=fake)
    assert result["status"] == daily.STATUS_FAILED
    assert "usage limit" in result["stop_reason"]
    assert len(fake.calls) == 1


def test_budget_stops_the_run_and_reports_backlog(tree):
    add_session(tree, "proj", SESSION_ID, chat(1))
    add_session(tree, "proj", OTHER_ID, chat(20))
    tree = dataclasses.replace(tree, model=dataclasses.replace(tree.model, run_budget_usd=0.5))
    fake = FakeCall(reply_of(note()))
    result = daily.run_daily(tree, "r1", call=fake)
    assert result["status"] == daily.STATUS_BUDGET_STOPPED
    assert result["backlog_sessions"] == [f"proj/{OTHER_ID}"]
    assert len(fake.calls) == 1
    assert daily.EXIT_CODES[result["status"]] == 3
    assert "processed_through" not in state_entries(tree).get(f"proj/{OTHER_ID}", {})


def test_budget_error_from_a_call_leaves_the_session_pinned(tree):
    add_session(tree, "proj", SESSION_ID, chat(1))
    result = daily.run_daily(tree, "r1", call=FakeCall(model_call.BudgetExhaustedError("limit")))
    assert result["status"] == daily.STATUS_BUDGET_STOPPED
    assert result["backlog_sessions"] == [f"proj/{SESSION_ID}"]
    assert state_entries(tree)[f"proj/{SESSION_ID}"]["pending"] is not None


def test_excluded_sessions_are_not_read_and_count_only_are_counted(tree, tmp_path):
    def at(cwd, session_id):
        return [{**record, "cwd": str(cwd), "sessionId": session_id} for record in chat()]

    excluded = "00000000-0000-4000-8000-00000000000a"
    glob_excluded = "00000000-0000-4000-8000-00000000000b"
    brief = "00000000-0000-4000-8000-00000000000c"
    touch_after_fixture_times(write_jsonl(session_path(tree, "ex", excluded), at(tmp_path / "excluded" / "sub", excluded)))
    touch_after_fixture_times(write_jsonl(session_path(tree, "tmp", glob_excluded), at(tmp_path / "temp-phase0-x", glob_excluded)))
    touch_after_fixture_times(write_jsonl(session_path(tree, "brief", brief), at(tmp_path / "brief", brief)))

    fake = FakeCall(reply_of())
    result = daily.run_daily(tree, "r1", call=fake)
    assert fake.calls == []
    assert (result["sessions_selected"], result["sessions_count_only"], result["sessions_read"]) == (1, 1, 0)
    written = [name for _, _, names in os.walk(os.path.join(tree.paths.data_dir, "counts")) for name in names]
    assert len(written) == 1 and written[0].startswith(brief)


def test_secret_in_a_note_is_redacted_and_counted(tree):
    add_session(tree, "proj", SESSION_ID, chat())
    secret = "ghp_" + "a" * 30
    result = daily.run_daily(tree, "r1", call=FakeCall(reply_of(note(what=f"The token {secret} was printed."))))
    assert result["secrets_redacted"] == 1
    assert secret not in json.dumps(notes_on_disk(tree))
    assert "[REDACTED-github]" in notes_on_disk(tree)[0]["what"]


def test_secret_in_a_rejected_reply_is_redacted(tree):
    add_session(tree, "proj", SESSION_ID, chat())
    secret = "ghp_" + "b" * 30
    daily.run_daily(tree, "r1", call=FakeCall(f"not json {secret}"))
    rejected = [
        os.path.join(directory, name)
        for directory, _, names in os.walk(os.path.join(tree.paths.data_dir, "notes"))
        for name in names if name.endswith(".rejected")
    ]
    assert len(rejected) == 1
    with open(rejected[0], encoding="utf-8") as handle:
        assert secret not in handle.read()


def test_snapshot_commits_memory_edits_and_creates_new_repositories(tree):
    memory = os.path.join(tree.paths.projects_dir, "proj", "memory")
    os.makedirs(memory)
    with open(os.path.join(memory, "a.md"), "w", encoding="utf-8") as handle:
        handle.write("first")
    result = daily.run_daily(tree, "r1", call=FakeCall(reply_of()))
    assert result["memory_snapshot"]["created"] == ["proj"]

    with open(os.path.join(memory, "a.md"), "a", encoding="utf-8") as handle:
        handle.write(" second")
    result = daily.run_daily(tree, "r2", call=FakeCall(reply_of()))
    assert result["memory_snapshot"]["committed"] == ["proj"]


def test_memory_folder_failure_is_reported_and_the_pass_still_reads(tree):
    memory = os.path.join(tree.paths.projects_dir, "bad", "memory")
    os.makedirs(memory)
    subprocess.run(["git", "-C", memory, "init", "--quiet", "--template="], check=True)
    add_session(tree, "proj", SESSION_ID, chat())
    result = daily.run_daily(tree, "r1", call=FakeCall(reply_of()))
    assert result["status"] == daily.STATUS_FAILED
    assert result["memory_snapshot"]["errors"][0]["project_folder"] == "bad"
    assert result["sessions_read"] == 1


def test_missing_state_file_raises(tree):
    os.remove(daily.state_path(tree))
    with pytest.raises(FileNotFoundError):
        daily.run_daily(tree, "r1", call=FakeCall(reply_of()))


def test_init_state_refuses_to_overwrite(tree):
    with pytest.raises(FileExistsError):
        daily.init_state(tree)


def test_pinned_window_with_a_lost_transcript_is_a_failure(tree):
    state = sessions.load_state(daily.state_path(tree))
    state["sessions"]["gone/abc"] = {"pending": {"after": "x", "through": "y", "mode": "read", "project_cwd": CWD}}
    sessions.save_state(daily.state_path(tree), state)
    result = daily.run_daily(tree, "r1", call=FakeCall(reply_of()))
    assert result["status"] == daily.STATUS_FAILED
    assert result["failed_sessions"][0]["session"] == "gone/abc"
