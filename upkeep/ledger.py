"""Reason ledgers: why each item exists, and what has been said for and against it since.

One JSON file per item, under the data folder:

    ledgers/global/<kind>/<name>.json              skills, hooks, tool servers, plugins
    ledgers/projects/<folder>/memory/<name>.json   memories, scoped by their project folder
    ledgers/revision-flags.json                    items that lost balance, rewritten each run
    ledgers/unmapped-mentions.json                 note mentions that could not become entries
    ledgers/stance-verdicts.json                   every verdict of the stance check, with its reason
    ledgers/review-decisions.json                  changes and proposals the user undid or rejected
    ledgers/item-problems.json                     items that could not be read, and possible renames

What this module holds to:

    The founding reason is written once and never expires: lost balance reads only entries.
    An entry comes from a note that names an item. Nothing here adds one for an item going
    unused, and a note saying so has the stance ``no_bearing``, which makes no entry.
    A flag proposes revision. It never edits or deletes a ledger or the item.

Lost balance, with numbers from config (see ``lost_balance``). The source states the rule and
this module fixes three points it leaves open:

    Only a note with endorsement ``said``, a quote found verbatim, and the stance check's word that
    the quote is about this item is the user's direct statement. A verified quote about the note's
    point and not this item ties the item to it by inference, so the entry is the agent's and inferred.
    ``accepted`` and ``relied_on`` are attributed to the user but count as inferred, because the
    wording is the agent's.
    The user's later direct statement outweighs what came before it: a direct "for" clears an
    earlier direct "against", and inferred "against" entries older than it stop counting.
    An inferred "for" never clears a direct "against".

Within one part of a session every note has the same date, so a note's place in its part decides
which came later. If one note says both, neither is later, so the "against" stands: a flag only
asks someone to read the item again.

Inferred entries count by session, not one by one: three parts of one session saying the same thing
are one piece of evidence. What flags an item is the balance over the window: sessions against minus
sessions for. A direct "for" in the window still holds inference back, as it is the user speaking.
An entry comes only from the stance the stance check settled on; see ``stance_check.py``.

A rule broken at a cost is an entry with its own direction, ``rule_broken``. The rule was not followed,
so it says nothing for or against the rule itself, and neither side of the balance reads it. It stays
in the item's ledger and on the review page, because a rule broken again and again may need revising.

A hook's, tool server's or plugin's own fault, once in a session, is an entry with the direction
``malfunction``. Twice in one session is ``against``, by the rule on repeated work, so a defect that fires
once per session would never show if each session were looked at alone. It is read by neither side of the
balance, and the review page counts it across sessions, per item.

An entry's source says which note it came from, and entries come only from notes. So a window read again
must lose its old entries first, which ``daily._discard_window`` does. An entry's id takes in the text of its
note, so no id can come to mean another note's text. ``apply_notes`` lists any entry whose note no longer
holds its text, because that means notes were replaced some other way. It does not repair it.

A name matches its ledger whatever its case, because a file system may not tell them apart and a
session may not spell a name as the file does. A ledger keeps the identity it holds until the item
itself is renamed in case, when ``ensure_ledger`` moves it along. A rename to another name cannot be
told from one item removed and another added, so the entries stay where they are, and ``possible_
renames`` in ``backfill.sync_items`` lists a likely pair for someone to read.
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
OUTCOME_CASE_RENAMED = "case_renamed"

FLAGS_FILE = "revision-flags.json"
UNMAPPED_FILE = "unmapped-mentions.json"
VERDICTS_FILE = "stance-verdicts.json"
OLD_REFUSED_FILE = "refused-stances.json"
STANCE_CHECKS_FILE = "stance-checks.json"
STANCE_CHECKS_SCHEMA_VERSION = 3
STANCE_USAGE_KEY = "stance-check"
UNKNOWN_NAME_PREFIX = "unknown:"
NOTES_SOURCE_PREFIX = "notes/"
DECISIONS_FILE = "review-decisions.json"
PROBLEMS_FILE = "item-problems.json"
DECISIONS_SCHEMA_VERSION = 1
DECISION_UNDONE = "undone"
DECISION_REJECTED = "rejected"
REVIEW_SOURCE_PREFIX = "review/"
DECISION_FIELDS = frozenset({"id", "decided_at", "decision", "scope", "kind", "name", "action", "claim", "week"})
REPORTS_SCHEMA_VERSION = 1

REASON_DIRECT = "direct_statement_against"
REASON_INFERRED = "inferred_against_outweighs_support"
UNMAPPED_NO_SUCH_ITEM = "no_such_item"
UNMAPPED_AMBIGUOUS = "ambiguous_name"
UNMAPPED_IDENTITY = "file_holds_another_item"
UNMAPPED_MARKED_UNKNOWN = "marked_unknown_by_the_reader"

_MARKDOWN_SUFFIX = ".md"
# Spaces and these marks are safe in a Windows file name; everything else is percent-encoded.
_SAFE_NAME_CHARS = " -_.@+()"


class LedgerError(ValueError):
    """A ledger is not what it should be, or a write would break a ledger rule."""


# What reading one item's ledger can raise: that item's problem, and no reason to stop the others.
UNREADABLE = (LedgerError, schemas.SchemaError)


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
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=1)
            handle.write("\n")
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise


def _read_ledger_file(path: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise LedgerError(f"{path}: not readable: {error}") from error
    schemas.validate_ledger(document, path)
    return document


def _located(ledgers_dir: str, item: ItemId) -> Optional[str]:
    """The item's file, whatever the case of its name, or None. Spelled as the item spells it comes
    first, for a file system that tells cases apart."""
    expected = ledger_path(ledgers_dir, item)
    directory, name = os.path.split(expected)
    if not os.path.isdir(directory):
        return None
    alike = [found for found in os.listdir(directory) if found.casefold() == name.casefold()]
    if name in alike:
        return expected
    if len(alike) > 1:
        raise LedgerError(f"{directory}: {alike} differ only by case")
    return os.path.join(directory, alike[0]) if alike else None


def _same_item(identity: Mapping[str, str], item: ItemId) -> bool:
    return all(identity[key].casefold() == value.casefold() for key, value in item.to_json().items())


def load_ledger(ledgers_dir: str, item: ItemId) -> dict[str, Any]:
    """Read and validate an item's ledger, whatever the case of the name asked for. What it returns
    holds the identity on file. A file holding another item raises."""
    path = _located(ledgers_dir, item)
    if path is None:
        raise FileNotFoundError(ledger_path(ledgers_dir, item))
    document = _read_ledger_file(path)
    if not _same_item(document["identity"], item):
        raise LedgerError(f"{path}: holds identity {document['identity']}, expected {item.to_json()}")
    return document


def item_exists(ledgers_dir: str, item: ItemId) -> bool:
    return _located(ledgers_dir, item) is not None


def ensure_ledger(
    ledgers_dir: str,
    item: ItemId,
    founding: Mapping[str, Any],
    would_be_wrong: Mapping[str, Any],
    origin: Mapping[str, Any],
    created: str,
) -> str:
    """Create a ledger once. On an existing one, the only changes allowed are filling in an
    untraced origin and following a change of case in the item's name, so the founding reason and
    the entries are never rewritten."""
    path = _located(ledgers_dir, item)
    if path is None:
        path = ledger_path(ledgers_dir, item)
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
    outcome = OUTCOME_UNCHANGED
    if document["origin"]["status"] == schemas.ORIGIN_UNTRACED and origin["status"] == schemas.ORIGIN_TRACED:
        document["origin"] = dict(origin)
        outcome = OUTCOME_ORIGIN_FILLED
    if document["identity"] != item.to_json():
        document["identity"] = item.to_json()
        outcome = OUTCOME_CASE_RENAMED
    if outcome != OUTCOME_UNCHANGED:
        schemas.validate_ledger(document, path)
        _write_json_atomic(path, document)
    if outcome == OUTCOME_CASE_RENAMED:
        os.replace(path, ledger_path(ledgers_dir, item))
    return outcome


def append_entry(ledgers_dir: str, item: ItemId, entry: Mapping[str, Any]) -> bool:
    """Add an entry to an existing ledger. Returns False if this entry id is already there."""
    document = load_ledger(ledgers_dir, item)
    if any(existing["id"] == entry["id"] for existing in document["entries"]):
        return False
    return _append(ledgers_dir, item, document, entry)


def _append(ledgers_dir: str, item: ItemId, document: dict[str, Any], entry: Mapping[str, Any]) -> bool:
    document["entries"].append(dict(entry))
    path = _located(ledgers_dir, item)
    schemas.validate_ledger(document, path)
    _write_json_atomic(path, document)
    return True


def _append_from_note(ledgers_dir: str, item: ItemId, entry: Mapping[str, Any]) -> bool:
    """Like ``append_entry``. One place in the notes gives one entry per direction, so an entry
    whose id was made before a rename in case is not added a second time under the new name."""
    document = load_ledger(ledgers_dir, item)
    for existing in document["entries"]:
        if existing["id"] == entry["id"] or (existing["source"] == entry["source"] and existing["direction"] == entry["direction"]):
            if existing["what"] != entry["what"]:
                raise LedgerError(_stale_message(existing))
            return False
    return _append(ledgers_dir, item, document, entry)


def _stale_message(entry: Mapping[str, Any]) -> str:
    source = entry["source"]
    return f"entry {entry['id']}: {source['notes']} note {source['note_index']} no longer holds its text, so the notes were replaced with the entry left behind"


def _note_problem(problems: Optional[list[dict[str, str]]], what: str, error: Exception) -> None:
    """Keep one item's problem for the review, or raise it if the caller keeps no such list."""
    if problems is None:
        raise error
    problems.append({"what": what, "detail": f"{type(error).__name__}: {error}"})


