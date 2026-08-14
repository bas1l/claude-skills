---
name: email-to-chat
description: "Convert an email thread (.eml or .msg) into a chat-style .docx — chronological, one bubble colour per participant, quoted trailers and signatures stripped, inline images embedded. Use when an email thread has to be readable by someone who was not on it."
argument-hint: "<path-to-.eml-or-.msg> [--preview]"
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
input.eml/.msg ──▶ extract_thread.py ──▶ you segment ──▶ render_chat_docx.py ──▶ .docx
                   thread.txt              chat.json
                   images/
                   manifest.json
```

## When to use

- Someone joins a project mid-thread and needs the history.
- A thread has to be filed as a readable project record.
- The user asks to "make this email readable", "clean up this thread", or to convert an
  `.eml`/`.msg` into a document.

Not for: a single message with no reply history (there is no conversation to reconstruct —
say so), mailbox archives, or anything that needs sending.

## Argument parsing

`$ARGUMENTS` is a path, optionally followed by flags.

| Input | Meaning |
|---|---|
| `<path>.eml` / `<path>.msg` | The thread to convert. |
| `--preview` | Also render a PDF via Word COM and read it back to check the layout. |
| empty | Ask the user for the path, and **stop**. Do not guess from the working directory. |

Output path is **not** an argument: it is always the input's own folder and basename with a
`.docx` extension. `manifest.json` reports it as `suggested_output`.

## Layout

| Path | What it is |
|---|---|
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
3. **Reply headers come in several dialects.** Recognise `From:/Sent:/Subject:`,
   `Von:/Gesendet:/Betreff:`, `De:/Envoyé:/Objet:`, and `On <date>, <name> wrote:` — a
   single thread can mix languages when participants use different Outlook locales. This is
   precisely why segmentation is your job and not a regex's.
4. **Keep greetings, drop closings.** "Dear Uta and Ines," records who was addressed in a
   multi-party thread and is worth keeping. Sign-offs, signature blocks, corporate legal
   footers, "Follow us on LinkedIn", ISO banners and address blocks all go.
5. **Timestamps**: use the local time printed in each reply header. The outermost message
   often carries only a UTC `Date:` header — convert it to the thread's prevailing local
   time and note the conversion in your final report.
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
