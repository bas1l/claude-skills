"""The monthly pass on a synthetic setup, with a fake model. No real transcript or memory text."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import synthetic_inventory

import memory_store
import model_call
import monthly
import monthly_inventory as inventory
import research
import review_data
import review_page
import schemas
from config import LocalSettings, load_config

REAL_CONFIG = Path(__file__).resolve().parent.parent / "config.json"
NOW = datetime(2030, 3, 2, 3, 0, tzinfo=timezone.utc)
NEXT_MONTH = datetime(2030, 4, 6, 3, 0, tzinfo=timezone.utc)
LOCAL = LocalSettings("python", False, ("secretproject",))
USAGE = {"input_tokens": 10, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 5}
ASK_RULE = "Always ask one question before you start any change."
DECIDE_RULE = "Never ask questions while working, decide and report instead."
SAME_RULE = "Run the whole test folder before calling any fix finished, because partial runs have hidden regressions in shared helpers."
GENERIC = "A tool that formats tables of numbers for a report."
EMPTY_COHERENCE = '{"contradictions": [], "stale": [], "level_moves": []}'


def memory_text(name: str, body: str, kind: str = "feedback") -> str:
    return f"---\nname: {name}\ndescription: {name}\nmetadata:\n  type: {kind}\n---\n\n{body}\n"


@pytest.fixture
def tree(tmp_path):
    projects = tmp_path / "projects"
    data = tmp_path / "upkeep"
    (data / "run").mkdir(parents=True)
    raw = json.loads(REAL_CONFIG.read_text(encoding="utf-8"))
    raw["paths"] = {
        "projects_dir": str(projects), "data_dir": str(data), "run_dir": str(data / "run"),
        "claude_exe": "not-used", "local_settings": str(data / "local.json"),
    }
    raw["memory"] = {"author_name": "Test Author", "author_email": "test@example.invalid"}
    raw["inventory"] = synthetic_inventory(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    (home / "imported.md").write_text(f"# Style\n\n{DECIDE_RULE}\n", encoding="utf-8")
    (home / "CLAUDE.md").write_text("@imported.md\n", encoding="utf-8")
    raw["monthly"]["global_claude_file"] = str(home / "CLAUDE.md")
    raw["monthly"]["global_rules_dir"] = str(home / "rules")
    raw["monthly"]["replacement_skills_per_month"] = 2

    for folder, cwd_name, files in (
        ("proj-a", "work-a", {"feedback-ask.md": memory_text("feedback-ask", ASK_RULE), "feedback-tests.md": memory_text("feedback-tests", SAME_RULE)}),
        ("proj-b", "work-b", {"feedback-full-tests.md": memory_text("feedback-full-tests", SAME_RULE), "fact.md": memory_text("fact", "The sensor sits on the left arm of the rig.", "project")}),
    ):
        cwd = tmp_path / cwd_name
        cwd.mkdir()
        memory = projects / folder / "memory"
        memory.mkdir(parents=True)
        for name, text in files.items():
            (memory / name).write_text(text, encoding="utf-8")
        (memory / "MEMORY.md").write_text("- [one](one.md) one line\n", encoding="utf-8")
        (projects / folder / "s1.jsonl").write_text(json.dumps({"type": "user", "cwd": str(cwd)}) + "\n", encoding="utf-8")
    (tmp_path / "work-a" / "CLAUDE.md").write_text("# Project\n\nUse the ruler helpers for every measurement of the rig.\n", encoding="utf-8")
    (projects / "proj-empty" / "memory").mkdir(parents=True)

    skills = Path(raw["inventory"]["skills_dir"])
    for name in ("alpha", "beta", "gamma"):
        (skills / name).mkdir()
        (skills / name / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Does the {name} job.\n---\n\nSteps of {name}.\n", encoding="utf-8")

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    config = load_config(str(config_path))
    memory_store.init_upkeep_repo(str(data), config.memory)
    return config


def side(corpus, name, quote_text):
    source = next(item for item in corpus.all_files() if item.name == name)
    number = next(index for index, line in enumerate(source.lines, 1) if quote_text in line)
    return {"file": source.ref, "line": number, "quote": quote_text}


def result_of(text, activity=()):
    return model_call.ModelResult(text, USAGE, {"m": {}}, 0.5, 1, 1, ("fake",), tuple(activity))


def web_activity(url="https://example.org/tool"):
    return [
        model_call.ToolActivity("WebSearch", {"query": "table format tool"}, f"found {url}", False),
        model_call.ToolActivity("WebFetch", {"url": url}, "page text", False),
    ]


def research_reply(recommendation="adopt", url="https://example.org/tool"):
    return json.dumps({
        "search_worked": True, "official_features": "none", "existing_tools": [{"name": "Tabler", "url": url, "maintenance_evidence": "released this year", "can_execute": "nothing"}],
        "conventions": "scripts", "sources": [{"url": url, "title": "Tabler", "used_for": "what it does"}],
        "recommendation": recommendation, "recommendation_reason": "It does the same job.",
    })


class Fake:
    """Answers by which prompt it was given, and records each call."""

    def __init__(self, coherence=None, duplicates=None, research_text=None, activity=None, descriptions=None, quality=None):
        self.calls = []
        self.coherence = coherence
        self.duplicates = duplicates
        self.research_text = research_text if research_text is not None else research_reply("build")
        self.activity = web_activity() if activity is None else activity
        self.descriptions = descriptions
        self.quality = quality
        self.answered = False

    def _coherence_reply(self, stdin_text):
        """The readings overlap, so a real reader would see these files more than once. The reply
        goes to the first reading holding every file cited; a made-up reference counts as held."""
        if self.coherence is None or self.answered:
            return EMPTY_COHERENCE
        text = self.coherence(stdin_text)
        document = json.loads(text)
        cited = {entry["file"] for entries in document.values() for item in entries for entry in item["sides"]}
        if any(f'<file ref="{ref}"' not in stdin_text and ref != "f9999" for ref in cited):
            return EMPTY_COHERENCE
        self.answered = True
        return text

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        prompt, stdin_text = kwargs["prompt"], kwargs["stdin_text"]
        if tuple(kwargs["tools"]) == model_call.RESEARCH_TOOLS:
            return result_of(self.research_text, self.activity)
        assert not kwargs["tools"]
        if "standing setup of an AI coding assistant for one person" in prompt:
            return result_of(self._coherence_reply(stdin_text))
        if "judging groups of texts" in prompt:
            return result_of(self.duplicates(stdin_text) if self.duplicates else _all_different(stdin_text))
        if "general description of the need" in prompt:
            chosen = [entry["skill"] for entry in json.loads(stdin_text)]
            return result_of(json.dumps({"descriptions": [{"skill": name, "description": self.descriptions or GENERIC} for name in chosen]}))
        if "scheduled job that maintains" in prompt:
            return result_of(self.quality)
        raise AssertionError(f"unexpected prompt: {prompt[:60]}")

    def with_tools(self):
        return [call for call in self.calls if call["tools"]]


def _clusters_in(stdin_text):
    return [part.split('"', 1)[0] for part in stdin_text.split('<cluster ref="')[1:]]


def _all_different(stdin_text):
    return json.dumps({"clusters": [
        {"cluster": ref, "verdict": "different", "reason": "They differ.", "title": "", "what": "", "why": "", "exact_change": "", "sides": []}
        for ref in _clusters_in(stdin_text)
    ]})


def read_report(config, month="2030-03"):
    return json.loads(Path(monthly.report_dir_of(config, month), "report.json").read_text(encoding="utf-8"))


def read_feed(config, month="2030-03"):
    return json.loads(Path(monthly.feed_path(config, month)).read_text(encoding="utf-8"))


def contradiction_reply(config):
    corpus = inventory.read_corpus(config)
    return json.dumps({"contradictions": [{
        "title": "Asking or deciding", "what": "One says ask first, one says never ask.", "why": "A change request brings them together.",
        "sides": [side(corpus, "feedback-ask", ASK_RULE), side(corpus, "imported.md", DECIDE_RULE)],
    }], "stale": [], "level_moves": []})


def real_review_of(config, now):
    report = {
        "schema_version": 1, "week": review_data.iso_week_of(now), "run_id": "w", "generated_at": now.isoformat(), "status": "ok", "stop_reason": None,
        "apply_enabled": False, "coverage": {}, "memory_changes": [], "rejected": [], "proposals": [], "held": [], "failures_ranked": [], "before_after": [], "usage": {},
    }
    os.makedirs(os.path.join(review_data.reports_dir(config.paths.data_dir), report["week"]), exist_ok=True)
    with open(os.path.join(review_data.reports_dir(config.paths.data_dir), report["week"], "report.json"), "w", encoding="utf-8") as handle:
        json.dump(report, handle)
    return report


# Measuring what each session loads.

def test_context_follows_imports_and_names_what_it_cannot_measure(tree):
    corpus = inventory.read_corpus(tree)
    context = inventory.measure_context(corpus, tree)
    assert [os.path.basename(entry["path"]) for entry in context["global_files"]] == ["CLAUDE.md", "imported.md"]
    assert context["global_chars"] == sum(item.chars for item in corpus.global_files)
    assert context["skills_listed"] == 3
    project_a = next(project for project in context["projects"] if project["project_folder"] == "proj-a")
    expected_instructions = len("# Project\n\nUse the ruler helpers for every measurement of the rig.\n")
    assert project_a["instructions_chars"] == expected_instructions
    assert project_a["total_chars"] == context["global_chars"] + context["skill_listing_chars"] + expected_instructions + project_a["index_chars_loaded"]
    assert "plugin skills" in context["not_measured"]


def test_empty_memory_folders_are_not_projects(tree):
    assert "proj-empty" not in inventory.read_corpus(tree).chain_of_folder


def test_index_past_the_load_limit_is_a_finding(tree):
    index = Path(tree.paths.projects_dir, "proj-a", "memory", "MEMORY.md")
    index.write_text("".join(f"- line {number}\n" for number in range(205)), encoding="utf-8")
    monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake())
    found = [item for item in read_feed(tree)["proposals"] if item["evidence"]["category"] == "context"]
    assert len(found) == 1 and found[0]["evidence"]["sides"][0]["line"] == 201


def test_missing_global_instructions_stop_the_run(tree):
    os.remove(tree.monthly.global_claude_file)
    with pytest.raises(FileNotFoundError):
        monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake())


def test_setting_facts_say_when_attribution_is_not_set(tree):
    settings = inventory.read_corpus(tree).settings
    assert "The setting attribution is not set in settings.json." in settings.lines


# Contradictions: both sides, by file and line.

def test_contradiction_is_kept_with_both_sides_by_file_and_line(tree):
    result = monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake(coherence=lambda _: contradiction_reply(tree)))
    assert result["status"] == "ok"
    found = [item for item in read_feed(tree)["proposals"] if item["evidence"]["category"] == "contradiction"]
    assert len(found) == 1
    sides = found[0]["evidence"]["sides"]
    assert {os.path.basename(entry["file"]) for entry in sides} == {"feedback-ask.md", "imported.md"}
    assert all(entry["line"] >= 1 and entry["quote"] for entry in sides)


@pytest.mark.parametrize("tamper, reason", [
    (lambda sides: sides[:1], monthly.REJECT_FEW_SIDES),
    (lambda sides: [sides[0], {**sides[1], "quote": "Words nobody ever wrote down."}], monthly.REJECT_CITATION),
    (lambda sides: [sides[0], {**sides[1], "line": sides[1]["line"] + 1}], monthly.REJECT_CITATION),
    (lambda sides: [sides[0], {**sides[1], "file": "f9999"}], monthly.REJECT_CITATION),
])
def test_a_citation_that_does_not_hold_rejects_that_finding(tree, tamper, reason):
    def reply(_):
        document = json.loads(contradiction_reply(tree))
        document["contradictions"][0]["sides"] = tamper(document["contradictions"][0]["sides"])
        return json.dumps(document)

    assert monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake(coherence=reply))["status"] == "ok"
    assert not [item for item in read_feed(tree)["proposals"] if item["evidence"]["category"] == "contradiction"]
    assert reason in {item["reason"] for item in read_report(tree)["rejected"]}


def test_all_citations_failing_fails_the_pass_and_writes_no_results(tree):
    def reply(_):
        return json.dumps({"contradictions": [
            {"title": f"t{number}", "what": "w", "why": "y", "sides": [{"file": "f1", "line": 1, "quote": f"not there at all {number}"}]}
            for number in range(tree.weekly.quote_failure_batch_min)
        ], "stale": [], "level_moves": []})

    result = monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake(coherence=reply))
    assert result["status"] == "failed" and "CitationBatchError" in result["stop_reason"]
    assert not os.path.exists(monthly.feed_path(tree, "2030-03"))


def test_a_reply_shaped_wrongly_fails_the_pass(tree):
    result = monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake(coherence=lambda _: '{"contradictions": []}'))
    assert result["status"] == "failed" and "SchemaError" in result["stop_reason"]


def _side(path, line, quote):
    return {"file": path, "ref": "f1", "role": "memory", "project_folder": "p", "name": "n", "line": line, "quote": quote}


def test_findings_citing_one_line_become_one_item_and_keep_what_each_said():
    shared = _side("settings", 1, "The setting is not set in the file.")
    first = monthly.finding("coherence", "contradiction", "One", "First view.", "Why one.", "a", [shared, _side("rule-a", 3, "Never add the trailer line.")])
    second = monthly.finding("coherence", "contradiction", "Two", "Second view.", "Why two.", "a", [shared, _side("rule-b", 7, "All commits by one author."), _side("rule-c", 9, "No such line in commits.")])
    apart = monthly.finding("coherence", "contradiction", "Other", "Another matter.", "Why.", "z", [_side("x", 1, "Some other words here."), _side("y", 2, "And other words there.")])
    merged = monthly.merge_overlapping([first, second, apart])
    assert sorted(item["title"] for item in merged) == ["Other", "Two"]
    item = next(entry for entry in merged if entry["title"] == "Two")
    assert {side["file"] for side in item["evidence"]["sides"]} == {"settings", "rule-a", "rule-b", "rule-c"}
    assert any("First view." in line for line in item["evidence"]["measured"])


def test_a_chain_of_shared_lines_joins_and_other_kinds_stay_apart():
    one = monthly.finding("coherence", "contradiction", "A", "w", "y", "t", [_side("a", 1, "Quote text one."), _side("b", 1, "Quote text two.")])
    two = monthly.finding("coherence", "contradiction", "B", "w", "y", "t", [_side("c", 1, "Quote text three."), _side("d", 1, "Quote text four.")])
    link = monthly.finding("coherence", "contradiction", "C", "w", "y", "t", [_side("b", 1, "Quote text two."), _side("c", 1, "Quote text three.")])
    stale = monthly.finding("coherence", "stale", "S", "w?", "y", "t", [_side("a", 1, "Quote text one.")])
    merged = monthly.merge_overlapping([one, two, link, stale])
    assert len(merged) == 2
    assert {item["evidence"]["category"] for item in merged} == {"contradiction", "stale"}


def test_a_finding_within_an_earlier_one_is_the_same_finding():
    wide = monthly.finding("coherence", "contradiction", "W", "w", "y", "t", [_side("a", 1, "Words on the first side."), _side("b", 2, "Words on the second side.")])
    narrow = monthly.finding("coherence", "contradiction", "N", "w", "y", "t", [_side("a", 1, "Words on the first side.")])
    assert monthly.same_finding(narrow, wide, 0.6)
    assert not monthly.same_finding(wide, narrow, 0.6)


# Staleness: a question, and never for non-use.

def stale_entry(ground, side_value, question="Does this still hold?"):
    return {"contradictions": [], "stale": [{"title": "Maybe stale", "question": question, "ground": ground, "why": "Because.", "sides": [side_value]}], "level_moves": []}


def test_non_use_is_not_a_ground_for_staleness(tree):
    corpus = inventory.read_corpus(tree)
    reply = json.dumps(stale_entry("not_used_lately", side(corpus, "fact", "The sensor sits")))
    assert monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake(coherence=lambda _: reply))["status"] == "failed"


def test_staleness_must_be_a_question(tree):
    corpus = inventory.read_corpus(tree)
    with pytest.raises(schemas.SchemaError):
        schemas.parse_monthly_coherence(json.dumps(stale_entry("stated_limit", side(corpus, "fact", "The sensor sits"), "This is old.")))


def test_a_ground_a_script_can_check_is_checked(tree):
    corpus = inventory.read_corpus(tree)
    reply = json.dumps(stale_entry("path_gone", side(corpus, "fact", "The sensor sits")))
    monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake(coherence=lambda _: reply))
    assert monthly.REJECT_GROUND in {item["reason"] for item in read_report(tree)["rejected"]}


def test_a_gone_path_supports_a_stale_question(tree, tmp_path):
    gone = tmp_path / "no-such-folder" / "data.csv"
    memory = Path(tree.paths.projects_dir, "proj-b", "memory", "fact.md")
    memory.write_text(memory_text("fact", f"The data is in {gone} on this machine."), encoding="utf-8")
    corpus = inventory.read_corpus(tree)
    reply = json.dumps(stale_entry("path_gone", side(corpus, "fact", "The data is in")))
    monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake(coherence=lambda _: reply))
    found = [item for item in read_feed(tree)["proposals"] if item["evidence"]["category"] == "stale"]
    assert len(found) == 1 and found[0]["what"].endswith("?")


# Duplicates: the script compares, then a reader judges.

def test_same_text_in_two_folders_is_a_candidate_and_unrelated_text_is_not(tree):
    candidates = inventory.duplicate_candidates(inventory.read_corpus(tree), tree)
    names = [{unit.source.name for unit in candidate.units} for candidate in candidates]
    assert {"feedback-tests", "feedback-full-tests"} in names
    assert not any("fact" in group for group in names)


def test_same_memory_name_in_two_folders_is_a_candidate(tree):
    Path(tree.paths.projects_dir, "proj-a", "memory", "fact.md").write_text(memory_text("fact", "Completely other words about cooking lentils."), encoding="utf-8")
    candidates = inventory.duplicate_candidates(inventory.read_corpus(tree), tree)
    assert any(candidate.same_name for candidate in candidates)


def duplicate_reply(tree, verdict="same"):
    corpus = inventory.read_corpus(tree)

    def reply(stdin_text):
        entries = []
        for ref in _clusters_in(stdin_text):
            entries.append({
                "cluster": ref, "verdict": verdict, "reason": "One rule twice.", "title": "One rule in two folders", "what": "Make it one global rule.", "why": "Saves repeating it.", "exact_change": "",
                "sides": [side(corpus, "feedback-tests", "Run the whole test folder"), side(corpus, "feedback-full-tests", "Run the whole test folder")],
            } if verdict == "same" else {
                "cluster": ref, "verdict": verdict, "reason": "Only the subject is shared.", "title": "", "what": "", "why": "", "exact_change": "", "sides": [],
            })
        return json.dumps({"clusters": entries})

    return reply


def test_a_rule_in_two_projects_counts_only_after_a_reader_says_so(tree):
    monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake(duplicates=duplicate_reply(tree)))
    report = read_report(tree)
    assert report["counts"][monthly.QUESTION_LEVEL] == {"level": 1}
    assert len(report["duplicate_candidates"]["judged_same"]) == 1


def test_a_candidate_the_reader_calls_different_counts_for_nothing(tree):
    monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake(duplicates=duplicate_reply(tree, "different")))
    report = read_report(tree)
    assert report["counts"][monthly.QUESTION_LEVEL] == {}
    assert report["duplicate_candidates"]["candidates"] == len(report["duplicate_candidates"]["judged_different"]) >= 1


def test_a_cluster_left_unanswered_fails_the_pass(tree):
    result = monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake(duplicates=lambda _: '{"clusters": []}'))
    assert result["status"] == "failed" and "SchemaError" in result["stop_reason"]


# Upkeep quality.

def decided_review(config, week, moment, outcomes):
    items = [{
        "number": position, "key": f"k-{week}-{position}", "section": "proposal", "origin": "weekly", "week": week, "carried": False, "title": "t",
        "allowed": ["approve", "reject", "skip", "why"], "decision": {"outcome": outcome, "at": moment.isoformat(), "detail": "d"}, "skipped_at": None, "ledger": None,
        "record": {"id": f"i{position}", "kind": "hook", "change_type": "new", "title": "t", "what": "w", "why": "y", "target": "", "basis": "recurrence", "evidence": {}, "exact_change": "x", "draft_path": None, "research": None, "status": "open", "project_folder": ""},
    } for position, outcome in enumerate(outcomes, 1)]
    review = {
        "schema_version": 1, "review_id": "x", "week": week, "run_id": "w", "built_at": moment.isoformat(), "report_status": "ok", "stop_reason": None, "apply_enabled": True,
        "weeks_overdue": 0, "last_action_at": moment.isoformat(), "failures": [], "coverage": {}, "usage": {}, "items": items, "held": [], "rejected": [], "failures_ranked": [], "before_after": [],
    }
    os.makedirs(os.path.dirname(review_data.review_path(config.paths.data_dir, week)), exist_ok=True)
    review_data.save_review(config.paths.data_dir, review)


def weeks_of_decisions(config, count):
    for position in range(count):
        moment = NOW - timedelta(weeks=position + 1)
        decided_review(config, review_data.iso_week_of(moment), moment, ["approved", "rejected"])


def test_too_few_weeks_says_not_enough_data_and_asks_no_model(tree):
    weeks_of_decisions(tree, 3)
    fake = Fake(quality='{"suggestions": []}')
    monthly.run_monthly(tree, LOCAL, "r1", NOW, fake)
    quality = read_report(tree)["quality"]
    assert quality["status"] == "not_enough_data" and quality["weeks_with_decisions"] == 3
    assert "not enough data" in quality["statement"]
    assert not any("scheduled job that maintains" in call["prompt"] for call in fake.calls)
    summary = [item for item in read_feed(tree)["proposals"] if item["evidence"]["category"] == "summary"][0]
    assert any("not enough data" in line for line in summary["evidence"]["measured"])


def test_enough_weeks_gives_rates_and_threshold_proposals_only(tree):
    weeks_of_decisions(tree, 4)
    fake = Fake(quality=json.dumps({"suggestions": [
        {"setting": "weekly.recurrence_sessions", "suggested": 4, "why": "Half of the proposals on this ground were rejected."},
        {"setting": "paths.data_dir", "suggested": 1, "why": "Not a threshold."},
    ]}))
    before = Path(REAL_CONFIG).read_bytes()
    monthly.run_monthly(tree, LOCAL, "r1", NOW, fake)
    report = read_report(tree)
    assert report["quality"]["acceptance_rate"] == 0.5 and report["quality"]["by_basis"]["recurrence"] == {"approved": 4, "rejected": 4}
    found = [item for item in report["findings"] if item["evidence"]["category"] == "threshold"]
    assert [item["target"] for item in found] == ["weekly.recurrence_sessions"]
    assert monthly.REJECT_SETTING in {item["reason"] for item in report["rejected"]}
    assert Path(REAL_CONFIG).read_bytes() == before and tree.weekly.recurrence_sessions == 3


# Replacements: rotation, privacy, and search.

def test_rotation_keeps_to_the_budget_and_covers_every_skill_over_time(tree):
    names = ["a", "b", "c", "d", "e"]
    checked: dict[str, str] = {}
    months = ["2030-01", "2030-02", "2030-03"]
    seen = []
    for month in months:
        chosen = monthly.choose_skills(names, checked, 2, month)
        assert len(chosen) == 2
        seen.extend(chosen)
        checked.update(dict.fromkeys(chosen, month))
    assert set(seen) == set(names)
    assert monthly.choose_skills(names, checked, 2, "2030-04")[0] == "b"


def test_the_pass_researches_only_its_budget_and_remembers_what_it_checked(tree):
    fake = Fake()
    monthly.run_monthly(tree, LOCAL, "r1", NOW, fake)
    assert len(fake.with_tools()) == 2
    state = json.loads(Path(monthly.state_path(tree)).read_text(encoding="utf-8"))
    assert state["replacement_checked"] == {"alpha": "2030-03", "beta": "2030-03"}
    next_fake = Fake()
    monthly.run_monthly(tree, LOCAL, "r2", NEXT_MONTH, next_fake)
    assert read_report(tree, "2030-04")["replacements"]["checked"][0] == "gamma"


def test_a_replacement_becomes_a_finding_with_its_links(tree):
    monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake(research_text=research_reply("adopt")))
    found = [item for item in read_feed(tree)["proposals"] if item["evidence"]["category"] == "replacement"]
    assert [item["target"] for item in found] == ["alpha", "beta"]
    assert found[0]["research"]["sources"][0]["url"] == "https://example.org/tool"


def test_build_means_nothing_outside_replaces_it(tree):
    monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake(research_text=research_reply("build")))
    report = read_report(tree)
    assert report["counts"][monthly.QUESTION_REPLACEMENT] == {}
    assert [item["skill"] for item in report["replacements"]["kept"]] == ["alpha", "beta"]


def test_search_unavailable_fails_loudly_and_writes_no_results(tree):
    failing = [model_call.ToolActivity("WebSearch", {"query": "q"}, "error", True)]
    result = monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake(activity=failing))
    assert result["status"] == "failed" and "SearchUnavailableError" in result["stop_reason"]
    assert not os.path.exists(monthly.feed_path(tree, "2030-03"))
    assert not os.path.exists(monthly.state_path(tree))
    assert read_report(tree)["status"] == "failed"


def test_memory_text_reaches_only_calls_without_tools(tree):
    fake = Fake()
    monthly.run_monthly(tree, LOCAL, "r1", NOW, fake)
    assert any(ASK_RULE in call["stdin_text"] and not call["tools"] for call in fake.calls)
    for call in fake.with_tools():
        assert call["stdin_text"] == GENERIC
        assert ASK_RULE not in call["stdin_text"] + call["prompt"]
    for call in fake.calls:
        if "general description of the need" in call["prompt"]:
            assert ASK_RULE not in call["stdin_text"] and SAME_RULE not in call["stdin_text"]


@pytest.mark.parametrize("description", [
    "A tool for the secretproject team.",
    "Run the whole test folder before calling any fix finished, every time.",
    r"A tool that reads C:\Users\someone\notes for you.",
])
def test_private_material_in_a_description_stops_the_pass_before_any_search(tree, description):
    fake = Fake(descriptions=description)
    result = monthly.run_monthly(tree, LOCAL, "r1", NOW, fake)
    assert result["status"] == "failed" and "PrivateMaterialError" in result["stop_reason"]
    assert fake.with_tools() == []


def test_generic_folder_names_do_not_count_as_private(tree):
    corpus = inventory.read_corpus(tree)
    names = monthly._project_names(corpus, tree)
    assert "work-a" in names
    public = research.build_private_material(["skills"], [], 6)
    assert research.private_findings("A skill and some skills", public)  # why such names are left out


# Run handling.

def fingerprint(root):
    found = {}
    for directory, _, names in os.walk(root):
        for name in names:
            path = os.path.join(directory, name)
            found[path] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return found


def test_nothing_outside_the_data_folder_changes(tree, tmp_path):
    outside = [tree.paths.projects_dir, tree.inventory.skills_dir, str(Path(tree.inventory.settings_file).parent), str(Path(tree.monthly.global_claude_file).parent)]
    before = [fingerprint(path) for path in outside]
    monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake(coherence=lambda _: contradiction_reply(tree), duplicates=duplicate_reply(tree), research_text=research_reply("adopt")))
    assert [fingerprint(path) for path in outside] == before
    assert not os.path.exists(os.path.join(tree.paths.projects_dir, "proj-a", "memory", ".git"))


def test_a_second_run_in_the_month_does_nothing(tree):
    monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake())
    fake = Fake()
    result = monthly.run_monthly(tree, LOCAL, "r2", NOW + timedelta(days=3), fake)
    assert result["skipped"] is True and fake.calls == []


def test_a_retry_after_failure_reuses_replies(tree):
    first = Fake(activity=[model_call.ToolActivity("WebSearch", {"query": "q"}, "error", True)])
    assert monthly.run_monthly(tree, LOCAL, "r1", NOW, first)["status"] == "failed"
    second = Fake()
    assert monthly.run_monthly(tree, LOCAL, "r2", NOW, second)["status"] == "ok"
    assert not any(not call["tools"] for call in second.calls)
    assert len(second.with_tools()) == 2


def test_budget_stop_is_reported_and_writes_no_results(tree):
    def stopping(**_):
        raise model_call.BudgetExhaustedError("stopped at the dollar limit")

    result = monthly.run_monthly(tree, LOCAL, "r1", NOW, stopping)
    assert result["status"] == "budget_stopped" and result["budget_stopped"] is True
    assert not os.path.exists(monthly.feed_path(tree, "2030-03"))


def test_the_same_finding_is_not_raised_again_next_month(tree):
    reply = lambda _: contradiction_reply(tree)  # noqa: E731
    monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake(coherence=reply))
    monthly.run_monthly(tree, LOCAL, "r2", NEXT_MONTH, Fake(coherence=reply))
    report = read_report(tree, "2030-04")
    assert report["counts"][monthly.QUESTION_COHERENCE].get("contradiction") is None
    assert [item["subject"] for item in report["already_raised"]] == ["Asking or deciding"]


def test_changed_text_may_be_raised_again(tree):
    monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake(coherence=lambda _: contradiction_reply(tree)))
    memory = Path(tree.paths.projects_dir, "proj-a", "memory", "feedback-ask.md")
    new_rule = "Stop and wait for an answer whenever a choice has two sensible options."
    memory.write_text(memory_text("feedback-ask", new_rule), encoding="utf-8")

    def reply(_):
        corpus = inventory.read_corpus(tree)
        return json.dumps({"contradictions": [{"title": "Waiting or deciding", "what": "w", "why": "y", "sides": [side(corpus, "feedback-ask", new_rule), side(corpus, "imported.md", DECIDE_RULE)]}], "stale": [], "level_moves": []})

    monthly.run_monthly(tree, LOCAL, "r2", NEXT_MONTH, Fake(coherence=reply))
    assert read_report(tree, "2030-04")["counts"][monthly.QUESTION_COHERENCE].get("contradiction") == 1


# Joining the review.

def test_results_join_the_next_review_with_stable_numbers_and_render_escaped(tree):
    def reply(_):
        document = json.loads(contradiction_reply(tree))
        document["contradictions"][0]["what"] = "<script>alert(1)</script> says ask."
        return json.dumps(document)

    monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake(coherence=reply, research_text=research_reply("adopt")))
    report = real_review_of(tree, NOW)
    first = review_data.build_review(tree, report, NOW)
    review_data.save_review(tree.paths.data_dir, first)
    again = review_data.build_review(tree, report, NOW + timedelta(hours=1))
    assert [(item["number"], item["key"]) for item in first["items"]] == [(item["number"], item["key"]) for item in again["items"]]
    assert first["review_id"] == again["review_id"]
    monthly_items = [item for item in first["items"] if item["origin"] == "monthly"]
    assert len(monthly_items) == len(read_feed(tree)["proposals"]) >= 3
    assert all(schemas.ACTION_APPROVE in item["allowed"] for item in monthly_items)

    page = review_page.render_page(first)
    assert "<script>" not in page and "From the monthly check" in page
    assert "feedback-ask.md" in page and ASK_RULE in page and "example.org/tool" in page


def test_a_failed_run_adds_nothing_to_the_review(tree):
    monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake(activity=[model_call.ToolActivity("WebSearch", {"query": "q"}, "error", True)]))
    review = review_data.build_review(tree, real_review_of(tree, NOW), NOW)
    assert review["items"] == []


def test_a_rejected_finding_stays_out_of_the_next_months_review(tree):
    import review_session

    reply = lambda _: contradiction_reply(tree)  # noqa: E731
    monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake(coherence=reply))
    report = real_review_of(tree, NOW)
    review = review_data.build_review(tree, report, NOW)
    review_data.save_review(tree.paths.data_dir, review)
    number = next(item["number"] for item in review["items"] if item["record"]["evidence"]["category"] == "contradiction")
    review_session.reject(tree, review["review_id"], number, "session-1", NOW + timedelta(hours=1))
    monthly.run_monthly(tree, LOCAL, "r2", NEXT_MONTH, Fake(coherence=reply))
    later = review_data.build_review(tree, real_review_of(tree, NEXT_MONTH), NEXT_MONTH)
    assert not [item for item in later["items"] if item["record"]["evidence"].get("category") == "contradiction"]


def test_approving_a_finding_is_recorded_by_hand(tree):
    import review_session

    monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake())
    review = review_data.build_review(tree, real_review_of(tree, NOW), NOW)
    review_data.save_review(tree.paths.data_dir, review)
    result = review_session.record_approved(tree, review["review_id"], 1, "Read it.", NOW)
    assert result["outcome"] == "approved"
