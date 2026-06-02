---
name: plan-commit
description: "Commit uncommitted files related to a plan: gather files, validate with user, then commit following project conventions"
allowed-tools:
  - Bash
  - Read
  - Glob
  - Grep
  - Agent
---

# Plan Commit

This skill automates committing work related to one or more plans. The agent
invoking this skill is a **pure manager** -- it dispatches all work to subagents
and never reads plan files, runs git commands, or cross-references file lists
itself. Its only responsibilities are: parse arguments, launch subagents, make
go/no-go decisions on subagent reports, communicate with the user, and display the
final summary.

It receives `$ARGUMENTS` in the format:
`<plan-name-1> [<plan-name-2> ...] [auto]` or list format with `- ` markers.

---

## Argument Parsing

Two formats are accepted:

**List format** (detected when `$ARGUMENTS` contains `- `):
Split on `- ` markers. Trim whitespace from each entry. Discard empty entries. If
the last entry (after trimming) is `auto`, enable auto mode and remove it.

**Slug format** (no `- ` markers):
Split on whitespace. If the last token is `auto`, enable auto mode and remove it.
All remaining tokens are plan names.

Each entry is a **plan identifier** -- can be a filename slug
(`per-session-touch-density-heatmaps`) or a full title
(`Per-Session Touch Density Heatmaps`).

- **Normal mode** (no `auto`): gathers files, shows them, asks for confirmation,
  then commits
- **Auto mode** (`auto` in args): skips confirmation but still enforces all safety
  checks

---

## Phase A: Resolve Plans & Gather State

### Step 1: Launch resolver-gatherer agent

Launch a **background Agent** with:
- The list of plan identifiers from argument parsing
- Instructions to read `.claude/skills/_plan-resolve/SKILL.md` and follow its
  procedure for plan resolution
- Search directories: `active/` and `pending/`
- After resolving plans, also:
  - Run `git branch --show-current` to get the current branch
  - Run `git status` to collect all staged, unstaged-modified, and untracked files
  - Cross-reference each file against all plans' "Files Modified" paths to
    categorize:
    - **plan-related** -- file path matches or is under a path listed in any plan
    - **plan-file** -- plan documents themselves, if they have uncommitted changes
    - **unrelated** -- files not referenced by any plan
    - **sensitive** -- files matching `.env*`, `*credentials*`, `*secret*`, `*key*`
  - Return all of: plan resolution results, current branch, categorized file list
    with git status indicators (M, A, ??)

### Step 2: Manager validates

When the agent returns, the manager applies these rules -- **no tool calls
needed**, just decision logic on the agent's report:

| Situation | Behavior |
|-----------|----------|
| Resolution FAILED (NOT_FOUND or AMBIGUOUS) | Display the agent's error, **stop** |
| Plans reference different branches (BRANCH_CONFLICT) | Display conflict, **stop** |
| On `main` | Refuse to commit on main, **stop** |
| Current branch != plan branch, normal mode | Warn, ask user to proceed |
| Current branch != plan branch, auto mode | **Stop.** Never auto-commit to wrong branch |
| No uncommitted changes | Report clean working tree, **stop** |

If all checks pass, display a plan summary:

**Single plan:**
```
Plan: <title> | Branch: <branch> | Status: <status>
```

**Multiple plans:**
```
Plans:
  1. <title-1> | Branch: <branch-1> | Status: <status-1>
  2. <title-2> | Branch: <branch-2> | Status: <status-2>
```

### Step 3: Present categorized file list

Display the categorized list from the agent's report:

```
Plan-related files:
  M  code/src/analysis/touch_analytics/unified_pipeline.py
  A  code/src/analysis/touch_analytics/feature_extraction/max_extractor.py
  ?? code/src/analysis/touch_analytics/clustering/kmeans_clusterer.py

Plan files:
  M  docs/development/plans/active/plan-a.md
  M  docs/development/plans/active/plan-b.md

Unrelated files (will NOT be committed):
  M  configs/unrelated_config.yaml

Sensitive files (excluded):
  ?? .env.local
```

