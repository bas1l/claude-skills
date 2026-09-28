#!/usr/bin/env python3
"""Stop hook: refuse to end the turn when a long reply lacks a valid TL;NR block.

Short replies are exempt: below conf["min_chars"] the hook exits immediately, so
a two-line answer never gets a summary bolted on top of it.

Exit 2 prevents Claude from stopping and forces another turn. The docs do NOT
promise a Stop hook's stderr reaches Claude (only PostToolUse and
PostToolUseFailure document that), so the reason goes out on stderr AND as
systemMessage -- whichever channel lands, lands.

Only structure is checked here. "Plain words" and "every bullet names its own
subject" are not machine-checkable -- a regex for "the logging" would misfire on
every well-written bullet -- so that half of the rule lives in tldr_switch.py,
which injects it before the turn.

Stop hooks hold the spinner until they exit -- keep this fast.
"""
import hashlib, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tldr_conf

FLAG      = os.path.join(tldr_conf.HOOK_DIR, "tldr-gate.flag")
STATE_DIR = os.path.join(os.environ.get("TEMP", tldr_conf.HOOK_DIR), "tldr-gate")

CANONICAL = "**TL;NR**"
# Accept either spelling, so the gate never rejects a block over a variant of
# its own name.
HEADER = re.compile(r"[*]{2}[ ]*TL[ ;:,.]*[DN]R[ ]*[*]{2}", re.IGNORECASE)

# The bullet that says what is wanted back from the operator. Bold optional, and
# a few synonyms accepted, so a well-formed block is never rejected on wording.
ASK = re.compile(r"^[*]{0,2}\s*(?:ask|you|your call|decide|needed from you)"
                 r"\s*[*]{0,2}\s*:\s*\S", re.IGNORECASE)

# Code is stripped before hunting for a question mark: a "?" inside a regex, a
# URL or a shell snippet is not a question put to the operator.
FENCE  = re.compile(r"```.*?```", re.DOTALL)
INLINE = re.compile(r"`[^`]*`")


# Emphasis marks are dropped so "*your* call" still reads as "your call".
EMPHASIS = re.compile(r"[*_~]+")
WS       = re.compile(r"\s+")

_PHRASE_CACHE = {}


def phrase_re(phrases):
    """One alternation over the configured wordings, built once per phrase list."""
    key = tuple(phrases)
    if key not in _PHRASE_CACHE:
        _PHRASE_CACHE[key] = re.compile(
            r"\b(?:%s)\b" % "|".join(re.escape(p) for p in phrases), re.IGNORECASE)
    return _PHRASE_CACHE[key]


def puts_a_question(body, cfg):
    """True when the answer above the block appears to ask the operator something.

    Two signals: a literal question mark, and any of the configured ask phrases
    ("tell me", "let me know", "shall I", ...) -- an ask is just as often an
    imperative as a question. Code is stripped first, so a "?" in a regex or a
    "should I" inside a quoted snippet does not count.
    """
    txt = WS.sub(" ", EMPHASIS.sub("", INLINE.sub(" ", FENCE.sub(" ", body))))
    return "?" in txt or bool(phrase_re(cfg["ask_phrases"]).search(txt))


