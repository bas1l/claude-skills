"""Validate what a model returns. Anything malformed raises ``SchemaError``.

A tool-less model can write fake tool calls as plain text while the call still reports
success, so tool-call-shaped text anywhere in the output is rejected first.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

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

# A rule broken at a cost is on record in the item's ledger, and counts neither way: see ledger.py.
DIRECTION_RULE_BROKEN = "rule_broken"
# So is a hook's, tool server's or plugin's own fault, once in a session: see ledger.py.
DIRECTION_MALFUNCTION = "malfunction"
ENTRY_DIRECTIONS = frozenset({STANCE_FOR, STANCE_AGAINST, DIRECTION_RULE_BROKEN, DIRECTION_MALFUNCTION})
KINDS_THAT_ACT = frozenset({"hook", "mcp", "plugin"})
WHO_USER = "user"
WHO_AGENT = "agent"
BASIS_DIRECT = "direct_statement"
BASIS_INFERRED = "inferred"
ENTRY_BASES_OF_USER = frozenset({BASIS_DIRECT, "accepted", "relied_on"})
# The user undid or rejected something in a review. It is their act, but not a statement about
# the item, so it holds no quote and does not count towards lost balance.
BASIS_REVIEW_DECISION = "review_decision"
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
    basis = _enum(values, "basis", ENTRY_BASES_OF_USER | {BASIS_INFERRED, BASIS_REVIEW_DECISION}, where)
    if (who == WHO_USER) != (basis in ENTRY_BASES_OF_USER or basis == BASIS_REVIEW_DECISION):
        raise SchemaError(f"{where}: who {who!r} does not fit basis {basis!r}")
    quote_check = _enum(values, "quote_check", frozenset({QUOTE_VERIFIED, QUOTE_NOT_FOUND, QUOTE_NONE}), where)
    if not isinstance(values["quote"], str):
        raise SchemaError(f"{where}: quote must be text")
    if basis == BASIS_REVIEW_DECISION:
        if values["quote"] or quote_check != QUOTE_NONE:
            raise SchemaError(f"{where}: a review decision holds no quote")
    else:
        if who == WHO_USER and quote_check != QUOTE_VERIFIED:
            raise SchemaError(f"{where}: an entry attributed to the user needs a verified quote")
        if bool(values["quote"]) != (who == WHO_USER):
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


# ---------------------------------------------------------------------------
# Weekly pass: memory changes, proposals and research, as the model returns them.
# ---------------------------------------------------------------------------

ACTION_CREATE = "create"
ACTION_ADD = "add"
ACTION_REPLACE = "replace"
ACTION_REMOVE = "remove"
ACTION_DELETE = "delete"
MEMORY_ACTIONS = frozenset({ACTION_CREATE, ACTION_ADD, ACTION_REPLACE, ACTION_REMOVE, ACTION_DELETE})
DELETING_ACTIONS = frozenset({ACTION_REMOVE, ACTION_DELETE})
ACTION_REVISION = "revision"
ENDORSED_SAID = "said"
ENDORSED_RELIED_ON = "relied_on"
MEMORY_CHANGE_FIELDS = frozenset({
    "action", "memory", "note", "claim", "old_text", "endorsement", "quote", "assistant_statement", "title",
})
FACT_PROPOSAL_FIELDS = frozenset({"memory", "note", "claim", "title"})

PROPOSAL_KINDS = frozenset({"skill", "plugin", "hook", "mcp", "global_rule"})
RESEARCHED_KINDS = frozenset({"skill", "plugin", "mcp"})
KINDS_WITH_EXACT_CHANGE = frozenset({"plugin", "hook", "mcp", "global_rule"})
CHANGE_NEW = "new"
CHANGE_EXISTING = "change"
BASIS_RECURRENCE = "recurrence"
BASIS_COSTLY_ONCE = "costly_once"
BASIS_FAILURE_COST = "failure_cost"
BASIS_STATED_RULE = "stated_rule"
PROPOSAL_BASES = frozenset({BASIS_RECURRENCE, BASIS_COSTLY_ONCE, BASIS_FAILURE_COST, BASIS_STATED_RULE})
PROPOSAL_FIELDS = frozenset({
    "kind", "change_type", "title", "what", "why", "target", "basis", "notes", "failure", "procedure",
    "exact_change", "draft", "generic_description",
})

VERDICT_SUPPORTS = "supports"
VERDICT_NOT_SUPPORTED = "does_not_support"
VERDICT_ONE_MOMENT = "one_moment_order"
CLAIM_VERDICTS = frozenset({VERDICT_SUPPORTS, VERDICT_NOT_SUPPORTED, VERDICT_ONE_MOMENT})
CLAIM_VERDICT_FIELDS = frozenset({"id", "verdict", "reason"})

RECOMMENDATIONS = frozenset({"adopt", "adapt", "build"})
RESEARCH_FIELDS = frozenset({
    "search_worked", "official_features", "existing_tools", "conventions", "sources", "recommendation",
    "recommendation_reason",
})
RESEARCH_TOOL_FIELDS = frozenset({"name", "url", "maintenance_evidence", "can_execute"})
RESEARCH_SOURCE_FIELDS = frozenset({"url", "title", "used_for"})

WEEKLY_REPORT_SCHEMA_VERSION = 1
OUTCOME_APPLIED = "applied"
OUTCOME_WOULD_APPLY = "would_apply"
WEEKLY_CHANGE_OUTCOMES = frozenset({OUTCOME_APPLIED, OUTCOME_WOULD_APPLY})
WEEKLY_REPORT_FIELDS = frozenset({
    "schema_version", "week", "run_id", "generated_at", "status", "stop_reason", "apply_enabled", "coverage",
    "memory_changes", "rejected", "proposals", "held", "failures_ranked", "before_after", "usage",
})
WEEKLY_CHANGE_FIELDS = frozenset({
    "id", "project_folder", "memory", "action", "claim", "old_text", "endorsement", "quote", "assistant_statement",
    "session", "source", "new_evidence", "outcome", "commit", "before", "after",
})
WEEKLY_REJECTED_FIELDS = frozenset({"subject", "project_folder", "reason", "detail", "claim", "quote", "source"})
WEEKLY_PROPOSAL_FIELDS = frozenset({
    "id", "kind", "change_type", "title", "what", "why", "target", "basis", "evidence", "exact_change", "draft_path",
    "research", "status", "project_folder",
})


@dataclass(frozen=True)
class MemoryChange:
    action: str
    memory: str
    note: str
    claim: str
    old_text: str
    endorsement: str
    quote: str
    assistant_statement: str
    title: str


@dataclass(frozen=True)
class FactProposal:
    memory: str
    note: str
    claim: str
    title: str


@dataclass(frozen=True)
class MemoryReply:
    changes: tuple[MemoryChange, ...]
    fact_proposals: tuple[FactProposal, ...]


@dataclass(frozen=True)
class Proposal:
    kind: str
    change_type: str
    title: str
    what: str
    why: str
    target: str
    basis: str
    notes: tuple[str, ...]
    failure: str
    procedure: str
    exact_change: str
    draft: str
    generic_description: str


def _exact_fields(values: Any, wanted: frozenset[str], where: str) -> None:
    if not isinstance(values, dict):
        raise SchemaError(f"{where}: must be an object")
    if set(values) != wanted:
        raise SchemaError(f"{where}: missing {sorted(wanted - set(values))}, unknown {sorted(set(values) - wanted)}")


def _string(values: Mapping[str, Any], key: str, where: str) -> str:
    value = values[key]
    if not isinstance(value, str):
        raise SchemaError(f"{where}: {key} must be a string")
    return value


def _list_of(document: Mapping[str, Any], key: str) -> list[Any]:
    if not isinstance(document[key], list):
        raise SchemaError(f"{key!r} must be a list")
    return document[key]


def _single_json_object(raw: str, keys: frozenset[str]) -> dict[str, Any]:
    reject_tool_call_text(raw)
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SchemaError(f"output is not a single JSON document: {error}") from error
    if not isinstance(document, dict) or set(document) != keys:
        raise SchemaError(f"output must be an object with exactly the keys {sorted(keys)}")
    return document


def validate_memory_change(values: Any, where: str) -> MemoryChange:
    """Shape only. Whether the evidence holds is the quote gate's question."""
    _exact_fields(values, MEMORY_CHANGE_FIELDS, where)
    action = _enum(values, "action", MEMORY_ACTIONS, where)
    endorsement = _enum(values, "endorsement", ENDORSEMENTS_WITH_QUOTE, where)
    old_text = _string(values, "old_text", where)
    if action in (ACTION_REPLACE, ACTION_REMOVE, ACTION_DELETE) and not old_text.strip():
        raise SchemaError(f"{where}: action {action!r} needs old_text")
    if action in (ACTION_CREATE, ACTION_ADD) and old_text:
        raise SchemaError(f"{where}: action {action!r} must have empty old_text")
    statement = _string(values, "assistant_statement", where)
    if endorsement == ENDORSED_SAID and statement:
        raise SchemaError(f"{where}: endorsement 'said' must have an empty assistant_statement")
    if endorsement != ENDORSED_SAID and not statement.strip():
        raise SchemaError(f"{where}: endorsement {endorsement!r} needs assistant_statement")
    title = _string(values, "title", where)
    if (action == ACTION_CREATE) != bool(title.strip()):
        raise SchemaError(f"{where}: title is set exactly when creating a memory")
    return MemoryChange(
        action=action,
        memory=_nonempty_string(values, "memory", where),
        note=_nonempty_string(values, "note", where),
        claim=_nonempty_string(values, "claim", where),
        old_text=old_text,
        endorsement=endorsement,
        quote=_nonempty_string(values, "quote", where),
        assistant_statement=statement,
        title=title,
    )


