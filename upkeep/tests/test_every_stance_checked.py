"""The stance check judges every stance, in both directions; what direct means; rules broken at a cost;
and what reaches the review page. All names and texts are invented."""
from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import daily
import extract
import ledger
import model_call
import review_data
import schemas
import stance_check
import weekly_notes
from conftest import SESSION_ID, stance_reply
from config import LedgerConfig
from test_item_names_and_stances import Reader, data_file, entries_of, run_daily_with, stance_note, write_inventory
from test_weekly import (
    DRY, NOW, PROJECT, SECOND_SESSION, FakeCall, add_session, chat, mark_daily_done, note, run,
    tree,  # noqa: F401 (a fixture)
)


class Answering(Reader):
    """Reads each session into these notes, and answers the check as told, by item name."""

    def __init__(self, *notes, answers=None, fail_on_call=None):
        super().__init__(*notes)
        self.answers = answers or {}
        self.fail_on_call = fail_on_call

    def __call__(self, **kwargs):
        if not kwargs["prompt"].startswith("You are judging"):
            return super().__call__(**kwargs)
        self.calls.append(kwargs)
        if self.fail_on_call is not None and len(self.stance_calls()) == self.fail_on_call:
            raise model_call.ModelCallError("this call fails")
        return model_call.ModelResult(
            text=stance_reply(kwargs["stdin_text"], answers=self.answers),
            usage={"input_tokens": 1, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 1},
            model_usage={"m": {}}, cost_usd=0.25, duration_ms=1, num_turns=1, command_line=("claude",),
        )


def judged(config):
    return data_file(config, ledger.VERDICTS_FILE)["mentions"]


def said_note(*items, quote="print reports short"):
    return note(type="preference", what="The user wants a thing done.", evidence="USER-TYPED", memory_candidate=False, endorsement="said",
                endorsement_quote=quote, origin_of_point="user", route="none",
                items=[dict(zip(("kind", "name", "stance"), item)) for item in items])


# --- Every stance is checked, and may move either way ---


def test_a_no_bearing_can_be_raised_and_then_makes_an_entry(tree):
    write_inventory(tree)
    raised = {"tea-brewing": {"verdict": "raised", "stance": "for", "reason": "its step two changed the work and it was accepted"}}
    result = run_daily_with(tree, Answering(stance_note(("skill", "tea-brewing", "no_bearing")), answers=raised))
    assert [entry["direction"] for entry in entries_of(tree, "skill", "tea-brewing")] == ["for"]
    assert result["stance_check"]["raised"] == 1
    assert result["ledger"]["notes"]["mentions_raised"] == 1
    assert [(item["stance"], item["final"], item["verdict"], item["reason"]) for item in judged(tree)] == [
        ("no_bearing", "for", "raised", "its step two changed the work and it was accepted")
    ]


def test_a_no_bearing_kept_makes_no_entry_and_is_on_record(tree):
    write_inventory(tree)
    result = run_daily_with(tree, Answering(stance_note(("hook", "kettle_gate", "no_bearing"))))
    assert entries_of(tree, "hook", "kettle_gate") == []
    assert [(item["final"], item["verdict"]) for item in judged(tree)] == [("no_bearing", "kept")]
    assert result["ledger"]["notes"]["mentions_awaiting_check"] == 0


def test_an_unjudged_no_bearing_waits_like_any_other(tree):
    write_inventory(tree)
    failing = Reader(stance_note(("hook", "kettle_gate", "no_bearing")), stance_error=model_call.ModelCallError("no"))
    result = run_daily_with(tree, failing)
    assert result["ledger"]["notes"]["mentions_awaiting_check"] == 1


@pytest.mark.parametrize("verdict", ["lowered", "refused"])
def test_a_stance_lowered_or_refused_makes_no_entry_and_is_on_record(tree, verdict):
    write_inventory(tree)
    answer = {"tea-brewing": {"verdict": verdict, "stance": "no_bearing", "quote_about_item": False, "reason": "not enough here"}}
    result = run_daily_with(tree, Answering(stance_note(("skill", "tea-brewing", "for")), answers=answer))
    assert entries_of(tree, "skill", "tea-brewing") == []
    assert result["stance_check"][verdict] == 1
    assert result["ledger"]["notes"][f"mentions_{verdict}"] == 1
    assert [(item["final"], item["verdict"], item["reason"]) for item in judged(tree)] == [("no_bearing", verdict, "not enough here")]


