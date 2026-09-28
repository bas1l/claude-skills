# -*- coding: utf-8 -*-
"""
Stage 1 of the email-to-chat skill.

Decode an .eml or .msg email thread into agent-readable material:

    python extract_thread.py <input.eml|input.msg> <workdir>

Writes into <workdir>:
    thread.txt      decoded plain text, Outlook safelinks unwrapped, link
                    duplication collapsed
    images/         every image and file attachment, original filenames
    manifest.json   headers + attachment inventory (cid, size, dimensions)

Nothing here interprets the conversation -- that is the model's job in Stage 2.
This stage only removes the encoding and the boilerplate noise, and never
discards content it cannot classify.
"""

import json
import os
import re
import sys
import struct
from email import policy
from email.parser import BytesParser
from urllib.parse import unquote


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------

def load_message(path):
    """Return an email.message.EmailMessage from .eml or .msg."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".msg":
        try:
            import extract_msg
        except ImportError:
            sys.exit("extract_msg is required for .msg input: "
                     "python -m pip install extract-msg")
        # Outlook writes .msg files that declare one string encoding and then
        # store bytes in another - a Swedish message advertising UTF-8 while
        # holding cp1252 raises UnicodeDecodeError on the first body read. Retry
        # with the encodings that actually occur before giving up, rather than
        # letting one bad file abort a whole conversation.
        last = None
        for override in (None, "cp1252", "latin-1"):
            try:
                kwargs = {"overrideEncoding": override} if override else {}
                msg = extract_msg.Message(path, **kwargs)
                try:
                    return msg.asEmailMessage()
                except AttributeError:
                    sys.exit("extract_msg is too old for .asEmailMessage(): "
                             "python -m pip install -U extract-msg")
            except UnicodeDecodeError as exc:
                last = exc
                continue
        raise UnicodeDecodeError(last.encoding, last.object, last.start,
                                 last.end,
                                 "%s (tried cp1252 and latin-1 too)"
                                 % last.reason)
    with open(path, "rb") as fh:
        return BytesParser(policy=policy.default).parse(fh)


def pick_body(msg):
    """Best available body text. Prefer text/plain; fall back to HTML."""
    plain, html = [], []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        disp = (part.get_content_disposition() or "").lower()
        if disp == "attachment":
            continue
        ctype = part.get_content_type()
        try:
            payload = part.get_content()
        except Exception:
            raw = part.get_payload(decode=True) or b""
            payload = raw.decode(part.get_content_charset() or "utf-8",
                                 errors="replace")
        if ctype == "text/plain":
            plain.append(payload)
        elif ctype == "text/html":
            html.append(payload)

    if plain:
        return "\n".join(plain), "text/plain"
    if html:
        return html_to_text("\n".join(html)), "text/html"
    return "", "none"


def html_to_text(html):
    """Crude HTML -> text. Only used when no text/plain part exists."""
    html = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    html = re.sub(r"(?i)</(p|div|tr|li|h[1-6])>", "\n", html)
    html = re.sub(r"(?s)<[^>]+>", "", html)
    import html as _html
    html = _html.unescape(html)
    return re.sub(r"\n{3,}", "\n\n", html)


# --------------------------------------------------------------------------
# link cleaning
# --------------------------------------------------------------------------

SAFELINK = re.compile(
    r"https?://[^\s<>\"]*?safelinks\.protection\.outlook\.com/[^\s<>\"]*",
    re.I)


def unwrap_safelinks(text):
    """Replace an Outlook safelink with the URL it wraps."""
    def repl(m):
        url = m.group(0)
        inner = re.search(r"[?&]url=([^&]+)", url)
        if not inner:
            return url
        target = unquote(inner.group(1))
        # safelinked URLs are percent-encoded twice often enough to matter
        if "%3A%2F%2F" in target or "%2F" in target:
            target = unquote(target)
        return target
    return SAFELINK.sub(repl, text)


def norm_url(u):
    """Normalise a URL for label/target comparison."""
    u = u.strip().lower()
    u = re.sub(r"^(https?:)?//", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.rstrip("/")


# a URL immediately followed by its own angle-bracketed target: the common
# `https://x<https://x>` duplication Outlook produces
URL_LINK = re.compile(
    r"(?<![\w/])((?:https?://|www\.)[^\s<>]+)<(https?://[^>\s]+)>")
# a prose label followed by its target. Confined to one line: allowing the
# label to cross newlines lets it swallow whole preceding paragraphs.
LABEL_LINK = re.compile(r"([^\s<>][^<>\n]{0,200}?)<(https?://[^>\s]+)>")
MAILTO = re.compile(r"<mailto:[^>]+>")
BARE_ANGLE_URL = re.compile(r"(?<![\w>])<(https?://[^>\s]+)>")
CID = re.compile(r"\[cid:([^\]@]+)(@[^\]]*)?\]")
CID_ONLY = re.compile(r"^\[cid:[^\]]+\]$")


def collapse_links(text):
    """
    Outlook plain-text emits `Label<target>`. Keep whichever form carries
    information:
      - label and target are the same URL  -> keep the label alone
      - label is prose                     -> `Label -- target`
    Drop `<mailto:...>` entirely; the address is already in the label.
    """
    text = MAILTO.sub("", text)
    # normalise cid markers first so a marker can be recognised as a label
    text = CID.sub(lambda m: "[cid:%s]" % m.group(1), text)

    def repl(m):
        label, target = m.group(1), m.group(2)
        if norm_url(label) == norm_url(target):
            return label
        if not label.strip():
            return target
        if CID_ONLY.match(label.strip()):
            return label
        return "%s — %s" % (label.rstrip(), target)

    text = URL_LINK.sub(repl, text)
    text = LABEL_LINK.sub(repl, text)
    text = BARE_ANGLE_URL.sub(lambda m: m.group(1), text)
    return text


def tidy(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("​", "").replace("\xa0", " ")
    text = unwrap_safelinks(text)
    text = collapse_links(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip() + "\n"


# --------------------------------------------------------------------------
# attachments
# --------------------------------------------------------------------------

def image_size(path):
    """(width, height) for png/jpeg/gif without pulling in Pillow."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(32)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                w, h = struct.unpack(">II", head[16:24])
                return int(w), int(h)
            if head[:6] in (b"GIF87a", b"GIF89a"):
                w, h = struct.unpack("<HH", head[6:10])
                return int(w), int(h)
            if head[:2] == b"\xff\xd8":
                fh.seek(2)
                while True:
                    b = fh.read(1)
                    while b and b != b"\xff":
                        b = fh.read(1)
                    marker = fh.read(1)
                    while marker == b"\xff":
                        marker = fh.read(1)
                    if not marker:
                        break
                    if marker[0] in (0xD8, 0xD9) or 0xD0 <= marker[0] <= 0xD7:
                        continue
                    seg = fh.read(2)
                    if len(seg) < 2:
                        break
                    length = struct.unpack(">H", seg)[0]
                    if 0xC0 <= marker[0] <= 0xCF and marker[0] not in (0xC4, 0xC8, 0xCC):
                        data = fh.read(5)
                        h, w = struct.unpack(">HH", data[1:5])
                        return int(w), int(h)
                    fh.seek(length - 2, 1)
    except Exception:
        pass
    return None, None


