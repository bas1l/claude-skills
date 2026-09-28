---
name: plan-pr
description: "Submit a matured feature branch for GitHub peer review: preflight the tree, mine the plan doc + commit log for a PR description, push, and open the pull request against its base branch. Replaces the local --no-ff merge."
allowed-tools:
  - Bash
  - Read
  - Write
  - Glob
  - Grep
---

# Plan PR

Terminal step of the plan lifecycle. Takes a feature branch that has been
implemented via `/plan-implement` and matured through review/adjustment cycles,
and submits it for **peer review on GitHub** as a pull request.

**Trigger:** `/plan-pr [plan-name-1] [plan-name-2] ...] [draft]`

**Arguments:** Optional. Plan identifiers (filename slug, slug containment, or
title search) used to source the PR description. If omitted, the plan is
inferred from the current branch name. The literal token `draft` opens the PR
as a draft.

---

## Contract

| Property | Value |
|----------|-------|
| Merge model | **The PR replaces the local `--no-ff` merge.** This skill never merges, never checks out the base branch, never deletes branches. |
| Reviewers | **None assigned.** The PR is opened and its URL reported; reviewer assignment is done by the user on GitHub. |
| Write scope | One `git push` of the current branch + one `gh pr create`. No commits, no file edits in the repo. |
| Review guidance | Every run ends by telling the user **how to review the PR**: a tiered walkthrough (contracts → core logic → wiring → tests) over the **code only**, with documentation, the plan file and generated artifacts excluded and counted separately. Emitted both into the PR body (`## Review order`) and to the user in the Phase 6 report. |
| Confirmation | The composed title/body/target are **always shown** before anything is pushed. Approval is required in interactive and attended-delegated runs; `/plan-implement … auto` carries a standing authorization, so the display is a record rather than a gate. |

