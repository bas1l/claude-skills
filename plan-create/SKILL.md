---
name: plan-create
description: "View and understand the feature planning procedure for this project; captures base branch at creation time"
disable-model-invocation: false
---

# Feature Planning Procedure

This skill provides comprehensive guidance on planning features in the social-touch-semi-controlled repository.

## ⛔ IMPLEMENTATION IS FORBIDDEN

**This skill writes a plan document. It does NOT implement anything.**
After the plan file is written, you MUST stop. No branches, no code edits, no commits, no `/plan-implement`.

---

## Mandatory Workflow — Follow This Order

When this skill is invoked, you MUST follow these steps in order:

### Step 1: Research (do this FIRST)
- Explore the codebase to understand existing patterns, similar features, and constraints
- Check the knowledge base for relevant patterns (see Best Practices below)
- **Read the pipeline / analytics engineering guides** in
  `~/.claude/knowledge/data-pipeline-engineering/` (start with `README.md`). Use `01` to name
  the system and `02`'s design checklist while decomposing the feature into
  stages; consult `03` for any statistical/analytics code and `05` for
  craftsmanship/maintainability. Reflect the applicable principles in the plan's
  Technical Design section.
- Identify dependencies with other systems
- Consider alternatives and trade-offs

### Step 2: Present findings to the user
- Summarize your research: what you found, relevant patterns, proposed approach
- Present the plan structure (sections, phases, key decisions) in conversation
- Do NOT write any files yet

### Step 3: Write the plan directly
- Proceed directly to Step 4 — no permission check, no confirmation prompt required.

### Step 4: Enable write mode and write the plan (ONLY after user approves)
- **If user approved in Step 3:** Exit any current mode (e.g., plan mode) and enable write mode to proceed with file operations
- Before writing, run `git branch --show-current` and substitute the result as
  the value of `**Base Branch:**` in the document. This records which branch
  the new feature branch will eventually be merged back into when `/plan-finish`
  is called.
- Write to `docs/development/plans/pending/[feature-name].md`
- Do NOT write to `active/` — that is reserved for plans with an open branch
- Do NOT leave the plan only in `.claude/` — that is internal scratch space,
  not part of the repository

### Step 5: STOP — Implementation Is FORBIDDEN

After writing the plan file, **STOP COMPLETELY.**

**STRICTLY PROHIBITED after /plan-create:**
- Creating branches (`git checkout -b`, `git branch`)
- Editing or writing any source code, config, or asset files
- Making commits (`git add`, `git commit`)
- Invoking `/plan-implement` or any implementation skill
- Running the pipeline, tests, or build commands
- Making any change to the repository beyond the plan document itself

**This prohibition is unconditional.** Even if the plan describes obvious next steps, even if the user says "looks good" or "great plan" — do NOT implement. Wait for an explicit `/plan-implement` command.

Past violations have caused unreviewed code to be written. The plan exists precisely to create a review gate before any code is touched.

## Quick Start Checklist

### For a lightweight idea capture

- [ ] Create file in `docs/development/plans/ideas/[idea-name].md`
- [ ] Use the idea template (below) — keep it to ~10 lines
- [ ] No review required

### For a full plan

Before creating a plan:
- [ ] You've explored the codebase and understand existing patterns
- [ ] You've checked the knowledge base for relevant patterns (see Best Practices below)
- [ ] You've identified dependencies with other systems
- [ ] You've considered alternatives and trade-offs

When creating a plan:
- [ ] Create file in `docs/development/plans/pending/[feature-name].md`
- [ ] Complete all required sections from the template
- [ ] Be specific and measurable (not vague)
- [ ] Submit for review before starting implementation
- [ ] Move plan to `active/` only when a branch is opened and work begins
- [ ] Move plan to `completed/` when shipped

---

## Planning Document Lifecycle

```
Idea  →  Draft  →  Approved  →  In Progress  →  Completed  →  Archived
  ↓        ↓          ↓              ↓               ↓             ↓
ideas/  pending/   pending/       active/        completed/    archived/
```

