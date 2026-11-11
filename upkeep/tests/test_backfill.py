"""Backfill on synthetic trees: inventory formats, origin tracing, idempotence."""
from __future__ import annotations

import dataclasses
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from conftest import SESSION_ID, human, synthetic_inventory, tool_result, tool_use, write_jsonl

import backfill
import ledger
import memory_store
import schemas
from config import InventoryConfig

NOW = datetime(2030, 6, 1, 12, 0, tzinfo=timezone.utc)
FOLDER = "project-a"
SCOPE = ledger.project_scope(FOLDER)
OTHER_SESSION = "00000000-0000-4000-8000-000000000002"


@pytest.fixture
def tree(config, tmp_path):
    projects = tmp_path / "projects"
    (projects / FOLDER / "memory").mkdir(parents=True)
    data = tmp_path / "upkeep"
    data.mkdir()
    inventory = synthetic_inventory(tmp_path)
    built = dataclasses.replace(
        config,
        paths=dataclasses.replace(config.paths, projects_dir=str(projects), data_dir=str(data)),
        memory=dataclasses.replace(config.memory, author_name="Test Author", author_email="test@example.invalid"),
        inventory=InventoryConfig(**{**inventory, "optional_settings_files": ()}),
    )
    memory_store.init_upkeep_repo(str(data), built.memory)
    return built


def write_memory(config, name, text):
    path = Path(config.paths.projects_dir) / FOLDER / "memory" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_json(path, document):
    Path(path).write_text(json.dumps(document), encoding="utf-8")


def memory_path_in_call(config, name, style="windows"):
    path = os.path.join(config.paths.projects_dir, FOLDER, "memory", name)
    return path.replace("\\", "/") if style == "forward" else path


def session_file(config, records, session_id=SESSION_ID, folder=FOLDER):
    return write_jsonl(Path(config.paths.projects_dir) / folder / f"{session_id}.jsonl", records)


def ledger_of(config, name, kind="memory", scope=SCOPE):
    return ledger.load_ledger(ledger.ledgers_dir_of(config.paths.data_dir), ledger.ItemId(scope, kind, name))


def by_name(items):
    return {item.id.name: item for item in items}


# Frontmatter


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("---\nname: a\ndescription: plain words\n---\nbody", "plain words"),
        ('---\ndescription: "quoted: words"\n---\n', "quoted: words"),
        ("---\ndescription: 'it''s quoted'\n---\n", "it's quoted"),
        ("---\ndescription: has: a colon in a plain value\n---\n", "has: a colon in a plain value"),
        ("---\ndescription: >\n  folded\n  block\n---\n", "folded block"),
        ("---\ndescription: |-\n  literal block\n---\n", "literal block"),
        ("---\ndescription: first\n  continued\n---\n", "first continued"),
    ],
)
def test_front_matter_values(text, expected):
    assert backfill.read_front_matter(text, "test")[0]["description"] == expected


def test_nested_metadata_is_read():
    front, body = backfill.read_front_matter("---\nmetadata:\n  type: feedback\n  originSessionId: abc\n---\nbody\n", "t")
    assert front["metadata"] == {"type": "feedback", "originSessionId": "abc"}
    assert body == "body"


def test_a_list_value_is_kept_as_lines():
    front, _ = backfill.read_front_matter("---\nallowed:\n  - one\n  - two\n---\n", "t")
    assert front["allowed"] == ["- one", "- two"]


def test_no_front_matter_is_all_body():
    assert backfill.read_front_matter("just text", "t") == ({}, "just text")


@pytest.mark.parametrize(
    "text",
    [
        "---\nname: never closed\n",
        "---\nthis line has no key\n---\n",
        "---\n  indented first: x\n---\n",
        "---\nname: a\nname: b\n---\n",
    ],
)
def test_unreadable_front_matter_raises(text):
    with pytest.raises(backfill.InventoryError):
        backfill.read_front_matter(text, "t")


# Why lines


def test_why_line_paragraph_stops_at_blank_line():
    assert backfill.why_lines("**Why:** first line\nsecond line\n\nother") == ["first line second line"]


def test_why_heading_section_reads_its_first_paragraph():
    assert backfill.why_lines("## Why\n\nthe reason\n\nmore") == ["the reason"]


def test_why_about_something_else_is_not_a_founding_reason():
    assert backfill.why_lines("**Why it matters:** other\n**Why not X:** other\nWhy so?") == []


def test_why_stops_before_how_to_apply():
    assert backfill.why_lines("**Why:** the reason\n**How to apply:** steps") == ["the reason"]


