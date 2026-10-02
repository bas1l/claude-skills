"""End-to-end tests for session_colocate.py (Windows, Python >= 3.12).

    python hooks/session-colocate/tests/run_tests.py

Runs the hook as a subprocess against fake temp/projects trees. Fixtures and the
hook log (via SESSION_COLOCATE_LOG) go to a fresh dir under %TEMP%, never into
the repo; it is deleted when every case passes and kept for inspection otherwise.
Exit code 0 = all passed, 1 = at least one failure.
"""
import json, os, shutil, subprocess, sys, tempfile, _winapi

HOOK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "session_colocate.py")
PY = sys.executable
WORK = tempfile.mkdtemp(prefix="session-colocate-tests-")
BASE = os.path.join(WORK, "trees")
LOG = os.path.join(WORK, "test.log")


def rm(p):
    if os.path.isjunction(p) or os.path.islink(p):
        os.rmdir(p)
    elif os.path.exists(p):
        # remove junctions inside first so rmtree never follows them
        for root, dirs, _ in os.walk(p):
            for d in dirs:
                q = os.path.join(root, d)
                if os.path.isjunction(q):
                    os.rmdir(q)
        shutil.rmtree(p)


def setup(case, sid="sess-0001"):
    root = os.path.join(BASE, case)
    rm(root)
    temp_proj = os.path.join(root, "temp", "claude", "f--proj")
    proj = os.path.join(root, "home", ".claude", "projects", "F--proj")
    os.makedirs(temp_proj)
    os.makedirs(proj)
    open(os.path.join(proj, sid + ".jsonl"), "w").close()
    return dict(sid=sid, temp=os.path.join(temp_proj, sid), target=os.path.join(proj, sid),
                payload={"session_id": sid, "source": "startup", "hook_event_name": "SessionStart",
                         "transcript_path": os.path.join(proj, sid + ".jsonl"),
                         "scratchpad_dir": os.path.join(temp_proj, sid, "scratchpad")})


def run(payload):
    env = dict(os.environ, SESSION_COLOCATE_LOG=LOG)
    r = subprocess.run([PY, HOOK], input=json.dumps(payload), capture_output=True, text=True, env=env)
    return r.returncode, r.stderr.strip()


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(text)


def read(p):
    with open(p) as f:
        return f.read()


results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))


# 1 fresh: no temp dir
c = setup("fresh")
rc, err = run(c["payload"])
check("fresh: exit 0", rc == 0, err)
check("fresh: junction -> target", os.path.isjunction(c["temp"]) and os.path.samefile(c["temp"], c["target"]))
write(os.path.join(c["temp"], "scratchpad", "x.txt"), "via-junction")
check("fresh: write-through", read(os.path.join(c["target"], "scratchpad", "x.txt")) == "via-junction")

# 2 temp dir with scratchpad + tasks files, no target
c = setup("move")
write(os.path.join(c["temp"], "scratchpad", "a.txt"), "A")
write(os.path.join(c["temp"], "scratchpad", "sub", "b.txt"), "B")
write(os.path.join(c["temp"], "tasks", "t1.output"), "T")
rc, err = run(c["payload"])
check("move: exit 0", rc == 0, err)
check("move: junction", os.path.isjunction(c["temp"]))
check("move: files in target", read(os.path.join(c["target"], "scratchpad", "sub", "b.txt")) == "B"
      and read(os.path.join(c["target"], "tasks", "t1.output")) == "T")
check("move: readable via junction", read(os.path.join(c["temp"], "scratchpad", "a.txt")) == "A")
write(os.path.join(c["target"], "tasks", "new.txt"), "N")
check("move: target write visible via junction", read(os.path.join(c["temp"], "tasks", "new.txt")) == "N")
check("move: no staging left", not os.path.lexists(c["temp"] + ".colocate-staging"))

# 3 merge with existing subagents/tool-results, plus overlapping dir name
c = setup("merge")
write(os.path.join(c["target"], "subagents", "agent-1.jsonl"), "S")
write(os.path.join(c["target"], "tool-results", "r1.txt"), "R")
write(os.path.join(c["target"], "scratchpad", "pre-existing.txt"), "P")
write(os.path.join(c["temp"], "scratchpad", "a.txt"), "A")
write(os.path.join(c["temp"], "tasks", "t.txt"), "T")
rc, err = run(c["payload"])
check("merge: exit 0", rc == 0, err)
check("merge: all present", all(os.path.isfile(os.path.join(c["target"], *p)) for p in [
    ("subagents", "agent-1.jsonl"), ("tool-results", "r1.txt"), ("scratchpad", "pre-existing.txt"),
    ("scratchpad", "a.txt"), ("tasks", "t.txt")]))