def iter_ledgers(ledgers_dir: str, problems: Optional[list[dict[str, str]]] = None) -> Iterator[dict[str, Any]]:
    """Every ledger, in a stable order. With a list given, a file that cannot be read goes on the
    list and the rest are still read. Without one, it raises."""
    for top in ("global", "projects"):
        for directory, subdirectories, names in os.walk(os.path.join(ledgers_dir, top)):
            subdirectories.sort()
            for name in sorted(names):
                path = os.path.join(directory, name)
                what = f"ledger file {os.path.relpath(path, ledgers_dir)}"
                if not name.endswith(".json"):
                    _note_problem(problems, what, LedgerError(f"unexpected file in the ledgers: {path}"))
                    continue
                try:
                    document = _read_ledger_file(path)
                except UNREADABLE as error:
                    _note_problem(problems, what, error)
                    continue
                yield document


def _entry_date(entry: Mapping[str, Any]) -> datetime:
    return datetime.fromisoformat(entry["date"])


def _entry_order(entry: Mapping[str, Any]) -> tuple[datetime, int]:
    return _entry_date(entry), entry["source"]["note_index"]


def lost_balance(document: Mapping[str, Any], as_of: datetime, rule: LedgerConfig) -> Optional[dict[str, Any]]:
    """The flag for one ledger, or None if it keeps its balance.

    Flagged when, after the user's last direct "for" if any:
      - the user has made at least ``direct_against_entries`` direct statements against; or
      - inside the last ``inferred_window_days``, the sessions with an inferred entry against, less
        the sessions with an entry for, come to at least ``inferred_against_entries``, and no direct
        statement for falls in that time. A session on both sides counts on both.

    Age alone never flags an item, since only entries are read. An undo or rejection in a review
    is held as an entry against but counts for neither: undoing one change says nothing about the
    rest of the item, and ``review-decisions.json`` is what stops the change coming back.
    """
    if as_of.tzinfo is None:
        raise LedgerError("as_of must carry a UTC offset")
    entries = sorted(document["entries"], key=lambda entry: (*_entry_order(entry), entry["id"]))
    direct = [entry for entry in entries if entry["basis"] == schemas.BASIS_DIRECT]
    direct_for = [entry for entry in direct if entry["direction"] == schemas.STANCE_FOR]
    if direct_for:
        cleared_through = _entry_order(direct_for[-1])
        direct_against = [
            entry for entry in direct
            if entry["direction"] == schemas.STANCE_AGAINST and _entry_order(entry) >= cleared_through
        ]
    else:
        cleared_through = None
        direct_against = [entry for entry in direct if entry["direction"] == schemas.STANCE_AGAINST]

    if len(direct_against) >= rule.direct_against_entries:
        return _flag(document, REASON_DIRECT, direct_against)

    window_start = as_of - timedelta(days=rule.inferred_window_days)
    recent = [entry for entry in entries if _entry_date(entry) > window_start]
    support = [entry for entry in recent if entry["direction"] == schemas.STANCE_FOR]
    if any(entry["basis"] == schemas.BASIS_DIRECT for entry in support):
        return None
    inferred_against = [
        entry for entry in recent
        if entry["basis"] not in (schemas.BASIS_DIRECT, schemas.BASIS_REVIEW_DECISION)
        and entry["direction"] == schemas.STANCE_AGAINST
        and (cleared_through is None or _entry_order(entry) >= cleared_through)
    ]
    sessions_against = len({entry["session"] for entry in inferred_against})
    sessions_for = len({entry["session"] for entry in support})
    if sessions_against - sessions_for >= rule.inferred_against_entries:
        return _flag(document, REASON_INFERRED, inferred_against, support)
    return None


