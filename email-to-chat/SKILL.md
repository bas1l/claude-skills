---
name: email-to-chat
description: "Convert an email thread into a chat-style .docx — chronological, one bubble colour per participant, quoted trailers and signatures stripped, inline images embedded. Takes an .eml/.msg file, or an email title to pull the whole conversation straight out of classic Outlook (which also recovers branches a single forwarded message cannot). Use when an email thread has to be readable by someone who was not on it."
argument-hint: "<email-title> | <path-to-.eml-or-.msg> [--preview] [--sources <dir>]"
disable-model-invocation: false
effort: high
---

# email-to-chat — turn an email thread into a readable conversation

A forwarded thread is close to unreadable for a newcomer: reverse chronological, every
message quoted again inside every later one, buried under signature blocks, legal footers
and 600-character Outlook safelinks. This skill flattens it into a chat transcript in Word —
oldest first, one bubble per message, one colour per person, images in place.

Three stages. Two scripts do the deterministic work; **you** do the one part that needs
judgement, which is splitting the thread into messages. Never try to do the decoding or the
rendering by hand, and never try to segment with a regex.

```
 a file  ─▶ input.eml/.msg ──────────────▶ extract_thread.py ─┐
                                           thread.txt         │
                                           images/            │
                                           manifest.json      │
                                                              ├─▶ you segment ─▶ render_chat_docx.py ─▶ .docx
 a title ─▶ export_conversation.ps1 ─▶ merge_conversation.py ─┘   chat.json
            one .msg per message         thread.txt
            _index.json                  images/ manifest.json
```

**Prefer the title route whenever Outlook is available.** A single exported message carries
only its own ancestor path in its quoted trailer, so any branch that forked earlier is
unrecoverable from it — no export of one message can fix that. The title route reads every
message in the conversation separately and is the only way to get a complete thread. On the
one thread where both routes were run, the file route produced 3 messages and the title
route 5.

## When to use

- Someone joins a project mid-thread and needs the history.
- A thread has to be filed as a readable project record.
- The user asks to "make this email readable", "clean up this thread", or to convert an
  `.eml`/`.msg` into a document.
- The user names a thread by its subject line, or complains that an export gave them only
  part of a conversation — that is the title route, and it is the fix.

Not for: a single message with no reply history (there is no conversation to reconstruct —
say so), mailbox archives, or anything that needs sending.

## Argument parsing

`$ARGUMENTS` is either a path or an email title, optionally followed by flags. Decide by
testing the argument with `Test-Path`: an existing file is the file route, anything else is a
title.

| Input | Meaning |
|---|---|
| `<path>.eml` / `<path>.msg` | Convert that one file. Incomplete by construction — see below. |
| `"<email title>"` | Find that conversation in Outlook and convert all of it. |
| `--preview` | Also render a PDF via Word COM and read it back to check the layout. |
| `--sources <dir>` | Parent folder for the per-conversation export folder. Default: the session's folder. |
| empty | Ask the user for a path or a title, and **stop**. Do not guess. |

If the argument is a path that does not exist, do **not** silently treat it as a title —
a mistyped filename would then search the mailbox for nonsense. Say the file is missing and
ask which was meant.

Output path: on the file route it is always the input's own folder and basename with a
`.docx` extension.

On the title route there is no input file, so stage 0 computes the name and reports it as
`suggested_output` in `manifest.json` — **use that value, never hand-build the path.** The
layout it produces, per conversation:

```
<session folder>\
    2026-08-03_Potential artifact help\        <- extracted .msg, one per message
        2026-08-03_1337_Irene Perini.msg
        2026-08-05_0910_do Nascimento Arantes Adryelle.msg
        ...
    2026-08-03_Potential artifact help.docx    <- the transcript
```

The base name is `<date of the FIRST message>_<conversation title>`, sanitised, and the
folder and the `.docx` always share it so the pairing is self-evident. The date is the
thread's start, not its most recent message, so the name does not change as a thread grows.

