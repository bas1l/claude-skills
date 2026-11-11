"""Item names that resolve, stances that are checked, balance over weeks, and split statements.
All names and texts are invented."""
from __future__ import annotations

import dataclasses
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import backfill
import daily
import extract
import ledger
import model_call
import render
import review_data
import review_session
import schemas
import stance_check
import weekly
import weekly_gate
import weekly_notes
from config import LedgerConfig
from conftest import stance_reply
from test_weekly import (
    DRY, LIVE, NOW, PROJECT, FakeCall, add_memory, change, chat, mark_daily_done, memory_path, memory_reply, note,
    read_notes, report_of, run, tree,  # noqa: F401 (tree is a fixture)
)

FOLDER = "folder-a"
KIND_ORDER = ("hook", "mcp", "memory", "plugin", "skill")


def write_inventory(config, folder=PROJECT):
    """One item of each kind, and a memory in another project folder."""
    inventory = config.inventory
    skill = Path(inventory.skills_dir) / "tea-brewing"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: tea-brewing\ndescription: Brews tea step by step with a very long description that goes on and on and on past any limit a listing would want to show to a reader at all\n---\n\nStep 1: boil water.\nStep 2: steep with key api_key=abcdefgh12345678.\n",
        encoding="utf-8",
    )
    script_dir = Path(inventory.skills_dir).parent / "hooks"
    script_dir.mkdir()
    script = script_dir / "kettle_gate.py"
    script.write_text('#!/usr/bin/env python3\n"""Stop hook: refuse to end the turn while the kettle is on.\n\nMore.\n"""\nprint("x")\n', encoding="utf-8")
    other = script_dir / "kettle_two.py"
    other.write_text('"""Second."""\n', encoding="utf-8")
    Path(inventory.settings_file).write_text(json.dumps({
        "hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": f'python "{script.as_posix()}"', "statusMessage": "Kettle gate"},
            {"type": "command", "command": f'python "{other.as_posix()}"', "statusMessage": "Shared label"},
        ]}, {"hooks": [
            {"type": "command", "command": f'python "{script.as_posix()}"', "statusMessage": "Shared label"},
        ]}]},
    }), encoding="utf-8")
    plugin_root = Path(inventory.skills_dir).parent / "plugin-root"
    (plugin_root / ".claude-plugin").mkdir(parents=True)
    (plugin_root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "teapot", "description": "Pours tea."}), encoding="utf-8")
    Path(inventory.installed_plugins_file).write_text(json.dumps({"version": 2, "plugins": {"teapot@shelf": [{"installPath": str(plugin_root)}]}}), encoding="utf-8")
    Path(inventory.plugins_manifest).write_text(json.dumps({
        "plugins": [{"id": "teapot@shelf", "enabled": True}],
        "mcpServers": [{"name": "cupboard", "scope": "user", "config": {"command": "cupboard-server", "env": {"CUPBOARD_TOKEN": "abcdefgh12345678"}}}],
    }), encoding="utf-8")
    for project, name, body in ((folder, "biscuits", "Biscuits go on the left."), ("other-folder", "saucers", "Saucers go on the right.")):
        memory = Path(config.paths.projects_dir) / project / "memory"
        memory.mkdir(parents=True, exist_ok=True)
        (memory / f"{name}.md").write_text(f"---\nname: {name}\ndescription: About {name}\n---\n\n{body}\n", encoding="utf-8")
    backfill.sync_items(config, NOW)


def stance_note(*items, what="The kettle gate blocked the turn.", **overrides):
    return note(type="failure", what=what, evidence="HOOK-BLOCK", memory_candidate=False, endorsement="none", endorsement_quote="",
                origin_of_point="hook", route="none", items=[dict(zip(("kind", "name", "stance"), item)) for item in items], **overrides)


