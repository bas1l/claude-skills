---
name: plan-overview
description: "Return plans in tables with descriptions. Optional args: active, pending, idea (default: active + pending)"
allowed-tools:
  - Glob
  - Read
---

## Instructions

1. **Parse arguments** from `$ARGUMENTS`:
   - Split by spaces, lowercase each token.
   - Valid tokens: `active`, `pending`, `idea`.
   - If no valid tokens are found, default to `["active", "pending"]`.

2. Use `Glob` to find all `*.md` files in the requested directories (skip `.gitkeep`):
   - If "active" requested: `docs/development/plans/active/*.md`
   - If "pending" requested: `docs/development/plans/pending/*.md`
   - If "idea" requested: `docs/development/plans/ideas/*.md`

3. For each **active** or **pending** file, `Read` the first 40 lines and extract:
   - **Filename** — the filename without path or `.md` extension
   - **Plan name** — the `# H1` title
   - **Description** — the text after `**What:**` in the Overview section (trim to one sentence); if no `**What:**` field exists, use the first sentence of the Overview prose
   - **Created** — the `**Created:**` field value; if absent, fall back to the `**Date:**` field value; if both absent, use `—`
   - **Status** — the `**Status:**` field value; if absent, use `—`
   - **Branch** — the `**Branch:**` field value (will be a code-formatted string like `feature/foo` or `fix/bar`); if absent, use `—`

4. For each **idea** file, `Read` the first 20 lines and extract:
   - **Filename** — the filename without path or `.md` extension
   - **Plan name** — the `# H1` title (strip the "Idea: " prefix if present)
   - **Summary** — the first sentence of the `## Summary` section
   - **Date** — the `**Date:**` field value

5. Output tables for each requested category, sorted by date (newest first):

   If "active" requested:

   **Active Plans**

   | Filename | Plan | Description | Created | Status | Branch |
   |----------|------|-------------|---------|--------|--------|
   | ...      | ...  | ...         | ...     | ...    | ...    |

   If "pending" requested:

   **Pending Plans**

   | Filename | Plan | Description | Created | Status | Branch |
   |----------|------|-------------|---------|--------|--------|
   | ...      | ...  | ...         | ...     | ...    | ...    |

   If "idea" requested:

   **Ideas**

   | Filename | Plan | Summary | Date |
   |----------|------|---------|------|
   | ...      | ...  | ...     | ...  |

6. If a directory is empty, still output the section heading and an empty table with the correct headers and no rows.
