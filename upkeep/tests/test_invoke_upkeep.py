"""Invoke-Upkeep.ps1 end to end, on temp folders, with a fake claude that returns no notes."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import SESSION_ID, assistant_text, human, user_with_origin, write_jsonl

import daily
import memory_store
from config import load_config
from conftest import synthetic_inventory

SCRIPT = Path(__file__).resolve().parent.parent / "Invoke-Upkeep.ps1"
REAL_CONFIG = SCRIPT.parent / "config.json"
FAKE_RESULT = {
    "type": "result", "subtype": "success", "is_error": False, "result": '{"notes": []}',
    "usage": {"input_tokens": 1, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 1},
    "modelUsage": {"m": {}}, "total_cost_usd": 0.01, "duration_ms": 1, "num_turns": 1,
}


def pwsh():
    found = shutil.which("pwsh")
    if found is None:
        raise FileNotFoundError("pwsh is needed for these tests")
    return found


@pytest.fixture
def setup(tmp_path):
    projects = tmp_path / "projects"
    data = tmp_path / "upkeep"
    projects.mkdir()
    data.mkdir()
    (tmp_path / "fake_claude.py").write_text(f"print({json.dumps(json.dumps(FAKE_RESULT))})\n", encoding="utf-8")
    fake = tmp_path / "fake_claude.cmd"
    fake.write_text(f'@"{sys.executable}" "{tmp_path / "fake_claude.py"}"\r\n', encoding="utf-8")
    raw = json.loads(REAL_CONFIG.read_text(encoding="utf-8"))
    raw["paths"] = {
        "projects_dir": str(projects),
        "data_dir": str(data),
        "run_dir": str(data / "run"),
        "claude_exe": str(fake),
        "local_settings": str(data / "local.json"),
    }
    raw["sessions"]["start_date"] = "2020-01-01T00:00:00+00:00"
    raw["memory"] = {"author_name": "Test Author", "author_email": "test@example.invalid"}
    raw["inventory"] = synthetic_inventory(tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    config = load_config(str(config_path))
    memory_store.init_upkeep_repo(str(data), config.memory)
    daily.init_state(config)
    (data / "local.json").write_text(json.dumps({"python_exe": sys.executable}), encoding="utf-8")
    return config_path, data, projects


def invoke(config_path, pass_name="daily"):
    return subprocess.run(
        [pwsh(), "-NoProfile", "-NonInteractive", "-File", str(SCRIPT), "-Pass", pass_name, "-ConfigPath", str(config_path)],
        capture_output=True,
        encoding="utf-8",
        creationflags=subprocess.CREATE_NO_WINDOW,
        check=False,
    )


def marker_of(data):
    path = data / "failure-marker.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def add_session(projects, records):
    write_jsonl(projects / "proj" / f"{SESSION_ID}.jsonl", records)


def write_lock(data, process_id, process_start, run_id="other"):
    lock = {"pass": "daily", "run_id": run_id, "pid": process_id, "pid_start": process_start, "child_pid": None, "child_start": None}
    (data / "upkeep.lock").write_text(json.dumps(lock), encoding="utf-8")


def test_clean_run_exits_zero_removes_lock_and_leaves_no_marker(setup):
    config_path, data, projects = setup
    add_session(projects, [human("hello", 1), assistant_text("Hi.", 2)])
    completed = invoke(config_path)
    assert completed.returncode == 0, completed.stderr
    assert not (data / "upkeep.lock").exists()
    assert marker_of(data) is None
    state = json.loads((data / "state" / "state.json").read_text(encoding="utf-8"))
    assert state["sessions"][f"proj/{SESSION_ID}"]["pending"] is None
    assert json.loads((data / "logs" / "runs.jsonl").read_text(encoding="utf-8").splitlines()[0])["status"] == "ok"


def test_live_lock_exits_non_zero_is_left_alone_and_reported_until_a_clean_run(setup):
    config_path, data, _ = setup
    holder = subprocess.Popen(
        [pwsh(), "-NoProfile", "-NonInteractive", "-Command",
         "(Get-Process -Id $PID).StartTime.ToFileTimeUtc(); [Console]::Out.Flush(); Start-Sleep 60"],
        stdout=subprocess.PIPE, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        write_lock(data, holder.pid, int(holder.stdout.readline().strip()))
        completed = invoke(config_path)
    finally:
        holder.kill()
        holder.wait()
    assert completed.returncode == 2
    assert "Another upkeep run is live" in completed.stderr
    assert (data / "upkeep.lock").exists()
    entry = marker_of(data)["entries"][0]
    assert entry["kind"] == "failed" and entry["pass"] == "daily" and entry["exit_code"] == 2
    assert "did not start" in entry["summary"]

    (data / "upkeep.lock").unlink()
    assert invoke(config_path).returncode == 0
    assert marker_of(data) is None


def test_stale_lock_is_detected_reported_and_taken_over(setup):
    config_path, data, _ = setup
    finished = subprocess.run(
        [pwsh(), "-NoProfile", "-NonInteractive", "-Command", "$PID"],
        capture_output=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW, check=True,
    )
    write_lock(data, int(finished.stdout), 1, run_id="dead")

    completed = invoke(config_path)
    assert completed.returncode == 0, completed.stderr
    assert not (data / "upkeep.lock").exists()
    entries = marker_of(data)["entries"]
    assert [entry["kind"] for entry in entries] == ["stale_lock"]
    assert "dead" in entries[0]["summary"]


def test_reused_process_id_is_not_live(setup):
    config_path, data, _ = setup
    # This pytest process exists, but with a different start time than recorded.
    write_lock(data, os.getpid(), 1, run_id="reused")
    assert invoke(config_path).returncode == 0
    assert marker_of(data)["entries"][0]["kind"] == "stale_lock"


def test_unreadable_lock_stops_the_run(setup):
    config_path, data, _ = setup
    (data / "upkeep.lock").write_text("not json", encoding="utf-8")
    completed = invoke(config_path)
    assert completed.returncode != 0
    assert "cannot be read" in completed.stderr


def test_missing_interpreter_fails_loudly(setup):
    config_path, data, _ = setup
    (data / "local.json").write_text(json.dumps({"python_exe": str(data / "no-such-python.exe")}), encoding="utf-8")
    completed = invoke(config_path)
    assert completed.returncode == 1
    assert "no-such-python" in completed.stderr
    assert marker_of(data)["entries"][0]["kind"] == "failed"
    assert not (data / "upkeep.lock").exists()


def test_missing_local_settings_fails_loudly(setup):
    config_path, data, _ = setup
    (data / "local.json").unlink()
    completed = invoke(config_path)
    assert completed.returncode == 1
    assert "local settings file not found" in completed.stderr


def test_unbuilt_pass_fails_loudly(setup, tmp_path):
    config_path, _, _ = setup
    lone_script = tmp_path / "lone" / "Invoke-Upkeep.ps1"
    lone_script.parent.mkdir()
    shutil.copy(SCRIPT, lone_script)
    completed = subprocess.run(
        [pwsh(), "-NoProfile", "-NonInteractive", "-File", str(lone_script), "-Pass", "monthly", "-ConfigPath", str(config_path)],
        capture_output=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW, check=False,
    )
    assert completed.returncode == 1
    assert "not built yet" in completed.stderr


def test_monthly_pass_runs_writes_its_results_and_does_nothing_on_a_retry(setup, tmp_path):
    config_path, data, _ = setup
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    instructions = tmp_path / "CLAUDE.md"
    instructions.write_text("# Style\n\nWrite plainly.\n", encoding="utf-8")
    raw["monthly"]["global_claude_file"] = str(instructions)
    raw["monthly"]["global_rules_dir"] = str(tmp_path / "rules")
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    (data / "local.json").write_text(json.dumps({"python_exe": sys.executable, "apply_memory_changes": False, "private_terms": []}), encoding="utf-8")
    reply = {**FAKE_RESULT, "result": '{"contradictions": [], "stale": [], "level_moves": []}'}
    (tmp_path / "fake_claude.py").write_text(f"print({json.dumps(json.dumps(reply))})\n", encoding="utf-8")

    completed = invoke(config_path, "monthly")
    assert completed.returncode == 0, completed.stderr
    feeds = list((data / "reports" / "monthly").glob("*.json"))
    assert len(feeds) == 1 and marker_of(data) is None
    assert not (data / "upkeep.lock").exists()

    second = invoke(config_path, "monthly")
    assert second.returncode == 0, second.stderr
    assert len(list((data / "logs").glob("monthly-*.result.json"))) >= 1


def test_weekly_pass_runs_writes_its_report_and_does_nothing_on_a_retry(setup):
    config_path, data, projects = setup
    (data / "local.json").write_text(
        json.dumps({"python_exe": sys.executable, "apply_memory_changes": False, "private_terms": []}), encoding="utf-8"
    )
    add_session(projects, [human("hello", 1), assistant_text("Hi.", 2)])
    completed = invoke(config_path, "weekly")
    assert completed.returncode == 0, completed.stderr
    assert len(list((data / "reports").rglob("report.json"))) == 1
    assert marker_of(data) is None

    retry = invoke(config_path, "weekly")
    assert retry.returncode == 0, retry.stderr
    result_files = sorted((data / "logs").glob("weekly-*.result.json"))
    assert json.loads(result_files[-1].read_text(encoding="utf-8"))["skipped"] is True


def test_weekly_pass_without_the_switch_in_local_settings_fails_loudly(setup):
    config_path, data, _ = setup
    completed = invoke(config_path, "weekly")
    assert completed.returncode == 1
    assert "failed" in json.dumps(marker_of(data))


def test_unknown_origin_gives_non_zero_exit_and_a_marker_then_clears_on_a_clean_run(setup):
    config_path, data, projects = setup
    add_session(projects, [user_with_origin("from-the-future", "hello", 1)])
    completed = invoke(config_path)
    assert completed.returncode == 1
    entry = marker_of(data)["entries"][0]
    assert entry["kind"] == "failed"
    assert "TranscriptFormatError" in entry["summary"]

    add_session(projects, [human("hello", 1), assistant_text("Hi.", 2)])
    assert invoke(config_path).returncode == 0
    assert marker_of(data) is None


def test_crash_is_reported_with_the_error_tail(setup):
    config_path, data, _ = setup
    (data / "state" / "state.json").unlink()
    completed = invoke(config_path)
    assert completed.returncode == 1
    entry = marker_of(data)["entries"][0]
    assert entry["kind"] == "failed"
    assert "crashed" in entry["summary"] and "FileNotFoundError" in entry["summary"]


def research_stream(search_error=False, fetch=True):
    """What a research call prints, as the fake claude's output."""
    url = "https://example.invalid/docs"
    reply = {
        "search_worked": True, "official_features": "none", "existing_tools": [], "conventions": "formatters",
        "sources": [{"url": url, "title": "docs", "used_for": "features"}],
        "recommendation": "build", "recommendation_reason": "nothing fits",
    }
    calls = [("s1", "WebSearch", {"query": "markdown table formatter"}, url, search_error)]
    if fetch:
        calls.append(("f1", "WebFetch", {"url": url}, "page text", False))
    events = []
    for call_id, name, tool_input, text, is_error in calls:
        events.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": call_id, "name": name, "input": tool_input}]}})
        events.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": call_id, "content": text, "is_error": is_error}]}})
    events.append({**FAKE_RESULT, "result": json.dumps(reply)})
    return "\n".join(json.dumps(event) for event in events)


