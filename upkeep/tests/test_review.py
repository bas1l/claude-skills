"""The review: page, data, session actions and launcher, on synthetic data only."""
from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

import pytest
from conftest import synthetic_inventory

import ledger
import memory_store
import review_data
import review_page
import review_session
import schemas
from config import InventoryConfig

NOW = datetime(2031, 1, 15, 12, 0, tzinfo=timezone.utc)
WEEK = "2031-W03"
EARLIER = "2031-W02"
PROJECT = "C--work-project"
SESSION = "00000000-0000-4000-8000-000000000009"
EVIL = "<script>alert('x')</script><img src=https://evil.example/a.png>"
UPKEEP = Path(__file__).resolve().parent.parent
START_SCRIPT = UPKEEP / "Start-UpkeepReview.ps1"
SKILL_FILE = UPKEEP.parent / "upkeep-review" / "SKILL.md"


@pytest.fixture
def tree(config, tmp_path):
    projects = tmp_path / "projects"
    (projects / PROJECT).mkdir(parents=True)
    data = tmp_path / "upkeep"
    data.mkdir()
    inventory = synthetic_inventory(tmp_path)
    (data / "local.json").write_text(json.dumps({"python_exe": "python", "apply_memory_changes": True, "private_terms": ["secretproject"]}), encoding="utf-8")
    built = dataclasses.replace(
        config,
        paths=dataclasses.replace(config.paths, projects_dir=str(projects), data_dir=str(data), run_dir=str(data / "run"), local_settings=str(data / "local.json")),
        memory=dataclasses.replace(config.memory, author_name="Test Author", author_email="test@example.invalid"),
        inventory=InventoryConfig(**{**inventory, "optional_settings_files": ()}),
    )
    memory_store.init_upkeep_repo(str(data), built.memory)
    return built


def memory_folder(config, project=PROJECT):
    return os.path.join(config.paths.projects_dir, project, "memory")


def change(number=1, week=WEEK, **overrides):
    values = {
        "id": f"change{number}", "project_folder": PROJECT, "memory": f"memory-{number}", "action": "create",
        "claim": f"Claim {number}.", "old_text": "", "endorsement": "said", "quote": f"quote {number}", "assistant_statement": "",
        "session": SESSION, "source": {"notes": f"notes/2031-01-10/{SESSION}/chunk-001.json", "note_index": 0},
        "new_evidence": False, "outcome": "would_apply", "commit": None, "before": None, "after": f"Claim {number}.\n",
    }
    values.update(overrides)
    return values


def proposal(number=1, **overrides):
    values = {
        "id": f"hook-{number}", "kind": "hook", "change_type": "change", "title": f"Proposal {number}", "what": f"What {number}.",
        "why": "Saves commands.", "target": "some_hook", "basis": "failure_cost",
        "evidence": {"notes": [{"session": SESSION, "source": {"notes": f"notes/2031-01-10/{SESSION}/chunk-001.json", "note_index": 0}, "what": "Seen.", "quote": ""}], "failure": None, "procedure": None},
        "exact_change": "Change the block message.", "draft_path": None, "research": None, "status": "open", "project_folder": "",
    }
    values.update(overrides)
    return values


def report(week=WEEK, changes=(), proposals=(), generated=NOW, **overrides):
    values = {
        "schema_version": schemas.WEEKLY_REPORT_SCHEMA_VERSION, "week": week, "run_id": "run1", "generated_at": generated.isoformat(),
        "status": "ok", "stop_reason": None, "apply_enabled": True, "coverage": {},
        "memory_changes": list(changes), "rejected": [], "proposals": list(proposals), "held": [],
        "failures_ranked": [], "before_after": [], "usage": {},
    }
    values.update(overrides)
    return values


def publish(config, document, now=NOW):
    """Write a report and its review, as the weekly pass does."""
    folder = Path(config.paths.data_dir) / "reports" / document["week"]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "report.json").write_text(json.dumps(document), encoding="utf-8")
    return review_data.build_review(config, document, now), review_data.write_review(config, document, now)


def current(config):
    return review_data.latest_review(config.paths.data_dir)


def write_note_file(config, what="A note."):
    path = Path(config.paths.data_dir) / "notes" / "2031-01-10" / SESSION / "chunk-001.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"session_id": SESSION, "project_folder": PROJECT, "last": NOW.isoformat(), "notes": [{"what": what}]}), encoding="utf-8")


def ensure_memory_ledger(config, name):
    item = ledger.ItemId(ledger.project_scope(PROJECT), ledger.KIND_MEMORY, name)
    ensure(config, item)
    return item


def ensure(config, item):
    ledger.ensure_ledger(
        ledger.ledgers_dir_of(config.paths.data_dir), item,
        {"reason": "A reason.", "status": schemas.FOUNDING_VERIFIED, "source": "discussion"},
        {"status": schemas.LIMIT_NOT_STATED, "text": None},
        {"status": schemas.ORIGIN_NOT_APPLICABLE, "session": None, "project_folder": None, "at": None, "tool": None, "creating_call_found": None},
        NOW.isoformat(),
    )


def apply_for_real(config, name, before, after, week="2031-W01"):
    """Commit a change to a memory the way the pass does. Returns the commit."""
    folder = memory_folder(config)
    os.makedirs(folder, exist_ok=True)
    if before is not None:
        with open(os.path.join(folder, f"{name}.md"), "w", encoding="utf-8", newline="") as handle:
            handle.write(before)
    index = []
    if before is None:
        index = [memory_store.IndexEdit(f"{name}.md", memory_store.index_line(name, f"{name}.md", "hook"))]
    outcome = memory_store.apply_memory_writes(
        folder, [memory_store.FileWrite(f"{name}.md", before, after)], index, config.memory, week, f"Upkeep weekly {week}",
    )
    return outcome["commit"]


