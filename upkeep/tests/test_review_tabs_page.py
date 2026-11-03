"""The tabbed page: which tab, what shows on every tab, and that hostile text stays inert. All text is made up."""
from __future__ import annotations

import base64
import hashlib
import json
import re

import pytest
from test_review import (  # noqa: F401 (tree is a fixture)
    EVIL,
    NOW,
    SESSION,
    WEEK,
    change,
    current,
    hostile_review,
    proposal,
    publish,
    report,
    tags_of,
    tree,
)

import review_data
import review_page
import review_session


def rated(importance="lower", clarity="clear", recommended="skip", options=(), reason="Costs little.", citations=()):
    return {
        "status": "rated", "digest": "d", "importance": importance, "clarity": clarity, "reason": reason, "recommended": recommended,
        "options": list(options), "unrated_reason": "", "citations": list(citations),
    }


def unrated(reason="It failed."):
    return {"status": "unrated", "digest": "", "importance": "", "clarity": "", "reason": "", "recommended": "", "options": [], "unrated_reason": reason, "citations": []}


def sorting_of(review, *entries):
    return {
        "schema_version": 1, "week": review["week"], "sorted_at": NOW.isoformat(), "run_id": "r", "model": "m", "cost_usd": 0.1,
        "items": {item["key"]: entry for item, entry in zip(review["items"], entries) if entry is not None},
    }


def built(tree, **kwargs):
    return review_data.build_review(tree, report(**kwargs), NOW)


def panel(page, tab):
    start = page.index(f'<section class="panel" id="panel-{tab}"')
    return page[start:page.index("</section>", start)]


def tab_button(page, tab):
    return re.search(rf'<button type="button" role="tab" data-tab="{tab}"[^>]*>([^<]*)</button>', page).group(1)


# ---- Which tab ----


@pytest.mark.parametrize("importance, clarity, tab", [
    ("important", "unclear", "important-unclear"),
    ("important", "clear", "important-clear"),
    ("lower", "clear", "lower-clear"),
    ("lower", "unclear", "lower-unclear"),
])
def test_a_rating_chooses_the_tab(tree, importance, clarity, tab):
    review = built(tree, proposals=[proposal(1)])
    options = ["a", "b"] if clarity == "unclear" else []
    page = review_page.render_page(review, sorting_of(review, rated(importance, clarity, options=options)))
    assert 'id="item-1"' in panel(page, tab)
    assert "(1)" in tab_button(page, tab)


def test_tabs_come_in_order_with_important_and_unclear_first(tree):
    page = review_page.render_page(built(tree))
    labels = [re.sub(r" \(.*", "", label) for label in re.findall(r'role="tab" data-tab="[^"]*"[^>]*>([^<]*)<', page)]
    assert labels == ["Important and unclear", "Important and clear", "Lower and clear", "Lower and unclear", "Unsorted", "Decided", "Failures and notices"]


def test_with_no_sort_every_open_item_is_unsorted_and_never_lower_or_clear(tree):
    page = review_page.render_page(built(tree, changes=[change(1)], proposals=[proposal(2)]))
    assert "(2)" in tab_button(page, "unsorted")
    for tab in ("important-unclear", "important-clear", "lower-clear", "lower-unclear"):
        assert "(0)" in tab_button(page, tab)
    assert "No sort has run" in panel(page, "unsorted")
    assert "2 items not sorted" in page


def test_an_unrated_item_shows_its_reason_and_offers_no_recommendation(tree):
    review = built(tree, proposals=[proposal(1)])
    page = review_page.render_page(review, sorting_of(review, unrated("The call for this batch failed.")))
    body = panel(page, "unsorted")
    assert "The call for this batch failed." in body
    assert 'class="recommended"' not in body and 'data-recommended=""' in body


def test_an_item_after_the_last_sort_is_unsorted_and_says_so(tree):
    review = built(tree, proposals=[proposal(1)])
    page = review_page.render_page(review, sorting_of(review, None))
    assert "came after the last sort" in panel(page, "unsorted")


