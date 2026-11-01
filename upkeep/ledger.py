"""Reason ledgers: why each item exists, and what has been said for and against it since.

One JSON file per item, under the data folder:

    ledgers/global/<kind>/<name>.json              skills, hooks, tool servers, plugins
    ledgers/projects/<folder>/memory/<name>.json   memories, scoped by their project folder
    ledgers/revision-flags.json                    items that lost balance, rewritten each run
    ledgers/unmapped-mentions.json                 note mentions that could not become entries
    ledgers/review-decisions.json                  changes and proposals the user undid or rejected

What this module holds to:

    The founding reason is written once and never expires: lost balance reads only entries.
    An entry comes from a note that names an item. Nothing here adds one for an item going
    unused, and a note saying so has the stance ``no_bearing``, which makes no entry.
    A flag proposes revision. It never edits or deletes a ledger or the item.

Lost balance, with numbers from config (see ``lost_balance``). The source states the rule and
this module fixes three points it leaves open:

    Only a note with endorsement ``said`` and a quote found verbatim is the user's direct statement.
    ``accepted`` and ``relied_on`` are attributed to the user but count as inferred, because the
    wording is the agent's.
    The user's later direct statement outweighs what came before it: a direct "for" clears an
    earlier direct "against", and inferred "against" entries older than it stop counting.
    An inferred "for" never clears a direct "against".
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterator, Mapping, Optional, Sequence
from urllib.parse import quote

import schemas
from config import LedgerConfig

SCOPE_GLOBAL = "global"
SCOPE_PROJECT_PREFIX = "project:"
KIND_MEMORY = "memory"
KIND_PLUGIN = "plugin"

OUTCOME_CREATED = "created"
OUTCOME_ORIGIN_FILLED = "origin_filled"
OUTCOME_UNCHANGED = "unchanged"

FLAGS_FILE = "revision-flags.json"
UNMAPPED_FILE = "unmapped-mentions.json"
DECISIONS_FILE = "review-decisions.json"
DECISIONS_SCHEMA_VERSION = 1
DECISION_UNDONE = "undone"
DECISION_REJECTED = "rejected"
REVIEW_SOURCE_PREFIX = "review/"
DECISION_FIELDS = frozenset({"id", "decided_at", "decision", "scope", "kind", "name", "action", "claim", "week"})
REPORTS_SCHEMA_VERSION = 1

REASON_DIRECT = "direct_statement_against"
REASON_INFERRED = "inferred_against_without_support"
UNMAPPED_NO_SUCH_ITEM = "no_such_item"
UNMAPPED_AMBIGUOUS = "ambiguous_name"

_MARKDOWN_SUFFIX = ".md"
# Spaces and these marks are safe in a Windows file name; everything else is percent-encoded.
_SAFE_NAME_CHARS = " -_.@+()"


class LedgerError(ValueError):
    """A ledger is not what it should be, or a write would break a ledger rule."""


@dataclass(frozen=True)
class ItemId:
    """The stable identity of an item."""

    scope: str
    kind: str
    name: str

    def to_json(self) -> dict[str, str]:
        return {"scope": self.scope, "kind": self.kind, "name": self.name}


def project_scope(project_folder: str) -> str:
    return f"{SCOPE_PROJECT_PREFIX}{project_folder}"


def ledgers_dir_of(data_dir: str) -> str:
    return os.path.join(data_dir, "ledgers")


def _encoded(name: str) -> str:
    return quote(name, safe=_SAFE_NAME_CHARS)


def ledger_path(ledgers_dir: str, item: ItemId) -> str:
    file_name = f"{_encoded(item.name)}.json"
    if item.scope == SCOPE_GLOBAL:
        return os.path.join(ledgers_dir, "global", item.kind, file_name)
    if not item.scope.startswith(SCOPE_PROJECT_PREFIX):
        raise LedgerError(f"unknown scope {item.scope!r}")
    folder = item.scope[len(SCOPE_PROJECT_PREFIX):]
    return os.path.join(ledgers_dir, "projects", _encoded(folder), item.kind, file_name)


def _write_json_atomic(path: str, document: Mapping[str, Any]) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=directory, prefix=".part-", suffix=".tmp")
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    os.replace(temporary, path)


def _read_ledger_file(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    schemas.validate_ledger(document, path)
    return document


def load_ledger(ledgers_dir: str, item: ItemId) -> dict[str, Any]:
    """Read and validate an item's ledger. A file holding another identity raises."""
    path = ledger_path(ledgers_dir, item)
    document = _read_ledger_file(path)
    if document["identity"] != item.to_json():
        raise LedgerError(f"{path}: holds identity {document['identity']}, expected {item.to_json()}")
    return document


