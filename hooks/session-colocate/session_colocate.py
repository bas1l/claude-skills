#!/usr/bin/env python3
"""SessionStart hook: co-locate a session's temp data with its transcript folder.

Claude Code keeps per-session temp data (scratchpad\\, tasks\\, ...) at
    %TEMP%\\claude\\<project>\\<session-id>\\
and the transcript at
    ~\\.claude\\projects\\<project>\\<session-id>.jsonl
with a sibling folder ~\\.claude\\projects\\<project>\\<session-id>\\.

This hook moves the temp session dir's contents into that sibling folder and
replaces the temp session dir with a directory junction pointing there, so
everything the session writes to temp lands next to its transcript.

Paths come only from the hook input (scratchpad_dir, transcript_path,
session_id); nothing is derived from the project-name string.

Fail-fast: any unexpected state -> message on stderr, exit 2 (SessionStart
cannot block; Claude Code shows the stderr to the user as a hook error notice
and the session proceeds). Every run appends one line to session_colocate.log
next to this script. Stdlib only.

Order of operations for an existing real temp dir (chosen so that a failure
never leaves the session without its data at the expected path):
  1. preflight: walk the temp dir and the target and refuse on any collision
     (a file, link or type mismatch that already exists in the target) before
     touching anything;
  2. os.rename(temp_dir, temp_dir + ".colocate-staging") -- a single atomic
     rename; if an open handle prevents it, nothing has changed;
  3. create the junction temp_dir -> target immediately;
  4. move every staged entry into the target (merging directories);
  5. rmdir the now-empty staging dir.
"""
import _winapi
import datetime
import json
import os
import sys
import traceback

HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
# Test override only: lets the test harness log elsewhere. Unset in production.
LOG_PATH = os.environ.get("SESSION_COLOCATE_LOG") or os.path.join(HOOK_DIR, "session_colocate.log")
STAGING_SUFFIX = ".colocate-staging"
EXIT_ERROR = 2  # SessionStart: non-blocking, stderr shown to the user


class ColocateError(Exception):
    pass


