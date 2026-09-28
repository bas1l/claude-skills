---
name: brainstorm-conversation
description: "Mature a raw idea through free-flowing, generative dialogue — widen the space, surface alternatives, and stress-test whether the stated goal is the one you really want. Re-runnable on the same idea; optionally hands off to /plan-create when the idea turns out to be buildable. Use to think an idea through, not to grade it."
argument-hint: "<rough idea | empty = the opening message | existing brainstorm slug to continue>"
disable-model-invocation: false
effort: high
---

# brainstorm-conversation — grow an idea by talking it through

The cheapest place to shape a project is before any plan exists. This skill treats an idea as a living
thing to **mature through conversation** — not a spec to grade. It widens the space of what the idea
could be, offers alternatives and provocations, and keeps checking the one thing that matters most:
**is the goal you stated the goal you actually want?** Progress is captured to a persistent brainstorm
file you can re-open and keep growing.

Its sibling `/brainstorm-interview` covers the same ground in a structured, question-led way. This one is
the free-flowing partner. Both write the same file, so an idea can move between them and keep maturing.

## Core stance
- **The goal is a hypothesis, not a given.** Probe the want beneath the stated goal; if the trajectory
  drifts from what the user really wants, say so and realign. Never just transcribe the first framing.
- **Widen before narrowing.** Generate options, analogies, inversions ("what if the opposite?"), adjacent
  framings. Expand the space first; converge only once there is something worth converging on.
- **Conversation, not interrogation.** One or two moves per turn, then listen. Follow the energy of the
  user's answers rather than marching through a list. Prefer prose to multiple-choice widgets.
- **Maturation over sessions.** The idea lives in a file. Re-running continues growth; it does not restart.

## Step 1 — Locate the idea
- If `$ARGUMENTS` names an existing brainstorm (a slug or title matching a file in the brainstorms dir),
  **load that file and continue** from where it stands — summarize the current form in one line first.
- Otherwise take the idea from `$ARGUMENTS` or the user's opening message. Restate the *intent* in one
  sentence and confirm you have it before diverging (don't invent scope).

## Step 2 — Brainstorm (the loop)
Run a genuine back-and-forth. Each turn, make ONE or TWO generative moves, then hand back:
- **Challenge the goal** — "you said X; is the real aim X, or is X a means to something bigger?"
- **Widen** — offer 2–3 alternative forms the idea could take, briefly.
- **Provoke** — invert it, push it to an extreme, remove its main assumption, or borrow from an analogy.
- **Deepen** — pull on whatever the user got animated about.

Keep it conversational. Do not batch a wall of questions. Let the idea change shape — that change *is* the
value, not filling out a form.

## Step 3 — Capture as you go
After a meaningful shift (a sharpened goal, a chosen direction, a dropped thread), update the brainstorm
file (format below). Don't wait until the end — the file is the memory of the maturation.

## Step 4 — Close a session
When the user winds down (or says stop), write the current best form back to the file, append one dated
line to the session log, and give a one-line status: what matured today, what's still open.

## Step 5 — Optional handoff (never forced)
If the idea has matured into something **buildable** and the user wants to act on it, offer:
> "Want me to turn this into a plan with `/plan-create`?"
Summarize the matured idea as its starting brief. If it is not (or not yet) a build task, just leave the
matured file — planning is optional, not the point of the skill.

---

## The brainstorm file
Write to `docs/development/brainstorms/<slug>.md` if the `docs/development/plans/` structure exists, else
`brainstorms/<slug>.md` (create the dir), else beside the cwd and say so. `<slug>` = kebab-case short
title. Both brainstorm skills share this exact format.

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
<!-- Directions considered — kept / parked / dropped, one line of why for each. -->

## Open questions
<!-- Unresolved — carry forward, don't block on them. -->

## Session log
<!-- Append one dated line each time the idea is grown. -->
~~~

## Notes
- Use today's date from context; do not invent timestamps.
- The value is the idea changing shape, not the template getting filled. The file serves the thinking.
