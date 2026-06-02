---
name: plan-finish
description: "Finish a feature branch: mark plans as completed, move to completed/, commit, merge into the base branch with --no-ff, and delete the feature branch"
allowed-tools:
  - Bash
  - Read
  - Edit
  - Glob
  - Grep
---

# Plan Finish

This skill automates the end-of-feature workflow: marking plans as completed,
moving them to `completed/`, committing, then merging the current feature branch
into its recorded base branch (or `dev` as a fallback).

**Trigger:** `/plan-finish [plan-name-1] [plan-name-2] ...`

**Arguments:** Optional list of plan identifiers (filename slug, slug containment,
or title search). If no arguments given, skip Phase A and go straight to Phase B
(merge).

---

## Phase A: Complete Plans (only if arguments provided)

Skip this entire phase if `$ARGUMENTS` is empty or blank.

### Step 1: Locate plans

Follow the procedure in `.claude/skills/_plan-resolve/SKILL.md` to resolve each
plan identifier. Search **`active/` only** -- plans must already be in active
state to be finished.

Apply `_plan-resolve` fail-fast rules: stop on AMBIGUOUS or NOT_FOUND.

### Step 2: Update plan metadata

For each matched plan file:

1. Read the file
2. Replace the `**Status:**` field value with `Completed`
3. Replace the `**Completed:**` field value with the current datetime in
   `YYYY-MM-DD HH:MM` format (get via `date +"%Y-%m-%d %H:%M"`)

Use the Edit tool for these replacements.

### Step 3: Move plans

For each plan file, move it from `active/` to `completed/` using `git mv`:

```bash
git mv docs/development/plans/active/<filename>.md docs/development/plans/completed/<filename>.md
```

### Step 4: Commit plan completion

1. Derive scope from the current branch name (e.g., `feature/touch-analytics` →
   `touch-analytics`)
2. Stage the moved/updated plan files (the `git mv` already stages; just ensure
   the content edits are staged too):
   ```bash
   git add docs/development/plans/completed/<filename>.md
   ```
3. Commit with message:
   - **Single plan:** `docs(<scope>): mark plan as completed`
   - **Multiple plans:** `docs(<scope>): mark plan(s) as completed`
4. Use HEREDOC format. **No `Co-Authored-By` trailer.**
5. Verify with `git log -1 --oneline`.

---

## Phase B: Merge to Base Branch

### Step 5: Identify current branch

```bash
git branch --show-current
```

- If on `main` → report "Cannot merge from main" and **stop**.
- Save the branch name as `<source-branch>`.

### Step 5b: Resolve target branch

Determine which branch to merge `<source-branch>` into:

1. **If Phase A ran** (plan name(s) were provided): read the `**Base Branch:**`
   field from each matched plan file. All plans must agree on the same base
   branch — if they differ, list the conflict and **stop**.

2. **If Phase A was skipped** (no arguments): scan every file in
   `docs/development/plans/active/` for one whose `**Branch:**` field value
   matches `<source-branch>`. If found, read its `**Base Branch:**` field.

3. **Fallback**: if no plan is found or the `**Base Branch:**` field is absent,
   use `dev`.

4. Save the resolved value as `<target-branch>`.

5. Guard: if `<source-branch>` == `<target-branch>` → report "Already on
   target branch `<target-branch>`, nothing to merge" and **stop**.

### Step 6: Safety check

```bash
git status
```

Detect any remaining uncommitted changes (staged, unstaged, or untracked).

### Step 7: Stash if needed

If there are **any** uncommitted changes from Step 6:

```bash
git stash push --include-untracked -m "plan-finish: auto-stash from <source-branch>"
```

Record that a stash was made (for Step 10).

If the working tree is clean, skip this step.

### Step 8: Checkout target branch

```bash
git checkout <target-branch>
```

If checkout fails, report the error and **stop**.

### Step 9: Merge

```bash
git merge --no-ff <source-branch>
```

**Always `--no-ff`** — per project convention.

- If the merge succeeds → continue to Step 10.
- If there are **merge conflicts** → report the conflicting files, tell the user
  to resolve manually, and **stop**. Do NOT attempt to auto-resolve conflicts.

### Step 10: Pop stash

Only if a stash was made in Step 7:

```bash
git stash pop
```

- If pop succeeds → continue.
- If pop has conflicts → warn the user: "Stash pop had conflicts. Resolve
  manually with `git stash drop` after fixing." Do NOT auto-resolve.

### Step 11: Push target branch to origin

```bash
git push origin <target-branch>
```

- If push succeeds → continue to report.
- If push fails (e.g., rejected due to remote changes) → report the error and
  **stop**. Do NOT force-push.

### Step 12: Delete feature branch

Delete the merged feature branch locally and remotely:

```bash
# Delete local branch (safe: we're on <target-branch>, branch is fully merged)
git branch -d <source-branch>

# Delete remote branch
git push origin --delete <source-branch>
```

Rules:
- **Guard:** Never delete `<target-branch>` or `main` — but this is already
  enforced by Steps 5 and 5b which stop if `<source-branch>` matches either.
- Use `-d` (not `-D`) so git refuses if the branch isn't fully merged (extra safety).
- If remote deletion fails (e.g., branch doesn't exist on remote), warn but
  **continue** — don't stop the workflow. The local delete is the critical one.

### Step 13: Report

Display a final summary:

```
--- plan-finish complete ---
Source branch:   <source-branch>
Target branch:   <target-branch>
Plans completed: <list of plan names, or "none (merge only)">
Merge commit:    <hash from git log -1 --oneline>
Current branch:  <target-branch>
Pushed:          origin/<target-branch>
Branch deleted:  <source-branch> (local + remote)
```

Then run `git status` to show the final working tree state.

---

## Edge Cases

| Situation | Behavior |
|-----------|----------|
| No arguments | Skip Phase A, go straight to Phase B (merge) |
| Plan not found in `active/` | List available active plans, stop |
| Ambiguous match | List matches, stop |
| `**Base Branch:**` field present in plan | Use it as `<target-branch>` |
| `**Base Branch:**` field absent / no plan found | Fall back to `dev` |
| Plans disagree on base branch | Report conflict, stop |
| `<source-branch>` equals `<target-branch>` | Report "already on target branch", stop |
| On `main` | Report "cannot merge from main", stop |
| Merge conflicts | Report conflicting files, stop |
| Stash pop conflicts | Warn user, stop |
| Clean tree (no stash needed) | Skip stash/pop steps |
| Push rejected | Report error, stop (never force-push) |
| Remote branch doesn't exist | Warn, continue (local branch still deleted) |

---

## Important Project Constraints

- **Authorship:** All commits by Basil Duvernoy only. Never add `Co-Authored-By` trailers.
- **Merge strategy:** Always `--no-ff` unless user explicitly says "fast-forward".
- **Git safety:** Run `git status` before any operation that touches the working tree.
- **Destructive operations:** Each requires individual approval — but stashing and
  feature branch deletion are explicitly part of this skill's contract, so they
  proceed automatically. Branch deletion only targets the merged feature branch,
  never `<target-branch>` or `main`.
