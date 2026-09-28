---
name: arch-diff
description: "Visualize a codebase's architecture and show an explicit before/after of what a plan will change — a color-coded Mermaid delta (current vs planned) so architecture is graspable at implementation time."
argument-hint: "<plan-name | current> [--html]"
disable-model-invocation: false
effort: high
---

# arch-diff — architecture before/after for an implementation

Make architecture **visible and comparable** when implementing a change. Given a plan (or the current
working change), this skill draws the **current** codebase (how modules interconnect) and the
**planned** state as one color-coded delta, so the whole system and the change are graspable at a
glance — green = added, amber = changed, red = removed.

It is the visual counterpart to the text contracts already in the workflow: `plan-create` defines the
`### Architecture & Module Contracts` table, `_code-conventions` sets the standing rules, and
`plan-review` audits against them. **This skill turns that same contract into a diagram** — it does not
invent a new source of truth; the Module Contracts table drives the delta.

## When to use
- Before implementing, to see what a plan will restructure (run against the plan).
- After implementing, to refresh the "after" and confirm the real change matches the contract.
- Any time you want to understand how a package currently hangs together.

## Output at a glance
- **Default:** a Markdown file with Mermaid diagrams at `docs/architecture/<plan-slug>-archdiff.md`
  (renders natively in Claude, diffs cleanly in git, matches the existing `docs/architecture/` convention).
- **`--html`:** additionally a self-contained interactive HTML artifact (pan/zoom + before/after toggle)
  for large diagrams — published via the Artifact tool.

---

## Argument parsing

