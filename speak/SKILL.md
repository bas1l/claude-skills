---
name: speak
description: Read the last Claude response aloud using edge-tts (Jenny neural voice). Optional speed shorthand.
argument-hint: "[start [speed]|stop|speed] — e.g. /speak, /speak f, /speak start, /speak start ff, /speak stop"
---

# Speak — text-to-speech for last response

Read aloud the **last assistant response** in this conversation using edge-tts with the Jenny neural voice.

## Argument parsing: $ARGUMENTS

First, check whether the arguments begin with `start` or `stop`:

### `/speak start [speed]`

Enable auto-speak mode: every subsequent assistant response will be spoken aloud automatically via the Stop hook — no manual `/speak` needed.

1. Parse the optional speed token after `start` (e.g. `/speak start ff`). If absent, default to `+0%`.
2. Map the speed token to an edge-tts rate string using the speed table below.
3. Write the rate string to the flag file using PowerShell:
   ```
   Set-Content -Path "C:\Users\basil\.claude\hooks\speak-auto.flag" -Value "<rate>" -NoNewline
   ```
4. Respond with only: `Auto-speak ON (rate: <rate>).` — nothing else.

### `/speak stop`

Disable auto-speak mode.

1. Delete the file `C:\Users\basil\.claude\hooks\speak-auto.flag` using PowerShell:
   ```
   Remove-Item "C:\Users\basil\.claude\hooks\speak-auto.flag" -ErrorAction SilentlyContinue
   ```
2. Respond with only: `Auto-speak OFF.` — nothing else.

### `/speak [speed]` (one-shot, no `start`/`stop`)

Read the last response aloud once — same behavior as before.

## Speed table

Map the speed argument to an edge-tts rate string:
- (empty / `normal` / `n`) → `+0%`
- `s` or `slow` → `-20%`
- `ss` → `-40%`
- `f` or `fast` → `+25%`
- `ff` → `+50%`
- `fff` → `+100%`
- A raw percentage like `+80%` or `-20%` → use as-is

## One-shot procedure

1. Retrieve your most recent assistant response text from this conversation (the message just before the user typed `/speak`). If there are multiple text blocks, join them.

2. Strip markdown for natural speech:
   - Remove code blocks (``` ... ```) — replace with nothing
   - Remove inline code backticks
   - Remove table rows (lines with pipes)
   - Remove heading markers (#)
   - Remove bold/italic markers (** and *)
   - Remove link syntax [text](url) → keep just text
   - Remove HTML tags
   - Remove horizontal rules (---)
   - Clean up list bullets and numbering
   - Collapse multiple newlines into ". " (pause)
   - Collapse remaining newlines into spaces

3. Truncate to 2000 characters if longer.

4. Use the **Write** tool to save the sanitized text to a temp file at `C:\Users\basil\AppData\Local\Temp\claude-speak.txt`.

5. Run this PowerShell command with the appropriate rate:
   ```
   & "D:\Programming\anaconda3\envs\social-touch\python.exe" "C:\Users\basil\.claude\hooks\speak.py" "C:\Users\basil\AppData\Local\Temp\claude-speak.txt" "en-US-JennyNeural" "<rate>"
   ```
   where `<rate>` is the edge-tts rate string (e.g., `+25%`).

6. Delete the temp file after playback.

7. Respond with only: "Done." — nothing else.
