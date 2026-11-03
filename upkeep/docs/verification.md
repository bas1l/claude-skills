# Upkeep: Phase 0 verification

Results of running what the docs state, before building on it. Run on 2026-11-01 with Claude Code 2.1.316 on Windows 11, from a non-elevated (Medium integrity) process.

## Summary

| Check | Result | Status |
|-------|--------|--------|
| 0.1 Trial files copied | 109 files, sizes match | Verified |
| 0.2 `disableAllHooks` under `-p` | Stops the TL;DR gate, session-start hooks and mods | Verified |
| 0.3 No tools | `--tools ''` alone is **not enough**: MCP tools stay. Needs `--strict-mcp-config` | Verified |
| 0.4 Web tools under S4U | Works in a user process and in an Interactive-logon task. S4U itself not run | **Not verified** |
| 0.5 Slash command through `wt.exe` | Not observed. The design uses the plain prompt | **Not verified**: needs the user's click at review |
| 0.6 S4U registration | **Needs elevation**: "Access is denied" when not elevated | Verified for the non-elevated case |

## Flags to pin

Extraction call:

```
claude -p --tools "" --permission-mode dontAsk --strict-mcp-config --disable-slash-commands --settings '{"disableAllHooks":true}'
```

Research call:

```
claude -p --tools "WebSearch,WebFetch" --allowedTools "WebSearch,WebFetch" --permission-mode dontAsk --permission-prompts none --strict-mcp-config --disable-slash-commands --settings '{"disableAllHooks":true}'
```

## What changes in the design

1. **`--tools ''` does not remove MCP tools.** The plan's extraction flags are not enough on their own. Without `--strict-mcp-config` the model had 13 MCP tools, including tools that create and delete documents, and it called one. Only `dontAsk` stopped that call.
2. **Research needs `--allowedTools`.** Under `dontAsk`, `--tools` makes a tool visible but does not permit it: both web tools were denied until they were also allowed.
3. **`Register-UpkeepTasks.ps1` must run elevated**, which means one UAC prompt. It cannot run silently from `setup/install.ps1` in a normal shell. It should check for elevation and stop with a clear message.
4. **A tool-less model can write fake tool calls as plain text.** In the 0.3 run the reply was 1,910 characters of `<invoke ...>` text. Nothing ran, but the result still reports `is_error: false`, so `schemas.py` has to reject it.

Item 4 supports the planned schema validation and does not add to it. No change to `tldr_gate.py` is needed.

## Test method

Each call ran through a Python list of arguments, so no shell altered the quoting. Unless stated otherwise, each used `--model haiku`, `--output-format stream-json --verbose --include-hook-events` and `--debug-file`, with the prompt on stdin, in a new folder under the system temp folder, and with `CLAUDECODE`, `CLAUDE_CODE_*` and similar variables removed so the nested call resembled a scheduled one.

Evidence came from the `init` event (tools, MCP servers, permission mode), `tool_use` blocks, `permission_denials`, hook events, the debug log, the gate's own log and the working folder's contents.

**Launch from a Windows `PATH`, not from a Git Bash shell.** The first control run, started from Git Bash, logged `Git Bash not found`, and hooks with quoted commands failed with a PowerShell parse error, so the gate never ran and that control proved nothing. Rerunning from PowerShell fixed it. The `PATH` difference is the likely cause; it was not isolated. Scheduled runs are not affected as far as tested: the Interactive-logon task did not log this message.

## 0.1 Trial files

Copied both trial folders from the session scratchpad to `~/.claude/upkeep/trials/`, then compared relative path and size for every file.

| Folder | Files, source and copy | Bytes, source and copy | Differences |
|--------|-------|-------|---|
| `trial-extraction` | 28 | 2,731,500 | 0 |
| `trial-whole-session` | 81 | 4,170,661 | 0 |

Sizes were compared, not contents. **Verified.** No `git init` was run.

## 0.2 `disableAllHooks` under `-p`

The prompt asked for a plain essay of about 350 words with no summary block, so the gate should block it.

| | Control | Hooks disabled |
|---|---|---|
| Added flags | none | `--settings '{"disableAllHooks":true}'` |
| Reply length, first attempt | 1,844 characters | 2,104 characters |
| Hook events | 28 | 0 |
| Gate decisions | 4 blocks | none; no entry for this session in the gate's log |
| Turns | 5 | 1 |
| Cost reported | $0.0061 | $0.0023 |
| Third-party plugin hook modules | loaded | 7 of 7 `not loaded` |
| Mod slash commands | present | 5 removed |

Both used `--tools "" --permission-mode dontAsk`. The control also shows the gate pushing the model to argue with it in its final reply, which is what a scheduled result would have held.

Built-in plugin modules still load, by design of the flag (debug log: "only managed plugins and built-in plugins run"). Plugins are still listed in `init`, but their hooks do not run. **Verified**, for a user-launched process. Under a scheduled task, the Interactive-logon run in 0.4 also showed 0 hook events.

## 0.3 No tools

The prompt told the model to really attempt Bash, Write, Read, WebSearch, an MCP search, a subagent and a skill. All used `--settings '{"disableAllHooks":true}'`.

| Added flags | Tools in `init` | Tool calls | Outcome |
|---|---|---|---|
| `--tools "" --permission-mode dontAsk` | 13 MCP tools | MCP search | Denied by `dontAsk`, listed in `permission_denials`. No files |
| `--tools "" --permission-mode dontAsk --strict-mcp-config --disable-slash-commands` | none; 0 MCP servers, 0 commands, 0 skills | none | Text only. No files |
| Check of the test: `--tools Write --permission-mode dontAsk --strict-mcp-config` | `Write` | 8 attempted | Write denied by `dontAsk`; the other 7 refused as "No such tool available". No files |

