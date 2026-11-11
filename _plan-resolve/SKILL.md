---
name: _plan-resolve
description: "Resolve plan identifiers to structured metadata: three-pass matching, metadata extraction, fail-fast on ambiguity. Reference skill for subagents."
disable-model-invocation: false
---

# Plan Resolve

Reference instructions for resolving plan identifiers to structured plan metadata.
This is a **helper skill** -- not invoked directly by users. Other skills
(`plan-commit`, `plan-implement`, `plan-review`, `plan-finish`) tell their
subagents to read this file and follow its procedure.

---

## Input

The calling skill provides:

1. A list of **plan identifiers** -- each can be:
   - A filename slug (e.g., `per-session-touch-density-heatmaps`)
   - A full title (e.g., `Per-Session Touch Density Heatmaps`)

2. A list of **search directories** (ordered by priority). The calling skill
   specifies which to search:
   - `docs/development/plans/active/`
   - `docs/development/plans/pending/`
   - `docs/development/plans/completed/`

---

## Procedure

### Step 1: Three-pass matching

For each plan identifier, search the specified directories in order using
three-pass matching (stop at first match):

1. **Exact filename:** identifier matches a filename (with or without `.md`)
2. **Slug containment:** slugify the identifier (lowercase, spaces/special chars
   to hyphens, collapse runs), check if any filename **starts with** or
   **contains** the slug
3. **Title search:** if still unmatched, read `# Plan:` headings from files in
   the search directories, case-insensitive substring match against the identifier

### Step 2: Fail-fast rules

- If a single identifier matches **multiple files** -- list all matches, report
  `AMBIGUOUS`, and **stop**.
- If **any** identifier is not found -- list available plans from all searched
  directories, report `NOT_FOUND`, and **stop**.

### Step 3: Extract metadata

For each matched plan file, read the file and extract:

| Field | Source | Required |
|-------|--------|----------|
| `title` | `# Plan:` heading | Yes |
| `branch` | `**Branch:**` field (strip backticks) | Yes |
| `status` | `**Status:**` field | Yes |
| `base_branch` | `**Base Branch:**` field (strip backticks) | No |
| `file_path` | Absolute path to the plan file | Yes |
| `directory` | Which directory (`active`, `pending`, `completed`) | Yes |
| `files_modified` | All paths under `**Files Modified:**` across all phases | No |

---

## Output Format

Return a structured report:

```
Resolution: OK | FAILED (<reason>)

Plans:
  1. Title: <title>
     Branch: <branch>
     Base Branch: <base_branch or "not specified">
     Status: <status>
     Path: <file_path>
     Directory: <active|pending|completed>
     Files Modified: <count> paths
       - path/to/file_a.py
       - path/to/file_b.py

Branch validation:
  Shared branch: <branch-name>
  -- or --
  BRANCH_CONFLICT: plans reference <branch-A>, <branch-B>
```

On `FAILED`, include the reason and list available plans to help the user.

---

## Directory conventions by calling skill

| Skill | Searches |
|-------|----------|
| `plan-commit` | `active/`, `pending/` |
| `plan-implement` | `pending/`, `active/` |
| `plan-review` | `active/`, `pending/`, `completed/` |
| `plan-finish` | `active/` only |