| Input | Meaning |
|-------|---------|
| `<plan-name>` | Resolve the plan (delegate to the `_plan-resolve` skill); the delta comes from its Module Contracts + Files Modified. |
| `current` or no arg | Diff the working change: `git diff --name-only <base>..HEAD` (base = the active plan's `**Base Branch:**`, else `dev`). Delta inferred from changed files. |
| `--html` (flag) | Also emit the interactive HTML artifact. |

If a plan-name is given but not found → list candidate plans and stop (same failure behaviour as `_plan-resolve`).

---

## Step 1 — Resolve inputs

1. **Plan mode:** delegate to `_plan-resolve` to get the plan's `file_path`. Read and extract:
   - the `### Architecture & Module Contracts` table rows (module · responsibility · inputs→outputs · **must NOT know about**),
   - `## Definitions` (load-bearing terms — carry them into diagram labels/notes so nothing is reinterpreted),
   - every phase's `**Files Modified:**` list.
   - If the plan has **no** Module Contracts table (older plan), fall back to inferring modules from Files Modified and note that the delta is file-derived, not contract-derived.
2. **Detect the package root** (reuse `deploy-workflow` Step-2 probing): look for `src/<pkg>/`, then
   `code/src/<pkg>/`, read the package name from `pyproject.toml`. Record `IMPORT_ROOT` (dir to point
   pyreverse at) and `PKG` (project label). Note config dir (`config/` or `configs/`) for the layer view.

---

## Step 2 — Build the CURRENT diagram (hybrid: extract, then distill)

1. **Auto-extract** with the one installed generator (needs no Graphviz — `mmd` is a text format):
   ```bash
   pyreverse -o mmd -p <PKG> -d <scratch_dir> <IMPORT_ROOT>
   ```
   This writes `packages_<PKG>.mmd` (module/package interconnections — the "how it's wired" view) and
   `classes_<PKG>.mmd` (class-level). Use the **packages** diagram as the base.
   - Run from the project root so the package imports. If pyreverse errors (import failure, no
     `__init__`), **fall back** to hand-authoring the diagram from reading the code + the Module
     Contracts, and say so in the output.
2. **Distill** the raw pyreverse output into a legible Mermaid `flowchart` (do not paste the raw dump):
   - Group nodes by the layer order from `~/.claude/knowledge/data-pipeline-engineering/02-architecture-principles-and-patterns.md`
     (Orchestration → Visualization → Statistical → Computation → Transformation → I/O) **or** by the
     project's own pipeline-stage subpackages (e.g. `acquisition → preprocessing → primary_processing →
     merging → postprocessing → analysis → utils`). Use Mermaid `subgraph` per layer/stage.
   - Node = module/package; edge = import / data flow. Keep it to the meaningful modules — collapse leaf
     utilities. Aim for a diagram a person can read in one glance, not an exhaustive class dump.

---

## Step 3 — Build the DELTA (planned state)

From the Module Contracts + Files Modified, classify every node and edge and render **one** color-coded
target-state diagram (see `templates/legend.md` for the exact `classDef` block):

- **added** (green) — module/edge that does not exist today.
- **changed** (amber) — existing module whose files are in Files Modified or whose contract changes.
- **removed** (red, dashed) — module/edge the plan deletes.
- **unchanged** (neutral) — everything else, kept for orientation.

Apply with Mermaid classes, e.g. `mapper:::changed` and a `classDef` block. Style changed/removed
**edges** too (`linkStyle`), not just nodes.

**Boundary check (ties to `plan-review` 5f):** for each Module Contract row, if the planned edges would
make a module depend on something in its **"must NOT know about"** column, mark that edge red and add a
`%% ⚠ boundary risk` note. Surface these in the Step 6 report — catching them here is cheaper than at review.

Add side-by-side `## Before` / `## After` diagrams **only** when the topology change is large enough that
a single delta diagram would be cluttered; otherwise the one delta diagram is clearer.

---

## Step 4 — Assemble the Markdown

Fill `templates/archdiff.md` and write to **`docs/architecture/<plan-slug>-archdiff.md`** (create
`docs/architecture/` if absent). Sections, in order:

1. **Header** — plan title, date, branch, one-line intent.
2. **Legend** — from `templates/legend.md`.
3. **Current architecture** — the distilled Mermaid flowchart (note if hand-authored fallback was used).
4. **Planned change — delta** — the color-coded diagram (+ side-by-side only if needed).
5. **Change table** — one row per Module Contract: `module · status (added/changed/removed) · boundary
   it must respect ("must NOT know about") · files touched`. This ties every node back to its contract.
6. **Why (ADR-lite)** — three lines: *Context / Decision / Consequence*, drawn from the plan's Overview
   and Technical Design. (Lightweight MADR flavour — the reasoning a diagram can't show.)

**Idempotent:** overwrite the same file on re-run, so after implementation you regenerate to refresh the
"after" against the real code.

---

## Step 5 — Optional interactive HTML (`--html`)

Fill `templates/archdiff.html` (self-contained; embeds the same diagrams as `<pre class="mermaid">`,
adds a Before/After toggle and pan/zoom) and publish with the **Artifact tool** — it renders Mermaid
natively. Private by default; this is the user's own project architecture (no impersonation concern), so
proactive publishing is fine. Report the artifact URL.

---

## Step 6 — Report

Print:
- the output path (`docs/architecture/<plan-slug>-archdiff.md`) and the artifact URL if `--html`,
- counts: **N added / M changed / K removed** modules,
- any **boundary risks** flagged in Step 3 (module → the thing it should not depend on), or "none".

---

## Edge cases

| Situation | Behaviour |
|-----------|-----------|
| Plan not found | List candidate plans (via `_plan-resolve`), stop. |
| Plan has no Module Contracts table | Infer modules from Files Modified; note the delta is file-derived; suggest adding the table via `/plan-create`. |
| `pyreverse` import error / not a package | Hand-author the current diagram from code + contracts; note the fallback in the doc. |
| No `docs/architecture/` dir | Create it. |
| Non-Python project | Skip pyreverse; hand-author from code reading. |
| Diagram too large to grasp | Split by layer/stage into multiple `subgraph`s, or recommend `--html` for pan/zoom. |

## Reuse (do not reinvent)
- `_plan-resolve` — plan lookup + canonical field set.
- `deploy-workflow/SKILL.md` Step 2 — package-root / layout auto-detection.
- `plan-create`'s `### Architecture & Module Contracts` — the structured delta source.
- `_code-conventions` + knowledge file `02-architecture-principles-and-patterns.md` — layer ordering.
- Templates: [templates/archdiff.md](templates/archdiff.md) · [templates/legend.md](templates/legend.md) · [templates/archdiff.html](templates/archdiff.html).

## Out of scope (future companion)
Boundary **enforcement** (`import-linter` / `tach`) is the real anti-drift layer but needs a tool install
+ CI (neither present today). Stretch: emit an `import-linter` `layers` contract from the Module
Contracts table so the drawn boundaries become CI-enforced.
