"""Validate what a model returns. Anything malformed raises ``SchemaError``.

A tool-less model can write fake tool calls as plain text while the call still reports
success, so tool-call-shaped text anywhere in the output is rejected first.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Mapping

# Version 1 notes have no ``items``, and stay readable as they are. Version 2 notes must have it.
NOTES_SCHEMA_VERSION = 2
NOTES_SCHEMA_WITHOUT_ITEMS = 1
LEDGER_SCHEMA_VERSION = 1

NOTE_TYPES = frozenset({"failure", "fact", "conflict", "procedure", "preference", "one_moment_order"})
ENDORSEMENTS_WITH_QUOTE = frozenset({"said", "accepted", "relied_on"})
ENDORSEMENTS = ENDORSEMENTS_WITH_QUOTE | {"none", "not_applicable"}
ORIGINS = frozenset({"user", "assistant", "subagent", "teammate", "hook", "tool_result", "paste", "web"})
ROUTES = frozenset({"none", "memory", "skill", "hook", "mcp", "global_rule", "script_count"})
CONFIDENCES = frozenset({"high", "medium", "low"})
NOTE_FIELDS = frozenset({
    "type", "what", "evidence", "memory_candidate", "endorsement", "endorsement_quote",
    "origin_of_point", "route", "confidence", "items",
})

QUOTE_VERIFIED = "verified"
QUOTE_NOT_FOUND = "not_found"
QUOTE_NONE = "no_quote"

ITEM_KINDS = frozenset({"memory", "skill", "hook", "mcp", "plugin"})
STANCE_FOR = "for"
STANCE_AGAINST = "against"
STANCE_NO_BEARING = "no_bearing"
ITEM_STANCES = frozenset({STANCE_FOR, STANCE_AGAINST, STANCE_NO_BEARING})
NOTE_ITEM_FIELDS = frozenset({"kind", "name", "stance"})

ENTRY_DIRECTIONS = frozenset({STANCE_FOR, STANCE_AGAINST})
WHO_USER = "user"
WHO_AGENT = "agent"
BASIS_DIRECT = "direct_statement"
BASIS_INFERRED = "inferred"
ENTRY_BASES_OF_USER = frozenset({BASIS_DIRECT, "accepted", "relied_on"})
ENTRY_FIELDS = frozenset({
    "id", "date", "session", "project_folder", "direction", "who", "basis", "what", "quote", "quote_check",
    "origin_of_point", "source",
})

FOUNDING_UNVERIFIED = "unverified"
FOUNDING_VERIFIED = "verified"
FOUNDING_NO_REASON = "no_stated_reason"
FOUNDING_SOURCES = frozenset({"why_line", "description", "discussion"})
LIMIT_STATED = "stated_in_item"
LIMIT_NOT_STATED = "not_stated"
ORIGIN_TRACED = "traced"
ORIGIN_UNTRACED = "untraced"
ORIGIN_NOT_APPLICABLE = "not_applicable"
LEDGER_FIELDS = frozenset({"schema_version", "identity", "created", "founding", "would_be_wrong", "origin", "entries"})

_TOOL_CALL_SHAPE_RE = re.compile(
    r"</?\s*(?:[a-z_]+:)?(?:invoke|function_calls|parameter\s+name|tool_use|tool_result)\b"
    r'|[\\]?"type[\\]?"\s*:\s*[\\]?"tool_use[\\]?"',
    re.I,
)


class SchemaError(ValueError):
    """Model output does not meet its schema."""


@dataclass(frozen=True)
class NoteItem:
    """A saved item a note speaks about, named as the session named it."""

    kind: str
    name: str
    stance: str


@dataclass(frozen=True)
class Note:
    type: str
    what: str
    evidence: str
    memory_candidate: bool
    endorsement: str
    endorsement_quote: str
    origin_of_point: str
    route: str
    confidence: str
    items: tuple[NoteItem, ...]

    def to_json(self) -> dict[str, Any]:
        return {**asdict(self), "items": [asdict(item) for item in self.items]}


def reject_tool_call_text(raw: str) -> None:
    """Raise if the text holds anything shaped like a tool call."""
    match = _TOOL_CALL_SHAPE_RE.search(raw)
    if match:
        raise SchemaError(f"output holds tool-call-shaped text at offset {match.start()}: {match.group(0)!r}")


def _nonempty_string(values: Mapping[str, Any], key: str, where: str) -> str:
    value = values[key]
    if not isinstance(value, str) or not value.strip():
        raise SchemaError(f"{where}: {key} must be a non-empty string")
    return value


def _enum(values: Mapping[str, Any], key: str, allowed: frozenset[str], where: str) -> str:
    value = values[key]
    if value not in allowed:
        raise SchemaError(f"{where}: {key} {value!r} is not one of {sorted(allowed)}")
    return value


def validate_note_item(values: Any, where: str) -> NoteItem:
    if not isinstance(values, dict):
        raise SchemaError(f"{where}: an item must be an object")
    if set(values) != NOTE_ITEM_FIELDS:
        raise SchemaError(
            f"{where}: missing {sorted(NOTE_ITEM_FIELDS - set(values))}, unknown {sorted(set(values) - NOTE_ITEM_FIELDS)}"
        )
    return NoteItem(
        kind=_enum(values, "kind", ITEM_KINDS, where),
        name=_nonempty_string(values, "name", where),
        stance=_enum(values, "stance", ITEM_STANCES, where),
    )


def validate_note(values: Any, where: str) -> Note:
    if not isinstance(values, dict):
        raise SchemaError(f"{where}: a note must be an object")
    if set(values) != NOTE_FIELDS:
        raise SchemaError(
            f"{where}: missing {sorted(NOTE_FIELDS - set(values))}, unknown {sorted(set(values) - NOTE_FIELDS)}"
        )
    if not isinstance(values["memory_candidate"], bool):
        raise SchemaError(f"{where}: memory_candidate must be true or false")
    endorsement = _enum(values, "endorsement", ENDORSEMENTS, where)
    quote = values["endorsement_quote"]
    if not isinstance(quote, str):
        raise SchemaError(f"{where}: endorsement_quote must be a string")
    if endorsement in ENDORSEMENTS_WITH_QUOTE and not quote.strip():
        raise SchemaError(f"{where}: endorsement {endorsement!r} needs a quote")
    if endorsement not in ENDORSEMENTS_WITH_QUOTE and quote:
        raise SchemaError(f"{where}: endorsement {endorsement!r} must have an empty quote")
    if not isinstance(values["items"], list):
        raise SchemaError(f"{where}: items must be a list")
    return Note(
        type=_enum(values, "type", NOTE_TYPES, where),
        what=_nonempty_string(values, "what", where),
        evidence=_nonempty_string(values, "evidence", where),
        memory_candidate=values["memory_candidate"],
        endorsement=endorsement,
        endorsement_quote=quote,
        origin_of_point=_enum(values, "origin_of_point", ORIGINS, where),
        route=_enum(values, "route", ROUTES, where),
        confidence=_enum(values, "confidence", CONFIDENCES, where),
        items=tuple(validate_note_item(item, f"{where} item {i}") for i, item in enumerate(values["items"])),
    )


def parse_notes(raw: str) -> list[Note]:
    """Parse a model reply: exactly one JSON object ``{"notes": [...]}`` and nothing else."""
    reject_tool_call_text(raw)
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SchemaError(f"output is not a single JSON document: {error}") from error
    if not isinstance(document, dict) or set(document) != {"notes"}:
        raise SchemaError('output must be an object with the single key "notes"')
    if not isinstance(document["notes"], list):
        raise SchemaError('"notes" must be a list')
    return [validate_note(values, f"note {index}") for index, values in enumerate(document["notes"])]


def _aware_timestamp(value: Any, where: str) -> None:
    if not isinstance(value, str):
        raise SchemaError(f"{where}: must be a timestamp string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise SchemaError(f"{where}: {error}") from error
    if parsed.tzinfo is None:
        raise SchemaError(f"{where}: {value!r} has no UTC offset")


def validate_ledger_entry(values: Any, where: str) -> None:
    """Raise unless this is a well-formed ledger entry."""
    if not isinstance(values, dict) or set(values) != ENTRY_FIELDS:
        raise SchemaError(f"{where}: an entry must hold exactly {sorted(ENTRY_FIELDS)}")
    for key in ("id", "session", "project_folder", "what"):
        _nonempty_string(values, key, where)
    _aware_timestamp(values["date"], f"{where}: date")
    _enum(values, "direction", ENTRY_DIRECTIONS, where)
    who = _enum(values, "who", frozenset({WHO_USER, WHO_AGENT}), where)
    basis = _enum(values, "basis", ENTRY_BASES_OF_USER | {BASIS_INFERRED}, where)
    if (who == WHO_USER) != (basis in ENTRY_BASES_OF_USER):
        raise SchemaError(f"{where}: who {who!r} does not fit basis {basis!r}")
    quote_check = _enum(values, "quote_check", frozenset({QUOTE_VERIFIED, QUOTE_NOT_FOUND, QUOTE_NONE}), where)
    if who == WHO_USER and quote_check != QUOTE_VERIFIED:
        raise SchemaError(f"{where}: an entry attributed to the user needs a verified quote")
    if not isinstance(values["quote"], str) or bool(values["quote"]) != (who == WHO_USER):
        raise SchemaError(f"{where}: quote must be set exactly when the entry is attributed to the user")
    _enum(values, "origin_of_point", ORIGINS, where)
    source = values["source"]
    if not isinstance(source, dict) or set(source) != {"notes", "note_index"}:
        raise SchemaError(f"{where}: source must hold notes and note_index")


def _validate_founding(founding: Any, where: str) -> None:
    if not isinstance(founding, dict) or set(founding) != {"reason", "status", "source"}:
        raise SchemaError(f"{where}: founding must hold reason, status and source")
    status = _enum(founding, "status", frozenset({FOUNDING_UNVERIFIED, FOUNDING_VERIFIED, FOUNDING_NO_REASON}), where)
    if status == FOUNDING_NO_REASON:
        if founding["reason"] is not None or founding["source"] is not None:
            raise SchemaError(f"{where}: an item with no stated reason cannot carry one")
        return
    _nonempty_string(founding, "reason", where)
    _enum(founding, "source", FOUNDING_SOURCES, where)


def _validate_limit(limit: Any, where: str) -> None:
    if not isinstance(limit, dict) or set(limit) != {"status", "text"}:
        raise SchemaError(f"{where}: would_be_wrong must hold status and text")
    status = _enum(limit, "status", frozenset({LIMIT_STATED, LIMIT_NOT_STATED}), where)
    if status == LIMIT_STATED:
        _nonempty_string(limit, "text", where)
    elif limit["text"] is not None:
        raise SchemaError(f"{where}: would_be_wrong is not stated, so it cannot carry text")


def _validate_origin(origin: Any, where: str) -> None:
    fields = {"status", "session", "project_folder", "at", "tool", "creating_call_found"}
    if not isinstance(origin, dict) or set(origin) != fields:
        raise SchemaError(f"{where}: origin must hold exactly {sorted(fields)}")
    status = _enum(origin, "status", frozenset({ORIGIN_TRACED, ORIGIN_UNTRACED, ORIGIN_NOT_APPLICABLE}), where)
    if status == ORIGIN_TRACED:
        for key in ("session", "project_folder", "tool"):
            _nonempty_string(origin, key, where)
        _aware_timestamp(origin["at"], f"{where}: origin at")
        if not isinstance(origin["creating_call_found"], bool):
            raise SchemaError(f"{where}: creating_call_found must be true or false")
    elif any(origin[key] is not None for key in fields - {"status"}):
        raise SchemaError(f"{where}: origin {status!r} cannot name a session")


def validate_ledger(document: Any, where: str) -> None:
    """Raise unless this is a well-formed ledger document."""
    if not isinstance(document, dict) or set(document) != LEDGER_FIELDS:
        raise SchemaError(f"{where}: a ledger must hold exactly {sorted(LEDGER_FIELDS)}")
    if document["schema_version"] != LEDGER_SCHEMA_VERSION:
        raise SchemaError(f"{where}: schema_version {document['schema_version']!r}")
    identity = document["identity"]
    if not isinstance(identity, dict) or set(identity) != {"scope", "kind", "name"}:
        raise SchemaError(f"{where}: identity must hold scope, kind and name")
    _nonempty_string(identity, "scope", where)
    _nonempty_string(identity, "name", where)
    _enum(identity, "kind", ITEM_KINDS, where)
    _nonempty_string(document, "created", where)
    _validate_founding(document["founding"], where)
    _validate_limit(document["would_be_wrong"], where)
    _validate_origin(document["origin"], where)
    if not isinstance(document["entries"], list):
        raise SchemaError(f"{where}: entries must be a list")
    for index, entry in enumerate(document["entries"]):
        validate_ledger_entry(entry, f"{where} entry {index}")
