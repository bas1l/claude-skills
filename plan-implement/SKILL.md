---
name: plan-implement
description: "Start implementing a plan: read it, move to active/, create a branch, and dispatch implementation to a background agent (the calling agent never writes implementation code itself)"
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
- Editing **only** the plan document itself for skill-level metadata (the `**Status:**` field in Step 4, and the move from `pending/` to `active/`)
- Launching `Agent` calls and reading their results

Any task in the plan — even a one-line change — is delegated. If the orchestrator finds itself about to call `Edit` or `Write` on a non-plan file, it must stop and dispatch an Agent instead. This rule applies in **both** manual and auto modes.

---

## Argument Parsing

Split `$ARGUMENTS` on whitespace. Scan all tokens for recognised flags and remove them; rejoin remaining tokens as the plan name. The `implement here` detection (Step 3) still applies to the remaining tokens.

Recognised flags (order-independent, combinable):

| Flag | Effect |
|------|--------|
| `auto` | Auto mode — dispatch all phases without pausing for confirmation |
| `commit` | Auto-commit — invoke `/plan-commit` automatically after all phases complete |

- **Manual mode** (default, no `auto`): dispatches **one phase at a time** to a background Agent, then pauses for user confirmation before the next phase
- **Auto mode** (`auto` flag present): dispatches all phases sequentially via background Agents with no pauses
- **`commit` flag**: triggers auto-commit after all phases complete, in either mode. `auto` implies `commit` (auto mode always auto-commits).

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

1. Run `git status` to detect uncommitted changes. If present, warn the user and list them — uncommitted changes will travel with the checkout.
2. If the branch from the plan **already exists**, ask the user whether to switch to it or abort.
3. Otherwise, create the branch: `git checkout -b <branch-name>`

### Special case: "implement here"

If `$ARGUMENTS` contains the phrase "implement here" (or the user says it), skip branch creation entirely and stay on the current branch.

---

## Step 4: Move to active/ and update status

**Only if the plan is currently in `pending/`** (skip if already in `active/`):

1. Move the file:
   ```bash
   git mv docs/development/plans/pending/<file> docs/development/plans/active/<file>
   ```

2. Edit the `**Status:**` field in the plan to `In Progress`.

3. Do **not** commit. Leave the plan file as an unstaged change — the user will commit after reviewing all implementation changes.

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
- The phase's goal, tasks, and files-modified (verbatim from the plan)
- A 2-3 sentence summary of what prior phase agents accomplished (for phases 2+)
- Explicit instructions to:
  - Implement all tasks in the phase
  - Update the plan doc: check off completed tasks (`- [x]`), fill `**Started:**` / `**Completed:**` timestamps
  - **Do not commit.** Leave changes unstaged for the user to review.

#### 3. Post-phase validation

After the agent returns:
- Run `git status` to verify files were actually changed.
- If **no changes** detected: warn the user, **stop the loop**.
- If the agent reported an **error or blocker**: display it, **stop the loop**.

#### 4. User confirmation gate

Display a summary of the phase's changes (e.g. `git status` / `git diff --stat`) and ask the user:

```
Phase N complete. Continue to Phase N+1? (yes / no)
```

- **yes** → extract a 2-3 sentence summary of what the phase agent did, feed it as prior context to the next phase agent, and proceed.
- **no / abort / anything else** → stop. Plan stays in `active/` with current progress; the user can resume later by re-running `/plan-implement <plan-name>` (skipped checkboxes are honoured).

#### 5. File tracking

After each phase, run:
```bash
git diff --name-only HEAD
```
Add all returned paths to a running **modified-files set** (deduplicated across phases). Carry this set forward to the next phase.

#### 6. Loop

Continue until all phases are complete or the user stops the loop.

After all phases complete in manual mode:

- Write accumulated modified-file list to the plan document (see Step 5c).
- If the `commit` flag was set: automatically invoke `/plan-commit <plan-name> auto` (same as auto mode Step 6).
- Otherwise: leave changes uncommitted. The user reviews and commits manually (typically via `/plan-commit <plan-name>`).

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
- The phase's goal, tasks, and files-modified (verbatim from the plan)
- 2-3 sentence summary of what prior phase agents accomplished (for phases 2+)
- Explicit instructions to:
  - Implement all tasks in the phase
  - Update the plan doc: check off completed tasks (`- [x]`), fill `**Started:**` / `**Completed:**` timestamps
  - **Do not commit.** Leave changes unstaged — Step 6 handles the commit after all phases finish.