class Reader(FakeCall):
    """Reads each session into these notes, and answers the stance check."""

    def __init__(self, *notes, refuse=(), stance_error=None):
        super().__init__()
        self.notes = notes
        self.refuse = refuse
        self.stance_error = stance_error

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["prompt"].startswith("You are judging"):
            if self.stance_error is not None:
                raise self.stance_error
            text = stance_reply(kwargs["stdin_text"], self.refuse)
        else:
            text = json.dumps({"notes": list(self.notes)})
        return model_call.ModelResult(
            text=text, usage={"input_tokens": 1, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 1},
            model_usage={"m": {}}, cost_usd=0.1, duration_ms=1, num_turns=1, command_line=("claude",),
        )

    def stance_calls(self):
        return [call for call in self.calls if call["prompt"].startswith("You are judging")]


def run_daily_with(config, reader, records=None):
    from test_weekly import add_session
    from conftest import SESSION_ID
    add_session(config, SESSION_ID, records if records is not None else chat(), PROJECT)
    return daily.run_daily(config, "reading", call=reader)


def entries_of(config, kind, name, scope=ledger.SCOPE_GLOBAL):
    return ledger.load_ledger(ledger.ledgers_dir_of(config.paths.data_dir), ledger.ItemId(scope, kind, name))["entries"]


def data_file(config, name):
    return json.loads(Path(ledger.ledgers_dir_of(config.paths.data_dir), name).read_text(encoding="utf-8"))


# --- A: a list of known names, and names that resolve ---


def test_the_list_holds_each_kind_with_description_and_display_name_and_only_this_folders_memories(tree):
    write_inventory(tree)
    text = backfill.known_items_text(tree, PROJECT)
    assert "skill tea-brewing: Brews tea" in text
    assert 'hook kettle_gate (shown as "Kettle gate", "Shared label"): Stop hook: refuse to end the turn while the kettle is on.' in text
    assert "mcp cupboard" in text
    assert "plugin teapot@shelf: Pours tea." in text
    assert "memory biscuits: About biscuits" in text
    assert "saucers" not in text


def test_the_list_cuts_descriptions_to_the_configured_length(tree):
    write_inventory(tree)
    limit = tree.item_check.listing_description_chars
    line = next(line for line in backfill.known_items_text(tree, PROJECT).splitlines() if line.startswith("skill tea-brewing"))
    assert len(line) <= len("skill tea-brewing: ") + limit + 1
    assert "at all" not in line


def test_a_chunk_is_read_with_the_list_before_the_timeline_and_its_size_is_recorded(tree):
    write_inventory(tree)
    reader = Reader(note())
    run_daily_with(tree, reader)
    sent = reader.calls[0]["stdin_text"]
    assert sent.index("<known_items") < sent.index("<user_timeline") < sent.index("<session_part")
    assert "hook kettle_gate" in sent
    chunk = next(Path(tree.paths.data_dir, "notes").glob("*/*/chunk-001.json"))
    assert json.loads(chunk.read_text(encoding="utf-8"))["known_items_chars"] > 0


def test_the_prompt_requires_names_from_the_list_or_a_marked_unknown():
    prompt = extract.read_prompt()
    assert "<known_items>" in prompt
    assert "unknown:" in prompt


@pytest.mark.parametrize("name", ["kettle_gate", "KETTLE_GATE", "Kettle gate", "kettle GATE"])
def test_exact_name_alias_and_any_case_reach_the_hook_ledger(tree, name):
    write_inventory(tree)
    run_daily_with(tree, Reader(stance_note(("hook", name, "against"))))
    assert len(entries_of(tree, "hook", "kettle_gate")) == 1
    assert data_file(tree, ledger.UNMAPPED_FILE)["mentions"] == []


def test_a_display_name_two_scripts_share_cannot_be_told_apart(tree):
    write_inventory(tree)
    run_daily_with(tree, Reader(stance_note(("hook", "Shared label", "against"))))
    assert [item["reason"] for item in data_file(tree, ledger.UNMAPPED_FILE)["mentions"]] == [ledger.UNMAPPED_AMBIGUOUS]


