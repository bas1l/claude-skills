"""Give every existing item a ledger, by script, with no model call.

The inventory reads how items are actually stored, and raises on a shape it does not know:

    memory  <projects>/<folder>/memory/**/*.md, except the MEMORY.md index
    skill   <skills>/<name>/SKILL.md
    hook    the ``hooks`` of the settings files, one item per script across its events
    mcp     the manifest, the settings files and the user config, including its projects
    plugin  the manifest and ``enabledPlugins`` in the settings files

The founding reason comes from a memory's "Why" lines, otherwise from the description, and is
marked unverified: nothing here shows the user gave it. An item with neither is marked as having
no stated reason. A description often says what an item is and not why, which is why the
source is recorded with the reason.

The origin of a memory comes only from successful ``Write`` or ``Edit`` calls found in
transcripts, whose result is present and not an error. The earliest one counts. If it is an
``Edit``, the call that created the file is in no surviving transcript. A frontmatter session
stamp is compared with it for the report, and is never used as the origin.

The transcript scan reads one file at a time as a stream of lines. A line is parsed only if
it could hold a matching call or its result. Rerunning changes nothing unless there is a new
item or an origin newly found. An item gone from the inventory keeps its ledger, and is
counted in the report.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

import ledger
import memory_store
import render
import schemas
import sessions
import transcripts
from config import Config, load_config

MEMORY_INDEX = "MEMORY.md"
MARKDOWN_SUFFIX = ".md"
SKILL_FILE = "SKILL.md"
CREATING_TOOL = "Write"
SOURCE_WHY = "why_line"
SOURCE_DESCRIPTION = "description"

_WHY_LINE_RE = re.compile(r"^\*\*Why:?\*\*:?\s*(.*)$")
_WHY_HEADING_RE = re.compile(r"^#{1,6}\s+Why\s*:?\s*$")
_KEY_RE = re.compile(r"^([A-Za-z_][\w-]*):(?:\s+(.*))?$")
_BLOCK_RE = re.compile(r"^[|>][+-]?$")
_SCRIPT_RE = re.compile(r"[^\s\"']+\.(?:py|ps1|sh|js|mjs|cmd|bat)(?=$|[\s\"'])", re.I)
_SLUG_RE = re.compile(r"[^a-z0-9]+")

_BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
_NICE_BELOW_NORMAL = 5


class InventoryError(ValueError):
    """An item is stored in a shape this script cannot read."""


@dataclass(frozen=True)
class Item:
    id: ledger.ItemId
    founding: Mapping[str, Any]
    would_be_wrong: Mapping[str, Any]
    session_stamp: Optional[str] = None


@dataclass(frozen=True)
class WriteCall:
    """One successful write to a memory file."""

    at: datetime
    session: str
    project_folder: str
    tool: str


@dataclass
class ScanResult:
    earliest: dict[tuple[str, str], WriteCall] = field(default_factory=dict)
    files: int = 0
    bytes_read: int = 0
    calls_confirmed: int = 0
    calls_failed: int = 0
    calls_without_result: int = 0


def _unquote(value: str) -> str:
    """The text of a value. One that merely starts with a quote mark is plain text, as real
    files have it, such as ``"Skin location" means where...``; the whole text is kept."""
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'" and "'" not in value[1:-1].replace("''", ""):
        return value[1:-1].replace("''", "'")
    return value


def read_front_matter(text: str, where: str) -> tuple[dict[str, Any], str]:
    """Split ``---`` frontmatter from the body.

    This reads a narrow line grammar and is not a YAML parser, because the runtime uses the
    standard library only and real files hold values YAML rejects, such as a plain value
    with a colon. It knows top-level ``key: value``, quoted values, ``|`` and ``>`` blocks,
    indented continuation lines, and one level of nested ``key: value``. Any other line raises.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    try:
        end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration:
        raise InventoryError(f"{where}: frontmatter is never closed") from None

    values: dict[str, Any] = {}
    key: Optional[str] = None
    indented: list[str] = []

    def finish() -> None:
        if key is None or not indented:
            return
        head = values[key]
        if head is None:
            pairs = [_KEY_RE.match(line) for line in indented]
            if all(pairs):
                values[key] = {pair.group(1): _unquote((pair.group(2) or "").strip()) for pair in pairs}
            else:
                values[key] = list(indented)
        elif _BLOCK_RE.match(head):
            values[key] = " ".join(indented)
        else:
            values[key] = " ".join([head, *indented])

    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] in " \t":
            if key is None:
                raise InventoryError(f"{where}: indented frontmatter line before any key")
            indented.append(line.strip())
            continue
        match = _KEY_RE.match(line)
        if match is None:
            raise InventoryError(f"{where}: unreadable frontmatter line: {line[:60]!r}")
        finish()
        key = match.group(1)
        if key in values:
            raise InventoryError(f"{where}: frontmatter key {key!r} appears twice")
        raw = (match.group(2) or "").strip()
        values[key] = raw if raw else None
        indented = []
    finish()
    for name, value in values.items():
        if isinstance(value, str) and not _BLOCK_RE.match(value):
            values[name] = _unquote(value)
    return values, "\n".join(lines[end + 1:])


