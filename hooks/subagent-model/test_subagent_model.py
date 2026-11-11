import json
import os
import tempfile
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).with_name("subagent_model.py")


def run(tool_input, tool_name="Agent", raw=None):
    payload = raw if raw is not None else json.dumps(
        {"tool_name": tool_name, "tool_input": tool_input, "cwd": "C:/nonexistent"})  # pii-allow
    env = {**os.environ, "SUBAGENT_MODEL_LOG": str(Path(tempfile.gettempdir()) / "subagent-model-test.jsonl")}
    p = subprocess.run([sys.executable, str(HOOK)], input=payload, capture_output=True, text=True, env=env)
    out = json.loads(p.stdout)["hookSpecificOutput"] if p.stdout.strip() else None
    return p, out


def model_of(tool_input):
    p, out = run(tool_input)
    assert p.returncode == 0, p.stderr
    assert out["permissionDecision"] == "allow"
    assert out["updatedInput"]["prompt"] == tool_input["prompt"]
    return out["updatedInput"]["model"]


def test_existing_model_untouched():
    p, out = run({"description": "Review plan", "prompt": "x", "model": "haiku"})
    assert p.returncode == 0 and out is None


def test_explore_haiku():
    assert model_of({"description": "Map the code", "prompt": "x", "subagent_type": "Explore"}) == "haiku"


def test_review_opus():
    assert model_of({"description": "Review implementation against plan", "prompt": "x"}) == "opus"


def test_implementation_sonnet():
    assert model_of({"description": "Implement phase 2 of the plan", "prompt": "x"}) == "sonnet"


def test_commit_haiku_but_work_wins():
    assert model_of({"description": "Commit and push branch", "prompt": "x"}) == "haiku"
    assert model_of({"description": "Fix and commit the parser", "prompt": "x"}) == "sonnet"


def test_ambiguous_sonnet():
    assert model_of({"description": "Do the thing", "prompt": "please review everything"}) == "sonnet"


def test_bad_input_fails_loudly_nonblocking():
    p, out = run(None, raw="not json")
    assert p.returncode == 1 and out is None and "ERROR" in p.stderr
    p, out = run({"description": "", "prompt": ""})
    assert p.returncode == 1 and "ERROR" in p.stderr
