---
name: weekly-rollup
description: "Print the Weekly Rollup — diffs a week of daily briefs to show what did NOT move: priorities carried day after day without resolution, ranked by days stalled, plus what got resolved and what is newly open. Defaults to the 7 days ending yesterday. Generates on demand if missing."
argument-hint: "[empty = last 7 days | YYYY-MM-DD (window end) | --days N | --regen]"
disable-model-invocation: false
effort: low
---

# weekly-rollup — what didn't move

A daily brief cannot tell a fresh priority from one deferred every day for a
month; both look identical in isolation. This diffs a run of daily briefs and
leads with the **carried-over set** — items that appeared as a priority on
multiple days and never appeared as an accomplishment.

Reads the already-generated briefs, not the transcripts, so it is cheap
(~60 K tokens, ~$0.22, ~100 s).

A scheduled task generates it every Monday at 03:20 for the week just ended.
This skill is the manual entry point.

## Layout

| Path | Purpose |
|---|---|
| `~/.claude/daily-brief/rollups/<start>_to_<end>.md` | The generated rollups |
| `~/.claude/daily-brief/Invoke-WeeklyRollup.ps1` | Runner |
| `~/.claude/daily-brief/rollup-prompt.md` | The prompt — edit to change structure |
| `~/.claude/daily-brief/logs/usage-rollup.csv` | Token/cost ledger |

## Procedure

**1. Resolve the window** from `$ARGUMENTS`:

- empty → the 7 days ending yesterday
- `YYYY-MM-DD` → the 7 days ending on that date
- `--days N` → window length N instead of 7
- `--regen` → force regeneration

Compute dates with PowerShell; do not rely on a remembered "today".

**2. If the rollup already exists** at
`~/.claude/daily-brief/rollups/<start>_to_<end>.md` and `--regen` was not passed,
read and print it. Do not regenerate.

**3. Otherwise generate it:**

```powershell
& "$env:USERPROFILE\.claude\daily-brief\Invoke-WeeklyRollup.ps1" -WeekEnding <YYYY-MM-DD> [-Days N] [-Force]
```

**4. Print it verbatim.** Do not re-summarize or re-order it.

## Notes

- Needs at least 2 daily briefs in the window; it throws otherwise. If briefs are
  missing, offer to backfill them with `Invoke-DailyBrief.ps1 -Date <date>` first
  (~$0.20 each) rather than silently rolling up a partial week.
- Missing days are passed to the prompt explicitly so they are not counted against
  any item's stall count.
- The **day counts are the load-bearing claim** in this document. If the user
  disputes one, check it against the individual briefs in
  `~/.claude/daily-brief/briefs/` rather than defending the model's arithmetic.
