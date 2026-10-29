#!/usr/bin/env python3
"""UserPromptSubmit + Stop hook: a WhatsApp-style time stamp on every message.

Hooks cannot edit message text, so the stamp is shown as a systemMessage -- a
notice line in the transcript, printed by the harness and never seen by the
model, so it costs no tokens and cannot be got wrong.

    msg_clock.py prompt   -> "you . 2026-10-05 12:29"        (prompt sent)
    msg_clock.py reply    -> "claude . 12:34 . took 5m 02s"  (turn finished)

The prompt time is kept per session in TEMP so the reply can show how long the
turn took. Independent of the TL;NR gate: stamps appear whether it is on or off.
"""
import datetime, json, os, re, sys

STATE_DIR = os.path.join(os.environ.get("TEMP", os.path.expanduser("~")), "msg-clock")
SAFE_ID   = re.compile(r"[^A-Za-z0-9_-]")


def state_path(session_id):
    return os.path.join(STATE_DIR, SAFE_ID.sub("_", session_id or "nosession"))


def took(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return "%dh %02dm" % (h, m)
    if m:
        return "%dm %02ds" % (m, s)
    return "%ds" % s


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)                      # never break a turn on a bad read

    now  = datetime.datetime.now()
    path = state_path(str(data.get("session_id", "")))
    mode = sys.argv[1] if len(sys.argv) > 1 else ""

    if mode == "prompt":
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            open(path, "w").write(now.isoformat())
        except Exception:
            pass
        msg = "you · %s" % now.strftime("%Y-%m-%d %H:%M")
    elif mode == "reply":
        msg = "claude · %s" % now.strftime("%H:%M")
        try:
            sent = datetime.datetime.fromisoformat(open(path).read().strip())
            if sent.date() != now.date():
                msg = "claude · %s" % now.strftime("%Y-%m-%d %H:%M")
            msg += " · took %s" % took((now - sent).total_seconds())
        except Exception:
            pass                         # no prompt stamp yet: time only
    else:
        sys.exit(0)

    print(json.dumps({"systemMessage": msg}))
    sys.exit(0)


if __name__ == "__main__":
    main()