def parse_memory_reply(raw: str) -> MemoryReply:
    """Exactly ``{"changes": [...], "fact_proposals": [...]}`` and nothing else."""
    document = _single_json_object(raw, frozenset({"changes", "fact_proposals"}))
    changes = tuple(validate_memory_change(item, f"change {i}") for i, item in enumerate(_list_of(document, "changes")))
    facts = []
    for index, item in enumerate(_list_of(document, "fact_proposals")):
        where = f"fact proposal {index}"
        _exact_fields(item, FACT_PROPOSAL_FIELDS, where)
        facts.append(FactProposal(
            _nonempty_string(item, "memory", where), _nonempty_string(item, "note", where), _nonempty_string(item, "claim", where), _nonempty_string(item, "title", where)
        ))
    return MemoryReply(changes, tuple(facts))


@dataclass(frozen=True)
class ClaimVerdict:
    id: str
    verdict: str
    reason: str


def parse_claim_verdicts(raw: str) -> tuple[ClaimVerdict, ...]:
    """Exactly ``{"verdicts": [...]}``. Whether it answers every claim is the gate's question."""
    document = _single_json_object(raw, frozenset({"verdicts"}))
    verdicts = []
    for index, item in enumerate(_list_of(document, "verdicts")):
        where = f"verdict {index}"
        _exact_fields(item, CLAIM_VERDICT_FIELDS, where)
        verdicts.append(ClaimVerdict(
            _nonempty_string(item, "id", where), _enum(item, "verdict", CLAIM_VERDICTS, where), _nonempty_string(item, "reason", where),
        ))
    return tuple(verdicts)