def log_of(folder, *arguments):
    return subprocess.run(["git", "-C", folder, "log", "--format=%H|%an|%ae|%B", *arguments], capture_output=True, encoding="utf-8", check=True).stdout


def commit_count(folder):
    return int(subprocess.run(["git", "-C", folder, "rev-list", "--count", "HEAD"], capture_output=True, encoding="utf-8", check=True).stdout)


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def tags_of(page):
    parser = _Tags()
    parser.feed(page)
    return parser.tags


def research_record(**overrides):
    values = {
        "schema_version": 1, "description": EVIL, "searched": [{"query": EVIL, "worked": True}],
        "fetched": [{"url": "https://docs.example/page", "worked": True}], "official_features": EVIL,
        "existing_tools": [{"name": EVIL, "url": "https://tool.example/", "maintenance_evidence": EVIL, "can_execute": EVIL}],
        "conventions": EVIL, "sources": [{"url": "javascript:alert(1)", "title": EVIL, "used_for": EVIL}],
        "recommendation": "adopt", "recommendation_reason": EVIL, "cost_usd": 0.1,
    }
    values.update(overrides)
    return values


def hostile_review(config):
    document = report(
        changes=[change(1, claim=EVIL, quote=EVIL, memory="short", after=EVIL, before=EVIL, session=EVIL, old_text=EVIL, assistant_statement=EVIL, endorsement="accepted", project_folder=PROJECT)],
        proposals=[proposal(1, title=EVIL, what=EVIL, why=EVIL, target="", exact_change=EVIL, research=research_record(), kind="skill", draft_path=EVIL)],
        held=[proposal(2, kind="skill", status="held:below_recurrence_threshold", title=EVIL, what=EVIL, research=research_record())],
        rejected=[{"subject": EVIL, "project_folder": PROJECT, "reason": EVIL, "detail": EVIL, "claim": EVIL, "quote": EVIL, "source": None}],
        failures_ranked=[{"ref": "f1", "tool": EVIL, "signature": EVIL, "commands_lost": 3, "sessions": 1}],
        status="failed", stop_reason=EVIL,
    )
    return review_data.build_review(config, document, NOW)


def test_transcript_text_stays_inert(tree):
    review = hostile_review(tree)
    page = review_page.render_page(review)
    assert "<script" not in page.lower()
    assert "<img" not in page.lower()
    assert page.count("&lt;script&gt;") >= 15


def test_page_has_no_scripts_no_remote_assets_and_only_plain_external_anchors(tree):
    page = review_page.render_page(hostile_review(tree))
    tags = tags_of(page)
    forbidden = {"script", "img", "iframe", "link", "object", "embed", "audio", "video", "source", "form", "base", "svg", "input", "button"}
    assert not {tag for tag, _ in tags} & forbidden
    for tag, attributes in tags:
        assert not {name for name in attributes if name.startswith("on") or name in ("src", "srcset", "srcdoc", "background", "action", "formaction")}, tag
        if "href" in attributes:
            assert tag == "a"
            assert attributes["href"].startswith(("https://", "http://"))
            assert attributes["rel"] == "noreferrer"
    assert "url(" not in page and "@import" not in page
    assert "Content-Security-Policy" in page and "default-src 'none'" in page
    assert page.count("external site:") == sum(1 for tag, attributes in tags if tag == "a")


def test_a_link_that_is_not_a_web_address_is_only_text(tree):
    page = review_page.render_page(hostile_review(tree))
    assert 'href="javascript' not in page
    assert "not a web link" in page


def test_applied_memory_says_it_stays_and_proposals_say_nothing_happens(tree):
    page = review_page.render_page(review_data.build_review(tree, report(changes=[change(outcome="applied", commit="abc")], proposals=[proposal()]), NOW))
    assert "Already applied, stays unless you undo." in page
    assert "Nothing happens unless you approve." in page
    assert "<code>undo 1</code>" in page and "<code>approve 2</code>" in page


def test_trial_run_says_would_apply(tree):
    page = review_page.render_page(review_data.build_review(tree, report(changes=[change()], apply_enabled=False), NOW))
    assert "Would apply." in page and "trial run" in page
    assert "Already applied, stays" not in page


def test_overdue_and_failures_come_before_the_items(tree):
    review = review_data.build_review(tree, report(changes=[change()], status="failed", stop_reason="the search stopped"), NOW)
    review["weeks_overdue"] = 2
    page = review_page.render_page(review)
    assert page.index("2 weeks overdue") < page.index("<article")
    assert page.index("the search stopped") < page.index("<article")


def test_a_failed_run_with_nothing_still_renders(tree):
    page = review_page.render_page(review_data.build_review(tree, report(status="failed", stop_reason="stopped early"), NOW))
    assert "stopped early" in page and "Nothing here this week." in page


def test_an_unknown_kind_raises(tree):
    review = review_data.build_review(tree, report(proposals=[proposal()]), NOW)
    review["items"][0]["record"]["kind"] = "new_kind"
    with pytest.raises(KeyError):
        review_page.render_page(review)


# ---------------------------------------------------------------------------
# review.json
# ---------------------------------------------------------------------------


def test_numbers_run_across_sections_with_carried_items_after_newer_ones(tree):
    publish(tree, report(EARLIER, [change(1, outcome="applied", commit="c1")], [proposal(1)], generated=NOW - timedelta(days=7)), NOW - timedelta(days=7))
    review, _ = publish(tree, report(WEEK, [change(2, outcome="applied", commit="c2")], [proposal(2)]))
    assert [(item["number"], item["section"], item["week"], item["carried"]) for item in review["items"]] == [
        (1, "memory", WEEK, False), (2, "memory", EARLIER, True), (3, "proposal", WEEK, False), (4, "proposal", EARLIER, True),
    ]
    assert review["items"][1]["record"]["id"] == "change1"