def test_a_stance_reversed_makes_an_entry_the_other_way(tree):
    write_inventory(tree)
    answer = {"tea-brewing": {"verdict": "reversed", "stance": "against", "reason": "the note shows harm, not help"}}
    run_daily_with(tree, Answering(stance_note(("skill", "tea-brewing", "for")), answers=answer))
    assert [entry["direction"] for entry in entries_of(tree, "skill", "tea-brewing")] == ["against"]


@pytest.mark.parametrize("stance,answer", [
    ("for", {"verdict": "kept", "stance": "against"}),
    ("no_bearing", {"verdict": "raised", "stance": "no_bearing"}),
    ("for", {"verdict": "raised", "stance": "against"}),
    ("no_bearing", {"verdict": "lowered", "stance": "no_bearing"}),
    ("no_bearing", {"verdict": "refused", "stance": "no_bearing"}),
    ("for", {"verdict": "lowered", "stance": "against"}),
    ("for", {"verdict": "reversed", "stance": "for"}),
    ("for", {"verdict": "reversed", "stance": "no_bearing"}),
    ("for", {"verdict": "kept", "stance": "for", "rule_broken": True}),
    ("for", {"verdict": "kept", "stance": "for", "quote_about_item": True}),
])
def test_a_verdict_that_does_not_fit_its_stance_fails_the_pass_and_records_nothing(tree, stance, answer):
    write_inventory(tree)
    result = run_daily_with(tree, Answering(stance_note(("skill", "tea-brewing", stance)), answers={"tea-brewing": answer}))
    assert result["status"] == daily.STATUS_FAILED
    assert [item["name"] for item in result["dropped_verdicts"]] == ["tea-brewing"]
    assert entries_of(tree, "skill", "tea-brewing") == []
    assert result["ledger"]["notes"]["mentions_awaiting_check"] == 1


def test_a_verdict_with_a_field_too_many_or_too_few_is_refused_by_the_schema():
    good = {"id": "s1", "verdict": "kept", "stance": "for", "quote_about_item": False, "rule_broken": False, "malfunction": False, "reason": "x"}
    assert schemas.parse_stance_verdicts(json.dumps({"verdicts": [good]}))[0].verdict == "kept"
    for bad in ({**good, "extra": 1}, {key: value for key, value in good.items() if key != "stance"}, {**good, "verdict": "holds"}, {**good, "rule_broken": "no"}, {**good, "quote_about_item": 1}):
        with pytest.raises(schemas.SchemaError):
            schemas.parse_stance_verdicts(json.dumps({"verdicts": [bad]}))


def test_the_weekly_reading_takes_the_final_stance(tree):
    write_inventory(tree)
    raised = {"biscuits": {"verdict": "raised", "stance": "against", "reason": "the user rejected it"}}
    run_daily_with(tree, Answering(stance_note(("memory", "biscuits", "no_bearing")), answers=raised))
    path = next(Path(tree.paths.data_dir, "notes").glob("*/*/chunk-001.json"))
    window = weekly_notes.Window("k", "s", PROJECT, "/w", NOW, NOW, None)
    records = weekly_notes._records_of_chunk(str(path), window, tree.paths.data_dir)
    assert records[0].items[0]["stance"] == schemas.STANCE_AGAINST
    assert weekly_notes.is_memory_note(records[0], tree.weekly)


# --- Groups, and like cases alike ---


def test_a_long_list_goes_in_several_calls_each_item_whole_and_all_paid_for(tree):
    write_inventory(tree)
    small = dataclasses.replace(tree, item_check=dataclasses.replace(tree.item_check, group_chars=1))
    notes = [stance_note(("skill", "tea-brewing", "for")), stance_note(("hook", "kettle_gate", "no_bearing")), stance_note(("skill", "tea-brewing", "no_bearing"))]
    reader = Answering(*notes)
    add_session(small, SESSION_ID, chat(), PROJECT)
    result = daily.run_daily(small, "reading", call=reader)
    calls = reader.stance_calls()
    assert len(calls) == 2, "one call per item, when each is over the limit"
    assert sum(call["stdin_text"].count('"name": "tea-brewing"') for call in calls) == 2
    assert all('"name": "tea-brewing"' not in call["stdin_text"] or '"name": "kettle_gate"' not in call["stdin_text"] for call in calls)
    assert result["stance_check"]["cost_usd"] == pytest.approx(0.5)
    assert result["stance_check"]["calls"] == 2
    assert result["stance_check"]["kept"] == 3