VERDICT_KEPT = "kept"
VERDICT_RAISED = "raised"
VERDICT_LOWERED = "lowered"
VERDICT_REFUSED = "refused"
VERDICT_REVERSED = "reversed"
STANCE_VERDICTS = (VERDICT_KEPT, VERDICT_RAISED, VERDICT_LOWERED, VERDICT_REFUSED, VERDICT_REVERSED)
STANCE_VERDICT_FIELDS = frozenset({"id", "verdict", "stance", "quote_about_item", "rule_broken", "malfunction", "reason"})


@dataclass(frozen=True)
class StanceVerdict:
    id: str
    verdict: str
    stance: str
    quote_about_item: bool
    rule_broken: bool
    malfunction: bool
    reason: str


def _boolean(values: Mapping[str, Any], key: str, where: str) -> bool:
    if not isinstance(values[key], bool):
        raise SchemaError(f"{where}: {key} must be true or false")
    return values[key]


def parse_stance_verdicts(raw: str) -> tuple[StanceVerdict, ...]:
    """Exactly ``{"verdicts": [...]}``. Whether it answers every stance, and whether each verdict fits
    the stance it answers, is the caller's question."""
    document = _single_json_object(raw, frozenset({"verdicts"}))
    verdicts = []
    for index, item in enumerate(_list_of(document, "verdicts")):
        where = f"stance verdict {index}"
        _exact_fields(item, STANCE_VERDICT_FIELDS, where)
        verdicts.append(StanceVerdict(
            _nonempty_string(item, "id", where), _enum(item, "verdict", frozenset(STANCE_VERDICTS), where), _enum(item, "stance", ITEM_STANCES, where),
            _boolean(item, "quote_about_item", where), _boolean(item, "rule_broken", where), _boolean(item, "malfunction", where), _nonempty_string(item, "reason", where),
        ))
    return tuple(verdicts)


