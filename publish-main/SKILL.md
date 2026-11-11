---
name: publish-main
description: "Merge dev into main (after pulling latest), push main to origin, and return to dev"
allowed-tools:
  - Bash
  - Read
---

# Publish Main

This skill publishes the `dev` branch to `main` — merge, push, and return to
`dev`. It is the counterpart to `/plan-finish` (which merges feature branches
into `dev`).

**Trigger:** `/publish-main`

**Arguments:** None.

---

## Step 1: Guard — must be on `dev`

```bash
git branch --show-current
```

- If current branch is **not** `dev` → report "Must run /publish-main from the
  dev branch. Currently on: `<branch>`" and **stop**.

## Step 2: Safety check

```bash
git status
```

Detect any uncommitted changes (staged, unstaged, or untracked).

## Step 3: Check dev is in sync with origin/dev

```bash
git rev-list --left-right --count dev...origin/dev
```

This returns `<local_ahead> <remote_ahead>`.

- If **both are 0**: dev and origin/dev are in sync → continue.
- If **local_ahead > 0**: local dev has unpushed commits.
  - Ask user: "Local dev is ahead of origin/dev by X commits. Push to origin first?"
  - Options:
    - **Push now:** Run `git push origin dev`, then continue to Step 4.
    - **Cancel:** Stop and let user handle it manually.
- If **remote_ahead > 0**: origin/dev has commits not pulled locally.
  - Ask user: "origin/dev is ahead of local dev by X commits. Pull first to sync?"
  - Options:
    - **Pull now:** Run `git pull origin dev`, then continue to Step 4.
    - **Cancel:** Stop and let user handle it manually.
- If **both > 0**: Diverged branches (conflict).
  - Report: "Local and origin/dev have diverged. Resolve manually first."
  - **Stop.**

## Step 4: Stash if needed

If there are **any** uncommitted changes from Step 2:

```bash
git stash push --include-untracked -m "publish-main: auto-stash from dev"
```

Record that a stash was made (for Step 8).

If the working tree is clean, skip this step.

## Step 5: Pull latest dev

```bash
git pull origin dev
```

Ensure `dev` is up to date before merging into `main`.

## Step 6: Checkout main and pull

```bash
git checkout main
git pull origin main
```

Ensure `main` is up to date with remote before merging.

If checkout fails, report the error and **stop**.

## Step 7: Merge dev into main

```bash
git merge --no-ff dev
```

**Always `--no-ff`** — per project convention.

- If the merge succeeds → continue.
- If there are **merge conflicts** → report the conflicting files, tell the user
  to resolve manually, and **stop**. Do NOT attempt to auto-resolve conflicts.

## Step 8: Push main

```bash
git push origin main
```

- If push succeeds → continue.
- If push fails (e.g., rejected due to remote changes) → report the error and
  **stop**. Do NOT force-push. **Never force-push to main.**

## Step 9: Return to dev

```bash
git checkout dev
```

## Step 9: Pop stash

Only if a stash was made in Step 3:

```bash
git stash pop
```

- If pop succeeds → continue.
- If pop has conflicts → warn the user: "Stash pop had conflicts. Resolve
  manually with `git stash drop` after fixing." Do NOT auto-resolve.

## Step 11: Report summary

Display a final summary:

```
--- publish-main complete ---
Merge commit: <hash from git log -1 --oneline main>
Current branch: dev
Pushed: origin/main
```

Then run `git status` to show the final working tree state.

---

## Edge Cases

| Situation | Behavior |
|-----------|----------|
| Not on `dev` | Report "must run from dev", stop |
| Uncommitted changes | Stash before, pop after |
| Local dev ahead of origin | Ask user to push first, then continue or cancel |
| origin/dev ahead of local | Ask user to pull first, then continue or cancel |
| Diverged branches | Report divergence, stop |
| Merge conflicts | Report conflicting files, stop |
| Push rejected | Report error, stop (never force-push) |
| Stash pop conflicts | Warn user, stop |
| `dev` doesn't exist | Report error, stop |
| `main` doesn't exist | Report error, stop |

---

## Important Project Constraints

- **Authorship:** All commits by Basil Duvernoy only. Never add `Co-Authored-By` trailers.
- **Merge strategy:** Always `--no-ff` unless user explicitly says "fast-forward".
- **Git safety:** Run `git status` before any operation that touches the working tree.
- **Destructive operations:** Never force-push, especially not to `main`.