def test_a_marked_unknown_and_a_real_mismatch_go_to_unmapped_whatever_their_stance(tree):
    write_inventory(tree)
    run_daily_with(tree, Reader(stance_note(("hook", "unknown: milk jug", "against"), ("skill", "no-such-skill", "no_bearing"), ("memory", "saucers", "for"))))
    assert [(item["name"], item["stance"], item["reason"]) for item in data_file(tree, ledger.UNMAPPED_FILE)["mentions"]] == [
        ("unknown: milk jug", "against", ledger.UNMAPPED_MARKED_UNKNOWN),
        ("no-such-skill", "no_bearing", ledger.UNMAPPED_NO_SUCH_ITEM),
        ("saucers", "for", ledger.UNMAPPED_NO_SUCH_ITEM),
    ]


# --- B: stances are checked ---


def test_one_tool_less_call_judges_the_stances_of_a_pass_given_the_items_contents(tree):
    write_inventory(tree)
    reader = Reader(stance_note(("skill", "tea-brewing", "for"), ("memory", "biscuits", "against"), ("hook", "kettle_gate", "no_bearing")))
    result = run_daily_with(tree, reader)
    calls = reader.stance_calls()
    assert len(calls) == 1
    call = calls[0]
    assert call["tools"] == ()
    assert call["model"] == tree.item_check.model
    text = call["stdin_text"]
    assert "Step 1: boil water." in text and "Biscuits go on the left." in text
    assert "The kettle gate blocked the turn." in text and "HOOK-BLOCK" in text
    assert "abcdefgh12345678" not in text, "contents are redacted"
    assert "kettle_gate" in text, "a no_bearing mention is judged too"
    assert result["ledger"]["notes"]["entries_added"] == 2
    assert result["stance_check"]["kept"] == 3


def test_no_call_when_no_note_names_an_item_and_none_on_a_second_pass(tree):
    write_inventory(tree)
    reader = Reader(note())
    run_daily_with(tree, reader)
    assert reader.stance_calls() == []
    named = Reader(stance_note(("skill", "tea-brewing", "for")))
    from conftest import SESSION_ID
    from test_weekly import add_session
    add_session(tree, "00000000-0000-4000-8000-000000000002", chat(), PROJECT)
    daily.run_daily(tree, "second", call=named)
    assert len(named.stance_calls()) == 1
    again = Reader()
    daily.run_daily(tree, "third", call=again)
    assert again.stance_calls() == []
    assert SESSION_ID


def test_a_refused_stance_makes_no_entry_and_is_recorded_with_its_reason(tree):
    write_inventory(tree)
    result = run_daily_with(tree, Reader(stance_note(("skill", "tea-brewing", "for"), ("memory", "biscuits", "against")), refuse=("tea-brewing",)))
    assert entries_of(tree, "skill", "tea-brewing") == []
    assert len(entries_of(tree, "memory", "biscuits", ledger.project_scope(PROJECT))) == 1
    judged = data_file(tree, ledger.VERDICTS_FILE)["mentions"]
    assert [(item["name"], item["stance"], item["verdict"], item["reason"]) for item in judged if item["verdict"] != "kept"] == [("tea-brewing", "for", "refused", "made up for a test")]
    assert result["ledger"]["notes"]["mentions_refused"] == 1
    assert result["stance_check"]["refused"] == 1


def test_a_failed_check_adds_no_entry_fails_the_pass_and_is_tried_again(tree):
    write_inventory(tree)
    failing = Reader(stance_note(("skill", "tea-brewing", "for")), stance_error=model_call.ModelCallError("no"))
    result = run_daily_with(tree, failing)
    assert result["status"] == daily.STATUS_FAILED
    assert "stance" in result["stop_reason"]
    assert entries_of(tree, "skill", "tea-brewing") == []
    assert result["ledger"]["notes"]["mentions_awaiting_check"] == 1
    retry = Reader()
    result = daily.run_daily(tree, "retry", call=retry)
    assert result["status"] == daily.STATUS_OK
    assert len(retry.stance_calls()) == 1
    assert len(entries_of(tree, "skill", "tea-brewing")) == 1