def _flag(document: Mapping[str, Any], reason: str, entries: Sequence[Mapping[str, Any]], support: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    return {"identity": document["identity"], "reason": reason, "entries": [entry["id"] for entry in entries], "entries_for": [entry["id"] for entry in support]}


def check_all(ledgers_dir: str, as_of: datetime, rule: LedgerConfig, problems: Optional[list[dict[str, str]]] = None) -> list[dict[str, Any]]:
    """Every revision flag across the ledgers. See ``iter_ledgers`` on ``problems``."""
    flags = (lost_balance(document, as_of, rule) for document in iter_ledgers(ledgers_dir, problems))
    return [flag for flag in flags if flag is not None]


def write_flags(ledgers_dir: str, as_of: datetime, rule: LedgerConfig, problems: Optional[list[dict[str, str]]] = None) -> list[dict[str, Any]]:
    """Recompute the flags and write them to their own file. No ledger is touched. The file
    holds no run date, so an unchanged result makes no new commit."""
    flags = check_all(ledgers_dir, as_of, rule, problems)
    _write_json_atomic(
        os.path.join(ledgers_dir, FLAGS_FILE),
        {"schema_version": REPORTS_SCHEMA_VERSION, "flags": flags},
    )
    return flags


def _attribution(note: Mapping[str, Any], about_item: bool) -> tuple[str, str, str, str]:
    """Who stands behind a stance: ``(who, basis, quote, quote_check)``. An unverified quote counts for
    nothing, and a statement counts as direct only if it is about this item. ``about_item`` is the
    stance check's word on that."""
    if note["quote_check"] != schemas.QUOTE_VERIFIED:
        return schemas.WHO_AGENT, schemas.BASIS_INFERRED, "", note["quote_check"]
    endorsement = note["endorsement"]
    if endorsement == "said" and not about_item:
        return schemas.WHO_AGENT, schemas.BASIS_INFERRED, "", schemas.QUOTE_NONE
    basis = schemas.BASIS_DIRECT if endorsement == "said" else endorsement
    if basis not in schemas.ENTRY_BASES_OF_USER:
        raise LedgerError(f"verified quote with endorsement {endorsement!r}")
    return schemas.WHO_USER, basis, note["endorsement_quote"], schemas.QUOTE_VERIFIED


def _by_display_name(ledgers_dir: str, reference: schemas.NoteItem, aliases: Mapping[tuple[str, str], Sequence[str]]) -> tuple[Optional[ItemId], Optional[str]]:
    """The item bearing this display name, or the reason it cannot be told."""
    names = aliases.get((reference.kind, reference.name.strip().casefold()), ())
    if len(names) > 1:
        return None, UNMAPPED_AMBIGUOUS
    if not names:
        return None, UNMAPPED_NO_SUCH_ITEM
    path = _located(ledgers_dir, ItemId(SCOPE_GLOBAL, reference.kind, names[0]))
    return (ItemId(**_read_ledger_file(path)["identity"]), None) if path is not None else (None, UNMAPPED_NO_SUCH_ITEM)


def _resolve(
    ledgers_dir: str, reference: schemas.NoteItem, project_folder: str, aliases: Mapping[tuple[str, str], Sequence[str]]
) -> tuple[Optional[ItemId], Optional[str]]:
    """The item a note names, or the reason it cannot be told.

    The reader marks a name that is not on its list as unknown. A display name, such as a hook's
    status message, leads to the item bearing it, in any case. The rest of this holds as well.

    A memory is looked up in the session's own project folder only, because the same file
    name can exist in several folders. A plugin may be named without its marketplace. A session
    may spell a name in another case, so what comes back is the identity on file. A file that
    holds another item altogether cannot be what the note meant.
    """
    name = reference.name
    if name.strip().casefold().startswith(UNKNOWN_NAME_PREFIX):
        return None, UNMAPPED_MARKED_UNKNOWN
    if reference.kind == KIND_MEMORY:
        if name.lower().endswith(_MARKDOWN_SUFFIX):
            name = name[: -len(_MARKDOWN_SUFFIX)]
        item = ItemId(project_scope(project_folder), KIND_MEMORY, name)
    else:
        item = ItemId(SCOPE_GLOBAL, reference.kind, name)
    try:
        path = _located(ledgers_dir, item)
    except LedgerError:
        return None, UNMAPPED_AMBIGUOUS
    if path is not None:
        identity = _read_ledger_file(path)["identity"]
        return (ItemId(**identity), None) if _same_item(identity, item) else (None, UNMAPPED_IDENTITY)
    if reference.kind != KIND_PLUGIN or "@" in name:
        return _by_display_name(ledgers_dir, reference, aliases)
    directory = os.path.dirname(ledger_path(ledgers_dir, item))
    start = f"{_encoded(name)}@".casefold()
    matches = sorted(found for found in os.listdir(directory) if found.casefold().startswith(start) and found.endswith(".json")) if os.path.isdir(directory) else []
    if not matches:
        return None, UNMAPPED_NO_SUCH_ITEM
    if len(matches) > 1:
        return None, UNMAPPED_AMBIGUOUS
    return ItemId(**_read_ledger_file(os.path.join(directory, matches[0]))["identity"]), None


def _entry_of(
    note: Mapping[str, Any], item: ItemId, document: Mapping[str, Any], relative_path: str, note_index: int, direction: str, second_stance: bool, about_item: bool
) -> dict[str, Any]:
    """The id takes in the note's text, so that it cannot come to mean another note's. Only a second,
    opposite stance has its direction in the id. An entry on file from before the text was part of the
    id is found again by its place in the notes."""
    who, basis, quoted, quote_check = _attribution(note, about_item)
    parts = (relative_path, str(note_index), item.scope, item.kind, item.name, note["what"])
    identity = "\n".join((*parts, direction) if second_stance else parts)
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
        "quote_check": quote_check,
        "origin_of_point": note["origin_of_point"],
        "source": {"notes": relative_path, "note_index": note_index},
    }


