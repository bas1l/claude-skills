#!/usr/bin/env python3
"""Shared knobs for the TL;NR hooks, re-read on every invocation.

Kept in one file so the threshold the gate ENFORCES and the threshold the
switch ANNOUNCES can never drift apart.
"""
import json, os

# Code and knobs are versioned in the skills repo, next to this file; runtime
# state (on/off flag, log) stays in ~/.claude/hooks so it never gets committed.
HOOK_DIR = os.path.join(os.path.expanduser("~"), ".claude", "hooks")
CONF     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tldr-gate.conf.json")

# Wordings that put something to the operator without a question mark. Matched
# case-insensitively on word boundaries, after code and emphasis are stripped.
ASK_PHRASES = [
    "tell me", "let me know", "let me have", "say the word", "your call",
    "your choice", "your decision", "up to you", "at your discretion",
    "want me to", "would you like", "do you want", "shall i", "should i",
    "please confirm", "confirm before", "confirm whether", "confirm that you",
    "pick one", "pick which", "choose one", "choose which", "which one do you",
    "which do you", "what do you", "how do you want", "decide whether",
    "waiting on you", "waiting for you", "need from you", "needed from you",
    "i need you to", "if you want me", "sign off", "green light",
    "give me the go", "over to you",
]

DEFAULTS = {
    "require_ask_bullet": True,  # an answer that asks the operator something
                                 # must end its block with "- Ask: ..."
    "min_chars":       1024,   # replies shorter than this need no block
    "max_bullets":        3,   # the Ask bullet is extra and does not count
    "max_bullet_words":  25,   # room to NAME the subject, not room for prose
    "max_ask_words":     35,   # the Ask must name the options as well as ask
    "max_retries":        2,
    "ask_phrases":  ASK_PHRASES,   # a "?" is not the only way to ask something
}


def load():
    cfg = dict(DEFAULTS)
    try:
        raw = json.load(open(CONF, encoding="utf-8"))
        for k, default in DEFAULTS.items():
            v = raw.get(k)
            # bool first: in Python bool is a subclass of int, so a plain
            # isinstance(v, int) test would swallow true/false silently.
            if isinstance(default, bool):
                if isinstance(v, bool):
                    cfg[k] = v
            elif isinstance(default, list):
                if isinstance(v, list) and all(isinstance(x, str) and x.strip()
                                               for x in v):
                    cfg[k] = [x.strip().lower() for x in v]
            elif isinstance(v, int) and not isinstance(v, bool) and v > 0:
                cfg[k] = v
    except Exception:
        pass                      # a broken conf must never break a turn
    return cfg
