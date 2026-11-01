"""Validate what a model returns. Anything malformed raises ``SchemaError``.

A tool-less model can write fake tool calls as plain text while the call still reports
success, so tool-call-shaped text anywhere in the output is rejected first.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping

NOTES_SCHEMA_VERSION = 1

NOTE_TYPES = frozenset({"failure", "fact", "conflict", "procedure", "preference", "one_moment_order"})
ENDORSEMENTS_WITH_QUOTE = frozenset({"said", "accepted", "relied_on"})
ENDORSEMENTS = ENDORSEMENTS_WITH_QUOTE | {"none", "not_applicable"}
ORIGINS = frozenset({"user", "assistant", "subagent", "teammate", "hook", "tool_result", "paste", "web"})
ROUTES = frozenset({"none", "memory", "skill", "hook", "mcp", "global_rule", "script_count"})
CONFIDENCES = frozenset({"high", "medium", "low"})
NOTE_FIELDS = frozenset({
    "type", "what", "evidence", "memory_candidate", "endorsement", "endorsement_quote",
    "origin_of_point", "route", "confidence",
})

_TOOL_CALL_SHAPE_RE = re.compile(
    r"</?\s*(?:[a-z_]+:)?(?:invoke|function_calls|parameter\s+name|tool_use|tool_result)\b"
    r'|[\\]?"type[\\]?"\s*:\s*[\\]?"tool_use[\\]?"',
    re.I,
)


class SchemaError(ValueError):
    """Model output does not meet its schema."""


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

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


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