def why_lines(body: str) -> list[str]:
    """Stated reasons in a memory's body: ``**Why:** ...`` paragraphs and ``## Why`` sections."""
    lines = body.splitlines()
    found: list[str] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        marker = _WHY_LINE_RE.match(stripped)
        if marker is None and not _WHY_HEADING_RE.match(stripped):
            continue
        paragraph = [marker.group(1)] if marker is not None and marker.group(1) else []
        for following in lines[index + 1:]:
            text = following.strip()
            if not text:
                if paragraph:
                    break
                continue
            if text.startswith(("#", "**Why")) or text.startswith("**How"):
                break
            paragraph.append(text)
        if paragraph:
            found.append(" ".join(paragraph))
    return found


def _no_reason() -> dict[str, Any]:
    return {"reason": None, "status": schemas.FOUNDING_NO_REASON, "source": None}


def _founding(reason: Optional[str], source: str, config: Config) -> dict[str, Any]:
    if not reason or not reason.strip():
        return _no_reason()
    return {
        "reason": render.redact_counted(reason.strip(), config.secrets)[0],
        "status": schemas.FOUNDING_UNVERIFIED,
        "source": source,
    }


def _not_stated() -> dict[str, Any]:
    return {"status": schemas.LIMIT_NOT_STATED, "text": None}


def _limits_stated(texts: Sequence[str], config: Config) -> dict[str, Any]:
    """Lines where the item itself limits its own validity, such as "for now"."""
    found = []
    for text in texts:
        for line in text.splitlines():
            if any(re.search(pattern, line) for pattern in config.ledger.stated_limit_patterns):
                found.append(line.strip())
    if not found:
        return _not_stated()
    return {"status": schemas.LIMIT_STATED, "text": render.redact_counted(" | ".join(found), config.secrets)[0]}


def _no_origin(status: str) -> dict[str, Any]:
    return {"status": status, "session": None, "project_folder": None, "at": None, "tool": None, "creating_call_found": None}


def _description(front: Mapping[str, Any], where: str) -> Optional[str]:
    value = front.get("description")
    if value is None or isinstance(value, str):
        return value
    raise InventoryError(f"{where}: description is not text")


def _read_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except UnicodeDecodeError as error:
        raise InventoryError(f"{path}: not UTF-8: {error}") from error


def _read_json(path: str) -> Mapping[str, Any]:
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, dict):
        raise InventoryError(f"{path}: expected a JSON object")
    return document


def _memory_stamp(front: Mapping[str, Any]) -> Optional[str]:
    nested = front.get("metadata")
    if isinstance(nested, dict) and nested.get("originSessionId"):
        return nested["originSessionId"]
    return front.get("originSessionId")