def item_exists(ledgers_dir: str, item: ItemId) -> bool:
    return os.path.isfile(ledger_path(ledgers_dir, item))


def ensure_ledger(
    ledgers_dir: str,
    item: ItemId,
    founding: Mapping[str, Any],
    would_be_wrong: Mapping[str, Any],
    origin: Mapping[str, Any],
    created: str,
) -> str:
    """Create a ledger once. On an existing one, the only change allowed is filling in an
    untraced origin, so the founding reason and the entries are never rewritten."""
    path = ledger_path(ledgers_dir, item)
    if not os.path.exists(path):
        document = {
            "schema_version": schemas.LEDGER_SCHEMA_VERSION,
            "identity": item.to_json(),
            "created": created,
            "founding": dict(founding),
            "would_be_wrong": dict(would_be_wrong),
            "origin": dict(origin),
            "entries": [],
        }
        schemas.validate_ledger(document, path)
        _write_json_atomic(path, document)
        return OUTCOME_CREATED
    document = load_ledger(ledgers_dir, item)
    if document["origin"]["status"] == schemas.ORIGIN_UNTRACED and origin["status"] == schemas.ORIGIN_TRACED:
        document["origin"] = dict(origin)
        schemas.validate_ledger(document, path)
        _write_json_atomic(path, document)
        return OUTCOME_ORIGIN_FILLED
    return OUTCOME_UNCHANGED


def append_entry(ledgers_dir: str, item: ItemId, entry: Mapping[str, Any]) -> bool:
    """Add an entry to an existing ledger. Returns False if this entry id is already there."""
    document = load_ledger(ledgers_dir, item)
    if any(existing["id"] == entry["id"] for existing in document["entries"]):
        return False
    document["entries"].append(dict(entry))
    path = ledger_path(ledgers_dir, item)
    schemas.validate_ledger(document, path)
    _write_json_atomic(path, document)
    return True


def iter_ledgers(ledgers_dir: str) -> Iterator[dict[str, Any]]:
    """Every ledger, in a stable order."""
    for top in ("global", "projects"):
        for directory, subdirectories, names in os.walk(os.path.join(ledgers_dir, top)):
            subdirectories.sort()
            for name in sorted(names):
                if not name.endswith(".json"):
                    raise LedgerError(f"unexpected file in the ledgers: {os.path.join(directory, name)}")
                yield _read_ledger_file(os.path.join(directory, name))


def _entry_date(entry: Mapping[str, Any]) -> datetime:
    return datetime.fromisoformat(entry["date"])


def lost_balance(document: Mapping[str, Any], as_of: datetime, rule: LedgerConfig) -> Optional[dict[str, Any]]:
    """The flag for one ledger, or None if it keeps its balance.

    Flagged when, after the user's last direct "for" if any:
      - the user has made at least ``direct_against_entries`` direct statements against; or
      - at least ``inferred_against_entries`` inferred entries against fall inside the last
        ``inferred_window_days``, and no entry for does.

    Age alone never flags an item, since only entries are read. An undo or rejection in a review
    is held as an entry against but counts for neither: undoing one change says nothing about the
    rest of the item, and ``review-decisions.json`` is what stops the change coming back.
    """
    if as_of.tzinfo is None:
        raise LedgerError("as_of must carry a UTC offset")
    entries = sorted(document["entries"], key=lambda entry: (_entry_date(entry), entry["id"]))
    direct = [entry for entry in entries if entry["basis"] == schemas.BASIS_DIRECT]
    direct_for = [entry for entry in direct if entry["direction"] == schemas.STANCE_FOR]
    if direct_for:
        cleared_through = _entry_date(direct_for[-1])
        direct_against = [
            entry for entry in direct
            if entry["direction"] == schemas.STANCE_AGAINST and _entry_date(entry) > cleared_through
        ]
    else:
        cleared_through = None
        direct_against = [entry for entry in direct if entry["direction"] == schemas.STANCE_AGAINST]

    if len(direct_against) >= rule.direct_against_entries:
        return _flag(document, REASON_DIRECT, direct_against)

    window_start = as_of - timedelta(days=rule.inferred_window_days)
    recent = [entry for entry in entries if _entry_date(entry) > window_start]
    if any(entry["direction"] == schemas.STANCE_FOR for entry in recent):
        return None
    inferred_against = [
        entry for entry in recent
        if entry["basis"] not in (schemas.BASIS_DIRECT, schemas.BASIS_REVIEW_DECISION)
        and entry["direction"] == schemas.STANCE_AGAINST
        and (cleared_through is None or _entry_date(entry) > cleared_through)
    ]
    if len(inferred_against) >= rule.inferred_against_entries:
        return _flag(document, REASON_INFERRED, inferred_against)
    return None