def log(session_id, source, action, result):
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    line = f"{ts}\tsession={session_id}\tsource={source}\taction={action}\tresult={result}\n"
    with open(LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(line)


def norm(p):
    return os.path.normcase(os.path.normpath(os.path.abspath(p)))


def same_path(a, b):
    return norm(os.path.realpath(a)) == norm(os.path.realpath(b))


def is_link(p):
    return os.path.islink(p) or os.path.isjunction(p)


def is_real_dir(p):
    return os.path.isdir(p) and not is_link(p)


def resolve_paths(data):
    for key in ("session_id", "transcript_path"):
        if not data.get(key):
            raise ColocateError(f"hook input missing required field '{key}'")
    sid = data["session_id"]
    scratch = os.path.normpath(data["scratchpad_dir"])
    transcript = os.path.normpath(data["transcript_path"])

    if os.path.basename(scratch).lower() != "scratchpad":
        raise ColocateError(f"scratchpad_dir does not end in 'scratchpad': {scratch}")
    temp_dir = os.path.dirname(scratch)
    if os.path.basename(temp_dir) != sid:
        raise ColocateError(f"parent of scratchpad_dir is not named after session_id {sid}: {temp_dir}")

    if not transcript.lower().endswith(".jsonl"):
        raise ColocateError(f"transcript_path does not end in .jsonl: {transcript}")
    target = transcript[: -len(".jsonl")]
    if os.path.basename(target) != sid:
        raise ColocateError(f"transcript_path is not named after session_id {sid}: {transcript}")
    if norm(temp_dir) == norm(target):
        raise ColocateError(f"temp session dir and target are the same path: {target}")
    return temp_dir, target


def find_collisions(src, dst, out):
    """Record every entry of src that cannot be moved/merged into dst."""
    for name in os.listdir(src):
        s, d = os.path.join(src, name), os.path.join(dst, name)
        if not os.path.lexists(d):
            continue
        if is_real_dir(s) and is_real_dir(d):
            find_collisions(s, d, out)
        else:
            out.append(d)


def move_tree(src, dst, moved):
    """Move every entry of src into dst (dst exists), merging real dirs."""
    for name in os.listdir(src):
        s, d = os.path.join(src, name), os.path.join(dst, name)
        if not os.path.lexists(d):
            os.rename(s, d)
            moved.append(d)
        elif is_real_dir(s) and is_real_dir(d):
            move_tree(s, d, moved)
            os.rmdir(s)  # empty now: every child was moved or the call raised
        else:
            raise ColocateError(f"collision appeared after preflight, refusing to overwrite: {d}")


def make_junction(link, target):
    _winapi.CreateJunction(target, link)
    if not (os.path.isjunction(link) and same_path(link, target)):
        raise ColocateError(f"junction {link} was created but does not resolve to {target}")


def colocate(temp_dir, target):
    """Return a short description of the action taken. Raises on any failure."""
    staging = temp_dir + STAGING_SUFFIX
    if os.path.lexists(staging):
        raise ColocateError(
            f"leftover staging dir from an earlier failed run exists: {staging}. "
            f"Inspect it and move its contents into {target} by hand.")

    if is_link(temp_dir):
        if os.path.isjunction(temp_dir) and same_path(temp_dir, target):
            if not os.path.isdir(target):
                raise ColocateError(f"junction {temp_dir} points to missing target {target}")
            return "noop-already-junctioned"
        raise ColocateError(
            f"temp session dir {temp_dir} is a link to {os.path.realpath(temp_dir)}, "
            f"not to the expected target {target}")

    if os.path.lexists(target) and not is_real_dir(target):
        raise ColocateError(f"target exists but is not a real directory: {target}")

    if not os.path.lexists(temp_dir):
        os.makedirs(target, exist_ok=True)
        os.makedirs(os.path.dirname(temp_dir), exist_ok=True)
        make_junction(temp_dir, target)
        return "created-junction"

    if not is_real_dir(temp_dir):
        raise ColocateError(f"temp session path exists but is not a directory: {temp_dir}")

    if os.path.isdir(target):
        collisions = []
        find_collisions(temp_dir, target, collisions)
        if collisions:
            raise ColocateError(
                "refusing to overwrite existing entries in target (nothing was moved): "
                + "; ".join(collisions))
    else:
        os.makedirs(target)

    try:
        os.rename(temp_dir, staging)
    except OSError as exc:
        raise ColocateError(
            f"could not rename {temp_dir} aside (open handle?): {exc}. Nothing was moved.") from exc

    try:
        make_junction(temp_dir, target)
    except Exception as exc:
        # Put the data back where Claude Code expects it before failing.
        if os.path.lexists(temp_dir) and not is_link(temp_dir):
            raise ColocateError(f"junction creation failed and {temp_dir} reappeared; data is in {staging}: {exc}") from exc
        if is_link(temp_dir):
            os.rmdir(temp_dir)  # removes the link only, never the target's contents
        os.rename(staging, temp_dir)
        raise ColocateError(f"junction creation failed; original temp dir restored, nothing moved: {exc}") from exc

    moved = []
    try:
        move_tree(staging, target, moved)
        os.rmdir(staging)
    except Exception as exc:
        remaining = []
        for root, dirs, files in os.walk(staging):
            remaining += [os.path.join(root, f) for f in files]
        raise ColocateError(
            f"partial move: junction {temp_dir} -> {target} is in place; moved {len(moved)} "
            f"entries ({moved}); still in {staging}: {remaining or 'empty dirs only'}. Error: {exc}") from exc
    return f"moved-{len(moved)}-entries-and-junctioned"


def main():
    sid, source = "?", "?"
    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
        sid = data.get("session_id", "?")
        source = data.get("source", "?")
        if not data.get("scratchpad_dir"):
            # Documented-expected case, not a fallback: Claude Code omits
            # scratchpad_dir when the session has no scratchpad (API key auth,
            # Bedrock/Vertex/Foundry, enableArtifact=false, temp unavailable).
            log(sid, source, "skip-no-scratchpad_dir", "ok")
            return 0
        temp_dir, target = resolve_paths(data)
        action = colocate(temp_dir, target)
        log(sid, source, action, f"ok temp={temp_dir} target={target}")
        return 0
    except Exception as exc:
        msg = f"session-colocate FAILED ({type(exc).__name__}): {exc}"
        sys.stderr.write(msg + "\n")
        if not isinstance(exc, ColocateError):
            sys.stderr.write(traceback.format_exc())
        try:
            log(sid, source, "error", msg.replace("\n", " | "))
        except Exception as log_exc:
            sys.stderr.write(f"session-colocate: also failed to write log {LOG_PATH}: {log_exc}\n")
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
