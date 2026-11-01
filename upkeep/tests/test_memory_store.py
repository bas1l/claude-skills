"""Memory repositories on synthetic folders in temp. Real memory folders are never used."""
from __future__ import annotations

import hashlib
import os
import subprocess

import pytest

import memory_store as ms
from config import MemoryConfig

IDENTITY = MemoryConfig(author_name="Test Author", author_email="test@example.invalid")


def git(folder, *arguments, check=True):
    return subprocess.run(["git", "-C", str(folder), *arguments], capture_output=True, encoding="utf-8", check=check)


@pytest.fixture
def projects(tmp_path):
    root = tmp_path / "projects"
    (root / "proj-a" / "memory").mkdir(parents=True)
    (root / "proj-a" / "memory" / "one.md").write_bytes(b"line one\r\nline two\r\n")
    (root / "proj-a" / "memory" / "two.md").write_bytes(b"lf only\n")
    (root / "proj-empty" / "memory").mkdir(parents=True)
    (root / "proj-no-memory").mkdir()
    return root


def test_folder_states(projects, tmp_path):
    assert ms.classify(str(projects / "proj-a" / "memory")) == ms.STATE_NEW
    assert ms.classify(str(projects / "proj-empty" / "memory")) == ms.STATE_EMPTY

    parent = tmp_path / "parent"
    (parent / "memory").mkdir(parents=True)
    git(parent, "init", "--quiet")
    assert ms.classify(str(parent / "memory")) == ms.STATE_PARENT_REPO

    unguarded = tmp_path / "unguarded"
    unguarded.mkdir()
    git(unguarded, "init", "--quiet", "--template=")
    assert ms.classify(str(unguarded)) == ms.STATE_FOREIGN


def test_baseline_keeps_bytes_and_tracks_every_file(projects):
    folder = projects / "proj-a" / "memory"
    before = {name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in ("one.md", "two.md")}

    ms.init_memory_repo(str(folder), IDENTITY)

    assert sorted(git(folder, "ls-files").stdout.split()) == ms.list_files(str(folder)) == ["one.md", "two.md"]
    assert git(folder, "status", "--porcelain").stdout == ""
    assert {name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in before} == before
    blob = subprocess.run(["git", "-C", str(folder), "show", "HEAD:one.md"], capture_output=True, check=True).stdout
    assert blob == b"line one\r\nline two\r\n"
    assert git(folder, "config", "core.autocrlf").stdout.strip() == "false"
    assert ms.classify(str(folder)) == ms.STATE_ADOPTABLE


def test_commit_author_is_set_with_no_trailer(projects):
    folder = projects / "proj-a" / "memory"
    ms.init_memory_repo(str(folder), IDENTITY)
    log = git(folder, "log", "-1", "--format=%an|%ae|%cn|%B").stdout
    assert log.startswith("Test Author|test@example.invalid|Test Author|")
    assert "Co-Authored-By" not in log


def test_push_guard_refuses_a_push(projects, tmp_path):
    folder = projects / "proj-a" / "memory"
    ms.init_memory_repo(str(folder), IDENTITY)
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "init", "--quiet", "--bare", str(bare)], check=True)
    pushed = git(folder, "push", str(bare), "HEAD:refs/heads/x", check=False)
    assert pushed.returncode != 0
    assert "push refused" in pushed.stderr
    assert subprocess.run(["git", "-C", str(bare), "for-each-ref"], capture_output=True, encoding="utf-8").stdout == ""


def test_adoption_changes_nothing(tmp_path):
    root = tmp_path / "projects"
    folder = root / "proj" / "memory"
    folder.mkdir(parents=True)
    (folder / "a.md").write_text("a", encoding="utf-8")
    git(folder, "init", "--quiet", "--template=")
    (folder / ".git" / "hooks").mkdir()
    (folder / ".git" / "hooks" / "pre-push").write_text(ms.MEMORY_GUARD, encoding="utf-8", newline="\n")
    git(folder, "add", "-A")
    git(folder, "-c", "user.name=Earlier", "-c", "user.email=e@example.invalid", "commit", "-qm", "earlier")
    config_before = (folder / ".git" / "config").read_bytes()

    outcome = ms.init_all_memory_repos(str(root), IDENTITY)

    assert outcome[ms.STATE_ADOPTABLE] == ["proj"]
    assert ms.snapshot_folder(str(folder), IDENTITY, "nothing") == ms.RESULT_UNCHANGED
    assert (folder / ".git" / "config").read_bytes() == config_before
    assert git(folder, "log", "--format=%s").stdout.split() == ["earlier"]