def _flag(document: Mapping[str, Any], reason: str, entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {"identity": document["identity"], "reason": reason, "entries": [entry["id"] for entry in entries]}


def check_all(ledgers_dir: str, as_of: datetime, rule: LedgerConfig) -> list[dict[str, Any]]:
    """Every revision flag across the ledgers."""
    flags = (lost_balance(document, as_of, rule) for document in iter_ledgers(ledgers_dir))
    return [flag for flag in flags if flag is not None]


def write_flags(ledgers_dir: str, as_of: datetime, rule: LedgerConfig) -> list[dict[str, Any]]:
    """Recompute the flags and write them to their own file. No ledger is touched. The file
    holds no run date, so an unchanged result makes no new commit."""
    flags = check_all(ledgers_dir, as_of, rule)
    _write_json_atomic(
        os.path.join(ledgers_dir, FLAGS_FILE),
        {"schema_version": REPORTS_SCHEMA_VERSION, "flags": flags},
    )
    return flags


def _attribution(note: Mapping[str, Any]) -> tuple[str, str, str]:
    """Who stands behind a note: ``(who, basis, quote)``. An unverified quote counts for nothing."""
    if note["quote_check"] != schemas.QUOTE_VERIFIED:
        return schemas.WHO_AGENT, schemas.BASIS_INFERRED, ""
    endorsement = note["endorsement"]
    basis = schemas.BASIS_DIRECT if endorsement == "said" else endorsement
    if basis not in schemas.ENTRY_BASES_OF_USER:
        raise LedgerError(f"verified quote with endorsement {endorsement!r}")
    return schemas.WHO_USER, basis, note["endorsement_quote"]


def _resolve(
    ledgers_dir: str, reference: schemas.NoteItem, project_folder: str
) -> tuple[Optional[ItemId], Optional[str]]:
    """The item a note names, or the reason it cannot be told.

    A memory is looked up in the session's own project folder only, because the same file
    name can exist in several folders. A plugin may be named without its marketplace.
    """
    name = reference.name
    if reference.kind == KIND_MEMORY:
        if name.endswith(_MARKDOWN_SUFFIX):
            name = name[: -len(_MARKDOWN_SUFFIX)]
        item = ItemId(project_scope(project_folder), KIND_MEMORY, name)
    else:
        item = ItemId(SCOPE_GLOBAL, reference.kind, name)
    if item_exists(ledgers_dir, item):
        return item, None
    if reference.kind != KIND_PLUGIN or "@" in name:
        return None, UNMAPPED_NO_SUCH_ITEM
    pattern = os.path.join(glob.escape(os.path.dirname(ledger_path(ledgers_dir, item))), f"{glob.escape(_encoded(name))}@*.json")
    matches = sorted(glob.glob(pattern))
    if not matches:
        return None, UNMAPPED_NO_SUCH_ITEM
    if len(matches) > 1:
        return None, UNMAPPED_AMBIGUOUS
    return ItemId(**_read_ledger_file(matches[0])["identity"]), None


def _entry_of(
    note: Mapping[str, Any], item: ItemId, document: Mapping[str, Any], relative_path: str, note_index: int, direction: str
) -> dict[str, Any]:
    who, basis, quoted = _attribution(note)
    identity = "\n".join((relative_path, str(note_index), item.scope, item.kind, item.name))
    return {
        "id": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16],
        "date": document["last"],
        "session": document["session_id"],
        "project_folder": document["project_folder"],
        "direction": direction,
        "who": who,
        "basis": basis,
        "what": note["what"],
        "quote": quoted,
        "quote_check": note["quote_check"],
        "origin_of_point": note["origin_of_point"],
        "source": {"notes": relative_path, "note_index": note_index},
    }


