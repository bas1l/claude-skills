#!/usr/bin/env python3
"""Compress a Claude Code session transcript into a digest a model can read.

A working session's transcript runs to megabytes, most of it tool results and
file dumps. Reading one into a conversation is the thing that makes summarising
a session impossible. This throws away the bulk and keeps the three things a
documentation update actually needs:

  * what the user asked for, in their own words, turn by turn;
  * what the assistant said between tool calls, which is where decisions and
    corrections get stated;
  * a ledger of which files were written and which commands were run.

Run with:  python extract_session.py [options]

Defaults to the current session in the current project, both discovered from
the environment. Writes to stdout unless --out is given.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

SYSTEM_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
WHITESPACE = re.compile(r"\s+")

WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
SHELL_TOOLS = {"Bash", "PowerShell"}
# Scratchpad writes are working notes, not repository changes.
SCRATCH = re.compile(r"[\\/][Tt]emp[\\/]claude[\\/]")


def encode_project_dir(path: str) -> str:
    """Claude Code's folder name for a working directory.

    Every character outside [A-Za-z0-9-] becomes a single dash, with no
    collapsing of runs, so `F:\\Personal\\1_projets` becomes
    `F--Personal-1-projets`. The mapping is lossy for non-ASCII and cannot be
    reversed; read the real path out of the transcript's `cwd` field instead.
    """
    return re.sub(r"[^A-Za-z0-9-]", "-", path)


def projects_root() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home()) / ".claude" / "projects"


def text_of(content) -> str:
    """`message.content` is a bare string or a list of typed blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def tidy(text: str, limit: int) -> str:
    text = SYSTEM_REMINDER.sub("", text)
    text = WHITESPACE.sub(" ", text).strip()
    if limit and len(text) > limit:
        text = text[:limit].rstrip() + " […]"
    return text


def records(path: Path):
    """Yield parsed records, skipping anything unparseable.

    The transcript is append-only and may be mid-flush, so the last line can be
    a partial object. A single bad line must not lose the whole session.
    """
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue


def harvest(path: Path, user_limit: int, assistant_limit: int, label: str = ""):
    turns: list[str] = []
    files: Counter[str] = Counter()
    commands: Counter[str] = Counter()
    meta = {"cwd": "", "branch": "", "first": "", "last": "", "human": 0, "assistant": 0}

    for record in records(path):
        if record.get("isMeta"):
            continue
        kind = record.get("type")
        if kind not in ("user", "assistant"):
            continue

        stamp = record.get("timestamp") or ""
        if stamp:
            meta["first"] = meta["first"] or stamp
            meta["last"] = stamp
        meta["cwd"] = meta["cwd"] or record.get("cwd", "")
        meta["branch"] = meta["branch"] or (record.get("gitBranch") or "")

        content = (record.get("message") or {}).get("content")

        if kind == "user":
            # Tool results, hook output and task notifications are all recorded
            # as type "user". Only a typed turn carries origin.kind == human.
            if (record.get("origin") or {}).get("kind") != "human":
                continue
            body = tidy(text_of(content), user_limit)
            if body:
                meta["human"] += 1
                turns.append(f"[{stamp[11:16]}] USER: {body}")
            continue

        meta["assistant"] += 1
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                name = block.get("name", "")
                params = block.get("input") or {}
                if name in WRITE_TOOLS:
                    target = str(params.get("file_path") or params.get("notebook_path") or "")
                    if target and not SCRATCH.search(target):
                        files[target] += 1
                elif name in SHELL_TOOLS:
                    what = str(params.get("description") or "").strip()
                    if what:
                        commands[what] += 1

        body = tidy(text_of(content), assistant_limit)
        if body:
            speaker = f"CLAUDE{label}"
            turns.append(f"[{stamp[11:16]}] {speaker}: {body}")

    return turns, files, commands, meta


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-id", default=os.environ.get("CLAUDE_CODE_SESSION_ID", ""))
    parser.add_argument("--project-dir", default=os.getcwd(),
                        help="working directory whose transcripts to read (default: cwd)")
    parser.add_argument("--transcript", default="", help="a .jsonl path, bypassing discovery")
    parser.add_argument("--out", default="", help="write here instead of stdout")
    parser.add_argument("--max-user", type=int, default=1500)
    parser.add_argument("--max-assistant", type=int, default=700)
    parser.add_argument("--subagents", action="store_true",
                        help="also digest delegated work, which the main transcript never contains")
    args = parser.parse_args()

    if args.transcript:
        transcript = Path(args.transcript)
    else:
        folder = projects_root() / encode_project_dir(args.project_dir)
        if not folder.is_dir():
            print(f"no transcript folder for {args.project_dir}\n  looked in {folder}", file=sys.stderr)
            return 1
        if args.session_id:
            transcript = folder / f"{args.session_id}.jsonl"
        else:
            # Newest by modification time. Wrong when two sessions share a
            # working directory, which is why the session id is preferred.
            candidates = sorted(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not candidates:
                print(f"no .jsonl transcripts in {folder}", file=sys.stderr)
                return 1
            transcript = candidates[0]

    if not transcript.is_file():
        print(f"transcript not found: {transcript}", file=sys.stderr)
        return 1

    turns, files, commands, meta = harvest(transcript, args.max_user, args.max_assistant)

    if args.subagents:
        sub_dir = transcript.with_suffix("") / "subagents"
        for index, sub in enumerate(sorted(sub_dir.glob("*.jsonl")), start=1):
            sub_turns, sub_files, sub_commands, _ = harvest(sub, args.max_user, args.max_assistant, f"/sub{index}")
            files.update(sub_files)
            commands.update(sub_commands)
            # Only the tail: a subagent's opening is its brief, already in the
            # parent thread, and its conclusion is what the parent acted on.
            turns.extend(sub_turns[-6:])

    out: list[str] = []
    out.append("# Session digest")
    out.append("")
    out.append(f"- transcript: `{transcript}`")
    out.append(f"- working directory: `{meta['cwd']}`")
    if meta["branch"]:
        out.append(f"- git branch: `{meta['branch']}`")
    out.append(f"- span (UTC): {meta['first']} .. {meta['last']}")
    out.append(f"- turns: {meta['human']} from the user, {meta['assistant']} from the assistant")
    out.append("")

    out.append("## Files written")
    out.append("")
    if files:
        for path, count in files.most_common():
            out.append(f"- `{path}` ({count})")
    else:
        out.append("- none")
    out.append("")

    out.append("## Commands run")
    out.append("")
    if commands:
        for what, count in commands.most_common(40):
            suffix = f" (x{count})" if count > 1 else ""
            out.append(f"- {what}{suffix}")
    else:
        out.append("- none")
    out.append("")

    out.append("## Conversation")
    out.append("")
    out.extend(turns)
    body = "\n".join(out) + "\n"

    if args.out:
        Path(args.out).write_text(body, encoding="utf-8")
        print(f"wrote {args.out} ({len(body):,} chars, {len(turns)} turns)")
    else:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
