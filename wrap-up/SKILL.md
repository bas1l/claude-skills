---
name: wrap-up
description: "Analyse branch cascade, commit outstanding work, fold intermediate feature branches together locally, and send each dev-rooted branch up as a GitHub PR — step-by-step or fully automatic with /wrap-up auto"
allowed-tools:
  - Bash
  - Read
  - Edit
  - Write
  - Glob
  - Grep
  - Agent
  - AskUserQuestion
---

# Wrap-Up

Consolidation skill that analyses the branch hierarchy, helps commit outstanding
work to the right plans, and merges feature branches back to `dev` in the correct
order.

**Trigger:** `/wrap-up [auto]`

**Arguments:**
- No arguments → **analysis only** (Phase 1, then stop — no commits, merges or PRs)
- `run`  → **step-by-step mode** (all phases; confirm after each phase, each merge, and each PR)
- `auto` → **automatic mode** (all phases; skip confirmations — including the PR approval gate — and stop only on errors/conflicts)
- `no-pr` → suppress Phase 3b entirely; every cascade edge becomes a local merge (the pre-PR behaviour)

---

## How branches reach `dev`

A cascade has two kinds of edge, and they are handled differently:

| Edge | Handling | Why |
|------|----------|-----|
| `feature/child` → `feature/parent` | **Local merge**, `--no-ff` | The parent is itself about to move. A PR into a branch that will be merged and deleted leaves a stacked PR needing manual retargeting on GitHub. |
| `feature/x` → `dev` | **GitHub PR** via `plan-pr` | This is the branch that actually lands on the integration line, so it is the one that gets reviewed. |

```
dev
 ├─ feature/a  ................  PR → dev
 └─ feature/b  ................  PR → dev
     └─ feature/c  ...........  local merge → feature/b

Phase 3a folds c into b. Phase 3b then opens two PRs: a → dev, b → dev.
Nothing needs retargeting.
```

Consequence: **Phase 3b never deletes a branch and never merges into `dev`.**
`dev` is only ever written by GitHub merging the PR. Cleaning up afterwards is
`/plan-finish <plan>`'s sync mode.

---

## Phase 1: Analysis (read-only)

### Step 1: Gather branches

```bash
git branch --format='%(refname:short)'
git branch --show-current
```

Save all local branches. Record the current branch. Classify branches:
- **Feature branches** — names starting with `feature/` or `fix/`
- **Infrastructure branches** — `dev`, `main`
- **Other** — version tags, release branches, etc.

### Step 2: Read all active plans

Use `Glob` to find all `*.md` files in `docs/development/plans/active/`.

For each plan file, `Read` the first 15 lines and extract:
- **Plan title** — the `# Plan:` or `# H1` heading (strip any `# Plan: ` prefix)
- **Branch** — the `**Branch:**` field value (strip backticks and whitespace)
- **Base Branch** — the `**Base Branch:**` field value (strip backticks and whitespace)
- **Status** — the `**Status:**` field value
- **Date** — the `**Date:**` field value
- **Filename** — the filename without path or `.md` extension

### Step 3: Build branch-plan mapping

For each feature branch from Step 1, find the plan(s) whose `Branch:` field
matches. Classify into three groups:

- **Matched** — branches with one or more active plans
- **Orphan branches** — feature branches with no active plan (plan already
  completed/moved, or branch predates the plan system)
- **Orphan plans** — active plans whose `Branch:` doesn't match any local branch
  (branch deleted after merge, or not yet created)

### Step 4: Detect co-located and fix plans

**Co-located plans:** multiple plans sharing the same `Branch:` value. Group them
by branch. These MUST be finished together — finishing one deletes the branch,
orphaning the others.

