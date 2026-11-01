"""Pinned flags and the result check. No real call is made."""
from __future__ import annotations

import json
import os
import subprocess

import pytest

import model_call


def good_result(**overrides):
    result = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": '{"notes": []}',
        "usage": {"input_tokens": 1, "output_tokens": 2},
        "modelUsage": {"test-model": {"inputTokens": 1}},
        "total_cost_usd": 0.5,
        "duration_ms": 10,
        "num_turns": 1,
        "permission_denials": [],
    }
    result.update(overrides)
    return result


def test_extraction_command_is_exact():
    assert model_call.build_command("claude", (), "sonnet", 2.5) == [
        "claude", "-p", "--tools", "",
        "--permission-mode", "dontAsk",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--settings", '{"disableAllHooks":true}',
        "--output-format", "json",
        "--max-budget-usd", "2.500000",
        "--model", "sonnet",
    ]


def test_session_default_passes_no_model_flag():
    assert "--model" not in model_call.build_command("claude", (), None, 1)


def test_research_command_allows_only_web_tools():
    command = model_call.build_command("claude", model_call.RESEARCH_TOOLS, None, 1)
    assert command[command.index("--tools") + 1] == "WebSearch,WebFetch"
    assert command[command.index("--allowedTools") + 1] == "WebSearch,WebFetch"
    assert command[command.index("--permission-prompts") + 1] == "none"
    assert command[command.index("--permission-mode") + 1] == "dontAsk"


def test_any_other_tool_list_raises():
    with pytest.raises(ValueError, match="not allowed"):
        model_call.build_command("claude", ("Bash",), None, 1)


def test_good_result_passes():
    assert model_call.check_result(json.dumps(good_result()), 0, "")["result"] == '{"notes": []}'


@pytest.mark.parametrize(
    "stdout,returncode",
    [
        ("not json", 0),
        ("[]", 0),
        (json.dumps(good_result(type="assistant")), 0),
        (json.dumps(good_result(is_error=True)), 0),
        (json.dumps(good_result(subtype="error_during_execution")), 0),
        (json.dumps(good_result()), 1),
        (json.dumps(good_result(result="")), 0),
        (json.dumps(good_result(permission_denials=[{"tool_name": "Bash"}])), 0),
    ],
)
def test_bad_results_raise(stdout, returncode):
    with pytest.raises(model_call.ModelCallError):
        model_call.check_result(stdout, returncode, "")


def test_missing_usage_raises():
    result = good_result()
    del result["usage"]
    with pytest.raises(model_call.ModelCallError, match="usage"):
        model_call.check_result(json.dumps(result), 0, "")


def test_budget_stop_is_its_own_error():
    with pytest.raises(model_call.BudgetExhaustedError):
        model_call.check_result(json.dumps(good_result(subtype="error_max_budget_usd", is_error=True)), 1, "")


def fake_run(monkeypatch, stdout, returncode=0):
    seen = {}

    def run(command, **kwargs):
        seen.update(command=command, **kwargs)
        return subprocess.CompletedProcess(command, returncode, stdout.encode("utf-8"), b"")

    monkeypatch.setattr(model_call.subprocess, "run", run)
    return seen


def call(config, tmp_path, **overrides):
    arguments = dict(
        prompt="PROMPT",
        stdin_text="DATA",
        tools=(),
        model="sonnet",
        max_budget_usd=1.0,
        cwd=str(tmp_path),
        claude_exe="claude",
        model_config=config.model,
        chunking_config=config.chunking,
        usage_log_path=str(tmp_path / "logs" / "usage.jsonl"),
    )
    arguments.update(overrides)
    return model_call.call_model(**arguments)


def test_call_sends_utf8_stdin_scrubs_nesting_and_logs(monkeypatch, config, tmp_path):
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "x")
    monkeypatch.setenv("UNRELATED_VARIABLE", "kept")
    seen = fake_run(monkeypatch, json.dumps(good_result()))
    result = call(config, tmp_path, stdin_text="Linköping")
    assert result.text == '{"notes": []}'
    assert seen["input"] == "PROMPT\n\nLinköping".encode("utf-8")
    assert seen["env"]["UNRELATED_VARIABLE"] == "kept"
    assert "CLAUDECODE" not in seen["env"] and "CLAUDE_CODE_ENTRYPOINT" not in seen["env"]
    log = json.loads((tmp_path / "logs" / "usage.jsonl").read_text(encoding="utf-8"))
    assert log["check"] == "passed"
    assert log["command_line"][:2] == ["claude", "-p"]
    assert "PROMPT" not in json.dumps(log)


def test_failed_check_is_logged_and_raises(monkeypatch, config, tmp_path):
    fake_run(monkeypatch, json.dumps(good_result(is_error=True)))
    with pytest.raises(model_call.ModelCallError):
        call(config, tmp_path)
    log = json.loads((tmp_path / "logs" / "usage.jsonl").read_text(encoding="utf-8"))
    assert log["check"] == "failed"


def test_stdin_over_the_limit_raises_before_any_call(monkeypatch, config, tmp_path):
    seen = fake_run(monkeypatch, json.dumps(good_result()))
    with pytest.raises(ValueError, match="limit"):
        call(config, tmp_path, stdin_text="x" * (config.chunking.stdin_limit_bytes + 1))
    assert seen == {}


def test_no_budget_left_raises_before_any_call(monkeypatch, config, tmp_path):
    seen = fake_run(monkeypatch, json.dumps(good_result()))
    with pytest.raises(model_call.BudgetExhaustedError):
        call(config, tmp_path, max_budget_usd=0)
    assert seen == {}


def test_missing_working_directory_raises(monkeypatch, config, tmp_path):
    fake_run(monkeypatch, json.dumps(good_result()))
    with pytest.raises(FileNotFoundError):
        call(config, tmp_path, cwd=os.path.join(str(tmp_path), "absent"))