def validate_proposal(values: Any, where: str) -> Proposal:
    _exact_fields(values, PROPOSAL_FIELDS, where)
    kind = _enum(values, "kind", PROPOSAL_KINDS, where)
    change_type = _enum(values, "change_type", frozenset({CHANGE_NEW, CHANGE_EXISTING}), where)
    target = _string(values, "target", where)
    if change_type == CHANGE_EXISTING and not target.strip():
        raise SchemaError(f"{where}: a change to an existing item must name it in target")
    notes = values["notes"]
    if not isinstance(notes, list) or not notes or not all(isinstance(note, str) and note for note in notes):
        raise SchemaError(f"{where}: notes must be a non-empty list of note references")
    exact_change = _string(values, "exact_change", where)
    if kind in KINDS_WITH_EXACT_CHANGE and not exact_change.strip():
        raise SchemaError(f"{where}: a {kind} proposal must show the exact command, config or text")
    draft = _string(values, "draft", where)
    if kind == "skill" and not draft.strip():
        raise SchemaError(f"{where}: a skill proposal must hold a draft")
    description = _string(values, "generic_description", where)
    if kind in RESEARCHED_KINDS and change_type == CHANGE_NEW and not description.strip():
        raise SchemaError(f"{where}: a new {kind} needs generic_description for research")
    return Proposal(
        kind=kind,
        change_type=change_type,
        title=_nonempty_string(values, "title", where),
        what=_nonempty_string(values, "what", where),
        why=_nonempty_string(values, "why", where),
        target=target,
        basis=_enum(values, "basis", PROPOSAL_BASES, where),
        notes=tuple(notes),
        failure=_string(values, "failure", where),
        procedure=_string(values, "procedure", where),
        exact_change=exact_change,
        draft=draft,
        generic_description=description,
    )


def parse_proposals(raw: str) -> tuple[Proposal, ...]:
    """Exactly ``{"proposals": [...]}`` and nothing else."""
    document = _single_json_object(raw, frozenset({"proposals"}))
    return tuple(validate_proposal(item, f"proposal {i}") for i, item in enumerate(_list_of(document, "proposals")))


def parse_research(raw: str) -> dict[str, Any]:
    """The research reply as validated data. Comparing it with what was searched is research.py's."""
    document = _single_json_object(raw, RESEARCH_FIELDS)
    if not isinstance(document["search_worked"], bool):
        raise SchemaError("search_worked must be true or false")
    for key in ("official_features", "conventions", "recommendation_reason"):
        _nonempty_string(document, key, "research")
    _enum(document, "recommendation", RECOMMENDATIONS, "research")
    for index, tool in enumerate(_list_of(document, "existing_tools")):
        where = f"research tool {index}"
        _exact_fields(tool, RESEARCH_TOOL_FIELDS, where)
        for key in RESEARCH_TOOL_FIELDS:
            _nonempty_string(tool, key, where)
    for index, source in enumerate(_list_of(document, "sources")):
        where = f"research source {index}"
        _exact_fields(source, RESEARCH_SOURCE_FIELDS, where)
        for key in RESEARCH_SOURCE_FIELDS:
            _nonempty_string(source, key, where)
    return document


