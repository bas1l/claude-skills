"""The real entry script, real pass processes and real git, on a synthetic tree in temp.

Only the ``claude`` program is replaced, by a script that answers by prompt and can be told to fail
or to hang. Process kills here are real ones, of the whole process tree.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import assistant_text, human, synthetic_inventory, write_jsonl

import daily
import memory_store
from config import load_config

UPKEEP = Path(__file__).resolve().parent.parent
SCRIPT = UPKEEP / "Invoke-Upkeep.ps1"
SESSION_A = "00000000-0000-4000-8000-00000000000a"
SESSION_B = "00000000-0000-4000-8000-00000000000b"
PROJECT = "proj"
WAIT_FOR_HANG_SECONDS = 120

FAKE_CLAUDE = r'''
import json, pathlib, re, sys, time

folder = pathlib.Path(__file__).parent
text = sys.stdin.buffer.read().decode("utf-8")
control = json.loads((folder / "control.json").read_text(encoding="utf-8"))
with open(folder / "calls.jsonl", "a", encoding="utf-8") as handle:
    handle.write(json.dumps({"argv": sys.argv[1:], "text": text}) + "\n")
number = sum(1 for _ in open(folder / "calls.jsonl", encoding="utf-8"))
RESULT = {
    "type": "result", "subtype": "success", "is_error": False,
    "usage": {"input_tokens": 1, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 1},
    "modelUsage": {"m": {}}, "total_cost_usd": 0.01, "duration_ms": 1, "num_turns": 1,
}
if control.get("hang_on_call") == number:
    (folder / "hanging").write_text("yes", encoding="utf-8")
    time.sleep(600)
if control.get("limit_on_call") == number:
    if control["limit_form"] == "json":
        print(json.dumps({**RESULT, "is_error": True, "result": "Weekly usage limit reached"}))
    else:
        print("Weekly usage limit reached")
    sys.exit(1)
if text.startswith("You are preparing changes"):
    reply = {"changes": [{
        "action": "create", "memory": "short-reports", "note": "n1", "claim": "Reports are kept short.", "old_text": "",
        "endorsement": "said", "quote": "print reports short, message 1", "assistant_statement": "", "title": "Short reports",
    }], "fact_proposals": []}
elif text.startswith("You are checking"):
    ids = re.findall(r'^\{"id": "(c\d+)"', text, re.M)
    reply = {"verdicts": [{"id": found, "verdict": "supports", "reason": "made up for a test"} for found in ids]}
elif text.startswith("You are judging"):
    lines = [json.loads(line) for line in text.rsplit("<stances>", 1)[1].split("</stances>")[0].strip().splitlines()]
    reply = {"verdicts": [{"id": line["id"], "verdict": "kept", "stance": line["stance"], "quote_about_item": bool(line["user_quote"]), "rule_broken": False, "malfunction": False, "reason": "made up for a test"} for line in lines]}
else:
    part = text.rsplit("<session_part", 1)[1]
    said = re.findall(r"print reports short, message \d+", part)
    reply = {"notes": [{
        "type": "preference", "what": f"Prefers short reports, from {quote}.", "evidence": "USER-TYPED",
        "memory_candidate": True, "endorsement": "said", "endorsement_quote": quote, "origin_of_point": "user",
        "route": "memory", "confidence": "high",
        "items": [{"kind": "memory", "name": "existing", "stance": "for"}],
    } for quote in said]}
print(json.dumps({**RESULT, "result": json.dumps(reply)}))
'''


class Tree:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.projects = root / "projects"
        self.data = root / "upkeep"
        self.config_path = root / "config.json"
        self.memory = self.projects / PROJECT / "memory"
        self.fake = root / "fake"

    def control(self, **values) -> None:
        (self.fake / "control.json").write_text(json.dumps(values), encoding="utf-8")

    def calls(self) -> list[dict]:
        path = self.fake / "calls.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def clear_calls(self) -> None:
        (self.fake / "calls.jsonl").unlink()

    def invoke_command(self, pass_name: str) -> list[str]:
        return [shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-File", str(SCRIPT), "-Pass", pass_name, "-ConfigPath", str(self.config_path)]

    def invoke(self, pass_name: str = "daily") -> subprocess.CompletedProcess:
        return subprocess.run(
            self.invoke_command(pass_name), capture_output=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW, check=False,
        )

    def state(self) -> dict:
        return json.loads((self.data / "state" / "state.json").read_text(encoding="utf-8"))["sessions"]

    def marker(self):
        path = self.data / "failure-marker.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def notes(self) -> list[dict]:
        found = []
        for path in sorted((self.data / "notes").rglob("chunk-*.json")):
            found.extend(json.loads(path.read_text(encoding="utf-8"))["notes"])
        return found

    def session_parts(self) -> list[str]:
        return [call["text"].rsplit("<session_part", 1)[1] for call in self.calls() if "<session_part number=" in call["text"]]

    def git(self, folder: Path, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(folder), *arguments], capture_output=True, encoding="utf-8", check=False)


def conversation(session_id: str, first: int, count: int) -> list[dict]:
    records = []
    for number in range(first, first + count):
        records.append({**human(f"print reports short, message {number}", number * 2), "sessionId": session_id})
        records.append({**assistant_text("Understood.", number * 2 + 1), "sessionId": session_id})
    return records


@pytest.fixture
def tree(tmp_path):
    built = Tree(tmp_path)
    built.memory.mkdir(parents=True)
    (built.memory / "existing.md").write_text("---\nname: existing\ndescription: test\n---\n\nAn existing memory.\n", encoding="utf-8")
    (built.memory / "MEMORY.md").write_text("- [Existing](existing.md) — test\n", encoding="utf-8")
    built.data.mkdir()
    built.fake.mkdir()
    (built.fake / "claude.py").write_text(FAKE_CLAUDE, encoding="utf-8")
    (built.fake / "claude.cmd").write_text(f'@"{sys.executable}" "{built.fake / "claude.py"}" %*\r\n', encoding="utf-8")
    built.control()
    raw = json.loads((UPKEEP / "config.json").read_text(encoding="utf-8"))
    raw["paths"] = {
        "projects_dir": str(built.projects), "data_dir": str(built.data), "run_dir": str(built.data / "run"),
        "claude_exe": str(built.fake / "claude.cmd"), "local_settings": str(built.data / "local.json"),
    }
    raw["sessions"]["start_date"] = "2020-01-01T00:00:00+00:00"
    raw["memory"] = {"author_name": "Test Author", "author_email": "test@example.invalid"}
    raw["inventory"] = synthetic_inventory(tmp_path)
    built.config_path.write_text(json.dumps(raw), encoding="utf-8")
    config = load_config(str(built.config_path))
    memory_store.init_upkeep_repo(str(built.data), config.memory)
    daily.init_state(config)
    (built.data / "local.json").write_text(
        json.dumps({"python_exe": sys.executable, "apply_memory_changes": True, "private_terms": []}), encoding="utf-8"
    )
    return built


def set_small_chunks(tree: Tree) -> None:
    raw = json.loads(tree.config_path.read_text(encoding="utf-8"))
    raw["chunking"]["chunk_chars"] = 60
    tree.config_path.write_text(json.dumps(raw), encoding="utf-8")


def add_session(tree: Tree, session_id: str, records: list[dict]) -> None:
    write_jsonl(tree.projects / PROJECT / f"{session_id}.jsonl", records)


def test_daily_then_weekly_end_in_commits_ledger_entries_and_a_review(tree):
    add_session(tree, SESSION_A, conversation(SESSION_A, 1, 1))

    completed = tree.invoke("daily")
    assert completed.returncode == 0, completed.stderr
    assert tree.state()[f"{PROJECT}/{SESSION_A}"]["pending"] is None
    assert [note["quote_check"] for note in tree.notes()] == ["verified"]
    baseline = tree.git(tree.memory, "log", "--format=%s").stdout
    assert baseline.startswith(memory_store.BASELINE_MESSAGE)

    completed = tree.invoke("weekly")
    assert completed.returncode == 0, completed.stderr
    assert tree.marker() is None
    result = json.loads(sorted((tree.data / "logs").glob("weekly-*.result.json"))[-1].read_text(encoding="utf-8"))
    assert result["status"] == "ok" and result["daily"] is None, "the daily pass of this date had completed"

    # Memory: applied, committed by itself, and in the index.
    created = (tree.memory / "short-reports.md").read_text(encoding="utf-8")
    assert "Reports are kept short." in created and "print reports short, message 1" in created
    assert "(short-reports.md)" in (tree.memory / "MEMORY.md").read_text(encoding="utf-8")
    assert tree.git(tree.memory, "status", "--porcelain").stdout == ""
    subject = tree.git(tree.memory, "log", "-1", "--format=%s|%an|%B").stdout
    assert subject.startswith("Upkeep weekly") and "|Test Author|" in subject and "Co-Authored-By" not in subject

    # Ledgers: the note's mention of an existing item, and the applied claim.
    ledgers = [json.loads(path.read_text(encoding="utf-8")) for path in (tree.data / "ledgers").rglob("*.json")]
    by_entries = [entry for ledger in ledgers if isinstance(ledger, dict) for entry in ledger.get("entries", [])]
    assert len([entry for entry in by_entries if entry.get("quote") == "print reports short, message 1"]) == 2

    # The review, both forms, listing the change.
    review_files = {path.name: path for path in (tree.data / "reports").rglob("review.*")}
    assert set(review_files) == {"review.json", "review.html"}
    review = json.loads(review_files["review.json"].read_text(encoding="utf-8"))
    assert [item["record"]["memory"] for item in review["items"]] == ["short-reports"]
    assert "Reports are kept short." in review_files["review.html"].read_text(encoding="utf-8")

    # The data folder holds both passes as commits and has nothing left over.
    subjects = tree.git(tree.data, "log", "--format=%s").stdout
    assert "Daily pass" in subjects and "Weekly pass" in subjects
    assert tree.git(tree.data, "status", "--porcelain").stdout == ""
    tracked = tree.git(tree.data, "ls-files").stdout.splitlines()
    assert any(name.startswith("notes/") for name in tracked) and any(name.startswith("ledgers/") for name in tracked)

    # The recorded command lines: no tools in any call, in the file the run itself wrote.
    logged = [json.loads(line) for path in (tree.data / "reports").rglob("usage.jsonl") for line in path.read_text(encoding="utf-8").splitlines()]
    logged += [json.loads(line) for path in (tree.data / "notes").rglob("usage.jsonl") for line in path.read_text(encoding="utf-8").splitlines()]
    command_lines = [item["command_line"] for item in logged if "command_line" in item]
    assert len(command_lines) >= 2
    for command in command_lines:
        assert command[command.index("--tools") + 1] == "" and "--strict-mcp-config" in command and "dontAsk" in command

    # Both repositories refuse a push, with the guard the pass itself left.
    bare = tree.root / "bare.git"
    subprocess.run(["git", "init", "--quiet", "--bare", str(bare)], check=True)
    for folder in (tree.memory, tree.data):
        pushed = tree.git(folder, "push", str(bare), "HEAD:refs/heads/x")
        assert pushed.returncode != 0 and "push refused" in pushed.stderr
    assert tree.git(bare, "for-each-ref").stdout == ""

    # The 05:30 trigger of the same week.
    tree.clear_calls()
    assert tree.invoke("weekly").returncode == 0
    assert tree.calls() == []
    assert len(tree.git(tree.memory, "log", "--format=%s", "--grep=Upkeep weekly").stdout.splitlines()) == 1


def test_a_run_killed_in_mid_session_resumes_with_no_duplicate_and_no_lost_session(tree):
    set_small_chunks(tree)
    add_session(tree, SESSION_A, conversation(SESSION_A, 1, 3))
    add_session(tree, SESSION_B, conversation(SESSION_B, 4, 1))
    tree.control(hang_on_call=2)

    running = subprocess.Popen(tree.invoke_command("daily"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        deadline = time.monotonic() + WAIT_FOR_HANG_SECONDS
        while not (tree.fake / "hanging").exists():
            assert running.poll() is None, "the run ended instead of reaching the second call"
            assert time.monotonic() < deadline, "the second call was never reached"
            time.sleep(0.2)
    finally:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(running.pid)], capture_output=True, check=False)
        running.wait()

    assert (tree.data / "upkeep.lock").exists(), "a killed run cannot release its lock"
    assert tree.state()[f"{PROJECT}/{SESSION_A}"]["pending"] is not None
    assert len(tree.notes()) == 1
    assert f"{PROJECT}/{SESSION_B}" not in tree.state()
    # Chunks are 1 message each, so call 1 read message 1 and the kill fell on the second chunk.
    assert "message 1" in tree.session_parts()[0]

    tree.control()
    completed = tree.invoke("daily")
    assert completed.returncode == 0, completed.stderr
    assert [entry["kind"] for entry in tree.marker()["entries"]] == ["stale_lock"]
    assert not (tree.data / "upkeep.lock").exists()

    quotes = sorted(note["endorsement_quote"] for note in tree.notes())
    assert quotes == [f"print reports short, message {number}" for number in (1, 2, 3, 4)]
    state = tree.state()
    for session_id in (SESSION_A, SESSION_B):
        assert state[f"{PROJECT}/{session_id}"]["pending"] is None
        assert state[f"{PROJECT}/{session_id}"]["processed_through"]
    message_1_reads = [part for part in tree.session_parts() if "message 1" in part]
    assert len(message_1_reads) == 1, "the chunk finished before the kill was read again"

    entries = [
        entry for path in (tree.data / "ledgers").rglob("*.json") if "memory" in path.name or "existing" in path.name
        for entry in json.loads(path.read_text(encoding="utf-8")).get("entries", [])
    ]
    assert sorted(entry["quote"] for entry in entries) == quotes

    tree.clear_calls()
    assert tree.invoke("daily").returncode == 0
    assert tree.calls() == []
    assert len(tree.notes()) == 4


@pytest.mark.parametrize("form", ["json", "text"])
def test_a_limit_reached_in_mid_session_stops_warns_and_the_next_run_finishes(tree, form):
    """The form of a real limit reply was not captured; both a JSON error and plain text must stop."""
    set_small_chunks(tree)
    add_session(tree, SESSION_A, conversation(SESSION_A, 1, 3))
    add_session(tree, SESSION_B, conversation(SESSION_B, 4, 1))
    tree.control(limit_on_call=2, limit_form=form)

    completed = tree.invoke("daily")
    assert completed.returncode == 1
    assert len(tree.calls()) == 2, "the first failure stops the run: each further call would fail the same way"
    entry = tree.marker()["entries"][0]
    assert entry["kind"] == "failed" and entry["pass"] == "daily" and "ModelCallError" in entry["summary"]
    assert tree.state()[f"{PROJECT}/{SESSION_A}"]["pending"] is not None
    assert len(tree.notes()) == 1
    assert not (tree.data / "upkeep.lock").exists()

    tree.control()
    completed = tree.invoke("daily")
    assert completed.returncode == 0, completed.stderr
    assert tree.marker() is None
    assert sorted(note["endorsement_quote"] for note in tree.notes()) == [f"print reports short, message {number}" for number in (1, 2, 3, 4)]
