"""A window read again, a hook's one-off fault, what the page says about a quiet ledger, and the check's
model. All names and texts are invented."""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import ledger
import review_data
import review_page
import schemas
import stance_check
from config import LedgerConfig, load_config
from test_every_stance_checked import Answering, check_prompt, extract_prompt, page_after_a_weekly_pass
from test_item_names_and_stances import data_file, entries_of, run_daily_with, stance_note, write_inventory
from test_ledger import ITEM, checked_apply_notes, named, stored_note, write_chunk, stores  # noqa: F401 (stores is a fixture)
from test_weekly import NOW, SECOND_SESSION, add_session, chat, tree  # noqa: F401 (tree is a fixture)


# --- Notes deleted and written again, with the ledgers left as they were ---


def note_with(what, *items):
    return {**stored_note(list(items)), "what": what}


def old_reading_then_new(data, notes, ledgers, old, new):
    """What the revalidation copy did: the ledgers kept, the notes folder deleted, the window read again."""
    write_chunk(data, "w1", *old)
    checked_apply_notes(notes, ledgers)
    shutil.rmtree(os.path.join(data, "notes", "2030-05-30", "w1"))
    write_chunk(data, "w1", *new)


def test_an_entry_left_behind_when_its_notes_were_replaced_is_reported(stores):
    data, ledgers, notes = stores
    old = [note_with("About plums."), note_with("Old text on the item.", named())]
    new = [note_with("New text on the item.", named()), note_with("About pears.")]
    old_reading_then_new(data, notes, ledgers, old, new)
    problems = []
    checked_apply_notes(notes, ledgers, problems)
    assert len(problems) == 1
    assert "no longer holds" in problems[0]["detail"]


def test_an_entry_left_behind_raises_when_no_list_is_kept(stores):
    data, ledgers, notes = stores
    old_reading_then_new(data, notes, ledgers, [note_with("Old text on the item.", named())], [note_with("About pears.")])
    with pytest.raises(ledger.LedgerError, match="no longer holds"):
        checked_apply_notes(notes, ledgers)


def test_an_entry_whose_notes_file_is_gone_is_reported(stores):
    data, ledgers, notes = stores
    write_chunk(data, "w1", note_with("Old text on the item.", named()))
    checked_apply_notes(notes, ledgers)
    shutil.rmtree(os.path.join(data, "notes", "2030-05-30", "w1"))
    problems = []
    ledger.apply_notes(notes, ledgers, problems)
    assert len(problems) == 1 and "no longer holds" in problems[0]["detail"]


def test_the_same_place_with_other_text_is_not_taken_as_already_there(stores):
    data, ledgers, notes = stores
    old_reading_then_new(data, notes, ledgers, [note_with("Old text on the item.", named())], [note_with("New text on the item.", named())])
    problems = []
    summary = checked_apply_notes(notes, ledgers, problems)
    assert summary["entries_already_present"] == 0
    assert problems and all("no longer holds" in problem["detail"] for problem in problems)
    assert [entry["what"] for entry in ledger.load_ledger(ledgers, ITEM)["entries"]] == ["Old text on the item."]


def test_entries_that_still_match_their_notes_report_nothing(stores):
    data, ledgers, notes = stores
    write_chunk(data, "w1", note_with("Text on the item.", named()))
    checked_apply_notes(notes, ledgers)
    problems = []
    ledger.apply_notes(notes, ledgers, problems)
    assert problems == []
    assert len(ledger.load_ledger(ledgers, ITEM)["entries"]) == 1


def test_an_id_depends_on_the_text_of_the_note():
    base = {"last": "2030-05-30T10:00:00+00:00", "session_id": "s", "project_folder": "f"}

    def id_for(what):
        made = {**stored_note([]), "what": what}
        return ledger._entry_of(made, ITEM, base, "notes/d/w/chunk-001.json", 3, "against", False, False)["id"]

    assert id_for("One text.") != id_for("Another text.")
    assert id_for("One text.") == id_for("One text.")


