#!/usr/bin/env python3
"""The PlasBench window's help, cohort details and console details.

- the page script parses (node --check, when node is installed)
- every page has help: PAGE_HELP covers every view, and each has what / steps
- the Add your own tool guide: its worked example (MOB-recon) is a valid manifest, and is the one the form loads
- cohort details (plasbench/cohort_info.py): every shipped cohort is summarised, the lock is joined in and checked,
  download estimate, metagenomic sheets; bad names are refused; the /api/cohorts/info route
- the terminal's command box is a textarea; a multi-line command is commented out line by line in a run script
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def main():
    tmp = Path(tempfile.mkdtemp())
    os.environ["PLASBENCH_UI_HOME"] = str(tmp / "ui")
    page = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    script = page[page.index("<script>") + 8:page.rindex("</script>")]

    print("page script")
    node = shutil.which("node")
    if node:
        js = tmp / "page.js"
        js.write_text(script, encoding="utf-8")
        r = subprocess.run([node, "--check", str(js)], capture_output=True, text=True)
        check("the page script parses", r.returncode == 0, r.stderr[-400:])
    else:
        print("  skip  node not installed: page script not syntax-checked")

    print("help on every page")
    views = json.loads(re.search(r"const VIEWS = (\[[^\]]*\]);", script).group(1))
    m = re.search(r"const PAGE_HELP = (\{.*?\});\nfunction curView", script, re.S)
    help_ = json.loads(m.group(1)) if m else {}
    check("every page has help", set(views) <= set(help_), set(views) - set(help_))
    check("each help says what the page is for and how to use it",
          all(h.get("what") and h.get("steps") and h.get("title") for h in help_.values()))
    check("Help in the top bar, on each page header, and F1", 'id="helpbtn"' in page and "data-pghelp" in script
          and 'e.key === "F1"' in script)

    print("Add your own tool guide")
    check("guide dialog and its button", 'id="uthelp"' in page and 'id="ut_help"' in page and 'id="uh_load"' in page)
    ex = json.loads(re.search(r"const UT_EXAMPLE = (\".*?\");\n", script).group(1))
    d = tmp / "tools" / "my_mob_recon"
    d.mkdir(parents=True)
    (d / "plasbench-tool.ini").write_text(ex, encoding="utf-8")
    env = dict(os.environ, PLASBENCH_TOOLS_PATH=str(tmp / "tools"))
    r = subprocess.run([sys.executable, str(ROOT / "python" / "user_tools.py"), "validate"], capture_output=True, text=True,
                       env=env, cwd=ROOT)
    check("the worked example is a valid manifest", r.returncode == 0 and "ok  my_mob_recon" in r.stdout, r.stdout + r.stderr)
    shown = re.search(r'<pre class="hman">(.*?)</pre>', page, re.S).group(1)
    shown = shown.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    check("the guide shows exactly the manifest the button loads", shown.strip() == ex.strip())

    print("cohort details")
    from plasbench import cohort_info
    names = [p.stem for p in sorted((ROOT / "cohorts").glob("*.tsv"))]
    infos = {n: cohort_info.info(ROOT, n) for n in names}
    check("every shipped cohort is summarised", all(i["summary"] for i in infos.values()), [n for n, i in infos.items() if not i["summary"]])
    v1 = infos["public-v1"]
    check("public-v1: 10 isolates, lock present and matching", v1["n"] == 10 and v1["lock"]["present"] and v1["lock"]["matches_sheet"])
    check("public-v1: organisms, tiers, plasmids counted", v1["summary"]["species"] >= 1 and v1["summary"]["truth_quality_tier"]
          and v1["summary"]["plasmids_total"] and v1["summary"]["plasmids_recorded"] == 10)
    check("lock joined in: country, reference sequencing, read size",
          all(k in v1["columns"] for k in ("country", "reference_sequencing", "read_gbases")) and v1["rows"][0]["read_gbases"])
    check("download estimate from the lock", v1["summary"]["download_estimate_gb"] and v1["summary"]["download_estimate_gb"] > 0)
    check("README section is the description", "public-v1" in v1["readme"])
    meta = [i for i in infos.values() if i["kind"] == "metagenomic"]
    check("metagenomic sheets: communities and regimes", meta and all("communities" in i["summary"] for i in meta))
    for bad in ("../README", "a/b", ""):
        try:
            cohort_info.info(ROOT, bad)
            check(f"refuses the name {bad!r}", False)
        except (ValueError, FileNotFoundError):
            check(f"refuses the name {bad!r}", True)
    # a stale lock is reported
    cdir = tmp / "proj" / "cohorts"
    cdir.mkdir(parents=True)
    shutil.copy(ROOT / "cohorts" / "public-v1.tsv", cdir / "x.tsv")
    shutil.copy(ROOT / "cohorts" / "public-v1.lock.json", cdir / "x.lock.json")
    with open(cdir / "x.tsv", "a", encoding="utf-8") as h:
        h.write("# edited\n")
    check("an edited sheet shows its lock as out of date", cohort_info.info(tmp / "proj", "x")["lock"]["matches_sheet"] is False)

    print("server route")
    import importlib
    webui = importlib.import_module("plasbench.webui")
    webui.UI_HOME = tmp / "ui"
    project = webui.Project(ROOT)
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.make_handler(project, webui.Jobs(project)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    def get(path):
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                     headers={"Host": f"127.0.0.1:{port}", "X-PlasBench-Token": webui.TOKEN})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    code, body = get("/api/cohorts/info?name=public-v2")
    check("/api/cohorts/info returns the summary and rows", code == 200 and body["n"] == len(body["rows"]) and body["summary"]["isolates"])
    code, _ = get("/api/cohorts/info?name=..%2FREADME")
    check("/api/cohorts/info refuses a path", code == 400)
    code, body = get("/api/git/files?repo=" + urllib.request.quote(str(ROOT)))
    check("/api/git/files lists a checkout's tracked files", code == 200 and ("plasbench/webui.py" in body.get("files", [])
          or not (ROOT / ".git").exists()), body if code != 200 else body["total"])
    code, body = get("/api/git/status")
    check("version control defaults to the working directory (where git init lives), never the program", code == 200
          and body["choices"][0]["kind"] == "workspace" and all(c["kind"] in ("workspace", "study", "program") for c in body["choices"])
          and Path(body["repo"]).resolve() != ROOT.resolve() and body["is_workspace"], body.get("repo"))
    code, _ = get("/api/cohorts/info?name=nope")
    check("/api/cohorts/info: unknown cohort is a 404", code == 404)
    server.shutdown()

    print("source control drawer")
    check("panel on every page: Panel button, Ctrl+Shift+G, six Git sections", 'id="gdrawer"' in page and 'id="gdbtn"' in page
          and 'e.key === "G"' in script and all(f'gdSec("gd_{k}"' in script for k in
                                               ("changes", "commit", "branches", "remote", "files", "history")))
    check("drawer collapses and remembers it", "pb_gd_open" in script and "gd-open" in page)
    check("the page makes room for the drawer on wide screens", "body.gd-open .shell{margin-right:var(--gdw)}" in page)
    from plasbench import gitops
    if gitops.find_git():
        repo = tmp / "repo"
        repo.mkdir()
        gitops.run(repo, "init", "-q")
        (repo / "a.txt").write_text("a", encoding="utf-8")
        (repo / "b.txt").write_text("b", encoding="utf-8")
        gitops.run(repo, "add", "a.txt")
        r = gitops.files(repo)
        check("tracked files are listed (git ls-files), untracked ones are not", r["files"] == ["a.txt"] and r["total"] == 1, r)
        check("the file list is capped", gitops.files(repo, limit=0)["truncated"] is True)
    else:
        print("  skip  git not installed")

    print("side panel, main tabs, git history")
    check("side panel tabs in order: Studies (default), Jobs, Git",
          page.index('data-pt="studies"') < page.index('data-pt="jobs"') < page.index('data-pt="git"')
          and 'const PT = {active: "studies"}' in script)
    check("Studies is a folder tree; files open as tabs", 'class="tree"' in page and "function treeFill" in script
          and 'openDoc({kind: "file"' in script)
    from plasbench import webui as w, studies as stu
    os.environ["PLASBENCH_WORKSPACE"] = str(tmp / "wsx")
    sd = stu.create(ROOT, "treecheck", "")
    (sd / "results").mkdir(exist_ok=True)
    (sd / "results" / "x.tsv").write_text("a\tb\n1\t2\n", encoding="utf-8")
    (sd / "results" / "x.bin").write_bytes(b"\0\1")
    r = w.read_study_file(ROOT, str(sd / "results" / "x.tsv"))
    check("a study's table is read for its tab", r["kind"] == "table" and r["text"].startswith("a\tb"), r)
    for bad, exc in ((str(ROOT / "README.md"), PermissionError), (str(sd / "results" / "x.bin"), ValueError)):
        try:
            w.read_study_file(ROOT, bad)
            check(f"refused: {Path(bad).name}", False)
        except exc:
            check(f"refused: {Path(bad).name}", True)
    os.environ.pop("PLASBENCH_WORKSPACE", None)
    check("side panel is as wide as the navigation rail", ":root{--gdw:248px}" in page and "--railw:248px" in page)
    check("main-area tabs: the page plus documents, closable", 'id="mtabs"' in page and 'id="v_doc"' in page
          and "function openDoc" in script and "function mtClose" in script and "auxclick" in script)
    check("diffs and commits open as tabs", 'openDoc({kind: "diff"' in script and 'openDoc({kind: "commit"' in script)
    check("every page opens as its own tab; the window starts with Overview", "function pageTab" in script
          and 'window.mtOnRoute = v => { MT.active = pageTab(v)' in script and '{kind: "page", view: "home", id: "page|home"}' in script)
    check("reports open as a tab, with Open in browser", 'openDoc({kind: "report"' in script and 'class="repframe"' in script
          and "Open in browser" in script and 'a[href^="/view/"]' in script)
    check("a closed last tab never leaves an empty window", "never an empty window" in script)
    check("history has a colour code and hover text", "const HLEGEND" in script and "function commitTip" in script
          and ".hdot.local" in page and ".hdot.pushed" in page)
    if gitops.find_git():
        g = tmp / "hist"
        g.mkdir()
        gitops.run(g, "init", "-q", "-b", "main")
        gitops.run(g, "config", "user.name", "T")
        gitops.run(g, "config", "user.email", "t@example.org")
        (g / "a.tsv").write_bytes(b"x\n")
        gitops.run(g, "add", "a.tsv")
        gitops.run(g, "commit", "-q", "-m", "first run")
        (g / "a.tsv").write_bytes(b"x\ny\n")
        log = gitops.log(g, 5)
        check("log: head, not pushed (no remote), refs, parents, ISO date", log and log[0]["head"] and not log[0]["pushed"]
              and log[0]["has_remote"] is False and any("main" in r for r in log[0]["refs"]) and log[0]["date"][:4].isdigit(), log[:1])
        d = gitops.commit_detail(g, log[0]["hash"])
        check("commit detail: files and patch", d["files"] == [{"status": "A", "path": "a.tsv", "from": ""}] and "+x" in d["patch"], d["files"])
        fs = gitops.file_state(g, "a.tsv")
        check("file state: changed, not staged", fs["changed"] and fs["unstaged"] and not fs["staged"], fs)
        try:
            gitops.commit_detail(g, "not-a-hash")
            check("commit detail refuses a bad id", False)
        except ValueError:
            check("commit detail refuses a bad id", True)

    print("optional git install and terminal shells")
    from plasbench import install_git, terminal as term
    plan = install_git.plan()
    check("install-git always has a plan", plan["action"] in ("none", "run", "manual") and plan["say"])
    if plan["action"] == "run":
        check("install-git runs a known installer", any(x in plan["argv"][0].lower() for x in ("winget", "conda", "mamba", "micromamba", "xcode-select")))
    shells = term.available_shells()
    check("the terminal offers at least one shell", bool(shells))
    check("WSL distributions are offered by name", all(k.startswith("wsl:") or k in ("posix", "powershell") for k in shells), shells)
    check("Git Bash is never the WSL launcher", not (term.git_for_windows_bash() or "").lower().endswith(("system32\\bash.exe", "system32/bash.exe")))

    print("console")
    check("the terminal command box is an expandable textarea", re.search(r'<textarea id="tcmd" rows="1"', page) is not None
          and "resize:vertical" in page)
    from plasbench import sessionlog
    log = sessionlog.SessionLog(tmp / "s.jsonl")
    log.event("terminal", shell="posix", cwd=str(ROOT), command="echo a\nrm -rf x", exit=1, seconds=0.1)
    sc = log.script(ROOT)
    lines = sc.splitlines()
    check("a failed multi-line command is commented out on every line",
          "# echo a" in lines and "# rm -rf x" in lines and not any(l.strip().startswith("rm -rf x") for l in lines), lines[-6:])

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all help/cohort/console checks passed'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
