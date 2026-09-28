---
name: voice-latch
description: Start, stop, restart or check the voice-latch push-to-talk AutoHotkey script (F:\Game-Optimization\voice-latch.ahk) that turns a G502 side button / F13 into a latch for Claude Code voice dictation. USE THIS SKILL whenever the user asks in plain language to start, stop, restart or check voice input, using any phrasing such as: "start voice chat", "start vocal", "start voice", "start voice mode", "start dictation", "start talking", "voice on", "vocal on", "mic on", "let me talk", "enable voice", "launch the voice latch", "voice latch", "push to talk", "stop voice chat", "stop vocal", "voice off", "mic off", "disable voice", "kill the voice script", "restart voice", "reload the voice script", "is voice running", "voice status". The process is launched detached so it keeps running after the conversation, terminal and Claude Code are closed.
argument-hint: "[start|stop|restart|status] — default: start"
---

# voice-latch — persistent AHK voice latch

Controls `F:\Game-Optimization\voice-latch.ahk` via the helper at
`C:\Users\basil\.claude\skills\voice-latch\scripts\voice-latch.ps1`.

The helper creates the process through WMI (`Win32_Process.Create`), so its parent
is `WmiPrvSE.exe` rather than the Claude Code shell. **It survives the end of this
conversation, the terminal being closed, and Claude Code exiting.** It stops only on
explicit `stop`, logoff, or reboot.

## Argument parsing: $ARGUMENTS

Map `$ARGUMENTS` to one action. When the skill is triggered by plain language rather than
the slash command, `$ARGUMENTS` may be empty or may be the user's whole sentence - read the
intent out of it. Empty, or anything not listed below, means `start`.

| Argument / phrasing | Action    |
|---------------------|-----------|
| *(empty)*, `start`, `on`, or any "start voice / start vocal / voice on / mic on / enable voice / let me talk / push to talk" phrasing | `start`   |
| `stop`, `off`, `kill`, or any "stop voice / stop vocal / voice off / mic off / disable voice" phrasing | `stop`    |
| `restart`, `reload`, or "restart voice / reload the voice script" | `restart` |
| `status`, `check`, or "is voice running / voice status" | `status`  |

## Execution

Run exactly one command with the PowerShell tool, substituting the resolved action:

```
& "C:\Users\basil\.claude\skills\voice-latch\scripts\voice-latch.ps1" -Action <action>
```

Do **not** launch `AutoHotkey64.exe` directly from Bash or with a bare
`Start-Process` — a process started that way is a child of the session shell and can
be killed when the conversation ends, which defeats the purpose of this skill.

## Response

Reply with a single line, nothing else:

- `STARTED pid=<n>`        → `Voice latch running (pid <n>) — persists after this session.`
- `ALREADY RUNNING pid=<n>`→ `Voice latch already running (pid <n>).`
- `RESTARTED pid=<n>`      → `Voice latch restarted (pid <n>).`
- `RUNNING pid=<n>`        → `Voice latch is running (pid <n>).`
- `STOPPED …`              → `Voice latch stopped.`

If the helper throws (AutoHotkey v2 missing, or the `.ahk` file moved), report the
error message verbatim and do not retry with a different launch method.

## What the script does (for context when the user asks)

- `F13` → press once to latch <kbd>Space</kbd> down (recording starts), press again to
  release and send <kbd>Enter</kbd> (stop **and** submit).
- `Shift+F13` on the second press → stop **without** submitting, leaving the text in the
  prompt for editing.
- While latched, <kbd>Enter</kbd> behaves like `F13` (stop and submit); when not latched,
  <kbd>Enter</kbd> is completely normal.
- The trigger is `F13`, typically bound to a G502 side button in G HUB.
