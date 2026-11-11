"""SessionStart hook: keep the cache-tax plugin's keepwarm at 12 hours from the last message.

A cache-tax plugin update installs a new version folder with the stock code. This
re-applies two patches to every installed version:

1. DEFAULT_WINDOW_MS = 12 hours (stock: 6 hours).
2. Rolling window: when a main-session turn completes and keepwarm is on (a window
   is running, or `/keepwarm always` is set), the window restarts at 12 hours from
   that moment. `/keepwarm off` still stops it for good. Subagent turns do not count.

Idempotent and silent when nothing needs changing. Raises loudly when the plugin
code no longer has the expected shape. A fix lands in the plugin's next session
start, because the plugin has already loaded by the time it runs.
"""
import re
import sys
from pathlib import Path

HOURS = 12
ROOT = Path.home() / ".claude" / "plugins" / "cache"
WINDOW_PATTERN = re.compile(r"(const DEFAULT_WINDOW_MS = )(\d+)( \* 60 \* 60 \* 1000)")

ROLLING_MARKER = "keepwarm-12h patch: rolling window"
ROLLING_ANCHOR = "    s.coldWritePending = false\n    await arm($, s)\n    return r\n"
ROLLING_PATCH = (
    "    s.coldWritePending = false\n"
    f"    // {ROLLING_MARKER}: each main-session message restarts the window from now.\n"
    "    if (s.deadline || s.always) {\n"
    "      s.deadline = now + DEFAULT_WINDOW_MS\n"
    "      s.stopped = null\n"
    "      await $.store.set(deadlineKey(s), s.deadline)\n"
    "    }\n"
    "    await arm($, s)\n"
    "    return r\n"
)


def patch_file(f: Path) -> list[str]:
    text = f.read_text(encoding="utf-8")
    changes = []

    m = WINDOW_PATTERN.search(text)
    if m is None:
        raise RuntimeError(f"keepwarm-12h: DEFAULT_WINDOW_MS not found in {f}; plugin changed shape")
    if int(m.group(2)) != HOURS:
        text = WINDOW_PATTERN.sub(rf"\g<1>{HOURS}\g<3>", text, count=1)
        changes.append(f"window {HOURS}h")

    if ROLLING_MARKER not in text:
        count = text.count(ROLLING_ANCHOR)
        if count != 1:
            raise RuntimeError(
                f"keepwarm-12h: turn.complete anchor found {count} times in {f} (expected 1); plugin changed shape"
            )
        text = text.replace(ROLLING_ANCHOR, ROLLING_PATCH, 1)
        changes.append("rolling window")

    if changes:
        f.write_text(text, encoding="utf-8")
    return changes


def main() -> int:
    files = list(ROOT.glob("*/cache-tax/*/hooks/register.ts"))
    if not files:
        raise RuntimeError(f"keepwarm-12h: no cache-tax register.ts under {ROOT}")
    report = []
    for f in files:
        changes = patch_file(f)
        if changes:
            report.append(f"{f.parent.parent.name} ({', '.join(changes)})")
    if report:
        print(f"keepwarm-12h: patched cache-tax {'; '.join(report)}; applies from the next session")
    return 0


if __name__ == "__main__":
    sys.exit(main())