**Fix plans:** a plan whose `Branch:` matches another plan's `Branch:` AND whose
title or filename contains "fix" (case-insensitive). These don't need a separate
merge — they are just marked completed alongside their parent plan. If no title/
filename indicator exists, fall back to: any plan that shares a branch with
another plan and has a `Base Branch:` equal to that same shared branch is a fix
plan (it was branched from itself, meaning it was implemented in-place).

### Step 5: Build cascade tree

Using the `Base Branch:` field from each matched plan:

1. Start with `dev` as the root node.
2. For each branch that has a plan, place it as a child of its `Base Branch:`.
3. Only include branches that eventually root at `dev`. Branches rooted at `main`
   or disconnected branches are excluded from the cascade (listed separately if
   any exist).
4. **Cycle detection:** before inserting a node, walk up the tree to the root. If
   the branch being inserted is already an ancestor, report the cycle and stop
   building that subtree.
5. If a `Base Branch:` value doesn't exist as a local branch, still show the
   relationship but annotate the base as `(missing)`.

### Step 6: Count commits per branch

For each feature branch with a known base branch that exists locally:

```bash
git rev-list --count <base-branch>..<feature-branch>
git log --oneline <base-branch>..<feature-branch>
```

If `<base-branch>` doesn't exist locally, skip and note "base missing."

### Step 6b: Probe PR state per branch

**This step is what keeps `wrap-up` from colliding with `plan-pr`.** Without it,
a branch GitHub has already merged would be merged locally a second time, and a
branch with an open PR would be merged behind that PR's back.

First establish whether GitHub is reachable at all:

```bash
gh auth status && git remote get-url origin
```

If `gh` is missing, unauthenticated, or `origin` is not a GitHub URL → record
**`no-github`**, skip the per-branch probe, and treat every edge as a local merge
(the pre-PR behaviour). Say so in the report; do not fail.

Otherwise, for each feature branch in the cascade:

```bash
gh pr view <branch> --json number,state,url,mergedAt 2>/dev/null
```

Record one state per branch and the resulting **edge kind**:

| PR state | Edge → `dev` | Edge → feature parent |
|----------|--------------|------------------------|
| No PR | **pr** — open one in Phase 3b | **local** — merge as usual |
| `OPEN` | **skip** — PR already awaiting review; nothing to do | **blocked** — see below |
| `MERGED` | **sync** — pull `dev`, clean up, no merge | **blocked** |
| `CLOSED`, unmerged | **ask** (step-by-step) / **blocked** (auto) | **blocked** |

**`blocked`** means: a branch that has a PR of its own must not be quietly
swallowed by a local merge into its parent — doing so would make the PR's diff
meaningless. Report it and **exclude that subtree from the cascade**. Do not
merge it, in either mode.

Feed the edge kind into Step 5's cascade tree so Step 8 can display it.

### Step 7: Gather uncommitted files

```bash
git status --short
```

For each uncommitted file, determine its plan association:

1. **Default association:** the current branch's plan owns all uncommitted files.
2. **Cross-plan check:** use `Grep` to search for each uncommitted file's path
   (just the filename, not the full path) across all active plan files. Look in
   `Files Modified:` sections and general file mentions. If a file appears in a
   plan OTHER than the current branch's plan, flag it as "cross-plan."
3. **Unassociated:** files that match no plan at all (IDE config, generated
   output, etc.).

### Step 8: Display the analysis report

Output the full report. Format:

```
═══════════════════════════════════════════
  WRAP-UP ANALYSIS
═══════════════════════════════════════════

Branch Cascade (dev-rooted):

  dev
  ├── feature/scb-raw-data-output — SCB Raw Data Output (1 commit)
  └── feature/persona-scb-field-alignment — Persona SCB Field Alignment (2 commits)
      └── feature/comparison-pipeline-outputs — Comparison Pipeline Outputs (1 commit)
          └── * feature/batch-extractor-identity-format — Batch Extractor (1 commit)

Co-located Plans (multiple plans → one branch):
  (none)

Fix Plans (no separate merge needed):
  (none)

Orphan Plans (active plan, branch missing):
  - pipeline-seed-documentation → feature/pipeline-seed-documentation (not found)
  - scb-population-analysis-pipeline → feature/scb-population-analysis-pipeline (not found)

Orphan Branches (no active plan):
  - v2.0.0_batch002-003

Uncommitted Files:
  Current branch plan (Batch Extractor):
    M  config/seed_manifests_manager.yaml
  Unassociated:
    ?? .vscode/
    ?? comparison_report.json

Phase 3a — Local merges (leaf → root):
  1. feature/batch-extractor-identity-format → feature/comparison-pipeline-outputs
  2. feature/comparison-pipeline-outputs → feature/persona-scb-field-alignment

Phase 3b — Pull requests (dev-rooted):
  3. feature/persona-scb-field-alignment → dev    PR (no existing PR)
  4. feature/scb-raw-data-output         → dev    SKIP — PR #7 already open
  5. feature/legacy-cleanup              → dev    SYNC — PR #5 merged, cleanup only

Excluded from cascade:
  (none)
```

Each cascade edge is annotated with its kind from Step 6b: `local`, `pr`,
`skip`, `sync`, `blocked`, or `ask`. If Step 6b recorded **`no-github`**, print
`GitHub unreachable — every edge treated as a local merge` above the merge order
and label every edge `local`.

In **analysis-only mode** (no args): display the report and stop. No further
prompts.

In **run mode** (`run` arg): after displaying the report, ask user:
- "Continue to commit assist?" (if uncommitted files exist)
- "Continue to merge cascade?" (if no uncommitted files)
- "Stop here?"

In **auto mode** (`auto` arg): continue automatically to Phase 2 if uncommitted
files exist, otherwise to Phase 3.

---

## Phase 2: Commit Assist

Only runs when invoked with `run` or `auto`. Skipped entirely in analysis-only
mode. Also skipped if the working tree is clean.

### Step 9: Triage uncommitted files

**If co-located plans exist on the current branch:**
- Use `AskUserQuestion` to ask the user which plan each uncommitted file belongs
  to. Present the list of co-located plan names as options.
- In auto mode: assign all files to the first plan (alphabetically by filename).

**If single plan on current branch:**
- All plan-associated and cross-plan files default to the current branch's plan.

**Unassociated files** (IDE config, generated output, etc.):
- Use `AskUserQuestion` with options: "Commit with current plan", "Skip (leave
  uncommitted)", "Add to .gitignore".
- In auto mode: skip unassociated files.

### Step 10: Commit per plan group

For each plan group from Step 9 that has files to commit:

1. Stage the relevant files using `git add <file1> <file2> ...` (never `git add .`).
2. Review staged changes: `git diff --cached --stat`.
3. Generate a commit message following _commit-procedure conventions:
   - **Type:** infer from changes — `feat` for new functionality, `fix` for bug
     fixes, `refactor` for restructuring, `docs` for documentation, `chore` for
     config/tooling.
   - **Scope:** derive from the current branch name (e.g.,
     `feature/batch-extractor-identity-format` → `batch-extractor-identity-format`).
   - **Subject:** imperative mood, lowercase, no trailing period, under 50 chars.
4. In step-by-step mode: show the proposed commit message. Use `AskUserQuestion`
   with options: "Commit as-is", "Edit message" (provide text input), "Skip".
5. In auto mode: commit directly.
6. Commit using HEREDOC format. **No `Co-Authored-By` trailer.**
7. Verify: `git log -1 --oneline`.

---

## Phase 3: Merge Cascade

Only runs when invoked with `run` or `auto`. Skipped entirely in analysis-only
mode.

### Step 11: Pre-merge safety check

```bash
git status --short
```

If there are ANY uncommitted changes (staged, unstaged, or untracked):
- In step-by-step mode: warn and ask — "Stash uncommitted changes and continue?"
  or "Stop and handle manually?"