def test_a_verdict_on_another_notes_text_makes_no_entry(stores):
    data, ledgers, notes = stores
    write_chunk(data, "w1", note_with("New text on the item.", named()))
    window = Path(data, "notes", "2030-05-30", "w1")
    (window / ledger.STANCE_CHECKS_FILE).write_text(json.dumps({"schema_version": ledger.STANCE_CHECKS_SCHEMA_VERSION, "checks": {"chunk-001.json#0#0": {
        "stance": "against", "final": "against", "verdict": "kept", "quote_about_item": False, "rule_broken": False, "malfunction": False,
        "reason": "made up", "item": ITEM.to_json(), "what": "Old text on the item.", "run_id": "old",
    }}}), encoding="utf-8")
    problems = []
    ledger.apply_notes(notes, ledgers, problems)
    assert ledger.load_ledger(ledgers, ITEM)["entries"] == []
    assert len(problems) == 1 and "another note" in problems[0]["detail"]


# --- A hook's or tool's own fault, once in a session ---

FAULT = {"kettle_gate": {"malfunction": True, "reason": "it read a stale state and blocked correct work once"}}


def fault_note(what="The kettle gate read a stale state and blocked a finished reply once, so it was sent again."):
    return stance_note(("hook", "kettle_gate", "no_bearing"), what=what)


def test_a_fault_is_on_record_apart_and_counts_for_nothing(tree):
    write_inventory(tree)
    result = run_daily_with(tree, Answering(fault_note(), answers=FAULT))
    entry, = entries_of(tree, "hook", "kettle_gate")
    assert entry["direction"] == schemas.DIRECTION_MALFUNCTION
    assert result["stance_check"]["malfunction"] == 1
    assert result["ledger"]["notes"]["malfunctions_added"] == 1
    assert result["ledger"]["notes"]["entries_added"] == 0
    assert result["ledger"]["revision_flags"] == 0
    assert data_file(tree, ledger.VERDICTS_FILE)["mentions"][0]["malfunction"] is True


def test_many_faults_across_sessions_flag_nothing_and_clear_nothing():
    rule = LedgerConfig(1, 3, 28, 0.5, 28, (), ())

    def entry(entry_id, session, direction):
        return {"id": entry_id, "date": NOW.isoformat(), "session": session, "project_folder": "f", "direction": direction, "who": "agent", "basis": "inferred",
                "what": "x", "quote": "", "quote_check": schemas.QUOTE_NONE, "origin_of_point": "hook", "source": {"notes": f"n/{entry_id}", "note_index": 0}}

    faults = [entry(f"m{n}", f"s{n}", schemas.DIRECTION_MALFUNCTION) for n in range(9)]
    assert ledger.lost_balance({"identity": {}, "entries": faults}, NOW, rule) is None
    against = [entry(f"a{n}", f"s{n}", "against") for n in range(3)]
    assert ledger.lost_balance({"identity": {}, "entries": [*against, *faults]}, NOW, rule)["reason"] == ledger.REASON_INFERRED


def test_a_fault_is_added_once_and_goes_with_its_window(tree):
    write_inventory(tree)
    run_daily_with(tree, Answering(fault_note(), answers=FAULT))
    ledgers_dir = ledger.ledgers_dir_of(tree.paths.data_dir)
    notes_dir = str(Path(tree.paths.data_dir, "notes"))
    assert ledger.apply_notes(notes_dir, ledgers_dir)["malfunctions_added"] == 0
    window = next(Path(notes_dir).glob("*/*"))
    assert ledger.discard_entries_from_notes(ledgers_dir, f"notes/{window.parent.name}/{window.name}/") == 1


@pytest.mark.parametrize("name,kind,answer", [
    ("kettle_gate", "hook", {"verdict": "raised", "stance": "against", "malfunction": True}),
    ("kettle_gate", "hook", {"malfunction": True, "rule_broken": True}),
    ("biscuits", "memory", {"malfunction": True}),
    ("tea-brewing", "skill", {"malfunction": True}),
])
def test_a_fault_that_does_not_fit_is_dropped_and_fails_the_run(tree, name, kind, answer):
    write_inventory(tree)
    result = run_daily_with(tree, Answering(stance_note((kind, name, "no_bearing")), answers={name: answer}))
    assert result["status"] == "failed"
    assert result["stance_check"]["dropped"] == 1
    assert [item["id"] for item in result["dropped_verdicts"]] == ["s1"]


