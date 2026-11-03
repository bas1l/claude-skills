"""Render a review as one HTML page, with tabs and a choice on each item. Knows no git and no model.

Everything shown comes from transcripts, memories, model replies or web pages, so all of it is
data. Every value goes through ``_text``, or ``_script_data`` inside the data block. The page's one
script is ``review_page.js``, allowed by its hash, and it makes no markup from data. It loads
nothing: a content security policy says so too, and the only links out are plain anchors, shown as
external. A link that is not http or https is shown as text. There is no form element, so
``form-action 'none'`` stays: Send uses ``fetch``, which only the served page's ``connect-src 'self'``
allows. Without a server behind it the page has no connection at all, so Send is off and says why.

Without its script the page still reads: every tab's items show one after the other. An item the
sort has not rated goes under Unsorted, with the reason. Nothing here gives it a rating.

An unknown kind or action raises, so a new one cannot go on the page unexplained.
"""
from __future__ import annotations

import base64
import difflib
import hashlib
import html
import json
import os
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import urlsplit

SECTION_MEMORY = "memory"
SECTION_PROPOSAL = "proposal"
OUTCOME_APPLIED = "applied"
KIND_POSSIBLE_RENAME = "possible_rename"
KIND_STANCE_CHECK = "stance_check"
KIND_RULE_BROKEN = "rule_broken"
KIND_MALFUNCTION = "malfunction"
KIND_SORT_FAILED = "sort_failed"
NOTICE_KINDS = frozenset({KIND_POSSIBLE_RENAME, KIND_STANCE_CHECK, KIND_RULE_BROKEN, KIND_MALFUNCTION})

TAB_IMPORTANT_UNCLEAR = "important-unclear"
TAB_IMPORTANT_CLEAR = "important-clear"
TAB_LOWER_CLEAR = "lower-clear"
TAB_LOWER_UNCLEAR = "lower-unclear"
TAB_UNSORTED = "unsorted"
TAB_DECIDED = "decided"
TAB_FAILURES = "failures"
_SORTED_TABS = {
    ("important", "unclear"): TAB_IMPORTANT_UNCLEAR,
    ("important", "clear"): TAB_IMPORTANT_CLEAR,
    ("lower", "clear"): TAB_LOWER_CLEAR,
    ("lower", "unclear"): TAB_LOWER_UNCLEAR,
}
ITEM_TABS = (
    (TAB_IMPORTANT_UNCLEAR, "Important and unclear"),
    (TAB_IMPORTANT_CLEAR, "Important and clear"),
    (TAB_LOWER_CLEAR, "Lower and clear"),
    (TAB_LOWER_UNCLEAR, "Lower and unclear"),
    (TAB_UNSORTED, "Unsorted"),
    (TAB_DECIDED, "Decided"),
)
SORT_NOT_RUN = "No sort has run on this review yet. To sort it: python review_sort.py sort. Reading it and deciding work the same without a sort."
SORT_NOT_READABLE = "The sort of this review could not be read."
SORT_NO_ENTRY = "This item came after the last sort."
# Kinds whose approval changes something only after a yes typed in the session, and those whose edits are shown first.
ASKED_IN_SESSION_KINDS = frozenset({"hook", "global_rule", "plugin", "mcp"})
SHOWN_FIRST_KINDS = frozenset({"monthly_finding"})
REOPEN_COMMAND = 'pwsh -File "$HOME\\.claude\\skills\\upkeep\\Start-UpkeepReview.ps1"'
SHORTCUT_NAME = "Claude Upkeep Review"
NOT_SERVED_REASON = "This copy of the page was opened as a file, with no local server behind it."

