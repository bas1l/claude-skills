"""Check that quoted evidence is verbatim in the user's own words in a session.

Only entries the sender rules label as the user's own count: pasted text, accepted
suggestions, assistant text and teammate messages all fail. An option label the user picked
counts only as a reaction, since the model wrote those words, and never as saying them.

Runs of whitespace compare as one space, because a model cannot reliably copy line breaks;
nothing else is relaxed. A quote must start and end on a word's edge, so that "k" is not found
in "ok" and "short" is not found in "shorter".
"""
from __future__ import annotations

import re
from typing import Iterable

import transcripts as t

_WHITESPACE_RE = re.compile(r"\s+")


def _normalise_whitespace(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def _holds(text: str, wanted: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(wanted)}(?!\w)", text) is not None


def _wanted(quote: str) -> str:
    wanted = _normalise_whitespace(quote)
    if not wanted:
        raise ValueError("cannot check an empty quote")
    return wanted


def user_entries_holding(quote: str, entries: Iterable[t.Entry], accepted: bool = False) -> list[t.Entry]:
    """The user's entries that hold ``quote`` verbatim. ``accepted`` also lets in option labels,
    for a quote of the user accepting something and not of the user saying it."""
    wanted = _wanted(quote)
    kinds = t.USER_REACTION_KINDS if accepted else t.USER_OWN_KINDS
    return [entry for entry in entries if entry.kind in kinds and _holds(_normalise_whitespace(entry.text), wanted)]


def quote_is_in_user_entries(quote: str, entries: Iterable[t.Entry], accepted: bool = False) -> bool:
    """True if ``quote`` appears verbatim in one of the user's entries."""
    return bool(user_entries_holding(quote, entries, accepted))


def quote_is_reaction_to(quote: str, statement: str, entries: Iterable[t.Entry]) -> bool:
    """True if ``quote`` is in a user entry whose preceding assistant text holds ``statement``.

    This is what accepting or relying on a claim means: the user's next reaction to the
    assistant stating it, with no other user message in between. For an option label, what the
    model offered in that question counts as stated too.
    """
    wanted_quote = _normalise_whitespace(quote)
    wanted_statement = _normalise_whitespace(statement)
    if not wanted_quote or not wanted_statement:
        raise ValueError("cannot check an empty quote or statement")
    said_since_last_user = ""
    for entry in sorted(entries, key=lambda item: item.timestamp):
        if entry.kind == t.ASSISTANT_TEXT and entry.source == "main":
            said_since_last_user += " " + _normalise_whitespace(entry.text)
        elif entry.kind in t.USER_REACTION_KINDS:
            offered = f"{said_since_last_user} {_normalise_whitespace(entry.context)} {_normalise_whitespace(entry.text)}" if entry.kind == t.USER_CHOSE_OPTION else said_since_last_user
            if _holds(_normalise_whitespace(entry.text), wanted_quote) and _holds(offered, wanted_statement):
                return True
            said_since_last_user = ""
    return False
