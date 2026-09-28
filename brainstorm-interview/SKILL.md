---
name: brainstorm-interview
description: "Mature a raw idea through a structured, question-led exploration — walk a set of exploration dimensions that widen the idea and stress-test whether the stated goal is the one you really want. Re-runnable on the same idea; optionally hands off to /plan-create when the idea turns out to be buildable. Explores and challenges, does NOT grade readiness."
argument-hint: "<rough idea | empty = the opening message | existing brainstorm slug to continue>"
disable-model-invocation: false
effort: high
---

# brainstorm-interview — grow an idea by walking it through

Same purpose as `/brainstorm-conversation` — **mature an idea, don't grade it** — but the structured
sibling. It walks a small set of **exploration dimensions**, one small batch at a time, using each to
*widen the idea and test the goal* rather than to score readiness. Progress is captured to the same
persistent brainstorm file, so an idea can move between the two skills and keep growing.

**Not a readiness gate.** Unlike `/idea` (which scores an idea 0–4 to check it's plan-ready), this skill
never scores and never gates. The dimensions are prompts for exploration, not a rubric to pass.

## Core stance
- **The goal is a hypothesis, not a given.** Dimensions 1 and 4 exist to challenge the stated goal and
  realign the trajectory toward what the user really wants. Never just transcribe the first framing.
- **Structured, but exploratory.** The dimensions give shape; the aim within each is to open the idea up,
  not to close it down to a checkbox.
- **Batched, discrete, prose-first.** Ask 2–3 questions per round as discrete numbered points; let the
  user answer in prose. Don't dump all dimensions at once, and don't force multiple-choice widgets.
- **Maturation over sessions.** The idea lives in a file. Re-running continues growth; it does not restart.

## Step 1 — Locate the idea
- If `$ARGUMENTS` names an existing brainstorm (a slug/title matching a file in the brainstorms dir),
  **load it and continue** — summarize where it stands, then resume at the first unresolved dimension.
- Otherwise take the idea from `$ARGUMENTS` or the opening message. Restate the *intent* in one sentence
  and confirm before proceeding (don't invent scope).

## Step 2 — Walk the dimensions
Work through the exploration dimensions below, **2–3 per round**, as discrete numbered questions. After
each round, reflect the answers back — reshaped, not just echoed — and let that reshaping feed the next
round. Cap at ~2–3 rounds; if a dimension stays fuzzy, park it under Open questions and move on. This is
exploration, not interrogation.

### Exploration dimensions
1. **Real goal.** What are you actually trying to achieve? Is the stated goal the true one, or a *means*
   to a deeper want? (Keep returning here as later answers shift it.)
2. **Trigger & stakes.** Why now? What happens if you don't do it? Who is it for?
3. **What "worth it" feels like.** How will you know this was worth doing — in felt terms, not just metrics?
4. **Alternatives.** What other forms could reach the real goal? (Surface at least two the user hasn't named.)
5. **The essence.** Strip it to the core: what is indispensable vs merely nice-to-have?
6. **Constraints & reality.** What's fixed, what's negotiable, what you will *not* do.
7. **Risks & unknowns.** The biggest risk, and the one unknown worth resolving first.
8. **Next move.** The smallest concrete step that would grow this idea further.

## Step 3 — Capture as you go
After each round, update the brainstorm file (format below). The file is the memory of the maturation —
write to it during, not only at the end.

## Step 4 — Close a session
Write the current best form back to the file, append one dated line to the session log, and give a
one-line status: what firmed up, what's still open.

## Step 5 — Optional handoff (never forced)
If the idea has matured into something **buildable** and the user wants to act on it, offer:
> "Want me to turn this into a plan with `/plan-create`?"
Summarize the matured idea as its starting brief. If it is not (or not yet) a build task, leave the
matured file — planning is optional.

---

## The brainstorm file
Write to `docs/development/brainstorms/<slug>.md` if the `docs/development/plans/` structure exists, else
`brainstorms/<slug>.md` (create the dir), else beside the cwd and say so. `<slug>` = kebab-case short
title. Identical format to `/brainstorm-conversation`.

~~~markdown
# Brainstorm: <title>

**Started:** <date>   **Last matured:** <date>   **Status:** Brainstorming | Matured | Handed off

## Real goal (north star)
<!-- What the user is actually trying to achieve. May differ from the first-stated goal; revisit each session. -->

## Where it stands
<!-- One paragraph: the current best form of the idea. Rewritten as it matures. -->

## Alternatives on the table
<!-- Forms still worth considering, each with a one-line note. -->

## Threads explored
<!-- Dimensions walked — what each surfaced, kept / parked / dropped. -->

## Open questions
<!-- Unresolved — carry forward, don't block on them. -->

## Session log
<!-- Append one dated line each time the idea is grown. -->
~~~

## Notes
- Use today's date from context; do not invent timestamps.
- No scores, ever. If you catch yourself grading, you're doing `/idea`'s job, not this one.