_KIND_LABEL = {
    "skill": "Skill (written instructions Claude can load)",
    "plugin": "Plugin (an install package for Claude Code)",
    "hook": "Hook (a check Claude Code runs by itself)",
    "mcp": "MCP server (a connection that gives Claude tools)",
    "global_rule": "Rule for every project (global CLAUDE.md)",
    "memory_fact": "Fact to save in memory",
    "memory_split_claim": "Half of a statement, held because the other half was rejected",
    "memory_deletion": "Text to remove from memory",
    "memory_revision": "Memory to reread and revise",
    "item_revision": "Item to reread and revise",
    "monthly_finding": "Finding of the monthly check, for you to read and decide",
}
_APPROVE_DOES = {
    "skill": "creates a local branch of the skills repository holding the draft. Nothing is merged or pushed.",
    "plugin": "the session shows the exact command, and applies it only after you confirm.",
    "hook": "the session shows the exact change, and applies it only after you confirm.",
    "mcp": "the session shows the exact command, and applies it only after you confirm.",
    "global_rule": "the session shows the exact change, and applies it only after you confirm.",
    "memory_fact": "writes this into the memory as a new commit, which can be reverted.",
    "memory_split_claim": "writes this into the memory as a new commit, which can be reverted.",
    "memory_deletion": "takes this out of the memory as a new commit, which can be reverted.",
    "memory_revision": "you and the session reread it together. Nothing changes by itself.",
    "item_revision": "you and the session reread it together. Nothing changes by itself.",
    "monthly_finding": "you and the session read it together, and make any edit you ask for. Nothing changes by itself.",
}
_BASIS_LABEL = {
    "": None,
    "recurrence": "It came up in several separate sessions",
    "costly_once": "One long procedure cost many tool calls",
    "failure_cost": "The same failure lost commands",
    "stated_rule": "You stated it as a rule",
}
_ENDORSEMENT_LABEL = {
    "said": "You said",
    "accepted": "You accepted this, in your next message",
    "relied_on": "You relied on this, in your next message",
}
_ACTION_LABEL = {
    "undo": "undo {n}",
    "keep": "keep {n}",
    "skip": "skip {n}",
    "why": "why {n}",
    "reject": "reject {n}",
    "approve": "approve {n}",
}
_OUTCOME_LABEL = {
    "undone": "Undone",
    "kept": "Kept",
    "rejected": "Rejected",
    "approved": "Approved",
}
_ACTION_DOES = {
    "undo": "Takes this change out, by a new commit. It will not be offered again without something new from you.",
    "keep": "It stays, and stops carrying forward.",
    "skip": "Stays open, and carries forward with its original week.",
    "why": "The session reads out the evidence behind it. Nothing changes.",
    "reject": "Nothing changes. It will not be offered again without something new from you.",
}
_CITATION_LABEL = {
    "matches": "The quote is still on this line.",
    "moved": "The quote is in the file, on another line now.",
    "changed": "The file no longer holds this quote, so the finding may no longer apply.",
    "redacted": "The quote holds a removed secret, so it could not be compared.",
    "file_gone": "The file is gone, so the finding may no longer apply.",
    "unreadable": "The file could not be read, so nothing could be compared.",
    "no_quote": "Nothing was quoted to compare.",
}
_CITATION_WARNS = frozenset({"changed", "file_gone", "unreadable"})
_QUIET_LEDGER = (
    'A missing "for" means little: it needs a visible reaction from you to what the item did, and most of the time nobody '
    "says anything when something works. A quiet ledger does not show that an item is fine. It shows only that nothing was seen either way."
)
_CHANGE_TYPE_LABEL = {"new": "Something new", "change": "A change to something that exists"}

_STYLE = """
:root { color-scheme: light dark; --ink: #1d2433; --soft: #5b6475; --line: #d9dde5; --card: #ffffff; --page: #f4f5f7;
  --warn-bg: #fdecea; --warn-ink: #8c1d18; --note-bg: #fff6df; --note-ink: #6b4e00; --add: #e3f4e6; --del: #fbe6e4; --mark: #2f5fb3; }
@media (prefers-color-scheme: dark) { :root { --ink: #e7e9ee; --soft: #a4acbb; --line: #363c49; --card: #20242d; --page: #15181e;
  --warn-bg: #43191a; --warn-ink: #ffc9c4; --note-bg: #3a2f10; --note-ink: #f2dc9f; --add: #1c3a24; --del: #472020; --mark: #8db1f2; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink); font: 16px/1.5 system-ui, "Segoe UI", sans-serif; }
main { max-width: 56rem; margin: 0 auto; padding: 1.5rem 1rem 4rem; }
h1 { font-size: 1.6rem; margin: 0 0 .25rem; } h2 { font-size: 1.25rem; margin: 2.25rem 0 .25rem; }
h3 { font-size: 1.05rem; margin: 0; } h4 { font-size: .85rem; margin: 1rem 0 .2rem; color: var(--soft); font-weight: 600; }
p { margin: .25rem 0; } .soft { color: var(--soft); font-size: .9rem; }
.banner { border-radius: .5rem; padding: .75rem 1rem; margin: .75rem 0; }
.warn { background: var(--warn-bg); color: var(--warn-ink); } .note { background: var(--note-bg); color: var(--note-ink); }
.plain { background: var(--card); border: 1px solid var(--line); }
article { background: var(--card); border: 1px solid var(--line); border-radius: .5rem; padding: 1rem; margin: .75rem 0; }
article.done { opacity: .72; }
.head { display: flex; gap: .6rem; align-items: baseline; flex-wrap: wrap; }
.number { font-weight: 700; color: var(--mark); font-size: 1.15rem; }
.tag { font-size: .78rem; border: 1px solid var(--line); border-radius: 1rem; padding: 0 .5rem; color: var(--soft); }
.tag.strong { color: var(--warn-ink); border-color: currentColor; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; margin: .25rem 0; padding: .5rem .6rem; border: 1px solid var(--line); border-radius: .35rem; font: .85rem/1.45 Consolas, monospace; }
.diff { padding: .25rem 0; } .diff div { padding: 0 .6rem; white-space: pre-wrap; overflow-wrap: anywhere; font: .85rem/1.45 Consolas, monospace; }
.diff .added { background: var(--add); } .diff .removed { background: var(--del); }
code { font: .88em Consolas, monospace; overflow-wrap: anywhere; }
details { margin: .5rem 0; } summary { cursor: pointer; color: var(--mark); }
a { color: var(--mark); } .external { font-size: .78rem; color: var(--soft); }
ul { margin: .25rem 0; padding-left: 1.2rem; } table { border-collapse: collapse; width: 100%; font-size: .9rem; }
th, td { text-align: left; border-bottom: 1px solid var(--line); padding: .3rem .5rem .3rem 0; vertical-align: top; }
blockquote { margin: .25rem 0; padding-left: .75rem; border-left: 3px solid var(--line); white-space: pre-wrap; overflow-wrap: anywhere; }
.tabbar { position: sticky; top: 0; z-index: 2; background: var(--page); display: flex; flex-wrap: wrap; gap: .25rem; padding: .5rem 0; border-bottom: 1px solid var(--line); }
.tabbar button { font: inherit; font-size: .88rem; padding: .3rem .6rem; border: 1px solid var(--line); border-radius: .35rem; background: var(--card); color: var(--ink); cursor: pointer; }
.tabbar button[aria-selected="true"] { background: var(--mark); color: var(--card); border-color: var(--mark); }
.tabbar button.alarm { color: var(--warn-ink); background: var(--warn-bg); border-color: currentColor; font-weight: 700; }
.scripted .panel { display: none; } .scripted .panel.active { display: block; }
html:not(.scripted) .tabbar, html:not(.scripted) .choose, html:not(.scripted) .sendbar, html:not(.scripted) .bulk { display: none; }
.scripted .no-script { display: none; }
.sort { margin: .5rem 0; padding: .4rem .6rem; border-left: 3px solid var(--mark); background: var(--page); font-size: .92rem; }
.sort.unsorted { border-left-color: var(--warn-ink); }
fieldset.choose { border: 1px solid var(--line); border-radius: .35rem; margin: .6rem 0; padding: .4rem .7rem; }
fieldset.choose legend { font-size: .85rem; color: var(--soft); font-weight: 600; }
fieldset.choose label { display: block; margin: .15rem 0; } fieldset.choose label small { color: var(--soft); }
.recommended { font-size: .75rem; border: 1px solid var(--mark); color: var(--mark); border-radius: 1rem; padding: 0 .4rem; margin-left: .25rem; }
textarea { width: 100%; min-height: 2.4rem; font: .9rem/1.4 system-ui, "Segoe UI", sans-serif; background: var(--card); color: var(--ink); border: 1px solid var(--line); border-radius: .35rem; padding: .3rem .4rem; }
.result { margin: .3rem 0; padding: .25rem .5rem; border-radius: .35rem; background: var(--note-bg); color: var(--note-ink); font-size: .9rem; }
.result.refused { background: var(--warn-bg); color: var(--warn-ink); }
.bulk { display: flex; flex-wrap: wrap; gap: .4rem; margin: .4rem 0; }
.bulk button, .sendbar button { font: inherit; font-size: .88rem; padding: .25rem .6rem; border: 1px solid var(--line); border-radius: .35rem; background: var(--card); color: var(--ink); cursor: pointer; }
.sendbar { position: sticky; bottom: 0; z-index: 2; background: var(--card); border: 1px solid var(--line); border-radius: .5rem; padding: .5rem .75rem; margin-top: 1rem; }
.sendbar button#send-button { background: var(--mark); color: var(--card); border-color: var(--mark); font-weight: 600; }
.sendbar button#send-button:disabled { opacity: .45; cursor: not-allowed; }
.strong-warn { color: var(--warn-ink); font-weight: 600; font-size: .9rem; }
"""
_SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "review_page.js")