def validate_weekly_report(document: Any, where: str) -> None:
    """Raise unless this is a well-formed weekly report. The format is described in weekly.py."""
    _exact_fields(document, WEEKLY_REPORT_FIELDS, where)
    if document["schema_version"] != WEEKLY_REPORT_SCHEMA_VERSION:
        raise SchemaError(f"{where}: schema_version {document['schema_version']!r}")
    if not isinstance(document["apply_enabled"], bool):
        raise SchemaError(f"{where}: apply_enabled must be true or false")
    for index, change in enumerate(document["memory_changes"]):
        _exact_fields(change, WEEKLY_CHANGE_FIELDS, f"{where} change {index}")
        _enum(change, "outcome", WEEKLY_CHANGE_OUTCOMES, f"{where} change {index}")
    for index, rejected in enumerate(document["rejected"]):
        _exact_fields(rejected, WEEKLY_REJECTED_FIELDS, f"{where} rejected {index}")
    for key in ("proposals", "held"):
        for index, proposal in enumerate(document[key]):
            _exact_fields(proposal, WEEKLY_PROPOSAL_FIELDS, f"{where} {key} {index}")


# ---------------------------------------------------------------------------
# Monthly pass: audit replies as the model returns them, and the report.
# ---------------------------------------------------------------------------

KIND_MONTHLY_FINDING = "monthly_finding"
STALE_PATH_GONE = "path_gone"
STALE_STATED_LIMIT = "stated_limit"
STALE_SUPERSEDED = "superseded"
# No ground means "not used lately": staleness has to rest on something a script or a reader can check.
STALE_GROUNDS = frozenset({STALE_PATH_GONE, STALE_STATED_LIMIT, STALE_SUPERSEDED})
LEVEL_TO_GLOBAL = "to_global"
LEVEL_TO_PROJECT = "to_project"
LEVEL_DIRECTIONS = frozenset({LEVEL_TO_GLOBAL, LEVEL_TO_PROJECT})
VERDICT_SAME = "same"
VERDICT_DIFFERENT = "different"
DUPLICATE_VERDICTS = frozenset({VERDICT_SAME, VERDICT_DIFFERENT})
SIDE_FIELDS = frozenset({"file", "line", "quote"})
MONTHLY_REPORT_SCHEMA_VERSION = 1
MONTHLY_REPORT_FIELDS = frozenset({
    "schema_version", "month", "run_id", "generated_at", "status", "stop_reason", "context", "coverage", "counts",
    "findings", "rejected", "already_raised", "duplicate_candidates", "quality", "replacements", "usage",
})


def _validate_sides(values: Any, where: str) -> None:
    if not isinstance(values, list):
        raise SchemaError(f"{where}: sides must be a list")
    for index, side in enumerate(values):
        place = f"{where} side {index}"
        _exact_fields(side, SIDE_FIELDS, place)
        _nonempty_string(side, "file", place)
        _nonempty_string(side, "quote", place)
        if not isinstance(side["line"], int) or isinstance(side["line"], bool) or side["line"] < 1:
            raise SchemaError(f"{place}: line must be a whole number from 1")


def _validate_entries(document: Mapping[str, Any], key: str, wanted: frozenset[str], texts: tuple[str, ...]) -> None:
    for index, entry in enumerate(_list_of(document, key)):
        where = f"{key} {index}"
        _exact_fields(entry, wanted, where)
        for name in texts:
            _nonempty_string(entry, name, where)
        _validate_sides(entry["sides"], where)


def parse_monthly_coherence(raw: str) -> dict[str, Any]:
    """Exactly ``{"contradictions": [...], "stale": [...], "level_moves": [...]}``. Shape only:
    whether the citations hold is the gate's question."""
    document = _single_json_object(raw, frozenset({"contradictions", "stale", "level_moves"}))
    _validate_entries(document, "contradictions", frozenset({"title", "what", "why", "sides"}), ("title", "what", "why"))
    _validate_entries(document, "stale", frozenset({"title", "question", "ground", "why", "sides"}), ("title", "question", "why"))
    for index, entry in enumerate(document["stale"]):
        _enum(entry, "ground", STALE_GROUNDS, f"stale {index}")
        if not entry["question"].rstrip().endswith("?"):
            raise SchemaError(f"stale {index}: staleness must be put as a question")
    _validate_entries(document, "level_moves", frozenset({"title", "what", "why", "direction", "exact_change", "sides"}), ("title", "what", "why"))
    for index, entry in enumerate(document["level_moves"]):
        _enum(entry, "direction", LEVEL_DIRECTIONS, f"level_moves {index}")
        _string(entry, "exact_change", f"level_moves {index}")
    return document


