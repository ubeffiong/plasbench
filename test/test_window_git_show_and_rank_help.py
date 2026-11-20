#!/usr/bin/env python3
"""Window wiring for audit AU-039 (git/show) and AU-041 (rank help, exit-0-with-failures wording).

  - AU-039: every git route the backend serves under /api/git/ is called by the window; git/show is now the "Copy patch" button of the commit page
    (it was the one route with no control);
  - AU-041: the Runs page explains what a rank is (task, track, headline metric, ties, ranked isolates) and the leaders carry a tooltip;
    a run that exits 0 with failed tool runs says so in the toast and the state chip (no plain "done"), with an explanation of what the report covers.
Static checks of ui.html and webui.py, plus a syntax check of the page's script when node is available.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
html = open(os.path.join(ROOT, "plasbench", "data", "ui.html"), encoding="utf-8").read()
web = open(os.path.join(ROOT, "plasbench", "webui.py"), encoding="utf-8").read()
OK = True


def check(label, good, detail=""):
    global OK
    print(f"  {label}: {'PASS' if good else 'FAIL'}" + ("" if good else f"  [{detail}]"))
    OK &= bool(good)


git_part = web[web.index('if what == "log":'):]
git_part = git_part[:git_part.index("no such API")]
routes = sorted(set(re.findall(r'if what == "(\w+)":', git_part)))
used = {r for r in routes if f"git/{r}" in html or f'op: "{r}"' in html}
check("the git GET routes are found", {"show", "diff", "log", "commit"} <= set(routes), str(routes))
check("git/show is used by the window", "git/show?" in html and 'id="cm_patch"' in html)
check("the Copy patch button copies through the one clipboard helper", "await copyText(r.text" in html and html.count("navigator.clipboard.writeText") == 1)
unused = [r for r in routes if r not in used and r not in ("info", "scan", "heavy", "gitignore", "checkignore", "file", "files", "branches")]
check("no served git GET route is left without a control", not unused, str(unused))

sys.path.insert(0, ROOT)
from plasbench import ui_help  # noqa: E402  (UI cleanup: the rank explanation is the (?) beside "Results folders", text in ui_help.PAGE["rank_help"])
_rk = " ".join([ui_help.PAGE["rank_help"]["summary"]] + ui_help.PAGE["rank_help"]["bullets"])
check("the Runs page explains a rank in a (?) tooltip", 'data-tipid="rank_help" id="rankhelp"' in html and all(x in _rk for x in ("task", "track", "tied", "CPRR", "Leaderboard")))
check("the leaders carry a rank tooltip", 'class="leader" title="Rank 1' in html)
check("exit 0 with failed tool runs is worded, not 'done'", "WARN_EXPLAIN" in html and "exited normally, exit 0" in html and "finished, but some tool runs failed" in html)
check("the toast uses the derived state", "const shown = j.display_state || j.state" in html)

node = shutil.which("node")
if node:
    scripts = re.findall(r"<script(?![^>]*src)[^>]*>(.*?)</script>", html, re.S)
    body = max(scripts, key=len)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "ui_script.js")
        open(path, "w", encoding="utf-8").write(body)
        done = subprocess.run([node, "--check", path], capture_output=True, text=True)
        check("the page script still parses", done.returncode == 0, done.stderr[-300:])
else:
    print("  SKIP: node not available; script syntax not checked")

print("ALL WINDOW GIT SHOW AND RANK HELP TESTS PASSED" if OK else "WINDOW GIT SHOW AND RANK HELP TESTS FAILED")
sys.exit(0 if OK else 1)