# Inventory


def test_memory_reason_prefers_the_why_line_and_is_unverified(tree):
    write_memory(tree, "m.md", "---\ndescription: what it is\n---\n**Why:** the reason\n")
    founding = by_name(backfill.memory_items(tree))["m"].founding
    assert founding == {"reason": "the reason", "status": schemas.FOUNDING_UNVERIFIED, "source": "why_line"}


def test_memory_reason_uses_the_description_when_there_is_no_why(tree):
    write_memory(tree, "m.md", "---\ndescription: what it is\n---\nbody\n")
    assert by_name(backfill.memory_items(tree))["m"].founding["source"] == "description"


def test_a_memory_with_no_stated_reason_is_marked_and_nothing_is_invented(tree):
    write_memory(tree, "m.md", "body only\n")
    founding = by_name(backfill.memory_items(tree))["m"].founding
    assert founding == {"reason": None, "status": schemas.FOUNDING_NO_REASON, "source": None}


def test_a_for_now_line_is_what_would_make_it_wrong(tree):
    write_memory(tree, "m.md", "---\ndescription: d\n---\nUse this for now, until the data is rebuilt.\nOther.\n")
    limit = by_name(backfill.memory_items(tree))["m"].would_be_wrong
    assert limit == {"status": schemas.LIMIT_STATED, "text": "Use this for now, until the data is rebuilt."}


def test_a_secret_in_a_reason_is_redacted(tree):
    write_memory(tree, "m.md", "**Why:** the key is sk-ant-abcdefghijklmnop\n")
    assert "sk-ant" not in by_name(backfill.memory_items(tree))["m"].founding["reason"]


def test_memory_index_is_not_an_item_and_subfolders_are_named_by_path(tree):
    write_memory(tree, "MEMORY.md", "- index\n")
    write_memory(tree, "sub/m.md", "body\n")
    assert list(by_name(backfill.memory_items(tree))) == ["sub/m"]


def test_a_file_that_is_not_markdown_raises(tree):
    write_memory(tree, "notes.txt", "text")
    with pytest.raises(backfill.InventoryError):
        backfill.memory_items(tree)


def test_a_memory_that_is_not_utf8_raises(tree):
    write_memory(tree, "m.md", "x").write_bytes(b"caf\xe9")
    with pytest.raises(backfill.InventoryError):
        backfill.memory_items(tree)


def test_skills_are_folders_with_a_skill_file(tree):
    root = Path(tree.inventory.skills_dir)
    (root / "real").mkdir()
    (root / "real" / "SKILL.md").write_text("---\nname: real\ndescription: does things\n---\n", encoding="utf-8")
    (root / "no-skill-file").mkdir()
    (root / "loose.md").write_text("x", encoding="utf-8")
    items = by_name(backfill.skill_items(tree))
    assert list(items) == ["real"]
    assert items["real"].founding["source"] == "description"


def test_hooks_are_one_item_per_script_across_events(tree):
    def hook(command, **fields):
        return {"type": "command", "command": command, **fields}

    write_json(tree.inventory.settings_file, {"hooks": {
        "Stop": [{"hooks": [hook('"python.exe" "C:/x/y/clock.py" reply')]}],
        "UserPromptSubmit": [{"hooks": [hook('"python.exe" "C:/x/y/clock.py" prompt')]}],
        "SessionStart": [
            {"hooks": [hook("python.exe", args=["C:/x/colocate.py"])]},
            {"matcher": "x", "hooks": [hook("powershell.exe -File C:\\x\\start.ps1")]},
        ],
        "Notification": [{"hooks": [hook('powershell.exe -Command "play sound.wav"', statusMessage="Notification sound")]}],
    }})
    items = by_name(backfill.hook_items(tree))
    assert sorted(items) == ["clock", "colocate", "notification-sound", "start"]
    assert items["clock"].founding["status"] == schemas.FOUNDING_NO_REASON


@pytest.mark.parametrize(
    "hooks",
    [
        [],
        {"Stop": {}},
        {"Stop": [{"nothooks": []}]},
        {"Stop": [{"hooks": [{"type": "prompt", "prompt": "x"}]}]},
        {"Stop": [{"hooks": [{"type": "command", "command": "inline with no name"}]}]},
        {"Stop": [{"hooks": [{"type": "command", "command": "a.py b.py"}]}]},
    ],
)
def test_a_hook_format_it_cannot_read_raises(tree, hooks):
    write_json(tree.inventory.settings_file, {"hooks": hooks})
    with pytest.raises(backfill.InventoryError):
        backfill.hook_items(tree)