def parse_monthly_duplicates(raw: str) -> list[dict[str, Any]]:
    """Exactly ``{"clusters": [...]}``, one verdict per cluster."""
    document = _single_json_object(raw, frozenset({"clusters"}))
    wanted = frozenset({"cluster", "verdict", "reason", "title", "what", "why", "exact_change", "sides"})
    _validate_entries(document, "clusters", wanted, ("cluster", "reason"))
    for index, entry in enumerate(document["clusters"]):
        where = f"clusters {index}"
        _enum(entry, "verdict", DUPLICATE_VERDICTS, where)
        _string(entry, "exact_change", where)
        if entry["verdict"] == VERDICT_SAME:
            _nonempty_string(entry, "title", where)
            _nonempty_string(entry, "what", where)
            _nonempty_string(entry, "why", where)
    return document["clusters"]


def parse_monthly_quality(raw: str) -> list[dict[str, Any]]:
    """Exactly ``{"suggestions": [{"setting", "suggested", "why"}]}``."""
    document = _single_json_object(raw, frozenset({"suggestions"}))
    for index, entry in enumerate(_list_of(document, "suggestions")):
        where = f"suggestion {index}"
        _exact_fields(entry, frozenset({"setting", "suggested", "why"}), where)
        _nonempty_string(entry, "setting", where)
        _nonempty_string(entry, "why", where)
        if not isinstance(entry["suggested"], (int, float)) or isinstance(entry["suggested"], bool):
            raise SchemaError(f"{where}: suggested must be a number")
    return document["suggestions"]


def parse_monthly_descriptions(raw: str) -> dict[str, str]:
    """Exactly ``{"descriptions": [{"skill", "description"}]}``, as a mapping by skill."""
    document = _single_json_object(raw, frozenset({"descriptions"}))
    found: dict[str, str] = {}
    for index, entry in enumerate(_list_of(document, "descriptions")):
        where = f"description {index}"
        _exact_fields(entry, frozenset({"skill", "description"}), where)
        found[_nonempty_string(entry, "skill", where)] = _nonempty_string(entry, "description", where)
    return found


def validate_monthly_report(document: Any, where: str) -> None:
    """Raise unless this is a well-formed monthly report. The format is described in monthly.py."""
    _exact_fields(document, MONTHLY_REPORT_FIELDS, where)
    if document["schema_version"] != MONTHLY_REPORT_SCHEMA_VERSION:
        raise SchemaError(f"{where}: schema_version {document['schema_version']!r}")
    for index, finding in enumerate(document["findings"]):
        _exact_fields(finding, WEEKLY_PROPOSAL_FIELDS, f"{where} finding {index}")
        _enum(finding, "kind", frozenset({KIND_MONTHLY_FINDING}), f"{where} finding {index}")


# ---------------------------------------------------------------------------
# The review: review.json, the source of truth of a review session.
# ---------------------------------------------------------------------------

REVIEW_SCHEMA_VERSION = 1
REVIEW_FIELDS = frozenset({
    "schema_version", "review_id", "week", "run_id", "built_at", "report_status", "stop_reason", "apply_enabled",
    "weeks_overdue", "last_action_at", "failures", "coverage", "usage", "items", "held", "rejected",
    "failures_ranked", "before_after",
})
REVIEW_ITEM_FIELDS = frozenset({
    "number", "key", "section", "origin", "week", "carried", "title", "allowed", "decision", "skipped_at", "ledger", "record",
})
SECTION_MEMORY = "memory"
SECTION_PROPOSAL = "proposal"
REVIEW_SECTIONS = frozenset({SECTION_MEMORY, SECTION_PROPOSAL})
ORIGIN_WEEKLY = "weekly"
ORIGIN_MONTHLY = "monthly"
REVIEW_ORIGINS = frozenset({ORIGIN_WEEKLY, ORIGIN_MONTHLY})
ACTION_UNDO = "undo"
ACTION_KEEP = "keep"
ACTION_SKIP = "skip"
ACTION_WHY = "why"
ACTION_REJECT = "reject"
ACTION_APPROVE = "approve"
REVIEW_ACTIONS = frozenset({ACTION_UNDO, ACTION_KEEP, ACTION_SKIP, ACTION_WHY, ACTION_REJECT, ACTION_APPROVE})
OUTCOME_UNDONE = "undone"
OUTCOME_KEPT = "kept"
OUTCOME_REJECTED = "rejected"
OUTCOME_APPROVED = "approved"
REVIEW_OUTCOMES = frozenset({OUTCOME_UNDONE, OUTCOME_KEPT, OUTCOME_REJECTED, OUTCOME_APPROVED})