def stance_key(chunk_file: str, note_index: int, position: int) -> str:
    return f"{chunk_file}#{note_index}#{position}"


def read_stance_checks(window_dir: str) -> dict[str, dict[str, Any]]:
    """The verdicts on this window's stances. No file means none has been judged yet."""
    path = os.path.join(window_dir, STANCE_CHECKS_FILE)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    if document.get("schema_version") != STANCE_CHECKS_SCHEMA_VERSION:
        raise LedgerError(f"{path}: schema_version {document.get('schema_version')!r}; verdicts from an older check are judged again after running stance_check.py rejudge-old")
    return document["checks"]


def add_stance_checks(window_dir: str, checks: Mapping[str, Mapping[str, Any]]) -> None:
    _write_json_atomic(
        os.path.join(window_dir, STANCE_CHECKS_FILE),
        {"schema_version": STANCE_CHECKS_SCHEMA_VERSION, "checks": {**read_stance_checks(window_dir), **checks}},
    )


@dataclass(frozen=True)
class StanceMention:
    """A stance in a note, of any kind, on an item that resolved, with no verdict yet."""

    window_dir: str
    key: str
    note: Mapping[str, Any]
    reference: schemas.NoteItem
    item: ItemId


def pending_stances(notes_dir: str, ledgers_dir: str, aliases: Mapping[tuple[str, str], Sequence[str]]) -> Iterator[StanceMention]:
    """What the stance check still has to judge. What cannot be read here is reported by
    ``apply_notes``, which reads the same files right after."""
    for path in sorted(glob.glob(os.path.join(glob.escape(notes_dir), "*", "*", "chunk-*.json"))):
        try:
            with open(path, encoding="utf-8") as handle:
                document = json.load(handle)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if document["notes_schema_version"] != schemas.NOTES_SCHEMA_VERSION:
            continue
        window_dir = os.path.dirname(path)
        checks = read_stance_checks(window_dir)
        for note_index, note in enumerate(document["notes"]):
            for position, values in enumerate(note["items"]):
                key = stance_key(os.path.basename(path), note_index, position)
                try:
                    reference = schemas.validate_note_item(values, path)
                    if key in checks:
                        continue
                    item, _ = _resolve(ledgers_dir, reference, document["project_folder"], aliases)
                except UNREADABLE:
                    continue
                if item is not None:
                    yield StanceMention(window_dir, key, note, reference, item)


