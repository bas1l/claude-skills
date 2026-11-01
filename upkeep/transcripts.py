"""Stream session transcripts and label every entry by who produced it.

The transcript format is undocumented and changes without notice, so everything this
module does not recognise raises ``TranscriptFormatError``: an unknown record type,
``origin.kind``, attachment type, system subtype, content block or denial kind stops
the run and leaves the session unprocessed.

The six sender rules, each found in real data:

1. Messages typed while the assistant is working exist only as ``queued_command``
   attachments and are included (``USER_QUEUED``).
2. Teammate records have no origin and are not marked meta or subagent. They are
   recognised by shape and excluded from the user's words (``TEAMMATE``).
3. Accepted suggestions are marked human but hold model words (``USER_ACCEPTED_SUGGESTION``).
4. Pasted text carries an id in its closing tag and is split off (``USER_PASTED``).
5. Harness reminders inside a human record are stripped.
6. Question answers and rejections inside tool results count as the user's
   (``USER_ANSWER``, ``USER_REJECTION``), as do the user's messages to teammates,
   found only in subagent files (``USER_TO_TEAMMATE``).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Iterable, Iterator, Mapping, Optional

USER_TYPED = "user_typed"
USER_QUEUED = "user_queued"
USER_ANSWER = "user_answer"
USER_REJECTION = "user_rejection"
USER_TO_TEAMMATE = "user_to_teammate"
USER_PASTED = "user_pasted"
USER_ACCEPTED_SUGGESTION = "user_accepted_suggestion"
USER_INTERRUPT = "user_interrupt"
ASSISTANT_TEXT = "assistant_text"
TOOL_CALL = "tool_call"
TOOL_RESULT = "tool_result"
TOOL_ERROR = "tool_error"
TOOL_DENIED = "tool_denied"
SUBAGENT_REPORT = "subagent_report"
SUBAGENT_PROMPT = "subagent_prompt"
COORDINATOR_MESSAGE = "coordinator_message"
TEAMMATE_MESSAGE = "teammate_message"
COMPACT_SUMMARY = "compact_summary"
SCRIPTED_PROMPT = "scripted_prompt"
LOCAL_COMMAND = "local_command"
INJECTED_SKILL = "injected_skill"
SYSTEM_TEXT = "system_text"
HOOK_FEEDBACK = "hook_feedback"
HOOK_BLOCK = "hook_block"
HOOK_ERROR = "hook_error"
HOOK_CANCELLED = "hook_cancelled"
HOOK_OK = "hook_ok"
HOOK_MESSAGE = "hook_message"
STOP_HOOK_SUMMARY = "stop_hook_summary"
API_ERROR = "api_error"
MODEL_USAGE = "model_usage"

# The user's own words: the only kinds a quote may be verified against.
USER_OWN_KINDS = frozenset({USER_TYPED, USER_QUEUED, USER_ANSWER, USER_REJECTION, USER_TO_TEAMMATE})

# Records that belong to the conversation. Everything else is bookkeeping.
CONVERSATION_RECORD_TYPES = frozenset({"user", "assistant", "attachment", "system"})
BOOKKEEPING_RECORD_TYPES = frozenset({
    "agent-name", "agent-setting", "ai-title", "api-request", "api-request-blob", "api-request-shape",
    "artifact-autoreact-ledger", "artifact-comment-monitor", "atis-latch", "bridge-session",
    "continued-in", "cost-state", "custom-title", "file-history-delta", "file-history-snapshot",
    "fork-context-ref", "frame-link", "last-prompt", "launched", "mode", "permission-mode",
    "queue-operation", "result", "started", "tools-used",
})

KNOWN_ORIGIN_KINDS = frozenset({"human", "task-notification", "coordinator", "peer", "auto-continuation"})
KNOWN_DENIAL_KINDS = frozenset({"permission-rule", "user-rejected", "automode-blocked", "interrupted"})
ATTACHMENTS_IGNORED = frozenset({
    "agent_listing_delta", "auto_mode", "bash_output_audience_note", "batching_reminder_sent",
    "budget_usd", "command_permissions", "compact_file_reference", "credential_org", "date",
    "date_change", "deferred_tools_delta", "deferred_tools_record", "environment", "instructions",
    "invoked_skills", "max_turns_reached", "mcp_instructions_delta", "model", "nested_memory",
    "prompt_snapshot", "read_truncation_notice", "remote_session_change", "session_context",
    "session_cron_carry", "skill_listing", "skill_mention", "task_reminder", "team_context",
    "thinking_drop", "total_tokens_reminder",
})
SYSTEM_SUBTYPES_READ = frozenset({
    "away_summary", "bridge_status", "compact_boundary", "informational", "local_command",
    "model_refusal_fallback", "scheduled_task_fire",
})
SYSTEM_SUBTYPES_IGNORED = frozenset({"agents_killed", "turn_duration"})
TOOL_RESULT_INNER_TYPES = frozenset({"text", "image", "tool_reference", "document"})

ASK_USER_TOOL = "AskUserQuestion"
REJECTION_PREFIX = "The user doesn't want to proceed with this tool use."

_PASTED_RE = re.compile(r"<pasted_content\b[^>]*>(.*?)(?:</pasted_content\b[^>]*>|\Z)", re.S)
_HARNESS_TEXT_RE = re.compile(
    r"<(system-reminder|local-command-caveat|local-command-stdout|bash-stdout|bash-stderr)>.*?</\1>", re.S
)
_COMMAND_NAME_RE = re.compile(r"<command-name>(.*?)</command-name>", re.S)
_COMMAND_ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.S)
_COMMAND_TAGS_RE = re.compile(r"<command-(message|name|args)>.*?</command-\1>", re.S)
_LOCAL_COMMAND_PREFIXES = ("<command-name>", "<local-command", "<bash-input>", "<bash-stdout>")
_TEAMMATE_PREFIXES = ("Another Claude session sent a message", "<teammate-message")
_QUEUED_NOTIFICATION_PREFIXES = ("<task-notification", "Background agent")


class TranscriptFormatError(ValueError):
    """A record does not match the known transcript format."""


@dataclass(frozen=True)
class Entry:
    """One labelled piece of a session, in transcript order."""

    kind: str
    timestamp: datetime
    text: str
    source: str
    cwd: str
    tool_name: str = ""
    tool_input: Optional[Mapping[str, Any]] = None
    context: str = ""
    denial_kind: str = ""
    message_id: str = ""
    model: str = ""
    usage: Optional[Mapping[str, Any]] = None
    prevented_continuation: bool = False


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise TranscriptFormatError(f"timestamp without a UTC offset: {value!r}")
    return parsed


def iter_records(path: str) -> Iterator[tuple[int, Mapping[str, Any]]]:
    """Yield ``(line_number, record)``.

    A final line with no newline is a record still being written by a live session,
    and is left for the next run. Any other unparsable line raises.
    """
    with open(path, encoding="utf-8", newline="\n") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.endswith("\n"):
                return
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise TranscriptFormatError(f"{path}:{line_number}: invalid JSON: {error}") from error
            record_type = record.get("type")
            if record_type not in CONVERSATION_RECORD_TYPES and record_type not in BOOKKEEPING_RECORD_TYPES:
                raise TranscriptFormatError(f"{path}:{line_number}: unknown record type {record_type!r}")
            yield line_number, record


def _require(mapping: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise TranscriptFormatError(f"{where}: missing field {key!r}")
    return mapping[key]


def _text_of_user_content(content: Any, where: str) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        raise TranscriptFormatError(f"{where}: message content is {type(content).__name__}")
    parts = []
    for block in content:
        block_type = _require(block, "type", where)
        if block_type == "text":
            parts.append(_require(block, "text", where))
        elif block_type == "image":
            parts.append("[image]")
        else:
            raise TranscriptFormatError(f"{where}: unknown user content block {block_type!r}")
    return "\n".join(parts)


def _text_of_tool_result(block: Mapping[str, Any], where: str) -> str:
    content = block.get("content", "")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        raise TranscriptFormatError(f"{where}: tool result content is {type(content).__name__}")
    parts = []
    for inner in content:
        inner_type = _require(inner, "type", where)
        if inner_type not in TOOL_RESULT_INNER_TYPES:
            raise TranscriptFormatError(f"{where}: unknown tool result block {inner_type!r}")
        parts.append(inner["text"] if inner_type == "text" else f"[{inner_type}]")
    return "\n".join(parts)


def split_pasted(text: str) -> list[tuple[bool, str]]:
    """Split a user message into ``(is_pasted, part)`` pairs, stripped, dropping empty parts."""
    parts: list[tuple[bool, str]] = []
    position = 0
    for match in _PASTED_RE.finditer(text):
        parts.append((False, text[position:match.start()]))
        parts.append((True, match.group(1)))
        position = match.end()
    parts.append((False, text[position:]))
    return [(pasted, part.strip()) for pasted, part in parts if part.strip()]


def _strip_harness_text(text: str) -> str:
    """Remove harness reminders and rewrite a slash-command wrapper to what was typed."""
    names = _COMMAND_NAME_RE.findall(text)
    if names:
        arguments = _COMMAND_ARGS_RE.findall(text)
        typed = " ".join([names[0].strip()] + [a.strip() for a in arguments if a.strip()])
        text = typed + "\n" + _COMMAND_TAGS_RE.sub("", text)
    return _HARNESS_TEXT_RE.sub("", text)


class _FileClassifier:
    """Turn the records of one transcript file into entries."""

    def __init__(self, path: str, source: str) -> None:
        self._path = path
        self._source = source
        self._tool_names: dict[str, str] = {}

    def note_tool_uses(self, record: Mapping[str, Any]) -> None:
        """Remember tool names, including those before a window, so results can be named."""
        if record.get("type") != "assistant":
            return
        for block in record["message"]["content"]:
            if block.get("type") == "tool_use":
                self._tool_names[block["id"]] = block["name"]

    def _entry(self, record: Mapping[str, Any], kind: str, text: str, where: str, **fields: Any) -> Entry:
        return Entry(
            kind=kind,
            timestamp=parse_timestamp(_require(record, "timestamp", where)),
            text=text,
            source=self._source,
            cwd=_require(record, "cwd", where),
            **fields,
        )

    def classify(self, record: Mapping[str, Any], line_number: int) -> list[Entry]:
        where = f"{self._path}:{line_number}"
        record_type = record["type"]
        if record_type == "user":
            return self._user(record, where)
        if record_type == "assistant":
            return self._assistant(record, where)
        if record_type == "attachment":
            return self._attachment(record, where)
        if record_type == "system":
            return self._system(record, where)
        return []

    # --- user records --------------------------------------------------------------

    def _user(self, record: Mapping[str, Any], where: str) -> list[Entry]:
        content = _require(_require(record, "message", where), "content", where)
        if isinstance(content, list) and any(block.get("type") == "tool_result" for block in content):
            return self._tool_results(record, content, where)
        text = _text_of_user_content(content, where)
        origin = record.get("origin")
        if origin is None:
            return [self._entry(record, self._kind_without_origin(record, text, where), text, where)]
        kind = _require(origin, "kind", where)
        if kind not in KNOWN_ORIGIN_KINDS:
            raise TranscriptFormatError(f"{where}: unknown origin.kind {kind!r}")
        if kind == "human":
            return self._human(record, text, where)
        return [self._entry(record, self._kind_of_other_origin(kind), text, where)]

    @staticmethod
    def _kind_of_other_origin(kind: str) -> str:
        return {
            "task-notification": SUBAGENT_REPORT,
            "coordinator": COORDINATOR_MESSAGE,
            "peer": TEAMMATE_MESSAGE,
            "auto-continuation": SYSTEM_TEXT,
        }[kind]

    @staticmethod
    def _kind_without_origin(record: Mapping[str, Any], text: str, where: str) -> str:
        if record.get("isCompactSummary"):
            return COMPACT_SUMMARY
        if record.get("isMeta"):
            if text.startswith("Stop hook"):
                return HOOK_FEEDBACK
            if "Base directory for this skill" in text[:300]:
                return INJECTED_SKILL
            return SYSTEM_TEXT
        if text.startswith(_TEAMMATE_PREFIXES):
            return TEAMMATE_MESSAGE
        if text.startswith("[Request interrupted"):
            return USER_INTERRUPT
        if text.startswith(_LOCAL_COMMAND_PREFIXES):
            return LOCAL_COMMAND
        if record.get("promptSource") == "sdk":
            return SCRIPTED_PROMPT
        if record.get("isSidechain"):
            return SUBAGENT_PROMPT
        raise TranscriptFormatError(f"{where}: user record with no origin and an unknown shape")

    def _human(self, record: Mapping[str, Any], text: str, where: str) -> list[Entry]:
        if record.get("promptSource") == "suggestion_accepted":
            return [self._entry(record, USER_ACCEPTED_SUGGESTION, text.strip(), where)]
        own_kind = USER_TO_TEAMMATE if self._source != "main" or record.get("isSidechain") else USER_TYPED
        return self._user_message_entries(record, text, own_kind, where)

    def _user_message_entries(self, record: Mapping[str, Any], text: str, own_kind: str, where: str) -> list[Entry]:
        entries = []
        for is_pasted, part in split_pasted(text):
            if is_pasted:
                entries.append(self._entry(record, USER_PASTED, part, where))
                continue
            own = _strip_harness_text(part).strip()
            if own:
                entries.append(self._entry(record, own_kind, own, where))
        return entries

    def _tool_results(self, record: Mapping[str, Any], blocks: list, where: str) -> list[Entry]:
        denial_kind = record.get("toolDenialKind") or ""
        if denial_kind and denial_kind not in KNOWN_DENIAL_KINDS:
            raise TranscriptFormatError(f"{where}: unknown toolDenialKind {denial_kind!r}")
        entries = []
        for block in blocks:
            block_type = _require(block, "type", where)
            if block_type == "text":
                entries.append(self._entry(record, SYSTEM_TEXT, _require(block, "text", where), where))
            elif block_type == "tool_result":
                entries.append(self._tool_result(record, block, denial_kind, where))
            else:
                raise TranscriptFormatError(f"{where}: unknown block {block_type!r} beside a tool result")
        return entries

    def _tool_result(self, record: Mapping[str, Any], block: Mapping[str, Any], denial_kind: str, where: str) -> Entry:
        tool_use_id = _require(block, "tool_use_id", where)
        if tool_use_id not in self._tool_names:
            raise TranscriptFormatError(f"{where}: tool result for an unseen tool call")
        tool_name = self._tool_names[tool_use_id]
        text = _text_of_tool_result(block, where)
        fields = {"tool_name": tool_name, "denial_kind": denial_kind}
        if denial_kind == "user-rejected":
            if not text.startswith(REJECTION_PREFIX):
                raise TranscriptFormatError(f"{where}: user rejection with an unknown shape")
            return self._entry(record, USER_REJECTION, f"[rejected the {tool_name} call]", where, **fields)
        if denial_kind:
            return self._entry(record, TOOL_DENIED, text, where, **fields)
        if block.get("is_error"):
            return self._entry(record, TOOL_ERROR, text, where, **fields)
        if tool_name == ASK_USER_TOOL:
            return self._question_answer(record, fields, where)
        return self._entry(record, TOOL_RESULT, text, where, **fields)

    def _question_answer(self, record: Mapping[str, Any], fields: Mapping[str, Any], where: str) -> Entry:
        result = _require(record, "toolUseResult", where)
        answers = _require(result, "answers", where)
        return self._entry(
            record,
            USER_ANSWER,
            "\n".join(str(answer) for answer in answers.values()),
            where,
            context="\n".join(str(question) for question in answers),
            **fields,
        )

    # --- assistant records ---------------------------------------------------------

    def _assistant(self, record: Mapping[str, Any], where: str) -> list[Entry]:
        message = _require(record, "message", where)
        entries = [
            self._entry(
                record,
                MODEL_USAGE,
                "",
                where,
                message_id=_require(message, "id", where),
                model=_require(message, "model", where),
                usage=_require(message, "usage", where),
            )
        ]
        for block in _require(message, "content", where):
            block_type = _require(block, "type", where)
            if block_type == "text":
                entries.append(self._entry(record, ASSISTANT_TEXT, _require(block, "text", where), where))
            elif block_type == "tool_use":
                entries.append(
                    self._entry(
                        record,
                        TOOL_CALL,
                        json.dumps(_require(block, "input", where), ensure_ascii=False),
                        where,
                        tool_name=_require(block, "name", where),
                        tool_input=block["input"],
                    )
                )
            elif block_type != "thinking":
                raise TranscriptFormatError(f"{where}: unknown assistant content block {block_type!r}")
        return entries

    # --- attachments ---------------------------------------------------------------

    def _attachment(self, record: Mapping[str, Any], where: str) -> list[Entry]:
        attachment = _require(record, "attachment", where)
        attachment_type = _require(attachment, "type", where)
        handler: Optional[Callable[[Mapping[str, Any], Mapping[str, Any], str], list[Entry]]] = {
            "queued_command": self._queued_command,
            "hook_blocking_error": self._hook_block,
            "hook_non_blocking_error": self._hook_error,
            "hook_cancelled": self._hook_cancelled,
            "hook_success": self._hook_success,
            "hook_system_message": self._hook_message,
            "silent_turn_reminder": self._silent_turn_reminder,
            "task_status": self._task_status,
            "edited_text_file": self._file_notice,
            "file": self._file_notice,
        }.get(attachment_type)
        if handler is not None:
            return handler(record, attachment, where)
        if attachment_type in ATTACHMENTS_IGNORED:
            return []
        raise TranscriptFormatError(f"{where}: unknown attachment type {attachment_type!r}")

    def _queued_command(self, record: Mapping[str, Any], attachment: Mapping[str, Any], where: str) -> list[Entry]:
        prompt = _require(attachment, "prompt", where)
        origin = attachment.get("origin")
        kind = _require(origin, "kind", where) if origin is not None else None
        if kind == "human":
            return self._user_message_entries(record, prompt, USER_QUEUED, where)
        if kind is None:
            if prompt.startswith(_QUEUED_NOTIFICATION_PREFIXES):
                return [self._entry(record, SUBAGENT_REPORT, prompt, where)]
            raise TranscriptFormatError(f"{where}: queued command with no origin and an unknown shape")
        if kind not in KNOWN_ORIGIN_KINDS:
            raise TranscriptFormatError(f"{where}: unknown origin.kind {kind!r} on a queued command")
        return [self._entry(record, self._kind_of_other_origin(kind), prompt, where)]

    def _hook_block(self, record: Mapping[str, Any], attachment: Mapping[str, Any], where: str) -> list[Entry]:
        text = json.dumps(_require(attachment, "blockingError", where), ensure_ascii=False)
        return [self._entry(record, HOOK_BLOCK, text, where, tool_name=str(attachment.get("hookName", "")))]

    def _hook_error(self, record: Mapping[str, Any], attachment: Mapping[str, Any], where: str) -> list[Entry]:
        text = str(_require(attachment, "stderr", where))
        return [self._entry(record, HOOK_ERROR, text, where, tool_name=str(attachment.get("hookName", "")))]

    def _hook_cancelled(self, record: Mapping[str, Any], attachment: Mapping[str, Any], where: str) -> list[Entry]:
        details = {key: attachment.get(key) for key in ("hookName", "command", "timedOut")}
        text = json.dumps(details, ensure_ascii=False)
        return [self._entry(record, HOOK_CANCELLED, text, where, tool_name=str(attachment.get("hookName", "")))]

    def _hook_success(self, record: Mapping[str, Any], attachment: Mapping[str, Any], where: str) -> list[Entry]:
        text = str(attachment.get("content", ""))
        return [self._entry(record, HOOK_OK, text, where, tool_name=str(attachment.get("hookName", "")))]

    def _hook_message(self, record: Mapping[str, Any], attachment: Mapping[str, Any], where: str) -> list[Entry]:
        return [self._entry(record, HOOK_MESSAGE, str(_require(attachment, "content", where)), where)]

    def _silent_turn_reminder(self, record: Mapping[str, Any], attachment: Mapping[str, Any], where: str) -> list[Entry]:
        return [self._entry(record, SYSTEM_TEXT, str(_require(attachment, "text", where)), where)]

    def _task_status(self, record: Mapping[str, Any], attachment: Mapping[str, Any], where: str) -> list[Entry]:
        text = f"task_status {attachment.get('description')} {attachment.get('status')}"
        return [self._entry(record, SYSTEM_TEXT, text, where)]

    def _file_notice(self, record: Mapping[str, Any], attachment: Mapping[str, Any], where: str) -> list[Entry]:
        text = f"{attachment['type']} {_require(attachment, 'filename', where)}"
        return [self._entry(record, SYSTEM_TEXT, text, where)]

    # --- system records ------------------------------------------------------------

    def _system(self, record: Mapping[str, Any], where: str) -> list[Entry]:
        subtype = _require(record, "subtype", where)
        if subtype in SYSTEM_SUBTYPES_READ:
            return [self._entry(record, SYSTEM_TEXT, f"{subtype}: {_require(record, 'content', where)}", where)]
        if subtype == "stop_hook_summary":
            prevented = bool(record.get("preventedContinuation"))
            return [self._entry(record, STOP_HOOK_SUMMARY, "", where, prevented_continuation=prevented)]
        if subtype == "api_error":
            return [self._entry(record, API_ERROR, "", where)]
        if subtype in SYSTEM_SUBTYPES_IGNORED:
            return []
        raise TranscriptFormatError(f"{where}: unknown system subtype {subtype!r}")


def iter_file_entries(
    path: str,
    source: str,
    after: Optional[datetime],
    through: Optional[datetime],
    seen_uuids: set[str],
) -> Iterator[Entry]:
    """Yield the entries of one file in the window ``after < timestamp <= through``.

    Records outside the window are not classified, so a format change in old records
    cannot stop a run that only reads new ones. Bookkeeping records carry no uuid and
    are never classified.
    """
    classifier = _FileClassifier(path, source)
    for line_number, record in iter_records(path):
        if record["type"] not in CONVERSATION_RECORD_TYPES:
            continue
        classifier.note_tool_uses(record)
        timestamp = parse_timestamp(_require(record, "timestamp", f"{path}:{line_number}"))
        if (after is not None and timestamp <= after) or (through is not None and timestamp > through):
            continue
        uuid = _require(record, "uuid", f"{path}:{line_number}")
        if uuid in seen_uuids:
            continue
        seen_uuids.add(uuid)
        yield from classifier.classify(record, line_number)


def iter_session_entries(
    main_path: str,
    subagent_paths: Iterable[str],
    after: Optional[datetime],
    through: Optional[datetime],
) -> Iterator[Entry]:
    """Yield a session's entries: the main file first, then each subagent file.

    Subagent files can repeat records copied from the main conversation, so a uuid
    seen once is not yielded again.
    """
    seen_uuids: set[str] = set()
    yield from iter_file_entries(main_path, "main", after, through, seen_uuids)
    for path in subagent_paths:
        yield from iter_file_entries(path, "subagent", after, through, seen_uuids)