def set_fake_reply(tmp_path, text):
    (tmp_path / "fake_claude.py").write_text(f"print({json.dumps(text)})\n", encoding="utf-8")


def set_local_settings(data):
    (data / "local.json").write_text(json.dumps({"python_exe": sys.executable, "apply_memory_changes": False, "private_terms": []}), encoding="utf-8")


def test_research_check_passes_writes_counts_and_clears_its_own_failure(setup, tmp_path):
    config_path, data, _ = setup
    set_local_settings(data)
    set_fake_reply(tmp_path, research_stream(search_error=True))
    assert invoke(config_path, "research_check").returncode == 1
    assert "SearchUnavailableError" in marker_of(data)["entries"][0]["summary"]

    set_fake_reply(tmp_path, research_stream())
    completed = invoke(config_path, "research_check")
    assert completed.returncode == 0, completed.stderr
    assert marker_of(data) is None
    result = json.loads(sorted((data / "logs").glob("research_check-*.result.json"))[-1].read_text(encoding="utf-8"))
    assert result["searches"] == 1 and result["fetches"] == 1


def test_research_check_without_a_fetched_page_fails_loudly(setup, tmp_path):
    config_path, data, _ = setup
    set_local_settings(data)
    set_fake_reply(tmp_path, research_stream(fetch=False))
    assert invoke(config_path, "research_check").returncode == 1
    entry = marker_of(data)["entries"][0]
    assert entry["kind"] == "failed" and entry["pass"] == "research_check"
    assert "no page was fetched" in entry["summary"]


def test_research_check_with_a_failing_call_fails_loudly(setup, tmp_path):
    config_path, data, _ = setup
    set_local_settings(data)
    set_fake_reply(tmp_path, "not a result")
    assert invoke(config_path, "research_check").returncode == 1
    assert marker_of(data)["entries"][0]["kind"] == "failed"
