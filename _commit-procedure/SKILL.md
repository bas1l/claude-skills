---
name: _commit-procedure
description: View and understand the GitHub commit procedure for this project
disable-model-invocation: false
---

# GitHub Commit Procedure

This skill provides comprehensive guidance on committing, branching, and merging
in the social-touch-semi-controlled repository.

---

## ⚠️ Working Tree Safety Protocol

**Run `git status` before any operation that touches the working tree.**

This includes: `git checkout`, `git reset`, `git merge`, `git rebase`, `git stash`.

If uncommitted changes are present:
1. **Stop.** Do not proceed automatically.
2. Report what files are modified/staged and what will happen to them.
3. Ask the user how to handle them (commit, stash, or accept the risk).

```bash
git status   # always run this first
```

> **Why this matters:** `git reset --hard` and branch switches can silently destroy
> uncommitted changes on tracked files. These are unrecoverable from git history.
> See: `docs/development/knowledge-base/note-git-merge-autonomous-fast-forward.md`

---

## Quick Start Checklist

Before committing:
- [ ] Run `git status` — identify any unrelated uncommitted changes
- [ ] You're on a feature branch (not `main` or `dev`)
- [ ] You've staged only the files you intend to commit
- [ ] Your changes are atomic (related to one concern)
- [ ] Your commit message follows the Conventional Commits format below

---

## Commit Message Format

Use **Conventional Commits** format:

```
<type>(<scope>): <subject>

<body - explain what and why>

<footer - references, breaking changes>
```

### Commit Types

| Type | When to Use | Example |
|------|-------------|---------|
| `feat` | New feature | `feat(auth): add JWT token refresh endpoint` |
| `fix` | Bug fix | `fix(config): handle missing optional fields gracefully` |
| `refactor` | Code restructuring (no behavior change) | `refactor(loader): extract validation into separate module` |
| `docs` | Documentation only | `docs(api): update endpoint examples` |
| `test` | Adding or updating tests | `test(auth): add coverage for edge cases` |
| `chore` | Build, CI, tooling changes | `chore(deps): upgrade pytest to v7.0` |
| `style` | Formatting (no logic change) | `style(formatting): remove trailing whitespace` |
| `perf` | Performance improvement | `perf(search): optimize query caching` |

### Scope Examples

- `hand-tracking` — Hand mesh processing
- `forearm-extraction` — Forearm segmentation
- `neural-kinect` — Neural and Kinect data merging
- `sticker-tracking` — Marker tracking
- `led-analysis` — LED state detection
- `config` — Configuration management
- `dag-launcher` — DAG config launcher GUI

### Subject Line Rules

- Start with lowercase
- Use imperative mood: "add", "fix", "update" (NOT "added", "fixed", "updated")
- Don't end with a period
- Keep under 50 characters when possible

### Good Examples ✅

```bash
git commit -m "feat(hand-tracking): add 3D hand visualization support"
git commit -m "fix(forearm-extraction): handle missing point cloud data"
git commit -m "refactor(sticker-tracking): extract centroid calculation"
git commit -m "docs(setup): add GPU configuration instructions"
git commit -m "test(neural-kinect): increase merger test coverage to 90%"
```

---

## Pre-Commit Workflow

### Step 1: Check the working tree

```bash
git status
```

Identify any modified files unrelated to the current task. Do not stage them.

### Step 2: Stage Specific Files

```bash
# Stage individual files (preferred)
git add path/to/file1.py path/to/file2.py
```

⚠️ **Avoid `git add .` or `git add -A`** — too easy to accidentally include `.env`,
build artifacts, or unrelated in-progress changes.

### Step 3: Review what will be committed

```bash
git diff --cached        # full diff of staged changes
git status               # confirm only intended files are staged
```

### Step 4: Create the Commit

```bash
git commit -m "$(cat <<'EOF'
feat(scope): subject line

Body explaining what and why.
EOF
)"
```

---

## Branch Operations

### Creating a Feature Branch

```bash
git status                          # check for uncommitted changes first
git checkout -b feature/my-feature  # create and switch
```

Always branch from the correct base (`dev` for features, `main` for hotfixes).

### Merging a Branch

**Always use `--no-ff` (no fast-forward).** Never choose the merge strategy
autonomously — `--no-ff` is the default for this project unless the user
explicitly requests a fast-forward.

```bash
# Always:
git merge --no-ff feature/my-feature

# Never (unless user explicitly says "fast-forward"):
git merge --ff-only feature/my-feature
```

**Why `--no-ff`:** A fast-forward erases branch provenance — commits from the
merged branch become indistinguishable from commits made directly on the target.
A merge commit preserves the record of which branch each commit came from.

**Before merging**, always run `git status` to confirm the working tree is clean.
If uncommitted changes are present, stop and handle them first.

---

## Destructive Operations Checklist

Before running any of: `git reset --hard`, `git checkout -- .`, `git restore`,
`git clean -f`:

1. Run `git status` and show the output
2. If uncommitted changes exist — **stop and warn the user**:
   - List what will be lost
   - Suggest alternatives: `git stash`, committing first, using `--soft`/`--mixed`
3. Only proceed after explicit user confirmation

| Reset mode | Working tree | Index | Use when |
|------------|-------------|-------|----------|
| `--soft`   | unchanged   | unchanged | Undo commit, keep everything staged |
| `--mixed`  | unchanged   | reset | Undo commit + unstage, keep file edits |
| `--hard`   | reset ⚠️    | reset | Full discard — confirm with user first |

---

## Branch Strategy

- **`main`** — Production-ready, protected
- **`dev`** — Integration branch for completed features, protected
- **`feature/*`**, **`fix/*`**, etc. — Working branches

**Never commit directly to `main` or `dev`.**

---

## Important Project Constraint

**CuPy Import Order**: Any script using CuPy must import it BEFORE any
`preprocessing` package imports.

```python
try:
    import cupy  # noqa: F401 — must precede preprocessing imports
except Exception:
    pass

from preprocessing.some_module import SomeClass  # safe after cupy init
```

---

## Authorship

All commits are authored by **Basil Duvernoy <basil.duvernoy@gmail.com>**.

- **Never** add a `Co-Authored-By: Claude` trailer (or any AI assistant).
- Git operations must reflect only the human author.

---

## Full Documentation

- **[Commit Procedure](../../docs/development/git/commit-procedure.md)**
- **[Git Workflow](../../docs/development/git/git-workflow.md)**
- **[KB: Autonomous fast-forward incident](../../docs/development/knowledge-base/note-git-merge-autonomous-fast-forward.md)**
