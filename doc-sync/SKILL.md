---
name: doc-sync
description: "Summarise the current Claude Code conversation and fold it into this repository's documentation — what was built, what was decided and why, and what was actually verified — editing the existing docs in their own voice rather than appending a session log. Use when a working session has moved ahead of the docs: after a feature lands, after a design decision is taken, or when the user says the docs are now behind."
argument-hint: "[doc-path ...] [--dry-run] [--session <id>] — default: the skill picks the docs"
disable-model-invocation: false
effort: high
---

# doc-sync — fold a session into the repo's documentation

A working session ends with the knowledge in the wrong place. The repository
holds the code; the reasoning that produced it — why this approach and not the
obvious one, what was measured, what was left undone on purpose — is in a
transcript nobody will open again. This moves that reasoning into the docs while
it is still recoverable.

It edits documentation **in place, in the voice already there**. It does not
append a changelog, and it does not create a "Session summary" section. A reader
six months from now should not be able to tell which paragraph came from a
conversation.

## When to use

- A feature or fix landed and the docs describe the state before it.
- A decision was taken with a real trade-off, and the reason will be lost.
- The session made an existing claim in the docs untrue.
- The user asks to summarise the conversation into the documentation.

## When not to use

- Nothing was built and nothing was decided — a session of questions and
  answers leaves no residue worth writing down.
- The user wants a commit. That is `_commit-procedure` / `plan-commit`, and
  this skill deliberately does not commit.
- The user wants a cross-day report of their own activity. That is
  `daily-brief`.

## Argument parsing: `$ARGUMENTS`

| Argument | Effect |
|---|---|
| empty | Survey the repo and choose which docs to update |
| one or more paths | Update only those files; still survey the rest for staleness |
| `--dry-run` | Report the proposed changes and write nothing |
| `--session <id>` | Digest that session instead of the current one |

## Layout

| Path | Purpose |
|---|---|
| `~/.claude/skills/doc-sync/scripts/extract_session.py` | Transcript → digest |
| `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl` | The raw transcript |
| `~/.claude/projects/<encoded-cwd>/<session-id>/subagents/*.jsonl` | Delegated work, absent from the main transcript |
| `$CLAUDE_CODE_SESSION_ID` | The current session id, set in the tool environment |

The folder name is the working directory with every character outside
`[A-Za-z0-9-]` replaced by a dash. The script does this itself; you should not
need to build the path by hand.

## Procedure

**1. Build the digest.** From the repository root:

```bash
PYTHONIOENCODING=utf-8 python ~/.claude/skills/doc-sync/scripts/extract_session.py \
  --subagents --out <scratchpad>/session-digest.md
```

Pass `--session <id>` if the user named one. `--subagents` matters: work you
delegated does not appear in the main transcript at all, so without it a session
that used agents looks like a session where little happened.

**2. Do not read the digest yourself.** A transcript is megabytes and a digest
is tens of kilobytes of someone else's dead ends. Dispatch **one subagent** and
give it, verbatim:

- the digest path;
- the repository root;
- the list of documentation files you found in step 3;
- the rules under *What goes in* and *Important rules* below;
- whether `--dry-run` is in force.

Ask it to return: the files it changed, one line each on what changed and why,
and anything it found stale but did not feel entitled to fix.

**3. Survey the documentation first, so the subagent is told where to write.**
Before dispatching, list what exists — `*.md` at the root, `docs/`, `README*`,
`CLAUDE.md` — and read enough of the two or three most relevant to know the
house voice. Repositories differ: some keep one README, some split *how it
works* from *how it came to work*. Match whatever is there. Create a new file
only when the session produced a subject that has no home, and say so in the
report.

**4. Verify the change-set against the repository, not the digest.** The
digest's file ledger only sees `Edit`/`Write` tool calls — **anything written
through a shell heredoc is invisible to it**. Cross-check with `git status`, or
with the modification times under the repo, before believing a list of what
changed.

**5. Report.** Name every file touched and what changed in it, then stop. Do not
commit, do not push, do not offer to.

## What goes in, and what does not

| Goes in | Stays out |
|---|---|
| A decision and the reason behind it | The order the work happened in |
| A trade-off that was weighed and rejected | Dead ends with nothing to teach |
| What was measured, with the number | An unverified claim dressed as a result |
| A limit that is deliberate | An apology or a narrative of the session |
| A correction to something the docs now get wrong | Anything already obvious from the code |

## Important rules

- **Never invent verification.** Write "343 transcripts parse, 81,805 cues" only
  if the digest shows that being run. If something was built but not tested, the
  docs should say so plainly — an untested claim in documentation is worse than
  a gap.
- **Correct what the session made untrue.** A doc that says "nothing has run on
  a device yet" after a session where it ran is a defect, and fixing it is part
  of the job, not scope creep.
- **Preserve the existing voice.** Read before writing. If the repo's docs use
  short declarative prose and tables, do not answer with bullet lists.
- **Do not commit.** The user decides when work is committed.
- **`--dry-run` writes nothing at all**, including new files.

## Edge cases

| Situation | Handling |
|---|---|
| The session summarises itself | The turn in flight is not in the transcript yet, so the last exchange is always missing. Fill it from your own context, and say in the report that you did. |
| Transcript folder not found | The cwd has no sessions recorded. Report the path tried; do not guess another. |
| Two sessions share a working directory | `$CLAUDE_CODE_SESSION_ID` is authoritative. Newest-mtime is the fallback and it is a guess — say so if you use it. |
| The digest is nearly empty | Say the session left no documentable residue and write nothing. That is a valid outcome. |
| Docs are generated, not written | Do not edit generated files. Report which they were. |
