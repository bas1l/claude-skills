# -*- coding: utf-8 -*-
"""
Stage 0b of the email-to-chat skill - merge an exported conversation.

    python merge_conversation.py <workdir>

<workdir> is what export_conversation.ps1 produced: `_index.json` plus
`sources/*.msg`. Writes into <workdir>:

    thread.txt      one section per message, in time order, each trimmed to the
                    text that message itself added
    manifest.json   per-message metadata, reply structure, attachment inventory
    images/         attachments, prefixed per message so names cannot collide

Why this exists: a single exported message carries only its own ancestor path in
its quoted trailer, so sibling branches are unrecoverable from it. With every
message exported separately, the trailers become redundant - each message is
taken once, from its own file, in its original form.

That makes the cut this script performs a much narrower problem than segmenting
a thread: it only has to find the FIRST trailer boundary in each body and drop
everything below. It still records the untrimmed body and which pattern matched,
so Stage 2 can check the cut rather than trust it.

Reply structure comes from ConversationIndex, not from the text. Its layout is a
22-byte header followed by one 5-byte block per reply level, so a message's
parent is the message whose index is its own minus the last block.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_thread import (load_message, pick_body, tidy,  # noqa: E402
                            save_attachments)


# --------------------------------------------------------------------------
# trailer boundaries
# --------------------------------------------------------------------------

# Each entry must be precise enough not to fire inside prose. The From:/Sent:
# form demands both header lines, because a bare "From:" appears in ordinary
# sentences. Locales are mixed deliberately: one thread can contain Swedish,
# German, French and Czech Outlook trailers when participants run different
# language builds - this corpus already has Re:, RE:, Sv: and Fwd: in one thread.
_SENDER = r"From|Från|Fran|Von|De|Da|Odesílatel|Odesilatel|Fra|Van|Mittente"
_SENT = (r"Sent|Skickat|Gesendet|Envoyé|Envoye|Date|Datum|Odesláno|Odeslano|"
         r"Verzonden|Inviato")

BOUNDARIES = [
    ("original-message",
     re.compile(r"(?m)^[ \t]*-{2,}[ \t]*(Original Message|Ursprungligt "
                r"meddelande|Originalnachricht|Message d'origine|"
                r"Původní zpráva)[ \t]*-{2,}", re.I)),
    ("header-block",
     re.compile(r"(?ms)^[ \t]*(?:%s)[ \t]*:.*?^[ \t]*(?:%s)[ \t]*:"
                % (_SENDER, _SENT))),
    ("on-wrote",
     re.compile(r"(?ms)^[ \t]*(On|Den|Am|Le|Op)\b.{4,240}?\b"
                r"(wrote|skrev|schrieb|a écrit|a ecrit|napsal)\s*:")),
    ("hr-rule",
     re.compile(r"(?m)^[ \t]*_{20,}[ \t]*$")),
]

AUTOREPLY = re.compile(
    r"^\s*(Automatic reply|Autosvar|Automatiskt svar|Out of office|"
    r"Automatische Antwort|Réponse automatique|Automaticka odpoved|"
    r"Automatická odpověď)\b", re.I)


def split_own_text(body):
    """
    Return (own_text, marker, cut_offset).

    own_text is everything above the earliest trailer boundary. marker names the
    pattern that fired, or None when the body has no trailer at all - which is
    normal for the message that started the thread.
    """
    earliest, marker = None, None
    for name, pat in BOUNDARIES:
        m = pat.search(body)
        if m and (earliest is None or m.start() < earliest):
            earliest, marker = m.start(), name
    if earliest is None:
        return body.strip(), None, None
    return body[:earliest].strip(), marker, earliest


# --------------------------------------------------------------------------
# reply structure from ConversationIndex
# --------------------------------------------------------------------------

HEADER_HEX = 44      # 22 bytes
BLOCK_HEX = 10       # 5 bytes per reply level


def index_depth(ci):
    if not ci or len(ci) < HEADER_HEX:
        return None
    return (len(ci) - HEADER_HEX) // BLOCK_HEX


def resolve_parents(messages):
    """
    Fill in `depth`, `parent` (list position or None) and `branch` per message.

    `branch` marks a message whose parent is not the one immediately before it
    in time - i.e. a reply to an earlier message that forked the thread. Those
    are exactly the messages a flat transcript would otherwise misrepresent as
    direct replies, and exactly the ones a single-message export loses.

    `branch` requires the parent to have been FOUND (parent_gap == 1). When an
    intermediate ancestor is absent from the export - typically the user's own
    reply, sitting in an unsynced Sent Items - the nearest present ancestor is
    further up, and treating that as a fork would assert a thread shape that the
    data does not support. Those get `parent_missing` instead, which is a
    statement about the export rather than about the conversation.
    """
    by_ci = {}
    for i, m in enumerate(messages):
        ci = (m.get("conversationIndex") or "").upper()
        if ci:
            by_ci.setdefault(ci, i)

    for i, m in enumerate(messages):
        ci = (m.get("conversationIndex") or "").upper()
        m["depth"] = index_depth(ci)
        m["parent"] = None
        m["branch"] = False
        m["parent_missing"] = 0
        if not ci or not m["depth"]:
            continue
        # walk up one block at a time; an intermediate message may be absent
        # from the export (deleted, or filed in a folder outside the scope)
        for k in range(1, m["depth"] + 1):
            cand = ci[:len(ci) - BLOCK_HEX * k]
            if len(cand) < HEADER_HEX:
                break
            j = by_ci.get(cand)
            if j is not None and j != i:
                m["parent"] = j
                m["parent_gap"] = k          # >1 means ancestors are missing
                break
        gap = m.get("parent_gap", 1)
        m["parent_missing"] = max(0, gap - 1)
        if m["parent"] is not None and m["parent"] != i - 1 and gap == 1:
            m["branch"] = True
    return messages


# --------------------------------------------------------------------------

def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__.strip())
    workdir = sys.argv[1]
    index_path = os.path.join(workdir, "_index.json")
    if not os.path.isfile(index_path):
        sys.exit("no _index.json in %s - run export_conversation.ps1 first"
                 % workdir)

    with open(index_path, encoding="utf-8-sig") as fh:
        meta = json.load(fh)

    src_dir = meta.get("sourceDir") or workdir
    raw = meta.get("messages") or []
    if isinstance(raw, dict):            # ConvertTo-Json collapses a 1-element list
        raw = [raw]

    messages, used_names = [], set()
    for i, rec in enumerate(raw):
        path = os.path.join(src_dir, rec["file"])
        if not os.path.isfile(path):
            print("WARN  missing source: %s" % rec["file"])
            continue

        # One unreadable file must not cost the other eighteen. Record the
        # failure as a message so it stays visible downstream instead of the
        # thread quietly coming up short.
        try:
            msg = load_message(path)
            body, body_source = pick_body(msg)
            body = tidy(body)
            own, marker, cut = split_own_text(body)
            atts = save_attachments(msg, workdir, prefix="m%02d_" % (i + 1),
                                    used=used_names)
            load_error = None
        except Exception as exc:
            print("ERROR unreadable, kept as a placeholder: %s (%s)"
                  % (rec["file"], exc))
            body, body_source, own, marker, cut, atts = "", "unreadable", "", None, None, []
            load_error = "%s: %s" % (type(exc).__name__, exc)

        messages.append({
            "n": i + 1,
            "file": rec["file"],
            "sender": rec.get("senderName") or "(unknown)",
            "sentOn": rec.get("sentOn"),
            "subject": rec.get("subject"),
            "conversationIndex": rec.get("conversationIndex"),
            "messageClass": rec.get("messageClass"),
            "is_meeting": str(rec.get("messageClass") or "").startswith(
                "IPM.Schedule.Meeting"),
            "folder": rec.get("folder"),
            "body_source": body_source,
            "load_error": load_error,
            "cut_marker": marker,
            "cut_offset": cut,
            "chars_own": len(own),
            "chars_full": len(body),
            "auto_reply": bool(AUTOREPLY.match(rec.get("subject") or "")),
            "own_text": own,
            "full_text": body,
            "attachments": atts,
        })

    messages.sort(key=lambda m: (m["sentOn"] or "", m["n"]))
    resolve_parents(messages)

    # ---------------------------------------------------------------- thread.txt
    lines = []
    lines.append("CONVERSATION  %s" % (meta.get("topic") or "(unknown topic)"))
    lines.append("messages      %d" % len(messages))
    lines.append("scope         %s" % ", ".join(meta.get("scope") or []))
    lines.append("")
    lines.append("Each section below is one message, trimmed to the text that "
                 "message itself added.")
    lines.append("Quoted trailers are cut, not interpreted - `cut` names the "
                 "pattern that fired.")
    lines.append("`replies-to` comes from ConversationIndex. BRANCH means it "
                 "replies to something")
    lines.append("other than the preceding message.")
    lines.append("=" * 74)

    for pos, m in enumerate(messages):
        parent = m.get("parent")
        if parent is None:
            rel = "thread root"
        elif m["parent_missing"]:
            rel = ("nearest present ancestor is message %d (%s)"
                   % (messages[parent]["n"], messages[parent]["sender"]))
        else:
            rel = "message %d (%s)" % (messages[parent]["n"], messages[parent]["sender"])
        flag = ""
        if m["branch"]:
            flag = "   *** BRANCH ***"
        elif m["parent_missing"]:
            flag = "   *** PARENT ABSENT ***"
        lines.append("")
        lines.append("[%d] %s  --  %s" % (m["n"], m["sender"], m["sentOn"] or "?"))
        lines.append("    subject     %s" % m["subject"])
        lines.append("    replies-to  %s%s" % (rel, flag))
        lines.append("    depth       %s   cut: %s   body: %s   own/full: %d/%d chars"
                     % (m["depth"], m["cut_marker"] or "none (no trailer)",
                        m["body_source"], m["chars_own"], m["chars_full"]))
        if m["parent_missing"]:
            lines.append("    NOTE        %d message(s) it replies through are absent from the"
                         % m["parent_missing"])
            lines.append("                export - check Sent Items, and do NOT call this a branch")
        if m["auto_reply"]:
            lines.append("    NOTE        looks like an out-of-office autoreply")
        if m["is_meeting"]:
            lines.append("    NOTE        meeting request (%s) - fold When/Where into one note"
                         % m["messageClass"])
        if m["attachments"]:
            for a in m["attachments"]:
                dims = ("%sx%s" % (a["width"], a["height"])) if a.get("width") else "-"
                lines.append("    attachment  %-28s %7d B  %-9s %s"
                             % (a["filename"], a["bytes"], dims,
                                "(likely decoration)" if a.get("likely_decoration") else ""))
        lines.append("    " + "-" * 66)
        for ln in (m["own_text"] or "(empty)").split("\n"):
            lines.append("    " + ln)

    with open(os.path.join(workdir, "thread.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines).rstrip() + "\n")

    # ---------------------------------------------------------------- manifest
    out = {
        "source": "outlook-conversation-export",
        "topic": meta.get("topic"),
        "query": meta.get("query"),
        "scope": meta.get("scope"),
        "base_name": meta.get("baseName"),
        # set by stage 0: <session folder>\<first-message date>_<topic>.docx,
        # sitting beside the same-named folder of extracted .msg files
        "suggested_output": meta.get("suggestedOutput"),
        "message_count": len(messages),
        "branches": sum(1 for m in messages if m["branch"]),
        "missing_ancestors": sum(m["parent_missing"] for m in messages),
        "autoreplies": sum(1 for m in messages if m["auto_reply"]),
        "messages": [{k: v for k, v in m.items() if k != "full_text"}
                     for m in messages],
        "warnings": [],
    }
    if any(m["body_source"] == "text/html" for m in messages):
        out["warnings"].append(
            "Some bodies were recovered from HTML; their text is approximate.")
    if any(m["cut_marker"] is None and m["depth"] for m in messages):
        out["warnings"].append(
            "A reply had no detectable trailer boundary - check its cut manually.")
    broken = [m["file"] for m in messages if m.get("load_error")]
    if broken:
        out["warnings"].append(
            "%d message(s) could not be decoded and are placeholders: %s"
            % (len(broken), ", ".join(broken)))
    if out["missing_ancestors"]:
        out["warnings"].append(
            "Messages reply through %d absent ancestor(s); the export is incomplete "
            "(Sent Items unsynced, or those messages are filed outside the scope)."
            % out["missing_ancestors"])
    with open(os.path.join(workdir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)

    print("messages     %d" % len(messages))
    print("branches     %d" % out["branches"])
    print("absent anc.  %d" % out["missing_ancestors"])
    print("autoreplies  %d" % out["autoreplies"])
    print("images       %d" % sum(len(m["attachments"]) for m in messages))
    for w in out["warnings"]:
        print("WARN  %s" % w)
    print("thread.txt   %s" % os.path.join(workdir, "thread.txt"))


if __name__ == "__main__":
    main()
