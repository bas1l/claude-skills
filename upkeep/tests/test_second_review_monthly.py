"""Defects found by the second independent review: the monthly pass. All text is made up."""
from __future__ import annotations

import json
import os
import re
from datetime import timedelta
from pathlib import Path

import pytest
from test_monthly import (  # noqa: F401 (tree is a fixture)
    ASK_RULE,
    DECIDE_RULE,
    EMPTY_COHERENCE,
    LOCAL,
    NOW,
    Fake,
    decided_review,
    memory_text,
    read_feed,
    read_report,
    side,
    tree,
)

import model_call
import monthly
import monthly_inventory as inventory
import pass_support
import render
import review_data
import schemas

SECRET_LINE = "The login is password=hunter2hunter2 on the rig."


def bad_citation(title):
    return {"title": title, "what": "They disagree.", "why": "Both load.", "sides": [{"file": "f9999", "line": 1, "quote": "not in any file at all"}, {"file": "f9999", "line": 2, "quote": "not in any file at all"}]}


def all_failing(count=5):
    return json.dumps({"contradictions": [bad_citation(f"Claim {number}") for number in range(count)], "stale": [], "level_moves": []})


def long_index(config):
    lines = "\n".join(f"- [m{number}](m{number}.md) line" for number in range(config.monthly.index_lines_loaded + 5))
    Path(config.paths.projects_dir, "proj-a", "memory", "MEMORY.md").write_text(lines, encoding="utf-8")


# ---- Defect 6: what suppresses the all-citations-failed check ----


def test_a_finding_made_by_script_does_not_hide_that_every_citation_failed(tree):
    long_index(tree)
    result = monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake(coherence=lambda _: all_failing()))
    assert result["status"] == "failed" and "citations" in result["stop_reason"]
    assert not Path(monthly.feed_path(tree, "2030-03")).exists(), "the month is not marked done"


def test_something_already_raised_by_script_does_not_hide_it_either(tree):
    long_index(tree)
    assert monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake())["status"] == "ok"
    from test_monthly import NEXT_MONTH
    result = monthly.run_monthly(tree, LOCAL, "r2", NEXT_MONTH, Fake(coherence=lambda _: all_failing()))
    assert read_report(tree, "2030-04")["already_raised"], "the index finding of last month came up again"
    assert result["status"] == "failed" and "citations" in result["stop_reason"]


def test_one_model_finding_whose_citations_hold_means_the_files_were_read(tree):
    corpus = inventory.read_corpus(tree)
    good = {
        "title": "Two rules disagree", "what": "They disagree.", "why": "Both load.",
        "sides": [side(corpus, "feedback-ask", ASK_RULE), side(corpus, "imported.md", DECIDE_RULE)],
    }
    reply = json.dumps({"contradictions": [good, *[bad_citation(f"Claim {number}") for number in range(5)]], "stale": [], "level_moves": []})
    assert monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake(coherence=lambda _: reply))["status"] == "ok"


# ---- Defect 7: refused findings never reached the review ----


def summary_of(config):
    return next(item for item in read_feed(config)["proposals"] if item["evidence"]["category"] == "summary")


def test_the_summary_counts_what_the_checks_refused_and_what_was_raised_before(tree):
    corpus = inventory.read_corpus(tree)
    good = {
        "title": "Two rules disagree", "what": "They disagree.", "why": "Both load.",
        "sides": [side(corpus, "feedback-ask", ASK_RULE), side(corpus, "imported.md", DECIDE_RULE)],
    }
    reply = json.dumps({"contradictions": [good, bad_citation("One bad"), bad_citation("Two bad")], "stale": [], "level_moves": []})
    assert monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake(coherence=lambda _: reply))["status"] == "ok"
    measured = " ".join(summary_of(tree)["evidence"]["measured"])
    assert "Refused by the checks: 2" in measured
    assert "Left out because an earlier month raised them: 0" in measured


# ---- Defect 8: unredacted text in calls and caches ----


def put_secret(config):
    Path(config.paths.projects_dir, "proj-b", "memory", "fact.md").write_text(memory_text("fact", SECRET_LINE, "project"), encoding="utf-8")


