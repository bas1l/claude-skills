#!/usr/bin/env python3
"""SessionStart hook: one warning line when an upkeep run left a failure marker, or when the
scheduled tasks seem to have stopped.

    upkeep_status.py [config.json]

Silent when the marker does not exist and a run is recent. A run is too old past
status.warn_after_hours_without_run in the config, counted only where upkeep is installed (its local
settings file exists) and has run at least once (logs/runs.jsonl holds a line of a scheduled pass),
so other machines stay silent. The line is a systemMessage, shown to the user and not
sent to the model. It is built from checked fields only, never from a marker's free text, because
that text can hold error output from a pass.

A marker, run log or config that cannot be read reports itself as broken, since failures may then be going
unseen. Always exits 0 without reading stdin, so it can never hold up or block a session. The
marker's format is in the header of upkeep/Invoke-Upkeep.ps1.
"""
import datetime, json, os, re, sys

MARKER_FILE = "failure-marker.json"
SCHEMA_VERSION = 1
DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "upkeep", "config.json")
WORD = re.compile(r"^[a-z_]+$")
STAMP = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})")
RUN_ID = re.compile(r"^\d{8}-\d{6}$")
RUNS_LOG = os.path.join("logs", "runs.jsonl")
SCHEDULED_PASSES = ("daily", "weekly", "monthly")


def say(line):
    print(json.dumps({"systemMessage": line}))


def read_config(config_path):
    with open(config_path, encoding="utf-8") as handle:
        config = json.load(handle)
    return (
        os.path.expanduser(config["paths"]["data_dir"]),
        os.path.expanduser(config["paths"]["local_settings"]),
        config["status"]["warn_after_hours_without_run"],
    )


def stale_run_problem(data_dir, local_settings, max_hours):
    """'no run for 60 hours, ...' if the last scheduled run is too old. Raises on a broken log."""
    path = os.path.join(data_dir, RUNS_LOG)
    if not os.path.exists(local_settings) or not os.path.exists(path):
        return None
    latest = None
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            run = json.loads(line)
            if run["pass"] not in SCHEDULED_PASSES:
                continue
            if not RUN_ID.match(run["run_id"]):
                raise ValueError("malformed run id")
            started = datetime.datetime.strptime(run["run_id"], "%Y%m%d-%H%M%S")
            latest = started if latest is None or started > latest else latest
    if latest is None:
        return None
    hours = int((datetime.datetime.now() - latest).total_seconds() // 3600)
    if hours < max_hours:
        return None
    return "no run for %d hours, last %s, so the scheduled tasks may have stopped" % (hours, latest.strftime("%Y-%m-%d %H:%M"))


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
        data_dir, local_settings, max_hours = read_config(config_path)
    except Exception as error:
        say("Upkeep warning: status hook is broken (%s), so failures may go unseen: %s" % (type(error).__name__, config_path))
        return
    path = os.path.join(data_dir, MARKER_FILE)
    problems = []
    try:
        if os.path.exists(path):
            problems.extend(read_problems(path))
    except Exception as error:
        problems.append("failure marker is broken (%s), so failures may go unseen" % type(error).__name__)
    try:
        stale = stale_run_problem(data_dir, local_settings, max_hours)
        if stale:
            problems.append(stale)
    except Exception as error:
        problems.append("run log is broken (%s), so stopped tasks may go unseen" % type(error).__name__)
    if problems:
        say("Upkeep warning: %s. Details: %s" % ("; ".join(problems), path if os.path.exists(path) else os.path.join(data_dir, RUNS_LOG)))


if __name__ == "__main__":
    main()
    sys.exit(0)
