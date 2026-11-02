"""Count tool activity, failures, denials, hook blocks and tokens from entries, by script.

The result is plain JSON-ready data for one session. Error classes are keyword hints:
a signature sits beside each class so that a reader can check a match before relying
on the count.
"""
from __future__ import annotations

import collections
import re
from typing import Any, Iterable, Optional

import render
import transcripts as t
from config import CountsConfig, SecretsConfig

SCHEMA_VERSION = 1
USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
STARTUP_ONLY_LABEL = "[only start-up output] "

_SHELL_SEPARATORS = ("&&", "||", ";", "|")
_ASSIGNMENT_RE = re.compile(r"""(?:\$env:[A-Za-z_]\w*\s*=\s*|[A-Za-z_]\w*=)(?:"[^"]*"|'[^']*'|\S*)(?:\s+|$)""")
_DIGITS_RE = re.compile(r"[0-9a-f]{8,}|\d+")


def _without_startup_noise(text: str, config: CountsConfig) -> tuple[str, bool]:
    """The start of an error text without lines a shell's start-up file printed, and whether
    any line was taken out. Such a line says nothing about the command that failed, and it comes
    first, so it would otherwise fill the signature and match the wrong class."""
    lines = text[: config.class_scan_chars].splitlines()
    kept = [line for line in lines if not any(re.search(pattern, line) for pattern in config.startup_noise_line_patterns)]
    return "\n".join(kept).strip(), len(kept) != len(lines)


def classify_error(text: str, config: CountsConfig) -> str:
    """The first configured class whose pattern matches the start of an error text. If start-up
    lines are all there is, they are what gets classified."""
    remaining, _ = _without_startup_noise(text, config)
    head = remaining if remaining else text[: config.class_scan_chars]
    for name, pattern in config.error_classes:
        if re.search(pattern, head):
            return name
    return "other"


def error_signature(text: str, config: CountsConfig) -> str:
    """The start of an error, past any start-up lines, with ids and numbers masked, so repeats
    group together. An error holding nothing else says so, because then no real error was seen.
    A Python traceback starts the same way whatever went wrong, so its last line is what is kept.
    The caller redacts first: a token with its digits masked no longer matches its pattern."""
    if config.traceback_marker in text:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return _DIGITS_RE.sub("#", lines[-1][: config.signature_chars])
    remaining, removed = _without_startup_noise(text, config)
    if not removed:
        return _DIGITS_RE.sub("#", text[: config.signature_chars])
    if remaining:
        return _DIGITS_RE.sub("#", remaining[: config.signature_chars])
    return STARTUP_ONLY_LABEL + _DIGITS_RE.sub("#", text[: config.signature_chars])


def _command_parts(command: str) -> list[str]:
    """A command line split at its separators, leaving quoted text whole. A quote never closed
    runs to the end, so that the words after it cannot pass for commands."""
    parts = []
    current: list[str] = []
    quote: Optional[str] = None
    position = 0
    while position < len(command):
        character = command[position]
        if quote is not None:
            if character == "\\" and quote == '"':
                current.append(command[position:position + 2])
                position += 2
                continue
            if character == quote:
                quote = None
        elif character in "\"'":
            quote = character
        else:
            separator = next((item for item in _SHELL_SEPARATORS if command.startswith(item, position)), None)
            if separator is not None:
                parts.append("".join(current))
                current = []
                position += len(separator)
                continue
        current.append(character)
        position += 1
    parts.append("".join(current))
    return parts


def _first_word(part: str) -> Optional[str]:
    """The command of one part, past any variable set in front of it, whose value may be a secret."""
    rest = part.strip()
    while True:
        match = _ASSIGNMENT_RE.match(rest)
        if match is None:
            break
        rest = rest[match.end():]
    pieces = rest.split()
    return pieces[0] if pieces else None


def command_words(command: str) -> list[str]:
    """The first word of each part of a shell command line, once each, in order."""
    words = []
    for part in _command_parts(command):
        word = _first_word(part)
        if word is not None and word not in words:
            words.append(word)
    return words


def _shell_command(entry: t.Entry) -> str:
    if entry.tool_input is None or "command" not in entry.tool_input:
        raise ValueError(f"shell tool call without a command at {entry.timestamp.isoformat()}")
    return str(entry.tool_input["command"])


