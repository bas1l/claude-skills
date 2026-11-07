"""PreToolUse hook (matcher "Agent"): assign a model to a subagent call that has none.

Rules only, no model call (a Haiku call via `claude -p` measured ~6.8 s per spawn).
- call already has `model`                 -> untouched
- subagent_type has own frontmatter model  -> untouched
- otherwise tier: opus / haiku / sonnet (default) from subagent_type, description, prompt head.
Output: hookSpecificOutput.updatedInput = full input + model, permissionDecision "allow".
Every decision, and every error, is appended to ~/.claude/hooks/subagent-model.jsonl.
On any failure: message to stderr, exit 1 (non-blocking), so CLAUDE_CODE_SUBAGENT_MODEL applies.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

import os
LOG = Path(os.environ.get("SUBAGENT_MODEL_LOG") or Path.home() / ".claude" / "hooks" / "subagent-model.jsonl")
PROMPT_HEAD_CHARS = 300

# subagent_type (lowercase) -> (model, rule name)
TYPE_RULES = {
    "explore": ("haiku", "type:Explore"),
    "web-fetch": ("haiku", "type:web-fetch"),
    "plan": ("opus", "type:Plan"),
}
OPUS_RE = re.compile(
    r"\b(review\w*|audit\w*|critique\w*|challeng\w*|mediat\w*|adjudicat\w*|statistic\w*|estimator\w*|"
    r"architect\w*|design\w*|root[- ]cause|debug\w*|diagnos\w*)\b", re.I)
# haiku applies only when nothing in the description signals real work (WORK_RE)
HAIKU_RE = re.compile(
    r"\b(commit\w*|push\w*|git|format\w*|lint\w*|link[- ]?check\w*|check links?|lookup|look up|locate|"
    r"find|search\w*|grep|list|read[- ]only|rename\w*)\b", re.I)
WORK_RE = re.compile(
    r"\b(implement\w*|build\w*|rebuild\w*|write|writ\w+|fix\w*|refactor\w*|run|runs|create\w*|generate\w*|"
    r"add|update\w*|migrat\w*|port\w*|test\w*|analy[sz]\w*|document\w*)\b", re.I)


def log(entry: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {"ts": dt.datetime.now().astimezone().isoformat(timespec="seconds"), **entry}
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def frontmatter_model(subagent_type: str, cwd: str) -> str | None:
    """`model:` of a custom agent whose frontmatter name equals subagent_type, if any."""
    dirs = [Path.home() / ".claude" / "agents"]
    if cwd:
        dirs.append(Path(cwd) / ".claude" / "agents")
    for d in dirs:
        if not d.is_dir():
            continue
        for md in d.glob("*.md"):
            text = md.read_text(encoding="utf-8")
            m = re.match(r"---\s*\n(.*?)\n---", text, re.S)
            if not m:
                continue
            fm = m.group(1)
            name = re.search(r"^name:\s*(.+?)\s*$", fm, re.M)
            if not name or name.group(1).strip("'\"") != subagent_type:
                continue
            model = re.search(r"^model:\s*(.+?)\s*$", fm, re.M)
            if model and model.group(1).strip("'\"") not in ("", "inherit"):
                return model.group(1).strip("'\"")
    return None


def classify(subagent_type: str, description: str, prompt: str) -> tuple[str, str]:
    t = TYPE_RULES.get(subagent_type.lower())
    if t:
        return t
    o = OPUS_RE.search(f"{subagent_type} {description}")
    if o:
        return "opus", "opus-keyword:" + o.group(0).lower()
    if OPUS_RE.search(prompt[:PROMPT_HEAD_CHARS]):
        # opus word only in the prompt head: ambiguous, do not pay for Opus
        return "sonnet", "ambiguous:opus-word-in-prompt-only"
    h = HAIKU_RE.search(description)
    if h and not WORK_RE.search(description):
        return "haiku", "haiku-keyword:" + h.group(0).lower()
    return "sonnet", "default"


def main() -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
        tool_input = data["tool_input"]
        if data.get("tool_name") not in ("Agent", "Task"):
            raise ValueError(f"unexpected tool_name {data.get('tool_name')!r}")
        if not isinstance(tool_input, dict):
            raise ValueError("tool_input is not an object")
        description = str(tool_input.get("description", ""))
        prompt = str(tool_input.get("prompt", ""))
        subagent_type = str(tool_input.get("subagent_type") or "general-purpose")
        if not description and not prompt:
            raise ValueError("neither description nor prompt present")
        if tool_input.get("model"):
            log({"action": "kept", "reason": "call has model", "model": tool_input["model"],
                 "subagent_type": subagent_type, "description": description})
            return 0
        fm = frontmatter_model(subagent_type, str(data.get("cwd", "")))
        if fm:
            log({"action": "kept", "reason": "agent frontmatter model", "model": fm,
                 "subagent_type": subagent_type, "description": description})
            return 0
        model, rule = classify(subagent_type, description, prompt)
        log({"action": "assigned", "model": model, "rule": rule, "subagent_type": subagent_type,
             "description": description, "session_id": data.get("session_id")})
    except Exception as e:  # fail loudly, non-blocking: env-var default applies
        msg = f"subagent-model hook ERROR: {type(e).__name__}: {e}; env default CLAUDE_CODE_SUBAGENT_MODEL applies"
        print(msg, file=sys.stderr)
        try:
            log({"action": "error", "error": msg, "stdin_head": raw[:300]})
        except Exception as le:
            print(f"subagent-model hook: log write failed: {le}", file=sys.stderr)
        return 1
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "permissionDecisionReason": f"subagent-model hook: {model} ({rule})",
        "updatedInput": {**tool_input, "model": model},
    }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