- In auto mode: auto-stash with message
  `"wrap-up: auto-stash from <current-branch>"`.

```bash
git stash push --include-untracked -m "wrap-up: auto-stash from <current-branch>"
```

Record that a stash was made (for final pop).

### Step 12: Phase 3a — Fold the cascade (local edges)

For each edge whose kind is **`local`**, in cascade order (leaf → root).

Edges marked `pr`, `skip`, `sync` or `ask` are **not** handled here — they go to
Step 13. Edges marked `blocked` are skipped entirely and reported.

If the `no-pr` argument was given, every edge is `local` and this step handles
the whole cascade, ending on `dev` exactly as it did before PRs existed.

#### 12a. Mark plans as completed

Read the plan file(s) for the source branch. For **each** plan (including
co-located and fix plans sharing this branch):

1. Read the plan file.
2. Replace the `**Status:**` field value with `Completed`.
3. Replace the `**Completed:**` field value with the current datetime
   (`YYYY-MM-DD HH:MM` — get via PowerShell `Get-Date -Format "yyyy-MM-dd HH:mm"`).
4. Move the plan file:
   ```bash
   git mv docs/development/plans/active/<filename>.md docs/development/plans/completed/<filename>.md
   ```
5. Stage the moved file:
   ```bash
   git add docs/development/plans/completed/<filename>.md
   ```

#### 12b. Commit plan completion

Derive scope from the source branch name (e.g., `feature/foo` → `foo`).

```bash
git commit -m "$(cat <<'EOF'
docs(<scope>): mark plan(s) as completed
EOF
)"
```

Single plan: `docs(<scope>): mark plan as completed`
Multiple plans: `docs(<scope>): mark N plans as completed`

**No `Co-Authored-By` trailer.**

#### 12c. Checkout target branch

```bash
git checkout <target-branch>
```

If checkout fails, report and stop.

#### 12d. Merge

```bash
git merge --no-ff <source-branch>
```

**Always `--no-ff`.**

- Success → continue to 12e.
- **Merge conflict** → report conflicting files, tell user to resolve manually,
  and **stop**. Do NOT auto-resolve.

#### 12e. Delete source branch

```bash
git branch -d <source-branch>
```

Use `-d` (not `-D`) — git refuses if the branch isn't fully merged (extra
safety). Never delete `dev` or `main`.

#### 12f. Step-by-step checkpoint

In step-by-step mode: display the result of this merge step and ask:
- "Continue to next merge?" / "Stop here?"

Show:
```
  ✓ <source-branch> → <target-branch>
    Plans completed: <plan-name-1>, <plan-name-2>
    Merge commit: <hash from git log -1 --oneline>
    Branch deleted: <source-branch>
    Now on: <target-branch>
```

In auto mode: continue to next merge.

---

### Step 13: Phase 3b — Open pull requests (dev-rooted edges)

Runs after **all** of Phase 3a, so each dev-rooted branch already contains its
folded children and its PR diff is complete. Skipped entirely if `no-pr` was
given or Step 6b recorded `no-github`.

Process dev-rooted branches **one at a time, serially.** Composing a PR reads
`git log`/`git diff` against a checked-out branch, and all branches share one
working tree — parallel compose agents would fight over `HEAD` and produce
diffs for the wrong branch.

For each dev-rooted branch, dispatch on its edge kind from Step 6b:

#### Kind `skip` — a PR is already open

Do nothing. Report:
`feature/x → dev  SKIP — PR #<n> already open (<url>)`

Do not push, do not re-compose, do not merge locally.

#### Kind `sync` — the PR is already merged

The work is on `dev` already. Do not merge, do not open a PR. Run
`/plan-finish <plan-name>` — it detects the merged PR and performs exactly this
cleanup (pull `dev`, mark plans completed there, push, delete the branch).

In **auto** mode invoke it directly. In **step-by-step** mode ask first.

