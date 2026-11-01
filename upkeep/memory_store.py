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
import tempfile
from dataclasses import dataclass
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


INDEX_FILE = "MEMORY.md"
WEEK_TRAILER = "Upkeep-Week"
_FRONT_MATTER_FENCE = "---"


class MemoryEditError(ValueError):
    """An edit does not fit the file as it stands."""


def read_memory_file(path: str) -> Optional[str]:
    """A memory's exact text, line endings included, or None if it does not exist."""
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def _body_start(text: str) -> int:
    """Where a memory's body begins, after any frontmatter."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != _FRONT_MATTER_FENCE:
        return 0
    offset = len(lines[0])
    for line in lines[1:]:
        offset += len(line)
        if line.strip() == _FRONT_MATTER_FENCE:
            return offset
    raise MemoryEditError("frontmatter is never closed")


def _locate_in_body(text: str, old_text: str) -> int:
    start = _body_start(text)
    count = text.count(old_text, start)
    if count != 1:
        raise MemoryEditError(f"old_text occurs {count} times in the body, must be exactly once")
    return text.index(old_text, start)


def add_to_memory(text: str, addition: str) -> str:
    return f"{text.rstrip()}\n\n{addition}\n"


def replace_in_memory(text: str, old_text: str, new_text: str) -> str:
    position = _locate_in_body(text, old_text)
    return text[:position] + new_text + text[position + len(old_text):]


def remove_from_memory(text: str, old_text: str) -> str:
    position = _locate_in_body(text, old_text)
    remaining = text[:position] + text[position + len(old_text):]
    return f"{remaining.rstrip()}\n"


def check_old_text(text: str, old_text: str) -> None:
    """Raise unless ``old_text`` occurs exactly once in the body."""
    _locate_in_body(text, old_text)


def index_line(title: str, file_name: str, hook: str) -> str:
    return f"- [{title}]({file_name}) \u2014 {hook}"


def index_with_line(index_text: Optional[str], line: str) -> str:
    return f"{line}\n" if not index_text else f"{index_text.rstrip()}\n{line}\n"


def index_without_file(index_text: Optional[str], file_name: str) -> Optional[str]:
    if index_text is None:
        return None
    return "".join(line for line in index_text.splitlines(keepends=True) if f"]({file_name})" not in line)


@dataclass(frozen=True)
class FileWrite:
    """The new text of one file, or None to delete it, with the text it was worked out from."""

    relative: str
    expected_before: Optional[str]
    content: Optional[str]


@dataclass(frozen=True)
class IndexEdit:
    """A change to the index, worked out on the index as it stands when applying, because
    live sessions add lines to it. ``line`` None takes the file's line out."""

    file_name: str
    line: Optional[str]


def week_already_applied(folder: str, week: str) -> bool:
    """True if this folder holds a commit of this week's pass. An unborn repository has none."""
    if not os.path.isdir(folder) or classify(folder) != STATE_ADOPTABLE:
        return False
    if _run_git(folder, "rev-parse", "--verify", "--quiet", "HEAD", check=False).returncode != 0:
        return False
    found = _run_git(folder, "log", "--fixed-strings", f"--grep={WEEK_TRAILER}: {week}", "--format=%H")
    return bool(found.stdout.strip())


def _prepare_folder_for_writing(folder: str, identity: MemoryConfig, snapshot_message: str) -> None:
    os.makedirs(folder, exist_ok=True)
    state = classify(folder)
    if state == STATE_EMPTY:
        _create_guarded_repo(folder, identity, MEMORY_GUARD)
    elif state == STATE_NEW:
        init_memory_repo(folder, identity)
    elif state == STATE_ADOPTABLE:
        commit_all(folder, identity, snapshot_message)
    else:
        raise MemoryStoreError(f"{folder}: state {state!r}; refusing to commit here")


