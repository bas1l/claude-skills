"""Counts by script."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import (
    assistant,
    attachment,
    system,
    tool_result,
    tool_use,
    user_no_origin,
    write_jsonl,
)

import counts
import transcripts as t
from config import load_config


def count(tmp_path, config, main_records, subagent_records=()):
    main = write_jsonl(tmp_path / "main.jsonl", main_records)
    subs = [write_jsonl(tmp_path / "agent-1.jsonl", subagent_records)] if subagent_records else []
    return counts.count_entries(t.iter_session_entries(main, subs, None, None), config.counts, config.secrets)


def test_tool_calls_and_failures_are_counted_per_source(tmp_path, config):
    main = [
        tool_use("a", "Bash", {"command": "ls"}),
        tool_result("a", "ok"),
        tool_use("b", "Bash", {"command": "cat x"}),
        tool_result("b", "cat: x: No such file or directory", is_error=True),
    ]
    subagent = [tool_use("c", "Read", {"file_path": "y"}), tool_result("c", "Traceback (most recent call)", is_error=True)]
    result = count(tmp_path, config, main, subagent)
    assert result["main"]["tool_calls"] == {"Bash": 2}
    assert result["main"]["errors_total"] == 1
    assert result["main"]["errors_by_class_hint"] == {"file missing": 1}
    assert result["subagent"]["errors_by_tool"] == {"Read": 1}
    assert result["subagent"]["errors_by_class_hint"] == {"python traceback": 1}


def test_ids_and_numbers_group_in_a_signature(config):
    first = counts.error_signature("failed at line 12 for deadbeef01", config.counts)
    second = counts.error_signature("failed at line 99 for cafebabe02", config.counts)
    assert first == second


STARTUP_LINE = "/c/Users/someone/.bashrc: line 1: /opt/conda/etc/profile.d/conda.sh: No such file or directory"


def test_a_startup_line_does_not_hide_the_real_error(config):
    first = counts.error_signature(f"{STARTUP_LINE}\nerror: pathspec 'x' did not match any file known to git", config.counts)
    second = counts.error_signature(f"{STARTUP_LINE}\nTypeError: unsupported operand", config.counts)
    assert first == "error: pathspec 'x' did not match any file known to git"
    assert second == "TypeError: unsupported operand"
    assert counts.error_signature("TypeError: unsupported operand", config.counts) == second


def test_a_startup_line_after_the_exit_code_header_is_taken_out_too(config):
    signature = counts.error_signature(f"Exit code 1\n{STARTUP_LINE}\nTypeError: unsupported operand", config.counts)
    assert signature == "Exit code #\nTypeError: unsupported operand"


def test_the_signature_holds_its_full_length_of_the_real_error(config):
    real = "x" * 100
    assert counts.error_signature(f"{STARTUP_LINE}\n{real}", config.counts) == "x" * config.counts.signature_chars


def test_a_startup_line_does_not_decide_the_class(config):
    text = f"{STARTUP_LINE}\nTypeError: unsupported operand"
    assert counts.classify_error(STARTUP_LINE, config.counts) == "file missing"
    assert counts.classify_error(text, config.counts) == "other"
    assert counts.classify_error(f"{STARTUP_LINE}\nTraceback (most recent call last):", config.counts) == "python traceback"


def test_an_error_with_only_startup_output_says_so(config):
    signature = counts.error_signature(STARTUP_LINE, config.counts)
    assert signature.startswith(counts.STARTUP_ONLY_LABEL)
    assert "conda.sh" in signature


@pytest.mark.parametrize("line", [
    "/home/someone/.zshrc:12: command not found: nvm",
    "/home/some one/.profile: line 3: oops: command not found",  # pii-allow
    "C:\\Users\\someone\\Documents\\PowerShell\\Microsoft.PowerShell_profile.ps1:4 something failed",
])
def test_other_startup_files_match_the_rule(config, line):
    assert counts.error_signature(f"{line}\nreal error", config.counts) == "real error"


@pytest.mark.parametrize("text", [
    "sed: /home/someone/.bashrc: No such file or directory",
    "cat: .profile: Permission denied",
    "",
])
def test_an_error_about_a_startup_file_itself_is_kept(config, text):
    assert counts.error_signature(text, config.counts) == text


def test_two_failures_behind_a_startup_line_count_apart(tmp_path, config):
    records = [
        tool_use("a", "Bash", {"command": "one"}),
        tool_result("a", f"Exit code 1\n{STARTUP_LINE}\nfirst real error", is_error=True),
        tool_use("b", "Bash", {"command": "two"}),
        tool_result("b", f"Exit code 1\n{STARTUP_LINE}\nsecond real error", is_error=True),
    ]
    main = count(tmp_path, config, records)["main"]
    assert sorted(item["signature"] for item in main["error_signatures"]) == ["Exit code #\nfirst real error", "Exit code #\nsecond real error"]
    assert main["errors_by_class_hint"] == {"exit code": 2}


def test_the_rule_is_a_required_setting(config, tmp_path):
    raw = json.loads((Path(__file__).resolve().parent.parent / "config.json").read_text(encoding="utf-8"))
    del raw["counts"]["startup_noise_line_patterns"]
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="startup_noise_line_patterns"):
        load_config(str(path))


def test_procedures_count_each_part_of_a_command_line():
    assert counts.command_words("cd x && rm y; rm z | wc -l") == ["cd", "rm", "wc"]


def test_denials_are_counted_by_kind_and_tool(tmp_path, config):
    records = [
        tool_use("a", "Bash", {"command": "rm x"}),
        tool_result("a", "held", is_error=True, toolDenialKind="permission-rule"),
    ]
    assert count(tmp_path, config, records)["main"]["denials"] == [
        {"kind": "permission-rule", "tool": "Bash", "count": 1}
    ]
    assert count(tmp_path, config, records)["main"]["procedures"] == {"Bash:rm": 1}


def test_usage_of_one_message_split_over_records_counts_once(tmp_path, config):
    usage = {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 100}
    records = [
        assistant([{"type": "text", "text": "a"}], message_id="m1", usage=usage),
        assistant([{"type": "text", "text": "b"}], message_id="m1", usage=usage),
        assistant([{"type": "text", "text": "c"}], message_id="m2", usage=usage),
    ]
    main = count(tmp_path, config, records)["main"]
    assert main["requests"] == 2
    assert main["usage"]["input_tokens"] == 20
    assert main["usage"]["cache_read_input_tokens"] == 200


def test_hooks_and_interrupts_are_counted(tmp_path, config):
    records = [
        attachment({"type": "hook_blocking_error", "hookName": "gate", "blockingError": {"x": 1}}),
        attachment({"type": "hook_cancelled", "hookName": "slow", "command": "c", "timedOut": True}),
        system("stop_hook_summary", preventedContinuation=True),
        system("api_error"),
        user_no_origin("[Request interrupted by user]"),
    ]
    main = count(tmp_path, config, records)["main"]
    assert main["hook_blocks"] == {"gate": 1}
    assert main["hook_cancelled"] == {"slow": 1}
    assert main["stop_hook_prevented"] == 1
    assert main["api_errors"] == 1
    assert main["user_interrupts"] == 1