def save_attachments(msg, workdir, prefix="", used=None):
    """
    Write every attachment into <workdir>/images and return an inventory.

    `prefix` is prepended to each saved filename, and `used` lets a caller share
    one name-collision set across several messages. Stage 0 needs both: a
    conversation export holds many messages that each call their inline figure
    image001.png, and without a per-message prefix they would overwrite one
    another. Stage 1 passes neither, so its behaviour is unchanged.
    """
    img_dir = os.path.join(workdir, "images")
    os.makedirs(img_dir, exist_ok=True)
    items = []
    if used is None:
        used = set()

    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        ctype = part.get_content_type()
        disp = (part.get_content_disposition() or "").lower()
        if ctype in ("text/plain", "text/html") and disp != "attachment":
            continue

        data = part.get_payload(decode=True)
        if not data:
            continue

        cid = (part.get("Content-ID") or "").strip().strip("<>")
        name = part.get_filename() or (cid.split("@")[0] if cid else None)
        if not name:
            ext = {"image/jpeg": ".jpg", "image/png": ".png",
                   "image/gif": ".gif"}.get(ctype, ".bin")
            name = "part%02d%s" % (len(items) + 1, ext)
        name = prefix + re.sub(r"[^\w.\-]", "_", os.path.basename(name))

        stem, ext = os.path.splitext(name)
        n = 1
        while name.lower() in used:
            n += 1
            name = "%s_%d%s" % (stem, n, ext)
        used.add(name.lower())

        out = os.path.join(img_dir, name)
        with open(out, "wb") as fh:
            fh.write(data)

        w, h = image_size(out) if ctype.startswith("image/") else (None, None)
        items.append({
            "filename": name,
            "cid": cid.split("@")[0] if cid else None,
            "content_type": ctype,
            "bytes": len(data),
            "width": w,
            "height": h,
            "inline": disp == "inline" or bool(cid),
            "likely_decoration": ctype.startswith("image/") and len(data) < 6000,
        })
    return items


# --------------------------------------------------------------------------

def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__.strip())
    src, workdir = sys.argv[1], sys.argv[2]
    if not os.path.isfile(src):
        sys.exit("no such file: %s" % src)
    os.makedirs(workdir, exist_ok=True)

    msg = load_message(src)
    body, body_source = pick_body(msg)
    text = tidy(body)

    thread_path = os.path.join(workdir, "thread.txt")
    with open(thread_path, "w", encoding="utf-8") as fh:
        fh.write(text)

    attachments = save_attachments(msg, workdir)

    manifest = {
        "source": os.path.abspath(src),
        "suggested_output": os.path.splitext(os.path.abspath(src))[0] + ".docx",
        "body_source": body_source,
        "headers": {k: str(msg.get(k) or "") for k in
                    ("From", "To", "Cc", "Subject", "Date")},
        "thread_chars": len(text),
        "attachments": attachments,
        "warnings": [],
    }
    if body_source == "html":
        manifest["warnings"].append(
            "No text/plain part; body recovered from HTML and may be rough.")
    if body_source == "none":
        manifest["warnings"].append("No readable body part found.")
    if any(p.get_content_type() in ("multipart/encrypted", "application/pkcs7-mime")
           for p in msg.walk()):
        manifest["warnings"].append("Message is encrypted or signed (S/MIME).")

    with open(os.path.join(workdir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)

    print("thread.txt   %d chars" % len(text))
    print("images/      %d file(s)" % len(attachments))
    for a in attachments:
        print("  %-28s %7d B  %s%s" % (
            a["filename"], a["bytes"],
            ("%sx%s" % (a["width"], a["height"])) if a["width"] else "-",
            "  (likely decoration)" if a["likely_decoration"] else ""))
    for w in manifest["warnings"]:
        print("WARNING: " + w)
    print("workdir      %s" % os.path.abspath(workdir))


if __name__ == "__main__":
    main()
