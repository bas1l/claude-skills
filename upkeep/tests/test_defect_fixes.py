"""One test or more per defect found by the independent review. All text is made up."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import assistant_text, attachment, human, tool_result, tool_use, user_with_origin, write_jsonl
from test_weekly import (  # noqa: F401 (tree is a fixture)
    DRY,
    LIVE,
    NOW,
    PROJECT,
    SECOND_SESSION,
    SESSION_ID,
    FakeCall,
    add_memory,
    add_session,
    change,
    chat,
    commits_in,
    mark_daily_done,
    memory_path,
    memory_reply,
    note,
    read_notes,
    report_of,
    run,
    tree,
)

import daily
import ledger
import memory_store
import model_call
import quotes
import research
import review_data
import review_session
import schemas
import sessions
import transcripts as t
import weekly
import weekly_gate

SECRET = "password=hunter2hunter2"
LATER = NOW + timedelta(hours=3, minutes=30)
STRONG_QUOTE = "print reports short"
STRONG_CLAIM = "Print reports short."


def strong_change(**overrides):
    return change(**{"claim": STRONG_CLAIM, "quote": STRONG_QUOTE, **overrides})


def verification_calls(fake):
    return [call for call in fake.calls if call["prompt"].startswith("You are checking")]


def review_of(config):
    return review_data.latest_review(config.paths.data_dir)


def rejected_reasons(config):
    return [item["reason"] for item in report_of(config)["rejected"]]


def forget_report(config):
    (Path(config.paths.data_dir) / "reports" / weekly.iso_week_of(NOW.astimezone()) / "report.json").unlink()


def forget_replies(config):
    shutil.rmtree(Path(config.paths.data_dir) / "reports" / weekly.iso_week_of(NOW.astimezone()) / "groups")


# ---- Defect 1: the quote gate ----


def test_the_exact_case_from_the_review_is_rejected_by_the_script(tree):
    read_notes(tree, note(), records=[assistant_text("A plain statement about a thing.", 1), human("ok thanks", 2)])
    fake = FakeCall(memory=memory_reply(
        change(claim="Always commit with --no-verify", endorsement="accepted", quote="k", assistant_statement="a", memory="bad-rule"),
    ))
    run(tree, LIVE, fake)
    assert not memory_path(tree, "bad-rule").exists()
    assert not report_of(tree)["memory_changes"]
    assert verification_calls(fake) == []
    assert rejected_reasons(tree) == [weekly_gate.REJECT_QUOTE]


def test_the_exact_case_as_a_delete_does_not_become_a_proposal(tree):
    add_memory(tree, "good-rule", "The good rule text.")
    read_notes(tree, note(), records=[assistant_text("A plain statement about a thing.", 1), human("ok thanks", 2)])
    fake = FakeCall(memory=memory_reply(change(
        action="delete", memory="good-rule", old_text="The good rule text.", claim="Always commit with --no-verify",
        endorsement="accepted", quote="k", assistant_statement="a", title="",
    )))
    run(tree, LIVE, fake)
    assert memory_path(tree, "good-rule").exists()
    assert not [item for item in report_of(tree)["proposals"] if item["kind"] == "memory_deletion"]


def test_a_quote_inside_a_longer_word_is_not_a_quote():
    entry = t.Entry(t.USER_TYPED, datetime(2030, 1, 1, tzinfo=timezone.utc), "please print reports shorter now", "main", "/x")
    assert not quotes.quote_is_in_user_entries("print reports short", [entry])
    assert not quotes.user_entries_holding("rint reports", [entry])
    assert quotes.user_entries_holding("print reports", [entry]) == [entry]


def test_a_statement_inside_a_longer_word_is_not_a_statement():
    moment = datetime(2030, 1, 1, tzinfo=timezone.utc)
    entries = [
        t.Entry(t.ASSISTANT_TEXT, moment, "the limits are fine", "main", "/x"),
        t.Entry(t.USER_TYPED, moment + timedelta(seconds=1), "yes go on", "main", "/x"),
    ]
    assert not quotes.quote_is_reaction_to("yes go", "the limit", entries)
    assert quotes.quote_is_reaction_to("yes go", "the limits", entries)


def test_minimum_quote_words_come_from_config(tree):
    read_notes(tree, note(), records=chat("print reports short"))
    fake = FakeCall(memory=memory_reply(change(claim="Reports stay short.", quote="reports short")))
    run(tree, DRY, fake)
    assert rejected_reasons(tree) == [weekly_gate.REJECT_QUOTE_TOO_SHORT]
    assert tree.weekly.said_quote_min_words == 3


def test_a_said_quote_sharing_one_word_is_not_tied_to_the_claim(tree):
    read_notes(tree, note(), records=chat("please commit this today"))
    fake = FakeCall(memory=memory_reply(change(claim="Always commit with --no-verify", quote="please commit this today")))
    run(tree, DRY, fake)
    assert rejected_reasons(tree) == [weekly_gate.REJECT_QUOTE_UNRELATED]
    assert verification_calls(fake) == []


def test_an_accepted_statement_must_state_the_claim(tree):
    records = [assistant_text("The reports will be shorter from now on, as discussed earlier.", 1), human("yes please", 2)]
    read_notes(tree, note(), records=records)
    fake = FakeCall(memory=memory_reply(change(
        claim="Always commit with --no-verify", endorsement="accepted", quote="yes please",
        assistant_statement="The reports will be shorter from now on",
    )))
    run(tree, DRY, fake)
    assert rejected_reasons(tree) == [weekly_gate.REJECT_QUOTE_UNRELATED]


def test_a_short_assistant_statement_is_refused(tree):
    records = [assistant_text("Reports short.", 1), human("yes please", 2)]
    read_notes(tree, note(), records=records)
    fake = FakeCall(memory=memory_reply(change(
        claim="Reports stay short.", endorsement="accepted", quote="yes please", assistant_statement="Reports short.",
    )))
    run(tree, DRY, fake)
    assert rejected_reasons(tree) == [weekly_gate.REJECT_QUOTE_TOO_SHORT]


def test_a_real_acceptance_passes(tree):
    records = [assistant_text("Reports will stay short from now on, as agreed.", 1), human("yes please", 2)]
    read_notes(tree, note(), records=records)
    fake = FakeCall(memory=memory_reply(change(
        claim="Reports stay short.", endorsement="accepted", quote="yes please",
        assistant_statement="Reports will stay short from now on",
    )))
    run(tree, DRY, fake)
    assert [item["endorsement"] for item in report_of(tree)["memory_changes"]] == ["accepted"]


def test_verification_is_one_tool_less_call_given_only_claims_and_quotes(tree):
    read_notes(tree, note(), records=chat(STRONG_QUOTE))
    fake = FakeCall(memory=memory_reply(strong_change()))
    result = run(tree, DRY, fake)
    assert result["status"] == "ok", result
    verifying = verification_calls(fake)
    assert len(verifying) == 1
    assert verifying[0]["tools"] == ()
    assert verifying[0]["model"] == tree.weekly.verification_model
    stdin_lines = verifying[0]["stdin_text"].splitlines()
    assert [set(json.loads(line)) for line in stdin_lines] == [{"id", "claim", "endorsement", "user_quote", "assistant_statement"}]
    assert "Understood" not in verifying[0]["stdin_text"]
    assert "data" in verifying[0]["prompt"].lower()


def test_verification_covers_changes_from_every_project_in_one_call(tree):
    read_notes(tree, note(), records=chat(STRONG_QUOTE))
    read_notes(tree, note(), session_id=SECOND_SESSION, records=chat(STRONG_QUOTE), project="other")
    fake = FakeCall(memory=memory_reply(strong_change()))
    result = run(tree, DRY, fake)
    assert result["status"] == "ok", result
    assert len(verification_calls(fake)) == 1
    assert len(report_of(tree)["memory_changes"]) == 2


def test_a_claim_the_quote_does_not_support_is_rejected_logged_and_out_of_later_steps(tree):
    read_notes(tree, note(), records=[*chat(STRONG_QUOTE, 1), *chat("print reports plain", 5)])
    fake = FakeCall(
        memory=memory_reply(
            strong_change(),
            change(action="add", claim="Print reports plain always.", quote="print reports plain", title=""),
            change(action="add", claim="Reports keep short always.", quote=STRONG_QUOTE, title=""),
        ),
        verdicts={"reports plain": "does_not_support"},
    )
    result = run(tree, LIVE, fake)
    assert result["status"] == "ok", result
    text = memory_path(tree, "short-reports").read_text(encoding="utf-8")
    assert "reports plain" not in text
    assert STRONG_CLAIM in text and "Reports keep short always." in text
    assert rejected_reasons(tree) == [weekly_gate.REJECT_NOT_SUPPORTED]
    assert all("reports plain" not in (item["after"] or "") for item in report_of(tree)["memory_changes"])
    assert report_of(tree)["rejected"][0]["detail"] == "made up for a test"


def test_a_verification_reply_that_skips_a_claim_stops_the_pass_and_applies_nothing(tree):
    read_notes(tree, note(), records=chat(STRONG_QUOTE))

    class Skipping(FakeCall):
        def __call__(self, **kwargs):
            if kwargs["prompt"].startswith("You are checking"):
                kwargs = {**kwargs, "stdin_text": ""}
            return super().__call__(**kwargs)

    result = run(tree, LIVE, Skipping(memory=memory_reply(strong_change())))
    assert result["status"] == "failed"
    assert "SchemaError" in result["stop_reason"]
    assert not memory_path(tree, "short-reports").exists()


def test_a_retry_reuses_the_verification_reply(tree):
    read_notes(tree, note(), records=chat(STRONG_QUOTE))
    fake = FakeCall(memory=memory_reply(strong_change()))
    run(tree, DRY, fake)
    forget_report(tree)
    run(tree, DRY, fake)
    assert len(verification_calls(fake)) == 1


def test_a_whole_file_delete_always_becomes_a_proposal(tree):
    add_memory(tree, "old-rule", "The old rule text.")
    read_notes(tree, note(), records=chat("delete the old rule please"))
    memory_store.snapshot_all(tree.paths.projects_dir, tree.memory, "base")
    fake = FakeCall(memory=memory_reply(change(
        action="delete", memory="old-rule", old_text="The old rule text.", claim="The old rule is gone now.",
        quote="delete the old rule please", title="",
    )))
    assert run(tree, LIVE, fake)["status"] == "ok"
    assert memory_path(tree, "old-rule").exists()
    report = report_of(tree)
    assert report["memory_changes"] == []
    deletion, = [item for item in report["proposals"] if item["kind"] == "memory_deletion"]
    assert review_data.deletion_parts(deletion["exact_change"])[:2] == ("delete", "old-rule")
    assert deletion["evidence"]["change"]["quote"] == "delete the old rule please"
    assert len(verification_calls(fake)) == 1


def test_a_delete_the_quote_does_not_support_is_not_even_proposed(tree):
    add_memory(tree, "old-rule", "The old rule text.")
    read_notes(tree, note(), records=chat("delete the old rule please"))
    fake = FakeCall(
        memory=memory_reply(change(
            action="delete", memory="old-rule", old_text="The old rule text.", claim="The old rule is gone now.",
            quote="delete the old rule please", title="",
        )),
        verdicts={"old rule": "does_not_support"},
    )
    run(tree, DRY, fake)
    assert not [item for item in report_of(tree)["proposals"] if item["kind"] == "memory_deletion"]


def test_a_quote_noted_as_a_one_moment_order_cannot_back_a_rule(tree):
    order = note(type="one_moment_order", endorsement_quote="HALT ALL PRINT JOBS AT ONCE", memory_candidate=False, route="none", what="Halt the print jobs.")
    read_notes(tree, note(), order, records=chat("HALT ALL PRINT JOBS AT ONCE print reports short"))
    fake = FakeCall(memory=memory_reply(change(claim="HALT ALL PRINT JOBS AT ONCE.", quote="HALT ALL PRINT JOBS AT ONCE")))
    run(tree, DRY, fake)
    assert rejected_reasons(tree) == [weekly_gate.REJECT_ONE_MOMENT]
    assert verification_calls(fake) == []


def test_the_model_can_name_a_one_moment_order_the_notes_missed(tree):
    read_notes(tree, note(), records=chat("no printing right now please"))
    fake = FakeCall(
        memory=memory_reply(change(claim="No printing right now.", quote="no printing right now please")),
        verdicts={"No printing": "one_moment_order"},
    )
    run(tree, DRY, fake)
    assert rejected_reasons(tree) == [weekly_gate.REJECT_ONE_MOMENT]
    assert report_of(tree)["memory_changes"] == []


@pytest.mark.parametrize("words", ["print reports long please", "Understood completely now."])
def test_criterion_4_a_fabricated_or_assistant_quote_is_rejected(tree, words):
    read_notes(tree, note(), records=[human(STRONG_QUOTE, 1), assistant_text("Understood completely now.", 2)])
    fake = FakeCall(memory=memory_reply(change(claim=f"{words} always.", quote=words)))
    run(tree, LIVE, fake)
    assert report_of(tree)["memory_changes"] == []
    assert rejected_reasons(tree) == [weekly_gate.REJECT_QUOTE]


def test_criterion_4_pasted_words_are_not_the_users(tree):
    read_notes(tree, note(), records=chat(f'read this <pasted_content id="a1">{STRONG_QUOTE}</pasted_content id="a1">'))
    run(tree, LIVE, FakeCall(memory=memory_reply(strong_change())))
    assert report_of(tree)["memory_changes"] == []
    assert rejected_reasons(tree) == [weekly_gate.REJECT_QUOTE]


def test_criterion_4_a_good_quote_is_applied_with_the_quote_in_the_file(tree):
    read_notes(tree, note(), records=chat(STRONG_QUOTE))
    assert run(tree, LIVE, FakeCall(memory=memory_reply(strong_change())))["status"] == "ok"
    assert STRONG_QUOTE in memory_path(tree, "short-reports").read_text(encoding="utf-8")


# ---- Defect 2: applied changes stay in the review ----


def failed_daily(config, run_id, call=None):
    return {
        "status": "failed", "stop_reason": None, "budget_stopped": False, "sessions_read": 0, "notes": 0, "cost_usd": 0.0,
        "failed_sessions": [{"session": "proj/broken", "error": "made up"}], "backlog_sessions": [], "windows_reset": [],
        "secrets_redacted": 0, "memory_snapshot": {"errors": []},
    }


def run_unmarked(config, local, fake, now):
    return weekly.run_weekly(config, local, "run-" + now.strftime("%H%M"), now=now, call=fake)


def crash(*arguments, **keywords):
    raise KeyboardInterrupt()


def test_a_retry_after_a_failed_session_keeps_applied_changes_in_the_report_and_the_review(tree, monkeypatch):
    read_notes(tree, note(), records=chat(STRONG_QUOTE))
    monkeypatch.setattr(daily, "run_daily", failed_daily)
    fake = FakeCall(memory=memory_reply(strong_change()))
    first = run_unmarked(tree, LIVE, fake, NOW)
    assert first["status"] == "failed"
    commit = report_of(tree)["memory_changes"][0]["commit"]
    assert commit

    second = run_unmarked(tree, LIVE, fake, LATER)
    assert second["status"] == "failed"
    assert [item["commit"] for item in report_of(tree)["memory_changes"]] == [commit]
    item, = [item for item in review_of(tree)["items"] if item["section"] == schemas.SECTION_MEMORY]
    assert schemas.ACTION_UNDO in item["allowed"]
    assert item["record"]["commit"] == commit

    review_session.undo(tree, review_of(tree)["review_id"], item["number"], "test-session", LATER)
    assert not memory_path(tree, "short-reports").exists()


def test_a_retry_keeps_an_undecided_proposal_of_the_same_week(tree, monkeypatch):
    add_memory(tree, "old-rule", "The old rule text.")
    read_notes(tree, note(), records=chat("delete the old rule please"))
    monkeypatch.setattr(daily, "run_daily", failed_daily)
    fake = FakeCall(memory=memory_reply(
        change(
            action="delete", memory="old-rule", old_text="The old rule text.", claim="The old rule is gone now.",
            quote="delete the old rule please", title="",
        ),
        strong_change(memory="other-rule", quote="delete the old rule please", claim="Delete the old rule please."),
    ))
    run_unmarked(tree, LIVE, fake, NOW)
    run_unmarked(tree, LIVE, fake, LATER)
    kinds = [item["record"]["kind"] for item in review_of(tree)["items"] if item["section"] == schemas.SECTION_PROPOSAL]
    assert "memory_deletion" in kinds
    assert any(item["kind"] == "memory_deletion" for item in report_of(tree)["proposals"])


def test_a_trial_run_item_is_still_worked_out_again(tree):
    read_notes(tree, note(), records=chat(STRONG_QUOTE))
    fake = FakeCall(memory=memory_reply(strong_change()))
    run(tree, DRY, fake)
    assert len(review_of(tree)["items"]) == 1
    forget_report(tree)
    forget_replies(tree)
    run(tree, DRY, FakeCall())
    assert review_of(tree)["items"] == []


def test_a_crash_after_the_commit_is_reconciled_on_the_next_run(tree, monkeypatch):
    read_notes(tree, note(), records=chat(STRONG_QUOTE))
    real = weekly._record_in_ledger
    monkeypatch.setattr(weekly, "_record_in_ledger", crash)
    fake = FakeCall(memory=memory_reply(strong_change()))
    mark_daily_done(tree)
    with pytest.raises(KeyboardInterrupt):
        weekly.run_weekly(tree, LIVE, "run1", now=NOW, call=fake)
    upkeep_commits = [line for line in commits_in(tree) if line.startswith("Upkeep weekly")]
    assert len(upkeep_commits) == 1
    assert not (Path(tree.paths.data_dir) / "reports" / weekly.iso_week_of(NOW.astimezone()) / "report.json").exists()

    monkeypatch.setattr(weekly, "_record_in_ledger", real)
    result = weekly.run_weekly(tree, LIVE, "run2", now=LATER, call=fake)
    assert result["status"] == "ok", result
    assert [line for line in commits_in(tree) if line.startswith("Upkeep weekly")] == upkeep_commits
    change_record, = report_of(tree)["memory_changes"]
    assert change_record["commit"]
    assert report_of(tree)["rejected"] == []
    item = ledger.ItemId(ledger.project_scope(PROJECT), "memory", "short-reports")
    assert len(ledger.load_ledger(ledger.ledgers_dir_of(tree.paths.data_dir), item)["entries"]) == 1
    entry, = [item for item in review_of(tree)["items"] if item["section"] == schemas.SECTION_MEMORY]
    assert schemas.ACTION_UNDO in entry["allowed"]
    state = json.loads(Path(weekly.weekly_state_path(tree)).read_text(encoding="utf-8"))
    assert state["consumed_windows"]


def test_a_crash_between_commit_and_its_record_is_found_by_its_trailer(tree, monkeypatch):
    read_notes(tree, note(), records=chat(STRONG_QUOTE))
    real = weekly._mark_folder_committed
    monkeypatch.setattr(weekly, "_mark_folder_committed", crash)
    fake = FakeCall(memory=memory_reply(strong_change()))
    mark_daily_done(tree)
    with pytest.raises(KeyboardInterrupt):
        weekly.run_weekly(tree, LIVE, "run1", now=NOW, call=fake)
    monkeypatch.setattr(weekly, "_mark_folder_committed", real)
    assert weekly.run_weekly(tree, LIVE, "run2", now=LATER, call=fake)["status"] == "ok"
    assert report_of(tree)["memory_changes"][0]["commit"]
    assert len([line for line in commits_in(tree) if line.startswith("Upkeep weekly")]) == 1


def test_a_crash_before_the_commit_puts_the_files_back_and_applies_once(tree, monkeypatch):
    add_memory(tree, "other", "Other text.")
    read_notes(tree, note(), records=chat(STRONG_QUOTE))
    memory_store.snapshot_all(tree.paths.projects_dir, tree.memory, "base")
    real = memory_store._commit_paths
    monkeypatch.setattr(memory_store, "_commit_paths", crash)
    fake = FakeCall(memory=memory_reply(strong_change()))
    mark_daily_done(tree)
    with pytest.raises(KeyboardInterrupt):
        weekly.run_weekly(tree, LIVE, "run1", now=NOW, call=fake)
    assert memory_path(tree, "short-reports").exists(), "the crash came after the write"

    monkeypatch.setattr(memory_store, "_commit_paths", real)
    commits_before = commits_in(tree)
    result = weekly.run_weekly(tree, LIVE, "run2", now=LATER, call=fake)
    assert result["status"] == "ok", result
    assert len([line for line in commits_in(tree) if line.startswith("Upkeep weekly")]) == 1
    assert len(commits_in(tree)) == len(commits_before) + 1, "no snapshot took the half-written state as live edits"
    assert report_of(tree)["memory_changes"][0]["commit"]
    assert memory_path(tree, "short-reports").read_text(encoding="utf-8").count(f"{STRONG_CLAIM} (user") == 1
    index = (memory_path(tree, "x").parent / "MEMORY.md").read_text(encoding="utf-8")
    assert index.count("(short-reports.md)") == 1


def test_a_crash_between_folders_applies_only_the_other_folder_on_the_next_run(tree, monkeypatch):
    read_notes(tree, note(), records=chat(STRONG_QUOTE))
    read_notes(tree, note(), session_id=SECOND_SESSION, records=chat(STRONG_QUOTE), project="other")
    real = memory_store.apply_memory_writes
    seen = []

    def crashing(folder, *arguments, **keywords):
        seen.append(folder)
        if len(seen) == 2:
            raise KeyboardInterrupt()
        return real(folder, *arguments, **keywords)

    monkeypatch.setattr(memory_store, "apply_memory_writes", crashing)
    fake = FakeCall(memory=memory_reply(strong_change()))
    mark_daily_done(tree)
    with pytest.raises(KeyboardInterrupt):
        weekly.run_weekly(tree, LIVE, "run1", now=NOW, call=fake)
    monkeypatch.setattr(memory_store, "apply_memory_writes", real)
    result = weekly.run_weekly(tree, LIVE, "run2", now=LATER, call=fake)
    assert result["status"] == "ok", result
    assert sorted(item["project_folder"] for item in report_of(tree)["memory_changes"]) == sorted([PROJECT, "other"])
    assert all(item["commit"] for item in report_of(tree)["memory_changes"])
    for project in (PROJECT, "other"):
        assert len([line for line in commits_in(tree, project) if line.startswith("Upkeep weekly")]) == 1


# ---- Defect 3: an unknown record type stops one session only ----


def test_pr_link_and_ultrathink_effort_are_known(tmp_path):
    path = write_jsonl(tmp_path / "a.jsonl", [
        {"type": "pr-link", "sessionId": "s"},
        attachment({"type": "ultrathink_effort", "level": "x"}, 1),
        human("hello there", 2),
    ])
    assert [entry.kind for entry in t.iter_session_entries(path, [], None, None)] == [t.USER_TYPED]


def test_an_unknown_bookkeeping_type_fails_that_session_and_the_rest_go_on(tree):
    add_session(tree, SESSION_ID, chat("first good session words", 1))
    add_session(tree, SECOND_SESSION, [*chat("some words", 1), {"type": "brand-new-type"}])
    result = daily.run_daily(tree, "r1", call=FakeCall())
    assert result["status"] == daily.STATUS_FAILED
    assert result["stop_reason"] is None
    assert result["sessions_read"] == 1
    failed, = result["failed_sessions"]
    assert failed["session"] == f"{PROJECT}/{SECOND_SESSION}"
    assert "brand-new-type" in failed["error"]
    entries = json.loads(Path(daily.state_path(tree)).read_text(encoding="utf-8"))["sessions"]
    assert entries[f"{PROJECT}/{SESSION_ID}"]["processed_through"]
    assert "processed_through" not in entries.get(f"{PROJECT}/{SECOND_SESSION}", {})


def test_an_unknown_origin_on_a_human_looking_record_stops_only_its_session(tree):
    add_session(tree, SESSION_ID, chat("first good session words", 1))
    add_session(tree, SECOND_SESSION, [user_with_origin("from-the-future", "hello", 1)])
    result = daily.run_daily(tree, "r1", call=FakeCall())
    assert result["status"] == daily.STATUS_FAILED
    assert daily.EXIT_CODES[result["status"]] != 0
    assert result["sessions_read"] == 1
    assert "origin.kind" in result["failed_sessions"][0]["error"]
    entries = json.loads(Path(daily.state_path(tree)).read_text(encoding="utf-8"))["sessions"]
    assert "processed_through" not in entries[f"{PROJECT}/{SECOND_SESSION}"]


def test_a_new_type_after_a_window_does_not_touch_that_window(tree):
    read_notes(tree, note(), records=chat(STRONG_QUOTE))
    path = Path(tree.paths.projects_dir) / PROJECT / f"{SESSION_ID}.jsonl"
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"type": "brand-new-type", "sessionId": SESSION_ID}) + "\n")
    assert run(tree, DRY, FakeCall(memory=memory_reply(strong_change())))["status"] == "ok"
    assert len(report_of(tree)["memory_changes"]) == 1


def test_a_new_type_in_a_processed_session_skips_its_window_in_the_weekly_pass(tree):
    read_notes(tree, note(), records=chat(STRONG_QUOTE))
    read_notes(tree, note(), session_id=SECOND_SESSION, records=chat(STRONG_QUOTE), project="other")
    for window_file in (Path(tree.paths.data_dir) / "notes").glob("*/*/window.json"):
        # Only a window from before line limits reads past its own end.
        if SECOND_SESSION in str(window_file):
            document = json.loads(window_file.read_text(encoding="utf-8"))
            for key in ("lines_after", "lines_through", "floor"):
                document.pop(key)
            window_file.write_text(json.dumps(document), encoding="utf-8")
    path = Path(tree.paths.projects_dir) / "other" / f"{SECOND_SESSION}.jsonl"
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"type": "brand-new-type", "sessionId": SECOND_SESSION}) + "\n")
    result = run(tree, DRY, FakeCall(memory=memory_reply(strong_change())))
    assert result["status"] == "ok", result
    report = report_of(tree)
    assert [item["project_folder"] for item in report["memory_changes"]] == [PROJECT]
    assert any("brand-new-type" in item["reason"] for item in report["coverage"]["windows_skipped"])


# ---- Defect 4: pasted text ----


def test_a_literal_closing_tag_inside_a_paste_does_not_end_it():
    text = 'mine <pasted_content id="a1">copied</pasted_content> still copied</pasted_content id="a1"> mine too'
    assert t.split_pasted(text) == [
        (False, "mine"), (True, "copied</pasted_content> still copied"), (False, "mine too"),
    ]


def test_a_closing_tag_with_another_id_does_not_end_a_paste():
    text = '<pasted_content id="a1">one</pasted_content id="b2"> two</pasted_content id="a1"> mine'
    assert t.split_pasted(text) == [(True, 'one</pasted_content id="b2"> two'), (False, "mine")]


def test_a_paste_never_closed_stays_pasted_to_the_end():
    assert t.split_pasted('mine <pasted_content id="a1">copied to the end') == [(False, "mine"), (True, "copied to the end")]


def test_a_paste_with_no_id_ends_at_its_last_closing_tag():
    text = "<pasted_content>one</pasted_content> two</pasted_content> mine"
    assert t.split_pasted(text) == [(True, "one</pasted_content> two"), (False, "mine")]


# ---- Defect 5: records written late ----


def append_records(path, records):
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps({**record, "sessionId": SESSION_ID}) + "\n")


def session_path(config, session_id=SESSION_ID, project=PROJECT):
    return Path(config.paths.projects_dir) / project / f"{session_id}.jsonl"


def queued(text, minute):
    return attachment({"type": "queued_command", "prompt": text, "origin": {"kind": "human"}}, minute)


def touch(path):
    stamp = datetime(2035, 1, 1, tzinfo=timezone.utc).timestamp()
    os.utime(path, (stamp, stamp))


def daily_reading(config, run_id):
    fake = FakeCall()
    return daily.run_daily(config, run_id, call=fake), fake


def test_a_queued_message_written_after_the_read_with_an_earlier_stamp_is_read(tree):
    add_session(tree, SESSION_ID, [human("first message", 1), assistant_text("Later reply.", 5)])
    first, _ = daily_reading(tree, "r1")
    assert first["sessions_read"] == 1
    path = session_path(tree)
    append_records(path, [queued("typed while it worked", 3)])
    touch(path)
    second, fake = daily_reading(tree, "r2")
    assert second["status"] == daily.STATUS_OK, second
    assert second["sessions_read"] == 1
    assert "typed while it worked" in fake.calls[0]["stdin_text"]
    assert "first message" not in fake.calls[0]["stdin_text"]
    third, _ = daily_reading(tree, "r3")
    assert third["sessions_selected"] == 0


def test_a_record_stamped_in_the_same_millisecond_as_the_last_read_is_read(tree):
    add_session(tree, SESSION_ID, [human("first message", 5)])
    daily_reading(tree, "r1")
    path = session_path(tree)
    append_records(path, [human("same moment words", 5)])
    touch(path)
    second, fake = daily_reading(tree, "r2")
    assert second["sessions_read"] == 1
    assert "same moment words" in fake.calls[0]["stdin_text"]


def test_two_late_only_windows_get_folders_of_their_own(tree):
    add_session(tree, SESSION_ID, [human("first message", 1), assistant_text("Later reply.", 5)])
    daily_reading(tree, "r1")
    path = session_path(tree)
    append_records(path, [queued("late one", 3)])
    touch(path)
    daily_reading(tree, "r2")
    append_records(path, [queued("late two", 4)])
    touch(path)
    third, _ = daily_reading(tree, "r3")
    assert third["status"] == daily.STATUS_OK, third
    assert third["windows_reset"] == []
    assert len(list((Path(tree.paths.data_dir) / "notes").glob("*/*/window.json"))) == 3


def test_a_late_record_can_back_a_claim_in_the_weekly_pass(tree):
    add_session(tree, SESSION_ID, [human("first message", 1), assistant_text("Later reply.", 5)])
    daily_reading(tree, "r1")
    path = session_path(tree)
    append_records(path, [queued(STRONG_QUOTE, 3)])
    touch(path)
    notes_reply = json.dumps({"notes": [note()]})

    class Reader(FakeCall):
        def __call__(self, **kwargs):
            result = super().__call__(**kwargs)
            return model_call.ModelResult(notes_reply, result.usage, result.model_usage, result.cost_usd, 1, 1, ("claude",))

    assert daily.run_daily(tree, "r2", call=Reader())["status"] == daily.STATUS_OK
    assert run(tree, DRY, FakeCall(memory=memory_reply(strong_change())))["status"] == "ok"
    assert [item["memory"] for item in report_of(tree)["memory_changes"]] == ["short-reports"]


def test_a_subagent_file_written_later_does_not_read_old_copies_again(tree):
    add_session(tree, SESSION_ID, [human("first message", 1), assistant_text("Reply.", 2)])
    daily_reading(tree, "r1")
    path = session_path(tree)
    main_lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    subagent = path.parent / SESSION_ID / "subagents" / "agent-1.jsonl"
    write_jsonl(subagent, [main_lines[0], {**human("to the teammate", 3), "sessionId": SESSION_ID, "isSidechain": True}])
    touch(subagent)
    second, fake = daily_reading(tree, "r2")
    assert second["sessions_read"] == 1
    assert "first message" not in fake.calls[0]["stdin_text"]
    assert "to the teammate" in fake.calls[0]["stdin_text"]


def test_a_later_file_holding_only_copies_opens_no_window(tree):
    add_session(tree, SESSION_ID, [human("first message", 1), assistant_text("Reply.", 2)])
    daily_reading(tree, "r1")
    path = session_path(tree)
    main_lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    subagent = path.parent / SESSION_ID / "subagents" / "agent-1.jsonl"
    write_jsonl(subagent, main_lines)
    touch(subagent)
    second, _ = daily_reading(tree, "r2")
    assert second["sessions_selected"] == 0


def test_old_state_carries_over_without_reading_old_records_again(tree):
    add_session(tree, SESSION_ID, [human("already read", 1), assistant_text("Reply.", 2)])
    state_file = Path(daily.state_path(tree))
    through = t.parse_timestamp("2030-01-01T10:02:00Z").isoformat()
    state_file.write_text(json.dumps({"schema_version": 1, "sessions": {f"{PROJECT}/{SESSION_ID}": {"processed_through": through, "pending": None}}}), encoding="utf-8")
    path = session_path(tree)
    append_records(path, [human("new words", 9), queued("late after the new words", 1)])
    touch(path)
    result, fake = daily_reading(tree, "r1")
    assert result["status"] == daily.STATUS_OK, result
    stdin_text = fake.calls[0]["stdin_text"]
    assert "new words" in stdin_text and "late after the new words" in stdin_text
    assert "already read" not in stdin_text
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["schema_version"] == sessions.STATE_SCHEMA_VERSION == 2
    assert saved["sessions"][f"{PROJECT}/{SESSION_ID}"]["lines_read"] == {f"{SESSION_ID}.jsonl": 4}


def test_an_old_pinned_window_carries_over(tree):
    add_session(tree, SESSION_ID, [human("pinned words", 1), assistant_text("Reply.", 2)])
    state_file = Path(daily.state_path(tree))
    pending = {
        "after": datetime(2020, 1, 2, tzinfo=timezone.utc).isoformat(),
        "through": t.parse_timestamp("2030-01-01T10:02:00Z").isoformat(),
        "mode": "read", "project_cwd": "/work/project",
    }
    state_file.write_text(json.dumps({"schema_version": 1, "sessions": {f"{PROJECT}/{SESSION_ID}": {"pending": pending}}}), encoding="utf-8")
    result, fake = daily_reading(tree, "r1")
    assert result["status"] == daily.STATUS_OK, result
    assert result["windows_reset"] == []
    assert "pinned words" in fake.calls[0]["stdin_text"]
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["sessions"][f"{PROJECT}/{SESSION_ID}"]["lines_read"] == {f"{SESSION_ID}.jsonl": 2}


def test_a_window_written_before_this_change_is_still_read_by_its_timestamps(tree):
    read_notes(tree, note(), records=chat(STRONG_QUOTE))
    window_file, = (Path(tree.paths.data_dir) / "notes").glob("*/*/window.json")
    document = json.loads(window_file.read_text(encoding="utf-8"))
    for key in ("lines_after", "lines_through", "floor"):
        document.pop(key)
    window_file.write_text(json.dumps(document), encoding="utf-8")
    assert run(tree, DRY, FakeCall(memory=memory_reply(strong_change())))["status"] == "ok"
    assert len(report_of(tree)["memory_changes"]) == 1


def test_a_transcript_that_shrank_fails_that_session(tree):
    add_session(tree, SESSION_ID, [human("first message", 1), human("second message", 2)])
    add_session(tree, SECOND_SESSION, chat("other session words", 1))
    daily_reading(tree, "r1")
    path = session_path(tree)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    path.write_text(lines[0], encoding="utf-8")
    touch(path)
    result, _ = daily_reading(tree, "r2")
    assert result["status"] == daily.STATUS_FAILED
    assert "shrank" in result["failed_sessions"][0]["error"]


# ---- Defect 6: undo never restores redacted text ----


def test_undo_restores_the_real_text_when_the_report_holds_it_redacted(tree):
    body = f"Kept line.\n\nThe rule with {SECRET} in it.\n\nLast line."
    path = add_memory(tree, "has-secret", body)
    exact = path.read_text(encoding="utf-8")
    read_notes(tree, note(), records=chat("the rule is wrong now"))
    memory_store.snapshot_all(tree.paths.projects_dir, tree.memory, "base")
    fake = FakeCall(memory=memory_reply(change(
        action="remove", memory="has-secret", old_text=f"The rule with {SECRET} in it.", claim="The rule is wrong now.",
        quote="the rule is wrong now", title="",
    )))
    assert run(tree, LIVE, fake)["status"] == "ok"
    assert SECRET not in path.read_text(encoding="utf-8")
    record, = report_of(tree)["memory_changes"]
    assert SECRET not in record["before"], "the report must hold it redacted"
    item, = [item for item in review_of(tree)["items"] if item["section"] == schemas.SECTION_MEMORY]
    review_session.undo(tree, review_of(tree)["review_id"], item["number"], "s", NOW)
    assert path.read_text(encoding="utf-8") == exact


def test_undo_of_one_of_two_changes_in_one_commit_keeps_the_other_and_the_secret(tree):
    body = f"Kept line with {SECRET} in it.\n\nFirst target.\n\nSecond target."
    path = add_memory(tree, "has-secret", body)
    read_notes(tree, note(), records=chat("the rule is wrong now"))
    memory_store.snapshot_all(tree.paths.projects_dir, tree.memory, "base")
    fake = FakeCall(memory=memory_reply(
        change(action="remove", memory="has-secret", old_text="First target.", claim="The rule is wrong now.", quote="the rule is wrong now", title=""),
        change(action="remove", memory="has-secret", old_text="Second target.", claim="The rule is wrong now again.", quote="the rule is wrong now", title=""),
    ))
    assert run(tree, LIVE, fake)["status"] == "ok"
    items = [item for item in review_of(tree)["items"] if item["section"] == schemas.SECTION_MEMORY]
    review_session.undo(tree, review_of(tree)["review_id"], items[1]["number"], "s", NOW)
    text = path.read_text(encoding="utf-8")
    assert "Second target." in text and "First target." not in text and SECRET in text


def test_a_redacted_text_no_line_of_the_commit_explains_is_refused(tree):
    folder = memory_path(tree, "x").parent
    add_memory(tree, "plain", "Text.")
    memory_store.snapshot_all(tree.paths.projects_dir, tree.memory, "base")
    commit = subprocess.run(["git", "-C", str(folder), "rev-parse", "HEAD"], capture_output=True, encoding="utf-8", check=True).stdout.strip()
    with pytest.raises(memory_store.MemoryStoreError, match="cannot be read back"):
        memory_store.exact_change_texts(str(folder), "plain.md", commit, "[REDACTED-key-value] other", None, lambda text: text.replace(SECRET, "[REDACTED-key-value]"))


# ---- Defect 7: memory writes are atomic ----


def test_a_failed_write_leaves_the_file_as_it_was_and_no_temporary(tree, monkeypatch):
    path = add_memory(tree, "atomic", "Original text.")
    original = memory_store.read_memory_file(str(path))
    folder = path.parent
    memory_store.snapshot_all(tree.paths.projects_dir, tree.memory, "base")

    def failing(source, target):
        raise OSError("disk went away")

    monkeypatch.setattr(memory_store.os, "replace", failing)
    write = memory_store.FileWrite("atomic.md", original, "New text.\n")
    with pytest.raises(memory_store.MemoryStoreError):
        memory_store.apply_memory_writes(str(folder), [write], [], tree.memory, "2031-W01", "message")
    assert memory_store.read_memory_file(str(path)) == original
    assert sorted(os.listdir(folder)) == [".git", "atomic.md"]


def test_a_temporary_left_by_a_crash_is_not_committed_and_is_removed(tree):
    path = add_memory(tree, "atomic", "Original text.")
    folder = path.parent
    memory_store.snapshot_all(tree.paths.projects_dir, tree.memory, "base")
    (folder / f"{memory_store.TEMP_PREFIX}atomic.md.123").write_text("half a fi", encoding="utf-8")
    assert memory_store.snapshot_folder(str(folder), tree.memory, "next") == memory_store.RESULT_UNCHANGED
    assert sorted(os.listdir(folder)) == [".git", "atomic.md"]
    tracked = subprocess.run(["git", "-C", str(folder), "ls-files"], capture_output=True, encoding="utf-8", check=True).stdout.split()
    assert tracked == ["atomic.md"]


def test_a_folder_holding_only_a_temporary_counts_as_empty(tree):
    folder = memory_path(tree, "x").parent
    folder.mkdir(parents=True)
    (folder / f"{memory_store.TEMP_PREFIX}atomic.md.123").write_text("half", encoding="utf-8")
    assert memory_store.classify(str(folder)) == memory_store.STATE_EMPTY


def test_a_memory_file_is_never_opened_for_writing_in_place():
    source = Path(memory_store.__file__).read_text(encoding="utf-8")
    assert 'open(path, "w"' not in source
    assert 'open(index_path, "w"' not in source


# ---- Defect 9: labels the model wrote ----


def ask(answers, questions, minute=1, annotations=None):
    return [
        tool_use("q1", "AskUserQuestion", {"questions": questions}, minute),
        tool_result("q1", "answered", minute + 1, toolUseResult={"questions": questions, "answers": answers, "annotations": annotations or {}}),
    ]


QUESTION = {"question": "Which one?", "header": "h", "multiSelect": False, "options": [{"label": "Use the left one"}, {"label": "No"}]}


def answer_entries(tmp_path, records):
    path = write_jsonl(tmp_path / "a.jsonl", records)
    return [entry for entry in t.iter_session_entries(path, [], None, None) if entry.kind in (t.USER_ANSWER, t.USER_CHOSE_OPTION)]


def test_a_chosen_label_is_not_the_users_own_words(tmp_path):
    entry, = answer_entries(tmp_path, ask({"Which one?": "Use the left one"}, [QUESTION]))
    assert entry.kind == t.USER_CHOSE_OPTION
    assert t.USER_CHOSE_OPTION not in t.USER_OWN_KINDS
    assert entry.context == "Which one?"


def test_a_typed_answer_stays_the_users_own(tmp_path):
    entry, = answer_entries(tmp_path, ask({"Which one?": "Now neither of them"}, [QUESTION]))
    assert entry.kind == t.USER_ANSWER and entry.text == "Now neither of them"


def test_words_typed_beside_a_label_are_split_from_it(tmp_path):
    chosen, own = answer_entries(tmp_path, ask({"Which one?": "Use the left one, and keep it quiet"}, [QUESTION]))
    assert (chosen.kind, chosen.text) == (t.USER_CHOSE_OPTION, "Use the left one")
    assert (own.kind, own.text) == (t.USER_ANSWER, "and keep it quiet")


def test_a_note_typed_on_an_option_is_the_users_own(tmp_path):
    chosen, own = answer_entries(tmp_path, ask({"Which one?": "No"}, [QUESTION], annotations={"Which one?": {"notes": "typed note"}}))
    assert chosen.kind == t.USER_CHOSE_OPTION
    assert (own.kind, own.text) == (t.USER_ANSWER, "typed note")


def test_a_label_cannot_back_said_but_can_back_accepted(tree):
    records = [
        assistant_text("Reports will use the short form from now on.", 1),
        *ask({"Which one?": "Use the left one"}, [QUESTION], 2),
    ]
    read_notes(tree, note(), records=records)
    said = FakeCall(memory=memory_reply(change(claim="Use the left one here.", quote="Use the left one")))
    run(tree, DRY, said)
    assert rejected_reasons(tree) == [weekly_gate.REJECT_QUOTE]

    forget_report(tree)
    forget_replies(tree)
    accepted = FakeCall(memory=memory_reply(change(
        claim="Reports use the short form.", endorsement="accepted", quote="Use the left one",
        assistant_statement="Reports will use the short form",
    )))
    run(tree, DRY, accepted)
    assert [item["endorsement"] for item in report_of(tree)["memory_changes"]] == ["accepted"]


def test_a_note_saying_said_on_a_label_fails_its_quote_check():
    moment = datetime(2030, 1, 1, tzinfo=timezone.utc)
    entry = t.Entry(t.USER_CHOSE_OPTION, moment, "Use the left one", "main", "/x")
    assert not quotes.quote_is_in_user_entries("Use the left one", [entry])
    assert quotes.quote_is_in_user_entries("Use the left one", [entry], accepted=True)


# ---- Defect 10: fetched links ----


def private_material():
    return research.build_private_material(["secretproject"], [], 6)


def fetch(url, result="page text"):
    return model_call.ToolActivity("WebFetch", {"url": url}, result, False)


SEARCH = model_call.ToolActivity(
    "WebSearch", {"query": "a general tool"},
    "see https://example.org/docs and https://example.org/00000000-0000-4000-8000-0000000000a1", False,
)


@pytest.mark.parametrize("url", [
    "https://example.org/secretproject/readme",
    "https://example.org/search?q=secretproject",
    "http://192.168.1.20/admin",
    "http://homeserver.local/status",
    "http://localhost:8080/",
    "https://example.org/C:/Users/someone/file",
])
def test_a_fetched_link_holding_private_material_is_refused(url):
    with pytest.raises(research.PrivateMaterialError):
        research.check_fetched_urls((SEARCH, fetch(url)), private_material(), ())


@pytest.mark.parametrize("url", [
    "https://example.org/docs",
    "https://docs.claude.com/en/docs/claude-code",
    "https://example.org:443/page",
    "https://example.org/00000000-0000-4000-8000-0000000000a1",
])
def test_a_public_link_passes(url):
    research.check_fetched_urls((SEARCH, fetch(url)), private_material(), ())


def test_a_private_host_named_by_a_search_result_is_still_refused():
    search = model_call.ToolActivity("WebSearch", {"query": "x"}, "see http://10.0.0.5/page", False)
    with pytest.raises(research.PrivateMaterialError):
        research.check_fetched_urls((search, fetch("http://10.0.0.5/page")), private_material(), ())


def test_research_stops_on_a_private_fetched_link(tree):
    fake = FakeCall(activity=(SEARCH, fetch("https://example.org/secretproject/readme")))
    with pytest.raises(research.PrivateMaterialError):
        research.research_description(
            "a general tool that does a thing", private_material(), tree, str(Path(tree.paths.data_dir) / "usage.jsonl"), 1.0, fake,
        )


# ---- A limit reply ----


def result_json(text, **fields):
    return json.dumps({
        "type": "result", "subtype": "success", "is_error": False, "result": text, "usage": {}, "modelUsage": {},
        "total_cost_usd": 0, "duration_ms": 1, "num_turns": 1, **fields,
    })


@pytest.mark.parametrize("text", [
    "You've hit your weekly limit \u00b7 resets at noon",
    "You've hit your session limit \u00b7 resets in an hour",
])
def test_a_limit_reply_is_a_limit_even_with_exit_zero_and_success(text):
    with pytest.raises(model_call.LimitReachedError):
        model_call.check_result(result_json(text), 0, "")


def test_a_limit_reply_as_a_json_error_with_exit_one_is_named():
    with pytest.raises(model_call.LimitReachedError):
        model_call.check_result(result_json("You've hit your weekly limit \u00b7 resets at noon", is_error=True), 1, "")


def test_a_limit_reply_as_plain_text_with_exit_one_is_named():
    with pytest.raises(model_call.LimitReachedError):
        model_call.check_result("You've hit your weekly limit \u00b7 resets at noon\n", 1, "")


def test_a_reply_that_merely_mentions_a_limit_is_not_a_limit():
    assert model_call.check_result(result_json('{"notes": [{"what": "You\'ve hit your weekly limit was seen"}]}'), 0, "")


def test_a_limit_stops_the_daily_pass_rather_than_failing_one_session(tree):
    add_session(tree, SESSION_ID, chat("first words", 1))
    add_session(tree, SECOND_SESSION, chat("second words", 1))

    def limited(**kwargs):
        raise model_call.LimitReachedError("limit")

    result = daily.run_daily(tree, "r1", call=limited)
    assert result["status"] == daily.STATUS_FAILED
    assert "LimitReachedError" in result["stop_reason"]
    assert result["failed_sessions"] == []
