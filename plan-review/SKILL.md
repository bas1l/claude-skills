---
name: plan-review
description: "Review implementation against a plan spec: verify tasks, audit files, check call-sites, detect scope creep, and generate a structured report"
allowed-tools:
  - Bash
  - Read
  - Glob
  - Grep
  - Agent
---

# Plan Review

This skill reviews an implementation against the plan specification. It is
**read-only** — no file edits, no commits, no branch changes.

It receives `$ARGUMENTS` in the format: `<plan-name> [phase N] [phase M] ... | [all]`.

---

## Argument Parsing

Split `$ARGUMENTS` on whitespace.

1. If the token `all` appears, enable **all-phases mode** and remove it.
2. Collect any tokens matching `phase` followed by a number (e.g., `phase 1`,
   `phase 3`). Record the phase numbers, remove those token pairs.
3. Rejoin remaining tokens as the **plan name**.

| Input | Result |
|-------|--------|
| `split-analysis all` | plan=`split-analysis`, scope=all phases |
| `split-analysis phase 1 phase 3` | plan=`split-analysis`, scope=phases 1 and 3 |
| `split-analysis` | plan=`split-analysis`, scope=completed phases only |

---

## Step 1: Locate the plan

Follow the procedure in `.claude/skills/_plan-resolve/SKILL.md` to resolve the
plan identifier. Search directories: `active/`, `pending/`, `completed/`.

Apply `_plan-resolve` fail-fast rules: stop on AMBIGUOUS or NOT_FOUND.