#### Kind `ask` — a closed, unmerged PR exists

- **Step-by-step:** `AskUserQuestion` — "Open a new PR", "Merge locally instead",
  or "Skip this branch".
- **Auto:** do **not** guess. Skip the branch and report it as needing a
  decision. Reopening work that was deliberately closed is not something `auto`
  authorizes.

#### Kind `pr` — no PR exists yet

1. **Checkout the branch:**
   ```bash
   git checkout <branch>
   ```

2. **Mark its plans completed and commit** — run Steps 12a and 12b against this
   branch. The completion commit then rides *inside* the PR, so nothing is left
   dangling on a branch that GitHub will merge later.

3. **Compose** — dispatch a background Agent instructed to read
   `~/.claude/skills/plan-pr/SKILL.md` (or the project-local copy if present) and
   execute **Phases 0–3 in delegated `compose` mode**. Pass the branch, its plan
   file path, and `dev` as the base. It must not push, must not run
   `gh pr create`, and must not edit any repo file.

   `Preflight: FAILED` → report the failed gate, skip this branch, continue to
   the next one. One branch failing preflight must not abort the others.

4. **Gate** — display the composed PR in full, then:
   - **Step-by-step:** ask `yes / edit / no`. On no, skip this branch (its
     completion commit stays on the branch; that is fine and reversible).
   - **Auto:** print `auto mode — opening this PR without confirmation` and
     proceed immediately. The display is a record, not a question.

5. **Execute** — dispatch a second background Agent to read the same file and run
   **Phases 4–6 in delegated `execute` mode**, carrying the matching
   authorization statement:
   - Step-by-step: `Approval granted: the user answered yes at the orchestrator's gate.`
   - Auto: `Approval granted: auto mode — standing authorization, no gate was run.`

   All of `plan-pr`'s hard rules apply: never force-push, never merge or delete a
   branch, stop and report on a rejected push.

6. **Do not delete the branch.** The PR is open, not merged — the branch is the
   PR. Deleting it would close the PR. Cleanup happens later via
   `/plan-finish <plan>` once GitHub has merged it.

#### After Phase 3b

Return to `dev`:

```bash
git checkout dev
```

`dev` is intentionally unchanged by Phase 3b — nothing was merged into it.

### Step 14: Pop stash

Only if a stash was made in Step 11:

```bash
git stash pop
```

- Success → continue.
- Conflict → warn: "Stash pop had conflicts. Resolve manually, then run
  `git stash drop`." Do NOT auto-resolve.

### Step 15: Final report

```
═══════════════════════════════════════════
  WRAP-UP COMPLETE
═══════════════════════════════════════════

Local merges (Phase 3a):
  ✓ feature/batch-extractor-identity-format → feature/comparison-pipeline-outputs
  ✓ feature/comparison-pipeline-outputs     → feature/persona-scb-field-alignment

Pull requests (Phase 3b):
  ✓ feature/persona-scb-field-alignment → dev   PR #12 opened  <url>
  – feature/scb-raw-data-output         → dev   skipped, PR #7 already open
  ✓ feature/legacy-cleanup              → dev   synced (PR #5 merged), branch deleted

Needing a decision:
  - feature/abandoned-idea — PR #9 closed unmerged; re-run with `run` to choose

Plans completed: 3
  - Batch Extractor — Identity Format Mismatch
  - Comparison Pipeline — Outputs
  - Persona Pipeline Field Expansion (SCB Alignment)

Branches still open (awaiting PR review — do NOT delete):
  - feature/persona-scb-field-alignment
  - feature/scb-raw-data-output

Current branch: dev   (unchanged — PRs merge on GitHub)
Working tree: clean / N uncommitted files

Next: review and merge the PRs on GitHub, then run
      /plan-finish <plan-name>   for each merged one.
```

Then run `git status` to show the final state.