check("merge: junction", os.path.isjunction(c["temp"]) and os.path.samefile(c["temp"], c["target"]))

# 4 rerun idempotency (resume) on merge case
before = sorted(os.listdir(c["target"]))
p = dict(c["payload"], source="resume")
rc, err = run(p)
check("resume: exit 0 noop", rc == 0, err)
check("resume: unchanged", sorted(os.listdir(c["target"])) == before and os.path.isjunction(c["temp"]))
rc, err = run(dict(c["payload"], source="compact"))
check("compact rerun: exit 0", rc == 0, err)

# 5 file collision: must fail, no data lost, nothing moved
c = setup("collision")
write(os.path.join(c["target"], "scratchpad", "a.txt"), "TARGET")
write(os.path.join(c["temp"], "scratchpad", "a.txt"), "TEMP")
write(os.path.join(c["temp"], "scratchpad", "other.txt"), "O")
rc, err = run(c["payload"])
check("collision: exit 2", rc == 2, err)
check("collision: message names file", "a.txt" in err, err)
check("collision: both copies intact, nothing moved",
      read(os.path.join(c["target"], "scratchpad", "a.txt")) == "TARGET"
      and read(os.path.join(c["temp"], "scratchpad", "a.txt")) == "TEMP"
      and os.path.isfile(os.path.join(c["temp"], "scratchpad", "other.txt"))
      and not os.path.exists(os.path.join(c["target"], "scratchpad", "other.txt"))
      and not os.path.isjunction(c["temp"]))

# 5b dir-vs-file type collision
c = setup("typecollision")
write(os.path.join(c["target"], "tasks"), "i am a file")
write(os.path.join(c["temp"], "tasks", "t.txt"), "T")
rc, err = run(c["payload"])
check("type collision: exit 2, intact", rc == 2 and os.path.isfile(os.path.join(c["temp"], "tasks", "t.txt")), err)

# 6 junction pointing elsewhere
c = setup("elsewhere")
other = os.path.join(BASE, "elsewhere", "other-target")
os.makedirs(other)
write(os.path.join(other, "keep.txt"), "K")
_winapi.CreateJunction(other, c["temp"])
rc, err = run(c["payload"])
check("elsewhere: exit 2", rc == 2, err)
check("elsewhere: untouched", os.path.isjunction(c["temp"]) and os.path.samefile(c["temp"], other)
      and read(os.path.join(other, "keep.txt")) == "K" and not os.path.exists(c["target"]))

# 7 open handle: cwd of a child process inside temp dir blocks rename
c = setup("openhandle")
write(os.path.join(c["temp"], "scratchpad", "a.txt"), "A")
holder = subprocess.Popen([PY, "-c", "import time; time.sleep(30)"], cwd=os.path.join(c["temp"], "scratchpad"))
try:
    rc, err = run(c["payload"])
finally:
    holder.kill(); holder.wait()
check("open handle: exit 2, nothing moved", rc == 2 and read(os.path.join(c["temp"], "scratchpad", "a.txt")) == "A"
      and not os.path.isjunction(c["temp"]), err)

# 8 missing scratchpad_dir -> documented skip
c = setup("noscratch")
p = dict(c["payload"]); del p["scratchpad_dir"]
rc, err = run(p)
check("no scratchpad_dir: exit 0 skip", rc == 0 and not os.path.exists(c["temp"]), err)

# 9 inconsistent input (scratchpad parent not named after session) -> fail
c = setup("badinput")
p = dict(c["payload"], session_id="other-id")
rc, err = run(p)
check("bad input: exit 2", rc == 2, err)

for name, ok, detail in results:
    print(("PASS " if ok else "FAIL ") + name + (("  | " + detail[:300]) if (detail and not ok) or name.endswith("exit 2") else ""))
passed = sum(ok for _, ok, _ in results)
print(f"{passed}/{len(results)} passed")
if passed == len(results):
    rm(WORK)
else:
    print(f"fixtures and log kept in {WORK}")
sys.exit(0 if passed == len(results) else 1)