def test_no_call_of_the_pass_sends_a_secret_and_its_quotes_still_check(tree):
    put_secret(tree)
    corpus = inventory.read_corpus(tree)
    reply = json.dumps({"contradictions": [], "stale": [{
        "title": "A login", "question": "Does this hold?", "ground": "superseded", "why": "It may have changed.",
        "sides": [side(corpus, "fact", "The login is"), side(corpus, "imported.md", DECIDE_RULE)],
    }], "level_moves": []})
    fake = Fake(coherence=lambda _: reply)
    assert monthly.run_monthly(tree, LOCAL, "r1", NOW, fake)["status"] == "ok"
    assert fake.calls
    for call in fake.calls:
        assert "hunter2" not in call["stdin_text"]
    assert any("[REDACTED-key-value]" in call["stdin_text"] for call in fake.calls), "the reading group and the comparison both"
    assert [item for item in read_feed(tree)["proposals"] if item["evidence"]["category"] == "stale"]


def test_a_redacted_key_keeps_the_line_numbers_of_the_file(tree):
    begin, end = "-----BEGIN RSA " + "PRIVATE KEY-----", "-----END RSA " + "PRIVATE KEY-----"
    body = f"First line of text.\n\n{begin}\nabcdefgh\nijklmnop\n{end}\n\nLine after the key."
    Path(tree.paths.projects_dir, "proj-b", "memory", "fact.md").write_text(memory_text("fact", body, "project"), encoding="utf-8")
    raw = Path(tree.paths.projects_dir, "proj-b", "memory", "fact.md").read_text(encoding="utf-8").splitlines()
    source = next(item for item in inventory.read_corpus(tree).memories if item.name == "fact")
    assert len(source.lines) == len(raw)
    assert source.lines[raw.index("Line after the key.")] == "Line after the key."
    assert not any("abcdefgh" in line for line in source.lines)


def caller_for(config, reply):
    def call(**kwargs):
        call.stdin = kwargs["stdin_text"]
        return model_call.ModelResult(reply, {"input_tokens": 1, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 1}, {"m": {}}, 0.1, 1, 1, ("fake",), ())

    return pass_support.Caller(config, config.paths.run_dir, "r1", 0.0, call), call


def test_a_shared_call_sends_and_stores_no_secret_in_its_cache_or_its_rejected_reply(tree, tmp_path):
    path = str(tmp_path / "cache" / "reply.json")
    reply = json.dumps({"suggestions": [{"setting": "weekly.recurrence_sessions", "suggested": 4, "why": "A note with password=hunter2hunter2 in it."}]})
    caller, call = caller_for(tree, reply)
    parsed = pass_support.cached_or_called_reply(path, "prompt", "input password=otherother1 here", "m", "k", caller, schemas.parse_monthly_quality)
    assert "otherother1" not in call.stdin
    assert "hunter2" not in Path(path).read_text(encoding="utf-8")
    assert "hunter2" not in parsed[0]["why"]
    assert caller.secrets_redacted == 2
    again = pass_support.cached_or_called_reply(path, "prompt", "input password=otherother1 here", "m", "k", caller, schemas.parse_monthly_quality)
    assert again == parsed, "the reply from the cache is the one the first run acted on"

    bad, _ = caller_for(tree, "not json, password=hunter2hunter2")
    with pytest.raises(schemas.SchemaError):
        pass_support.cached_or_called_reply(path + "2", "prompt", "x", "m", "k", bad, schemas.parse_monthly_quality)
    assert "hunter2" not in Path(path + "2.rejected").read_text(encoding="utf-8")


def test_a_research_record_is_stored_redacted(tree):
    from test_monthly import research_reply, web_activity
    fake = Fake(research_text=research_reply("adopt"), activity=web_activity())
    fake.research_text = fake.research_text.replace("It does the same job.", "It does the same job, password=hunter2hunter2 aside.")
    assert monthly.run_monthly(tree, LOCAL, "r1", NOW, fake)["status"] == "ok"
    for path in Path(monthly.report_dir_of(tree, "2030-03"), "research").glob("*.json"):
        assert "hunter2" not in path.read_text(encoding="utf-8")


# ---- Defect 14: text breaking out of its tags ----