def test_snapshot_commits_edits_new_files_and_deletions(projects):
    folder = projects / "proj-a" / "memory"
    ms.init_memory_repo(str(folder), IDENTITY)
    (folder / "one.md").write_bytes(b"edited\r\n")
    (folder / "three.md").write_bytes(b"new\n")
    (folder / "two.md").unlink()

    assert ms.snapshot_folder(str(folder), IDENTITY, "snap") == ms.RESULT_COMMITTED
    assert git(folder, "log", "--format=%s").stdout.splitlines()[0] == "snap"
    assert sorted(git(folder, "ls-files").stdout.split()) == ["one.md", "three.md"]
    assert ms.snapshot_folder(str(folder), IDENTITY, "again") == ms.RESULT_UNCHANGED
    assert len(git(folder, "log", "--format=%s").stdout.splitlines()) == 2


def test_empty_folder_gets_a_repository_when_first_written(projects):
    folder = projects / "proj-empty" / "memory"
    assert ms.snapshot_folder(str(folder), IDENTITY, "snap") == ms.RESULT_EMPTY
    assert not (folder / ".git").exists()
    (folder / "first.md").write_bytes(b"first\n")
    assert ms.snapshot_folder(str(folder), IDENTITY, "snap") == ms.RESULT_CREATED
    assert git(folder, "ls-files").stdout.split() == ["first.md"]
    assert ms.has_push_guard(str(folder))


def test_remote_is_refused(projects, tmp_path):
    folder = projects / "proj-a" / "memory"
    ms.init_memory_repo(str(folder), IDENTITY)
    git(folder, "remote", "add", "origin", str(tmp_path / "elsewhere.git"))
    assert ms.classify(str(folder)) == ms.STATE_FOREIGN
    with pytest.raises(ms.MemoryStoreError, match="foreign"):
        ms.snapshot_folder(str(folder), IDENTITY, "snap")


def test_snapshot_all_lists_a_failing_folder_and_continues(projects):
    good = projects / "proj-a" / "memory"
    bad = projects / "proj-b" / "memory"
    bad.mkdir(parents=True)
    (bad / "x.md").write_bytes(b"x\n")
    git(bad, "init", "--quiet", "--template=")

    result = ms.snapshot_all(str(projects), IDENTITY, "snap")

    assert result[ms.RESULT_CREATED] == ["proj-a"]
    assert [item["project_folder"] for item in result["errors"]] == ["proj-b"]
    assert ms.classify(str(good)) == ms.STATE_ADOPTABLE


def test_plan_changes_nothing_and_flags_unexpected_files(projects):
    (projects / "proj-a" / "memory" / "odd.bin").write_bytes(b"\0")
    plan = {row["project_folder"]: row for row in ms.plan_memory_repos(str(projects))}
    assert plan["proj-a"]["state"] == ms.STATE_NEW
    assert plan["proj-a"]["not_markdown"] == ["odd.bin"]
    assert not (projects / "proj-a" / "memory" / ".git").exists()


def test_init_all_reports_each_state(projects):
    parent_project = projects / "proj-parent"
    (parent_project / "memory").mkdir(parents=True)
    git(parent_project, "init", "--quiet")
    outcome = ms.init_all_memory_repos(str(projects), IDENTITY)
    assert outcome[ms.STATE_NEW] == ["proj-a"]
    assert outcome[ms.STATE_EMPTY] == ["proj-empty"]
    assert outcome[ms.STATE_PARENT_REPO] == ["proj-parent"]


def test_upkeep_repo_tracks_data_and_ignores_working_folders(tmp_path):
    data = tmp_path / "upkeep"
    (data / "trials").mkdir(parents=True)
    (data / "trials" / "t.txt").write_text("t", encoding="utf-8")
    (data / "run").mkdir()
    ms.init_upkeep_repo(str(data), IDENTITY)

    for name in ("state", "notes", "logs", "run", "review"):
        (data / name).mkdir(exist_ok=True)
        (data / name / "f.txt").write_text("x", encoding="utf-8")
    (data / "failure-marker.json").write_text("{}", encoding="utf-8")
    (data / "upkeep.lock").write_text("{}", encoding="utf-8")

    assert ms.commit_all(str(data), IDENTITY, "data") == ms.RESULT_COMMITTED
    tracked = set(git(data, "ls-files").stdout.split())
    assert {"state/f.txt", "notes/f.txt", "trials/t.txt", ".gitignore"} == tracked
    assert ms.has_push_guard(str(data))
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "init", "--quiet", "--bare", str(bare)], check=True)
    assert git(data, "push", str(bare), "HEAD:refs/heads/x", check=False).returncode != 0
    with pytest.raises(ms.MemoryStoreError, match="already"):
        ms.init_upkeep_repo(str(data), IDENTITY)


def test_commit_all_refuses_a_remote(tmp_path):
    data = tmp_path / "upkeep"
    data.mkdir()
    ms.init_upkeep_repo(str(data), IDENTITY)
    git(data, "remote", "add", "origin", "https://example.invalid/x.git")
    with pytest.raises(ms.MemoryStoreError, match="remote"):
        ms.commit_all(str(data), IDENTITY, "data")


def test_git_commands_ignore_inherited_repository_variables(projects, tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "wrong"))
    folder = projects / "proj-a" / "memory"
    ms.init_memory_repo(str(folder), IDENTITY)
    assert os.path.isdir(folder / ".git")
