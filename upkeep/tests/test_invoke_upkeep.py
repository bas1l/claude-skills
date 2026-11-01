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


def test_live_lock_exits_non_zero_and_is_left_alone(setup):
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


def test_unbuilt_pass_fails_loudly(setup):
    config_path, _, _ = setup
    completed = invoke(config_path, "monthly")
    assert completed.returncode == 1
    assert "not built yet" in completed.stderr


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