If found in **pending/** -- warn: "Plan is in pending/ -- no implementation
likely exists yet." Continue anyway (the user may have a reason).

Display: title, location (directory), status, branch.

---

## Step 2: Read plan and extract structure

Read the full plan document. Parse and extract:

- **Title** — from the `# Plan:` heading
- **Status** — from the `**Status:**` field
- **Branch** — from the `**Branch:**` field (strip backticks)
- **Success Criteria** — all items under the `## Success Criteria` section
- **Out of Scope** — all items under the `## Out of Scope` section
- **Implementation Plan phases** — for each `### Phase N:` section:
  - Phase number and title
  - Goal (from `**Goal:**`)
  - `**Started:**` and `**Completed:**` timestamps
  - Tasks (checkbox items `- [x]` / `- [ ]`)
  - Files Modified (the file list under `**Files Modified:**`)
- **Testing Plan** — items under the `## Testing Plan` section
- **Documentation Plan** — items under the `## Documentation Plan` section
- **Definitions** — term → meaning pairs under the `## Definitions` section (load-bearing terms the implementation must not silently reinterpret)
- **Module Contracts** — the rows of the `### Architecture & Module Contracts` table (module · responsibility · inputs→outputs · must NOT know about)

If any of these sections are missing, note it and skip the corresponding checks
later.

---

## Step 3: Determine review scope

| Input | Scope |
|-------|-------|
| No phase args, no `all` | Phases with `**Completed:**` timestamp filled **or** all tasks `[x]` |
| `phase 1 phase 3` | Only those specific phases |
| `all` | Every phase |

- If the computed scope is **empty** (no completed phases, no explicit
  selection) → report: "No completed phases found. Use `phase N` to review a
  specific phase, or `all` to review everything." **Stop.**
- Display which phases are **in scope** and which are **skipped**.

---

## Step 4: Determine git diff baseline

1. Read the `**Branch:**` field from the plan.
2. Check if the branch exists: `git branch --list <branch>`.
3. If branch exists:
   - Compute merge base: `git merge-base dev <branch>`
   - Get changed files: `git diff --name-only <merge-base>..<branch>`
   - Get diff stat: `git diff --stat <merge-base>..<branch>`
   - Save the `changed_files` list and `merge_base` hash.
4. If branch **not found** (merged/deleted) or `git merge-base` **fails**:
   - Switch to **file-read-only mode**.
   - The `changed_files` list will be empty — file audits will read files
     directly instead of relying on diff.
   - Note reduced confidence in the report header.

**Never checkout or switch branches.** All operations use explicit refs.

---

## Step 5: Per-phase review (parallel background Agents)

Launch one **background Agent per phase** in scope. Each agent receives:

- Plan title, branch, file path
- Phase number, title, goal, tasks, files-modified (verbatim from the plan)
- The `changed_files` list from Step 4 (or note that file-read-only mode is active)
- Out of Scope items (for scope creep detection)
- The plan's **Definitions** and **Module Contracts**, plus the standing rules from the `_code-conventions` skill
- Project conventions: CuPy must be imported before preprocessing packages

Each agent performs the checks below and returns structured results.

### 5a. Task verification

For each task in the phase:

- `[x]` (claimed complete) → read relevant files, verify the work was done:
  - **VERIFIED** — evidence found in code
  - **UNCERTAIN** — could not confirm; include reason
  - **NOT FOUND** — no evidence at all
- `[ ]` (claimed incomplete) → check if done anyway:
  - **INCOMPLETE (expected)** — task genuinely not done
  - **DONE-BUT-UNCHECKED** — work appears done but checkbox not ticked

### 5b. Files Modified audit

For each file listed in the phase's Files Modified:
- Does the file exist?
- Is it in `changed_files`? (skip this check in file-read-only mode)
- Verdict: **OK** / **LISTED-BUT-UNCHANGED** / **FILE-NOT-FOUND**

For files in `changed_files` not listed in **any** phase's Files Modified:
- Flag as **UNLISTED-CHANGE** (consolidated in Step 6)

### 5c. Code quality spot-check

For each modified file in the phase:
- **CuPy import order:** if the file imports both `cupy` and anything from
  `preprocessing`, verify CuPy is imported first. Flag violations.
- **TODO/FIXME/HACK markers:** search for these in the file, flag any found.
- **Consistency with plan:** does the file's actual role match what the plan
  describes?

### 5d. Call-site consistency / ripple-effect analysis

This is the **most critical** review check — a stale caller is a runtime error
waiting to happen.

For each modified file in the phase:
1. Identify changed function signatures, class constructors, method APIs,
   renamed/removed parameters (compare against the diff or read the file and
   cross-reference with the plan's task descriptions).
2. Search the codebase (using Grep) for all callers of each changed
   function/method.
3. Check whether callers have been updated to match the new signature.
4. Verdict per finding:
   - **CALLER-UPDATED** — caller uses the new signature
   - **CALLER-STALE** — caller still uses old signature (include file:line)
   - **CALLER-MISSING** — function was removed but is still called somewhere

### 5e. Scope creep detection

For files changed (in `changed_files`) but not listed in this phase's Files
Modified:
- Cross-reference against Out of Scope items.
- Flag potential scope violations.

### 5f. Boundary & convention adherence (review at the seam)

Architecture drift and hardcoding are this user's most frequent source of rework, so check them
explicitly:
- **Module boundaries:** for each row of the plan's Module Contracts, verify the implementation
  respects it — especially the **"must NOT know about"** column. A module or base class that
  references a concrete field, label, country, or path it was meant to be agnostic to →
  **BOUNDARY-VIOLATION** (include file:line).
- **Load-bearing terms:** verify behaviour matches the plan's `## Definitions`, not a reinterpretation
  of the term → **TERM-DRIFT**.
- **Conventions (`_code-conventions`):** flag hardcoded values/paths that belong in config, data baked
  in instead of fetched from the source of truth, and one-file-many-concerns violations →
  **CONVENTION-VIOLATION** (name the rule). The sanctioned exception is a labelled config block at the
  top of a workflow `main()`.

> 💡 For a visual current-vs-implemented comparison of the module boundaries, run `/arch-diff <plan>`
> (optional; not automatic).

---

## Step 6: Plan-level cross-checks (main context, after agents return)

After all phase agents complete, perform these checks in the main context:

### Success Criteria

For each item under Success Criteria:
- **COVERED** — evidence exists in the reviewed phases
- **PARTIALLY COVERED** — some but not all aspects addressed
- **NOT COVERED** — no evidence found
- **CANNOT ASSESS** — insufficient information to determine

### Testing Plan

For each item under Testing Plan:
- **TEST EXISTS** — a corresponding test file/function was found
- **NO TEST FILE** — expected test not found
- **MANUAL** — item is a manual verification step (no automated test expected)

### Documentation Plan

For each item under Documentation Plan:
- **UPDATED** — the referenced doc was changed (in `changed_files` or has
  relevant content)
- **NOT UPDATED** — no evidence of the doc change

### Unlisted files summary

Consolidate all files from `changed_files` that do not appear in **any**
phase's Files Modified section. List them with a brief note.

---

## Step 7: Generate review report

Display the report in this format:

```
=== PLAN REVIEW: <Title> ===
Branch: <branch> | Status: <status> | Location: <directory>
Diff baseline: <merge-base-hash> (or "file-read-only mode")
Review scope: Phase 1, Phase 2 (of N total)

--- Phase 1: <Title> ---
Goal: <goal>

Tasks:
  [x] VERIFIED   Task 1.1 — description
  [x] UNCERTAIN  Task 1.2 — description
                 ^ Could not confirm: <reason>

Files Audit:
  OK       path/to/file.py (listed + changed)
  WARNING  path/to/other.py (listed but NOT changed)

Code Issues:
  path/to/file.py:42 — TODO marker left in code

Call-Site Consistency:
  OK           module.function_name() — N callers, all updated
  STALE CALLER path/to/caller.py:87 — calls old_func(old_param=...) but param renamed to new_param=

Scope Creep: None detected

Boundaries & Conventions:
  BOUNDARY-VIOLATION   src/base_mapper.py:33 — base class references country label (contract: must be agnostic)
  CONVENTION-VIOLATION src/run.py:12 — hardcoded output path (belongs in config)
  TERM-DRIFT           behaviour of "intact" differs from the plan's Definition

--- Phase 2: <Title> ---
[... same structure ...]

=== PLAN-LEVEL CHECKS ===

Success Criteria:
  COVERED          "Criterion 1..."
  NOT COVERED      "Criterion 2..."

Testing Plan:
  NO TEST FILE     Unit test case 1
  MANUAL           Manual verification step 1

Documentation Plan:
  UPDATED          Update CLAUDE.md
  NOT UPDATED      Create user guide

Unlisted Files:
  path/to/unexpected.py — not in any phase

=== SUMMARY ===
Phases reviewed: N/M
Tasks: X verified, Y uncertain, Z not found
Files: A OK, B warning, C unlisted
Call-site issues: D stale callers
Code issues: E
Scope creep: F
Boundary/convention: J violations (boundary + convention + term-drift)
Success criteria: G covered, H partial, I not covered
```

---

## Edge Cases

| Situation | Behavior |
|-----------|----------|
| Plan not found | List available plans, stop |
| Ambiguous match | List matches, stop |
| No completed phases + no explicit phase args | Report, suggest `phase N` or `all`, stop |
| Branch not found (merged/deleted) | File-read-only mode, note in report |
| Plan in `completed/` | Works normally (post-mortem review) |
| Plan in `pending/` | Warn that no implementation likely exists, continue |
| Files listed in plan don't exist | Flag as FILE-NOT-FOUND in audit |
| Plan missing Success Criteria / Testing / Docs | Skip those cross-checks, note in report |
| `git merge-base` fails | Fall back to file-read-only mode |
| Phase number out of range | Warn, list valid phase numbers, stop |

---

## Important Project Constraints

- **Read-only:** This skill does NOT edit files, create commits, or switch branches.
- **CuPy import order:** Flagged in code quality checks — import CuPy before any `preprocessing` package imports.
- **Authorship:** Not directly relevant (no commits), but noted for completeness.
- **Git safety:** No destructive git operations. All diff commands use explicit refs.
