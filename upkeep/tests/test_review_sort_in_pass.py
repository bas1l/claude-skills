"""The sort as a step of the weekly pass, with a fake model. All text is made up."""
from __future__ import annotations

import dataclasses
import json
import os

from test_weekly import (  # noqa: F401 (tree is a fixture)
    DRY,
    FakeCall,
    NOW,
    change,
    memory_reply,
    note,
    read_notes,
    report_of,
    run,
    tree,
)

import model_call
import review_data
import schemas


class SortingCall(FakeCall):
    """The weekly fake, which also answers the sort, or fails it."""

    def __init__(self, sort_error=None, **kwargs):
        super().__init__(**kwargs)
        self.sort_error = sort_error
        self.sort_calls = 0

    def __call__(self, **kwargs):
        if not kwargs["prompt"].startswith("You are sorting"):
            return super().__call__(**kwargs)
        self.sort_calls += 1
        if self.sort_error is not None:
            raise self.sort_error
        lines = kwargs["stdin_text"].split("<items>")[1].split("</items>")[0].strip().splitlines()
        ratings = [
            {"id": json.loads(line)["id"], "importance": "important", "clarity": "clear", "reason": "It lasts.", "recommended": json.loads(line)["allowed"][0], "options": []}
            for line in lines
        ]
        return model_call.ModelResult(
            text=json.dumps({"ratings": ratings}), usage={"input_tokens": 10, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 5},
            model_usage={"m": {}}, cost_usd=0.1, duration_ms=100, num_turns=1, command_line=("claude",),
        )


def sort_file(config, week):
    return review_data.read_sort(config.paths.data_dir, week)


def test_a_pass_sorts_its_review_and_counts_the_cost(tree):
    read_notes(tree, note())
    fake = SortingCall(memory=memory_reply(change()))
    result = run(tree, DRY, fake)
    assert fake.sort_calls == 1 and result["sort"]["rated"] >= 1 and result["sort"]["unrated"] == 0
    assert result["cost_usd"] >= result["sort"]["cost_usd"] == 0.1
    review = review_data.latest_review(tree.paths.data_dir)
    assert [item["number"] for item in review["items"]] == list(range(1, len(review["items"]) + 1))
    assert not [failure for failure in review["failures"] if failure["kind"] == review_data.KIND_SORT_FAILED]
    with open(result["review_page"], encoding="utf-8") as handle:
        page = handle.read()
    assert "It lasts." in page


def test_a_failed_sort_leaves_the_review_written_and_the_pass_as_it_was(tree):
    read_notes(tree, note())
    result = run(tree, DRY, SortingCall(sort_error=model_call.ModelCallError("the model is away"), memory=memory_reply(change())))
    assert os.path.exists(result["review_page"]) and result["status"] == "ok"
    review = review_data.latest_review(tree.paths.data_dir)
    assert review["items"], "the review holds the items"
    failures = [failure for failure in review["failures"] if failure["kind"] == review_data.KIND_SORT_FAILED]
    assert len(failures) == 1 and "the model is away" in failures[0]["summary"]
    entries = sort_file(tree, review["week"])[0]["items"]
    assert all(entry["status"] == schemas.SORT_ENTRY_UNRATED for entry in entries.values())
    assert result["data_commit"] is not None
    marker = json.loads(open(os.path.join(tree.paths.data_dir, review_data.MARKER_FILE), encoding="utf-8").read())
    assert [(entry["pass"], entry["kind"]) for entry in marker["entries"]] == [("review", "sort_failed")]


def test_a_pass_stopped_by_its_budget_still_writes_its_review_and_rates_nothing(tree):
    read_notes(tree, note())
    small = dataclasses.replace(tree, model=dataclasses.replace(tree.model, run_budget_usd=0.5))
    fake = SortingCall(memory=memory_reply(change()))
    result = run(small, DRY, fake)
    assert result["status"] == "budget_stopped" and fake.sort_calls == 0 and result["sort"]["rated"] == 0
    assert os.path.exists(result["review_page"])


def test_a_pass_whose_sort_succeeds_clears_the_warning(tree):
    read_notes(tree, note())
    run(tree, DRY, SortingCall(sort_error=model_call.ModelCallError("the model is away"), memory=memory_reply(change())))
    marker = os.path.join(tree.paths.data_dir, review_data.MARKER_FILE)
    assert os.path.exists(marker)
    report = report_of(tree)
    os.remove(os.path.join(tree.paths.data_dir, "reports", report["week"], "report.json"))
    run(tree, DRY, SortingCall(memory=memory_reply(change())))
    assert not os.path.exists(marker)


def test_the_sort_is_tracked_in_the_data_folder_with_the_review(tree):
    read_notes(tree, note())
    run(tree, DRY, SortingCall(memory=memory_reply(change())))
    report = report_of(tree)
    assert os.path.isfile(review_data.sort_path(tree.paths.data_dir, report["week"]))
