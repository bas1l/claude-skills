# session-colocate

SessionStart hook (all sources: startup, resume, clear, compact, fork) that
co-locates a session's temp data with its transcript, so everything a
conversation produced lives in one folder under `~\.claude\projects`.

## Why

Claude Code splits a session's data across two trees:

- `~\.claude\projects\<project>\<session-id>.jsonl` (transcript) and its sibling
  folder `<session-id>\` (`subagents\`, `tool-results\`);
- `%TEMP%\claude\<project>\<session-id>\` (`scratchpad\`, `tasks\`, ...), which
  OS temp cleaners may delete.

## Design: move + junction

- Temp session dir: parent of the hook input `scratchpad_dir`,
  i.e. `%TEMP%\claude\<project>\<session-id>\`.
- Target: `transcript_path` minus `.jsonl`,
  i.e. `~\.claude\projects\<project>\<session-id>\`.

Paths come only from the hook input (`scratchpad_dir`, `transcript_path`,
`session_id`), never from parsing the project-name string.

The temp session dir's contents are moved into the target and the temp session
dir is replaced by a Windows directory junction to the target. Claude Code keeps
using its usual temp path; anything it creates there later (scratchpad, tasks,
...) physically lands in `projects`. A junction (not a symlink) is used because
it needs no admin rights or Developer Mode.

## Behaviour

| State of temp session dir | Action |
|---|---|
| junction to target | no-op (resume / rerun) |
| junction/symlink elsewhere | fail |
| missing | create target, create junction |
| real dir | preflight collisions -> rename aside to `<sid>.colocate-staging` -> junction -> move entries (dirs merged) -> rmdir staging |
| `scratchpad_dir` absent from input | skip (documented: session has no scratchpad) |

Order for a real dir is chosen so a failure never leaves the session without its
data at the expected path: the atomic rename happens only after the preflight,
and the junction is created immediately after it.

## Fail-loud cases

Errors go to stderr with exit 2 (SessionStart cannot block; Claude Code shows
the notice to the user and the session continues). Nothing is ever overwritten.

- a file, link or file/dir type mismatch already present in the target
  (detected in preflight; nothing is moved);
- the temp session dir is a junction/symlink to somewhere other than the target;
- the target exists but is not a real directory;
- an open handle blocks the initial rename (nothing changes);
- inconsistent hook input (`scratchpad_dir` not ending in `scratchpad`, its
  parent or the transcript not named after `session_id`);
- a leftover `<sid>.colocate-staging` from an earlier mid-move failure (resolve
  by hand);
- a mid-move failure reports what was moved and what is still in staging.

Every run appends one line to `session_colocate.log` next to the script
(git-ignored). `SESSION_COLOCATE_LOG` overrides the log path (tests only).

## Installation

`setup/install.ps1` registers it in `~/.claude/settings.json` ->
`hooks.SessionStart`, using the `command` + `args` form:

```json
{ "type": "command", "command": "<python.exe>",
  "args": ["<~/.claude>/skills/hooks/session-colocate/session_colocate.py"],
  "timeout": 30 }
```

The quoted-string form (`"\"python.exe\" \"script.py\""`) failed under
PowerShell in a `claude -p` probe; `args` passes the script path without any
shell quoting. The installer also sets `cleanupPeriodDays: 36500` (see below).
Stdlib only; Python >= 3.12.

## Tests

```powershell
python $HOME\.claude\skills\hooks\session-colocate\tests\run_tests.py
```

24 end-to-end cases (fresh, move, merge, resume/compact rerun, file and type
collisions, junction elsewhere, open handle, missing `scratchpad_dir`, bad
input). Fixtures are built under `%TEMP%\session-colocate-tests-*`, deleted when
all pass and kept otherwise.

## Deletion of the temp tree

- **Windows Storage Sense** (tested 2026-10-02): it deleted a junction in
  `%TEMP%` but did NOT follow it; the files behind it, in `projects`, survived.
- Explorer, `rmdir /s` and Node's `fs.rm` remove a junction without descending
  into it. Tools that do not distinguish junctions could delete the target's
  contents.
- **Claude Code's retention sweep**: the docs do not state whether it follows
  junctions. `cleanupPeriodDays` is set to 36500 so the sweep effectively never
  runs.

## Caveats

- Windows only (`_winapi.CreateJunction`, `os.path.isjunction`, Python >= 3.12).
- `claude -p` sessions may get no `scratchpad_dir` in the hook input; the hook
  then logs a skip and does nothing.
- If the temp junction is deleted mid-session (e.g. by Storage Sense), the live
  session may recreate a fresh plain temp dir and write there until the next
  SessionStart (resume, clear, compact), which then moves it into the target.
- Old sessions (created before the hook) are migrated the first time they are
  resumed or compacted. A compaction in a live session migrates that session in
  place; if any process holds a handle inside the temp dir the rename fails
  cleanly and the session keeps its original temp dir.