def test_verdicts_of_a_finished_call_stay_when_a_later_call_fails(tree):
    write_inventory(tree)
    small = dataclasses.replace(tree, item_check=dataclasses.replace(tree.item_check, group_chars=1))
    reader = Answering(stance_note(("skill", "tea-brewing", "for")), stance_note(("hook", "kettle_gate", "no_bearing")), fail_on_call=2)
    add_session(small, SESSION_ID, chat(), PROJECT)
    result = daily.run_daily(small, "reading", call=reader)
    assert result["status"] == daily.STATUS_FAILED
    assert len(judged(small)) == 1
    assert result["ledger"]["notes"]["mentions_awaiting_check"] == 1


def test_a_later_pass_sees_how_the_same_item_was_ruled_on_and_no_other(tree):
    write_inventory(tree)
    answer = {"kettle_gate": {"verdict": "raised", "stance": "against", "reason": "it blocked good work again and again"}}
    run_daily_with(tree, Answering(stance_note(("hook", "kettle_gate", "no_bearing"), what="The gate kept blocking a kept promise."), stance_note(("skill", "tea-brewing", "no_bearing"), what="The tea came up."), answers=answer))
    add_session(tree, SECOND_SESSION, chat(), PROJECT)
    second = Answering(stance_note(("hook", "kettle_gate", "no_bearing"), what="The gate blocked once more."))
    # The first session's window is finished, so only the new note is pending.
    daily.run_daily(tree, "second", call=second)
    text = second.stance_calls()[0]["stdin_text"]
    assert "it blocked good work again and again" in text
    assert "The gate kept blocking a kept promise." in text
    assert "The tea came up." not in text


def test_earlier_rulings_are_limited_by_config(tree):
    write_inventory(tree)
    none_shown = dataclasses.replace(tree, item_check=dataclasses.replace(tree.item_check, earlier_rulings_shown=0))
    answer = {"kettle_gate": {"verdict": "raised", "stance": "against", "reason": "it blocked good work again and again"}}
    run_daily_with(none_shown, Answering(stance_note(("hook", "kettle_gate", "no_bearing")), answers=answer))
    add_session(none_shown, SECOND_SESSION, chat(), PROJECT)
    second = Answering(stance_note(("hook", "kettle_gate", "no_bearing"), what="The gate blocked once more."))
    daily.run_daily(none_shown, "second", call=second)
    assert "it blocked good work again and again" not in second.stance_calls()[0]["stdin_text"]


# --- Direct means the user's words are about this item ---


def test_a_said_quote_about_something_else_is_inferred_not_direct(tree):
    write_inventory(tree)
    elsewhere = {"tea-brewing": {"quote_about_item": False}}
    run_daily_with(tree, Answering(said_note(("skill", "tea-brewing", "against")), answers=elsewhere), records=chat())
    entry, = entries_of(tree, "skill", "tea-brewing")
    assert (entry["who"], entry["basis"], entry["quote"], entry["quote_check"]) == ("agent", "inferred", "", schemas.QUOTE_NONE)
    assert ledger.lost_balance({"identity": {}, "entries": [entry]}, NOW, tree.ledger) is None, "one inferred entry against does not flag"


def test_a_said_quote_about_this_item_is_direct(tree):
    write_inventory(tree)
    run_daily_with(tree, Answering(said_note(("skill", "tea-brewing", "against")), answers={"tea-brewing": {"quote_about_item": True}}), records=chat())
    entry, = entries_of(tree, "skill", "tea-brewing")
    assert (entry["who"], entry["basis"], entry["quote"]) == ("user", "direct_statement", "print reports short")
    assert ledger.lost_balance({"identity": {}, "entries": [entry]}, NOW, tree.ledger)["reason"] == ledger.REASON_DIRECT