def test_servers_and_plugins_are_the_union_of_their_sources(tree):
    write_json(tree.inventory.plugins_manifest, {
        "plugins": [{"id": "a@m", "enabled": True}],
        "mcpServers": [{"name": "listed", "scope": "user", "config": {}}],
    })
    write_json(tree.inventory.settings_file, {"enabledPlugins": {"a@m": True, "b@m": False}, "mcpServers": {"in-settings": {}}})
    write_json(tree.inventory.user_config, {"mcpServers": {"in-user": {}}, "projects": {"p": {"mcpServers": {"in-project": {}}}}})
    assert sorted(by_name(backfill.mcp_items(tree))) == ["in-project", "in-settings", "in-user", "listed"]
    assert sorted(by_name(backfill.plugin_items(tree))) == ["a@m", "b@m"]


@pytest.mark.parametrize("manifest", [{}, {"plugins": [], "mcpServers": {}}, {"plugins": [{}], "mcpServers": []}])
def test_a_manifest_it_cannot_read_raises(tree, manifest):
    write_json(tree.inventory.plugins_manifest, manifest)
    with pytest.raises(backfill.InventoryError):
        backfill.plugin_items(tree)
        backfill.mcp_items(tree)


def test_a_missing_settings_file_raises(tree):
    os.remove(tree.inventory.settings_file)
    with pytest.raises(FileNotFoundError):
        backfill.hook_items(tree)


# Origin


def write_call(config, tool, call_id, name="m.md", minute=1, is_error=False, result=True, style="windows"):
    records = [tool_use(call_id, tool, {"file_path": memory_path_in_call(config, name, style)}, minute)]
    if result:
        records.append(tool_result(call_id, "ok", minute, is_error=is_error))
    return records


def test_origin_is_the_earliest_successful_write_across_sessions(tree):
    session_file(tree, write_call(tree, "Edit", "t2", minute=20))
    session_file(tree, write_call(tree, "Write", "t1", minute=5), session_id=OTHER_SESSION)
    call = backfill.scan_transcripts(tree).earliest[("project-a", "m.md")]
    assert (call.session, call.tool, call.project_folder) == (OTHER_SESSION, "Write", FOLDER)


def test_a_failed_or_unanswered_write_is_not_an_origin(tree):
    session_file(tree, [
        *write_call(tree, "Write", "t1", is_error=True),
        *write_call(tree, "Write", "t2", name="n.md", result=False),
    ])
    scan = backfill.scan_transcripts(tree)
    assert scan.earliest == {}
    assert (scan.calls_failed, scan.calls_without_result) == (1, 1)


def test_forward_slash_and_case_variants_match(tree):
    path = memory_path_in_call(tree, "M.md", "forward").replace(FOLDER, FOLDER.upper())
    session_file(tree, [tool_use("t1", "Write", {"file_path": path}, 1), tool_result("t1", "ok", 1)])
    assert ("project-a", "m.md") in backfill.scan_transcripts(tree).earliest


def test_other_tools_and_other_paths_are_ignored(tree):
    session_file(tree, [
        tool_use("t1", "Read", {"file_path": memory_path_in_call(tree, "m.md")}, 1),
        tool_result("t1", "ok", 1),
        tool_use("t2", "Write", {"file_path": "/work/memory/m.md"}, 1),
        tool_result("t2", "ok", 1),
    ])
    assert backfill.scan_transcripts(tree).earliest == {}


def test_a_subagent_write_counts_for_its_session(tree):
    session_file(tree, [human("hello")])
    write_jsonl(
        Path(tree.paths.projects_dir) / FOLDER / SESSION_ID / "subagents" / "agent-1.jsonl",
        write_call(tree, "Write", "t1"),
    )
    assert backfill.scan_transcripts(tree).earliest[("project-a", "m.md")].session == SESSION_ID


def test_a_bookkeeping_copy_of_a_call_is_not_a_call(tree):
    call, result = write_call(tree, "Write", "t1")
    copy = {"type": "api-request-blob", "sessionId": SESSION_ID, "message": call["message"]}
    session_file(tree, [copy, result])
    assert backfill.scan_transcripts(tree).earliest == {}


def test_an_unknown_record_type_on_a_candidate_line_raises(tree):
    call, _ = write_call(tree, "Write", "t1")
    session_file(tree, [{**call, "type": "alien"}])
    with pytest.raises(backfill.transcripts.TranscriptFormatError):
        backfill.scan_transcripts(tree)


