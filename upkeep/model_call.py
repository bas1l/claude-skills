"""The only place that runs ``claude``.

Pins the flags tested in ``docs/verification.md``: ``--tools ''`` alone leaves MCP tools
available, so the extraction call also needs ``--strict-mcp-config`` and the others, and
a research call needs ``--allowedTools`` because ``dontAsk`` refuses anything not allowed.

A research call uses the stream output, which holds each tool call and its result, so that
what was searched comes from the record of the run and not from the model's account of it.

The prompt goes on stdin, in UTF-8. Each call is logged with its command line, sizes,
usage and the result check, whether or not it succeeded.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from config import ChunkingConfig, ModelConfig

RESEARCH_TOOLS = ("WebSearch", "WebFetch")
NO_HOOKS_SETTINGS = '{"disableAllHooks":true}'


class ModelCallError(RuntimeError):
    """The call failed, or its result did not pass the check."""


class BudgetExhaustedError(ModelCallError):
    """The call stopped at its dollar limit."""


@dataclass(frozen=True)
class ToolActivity:
    """One tool call in a research run, with the text of its result."""

    name: str
    input: Mapping[str, Any]
    result_text: str
    is_error: bool


@dataclass(frozen=True)
class ModelResult:
    text: str
    usage: Mapping[str, Any]
    model_usage: Mapping[str, Any]
    cost_usd: float
    duration_ms: int
    num_turns: int
    command_line: tuple[str, ...]
    tool_activity: tuple[ToolActivity, ...] = ()


def build_command(claude_exe: str, tools: Sequence[str], model: Optional[str], max_budget_usd: float) -> list[str]:
    """The exact command for a tool list. ``model=None`` leaves the session default."""
    command = [claude_exe, "-p"]
    output_format = ["--output-format", "json"]
    if not tools:
        command += ["--tools", ""]
    elif tuple(tools) == RESEARCH_TOOLS:
        joined = ",".join(tools)
        command += ["--tools", joined, "--allowedTools", joined, "--permission-prompts", "none"]
        output_format = ["--output-format", "stream-json", "--verbose"]
    else:
        raise ValueError(f"tool list not allowed: {list(tools)}")
    command += [
        "--permission-mode", "dontAsk",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--settings", NO_HOOKS_SETTINGS,
        *output_format,
        "--max-budget-usd", f"{max_budget_usd:.6f}",
    ]
    if model is not None:
        command += ["--model", model]
    return command


def scrubbed_environment(prefixes: Sequence[str]) -> dict[str, str]:
    """The current environment without variables that mark a nested session."""
    return {key: value for key, value in os.environ.items() if not key.startswith(tuple(prefixes))}


def check_result(stdout: str, returncode: int, stderr: str) -> Mapping[str, Any]:
    """Parse the JSON result and raise unless it is a clean, tool-free success."""
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise ModelCallError(
            f"result is not JSON (exit {returncode}, {len(stdout)} chars of output); stderr: {stderr[:500]}"
        ) from error
    if not isinstance(result, dict) or result.get("type") != "result":
        raise ModelCallError(f"result has an unexpected shape (exit {returncode})")
    subtype = result.get("subtype")
    if "budget" in str(subtype):
        raise BudgetExhaustedError(f"stopped at the dollar limit: subtype {subtype!r}")
    if returncode != 0 or subtype != "success" or result.get("is_error") is not False:
        raise ModelCallError(
            f"call failed: exit {returncode}, subtype {subtype!r}, is_error {result.get('is_error')!r}, "
            f"result {str(result.get('result'))[:300]!r}; stderr: {stderr[:500]}"
        )
    if result.get("permission_denials"):
        raise ModelCallError(f"the model tried to use a tool: {len(result['permission_denials'])} denials")
    if not isinstance(result.get("result"), str) or not result["result"].strip():
        raise ModelCallError("result text is empty")
    for key in ("usage", "modelUsage", "total_cost_usd", "duration_ms", "num_turns"):
        if key not in result:
            raise ModelCallError(f"result lacks {key!r}")
    return result


def _result_text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(block.get("text", "")) if isinstance(block, dict) else str(block) for block in content)
    raise ModelCallError(f"tool result content has an unexpected shape: {type(content).__name__}")


def parse_stream(stdout: str) -> tuple[str, tuple[ToolActivity, ...]]:
    """From a stream output: the final result line as JSON text, and the tool calls made.
    A call with no result recorded counts as failed."""
    calls: dict[str, dict[str, Any]] = {}
    results: dict[str, tuple[str, bool]] = {}
    final = ""
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise ModelCallError(f"stream line is not JSON: {error}") from error
        kind = event.get("type")
        if kind == "result":
            final = line
        elif kind in ("assistant", "user"):
            content = event["message"]["content"]
            for block in content if isinstance(content, list) else ():
                if block.get("type") == "tool_use":
                    calls[block["id"]] = {"name": block["name"], "input": block["input"]}
                elif block.get("type") == "tool_result":
                    results[block["tool_use_id"]] = (_result_text_of(block.get("content", "")), bool(block.get("is_error")))
    activity = tuple(
        ToolActivity(call["name"], call["input"], *results.get(call_id, ("", True))) for call_id, call in calls.items()
    )
    return final, activity


def _append_log(path: str, record: Mapping[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def call_model(
    *,
    prompt: str,
    stdin_text: str,
    tools: Sequence[str],
    model: Optional[str],
    max_budget_usd: float,
    cwd: str,
    claude_exe: str,
    model_config: ModelConfig,
    chunking_config: ChunkingConfig,
    usage_log_path: str,
) -> ModelResult:
    """Run one call with ``prompt`` and ``stdin_text`` on stdin; return checked text and usage."""
    if max_budget_usd <= 0:
        raise BudgetExhaustedError(f"no budget left for this call: {max_budget_usd}")
    if not os.path.isdir(cwd):
        raise FileNotFoundError(f"working directory for the call not found: {cwd}")
    payload = f"{prompt}\n\n{stdin_text}".encode("utf-8")
    if len(payload) > chunking_config.stdin_limit_bytes:
        raise ValueError(f"stdin of {len(payload)} bytes is over the {chunking_config.stdin_limit_bytes} limit")
    command = build_command(claude_exe, tools, model, max_budget_usd)
    log: dict[str, Any] = {
        "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "command_line": command,
        "cwd": cwd,
        "stdin_bytes": len(payload),
    }
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            input=payload,
            capture_output=True,
            cwd=cwd,
            env=scrubbed_environment(model_config.scrub_env_prefixes),
            timeout=model_config.call_timeout_seconds,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            check=False,
        )
        stdout = completed.stdout.decode("utf-8")
        stderr = completed.stderr.decode("utf-8", "replace")
        log["returncode"] = completed.returncode
        activity: tuple[ToolActivity, ...] = ()
        if "stream-json" in command:
            stdout, activity = parse_stream(stdout)
        result = check_result(stdout, completed.returncode, stderr)
    except (ModelCallError, subprocess.TimeoutExpired, UnicodeDecodeError) as error:
        log.update(check="failed", error=str(error), wall_seconds=round(time.monotonic() - started, 1))
        _append_log(usage_log_path, log)
        raise
    log.update(
        check="passed",
        wall_seconds=round(time.monotonic() - started, 1),
        usage=result["usage"],
        model_usage=result["modelUsage"],
        cost_usd=result["total_cost_usd"],
        duration_ms=result["duration_ms"],
        num_turns=result["num_turns"],
        result_chars=len(result["result"]),
        tool_calls=[item.name for item in activity],
    )
    _append_log(usage_log_path, log)
    return ModelResult(
        text=result["result"],
        usage=result["usage"],
        model_usage=result["modelUsage"],
        cost_usd=result["total_cost_usd"],
        duration_ms=result["duration_ms"],
        num_turns=result["num_turns"],
        command_line=tuple(command),
        tool_activity=activity,
    )