def test_a_decided_item_moves_to_decided_and_offers_no_choice(tree):
    publish(tree, report(proposals=[proposal(1), proposal(2)]))
    review_session.reject(tree, current(tree)["review_id"], 1, SESSION, NOW)
    review = current(tree)
    page = review_page.render_page(review, sorting_of(review, rated(), rated()))
    assert 'id="item-1"' in panel(page, "decided")
    assert "choice-1" not in page and "choice-2" in page
    assert "Decided" in panel(page, "decided")


def test_counts_are_on_the_tabs(tree):
    review = built(tree, proposals=[proposal(1), proposal(2), proposal(3)])
    page = review_page.render_page(review, sorting_of(review, rated(), rated(), rated("important", "clear")))
    assert tab_button(page, "lower-clear") == "Lower and clear (2)"
    assert tab_button(page, "important-clear") == "Important and clear (1)"


# ---- Failures, whichever tab is open ----


def test_failures_sit_above_the_tabs_and_in_their_own_tab(tree):
    review = built(tree, proposals=[proposal(1)], status="failed", stop_reason="the search stopped")
    page = review_page.render_page(review)
    tabbar = page.index('class="tabbar"')
    assert page.index("the search stopped") < tabbar
    assert "the search stopped" in panel(page, "failures")
    assert 'class="alarm"' in page
    assert "1 failed" in tab_button(page, "failures")


def test_notices_stay_in_their_tab_and_do_not_read_as_failures(tree):
    review = built(tree)
    review["failures"].append({"kind": review_page.KIND_POSSIBLE_RENAME, "summary": "Maybe the same item."})
    page = review_page.render_page(review)
    assert "Maybe the same item." in panel(page, "failures")
    assert page.index("Maybe the same item.") > page.index('class="tabbar"')
    assert "0 failed, 1 to note" in tab_button(page, "failures")
    assert 'class="alarm"' not in page


def test_with_no_script_every_tab_still_reads_and_says_so(tree):
    style = review_page._STYLE
    assert ".scripted .panel { display: none; }" in style and "html:not(.scripted) .tabbar" in style
    assert "Scripts are off for this page" in review_page.render_page(built(tree))


# ---- The choices ----


def test_bullets_are_the_allowed_actions_with_the_options_after_them(tree):
    review = built(tree, proposals=[proposal(1)])
    entry = rated("important", "unclear", recommended="reject", options=["It still holds", "It went stale"])
    body = panel(review_page.render_page(review, sorting_of(review, entry)), "important-unclear")
    values = re.findall(r'name="choice-1" value="([^"]*)"', body)
    assert values == ["action:approve", "action:reject", "action:skip", "action:why", "option:0", "option:1"]
    assert "It still holds" in body and "runs nothing" in body
    assert 'id="note-1"' in body


def test_the_recommended_action_is_marked_and_not_selected(tree):
    review = built(tree, proposals=[proposal(1)])
    page = review_page.render_page(review, sorting_of(review, rated(recommended="reject")))
    body = panel(page, "lower-clear")
    assert re.search(r'value="action:reject"[^>]*> Reject<span class="recommended">Recommended</span>', body)
    assert 'data-recommended="action:reject"' in body
    assert "checked" not in body


def test_a_recommendation_no_longer_allowed_is_not_offered(tree):
    review = built(tree, proposals=[proposal(1)])
    page = review_page.render_page(review, sorting_of(review, rated(recommended="undo")))
    assert 'class="recommended"' not in page and 'data-recommended=""' in page


def test_bulk_fill_is_on_sorted_tabs_with_items_and_says_it_only_fills(tree):
    review = built(tree, proposals=[proposal(1)])
    page = review_page.render_page(review, sorting_of(review, rated()))
    assert 'data-fill="lower-clear"' in panel(page, "lower-clear")
    assert "only fills in the choices" in panel(page, "lower-clear")
    assert 'data-fill="important-clear"' not in page and 'data-fill="unsorted"' not in page