def test_a_said_for_about_something_else_does_not_hold_inferred_flags_back():
    rule = LedgerConfig(1, 3, 28, 0.5, 28, (), ())
    base = {"session": "s", "project_folder": "f", "what": "x", "origin_of_point": "user", "date": NOW.isoformat()}
    note_values = {"quote_check": schemas.QUOTE_VERIFIED, "endorsement": "said", "endorsement_quote": "some words here"}
    who, basis, quoted, quote_check = ledger._attribution(note_values, about_item=False)
    support = {**base, "id": "f", "session": "s9", "direction": "for", "who": who, "basis": basis, "quote": quoted, "quote_check": quote_check, "source": {"notes": "n/f", "note_index": 0}}
    against = [{**base, "id": f"a{n}", "session": f"s{n}", "direction": "against", "who": "agent", "basis": "inferred", "quote": "", "quote_check": schemas.QUOTE_NONE, "source": {"notes": f"n/{n}", "note_index": 0}} for n in range(4)]
    assert ledger.lost_balance({"identity": {}, "entries": [*against, support]}, NOW + timedelta(days=1), rule)["reason"] == ledger.REASON_INFERRED


def test_accepted_stays_with_the_user_and_counted_as_inferred_whatever_the_flag():
    note_values = {"quote_check": schemas.QUOTE_VERIFIED, "endorsement": "accepted", "endorsement_quote": "yes go on"}
    assert ledger._attribution(note_values, about_item=False) == ("user", "accepted", "yes go on", schemas.QUOTE_VERIFIED)


# --- A rule broken at a cost: on record, and counted for nothing ---

BROKEN = {"biscuits": {"rule_broken": True, "reason": "the rule was left out and the batch was made again"}}


def broken_note(what="The assistant put the biscuits on the right, against the rule, and redid the tray."):
    return stance_note(("memory", "biscuits", "no_bearing"), what=what)


def test_a_rule_broken_at_a_cost_is_in_the_ledger_and_counts_for_nothing(tree):
    write_inventory(tree)
    result = run_daily_with(tree, Answering(broken_note(), answers=BROKEN))
    entry, = entries_of(tree, "memory", "biscuits", ledger.project_scope(PROJECT))
    assert entry["direction"] == schemas.DIRECTION_RULE_BROKEN
    assert result["stance_check"]["rule_broken"] == 1
    assert result["ledger"]["notes"]["rule_broken_added"] == 1
    assert result["ledger"]["notes"]["entries_added"] == 0
    assert result["ledger"]["revision_flags"] == 0


def test_many_rules_broken_flag_nothing_and_clear_nothing():
    rule = LedgerConfig(1, 3, 28, 0.5, 28, (), ())

    def entry(entry_id, session, direction, basis="inferred"):
        user = basis != "inferred"
        return {"id": entry_id, "date": NOW.isoformat(), "session": session, "project_folder": "f", "direction": direction, "who": "user" if user else "agent", "basis": basis,
                "what": "x", "quote": "q" if user else "", "quote_check": schemas.QUOTE_VERIFIED if user else schemas.QUOTE_NONE, "origin_of_point": "user", "source": {"notes": f"n/{entry_id}", "note_index": 0}}

    breaches = [entry(f"b{n}", f"s{n}", schemas.DIRECTION_RULE_BROKEN) for n in range(9)]
    assert ledger.lost_balance({"identity": {}, "entries": breaches}, NOW, rule) is None
    direct_breach = entry("d", "s99", schemas.DIRECTION_RULE_BROKEN, "direct_statement")
    assert ledger.lost_balance({"identity": {}, "entries": [direct_breach]}, NOW, rule) is None
    against = [entry(f"a{n}", f"s{n}", "against") for n in range(3)]
    assert ledger.lost_balance({"identity": {}, "entries": [*against, direct_breach]}, NOW, rule)["reason"] == ledger.REASON_INFERRED


def test_a_rule_broken_entry_is_added_once_and_goes_with_its_window(tree):
    write_inventory(tree)
    run_daily_with(tree, Answering(broken_note(), answers=BROKEN))
    ledgers_dir = ledger.ledgers_dir_of(tree.paths.data_dir)
    notes_dir = str(Path(tree.paths.data_dir, "notes"))
    again = ledger.apply_notes(notes_dir, ledgers_dir)
    assert again["rule_broken_added"] == 0
    assert len(entries_of(tree, "memory", "biscuits", ledger.project_scope(PROJECT))) == 1
    window = next(Path(notes_dir).glob("*/*"))
    assert ledger.discard_entries_from_notes(ledgers_dir, f"notes/{window.parent.name}/{window.name}/") == 1


