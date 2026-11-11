---
name: plan-finish
description: "Finish a feature branch: mark plans as completed, move to completed/, commit, and either merge locally with --no-ff (no-PR flow) or sync after a GitHub PR merge (plan-pr flow). Detects which flow applies."
allowed-tools:
  - Bash
  - Read
  - Edit
  - Glob
  - Grep
---

# Plan Finish

End-of-feature workflow: mark plans as completed, move them to `completed/`,
commit, and reconcile the feature branch with its base.

**How the branch reaches the base depends on how the feature was reviewed**, and
this skill detects which case applies rather than assuming:

| Flow | How the branch merges | What this skill does |
|------|----------------------|----------------------|
| No PR (legacy) | This skill merges it locally, `--no-ff` | Phase A → Phase B |
| `/plan-pr` | **GitHub merges it** via the pull request | Phase S1 → Phase A → Phase S2 |

**It never merges a branch that GitHub already merged.** That is the overlap
`plan-pr` would otherwise create.

**Trigger:** `/plan-finish [plan-name-1] [plan-name-2] ...] [no-merge | merge]`

**Arguments:** Optional plan identifiers (filename slug, slug containment, or
title search). Plus at most one mode-override flag.

| Flag | Effect |
|------|--------|
| *(none)* | **Auto-detect** the mode — see Step 0 |
| `no-merge` | **Bookkeep mode.** Phase A only, on the current branch, then stop. Use before opening a PR so the completion commit rides along in it. |
| `merge` | Force **merge mode**, skipping PR detection. Escape hatch only. |

Passing both `no-merge` and `merge` is an error — report and stop.

---

## Step 0: Determine the finish mode

Runs first, before any file is touched. Mode decides *where Phase A commits*,
so it cannot be deferred.

### 0a. Identify the current branch

```bash
git branch --show-current
```

- Empty (detached HEAD) → **stop**.
- `main` or `master` → **stop**: "Cannot finish from the trunk branch."
- Save as `<source-branch>`.

### 0b. Resolve the target branch

1. **If plan names were given:** resolve them (Phase A Step 1) and read the
   `**Base Branch:**` field from each. All must agree — if they differ, list the
   conflict and **stop**.
2. **If no plan names:** scan `docs/development/plans/active/` for a file whose
   `**Branch:**` field equals `<source-branch>`; read its `**Base Branch:**`.
3. **Fallback:** no plan found, or the field is absent → `dev`.
4. Save as `<target-branch>`.
5. Guard: `<source-branch>` == `<target-branch>` → **stop**, "Already on the
   target branch."

### 0c. Select the mode

If `no-merge` was passed → mode = **bookkeep**. Skip the rest of 0c.
If `merge` was passed → mode = **merge**. Skip the rest of 0c.

Otherwise probe GitHub:

```bash
gh pr view <source-branch> --json number,state,url,mergedAt 2>/dev/null
```

| Probe result | Mode | Note |
|--------------|------|------|
| `gh` missing / not authed / `origin` not GitHub | **merge** | Legacy flow; say so in the report |
| No PR for this branch | **merge** | Legacy flow |
| `state: MERGED` | **sync** | GitHub already merged it — do not merge again |
| `state: OPEN` | **stop** | See below |
| `state: CLOSED`, `mergedAt: null` | **ask** | See below |

**On `OPEN`** — stop with:

```
PR #<n> is open and not yet merged: <url>
Merging locally now would duplicate the PR merge and leave the PR dangling.

  → Merge the PR on GitHub, then re-run /plan-finish <plans>
  → Or, to abandon the PR and merge locally: /plan-finish <plans> merge
```

Do not proceed. Do not close the PR.

**On `CLOSED` without a merge** — the PR was rejected or abandoned. Report the
URL and **ask** whether to merge locally anyway. Only proceed to merge mode on an
explicit yes.

### 0d. Announce the mode

Before doing anything, print:

```
Mode:    <bookkeep | merge | sync>   (<auto-detected | forced by flag>)
Branch:  <source-branch> → <target-branch>
PR:      <url + state, or "none">
Plans:   <names, or "none">
```

### Execution order by mode

