#!/usr/bin/env python3
"""Fill assets/page_template.html and write one self-contained page.

    python build_page.py --title "..." --body body.txt --js figures.js [--data data.json] --out page.html

Fragments must not end in .html: a Write of a .html file opens a browser tab.
Stops with an error when the page breaks a rule SKILL.md makes checkable.
"""
import argparse
import html
import json
import re
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "page_template.html"
PLACEHOLDER = re.compile(r"__(TITLE|BODY|DATA|FIGURES_JS)__")
SITUATION_LABELS = (
    "What we are trying to find out",
    "What data it rests on",
    "Already decided",
    "Why this comes up now",
)
EXTERNAL = re.compile(
    r"<link\b|@import|<script[^>]+\bsrc\s*="
    r"|<(?:img|iframe|video|audio|source)[^>]+\bsrc\s*=\s*[\"']?(?:https?:)?//"
    r"|url\(\s*[\"']?(?:https?:)?//",
    re.I,
)
FIGURE = re.compile(r'class="fig"|<svg\b')
LABEL = re.compile(r'class="tag (?:real|made)"')


def split_blocks(body, opener):
    """Text from each match of opener up to the next match, or the end."""
    starts = [m.start() for m in re.finditer(opener, body)]
    return [body[a:b] for a, b in zip(starts, starts[1:] + [len(body)])]


def check_body(body):
    problems = []
    if not re.match(r'\s*<section class="situation">', body):
        problems.append('the body must open with <section class="situation">')
    for label in SITUATION_LABELS:
        if f"<dt>{label}</dt>" not in body:
            problems.append(f"the situation lacks <dt>{label}</dt>")
    if not re.search(r'</section>\s*<div class="answer">', body):
        problems.append('<div class="answer"> must directly follow the situation')

    figures, labels = len(FIGURE.findall(body)), len(LABEL.findall(body))
    if figures == 0:
        problems.append("the page has no figure")
    if figures > labels:
        problems.append(f"{figures} figures but only {labels} real/made-up labels")

    for block in split_blocks(body, r"<section>"):
        title = re.search(r"<h2>(.*?)</h2>", block)
        name = title.group(1) if title else block[:60]
        if not FIGURE.search(block):
            problems.append(f"section without a figure: {name}")
        if 'class="point"' not in block:
            problems.append(f"section without a point line: {name}")

    tab_ids = re.findall(r'<div class="tab" id="(\w+)"', body)
    button_ids = re.findall(r'data-t="(\w+)"', body)
    if sorted(tab_ids) != sorted(button_ids):
        problems.append(f"tab buttons {button_ids} do not match tabs {tab_ids}")

    asks = body.count('class="ask"')
    in_tabs = 0
    for block in split_blocks(body, r'<div class="tab" id="'):
        if 'class="ask"' not in block:
            continue
        in_tabs += block.count('class="ask"')
        name = re.search(r'id="(\w+)"', block).group(1)
        for needed, what in (
            ('class="context"', "context restated for a reader of this tab alone"),
            ('<tr class="rec">', "a recommended option row"),
            ('class="unknown"', "a statement of what is not known"),
            ('class="next"', "a line on what happens next"),
        ):
            if needed not in block:
                problems.append(f"question tab {name} lacks {what} ({needed})")
    if asks != in_tabs:
        problems.append("every question must sit in its own tab")
    if asks and 'class="reply"' not in body:
        problems.append('questions need a <div class="reply"> offering a one-line answer')
    return problems


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--title", required=True)
    p.add_argument("--body", required=True, type=Path)
    p.add_argument("--js", required=True, type=Path)
    p.add_argument("--data", type=Path)
    p.add_argument("--out", required=True, type=Path)
    a = p.parse_args()

    body = a.body.read_text(encoding="utf8")
    js = a.js.read_text(encoding="utf8")
    if "</script" in js.lower():
        raise ValueError("figures JS must not contain </script")
    data = json.loads(a.data.read_text(encoding="utf8")) if a.data else None
    data_js = json.dumps(data, ensure_ascii=False, allow_nan=False).replace("</", "<\\/")

    problems = check_body(body)
    if problems:
        raise ValueError("page breaks the skill's rules:\n- " + "\n- ".join(problems))

    template = TEMPLATE.read_text(encoding="utf8")
    fill = {"TITLE": html.escape(a.title), "BODY": body, "DATA": data_js, "FIGURES_JS": js}
    # One pass, so text inserted from a fragment is never treated as a placeholder.
    page = PLACEHOLDER.sub(lambda m: fill[m.group(1)], template)

    external = EXTERNAL.search(page)
    if external:
        raise ValueError(f"page loads an external resource: {external.group(0)}")

    a.out.parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", encoding="utf8", newline="\n") as f:
        f.write(page)
    print(f"{a.out.resolve()}  {len(page)} characters")


if __name__ == "__main__":
    main()
