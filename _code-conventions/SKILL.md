---
name: _code-conventions
description: Standing engineering conventions for this user's codebases — config-vs-hardcoded, layer agnosticism, naming, separation of concerns. Reference skill consumed by planning/implementation/review.
disable-model-invocation: false
---

# Standing Code Conventions

Conventions that apply across this user's projects, **banked once here** so they never have to be
re-stated per session. They exist because these exact corrections recurred across dozens of sessions
(a communication-history analysis found architecture/refactor prompts rising and "no hardcoded values"
issued repeatedly). Treat every rule here as a default constraint, not a suggestion.

**How this skill is used**
- `/plan-create` — the plan's *Definitions* and *Architecture & Module Contracts* sections should make these concrete for the feature at hand.
- `/plan-implement` — every phase agent is handed these rules in its brief and must build to them.
- `/plan-review` — the implementation is audited against these; a violation is a finding.
- **When the user issues a new standing correction, append it here** (one line), so the class of rework disappears instead of recurring.

---

## The conventions

### 1. No hardcoded values — configuration-driven
Paths, parameters, thresholds, and category values live in **config files**, not baked into `.py`
source. The one sanctioned exception is a clearly-labelled configuration block at the **top of a
workflow `main()`** (constants as named variables, no argparse) — matching the `deploy-workflow`
paradigm. Anywhere else, a literal that a user might want to change is a smell.

### 2. Data comes from the source of truth
When a script needs data that lives in a database or config, it **fetches it at run time** — it does
not embed a copy. Explicitly: *no data should be hardcoded when it can be fetched from the database.*

### 3. Layer agnosticism is a concrete contract
Abstract/base classes and shared utilities must **not know about** concrete fields, labels, country,
or file paths — those are injected by the caller. "Agnostic" and "separation of concerns" are never
left as principles: each module states what it must **not** depend on (see the plan's *Module
Contracts* table). If a base class references a specific label or country, that is a violation.

### 4. Naming reflects what code acts on
Functions and modules are named for **what they operate on**, not generically. E.g. a loader for
synthetic vs database populations carries that in its name (`load_synthetic_population`, not
`load_raw_population`). Analysis scripts are named/ordered so a user can read the pipeline from the
filenames.

### 5. One file, one concern
A module has a single responsibility. Prefer splitting by concern over growing a god-file. This is a
design default, not a post-hoc refactor — raise it at plan time, in the *Module Contracts*.

### 6. Idempotency and outputs live in the workflow, not the tasks
Never overwrite existing outputs without user confirmation. Idempotency / should-process / output
cleanup belong to the orchestrating workflow; tasks are pure processors that receive resolved paths
and write outputs (matching the `deploy-workflow` paradigm).

---

## Applying the rules
- Prefer catching a violation **at plan time** (make it concrete in the plan) over **review time**
  (flag it) over **runtime** (the user corrects it) — the whole point is to move the fix earlier.
- When unsure whether a literal belongs in config vs code, default to config and note it in the plan.
- If a project's own `CLAUDE.md` states a stricter or different rule, that project rule wins.