def memory_items(config: Config) -> list[Item]:
    items = []
    for folder in memory_store.memory_folders(config.paths.projects_dir):
        project = os.path.basename(os.path.dirname(folder))
        for relative in memory_store.list_files(folder):
            if relative == MEMORY_INDEX:
                continue
            path = os.path.join(folder, relative)
            if not relative.endswith(MARKDOWN_SUFFIX):
                raise InventoryError(f"{path}: a memory folder holds a file that is not Markdown")
            text = _read_text(path)
            front, body = read_front_matter(text, path)
            description = _description(front, path)
            reasons = why_lines(body)
            founding = (
                _founding("\n".join(reasons), SOURCE_WHY, config)
                if reasons
                else _founding(description, SOURCE_DESCRIPTION, config)
            )
            name = relative[: -len(MARKDOWN_SUFFIX)].replace(os.sep, "/")
            items.append(Item(
                id=ledger.ItemId(ledger.project_scope(project), ledger.KIND_MEMORY, name),
                founding=founding,
                would_be_wrong=_limits_stated([description or "", body], config),
                session_stamp=_memory_stamp(front),
            ))
    return items


def skill_items(config: Config) -> list[Item]:
    root = config.inventory.skills_dir
    if not os.path.isdir(root):
        raise FileNotFoundError(f"skills folder not found: {root}")
    items = []
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name, SKILL_FILE)
        if not os.path.isfile(path):
            continue
        front, _ = read_front_matter(_read_text(path), path)
        description = _description(front, path)
        items.append(Item(
            id=ledger.ItemId(ledger.SCOPE_GLOBAL, "skill", name),
            founding=_founding(description, SOURCE_DESCRIPTION, config),
            would_be_wrong=_limits_stated([description or ""], config),
        ))
    return items


def _settings_documents(config: Config) -> list[tuple[str, Mapping[str, Any]]]:
    paths = [config.inventory.settings_file]
    paths.extend(path for path in config.inventory.optional_settings_files if os.path.exists(path))
    return [(path, _read_json(path)) for path in paths]


def _hook_name(hook: Mapping[str, Any], where: str) -> str:
    """A hook is named after its script, so the same script on two events is one item.
    An inline command has no script, so its status message names it."""
    if hook.get("type") != "command" or not isinstance(hook.get("command"), str):
        raise InventoryError(f"{where}: a hook that is not a command: {hook.get('type')!r}")
    arguments = hook.get("args", [])
    if not isinstance(arguments, list):
        raise InventoryError(f"{where}: hook args must be a list")
    scripts = set()
    for text in (hook["command"], *arguments):
        scripts.update(os.path.splitext(os.path.basename(found.replace("\\", "/")))[0] for found in _SCRIPT_RE.findall(text))
    if len(scripts) > 1:
        raise InventoryError(f"{where}: a hook names several scripts: {sorted(scripts)}")
    if scripts:
        return scripts.pop()
    message = hook.get("statusMessage")
    if not isinstance(message, str) or not message.strip():
        raise InventoryError(f"{where}: an inline hook with no status message to name it")
    return _SLUG_RE.sub("-", message.lower()).strip("-")


def hook_items(config: Config) -> list[Item]:
    names = set()
    for path, settings in _settings_documents(config):
        hooks = settings.get("hooks", {})
        if not isinstance(hooks, dict):
            raise InventoryError(f"{path}: hooks must be an object")
        for event, groups in hooks.items():
            where = f"{path} hooks.{event}"
            if not isinstance(groups, list):
                raise InventoryError(f"{where}: must be a list")
            for group in groups:
                if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                    raise InventoryError(f"{where}: a group must hold a list named hooks")
                names.update(_hook_name(hook, where) for hook in group["hooks"])
    return [_item_with_no_reason("hook", name) for name in sorted(names)]


def _item_with_no_reason(kind: str, name: str) -> Item:
    return Item(id=ledger.ItemId(ledger.SCOPE_GLOBAL, kind, name), founding=_no_reason(), would_be_wrong=_not_stated())


def _server_names(document: Mapping[str, Any], where: str) -> set[str]:
    servers = document.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise InventoryError(f"{where}: mcpServers must be an object")
    return set(servers)


def _manifest(config: Config) -> tuple[list[Any], list[Any]]:
    path = config.inventory.plugins_manifest
    manifest = _read_json(path)
    for key in ("plugins", "mcpServers"):
        if not isinstance(manifest.get(key), list):
            raise InventoryError(f"{path}: {key} must be a list")
    return manifest["plugins"], manifest["mcpServers"]