def test_a_partial_final_line_is_left_alone(tree):
    path = session_file(tree, write_call(tree, "Write", "t1"))
    with open(path, "a", encoding="utf-8") as handle:
        handle.write('{"type": "assistant", "tool_use" "file_path" memory')
    assert ("project-a", "m.md") in backfill.scan_transcripts(tree).earliest


def test_an_unparsable_candidate_line_raises(tree):
    path = session_file(tree, [human("hello")])
    with open(path, "a", encoding="utf-8") as handle:
        handle.write('{"bad": "tool_use" "file_path" memory\n')
    with pytest.raises(backfill.transcripts.TranscriptFormatError):
        backfill.scan_transcripts(tree)


# Whole run


def test_run_traces_marks_and_is_idempotent(tree):
    write_memory(tree, "m.md", "---\nmetadata:\n  originSessionId: some-stamp\n---\n**Why:** reason\n")
    write_memory(tree, "edited.md", "body\n")
    write_memory(tree, "lost.md", "---\ndescription: d\n---\n")
    session_file(tree, [*write_call(tree, "Write", "t1"), *write_call(tree, "Edit", "t2", name="edited.md")])
    first = backfill.run_backfill(tree, "r1", NOW)
    assert first["ledgers_by_kind"] == {"memory": 3}
    assert (first["memories_traced"], first["memories_traced_to_creating_call"], first["memories_untraced"]) == (2, 1, 1)
    assert first["founding_status"] == {"unverified": 2, "no_stated_reason": 1}
    assert first["founding_source"] == {"why_line": 1, "None": 1, "description": 1}
    assert first["data_commit"] == memory_store.RESULT_COMMITTED
    assert (first["traced_with_frontmatter_stamp"], first["frontmatter_stamp_agrees"]) == (1, 0)

    traced = ledger_of(tree, "m")
    assert traced["origin"]["session"] == SESSION_ID
    assert traced["origin"]["creating_call_found"] is True
    assert ledger_of(tree, "edited")["origin"]["creating_call_found"] is False
    assert ledger_of(tree, "lost")["origin"]["status"] == schemas.ORIGIN_UNTRACED

    second = backfill.run_backfill(tree, "r2", NOW)
    assert second["data_commit"] == memory_store.RESULT_UNCHANGED
    assert second["sync"][ledger.OUTCOME_UNCHANGED] == 3
    log = subprocess.run(
        ["git", "-C", tree.paths.data_dir, "status", "--short"], capture_output=True, encoding="utf-8", check=True
    )
    assert log.stdout == ""


def test_an_edited_memory_keeps_its_founding_reason_and_a_new_origin_fills_in(tree):
    path = write_memory(tree, "m.md", "**Why:** first reason\n")
    backfill.run_backfill(tree, "r1", NOW)
    assert ledger_of(tree, "m")["origin"]["status"] == schemas.ORIGIN_UNTRACED
    path.write_text("**Why:** a later reason\n", encoding="utf-8")
    session_file(tree, write_call(tree, "Write", "t1"))
    result = backfill.run_backfill(tree, "r2", NOW)
    assert result["sync"][ledger.OUTCOME_ORIGIN_FILLED] == 1
    document = ledger_of(tree, "m")
    assert document["founding"]["reason"] == "first reason"
    assert document["origin"]["status"] == schemas.ORIGIN_TRACED


def test_an_item_gone_from_the_inventory_keeps_its_ledger(tree):
    path = write_memory(tree, "m.md", "body\n")
    backfill.run_backfill(tree, "r1", NOW)
    path.unlink()
    result = backfill.run_backfill(tree, "r2", NOW)
    assert result["absent_from_inventory"] == 1
    assert ledger_of(tree, "m")["identity"]["name"] == "m"


def test_a_format_problem_stops_before_anything_is_written(tree):
    write_memory(tree, "bad.md", "---\nnever closed\n")
    with pytest.raises(backfill.InventoryError):
        backfill.run_backfill(tree, "r1", NOW)
    assert not list(Path(tree.paths.data_dir, "ledgers").rglob("*.json"))


def test_sync_alone_never_reads_a_transcript(tree, monkeypatch):
    write_memory(tree, "m.md", "body\n")
    monkeypatch.setattr(backfill, "scan_transcripts", lambda _: pytest.fail("scanned"))
    assert backfill.sync_items(tree, NOW)[ledger.OUTCOME_CREATED] == 1