def validate_review(document: Any, where: str) -> None:
    """Raise unless this is a well-formed review. Numbers must run 1 to n, so that a number
    Basil types can only mean one item."""
    _exact_fields(document, REVIEW_FIELDS, where)
    if document["schema_version"] != REVIEW_SCHEMA_VERSION:
        raise SchemaError(f"{where}: schema_version {document['schema_version']!r}")
    if not isinstance(document["apply_enabled"], bool):
        raise SchemaError(f"{where}: apply_enabled must be true or false")
    if not isinstance(document["weeks_overdue"], int) or document["weeks_overdue"] < 0:
        raise SchemaError(f"{where}: weeks_overdue must be a whole number, 0 or more")
    items = document["items"]
    if [item.get("number") for item in items] != list(range(1, len(items) + 1)):
        raise SchemaError(f"{where}: item numbers must run from 1 without a gap")
    keys = [item.get("key") for item in items]
    if len(set(keys)) != len(keys):
        raise SchemaError(f"{where}: two items hold the same key")
    for item in items:
        place = f"{where} item {item.get('number')}"
        _exact_fields(item, REVIEW_ITEM_FIELDS, place)
        _enum(item, "section", REVIEW_SECTIONS, place)
        _enum(item, "origin", REVIEW_ORIGINS, place)
        if not set(item["allowed"]) <= REVIEW_ACTIONS:
            raise SchemaError(f"{place}: unknown action in {item['allowed']}")
        decision = item["decision"]
        if decision is not None:
            _exact_fields(decision, frozenset({"outcome", "at", "detail"}), f"{place} decision")
            _enum(decision, "outcome", REVIEW_OUTCOMES, f"{place} decision")


# ---------------------------------------------------------------------------
# The sort: reports/YYYY-Www/sort.json, one rating per item key. Numbers are not in it, so that
# sorting cannot move them. See review_sort.py.
# ---------------------------------------------------------------------------

SORT_SCHEMA_VERSION = 1
IMPORTANCE_IMPORTANT = "important"
IMPORTANCE_LOWER = "lower"
SORT_IMPORTANCES = frozenset({IMPORTANCE_IMPORTANT, IMPORTANCE_LOWER})
CLARITY_CLEAR = "clear"
CLARITY_UNCLEAR = "unclear"
SORT_CLARITIES = frozenset({CLARITY_CLEAR, CLARITY_UNCLEAR})
SORT_OPTIONS_MIN = 2
SORT_OPTIONS_MAX = 4
SORT_RATING_FIELDS = frozenset({"id", "importance", "clarity", "reason", "recommended", "options"})
SORT_DOCUMENT_FIELDS = frozenset({"schema_version", "week", "sorted_at", "run_id", "model", "cost_usd", "items"})
SORT_ENTRY_RATED = "rated"
SORT_ENTRY_UNRATED = "unrated"
SORT_ENTRY_STATUSES = frozenset({SORT_ENTRY_RATED, SORT_ENTRY_UNRATED})
SORT_ENTRY_FIELDS = frozenset({"status", "digest", "importance", "clarity", "reason", "recommended", "options", "unrated_reason", "citations"})
CITATION_MATCHES = "matches"
CITATION_MOVED = "moved"
CITATION_CHANGED = "changed"
CITATION_REDACTED = "redacted"
CITATION_FILE_GONE = "file_gone"
CITATION_UNREADABLE = "unreadable"
CITATION_NO_QUOTE = "no_quote"
CITATION_STATUSES = frozenset({
    CITATION_MATCHES, CITATION_MOVED, CITATION_CHANGED, CITATION_REDACTED, CITATION_FILE_GONE, CITATION_UNREADABLE, CITATION_NO_QUOTE,
})
CITATION_FIELDS = frozenset({"file", "line", "status", "found_line"})