def measure(msg):
    """Length in characters, and a rough token estimate for the operator's log."""
    chars = len(msg.strip())
    return chars, max(1, chars // 4)      # ~4 chars/token: an estimate, not a count


def violations(msg, cfg):
    """Return a list of structural problems; empty list means the block is fine."""
    lines = msg.strip().splitlines()
    if not lines:
        return []

    # The block closes the response: find the LAST header line, so a header
    # quoted earlier in the body is never mistaken for the block itself.
    heads = [n for n, l in enumerate(lines) if HEADER.fullmatch(l.strip())]
    if not heads:
        return ['the response must end with a "%s" block (no header line found)' % CANONICAL]
    h = heads[-1]

    bullets = []
    for j in range(h + 1, len(lines)):
        stripped = lines[j].strip()
        if not stripped.startswith("- "):
            return ['line %d after "%s" must start with "- ", and nothing may follow '
                    'the block (found: %r)' % (j - h, CANONICAL, stripped[:60])]
        bullets.append(stripped[2:])
    errs = []
    if not bullets:
        errs.append("the block has no bullets")

    asks = [n for n, b in enumerate(bullets) if ASK.match(b)]
    # The Ask bullet is an addition to the summary, not one of its slots.
    if len(bullets) - len(asks) > cfg["max_bullets"]:
        errs.append("%d summary bullets (Ask excluded); the maximum is %d"
                    % (len(bullets) - len(asks), cfg["max_bullets"]))
    if len(asks) > 1:
        errs.append("%d Ask bullets; there must be at most one" % len(asks))
    elif asks and asks[0] != len(bullets) - 1:
        errs.append("the Ask bullet must be the last bullet of the block")

    for n, b in enumerate(bullets, 1):
        # The Ask bullet has to name its options as well as ask for one, so it
        # gets the larger allowance. Both caps come from tldr_conf, which is also
        # what tldr_switch.py announces -- the two can never disagree.
        cap = cfg["max_ask_words"] if n - 1 in asks else cfg["max_bullet_words"]
        words = len(b.split())
        if words > cap:
            errs.append("bullet %d is %d words; the maximum is %d" % (n, words, cap))

    body = lines[:h]
    if not any(l.strip() for l in body):
        errs.append("the full answer must come first, then a blank line, then the block")
    elif body[-1].strip():
        errs.append('a blank line must separate the full answer from "%s"' % CANONICAL)
    elif cfg["require_ask_bullet"] and not asks and puts_a_question(chr(10).join(body), cfg):
        errs.append('the answer asks the operator something, so the block must end '
                    'with a bullet starting "Ask:" saying what is wanted back '
                    '(it does not count against the bullet limit)')
    return errs


def retries_exhausted(session_id, msg, cfg):
    """Count re-rolls per distinct response so an unsatisfiable rule cannot loop."""
    key = hashlib.sha1((session_id + msg).encode("utf-8", "replace")).hexdigest()[:16]
    os.makedirs(STATE_DIR, exist_ok=True)
    path = os.path.join(STATE_DIR, key)
    n = 0
    if os.path.exists(path):
        try:
            n = int(open(path).read().strip() or 0)
        except ValueError:
            n = 0
    if n >= cfg["max_retries"]:
        return True
    with open(path, "w") as fh:
        fh.write(str(n + 1))
    return False


def main():
    if not os.path.exists(FLAG):
        sys.exit(0)

    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)                       # never wedge a turn on a bad read

    cfg = tldr_conf.load()
    msg = data.get("last_assistant_message") or ""
    chars, est_tokens = measure(msg)

    if chars < cfg["min_chars"]:          # short reply: exempt by design
        sys.exit(0)

    errs = violations(msg, cfg)
    if not errs:
        sys.exit(0)

    if retries_exhausted(data.get("session_id", ""), msg, cfg):
        print(json.dumps({"systemMessage":
                          "TL;NR gate: giving up after %d attempts." % cfg["max_retries"]}))
        sys.exit(0)

    reason = ("Your last response is %d characters (~%d tokens), over the %d-character "
              "threshold, so it needs a summary block. Re-send the SAME answer, then a "
              "blank line, then this at the very end with nothing after it:" % (chars, est_tokens, cfg["min_chars"])
              + chr(10) * 2 + CANONICAL + chr(10) +
              "- name the subject inside the bullet, then say what is true of it"
              + chr(10) +
              "- essential facts only, readable with no body and no earlier turns"
              + chr(10) +
              "- Ask: <only when the answer needs something back; name the options>"
              + chr(10) * 2 +
              "Problems found:" + chr(10) + "- " + (chr(10) + "- ").join(errs))

    print(json.dumps({"systemMessage": reason}))
    print(reason, file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