**Mode to pin: `dontAsk`.** It denies anything not explicitly allowed, and needs no prompt. It overrides the user's `defaultMode`, as `init` confirmed. `bypassPermissions` is not needed; the first row shows why it would be unsafe here, since only the mode stopped the MCP call. **Verified.**

Not run: an MCP call under `bypassPermissions`. The Daily Brief uses `--tools '' --permission-mode bypassPermissions` without `--strict-mcp-config`, so its MCP tools are probably callable. This is inferred, and the brief's task was left unchanged.

`--bare` was not used. `--help` says it reads only `ANTHROPIC_API_KEY` or `apiKeyHelper`, never the login, so it does not suit a login-based job. The CLI reference also says it gives Bash, read and edit tools. Whether `--bare` becoming the `-p` default would affect these calls cannot be tested today; a change would surface as a failed call, which the result check must treat as fatal.

## 0.4 Web tools under S4U

All used `--tools "WebSearch,WebFetch" --permission-prompts none --permission-mode dontAsk --strict-mcp-config --disable-slash-commands --settings '{"disableAllHooks":true}' --max-budget-usd 1`.

| Where it ran | `--allowedTools` | Web tools | Others asked for | Status |
|---|---|---|---|---|
| User process | absent | Denied by `dontAsk` | Unavailable | Verified |
| User process | `WebSearch,WebFetch` | Both worked | Unavailable; no files | Verified |
| One-shot task, Interactive logon, windowless | `WebSearch,WebFetch` | Both worked | Refused; no files | Verified |
| One-shot task, **S4U** | `WebSearch,WebFetch` | Not run | Not run | **Not verified** |

Registering the S4U task was refused (see 0.6), so the S4U run did not happen. Elevating needs a UAC prompt on the user's desktop, which was not triggered during this run.

What supports S4U working, without proving it: the existing S4U Daily Brief task last returned 0 on 2026-11-01, so login and model calls work under S4U. It does not use web tools. `WebFetch` fetches from this machine, so whether it works under S4U is the open point.

`--max-budget-usd 1` was accepted under a login session. Its limit was not reached, so enforcement is untested.

Every temporary task was removed, and only the two existing tasks remained afterwards, unaltered.

### To finish this check

Paste into an elevated PowerShell 7 window (one UAC prompt). It runs the S4U test, prints the outcome and deletes the task.