def parse_sort_reply(raw: str) -> list[Any]:
    """Exactly ``{"ratings": [...]}``. Each rating is checked alone by ``validate_sort_rating``, so
    that one bad rating leaves only its own item unsorted."""
    return _list_of(_single_json_object(raw, frozenset({"ratings"})), "ratings")


def _rated_fields(values: Mapping[str, Any], allowed: Sequence[str], reason_max: int, option_max: int, where: str) -> None:
    """What makes a rating usable: the same for a model's reply and for what is stored of it."""
    _enum(values, "importance", SORT_IMPORTANCES, where)
    clarity = _enum(values, "clarity", SORT_CLARITIES, where)
    reason = _nonempty_string(values, "reason", where)
    if len(reason) > reason_max or "\n" in reason.strip():
        raise SchemaError(f"{where}: reason must be one line of at most {reason_max} characters")
    if values["recommended"] not in allowed:
        raise SchemaError(f"{where}: recommended {values['recommended']!r} is not among {list(allowed)}")
    options = values["options"]
    if not isinstance(options, list) or not all(isinstance(option, str) and option.strip() for option in options):
        raise SchemaError(f"{where}: options must be a list of non-empty strings")
    if any(len(option) > option_max or "\n" in option.strip() for option in options):
        raise SchemaError(f"{where}: an option must be one line of at most {option_max} characters")
    if clarity == CLARITY_UNCLEAR and not SORT_OPTIONS_MIN <= len(options) <= SORT_OPTIONS_MAX:
        raise SchemaError(f"{where}: an unclear item needs {SORT_OPTIONS_MIN} to {SORT_OPTIONS_MAX} options, not {len(options)}")
    if clarity == CLARITY_CLEAR and options:
        raise SchemaError(f"{where}: a clear item has no options")


def validate_sort_rating(values: Any, allowed: Sequence[str], reason_max: int, option_max: int, where: str) -> None:
    """One rating, against the actions its item can take."""
    _exact_fields(values, SORT_RATING_FIELDS, where)
    _rated_fields(values, allowed, reason_max, option_max, where)


def validate_sort_document(document: Any, where: str) -> None:
    """Raise unless this is a well-formed sort.json. A rated entry holds every rating field and an
    unrated one none, so that nothing can read as rated without having been rated."""
    _exact_fields(document, SORT_DOCUMENT_FIELDS, where)
    if document["schema_version"] != SORT_SCHEMA_VERSION:
        raise SchemaError(f"{where}: schema_version {document['schema_version']!r}")
    if not isinstance(document["items"], dict):
        raise SchemaError(f"{where}: items must be an object")
    for key, entry in document["items"].items():
        place = f"{where} item {key}"
        _exact_fields(entry, SORT_ENTRY_FIELDS, place)
        status = _enum(entry, "status", SORT_ENTRY_STATUSES, place)
        if not isinstance(entry["citations"], list):
            raise SchemaError(f"{place}: citations must be a list")
        for citation in entry["citations"]:
            _exact_fields(citation, CITATION_FIELDS, f"{place} citation")
            _enum(citation, "status", CITATION_STATUSES, f"{place} citation")
        if status == SORT_ENTRY_UNRATED:
            _nonempty_string(entry, "unrated_reason", place)
            if any(entry[name] for name in ("importance", "clarity", "reason", "recommended", "options")):
                raise SchemaError(f"{place}: an unrated entry holds a rating")
        else:
            if entry["unrated_reason"]:
                raise SchemaError(f"{place}: a rated entry holds a reason it is unrated")
            _enum(entry, "importance", SORT_IMPORTANCES, place)
            _enum(entry, "clarity", SORT_CLARITIES, place)
            _nonempty_string(entry, "reason", place)
            _nonempty_string(entry, "recommended", place)
            if not isinstance(entry["options"], list) or not all(isinstance(option, str) for option in entry["options"]):
                raise SchemaError(f"{place}: options must be a list of strings")