| Mode | Order |
|------|-------|
| `bookkeep` | Phase A (on `<source-branch>`) → stop |
| `merge` | Phase A (on `<source-branch>`) → Phase B |
| `sync` | Phase S1 → Phase A (on `<target-branch>`) → Phase S2 |

In **sync** mode Phase A runs *after* the checkout-and-pull, deliberately: the
feature branch is already merged on GitHub, so a commit made on it would be
stranded outside `<target-branch>` and would need a second PR to land.

---

## Phase A: Complete Plans

Skip this entire phase if no plan identifiers were given. (In `sync` mode with no
plan names, Phase S1 and S2 still run — the branch still needs cleaning up.)

### Step 1: Locate plans

Follow the procedure in the `_plan-resolve` skill — read
`~/.claude/skills/_plan-resolve/SKILL.md`, or the project-local
`.claude/skills/_plan-resolve/SKILL.md` if present (project copy wins).

Search **`active/` only** — plans must already be in active state to be finished.

Apply `_plan-resolve` fail-fast rules: stop on AMBIGUOUS or NOT_FOUND.

> In `sync` mode this resolution happens **twice**: once in Step 0b against the
> feature branch's working tree (to read `**Base Branch:**`), and again here
> after Phase S1 has checked out and pulled `<target-branch>`. The files are the
> same — the PR carried them into the base — but re-read them; do not reuse
> stale content from before the checkout.

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

1. Derive scope from `<source-branch>` (e.g., `feature/touch-analytics` →
   `touch-analytics`). **Use `<source-branch>` for the scope even in `sync`
   mode**, where the commit lands on `<target-branch>` — the scope names the
   feature, not the branch being committed to.
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

**Bookkeep mode ends here.** Report and stop:

```
--- plan-finish complete (bookkeep) ---
Plans completed: <names>
Committed on:    <source-branch>  <hash> <subject>
Not merged.      Open the PR with /plan-pr, or merge with /plan-finish merge.
```

---

## Phase B: Local merge (mode = `merge` only)

Never runs in `sync` mode.

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

Record that a stash was made (for Step 10). If the tree is clean, skip.

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

- Merge succeeds → continue to Step 10.
- **Merge conflicts** → report the conflicting files, tell the user to resolve
  manually, and **stop**. Do NOT attempt to auto-resolve.

### Step 10: Pop stash

Only if a stash was made in Step 7:

```bash
git stash pop
```

- Pop succeeds → continue.
- Pop conflicts → warn: "Stash pop had conflicts. Resolve manually with
  `git stash drop` after fixing." Do NOT auto-resolve.

### Step 11: Push target branch to origin

```bash
git push origin <target-branch>
```

Push fails → report and **stop**. Do NOT force-push.

### Step 12: Delete feature branch

```bash
git branch -d <source-branch>
git push origin --delete <source-branch>
```

Rules:
- **Guard:** never delete `<target-branch>` or `main` — already enforced by
  Steps 0a and 0b.
- Use `-d` (not `-D`) so git refuses if the branch isn't fully merged.
- Remote deletion failure (branch not on remote) → warn but **continue**.

Then go to Step 13 (Report).

---

## Phase S: Post-PR sync (mode = `sync` only)

The PR is already merged on GitHub. This phase brings the local repo in line and
lands the plan bookkeeping on `<target-branch>`. **No `git merge` runs anywhere
in this phase.**

### Phase S1 — before Phase A

#### Step S1a: Safety check and stash

```bash
git status
```

Any uncommitted changes → stash them:

```bash
git stash push --include-untracked -m "plan-finish: auto-stash from <source-branch>"
```

Record that a stash was made (for Step S2c).

#### Step S1b: Checkout and pull the target

```bash
git checkout <target-branch>
git pull origin <target-branch>
```

- Checkout fails → report and **stop**.
- Pull fails → report and **stop**. Do not merge, do not reset.

#### Step S1c: Verify the PR merge actually landed

```bash
git log origin/<target-branch> --oneline -5
```

Confirm the PR's merge (or squash) commit is present. If `<target-branch>`
contains none of the feature's work, **stop** and report — the PR state said
MERGED but the local base disagrees, and guessing from here risks losing work.

→ Now run **Phase A** (against this checked-out `<target-branch>`).

### Phase S2 — after Phase A

#### Step S2a: Push the bookkeeping commit