def mcp_items(config: Config) -> list[Item]:
    _, listed = _manifest(config)
    names = set()
    for server in listed:
        if not isinstance(server, dict) or not isinstance(server.get("name"), str):
            raise InventoryError(f"{config.inventory.plugins_manifest}: a server with no name")
        names.add(server["name"])
    for path, settings in _settings_documents(config):
        names |= _server_names(settings, path)
    user_path = config.inventory.user_config
    user_config = _read_json(user_path)
    names |= _server_names(user_config, user_path)
    projects = user_config.get("projects", {})
    if not isinstance(projects, dict):
        raise InventoryError(f"{user_path}: projects must be an object")
    for project in projects.values():
        names |= _server_names(project, user_path)
    return [_item_with_no_reason("mcp", name) for name in sorted(names)]


def plugin_items(config: Config) -> list[Item]:
    listed, _ = _manifest(config)
    names = set()
    for plugin in listed:
        if not isinstance(plugin, dict) or not isinstance(plugin.get("id"), str):
            raise InventoryError(f"{config.inventory.plugins_manifest}: a plugin with no id")
        names.add(plugin["id"])
    for path, settings in _settings_documents(config):
        enabled = settings.get("enabledPlugins", {})
        if not isinstance(enabled, dict):
            raise InventoryError(f"{path}: enabledPlugins must be an object")
        names |= set(enabled)
    return [_item_with_no_reason(ledger.KIND_PLUGIN, name) for name in sorted(names)]


def inventory(config: Config) -> list[Item]:
    """Everything that gets a ledger."""
    items = memory_items(config) + skill_items(config) + hook_items(config) + mcp_items(config) + plugin_items(config)
    seen = set()
    for item in items:
        key = tuple(part.casefold() for part in (item.id.scope, item.id.kind, item.id.name))
        if key in seen:
            raise InventoryError(f"two items share one identity on a case-blind file system: {item.id}")
        seen.add(key)
    return items


def _memory_target(file_path: Any, projects_name: str) -> Optional[tuple[str, str]]:
    if not isinstance(file_path, str):
        raise transcripts.TranscriptFormatError(f"file_path is not text: {file_path!r}")
    normal = file_path.replace("\\", "/")
    marker = f"/{projects_name}/".casefold()
    position = normal.casefold().rfind(marker)
    if position < 0:
        return None
    parts = normal[position + len(marker):].split("/", 2)
    if len(parts) != 3 or parts[1].casefold() != "memory":
        return None
    return parts[0], parts[2]


def _target_key(project: str, relative: str) -> tuple[str, str]:
    return project.casefold(), relative.casefold()


def _scan_file(
    path: str,
    session_id: str,
    project_folder: str,
    tools: frozenset[str],
    projects_name: str,
    confirmed: dict[str, tuple[tuple[str, str], WriteCall]],
    failed: set[str],
    unanswered: dict[str, tuple[tuple[str, str], WriteCall]],
) -> int:
    """Find write calls to memory files in one transcript file. Returns the bytes read."""
    pending: dict[bytes, str] = {}
    size = 0
    with open(path, "rb") as handle:
        for line_number, line in enumerate(handle, 1):
            size += len(line)
            if not line.endswith(b"\n"):
                break
            could_be_call = b'"tool_use"' in line and b'"file_path"' in line and b"memory" in line
            could_be_result = bool(pending) and any(key in line for key in pending)
            if not could_be_call and not could_be_result:
                continue
            where = f"{path}:{line_number}"
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise transcripts.TranscriptFormatError(f"{where}: invalid JSON: {error}") from error
            if not isinstance(record, dict):
                raise transcripts.TranscriptFormatError(f"{where}: a record that is not an object")
            record_type = record.get("type")
            if record_type not in transcripts.CONVERSATION_RECORD_TYPES:
                # Bookkeeping records can repeat request content, so they are not evidence of a call.
                if record_type not in transcripts.BOOKKEEPING_RECORD_TYPES:
                    raise transcripts.TranscriptFormatError(f"{where}: unknown record type {record_type!r}")
                continue
            message = record.get("message")
            blocks = message.get("content") if isinstance(message, dict) else None
            if not isinstance(blocks, list):
                continue
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use" and block.get("name") in tools:
                    target = _memory_target(block["input"].get("file_path"), projects_name)
                    if target is None:
                        continue
                    if "timestamp" not in record:
                        raise transcripts.TranscriptFormatError(f"{where}: a tool call with no timestamp")
                    call = WriteCall(
                        at=transcripts.parse_timestamp(record["timestamp"]),
                        session=session_id,
                        project_folder=project_folder,
                        tool=block["name"],
                    )
                    unanswered[block["id"]] = (_target_key(*target), call)
                    pending[block["id"].encode("utf-8")] = block["id"]
                elif block.get("type") == "tool_result" and block.get("tool_use_id") in unanswered:
                    call_id = block["tool_use_id"]
                    if block.get("is_error") is True:
                        failed.add(call_id)
                        del unanswered[call_id]
                    else:
                        confirmed[call_id] = unanswered.pop(call_id)
                    pending.pop(call_id.encode("utf-8"), None)
    return size


