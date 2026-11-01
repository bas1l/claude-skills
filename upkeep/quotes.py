"""Check that quoted evidence is verbatim in the user's own words in a session.

Only entries the sender rules label as the user's own count: pasted text, accepted
suggestions, assistant text and teammate messages all fail. Runs of whitespace compare
as one space, because a model cannot reliably copy line breaks; nothing else is relaxed.
"""
from __future__ import annotations

import re
from typing import Iterable

import transcripts as t

_WHITESPACE_RE = re.compile(r"\s+")


def _normalise_whitespace(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def quote_is_in_user_entries(quote: str, entries: Iterable[t.Entry]) -> bool:
    """True if ``quote`` appears verbatim in one of the user's own entries."""
    wanted = _normalise_whitespace(quote)
    if not wanted:
        raise ValueError("cannot check an empty quote")
    return any(
        wanted in _normalise_whitespace(entry.text) for entry in entries if entry.kind in t.USER_OWN_KINDS
    )


def user_entries_holding(quote: str, entries: Iterable[t.Entry]) -> list[t.Entry]:
    """The user's own entries that hold ``quote`` verbatim."""
    wanted = _normalise_whitespace(quote)
    if not wanted:
        raise ValueError("cannot check an empty quote")
    return [entry for entry in entries if entry.kind in t.USER_OWN_KINDS and wanted in _normalise_whitespace(entry.text)]


def quote_is_reaction_to(quote: str, statement: str, entries: Iterable[t.Entry]) -> bool:
    """True if ``quote`` is in a user entry whose preceding assistant text holds ``statement``.

    This is what accepting or relying on a claim means: the user's next reaction to the
    assistant stating it, with no other user message in between.
    """
    wanted_quote = _normalise_whitespace(quote)
    wanted_statement = _normalise_whitespace(statement)
    if not wanted_quote or not wanted_statement:
        raise ValueError("cannot check an empty quote or statement")
    said_since_last_user = ""
    for entry in sorted(entries, key=lambda item: item.timestamp):
        if entry.kind == t.ASSISTANT_TEXT and entry.source == "main":
            said_since_last_user += " " + _normalise_whitespace(entry.text)
        elif entry.kind in t.USER_OWN_KINDS:
            if wanted_quote in _normalise_whitespace(entry.text) and wanted_statement in said_since_last_user:
                return True
            said_since_last_user = ""
    return False