def test_the_field_is_required_and_must_be_true_or_false():
    good = {"id": "s1", "verdict": "kept", "stance": "no_bearing", "quote_about_item": False, "rule_broken": False, "malfunction": False, "reason": "x"}
    assert schemas.parse_stance_verdicts(json.dumps({"verdicts": [good]}))[0].malfunction is False
    for bad in ({key: value for key, value in good.items() if key != "malfunction"}, {**good, "malfunction": "no"}):
        with pytest.raises(schemas.SchemaError):
            schemas.parse_stance_verdicts(json.dumps({"verdicts": [bad]}))


def test_verdicts_from_before_this_field_are_old_and_rejudge_clears_them(tree):
    write_inventory(tree)
    run_daily_with(tree, Answering(stance_note(("skill", "tea-brewing", "for"))))
    window = next(Path(tree.paths.data_dir, "notes").glob("*/*"))
    held = json.loads((window / ledger.STANCE_CHECKS_FILE).read_text(encoding="utf-8"))
    (window / ledger.STANCE_CHECKS_FILE).write_text(json.dumps({**held, "schema_version": 2}), encoding="utf-8")
    with pytest.raises(ledger.LedgerError, match="rejudge-old"):
        ledger.read_stance_checks(str(window))
    assert stance_check.rejudge_old(tree) == {"verdict_files_removed": 1, "ledger_entries_removed": 1}


def test_the_review_page_counts_a_fault_across_sessions_per_item(tree):
    write_inventory(tree)
    add_session(tree, SECOND_SESSION, chat("a second session", 30))
    page = page_after_a_weekly_pass(tree, Answering(fault_note("The kettle gate blocked a finished reply once."), answers=FAULT))
    review = review_data.latest_review(tree.paths.data_dir)
    summary, = [item["summary"] for item in review["failures"] if item["kind"] == review_data.KIND_MALFUNCTION]
    assert "hook kettle_gate" in summary and "2 times in 2 sessions" in summary
    assert "The kettle gate blocked a finished reply once." in summary and "not counted" in summary
    assert "A fault of its own" in page
    assert "Something failed (malfunction)" not in page


def test_a_fault_older_than_the_window_is_not_counted(tree):
    write_inventory(tree)
    run_daily_with(tree, Answering(fault_note(), answers=FAULT))
    later = datetime(2030, 1, 1, tzinfo=timezone.utc) + timedelta(days=4000)
    signals = review_data._signals(tree.paths.data_dir, tree.ledger.inferred_window_days, later)
    assert [signal for signal in signals if signal["kind"] == review_data.KIND_MALFUNCTION] == []


def test_an_earlier_ruling_shows_a_fault_to_the_next_check():
    line = stance_check._ruling_line({"final": "no_bearing", "rule_broken": False, "malfunction": True, "what": "It blocked once.", "reason": "stale state"})
    assert "fault of its own" in line


# --- The two prompts ---


@pytest.mark.parametrize("read", [extract_prompt, check_prompt])
def test_both_prompts_tighten_for_route_a(read):
    prompt = read()
    for words in ("A reply about something else does not count as accepting", "must be in scope for the task at hand", "default must really have differed"):
        assert words in prompt, words


def test_the_reader_reports_a_faults_single_occurrence():
    prompt = extract_prompt()
    assert "own behaviour went wrong once" in prompt
    assert "Do report a hook's, tool server's or plugin's own fault" in prompt


def test_the_check_prompt_asks_for_the_fault_field():
    prompt = check_prompt()
    assert '"malfunction"' in prompt and "`malfunction`" in prompt


def test_the_check_prompt_says_to_settle_before_replying_because_a_correction_after_the_json_fails_the_call():
    assert "Settle every verdict before you start the reply" in check_prompt()
    with pytest.raises(schemas.SchemaError, match="single JSON"):
        schemas.parse_stance_verdicts('{"verdicts": []}\n\nCorrection: the verdict above is wrong.\n\n{"verdicts": []}')


# --- What the page says about a quiet ledger ---


def test_the_ledger_summary_says_a_quiet_ledger_shows_little():
    summary = {"founding_reason": "A reason.", "founding_status": "unverified", "entries_for": 0, "entries_against": 0, "file": "ledgers/x.json", "latest": []}
    text = review_page._ledger({"ledger": summary})
    assert "A missing &quot;for&quot; means little" in text
    assert "A quiet ledger does not show" in text
    assert "reaction" in text


# --- The check's model ---


def test_the_check_runs_on_sonnet():
    assert load_config().item_check.model == "sonnet"