def test_a_note_can_hold_a_stance_on_one_item_and_a_broken_rule_on_another(tree):
    write_inventory(tree)
    both = stance_note(("memory", "biscuits", "no_bearing"), ("skill", "tea-brewing", "for"))
    run_daily_with(tree, Answering(both, answers=BROKEN))
    assert [entry["direction"] for entry in entries_of(tree, "memory", "biscuits", ledger.project_scope(PROJECT))] == [schemas.DIRECTION_RULE_BROKEN]
    assert [entry["direction"] for entry in entries_of(tree, "skill", "tea-brewing")] == ["for"]


# --- What reaches the review page ---


def page_after_a_weekly_pass(config, reader):
    run_daily_with(config, reader)
    mark_daily_done(config)
    run(config, DRY, FakeCall(), now=NOW)
    # The window counts back from now, the sessions are dated 2030 and the usage log by the real clock.
    page = review_data.refresh_review(config, datetime.now(timezone.utc))
    return Path(page).read_text(encoding="utf-8")


def test_the_review_page_shows_the_counts_and_the_cost_of_the_check(tree):
    write_inventory(tree)
    answers = {
        "tea-brewing": {"verdict": "raised", "stance": "for"},
        "biscuits": {"verdict": "refused", "stance": "no_bearing", "quote_about_item": False},
    }
    page = page_after_a_weekly_pass(tree, Answering(stance_note(("skill", "tea-brewing", "no_bearing"), ("memory", "biscuits", "against"), ("hook", "kettle_gate", "no_bearing")), answers=answers))
    review = review_data.latest_review(tree.paths.data_dir)
    summary = next(item["summary"] for item in review["failures"] if item["kind"] == review_data.KIND_STANCE_CHECK)
    assert "3 stances" in summary and "1 kept" in summary and "1 raised" in summary and "0 lowered" in summary and "1 refused" in summary and "0 reversed" in summary
    assert "$0.25" in summary
    assert ledger.VERDICTS_FILE in summary
    assert summary in page.replace("&#x27;", "'")
    assert "Something failed (stance_check)" not in page


def test_the_review_page_lists_a_rule_broken_with_its_count(tree):
    write_inventory(tree)
    page = page_after_a_weekly_pass(tree, Answering(broken_note(what="The tray was laid wrong and redone."), answers=BROKEN))
    review = review_data.latest_review(tree.paths.data_dir)
    summary = next(item["summary"] for item in review["failures"] if item["kind"] == review_data.KIND_RULE_BROKEN)
    assert "memory biscuits" in summary and "1 time" in summary and "The tray was laid wrong and redone." in summary and "not counted" in summary
    assert "Rule broken, with a cost" in page
    assert "Something failed (rule_broken)" not in page


def test_the_cost_counts_only_lines_of_the_check_and_inside_the_window(tree):
    log = Path(tree.paths.data_dir, "logs", "usage.jsonl")
    log.parent.mkdir(exist_ok=True)
    lines = [
        {"started": "2030-01-01T00:00:00+0000", "cost_usd": 9.0},
        {"at": "2030-01-01T00:00:00+0000", "session": "some-window", "cost_usd": 9.0},
        {"at": "2029-01-01T00:00:00+0000", "session": ledger.STANCE_USAGE_KEY, "cost_usd": 9.0},
        {"at": "2030-01-01T00:00:00+0000", "session": ledger.STANCE_USAGE_KEY, "cost_usd": 0.5},
    ]
    log.write_text("".join(json.dumps(line) + chr(10) for line in lines), encoding="utf-8")
    assert review_data._stance_cost(tree.paths.data_dir, datetime(2029, 12, 1, tzinfo=timezone.utc)) == pytest.approx(0.5)


def test_nothing_is_shown_when_nothing_was_judged(tree):
    write_inventory(tree)
    page = page_after_a_weekly_pass(tree, Reader(note()))
    assert "Stance check" not in page and "Rule broken" not in page


def test_old_verdicts_and_old_breaches_fall_out_of_the_page_with_the_window(tree):
    write_inventory(tree)
    run_daily_with(tree, Answering(broken_note(), answers=BROKEN))
    mark_daily_done(tree)
    later = datetime(2030, 1, 1, tzinfo=timezone.utc) + timedelta(days=4000)
    assert review_data._signals(tree.paths.data_dir, tree.ledger.inferred_window_days, later) == []


# --- Files from before this version of the check ---


