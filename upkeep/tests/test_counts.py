"""Counts by script."""
from __future__ import annotations

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


def count(tmp_path, config, main_records, subagent_records=()):
    main = write_jsonl(tmp_path / "main.jsonl", main_records)
    subs = [write_jsonl(tmp_path / "agent-1.jsonl", subagent_records)] if subagent_records else []
    return counts.count_entries(t.iter_session_entries(main, subs, None, None), config.counts)


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
