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