> This skill **supersedes Phase B of `/plan-finish`** (the local merge, push and
> branch deletion). Do not run `/plan-finish` after it — see
> [After the PR merges](#after-the-pr-merges).

---

## Invocation modes

This skill is entered in exactly two ways:

### Interactive mode (default)

The user types `/plan-pr`. Run **Phases 0 → 6 in order**, including the Phase 3c
approval gate, in a single agent that can talk to the user.

### Delegated mode

An orchestrator (currently `/plan-implement` with the `pr` flag, Step 7)
dispatches background Agents that **read this file** and execute a *slice* of it.
The approval gate cannot run inside a background Agent, so the phases are split
around it and the orchestrator holds the gate:

| Slice | Phases | Runs | Must not |
|-------|--------|------|----------|
| `compose` | 0, 1, 2, 3 (**stop before 3c**) | Preflight, plan resolution, diff gathering, title/body composition | Push, `gh pr create`, edit any repo file |
| *(gate)* | 3c | **Orchestrator**, in the chat with the user | — |
| `execute` | 4, 5, 6 | Push, create/update the PR, report | Re-compose the body, re-ask for approval, force-push |

Rules that hold in delegated mode:

- The `compose` slice returns its result as **text** — preflight verdict,
  head/base, existing-PR state, title, body temp-file path, commit and file
  counts, and the full body markdown. It returns; it does not act.
- A failed Phase 0 or Phase 1 gate in `compose` is terminal. It is reported
  upward and the orchestrator stops. It is never worked around.
- The `execute` slice runs **only** when its prompt carries one of the two
  authorization statements below. Absent both, refuse and report — never infer
  approval from the dispatch itself.
- The `execute` slice's Phase 6 output **includes the "how to review this PR"
  block**, reproduced from the `## Review order` section the `compose` slice
  wrote. `/plan-implement` Step 7d relays that output verbatim, which is how the
  guidance reaches the user under `auto`.
- Every hard rule at the bottom of this file applies to both slices unchanged.

#### The two authorizations

| Statement in the dispatch prompt | Meaning |
|---|---|
| `Approval granted: the user answered yes at the orchestrator's gate.` | **Attended.** A human saw the composed PR and said yes. |
| `Approval granted: auto mode — standing authorization, no gate was run.` | **Unattended.** `/plan-implement … auto` is a standing instruction to run to completion without the user present. |

Under **unattended** authorization the gate is *pre-satisfied, not removed*. It
covers exactly one action: opening the PR that `compose` just described. It does
**not** extend to decisions `compose` could not foresee. Specifically, in
Phase 4a:

- **Open PR already exists** → push (updating its diff is the point of a re-run)
  but **do not overwrite its body**; report that the body was left as-is.
- **Closed or merged PR exists** → **stop and report.** Never create a second PR
  unattended.

Everything else — a rejected push, a failed preflight, a `gh` error — stops and
reports exactly as it would in interactive mode. Unattended means *nobody is
waiting*, not *proceed regardless*.

---

## Phase 0: Preflight

Every check is a hard gate. On failure, report the specific reason and **stop** —
do not attempt a workaround.

### Step 0a: Working tree must be clean

```bash
git status --porcelain
```

Any output (staged, unstaged, or untracked) → **stop**. Report the files and
tell the user to run `/plan-commit` or stash. A PR must describe committed work
only; opening one over a dirty tree misrepresents what reviewers will see.

### Step 0b: Branch must be a feature branch

```bash
git branch --show-current
```

- Empty (detached HEAD) → **stop**.
- `main` or `master` → **stop**: "Cannot open a PR from the trunk branch."
- Save as `<source-branch>`.

### Step 0c: GitHub must be reachable and authenticated

```bash
gh auth status
git remote get-url origin
```

- `gh` not installed or not authenticated → **stop**, print the `gh auth login`
  hint.
- No `origin` remote, or `origin` is not a GitHub URL → **stop**.

---

## Phase 1: Resolve plan(s) and base branch

### Step 1a: Resolve plans

Follow the procedure in the `_plan-resolve` skill — read
`~/.claude/skills/_plan-resolve/SKILL.md`, or the project-local
`.claude/skills/_plan-resolve/SKILL.md` if that file exists (project copy wins).

Search directories, in order: `active/`, `completed/`, `pending/`.

Apply the `_plan-resolve` fail-fast rules: stop on `AMBIGUOUS` or `NOT_FOUND`.

**If no plan identifiers were given:** scan every file in
`docs/development/plans/active/` and `docs/development/plans/completed/` for one
whose `**Branch:**` field equals `<source-branch>`.
- Exactly one match → use it.
- Multiple matches → list them and **stop** (ask which to use).
- No match → continue with **no plan** (Phase 2 falls back to commits + diff
  only). Warn the user that the PR body will be commit-derived and thinner.

**Sanity check:** if a resolved plan's `**Branch:**` field does not match
`<source-branch>`, warn loudly and ask before continuing — the description would
describe different work than the diff.

**Status note:** if a resolved plan is still in `active/`, note it in the final
report. It stays in `active/` — plan bookkeeping is not this skill's job.

### Step 1b: Resolve the base branch

1. From the resolved plan(s): read the `**Base Branch:**` field. If several
   plans disagree → list the conflict and **stop**.
2. If absent, or no plan was resolved → fall back to `dev`.
3. Save as `<base-branch>`.
4. Guard: `<source-branch>` == `<base-branch>` → **stop**, nothing to review.
5. Confirm the base exists on the remote:
   ```bash
   git ls-remote --heads origin <base-branch>
   ```
   Empty result → **stop**: the base branch is not on `origin`, so the PR has no
   target.

---

## Phase 2: Gather review material

Run these read-only commands and keep the output for composition:

```bash
git fetch origin <base-branch> --quiet
git log origin/<base-branch>..HEAD --oneline --no-merges   # commits under review
git diff origin/<base-branch>...HEAD --stat                # files + churn
git diff origin/<base-branch>...HEAD --name-status         # add/modify/delete
```

Guard: if the commit list is **empty** → **stop**: "No commits ahead of
`<base-branch>` — nothing to review."

From each resolved plan file, extract verbatim (do not paraphrase away the
author's wording):

| Plan section | Used for |
|--------------|----------|
| `# Plan:` heading | PR title |
| `## Overview` | Summary |
| `## Problem Statement` | Motivation |
| `### In Scope` (under `## Goals`) | What changed — cross-checked against the diff |
| `### Out of Scope` | Out of scope |
| `## Success Criteria` | Verification checklist, **with actual checkbox state preserved** |

### Step 2b: Classify the changed files into review tiers

Take every path from `--name-status` and assign it exactly one tier. This is the
input to the `## Review order` section (Phase 3) and to the Phase 6 report. It is
derived from the **diff**, never from the plan's intentions.

| Tier | What belongs in it | Why it is read at this point |
|------|--------------------|------------------------------|
| **0 — Not reviewed** | Documentation, the plan document itself, changelogs, generated/vendored artifacts, lockfiles, and diffs that are pure formatting or import reordering | Read last or not at all. It cannot be wrong in a way that costs anything, and it is the bulk of the line count in a plan-driven branch |
| **1 — Contracts** | Interfaces, abstract base classes, public signatures, data schemas, config files and registries that *define* behaviour, CLI/API surface declarations | Fixes what every other file must obey. A defect here invalidates the reading of tiers 2–4 |
| **2 — Core logic** | The modules that implement the new behaviour — algorithms, computation, state transitions, the actual subject of the plan | The change itself. This is where correctness bugs live |
| **3 — Wiring** | Call sites, dispatch, orchestration, CLI flag plumbing, GUI/scripts, adapters, anything that only *connects* tier 1 to tier 2 | Mechanical, but the place where a signature change silently misses a caller |
| **4 — Tests** | Test files | Read as executable specification, confirming what tiers 1–3 claimed |

Rules:

- **Earliest tier wins.** A file that fits two tiers takes the lower number — a
  contract change buried inside a logic module is still a contract change, and
  saying so is the point of the ordering.
- **No tier by path convention alone.** `config/` is tier 1 only when the file
  defines behaviour; a fixture or a sample output is tier 0. Decide from what the
  diff does to the file, not from the directory it sits in.
- **Nothing fits any of 1–4** → tier 3, and name it plainly as unclassified in
  the ordering so the reviewer knows it was not placed on evidence.
- **Never silently drop a file.** Every path in `--name-status` lands in exactly
  one tier, and every tier states its full file count even when the listing is
  truncated.
- A tier with no files is **omitted** from the output, not printed empty.

---

## Phase 3: Compose the PR

### Title

- **One plan:** the plan title, verbatim.
- **Multiple plans:** a title covering both, derived from the branch name
  (`feature/cap-population-to-n` → `Cap population to N`), with plan titles
  listed in the body.
- **No plan:** derive from the branch name.

Keep it under ~70 characters. No trailing period. No conventional-commit prefix
unless the repo's existing PR titles use one — check with
`gh pr list --state all --limit 5 --json title`.

### Body

Write to a temp file (never inline in the shell — bodies contain backticks,
quotes and newlines that mangle under quoting). Use the session scratchpad
directory if one is available, otherwise the OS temp dir. Then pass it via
`--body-file`.

Template:

```markdown
## Summary

<2–4 sentences from the plan Overview, tightened. What this branch does and why
it exists. No marketing language.>

## Motivation

<Condensed Problem Statement — the concrete defect or gap being closed. Skip
this section entirely if there is no plan.>

## What changed

<Bullets grouped by area, reconciled against `--name-status`. Each bullet names
the real path(s). Derive these from the diff, not only from the plan — the plan
states intent, the diff states fact. Where they diverge, describe the diff and
flag the divergence under Review notes.>

- `src/<area>/…` — <what and why>
- `config/…` — <what and why>
- `tests/…` — <what is now covered>

## Out of scope

<Verbatim from the plan's Out of Scope. Omit the section if there is no plan.>

## Verification

<Success Criteria with their real checkbox state. Unchecked boxes are reported
as unchecked — never tick a box the plan leaves open.>

- [x] <criterion>
- [ ] <criterion — still open>

<If the plan documents a test command, name it and state plainly whether it was
run in this session and what the result was. If it was not run, say
"not run in this session" — do not imply a green suite.>

## Review order

<The Step 2b tiers, rendered as an ordered walkthrough. Code only — tier 0 is
never interleaved here. Each file carries a specific "what to check", not a
restatement of its filename. Omit any tier with no files. List at most 8 files
per tier; if a tier holds more, say `+N more` and give the tier's real count.>

**1 · Contracts — start here (<n> files)**
- `path/to/interface.py` — <the contract that changed, and what now must obey it>

**2 · Core logic (<n> files)**
- `path/to/module.py` — <the specific behaviour to verify, e.g. "the tie-break
  when both series are empty">

**3 · Wiring (<n> files)**
- `path/to/caller.py` — <which tier-1 change it must track>

**4 · Tests (<n> files)**
- `tests/test_x.py` — <which tier-2 claim this pins down>

<One line naming the single file a reviewer should read if they read only one,
and why it is that one.>

Not part of the code review: <n> documentation/plan/generated files.

## Review notes

<Known rough edges, deliberate compromises, and follow-ups left for a later
branch. Anything the reviewer would otherwise flag as a defect and that was in
fact a choice — say which, and why. Omit the section if there is genuinely
nothing.>

---

Plan: `docs/development/plans/<dir>/<file>.md`
Commits: <n> · Files changed: <n>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

Sections with nothing real to say are **removed**, not filled with filler.

### Step 3c: Confirmation gate

**Delegated mode:** the `compose` slice stops *here* in **both** attended and
unattended runs. Return the block below as text to the orchestrator and exit — do
not ask, do not proceed to Phase 4. The orchestrator decides whether a human is
asked, and dispatches the `execute` slice with the matching authorization.

**Interactive mode:** the gate is **mandatory**. Display to the user, in the chat:

```
--- PR to be opened ---
Head:   <source-branch>
Base:   <base-branch>
Draft:  yes | no
Title:  <title>

<full body text>
```

Then ask for explicit approval. Accept edits to the title/body and re-display.
**Nothing is pushed until the user approves.** Opening a PR is outward-facing
and publishes the branch — approval for a prior run does not carry over.

---

## Phase 4: Push

### Step 4a: Detect an existing PR

```bash
gh pr view <source-branch> --json url,state,isDraft 2>/dev/null
```

- An **open** PR already exists → do not create a second one. Push (Step 4b),
  then report the existing URL and note that the PR was updated rather than
  created. Skip Phase 5 — but Phase 6 still prints the "how to review" block,
  read from the composed body file (which Phase 5 would have deleted). When the
  existing body was left untouched, say so: the walkthrough describes the pushed
  diff, not what is currently rendered on GitHub.
  - *Attended:* ask before overwriting the existing PR body.
  - *Unattended:* **leave the body untouched** and say so in the report.
- A **closed/merged** PR exists → do not create a new one on your own initiative.
  - *Attended:* warn and ask.
  - *Unattended:* **stop and report.** Nothing is pushed.
- No PR → continue.

### Step 4b: Push the branch

```bash
git push -u origin <source-branch>
```

- Rejected as non-fast-forward → **stop**. Report it. **Never force-push** —
  not `--force`, not `--force-with-lease`. A rejected push means the remote
  branch has commits this branch does not; that is the user's call to resolve.
- Any other failure → report and **stop**.

---

## Phase 5: Open the pull request

```bash
gh pr create \
  --base <base-branch> \
  --head <source-branch> \
  --title "<title>" \
  --body-file <temp-body-file>
```

Append `--draft` if the `draft` argument was given.

Do **not** pass `--reviewer`, `--assignee`, or `--label` — reviewer assignment is
out of contract.

If `gh pr create` fails, report stderr verbatim and stop. The branch is already
pushed, so the user can open the PR manually from the printed URL.

Delete the temp body file afterwards — but **read the `## Review order` section
out of it first** and keep it. Phase 6 reproduces that section verbatim, and it
is unrecoverable once both the file is gone and the body lives only on GitHub.

---

## Phase 6: Report

```
--- plan-pr complete ---
PR:              <url>
Title:           <title>
Head → Base:     <source-branch> → <base-branch>
State:           open | draft
Plans:           <titles, or "none (commit-derived)">
Plan status:     <active | completed> — <note if still in active/>
Commits:         <n>
Files changed:   <n> (+<add>/-<del>)
Reviewers:       none assigned — assign on GitHub
```

### How to review this PR

Print this **immediately after** the report block above, every run, in both
interactive and delegated (`execute`) mode. It is the user's answer to "where do
I start?" and it is the reason Step 2b exists. Reproduce the tier listing from
the body's `## Review order` section verbatim — do not recompute it, and do not
summarise it into prose.

```
--- how to review ---
Code only. Documentation, the plan file and generated artifacts (<n> files) are
excluded from every step below.

1. Contracts (<n> files) — what everything else must obey
   <file> — <what to check>
2. Core logic (<n> files) — where a correctness bug would be
   <file> — <what to check>
3. Wiring (<n> files) — confirm every tier-1 change reached its call sites
   <file> — <what to check>
4. Tests (<n> files) — read as the spec, confirm it pins tier 2 down
   <file> — <what to check>

Read this first if you read nothing else: <path> — <why>.

Two ways through it:
  By layer   — GitHub "Files changed", following the order above
  By phase   — GitHub "Commits" tab: <n> commits, one per plan phase, each
               reviewable on its own
               locally: git log --oneline origin/<base-branch>..<source-branch>
                        git show <hash>
```

Rules for this block:

- **Order is fixed** — contracts, logic, wiring, tests. Never reorder it to match
  the diff's alphabetical order or the plan's phase order; the whole point is
  that it cuts across both.
- **Omit empty tiers**, and renumber the remaining ones so the list reads 1..n.
- **Every "what to check" is specific.** `— review the changes` is not a
  reviewer instruction; name the condition, the edge case, or the invariant.
- **The excluded count is always printed**, even when it is 0. Silence there
  reads as "there were no docs", which is a different claim.
- The **by-phase** route is printed only when the commit count is greater than 1.

### After the PR merges

State this follow-up explicitly in the report; do not perform it:

```
Once the PR is merged on GitHub, run:

  /plan-finish <plan-name>

It detects the merged PR and enters sync mode: pulls <base-branch>, marks the
plan completed there, pushes, and deletes the feature branch. It will NOT merge
locally — that already happened on GitHub.
```

`plan-finish` Step 0c probes `gh pr view <branch>` and picks its mode from the PR
state, so the two skills do not overlap:

| PR state when `/plan-finish` runs | What it does |
|---|---|
| Merged | Sync mode — pull, bookkeep on the base, clean up. No local merge. |
| Open | **Stops** and tells the user to merge the PR first |
| None | Legacy merge mode — merges locally with `--no-ff` |

Do not restate the old "do not run /plan-finish" warning — it is obsolete.

---

## Hard rules

- **Never force-push.** Under any circumstance.
- **Never merge, rebase, checkout another branch, or delete a branch.** This
  skill touches exactly two remote-affecting commands: `git push -u` and
  `gh pr create`.
- **Never open a PR without a Phase 3c authorization.** Interactive mode: the
  user's "yes". Delegated mode: one of the two authorization statements in
  [Invocation modes](#delegated-mode) — the relayed "yes", or `auto` mode's
  standing authorization. Absent any of these, refuse.
- **Never create a second PR unattended** when a closed or merged one already
  exists for the branch, and never overwrite an existing PR body unattended.
- **Never state a test suite passed unless it was actually run and observed** in
  this session. "Not run in this session" is the correct thing to write.
- **Never tick a Success Criteria checkbox** that the plan document leaves
  unticked.
- **Never present a documentation, plan or generated file as a review step.**
  Tier 0 is counted and excluded, never interleaved into the walkthrough. A
  review order padded with docs is what makes a reviewer skim.
- **Never end a run without the "how to review" block.** It is part of the
  report, not an optional extra, and it is emitted even when a single file
  changed.
- **Fail loudly.** Every gate in Phase 0 and Phase 1 stops the workflow; none
  falls back to a default beyond the documented `dev` base-branch fallback.