Two consequences to keep in mind. Stage 0 shortens the base name at a word boundary when the
session folder is long enough that `<folder>\<base>\<message>.msg` would exceed MAX_PATH —
it prints a `note` when it does, and the `.docx` is shortened identically. And two
conversations that start on the same day with the same title collide; stage 0 does not
disambiguate them, so check the `-ListOnly` output when that looks possible.

If a `.docx` for the thread already exists under a different name from the file route,
**replace it** rather than leaving both. Two documents of one thread, one of them missing
messages, is worse than one.

## Layout

| Path | What it is |
|---|---|
| `scripts/export_conversation.ps1` | Stage 0 — find a conversation by title in Outlook, export every message as `.msg`. |
| `scripts/merge_conversation.py` | Stage 0b — trim each message to its own text, resolve reply structure. |
| `scripts/extract_thread.py` | Stage 1 — MIME decode, safelink unwrap, attachment extraction. |
| `scripts/render_chat_docx.py` | Stage 3 — the renderer. Owns all styling decisions. |
| `%TEMP%\email-to-chat\<basename>\` | Working directory for one run. |

---

## Step 0 — dependencies

```powershell
python -c "import docx" 2>$null || python -m pip install python-docx --quiet
```

Only if the input is `.msg`:

```powershell
python -c "import extract_msg" 2>$null || python -m pip install extract-msg --quiet
```

## Step 0b — title route: export the conversation from Outlook

Skip to Step 1 if the argument was a file path.

First list what matches, without exporting anything:

```powershell
& "$env:USERPROFILE\.claude\skills\email-to-chat\scripts\export_conversation.ps1" -Title "<title>" -ListOnly
```

It prints one block per distinct conversation: topic, message count, date span, senders.
**Show that to the user before exporting** — title matching is deliberately the only key, so
unrelated mail sharing a subject appears here, and it is cheaper to notice now.

- Several conversations listed → re-run with `-Group "<exact topic>"`.
- Nothing listed → the mail may not be in Inbox. Report it; do not silently widen the scope.

Then export and merge:

```powershell
& "$env:USERPROFILE\.claude\skills\email-to-chat\scripts\export_conversation.ps1" -Title "<title>" -SourceDir "<session folder>"
```

`-SourceDir` is the **parent** folder — stage 0 creates the per-conversation subfolder inside
it and prints both `sources` and `render to`. Omit it and it defaults to the session folder,
which is normally what you want. `-WorkDir` defaults to
`%TEMP%\email-to-chat\<base name>`; pass it only to override. Then merge with whatever
`workdir` the export printed:

```powershell
python "$env:USERPROFILE\.claude\skills\email-to-chat\scripts\merge_conversation.py" "<workdir>"
```

`merge_conversation.py` writes the same `thread.txt` / `manifest.json` / `images/` trio the
file route produces, so Steps 2–4 are unchanged. What differs is that `thread.txt` already
holds one section per message, each trimmed to its own text — you are no longer un-nesting
trailers, only judging what to keep. Verify rather than trust:

- `cut:` names the boundary pattern that fired. `none (no trailer)` is correct for the thread
  root and suspicious anywhere else — the manifest warns when a reply has no boundary.
- `own/full` char counts show how much was trimmed.
- `*** BRANCH ***` marks a message replying to something other than the one above it. Give
  each of those a `note` block naming its real parent, e.g.
  `[Replies to Irene's 14:28 message, in parallel with Bo Wahlström's reply]`. A flat
  transcript otherwise reads it as a direct reply, which is exactly wrong on the threads this
  route exists to capture.
- Autoreplies are flagged `auto_reply`. Render as a one-line `note`, not a bubble.

### Constraints of this route

Verified on this machine, not guesses:

- **Classic Outlook desktop only.** The new Outlook (`olk.exe`) exposes no COM. Exit code 4.
- **MAX_PATH.** `SaveAs` fails with a bare "The operation failed." when the target path
  reaches 260 characters — indistinguishable from a permissions refusal. The script checks
  the length first and names the cause. Keep `-SourceDir` short.
- **Sync.** A mailbox mid-download returns a partial thread with no error. Before trusting a
  result, run `-ListOnly` twice and check the count is stable; the global inbox count may
  still be climbing while a recent thread is already complete, so watch the thread, not the
  mailbox.
- **Scope is Inbox + Sent Items of the default account.** If Sent Items is empty or unsynced,
  the user's own messages are missing from the export even though the trailers of others'
  replies may contain them. Say so in the final report rather than presenting the thread as
  complete.
- The Outlook Object Model Guard did not prompt here (AV registered with Windows Security
  Center suppresses it). If it does, the error names the `PromptOOMSaveAs` policy value.

## Step 1 — extract

```powershell
python "$env:USERPROFILE\.claude\skills\email-to-chat\scripts\extract_thread.py" "<input>" "$env:TEMP\email-to-chat\<basename>"
```

It prints the character count, every attachment with its byte size and pixel dimensions, and
any warnings. Read those warnings before continuing — an encrypted message or an
HTML-only body changes what you can promise.

## Step 2 — segment

Read `thread.txt` and `manifest.json`. Write `chat.json` into the same working directory.

### Schema

```json
{
  "title": "TILA2 — temporal interference / fMRI",
  "messages": [
    { "sender": "Irene Perini",
      "date":   "2026-06-18",
      "time":   "14:59",
      "domain": "liu.se",
      "blocks": [
        {"type": "text",  "value": "Dear all,"},
        {"type": "ref",   "value": "pubmed.ncbi.nlm.nih.gov/28213645/"},
        {"type": "image", "value": "image001.jpg"},
        {"type": "note",  "value": "[2 images — not carried over in the forwarded thread]"}
      ] } ] }