Report honestly: a branch whose PR failed preflight, was skipped, or needs a
decision is listed as such. Never present a skipped branch as completed.

---

## Edge Cases

| Situation | Behavior |
|-----------|----------|
| No active plans | Report "No active plans found", show branches only, skip Phase 3 |
| No feature branches | Report "No feature branches found", show orphan plans only |
| Co-located plans (same branch) | Group together, finish ALL in one merge step |
| Fix plan (same branch as parent) | Mark completed alongside parent, no separate merge |
| Circular base-branch refs | Detect cycle, report it, stop building that subtree |
| Plan branch doesn't exist locally | List under "Orphan plans" |
| Branch has no active plan | List under "Orphan branches" |
| Uncommitted files exist at merge time | Require clean tree; stash if needed |
| Merge conflict | Report conflicting files, stop (no auto-resolve) |
| Already on `dev` | Still run analysis; skip merge if no cascade exists |
| `auto` argument | Skip all confirmations **including the PR approval gate**; stop only on errors/conflicts |
| `no-pr` argument | Phase 3b skipped; whole cascade merges locally into `dev` (pre-PR behaviour) |
| `gh` missing / unauthenticated / non-GitHub remote | Record `no-github`, treat every edge as local, note it in the report — do not fail |
| Dev-rooted branch with **open** PR | Skip it. Never merge locally behind an open PR |
| Dev-rooted branch with **merged** PR | Sync via `/plan-finish` (pull, bookkeep, delete). No merge, no new PR |
| Dev-rooted branch with **closed unmerged** PR | Step-by-step: ask. Auto: skip and flag — never re-open closed work unattended |
| **Intermediate** branch that has its own PR | `blocked` — exclude that subtree; folding it into its parent would void the PR's diff |
| Phase 3b compose returns `Preflight: FAILED` | Report the gate, skip that branch, continue with the remaining ones |
| Phase 3b + user answers "no" at the gate | Skip the branch; its completion commit stays on it (harmless, reversible) |
| Phase 3b branch deletion | **Never.** The branch *is* the open PR; deleting it closes the PR |
| `dev` after Phase 3b | Unchanged — PRs merge on GitHub, not locally |
| No `run`/`auto` arg | Stop after Phase 1 report; never enter Phase 2 or Phase 3 |
| Stash pop conflict | Warn user, stop |
| `completed/` directory missing | Create it: `mkdir -p docs/development/plans/completed` |
| Source == target branch | Report "already on target", skip this merge step |
| Base branch missing locally | Show in tree as `(missing)`, skip commit count |

---

## Important Constraints

- **Remote operations are confined to Phase 3b** — and there, to exactly what
  `plan-pr` does: `git push -u origin <branch>` and `gh pr create`. Phases 1, 2
  and 3a remain entirely local. **Never** `git push origin dev`, never
  `git push --delete`, never force-push. `dev` reaches `origin` by GitHub
  merging a PR, or via `/publish-main`.
- **Never merge into `dev` locally** unless `no-pr` was given or GitHub is
  unreachable. That is the PR's job, and doing both duplicates the merge.
- **Authorship** — All commits by Basil Duvernoy only. Never add `Co-Authored-By`
  trailers.
- **Merge strategy** — always `--no-ff` unless user explicitly says "fast-forward".
- **Branch safety** — `git branch -d` (not `-D`), never delete `dev` or `main`.
- **Git safety** — run `git status` before any operation that touches the working
  tree.
- **Destructive operations** — stash and branch deletion are part of this skill's
  contract. In step-by-step mode, each gets individual confirmation. In auto mode,
  they proceed automatically but only via safe commands (`-d` not `-D`, stash
  with message). **Branch deletion never applies to a branch with an open PR** —
  deleting it would close the PR.
- **Dev-rooted only** — the cascade tree only includes branches that chain back
  to `dev`. Branches rooted at `main` or disconnected branches are listed
  separately but not included in the merge cascade.
