"""The plan's edge cases, on synthetic project trees with a fake model call."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from conftest import assistant_text, human, system, tool_result, tool_use, user_no_origin, write_jsonl
from test_weekly import (  # noqa: F401 (tree is a fixture)
    DRY,
    LIVE,
    NOW,
    PROJECT,
    SECOND_SESSION,
    SESSION_ID,
    FakeCall,
    add_memory,
    add_session,
    change,
    chat,
    commits_in,
    mark_daily_done,
    memory_path,
    memory_reply,
    note,
    read_notes,
    report_of,
    run,
    tree,
)

import daily
import memory_store
import model_call
import monthly
import sessions
import weekly
import weekly_gate
import weekly_notes

UPKEEP = Path(__file__).resolve().parent.parent
REPO = UPKEEP.parent


def state_of(config, session_id=SESSION_ID, project=PROJECT):
    return sessions.load_state(daily.state_path(config))["sessions"][f"{project}/{session_id}"]


class Notes(FakeCall):
    """A daily reader: the same notes for each call, and something to do during the call."""

    def __init__(self, *notes_list, during=None):
        super().__init__()
        self.notes_list = notes_list
        self.during = during

    def __call__(self, **kwargs):
        if self.during is not None:
            self.during()
        self.calls.append(kwargs)
        return model_call.ModelResult(
            text=json.dumps({"notes": list(self.notes_list)}),
            usage={"input_tokens": 1, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 1},
            model_usage={"m": {}}, cost_usd=0.1, duration_ms=1, num_turns=1, command_line=("claude",),
        )


def session_file(config, session_id=SESSION_ID, project=PROJECT):
    return Path(config.paths.projects_dir) / project / f"{session_id}.jsonl"


def append(path, record, session_id=SESSION_ID):
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({**record, "sessionId": session_id}) + "\n")
    stamp = NOW.timestamp() + 86400 * 365
    os.utime(path, (stamp, stamp))


# ---- a session still running at the cutoff ----


def test_a_session_still_running_is_read_to_where_it_was_and_the_rest_next_night(tree):
    add_session(tree, SESSION_ID, chat("first words of the session", 1))
    path = session_file(tree)

    first = Notes(during=lambda: append(path, human("words typed during the pass", 30)))
    result = daily.run_daily(tree, "night1", call=first)
    assert result["status"] == daily.STATUS_OK, result
    assert state_of(tree)["processed_through"] == "2030-01-01T10:02:00+00:00"
    assert state_of(tree)["pending"] is None
    assert "words typed during the pass" not in first.calls[0]["stdin_text"]

    second = Notes()
    result = daily.run_daily(tree, "night2", call=second)
    assert result["sessions_read"] == 1
    assert "words typed during the pass" in second.calls[0]["stdin_text"]
    assert "first words of the session" not in second.calls[0]["stdin_text"]
    assert state_of(tree)["processed_through"] == "2030-01-01T10:30:00+00:00"

    third = Notes()
    assert daily.run_daily(tree, "night3", call=third)["sessions_selected"] == 0
    assert third.calls == []


def test_a_record_half_written_at_the_cutoff_is_left_for_the_next_night(tree):
    add_session(tree, SESSION_ID, chat("complete words", 1))
    path = session_file(tree)
    whole_line = json.dumps({**human("words half written", 40), "sessionId": SESSION_ID})
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(whole_line[: len(whole_line) // 2])

    first = Notes()
    result = daily.run_daily(tree, "night1", call=first)
    assert result["status"] == daily.STATUS_OK, result
    assert state_of(tree)["processed_through"] == "2030-01-01T10:02:00+00:00"

    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(whole_line[len(whole_line) // 2:] + "\n")
    stamp = NOW.timestamp() + 86400 * 365
    os.utime(path, (stamp, stamp))
    second = Notes()
    assert daily.run_daily(tree, "night2", call=second)["sessions_read"] == 1
    assert "words half written" in second.calls[0]["stdin_text"]


def test_a_session_interrupted_and_still_growing_finishes_its_window_then_the_growth(tree):
    add_session(tree, SESSION_ID, chat("first words of the session", 1))
    path = session_file(tree)
    assert daily.run_daily(tree, "night1", call=Notes(during=lambda: (_ for _ in ()).throw(model_call.ModelCallError("limit"))))["status"] == daily.STATUS_FAILED
    assert state_of(tree)["pending"] is not None
    append(path, human("words after the stop", 50))

    second = Notes()
    result = daily.run_daily(tree, "night2", call=second)
    assert result["status"] == daily.STATUS_OK and result["windows_reset"] == []
    assert "words after the stop" not in second.calls[0]["stdin_text"]
    assert state_of(tree)["processed_through"] == "2030-01-01T10:02:00+00:00"

    third = Notes()
    assert daily.run_daily(tree, "night3", call=third)["sessions_read"] == 1
    assert "words after the stop" in third.calls[0]["stdin_text"]


# ---- a session with no messages from the user ----


def test_a_session_with_no_user_messages_is_read_and_no_quote_can_pass(tree):
    records = [user_no_origin("A scheduled prompt, print reports short.", 1, promptSource="sdk"), assistant_text("print reports short", 2)]
    add_session(tree, SESSION_ID, records)
    reader = Notes(note(endorsement_quote="print reports short"))
    result = daily.run_daily(tree, "night1", call=reader)
    assert result["status"] == daily.STATUS_OK, result
    assert result["notes"] == 1
    assert state_of(tree)["pending"] is None

    weekly_result = run(tree, LIVE, FakeCall(memory=memory_reply(change())))
    assert weekly_result["status"] == "ok", weekly_result
    assert not memory_path(tree, "short-reports").exists()
    assert [item["reason"] for item in report_of(tree)["rejected"]] == [weekly_gate.REJECT_QUOTE]


def test_a_scheduled_brief_with_no_user_messages_is_counted_not_read(tree, tmp_path):
    brief = tmp_path / "brief"
    records = [user_no_origin("Write the brief.", 1, promptSource="sdk"), assistant_text("Done.", 2), tool_use("a", "Bash", {"command": "ls"}, 3), tool_result("a", "boom", 4, is_error=True)]
    add_session(tree, SESSION_ID, [{**record, "cwd": str(brief)} for record in records], project="brief")
    reader = Notes()
    result = daily.run_daily(tree, "night1", call=reader)
    assert reader.calls == []
    assert (result["status"], result["sessions_count_only"]) == (daily.STATUS_OK, 1)
    assert state_of(tree, project="brief")["processed_through"]
    failures, _ = weekly_notes.aggregate_counts(tree, {})
    assert [failure.signature for failure in failures] == ["boom"]


def test_a_session_with_records_but_nothing_to_read_is_done_with_no_call(tree):
    add_session(tree, SESSION_ID, [system("api_error", 1)])
    reader = Notes()
    result = daily.run_daily(tree, "night1", call=reader)
    assert result["status"] == daily.STATUS_OK, result
    assert reader.calls == []
    assert state_of(tree)["pending"] is None

    mark_daily_done(tree)
    assert weekly.run_weekly(tree, DRY, "w1", now=NOW, call=FakeCall())["status"] == "ok"


def test_a_session_file_with_nothing_to_read_stays_unselected(tree):
    add_session(tree, SESSION_ID, [{"type": "ai-title", "title": "A title"}])
    reader = Notes()
    result = daily.run_daily(tree, "night1", call=reader)
    assert (result["status"], result["sessions_selected"]) == (daily.STATUS_OK, 0)


# ---- the weekly limit reached in the middle of the weekly pass ----


class LimitOnSecondProject(FakeCall):
    def __init__(self):
        super().__init__(memory=memory_reply(change()))
        self.memory_calls = 0

    def __call__(self, **kwargs):
        if kwargs["prompt"].startswith("You are preparing changes"):
            self.memory_calls += 1
            if self.memory_calls == 2:
                raise model_call.ModelCallError("call failed: Weekly usage limit reached")
        return super().__call__(**kwargs)


def test_a_limit_reached_in_the_weekly_pass_applies_nothing_and_the_retry_finishes_once(tree):
    read_notes(tree, note(), session_id=SESSION_ID, project="proj-a")
    read_notes(tree, note(), session_id=SECOND_SESSION, project="proj-b")

    stopped = LimitOnSecondProject()
    result = run(tree, LIVE, stopped)
    assert result["status"] == "failed"
    assert "Weekly usage limit" in result["stop_reason"]
    assert daily.EXIT_CODES[result["status"]] == 1
    for project in ("proj-a", "proj-b"):
        assert not memory_path(tree, "short-reports", project).exists()
    assert report_of(tree)["status"] == "failed"
    assert not os.path.exists(weekly.weekly_state_path(tree))

    retry = FakeCall(memory=memory_reply(change()))
    later = NOW + timedelta(hours=3, minutes=30)
    result = run(tree, LIVE, retry, now=later)
    assert result["status"] == "ok", result
    asked = [call for call in retry.calls if call["prompt"].startswith("You are preparing changes")]
    assert len(asked) == 1, "the first project's reply is reused from the stopped run"
    for project in ("proj-a", "proj-b"):
        assert memory_path(tree, "short-reports", project).exists()
        assert len([line for line in commits_in(tree, project) if line.startswith("Upkeep weekly")]) == 1

    assert run(tree, LIVE, FakeCall(), now=later + timedelta(minutes=5))["skipped"] is True


# ---- a memory folder edited by a live session while the pass commits ----


def git_wrapper_with_edit(monkeypatch, on_command, edit):
    real = memory_store._run_git

    def wrapped(folder, *arguments, **keywords):
        completed = real(folder, *arguments, **keywords)
        if on_command in arguments and not edit.done:
            edit.done = True
            edit()
        return completed

    monkeypatch.setattr(memory_store, "_run_git", wrapped)


def test_an_edit_arriving_between_stage_and_commit_of_a_snapshot_is_kept_for_the_next(tree, monkeypatch):
    path = add_memory(tree, "lively", "Before.")
    memory_store.snapshot_all(tree.paths.projects_dir, tree.memory, "base")
    path.write_text(path.read_text(encoding="utf-8") + "Staged edit.\n", encoding="utf-8")

    def edit():
        path.write_text(path.read_text(encoding="utf-8") + "Later edit.\n", encoding="utf-8")

    edit.done = False
    git_wrapper_with_edit(monkeypatch, "add", edit)
    result = memory_store.snapshot_all(tree.paths.projects_dir, tree.memory, "during")
    assert result["errors"] == [] and result[memory_store.RESULT_COMMITTED] == [PROJECT]
    folder = path.parent
    show = subprocess.run(["git", "-C", str(folder), "show", "HEAD:lively.md"], capture_output=True, encoding="utf-8", check=True).stdout
    assert "Staged edit." in show and "Later edit." not in show
    assert "Later edit." in path.read_text(encoding="utf-8")

    monkeypatch.undo()
    assert memory_store.snapshot_all(tree.paths.projects_dir, tree.memory, "next")[memory_store.RESULT_COMMITTED] == [PROJECT]
    show = subprocess.run(["git", "-C", str(folder), "show", "HEAD:lively.md"], capture_output=True, encoding="utf-8", check=True).stdout
    assert "Later edit." in show


def test_a_live_file_arriving_while_a_change_commits_stays_out_of_the_commit(tree, monkeypatch):
    read_notes(tree, note())
    add_memory(tree, "other", "Other text.")
    memory_store.snapshot_all(tree.paths.projects_dir, tree.memory, "base")
    folder = memory_path(tree, "x").parent
    live = folder / "live-note.md"

    def edit():
        live.write_text("written by a live session\n", encoding="utf-8")

    edit.done = False
    real_apply = memory_store.apply_memory_writes

    def apply_with_edit(*arguments, **keywords):
        # Only the apply step: the earlier snapshots use the same git command.
        git_wrapper_with_edit(monkeypatch, "--", edit)
        return real_apply(*arguments, **keywords)

    monkeypatch.setattr(memory_store, "apply_memory_writes", apply_with_edit)
    result = run(tree, LIVE, FakeCall(memory=memory_reply(change())))
    assert result["status"] == "ok", result
    assert edit.done
    committed = subprocess.run(["git", "-C", str(folder), "show", "--name-only", "--format=", "HEAD"], capture_output=True, encoding="utf-8", check=True).stdout.split()
    assert "short-reports.md" in committed and "live-note.md" not in committed
    assert live.read_text(encoding="utf-8") == "written by a live session\n"

    monkeypatch.undo()
    assert memory_store.snapshot_all(tree.paths.projects_dir, tree.memory, "next")[memory_store.RESULT_COMMITTED] == [PROJECT]


def test_one_file_edited_live_is_refused_and_the_others_in_the_folder_go_ahead(tree, monkeypatch):
    read_notes(tree, note())
    busy = add_memory(tree, "busy", "Busy text.")
    calm = add_memory(tree, "calm", "Calm text.")
    memory_store.snapshot_all(tree.paths.projects_dir, tree.memory, "base")
    changes = [change(action="add", memory="busy", title=""), change(action="add", memory="calm", title="")]
    real_research = weekly._research_candidates

    def live_edit_then(*arguments, **keywords):
        busy.write_text(busy.read_text(encoding="utf-8") + "\nA live edit.\n", encoding="utf-8")
        return real_research(*arguments, **keywords)

    monkeypatch.setattr(weekly, "_research_candidates", live_edit_then)
    result = run(tree, LIVE, FakeCall(memory=memory_reply(*changes)))
    assert result["status"] == "ok", result
    assert "A live edit." in busy.read_text(encoding="utf-8")
    assert "Reports are kept short." not in busy.read_text(encoding="utf-8")
    assert "Reports are kept short." in calm.read_text(encoding="utf-8")
    report = report_of(tree)
    assert [item["memory"] for item in report["memory_changes"]] == ["calm"]
    assert [(item["subject"], item["reason"]) for item in report["rejected"]] == [("busy", "changed_during_the_pass")]
    folder = busy.parent
    shown = subprocess.run(["git", "-C", str(folder), "log", "--format=%s"], capture_output=True, encoding="utf-8", check=True).stdout
    assert "Snapshot of edits by live sessions" in shown, "the live edit has its own commit and can be restored"


def test_a_git_lock_left_in_a_memory_folder_is_reported_and_clears(tree):
    add_session(tree, SESSION_ID, chat())
    path = add_memory(tree, "locked", "Text.")
    memory_store.snapshot_all(tree.paths.projects_dir, tree.memory, "base")
    path.write_text("Changed.\n", encoding="utf-8")
    lock = path.parent / ".git" / "index.lock"
    lock.write_text("", encoding="utf-8")

    result = daily.run_daily(tree, "night1", call=Notes())
    assert result["status"] == daily.STATUS_FAILED
    assert [item["project_folder"] for item in result["memory_snapshot"]["errors"]] == [PROJECT]
    assert result["sessions_read"] == 1

    lock.unlink()
    result = daily.run_daily(tree, "night2", call=Notes())
    assert result["status"] == daily.STATUS_OK, result
    assert result["memory_snapshot"]["committed"] == [PROJECT]


# ---- a PC that was off at the trigger: the logic that runs when it comes back ----


def test_three_missed_nights_are_all_caught_up_by_the_next_run(tree):
    days = {
        "00000000-0000-4000-8000-000000000011": "2030-01-01T10:00:00.000Z",
        "00000000-0000-4000-8000-000000000012": "2030-01-02T10:00:00.000Z",
        "00000000-0000-4000-8000-000000000013": "2030-01-03T10:00:00.000Z",
    }
    for session_id, stamp in days.items():
        add_session(tree, session_id, [{**human(f"said in {session_id}", 1), "timestamp": stamp}])

    reader = Notes()
    result = daily.run_daily(tree, "back", call=reader)
    assert (result["status"], result["sessions_read"]) == (daily.STATUS_OK, 3)
    for session_id, stamp in days.items():
        assert state_of(tree, session_id)["processed_through"].startswith(stamp[:19])
    assert daily.run_daily(tree, "next", call=Notes())["sessions_selected"] == 0


def test_seven_simulated_nights_leave_every_session_processed_or_reported_by_id(tree):
    """The logic of the first success criterion, in one process. The criterion itself needs a real week."""

    class FailsOneSession(Notes):
        def __call__(self, **kwargs):
            if "the session that fails" in kwargs["stdin_text"] and self.broken:
                return model_call.ModelResult('<invoke name="Bash">', {"input_tokens": 1, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 1}, {"m": {}}, 0.1, 1, 1, ("claude",))
            return super().__call__(**kwargs)

    failing = "00000000-0000-4000-8000-000000000003"
    seen = {}
    for night in range(1, 8):
        session_id = f"00000000-0000-4000-8000-0000000000{night:02d}"
        text = "the session that fails" if session_id == failing else f"said on night {night}"
        add_session(tree, session_id, [{**human(text, 1), "timestamp": f"2030-01-{night:02d}T10:00:00.000Z"}])
        reader = FailsOneSession()
        reader.broken = night < 7
        result = daily.run_daily(tree, f"night{night}", call=reader)
        seen[session_id] = result
        reported = {item["session"] for item in result["failed_sessions"]}
        states = sessions.load_state(daily.state_path(tree))["sessions"]
        for earlier in seen:
            key = f"{PROJECT}/{earlier}"
            assert key in reported or states[key]["pending"] is None, f"night {night}: {key} is neither processed nor reported"
        assert reported == ({f"{PROJECT}/{failing}"} if 3 <= night < 7 else set())
    assert state_of(tree, failing)["processed_through"].startswith("2030-01-03T10:00:00")


def test_a_weekly_pass_that_starts_days_late_still_counts_for_its_week(tree):
    read_notes(tree, note())
    thursday = NOW + timedelta(days=1)
    assert weekly.iso_week_of(thursday) == weekly.iso_week_of(NOW)
    assert run(tree, LIVE, FakeCall(memory=memory_reply(change())), now=thursday)["status"] == "ok"
    assert run(tree, LIVE, FakeCall(), now=thursday + timedelta(days=1))["skipped"] is True


def test_a_whole_week_missed_loses_no_notes(tree):
    read_notes(tree, note())
    next_week = NOW + timedelta(days=7)
    fake = FakeCall(memory=memory_reply(change()))
    assert run(tree, LIVE, fake, now=next_week)["status"] == "ok"
    assert memory_path(tree, "short-reports").exists()
    assert report_of(tree, next_week)["coverage"]["sessions"] == 1


def test_the_weekly_pass_finishes_the_daily_pass_the_pc_slept_through(tree):
    add_session(tree, SESSION_ID, chat())
    (Path(tree.paths.data_dir) / "logs").mkdir(exist_ok=True)
    result = weekly.run_weekly(tree, DRY, "20310108-020000", now=NOW, call=FakeCall())
    assert result["daily"]["status"] == daily.STATUS_OK and result["daily"]["sessions_read"] == 1
    assert state_of(tree)["pending"] is None


def test_a_monthly_pass_that_starts_days_late_stays_in_its_month():
    tuesday = NOW.replace(year=2030, month=3, day=12, hour=12)
    assert monthly.month_of(tuesday) == "2030-03"


# ---- a daylight saving night ----


def test_a_daylight_saving_night_leaves_windows_whole():
    """Runs in a child process, because a time zone can only be set at process start on Windows."""
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", str(UPKEEP / "tests" / "dst_scenarios.py"), "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=str(UPKEEP), env={**os.environ, "TZ": "EST5EDT"}, capture_output=True, encoding="utf-8",
        creationflags=subprocess.CREATE_NO_WINDOW, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert re.search(r"\b4 passed\b", completed.stdout), completed.stdout


# ---- what the public repository holds ----


def test_no_transcript_note_or_ledger_is_tracked_in_this_repository():
    tracked = subprocess.run(["git", "-C", str(REPO), "ls-files"], capture_output=True, encoding="utf-8", check=True).stdout.splitlines()
    assert "upkeep/config.json" in tracked
    assert not [name for name in tracked if name.endswith(".jsonl")]
    data_folders = re.compile(r"^upkeep/(state|notes|counts|ledgers|proposals|reports|logs|run|review|trials)/")
    assert not [name for name in tracked if data_folders.match(name)]
    assert not [name for name in tracked if name.endswith(("failure-marker.json", "local.json", "upkeep.lock", "state.json"))]


def test_session_ids_in_upkeep_code_are_synthetic():
    tracked = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", "upkeep", "upkeep-review", "hooks/upkeep_status"], capture_output=True, encoding="utf-8", check=True,
    ).stdout.splitlines()
    pattern = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
    found = {
        match for name in tracked for match in pattern.findall((REPO / name).read_text(encoding="utf-8", errors="replace"))
        if not match.startswith("00000000-")
    }
    assert not found


def test_the_data_folder_is_configured_outside_this_repository(config):
    data = Path(config.paths.data_dir).resolve()
    assert REPO.resolve() not in data.parents and data != REPO.resolve()
    assert Path(config.paths.data_dir).name == "upkeep" and ".claude" in Path(config.paths.data_dir).parts


# ---- the signature rule through to the ranking ----


def test_failures_behind_a_startup_line_rank_by_the_real_error(tree):
    noise = "/c/Users/someone/.bashrc: line 1: /opt/conda/etc/profile.d/conda.sh: No such file or directory"
    records = []
    for number in range(3):
        records += [tool_use(f"a{number}", "Bash", {"command": "one"}), tool_result(f"a{number}", f"Exit code 1\n{noise}\nthe common error", is_error=True)]
    records += [tool_use("b", "Bash", {"command": "two"}), tool_result("b", f"Exit code 2\n{noise}\nthe rare error", is_error=True)]
    add_session(tree, SESSION_ID, [human("hello", 1), *records])
    assert daily.run_daily(tree, "night1", call=Notes())["status"] == daily.STATUS_OK
    failures, _ = weekly_notes.aggregate_counts(tree, {})
    assert [(failure.signature, failure.commands_lost) for failure in failures] == [("Exit code #\nthe common error", 3), ("Exit code #\nthe rare error", 1)]