def test_a_carried_item_offered_again_does_not_repeat_as_new(tree):
    publish(tree, report(EARLIER, [change(1, outcome="applied", commit="c1")], [proposal(1)], generated=NOW - timedelta(days=7)), NOW - timedelta(days=7))
    reworded = proposal(1, title="Worded otherwise", what="Other words.", status="already_open")
    review, _ = publish(tree, report(WEEK, [change(1, outcome="applied", commit="c1")], [proposal(1), reworded]))
    assert [(item["key"].split(":")[1], item["week"]) for item in review["items"]] == [("change1", EARLIER), ("hook-1", EARLIER)]


def test_an_open_proposal_reworded_under_a_new_id_does_not_repeat_as_new(tree):
    wording = "Change the block message so that only the missing part is sent again."
    publish(tree, report(EARLIER, proposals=[proposal(1, what=wording)], generated=NOW - timedelta(days=7)), NOW - timedelta(days=7))
    review, _ = publish(tree, report(WEEK, proposals=[proposal(2, what=f"{wording} Fully.", title="Another title"), proposal(3, what="Stop checking scheduled runs at all.")]))
    assert [(item["record"]["id"], item["week"]) for item in review["items"]] == [("hook-3", WEEK), ("hook-1", EARLIER)]


def test_same_id_different_wording_stays_two_items(tree):
    review = review_data.build_review(tree, report(proposals=[proposal(1), proposal(1, title="Another", what="Another thing.")]), NOW)
    assert len(review["items"]) == 2


def test_a_trial_run_change_is_not_carried(tree):
    publish(tree, report(EARLIER, [change(1)], generated=NOW - timedelta(days=7)), NOW - timedelta(days=7))
    review, _ = publish(tree, report(WEEK))
    assert review["items"] == []


def test_a_decided_item_is_not_carried_and_a_skipped_one_is(tree):
    publish(tree, report(EARLIER, proposals=[proposal(1), proposal(2)], generated=NOW - timedelta(days=7)), NOW - timedelta(days=7))
    earlier = current(tree)
    review_session.reject(tree, earlier["review_id"], 1, SESSION, NOW - timedelta(days=6))
    review_session.skip(tree, earlier["review_id"], 2, NOW - timedelta(days=6))
    review, _ = publish(tree, report(WEEK))
    assert [item["record"]["id"] for item in review["items"]] == ["hook-2"]
    assert review["items"][0]["carried"] and review["items"][0]["week"] == EARLIER and review["items"][0]["skipped_at"]


def test_a_review_built_again_in_its_week_keeps_decisions(tree):
    publish(tree, report(proposals=[proposal(1), proposal(2)]))
    review_session.reject(tree, current(tree)["review_id"], 1, SESSION, NOW)
    review, _ = publish(tree, report(proposals=[proposal(2), proposal(3)]))
    outcomes = {item["record"]["id"]: None if item["decision"] is None else item["decision"]["outcome"] for item in review["items"]}
    assert outcomes == {"hook-1": "rejected", "hook-2": None, "hook-3": None}


def test_review_rejects_a_gap_in_numbers(tree):
    review = review_data.build_review(tree, report(proposals=[proposal(1), proposal(2)]), NOW)
    review["items"][1]["number"] = 5
    with pytest.raises(schemas.SchemaError):
        schemas.validate_review(review, "test")


def test_weeks_overdue_counts_from_the_oldest_report_with_no_action_since(tree):
    publish(tree, report(EARLIER, proposals=[proposal(1)], generated=NOW - timedelta(days=7)), NOW - timedelta(days=7))
    publish(tree, report(WEEK, proposals=[proposal(2)]))
    assert review_data.weeks_overdue(tree.paths.data_dir, NOW) == 1
    assert review_data.weeks_overdue(tree.paths.data_dir, NOW + timedelta(days=14)) == 3
    review_session.skip(tree, current(tree)["review_id"], 1, NOW + timedelta(minutes=1))
    assert review_data.weeks_overdue(tree.paths.data_dir, NOW + timedelta(days=14)) == 0


def test_a_report_set_aside_under_another_name_is_not_a_week(tree):
    aside = Path(tree.paths.data_dir) / "reports" / "2031-W09-first-dry-run"
    aside.mkdir(parents=True)
    (aside / "report.json").write_text(json.dumps(report("2031-W09", generated=NOW - timedelta(days=90))), encoding="utf-8")
    publish(tree, report(WEEK))
    assert review_data.week_folders(tree.paths.data_dir) == [WEEK]
    assert current(tree)["week"] == WEEK
    assert review_data.weeks_overdue(tree.paths.data_dir, NOW) == 0


def test_refresh_brings_failures_up_to_date_and_leaves_numbers_alone(tree):
    publish(tree, report(WEEK, proposals=[proposal(1)]))
    before = current(tree)
    (Path(tree.paths.data_dir) / review_data.MARKER_FILE).write_text(json.dumps({"schema_version": 1, "entries": [{"kind": "failed", "summary": "the daily pass failed"}]}), encoding="utf-8")
    page = review_data.refresh_review(tree, NOW + timedelta(days=7))
    after = current(tree)
    assert after["review_id"] == before["review_id"] and after["items"] == before["items"]
    assert after["weeks_overdue"] == 1
    assert "the daily pass failed" in Path(page).read_text(encoding="utf-8")


def write_feed(config, name, proposals, generated=NOW):
    folder = Path(config.paths.data_dir) / "reports" / review_data.MONTHLY_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.json").write_text(json.dumps({"schema_version": 1, "source": "monthly", "run_id": "m1", "generated_at": generated.isoformat(), "proposals": proposals}), encoding="utf-8")


