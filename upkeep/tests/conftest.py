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


def synthetic_inventory(root: Path) -> dict[str, Any]:
    """An empty inventory under ``root``, as the ``inventory`` section of the config."""
    skills = root / "inventory" / "skills"
    skills.mkdir(parents=True)
    settings = root / "inventory" / "settings.json"
    settings.write_text("{}", encoding="utf-8")
    manifest = root / "inventory" / "manifest.json"
    manifest.write_text('{"plugins": [], "mcpServers": []}', encoding="utf-8")
    user_config = root / "inventory" / "user_config.json"
    user_config.write_text("{}", encoding="utf-8")
    installed = root / "inventory" / "installed_plugins.json"
    installed.write_text('{"version": 2, "plugins": {}}', encoding="utf-8")
    return {
        "skills_dir": str(skills),
        "settings_file": str(settings),
        "optional_settings_files": [],
        "plugins_manifest": str(manifest),
        "user_config": str(user_config),
        "installed_plugins_file": str(installed),
    }


@pytest.fixture
def config():
    return load_config()


def stance_reply(stdin_text: str, refuse: Iterable[str] = (), answers: Any = None) -> str:
    """A reply to the stance check: every stance is kept, except on an item whose name is in ``refuse``
    (a for or against is refused), or in ``answers``, which maps a name to the fields to change. A
    quote is taken to be about the item, unless the answer says otherwise."""
    replies = []
    for line in stdin_text.split("<stances>")[1].split("</stances>")[0].strip().splitlines():
        stance = json.loads(line)
        reply = {
            "id": stance["id"], "verdict": "kept", "stance": stance["stance"], "quote_about_item": bool(stance["user_quote"]),
            "rule_broken": False, "malfunction": False, "reason": "made up for a test",
        }
        if stance["name"] in tuple(refuse) and stance["stance"] != "no_bearing":
            reply.update(verdict="refused", stance="no_bearing", quote_about_item=False)
        reply.update((answers or {}).get(stance["name"], {}))
        replies.append(reply)
    return json.dumps({"verdicts": replies})


def hold_all_stances(notes_dir: str) -> None:
    """Record that every stance in these notes passed the stance check, for a test about something
    else. The check itself has its own tests."""
    import glob

    for path in glob.glob(os.path.join(glob.escape(notes_dir), "*", "*", "chunk-*.json")):
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
        if document["notes_schema_version"] != 2:
            continue
        window = os.path.dirname(path)
        checks_path = os.path.join(window, "stance-checks.json")
        checks: dict[str, Any] = {}
        if os.path.exists(checks_path):
            with open(checks_path, encoding="utf-8") as handle:
                checks = json.load(handle)["checks"]
        for index, note in enumerate(document["notes"]):
            for position, item in enumerate(note["items"]):
                if isinstance(item, dict) and item.get("stance") in ("for", "against", "no_bearing"):
                    checks.setdefault(f"{os.path.basename(path)}#{index}#{position}", {
                        "stance": item["stance"], "final": item["stance"], "verdict": "kept", "quote_about_item": note["endorsement"] == "said",
                        "rule_broken": False, "malfunction": False, "reason": "made up for a test", "item": {"scope": "", "kind": item["kind"], "name": item["name"]}, "what": note["what"], "run_id": "test",
                    })
        with open(checks_path, "w", encoding="utf-8") as handle:
            json.dump({"schema_version": 3, "checks": checks}, handle)
