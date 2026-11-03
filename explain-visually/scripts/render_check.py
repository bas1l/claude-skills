#!/usr/bin/env python3
"""Check a page in headless Chrome, with no window and no browser tab on screen.

    python render_check.py page.html --work <folder> [--test clicks.js]

Writes to <folder>: one PNG per tab (or page.png), and cold_read.txt with all the
text the page shows, for the cold read. Exit 1 on a script error, overlapping or
clipped SVG labels, sideways scrolling, or a failed click test.

clicks.js runs in a temporary copy after load and calls check("what", condition);
labelProblems() returns the label problems of whatever state it has clicked to.
"""
import argparse
import html
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
WIDTH = 1000

PROBE = r"""
window.__checks=[];
function check(name,ok){window.__checks.push({name:name,ok:!!ok});}
/* Call labelProblems() in a click test to check a state the page reaches only by clicking. */
function labelProblems(){
  var problems=[];
  document.querySelectorAll("svg").forEach(function(svg){
    var box=svg.getBoundingClientRect();
    if(box.width===0)return;
    var items=[...svg.querySelectorAll("text")].map(function(t){return {t:t.textContent,r:t.getBoundingClientRect()};});
    items.forEach(function(a,i){
      if(a.r.left<box.left-1||a.r.right>box.right+1||a.r.top<box.top-1||a.r.bottom>box.bottom+1)
        problems.push("clipped label: "+a.t);
      items.slice(i+1).forEach(function(b){
        var w=Math.min(a.r.right,b.r.right)-Math.max(a.r.left,b.r.left);
        var h=Math.min(a.r.bottom,b.r.bottom)-Math.max(a.r.top,b.r.top);
        if(w>1&&h>3)problems.push("overlapping labels: "+a.t+" | "+b.t);
      });
    });
  });
  return problems;
}
window.addEventListener("load",function(){
  var problems=[];
  var main=document.querySelector("main");
  var text=main?main.innerText:"";
  var labels=[...document.querySelectorAll("svg")].filter(function(v){return v.getBoundingClientRect().width>0;})
    .flatMap(function(v){return [...v.querySelectorAll("text")].map(function(t){return t.textContent;});});
  problems=problems.concat(labelProblems());
  __TEST__
  var root=document.documentElement;
  if(root.scrollWidth>root.clientWidth)problems.push("page scrolls sideways");
  var err=document.getElementById("page-error");
  if(err)problems.push(err.textContent);
  var out=document.createElement("pre");
  out.id="__probe";out.style.display="none";
  out.textContent=JSON.stringify({problems:problems,checks:window.__checks,height:root.scrollHeight,text:text,labels:labels});
  document.body.appendChild(out);
});
"""


def chrome(args, profile, timeout=120):
    done = subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
         f"--user-data-dir={profile}", "--virtual-time-budget=4000", *args],
        capture_output=True, text=True, encoding="utf8", errors="replace",
        timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if done.returncode != 0:
        raise RuntimeError(f"Chrome exit {done.returncode}: {done.stderr[-800:]}")
    return done.stdout


def probe(copy, tab, profile):
    url = copy.resolve().as_uri() + (f"#{tab}" if tab else "")
    dom = chrome([f"--window-size={WIDTH},900", "--dump-dom", url], profile)
    found = re.search(r'<pre id="__probe"[^>]*>(.*?)</pre>', dom, re.S)
    if not found:
        raise RuntimeError(f"the probe did not report for tab {tab}; the page script may not have run")
    return json.loads(html.unescape(found.group(1)))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("page", type=Path)
    p.add_argument("--work", required=True, type=Path)
    p.add_argument("--test", type=Path)
    a = p.parse_args()
    if not Path(CHROME).exists():
        raise FileNotFoundError(CHROME)
    source = a.page.read_text(encoding="utf8")
    if source.count("</body>") != 1:
        raise ValueError("expected exactly one </body> in the page")
    a.work.mkdir(parents=True, exist_ok=True)
    test = a.test.read_text(encoding="utf8") if a.test else ""
    tabs = re.findall(r'<button data-t="(\w+)"', source) or [None]

    profile = Path(tempfile.mkdtemp(prefix="explain_chrome_"))
    failed = False
    cold = []
    try:
        for tab in tabs:
            copy = a.work / "_probe_copy.html"
            # The click test runs once, on the page as it first opens.
            script = PROBE.replace("__TEST__", test if tab == tabs[0] else "")
            copy.write_text(source.replace("</body>", f"<script>{script}</script></body>"), encoding="utf8")
            report = probe(copy, tab, profile)
            copy.unlink()

            name = tab or "page"
            png = (a.work / f"{name}.png").resolve()
            png.unlink(missing_ok=True)
            url = a.page.resolve().as_uri() + (f"#{tab}" if tab else "")
            chrome([f"--window-size={WIDTH},{report['height'] + 120}", f"--screenshot={png}", url], profile)
            if not png.exists() or png.stat().st_size == 0:
                raise RuntimeError(f"no screenshot written for {name}")

            bad = report["problems"] + [f"click test failed: {c['name']}" for c in report["checks"] if not c["ok"]]
            passed = sum(c["ok"] for c in report["checks"])
            print(f"{png}  height {report['height']}px  clicks passed {passed}/{len(report['checks'])}")
            for line in bad:
                print(f"  PROBLEM {line}")
            failed = failed or bool(bad)
            cold.append(f"=== {name} ===\n{report['text']}\n\nLabels inside figures:\n" + "\n".join(report["labels"]))
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    cold_path = (a.work / "cold_read.txt").resolve()
    cold_path.write_text("\n\n".join(cold), encoding="utf8")
    print(cold_path)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