def test_monthly_results_join_the_next_review_once(tree):
    write_feed(tree, "2031-01", [proposal(7, kind="global_rule", target="")], NOW - timedelta(days=7))
    first, _ = publish(tree, report(EARLIER, generated=NOW - timedelta(days=7)), NOW - timedelta(days=7))
    assert [(item["origin"], item["record"]["id"]) for item in first["items"]] == [("monthly", "hook-7")]
    review_session.reject(tree, first["review_id"], 1, SESSION, NOW - timedelta(days=6))
    second, _ = publish(tree, report(WEEK))
    assert second["items"] == []


def test_a_malformed_monthly_result_raises(tree):
    write_feed(tree, "bad", [{"id": "x"}])
    with pytest.raises(review_data.ReviewDataError):
        review_data.build_review(tree, report(WEEK), NOW)


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_a_number_that_does_not_exist_is_refused(tree):
    publish(tree, report(proposals=[proposal(1)]))
    review_id = current(tree)["review_id"]
    with pytest.raises(review_session.ReviewRefused, match="no item 3"):
        review_session.reject(tree, review_id, 3, SESSION, NOW)
    assert ledger.load_decisions(ledger.ledgers_dir_of(tree.paths.data_dir)) == []


def test_a_review_that_changed_is_refused(tree):
    publish(tree, report(proposals=[proposal(1), proposal(2)]))
    stale = current(tree)["review_id"]
    publish(tree, report(proposals=[proposal(2), proposal(1)]))
    with pytest.raises(review_session.ReviewRefused, match="changed since it was read"):
        review_session.reject(tree, stale, 1, SESSION, NOW)


def test_undo_cannot_hit_an_item_decided_or_of_the_wrong_section(tree):
    publish(tree, report(changes=[change(1)], proposals=[proposal(1)]))
    review_id = current(tree)["review_id"]
    with pytest.raises(review_session.ReviewRefused, match="cannot take 'undo'"):
        review_session.undo(tree, review_id, 2, SESSION, NOW)
    with pytest.raises(review_session.ReviewRefused, match="cannot take 'reject'"):
        review_session.reject(tree, review_id, 1, SESSION, NOW)
    review_session.reject(tree, review_id, 2, SESSION, NOW)
    with pytest.raises(review_session.ReviewRefused, match="already decided"):
        review_session.reject(tree, review_id, 2, SESSION, NOW)


def test_a_running_pass_blocks_actions(tree):
    publish(tree, report(proposals=[proposal(1)]))
    (Path(tree.paths.data_dir) / review_session.LOCK_FILE).write_text("{}", encoding="utf-8")
    with pytest.raises(review_session.ReviewRefused, match="holds"):
        review_session.keep(tree, current(tree)["review_id"], 1, NOW)


