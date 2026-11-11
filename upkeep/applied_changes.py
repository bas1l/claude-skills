"""The record of memory changes a weekly pass applied, written before the files are.

    reports/YYYY-Www/applied.json

    {"schema_version": 1, "week": "...",
     "folders": {"<project folder>": {
         "status": "prepared|committed", "run_id": "...", "commit": "<sha>"|null,
         "changes": [<report's change records, redacted>],
         "written": [{"relative": "...", "content_sha256": "..."|null}],
         "windows": ["<note windows this pass had read for this folder>"],
         "ledger_recorded": false, "reported": false}}}

A commit in a memory folder and a file in the data folder cannot be written as one step, so this file
goes first, and whichever step a crash stopped at can be told afterwards:

    prepared, and the folder holds this week's commit   the crash came after the commit: it is committed
    prepared, and no such commit                         the crash came before it: what was written is
                                                         put back, and the pass works it out again
    committed, not ledger_recorded                       the weekly pass adds the ledger entries
    committed, not reported                              the weekly pass puts them in its report

Applied changes are taken from here for every report and review of the week, so a retry that finds
nothing new cannot drop them. Knows no model and no transcript.
"""
from __future__ import annotations

import glob
import json
import os
import re
from typing import Any, Iterable, Mapping

import extract
import memory_store
from config import Config

SCHEMA_VERSION = 1
FILE_NAME = "applied.json"
STATUS_PREPARED = "prepared"
STATUS_COMMITTED = "committed"
_WEEK_RE = re.compile(r"^\d{4}-W\d{2}$")


def path_of(config: Config, week: str) -> str:
    return os.path.join(config.paths.data_dir, "reports", week, FILE_NAME)


def load(config: Config, week: str) -> dict[str, Any]:
    path = path_of(config, week)
    if not os.path.exists(path):
        return {"schema_version": SCHEMA_VERSION, "week": week, "folders": {}}
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    if document.get("schema_version") != SCHEMA_VERSION or document.get("week") != week:
        raise ValueError(f"{path}: not the applied changes of {week}")
    return document


def save(config: Config, document: Mapping[str, Any]) -> None:
    path = path_of(config, document["week"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    extract.write_json_atomic(path, document)


def weeks_on_disk(config: Config) -> list[str]:
    """Weeks holding a record, oldest first. A folder set aside under another name is not a week."""
    pattern = os.path.join(glob.escape(os.path.join(config.paths.data_dir, "reports")), "*", FILE_NAME)
    names = (os.path.basename(os.path.dirname(path)) for path in glob.glob(pattern))
    return sorted(name for name in names if _WEEK_RE.fullmatch(name))


def memory_folder(config: Config, project_folder: str) -> str:
    return os.path.join(config.paths.projects_dir, project_folder, "memory")


def mark_committed(entry: dict[str, Any], commit: str) -> None:
    entry["status"] = STATUS_COMMITTED
    entry["commit"] = commit
    for record in entry["changes"]:
        record["commit"] = commit


def settle_folders(config: Config) -> None:
    """Bring each prepared folder to committed or back to how it was. Safe to repeat, and to run
    before anything that would commit what a crash left in a memory folder."""
    for week in weeks_on_disk(config):
        document = load(config, week)
        changed = False
        for project_folder, entry in list(document["folders"].items()):
            if entry["status"] != STATUS_PREPARED:
                continue
            folder = memory_folder(config, project_folder)
            commit = memory_store.week_commit(folder, week)
            if commit is not None:
                mark_committed(entry, commit)
            else:
                memory_store.put_back_uncommitted(folder, entry["written"])
                del document["folders"][project_folder]
            changed = True
        if changed:
            save(config, document)


def committed_entries(document: Mapping[str, Any]) -> Iterable[tuple[str, dict[str, Any]]]:
    return ((name, entry) for name, entry in document["folders"].items() if entry["status"] == STATUS_COMMITTED)
