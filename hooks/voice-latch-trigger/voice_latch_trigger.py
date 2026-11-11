"""UserPromptSubmit hook: run the voice-latch helper on an exact "voice on" / "voice off" prompt.

The prompt is matched case-insensitively after trimming, with optional trailing
punctuation. Anything else is ignored (exit 0, no output). On a match the helper
runs here, so the action does not depend on the model choosing to invoke the skill,
and its result is passed back to the model as context.
"""
import json
import os
import re
import subprocess
import sys

PATTERN = re.compile(r"^\s*voice\s+(on|off)\s*[.!?,;:]*\s*$", re.IGNORECASE)
HELPER = os.path.join(os.path.expanduser("~"), ".claude", "skills", "voice-latch", "scripts", "voice-latch.ps1")


def main() -> int:
    try:
        prompt = json.load(sys.stdin).get("prompt", "")
    except (ValueError, OSError):
        return 0
    m = PATTERN.match(prompt or "")
    if not m:
        return 0
    action = "start" if m.group(1).lower() == "on" else "stop"
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", HELPER, "-Action", action],
            capture_output=True, text=True, timeout=20,
        )
        out = (r.stdout.strip() or r.stderr.strip() or f"exit {r.returncode}")
        ok = r.returncode == 0
    except Exception as e:  # noqa: BLE001
        out, ok = f"{type(e).__name__}: {e}", False
    if ok:
        ctx = (f"[voice-latch hook] The user typed 'voice {m.group(1).lower()}'. The hook already ran "
               f"voice-latch.ps1 -Action {action}. Result: {out}. Do NOT run the skill or any tool again. "
               f"Reply with one line only: report the result.")
    else:
        ctx = (f"[voice-latch hook] The user typed 'voice {m.group(1).lower()}'. The hook ran "
               f"voice-latch.ps1 -Action {action} and it FAILED: {out}. Report this error verbatim; "
               f"do not retry with a different launch method.")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ctx}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