def scan_transcripts(config: Config) -> ScanResult:
    """The earliest successful write to each memory file, across all transcripts."""
    tools = frozenset(config.ledger.origin_tools)
    projects_name = os.path.basename(config.paths.projects_dir)
    result = ScanResult()
    for files in sessions.discover_sessions(config.paths.projects_dir):
        confirmed: dict[str, tuple[tuple[str, str], WriteCall]] = {}
        failed: set[str] = set()
        unanswered: dict[str, tuple[tuple[str, str], WriteCall]] = {}
        for path in (files.main_path, *files.subagent_paths):
            result.bytes_read += _scan_file(
                path, files.session_id, files.project_folder, tools, projects_name, confirmed, failed, unanswered
            )
            result.files += 1
        result.calls_confirmed += len(confirmed)
        result.calls_failed += len(failed)
        result.calls_without_result += len(set(unanswered) - set(confirmed) - failed)
        for key, call in confirmed.values():
            known = result.earliest.get(key)
            if known is None or call.at < known.at:
                result.earliest[key] = call
    return result


def _origin_of(item: Item, scan: Optional[ScanResult]) -> dict[str, Any]:
    if item.id.kind != ledger.KIND_MEMORY:
        return _no_origin(schemas.ORIGIN_NOT_APPLICABLE)
    call = scan.earliest.get(_key_of_memory(item.id)) if scan is not None else None
    if call is None:
        return _no_origin(schemas.ORIGIN_UNTRACED)
    return {
        "status": schemas.ORIGIN_TRACED,
        "session": call.session,
        "project_folder": call.project_folder,
        "at": call.at.isoformat(),
        "tool": call.tool,
        "creating_call_found": call.tool == CREATING_TOOL,
    }


def _key_of_memory(item: ledger.ItemId) -> tuple[str, str]:
    folder = item.scope[len(ledger.SCOPE_PROJECT_PREFIX):]
    return _target_key(folder, f"{item.name}{MARKDOWN_SUFFIX}")


def sync_items(config: Config, as_of: datetime, scan: Optional[ScanResult] = None) -> dict[str, Any]:
    """Create the ledger of each new item. Without a scan, a new memory's origin stays untraced."""
    ledgers_dir = ledger.ledgers_dir_of(config.paths.data_dir)
    items = inventory(config)
    outcomes = {ledger.OUTCOME_CREATED: 0, ledger.OUTCOME_ORIGIN_FILLED: 0, ledger.OUTCOME_UNCHANGED: 0}
    known = set()
    for item in items:
        known.add((item.id.scope, item.id.kind, item.id.name))
        outcome = ledger.ensure_ledger(
            ledgers_dir, item.id, item.founding, item.would_be_wrong, _origin_of(item, scan),
            as_of.date().isoformat(),
        )
        outcomes[outcome] += 1
    absent = [
        document["identity"]
        for document in ledger.iter_ledgers(ledgers_dir)
        if (document["identity"]["scope"], document["identity"]["kind"], document["identity"]["name"]) not in known
    ]
    return {"items": len(items), **outcomes, "absent_from_inventory": absent}


