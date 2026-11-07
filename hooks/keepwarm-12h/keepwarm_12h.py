"""SessionStart hook: keep the cache-tax plugin's keepwarm default at 12 hours.

A cache-tax plugin update installs a new version folder with the stock 6-hour
DEFAULT_WINDOW_MS. This re-applies the 12-hour value to every installed version.
Idempotent and silent when nothing needs changing. A fix lands in the plugin's
next session start, because the plugin has already loaded by the time it runs.
"""
import re
import sys
from pathlib import Path

HOURS = 12
ROOT = Path.home() / ".claude" / "plugins" / "cache"
PATTERN = re.compile(r"(const DEFAULT_WINDOW_MS = )(\d+)( \* 60 \* 60 \* 1000)")


def main() -> int:
    patched = []
    for f in ROOT.glob("*/cache-tax/*/hooks/register.ts"):
        text = f.read_text(encoding="utf-8")
        m = PATTERN.search(text)
        if m is None:
            print(f"keepwarm-12h: DEFAULT_WINDOW_MS not found in {f}; plugin changed shape", file=sys.stderr)
            continue
        if int(m.group(2)) == HOURS:
            continue
        f.write_text(PATTERN.sub(rf"\g<1>{HOURS}\g<3>", text, count=1), encoding="utf-8")
        patched.append(f.parent.parent.name)
    if patched:
        print(f"keepwarm-12h: set default window to {HOURS}h in cache-tax {', '.join(patched)}; applies from the next session")
    return 0


if __name__ == "__main__":
    sys.exit(main())
