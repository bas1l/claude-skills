---
name: plan-implement
description: "Start implementing a plan: read it, move to active/, create a branch, and dispatch implementation to a background agent (the calling agent never writes implementation code itself). Each phase is committed on its own as it completes, so the branch can be reviewed one phase at a time. With the `pr` flag, also dispatches plan-pr to open the GitHub peer-review PR."
allowed-tools:
  - Bash
  - Read
  - Edit
  - Write
  - Glob
  - Grep
  - Agent
---

# Implement Plan

This skill automates the transition from an approved plan to active implementation.
It receives `$ARGUMENTS` in the format: `<plan-name> [auto] [commit]`.

---

## Hard Rule: Implementation MUST run in a background Agent

The agent invoking `/plan-implement` is an **orchestrator**, not an implementer. It MUST NOT edit, write, or otherwise modify any implementation file (source code, configuration, tests, assets, etc.) under its own identity. Every code change required by the plan is dispatched to a **background `Agent` call** (`run_in_background: true`).

The orchestrator's own tool use is restricted to:

- Reading files (the plan, project conventions, validation lookups)
- Running `git` inspection / branching commands via `Bash`
- Running `git add` / `git commit` for the **per-phase commit** (Step 5d). Committing records changes an Agent already wrote; it does not author file content, so it does not breach this rule. The orchestrator must never edit a file in order to make a commit succeed — on a hook failure or a conflict it stops and reports.
- Editing **only** the plan document itself for skill-level metadata (the `**Base Branch:**` field in Step 3, the `**Status:**` field in Step 4, and the move from `pending/` to `active/`)
- Launching `Agent` calls and reading their results

Any task in the plan — even a one-line change — is delegated. If the orchestrator finds itself about to call `Edit` or `Write` on a non-plan file, it must stop and dispatch an Agent instead. This rule applies in **both** manual and auto modes.

---

## Argument Parsing

Split `$ARGUMENTS` on whitespace. Scan all tokens for recognised flags and remove them; rejoin remaining tokens as the plan name. The `implement here` detection (Step 3) still applies to the remaining tokens.

Recognised flags (order-independent, combinable):

| Flag | Effect |
|------|--------|
| `auto` | Auto mode — run everything unattended, end to end. **Implies `commit` and `pr`.** |
| `commit` | Final sweep commit — invoke `/plan-commit` automatically after all phases complete, for whatever the per-phase commits did not capture |
| `no-phase-commit` | Disable the per-phase commit (Step 5d). All phases accumulate into the working tree and land as one commit, the pre-2026-07 behaviour. Escape hatch only. |
| `pr` | Auto peer review — after the commit lands, dispatch `plan-pr` to background Agents to compose and open the GitHub PR (Step 7). Implies `commit`. |
| `no-pr` | Suppress Step 7 even under `auto`. Phases + commit only. |
| `draft` | Open the PR as a **draft** (passed through to `plan-pr`). Only meaningful with `pr` or `auto`. |

- **Per-phase commit is the default in BOTH modes** (Step 5d): each phase lands as its own commit as soon as it validates, so a reviewer can step through the branch one phase at a time instead of reading one 40-file diff. It is not gated on any flag; `no-phase-commit` is the only way off.
- **Manual mode** (default, no `auto`): dispatches **one phase at a time** to a background Agent, commits that phase, then pauses for user confirmation before the next phase
- **Auto mode** (`auto` flag present): dispatches all phases sequentially via background Agents with no pauses, commits each phase, **and opens the PR — without pausing for approval**
- **`commit` flag**: triggers the **final sweep** commit after all phases complete, in either mode. With per-phase commits active this usually covers only the plan document's `## Modified Files` section, so a clean tree at Step 6 is a **success**, not an error.
- **`pr` flag**: triggers Step 7 after a successful auto-commit, in either mode. Implies `commit`.
- **`no-pr` flag**: cancels the `pr` implied by `auto`. `auto no-pr` = unattended phases + commit, no PR. If both `pr` and `no-pr` are passed explicitly, report the contradiction and **stop**.

### Attended vs unattended Step 7

The one thing that differs between the two is the **approval gate** (Step 7b):

| Invocation | Phases | Phase commits | Final sweep | PR | Approval gate |
|------------|--------|---------------|-------------|-----|---------------|
| *(none)* | one at a time, gated | **yes** | no | no | — |
| `commit` | one at a time, gated | **yes** | yes | no | — |
| `pr` | one at a time, gated | **yes** | yes | yes | **asks you** |
| `auto` | all, ungated | **yes** | yes | yes | **skipped — PR opens unattended** |
| `auto no-pr` | all, ungated | **yes** | yes | no | — |
| `no-phase-commit` | one at a time, gated | no | no | no | — |

