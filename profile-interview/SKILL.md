---
name: profile-interview
description: "Elicit Basil's expertise levels, knowledge gaps, and explanation-style preferences into ~/.claude/basil/, so explanations can be calibrated to what he already knows. Run a module, drain the parked-questions queue, or continue where the last session stopped."
argument-hint: "<module id (M1-M13) | 'queue' | 'status' | empty = next priority module>"
disable-model-invocation: false
effort: high
---

# Profile interview

Fills `~/.claude/basil/` — the personal profile that is imported into every session via
`@basil/PROFILE.md` and used to decide how deeply to explain any given topic.

## Files

| File | Role |
|---|---|
| `~/.claude/basil/PROFILE.md` | Eager index: identity + the expertise-level table. Must stay small. |
| `~/.claude/basil/_interview.md` | The question bank. Modules M1–M13 with `[ ]` / `[x]` status. |
| `~/.claude/basil/_queue.md` | Topics parked mid-session at an unknown level. |
| `~/.claude/basil/<type>-<slug>.md` | Leaf files: one fact each, for anything with a reason behind it. |

## Argument handling

- **empty** — read `_interview.md`, pick the highest-priority module with unanswered items, run it
- **`M3`** (or any module id) — run that module
- **`queue`** — drain `_queue.md` instead of a module
- **`status`** — report counts answered/unanswered per module and queue depth, then stop

## Procedure

1. **Read** `_interview.md` and `PROFILE.md`. Do not read leaf files unless an item touches one.
2. **Announce** which module is running and roughly how many items it holds. One line.
3. **Ask in batches of 3–4** using AskUserQuestion. For level items, offer the 0–4 scale as options
   with the *behavioural consequence* spelled out in each option description — Basil is calibrating
   your output, not rating himself, and the options should make that concrete.
4. **Accept loose answers.** "Everything in that block is 1 except EEG which is 3" is a complete
   answer. Do not re-ask item by item to make it tidy.
5. **Record as you go**, not at the end — a session that gets interrupted must not lose answers.
   Levels go into the `PROFILE.md` table; drop the `*` when an inferred value is confirmed.
   Reasoned facts go into leaf files per the schema at the bottom of `_interview.md`, with a
   one-line pointer added under **Leaf files** in `PROFILE.md`.
6. **Mark items `[x]`** in `_interview.md` as they are answered. Leave skipped items `[ ]`.
7. **Stop when the module ends** or Basil says stop. Report what was recorded and what remains.

## Hard rules

- **Never infer a level.** A guessed level silently miscalibrates every future explanation on that
  topic and Basil has no way to notice. Unanswered is a known unknown; guessed is a hidden error.
- **Never let `PROFILE.md` grow past the level table plus identity plus pointers.** It costs tokens
  in every session, in every project. Detail goes in leaf files.
- **One fact per leaf file.** Same convention as the project memory system.
- **Contradictions win over age.** If a new answer contradicts an existing entry, overwrite it and
  say so — do not keep both.
- Do not implement, refactor, or touch anything outside `~/.claude/basil/` and `_interview.md`.

## Parking a question during normal work

Outside this skill, when a topic comes up whose level is unknown and there is no time to ask,
append to `_queue.md`:

```
- [ ] <topic> — hit in <project/context> on <YYYY-MM-DD> — <why it mattered>
```

Then proceed using the fallback in `CLAUDE.md`. The queue is drained later via
`/profile-interview queue`.
