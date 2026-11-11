"""A verdict that does not fit its stance is dropped alone, and the run still fails, loudly. A reply that
cannot be read as an answer to what was sent fails its call. All names and texts are invented."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

import daily
import ledger
import model_call
import review_data
import stance_check
import weekly
from conftest import SESSION_ID, stance_reply
from test_item_names_and_stances import Reader, entries_of, run_daily_with, stance_note, write_inventory
from test_weekly import (
    DRY, NOW, PROJECT, SECOND_SESSION, FakeCall, add_session, chat, note,
    tree,  # noqa: F401 (a fixture)
)

BAD = {"verdict": "reversed", "stance": "no_bearing", "reason": "the model's words"}
BAD_PROBLEM = "verdict 'reversed' does not fit 'for' becoming 'no_bearing'"
TEA_FOR = ("skill", "tea-brewing", "for")
GATE_FOR = ("hook", "kettle_gate", "for")


def result_of(text):
    return model_call.ModelResult(
        text=text, usage={"input_tokens": 1, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 1},
        model_usage={"m": {}}, cost_usd=0.25, duration_ms=1, num_turns=1, command_line=("claude",),
    )


class Scripted(Reader):
    """Reads each session into these notes. ``replies`` answers each stance call in turn: a dict of answers
    by item name, a function of the input giving the reply, or an error to raise. Past the end, all hold."""

    def __init__(self, *notes, replies=()):
        super().__init__(*notes)
        self.replies = list(replies)

    def __call__(self, **kwargs):
        if not kwargs["prompt"].startswith("You are judging"):
            return super().__call__(**kwargs)
        self.calls.append(kwargs)
        position = len(self.stance_calls()) - 1
        reply = self.replies[position] if position < len(self.replies) else {}
        if isinstance(reply, BaseException):
            raise reply
        return result_of(reply(kwargs["stdin_text"]) if callable(reply) else stance_reply(kwargs["stdin_text"], answers=reply))


def split_per_item(config):
    return dataclasses.replace(config, item_check=dataclasses.replace(config.item_check, group_chars=1))


def rejected_log(config):
    return Path(config.paths.data_dir, "logs", stance_check.REJECTED_REPLY)


def checks_of(config):
    found = {}
    for path in Path(config.paths.data_dir, "notes").glob(f"*/*/{ledger.STANCE_CHECKS_FILE}"):
        found.update(ledger.read_stance_checks(str(path.parent)))
    return found


# --- One verdict that does not fit is dropped alone ---


def test_the_others_are_stored_the_ledger_uses_them_and_the_run_still_fails(tree):
    write_inventory(tree)
    reader = Scripted(stance_note(TEA_FOR), stance_note(GATE_FOR), replies=[{"kettle_gate": BAD}])
    result = run_daily_with(tree, reader)
    assert result["status"] == daily.STATUS_FAILED
    assert daily.EXIT_CODES[result["status"]] == 1
    assert [entry["direction"] for entry in entries_of(tree, "skill", "tea-brewing")] == ["for"], "the settled one reached its ledger"
    assert entries_of(tree, "hook", "kettle_gate") == [], "a label and a stance that disagree are not repaired"
    assert [check["item"]["name"] for check in checks_of(tree).values()] == ["tea-brewing"]
    assert result["ledger"]["notes"]["mentions_kept"] == 1
    assert result["ledger"]["notes"]["mentions_awaiting_check"] == 1


def test_the_result_names_how_many_which_and_why_and_the_summary_counts_them(tree):
    write_inventory(tree)
    result = run_daily_with(tree, Scripted(stance_note(TEA_FOR), stance_note(GATE_FOR), replies=[{"kettle_gate": BAD}]))
    dropped, = result["dropped_verdicts"]
    assert (dropped["call"], dropped["id"], dropped["kind"], dropped["name"], dropped["problem"]) == (1, "s2", "hook", "kettle_gate", BAD_PROBLEM)
    assert dropped["stance_at"].endswith("chunk-001.json#1#0")
    assert result["stop_reason"] is None, "a stop_reason would stop the weekly pass, as a call that failed does"
    summary = result["stance_check"]
    assert (summary["stances_checked"], summary["kept"], summary["dropped"], summary["calls"]) == (2, 1, 1, 1)
    assert "the model's words" not in json.dumps(result["dropped_verdicts"])


def test_the_rejected_reply_is_still_written(tree):
    write_inventory(tree)
    run_daily_with(tree, Scripted(stance_note(TEA_FOR), stance_note(GATE_FOR), replies=[{"kettle_gate": BAD}]))
    assert "the model's words" in rejected_log(tree).read_text(encoding="utf-8")


def test_a_clean_reply_drops_nothing_and_writes_no_rejected_reply(tree):
    write_inventory(tree)
    result = run_daily_with(tree, Scripted(stance_note(TEA_FOR)))
    assert result["status"] == daily.STATUS_OK
    assert result["dropped_verdicts"] == []
    assert result["stance_check"]["dropped"] == 0
    assert not rejected_log(tree).exists()


def test_the_dropped_stance_alone_is_judged_again_and_then_counts(tree):
    write_inventory(tree)
    run_daily_with(tree, Scripted(stance_note(TEA_FOR), stance_note(GATE_FOR), replies=[{"kettle_gate": BAD}]))
    retry = Scripted()
    result = daily.run_daily(tree, "retry", call=retry)
    assert result["status"] == daily.STATUS_OK
    assert result["dropped_verdicts"] == []
    sent = retry.stance_calls()[0]["stdin_text"]
    assert '"name": "kettle_gate"' in sent and '"name": "tea-brewing"' not in sent
    assert [entry["direction"] for entry in entries_of(tree, "hook", "kettle_gate")] == ["for"]
    assert len(entries_of(tree, "skill", "tea-brewing")) == 1


def test_two_stances_in_one_note_keep_their_own_verdicts_across_the_two_runs(tree):
    write_inventory(tree)
    both = stance_note(TEA_FOR, GATE_FOR)
    run_daily_with(tree, Scripted(both, replies=[{"tea-brewing": BAD}]))
    assert [check["item"]["name"] for check in checks_of(tree).values()] == ["kettle_gate"]
    retry = Scripted(replies=[{"tea-brewing": {"verdict": "refused", "stance": "no_bearing", "reason": "no part in this"}}])
    assert daily.run_daily(tree, "retry", call=retry)["status"] == daily.STATUS_OK
    verdicts = {check["item"]["name"]: check["verdict"] for check in checks_of(tree).values()}
    assert verdicts == {"kettle_gate": "kept", "tea-brewing": "refused"}


def test_every_verdict_of_a_reply_can_be_dropped_and_each_is_listed(tree):
    write_inventory(tree)
    reader = Scripted(stance_note(TEA_FOR), stance_note(GATE_FOR), replies=[{"tea-brewing": BAD, "kettle_gate": BAD}])
    result = run_daily_with(tree, reader)
    assert [item["id"] for item in result["dropped_verdicts"]] == ["s1", "s2"]
    assert result["stance_check"]["dropped"] == 2
    assert checks_of(tree) == {}
    assert result["ledger"]["notes"]["mentions_awaiting_check"] == 2


# --- Several calls ---


def test_the_ids_of_two_calls_are_told_apart_and_both_replies_stay_in_the_log(tree):
    write_inventory(tree)
    small = split_per_item(tree)
    bad_one = {"tea-brewing": {**BAD, "reason": "the first reply"}}
    bad_two = {"kettle_gate": {**BAD, "reason": "the second reply"}}
    add_session(small, SESSION_ID, chat(), PROJECT)
    result = daily.run_daily(small, "reading", call=Scripted(stance_note(TEA_FOR), stance_note(GATE_FOR), replies=[bad_one, bad_two]))
    assert [(item["call"], item["id"], item["name"]) for item in result["dropped_verdicts"]] == [(1, "s1", "tea-brewing"), (2, "s1", "kettle_gate")]
    log = rejected_log(small).read_text(encoding="utf-8")
    assert "the first reply" in log and "the second reply" in log


def test_a_rejected_reply_of_an_earlier_run_is_not_kept_beside_this_runs(tree):
    write_inventory(tree)
    run_daily_with(tree, Scripted(stance_note(TEA_FOR), replies=[{"tea-brewing": {**BAD, "reason": "an old reply"}}]))
    daily.run_daily(tree, "retry", call=Scripted(replies=[{"tea-brewing": {**BAD, "reason": "a new reply"}}]))
    log = rejected_log(tree).read_text(encoding="utf-8")
    assert "a new reply" in log and "an old reply" not in log


@pytest.mark.parametrize("later", [
    model_call.ModelCallError("this call fails"),
    lambda stdin_text: "not json",
])
def test_a_later_call_failing_loses_neither_the_settled_nor_the_list_of_the_dropped(tree, later):
    write_inventory(tree)
    small = split_per_item(tree)
    third = ("memory", "biscuits", "for")
    add_session(small, SESSION_ID, chat(), PROJECT)
    result = daily.run_daily(small, "reading", call=Scripted(stance_note(TEA_FOR, GATE_FOR), stance_note(third), replies=[{"tea-brewing": BAD}, {}, later]))
    assert result["status"] == daily.STATUS_FAILED
    assert result["stance_check"] is None
    assert [item["name"] for item in result["dropped_verdicts"]] == ["tea-brewing"]
    assert result["stop_reason"].startswith("stance check: ")
    assert f"1 stance verdicts dropped: call 1 s1: {BAD_PROBLEM}" in result["stop_reason"]
    assert [check["item"]["name"] for check in checks_of(small).values()] == ["kettle_gate"]
    assert len(entries_of(small, "hook", "kettle_gate")) == 1
    assert result["ledger"]["notes"]["mentions_awaiting_check"] == 2


def test_a_dropped_verdict_outranks_the_budget_running_out_later(tree):
    write_inventory(tree)
    small = split_per_item(tree)
    add_session(small, SESSION_ID, chat(), PROJECT)
    result = daily.run_daily(small, "reading", call=Scripted(stance_note(TEA_FOR), stance_note(GATE_FOR), replies=[{"tea-brewing": BAD}, model_call.BudgetExhaustedError("spent")]))
    assert result["status"] == daily.STATUS_FAILED
    assert result["budget_stopped"] is True
    assert [item["id"] for item in result["dropped_verdicts"]] == ["s1"]


# --- What is not an answer to what was sent fails the call, as before ---


def stance_ids(stdin_text):
    return [json.loads(line)["id"] for line in stdin_text.split("<stances>")[1].split("</stances>")[0].strip().splitlines()]


def replying_with(ids_of):
    def reply(stdin_text):
        kept = {"verdict": "kept", "stance": "for", "quote_about_item": False, "rule_broken": False, "malfunction": False, "reason": "made up"}
        return json.dumps({"verdicts": [{"id": found, **kept} for found in ids_of(stance_ids(stdin_text))]})
    return reply


@pytest.mark.parametrize("reply", [
    lambda stdin_text: "not json",
    lambda stdin_text: '{"verdicts": [{"id": "s1", "verdict": "holds"}]}',
    replying_with(lambda ids: ids[:-1]),
    replying_with(lambda ids: [*ids, ids[0]]),
    replying_with(lambda ids: [*ids, "s99"]),
    replying_with(lambda ids: [*ids[:-1], "s99"]),
], ids=["unparseable", "bad_field", "missing", "duplicate", "extra", "wrong_id"])
def test_a_reply_that_does_not_answer_what_was_sent_fails_the_call_and_stores_nothing(tree, reply):
    write_inventory(tree)
    result = run_daily_with(tree, Scripted(stance_note(TEA_FOR), stance_note(GATE_FOR), replies=[reply]))
    assert result["status"] == daily.STATUS_FAILED
    assert result["stop_reason"].startswith("stance check: SchemaError")
    assert result["stance_check"] is None
    assert result["dropped_verdicts"] == []
    assert checks_of(tree) == {}
    assert entries_of(tree, "skill", "tea-brewing") == []
    assert result["ledger"]["notes"]["mentions_awaiting_check"] == 2
    assert rejected_log(tree).exists()


# --- The weekly pass, which runs the daily pass when none ended clean today ---


class WeeklyReader(FakeCall):
    """The weekly calls as FakeCall gives them; each session read into this note, and the check as told."""

    def __init__(self, read_note, answers):
        super().__init__()
        self.read_note = read_note
        self.answers = answers

    def __call__(self, **kwargs):
        prompt = kwargs["prompt"]
        if prompt.startswith("You are judging"):
            self.calls.append(kwargs)
            return result_of(stance_reply(kwargs["stdin_text"], answers=self.answers))
        if not kwargs["tools"] and not prompt.startswith(("You are preparing changes", "You are looking across", "You are checking")):
            self.calls.append(kwargs)
            return result_of(json.dumps({"notes": [self.read_note]}))
        return super().__call__(**kwargs)


def weekly_with_a_dropped_verdict(config):
    write_inventory(config)
    add_session(config, SESSION_ID, chat(), PROJECT)
    read_note = note(items=[{"kind": "skill", "name": "tea-brewing", "stance": "for"}, {"kind": "hook", "name": "kettle_gate", "stance": "for"}])
    reader = WeeklyReader(read_note, {"kettle_gate": BAD})
    return weekly.run_weekly(config, DRY, "run1", now=NOW, call=reader), reader


def test_the_weekly_pass_does_its_work_and_ends_failed_naming_what_was_dropped(tree):
    result, reader = weekly_with_a_dropped_verdict(tree)
    assert any(call["prompt"].startswith("You are preparing changes") for call in reader.calls), "the memory step ran"
    assert result["status"] == weekly.STATUS_FAILED
    assert result["stop_reason"] == f"the daily pass: 1 stance verdicts dropped: call 1 s2: {BAD_PROBLEM}"
    assert [item["name"] for item in result["dropped_verdicts"]] == ["kettle_gate"]
    assert result["daily"]["stop_reason"] is None
    assert [entry["direction"] for entry in entries_of(tree, "skill", "tea-brewing")] == ["for"]


def test_the_review_says_why_the_weekly_pass_failed_and_not_that_it_did_not_finish(tree):
    weekly_with_a_dropped_verdict(tree)
    failures = review_data.latest_review(tree.paths.data_dir)["failures"]
    summaries = " ".join(failure["summary"] for failure in failures)
    assert "1 stance verdicts dropped" in summaries
    assert "did not finish" not in summaries


def test_the_weekly_pass_with_nothing_dropped_lists_nothing(tree):
    write_inventory(tree)
    add_session(tree, SECOND_SESSION, chat(), PROJECT)
    result = weekly.run_weekly(tree, DRY, "run1", now=NOW, call=WeeklyReader(note(), {}))
    assert result["status"] == weekly.STATUS_OK
    assert result["dropped_verdicts"] == []


# --- The prompt ---


def test_the_prompt_keeps_reversed_apart_from_lowered_and_refused():
    prompt = Path(stance_check.PROMPT_PATH).read_text(encoding="utf-8")
    line = next(line for line in prompt.splitlines() if line.startswith("- `reversed`"))
    assert "never `no_bearing`" in line
    assert "`lowered` or `refused`" in line