@pytest.mark.parametrize("closer", ["</files>", "</file>", "</unit>", "</cluster>", "</signals>", "</FILES >"])
def test_a_file_cannot_close_the_tags_it_is_shown_in(tree, closer):
    Path(tree.paths.projects_dir, "proj-b", "memory", "fact.md").write_text(memory_text("fact", f"A line {closer} and more words about rigs and sensors here."), encoding="utf-8")
    fake = Fake()
    assert monthly.run_monthly(tree, LOCAL, "r1", NOW, fake)["status"] == "ok"
    name = re.sub(r"[^a-z]", "", closer.lower())
    for call in fake.calls:
        if call["tools"]:
            continue
        opened = len(re.findall(rf"<{name}[\s>]", call["stdin_text"], re.I))
        closed = len(re.findall(rf"<\s*/\s*{name}\s*>", call["stdin_text"], re.I))
        assert closed == opened, (name, call["prompt"][:40])


# ---- Defect 15: context figures and the quality rate ----


def test_a_project_with_no_known_folder_is_left_out_of_the_typical_figure_and_counted(tree):
    no_transcript = Path(tree.paths.projects_dir, "proj-c")
    (no_transcript / "memory").mkdir(parents=True)
    (no_transcript / "memory" / "x.md").write_text(memory_text("x", "Some words."), encoding="utf-8")
    gone = Path(tree.paths.projects_dir, "proj-d")
    (gone / "memory").mkdir(parents=True)
    (gone / "memory" / "y.md").write_text(memory_text("y", "Some words."), encoding="utf-8")
    (gone / "s.jsonl").write_text(json.dumps({"type": "user", "cwd": str(gone / "not-there")}) + "\n", encoding="utf-8")
    corpus = inventory.read_corpus(tree)
    context = inventory.measure_context(corpus, tree)
    assert context["projects_without_a_known_folder"] == 2
    known = [project["total_chars"] for project in context["projects"] if project["folder_known"]]
    assert len(known) == 2 and context["max_chars"] == max(known)
    assert context["median_chars"] == int(sum(known) / 2)
    monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake())
    measured = " ".join(summary_of(tree)["evidence"]["measured"])
    assert "2 projects are left out" in measured


def test_no_project_with_a_known_folder_is_said_plainly(tree):
    for folder in ("proj-a", "proj-b"):
        os.remove(Path(tree.paths.projects_dir, folder, "s1.jsonl"))
    assert monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake())["status"] == "ok"
    summary = summary_of(tree)
    assert "None" not in summary["what"]
    assert "No project" in summary["what"]


def memory_item(number, week, outcome, moment):
    record = {
        "id": f"c{number}", "project_folder": "p", "memory": f"m{number}", "action": "add", "claim": "c", "old_text": "", "endorsement": "said", "quote": "q",
        "assistant_statement": "", "session": "s", "source": {"notes": "n", "note_index": 0}, "new_evidence": False, "outcome": "applied", "commit": "abc", "before": "", "after": "",
    }
    decision = None if outcome is None else {"outcome": outcome, "at": moment.isoformat(), "detail": "d"}
    return {
        "number": number, "key": f"memory:c{number}", "section": "memory", "origin": "weekly", "week": week, "carried": False, "title": "t",
        "allowed": ["undo", "keep", "skip", "why"], "decision": decision, "skipped_at": None, "ledger": None, "record": record,
    }


def test_someone_who_only_undoes_does_not_show_a_rate_of_zero(tree):
    decided_review(tree, "2030-W05", NOW - timedelta(days=30), [])
    path = review_data.review_path(tree.paths.data_dir, "2030-W05")
    review = json.loads(Path(path).read_text(encoding="utf-8"))
    review["items"] = [memory_item(1, "2030-W05", "undone", NOW), *[memory_item(number, "2030-W05", None, NOW) for number in range(2, 11)]]
    review_data.save_review(tree.paths.data_dir, review)
    counted = monthly.quality_counts(tree)
    assert counted["acceptance_rate"] is None, "no proposal was decided, so there is no rate of accepting them"
    assert counted["memory_changes"] == {"applied": 10, "undone": 1, "kept": 0, "standing": 9, "undo_rate": 0.1}