- **ideas/** — Lightweight captures. No phases, no testing plan. Just enough to not lose the thought.
- **pending/** — Fully drafted plans that are approved and queued but not yet being worked on.
- **active/** — Plans with an open branch and active commits. Only move here when work has started.
- **completed/** — Plans for features that were shipped as designed. Canonical design records.
- **archived/** — Plans that were superseded, abandoned, or substantially rewritten before completion.

### Directory Structure

```
docs/development/plans/
├── ideas/                             # Lightweight idea captures
│   └── idea-name.md
├── pending/                           # Drafted/approved plans awaiting implementation
│   ├── feature-name.md               # Primary plan document
│   └── feature-name/                 # Optional: phase breakdowns
│       ├── 01-foundation.md
│       ├── 02-core.md
│       └── 03-integration.md
├── active/                            # Plans currently being implemented
│   └── feature-name.md
├── completed/                         # Successfully shipped features
│   └── [shipped feature plans]
└── archived/                          # Old versions, superseded plans
    └── [old plans]
```

---

## Idea Template

Use for quick captures — do not spend more than a few minutes on it:

```markdown
# Idea: [Short Title]

**Date:** YYYY-MM-DD
**Status:** Idea

## Summary

[1-3 sentences — what it is and why it matters]

## Rough Approach

[Optional: which area of code, high-level sketch of how it might work]

## Notes

[Constraints, prior art, related ideas, open questions]
```

To promote an idea to a full plan: create a new file in `pending/` using the full planning template, then delete or archive the idea file.

---

## Required Plan Sections

Every planning document must include these sections:

### 1. Overview (2-3 sentences)
- **What:** High-level description of what is being built
- **Why:** Problem being solved or improvement being made
- **How:** Concise summary of the approach

### 2. Problem Statement
- Current limitation or issue
- Why it matters for the project
- User impact or technical debt implications

### 3. Goals

#### In Scope
1. Specific goal 1
2. Specific goal 2
3. Specific goal 3

#### Out of Scope
- Explicitly excluded feature or responsibility
- Future work that won't be included now

### 4. Success Criteria
Measurable checkboxes that define "done":
- [ ] Specific, measurable criterion 1
- [ ] Specific, measurable criterion 2
- [ ] Specific, measurable criterion 3

### 5. Definitions & Terminology

Pin down any term the plan's correctness depends on — concretely, not by principle. If a word like
"intact", "realistic", "agnostic", or "clean" is load-bearing, define it in testable terms so
implementation cannot drift on interpretation. Omit only when there are genuinely no such terms.

- **[term]:** [concrete, testable meaning in this plan's context]

### 6. Technical Design

#### Approach
- High-level description of chosen solution
- Why this approach was selected

#### Alternatives Considered
Table comparing approaches:
| Approach | Pros | Cons | Decision |
|----------|------|------|----------|
| Option A | [Pro] | [Con] | Chosen |
| Option B | [Pro] | [Con] | Rejected |

#### Architecture Changes — Module Boundaries & Contracts
Describe the structure as a *contract*, not a principle:
- New modules or classes, each with a one-line **responsibility** and its **inputs → outputs**
- For each, what it must **NOT** know about — the concrete form of "agnostic" / separation of concerns
- Integration points and interfaces with existing code (name the signatures that change)
- A directory tree or interface sketch when it helps

| Module / layer | Responsibility | Inputs → Outputs | Must NOT know about |
|----------------|----------------|------------------|---------------------|
| [module] | [one job] | [in → out] | [labels, paths, country, …] |

> 💡 To see the proposed change as a color-coded before/after diagram, run `/arch-diff <plan>` once the contracts are drafted (optional; not automatic).

### 7. Implementation Plan

Break into logical phases with clear dependencies:

#### Phase 1: [Foundation]
**Goal:** What this phase accomplishes

**Tasks:**
- [ ] Task 1.1 — Description
- [ ] Task 1.2 — Description
- [ ] Task 1.3 — Description

**Files Modified:**
- `path/to/file.py` — Brief description of changes
- `path/to/other.py` — Brief description of changes

**Dependencies:** None

#### Phase 2: [Core Feature]
**Goal:** What this phase accomplishes

**Tasks:**
- [ ] Task 2.1 — Description
- [ ] Task 2.2 — Description

**Files Modified:**
- `path/to/file.py` — Brief description of changes

**Dependencies:** Phase 1

#### Phase 3: [Integration]
**Goal:** What this phase accomplishes

**Tasks:**
- [ ] Task 3.1 — Description
- [ ] Task 3.2 — Description

**Files Modified:**
- `path/to/file.py` — Brief description of changes

**Dependencies:** Phase 2

### 8. Testing Plan

#### Unit Tests
- [ ] Test case 1 — What is being tested and expected behavior
- [ ] Test case 2 — What is being tested and expected behavior
- [ ] Test case 3 — What is being tested and expected behavior

#### Integration Tests
- [ ] Test scenario 1 — How components work together
- [ ] Test scenario 2 — How components work together

#### Manual Verification
- [ ] Verification step 1 — Manual steps to confirm feature works
- [ ] Verification step 2 — Manual steps to confirm feature works

#### Edge Cases
- [ ] Edge case 1 — Unusual but valid input/state
- [ ] Edge case 2 — Boundary condition testing

### 9. Documentation Plan

- [ ] Update README.md with new commands/features
- [ ] Update CLAUDE.md with architecture changes
- [ ] Create/update user guide: `docs/guides/[feature].md`
- [ ] Create/update API documentation (if applicable)
- [ ] Add changelog entry: `docs/changelogs/[feature].md`
- [ ] Update inline code comments for complex logic

### 10. Rollback Plan

How to safely revert if something goes wrong:

1. **Before deployment:**
   - [Rollback step 1]
   - [Rollback step 2]

2. **Data considerations:**
   - Are there migrations? How to reverse them?
   - Are there breaking changes? How to handle?

3. **Rollback procedure:**
   - Which commits to revert
   - Which files to restore
   - Database/state reset steps

### 11. Risks and Mitigations

Identify potential blockers and how to handle them:

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| [Risk description] | Low/Med/High | Low/Med/High | [How to prevent or handle] |
| [Risk description] | Low/Med/High | Low/Med/High | [How to prevent or handle] |

---

## Best Practices

### Before Writing the Plan

- **Check knowledge base for relevant patterns** — As one of the first parallel
  research tasks, spawn an Explore subagent with the following prompt:

  > Read `docs/development/knowledge-base/README.md`. For each note listed in
  > the index, assess whether its problem class overlaps with the feature being
  > planned. Read the full content of any relevant notes and return a concise
  > summary of what applies: which constraints to respect, which approaches
  > were rejected and why, and which code patterns to reuse.

  Incorporate the findings into the Technical Design section — especially
  **Alternatives Considered** and **Architecture Constraints** — before the
  plan is submitted for review.

- **Read the pipeline-engineering guides** — Read `~/.claude/knowledge/data-pipeline-engineering/README.md`
  and the relevant guides it indexes (`01` system classification, `02`
  architecture patterns & checklist, `03` statistical/scientific software, `05`
  code craftsmanship). Apply the checklists when shaping the plan, especially the
  **Technical Design**, **Alternatives Considered**, and **Architecture
  Constraints** sections.
- **Explore the codebase** — Understand existing patterns, similar features, and constraints
- **Identify dependencies** — What other systems does this integrate with?
- **Consider alternatives** — Why is your chosen approach best? Document trade-offs

### During Planning

- **Be specific** — "Add validation" is vague; "Add `validate_references()` method to `ConfigLoader` that checks all topology node references" is actionable
- **List files explicitly** — Don't just say "update core modules", name them
- **Estimate scope** — How many lines of code? How many files?
- **Identify risks** — What could go wrong? Unknown dependencies? Complex integrations?
- **Consider testing** — How will this be verified? What are edge cases?

### Naming and Organization

- **Ideas:** `idea-name.md` in `docs/development/plans/ideas/` directory
- **Plans:** `feature-name.md` in `docs/development/plans/pending/` directory
- **Branch naming:** `feature/[feature-name]` (use hyphens, lowercase)
- **Phase breakdown:** Only use phase files if plan is large (3+ phases with significant detail)

---

## Common Mistakes to Avoid

### ❌ Writing a plan directly to active/

Plans go to `pending/` by default. `active/` is only for plans with an open branch.

### ✅ Correct flow

```
pending/my-feature.md   →  (open branch)  →  active/my-feature.md  →  completed/
```

---

### ❌ Too Vague

```
"Add features to improve user experience"
"Refactor the system for better performance"
```

### ✅ Specific and Actionable

```
"Add LED state validation filter: moving average over 5 frames, 3σ threshold"
"Extract centroid calculation into separate CentroidCalculator class for testability"
```

---

### ❌ Missing Out-of-Scope

Reader doesn't know what's NOT being done, creating scope creep during implementation.

### ✅ Clear Boundaries

```
Out of Scope: "Real-time video streaming" (future enhancement)
Out of Scope: "GPU acceleration" (not in this phase)
```

---

### ❌ Isolated Design

No mention of integration with existing code, leading to surprise incompatibilities.

### ✅ Integrated Thinking

```
"Extends DataHandler abstract class (used by 3 other modules)"
"Adds optional parameter to process() (backward compatible)"
```

---

## Review Process

### Plan Review Checklist

Before approving a plan:

- [ ] **Clarity** — Goals are clear and measurable
- [ ] **Scope** — Well-defined boundaries (what's in/out of scope)
- [ ] **Technical soundness** — Approach is solid and considers alternatives
- [ ] **Testing** — Plan covers success and failure paths
- [ ] **Documentation** — Docs plan is included
- [ ] **Risk management** — Risks identified with mitigation strategies
- [ ] **No over-engineering** — Solution matches problem scope, not over-designed

### During Implementation

- [ ] Following the approved plan
- [ ] Each phase tested before proceeding
- [ ] Documentation updated alongside code
- [ ] Plan updated if approach changes
- [ ] No unplanned scope additions

---

## Post-Implementation

### Completing a Plan

1. **Mark as completed:** Update `Status: Completed` and add completion date
2. **Move to completed:** `docs/development/plans/completed/[feature-name].md`
3. **Update README:** Move from active to completed in index
4. **Reference from code:** Link to plan from relevant module docs
5. **Lessons learned:** Optional note on what went well/differently

### Post-Mortem (Optional)

If the implementation revealed important learnings:
1. Document what changed from the plan
2. Why the change was necessary
3. What the team learned for future plans
4. Link from both plan and related code

---

## Planning Template

Use this template when creating a new plan:

```markdown
# Plan: [Feature Name]

**Date:** YYYY-MM-DD
**Author:** [Your Name]
**Status:** Draft | Approved | In Progress | Completed
**Base Branch:** `<current-branch>`
**Branch:** `feature/[branch-name]`

---

## Overview

[What is being built and why. 2-3 sentences.]

## Problem Statement

[What problem does this solve? What is the current limitation?]

## Goals

### In Scope
1. [Goal 1]
2. [Goal 2]
3. [Goal 3]

### Out of Scope
- [Explicitly excluded item 1]
- [Explicitly excluded item 2]

## Success Criteria

- [ ] [Measurable criterion 1]
- [ ] [Measurable criterion 2]
- [ ] [Measurable criterion 3]

## Definitions

<!-- Any term whose meaning the plan's correctness depends on. Define it concretely and testably,
     NOT by principle. If a word like "intact", "realistic", "agnostic", or "clean" is load-bearing
     here, pin it down before any code is written. Omit the section only if there are genuinely none. -->

- **[term]**: [what it means here, in concrete/testable terms]

---

## Technical Design

### Approach

[High-level description of the chosen approach and why it was selected over alternatives]

### Alternatives Considered

| Approach | Pros | Cons | Decision |
|----------|------|------|----------|
| [Option A] | [Pro] | [Con] | Chosen |
| [Option B] | [Pro] | [Con] | Rejected |

### Architecture & Module Contracts

Define the structure as a *contract*, not a principle. For each new or significantly changed module,
state its responsibility, its inputs → outputs, and — crucially — what it must **NOT** know about
(the concrete form of "agnostic" / separation of concerns). This is the review surface: implementers
build to it and `/plan-review` checks against it.

| Module / layer | Responsibility | Inputs → Outputs | Must NOT know about |
|----------------|----------------|------------------|---------------------|
| [module] | [one job] | [in → out] | [labels, paths, country, …] |

```
[Directory tree / interface signatures if helpful]
```

---

## Implementation Plan

### Phase 1: [Foundation]
**Goal:** [What this phase achieves]

- [ ] [Task 1.1]
- [ ] [Task 1.2]
- [ ] [Task 1.3]

**Files Modified:**
- `path/to/file.ext` — [What changes]

**Dependencies:** None

### Phase 2: [Core Feature]
**Goal:** [What this phase achieves]

- [ ] [Task 2.1]
- [ ] [Task 2.2]

**Files Modified:**
- `path/to/file.ext` — [What changes]

**Dependencies:** Phase 1

### Phase 3: [Integration]
**Goal:** [What this phase achieves]

- [ ] [Task 3.1]
- [ ] [Task 3.2]

**Files Modified:**
- `path/to/file.ext` — [What changes]

**Dependencies:** Phase 2

---

## Testing Plan

### Unit Tests
- [ ] [Test case 1]
- [ ] [Test case 2]

### Integration Tests
- [ ] [Test scenario 1]
- [ ] [Test scenario 2]

### Manual Verification
- [ ] [Verification step 1]
- [ ] [Verification step 2]

---

## Documentation Plan

- [ ] Update README.md with new commands/features
- [ ] Update CLAUDE.md with architecture changes
- [ ] Create/update user guide: `docs/guides/[feature].md`
- [ ] Add changelog entry: `docs/changelogs/[feature].md`

---

## Rollback Plan

[How to revert if something goes wrong]

1. [Rollback step 1]
2. [Rollback step 2]

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| [Risk 1] | Low/Med/High | Low/Med/High | [Mitigation strategy] |
| [Risk 2] | Low/Med/High | Low/Med/High | [Mitigation strategy] |

---

## Timeline

| Phase | Estimated Effort | Dependencies |
|-------|-----------------|--------------|
| Phase 1 | [estimate] | None |
| Phase 2 | [estimate] | Phase 1 |
| Phase 3 | [estimate] | Phase 2 |

---

## References

- Related Issue: #[number]
- Related Plans: `docs/development/plans/[related-plan].md`

---
```

---

## Full Documentation

For comprehensive information, see:
- **[Planning Procedure](../../docs/development/planning-procedure.md)** — Detailed step-by-step guide with examples
- **[skeleton/topics/04-planning-process.md](../../skeleton/topics/04-planning-process.md)** — Original reference material

---

## Important Project Constraint

**CuPy Import Order**: When implementing a plan that involves scripts using CuPy, remember to import CuPy BEFORE any `preprocessing` package imports. This avoids the NumPy 2.0 `bool8` dtype-registry crash. See `CLAUDE.md` for details.

---

## Workflow Summary

1. **Idea Phase** — Capture in `docs/development/plans/ideas/` (lightweight, informal)
2. **Plan Phase** — Create detailed plan in `docs/development/plans/pending/`
3. **Review Phase** — Get approval from team using review checklist
4. **Implementation Phase** — Move plan to `active/`, follow approved plan, update if approach changes
5. **Testing Phase** — Execute all testing from plan
6. **Documentation Phase** — Complete all documentation tasks
7. **Completion Phase** — Move plan to `docs/development/plans/completed/`

Questions? See [Planning Procedure](../../docs/development/planning-procedure.md) or ask your team lead.
