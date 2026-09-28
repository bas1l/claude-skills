#!/usr/bin/env python3
"""UserPromptSubmit hook: TL;NR gate switch + per-turn rule injection.

`tlnr on|off|status` (also tldr, tl;dr, tl;nr) as an entire prompt flips the flag
and is erased (exit 2), so it costs no turn. Any other prompt passes through;
when the flag is on, the rules go to stdout, which Claude Code injects as context
the model can see -- the one channel the docs guarantee reaches Claude.

The length threshold is announced here and enforced in tldr_gate.py. Both read
it from tldr_conf.py so they cannot disagree.
"""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tldr_conf

HOOK_DIR = tldr_conf.HOOK_DIR
FLAG     = os.path.join(HOOK_DIR, "tldr-gate.flag")
LOG      = os.path.join(HOOK_DIR, "tldr-hook.log")

# Deliberately liberal: tl / tldr / tlnr / tl;dr / tl;nr / tl dr, any case.
TRIGGER = re.compile(r"tl[ ;:,.]*[dn]r[ ]+(on|off|status)", re.IGNORECASE)


ASK_RULE = """
If the answer needs anything back from the operator -- a question, a decision, a
choice between options, a missing fact, an approval -- the LAST bullet of the
block must say so, and must start with "Ask:":

- Ask: run the 10-second head-sweep capture now, or add pose logging to the viewer page first?

The Ask bullet is the one that demands an answer, so it above all must read cold:
spell out each option instead of pointing at it ("add pose logging to the viewer
page", never "add the logging"). It may run to %d words, since it carries the
options as well as their subjects. It is extra: it does not count against the
bullet limit above. Write it whenever the answer puts a question to the operator,
including when the question is only implied by "tell me which" or "confirm before
I proceed". If nothing is needed from them, leave it out -- never write an empty
Ask.

"""


def rules(cfg):
    return """[TL;NR gate is ON for this turn.]

If your response will run longer than about %d characters (roughly %d lines of
prose), write the full answer first, then a blank line, then END the response
with a summary block -- nothing may follow the block:

**TL;NR**
- one to three bullets, each starting with "- "
- plain words: no jargon, no hedging, no throat-clearing
- essential facts only -- what is true, what it means, what to do next

Every bullet must name its own subject. Write for someone who reads ONLY this
block: no body above it, no memory of earlier turns. Concretely:

- no bare definite reference to something the block never names -- "the logging",
  "the fix", "the test", "the probe", "the change"
- no pronoun whose antecedent sits in the body -- "it", "this", "that one"
- no section number, file name, identifier or bare figure standing on its own
  (a naked "section 32", "0 of 433", "v7", "the 133 ms") unless the same bullet
  says what it is and what it shows
- no project shorthand and no unexplained jargon
- name the thing before leaning on it: "add pose logging to the viewer page",
  not "add the logging"; "the 433-frame pose solve moved 0 frames", not
  "0 of 433"

Each bullet must stand alone, be readable in under two seconds, and be %d words
or fewer -- long enough to name a subject, too short to become prose. Do not thin
out the full answer above it; the block is an addition, not a replacement. The
header may be written **TL;NR** or **TL;DR**.
%s
If the response is shorter than that, skip the block entirely -- a short answer
is already its own summary and a block under it is noise.""" % (
        cfg["min_chars"], max(1, cfg["min_chars"] // 80), cfg["max_bullet_words"],
        (ASK_RULE % cfg["max_ask_words"]) if cfg["require_ask_bullet"] else "")


def note(msg):
    """One line per invocation, so "did the hook actually fire?" is answerable."""
    try:
        lines = open(LOG, encoding="utf-8").readlines() if os.path.exists(LOG) else []
        lines = lines[-199:] + [msg + chr(10)]
        open(LOG, "w", encoding="utf-8").writelines(lines)
    except Exception:
        pass


def state():
    return "ON" if os.path.exists(FLAG) else "OFF"


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)                      # never break the prompt on a bad read

    cfg    = tldr_conf.load()
    prompt = (data.get("prompt") or "").strip()
    m      = TRIGGER.fullmatch(prompt)
    note("fired session=%s gate=%s match=%s prompt=%r"
         % (str(data.get("session_id", "?"))[:8], state(), bool(m), prompt[:40]))

    if m:
        action = m.group(1).lower()
        if action == "on":
            os.makedirs(HOOK_DIR, exist_ok=True)
            open(FLAG, "w").close()
        elif action == "off" and os.path.exists(FLAG):
            os.remove(FLAG)
        msg = "TL;NR gate: %s (threshold %d chars)" % (state(), cfg["min_chars"])
        print(json.dumps({"systemMessage": msg}))
        print("[%s]" % msg, file=sys.stderr)
        sys.exit(2)                      # erase the control phrase

    if os.path.exists(FLAG):
        print(rules(cfg))                # injected as context Claude sees
    sys.exit(0)


if __name__ == "__main__":
    main()
