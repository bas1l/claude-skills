"""Defects found by the second independent review: the review page and session. All text is made up."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from test_review import (  # noqa: F401 (tree is a fixture)
    NOW,
    SESSION,
    WEEK,
    change,
    current,
    ensure_memory_ledger,
    proposal,
    publish,
    report,
    tree,
)

import review_data
import review_page
import review_session


# ---- Defect 9: lines that look like diff headers ----


def diff_rows(before, after):
    return review_page._diff(before, after)


def test_removing_a_line_starting_with_two_dashes_shows(tree):
    assert "--flag was here" in diff_rows("keep\n--flag was here\n", "keep\n")


def test_adding_a_line_starting_with_two_pluses_shows(tree):
    assert "++added" in diff_rows("keep\n", "keep\n++added\n")


def test_the_two_header_lines_and_hunk_lines_stay_out(tree):
    rows = diff_rows("one\n", "two\n")
    assert rows.count("<div class=") == 3, "the frame and two rows, with no header and no hunk line"
    assert "@@" not in rows
    assert "No lines differ" in diff_rows("same\n", "same\n")


def test_a_new_file_of_frontmatter_shows_its_fences(tree):
    assert diff_rows(None, "---\ndescription: x\n---\nbody\n").count("+---") == 2


# ---- Defect 11: the overdue banner ----


def test_weeks_with_nothing_to_review_are_not_overdue(tree):
    publish(tree, report("2031-W03"), NOW)
    publish(tree, report("2031-W04", generated=NOW + timedelta(days=7)), NOW + timedelta(days=7))
    publish(tree, report("2031-W05", generated=NOW + timedelta(days=14)), NOW + timedelta(days=14))
    assert review_data.weeks_overdue(tree.paths.data_dir, NOW + timedelta(days=14)) == 0
    assert current(tree)["weeks_overdue"] == 0


def test_a_week_with_an_open_item_stays_overdue_through_empty_ones(tree):
    publish(tree, report("2031-W03", proposals=[proposal(1)]), NOW)
    publish(tree, report("2031-W04", generated=NOW + timedelta(days=7)), NOW + timedelta(days=7))
    assert current(tree)["weeks_overdue"] == 1
    assert review_data.weeks_overdue(tree.paths.data_dir, NOW + timedelta(days=14)) == 2


def test_the_review_being_built_counts_its_own_open_items(tree):
    publish(tree, report("2031-W03", proposals=[proposal(1)]), NOW + timedelta(days=7))
    assert current(tree)["weeks_overdue"] == 1


# ---- Defect 16: small ones ----


@pytest.mark.parametrize("address", ["http://[bad/x", "https://[", "http://[::1/x"])
def test_a_bad_address_is_inert_text_and_does_not_stop_the_page(address):
    rendered = review_page._link(address, "Some label")
    assert "<a " not in rendered and "Some label" in rendered and "not a web link" in rendered


def test_a_good_address_is_still_a_link():
    assert '<a href="https://example.org/x"' in review_page._link("https://example.org/x")


def test_the_page_shows_the_ledger_after_a_reject_and_an_undo_on_a_trial_item(tree):
    ensure_memory_ledger(tree, "memory-1")
    publish(tree, report(WEEK, changes=[change(1)]))
    review = current(tree)
    assert review["items"][0]["ledger"]["entries_against"] == 0
    page = review_session.undo(tree, review["review_id"], 1, SESSION, NOW)["page"]
    after = current(tree)
    assert after["items"][0]["ledger"]["entries_against"] == 1
    assert "0 entries for, 1 against" in Path(page).read_text(encoding="utf-8")


def test_the_page_shows_its_version(tree):
    publish(tree, report(WEEK, proposals=[proposal(1)]))
    review = current(tree)
    assert review["review_id"] in review_page.render_page(review)


def cli(tree, monkeypatch, *arguments):
    monkeypatch.setattr(review_session, "load_config", lambda _: tree)
    return review_session.main(list(arguments))


def test_a_number_from_another_version_of_the_page_is_refused(tree, monkeypatch, capsys):
    publish(tree, report(WEEK, proposals=[proposal(1), proposal(2)]))
    first_id = current(tree)["review_id"]
    assert cli(tree, monkeypatch, "skip", "1", "--review", first_id, "--session", SESSION) == 0

    publish(tree, report("2031-W04", proposals=[proposal(3)], generated=NOW + timedelta(days=7)), NOW + timedelta(days=7))
    second_id = current(tree)["review_id"]
    assert second_id != first_id
    assert cli(tree, monkeypatch, "skip", "1", "--review", first_id, "--session", SESSION) == review_session.EXIT_REFUSED
    capsys.readouterr()

    # The session reads the review again and has the new id, while Basil still has the old page open.
    assert cli(tree, monkeypatch, "skip", "1", "--review", second_id, "--session", SESSION) == review_session.EXIT_REFUSED
    message = capsys.readouterr().err
    assert first_id in message and second_id in message and "reload" in message.lower()
    assert current(tree)["items"][0]["skipped_at"] is None

    # He reloaded the page and said so.
    assert cli(tree, monkeypatch, "read-again", "--review", second_id, "--session", SESSION) == 0
    capsys.readouterr()
    assert cli(tree, monkeypatch, "skip", "2", "--review", second_id, "--session", SESSION) == 0


def test_every_action_that_writes_needs_the_session(tree, monkeypatch, capsys):
    publish(tree, report(WEEK, proposals=[proposal(1)]))
    assert cli(tree, monkeypatch, "skip", "1", "--review", current(tree)["review_id"]) == review_session.EXIT_REFUSED
    assert "--session" in capsys.readouterr().err


def test_read_again_is_refused_for_a_version_that_is_not_the_current_one(tree, monkeypatch):
    publish(tree, report(WEEK, proposals=[proposal(1)]))
    assert cli(tree, monkeypatch, "read-again", "--review", "not-the-id", "--session", SESSION) == review_session.EXIT_REFUSED


def test_two_sessions_hold_their_own_version(tree, monkeypatch):
    publish(tree, report(WEEK, proposals=[proposal(1), proposal(2)]))
    review_id = current(tree)["review_id"]
    assert cli(tree, monkeypatch, "skip", "1", "--review", review_id, "--session", "first-session") == 0
    assert cli(tree, monkeypatch, "skip", "2", "--review", review_id, "--session", "second-session") == 0


def test_the_skill_says_what_to_do_when_the_page_changed():
    from test_review import SKILL_FILE
    text = SKILL_FILE.read_text(encoding="utf-8")
    assert "read-again" in text