Only **plan-related** + **plan-file** are selected for commit by default.
Unrelated files are shown but excluded unless user explicitly includes them.

---

## Phase B: User Validation

**If `auto` is NOT in `$ARGUMENTS`:**
- Ask the user: "Commit these files? (yes / no / select specific files)"
- If "no" -- **stop**
- If user selects specific files -- use only those

**If `auto` IS in `$ARGUMENTS`:**
- Skip confirmation, use all plan-related + plan-file files (minus sensitive)

---

## Phase C: Commit

### Step 4: Launch commit agent

Launch a **background Agent** that:

1. Receives the validated file list and all plan metadata (title, branch, status,
   plan file path for each plan)
2. Reads `.claude/skills/_commit-procedure/SKILL.md` first
3. Follows the commit-procedure conventions:
   - Stage the specific files: `git add <file1> <file2> ...` (never `git add .`)
   - Generate a conventional commit message from the plan(s):
     - **Type:** infer from plan title (`feat` for new features, `fix` for bug
       fixes, `refactor` for restructuring, `docs` for documentation)
     - **Scope:** derive from branch name (e.g., `feature/touch-analytics` ->
       `touch-analytics`)
     - **Subject (single plan):** concise imperative summary from plan title
     - **Subject (multiple plans):** if plan titles are closely related,
       synthesize a combined summary; otherwise use the first plan's title with
       "(+ N more)"
     - **Body (single plan):** include plan file path for traceability
     - **Body (multiple plans):** list all plan file paths:
       ```
       Plans:
       - docs/development/plans/active/plan-a.md
       - docs/development/plans/active/plan-b.md
       ```
   - **Normal mode:** present the commit message to the user before committing
   - **Auto mode:** use the generated message directly
   - Commit with NO `Co-Authored-By` trailer (Basil Duvernoy authorship only --
     see CLAUDE.md)
   - Use HEREDOC format for the commit message
   - Run `git log -1 --stat` and `git status` after committing
4. Return: commit hash, full commit message, `git log -1 --stat` output,
   remaining uncommitted file count and list

### Step 5: Post-commit summary

When the commit agent completes, display:

```
--- plan-commit complete ---
Commit: <short-hash> <type>(<scope>): <subject>
Branch: <branch-name>

Files committed (<N>):
  plan-related:
    M  path/to/file_a.py
    A  path/to/file_b.py
  plan-files:
    M  docs/development/plans/active/plan-name.md

Diff stats:
  <git log -1 --stat output, indented>

Remaining uncommitted: <count> files
  <list of remaining files, if any>
```

If there are **no remaining uncommitted files**, show:
```
Remaining uncommitted: none
```

---

## Edge Cases

| Situation | Behavior |
|-----------|----------|
| Plan not found (any in batch) | List available plans, stop (fail-fast) |
| Plans reference different branches | Stop, show conflict |
| On `main` | Refuse, stop |
| Wrong branch + auto | Stop (safety) |
| Wrong branch + normal | Warn, ask |
| Clean tree | Report, stop |
| Sensitive files | Warn, exclude by default |
| Ambiguous match (identifier matches multiple plans) | List matches, stop |
| Commit hook failure | Show error, do not retry |

---

## Manager Role Summary

The manager agent's **only responsibilities** are:

1. Parse arguments (in-context, no tools needed)
2. Launch subagents and receive their results
3. Make go/no-go decisions based on subagent reports
4. Communicate with the user (display summaries, ask for confirmation)
5. Display the final post-commit summary

The manager **never**:

- Reads plan files directly
- Runs `git` commands directly
- Cross-references file lists
- Generates commit messages

---

## Important Project Constraints

- **Authorship:** All commits by Basil Duvernoy only. Never add `Co-Authored-By`
  trailers.
- **Merge strategy:** Always `--no-ff` unless user explicitly says "fast-forward".
- **Git safety:** Run `git status` before any operation that touches the working
  tree.
