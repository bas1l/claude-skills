"""Ledger rules, on synthetic ledgers and notes."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

import ledger
import schemas
from config import LedgerConfig

NOW = datetime(2030, 6, 1, 12, 0, tzinfo=timezone.utc)
RULE = LedgerConfig(
    direct_against_entries=1,
    inferred_against_entries=3,
    inferred_window_days=28,
    rename_name_overlap=0.5,
    rename_flag_days=28,
    stated_limit_patterns=(),
    origin_tools=("Write", "Edit"),
)
FOLDER = "project-a"
ITEM = ledger.ItemId(ledger.project_scope(FOLDER), "memory", "some-memory")
UNVERIFIED = {"reason": "A stated reason.", "status": schemas.FOUNDING_UNVERIFIED, "source": "why_line"}
NO_LIMIT = {"status": schemas.LIMIT_NOT_STATED, "text": None}
NO_ORIGIN = {
    "status": schemas.ORIGIN_UNTRACED, "session": None, "project_folder": None, "at": None, "tool": None,
    "creating_call_found": None,
}
TRACED = {
    "status": schemas.ORIGIN_TRACED, "session": "s-1", "project_folder": FOLDER, "at": "2030-01-01T00:00:00+00:00",
    "tool": "Write", "creating_call_found": True,
}


def checked_apply_notes(notes_dir, *rest, **keywords):
    """Every stance has passed its check: that check has tests of its own."""
    from conftest import hold_all_stances
    hold_all_stances(notes_dir)
    return ledger.apply_notes(notes_dir, *rest, **keywords)


def entry(entry_id, days_ago, direction, basis=schemas.BASIS_INFERRED):
    is_user = basis != schemas.BASIS_INFERRED
    return {
        "id": entry_id,
        "date": (NOW - timedelta(days=days_ago)).isoformat(),
        "session": f"s-{entry_id}",
        "project_folder": FOLDER,
        "direction": direction,
        "who": schemas.WHO_USER if is_user else schemas.WHO_AGENT,
        "basis": basis,
        "what": "A finding.",
        "quote": "words" if is_user else "",
        "quote_check": schemas.QUOTE_VERIFIED if is_user else schemas.QUOTE_NONE,
        "origin_of_point": "user" if is_user else "assistant",
        "source": {"notes": "notes/x/y/chunk-001.json", "note_index": 0},
    }


def ledger_with(*entries):
    return {
        "schema_version": schemas.LEDGER_SCHEMA_VERSION,
        "identity": ITEM.to_json(),
        "created": "2030-01-01",
        "founding": UNVERIFIED,
        "would_be_wrong": NO_LIMIT,
        "origin": NO_ORIGIN,
        "entries": list(entries),
    }


def test_no_entries_never_flags_however_old():
    assert ledger.lost_balance(ledger_with(), NOW + timedelta(days=36500), RULE) is None


def test_one_direct_statement_against_flags():
    flag = ledger.lost_balance(ledger_with(entry("a", 400, "against", schemas.BASIS_DIRECT)), NOW, RULE)
    assert flag["reason"] == ledger.REASON_DIRECT
    assert flag["entries"] == ["a"]


def test_three_inferred_against_flag_and_two_do_not():
    three = [entry(name, 3, "against") for name in "abc"]
    assert ledger.lost_balance(ledger_with(*three), NOW, RULE)["reason"] == ledger.REASON_INFERRED
    assert ledger.lost_balance(ledger_with(*three[:2]), NOW, RULE) is None


def test_inferred_against_outside_the_window_do_not_count():
    entries = [entry("a", 3, "against"), entry("b", 3, "against"), entry("c", 40, "against")]
    assert ledger.lost_balance(ledger_with(*entries), NOW, RULE) is None


def test_an_entry_for_in_the_window_counts_against_the_inferred_balance():
    entries = [entry(name, 3, "against") for name in "abc"] + [entry("d", 10, "for")]
    assert ledger.lost_balance(ledger_with(*entries), NOW, RULE) is None


def test_an_entry_for_before_the_window_does_not_block():
    entries = [entry(name, 3, "against") for name in "abc"] + [entry("d", 40, "for")]
    assert ledger.lost_balance(ledger_with(*entries), NOW, RULE) is not None


def test_inferred_support_does_not_outweigh_a_direct_statement():
    entries = [entry("a", 5, "against", schemas.BASIS_DIRECT)] + [entry(name, 1, "for") for name in "bcdef"]
    assert ledger.lost_balance(ledger_with(*entries), NOW, RULE)["reason"] == ledger.REASON_DIRECT


def test_later_direct_support_clears_earlier_direct_and_inferred_against():
    entries = [
        entry("a", 20, "against", schemas.BASIS_DIRECT),
        *[entry(name, 40, "against") for name in "bcd"],
        entry("e", 10, "for", schemas.BASIS_DIRECT),
    ]
    assert ledger.lost_balance(ledger_with(*entries), NOW, RULE) is None


def test_direct_support_older_than_the_window_does_not_hide_newer_inference():
    entries = [entry(name, 3, "against") for name in "abc"] + [entry("d", 60, "for", schemas.BASIS_DIRECT)]
    assert ledger.lost_balance(ledger_with(*entries), NOW, RULE)["reason"] == ledger.REASON_INFERRED


def test_accepted_is_not_a_direct_statement():
    assert ledger.lost_balance(ledger_with(entry("a", 1, "against", "accepted")), NOW, RULE) is None


def test_thresholds_come_from_the_rule():
    strict = LedgerConfig(2, 1, 28, 0.5, 28, (), ())
    assert ledger.lost_balance(ledger_with(entry("a", 1, "against", schemas.BASIS_DIRECT)), NOW, strict) is None
    assert ledger.lost_balance(ledger_with(entry("a", 1, "against")), NOW, strict)["reason"] == ledger.REASON_INFERRED


def test_ensure_keeps_founding_and_fills_only_an_untraced_origin(tmp_path):
    root = str(tmp_path)
    assert ledger.ensure_ledger(root, ITEM, UNVERIFIED, NO_LIMIT, NO_ORIGIN, "2030-01-01") == ledger.OUTCOME_CREATED
    changed_reason = {**UNVERIFIED, "reason": "A rewritten reason."}
    assert ledger.ensure_ledger(root, ITEM, changed_reason, NO_LIMIT, NO_ORIGIN, "2031-01-01") == ledger.OUTCOME_UNCHANGED
    assert ledger.load_ledger(root, ITEM)["founding"] == UNVERIFIED
    assert ledger.ensure_ledger(root, ITEM, changed_reason, NO_LIMIT, TRACED, "2031-01-01") == ledger.OUTCOME_ORIGIN_FILLED
    document = ledger.load_ledger(root, ITEM)
    assert (document["origin"], document["founding"], document["created"]) == (TRACED, UNVERIFIED, "2030-01-01")
    other = {**TRACED, "session": "s-2"}
    assert ledger.ensure_ledger(root, ITEM, UNVERIFIED, NO_LIMIT, other, "2031-01-01") == ledger.OUTCOME_UNCHANGED


def test_a_file_holding_another_identity_raises(tmp_path):
    root = str(tmp_path)
    ledger.ensure_ledger(root, ITEM, UNVERIFIED, NO_LIMIT, NO_ORIGIN, "2030-01-01")
    other = ledger.ItemId(ITEM.scope, ITEM.kind, "other")
    os.replace(ledger.ledger_path(root, ITEM), ledger.ledger_path(root, other))
    with pytest.raises(ledger.LedgerError):
        ledger.load_ledger(root, other)


def test_awkward_names_get_a_file_inside_their_folder(tmp_path):
    item = ledger.ItemId(ledger.SCOPE_GLOBAL, "skill", "a/../b: c - backup")
    path = ledger.ledger_path(str(tmp_path), item)
    assert os.path.dirname(path) == os.path.join(str(tmp_path), "global", "skill")
    ledger.ensure_ledger(str(tmp_path), item, UNVERIFIED, NO_LIMIT, NO_ORIGIN, "2030-01-01")
    assert ledger.load_ledger(str(tmp_path), item)["identity"]["name"] == item.name


@pytest.mark.parametrize(
    "change",
    [
        {"founding": {"reason": "invented", "status": schemas.FOUNDING_NO_REASON, "source": None}},
        {"founding": {"reason": "x", "status": "maybe", "source": "why_line"}},
        {"origin": {**NO_ORIGIN, "session": "s-1"}},
        {"entries": [{**entry("a", 1, "for"), "direction": "unused"}]},
        {"entries": [{**entry("a", 1, "for"), "who": schemas.WHO_USER}]},
        {"entries": [{**entry("a", 1, "for", schemas.BASIS_DIRECT), "quote_check": schemas.QUOTE_NOT_FOUND}]},
        {"unknown": 1},
    ],
)
def test_malformed_ledgers_are_rejected(change):
    with pytest.raises(schemas.SchemaError):
        schemas.validate_ledger({**ledger_with(), **change}, "test")


def stored_note(items, endorsement="none", quote="", quote_check=schemas.QUOTE_NONE, origin="assistant"):
    return {
        "type": "conflict", "what": "A finding.", "evidence": "ASSISTANT-TEXT", "memory_candidate": False,
        "endorsement": endorsement, "endorsement_quote": quote, "origin_of_point": origin, "route": "none",
        "confidence": "high", "items": items, "quote_check": quote_check,
    }


def write_chunk(data_dir, window, *notes, version=schemas.NOTES_SCHEMA_VERSION, folder=FOLDER):
    path = os.path.join(data_dir, "notes", "2030-05-30", window, "chunk-001.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    document = {
        "schema_version": 2, "notes_schema_version": version, "session_id": "s-9", "project_cwd": "/work",
        "last": "2030-05-30T10:00:00+00:00", "notes": list(notes),
    }
    if version == schemas.NOTES_SCHEMA_VERSION:
        document["project_folder"] = folder
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(document, handle)


def named(stance="against", name="some-memory", kind="memory"):
    return {"kind": kind, "name": name, "stance": stance}


@pytest.fixture
def stores(tmp_path):
    data = str(tmp_path)
    ledgers = ledger.ledgers_dir_of(data)
    ledger.ensure_ledger(ledgers, ITEM, UNVERIFIED, NO_LIMIT, NO_ORIGIN, "2030-01-01")
    return data, ledgers, os.path.join(data, "notes")


def test_a_note_naming_an_item_adds_one_entry_and_rerun_adds_none(stores):
    data, ledgers, notes = stores
    write_chunk(data, "w1", stored_note([named()]))
    summary = checked_apply_notes(notes, ledgers)
    assert (summary["entries_added"], summary["notes_with_entries"]) == (1, 1)
    before = open(ledger.ledger_path(ledgers, ITEM), "rb").read()
    summary = checked_apply_notes(notes, ledgers)
    assert (summary["entries_added"], summary["entries_already_present"]) == (0, 1)
    assert open(ledger.ledger_path(ledgers, ITEM), "rb").read() == before
    added = ledger.load_ledger(ledgers, ITEM)["entries"][0]
    assert (added["direction"], added["who"], added["basis"], added["session"]) == ("against", "agent", "inferred", "s-9")
    assert added["source"]["notes"] == "notes/2030-05-30/w1/chunk-001.json"


def test_non_use_adds_no_entry(stores):
    data, ledgers, notes = stores
    write_chunk(data, "w1", stored_note([named("no_bearing")]))
    summary = checked_apply_notes(notes, ledgers)
    assert (summary["entries_added"], summary["mentions_no_bearing"], summary["notes_with_entries"]) == (0, 1, 0)
    assert ledger.load_ledger(ledgers, ITEM)["entries"] == []


def test_an_unknown_item_is_logged_and_not_added(stores):
    data, ledgers, notes = stores
    write_chunk(data, "w1", stored_note([named(name="no-such-memory"), named(kind="skill", name="no-such-skill")]))
    summary = checked_apply_notes(notes, ledgers)
    assert (summary["entries_added"], summary["mentions_unmapped"]) == (0, 2)
    with open(os.path.join(ledgers, ledger.UNMAPPED_FILE), encoding="utf-8") as handle:
        logged = json.load(handle)["mentions"]
    assert [(mention["name"], mention["reason"]) for mention in logged] == [
        ("no-such-memory", ledger.UNMAPPED_NO_SUCH_ITEM), ("no-such-skill", ledger.UNMAPPED_NO_SUCH_ITEM),
    ]
    assert not os.path.exists(ledger.ledger_path(ledgers, ledger.ItemId(ITEM.scope, "memory", "no-such-memory")))


def test_a_memory_is_looked_up_in_the_sessions_own_folder_only(stores):
    data, ledgers, notes = stores
    write_chunk(data, "w1", stored_note([named()]), folder="another-project")
    summary = checked_apply_notes(notes, ledgers)
    assert (summary["entries_added"], summary["mentions_unmapped"]) == (0, 1)


def test_a_markdown_suffix_on_a_memory_name_is_accepted(stores):
    data, ledgers, notes = stores
    write_chunk(data, "w1", stored_note([named(name="some-memory.md")]))
    assert checked_apply_notes(notes, ledgers)["entries_added"] == 1


def test_a_plugin_may_be_named_without_its_marketplace(stores):
    data, ledgers, notes = stores
    for name in ("one@market", "two@market", "two@other"):
        plugin = ledger.ItemId(ledger.SCOPE_GLOBAL, "plugin", name)
        ledger.ensure_ledger(ledgers, plugin, UNVERIFIED, NO_LIMIT, {**NO_ORIGIN, "status": schemas.ORIGIN_NOT_APPLICABLE}, "2030-01-01")
    write_chunk(data, "w1", stored_note([named(kind="plugin", name="one"), named(kind="plugin", name="two")]))
    summary = checked_apply_notes(notes, ledgers)
    assert (summary["entries_added"], summary["mentions_unmapped"]) == (1, 1)
    with open(os.path.join(ledgers, ledger.UNMAPPED_FILE), encoding="utf-8") as handle:
        assert json.load(handle)["mentions"][0]["reason"] == ledger.UNMAPPED_AMBIGUOUS


def test_only_a_verified_said_quote_is_a_direct_statement(stores):
    data, ledgers, notes = stores
    write_chunk(
        data, "w1",
        stored_note([named()], "said", "this is wrong", schemas.QUOTE_VERIFIED, "user"),
        stored_note([named()], "said", "a fabricated quote", schemas.QUOTE_NOT_FOUND, "user"),
        stored_note([named()], "accepted", "yes", schemas.QUOTE_VERIFIED),
    )
    checked_apply_notes(notes, ledgers)
    entries = ledger.load_ledger(ledgers, ITEM)["entries"]
    assert [(e["who"], e["basis"], e["quote"]) for e in entries] == [
        ("user", "direct_statement", "this is wrong"),
        ("agent", "inferred", ""),
        ("user", "accepted", "yes"),
    ]


def test_old_notes_stay_readable_and_add_nothing(stores):
    data, ledgers, notes = stores
    old = stored_note([])
    del old["items"]
    write_chunk(data, "w1", old, version=schemas.NOTES_SCHEMA_WITHOUT_ITEMS)
    summary = checked_apply_notes(notes, ledgers)
    assert (summary["notes_that_cannot_name_items"], summary["entries_added"]) == (1, 0)


def test_an_unknown_notes_version_raises(stores):
    data, ledgers, notes = stores
    write_chunk(data, "w1", stored_note([]), version=99)
    with pytest.raises(ledger.LedgerError):
        checked_apply_notes(notes, ledgers)


def test_a_bad_stored_item_raises(stores):
    data, ledgers, notes = stores
    write_chunk(data, "w1", stored_note([{"kind": "memory", "name": "x", "stance": "unused"}]))
    with pytest.raises(schemas.SchemaError):
        checked_apply_notes(notes, ledgers)


def test_a_flag_edits_no_ledger(stores):
    data, ledgers, notes = stores
    write_chunk(data, "w1", stored_note([named()], "said", "this is wrong", schemas.QUOTE_VERIFIED, "user"))
    checked_apply_notes(notes, ledgers)
    path = ledger.ledger_path(ledgers, ITEM)
    before = open(path, "rb").read()
    flags = ledger.write_flags(ledgers, NOW, RULE)
    assert [flag["identity"]["name"] for flag in flags] == ["some-memory"]
    assert open(path, "rb").read() == before
    with open(os.path.join(ledgers, ledger.FLAGS_FILE), encoding="utf-8") as handle:
        assert json.load(handle)["flags"] == flags