Note that plain `/plan-implement <plan>` now **does** produce commits — one per
phase. What it still does not do is the final sweep or the PR.

`auto` is an explicit instruction to run to completion without the user present.
Stopping to ask before the PR would defeat it, so under `auto` the gate is
pre-authorized: the composed PR is **displayed for the record, not for
approval**, and Step 7c proceeds immediately. Every other `plan-pr` safeguard
(preflight gates, no force-push, no duplicate PR) still applies unchanged.

In both modes, the orchestrator never writes implementation code itself — see the Hard Rule above.

---

## Step 1: Locate the plan

Follow the procedure in `.claude/skills/_plan-resolve/SKILL.md` to resolve the
plan identifier. Search directories: `pending/` then `active/`.

Apply `_plan-resolve` fail-fast rules: stop on AMBIGUOUS or NOT_FOUND.

After resolution:
- If found in **active/** — skip the move step (Step 4). Proceed to branch creation.
- If found in **pending/** — proceed normally through all steps.

---

## Step 2: Read the plan

Read the full plan document. Display a brief summary to the user:

- **Title** (from the `# Plan:` heading)
- **Status** (from the `**Status:**` field)
- **Branch** (from the `**Branch:**` field)
- **Phase count** (number of `### Phase N:` sections)

---

## Step 3: Branch creation

Read the `**Branch:**` field from the plan to get the intended branch name.

### Guard: main branch protection

If the current branch is `main`:
- **STOP.** Do not create a branch from main.
- Tell the user: "You are on `main`. Please switch to the correct base branch first (e.g., `dev` or another feature branch), then re-run this command."
- Do not proceed further.

### If not on main:

1. Run `git status --porcelain` to detect uncommitted changes. If present, warn the user and list them — uncommitted changes will travel with the checkout.
2. **Record the returned paths as the `pre-existing` set** and carry it through the whole run. Step 5d must never stage a path in this set unless a phase's own files-modified list names it. This is what keeps unrelated in-flight work out of the phase commits; without it, a per-phase `git add` sweeps up whatever was already dirty.
3. Run `git branch --show-current` and **record the result as `<fork-point>`** — the branch the new branch is about to be cut from. The main guard above has already run, so this can never be `main`.
4. If the branch from the plan **already exists**, ask the user whether to switch to it or abort. On "switch", **do not** rewrite `**Base Branch:**` (Step 3b) — the branch was cut earlier, from somewhere this run cannot observe.
5. Otherwise, create the branch: `git checkout -b <branch-name>`, then run **Step 3b**.

### Step 3b: Record the real base branch

Runs **only** when Step 3 just created the branch with `git checkout -b`.

`plan-create` stamps `**Base Branch:**` with whatever branch was checked out the
day the plan was *written*. A plan that waits in `pending/` outlives that branch:
`/plan-finish` and `/wrap-up` merge it into `dev` and delete it. The field then
names a branch that no longer exists on `origin`, and `plan-pr` Phase 1b step 5
(`git ls-remote --heads origin <base-branch>`) fails preflight — so an
`auto` run implements and commits every phase, then dies at Step 7 with no PR.

`<fork-point>` is the branch the feature branch was **actually** cut from, and it
is true by construction. Write it into the plan document, at whatever path the
plan currently sits (`pending/` or `active/` — Step 4's `git mv` carries the edit
with it):

- Field **present** → replace its value with the backticked `<fork-point>`.
- Field **absent** → insert the line below immediately above `**Branch:**`,
  matching the `plan-create` template.
- Value **already equals** `<fork-point>` → no edit, no report line.

```markdown
**Base Branch:** `<fork-point>`
```

This is metadata about the branch this skill just created, so it is the one place
that can state it correctly. It does **not** override a deliberate stacked base:
if you branch from a live feature branch, `<fork-point>` *is* that feature branch
and the PR still targets it.

Report the change on one line, so a surprising target is visible before any
phase runs:

```
Base branch: <old value or "(absent)"> -> <fork-point>   [plan updated]
```

### Special case: "implement here"

If `$ARGUMENTS` contains the phrase "implement here" (or the user says it), skip branch creation entirely and stay on the current branch. **Step 3b does not run** — the current branch is the *source* branch, so recording it as the base would make source == base and trip `plan-pr` Phase 1b guard 4 ("nothing to review"). The fork point of a branch this run did not create is not observable; leave the field alone.

---

## Step 4: Move to active/ and update status

**Only if the plan is currently in `pending/`** (skip if already in `active/`):

1. Move the file:
   ```bash
   git mv docs/development/plans/pending/<file> docs/development/plans/active/<file>
   ```

2. Edit the `**Status:**` field in the plan to `In Progress`.

3. Do **not** commit here. The rename, the `**Status:**` edit and Step 3b's `**Base Branch:**` edit ride along in the **Phase 1** commit (Step 5d), which is where they belong: the plan going active is part of starting the work, not a change of its own.

---

## Step 5a: Implement (Manual mode — default)

If auto mode is **not** enabled, walk the plan **phase by phase** by dispatching each phase to a background Agent and pausing for user confirmation between phases. The orchestrator never writes implementation code itself (see Hard Rule).

### Phase discovery

1. Parse the plan's `## Implementation Plan` section for all `### Phase N:` headings.
2. For each phase, extract: number, title, goal, tasks, files-modified, dependencies.
3. Skip phases where **all** tasks are already `- [x]` (completed).
4. Build an ordered list of remaining (incomplete) phases.

### Phase execution loop

For each incomplete phase, in order:

#### 1. Status update

Display to the user:
```
--- Phase N/M: <Title> ---
Goal: <goal>
Tasks: <count> | Files: <count>
```

#### 2. Launch background Agent

Launch a **background Agent** (`run_in_background: true`) with a self-contained prompt containing:

- Plan title and absolute file path
- Project conventions (CuPy import order, authorship, git safety, no `Co-Authored-By` trailers)
- Instruction to read the pipeline-engineering guides in `~/.claude/knowledge/data-pipeline-engineering/` (`README.md` index; apply `02`'s architecture patterns/checklist, `03` for statistical/analytics code, and `05` for code craftsmanship) and follow their principles while implementing
- **The plan's `## Definitions` and `### Architecture & Module Contracts` sections, plus the standing rules from the `_code-conventions` skill** — the agent must build **to these boundaries** (respect each module's "must NOT know about") and honour the conventions (config-driven, no hardcoded values/paths, layer agnosticism). If the task seems to require violating a boundary or convention, stop and report rather than working around it.
- The phase's goal, tasks, and files-modified (verbatim from the plan)
- A 2-3 sentence summary of what prior phase agents accomplished (for phases 2+)
- Explicit instructions to:
  - Implement all tasks in the phase
  - Update the plan doc: check off completed tasks (`- [x]`), fill `**Started:**` / `**Completed:**` timestamps
  - **Do not commit and do not stage.** The orchestrator commits the phase in Step 5d, after it has validated the result.
  - Report, as the last line of its output, `Checks: <what was run and the outcome>` — e.g. `ruff clean; pytest 412 passed` or `not run (phase is docs-only)`. The orchestrator copies this verbatim into the phase commit body.

#### 3. Post-phase validation

After the agent returns:
- Run `git status` to verify files were actually changed.
- If **no changes** detected: warn the user, **stop the loop**.
- If the agent reported an **error or blocker**: display it, **stop the loop**.

#### 4. Phase commit

Run **Step 5d** for this phase. On a commit failure, stop the loop — do not
advance to the gate with the phase half-recorded.

#### 5. User confirmation gate

Display a summary of the phase's changes (`git show --stat HEAD`) and ask the user:

```
Phase N complete — committed <short-hash> <type>(<scope>): <subject>
Continue to Phase N+1? (yes / no)
```

- **yes** → extract a 2-3 sentence summary of what the phase agent did, feed it as prior context to the next phase agent, and proceed.
- **no / abort / anything else** → stop. Plan stays in `active/` with current progress; the user can resume later by re-running `/plan-implement <plan-name>` (skipped checkboxes are honoured).

#### 6. File tracking

After each phase commit, run:
```bash
git show --name-only --format= HEAD      # paths the phase commit recorded
git status --porcelain                   # anything the phase left behind
```
Add all paths from the first command to a running **modified-files set** (deduplicated across phases). Carry this set forward to the next phase. Any path from the second command that is **not** in the `pre-existing` set is a straggler the phase commit missed — list it for the user before the gate.

Under `no-phase-commit` there is no commit to read, so fall back to `git diff --name-only HEAD` plus untracked paths from `git status --porcelain`.

#### 7. Loop

Continue until all phases are complete or the user stops the loop.

After all phases complete in manual mode:

- Write accumulated modified-file list to the plan document (see Step 5c).
- If the `commit` flag was set: automatically invoke `/plan-commit <plan-name> auto` (same as auto mode Step 6).
- Otherwise: the phase commits stand as the branch history, and the only thing left uncommitted is the `## Modified Files` edit from Step 5c. Say so explicitly, and point the user at `/plan-commit <plan-name>` for it.

---

## Step 5b: Implement (Auto mode)

If auto mode **is** enabled, execute all phases sequentially using background agents. After all phases complete, proceed to Step 6 for auto-commit.

### Phase discovery

1. Parse the plan's `## Implementation Plan` section for all `### Phase N:` headings.
2. For each phase, extract: number, title, goal, tasks, files-modified, dependencies.
3. Skip phases where **all** tasks are already `- [x]` (completed).
4. Build an ordered list of remaining (incomplete) phases.

### Phase execution loop

For each incomplete phase:

#### 1. Status update

Display to the user:
```
--- Phase N/M: <Title> ---
Goal: <goal>
Tasks: <count> | Files: <count>
```

#### 2. Launch background Agent

Launch a **background Agent** (`run_in_background: true`) with a self-contained prompt containing:
- Plan title and absolute file path
- Project conventions (CuPy import order, authorship, git safety, no `Co-Authored-By` trailers)
- Instruction to read the pipeline-engineering guides in `~/.claude/knowledge/data-pipeline-engineering/` (`README.md` index; apply `02`'s architecture patterns/checklist, `03` for statistical/analytics code, and `05` for code craftsmanship) and follow their principles while implementing
- **The plan's `## Definitions` and `### Architecture & Module Contracts` sections, plus the standing rules from the `_code-conventions` skill** — the agent must build **to these boundaries** (respect each module's "must NOT know about") and honour the conventions (config-driven, no hardcoded values/paths, layer agnosticism). If the task seems to require violating a boundary or convention, stop and report rather than working around it.
- The phase's goal, tasks, and files-modified (verbatim from the plan)
- 2-3 sentence summary of what prior phase agents accomplished (for phases 2+)
- Explicit instructions to:
  - Implement all tasks in the phase
  - Update the plan doc: check off completed tasks (`- [x]`), fill `**Started:**` / `**Completed:**` timestamps
  - **Do not commit and do not stage.** The orchestrator commits the phase in Step 5d, after it has validated the result.
  - Report, as the last line of its output, `Checks: <what was run and the outcome>` — e.g. `ruff clean; pytest 412 passed` or `not run (phase is docs-only)`. The orchestrator copies this verbatim into the phase commit body.

#### 3. Post-phase validation

After the agent returns:
- Run `git status` to verify files were actually changed.
- If **no changes** detected: warn the user, **stop the auto loop**.
- If the agent reported an **error or blocker**: display it, **stop the auto loop**.

#### 4. Phase commit

Run **Step 5d** for this phase. On a commit failure, **stop the auto loop** and
report — an unattended run must not keep piling phases on top of a phase that
failed to record.

#### 5. Post-phase status

Display:
```
Phase N complete — committed <short-hash> <type>(<scope>): <subject>
Remaining: <count> phases
```

#### 6. Context passing

Extract a 2-3 sentence summary from the phase agent's output. Feed this to the next phase agent as prior context so it understands what was already done.

#### 7. File tracking

After each phase commit, run:
```bash
git show --name-only --format= HEAD      # paths the phase commit recorded
git status --porcelain                   # anything the phase left behind
```
Add all paths from the first command to a running **modified-files set** (deduplicated across phases). Carry this set forward to the next phase. Any path from the second command that is **not** in the `pre-existing` set is a straggler the phase commit missed — report it; do not stop the loop for it, Step 6's sweep will catch it.

Under `no-phase-commit` there is no commit to read, so fall back to `git diff --name-only HEAD` plus untracked paths from `git status --porcelain`.

---

## Step 5c: Write modified-files list to plan

After all phases complete (in **both** manual and auto modes), before committing, append or replace a `## Modified Files` section at the end of the plan document with the accumulated modified-files set:

```markdown
## Modified Files

<!-- auto-generated by /plan-implement — do not edit manually -->
- path/to/file_a.py
- path/to/file_b.py
- docs/development/plans/active/plan-name.md
```

Rules:
- If a `## Modified Files` section already exists in the plan, **replace** its content entirely.
- If no such section exists, **append** it at the end of the file.
- Sort paths alphabetically.
- Include the plan file itself if it was modified.
- This section is the canonical input for `/plan-commit` when it lists files to stage.

---

## Step 5d: Phase commit

Invoked **from inside** both phase loops (manual step 4, auto step 4), once per
phase, immediately after post-phase validation passes. Runs by default in both
modes; skipped only under `no-phase-commit`.

The orchestrator performs this itself with `Bash` — do **not** dispatch an Agent
and do **not** call `/plan-commit`. `plan-commit` is plan-scoped and interactive;
a phase commit is a narrow, mechanical recording of one already-validated phase.

### 1. Determine the file set

```bash
git status --porcelain      # staged + unstaged + untracked, all of it
```

From those paths, build the commit set:

| Rule | Action |
|------|--------|
| Path is in the `pre-existing` set (Step 3) | **Exclude** — unless this phase's files-modified list names it, in which case include it and say so |
| Path matches `.env*`, `*credentials*`, `*secret*`, `*key*` | **Stop.** Do not commit, do not exclude-and-continue. Report and let the user resolve it |
| The plan document | **Include** — the agent ticked its checkboxes and timestamps, and that record belongs with the phase it describes |
| Anything else dirty | Include |

Do not filter to the phase's declared files-modified list. An agent that
legitimately touched a file the plan did not anticipate must still have that
file recorded in the phase that caused it — otherwise it silently drifts into a
later phase's commit and the review boundary you wanted is gone.

Stage explicitly, never wholesale:

```bash
git add <path1> <path2> ...      # never `git add .` or `git add -A`
git diff --cached --stat         # confirm before committing
```

If the commit set is **empty** after exclusions, do not create an empty commit.
Report it and handle it as the no-changes case for the calling loop (stop).

### 2. Compose the message

Conventional Commits, per `_commit-procedure`. Infer the **type from the phase**,
not from the plan as a whole — a docs phase is `docs`, a test-only phase is
`test`, a restructuring phase is `refactor`. This per-phase typing is a large
part of what makes the history readable.

```bash
git commit -m "$(cat <<'EOF'
<type>(<scope>): <phase subject, lowercase imperative>

Phase <N>/<M> of <plan title>.

<the phase's Goal line>

- <task N.1 text>
- <task N.2 text>

Checks: <the agent's Checks: line, verbatim>
Plan: <plan file path>
EOF
)"
```

- **scope**: derived from the branch name (`feature/strategy-v2-scb-chain-alignment` → `strategy-v2`)
- **subject**: the phase title, imperative and lowercase, under 50 chars where possible
- **No `Co-Authored-By` trailer.** Basil Duvernoy authorship only

### 3. Verify and report

```bash
git log -1 --stat
```

Return the short hash and subject to the calling loop for its status line.

### 4. Failure handling

| Situation | Behaviour |
|-----------|-----------|
| Commit hook rejects the commit | Display stderr verbatim, **do not retry**, stop the loop. The orchestrator must not edit files to satisfy a hook — that is implementation work, dispatch an Agent or hand back to the user |
| Sensitive path in the dirty set | Stop before staging anything. Report the path |
| Empty commit set | No commit; treat as no-changes, stop the loop |
| Current branch is not the plan's branch | Stop. Never commit a phase to the wrong branch |

### On phases that are not independently green

A phase commit is a **review boundary, not a release**. Phases that split an
accessor from its call sites, or an interface from its consumers, will produce
intermediate commits that do not pass `pytest` on their own. That is expected and
is the price of the boundary. Do not reorder phases, merge them, or delay a
commit to manufacture a green intermediate — record the truth in the `Checks:`
line and move on.

---

## Step 6: Final summary and auto-commit

This step runs when the `auto` flag or the `commit` flag is set. It does **not** run in plain manual mode (no flags).

### 6a. Invoke plan-commit

With per-phase commits active, the phases are already recorded. This step is a
**sweep**, not the commit: it picks up whatever is left — normally just the
`## Modified Files` edit from Step 5c, plus any straggler the phase loop flagged.

First check:

```bash
git status --porcelain
```

- **Clean tree, or only `pre-existing` paths dirty** → skip `/plan-commit` entirely and report `Final sweep: nothing to commit — all N phases are already committed.` This is a **success**. Do not treat `plan-commit`'s clean-tree stop as an error, and do not invoke it just to receive one.
- **Otherwise** → automatically invoke `/plan-commit <plan-name> auto`:
  - This call inherits the plan name from Step 1
  - Runs in auto mode (no confirmation prompts)
  - Uses the `## Modified Files` section written in Step 5c as the authoritative file list
  - Generates a conventional commit message and commits
  - Display the `/plan-commit` result (commit hash, message, final status)

Under `no-phase-commit` this step is the only commit and behaves as it always did.

If `/plan-commit` encounters an error (e.g., sensitive files, branch mismatch):
- Display the error
- Suggest manual review: "Run `git status` and `/plan-commit <plan-name>` manually if needed"
- Do **not** stop or fail — the phases are complete; commit is a follow-up step

### 6b. Final summary

Display:

```
--- plan-implement complete ---
Plan: <title>
Branch: <branch>
Mode: <auto|manual> + commit
Phases completed: N/N
Modified files: <count> (see ## Modified Files in plan)
Phase commits:
  <hash> <type>(<scope>): <phase 1 subject>
  <hash> <type>(<scope>): <phase 2 subject>
  ...
Final sweep: <hash> <type>(<scope>): <subject> | nothing to commit

Review one phase at a time:  git log --oneline <base-branch>..<branch>
                             git show <hash>

Plan remains in active/ with status "In Progress". Review, test, then run /plan-finish when ready.
```

If no `commit` flag (manual mode without commit):

```
--- plan-implement complete ---
Plan: <title>
Branch: <branch>
Mode: manual (no final sweep)
Phases completed: N/N
Modified files: <count> (see ## Modified Files in plan)
Phase commits:
  <hash> <type>(<scope>): <phase 1 subject>
  ...

Review one phase at a time:  git log --oneline <base-branch>..<branch>
                             git show <hash>

Still uncommitted: the ## Modified Files edit from Step 5c<, plus: ...>.
Run /plan-commit <plan-name> when ready.
```

Under `no-phase-commit`, replace the phase-commit block with
`Changes are uncommitted. Review with git diff, then run /plan-commit <plan-name> when ready.`

**Does NOT** mark the plan as completed or call `/plan-finish`. The plan stays in `active/` with status `In Progress` so the user can review, test, and make further changes before finishing.

If Step 7 will run (`pr` set, or `auto` without `no-pr`), append to either summary:

```
Peer review: dispatching plan-pr (Step 7) — <will ask before opening the PR | auto mode, opening without confirmation>
```

---

## Step 7: Submit for peer review (only if `pr` flag)

Runs when the `pr` flag is present, **or** when `auto` is present without
`no-pr`. Under `auto` it runs unattended — see 7b.

### Preconditions — all must hold, else skip Step 7 and say why

1. All phases completed (the loop was not stopped by an error, a no-change
   phase, or a user "no").
2. Step 6a either **succeeded** or **legitimately skipped** (clean tree — every
   phase already committed). A `/plan-commit` that errored is a skip; a
   `/plan-commit` that was never needed is not.
3. `git status --porcelain` is empty, or contains only `pre-existing` paths. This
   is the real gate — a PR cannot be opened over uncommitted work.

On a skip, print: `Peer review skipped: <reason>. Run /plan-pr manually when ready.`

### Why this is split across two Agents

`plan-pr` has a **user approval gate** before anything is pushed (its Phase 3c).
A background Agent cannot talk to the user, so the gate lives with the
orchestrator: Agent #1 composes, the orchestrator handles 7b, Agent #2 executes.

Keep the split in **both** modes. Under `auto` the gate is pre-authorized rather
than removed, and the split is what still gives the user a transcript record of
exactly what was published, plus a clean stop point when preflight fails —
before any push has happened. Never collapse Step 7 into one Agent.

`plan-pr` sets `disable-model-invocation: true`. Do **not** call it as a skill —
dispatch Agents that **read** `~/.claude/skills/plan-pr/SKILL.md` (or the
project-local `.claude/skills/plan-pr/SKILL.md` if it exists) and follow its
procedure, exactly as phase agents are told to read the conventions guides.

### 7a. Compose Agent (background, read-only)

Launch a background Agent (`run_in_background: true`) with a self-contained
prompt containing:

- Instruction to read `~/.claude/skills/plan-pr/SKILL.md` and execute
  **Phases 0, 1, 2 and 3 only — in delegated `compose` mode**.
- The plan title and absolute plan file path (so it skips branch-based inference).
- The `<source-branch>` from Step 3.
- Explicit prohibitions: **do not** `git push`, **do not** run `gh pr create`,
  **do not** edit any repo file. The only write permitted is the PR body temp
  file outside the repo.

Require the Agent to return, verbatim:

```
Preflight:    OK | FAILED (<reason>)
Head → Base:  <source-branch> → <base-branch>
Existing PR:  none | open <url> | closed <url>
Title:        <title>
Body file:    <absolute temp path>
Commits:      <n>
Files:        <n> (+<add>/-<del>)

<full body markdown>
```

If `Preflight: FAILED`, display the reason and **stop Step 7**. Do not retry and
do not work around the failed gate.

### 7b. Approval gate (orchestrator, in the chat)

Behaviour depends on the mode. In both cases, first display the Agent's returned
block to the user **in full**.

#### Attended (`pr` without `auto`) — ask

```
Open this PR against <base-branch>? (yes / edit / no)
```

- **yes** → proceed to 7c.
- **edit** → take the user's revisions to the title/body, rewrite the temp body
  file, re-display, ask again.
- **no / anything else** → stop. Report that the branch was **not** pushed and
  that `/plan-pr` can be run manually later. This is not a failure.

#### Unattended (`auto`) — do not ask

Print the block followed by:

```
auto mode — opening this PR without confirmation.
```

Then go **straight to 7c**. Do not ask, do not wait, do not offer `edit`. The
`auto` flag is the user's standing authorization for this run; treating it as
anything else would stall an invocation whose entire purpose is to finish
unattended.

The display is still mandatory — it is the user's record of what was published,
and the only place the composed body appears before it exists on GitHub.

The orchestrator may write the temp body file itself — it is outside the repo, so
the Hard Rule (which governs repo files) does not apply.

### 7c. Execute Agent (background)

Reached on an explicit **yes** (attended) or immediately (unattended). Launch a
second background Agent with:

- Instruction to read `~/.claude/skills/plan-pr/SKILL.md` and execute
  **Phases 4, 5 and 6 only — in delegated `execute` mode**.
- The approved `<title>`, the body temp file path, `<source-branch>`,
  `<base-branch>`, the existing-PR state from 7a, and whether `draft` applies.
- Explicit prohibitions, repeated verbatim from `plan-pr`'s hard rules:
  **never force-push**; **never merge, rebase, checkout another branch or delete
  a branch**; on a rejected push, stop and report rather than resolving it.
- A requirement that its Phase 6 output **end with `plan-pr`'s "how to review
  this PR" block**, reproduced from the composed body's `## Review order`
  section — not summarised, not omitted when the diff is small.
- One of these two authorization statements, verbatim — the Agent refuses if
  neither is present:
  - Attended: `Approval granted: the user answered yes at the orchestrator's gate.`
  - Unattended: `Approval granted: auto mode — standing authorization, no gate was run.`

Under `auto`, the Agent must also be told that Phase 4a's questions have no one
to answer them, and how to resolve each without asking:

| Phase 4a finding | Unattended behaviour |
|---|---|
| No PR | Normal path — push, create the PR |
| **Open** PR for this branch | Push (this updates the PR's diff, which is the intent of a re-run) but **leave the existing body untouched**. Report the URL and state plainly that the body was not rewritten. |
| **Closed or merged** PR for this branch | **Stop and report.** Do not create a second PR. `auto` authorizes opening the intended PR, not deciding to re-open closed work. |

Step 7d surfaces a stop here as an incomplete PR step. Silence is not consent for
the closed/merged case.

### 7d. Report

Display the Agent's Phase 6 report verbatim — **including its "how to review this
PR" block**, which is the whole reason an unattended run still ends in the chat
rather than only on GitHub. Then:

```
--- plan-implement + peer review complete ---
PR:           <url>
Head → Base:  <source-branch> → <base-branch>
Reviewers:    none assigned — assign on GitHub

Plan remains in active/. The merge happens on GitHub.
Once the PR is merged there, run:  /plan-finish <plan-name>
It auto-detects the merged PR and syncs (pull + bookkeep + cleanup, no local merge).
```

If the Execute Agent reports a push rejection or `gh pr create` failure, display
stderr verbatim, state clearly whether the branch was pushed, and stop.

---

## Edge Cases

| Situation | Behavior |
|-----------|----------|
| Plan already in `active/` | Skip move (Step 4), go to branch + implement |
| Current branch is `main` | Refuse with clear message, do not proceed |
| `$ARGUMENTS` contains "implement here" | Skip branch creation (Step 3) **and** Step 3b — the current branch is the source branch, not a base |
| Branch name from plan already exists | Ask user: switch to it or abort? On "switch", skip Step 3b — this run did not cut the branch and cannot observe its fork point |
| Plan's `**Base Branch:**` names a branch that was merged and deleted | Step 3b overwrites it with `<fork-point>`. This is the fix for `plan-pr` preflight failing on a base that is no longer on `origin` |
| Plan has no `**Base Branch:**` field at all | Step 3b inserts it above `**Branch:**` rather than leaving `plan-pr` to fall back to `dev` |
| Plan's `**Base Branch:**` already equals `<fork-point>` | No edit, no report line |
| Plan not found | List available plans, stop |
| Uncommitted changes present | Warn user, list files, then proceed (changes travel with checkout) |
| Orchestrator about to call `Edit`/`Write` on a non-plan file | Stop, dispatch a background Agent for that change instead (Hard Rule) |
| Manual mode + phase agent produces no changes | Warn, stop loop, leave plan as-is |
| Manual mode + phase agent reports error | Display error, stop loop |
| Manual mode + user answers "no" at confirmation gate | Stop loop; plan stays in `active/`. Progress is **committed**, not just preserved — phases 1..N are already in the history and a resume starts clean |
| Manual mode + phases complete | Write `## Modified Files` to plan; phases are already committed; that one edit is the only thing left for `/plan-commit` |
| Phase commit: commit hook rejects | Display stderr verbatim, **do not retry**, stop the loop. Never edit files to satisfy a hook |
| Phase commit: sensitive path dirty (`.env*`, `*secret*`, …) | Stop before staging anything. Report the path; do not silently exclude it |
| Phase commit: empty set after exclusions | No commit, no empty commit. Treated as the no-changes case → stop the loop |
| Phase commit: unrelated file was already dirty before Step 3 | It is in the `pre-existing` set, so it is excluded from every phase commit — unless a phase's files-modified list names it |
| Phase commit: agent touched a file the plan did not list | **Committed with that phase anyway.** Recording it in the phase that caused it is the point; the alternative is silent drift into a later commit |
| Phase leaves a straggler after its commit | Manual: list it before the gate. Auto: report and continue — Step 6a's sweep catches it |
| `no-phase-commit` | Reverts to the pre-2026-07 behaviour: nothing commits until Step 6, and Step 6 needs `commit`/`auto` to run at all |
| Manual mode + `commit` flag + phases complete | Write `## Modified Files` to plan; auto-invoke `/plan-commit <plan-name> auto` |
| Manual mode + re-run after interruption | Resumes from first incomplete phase (checkbox state) |
| `auto` + phase agent produces no changes | Warn, stop auto loop |
| `auto` + phase agent reports error | Display error, stop auto loop |
| `auto` + all phases complete | Write `## Modified Files` to plan; run the Step 6a sweep (skipped as a success if the tree is already clean) |
| `auto` + plan-commit error | Display error, suggest manual `/plan-commit`, do not fail |
| `auto` + re-run after interruption | Resumes from first incomplete phase (checkbox state) |
| `commit` without `auto` | Behaves like manual mode, plus the Step 6a sweep at the end |
| `auto` alone | Implies `commit` **and** `pr`: all phases, commit, PR opened with **no approval gate** |
| `auto no-pr` | Unattended phases + commit, Step 7 skipped entirely |
| `pr` and `no-pr` both passed | Report the contradiction, stop |
| `auto` + composed PR displayed | Display is mandatory (the user's record) but non-blocking — proceed straight to 7c |
| `auto` + **open** PR already exists for the branch | Push to update its diff, **leave the existing body untouched** (no one to approve an overwrite), report the URL and say the body was not rewritten |
| `auto` + **closed or merged** PR exists for the branch | **Stop Step 7 and report.** `auto` authorizes opening the intended PR, not deciding to re-open work that was already closed |
| `pr` without `auto` | Behaves like manual mode, auto-commits, then runs Step 7 **with** the approval gate |
| `pr` + plan-commit failed | Skip Step 7 entirely, report why, suggest manual `/plan-pr` |
| `pr` + loop stopped early (error / no changes / user "no") | Skip Step 7 — phases are incomplete, nothing to review |
| `pr` + Compose Agent returns `Preflight: FAILED` | Display the gate that failed, stop Step 7, do not retry |
| `pr` + user answers "no" at the 7b approval gate | Stop. Branch **not** pushed. Not a failure — report it plainly |
| `pr` (attended) + open PR already exists | Agent #2 pushes to update it instead of creating a duplicate; asks before overwriting its body; reports the existing URL |
| `pr` + push rejected (non-fast-forward) | Stop. Never force-push. Report and leave resolution to the user |
| Phase agent touches no new files, only edits ones a prior phase already changed | Normal. The phase still gets its own commit; the modified-files set simply does not grow |

---

## Important Project Constraints

- **Pipeline-engineering guides:** Every phase agent prompt must instruct the agent to read `~/.claude/knowledge/data-pipeline-engineering/` (`README.md` index → `02` architecture patterns/checklist, `03` statistical/scientific software, `05` code craftsmanship) and follow their principles while implementing.
- **One phase, one commit:** the unit of review is the phase. Never let two phases share a commit, and never split one phase across two — a plan with N phases produces N commits plus at most one sweep. If a phase is too large to review as one commit, that is a signal the *plan* needed another phase boundary; say so rather than splitting the commit.
- **Authorship:** All commits by Basil Duvernoy only. Never add `Co-Authored-By` trailers.
- **Merge strategy:** Always `--no-ff` unless user explicitly says "fast-forward".
- **CuPy import order:** Import CuPy before any `preprocessing` package imports.
- **Git safety:** Run `git status` before any operation that touches the working tree.
