---
name: idea
description: "Score a raw idea/feature request on a 0–4 readiness scale across the characteristics that make it plannable, then interactively refine the weak ones and emit a sharpened brief for /plan-create. Use at the START of any request to build/create/generate something new (a feature, script, document, tool, analysis) before planning or coding."
argument-hint: "<rough idea | empty = the opening message>"
disable-model-invocation: false
effort: high
---

# idea — score & refine an idea before it becomes a plan

The cheapest place to fix a project is the idea, before any plan or code exists. This skill takes a raw
(often voice-dictated) idea, **scores it 0–4 on eight characteristics**, **refines the weak ones** with a
few targeted questions, and writes a **sharpened brief** that `/plan-create` can promote directly. A
strong idea maps 1:1 onto the plan template — so a high score literally means "ready to plan."

## When to use
- The first substantive request of a session is to **build / create / generate something new** — run this
  before planning or coding. (A SessionStart hook nudges this automatically; you can also call `/idea …`.)
- Any time an idea feels vague and you want it sharpened before committing to a plan.

**Do NOT use** for: fixing a typo, answering a question, a one-line tweak, or a request that already
carries a full spec — those take the fast-path (Step 4) or skip the skill entirely. Never let this
become ceremony on a well-formed ask.

---

## Step 1 — Take the idea
Use `$ARGUMENTS` if given; otherwise use the user's opening message. Restate it in one sentence and
confirm you've understood the *intent* before scoring (don't invent scope).

## Step 2 — Score the eight characteristics (0–4)
Score each against the rubric in [templates/scale.md](templates/scale.md). Show a compact scorecard:

```
Readiness for: <one-line idea>
  1 Goal & motivation      ●●●○○  3/4
  2 Success criteria       ●○○○○  1/4  ← weak
  3 Definitions            ●●○○○  2/4  ← weak
  4 Constraints & convent. ●●●○○  3/4
  5 Scope (in/out)         ●●○○○  2/4  ← weak
  6 Decomposition          ●●●○○  3/4
  7 Architecture impact    ●○○○○  1/4  ← weak
  8 Risks & unknowns       ●●○○○  2/4
  ── overall 17/32 ─────────────────────
```
Be honest and conservative — score what's actually stated, not what you can infer. A characteristic is
**weak at ≤2**.

## Step 3 — Guided refinement (only the weak ones)
For each characteristic scoring **≤2**, form ONE targeted question that would raise it a level (the
rubric's "next:" hint tells you what's missing). Ask them **batched, 2–3 per round**, via
`AskUserQuestion` — never a wall of questions (respect the discrete-points preference). After answers,
**re-score** the affected characteristics.

- Cap at **~5–6 questions total** (1–2 rounds). If something is still weak after that, don't keep
  drilling — record it under "Open questions" in the brief and move on. Refinement, not interrogation.
- For the **Architecture impact** characteristic, if a change touches module structure, capture the
  affected modules and their boundaries (this seeds `/plan-create`'s Module Contracts and `/arch-diff`).

## Step 4 — Fast-path
If every characteristic already scores **≥3** at Step 2, skip questions entirely: show the scorecard,
say it's plan-ready, and go straight to Step 5. No ceremony.

## Step 5 — Emit the refined brief
Fill [templates/refined-idea.md](templates/refined-idea.md) and write it to the ideas directory:
- `docs/development/plans/ideas/<slug>.md` if that structure exists (the plan-workflow projects),
- else `plans/ideas/<slug>.md`, creating the dir; if not in a project, write beside the cwd and say so.

`<slug>` = kebab-case of a short title. The brief carries the eight pinned fields so `/plan-create` can
promote it without reformatting.

## Step 6 — Report & hand off
Print the **before → after** overall score, the path written, and:
> "Refined (17/32 → 27/32). Run `/plan-create` to turn this into a plan." — plus any Open questions left.

---

## The scale at a glance (full rungs in `templates/scale.md`)
| # | Characteristic | What "4" looks like |
|---|----------------|---------------------|
| 1 | Goal & motivation | Outcome + why, in one clear sentence |
| 2 | Success criteria | Measurable "done", incl. edge cases |
| 3 | Definitions | Every load-bearing term pinned & testable |
| 4 | Constraints & conventions | Hard limits + relevant `_code-conventions` named |
| 5 | Scope (in/out) | Explicit in-scope AND out-of-scope |
| 6 | Decomposition | Discrete, ordered steps |
| 7 | Architecture / module impact | Modules touched + boundaries ("must NOT know about") |
| 8 | Risks & unknowns | Key risks + the open unknowns named |

## Reuse (don't reinvent)
- `plan-create` Idea Template + `ideas/` lifecycle — the emitted brief plugs straight in.
- The eight characteristics = `plan-create` required sections + `### Architecture & Module Contracts` + `_code-conventions`.
- `AskUserQuestion` for the batched refinement rounds; reference `/arch-diff` for the architecture characteristic.

## Notes
- Keep it fast: most well-briefed ideas should reach the fast-path. The value is catching the *few*
  weak characteristics early, not scoring for its own sake.
- The characteristic set lives in `templates/scale.md` and is tunable — edit rungs there, not here.
