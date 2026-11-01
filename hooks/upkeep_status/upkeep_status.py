#!/usr/bin/env python3
"""SessionStart hook: one warning line when an upkeep run left a failure marker.

    upkeep_status.py [config.json]

Silent when the marker does not exist. The line is a systemMessage, shown to the user and not
sent to the model. It is built from checked fields only, never from a marker's free text, because
that text can hold error output from a pass.

A marker or config that cannot be read reports itself as broken, since failures may then be going
unseen. Always exits 0 without reading stdin, so it can never hold up or block a session. The
marker's format is in the header of upkeep/Invoke-Upkeep.ps1.
"""
import json, os, re, sys

MARKER_FILE = "failure-marker.json"
SCHEMA_VERSION = 1
DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "upkeep", "config.json")
WORD = re.compile(r"^[a-z_]+$")
STAMP = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})")


def say(line):
    print(json.dumps({"systemMessage": line}))


def marker_path(config_path):
    with open(config_path, encoding="utf-8") as handle:
        return os.path.join(os.path.expanduser(json.load(handle)["paths"]["data_dir"]), MARKER_FILE)


def read_problems(path):
    """Returns 'weekly failed, last 2026-11-04 02:00' per pass and kind. Raises on a broken marker."""
    with open(path, encoding="utf-8") as handle:
        marker = json.load(handle)
    if marker["schema_version"] != SCHEMA_VERSION:
        raise ValueError("schema version")
    if not isinstance(marker["entries"], list) or not marker["entries"]:
        raise ValueError("no entries")
    latest = {}
    counts = {}
    for entry in marker["entries"]:
        name, kind = entry["pass"], entry["kind"]
        stamp = STAMP.match(entry["at"])
        if not (WORD.match(name) and WORD.match(kind) and stamp):
            raise ValueError("malformed entry")
        key = (name, kind)
        counts[key] = counts.get(key, 0) + 1
        latest[key] = max(latest.get(key, ""), "%s %s" % stamp.groups())
    return [
        "%s %s%s, last %s" % (name, kind.replace("_", " "), " x%d" % counts[(name, kind)] if counts[(name, kind)] > 1 else "", latest[(name, kind)])
        for name, kind in latest
    ]


def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CONFIG
    try:
        path = marker_path(config_path)
    except Exception as error:
        say("Upkeep warning: status hook is broken (%s), so failures may go unseen: %s" % (type(error).__name__, config_path))
        return
    try:
        if not os.path.exists(path):
            return
        problems = read_problems(path)
    except Exception as error:
        say("Upkeep warning: failure marker is broken (%s), so failures may go unseen: %s" % (type(error).__name__, path))
        return
    say("Upkeep warning: %s. Details: %s" % ("; ".join(problems), path))


if __name__ == "__main__":
    main()
    sys.exit(0)