def apply_notes(notes_dir: str, ledgers_dir: str) -> dict[str, Any]:
    """Turn the items named in all validated notes into entries. Safe to run repeatedly.

    Notes written before notes could name items (schema version 1) add nothing. A mention of
    an unknown item goes to the unmapped file and never into a ledger.
    """
    summary = {
        "notes_read": 0, "notes_that_cannot_name_items": 0, "notes_with_entries": 0,
        "entries_added": 0, "entries_already_present": 0, "mentions_no_bearing": 0,
    }
    unmapped: list[dict[str, Any]] = []
    pattern = os.path.join(glob.escape(notes_dir), "*", "*", "chunk-*.json")
    for path in sorted(glob.glob(pattern)):
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
        relative_path = os.path.relpath(path, os.path.dirname(notes_dir)).replace(os.sep, "/")
        version = document["notes_schema_version"]
        summary["notes_read"] += len(document["notes"])
        if version == schemas.NOTES_SCHEMA_WITHOUT_ITEMS:
            summary["notes_that_cannot_name_items"] += len(document["notes"])
            continue
        if version != schemas.NOTES_SCHEMA_VERSION:
            raise LedgerError(f"{path}: notes schema version {version!r}")
        for note_index, note in enumerate(document["notes"]):
            produced = False
            for position, values in enumerate(note["items"]):
                reference = schemas.validate_note_item(values, f"{path} note {note_index} item {position}")
                if reference.stance == schemas.STANCE_NO_BEARING:
                    summary["mentions_no_bearing"] += 1
                    continue
                item, reason = _resolve(ledgers_dir, reference, document["project_folder"])
                if item is None:
                    unmapped.append({
                        "kind": reference.kind, "name": reference.name, "stance": reference.stance, "reason": reason,
                        "session": document["session_id"], "notes": relative_path, "note_index": note_index,
                    })
                    continue
                entry = _entry_of(note, item, document, relative_path, note_index, reference.stance)
                if append_entry(ledgers_dir, item, entry):
                    summary["entries_added"] += 1
                else:
                    summary["entries_already_present"] += 1
                produced = True
            if produced:
                summary["notes_with_entries"] += 1
    _write_json_atomic(
        os.path.join(ledgers_dir, UNMAPPED_FILE),
        {"schema_version": REPORTS_SCHEMA_VERSION, "mentions": unmapped},
    )
    return {**summary, "mentions_unmapped": len(unmapped)}


def discard_entries_from_notes(ledgers_dir: str, notes_prefix: str) -> int:
    """Take out entries whose source notes were discarded, so that a window read again cannot
    keep what its old reading said. Returns how many were taken out."""
    removed = 0
    for top in ("global", "projects"):
        for directory, _, names in os.walk(os.path.join(ledgers_dir, top)):
            for name in names:
                path = os.path.join(directory, name)
                document = _read_ledger_file(path)
                kept = [entry for entry in document["entries"] if not entry["source"]["notes"].startswith(notes_prefix)]
                if len(kept) != len(document["entries"]):
                    removed += len(document["entries"]) - len(kept)
                    document["entries"] = kept
                    _write_json_atomic(path, document)
    return removed


def review_entry(
    entry_id: str, decided_at: str, session: str, project_folder: str, what: str, week: str, item_key: str
) -> dict[str, Any]:
    """An entry against, for something the user undid or rejected in a review."""
    return {
        "id": entry_id,
        "date": decided_at,
        "session": session,
        "project_folder": project_folder,
        "direction": schemas.STANCE_AGAINST,
        "who": schemas.WHO_USER,
        "basis": schemas.BASIS_REVIEW_DECISION,
        "what": what,
        "quote": "",
        "quote_check": schemas.QUOTE_NONE,
        "origin_of_point": "user",
        "source": {"notes": f"{REVIEW_SOURCE_PREFIX}{week}/{item_key}", "note_index": 0},
    }


def _check_decision(decision: Mapping[str, Any], where: str) -> None:
    if set(decision) != DECISION_FIELDS or decision["decision"] not in (DECISION_UNDONE, DECISION_REJECTED):
        raise LedgerError(f"{where}: malformed decision {sorted(decision)}")
    if datetime.fromisoformat(decision["decided_at"]).tzinfo is None:
        raise LedgerError(f"{where}: decision {decision['id']!r} has no UTC offset")


def load_decisions(ledgers_dir: str) -> list[dict[str, Any]]:
    """Every recorded undo and rejection. No file means none has been made yet."""
    path = os.path.join(ledgers_dir, DECISIONS_FILE)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    if document.get("schema_version") != DECISIONS_SCHEMA_VERSION:
        raise LedgerError(f"{path}: schema_version {document.get('schema_version')!r}")
    for decision in document["decisions"]:
        _check_decision(decision, path)
    return document["decisions"]


def record_decision(ledgers_dir: str, decision: Mapping[str, Any]) -> bool:
    """Record an undo or rejection, for the review step. Returns False if already recorded."""
    _check_decision(decision, "new decision")
    decisions = load_decisions(ledgers_dir)
    if any(existing["id"] == decision["id"] for existing in decisions):
        return False
    _write_json_atomic(
        os.path.join(ledgers_dir, DECISIONS_FILE),
        {"schema_version": DECISIONS_SCHEMA_VERSION, "decisions": [*decisions, dict(decision)]},
    )
    return True