@dataclass(frozen=True)
class SendState:
    """What the page's Send button can do. ``reason`` says why it cannot, and shows on the page."""

    served: bool
    reason: str
    heartbeat_ms: int = 0
    poll_ms: int = 0
    max_note_chars: int = 0
    max_page_note_chars: int = 0


STATIC_SEND = SendState(False, NOT_SERVED_REASON)


def _page_script() -> str:
    """The script as the browser will hash it: HTML parsing turns a line ending into a plain newline."""
    with open(_SCRIPT_PATH, encoding="utf-8", newline="") as handle:
        return handle.read().replace("\r\n", "\n")


def _source_hash(text: str) -> str:
    return "sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii")


def content_security_policy(served: bool, for_header: bool = False) -> str:
    """The policy of the page. It allows this page's own script and style by hash, and nothing else
    at all, except that a served page may talk to the server it came from. ``frame-ancestors`` has
    no effect in a meta tag, so only the header holds it."""
    parts = [
        "default-src 'none'",
        f"script-src '{_source_hash(_page_script())}'",
        f"style-src '{_source_hash(_STYLE)}'",
        "base-uri 'none'",
        "form-action 'none'",
    ]
    if served:
        parts.append("connect-src 'self'")
    if for_header:
        parts.append("frame-ancestors 'none'")
    return "; ".join(parts)