#### 3. Post-phase validation

After the agent returns:
- Run `git status` to verify files were actually changed.
- If **no changes** detected: warn the user, **stop the auto loop**.
- If the agent reported an **error or blocker**: display it, **stop the auto loop**.

#### 4. Post-phase status

Display:
```
Phase N complete.
Remaining: <count> phases
```

#### 5. Context passing

Extract a 2-3 sentence summary from the phase agent's output. Feed this to the next phase agent as prior context so it understands what was already done.

#### 6. File tracking

After each phase, run:
```bash
git diff --name-only HEAD
```
Add all returned paths to a running **modified-files set** (deduplicated across phases). Carry this set forward to the next phase.

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

## Step 6: Final summary and auto-commit

This step runs when the `auto` flag or the `commit` flag is set. It does **not** run in plain manual mode (no flags).

### 6a. Invoke plan-commit

Automatically invoke `/plan-commit <plan-name> auto` to commit all plan-related changes:

- This call inherits the plan name from Step 1
- Runs in auto mode (no confirmation prompts)
- Uses the `## Modified Files` section written in Step 5c as the authoritative file list
- Generates a conventional commit message and commits
- Display the `/plan-commit` result (commit hash, message, final status)

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
Commit: <hash> <type>(<scope>): <subject>

Plan remains in active/ with status "In Progress". Review, test, then run /plan-finish when ready.
```

If no `commit` flag (manual mode without commit):

```
--- plan-implement complete ---
Plan: <title>
Branch: <branch>
Mode: manual (no auto-commit)
Phases completed: N/N
Modified files: <count> (see ## Modified Files in plan)

Changes are uncommitted. Review with `git diff`, then run /plan-commit <plan-name> when ready.
```

**Does NOT** mark the plan as completed or call `/plan-finish`. The plan stays in `active/` with status `In Progress` so the user can review, test, and make further changes before finishing.

---

## Edge Cases

| Situation | Behavior |
|-----------|----------|
| Plan already in `active/` | Skip move (Step 4), go to branch + implement |
| Current branch is `main` | Refuse with clear message, do not proceed |
| `$ARGUMENTS` contains "implement here" | Skip branch creation (Step 3) |
| Branch name from plan already exists | Ask user: switch to it or abort? |
| Plan not found | List available plans, stop |
| Uncommitted changes present | Warn user, list files, then proceed (changes travel with checkout) |
| Orchestrator about to call `Edit`/`Write` on a non-plan file | Stop, dispatch a background Agent for that change instead (Hard Rule) |
| Manual mode + phase agent produces no changes | Warn, stop loop, leave plan as-is |
| Manual mode + phase agent reports error | Display error, stop loop |
| Manual mode + user answers "no" at confirmation gate | Stop loop; plan stays in `active/` with progress preserved |
| Manual mode + phases complete | Write `## Modified Files` to plan; leave changes uncommitted; user commits manually via `/plan-commit` |
| Manual mode + `commit` flag + phases complete | Write `## Modified Files` to plan; auto-invoke `/plan-commit <plan-name> auto` |
| Manual mode + re-run after interruption | Resumes from first incomplete phase (checkbox state) |
| `auto` + phase agent produces no changes | Warn, stop auto loop |
| `auto` + phase agent reports error | Display error, stop auto loop |
| `auto` + all phases complete | Write `## Modified Files` to plan; auto-invoke `/plan-commit <plan-name> auto` |
| `auto` + plan-commit error | Display error, suggest manual `/plan-commit`, do not fail |
| `auto` + re-run after interruption | Resumes from first incomplete phase (checkbox state) |
| `commit` without `auto` | Behaves like manual mode but auto-commits at the end |
| Phase agent touches no new files | `git diff --name-only HEAD` returns empty; previous set unchanged; no warning needed |

---

## Important Project Constraints

- **Authorship:** All commits by Basil Duvernoy only. Never add `Co-Authored-By` trailers.
- **Merge strategy:** Always `--no-ff` unless user explicitly says "fast-forward".
- **CuPy import order:** Import CuPy before any `preprocessing` package imports.
- **Git safety:** Run `git status` before any operation that touches the working tree.
