"""Does each file and line a monthly finding cites still hold its quote?

A deterministic look at the files as they are now, made before the sort so that the model and the
page both see it. A finding may be months old by the time it is read. Only a status and a line
number come out: no text of the file reaches the sort or the page from here.

Knows no model, no review and no page. A file is read and compared the way the monthly pass read it
when it accepted the citation: redacted, tags neutralised, runs of whitespace as one space.
"""
from __future__ import annotations

import os
from typing import Any, Mapping, Optional, Sequence

import monthly_inventory
import schemas
from config import SecretsConfig
from memory_store import REDACTED_MARK


def _normal(text: str) -> str:
    return " ".join(text.split())


def _found_line(lines: Sequence[str], quote: str) -> Optional[int]:
    for position, line in enumerate(lines, 1):
        if quote in _normal(line):
            return position
    return None


def _status_of(side: Mapping[str, Any], secrets: SecretsConfig) -> tuple[str, Optional[int]]:
    path = os.path.expanduser(str(side["file"]))
    quote = _normal(str(side["quote"]))
    if not quote:
        return schemas.CITATION_NO_QUOTE, None
    if not os.path.isfile(path):
        return schemas.CITATION_FILE_GONE, None
    try:
        lines = monthly_inventory.read_cited_lines(path, secrets)
    except (OSError, UnicodeDecodeError):
        return schemas.CITATION_UNREADABLE, None
    line = side["line"]
    if isinstance(line, int) and 1 <= line <= len(lines) and quote in _normal(lines[line - 1]):
        return schemas.CITATION_MATCHES, line
    found = _found_line(lines, quote)
    if found is not None:
        return schemas.CITATION_MOVED, found
    # A report redacts again when it is written, so such a quote may not compare with the file at all.
    return (schemas.CITATION_REDACTED if REDACTED_MARK in quote else schemas.CITATION_CHANGED), None


def check_finding_citations(record: Mapping[str, Any], secrets: SecretsConfig) -> list[dict[str, Any]]:
    """One entry per side of a monthly finding. Anything else cites no line, so it has none."""
    if record.get("kind") != schemas.KIND_MONTHLY_FINDING:
        return []
    checked = []
    for side in record["evidence"].get("sides", []):
        status, found = _status_of(side, secrets)
        checked.append({"file": side["file"], "line": side["line"], "status": status, "found_line": found})
    return checked