```

`title` — the thread subject with `RE:`/`FW:` prefixes removed. `domain` — the sender's
email domain; it drives the left/right split, so fill it in for every message.

| Block type | Renders as | Use for |
|---|---|---|
| `text` | normal paragraph | body text, one block per paragraph |
| `ref` | smaller, indented | URLs, citation lists, passages the sender quotes back |
| `image` | embedded picture | filename exactly as listed in `manifest.json` |
| `note` | small italic grey | lost images, attachments, meeting metadata, your annotations |

### Rules

1. **Chronological ascending** — oldest message first. This is the reverse of how the
   thread reads in the mail client. Getting this backwards defeats the whole point.
2. **Un-nest the quoted trailers.** Every message appears again, quoted, inside every later
   message. Take each message exactly once, at its own position, from its earliest
   appearance. A thread of N messages yields N bubbles, not N(N+1)/2 paragraphs.
   *Title route:* already done — each section of `thread.txt` is one message's own text. Do
   not go looking in the trailers for messages, but do read `*** BRANCH ***` (rule 10).
3. **Reply headers come in several dialects.** Recognise `From:/Sent:/Subject:`,
   `Von:/Gesendet:/Betreff:`, `De:/Envoyé:/Objet:`, and `On <date>, <name> wrote:` — a
   single thread can mix languages when participants use different Outlook locales. This is
   precisely why segmentation is your job and not a regex's.
4. **Keep greetings, drop closings.** "Dear Uta and Ines," records who was addressed in a
   multi-party thread and is worth keeping. Sign-offs, signature blocks, corporate legal
   footers, "Follow us on LinkedIn", ISO banners and address blocks all go.
5. **Timestamps**: use the local time printed in each reply header. The outermost message
   often carries only a UTC `Date:` header — convert it to the thread's prevailing local
   time and note the conversion in your final report. *Title route:* `sentOn` comes from
   Outlook and is already local, so no conversion and no caveat is needed. Prefer it over a
   time printed in a trailer — the two can disagree by a few minutes.
6. **Lost images are marked, never dropped silently.** A `[cid:image001.png]` or
   `<image004.jpg>` placeholder with no matching entry in `manifest.json` becomes a `note`
   block. Forwarding routinely strips inline figures, and those figures are often what the
   discussion is about.
7. **Discard decoration.** `manifest.json` flags images under 6 KB as `likely_decoration` —
   these are signature logos and social-media icons. Check that the flag matches context
   before dropping; a small image referenced in the body text is content.
8. Non-image attachments are named in a `note` block (`Attached: report.pdf`), never
   embedded.
9. Meeting invitations: fold When/Where into a single `note` block.
10. **Branches get a `note` naming the real parent** (title route only). `manifest.json` gives
    `parent` and `branch` per message, derived from `ConversationIndex`. Without the note a
    parallel reply reads as a direct one. Also honour `parent_gap > 1`: an ancestor is missing
    from the export, which is worth a `note` and a line in the final report.

## Step 3 — render

```powershell
python "$env:USERPROFILE\.claude\skills\email-to-chat\scripts\render_chat_docx.py" "$env:TEMP\email-to-chat\<basename>\chat.json" "<suggested_output>" "$env:TEMP\email-to-chat\<basename>\images"
```

The renderer owns every styling decision — do not ask the user about colours or layout, and
do not hand-edit the docx afterwards:

- **Colour per participant**, assigned from a fixed 8-colour palette in order of first
  appearance. A legend under the title names each one.
- **Side**: the email domain that sent the most messages goes left, everyone else right.
  Above four participants or two domains it falls back to a single left column, because a
  two-sided layout stops meaning anything at that point.
- Date separator pills, sender name, right-aligned timestamp, bubbles that do not split
  across pages, chat wallpaper background.

It prints the message count, each participant's colour and side, and warns about any image
it could not find.

## Step 4 — verify and report

With `--preview`, convert and look at the result:

```powershell
$w = New-Object -ComObject Word.Application; $w.Visible = $false
$d = $w.Documents.Open("<output.docx>", $false, $true)
$d.SaveAs([ref]"$env:TEMP\email-to-chat\preview.pdf", [ref]17)
"pages: $($d.ComputeStatistics(2))"; $d.Close([ref]0); $w.Quit()
```

Then Read the PDF's first pages to confirm the layout.

Always finish with a short report to the user: message count and date span, participants
with their colours, images embedded, **images lost in the forward**, timezone conversions
applied, page count. Never block mid-run to ask about any of this — mark it and report it.

---

## Edge cases

| Condition | Action |
|---|---|
| Encrypted or S/MIME-signed (`manifest.json` warning) | Report it and **stop**. The body cannot be read. |
| No `text/plain` part | Stage 1 falls back to HTML and warns. Segment anyway, tell the user the text is approximate. |
| Single message, no reply history | Render as one bubble, and say the thread had nothing to flatten. |
| More than 8 participants | Palette cycles; the renderer forces a single column. Nothing to do. |
| Two people, one domain | Single column — a left/right split needs two domains. Expected, not a bug. |
| Same sender, two name spellings ("Peter Lundberg" / "Lundberg, Peter") | Normalise to one form in `chat.json`, or they get two colours. |
| Image referenced but absent | `note` block. Suggest the user request it from the sender. |
| Thread over ~60 messages | Segment in passes of ~20 and concatenate the `messages` arrays before rendering. |

## Important rules

- **Never invent content.** If a message body is truncated or garbled, put what survives in
  a `text` block and add a `note` saying it was truncated.
- **Never reorder within a message.** Blocks keep the sender's own sequence.
- **Do not hand-edit the .docx.** Every styling change belongs in `render_chat_docx.py`, so
  the next thread renders identically.
- Re-running is cheap: fix `chat.json` and re-run Step 3 alone. Do not re-extract.
- Leave the working directory in `%TEMP%` in place after the run — it is the audit trail if
  the user disputes a segmentation.

## Out of scope

mbox and batch folders; pasted plain text; PDF as a first-class output; replying, sending
or filing to a mail server; per-run styling flags. Colour and side assignment are automatic
by design — if the user wants a different look, change the renderer.
