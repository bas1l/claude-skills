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
- **The classifier was run over every transcript on this PC:** 291 sessions, 1,256 subagent files, no record rejected. So the known-type lists match today's format, and any addition stops the run.

## Found while building the daily pass

- **Interpreter:** `Invoke-Upkeep.ps1` reads it from the machine's local settings file, named by `paths.local_settings` in `config.json`, as `{"python_exe": "<full path>"}`. The path differs per machine and this repository is public, so it is not in `config.json`. A missing file or interpreter stops the run.
- **Failure marker:** `<data>\failure-marker.json`; format and clearing rule are in the header of `Invoke-Upkeep.ps1`. The file exists only when there is something to report, so the Phase 7 hook needs only to read it.
- **`git` on the machine `PATH`:** confirmed on this PC, which matters because an S4U task does not get user `PATH` entries. Not run under S4U.
- **A long Bash tool command fails with `ENAMETOOLONG`:** the same fault as in the trials, hit again while building this. Long text went through files instead.
- **A window can stick:** if records stamped inside a pinned window appear after an interruption, its chunks differ from those recorded and the session fails on every run with `WindowMismatchError`, reported by id. Clearing it means deleting that window's folder by hand. Not seen in real data.

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
- **Undo and rejection are recorded in `ledgers/review-decisions.json`,** through `ledger.record_decision`, because a rejected new skill has no ledger of its own to hold an entry. A model will reword a claim, so a match is the same item and action, or wording sharing a set share of its words. The review step writes these; the plan's "entries against" are left for it to add, since an undone change is not by itself evidence against the memory it touched.

- **The check on queries fired on the first real research run,** on a query naming the product's own settings folder. That folder is public documentation and not private, so `research.public_path_fragments` lists it for queries only; a description still may not hold it. A refused query is now named in the stop reason, since the first refusal left nothing to read.
- **A real quote can sit beside a claim it does not state.** The gate now refuses a `said` quote sharing no word of 4 or more letters with its claim. This catches a plain mismatch only: it cannot tell that the words mean the same, so whether a quote supports a claim stays a question for review.
- **Error signatures can hide the error.** A signature is the first 70 characters of the error text, so a line printed by the shell's start-up file can fill it, and different failures then group by that line. Ranking by commands lost inherits this. `counts.signature_chars` or a filter of such lines is a change for later.
- **Research under S4U is still not verified** (see 0.4). The dry run ran in a user process.

## Folders created by these tests

Under the system temp folder, `upkeep-phase0-<name>`, and for each a matching project folder under `~/.claude/projects/`, for these names: `t02a-control`, `t02b-disabled`, `t02c-control`, `t02d-disabled`, `t03a-mcp`, `t03b-strict`, `t03c-control-tools`, `t04a-noallow`, `t04b-allow`, `t04d-task`, `s4u`. All are safe to delete.
