# Upkeep

Scheduled passes that read the Claude Code conversations on this PC, keep memories up to date with quoted evidence, and propose changes to skills, hooks, plugins, MCP servers and global instructions. Unattended runs change memories only. Everything else waits for the weekly review.

The model is called with no tools, or with only the web tools for research. Scripts do all reading, checking and writing.

## What runs when

All times are local and stay local across daylight saving.

| Task | When | What it does |
|---|---|---|
| `Claude Code Upkeep Daily` | Every day, 01:00 | Reads new sessions, writes notes and counts, adds ledger entries, commits memory folder snapshots |
| `Claude Code Upkeep Weekly` | Wednesday, 02:00 and 05:30 | Runs the daily pass if that day's did not complete, applies memory changes, researches proposals, writes the review. The 05:30 run does nothing if the week's pass succeeded |
| `Claude Code Upkeep Monthly` | First Saturday, 03:00 | Audits the whole setup. Only proposes; results join the next weekly review |

Each task runs without a logged-on user (S4U), wakes the PC, runs as soon as possible after a missed start, needs a network and stops after 6 hours. A new run catches up all unprocessed sessions. Each pass has a budget, `model.run_budget_usd` in `config.json`.

Nothing here touches `Claude Code Daily Brief` or `Claude Code Weekly Rollup`.

## Going live on this PC

Do these in order, after the feature branch is merged. Registration needs an elevated window, and the first step that uses web research under S4U is the one thing not yet verified.

1. Update the installed copy: `git -C "$HOME\.claude\skills" pull`.
2. In an elevated PowerShell 7 window, run the installer with the opt-in flag:
   ```powershell
   pwsh -File "$HOME\.claude\skills\setup\install.ps1" -RegisterUpkeep
   ```
   Check first with `pwsh -File "$HOME\.claude\skills\upkeep\Register-UpkeepTasks.ps1" -PlanOnly`, which changes nothing and needs no elevation.
3. In the same window, check web research under S4U, once:
   ```powershell
   pwsh -File "$HOME\.claude\skills\upkeep\Register-UpkeepTasks.ps1" -CheckResearch
   ```
   It runs one real research call through the weekly pass's own code and flags in a temporary task, then removes the task. Expect `RESEARCH CHECK PASSED`. In a user process the same check took 50 seconds and reported $0.15; its limit is the research budget of one candidate. On failure it says so, exits 1, and leaves a warning that appears at each session start until a rerun passes. Do not go on until it passes: without web research the weekly pass stops and writes no proposal.
4. Restart Claude Code, so the session-start hook is active.
5. Click the desktop shortcut `Claude Upkeep Review`. If it is missing: `pwsh -File "$HOME\.claude\skills\upkeep\Start-UpkeepReview.ps1" -CreateShortcut`. The page and a review session should open. This also settles whether the launch through Windows Terminal works, which has not been run.
6. Review the dry run. In that session, read each listed memory change and try one of each: "undo 1", "approve 2", "why 3?".
7. Only then set `"apply_memory_changes": true` in `~/.claude/upkeep/local.json`. Until then the weekly pass writes its report and applies no memory change.

## Week one: measured duration and tokens

**Pending.** To be filled in after one full week of scheduled runs (plan task 7.3). The sources are `~/.claude/upkeep/logs/runs.jsonl` for wall time and exit code, and `logs/usage.jsonl` and `reports/<week>/usage.jsonl` for tokens and cost.

| Pass | Runs | Wall time (typical, longest) | Tokens | Cost reported | Limit failures |
|---|---|---|---|---|---|
| Daily | pending | pending | pending | pending | pending |
| Weekly | pending | pending | pending | pending | pending |
| Monthly | pending | pending | pending | pending | pending |

Web research under S4U: pending, from step 3 above.

## Where data lives

Code is in this repository, which is public. All data stays outside it, in `~/.claude/upkeep/`, a local git repository with a guard that refuses pushes:

| Path | Holds |
|---|---|
| `state/` | Which sessions are processed, and up to when |
| `notes/YYYY-MM-DD/`, `counts/` | Extraction notes and script-made counts |
| `ledgers/` | Reasons for and against each memory, skill, hook and MCP server |
| `proposals/`, `reports/YYYY-Www/`, `reports/monthly/` | Proposals, drafts, and the weekly review and its page |
| `logs/` | One record per run, usage, and each run's output |
| `run/`, `review/` | Working folders of the passes and of the review session |
| `local.json` | This machine's interpreter, private terms and `apply_memory_changes` |
| `failure-marker.json` | Exists only when a run has something to report |

Each memory folder under `~/.claude/projects/` is its own local git repository, also with the push guard.

## When a session starts with `Upkeep warning:`

The `upkeep_status` hook prints that line only when `failure-marker.json` exists, and is otherwise silent. It stays out of the passes' own runs, which disable all hooks. The line gives pass, kind and time; the marker holds each entry's summary, the failed session ids and the path to its log.

| Kind | Means | What clears it |
|---|---|---|
| `failed` | The pass stopped, or did not start because another run held the lock | The next clean run of that pass |
| `budget stopped` | The budget ran out; the rest wait | The next clean run of that pass |
| `stale lock` | A run ended without releasing its lock | Read it, then delete the entry or the file |
| `secrets matched` | A secret pattern was redacted from notes | Read those notes, then delete the entry or the file |
| `window reset` | A session's records changed, so it was read again | Read it, then delete the entry or the file |

To rerun by hand, from any window: `pwsh -File "$HOME\.claude\skills\upkeep\Invoke-Upkeep.ps1" -Pass daily`, or `weekly` or `monthly`. A monthly pass that failed has no retry until you do this.

A broken marker reports itself as broken. Read it, then delete it. The marker can only be written if the data folder exists, so a run that fails before that shows only in the task's last result: `Get-ScheduledTaskInfo -TaskName 'Claude Code Upkeep Daily'`.

## Pause

From an elevated window, for one task or each of them:

```powershell
Disable-ScheduledTask -TaskName 'Claude Code Upkeep Daily'
Enable-ScheduledTask -TaskName 'Claude Code Upkeep Daily'
```

Running `install.ps1 -RegisterUpkeep` or `Register-UpkeepTasks.ps1` again re-enables them.

## Undo

- **A memory change:** in the review, "undo N". This adds a new commit, and the change is not proposed again unless new evidence comes from you. Otherwise, revert that commit in the memory folder.
- **A whole pass:** each memory folder has one commit per pass, so revert that commit in each folder. The commit message names the run.
- **Stop applying memory changes, keep the rest:** set `apply_memory_changes` to false in `local.json`.

## Uninstall

1. In an elevated window: `pwsh -File "$HOME\.claude\skills\upkeep\Register-UpkeepTasks.ps1" -Unregister`. Only the three upkeep tasks are removed.
2. Remove the `upkeep_status` entry from `SessionStart` in `setup/settings.hooks.json`, or revert the feature branch, and run `install.ps1`.
3. Delete the desktop shortcut.
4. `~/.claude/upkeep/` can stay or be deleted. Memory repositories can stay, since `.git` folders do not affect memory loading.

## On another machine

Nothing runs unless asked. `install.ps1` registers no task without `-RegisterUpkeep`, and the hook is silent with no marker. To opt in, first create the data folder with `memory_store.py init-upkeep` and `daily.py init-state`, and write `local.json` with `python_exe`, `apply_memory_changes` and `private_terms`. Registration stops and names what is missing.

## More

- What was actually run and verified, and what was not: [docs/verification.md](docs/verification.md).
- Tests: `python -m pytest upkeep/tests`. All fixtures are synthetic.