def test_typing_is_still_offered_on_every_open_item(tree):
    review = built(tree, changes=[change(1, outcome="applied", commit="abc")], proposals=[proposal(2)])
    page = review_page.render_page(review, sorting_of(review, rated(), rated()))
    assert "<code>undo 1</code>" in page and "<code>approve 2</code>" in page


@pytest.mark.parametrize("kind", ["hook", "global_rule", "plugin", "mcp"])
def test_approving_what_needs_a_typed_yes_says_it_will_be_asked(tree, kind):
    page = review_page.render_page(built(tree, proposals=[proposal(1, kind=kind)]))
    assert "This will be asked in the session" in page and 'data-asks="yes"' in page


def test_a_monthly_finding_says_its_edit_is_shown_first(tree):
    record = proposal(1, kind="monthly_finding", basis="", evidence={"audit_question": "q", "question": "q", "category": "c", "sides": [], "measured": []})
    page = review_page.render_page(built(tree, proposals=[record]))
    assert "The session shows you any edit first" in page and 'data-asks="no"' in page


def test_the_page_says_generally_what_will_be_asked_in_the_session(tree):
    assert "will be asked in the session, on the exact change" in review_page.render_page(built(tree))


def test_an_unknown_action_raises(tree):
    review = built(tree, proposals=[proposal(1)])
    review["items"][0]["allowed"] = ["launch"]
    with pytest.raises(KeyError):
        review_page.render_page(review)


# ---- Send on and off ----


def test_a_static_page_has_send_off_says_why_and_can_talk_to_nothing(tree):
    page = review_page.render_page(built(tree))
    assert "Send is off." in page and review_page.NOT_SERVED_REASON in page
    assert 'id="send-button" disabled' in page
    assert "connect-src" not in page
    assert json.loads(re.search(r'id="page-data">(.*?)</script>', page).group(1))["served"] is False


def test_the_reason_send_is_off_can_be_given_and_is_escaped(tree):
    page = review_page.render_page(built(tree), send=review_page.SendState(False, f"The server failed: {EVIL}"))
    assert "The server failed" in page and "<img" not in page
    assert page.lower().count("<script") == 2


def test_a_served_page_may_talk_to_its_own_server_only(tree):
    send = review_page.SendState(True, "", 20000, 3000, 4000, 8000)
    page = review_page.render_page(built(tree, proposals=[proposal(1)]), send=send)
    assert "connect-src 'self'" in page and "<strong>Send is off.</strong>" not in page
    assert 'maxlength="4000"' in page and 'maxlength="8000"' in page
    data = json.loads(re.search(r'id="page-data">(.*?)</script>', page).group(1))
    assert data == {"review_id": data["review_id"], "served": True, "off_reason": "", "heartbeat_ms": 20000, "poll_ms": 3000}


def test_the_page_says_plainly_how_to_reopen_after_the_server_closes(tree):
    page = review_page.render_page(built(tree), send=review_page.SendState(True, "", 1, 1, 1, 1))
    closed = page[page.index('id="server-closed"'):]
    assert "The local server has closed" in closed and "Start-UpkeepReview.ps1" in closed and review_page.SHORTCUT_NAME in closed


# ---- The security policy ----


def policy_of(page):
    return re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">', page).group(1)


def b64_sha256(text):
    return base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii")


def test_the_policy_allows_only_this_script_and_this_style_by_hash(tree):
    page = review_page.render_page(built(tree))
    policy = policy_of(page)
    script = re.search(r"<script>(.*?)</script>", page, re.S).group(1)
    style = re.search(r"<style>(.*?)</style>", page, re.S).group(1)
    assert f"script-src 'sha256-{b64_sha256(script)}'" in policy
    assert f"style-src 'sha256-{b64_sha256(style)}'" in policy
    assert "default-src 'none'" in policy and "base-uri 'none'" in policy and "form-action 'none'" in policy
    assert "unsafe" not in policy and "http" not in policy