def test_a_reply_that_leaves_out_a_stance_fails_the_check_and_adds_nothing(tree):
    write_inventory(tree)

    class Silent(Reader):
        def __call__(self, **kwargs):
            if kwargs["prompt"].startswith("You are judging"):
                self.calls.append(kwargs)
                return model_call.ModelResult(
                    text='{"verdicts": []}', usage={"input_tokens": 1, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 1},
                    model_usage={"m": {}}, cost_usd=0.1, duration_ms=1, num_turns=1, command_line=("claude",),
                )
            return super().__call__(**kwargs)

    result = run_daily_with(tree, Silent(stance_note(("skill", "tea-brewing", "for"))))
    assert result["status"] == daily.STATUS_FAILED
    assert entries_of(tree, "skill", "tea-brewing") == []


def test_the_budget_running_out_at_the_check_leaves_the_stance_waiting(tree):
    write_inventory(tree)
    result = run_daily_with(tree, Reader(stance_note(("skill", "tea-brewing", "for")), stance_error=model_call.BudgetExhaustedError("spent")))
    assert result["status"] == daily.STATUS_BUDGET_STOPPED
    assert entries_of(tree, "skill", "tea-brewing") == []


def test_long_contents_are_cut_where_it_shows(tree):
    write_inventory(tree)
    small = dataclasses.replace(tree, item_check=dataclasses.replace(tree.item_check, item_chars=20))
    reader = Reader(stance_note(("skill", "tea-brewing", "for")))
    run_daily_with(small, reader)
    assert "...[CUT " in reader.stance_calls()[0]["stdin_text"]


def test_a_refused_stance_does_not_make_a_note_speak_of_a_memory(tree):
    write_inventory(tree)
    run_daily_with(tree, Reader(stance_note(("memory", "biscuits", "against")), refuse=("biscuits",)))
    path = next(Path(tree.paths.data_dir, "notes").glob("*/*/chunk-001.json"))
    window = weekly_notes.Window("k", "s", PROJECT, "/w", NOW, NOW, None)
    records = weekly_notes._records_of_chunk(str(path), window, tree.paths.data_dir)
    assert records[0].items[0]["stance"] == schemas.STANCE_NO_BEARING
    assert not weekly_notes.is_memory_note(records[0], tree.weekly)


def test_the_extraction_prompt_states_the_stance_rules():
    prompt = extract.read_prompt()
    for words in ("ordinary default", "visibly caused harm", "second-hand", "one of"):
        assert words in prompt


def test_the_prompt_for_the_check_holds_no_session_material_and_answers_in_verdicts():
    prompt = Path(stance_check.PROMPT_PATH).read_text(encoding="utf-8")
    assert prompt.startswith("You are judging")
    assert '"verdicts"' in prompt


# --- B3: balance over weeks ---

RULE = LedgerConfig(1, 3, 28, 0.5, 28, (), ())
AS_OF = datetime(2030, 6, 1, tzinfo=timezone.utc)


def dated(entry_id, session, direction, basis=schemas.BASIS_INFERRED, days_ago=3):
    user = basis != schemas.BASIS_INFERRED
    return {
        "id": entry_id, "date": (AS_OF - timedelta(days=days_ago)).isoformat(), "session": session, "project_folder": "f",
        "direction": direction, "who": "user" if user else "agent", "basis": basis, "what": "x", "quote": "q" if user else "",
        "quote_check": schemas.QUOTE_VERIFIED if user else schemas.QUOTE_NONE, "origin_of_point": "assistant",
        "source": {"notes": f"notes/{entry_id}", "note_index": 0},
    }


def balance(*entries):
    return ledger.lost_balance({"identity": {"scope": "global", "kind": "skill", "name": "x"}, "entries": list(entries)}, AS_OF, RULE)


def test_one_inferred_for_no_longer_clears_a_clear_majority_against():
    flag = balance(*[dated(f"a{n}", f"s{n}", "against") for n in range(4)], dated("f", "s9", "for"))
    assert flag["reason"] == ledger.REASON_INFERRED
    assert flag["entries_for"] == ["f"]


def test_the_balance_must_reach_the_threshold():
    assert balance(*[dated(f"a{n}", f"s{n}", "against") for n in range(3)], dated("f", "s9", "for")) is None


