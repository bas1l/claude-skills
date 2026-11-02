# Upkeep

Scheduled passes that read the Claude Code conversations on this PC, keep memories up to date with quoted evidence, and propose changes to skills, hooks, plugins, MCP servers and global instructions. Unattended runs change memories only. Everything else waits for the weekly review.

The model is called with no tools, or with only the web tools for research. Scripts do all reading, checking and writing.

## What runs when

All times are local and stay local across daylight saving.

| Task | When | What it does |
|---|---|---|
| `Claude Code Upkeep Daily` | Every day, 01:00 | Reads new sessions, writes notes and counts, adds ledger entries, commits memory folder snapshots |
| `Claude Code Upkeep Weekly` | Wednesday, 02:00 and 05:30 | Runs the daily pass if that day's did not complete, applies memory changes, researches proposals, writes the review. The 05:30 run does nothing if the week's pass succeeded |
| `Claude Code Upkeep Monthly` | First Saturday, 03:00 and 09:30 | Audits the whole setup. Only proposes; results join the next weekly review. The 09:30 run does nothing if the month's pass succeeded |

Each task runs without a logged-on user (S4U), wakes the PC, runs as soon as possible after a missed start, needs a network and stops after 6 hours. A new run catches up all unprocessed sessions. Each pass has a budget, `model.run_budget_usd` in `config.json`.

Nothing here touches `Claude Code Daily Brief` or `Claude Code Weekly Rollup`.

## Going live on this PC

Do these in order, after the feature branch is merged. Registration needs an elevated window, and the first step that uses web research under S4U is the one thing not yet verified.

1. Update the installed copy: `git -C "$HOME\.claude\skills" pull`. On this PC there is no more to do here: `stance_check.py rejudge-old` was run on the data folder on 2026-11-02, and the next pass judges those stances again. On a data folder that holds verdicts of an older version, run `python "$HOME\.claude\skills\upkeep\stance_check.py" rejudge-old` here, or the next pass stops and says so. It removes those verdict files and the ledger entries they let through.
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
| `state/` | Which sessions are processed, up to which line of each file |
| `notes/YYYY-MM-DD/`, `counts/` | Extraction notes and script-made counts |
| `ledgers/` | Reasons for and against each memory, skill, hook and MCP server, rules broken at a cost, faults of a hook or tool, what could not be read, possible renames, and every verdict of the stance check |
| `proposals/`, `reports/YYYY-Www/`, `reports/monthly/` | Proposals, drafts, and the weekly review and its page |
| `logs/` | One record per run, usage, and each run's output |
| `run/`, `review/` | Working folders of the passes and of the review session |
| `local.json` | This machine's interpreter, private terms and `apply_memory_changes` |
| `failure-marker.json` | Exists only when a run has something to report |

Each memory folder under `~/.claude/projects/` is its own local git repository, also with the push guard.

## When a session starts with `Upkeep warning:`

The `upkeep_status` hook prints that line when `failure-marker.json` exists, or when no scheduled pass has logged a run for `status.warn_after_hours_without_run` hours (only where upkeep is installed and has run once), and is otherwise silent. It stays out of the passes' own runs, which disable all hooks. The line gives pass, kind and time; the marker holds each entry's summary, the failed session ids and the path to its log.

| Kind | Means | What clears it |
|---|---|---|
| `failed` | The pass stopped, did not start because another run held the lock, or could not read an item or a session and went on with the rest | The next clean run of that pass |
| `budget stopped` | The budget ran out; the rest wait | The next clean run of that pass |
| `stale lock` | A run ended without releasing its lock, or left one that could not be read | Read it, then delete the entry or the file |
| `secrets matched` | A secret pattern was redacted from notes | Read those notes, then delete the entry or the file |
| `window reset` | A session's records changed, so it was read again | Read it, then delete the entry or the file |
| `no run for N hours` | The scheduled tasks stopped firing, or are paused or not registered yet. It is not an entry in the marker | The next run of a pass |

To rerun by hand, from any window: `pwsh -File "$HOME\.claude\skills\upkeep\Invoke-Upkeep.ps1" -Pass daily`, or `weekly` or `monthly`. A monthly pass that failed at 03:00 retries by itself at 09:30, after the 03:00 run's 6-hour limit. If that fails too, it waits for this or for next month. A spent weekly limit will not have reset by 09:30, so that case takes a hand run.

A broken marker reports itself as broken. Read it, then delete it. The marker can only be written if the data folder exists, so a run that fails before that shows only in the task's last result: `Get-ScheduledTaskInfo -TaskName 'Claude Code Upkeep Daily'`.

## When an item cannot be read

One bad item stops nothing else. A skill or memory whose header the reader does not know, or a ledger file that is not valid, is listed in `ledgers/item-problems.json`. The other items go on, the weekly memory step still runs, the review shows it at the top, and the pass ends `failed` with a non-zero exit until the file is fixed. A file that cannot be read gets no new ledger until it can be, because a founding reason is written once.

An entry whose note no longer holds its text is listed the same way. A window read again by a pass cannot cause this, since the pass takes out that window's entries first, so it means notes were replaced by hand or by some other script. Nothing repairs it for you. Delete that entry from the ledger file, and the next pass makes the entry anew if the note still calls for one.

