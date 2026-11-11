---
name: daily-brief
description: "Print the Daily Brief — an executive summary of what you accomplished in Claude Code on a given day and the top 5 things to focus on next, derived from your local session transcripts and persistent memories. Defaults to yesterday. Generates the brief on demand if it does not exist yet."
argument-hint: "[yesterday | today | YYYY-MM-DD | --regen] "
disable-model-invocation: false
effort: low
---

# daily-brief — what I did, and what's next

Reads the Claude Code transcripts stored on this machine
(`~/.claude/projects/<slug>/*.jsonl`) for one local calendar day, compresses them,
and prints an executive brief: **what got done** and **the top 3 priorities next**.

A scheduled task already generates yesterday's brief at 03:07 daily. This skill is
the manual entry point — for reading a past brief, or for briefing a day the
scheduler has not covered yet (including today).

## Layout

| Path | Purpose |
|---|---|
| `~/.claude/daily-brief/briefs/<date>.md` | The generated briefs — one per day |
| `~/.claude/daily-brief/Invoke-DailyBrief.ps1` | Runner: digest → headless Claude → brief |
| `~/.claude/daily-brief/Build-Digest.ps1` | Transcript compressor (~70 MB/day → ~180 KB) |
| `~/.claude/daily-brief/brief-prompt.md` | The summarization prompt — edit to change tone or structure |
| `~/.claude/daily-brief/logs/` | Run log plus the digest each brief was built from |

## Procedure

**1. Resolve the target date** from `$ARGUMENTS`:

- empty or `yesterday` → yesterday
- `today` → today's date
- `YYYY-MM-DD` → that date
- `--regen` → same date resolution, but force regeneration

Compute the actual date with PowerShell rather than assuming — do not rely on a
remembered "today".

**2. If the brief already exists** at `~/.claude/daily-brief/briefs/<date>.md`
and `--regen` was not passed, just read and print it. Do not regenerate — briefs
are cheap to read and expensive to rebuild.

**3. Otherwise generate it.** This takes ~40 s and consumes quota:

```powershell
& "$env:USERPROFILE\.claude\daily-brief\Invoke-DailyBrief.ps1" -Date <YYYY-MM-DD> [-Force]
```

Then read the resulting file.

**4. Print the brief verbatim** into the conversation. It is already formatted
for reading — do not re-summarize it, re-order it, or add commentary around it.

## Notes

- Briefing **today** is legitimate but partial: it only covers sessions closed so
  far. Say so when you do it.
- A day with no sessions produces a short placeholder brief. That is a correct
  result, not a failure.
- If the runner throws, read `~/.claude/daily-brief/logs/daily-brief.log` and the
  matching `digest-<date>.md` to tell a transcript-extraction problem apart from a
  summarization problem.
