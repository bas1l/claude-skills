---
name: critique
description: "Orchestrates /challenge then /mediator in sequence on a plan: runs opposition analysis first, then adjudicates plan vs challenge — both as background agents"
allowed-tools:
  - Agent
---

# Critique — Orchestrated Challenge + Mediation

Runs `/challenge` and `/mediator` in sequence on a single plan or file:

1. **Challenge phase** (background): Argues against the plan, writes `<plan>-challenge.md` to `docs/development/challenges/`
2. **Mediation phase** (background): Adjudicates the plan vs its challenge file

Receives `$ARGUMENTS` — a plan name or file path accepted by `/challenge`.

---

## Step 1: Validate input

If `$ARGUMENTS` is empty → ask the user what to critique, **stop**.

---

## Step 2: Launch challenge agent (background)

Use the Agent tool with `run_in_background: true` and `subagent_type: "general-purpose"`.

Agent description: `"Run challenge skill on $ARGUMENTS"`

Agent prompt (substitute `$ARGUMENTS` literally):
> Read the skill file at `C:\Users\basil\.claude\skills\challenge\SKILL.md` in full,
> then follow every step exactly as written, treating `$ARGUMENTS` as the `$ARGUMENTS`
> value. Complete all steps including writing the `-challenge.md` output file.

Inform the user: "Challenge phase started in the background for `$ARGUMENTS`."

---

## Step 3: Wait for challenge completion

Do NOT launch the mediator until you receive the challenge agent's completion
notification. The mediator requires the `-challenge.md` file that challenge produces.

When the challenge agent completes, briefly confirm: "Challenge complete. Starting mediation."

---

## Step 4: Launch mediator agent (background)

Use the Agent tool with `run_in_background: true` and `subagent_type: "general-purpose"`.

Agent description: `"Run mediator skill on $ARGUMENTS"`

Agent prompt (substitute `$ARGUMENTS` literally):
> Read the skill file at `C:\Users\basil\.claude\skills\mediator\SKILL.md` in full,
> then follow every step exactly as written, treating `$ARGUMENTS` as the `$ARGUMENTS`
> value. The mediator will auto-pair the plan with its `-challenge.md` file.
> Return the full adjudication report in your response.

---

## Step 5: Report mediation results

When the mediator agent completes, relay its full adjudication report to the user.
