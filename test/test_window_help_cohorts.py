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
    code, _ = get("/api/cohorts/info?name=nope")
    check("/api/cohorts/info: unknown cohort is a 404", code == 404)
    server.shutdown()

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