def test_the_script_hash_does_not_depend_on_how_the_file_ends_its_lines(tree, tmp_path, monkeypatch):
    with open(review_page._SCRIPT_PATH, encoding="utf-8", newline="") as handle:
        original = handle.read().replace("\r\n", "\n")
    copy = tmp_path / "crlf.js"
    copy.write_bytes(original.replace("\n", "\r\n").encode("utf-8"))
    monkeypatch.setattr(review_page, "_SCRIPT_PATH", str(copy))
    assert "\r" not in review_page._page_script()
    assert review_page._source_hash(review_page._page_script()) == review_page._source_hash(original)


def test_the_header_policy_also_refuses_framing(tree):
    assert "frame-ancestors 'none'" in review_page.content_security_policy(True, for_header=True)
    assert "frame-ancestors" not in review_page.content_security_policy(True)


def test_the_script_builds_no_markup_and_loads_nothing():
    with open(review_page._SCRIPT_PATH, encoding="utf-8") as handle:
        script = handle.read()
    for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "Function(", "createElement", "</script", "XMLHttpRequest", "http://", "https://"):
        assert forbidden not in script, forbidden


# ---- Hostile text in every field ----


def hostile_sort(review):
    citation = {"file": EVIL, "line": 1, "status": "moved", "found_line": 2}
    entries = {}
    for position, item in enumerate(review["items"]):
        entries[item["key"]] = (
            rated("important", "unclear", recommended=item["allowed"][0], options=[EVIL, f"{EVIL} two"], reason=EVIL, citations=[citation])
            if position % 2 == 0 else unrated(EVIL)
        )
    return {"schema_version": 1, "week": EVIL, "sorted_at": EVIL, "run_id": EVIL, "model": EVIL, "cost_usd": 0.0, "items": entries}


@pytest.mark.parametrize("send", [review_page.STATIC_SEND, review_page.SendState(True, "", 1, 1, 1, 1), review_page.SendState(False, EVIL)])
def test_hostile_text_in_every_field_stays_inert(tree, send):
    review = hostile_review(tree)
    review["failures"].extend({"kind": kind, "summary": EVIL} for kind in (*review_page.NOTICE_KINDS, review_page.KIND_SORT_FAILED, EVIL))
    review["review_id"] = EVIL
    review["week"] = EVIL
    review["run_id"] = EVIL
    review["built_at"] = EVIL
    page = review_page.render_page(review, hostile_sort(review), EVIL, send)
    tags = tags_of(page)
    assert EVIL not in page
    assert "<img" not in page.lower() and "<iframe" not in page.lower()
    scripts = [attributes for tag, attributes in tags if tag == "script"]
    assert scripts == [{"type": "application/json", "id": "page-data"}, {}], "exactly the data block and the one allowed script"
    allowed = {"html", "head", "meta", "title", "style", "body", "main", "h1", "h2", "h3", "h4", "p", "div", "span", "section", "article", "ul", "li", "details", "summary",
               "pre", "code", "blockquote", "strong", "em", "table", "tr", "th", "td", "a", "fieldset", "legend", "label", "input", "textarea", "button", "small", "script", "br"}
    assert {tag for tag, _ in tags} <= allowed
    for tag, attributes in tags:
        names = set(attributes)
        assert not {name for name in names if name.startswith("on") or name in ("src", "srcset", "srcdoc", "background", "action", "formaction", "style")}, tag


def test_data_in_the_script_block_cannot_end_it(tree):
    text = review_page._script_data({"x": "</script><script>alert(1)</script><!-- &  "})
    assert "<" not in text and ">" not in text and "&" not in text and " " not in text
    assert json.loads(text)["x"].startswith("</script>")


def test_a_hostile_option_cannot_reach_a_value_only_a_label(tree):
    review = built(tree, proposals=[proposal(1)])
    entry = rated("important", "unclear", recommended="skip", options=['" onfocus="alert(1)', '</label><script>alert(2)</script>'])
    page = review_page.render_page(review, sorting_of(review, entry))
    tags = [attributes for tag, attributes in tags_of(page) if tag == "input"]
    assert {attributes["value"] for attributes in tags} >= {"option:0", "option:1"}
    assert not [name for attributes in tags for name in attributes if name.startswith("on")]
    assert page.lower().count("<script") == 2