Only if Phase A ran and produced a commit:

```bash
git push origin <target-branch>
```

Push rejected → report and **stop**. Never force-push.

#### Step S2b: Delete the feature branch

```bash
git branch -d <source-branch>
```

- Succeeds → also delete the remote if it still exists:
  ```bash
  git push origin --delete <source-branch>
  ```
  A failure here (GitHub auto-deleted it on merge) is a warning, not an error.
- **`-d` refuses** ("not fully merged") → this is expected when the PR was
  **squash-merged or rebase-merged**: GitHub rewrote the commits, so the original
  branch tip is not an ancestor of `<target-branch>`. Do **not** silently escalate
  to `-D`. Report:

  ```
  git branch -d <source-branch> refused: not an ancestor of <target-branch>.
  This is normal for a squash or rebase merge. PR #<n> is merged (<url>),
  so the work is safely in <target-branch>.

  Delete the local branch anyway? (yes / no)   → runs: git branch -D <source-branch>
  ```

  Only run `-D` on an explicit yes. On no, leave the branch and say so.

#### Step S2c: Pop stash

Only if a stash was made in Step S1a:

```bash
git stash pop
```

Conflicts → warn, do not auto-resolve.

---

## Step 13: Report

### Merge mode

```
--- plan-finish complete (merge) ---
Source branch:   <source-branch>
Target branch:   <target-branch>
Plans completed: <names, or "none (merge only)">
Merge commit:    <hash from git log -1 --oneline>
Current branch:  <target-branch>
Pushed:          origin/<target-branch>
Branch deleted:  <source-branch> (local + remote)
```

### Sync mode

```
--- plan-finish complete (sync after PR) ---
PR:              #<n> merged — <url>
Source branch:   <source-branch>
Target branch:   <target-branch>  (pulled from origin — not merged locally)
Plans completed: <names, or "none (cleanup only)">
Bookkeeping:     <hash> <subject>, pushed to origin/<target-branch>
Current branch:  <target-branch>
Branch deleted:  <source-branch> (local + remote | local only | kept — <reason>)
```

Then run `git status` to show the final working tree state.

---

## Edge Cases

| Situation | Behavior |
|-----------|----------|
| No arguments | Skip Phase A; still detect mode and run Phase B or Phase S |
| Plan not found in `active/` | List available active plans, stop |
| Ambiguous match | List matches, stop |
| `**Base Branch:**` present in plan | Use it as `<target-branch>` |
| `**Base Branch:**` absent / no plan found | Fall back to `dev` |
| Plans disagree on base branch | Report conflict, stop |
| `<source-branch>` equals `<target-branch>` | Report "already on target branch", stop |
| On `main` / detached HEAD | Report and stop |
| Both `no-merge` and `merge` passed | Report contradiction, stop |
| **PR open and unmerged** | **Stop** with instructions — never merge locally over an open PR |
| **PR merged (auto-detected)** | Sync mode: pull, bookkeep on target, clean up. **No local merge** |
| PR closed without merging | Ask before falling back to merge mode |
| `gh` absent / unauthenticated / non-GitHub remote | Merge mode (legacy), noted in the report |
| Sync mode + PR says MERGED but target lacks the work | Stop — do not guess |
| Sync mode + `git branch -d` refuses (squash/rebase merge) | Explain why, ask before `-D` |
| Sync mode + remote branch already gone | Warn, continue |
| Merge conflicts (merge mode) | Report conflicting files, stop |
| Stash pop conflicts | Warn user, stop |
| Clean tree | Skip stash/pop steps |
| Push rejected | Report error, stop (never force-push) |

---

## Important Project Constraints

- **Authorship:** All commits by Basil Duvernoy only. Never add `Co-Authored-By` trailers.
- **Merge strategy:** Always `--no-ff` unless the user explicitly says "fast-forward".
  Applies to merge mode only — sync mode performs no merge.
- **Never force-push**, in any mode.
- **Git safety:** Run `git status` before any operation that touches the working tree.
- **Destructive operations:** Stashing and feature-branch deletion are part of this
  skill's contract and proceed automatically — *except* `git branch -D`, which always
  requires explicit confirmation. Branch deletion never targets `<target-branch>` or `main`.