def test_command_line_refusal_exits_2_with_the_reason(tree, tmp_path, capsys):
    raw = json.loads((UPKEEP / "config.json").read_text(encoding="utf-8"))
    raw["paths"] = {**raw["paths"], "data_dir": tree.paths.data_dir, "projects_dir": tree.paths.projects_dir, "local_settings": tree.paths.local_settings}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    publish(tree, report(proposals=[proposal(1)]))
    assert review_session.main(["why", "9", "--config", str(path)]) == review_session.EXIT_REFUSED
    assert "no item 9" in capsys.readouterr().err
    assert review_session.main(["show", "--config", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["items"][0]["number"] == 1


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------


def applied(config, name, before, after, commit, number=1, action="create", claim="Claim."):
    return change(number, memory=name, before=before, after=after, commit=commit, outcome="applied", action=action, claim=claim)


def test_undo_of_a_new_memory_removes_it_by_a_new_commit_and_records_against(tree):
    commit = apply_for_real(tree, "alpha", None, "---\nname: alpha\n---\n\nA claim.\n")
    ensure_memory_ledger(tree, "alpha")
    publish(tree, report(changes=[applied(tree, "alpha", None, "---\nname: alpha\n---\n\nA claim.\n", commit)]))
    folder = memory_folder(tree)
    commits_before = commit_count(folder)
    result = review_session.undo(tree, current(tree)["review_id"], 1, SESSION, NOW)
    assert result["outcome"] == "undone"
    assert not os.path.exists(os.path.join(folder, "alpha.md"))
    assert "alpha.md" not in Path(folder, "MEMORY.md").read_text(encoding="utf-8")
    assert commit_count(folder) == commits_before + 1
    assert commit in log_of(folder)
    head = log_of(folder, "-1")
    assert "Test Author|test@example.invalid" in head and "Co-Authored-By" not in head and "Upkeep-Week" not in head

    ledgers_dir = ledger.ledgers_dir_of(tree.paths.data_dir)
    entries = ledger.load_ledger(ledgers_dir, ledger.ItemId(ledger.project_scope(PROJECT), "memory", "alpha"))["entries"]
    assert [(entry["direction"], entry["who"], entry["basis"], entry["session"]) for entry in entries] == [("against", "user", schemas.BASIS_REVIEW_DECISION, SESSION)]
    decision = ledger.load_decisions(ledgers_dir)[0]
    assert (decision["decision"], decision["name"], decision["action"]) == ("undone", "alpha", "create")
    assert current(tree)["items"][0]["decision"]["outcome"] == "undone"
    assert "new commit" in current(tree)["items"][0]["decision"]["detail"]


def test_undo_keeps_a_later_edit_in_other_lines_and_line_endings(tree):
    before = "---\r\nname: beta\r\n---\r\n\r\nFirst.\r\n\r\nSecond.\r\n"
    after = before.replace("Second.", "Second.\r\n\r\nAdded.")
    commit = apply_for_real(tree, "beta", before, after)
    path = os.path.join(memory_folder(tree), "beta.md")
    edited = after.replace("First.", "First, edited by a live session.")
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(edited)
    publish(tree, report(changes=[applied(tree, "beta", before, after, commit, action="add")]))
    review_session.undo(tree, current(tree)["review_id"], 1, SESSION, NOW)
    assert memory_store.read_memory_file(path) == before.replace("First.", "First, edited by a live session.")


def test_undo_of_a_change_with_a_newer_one_on_it_is_refused_until_the_newer_is_undone(tree):
    text_0 = "Start.\n"
    text_1 = "Start.\n\nOne.\n"
    text_2 = "Start.\n\nOne.\n\nTwo.\n"
    commit_1 = apply_for_real(tree, "gamma", text_0, text_1)
    commit_2 = apply_for_real(tree, "gamma", text_1, text_2, week="2031-W02")
    publish(tree, report(changes=[
        applied(tree, "gamma", text_0, text_1, commit_1, number=1, action="add"),
        applied(tree, "gamma", text_1, text_2, commit_2, number=2, action="add"),
    ]))
    review_id = current(tree)["review_id"]
    path = os.path.join(memory_folder(tree), "gamma.md")
    with pytest.raises(review_session.ReviewRefused, match="Undo the newer change"):
        review_session.undo(tree, review_id, 1, SESSION, NOW)
    assert memory_store.read_memory_file(path) == text_2
    assert ledger.load_decisions(ledger.ledgers_dir_of(tree.paths.data_dir)) == []
    review_session.undo(tree, review_id, 2, SESSION, NOW)
    assert memory_store.read_memory_file(path) == text_1
    review_session.undo(tree, review_id, 1, SESSION, NOW)
    assert memory_store.read_memory_file(path) == text_0


def test_undo_of_a_deleted_memory_restores_the_file_and_its_index_line(tree):
    folder = memory_folder(tree)
    os.makedirs(folder)
    text = "---\nname: delta\n---\n\nBody.\n"
    Path(folder, "delta.md").write_bytes(text.encode("utf-8"))
    line = memory_store.index_line("Delta", "delta.md", "hook")
    Path(folder, "MEMORY.md").write_text(f"{line}\n", encoding="utf-8")
    outcome = memory_store.apply_memory_writes(
        folder, [memory_store.FileWrite("delta.md", text, None)], [memory_store.IndexEdit("delta.md", None)], tree.memory, "2031-W01", "Upkeep",
    )
    publish(tree, report(changes=[applied(tree, "delta", text, None, outcome["commit"], action="delete")]))
    review_session.undo(tree, current(tree)["review_id"], 1, SESSION, NOW)
    assert memory_store.read_memory_file(os.path.join(folder, "delta.md")) == text
    assert line in Path(folder, "MEMORY.md").read_text(encoding="utf-8")


def test_undo_run_again_commits_nothing(tree):
    text_0, text_1 = "Start.\n", "Start.\n\nOne.\n"
    commit = apply_for_real(tree, "epsilon", text_0, text_1)
    folder = memory_folder(tree)
    first = memory_store.undo_change(folder, "epsilon.md", text_0, text_1, commit, tree.memory, "Undo")
    count = commit_count(folder)
    second = memory_store.undo_change(folder, "epsilon.md", text_0, text_1, commit, tree.memory, "Undo")
    assert first["result"] == memory_store.UNDO_RESTORED and second["result"] == memory_store.UNDO_ALREADY
    assert commit_count(folder) == count


def test_undo_with_an_unknown_commit_raises(tree):
    apply_for_real(tree, "zeta", "Start.\n", "Start.\n\nOne.\n")
    with pytest.raises(memory_store.MemoryStoreError, match="holds no commit"):
        memory_store.undo_change(memory_folder(tree), "zeta.md", "Start.\n", "Start.\n\nOne.\n", "0" * 40, tree.memory, "Undo")


def test_undo_on_a_trial_run_item_changes_no_memory_and_records_it(tree):
    publish(tree, report(changes=[change(1)], apply_enabled=False))
    result = review_session.undo(tree, current(tree)["review_id"], 1, SESSION, NOW)
    assert result["outcome"] == "rejected" and "trial run" in result["detail"]
    assert not os.path.exists(memory_folder(tree))
    assert ledger.load_decisions(ledger.ledgers_dir_of(tree.paths.data_dir))[0]["decision"] == "rejected"


def test_a_review_decision_does_not_count_towards_lost_balance(tree, config):
    item = ensure_memory_ledger(tree, "eta")
    ledgers_dir = ledger.ledgers_dir_of(tree.paths.data_dir)
    for number in range(4):
        ledger.append_entry(ledgers_dir, item, ledger.review_entry(f"e{number}", NOW.isoformat(), SESSION, PROJECT, "Undone", WEEK, f"k{number}"))
    assert ledger.lost_balance(ledger.load_ledger(ledgers_dir, item), NOW, config.ledger) is None


# ---------------------------------------------------------------------------
# Reject, keep, skip
# ---------------------------------------------------------------------------


def test_reject_adds_an_entry_when_the_item_has_a_ledger(tree):
    item = ledger.ItemId(ledger.SCOPE_GLOBAL, "hook", "some_hook")
    ensure(tree, item)
    publish(tree, report(proposals=[proposal(1)]))
    result = review_session.reject(tree, current(tree)["review_id"], 1, SESSION, NOW)
    ledgers_dir = ledger.ledgers_dir_of(tree.paths.data_dir)
    assert ledger.load_ledger(ledgers_dir, item)["entries"][0]["direction"] == "against"
    decision = ledger.load_decisions(ledgers_dir)[0]
    assert (decision["scope"], decision["kind"], decision["name"], decision["action"], decision["claim"]) == (
        ledger.SCOPE_GLOBAL, "hook", "some_hook", "change", "Proposal 1 What 1.",
    )
    assert "entry against" in result["detail"]


def test_reject_of_something_with_no_ledger_records_the_decision_and_says_so(tree):
    publish(tree, report(proposals=[proposal(1, kind="skill", target="", change_type="new")]))
    result = review_session.reject(tree, current(tree)["review_id"], 1, SESSION, NOW)
    assert "no ledger" in result["detail"]
    decision = ledger.load_decisions(ledger.ledgers_dir_of(tree.paths.data_dir))[0]
    assert (decision["name"], decision["action"]) == ("Proposal 1", "new")


def test_reject_of_a_fact_uses_the_terms_the_gate_compares(tree):
    fact = proposal(1, kind="memory_fact", target="theta", exact_change="A lasting fact.", project_folder=PROJECT, change_type="new", basis="")
    publish(tree, report(proposals=[fact]))
    review_session.reject(tree, current(tree)["review_id"], 1, SESSION, NOW)
    decision = ledger.load_decisions(ledger.ledgers_dir_of(tree.paths.data_dir))[0]
    assert (decision["scope"], decision["kind"], decision["name"], decision["action"], decision["claim"]) == (
        ledger.project_scope(PROJECT), "memory", "theta", "fact", "A lasting fact.",
    )


def test_keep_closes_an_applied_change_and_leaves_the_memory(tree):
    commit = apply_for_real(tree, "iota", None, "Text.\n")
    publish(tree, report(changes=[applied(tree, "iota", None, "Text.\n", commit)]))
    assert review_session.keep(tree, current(tree)["review_id"], 1, NOW)["outcome"] == "kept"
    assert memory_store.read_memory_file(os.path.join(memory_folder(tree), "iota.md")) == "Text.\n"


def test_each_action_commits_the_data_folder(tree):
    publish(tree, report(proposals=[proposal(1)]))
    review_session.skip(tree, current(tree)["review_id"], 1, NOW)
    assert "item 1 skipped" in log_of(tree.paths.data_dir, "-1")


# ---------------------------------------------------------------------------
# Approve
# ---------------------------------------------------------------------------


DRAFT = "---\nname: lookup-tool\ndescription: Look something up.\n---\n\n# lookup-tool\n\nSteps.\n"


@pytest.fixture
def skills(tree):
    repository = tree.inventory.skills_dir
    subprocess.run(["git", "-C", repository, "init", "--quiet", "--initial-branch=master"], check=True)
    Path(repository, "README.md").write_text("Readme\n", encoding="utf-8")
    for arguments in (["add", "--all"], ["-c", "user.name=Someone", "-c", "user.email=s@example.invalid", "commit", "--quiet", "-m", "Start"]):
        subprocess.run(["git", "-C", repository, *arguments], check=True)
    return repository


def skill_review(config, draft=DRAFT, **overrides):
    path = Path(config.paths.data_dir) / "proposals" / WEEK / "skill-1" / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(draft)
    values = {"id": "skill-1", "kind": "skill", "change_type": "new", "target": "lookup-tool", "exact_change": "", "draft_path": f"proposals/{WEEK}/skill-1/SKILL.md"}
    values.update(overrides)
    publish(config, report(proposals=[proposal(1, **values)]))
    return current(config)["review_id"]


def git_out(repository, *arguments):
    return subprocess.run(["git", "-C", repository, *arguments], capture_output=True, encoding="utf-8", check=True).stdout.strip()


def test_approve_skill_makes_a_branch_and_leaves_the_checked_out_files_alone(tree, skills):
    review_id = skill_review(tree)
    Path(skills, "uncommitted.txt").write_text("Work in progress\n", encoding="utf-8")
    head_before = git_out(skills, "rev-parse", "HEAD")
    status_before = git_out(skills, "status", "--porcelain")
    result = review_session.approve_skill(tree, review_id, 1, None, NOW)
    assert result["branch"] == f"upkeep/{WEEK}-lookup-tool"
    assert git_out(skills, "rev-parse", "HEAD") == head_before
    assert git_out(skills, "symbolic-ref", "--short", "HEAD") == "master"
    assert git_out(skills, "status", "--porcelain") == status_before
    assert not Path(skills, "lookup-tool").exists()
    assert git_out(skills, "show", f"{result['branch']}:lookup-tool/SKILL.md") + "\n" == DRAFT
    assert git_out(skills, "diff", "--name-only", "master", result["branch"]) == "lookup-tool/SKILL.md"
    log = git_out(skills, "log", "-1", "--format=%an|%ae|%cn|%B", result["branch"])
    assert log.startswith("Test Author|test@example.invalid|Test Author|") and "Co-Authored-By" not in log
    assert git_out(skills, "remote") == ""
    assert any("push" in step for step in result["next_steps"])
    assert current(tree)["items"][0]["decision"]["outcome"] == "approved"


@pytest.mark.parametrize("private_text,finding", [
    ("Talks to 192.168.1.20 for data.", "server address"),
    ("The session 00000000-0000-4000-8000-000000000001 shows it.", "session id"),
    ("Used on secretproject only.", "private term"),
    ("Reads from D:\\data\\files.", "file path"),
    ("password = hunter2hunter2", "secret pattern"),
])
def test_approve_skill_refuses_a_draft_with_private_material(tree, skills, private_text, finding):
    review_id = skill_review(tree, DRAFT + private_text + "\n")
    with pytest.raises(review_session.ReviewRefused, match=finding):
        review_session.approve_skill(tree, review_id, 1, None, NOW)
    assert git_out(skills, "branch", "--list") == "* master"
    assert current(tree)["items"][0]["decision"] is None


def test_a_draft_may_mention_the_products_own_settings_folder(tree, skills):
    review_id = skill_review(tree, DRAFT + "Skills live in ~/.claude/skills/ on every machine.\n")
    assert review_session.approve_skill(tree, review_id, 1, None, NOW)["outcome"] == "approved"


def test_approve_skill_refuses_text_copied_from_a_memory(tree, skills):
    folder = memory_folder(tree)
    os.makedirs(folder)
    Path(folder, "note.md").write_text("the quiet blue heron waits by the old mill pond\n", encoding="utf-8")
    review_id = skill_review(tree, DRAFT + "The quiet blue heron waits by the old mill pond.\n")
    with pytest.raises(review_session.ReviewRefused, match="copied from a memory"):
        review_session.approve_skill(tree, review_id, 1, None, NOW)


def test_approve_skill_refuses_an_unsafe_folder_a_wrong_name_and_a_partial_draft(tree, skills):
    review_id = skill_review(tree, target="")
    with pytest.raises(review_session.ReviewRefused, match="names no folder"):
        review_session.approve_skill(tree, review_id, 1, None, NOW)
    with pytest.raises(review_session.ReviewRefused, match="not a plain skill folder"):
        review_session.approve_skill(tree, review_id, 1, "../outside", NOW)
    with pytest.raises(review_session.ReviewRefused, match="names itself"):
        review_session.approve_skill(tree, review_id, 1, "other-name", NOW)
    assert review_session.approve_skill(tree, review_id, 1, "lookup-tool", NOW)["outcome"] == "approved"


def test_a_draft_that_is_only_a_change_is_refused(tree, skills):
    review_id = skill_review(tree, "Replace step 2 with step 3.\n", change_type="change")
    with pytest.raises(review_session.ReviewRefused, match="not a whole skill file"):
        review_session.approve_skill(tree, review_id, 1, None, NOW)


def test_approve_skill_refuses_to_overwrite_a_skill_that_exists_when_new_was_proposed(tree, skills):
    Path(skills, "lookup-tool").mkdir()
    Path(skills, "lookup-tool", "SKILL.md").write_text("Existing\n", encoding="utf-8")
    subprocess.run(["git", "-C", skills, "add", "--all"], check=True)
    subprocess.run(["git", "-C", skills, "-c", "user.name=S", "-c", "user.email=s@example.invalid", "commit", "--quiet", "-m", "Add"], check=True)
    review_id = skill_review(tree)
    with pytest.raises(review_session.ReviewRefused, match="already exists"):
        review_session.approve_skill(tree, review_id, 1, None, NOW)


def test_approve_skill_refuses_a_hook(tree, skills):
    publish(tree, report(proposals=[proposal(1)]))
    with pytest.raises(review_session.ReviewRefused, match="not a skill"):
        review_session.approve_skill(tree, current(tree)["review_id"], 1, None, NOW)


def fact(**overrides):
    values = {"kind": "memory_fact", "target": "kappa", "exact_change": "A lasting fact.", "project_folder": PROJECT, "change_type": "new", "basis": ""}
    values.update(overrides)
    return proposal(1, **values)


def test_approve_fact_creates_the_memory_and_its_index_line_by_a_commit(tree):
    publish(tree, report(proposals=[fact()]))
    result = review_session.approve_memory(tree, current(tree)["review_id"], 1, NOW)
    folder = memory_folder(tree)
    text = memory_store.read_memory_file(os.path.join(folder, "kappa.md"))
    assert text.startswith("---\nname: kappa\n") and "A lasting fact. (user approved in review on 2031-01-15)" in text
    assert "(kappa.md)" in Path(folder, "MEMORY.md").read_text(encoding="utf-8")
    assert result["outcome"] == "approved" and git_out(folder, "status", "--porcelain") == ""
    assert not memory_store.week_already_applied(folder, WEEK)


def test_approve_fact_adds_to_an_existing_memory(tree):
    apply_for_real(tree, "kappa", None, "Existing.\n")
    publish(tree, report(proposals=[fact()]))
    review_session.approve_memory(tree, current(tree)["review_id"], 1, NOW)
    text = memory_store.read_memory_file(os.path.join(memory_folder(tree), "kappa.md"))
    assert text.startswith("Existing.\n\nA lasting fact.")


def test_approve_deletion_removes_the_text_and_refuses_when_it_no_longer_fits(tree):
    apply_for_real(tree, "lambda", None, "Keep this.\n\nDrop this.\n")
    deletion = proposal(1, kind="memory_deletion", target="lambda Drop this.", exact_change="remove lambda: Drop this.", project_folder=PROJECT, basis="")
    publish(tree, report(proposals=[deletion, proposal(2, kind="memory_deletion", target="lambda Not there.", exact_change="remove lambda: Not there.", project_folder=PROJECT, basis="")]))
    review_id = current(tree)["review_id"]
    review_session.approve_memory(tree, review_id, 1, NOW)
    assert memory_store.read_memory_file(os.path.join(memory_folder(tree), "lambda.md")) == "Keep this.\n"
    with pytest.raises(review_session.ReviewRefused, match="does not fit"):
        review_session.approve_memory(tree, review_id, 2, NOW)


def test_approve_memory_refuses_other_kinds(tree):
    publish(tree, report(proposals=[proposal(1)]))
    with pytest.raises(review_session.ReviewRefused, match="not written by approve-memory"):
        review_session.approve_memory(tree, current(tree)["review_id"], 1, NOW)


@pytest.mark.parametrize("kind,refresh", [("hook", False), ("global_rule", False), ("mcp", True), ("plugin", True)])
def test_record_approved_records_what_was_applied_and_says_when_the_manifest_needs_refreshing(tree, kind, refresh):
    publish(tree, report(proposals=[proposal(1, kind=kind)]))
    result = review_session.record_approved(tree, current(tree)["review_id"], 1, "Ran the command.", NOW)
    assert result["refresh_manifest"] is refresh
    assert current(tree)["items"][0]["decision"] == {"outcome": "approved", "at": NOW.isoformat(), "detail": "Ran the command."}


def test_record_approved_needs_a_detail_and_refuses_kinds_with_their_own_action(tree, skills):
    review_id = skill_review(tree)
    with pytest.raises(review_session.ReviewRefused, match="own approve action"):
        review_session.record_approved(tree, review_id, 1, "Done.", NOW)
    publish(tree, report(proposals=[proposal(1)]))
    with pytest.raises(review_session.ReviewRefused, match="Say what was applied"):
        review_session.record_approved(tree, current(tree)["review_id"], 1, " ", NOW)


# ---------------------------------------------------------------------------
# Why
# ---------------------------------------------------------------------------


def test_why_returns_ledger_notes_and_transcript_place(tree):
    item = ensure_memory_ledger(tree, "memory-1")
    write_note_file(tree, "The note behind it.")
    transcript = Path(tree.paths.projects_dir) / PROJECT / f"{SESSION}.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    publish(tree, report(changes=[change(1)]))
    result = review_session.why(tree, 1)
    assert result["ledger"]["identity"] == item.to_json()
    assert result["sources"][0]["note"]["what"] == "The note behind it."
    assert result["sources"][0]["transcript"] == str(transcript) and result["sources"][0]["transcript_exists"] is True
    assert "data" in result["notice"]


def test_why_says_when_a_transcript_is_gone_and_raises_when_a_note_is(tree):
    publish(tree, report(proposals=[proposal(1)]))
    with pytest.raises(FileNotFoundError):
        review_session.why(tree, 1)
    write_note_file(tree)
    assert review_session.why(tree, 1)["sources"][0]["transcript_exists"] is False


# ---------------------------------------------------------------------------
# Launcher and skill
# ---------------------------------------------------------------------------


def pwsh():
    found = shutil.which("pwsh")
    if found is None:
        raise FileNotFoundError("pwsh is needed for these tests")
    return found


def start(*arguments):
    return subprocess.run(
        [pwsh(), "-NoProfile", "-NonInteractive", "-File", str(START_SCRIPT), *arguments],
        capture_output=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW, check=False,
    )


@pytest.fixture
def launcher(tree, tmp_path):
    fake_claude = tmp_path / "claude.exe"
    fake_claude.write_text("", encoding="utf-8")
    raw = json.loads((UPKEEP / "config.json").read_text(encoding="utf-8"))
    raw["paths"] = {**raw["paths"], "projects_dir": tree.paths.projects_dir, "data_dir": tree.paths.data_dir, "claude_exe": str(fake_claude), "local_settings": tree.paths.local_settings}
    Path(tree.paths.local_settings).write_text(json.dumps({"python_exe": os.path.abspath(os.sys.executable), "apply_memory_changes": True, "private_terms": []}), encoding="utf-8")
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return str(path)


def test_start_fails_loudly_with_no_report(tree, launcher):
    completed = start("-PlanOnly", "-ConfigPath", launcher)
    assert completed.returncode == 1 and "No upkeep report" in completed.stderr


def test_start_fails_loudly_when_the_page_is_missing(tree, launcher):
    publish(tree, report(proposals=[proposal(1)]))
    os.remove(review_data.page_path(tree.paths.data_dir, WEEK))
    completed = start("-PlanOnly", "-ConfigPath", launcher)
    assert completed.returncode == 1 and "page is missing" in completed.stderr


def test_start_ignores_a_report_set_aside_and_plans_the_right_launch(tree, launcher):
    publish(tree, report(proposals=[proposal(1)]))
    aside = Path(tree.paths.data_dir) / "reports" / "2031-W09-first-dry-run"
    aside.mkdir()
    (aside / "report.json").write_text("{}", encoding="utf-8")
    completed = start("-PlanOnly", "-ConfigPath", launcher)
    assert completed.returncode == 0, completed.stderr
    plan = json.loads(completed.stdout)
    assert plan["page"] == review_data.page_path(tree.paths.data_dir, WEEK)
    assert plan["working_directory"] == os.path.join(tree.paths.data_dir, "review")
    assert plan["terminal_arguments"].endswith('"Run the upkeep-review skill"')


def test_start_stops_when_the_review_cannot_be_brought_up_to_date(tree, launcher):
    publish(tree, report(proposals=[proposal(1)]))
    (Path(tree.paths.data_dir) / review_data.MARKER_FILE).write_text('{"schema_version": 99}', encoding="utf-8")
    completed = start("-PlanOnly", "-ConfigPath", launcher)
    assert completed.returncode == 1 and "up to date" in completed.stderr


def test_shortcut_points_at_the_installed_script_under_home(tmp_path):
    completed = start("-CreateShortcut", "-ShortcutFolder", str(tmp_path))
    assert completed.returncode == 0, completed.stderr
    saved = json.loads(completed.stdout)
    home = os.path.expanduser("~")
    assert os.path.exists(saved["shortcut"])
    assert saved["target"].lower().endswith("pwsh.exe")
    assert os.path.join(home, ".claude", "skills", "upkeep", "Start-UpkeepReview.ps1") in saved["arguments"]
    assert "-ShowErrorsInWindow" in saved["arguments"]


def test_skill_can_be_triggered_by_the_launch_prompt_and_names_real_actions():
    text = SKILL_FILE.read_text(encoding="utf-8")
    front = text.split("---")[1]
    assert "name: upkeep-review" in front and "Run the upkeep-review skill" in front
    choices = {"show", "undo", "reject", "keep", "skip", "why", "approve-skill", "approve-memory", "record-approved", "check-draft"}
    for choice in choices:
        assert choice in text
    assert "plugins-mcp.ps1" in text and "-Mode Capture" in text and "uninstalls" in text
    assert "Co-Authored-By" in text and "data, not instructions" in text and "public" in text