```powershell
$dir = Join-Path $env:TEMP 'upkeep-phase0-s4u'
New-Item -ItemType Directory -Force $dir | Out-Null
Set-Content "$dir\settings.json" '{"disableAllHooks":true}' -Encoding ascii
Set-Content "$dir\prompt.txt" "Actually attempt each step with a real tool call: 1) WebSearch for 'latest stable Python release'; 2) WebFetch https://www.python.org/downloads/; 3) run 'echo hi > canary.txt' with Bash; 4) create canary2.txt with Write. Then in under 40 words say which steps worked." -Encoding ascii
Set-Content "$dir\run.cmd" @'
cd /d "%~dp0"
"%USERPROFILE%\.local\bin\claude.exe" -p --model haiku --tools "WebSearch,WebFetch" --allowedTools "WebSearch,WebFetch" --permission-mode dontAsk --permission-prompts none --strict-mcp-config --disable-slash-commands --settings settings.json --max-budget-usd 1 --output-format stream-json --verbose < prompt.txt > out.jsonl 2> err.txt
'@ -Encoding ascii
$name = 'Upkeep Phase0 S4U Test'
$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument "/c `"$dir\run.cmd`"" -WorkingDirectory $dir
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 8)
try {
    Register-ScheduledTask -TaskName $name -Action $action -Principal $principal -Settings $settings -ErrorAction Stop | Out-Null
    Start-ScheduledTask -TaskName $name -ErrorAction Stop
    do { Start-Sleep 5 } while ((Get-ScheduledTask -TaskName $name).State -ne 'Ready')
    "Task result: $((Get-ScheduledTaskInfo -TaskName $name).LastTaskResult)"
} finally {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) { Unregister-ScheduledTask -TaskName $name -Confirm:$false }
}
Get-Content "$dir\err.txt"
Get-Content "$dir\out.jsonl" | Select-Object -Last 1
Get-ChildItem $dir -Filter 'canary*'
```

Passing means: the task result is 0, the last line has `"is_error":false` and an empty `permission_denials`, the reply says the web steps worked, and no `canary` file is listed. The body of `run.cmd` was run from a normal shell to confirm it works; the elevated script as a whole has not been run.

## 0.5 Slash command through `wt.exe`

- `wt.exe` is on this PC.
- `claude --help` and the CLI reference document `claude "query"` as "Start interactive session with initial prompt".
- Neither says whether `claude "/skill-name"` expands as a slash command. A web search found only third-party pages that do not settle it.
- Watching it needs a window on the user's desktop, which was not opened during this run.

**Design decision: the shortcut uses the prompt `Run the upkeep-review skill`**, which does not depend on slash expansion. **Not verified**: needs the user's click at review, which task 5.4's manual check covers.

## 0.6 S4U registration and elevation

| Method, from Medium integrity | Result |
|---|---|
| `Register-ScheduledTask` with `-LogonType S4U -RunLevel Limited` | `Access is denied.` |
| `schtasks /Create ... /RU DOMAIN\user /NP` | `ERROR: Access is denied.` |
| `Register-ScheduledTask` with `-LogonType Interactive`, same account (control) | Registered, ran, result 0, removed |

The control shows the refusal comes from S4U, not from registering tasks in general. **Verified** that non-elevated registration fails. That elevated registration succeeds is inferred: both existing tasks are S4U, so it was done somehow, but no elevated attempt was made here.

The existing tasks show `LogonType S4U`, `RunLevel Limited`, so the elevation is needed only to register; the task itself runs without it.

An Interactive-logon task would avoid UAC, but it runs only while the user is logged on, and it would miss a run after a reboot with nobody logged in. Keep S4U.

## Found while building the reading path

These came from running Phase 1 code on real data. Measured figures stay in local files.

- **`--max-budget-usd` enforcement: verified.** With a limit below one call's cost, the call ends with exit code 1 and `subtype: error_max_budget_usd`. The result still parses as JSON, so `model_call.py` reports it as its own error. The value must be above zero: a limit rounded to `0.00` is refused as an invalid argument, so limits are passed with 6 decimals.
- **The result JSON carries** `usage`, `modelUsage`, `total_cost_usd`, `duration_ms`, `num_turns` and `permission_denials`, and `modelUsage` names the model that ran, so "session default" can be recorded by name. A tool request in the prompt under the extraction flags gave one turn, no denials and no files.
- **Characters per token:** about 2.3 on one real chunk of 320,000 bytes, close to the 2 observed in the trial. A chunk of 300,000 characters plus a timeline stayed well under the context window.
- **One session id can exist in two project folders**, as an identical copy or with different lengths, so state is keyed by folder and id. A session copied after the start date would be read twice.
- **Subagent files can sit deeper** than `subagents/`, under `subagents/workflows/<id>/`, beside a `journal.jsonl` that is not a transcript. Only `agent-*.jsonl` is read.
- **Subagent files repeat main-conversation records** with the same uuid, so a uuid is read once per session.
- **One API message spans several records that repeat its usage.** Summing per record overstates tokens, so usage is counted once per message id.
- **Desktop-app prompts are marked `promptSource: sdk` with `origin.kind: human`** and are the user's words, so `sdk` alone does not mark a scripted prompt. Scripted prompts have no origin.
- **The classifier was run over every transcript on this PC:** 291 sessions, 1,256 subagent files, no record rejected. Run again after the independent review, on 340 sessions and 1,273 subagent files, it found two types added since: the record type `pr-link` and the attachment type `ultrathink_effort`. Both are now known. Any later addition fails that session only.

## Found while building the daily pass

- **Interpreter:** `Invoke-Upkeep.ps1` reads it from the machine's local settings file, named by `paths.local_settings` in `config.json`, as `{"python_exe": "<full path>"}`. The path differs per machine and this repository is public, so it is not in `config.json`. A missing file or interpreter stops the run.
- **Failure marker:** `<data>\failure-marker.json`; format and clearing rule are in the header of `Invoke-Upkeep.ps1`. The file exists only when there is something to report, so the Phase 7 hook needs only to read it.
- **`git` on the machine `PATH`:** confirmed on this PC, which matters because an S4U task does not get user `PATH` entries. Not run under S4U.
- **A long Bash tool command fails with `ENAMETOOLONG`:** the same fault as in the trials, hit again while building this. Long text went through files instead.
- **A window can stick:** if a pinned window's records change after an interruption, its chunks differ from those recorded and the session fails with `WindowMismatchError`, reported by id. Since windows go by line, a record merely written late no longer does this.

## Found while building the ledgers

- **Most memories have no surviving origin.** Memory files often carry a session stamp in their frontmatter. For the untraced memories that have one, none of the stamped sessions still has a transcript on this PC. Where both exist, the stamp and the traced `Write` nearly always name the same session, so the trace is sound and the gap is in the transcripts. The stamp is compared for the report and is not used as the origin.
- **Some of the untraced memories are named only in shell commands.** A `Bash` or `PowerShell` call may have written them, but such a call is not parsed as a write, since the rule accepts only `Write` and `Edit`.
- **`api-request-blob` records repeat request content, including tool calls, with no timestamp.** They are bookkeeping, not calls, and reading them as calls would double-count. Only conversation records are read.
- **Frontmatter is not always valid YAML.** A description can start with a quote mark and continue as plain text. `backfill.py` reads a narrow line grammar and raises on any other line. Runtime code is standard library only, so `ruamel.yaml` is not used for this read-only step. Nothing writes frontmatter.
- **Scanning all transcripts** took under a minute at below-normal priority, single process, because most lines are rejected by a byte check before parsing.
- **Notes written before schema version 2 cannot name items:** they hold no field for it and no stance, so they add no entries.
- **A real tool-less model call** with the changed prompt, on a synthetic session, returned valid `items`: `against` for a memory the user corrected, `for` for a hook that worked, and nothing for a skill mentioned as unused.

## Found while building the weekly pass

- **The ledgers folder holds two more files than items:** `revision-flags.json` and `unmapped-mentions.json` sit beside the ledgers, by design. Every ledger file has a distinct identity, so there are no duplicates.
- **A window that stuck now recovers by itself.** The limit recorded above is closed: its partial results and the ledger entries drawn from them are discarded, the window is read once more in the same run, and the run lists it under `windows_reset`, which also adds a `window_reset` entry to the failure marker. If it still differs, that session fails and is listed.
- **What was searched comes from the run, not the model.** A research call uses `--output-format stream-json --verbose`, the form Phase 0 tested, and the script reads each tool call and result from it. A link that appears in no tool result rejects the proposal.
- **`apply_memory_changes` has no value in code.** The key must be in the local settings file and literally true or false; a missing key stops the weekly pass. Its value is false until the dry run has been reviewed.
- **Undo and rejection are recorded in `ledgers/review-decisions.json`,** through `ledger.record_decision`, because a rejected new skill has no ledger of its own to hold an entry. A model will reword a claim, so a match is the same item and action, or wording sharing a set share of its words. The review step writes these, and adds the plan's "entries against": see "Found while building the review" for how they are kept out of lost balance.

- **The check on queries fired on the first real research run,** on a query naming the product's own settings folder. That folder is public documentation and not private, so `research.public_path_fragments` lists it for queries only; a description still may not hold it. A refused query is now named in the stop reason, since the first refusal left nothing to read.
- **A real quote can sit beside a claim it does not state.** See "Found by the independent review" for what the gate does about it now.
- **Error signatures can hide the error.** A signature is the first 70 characters of the error text, so a line printed by the shell's start-up file can fill it, and different failures then group by that line. Ranking by commands lost inherits this, and the class hint too: a start-up line saying `No such file` classed every failure behind it as a missing file. **Fixed:** lines matching `counts.startup_noise_line_patterns` are taken out before both. An error with nothing else is labelled `[only start-up output]`. The lines are not counted, so a broken start-up file no longer shows in the ranking unless it is all a command printed.
- **Research under S4U is still not verified** (see 0.4). The dry run ran in a user process.

## Found while building the review

- **Proposal ids collided.** An id was worked out from the kind and target alone, so two different proposals on one hook, or two facts on one memory, shared an id. The second overwrote the first's folder, and the first dry run stored 13 folders for 18 proposals. New ids include the title or the claim. The review tells items apart by id and wording, so a report written before this fix still gives one item per proposal.
- **An undo or rejection is held as an entry against, with the basis `review_decision`.** It is the user's act and not a statement about the item, so it holds no quote and counts for neither side of lost balance. Otherwise one undone `add` would flag the whole memory for revision, because one direct statement against is enough. `review-decisions.json` remains what stops a change coming back.
- **A new item that was never made has no ledger,** so rejecting it adds no entry. The decision record alone holds it, and the result says so. Giving it a ledger would list it among existing items for the weekly model.
- **A flag raised a revision proposal every week,** whatever had been decided. A rejected revision now stays out until an entry behind the flag is newer than the rejection.
- **A rejection reaches further than its wording.** The gate matches the same target and action, so rejecting one of two `change` proposals on a hook also stops the other being proposed again until something new comes from the user. An item already in the review stays open. The skill tells him when he rejects one.
- **Undo works from the change's own before and after,** with a three-way merge, because one commit per folder per pass may hold several changes. Edits in other lines stay. A newer change in the same lines refuses the undo and changes nothing.
- **A skill branch is built with a temporary index,** not a checkout, because the skills repository is the live install: its current branch and files stay as they are. No Git hook of that repository runs for this commit.
- **Windows Terminal quoting and the launch are not verified:** `wt.exe -d "<folder>" "<claude>" "Run the upkeep-review skill"` was not run, because it opens a window. The click test covers it. No browser was available headless, so the page was checked by reading its HTML, not by looking at it.
- **The desktop shortcut points at the installed script,** which does not exist until this branch is merged. Until then, the shortcut fails with a message window.

## Found while building the monthly pass

- **Limits checked against the product's memory documentation:** the memory index loads its first 200 lines or 25KB, whichever comes first, and imports reach four hops. Both are in `config.json`.
- **One of the two known contradictions is in no file.** The instruction to add a co-author line comes from the product when the `attribution` setting is unset. The script therefore writes a line stating whether that setting is set, which a finding can cite like any other text. That the unset setting produces the instruction was seen in sessions and stated in the prompt; it is not read from the product.
- **The call log confirms who received what:** 6 calls with `--tools ""`, the largest of 441,115 bytes, used no tools. The 3 research calls received about 2,200 bytes each, of which only the description is about the skill.
- **Readings overlap, so one matter came back several times.** The first real run gave 70 findings, with one setting against rules raised three times. Findings of one kind citing the same line now become one item, keeping what each said: 53 items from the same replies. Two findings on different lines of one matter stay apart.
- **The check on stated limits rejected 6 stale findings** whose cited line said nothing like "for now". A reader can name a limit stated in other words, so a few real ones may be lost. A rejection is listed in the monthly report, not on the review page.
- **Measured context is a lower limit.** Most memory folders have no transcript left to say where the project lives, so their project instructions cannot be found. The report counts them. Plugin skills, tool server definitions, the product's own prompt and what session start hooks print are not measured.
- **A research reply of `adapt` can mean little.** The real run's two replacement findings both said `adapt`, with a reason saying that nothing found fits and the content has to be written anyway. The pass makes a finding from any `adopt` or `adapt` that names a tool, so these reach the review as they are.
- **Research for a month's skills is taken in name order at first,** so the reference skills came up first.

## Found while building the schedule

- **"First Saturday" needs XML.** `New-ScheduledTaskTrigger` has no monthly form, so tasks are written as XML with `ScheduleByMonthDayOfWeek`. The Task Scheduler read one back as trigger type 5, week mask 1, day mask 64 and month mask 4095, which is the first Saturday of all 12 months. A week of 9 was refused, so the parse does check. No fire time was observed: the scheduler computes those only for a registered task.
- **Definitions can be checked unelevated, without registering.** `RegisterTask` with `TASK_VALIDATE_ONLY` accepted an S4U definition from a Medium-integrity process and registered nothing, as a lookup afterwards confirmed. `-PlanOnly` uses it. **Not verified:** the same call with `TASK_CREATE_OR_UPDATE` from an elevated window, which also reads the logon type back and stops if it is not S4U.
- **A held lock used to be silent.** The run exited 2 with no marker. If the weekly pass met the daily's lock at both 02:00 and 05:30 the week would pass unseen, and a monthly pass would wait a month. It now adds a `failed` entry, which that pass's next clean run clears. It is written without the lock, so a pass ending at that instant could overwrite it.
- **`-CheckResearch` replaces the paste script in 0.4,** and runs the weekly pass's own code and flags. It also requires a page to be fetched, the open point in 0.4, and `git` on the path. Run through `Invoke-Upkeep.ps1` in a user process with real calls: exit 0, 4 searches, 6 fetches, 50 seconds, $0.15. **Under S4U it is still not verified;** that run is the user's, after the merge.
- **The hook in a real session start,** with a synthetic marker and `claude -p --include-hook-events`: the `SessionStart:startup` event gave exit 0 and the expected `systemMessage`. With `disableAllHooks`, 0 hook events. The silent path took 137 ms including interpreter start. The line appearing in the interactive interface was not observed; `systemMessage` is what the message clock hook already shows there.
- **The line holds no free text from the marker.** A marker's summary can hold a pass's error output, so the hook prints only pass, kind and time, each checked by pattern. It is not sent to the model.
- **The review layout matches the install.** The review folder, the skill's `review_session.py` path and the shortcut's target all resolve under the home directory, and only the installed scripts are missing until the merge.
- **A monthly pass that fails retries once,** at 09:30 the same day, which goes beyond the plan's one trigger. It comes after the 03:00 run's 6-hour limit, so `IgnoreNew` cannot drop it. If the weekly limit is the cause it will not have reset by then, since that reset is on Wednesdays, and the warning stays until a hand run or next month.

## Found while finishing the tests

All on synthetic trees, in `tests/test_end_to_end.py`, `tests/test_edge_cases.py` and `tests/dst_scenarios.py`. The end-to-end tests run the real entry script, passes and git, with only `claude` replaced, and kill the real process tree.

- **The class hint was skewed too,** not only the signature: see "Error signatures can hide the error" above.
- **The form of a real limit reply:** see "Found by the independent review".
- **A daylight saving night, by test:** every trigger has a local time with no offset, in the file and as the Task Scheduler reads it back, and no record is lost or repeated when a local hour happens twice or not at all. Python on Windows takes a zone from `TZ` only at process start and applies the C library's United States dates, so that run uses `EST5EDT`. **Not tested:** what the Task Scheduler does on such a night. In Central Europe no upkeep trigger falls in the changed hour, since the change is at 02:00 to 03:00 on a Sunday and only the 01:00 daily runs that day.
- **PC asleep or off, by test:** the definitions ask for a wake and a late start, and the next run catches up missed nights and a missed week. **Not tested:** Windows acting on the definitions. That needs real nights.
- **A record stamped in the millisecond of the last one read is no longer missed.** It was a limit of windows by time. Windows now go by line: see "Found by the independent review".
- **A live edit can land between the check of a file and its write.** The check and the write are a few lines apart with no lock, because live sessions take none. The test covers an edit before the check and one after the stage, not this gap.
- **A push guard is a Git hook,** so `git push --no-verify` passes it. The tests prove refusal of a plain push, and that any remote found stops a commit.

## Found by the independent review

Each fix has a test in `tests/test_defect_fixes.py`, `test_scheduling.py` or `test_invoke_upkeep.py` that failed before it.

- **The quote gate passed unrelated claims.** An `accepted` change with the quote `k` and the statement `a` passed for "Always commit with --no-verify", since both were found inside longer words. Now quotes and statements match on word edges only. A `said` quote needs 3 words, a reaction 2 and its statement 4, and the quote or statement must share 2 words of 3 or more letters with the claim, leaving out the common words in `weekly.tied_ignored_words`. All of these are in `config.json`. **A bare "yes" no longer backs a claim.** That loses some real agreement on purpose: the words after a one-word reply could be anything, and a wrong memory loads into every session.
- **A script cannot judge meaning,** so what passes the script goes to one tool-less call per pass, `prompts/weekly_verify.md`, which sees only each claim and its quotes. It treats them as data and gives `supports`, `does_not_support` or `one_moment_order`. Only `supports` goes on. A reply not answering each claim once stops the pass. File text is worked out after this call, so a rejected claim cannot reach the changes after it. This call is itself a model reading quotes: it lowers the risk, and does not prove a claim right.
- **On real data:** one weekly pass with application off, replaying the memory replies of the dry run before these fixes, so that the same 7 changes met the new gate. All 7 passed the script checks. The verification call, the only model call, cost $0.06 and rejected 1 of the 7: the quote shared words with the claim but held nothing of what it said. 6 went on. The earlier run's folder stays under `reports/` with a name that is not a week. That the new prompt gives good changes from scratch was not run.
- **A one-moment order** is refused by script if a note marked those words as one, and otherwise by the model's verdict.
- **Deleting a whole file is always a proposal,** after the same checks. Removing a statement still follows the limit per pass.
- **Applied changes vanished from the review.** After a failed run, a retry found its notes used up and overwrote the report, and a build dropped the week's undecided items. A crash after a commit lost the record altogether, and every retry then refused the folder. Now `reports/YYYY-Www/applied.json` is written before any memory file, and every report and review of the week takes applied changes from it. On the next run, and before any snapshot, a `prepared` entry is settled: if the folder holds this week's commit it counts as committed and its ledger entries are added; if not, what was written is put back from `HEAD`. **Not run:** a real process killed at these points. The tests raise at each point instead, and `tests/test_end_to_end.py` kills a real run only at other points.
- **A review built again in its week now keeps its undecided items,** except a change that only would have applied in a trial run, which the next pass works out again.
- **One unknown record type stopped every session, every night.** It now fails that session, by id, with a non-zero exit, and the rest go on. This changes plan criterion 3 only in scope: an unknown `origin.kind` still ends the run non-zero with that session unprocessed, but no longer stops the others. A later record of an unknown type does not touch windows already read.
- **Queued messages could be lost.** They are written after records stamped later than themselves, and a read in that gap dropped them. A window now goes by line: `lines_read` in the state file per transcript file, `lines_after` and `lines_through` in a pinned window and in `window.json`. A uuid read before is not read again, so a subagent file written later cannot bring old copies back. A transcript shorter than what was read fails that session. **Carrying over:** an old state file loads as is, and each entry is converted when next reached, from the run of lines at the start whose stamps are at or before `processed_through`. Everything after that run was certainly written after that read. A late record inside the run cannot be told apart, so it stays lost as it was. An old `window.json` is still read by its timestamps.
- **Undo restored redacted text.** A change's before and after are redacted in the report. Undo now reads their real lines from the commit that made the change, and refuses if a redacted line is not found there.
- **Memory writes are atomic,** through a temporary beside the file and `os.replace`. A temporary left by a crash is removed by the next commit or snapshot, is excluded from staging, and does not count as a file. **Not tested:** a power cut. `fsync` is called, and what the disk does after that is not checked.
- **An empty or unreadable lock** now adds a marker. Older than `status.unreadable_lock_grace_seconds` it counts as stale and the run goes on. Younger, it may be a run just starting, so this run exits 2.
- **Tasks that stop firing now warn at session start,** past `status.warn_after_hours_without_run`, once the local settings file exists and a scheduled pass has logged a run. A deliberate pause warns too, and so does the time between the first hand runs and registering the tasks. A task that fires and crashes before logging counts as not firing.
- **An option label the user picked counts as `accepted`, never `said`.** The model wrote those words. Words typed beside a label, and a note typed on an option, stay the user's own.
- **Fetched links are checked.** A private host always stops the pass. The rest of a link is checked only if the model wrote it: one that an earlier result returned came from the web. **Not checked:** the `prompt` of a `WebFetch` call, which goes to a model and not to a site.
- **The form of a real limit reply.** The Daily Brief's log holds 8 failed attempts with a usage limit reply on 4 nights: a short line of text, each with exit 1. None exited 0, so a success with those words has not been seen, and the log does not say whether that output was JSON or plain text. All three forms are now named as `LimitReachedError`, which stops the pass, by the opening words of the reply. A limit reply worded differently and exiting 0 would still fail schema checks, one session at a time.

## Found by the second independent review

Each fix has a test in `tests/test_second_review_weekly.py`, `test_second_review_monthly.py` or `test_second_review_page.py` that failed before it.

- **Counts used up the notes of their window.** A counts file and a notes window had one key, so a live pass marked every window used, including one set aside or waiting for next week, whose notes then never reached the memory or proposal steps. State version 2 keeps `consumed_windows` and `consumed_counts` apart. **Carrying over:** a version 1 state file converts when read, each key counting as used in both maps, because which of the two a key stood for cannot be told. Nothing used up is read again. A window a version 1 pass wrongly used up stays used up.
- **One bad item stopped everything.** A name in another case, a case-only rename, a leftover temporary and an unreadable header each stopped the daily pass, and so the weekly stages. Now names resolve whatever their case, against the identity on file. A case-only rename seen in the inventory moves the ledger. Temporaries are removed at the start of each pass and by each commit, and a failed atomic write removes its own. What cannot be read goes to `ledgers/item-problems.json`, reaches the review, and fails the pass with a non-zero exit while everything else goes on. A window reset that meets an unreadable ledger fails that session only.
- **A list at the first column of a header** is now read like an indented one. Any other unknown line is still refused: for that file only in a scheduled pass, and for the whole run in a manual backfill. The reader stays a line grammar with no dependency. Whether to replace it is an open question.
- **Secrets in counts.** Keys are redacted too, with counts under keys that become one added up. `command_words` takes out `VAR=` and `$env:VAR=` and splits outside quotes, so a value holding `;` leaves no fragment. An error is redacted before it is cut and masked, since a token with masked digits no longer matches.
- **Secret patterns widened:** names joined by `_`, such as `DB_PASSWORD`, and `dbPassword`, since a word edge fails after `_`; `sk-proj-` keys; a whole private key with its body, to the end of the text if it has no end line; `"password": "x"` and quoted values with spaces. A bare `token` needs a value holding a letter, so `max_tokens: 123456789` is left alone, and `secrets` is not `secret`, so `secrets: SomeType` is too. **Price of this:** a field named `password` with a long type annotation is now redacted when its code appears in a transcript. In what the model reads, redaction comes before the cut, so a cut can no longer split a token.
- **Same-chunk order.** Every note of a chunk has one date, so a direct "against" after a "for" was lost. Order is now date, then the note's place in its chunk. If one note says both, neither is later, so the "against" stands and flags.
- **A note giving both stances** on one item now keeps both. The first keeps the id it always had, so entries on file are found again, and only an opposite second stance has its direction in the id. One place in the notes gives one entry per direction, so a rename in case adds no duplicate.
- **A rename to another name is flagged, not carried.** It cannot be told from a removal and an addition, and a wrong carry would give an unrelated item a false history. See the README.
- **A flagged item no longer installed** raises no `item_revision`. If its file or kind could not be read, it cannot be called gone, so the flag stands.
- **Inferred flags count sessions.** The plan's wording is "entries": see the README.
- **Monthly, all citations failed.** Findings made by script, and anything raised earlier, hid this, so a month with nothing read was marked done. Only a model's finding whose citations held counts now. A failed run's report also lists what it refused.
- **Monthly, refused findings** now appear as counts in the summary, with the list in `report.json`.
- **Monthly, unredacted text.** Each file is redacted and its tags neutralised when read, keeping its line numbers, so what a call sees is what a citation is checked against. `pass_support` also redacts what any pass sends, its cached reply and its rejected reply, and a run acts on the reply as stored so that a retry does the same. A reply is redacted as parsed data, because redacting JSON text can end inside an escape and break it. The weekly gate refuses a claim holding the redaction mark. **Carrying over:** caches written before this hold what they held.
- **Text breaking out of its frame.** A look-alike of an entry header is neutralised anywhere in a text, and every tag a prompt frames data with has its `<` replaced, from `render.FRAME_TAGS`. A memory holding such a tag then no longer matches its own `old_text`, so that one change is rejected, visibly.
- **Tracebacks** now sign by their last line, so two failures of one script stay apart.
- **The overdue banner** counts only reports whose review holds something open, since an action can only be taken on an item.
- **Context figures** leave out projects with no known folder, including a folder since removed, and count them. If none is left, the summary says so.
- **A retry after a crash** between feed, state and report picks the same skills, so it reuses their research and writes the same findings. A skill checked this month comes first in the rotation.
- **Duplicates left out** by a raised bar or the group limit are listed in the report and the summary.
- **Page and session:** a bad address is inert text, a removed `--flag` line shows, the ledger shown follows a reject or undo, and the page shows its version. **Limit:** the script cannot see the browser. `read-again` is run by the session after Basil says he reloaded, and a new session starts on the current version, whichever page he has open.
- **A chosen option** is `accepted`, and the quote may come from its label. The prompt now says so, as the gate always did.

**Existing tests changed, and why:** `test_ledger.py`, whose entries all shared one session, which is now one piece of evidence, and whose rule needs the new settings; `test_counts.py` and `test_monthly.py` for a new argument.

**Not tested:** a real crash leaving a temporary, since the tests write one by hand; a case-only rename on a case-sensitive file system, though the lookup is written for one; a model given the new prompt wording.

## Found by a real run of the job

One pass over real sessions was read by a person, who judged most of its ledger entries wrong or unclear. What it showed, and what changed:

- **Names did not resolve.** A hook appeared in sessions only by its status message, and the prompt asked for both its script name and the name as shown, so its mentions could not reach its ledger. A tool-less reader cannot see what exists, so each chunk now gets a list of known names by script. `statusMessage` in the settings is where a hook's display name can be established, so no alias map was needed. Exact name, display name and any case resolve. The rest go to `unmapped-mentions.json`, including mentions with no bearing, which used to go unrecorded.
- **Stances were not checked.** The gate checked only that a name exists. There is now one tool-less call per daily pass, on Sonnet, given each for or against with the item's real contents. Fixtures test that refused stances make no entry and are listed with their reason. **Refusal has not been seen on real data:** in the rerun below, the stricter reading prompt left one stance to judge, and it held.
- **The list could not be prefix-cached.** `model_call.py` sends the prompt and the input as one text block, and caching works at block boundaries. Measured: `cache_read_input_tokens` stayed at 2204 on both chunks. So the list is paid in full per chunk. It is placed first, in case the call is ever split.
- **One statement split into claims.** The stricter half could be saved with its qualifier rejected. Replaying that run's claims through the new tie found the pair under one user entry. The fresh dry run produced no such pair, so the proposal itself has only been exercised on fixtures.

Same two windows read before and after, by pinning them again with `sessions.pin_window` after `daily._discard_window`, so that the model read the same transcript:

| | Before | After |
|---|---|---|
| Reading, two chunks | $1.9964 | $2.0387 |
| Tokens written to cache | 203,068 | 211,559 |
| Output tokens | 18,562 | 17,270 |
| Stance check | none | $0.0418 (one stance, 9,749 characters) |
| Daily pass | $1.9964 | $2.0806 |
| Weekly dry run | $1.5917 | $1.5065 |

The list holds 10,051 characters on 82 lines. The extra 8,491 tokens also include the longer prompt, and reading's cost moved less than they would suggest because output fell. The check's cost grows with the stances and items it is given, which a thin pass does not show.

## Found by a judge reading the ledger stances

An independent judge read 21 mentions from 2 sessions after the fixes above. False "against" had stopped, but the valve had become one-way: 1 entry, some `no_bearing` that should have been entries, no `for`, and one hook behaviour with `against` in one session and `no_bearing` in another. What changed:

- **The check now judges every stance,** `no_bearing` included, against the item's full contents, since the reader sees about 100 characters of each. It may raise, lower, refuse or reverse. A failed call keeps what earlier calls settled. A verdict that does not fit its stance at first failed its call too; since one such verdict among many lost a whole reply on a real run, it is now dropped alone, its stance waits, and the run ends failed with it listed. Every verdict goes to `ledgers/stance-verdicts.json`, and the counts and cost reach the review page.
- **Direct depended on the note, not the item.** `_attribution` read the note's endorsement, so a user's sentence on any subject gave a stance on a named item the weight of a direct statement. One such `against` flagged at once, and one such `for` held inferred flags back for 28 days. The check now says whether the quote is about this item, and otherwise the entry is inferred.
- **A rule broken at a cost was lost,** either as `no_bearing` or as a wrong `against`. It is now an entry with direction `rule_broken`, read by neither side of the balance, and listed on the review page.
- **The wording of `for` and `against`** changed in both prompts. `against` now covers a hook's or tool's own behaviour costing repeated work, since a hook is not followed. The self-exclusion now covers only this job itself or evidence that is only this job's own report.
- **Like cases alike:** an item's stances share one call, and each item comes with its latest rulings from earlier passes.

Measured on a copy of the data folder, with the reading and the check on real sessions. Ten finished sessions were picked by a script rule fixed before any result: 3 to 28 days old, not about this job, one per project folder, highest count of visible item uses first, taken in turn from three size bands. Two earlier sessions were added for comparison. Nothing was written to the real ledgers.

| | Result |
|---|---|
| Reading, 10 sessions, 11,000 to 620,000 characters, 1 to 3 chunks, 1 to 44 notes | $0.11 to $2.82 each, $9.23 in all |
| Reading, the 2 earlier sessions | $2.08 |
| Notes, of which naming no item | 170, 116 |
| Mentions by the reader: no bearing, against, for | 57, 9, 5, of which 1 not on the list of names |
| Check, Sonnet: 70 stances, 186,874 characters, one call | $0.36: 64 kept, 3 raised, 3 lowered, 4 rules broken |
| Check, Opus: same input | $0.83: 66 kept, 3 raised, 1 lowered, 1 rule broken |
| After the Opus check: no bearing, against, for | 54, 11, 5 |
| Entries added, flags, Opus | 16 and 1 rule broken, 1 flag on a hook |
| The models agree on the final stance | 66 of 70 |

**Which model.** Sonnet is now set in `item_check.model`. Opus was set when the table above was measured, as a judgement on cost and consequence: both models got 32 of 32 on invented cases. The independent reader then judged the 4 disagreements, and found Sonnet right on 3 of them, as the next section says.

**Consistency.** The real prompt on invented cases, each in its own call, twice on each model: one hook behaviour told with 2 or 9 repeats, starting from `against` or `no_bearing`, always ended `against`, and a single block fixed at once always ended `no_bearing`. On the real sessions, one hook behaviour appeared in 7 sessions. The reader gave it `no_bearing` in 3 of them. After the check, on both models, it was `against` in all 7, including the two earlier sessions.

**Not run.** `daily.run_daily` on real sessions, since it commits memory folders: the check and the ledger step were called directly on the copy. Earlier rulings on real data, since this was one pass; fixtures cover them. The review page from a real weekly pass; the banners were computed from the copy, and rendered by fixtures. Backdated reading has one flaw that a live pass does not: some sessions predate a memory they are read against. Sonnet recorded a broken rule for such a memory, and Opus said why not.

## The independent reader's results, and the last fixes

An independent reader judged the Opus verdicts above against the sessions. The measured results, for that sample of 41 stances:

| Final stance | Result | In plain words |
|---|---|---|
| `against` | 10 of 11 correct | When the check says an item did harm, it is nearly always right |
| `for` | 2 of 5 correct | When it says an item helped, it is more often wrong than right, in a small sample |
| `no_bearing` | 0 of 25 false | None of these should have been `for` or `against` |

These figures are from before the changes below, and have not been measured again on real sessions. What follows came out of them.

**The entry that did not fit its note.** The table above says 16 entries for and against, but the ledgers of the copy hold 17, one with a source note that says something else. It is the throwaway revalidation route and not production code. That script copied the data folder with its ledgers, deleted the notes, and read the sessions again, with no step for the ledgers. The one entry the real ledgers held at the time stayed in the copy, and the second reading of its window put other notes at that place. A session counts once in the balance, and this session had a new entry against the same item, so the flag in the table does not change. The real ledgers were checked the same way, and no entry there had this fault.

The production route was already safe: `daily._discard_window` takes out a window's entries before its notes, and if that fails the notes stay. Tests now hold that, with a second reading in another order, and these were added for the other routes. An entry's id takes in the text of its note, so it cannot come to mean another note's text. Each ledger step lists any entry whose note no longer holds its text, and any verdict given on another note's text makes no entry and is listed. The run then ends failed. Nothing repairs it silently.

**Wording of `for`, route (a).** Both prompts now say that a reply about something else does not count as accepting the result, that the item must be in scope for the task at hand, and that the assistant's default must really have differed.

**One-off faults.** The test "more than once" on a hook's or tool's own behaviour was applied per session, so a defect firing once in each session never showed. Such a fault is now an entry with direction `malfunction`, read by neither side of the balance, with each item's count across sessions on the review page.

**The real prompts on invented cases, with Sonnet.** Each case in its own call, 54 calls in all, the new cases twice and the 16 of the earlier round once, on prompts in their final wording.

| Cases | As expected |
|---|---|
| Check, route (a) for `for`: reply elsewhere or none, out of scope, default no different, all three holding | 18 of 20 |
| Check, a fault of its own: once, from either starting stance, on a hook and a tool server, and a memory that must not get one | 7 of 8 |
| Check, the earlier round again | 15 of 16 |
| Reader, whole invented session parts: route (a) and a one-off fault | 10 of 10 |
| All | 50 of 54 |

The four misses, none of them a wrong `for` or a wrong `against`:

- A hook doing as it should, and the user praising it, was expected to be `for` and came back `no_bearing`, both times. A hook's `for` may be harder to reach than the rule intends.
- A hook that blocked rightly, once, was marked as a fault, in 1 of 2 runs of that case here and 1 of 4 over two rounds. It moves no balance, but it would add to the count on the page.
- A memory followed, with harm from a broken fridge, came back `no_bearing` once. That case was badly chosen, as the fridge did the harm. It did get no fault, which is what it was there to show.

An earlier round of the same cases had 2 replies rejected, of 44 on the check, both on the case of the hook being praised: Sonnet wrote its JSON, then wrote a correction after it. The parser rejects that, the whole call fails, its stances wait for the next pass, and the pass ends failed. The prompt now says to settle every verdict before replying, and the round above had none rejected of 44. That sample does not show the fault is gone. A real pass runs the reader on Opus, so the 10 of 10 says nothing about Opus. All rounds together cost $2.64, including a first run that such a reply stopped before its results were kept.

**The real data folder.** It was committed first, with nothing outstanding. `stance_check.py rejudge-old` then removed 1 verdict file and 1 ledger entry, the only ones there, and the old file of refused stances. On a scratch copy of the data folder, with memory folders and the 2 waiting sessions copied, `daily.run_daily` was run with a call that raises at once, so no model was called. It reached the reading of a session, on Opus. With no sessions to read it reached the stance check, on Sonnet, with 21 stances waiting and one call of 103,392 characters. The ledger step then read everything and listed no problem.

**Not run.** A pass on real sessions with these prompts, and a real model reply through `daily.run_daily`. How the wording changes `for` on real sessions, so the 2 of 5 stands until it is measured again. A fault of its own on a real session, and the page with real ones: fixtures cover them. How often Sonnet writes a correction after its reply on real input, where one call holds all waiting stances.

## Folders created by these tests

Under the system temp folder, `upkeep-phase0-<name>`, and for each a matching project folder under `~/.claude/projects/`, for these names: `t02a-control`, `t02b-disabled`, `t02c-control`, `t02d-disabled`, `t03a-mcp`, `t03b-strict`, `t03c-control-tools`, `t04a-noallow`, `t04b-allow`, `t04d-task`, `s4u`. All are safe to delete.