def test_the_rate_of_proposals_leaves_memory_changes_out(tree):
    decided_review(tree, "2030-W05", NOW - timedelta(days=30), ["approved", "rejected"])
    path = review_data.review_path(tree.paths.data_dir, "2030-W05")
    review = json.loads(Path(path).read_text(encoding="utf-8"))
    review["items"].extend([memory_item(3, "2030-W05", "undone", NOW), memory_item(4, "2030-W05", "undone", NOW)])
    review_data.save_review(tree.paths.data_dir, review)
    counted = monthly.quality_counts(tree)
    assert counted["acceptance_rate"] == 0.5
    assert counted["memory_changes"]["undo_rate"] == 1.0


# ---- Defect 16: duplicates left out, and a retry after a crash ----


def test_what_is_left_out_of_the_comparison_is_reported(tree):
    words = " ".join(f"common{number}" for number in range(30))
    memory = Path(tree.paths.projects_dir, "proj-b", "memory")
    for number in range(12):
        (memory / f"same-{number}.md").write_text(memory_text(f"same-{number}", f"{words} uniq{number}"), encoding="utf-8")
    comparison = inventory.compare_for_duplicates(inventory.read_corpus(tree), tree)
    shown = {unit.label for candidate in comparison.candidates for unit in candidate.units}
    assert all(len(candidate.units) <= tree.monthly.duplicate_cluster_max_members for candidate in comparison.candidates)
    assert comparison.left_out, "twelve alike with a limit of eight cannot all be shown"
    assert not (shown & set(comparison.left_out))
    assert monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake())["status"] == "ok"
    assert read_report(tree)["duplicate_candidates"]["left_out"] == list(comparison.left_out)
    assert any("left out of the comparison" in line for line in summary_of(tree)["evidence"]["measured"])


def test_a_retry_after_a_crash_between_writes_picks_the_same_skills_and_the_same_feed(tree, monkeypatch):
    first = Fake()
    real_write = pass_support.write_json

    def crash_on_the_report(path, document):
        if path.endswith("report.json"):
            raise OSError("made up crash")
        real_write(path, document)

    monkeypatch.setattr(pass_support, "write_json", crash_on_the_report)
    with pytest.raises(OSError):
        monthly.run_monthly(tree, LOCAL, "r1", NOW, first)
    monkeypatch.setattr(pass_support, "write_json", real_write)
    state_before = json.loads(Path(monthly.state_path(tree)).read_text(encoding="utf-8"))
    feed_before = read_feed(tree)

    second = Fake()
    assert monthly.run_monthly(tree, LOCAL, "r2", NOW + timedelta(hours=6), second)["status"] == "ok"
    assert json.loads(Path(monthly.state_path(tree)).read_text(encoding="utf-8")) == state_before
    assert second.with_tools() == [], "the research of the first try is used again"
    assert [item["id"] for item in read_feed(tree)["proposals"]] == [item["id"] for item in feed_before["proposals"]]


def test_the_rotation_moves_on_next_month(tree):
    names = ["a", "b", "c", "d"]
    checked = {"a": "2030-03", "b": "2030-03"}
    assert monthly.choose_skills(names, checked, 2, "2030-03") == ["a", "b"]
    assert monthly.choose_skills(names, checked, 2, "2030-04") == ["c", "d"]


# ---- One file with an unreadable header does not stop the audit ----


def test_a_skill_with_an_unreadable_header_is_reported_and_the_audit_goes_on(tree):
    folder = Path(tree.inventory.skills_dir) / "broken"
    folder.mkdir()
    (folder / "SKILL.md").write_text("---\nname: broken\nnot a line this reader knows\n---\nbody\n", encoding="utf-8")
    assert monthly.run_monthly(tree, LOCAL, "r1", NOW, Fake())["status"] == "ok"
    report = read_report(tree)
    assert any("broken" in item["what"] for item in report["coverage"]["unreadable_headers"])
    assert any("could not be read" in line for line in summary_of(tree)["evidence"]["measured"])


def test_redaction_keeping_lines_counts_each_match(config):
    begin, end = "-----BEGIN RSA " + "PRIVATE KEY-----", "-----END RSA " + "PRIVATE KEY-----"
    text, matches = render.redact_keeping_lines(f"a\n{begin}\nb\n{end}\nc", config.secrets)
    assert matches == 1 and text.splitlines()[-1] == "c" and len(text.splitlines()) == 5