class _SourceCounts:
    """Counters for one source: the main conversation or the subagents together."""

    def __init__(self) -> None:
        self.tool_calls: collections.Counter[str] = collections.Counter()
        self.tool_results = 0
        self.errors_by_tool: collections.Counter[str] = collections.Counter()
        self.errors_by_class: collections.Counter[str] = collections.Counter()
        self.error_signatures: collections.Counter[tuple[str, str, str]] = collections.Counter()
        self.denials: collections.Counter[tuple[str, str]] = collections.Counter()
        self.procedures: collections.Counter[str] = collections.Counter()
        self.hook_blocks: collections.Counter[str] = collections.Counter()
        self.hook_errors: collections.Counter[str] = collections.Counter()
        self.hook_cancelled: collections.Counter[str] = collections.Counter()
        self.stop_hook_prevented = 0
        self.api_errors = 0
        self.user_interrupts = 0
        self.usage: collections.Counter[str] = collections.Counter()
        self.requests = 0
        self.seen_messages: set[str] = set()
        self.secrets_redacted = 0

    def add(self, entry: t.Entry, config: CountsConfig, secrets: SecretsConfig) -> None:
        kind = entry.kind
        if kind == t.TOOL_CALL:
            self.tool_calls[entry.tool_name] += 1
            if entry.tool_name in config.shell_tools:
                for word in command_words(_shell_command(entry)):
                    self.procedures[f"{entry.tool_name}:{word}"] += 1
        elif kind in (t.TOOL_RESULT, t.USER_ANSWER, t.USER_CHOSE_OPTION):
            self.tool_results += 1
        elif kind == t.TOOL_ERROR:
            self.tool_results += 1
            self.errors_by_tool[entry.tool_name] += 1
            error_class = classify_error(entry.text, config)
            self.errors_by_class[error_class] += 1
            redacted, matches = render.redact_counted(entry.text, secrets)
            self.secrets_redacted += matches
            self.error_signatures[(entry.tool_name, error_class, error_signature(redacted, config))] += 1
        elif kind in (t.TOOL_DENIED, t.USER_REJECTION):
            self.tool_results += 1
            self.denials[(entry.denial_kind, entry.tool_name)] += 1
        elif kind == t.HOOK_BLOCK:
            self.hook_blocks[entry.tool_name] += 1
        elif kind == t.HOOK_ERROR:
            self.hook_errors[entry.tool_name] += 1
        elif kind == t.HOOK_CANCELLED:
            self.hook_cancelled[entry.tool_name] += 1
        elif kind == t.STOP_HOOK_SUMMARY:
            self.stop_hook_prevented += int(entry.prevented_continuation)
        elif kind == t.API_ERROR:
            self.api_errors += 1
        elif kind == t.USER_INTERRUPT:
            self.user_interrupts += 1
        elif kind == t.MODEL_USAGE:
            self._add_usage(entry)

    def _add_usage(self, entry: t.Entry) -> None:
        # One API message spans several records that repeat the same usage.
        if entry.message_id in self.seen_messages:
            return
        self.seen_messages.add(entry.message_id)
        self.requests += 1
        for field in USAGE_FIELDS:
            self.usage[field] += entry.usage.get(field) or 0

    def to_json(self) -> dict[str, Any]:
        return {
            "tool_calls": dict(self.tool_calls),
            "tool_results": self.tool_results,
            "errors_total": sum(self.errors_by_tool.values()),
            "errors_by_tool": dict(self.errors_by_tool),
            "errors_by_class_hint": dict(self.errors_by_class),
            "error_signatures": [
                {"tool": tool, "class_hint": error_class, "signature": signature, "count": count}
                for (tool, error_class, signature), count in self.error_signatures.most_common()
            ],
            "denials": [
                {"kind": kind, "tool": tool, "count": count} for (kind, tool), count in self.denials.most_common()
            ],
            "procedures": dict(self.procedures),
            "hook_blocks": dict(self.hook_blocks),
            "hook_errors": dict(self.hook_errors),
            "hook_cancelled": dict(self.hook_cancelled),
            "stop_hook_prevented": self.stop_hook_prevented,
            "api_errors": self.api_errors,
            "user_interrupts": self.user_interrupts,
            "requests": self.requests,
            "usage": {field: self.usage[field] for field in USAGE_FIELDS},
            "secrets_redacted": self.secrets_redacted,
        }


def count_entries(entries: Iterable[t.Entry], config: CountsConfig, secrets: SecretsConfig) -> dict[str, Any]:
    """Counts per source, with unknown sources raising."""
    by_source = {"main": _SourceCounts(), "subagent": _SourceCounts()}
    for entry in entries:
        by_source[entry.source].add(entry, config, secrets)
    return {
        "schema_version": SCHEMA_VERSION,
        "main": by_source["main"].to_json(),
        "subagent": by_source["subagent"].to_json(),
    }