def _old_style_window(config):
    run_daily_with(config, Answering(stance_note(("skill", "tea-brewing", "for"))))
    window = next(Path(config.paths.data_dir, "notes").glob("*/*"))
    (window / ledger.STANCE_CHECKS_FILE).write_text(json.dumps({"schema_version": 1, "checks": {"chunk-001.json#0#0": {"stance": "for", "verdict": "holds", "reason": "old", "item": "skill tea-brewing", "run_id": "old"}}}), encoding="utf-8")
    return window


def test_an_old_verdict_file_stops_the_pass_and_names_the_way_out(tree):
    write_inventory(tree)
    window = _old_style_window(tree)
    with pytest.raises(ledger.LedgerError, match="rejudge-old"):
        ledger.read_stance_checks(str(window))


def test_rejudge_old_forgets_old_verdicts_and_what_came_of_them_so_the_next_pass_judges_again(tree):
    write_inventory(tree)
    window = _old_style_window(tree)
    stale = Path(ledger.ledgers_dir_of(tree.paths.data_dir), "refused-stances.json")
    stale.write_text('{"schema_version": 1, "mentions": []}', encoding="utf-8")
    assert len(entries_of(tree, "skill", "tea-brewing")) == 1
    outcome = stance_check.rejudge_old(tree)
    assert outcome == {"verdict_files_removed": 1, "ledger_entries_removed": 1}
    assert not (window / ledger.STANCE_CHECKS_FILE).exists()
    assert not stale.exists()
    assert entries_of(tree, "skill", "tea-brewing") == []
    retry = Answering()
    assert daily.run_daily(tree, "again", call=retry)["status"] == daily.STATUS_OK
    assert len(retry.stance_calls()) == 1
    assert len(entries_of(tree, "skill", "tea-brewing")) == 1
    assert stance_check.rejudge_old(tree) == {"verdict_files_removed": 0, "ledger_entries_removed": 0}


# --- The prompts say it ---


def extract_prompt():
    return extract.read_prompt()


def check_prompt():
    return Path(stance_check.PROMPT_PATH).read_text(encoding="utf-8")


@pytest.mark.parametrize("read", [extract_prompt, check_prompt])
def test_both_prompts_hold_the_meaning_of_for(read):
    prompt = read()
    for words in (
        "ordinary default", "next reaction", "names the instruction", "in their own words", "as a general rule",
        "visibly changed an answer or decision", "merely loaded", "any assistant would have", "does not contain",
        "order just before", "a model saying", "Silence",
    ):
        assert words in prompt, words


@pytest.mark.parametrize("read", [extract_prompt, check_prompt])
def test_both_prompts_cover_a_hook_that_is_not_followed_and_like_cases_alike(read):
    prompt = read()
    for words in ("its own behaviour", "repeated work", "not followed", "however many"):
        assert words in prompt, words


@pytest.mark.parametrize("read", [extract_prompt, check_prompt])
def test_both_prompts_narrow_what_is_left_out_as_this_job(read):
    prompt = read()
    assert "is this job itself" in prompt
    assert "only evidence is this job's own report" in prompt
    assert "merely about this job" in prompt
    assert "the session discussing or building this upkeep job" not in prompt
    assert "a session discussing, building or testing this very job" not in prompt


def test_the_reader_may_note_an_instruction_that_changed_the_work_and_still_not_routine_progress():
    prompt = extract_prompt()
    assert "changed the work and was accepted, even when nothing went wrong" in prompt
    assert "Do not report routine progress" in prompt


def test_the_reader_names_a_broken_rule_without_a_stance():
    assert "went against this item and it cost work" in extract_prompt()


def test_the_check_prompt_asks_for_each_field_and_each_verdict():
    prompt = check_prompt()
    for words in ('"quote_about_item"', '"rule_broken"', '"stance"', "`kept`", "`raised`", "`lowered`", "`refused`", "`reversed`", "earlier ruling"):
        assert words in prompt, words


@pytest.mark.parametrize("read", [extract_prompt, check_prompt])
def test_examples_stay_on_an_invented_subject(read):
    assert "dough" in read()


def test_the_check_gets_each_item_whole_up_to_the_setting_not_a_short_description(tree):
    write_inventory(tree)
    reader = Answering(stance_note(("skill", "tea-brewing", "no_bearing")))
    run_daily_with(tree, reader)
    assert "Step 1: boil water." in reader.stance_calls()[0]["stdin_text"]


def test_config_carries_the_new_settings(tree):
    assert tree.item_check.group_chars > 0
    assert tree.item_check.earlier_rulings_shown >= 0