def earlier_rulings(notes_dir: str, limit: int) -> dict[ItemId, list[dict[str, str]]]:
    """Up to ``limit`` of the latest verdicts on each item, by the date of their window's folder, so
    that a later pass can treat like cases alike."""
    found: dict[ItemId, list[dict[str, str]]] = {}
    for path in sorted(glob.glob(os.path.join(glob.escape(notes_dir), "*", "*", STANCE_CHECKS_FILE))):
        for check in read_stance_checks(os.path.dirname(path)).values():
            found.setdefault(ItemId(**check["item"]), []).append({"final": check["final"], "rule_broken": check["rule_broken"], "malfunction": check["malfunction"], "what": check["what"], "reason": check["reason"]})
    return {item: rulings[-limit:] if limit else [] for item, rulings in found.items()}


def apply_notes(
    notes_dir: str,
    ledgers_dir: str,
    problems: Optional[list[dict[str, str]]] = None,
    aliases: Mapping[tuple[str, str], Sequence[str]] = {},
) -> dict[str, Any]:
    """Turn the items named in all validated notes into entries. Safe to run repeatedly.

    Notes written before notes could name items (schema version 1) add nothing. A mention of
    an unknown item goes to the unmapped file and never into a ledger, whatever its stance. Every other
    mention waits until the stance check has judged it, and its verdict then goes to the verdicts file.
    The stance the check settled on makes an entry, unless it is no bearing. A rule broken at a cost
    makes an entry of its own direction, and so does a hook's or tool's own fault. With a list given, a notes
    file or a ledger that cannot be read goes on the list, and everything else is still read, and so does
    an entry whose note no longer holds its text.
    """
    summary = {
        "notes_read": 0, "notes_that_cannot_name_items": 0, "notes_with_entries": 0,
        "entries_added": 0, "entries_already_present": 0, "mentions_no_bearing": 0,
        "rule_broken_added": 0, "malfunctions_added": 0, "mentions_awaiting_check": 0,
        **{f"mentions_{verdict}": 0 for verdict in schemas.STANCE_VERDICTS},
    }
    unmapped: list[dict[str, Any]] = []
    verdicts: list[dict[str, Any]] = []
    pattern = os.path.join(glob.escape(notes_dir), "*", "*", "chunk-*.json")
    for path in sorted(glob.glob(pattern)):
        relative_path = os.path.relpath(path, os.path.dirname(notes_dir)).replace(os.sep, "/")
        try:
            with open(path, encoding="utf-8") as handle:
                document = json.load(handle)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            _note_problem(problems, f"notes file {relative_path}", LedgerError(f"{path}: not readable: {error}"))
            continue
        version = document["notes_schema_version"]
        summary["notes_read"] += len(document["notes"])
        if version == schemas.NOTES_SCHEMA_WITHOUT_ITEMS:
            summary["notes_that_cannot_name_items"] += len(document["notes"])
            continue
        if version != schemas.NOTES_SCHEMA_VERSION:
            _note_problem(problems, f"notes file {relative_path}", LedgerError(f"{path}: notes schema version {version!r}"))
            continue
        checks = read_stance_checks(os.path.dirname(path))
        for note_index, note in enumerate(document["notes"]):
            produced = False
            first_stance: dict[ItemId, str] = {}
            for position, values in enumerate(note["items"]):
                what = f"{values.get('kind')} {values.get('name')}, named in {relative_path}" if isinstance(values, dict) else f"notes file {relative_path}"
                try:
                    reference = schemas.validate_note_item(values, f"{path} note {note_index} item {position}")
                    item, reason = _resolve(ledgers_dir, reference, document["project_folder"], aliases)
                    if item is None:
                        summary["mentions_no_bearing"] += reference.stance == schemas.STANCE_NO_BEARING
                        unmapped.append({
                            "kind": reference.kind, "name": reference.name, "stance": reference.stance, "reason": reason,
                            "session": document["session_id"], "notes": relative_path, "note_index": note_index,
                        })
                        continue
                    check = checks.get(stance_key(os.path.basename(path), note_index, position))
                    if check is None:
                        summary["mentions_awaiting_check"] += 1
                        continue
                    if check["what"] != note["what"]:
                        raise LedgerError(f"{relative_path} note {note_index}: its verdict was given on another note's text, so the notes were replaced with the verdict left behind")
                    final = check["final"]
                    summary[f"mentions_{check['verdict']}"] += 1
                    verdicts.append({
                        "kind": reference.kind, "name": reference.name, "item": item.to_json(), "stance": reference.stance, "final": final,
                        "verdict": check["verdict"], "rule_broken": check["rule_broken"], "malfunction": check["malfunction"], "reason": check["reason"], "date": document["last"],
                        "session": document["session_id"], "notes": relative_path, "note_index": note_index,
                    })
                    if check["rule_broken"]:
                        breach = _entry_of(note, item, document, relative_path, note_index, schemas.DIRECTION_RULE_BROKEN, True, check["quote_about_item"])
                        summary["rule_broken_added"] += _append_from_note(ledgers_dir, item, breach)
                    if check["malfunction"]:
                        fault = _entry_of(note, item, document, relative_path, note_index, schemas.DIRECTION_MALFUNCTION, True, check["quote_about_item"])
                        summary["malfunctions_added"] += _append_from_note(ledgers_dir, item, fault)
                    if final == schemas.STANCE_NO_BEARING:
                        summary["mentions_no_bearing"] += 1
                        continue
                    second_stance = first_stance.setdefault(item, final) != final
                    entry = _entry_of(note, item, document, relative_path, note_index, final, second_stance, check["quote_about_item"])
                    if _append_from_note(ledgers_dir, item, entry):
                        summary["entries_added"] += 1
                    else:
                        summary["entries_already_present"] += 1
                except UNREADABLE as error:
                    _note_problem(problems, what, error)
                    continue
                produced = True
            if produced:
                summary["notes_with_entries"] += 1
    _write_json_atomic(
        os.path.join(ledgers_dir, UNMAPPED_FILE),
        {"schema_version": REPORTS_SCHEMA_VERSION, "mentions": unmapped},
    )
    _write_json_atomic(
        os.path.join(ledgers_dir, VERDICTS_FILE),
        {"schema_version": REPORTS_SCHEMA_VERSION, "mentions": verdicts},
    )
    _report_entries_left_behind(ledgers_dir, problems)
    return {**summary, "mentions_unmapped": len(unmapped)}