def test_balance_counts_sessions_not_entries():
    many_for_one_session = [dated(f"f{n}", "s9", "for") for n in range(5)]
    assert balance(*[dated(f"a{n}", f"s{n}", "against") for n in range(4)], *many_for_one_session) is not None
    assert balance(*[dated(f"a{n}", "s1", "against") for n in range(5)]) is None


def test_a_session_on_both_sides_counts_on_both():
    assert balance(*[dated(f"a{n}", f"s{n}", "against") for n in range(4)], dated("f", "s0", "for")) is not None
    assert balance(*[dated(f"a{n}", f"s{n}", "against") for n in range(3)], dated("f", "s0", "for")) is None


def test_a_direct_for_in_the_window_still_holds_inference_back():
    assert balance(*[dated(f"a{n}", f"s{n}", "against", days_ago=2) for n in range(6)], dated("f", "s9", "for", schemas.BASIS_DIRECT, days_ago=10)) is None


def test_a_direct_against_still_flags_alone():
    assert balance(dated("a", "s1", "against", schemas.BASIS_DIRECT), dated("f", "s2", "for"))["reason"] == ledger.REASON_DIRECT


def test_a_for_outside_the_window_does_not_count():
    assert balance(*[dated(f"a{n}", f"s{n}", "against") for n in range(3)], dated("f", "s9", "for", days_ago=40)) is not None


# --- C: one statement split into claims ---

STATEMENT = "print reports short unless the review is long"
STRICT = "Reports are kept short."
QUALIFIER = "A long review may have long reports."


def split_tree(config, **note_overrides):
    read_notes(config, note(**note_overrides), records=chat(STATEMENT))
    mark_daily_done(config)


def test_when_one_half_of_a_statement_is_rejected_the_other_becomes_a_proposal(tree):
    split_tree(tree)
    fake = FakeCall(
        memory=memory_reply(
            change(memory="report-size", claim=STRICT, quote="print reports short"),
            change(memory="long-reviews", claim=QUALIFIER, quote="unless the review is long", title="Long reviews"),
        ),
        verdicts={"long review": "does_not_support"},
    )
    assert run(tree, LIVE, fake)["status"] == "ok"
    report = report_of(tree)
    assert report["memory_changes"] == []
    assert not memory_path(tree, "report-size").exists()
    split = [item for item in report["proposals"] if item["kind"] == weekly.KIND_MEMORY_SPLIT]
    assert [(item["target"], item["exact_change"]) for item in split] == [("report-size", STRICT)]
    assert QUALIFIER in split[0]["why"]
    assert [item["subject"] for item in report["rejected"]] == ["long-reviews"]


def test_a_half_rejected_by_the_script_also_counts(tree):
    split_tree(tree)
    fake = FakeCall(memory=memory_reply(
        change(memory="report-size", claim=STRICT, quote="print reports short"),
        change(memory="long-reviews", claim=QUALIFIER, quote="the review", title="Long reviews"),
    ))
    run(tree, DRY, fake)
    report = report_of(tree)
    assert report["memory_changes"] == []
    assert [item["kind"] for item in report["proposals"]] == [weekly.KIND_MEMORY_SPLIT]


def test_claims_from_different_statements_stay_apart(tree):
    read_notes(tree, note(), note(what="A second point."), records=[*chat("print reports short", 1), *chat("a long review may run on", 5)])
    mark_daily_done(tree)
    fake = FakeCall(
        memory=memory_reply(
            change(memory="report-size", claim=STRICT, quote="print reports short"),
            change(memory="long-reviews", note="n2", claim=QUALIFIER, quote="a long review may run on", title="Long reviews"),
        ),
        verdicts={"long review": "does_not_support"},
    )
    run(tree, DRY, fake)
    report = report_of(tree)
    assert [item["memory"] for item in report["memory_changes"]] == ["report-size"]
    assert [item for item in report["proposals"] if item["kind"] == weekly.KIND_MEMORY_SPLIT] == []


