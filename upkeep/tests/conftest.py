"""Shared helpers. All fixtures are synthetic; no real transcript text belongs here."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import load_config  # noqa: E402

SESSION_ID = "00000000-0000-4000-8000-000000000001"
CWD = os.path.normpath("/work/project")


def stamp(minute: int) -> str:
    return f"2030-01-01T10:{minute:02d}:00.000Z"


_counter = {"n": 0}


def _base(record_type: str, minute: int, **fields: Any) -> dict[str, Any]:
    _counter["n"] += 1
    return {
        "type": record_type,
        "uuid": f"uuid-{_counter['n']}",
        "timestamp": stamp(minute),
        "cwd": CWD,
        "sessionId": SESSION_ID,
        **fields,
    }


def human(text: Any, minute: int = 0, **fields: Any) -> dict[str, Any]:
    return _base("user", minute, origin={"kind": "human"}, promptSource="typed", message={"content": text}, **fields)


def user_no_origin(text: Any, minute: int = 0, **fields: Any) -> dict[str, Any]:
    return _base("user", minute, message={"content": text}, **fields)


def user_with_origin(kind: str, text: str, minute: int = 0, **fields: Any) -> dict[str, Any]:
    return _base("user", minute, origin={"kind": kind}, message={"content": text}, **fields)


def assistant(blocks: list, minute: int = 0, message_id: str = "msg-1", usage: dict | None = None) -> dict[str, Any]:
    return _base(
        "assistant",
        minute,
        message={
            "id": message_id,
            "model": "test-model",
            "usage": usage if usage is not None else {"input_tokens": 1, "output_tokens": 2},
            "content": blocks,
        },
    )


def assistant_text(text: str, minute: int = 0, **fields: Any) -> dict[str, Any]:
    return assistant([{"type": "text", "text": text}], minute, **fields)


def tool_use(tool_id: str, name: str, tool_input: dict, minute: int = 0, **fields: Any) -> dict[str, Any]:
    return assistant([{"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}], minute, **fields)


def tool_result(tool_id: str, text: Any, minute: int = 0, is_error: bool = False, **fields: Any) -> dict[str, Any]:
    block = {"type": "tool_result", "tool_use_id": tool_id, "content": text, "is_error": is_error}
    return _base("user", minute, message={"content": [block]}, **fields)


def attachment(attachment_fields: dict, minute: int = 0) -> dict[str, Any]:
    return _base("attachment", minute, attachment=attachment_fields)


def system(subtype: str, minute: int = 0, **fields: Any) -> dict[str, Any]:
    return _base("system", minute, subtype=subtype, **fields)


def write_jsonl(path: Path, records: Iterable[dict]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    return str(path)


@pytest.fixture
def config():
    return load_config()