def _script_data(value: Any) -> str:
    """JSON that cannot end its script element or start a comment there, whatever it holds."""
    return json.dumps(value, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def tab_of(item: Mapping[str, Any], entry: Optional[Mapping[str, Any]]) -> str:
    """The tab an item belongs under. Only a rating puts an item in a sorted tab."""
    if item["decision"] is not None:
        return TAB_DECIDED
    if entry is None or entry["status"] != "rated":
        return TAB_UNSORTED
    return _SORTED_TABS[(entry["importance"], entry["clarity"])]


def _text(value: Any) -> str:
    """Any value as inert HTML text."""
    return html.escape("" if value is None else str(value), quote=True)


def _link(url: Any, label: Any = None) -> str:
    """A plain anchor shown as external, or inert text if it is not a web address."""
    address = str(url)
    shown = _text(label if label else address)
    try:
        parts = urlsplit(address)
        host = parts.hostname
    except ValueError:
        return f"{shown} <span class=\"external\">(not a web link)</span>"
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return f"{shown} <span class=\"external\">(not a web link)</span>"
    return (
        f'<a href="{_text(address)}" rel="noreferrer" target="_blank">{shown}</a> '
        f'<span class="external">(external site: {_text(host)})</span>'
    )


def _field(label: str, body: str) -> str:
    return f"<h4>{_text(label)}</h4>{body}"


def _para(value: Any) -> str:
    return f"<p>{_text(value)}</p>"


def _diff(before: Optional[str], after: Optional[str]) -> str:
    """Only the lines that change, added or removed."""
    lines = difflib.unified_diff((before or "").splitlines(), (after or "").splitlines(), lineterm="", n=0)
    rows = []
    for position, line in enumerate(lines):
        # The first two lines are the file header. A hunk line starts at the first character, and
        # a line of the file never does, since every one of them has its + or - in front.
        if position < 2 or line.startswith("@@"):
            continue
        name = "added" if line.startswith("+") else "removed"
        rows.append(f'<div class="{name}">{_text(line)}</div>')
    return f'<div class="diff">{"".join(rows)}</div>' if rows else '<p class="soft">No lines differ.</p>'


def _full_text(summary: str, value: Optional[str]) -> str:
    body = f"<pre>{_text(value)}</pre>" if value is not None else '<p class="soft">This file does not exist at this point.</p>'
    return f"<details><summary>{_text(summary)}</summary>{body}</details>"


def _ledger(item: Mapping[str, Any]) -> str:
    summary = item["ledger"]
    if summary is None:
        return _field("Ledger (the reasons recorded for and against this)", '<p class="soft">Nothing is recorded yet, because this item has no ledger.</p>')
    reason = summary["founding_reason"]
    status = summary["founding_status"]
    rows = "".join(
        f"<li>{_text(entry['date'][:10])}, {_text(entry['direction'].replace('_', ' '))}, by {_text(entry['who'])}: {_text(entry['what'])}</li>"
        for entry in summary["latest"]
    )
    body = (
        f"<p>Why it exists: {_text(reason) if reason else 'no reason was recorded'} "
        f'<span class="soft">({_text(status)})</span></p>'
        f"<p>{_text(summary['entries_for'])} entries for, {_text(summary['entries_against'])} against. "
        f'<span class="soft">File: <code>{_text(summary["file"])}</code></span></p>'
        f'<p class="soft">{_text(_QUIET_LEDGER)}</p>'
    )
    if rows:
        body += f"<ul>{rows}</ul>"
    return _field("Ledger (the reasons recorded for and against this)", body)


def _research(research: Optional[Mapping[str, Any]]) -> str:
    if research is None:
        return ""
    searched = "".join(
        f"<li>{_text(entry['query'])}{'' if entry['worked'] else ' (failed)'}</li>" for entry in research["searched"]
    )
    fetched = "".join(
        f"<li>{_link(entry['url'])}{'' if entry['worked'] else ' (failed)'}</li>" for entry in research["fetched"]
    )
    tools = "".join(
        f"<li>{_link(tool['url'], tool['name'])}<br>Upkeep of that tool: {_text(tool['maintenance_evidence'])}<br>"
        f"What it can run on this PC: {_text(tool['can_execute'])}</li>"
        for tool in research["existing_tools"]
    )
    sources = "".join(
        f"<li>{_link(source['url'], source['title'])}: {_text(source['used_for'])}</li>" for source in research["sources"]
    )
    body = (
        f"<p><strong>Suggestion: {_text(research['recommendation'])}.</strong> {_text(research['recommendation_reason'])}</p>"
        f"<p class=\"soft\">Web text below is what the pages said. It is not advice from you.</p>"
        f"<details><summary>Details of the search</summary>"
        f"{_field('What was described to the search', _para(research['description']))}"
        f"{_field('Searches run', f'<ul>{searched}</ul>')}"
        f"{_field('Pages read', f'<ul>{fetched}</ul>')}"
        f"{_field('What Claude Code already offers', _para(research['official_features']))}"
        f"{_field('Existing tools', f'<ul>{tools}</ul>' if tools else '<p class=soft>None found.</p>')}"
        f"{_field('Conventions', _para(research['conventions']))}"
        f"{_field('Sources', f'<ul>{sources}</ul>')}"
        f"</details>"
    )
    return _field("Internet research", body)


def _evidence(evidence: Mapping[str, Any]) -> str:
    parts = []
    if evidence.get("audit_question"):
        parts.append(_para(f"Monthly question: {evidence['audit_question']}."))
    sides = "".join(
        f'<li><code>{_text(side["file"])}</code>, line {_text(side["line"])}'
        + (f'<blockquote>{_text(side["quote"])}</blockquote>' if side["quote"] else "")
        + "</li>"
        for side in evidence.get("sides", [])
    )
    if sides:
        parts.append(f"<ul>{sides}</ul>")
    measured = "".join(f"<li>{_text(line)}</li>" for line in evidence.get("measured", []))
    if measured:
        parts.append(f"<ul>{measured}</ul>")
    failure = evidence.get("failure")
    if failure:
        parts.append(_para(
            f"Measured failure: {failure['tool']}, {failure['commands_lost']} commands lost across "
            f"{failure['sessions']} sessions. It began: {failure['signature']}"
        ))
    procedure = evidence.get("procedure")
    if procedure:
        parts.append(_para(f"Measured procedure: {procedure['name']}, {procedure['calls']} tool calls in session {procedure['session']}."))
    if evidence.get("flag_reason"):
        parts.append(_para(f"Why it was flagged: {evidence['flag_reason']}."))
    if evidence.get("held_detail"):
        parts.append(_para(f"Why it was held: {evidence['held_detail']}."))
    rows = []
    for note in evidence.get("notes", []):
        said = f"<blockquote>{_text(note['quote'])}</blockquote>" if note["quote"] else ""
        rows.append(f'<li>{_text(note["what"])} <span class="soft">(session <code>{_text(note["session"])}</code>)</span>{said}</li>')
    for entry in evidence.get("entries", []):
        said = f"<blockquote>{_text(entry['quote'])}</blockquote>" if entry["quote"] else ""
        rows.append(
            f'<li>{_text(entry["what"])} <span class="soft">({_text(entry["date"][:10])}, by {_text(entry["who"])}, '
            f'session <code>{_text(entry["session"])}</code>)</span>{said}</li>'
        )
    if rows:
        parts.append(f"<ul>{''.join(rows)}</ul>")
    return _field("What this rests on", "".join(parts)) if parts else ""


def _memory_body(record: Mapping[str, Any]) -> str:
    parts = [
        _field("What it says", _para(record["claim"])),
        _field(
            "Why",
            f"<p>{_text(_ENDORSEMENT_LABEL[record['endorsement']])}:</p><blockquote>{_text(record['quote'])}</blockquote>"
            + (_para(f"That was your reply to: {record['assistant_statement']}") if record["assistant_statement"] else "")
            + ('<p class="soft">This was undone or rejected before. It is back because you said something new.</p>' if record["new_evidence"] else ""),
        ),
    ]
    if record["old_text"]:
        parts.append(_field("Text it replaces or removes", f"<pre>{_text(record['old_text'])}</pre>"))
    parts.append(_field("Before and after: lines added (+) and removed (-)", _diff(record["before"], record["after"])))
    parts.append(_full_text("The whole memory before", record["before"]))
    parts.append(_full_text("The whole memory after", record["after"]))
    place = f'<p>Project folder <code>{_text(record["project_folder"])}</code>, memory <code>{_text(record["memory"])}</code></p>'
    place += f'<p>Session <code>{_text(record["session"])}</code></p>'
    if record["commit"]:
        place += f'<p>Commit <code>{_text(record["commit"])}</code></p>'
    parts.append(_field("Where", place))
    return "".join(parts)


def _proposal_body(record: Mapping[str, Any]) -> str:
    kind = record["kind"]
    parts = [
        _para(_KIND_LABEL[kind]),
        _field("What would change", _para(record["what"])),
        _field("Why", _para(record["why"])),
    ]
    basis = _BASIS_LABEL[record["basis"]]
    if basis:
        parts.append(_field("Grounds", _para(basis)))
    facts = [_CHANGE_TYPE_LABEL[record["change_type"]]]
    if record["target"]:
        facts.append(f"Target: {record['target']}")
    if record["project_folder"]:
        facts.append(f"Project folder: {record['project_folder']}")
    parts.append(_field("About", _para(". ".join(facts))))
    if record["exact_change"]:
        parts.append(_field("The exact change", f"<pre>{_text(record['exact_change'])}</pre>"))
    if record["draft_path"]:
        parts.append(_field("Draft", f'<p>Under the upkeep folder: <code>{_text(record["draft_path"])}</code></p>'))
    parts.append(_research(record["research"]))
    parts.append(_evidence(record["evidence"]))
    parts.append(_field("If you approve", _para(_APPROVE_DOES[kind])))
    return "".join(parts)


def _citations(entry: Optional[Mapping[str, Any]]) -> str:
    if entry is None or not entry["citations"]:
        return ""
    rows = []
    for citation in entry["citations"]:
        place = f"<code>{_text(citation['file'])}</code>, line {_text(citation['line'])}"
        moved = f" Now on line {_text(citation['found_line'])}." if citation["status"] == "moved" else ""
        label = _text(_CITATION_LABEL[citation["status"]])
        shown = f'<strong>{label}</strong>' if citation["status"] in _CITATION_WARNS else label
        rows.append(f"<li>{place}: {shown}{moved}</li>")
    return _field("Checked against the file, when this was sorted", f"<ul>{''.join(rows)}</ul>")


def _sort_note(item: Mapping[str, Any], entry: Optional[Mapping[str, Any]], unsorted_reason: str) -> str:
    if item["decision"] is not None:
        return ""
    if entry is None or entry["status"] != "rated":
        reason = entry["unrated_reason"] if entry is not None else unsorted_reason
        return f'<div class="sort unsorted"><strong>Not sorted.</strong> {_text(reason)}</div>'
    return (
        f'<div class="sort">{_text(entry["importance"].capitalize())}, {_text(entry["clarity"])}. '
        f'{_text(entry["reason"])} <span class="soft">(a model\'s reading, not yours)</span></div>'
    )


def _action_note(item: Mapping[str, Any], action: str) -> str:
    if action != "approve":
        return _ACTION_DOES[action]
    kind = item["record"]["kind"]
    if kind in ASKED_IN_SESSION_KINDS:
        return f"This will be asked in the session: {_APPROVE_DOES[kind]}"
    if kind in SHOWN_FIRST_KINDS:
        return f"The session shows you any edit first: {_APPROVE_DOES[kind]}"
    return _APPROVE_DOES[kind]


def _choices(item: Mapping[str, Any], entry: Optional[Mapping[str, Any]], send: SendState) -> str:
    """One bullet for each allowed action and each option, and a box for his own words."""
    number = _text(item["number"])
    rated = entry is not None and entry["status"] == "rated"
    recommended = entry["recommended"] if rated and entry["recommended"] in item["allowed"] else ""
    rows = []
    for action in item["allowed"]:
        mark = '<span class="recommended">Recommended</span>' if action == recommended else ""
        rows.append(
            f'<label><input type="radio" name="choice-{number}" value="action:{_text(action)}" data-number="{number}"> '
            f"{_text(action.capitalize())}{mark} <small>{_text(_action_note(item, action))}</small></label>"
        )
    for position, option in enumerate(entry["options"] if rated else []):
        rows.append(
            f'<label><input type="radio" name="choice-{number}" value="option:{position}" data-number="{number}"> '
            f'<span id="option-{number}-{position}">{_text(option)}</span> '
            f"<small>Words a model wrote. Sent as your note, and runs nothing: the session asks what you want done.</small></label>"
        )
    limit = f' maxlength="{_text(send.max_note_chars)}"' if send.max_note_chars else ""
    return (
        f'<fieldset class="choose" id="choose-{number}" data-number="{number}" data-recommended="{"action:" + _text(recommended) if recommended else ""}">'
        f"<legend>Your decision on {number}</legend>{''.join(rows)}"
        f'<label>Your own words on this item (optional)<textarea id="note-{number}" data-number="{number}" rows="1"{limit}></textarea></label>'
        f"</fieldset>"
        f'<p class="result" id="result-{number}" hidden></p>'
    )


def _lead(item: Mapping[str, Any]) -> str:
    """What the item is, in a line or two, above the choices. The rest waits under Details."""
    record = item["record"]
    return _para(record["claim"] if item["section"] == SECTION_MEMORY else record["what"])


def _item(item: Mapping[str, Any], entry: Optional[Mapping[str, Any]], unsorted_reason: str, section_note: str, send: SendState) -> str:
    number = item["number"]
    decision = item["decision"]
    tags = [f'<span class="tag">Week {_text(item["week"])}</span>']
    if item["carried"]:
        tags.append(f'<span class="tag strong">Carried forward from week {_text(item["week"])}</span>')
    if item["origin"] == "monthly":
        tags.append('<span class="tag">From the monthly check</span>')
    if item["skipped_at"] and decision is None:
        tags.append(f'<span class="tag">Skipped on {_text(item["skipped_at"][:10])}</span>')
    if decision is not None:
        tags.append(f'<span class="tag strong">{_text(_OUTCOME_LABEL[decision["outcome"]])} on {_text(decision["at"][:10])}</span>')
    body = _memory_body(item["record"]) if item["section"] == SECTION_MEMORY else _proposal_body(item["record"])
    if decision is None:
        typed = ", ".join(f"<code>{_text(_ACTION_LABEL[action].format(n=number))}</code>" for action in item["allowed"])
        actions = _choices(item, entry, send) + _field("What you can type", f"<p>{typed}</p>")
    else:
        actions = _field("Decided", _para(decision["detail"]))
    done = ' class="done"' if decision is not None else ""
    asks = "yes" if item["section"] != SECTION_MEMORY and item["record"]["kind"] in ASKED_IN_SESSION_KINDS else "no"
    return (
        f'<article id="item-{_text(number)}" data-asks="{asks}"{done}>'
        f'<div class="head"><span class="number">{_text(number)}</span><h3>{_text(item["title"])}</h3>{"".join(tags)}</div>'
        f"{_sort_note(item, entry, unsorted_reason)}{_lead(item)}{_citations(entry)}<p class=\"soft\">{_text(section_note)}</p>{actions}"
        f"<details><summary>Everything about this item</summary>{body}{_ledger(item)}</details></article>"
    )


def _failure_banner(failure: Mapping[str, Any]) -> str:
    if failure["kind"] == KIND_POSSIBLE_RENAME:
        return f'<div class="banner note"><strong>Worth a look: this may be a rename.</strong> {_text(failure["summary"])}</div>'
    if failure["kind"] == KIND_STANCE_CHECK:
        return f'<div class="banner plain"><strong>Stance check.</strong> {_text(failure["summary"])}</div>'
    if failure["kind"] == KIND_RULE_BROKEN:
        return f'<div class="banner note"><strong>Rule broken, with a cost.</strong> {_text(failure["summary"])}</div>'
    if failure["kind"] == KIND_MALFUNCTION:
        return f'<div class="banner note"><strong>A fault of its own, across sessions.</strong> {_text(failure["summary"])}</div>'
    return f'<div class="banner warn"><strong>Something failed ({_text(failure["kind"])}).</strong> {_text(failure["summary"])}</div>'


def _top(review: Mapping[str, Any], unsorted_count: int) -> str:
    """What must be seen whichever tab is open: this sits above the tabs."""
    parts = []
    overdue = review["weeks_overdue"]
    if overdue:
        parts.append(f'<div class="banner warn"><strong>This review is {_text(overdue)} week{"" if overdue == 1 else "s"} overdue.</strong> Older items wait below, marked as carried forward.</div>')
    else:
        parts.append('<div class="banner plain">Weeks overdue: 0.</div>')
    parts.extend(_failure_banner(failure) for failure in review["failures"] if failure["kind"] not in NOTICE_KINDS)
    if unsorted_count:
        parts.append(f'<div class="banner note"><strong>{_text(unsorted_count)} item{"" if unsorted_count == 1 else "s"} not sorted.</strong> They wait under Unsorted, each with the reason.</div>')
    if not review["apply_enabled"]:
        parts.append('<div class="banner note"><strong>This was a trial run.</strong> No memory was changed. Memory items show what would have applied.</div>')
    coverage = review["coverage"]
    if coverage:
        parts.append(
            f'<p class="soft">Covers {_text(coverage["sessions"])} sessions and {_text(coverage["notes"])} notes, '
            f'from {_text(str(coverage["first"])[:10])} to {_text(str(coverage["last"])[:10])}.</p>'
        )
    parts.append(
        '<div class="banner plain"><strong>How to use this page.</strong> Pick a choice on the items you want to settle, then press Send at the bottom. '
        "Or type in the terminal that opened with it, in plain words, using the numbers below. For example: <code>undo 1, approve 2, why 3</code>. "
        "This page cannot change anything by itself: the session carries out each choice and checks it first. "
        "Approving a hook, a global rule, a plugin or an MCP server, or editing the global CLAUDE.md, will be asked in the session, on the exact change. "
        "An edit from a monthly finding is shown there before it is made. "
        "Reload to see what you decided. If the session says the numbers changed, reload this page and check the page version above before you go on.</div>"
    )
    return "".join(parts)


def _panel(tab: str, label: str, body: str, has_bulk: bool) -> str:
    bulk = ""
    if has_bulk:
        bulk = (
            f'<div class="bulk"><button type="button" data-fill="{tab}">Approve all recommended in this tab</button>'
            f'<button type="button" data-clear="{tab}">Clear the choices in this tab</button>'
            '<span class="soft">This only fills in the choices, where you have made none. You can change any of them, and nothing is sent until you press Send.</span></div>'
        )
    return f'<section class="panel" id="panel-{tab}" data-panel="{tab}" role="tabpanel"><h2>{_text(label)}</h2>{bulk}{body}</section>'


def _tab_button(tab: str, label: str, count_text: str, alarm: bool) -> str:
    style = ' class="alarm"' if alarm else ""
    return f'<button type="button" role="tab" data-tab="{tab}"{style}>{_text(label)} ({_text(count_text)})</button>'


def _failures_panel_body(review: Mapping[str, Any]) -> str:
    banners = "".join(_failure_banner(failure) for failure in review["failures"])
    if not banners:
        banners = '<p class="soft">Nothing failed, and there is nothing to note.</p>'
    return f"{banners}{_held(review)}{_rejected(review)}{_failures_ranked(review)}{_before_after(review)}"


def _server_notices(send: SendState) -> str:
    closed = (
        '<div class="banner warn" id="server-closed" hidden><strong>The local server has closed, so Send is off.</strong> '
        '<span id="closed-reason"></span> '
        "What you typed in the terminal still works, and the choices on this page are listed below for you to copy. "
        f"To reopen: click the desktop shortcut <em>{_text(SHORTCUT_NAME)}</em>, or run <code>{_text(REOPEN_COMMAND)}</code>. It opens a new address.</div>"
        '<div class="banner warn" id="reload-notice" hidden><strong>The review has changed since this page was loaded, so the numbers here may mean other items.</strong> '
        "Reload this page before you send anything.</div>"
    )
    if send.served:
        return closed
    return f'<div class="banner note"><strong>Send is off.</strong> {_text(send.reason)} Tabs and choices work, and typing in the terminal works.</div>{closed}'


def _send_bar(send: SendState) -> str:
    limit = f' maxlength="{_text(send.max_page_note_chars)}"' if send.max_page_note_chars else ""
    return (
        '<div class="sendbar" id="send-bar">'
        f'<details><summary>A note about the whole page (optional)</summary><textarea id="page-note" rows="2"{limit}></textarea></details>'
        '<p class="soft" id="send-count"></p><p class="soft" id="send-asked"></p>'
        '<button type="button" id="send-button" disabled>Send</button> <span id="send-status" class="soft"></span>'
        '<details id="typed-details"><summary>The same choices, to type in the session</summary><textarea id="typed-form" rows="2" readonly></textarea></details>'
        "</div>"
    )


def _held(review: Mapping[str, Any]) -> str:
    if not review["held"]:
        return ""
    rows = []
    for held in review["held"]:
        reason = held["status"].partition(":")[2].replace("_", " ")
        rows.append(
            f"<article><h3>{_text(held['title'])}</h3>{_para(_KIND_LABEL[held['kind']])}"
            f"{_field('What it would be', _para(held['what']))}{_field('Why it is not offered yet', _para(reason))}"
            f"{_research(held['research'])}{_evidence(held['evidence'])}</article>"
        )
    return "<h2>Held back</h2><p>Not ready to offer, and no number. A later pass offers it if it comes up enough.</p>" + "".join(rows)


def _rejected(review: Mapping[str, Any]) -> str:
    if not review["rejected"]:
        return ""
    rows = "".join(
        f"<tr><td>{_text(item['subject'])}</td><td>{_text(item['claim'])}</td>"
        f"<td>{_text(item['reason'].replace('_', ' '))}. {_text(item['detail'])}</td></tr>"
        for item in review["rejected"]
    )
    return (
        "<h2>Refused by the checks</h2><p>The model suggested these and the scripts refused them, so nothing happened.</p>"
        f"<table><tr><th>About</th><th>What it said</th><th>Why refused</th></tr>{rows}</table>"
    )


def _failures_ranked(review: Mapping[str, Any]) -> str:
    if not review["failures_ranked"]:
        return ""
    rows = "".join(
        f"<tr><td>{_text(item['tool'])}</td><td>{_text(item['commands_lost'])}</td><td>{_text(item['sessions'])}</td><td><code>{_text(item['signature'])}</code></td></tr>"
        for item in review["failures_ranked"]
    )
    return (
        "<h2>Commands that failed most</h2><p>Counted by script, for reading only. The start of an error can be misleading, so read before trusting a row.</p>"
        f"<table><tr><th>Tool</th><th>Commands lost</th><th>Sessions</th><th>Error began</th></tr>{rows}</table>"
    )


def _before_after(review: Mapping[str, Any]) -> str:
    if not review["before_after"]:
        return ""
    rows = "".join(
        f"<tr><td>{_text(item['memory'])}</td><td>{_text(item['week'])}</td><td>{_text(item['before']['for'])} for, {_text(item['before']['against'])} against</td>"
        f"<td>{_text(item['since']['for'])} for, {_text(item['since']['against'])} against</td><td>{'Yes' if item['text_still_in_file'] else 'No'}</td></tr>"
        for item in review["before_after"]
    )
    return (
        "<h2>Earlier changes, since they were made</h2><p>What was recorded about each earlier change. One row per change, with no overall trend.</p>"
        f"<table><tr><th>Memory</th><th>Week applied</th><th>Before</th><th>Since</th><th>Text still there</th></tr>{rows}</table>"
    )


def render_page(
    review: Mapping[str, Any], sorting: Optional[Mapping[str, Any]] = None, sort_problem: Optional[str] = None, send: SendState = STATIC_SEND,
) -> str:
    """The whole page, as text. ``sorting`` is the sort.json of this review, if it has one."""
    entries: Mapping[str, Any] = sorting["items"] if sorting else {}
    if sort_problem:
        unsorted_reason = SORT_NOT_READABLE
    else:
        unsorted_reason = SORT_NO_ENTRY if sorting else SORT_NOT_RUN
    memory = [item for item in review["items"] if item["section"] == SECTION_MEMORY]
    memory_note = (
        "Already applied, stays unless you undo."
        if review["apply_enabled"]
        else "Would apply. Nothing was changed, because this was a trial run."
    )
    if not review["apply_enabled"] and any(item["record"]["outcome"] == OUTCOME_APPLIED for item in memory):
        memory_note = "New items would apply, since this was a trial run. Items with a commit are already applied, and stay unless you undo."
    proposal_note = "Nothing happens unless you approve."
    by_tab: dict[str, list[str]] = {tab: [] for tab, _ in ITEM_TABS}
    for item in review["items"]:
        entry = entries.get(item["key"])
        note = memory_note if item["section"] == SECTION_MEMORY else proposal_note
        by_tab[tab_of(item, entry)].append(_item(item, entry, unsorted_reason, note, send))
    buttons = [_tab_button(tab, label, str(len(by_tab[tab])), False) for tab, label in ITEM_TABS]
    failed = sum(1 for failure in review["failures"] if failure["kind"] not in NOTICE_KINDS)
    noted = len(review["failures"]) - failed
    buttons.append(_tab_button(TAB_FAILURES, "Failures and notices", f"{failed} failed, {noted} to note", failed > 0))
    panels = [
        _panel(tab, label, "".join(by_tab[tab]) if by_tab[tab] else '<p class="soft">Nothing here this week.</p>', tab in _SORTED_TABS.values() and bool(by_tab[tab]))
        for tab, label in ITEM_TABS
    ]
    panels.append(_panel(TAB_FAILURES, "Failures and notices", _failures_panel_body(review), False))
    script_data = _script_data({
        "review_id": review["review_id"], "served": send.served, "off_reason": send.reason,
        "heartbeat_ms": send.heartbeat_ms, "poll_ms": send.poll_ms,
    })
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{content_security_policy(send.served)}">'
        '<meta name="referrer" content="no-referrer"><meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Claude setup review, week {_text(review['week'])}</title><style>{_STYLE}</style></head><body><main>"
        f"<h1>Claude setup review, week {_text(review['week'])}</h1>"
        f'<p class="soft">Built {_text(review["built_at"][:16].replace("T", " "))} UTC from weekly run {_text(review["run_id"])}. '
        f'{_text(len(review["items"]))} numbered items. Page version <code>{_text(review["review_id"])}</code>.</p>'
        f"{_top(review, len(by_tab[TAB_UNSORTED]))}{_server_notices(send)}"
        '<p class="soft no-script">Scripts are off for this page, so all its parts follow one after the other, and choosing here does not work. Typing in the terminal does.</p>'
        f'<div class="tabbar" role="tablist">{"".join(buttons)}</div>'
        f'{"".join(panels)}{_send_bar(send)}'
        f'<script type="application/json" id="page-data">{script_data}</script>'
        f"<script>{_page_script()}</script>"
        "</main></body></html>\n"
    )
