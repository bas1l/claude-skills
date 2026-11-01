"""Turn labelled entries into text for reading, cut to size and split into chunks.

Assistant text is complete. Tool calls and results are cut to ``tool_chars``, subagent
and teammate reports to ``report_chars``. Subagent files contribute only the user's
messages to teammates; their tool activity is counted by ``counts.py``.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

import transcripts as t
from config import CutsConfig, SecretsConfig

# Kinds a script counts and the model never reads.
SCRIPT_ONLY_KINDS = frozenset({t.MODEL_USAGE, t.STOP_HOOK_SUMMARY, t.API_ERROR})

# Kinds that make up the user's timeline, including the labelled non-own kinds, so a
# reader of any chunk can see what the user pasted, accepted or interrupted.
TIMELINE_KINDS = t.USER_OWN_KINDS | {t.USER_PASTED, t.USER_ACCEPTED_SUGGESTION, t.USER_INTERRUPT}

_FIXED_LABELS = {
    t.USER_TYPED: "USER-TYPED",
    t.USER_QUEUED: "USER-TYPED-WHILE-WORKING",
    t.USER_ANSWER: "USER-ANSWER",
    t.USER_REJECTION: "USER-REJECTED-TOOL-CALL",
    t.USER_TO_TEAMMATE: "USER-TO-TEAMMATE",
    t.USER_PASTED: "USER-PASTED (not the user's own words)",
    t.USER_ACCEPTED_SUGGESTION: "USER-ACCEPTED-SUGGESTION (model words)",
    t.USER_INTERRUPT: "USER-INTERRUPT",
    t.ASSISTANT_TEXT: "ASSISTANT-TEXT",
    t.SUBAGENT_REPORT: "SUBAGENT-REPORT",
    t.SUBAGENT_PROMPT: "SUBAGENT-PROMPT",
    t.COORDINATOR_MESSAGE: "COORDINATOR-MESSAGE",
    t.TEAMMATE_MESSAGE: "TEAMMATE-MESSAGE",
    t.COMPACT_SUMMARY: "COMPACT-SUMMARY (model words)",
    t.SCRIPTED_PROMPT: "SCRIPTED-PROMPT",
    t.LOCAL_COMMAND: "LOCAL-COMMAND",
    t.INJECTED_SKILL: "INJECTED-SKILL",
    t.SYSTEM_TEXT: "SYSTEM-TEXT",
    t.HOOK_FEEDBACK: "HOOK-FEEDBACK",
    t.HOOK_MESSAGE: "HOOK-MESSAGE",
}
_TOOL_LABELS = {
    t.TOOL_CALL: "TOOL-CALL",
    t.TOOL_RESULT: "TOOL-RESULT",
    t.TOOL_ERROR: "TOOL-ERROR",
    t.HOOK_BLOCK: "HOOK-BLOCK",
    t.HOOK_ERROR: "HOOK-ERROR",
    t.HOOK_CANCELLED: "HOOK-CANCELLED",
    t.HOOK_OK: "HOOK-OK",
}

_ENTRY_HEADER_RE = re.compile(r"^=== \[", re.M)


@dataclass(frozen=True)
class RenderedEntry:
    kind: str
    timestamp: datetime
    text: str


@dataclass(frozen=True)
class Chunk:
    number: int
    total: int
    entries_text: str
    first_timestamp: datetime
    last_timestamp: datetime
    entry_count: int

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.entries_text.encode("utf-8")).hexdigest()


def _label(entry: t.Entry) -> str:
    if entry.kind in _FIXED_LABELS:
        return _FIXED_LABELS[entry.kind]
    if entry.kind in _TOOL_LABELS:
        return f"{_TOOL_LABELS[entry.kind]} {entry.tool_name}"
    if entry.kind == t.TOOL_DENIED:
        return f"TOOL-DENIED:{entry.denial_kind} {entry.tool_name}"
    raise ValueError(f"no label for entry kind {entry.kind!r}")


def _limit(entry: t.Entry, cuts: CutsConfig) -> int | None:
    """The cut for an entry, or None where the text stays complete."""
    if entry.kind in (t.TOOL_CALL, t.TOOL_RESULT, t.TOOL_ERROR, t.TOOL_DENIED):
        return cuts.report_chars if entry.tool_name in cuts.report_tools else cuts.tool_chars
    if entry.kind in (t.SUBAGENT_REPORT, t.TEAMMATE_MESSAGE, t.COORDINATOR_MESSAGE, t.SUBAGENT_PROMPT):
        return cuts.report_chars
    if entry.kind == t.USER_PASTED:
        return cuts.pasted_chars
    if entry.kind == t.COMPACT_SUMMARY:
        return cuts.compact_summary_chars
    if entry.kind in (t.SYSTEM_TEXT, t.SCRIPTED_PROMPT, t.LOCAL_COMMAND, t.INJECTED_SKILL):
        return cuts.system_chars
    if entry.kind in (t.HOOK_FEEDBACK, t.HOOK_BLOCK, t.HOOK_ERROR, t.HOOK_CANCELLED, t.HOOK_OK, t.HOOK_MESSAGE):
        return cuts.hook_chars
    return None


def cut_text(text: str, limit: int | None) -> str:
    if limit is None or len(text) <= limit:
        return text
    return f"{text[:limit]} ...[CUT {len(text) - limit} chars]"


def redact_secrets(text: str, secrets: SecretsConfig) -> str:
    for name, pattern in secrets.patterns:
        text = re.sub(pattern, f"[REDACTED-{name}]", text)
    return text


def _clean(text: str) -> str:
    """Make text safe to send: lone surrogates become U+FFFD, and a line in the text
    cannot pose as an entry header."""
    text = text.encode("utf-8", "replace").decode("utf-8")
    return _ENTRY_HEADER_RE.sub("=== (", text)


def is_read_by_model(entry: t.Entry) -> bool:
    if entry.kind in SCRIPT_ONLY_KINDS:
        return False
    return entry.source == "main" or entry.kind == t.USER_TO_TEAMMATE


def render_entries(entries: Iterable[t.Entry], cuts: CutsConfig, secrets: SecretsConfig) -> list[RenderedEntry]:
    """Render what the model reads, in time order. Repeated hook successes appear once."""
    selected = sorted((e for e in entries if is_read_by_model(e)), key=lambda e: e.timestamp)
    seen_hook_prefixes: set[str] = set()
    rendered = []
    for entry in selected:
        if entry.kind == t.HOOK_OK:
            prefix = entry.text[: cuts.hook_repeat_prefix_chars]
            if prefix in seen_hook_prefixes or not entry.text.strip():
                continue
            seen_hook_prefixes.add(prefix)
        body = cut_text(entry.text, _limit(entry, cuts))
        if entry.context:
            body = f"(asked: {cut_text(entry.context, cuts.tool_chars)})\n{body}"
        body = _clean(redact_secrets(body, secrets))
        stamp = entry.timestamp.strftime("%Y-%m-%dT%H:%M:%S")
        rendered.append(RenderedEntry(entry.kind, entry.timestamp, f"\n=== [{_label(entry)}] {stamp}\n{body}"))
    return rendered


def build_timeline(rendered: Iterable[RenderedEntry]) -> str:
    """Every user message in order, for orientation in each chunk."""
    return "".join(entry.text for entry in rendered if entry.kind in TIMELINE_KINDS)


def split_into_chunks(rendered: list[RenderedEntry], chunk_chars: int) -> list[Chunk]:
    """Split on entry boundaries into chunks of at most ``chunk_chars``.

    An entry longer than ``chunk_chars`` is kept whole in a chunk of its own, because
    assistant text is never cut.
    """
    if chunk_chars <= 0:
        raise ValueError(f"chunk_chars must be positive: {chunk_chars}")
    groups: list[list[RenderedEntry]] = []
    current: list[RenderedEntry] = []
    size = 0
    for entry in rendered:
        if current and size + len(entry.text) > chunk_chars:
            groups.append(current)
            current = []
            size = 0
        current.append(entry)
        size += len(entry.text)
    if current:
        groups.append(current)
    return [
        Chunk(
            number=number,
            total=len(groups),
            entries_text="".join(entry.text for entry in group),
            first_timestamp=group[0].timestamp,
            last_timestamp=group[-1].timestamp,
            entry_count=len(group),
        )
        for number, group in enumerate(groups, 1)
    ]


def chunk_input_text(chunk: Chunk, timeline: str) -> str:
    """The text one model call reads: the user's timeline, then this part of the session."""
    return (
        "<user_timeline note=\"All the user's messages in this window, for context. "
        "Covers more than this part.\">"
        f"{timeline}\n</user_timeline>\n\n"
        f"<session_part number=\"{chunk.number}\" of=\"{chunk.total}\">"
        f"{chunk.entries_text}\n</session_part>\n"
    )