A name matches its ledger whatever its case. A note naming `Plan-Create` reaches the ledger of `plan-create`, and a memory renamed only in case takes its ledger along. Each part of a session is read with a list of known names: every skill, hook, tool server and plugin, and the memories of that session's project folder, each with a short description. There are no global memories to add, since each folder holds its own. A hook also matches the status message its settings give it, which is what sessions call it, so `Kettle gate` reaches `kettle_gate`. A status message two scripts share matches neither. A name not on the list, written as `unknown: ...` by the reader, a true mismatch, and a name whose file holds some other item all go to `ledgers/unmapped-mentions.json`, whatever their stance.

A rename to another name cannot be told from one item removed and another added, so entries stay under the old name. If an item with entries is gone, and a new empty one of the same scope and kind has the same founding reason or much the same name, the review lists the pair for `ledger.rename_flag_days` days. It fails nothing. If it is one item, move the entries into the new ledger file by hand, and delete the old file.

## Rules a reader may want

- **Lost balance** (`ledger.py`, `config.json`): an item is flagged for revision by one direct statement against, meaning the user's verified words about this item itself, or when, within 28 days, the sessions with an inferred entry against less the sessions with an entry for come to 3, with no direct statement for in that time. Four sessions against and one for flags; three against and one for does not. One inferred "for" no longer clears everything for 28 days, because the aim is to catch an item whose balance is lost over weeks. This differs from the plan, which says "3 agent-inferred entries" with no entry for. Counting sessions is narrower on purpose: three parts of one session saying one thing are one piece of evidence. `ledger.inferred_against_entries` keeps its name, and now means that balance of sessions. A flag on a skill, hook, tool server or plugin that is no longer installed raises no proposal.
- **Every stance is checked before it counts** (`stance_check.py`, `prompts/stance_check.md`): the reader sees a short description of each item, so the check gets every stance, `no_bearing` included, with its note and the item's real description and contents, redacted. Its verdict is one of `kept`, `raised` (no bearing to for or against), `lowered` (it played a part, but falls short), `refused` (it had no part, or the case is excluded) or `reversed`. Every verdict and its reason is listed in `ledgers/stance-verdicts.json`, and the review page shows the counts and the cost for the last 28 days. A stance not judged yet makes no entry and waits for the next pass. A call that fails, or a verdict that does not fit its stance, ends the pass failed, and what earlier calls settled stays. An item's stances go in one call, each item comes with its latest rulings from earlier passes (`item_check.earlier_rulings_shown`), and a long list is split by `item_check.group_chars`. The model is `item_check.model`, now Sonnet; see [docs/verification.md](docs/verification.md) for the two compared.
- **What `for` and `against` mean** (both prompts): `for` needs the assistant doing what this item specifically says where its ordinary default would differ, with the user's next reaction accepting the result, on a task the item is meant for. A reply about something else accepts nothing. Or the user stating the item's rule in their own words; or, for a tool server or plugin, a result that visibly changed what the user then used. `against` needs harm from following the item, the user rejecting it, or, for a hook, tool server or plugin, its own behaviour costing repeated work. A stance is left out only where the item is this job itself or the only evidence is this job's own report. A session merely about this job counts like any other for other items.
- **Direct means about this item:** a note's endorsement says the user stood behind the note's point, which may have nothing to do with the item named. So the check also says whether the verified quote is about this item, and only then is the entry direct. Otherwise it is inferred, and neither flags alone nor holds flags back.
- **A rule broken at a cost** is an entry with direction `rule_broken` in the item's ledger, when the assistant went against the item and the user corrected it or work was redone. It counts for nothing in the balance, since an unfollowed rule neither helped nor harmed. The review page lists each item with its count, because a rule broken again and again may need revising.
- **A hook's or tool's own fault, once in a session,** is an entry with direction `malfunction`. Twice in one session is `against`, so a defect firing once per session across many sessions would otherwise never show. For example, a hook that wrongly blocks one finished reply in each of 9 sessions gets 9 such entries and no `against`. The balance reads none of them, and the review page gives each item's count: "9 times in 9 sessions in the last 28 days". A memory or skill does not act by itself, so it has none, and a block that was right is not one.
- **A quiet ledger shows little:** `for` needs a visible reaction from the user, and most of the time nobody says anything when something works. So a missing `for` means little, and a quiet ledger does not show that an item is fine. The page says so on each ledger summary. In the one measured sample, 3 of 5 `for` entries were wrong, so few `for` entries is also no count of real use.
- **One statement split into claims** (`weekly_gate.py`): if a claim is rejected, each other claim quoting the same user message becomes a proposal, with the reason, since saving only the stricter half would say something the user did not say. A claim that merely does not fit the file, such as one already there, does not count as rejected for this. Approving a create or add writes it. A replace or remove is read and revised by hand.
- **Upkeep quality** (monthly): `acceptance_rate` covers only what someone had to approve or reject. Applied memory changes get their own figures, since a change stands unless it is undone.
- **Page version:** the review page shows its version. A session stays on the version of its first action, and if the review moves on, every action is refused until Basil has reloaded the page and said so.

## Pause

From an elevated window, for one task or each of them:

```powershell
Disable-ScheduledTask -TaskName 'Claude Code Upkeep Daily'
Enable-ScheduledTask -TaskName 'Claude Code Upkeep Daily'
```

Running `install.ps1 -RegisterUpkeep` or `Register-UpkeepTasks.ps1` again re-enables them.

## Undo

- **A memory change:** in the review, "undo N". This adds a new commit, and the change is not proposed again unless new evidence comes from you. A change stays in the review after a failed run or a crash, since `reports/YYYY-Www/applied.json` records it before it is written. Otherwise, revert that commit in the memory folder.
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