def test_a_claim_that_does_not_fit_the_file_says_nothing_about_its_sibling(tree):
    add_memory(tree, "report-size", "Reports are kept short.")
    split_tree(tree)
    fake = FakeCall(memory=memory_reply(
        change(action="add", memory="report-size", claim=STRICT, quote="print reports short", title=""),
        change(memory="long-reviews", claim=QUALIFIER, quote="unless the review is long", title="Long reviews"),
    ))
    run(tree, DRY, fake)
    report = report_of(tree)
    assert [item["memory"] for item in report["memory_changes"]] == ["long-reviews"]
    assert [item["reason"] for item in report["rejected"]] == [weekly_gate.REJECT_PRESENT]


def test_a_split_replace_goes_to_a_reread_since_it_cannot_be_written_by_adding(tree):
    add_memory(tree, "report-size", "Reports may run on.")
    split_tree(tree)
    fake = FakeCall(
        memory=memory_reply(
            change(action="replace", memory="report-size", claim=STRICT, old_text="Reports may run on.", quote="print reports short", title=""),
            change(memory="long-reviews", claim=QUALIFIER, quote="unless the review is long", title="Long reviews"),
        ),
        verdicts={"long review": "does_not_support"},
    )
    run(tree, DRY, fake)
    report = report_of(tree)
    assert [item["kind"] for item in report["proposals"]] == [weekly.KIND_MEMORY_REVISION]
    assert STRICT in report["proposals"][0]["what"]


def test_a_split_proposal_is_written_by_approve_and_shown_with_a_label(tree):
    split_tree(tree)
    fake = FakeCall(
        memory=memory_reply(
            change(memory="report-size", claim=STRICT, quote="print reports short"),
            change(memory="long-reviews", claim=QUALIFIER, quote="unless the review is long", title="Long reviews"),
        ),
        verdicts={"long review": "does_not_support"},
    )
    run(tree, DRY, fake)
    review = review_data.latest_review(tree.paths.data_dir)
    item = next(item for item in review["items"] if item["record"].get("kind") == weekly.KIND_MEMORY_SPLIT)
    assert item["section"] == schemas.SECTION_PROPOSAL
    assert weekly.KIND_MEMORY_SPLIT in review_data.review_page._KIND_LABEL
    assert weekly.KIND_MEMORY_SPLIT in review_data.review_page._APPROVE_DOES
    outcome = review_session.approve_memory(tree, review["review_id"], item["number"], NOW)
    assert outcome["outcome"] == schemas.OUTCOME_APPROVED
    assert STRICT in memory_path(tree, "report-size").read_text(encoding="utf-8")


# --- D: what the weekly memory prompt asks, and what a fact is called ---


def test_the_weekly_memory_prompt_refuses_what_the_repo_records_and_states_of_one_day():
    prompt = Path(weekly.MEMORY_PROMPT).read_text(encoding="utf-8")
    assert "repository, its plans or its docs" in prompt
    assert "true only today" in prompt


def test_a_fact_proposal_is_titled_by_the_model_with_the_fact(tree):
    read_notes(tree, note(endorsement="none", endorsement_quote="", origin_of_point="tool_result", memory_candidate=True))
    mark_daily_done(tree)
    fake = FakeCall(memory=memory_reply(facts=[{"memory": "kiln", "note": "n1", "claim": "The kiln cools in four hours.", "title": "Kiln cools in four hours"}]))
    run(tree, DRY, fake)
    assert [item["title"] for item in report_of(tree)["proposals"]] == ["Kiln cools in four hours"]


def test_a_fact_proposal_without_a_title_is_refused_by_the_schema():
    with pytest.raises(schemas.SchemaError):
        schemas.parse_memory_reply(json.dumps({"changes": [], "fact_proposals": [{"memory": "kiln", "note": "n1", "claim": "The kiln cools."}]}))


def test_render_frames_the_new_tags():
    assert render.neutralise_tags("<known_items>") != "<known_items>"
    assert render.neutralise_tags("</stances>") != "</stances>"


def test_ledger_keeps_a_stance_checks_file_inside_the_window_so_discarding_takes_it(tree):
    write_inventory(tree)
    run_daily_with(tree, Reader(stance_note(("skill", "tea-brewing", "for"))))
    window = next(Path(tree.paths.data_dir, "notes").glob("*/*"))
    assert (window / ledger.STANCE_CHECKS_FILE).exists()
    assert os.path.isdir(window)