def _set_below_normal_priority() -> None:
    if os.name == "nt":
        kernel = ctypes.windll.kernel32
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        kernel.SetPriorityClass.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        if not kernel.SetPriorityClass(kernel.GetCurrentProcess(), _BELOW_NORMAL_PRIORITY_CLASS):
            raise OSError("could not set below-normal priority")
    else:
        os.nice(_NICE_BELOW_NORMAL)


def _ledger_counts(ledgers_dir: str, items: Sequence[Item]) -> dict[str, Any]:
    by_kind: dict[str, int] = {}
    founding_status: dict[str, int] = {}
    founding_source: dict[str, int] = {}
    limits_stated = 0
    traced = 0
    traced_creating = 0
    untraced = 0
    stamped = stamp_agrees = 0
    stamps = {(item.id.scope, item.id.name): item.session_stamp for item in items if item.id.kind == ledger.KIND_MEMORY}
    for document in ledger.iter_ledgers(ledgers_dir):
        identity = document["identity"]
        by_kind[identity["kind"]] = by_kind.get(identity["kind"], 0) + 1
        founding = document["founding"]
        founding_status[founding["status"]] = founding_status.get(founding["status"], 0) + 1
        source = str(founding["source"])
        founding_source[source] = founding_source.get(source, 0) + 1
        limits_stated += document["would_be_wrong"]["status"] == schemas.LIMIT_STATED
        origin = document["origin"]
        if origin["status"] == schemas.ORIGIN_TRACED:
            traced += 1
            traced_creating += origin["creating_call_found"]
        elif origin["status"] == schemas.ORIGIN_UNTRACED:
            untraced += 1
        stamp = stamps.get((identity["scope"], identity["name"]))
        if identity["kind"] == ledger.KIND_MEMORY and stamp and origin["status"] == schemas.ORIGIN_TRACED:
            stamped += 1
            stamp_agrees += origin["session"] == stamp
    return {
        "ledgers_by_kind": by_kind,
        "founding_status": founding_status,
        "founding_source": founding_source,
        "stated_limits": limits_stated,
        "memories_traced": traced,
        "memories_traced_to_creating_call": traced_creating,
        "memories_untraced": untraced,
        "traced_with_frontmatter_stamp": stamped,
        "frontmatter_stamp_agrees": stamp_agrees,
    }


def run_backfill(config: Config, run_id: str, as_of: datetime) -> dict[str, Any]:
    """Scan the transcripts, write the ledgers, apply existing notes, and commit locally."""
    started = time.monotonic()
    items = inventory(config)  # A format problem should stop this before the long scan.
    scan_started = time.monotonic()
    scan = scan_transcripts(config)
    scan_seconds = time.monotonic() - scan_started
    synced = sync_items(config, as_of, scan)
    ledgers_dir = ledger.ledgers_dir_of(config.paths.data_dir)
    notes = ledger.apply_notes(os.path.join(config.paths.data_dir, "notes"), ledgers_dir)
    flags = ledger.write_flags(ledgers_dir, as_of, config.ledger)
    data_commit = memory_store.commit_all(config.paths.data_dir, config.memory, f"Ledger backfill {run_id}")
    return {
        "run_id": run_id,
        "sync": synced,
        "absent_from_inventory": len(synced["absent_from_inventory"]),
        **_ledger_counts(ledgers_dir, items),
        "notes": notes,
        "revision_flags": flags,
        "transcript_files": scan.files,
        "transcript_bytes": scan.bytes_read,
        "write_calls_confirmed": scan.calls_confirmed,
        "write_calls_failed": scan.calls_failed,
        "write_calls_without_result": scan.calls_without_result,
        "scan_seconds": round(scan_seconds, 1),
        "total_seconds": round(time.monotonic() - started, 1),
        "data_commit": data_commit,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--result-file", required=True)
    arguments = parser.parse_args(argv)
    _set_below_normal_priority()
    result = run_backfill(load_config(arguments.config), arguments.run_id, datetime.now(timezone.utc))
    with open(arguments.result_file, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=1)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=1)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
