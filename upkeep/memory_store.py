"""Local git history for memory folders and for the upkeep data folder.

Every repository here is local: each has a ``pre-push`` hook that refuses, and any
remote found raises. A memory file is never moved, rewritten or deleted by this module;
a baseline commit adds ``.git`` and nothing else to the folder.

A folder is in exactly one state:

    empty        no files and no repository; gets a repository when first written
    new          files and no repository
    adoptable    its own repository, with the guard and no remote; config left as found
    foreign      its own repository that fails either check; reported, never changed
    parent_repo  inside some other repository; reported, never changed

Snapshots commit whatever live sessions left in a folder. Deletions by a session count
as edits, so a later revert can restore them.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any, Optional, Sequence

from config import Config, MemoryConfig, load_config

STATE_EMPTY = "empty"
STATE_NEW = "new"
STATE_ADOPTABLE = "adoptable"
STATE_FOREIGN = "foreign"
STATE_PARENT_REPO = "parent_repo"

RESULT_CREATED = "created"
RESULT_COMMITTED = "committed"
RESULT_UNCHANGED = "unchanged"
RESULT_EMPTY = "empty"

MEMORY_GUARD = "#!/bin/sh\necho 'This memory repository is local only: push refused.' >&2\nexit 1\n"
UPKEEP_GUARD = "#!/bin/sh\necho 'This upkeep repository is local only: push refused.' >&2\nexit 1\n"
GUARD_MARKER = "push refused"

BASELINE_MESSAGE = "Baseline of memory folder before automated upkeep"
UPKEEP_BASELINE_MESSAGE = "Baseline of upkeep data folder"

# Keeps bytes as they are on disk and leaves no dependency on machine-wide git config.
NEW_REPO_SETTINGS = (
    ("core.autocrlf", "false"),
    ("core.safecrlf", "false"),
    ("core.longpaths", "true"),
)

UPKEEP_TRACKED_FOLDERS = ("state", "notes", "counts", "ledgers", "proposals", "reports")
UPKEEP_WORKING_FOLDERS = ("logs", "run", "review")
UPKEEP_GITIGNORE = (
    "# Working folders and transient files. Everything else is tracked. Nothing here has a remote.\n"
    "/logs/\n"
    "/run/\n"
    "/review/\n"
    "/upkeep.lock\n"
    "/failure-marker.json\n"
)

_SCRUBBED_GIT_VARIABLES = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_PREFIX")
_NOT_A_REPO = "not a git repository"


class MemoryStoreError(RuntimeError):
    """A repository is not in the expected state, or a git command failed."""


def _run_git(folder: str, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    environment = {key: value for key, value in os.environ.items() if key not in _SCRUBBED_GIT_VARIABLES}
    completed = subprocess.run(
        ["git", "-C", folder, *arguments],
        capture_output=True,
        encoding="utf-8",
        env=environment,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        check=False,
    )
    if check and completed.returncode != 0:
        raise MemoryStoreError(f"git {' '.join(arguments)} in {folder}: exit {completed.returncode}: {completed.stderr.strip()}")
    return completed


def _commit(folder: str, identity: MemoryConfig, message: str) -> None:
    _run_git(
        folder,
        "-c", f"user.name={identity.author_name}",
        "-c", f"user.email={identity.author_email}",
        "commit", "--quiet", "--message", message,
    )


def list_files(folder: str) -> list[str]:
    """Every file under a folder, as a sorted relative path, outside ``.git``."""
    found = []
    for directory, subdirectories, names in os.walk(folder):
        if directory == folder and ".git" in subdirectories:
            subdirectories.remove(".git")
        found.extend(os.path.relpath(os.path.join(directory, name), folder) for name in names)
    return sorted(name for name in found if name != ".git")


def memory_folders(projects_dir: str) -> list[str]:
    """Each ``<project>/memory`` folder that exists."""
    if not os.path.isdir(projects_dir):
        raise FileNotFoundError(f"projects folder not found: {projects_dir}")
    candidates = (os.path.join(projects_dir, name, "memory") for name in sorted(os.listdir(projects_dir)))
    return [path for path in candidates if os.path.isdir(path)]


def _same_path(first: str, second: str) -> bool:
    return os.path.normcase(os.path.realpath(first)) == os.path.normcase(os.path.realpath(second))


def _toplevel(folder: str) -> Optional[str]:
    completed = _run_git(folder, "rev-parse", "--show-toplevel", check=False)
    if completed.returncode == 0:
        return completed.stdout.strip()
    if _NOT_A_REPO in completed.stderr:
        return None
    raise MemoryStoreError(f"git rev-parse in {folder}: {completed.stderr.strip()}")


def _guard_path(folder: str) -> str:
    return os.path.join(folder, ".git", "hooks", "pre-push")


def has_push_guard(folder: str) -> bool:
    path = _guard_path(folder)
    if not os.path.isfile(path):
        return False
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    return GUARD_MARKER in text and "exit 1" in text


def remotes_of(folder: str) -> list[str]:
    return _run_git(folder, "remote").stdout.split()


def classify(folder: str) -> str:
    """The state of a folder; see the module docstring."""
    top = _toplevel(folder)
    if top is not None and not _same_path(top, folder):
        return STATE_PARENT_REPO
    if top is not None:
        return STATE_ADOPTABLE if has_push_guard(folder) and not remotes_of(folder) else STATE_FOREIGN
    if os.path.exists(os.path.join(folder, ".git")):
        return STATE_FOREIGN
    return STATE_NEW if list_files(folder) else STATE_EMPTY


def _create_guarded_repo(folder: str, identity: MemoryConfig, guard: str) -> None:
    """A repository holding no commit yet: byte-preserving settings, identity, push guard."""
    _run_git(folder, "init", "--quiet", "--template=")
    for key, value in (*NEW_REPO_SETTINGS, ("user.name", identity.author_name), ("user.email", identity.author_email)):
        _run_git(folder, "config", key, value)
    os.makedirs(os.path.dirname(_guard_path(folder)), exist_ok=True)
    with open(_guard_path(folder), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(guard)


def init_memory_repo(folder: str, identity: MemoryConfig) -> None:
    """Create the repository of a ``new`` folder, with every file in one baseline commit."""
    state = classify(folder)
    if state != STATE_NEW:
        raise MemoryStoreError(f"{folder}: state {state!r}, expected {STATE_NEW!r}")
    _create_guarded_repo(folder, identity, MEMORY_GUARD)
    _run_git(folder, "add", "--all")
    _commit(folder, identity, BASELINE_MESSAGE)


def snapshot_folder(folder: str, identity: MemoryConfig, message: str) -> str:
    """Commit what live sessions left in a folder; a first write creates its repository."""
    state = classify(folder)
    if state == STATE_EMPTY:
        return RESULT_EMPTY
    if state == STATE_NEW:
        init_memory_repo(folder, identity)
        return RESULT_CREATED
    if state != STATE_ADOPTABLE:
        raise MemoryStoreError(f"{folder}: state {state!r}; refusing to commit here")
    return commit_all(folder, identity, message)


def commit_all(folder: str, identity: MemoryConfig, message: str) -> str:
    """Stage everything and commit if anything changed. Refuses a repository with a remote."""
    if remotes_of(folder):
        raise MemoryStoreError(f"{folder}: has a remote; nothing here may have one")
    _run_git(folder, "add", "--all")
    difference = _run_git(folder, "diff", "--cached", "--quiet", check=False)
    if difference.returncode == 0:
        return RESULT_UNCHANGED
    if difference.returncode != 1:
        raise MemoryStoreError(f"git diff in {folder}: exit {difference.returncode}: {difference.stderr.strip()}")
    _commit(folder, identity, message)
    return RESULT_COMMITTED


def snapshot_all(projects_dir: str, identity: MemoryConfig, message: str) -> dict[str, Any]:
    """Snapshot every memory folder. A failing folder is listed and does not stop the rest."""
    results: dict[str, list[str]] = {RESULT_CREATED: [], RESULT_COMMITTED: [], RESULT_UNCHANGED: [], RESULT_EMPTY: []}
    errors = []
    for folder in memory_folders(projects_dir):
        project = os.path.basename(os.path.dirname(folder))
        try:
            results[snapshot_folder(folder, identity, message)].append(project)
        except MemoryStoreError as error:
            errors.append({"project_folder": project, "error": str(error)})
    return {**results, "errors": errors}


def plan_memory_repos(projects_dir: str) -> list[dict[str, Any]]:
    """What initialising would find, changing nothing."""
    plan = []
    for folder in memory_folders(projects_dir):
        files = list_files(folder)
        plan.append({
            "project_folder": os.path.basename(os.path.dirname(folder)),
            "state": classify(folder),
            "files": len(files),
            "not_markdown": [name for name in files if not name.endswith(".md")],
            "in_subfolders": [name for name in files if os.path.dirname(name)],
        })
    return plan


def init_all_memory_repos(projects_dir: str, identity: MemoryConfig) -> dict[str, list[str]]:
    """Create a repository in each ``new`` folder. Others stay as found and are listed by state."""
    outcome: dict[str, list[str]] = {
        STATE_NEW: [], STATE_ADOPTABLE: [], STATE_EMPTY: [], STATE_FOREIGN: [], STATE_PARENT_REPO: [],
    }
    for folder in memory_folders(projects_dir):
        state = classify(folder)
        if state == STATE_NEW:
            init_memory_repo(folder, identity)
        outcome[state].append(os.path.basename(os.path.dirname(folder)))
    return outcome


def init_upkeep_repo(data_dir: str, identity: MemoryConfig) -> None:
    """Set up the upkeep data folder as a local repository. Refuses one already set up."""
    if not os.path.isdir(data_dir):
        raise FileNotFoundError(f"upkeep data folder not found: {data_dir}")
    if _toplevel(data_dir) is not None or os.path.exists(os.path.join(data_dir, ".git")):
        raise MemoryStoreError(f"{data_dir}: already inside a repository")
    if os.path.exists(os.path.join(data_dir, ".gitignore")):
        raise MemoryStoreError(f"{data_dir}: already holds a .gitignore")
    for name in (*UPKEEP_TRACKED_FOLDERS, *UPKEEP_WORKING_FOLDERS):
        os.makedirs(os.path.join(data_dir, name), exist_ok=True)
    _create_guarded_repo(data_dir, identity, UPKEEP_GUARD)
    with open(os.path.join(data_dir, ".gitignore"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(UPKEEP_GITIGNORE)
    _run_git(data_dir, "add", "--all")
    _commit(data_dir, identity, UPKEEP_BASELINE_MESSAGE)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("plan", "init-memory", "init-upkeep"))
    parser.add_argument("--config", required=True)
    arguments = parser.parse_args(argv)
    config: Config = load_config(arguments.config)
    if arguments.action == "plan":
        json.dump(plan_memory_repos(config.paths.projects_dir), sys.stdout, indent=1)
    elif arguments.action == "init-memory":
        json.dump(init_all_memory_repos(config.paths.projects_dir, config.memory), sys.stdout, indent=1)
    else:
        init_upkeep_repo(config.paths.data_dir, config.memory)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