def apply_memory_writes(
    folder: str,
    writes: Sequence[FileWrite],
    index_edits: Sequence[IndexEdit],
    identity: MemoryConfig,
    week: str,
    message: str,
) -> dict[str, Any]:
    """One commit for one pass in one folder.

    What live sessions left is committed first, on its own. A file that changed since its new
    text was worked out is left alone and listed in ``conflicts``; the others go ahead. Only
    the files written are in the commit, so a live edit arriving meanwhile stays out of it.
    A folder that already holds this week's commit raises.
    """
    if week_already_applied(folder, week):
        raise MemoryStoreError(f"{folder}: already holds a commit of {week}")
    _prepare_folder_for_writing(folder, identity, f"Snapshot of edits by live sessions, before upkeep {week}")
    conflicts = []
    paths = []
    for write in writes:
        path = os.path.join(folder, write.relative)
        if read_memory_file(path) != write.expected_before:
            conflicts.append(write.relative)
            continue
        if write.content is None:
            os.remove(path)
        else:
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(write.content)
        paths.append(write.relative)
    if not paths:
        return {"commit": None, "conflicts": conflicts}
    index_path = os.path.join(folder, INDEX_FILE)
    index_text = read_memory_file(index_path)
    edited = False
    for edit in index_edits:
        if edit.file_name in conflicts:
            continue
        index_text = index_without_file(index_text, edit.file_name)
        if edit.line is not None:
            index_text = index_with_line(index_text, edit.line)
        edited = True
    if edited and index_text is not None:
        with open(index_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(index_text)
        paths.append(INDEX_FILE)
    _run_git(folder, "add", "--all", "--", *paths)
    _run_git(
        folder,
        "-c", f"user.name={identity.author_name}",
        "-c", f"user.email={identity.author_email}",
        "commit", "--quiet", "--message", f"{message}\n\n{WEEK_TRAILER}: {week}", "--", *paths,
    )
    return {"commit": _run_git(folder, "rev-parse", "HEAD").stdout.strip(), "conflicts": conflicts}


class UndoConflictError(MemoryStoreError):
    """The file has moved on in the same lines, so one change cannot be taken out by itself."""


UNDO_RESTORED = "restored"
UNDO_ALREADY = "already_restored"


def _three_way(current: str, base: str, target: str) -> Optional[str]:
    """``current`` with the step from ``base`` to ``target`` applied, or None if they clash.
    Works on bytes, so that line endings stay as they are."""
    with tempfile.TemporaryDirectory(prefix="upkeep-undo-") as directory:
        paths = []
        for name, text in (("current", current), ("base", base), ("target", target)):
            path = os.path.join(directory, name)
            with open(path, "wb") as handle:
                handle.write(text.encode("utf-8"))
            paths.append(path)
        completed = subprocess.run(
            ["git", "merge-file", "-p", "-q", *paths],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            check=False,
        )
    if completed.returncode == 0:
        return completed.stdout.decode("utf-8")
    if 0 < completed.returncode < 128:
        return None
    raise MemoryStoreError(f"git merge-file: exit {completed.returncode}: {completed.stderr.decode('utf-8', 'replace').strip()}")


def _text_after_undo(current: Optional[str], before: Optional[str], after: Optional[str], file_name: str) -> Optional[str]:
    """What the file should hold once this one change is taken out. Raises if that cannot be told."""
    clash = (
        f"{file_name} has changed since, in the same lines, so this change cannot be taken out by itself. "
        "Undo the newer change on this memory first, or edit the file by hand."
    )
    if before is None:
        if current is None or current == after:
            return None
        merged = _three_way(current, after if after is not None else "", "")
        if merged is None:
            raise UndoConflictError(clash)
        return merged if merged.strip() else None
    if after is None:
        if current is None or current == before:
            return before
        raise UndoConflictError(clash)
    if current is None:
        raise UndoConflictError(clash)
    merged = _three_way(current, after, before)
    if merged is None:
        raise UndoConflictError(clash)
    return merged


def _commit_paths(folder: str, paths: Sequence[str], identity: MemoryConfig, message: str) -> str:
    """Commit these paths alone, so that a live edit arriving meanwhile stays out."""
    _run_git(folder, "add", "--all", "--", *paths)
    _run_git(
        folder,
        "-c", f"user.name={identity.author_name}",
        "-c", f"user.email={identity.author_email}",
        "commit", "--quiet", "--message", message, "--", *paths,
    )
    return _run_git(folder, "rev-parse", "HEAD").stdout.strip()


def _write_exact(path: str, text: Optional[str]) -> None:
    if text is None:
        os.remove(path)
        return
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def _index_line_at(folder: str, commit: str, file_name: str) -> Optional[str]:
    """The index line this file had just before a commit, if it had one."""
    shown = _run_git(folder, "show", f"{commit}^:{INDEX_FILE}", check=False)
    if shown.returncode != 0:
        return None
    lines = [line for line in shown.stdout.splitlines() if f"]({file_name})" in line]
    return lines[0] if lines else None


def undo_change(
    folder: str,
    file_name: str,
    before: Optional[str],
    after: Optional[str],
    commit: str,
    identity: MemoryConfig,
    message: str,
) -> dict[str, Any]:
    """Take one applied change out of a memory by a new commit. History is never rewritten.

    A pass makes one commit per folder, which may hold several changes, so this works from the
    change's own before and after and not by reverting the commit. Edits made since in other lines
    stay. Running it again finds the change gone and commits nothing.
    """
    state = classify(folder)
    if state != STATE_ADOPTABLE:
        raise MemoryStoreError(f"{folder}: state {state!r}; refusing to commit here")
    if _run_git(folder, "cat-file", "-e", f"{commit}^{{commit}}", check=False).returncode != 0:
        raise MemoryStoreError(f"{folder}: holds no commit {commit}")
    commit_all(folder, identity, f"Snapshot of edits by live sessions, before an undo of {file_name}")
    path = os.path.join(folder, file_name)
    current = read_memory_file(path)
    restored = _text_after_undo(current, before, after, file_name)
    if restored == current:
        return {"result": UNDO_ALREADY, "commit": None}
    _write_exact(path, restored)
    paths = [file_name]
    index_path = os.path.join(folder, INDEX_FILE)
    index_text = read_memory_file(index_path)
    edited = index_text
    if restored is None:
        edited = index_without_file(index_text, file_name)
    elif current is None:
        line = _index_line_at(folder, commit, file_name)
        if line is not None:
            edited = index_with_line(index_without_file(index_text, file_name), line)
    if edited != index_text:
        _write_exact(index_path, edited)
        paths.append(INDEX_FILE)
    return {"result": UNDO_RESTORED, "commit": _commit_paths(folder, paths, identity, message)}


def write_reviewed_memory(
    folder: str,
    file_name: str,
    expected_before: Optional[str],
    content: Optional[str],
    index_edit: Optional[IndexEdit],
    identity: MemoryConfig,
    message: str,
) -> str:
    """Write a change the user approved in a review, as a commit of its own. Refuses a file that
    differs from what the change was worked out on. Holds no week trailer, since it is no pass."""
    _prepare_folder_for_writing(folder, identity, f"Snapshot of edits by live sessions, before a reviewed change of {file_name}")
    path = os.path.join(folder, file_name)
    if read_memory_file(path) != expected_before:
        raise MemoryEditError(f"{file_name} changed while this was being applied")
    _write_exact(path, content)
    paths = [file_name]
    if index_edit is not None:
        index_path = os.path.join(folder, INDEX_FILE)
        index_text = index_without_file(read_memory_file(index_path), index_edit.file_name)
        if index_edit.line is not None:
            index_text = index_with_line(index_text, index_edit.line)
        if index_text is not None:
            _write_exact(index_path, index_text)
            paths.append(INDEX_FILE)
    return _commit_paths(folder, paths, identity, message)


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