def _report_entries_left_behind(ledgers_dir: str, problems: Optional[list[dict[str, str]]]) -> None:
    """Any entry whose source note no longer holds its text. A notes file that cannot be read is already
    on the list, and so is a ledger that cannot be read, by the pass that writes the flags."""
    root = os.path.dirname(ledgers_dir)
    texts: dict[str, Optional[list[str]]] = {}
    for held in iter_ledgers(ledgers_dir, []):
        identity = held["identity"]
        for entry in held["entries"]:
            source = entry["source"]
            if not source["notes"].startswith(NOTES_SOURCE_PREFIX):
                continue
            if source["notes"] not in texts:
                texts[source["notes"]] = _note_texts(os.path.join(root, source["notes"]))
            found = texts[source["notes"]]
            if found is None:
                continue
            if source["note_index"] >= len(found) or found[source["note_index"]] != entry["what"]:
                _note_problem(problems, f"{identity['kind']} {identity['name']}", LedgerError(_stale_message(entry)))


def _note_texts(path: str) -> Optional[list[str]]:
    """The text of each note in a file, empty if the file is gone, or None if it cannot be read."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as handle:
            return [note["what"] for note in json.load(handle)["notes"]]
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def discard_entries_from_notes(ledgers_dir: str, notes_prefix: str) -> int:
    """Take out entries whose source notes were discarded, so that a window read again cannot
    keep what its old reading said. Returns how many were taken out. A ledger that cannot be read
    may hold such an entry, so after doing the rest this raises, naming each."""
    removed = 0
    unreadable: list[str] = []
    for top in ("global", "projects"):
        for directory, _, names in os.walk(os.path.join(ledgers_dir, top)):
            for name in names:
                path = os.path.join(directory, name)
                try:
                    document = _read_ledger_file(path)
                except UNREADABLE as error:
                    unreadable.append(f"{os.path.relpath(path, ledgers_dir)}: {error}")
                    continue
                kept = [entry for entry in document["entries"] if not entry["source"]["notes"].startswith(notes_prefix)]
                if len(kept) != len(document["entries"]):
                    removed += len(document["entries"]) - len(kept)
                    document["entries"] = kept
                    _write_json_atomic(path, document)
    if unreadable:
        raise LedgerError(f"entries from {notes_prefix} may remain in ledgers that could not be read: {unreadable}")
    return removed


def _problems_path(ledgers_dir: str) -> str:
    return os.path.join(ledgers_dir, PROBLEMS_FILE)


def read_item_problems(ledgers_dir: str) -> dict[str, list[dict[str, str]]]:
    """Items a pass could not read, and possible renames. No file means none has been found yet."""
    path = _problems_path(ledgers_dir)
    if not os.path.exists(path):
        return {"problems": [], "possible_renames": []}
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    if document.get("schema_version") != REPORTS_SCHEMA_VERSION:
        raise LedgerError(f"{path}: schema_version {document.get('schema_version')!r}")
    return {"problems": document["problems"], "possible_renames": document["possible_renames"]}


def _distinct_problems(problems: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    found: dict[tuple[str, str], dict[str, str]] = {}
    for problem in problems:
        found.setdefault((problem["what"], problem["detail"]), dict(problem))
    return list(found.values())


def write_item_problems(ledgers_dir: str, problems: Sequence[Mapping[str, str]], possible_renames: Sequence[Mapping[str, str]]) -> None:
    """The whole list, as a pass that has just looked at every item found it. Reaches the review."""
    _write_json_atomic(_problems_path(ledgers_dir), {
        "schema_version": REPORTS_SCHEMA_VERSION, "problems": _distinct_problems(problems), "possible_renames": list(possible_renames),
    })


def add_item_problems(ledgers_dir: str, problems: Sequence[Mapping[str, str]]) -> None:
    """Problems met along the way by a pass that does not look at every item."""
    if problems:
        held = read_item_problems(ledgers_dir)
        write_item_problems(ledgers_dir, [*held["problems"], *problems], held["possible_renames"])


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
