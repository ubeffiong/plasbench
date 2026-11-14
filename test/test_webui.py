#!/usr/bin/env python3
"""`plasbench ui` (plasbench/webui.py, plasbench/ui_schema.py, plasbench/data/ui.html), against a real server.

- every CLI command and option is in the window's schema, under a category, and the parser validates what it builds
- security: no token or a foreign Host header is refused; a cross-origin POST is refused; only plasbench runs
- settings are written to config/local.env without disturbing other lines, and removed to restore a default
- user-tool manifests are validated and saved from the window
- a job runs, its log streams, and it can be cancelled; a command the parser rejects never starts
- result folders are served read-only, and nothing outside them
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
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
    os.environ["PLASBENCH_LOCAL_SETTINGS"] = str(tmp / "local.env")
    os.environ["HOME"] = os.environ["USERPROFILE"] = str(tmp / "home")
    os.environ["PLASBENCH_TOOLS_PATH"] = str(tmp / "tools")
    (tmp / "home").mkdir()
    (tmp / "local.env").write_text("# mine\nexport KEEP_ME='yes'\nexport THREADS=2\n", encoding="utf-8")

    import importlib
    from plasbench import cli, ui_schema
    webui = importlib.import_module("plasbench.webui")
    webui.UI_HOME = tmp / "ui"

    print("schema")
    sch = ui_schema.schema()
    parser_names = set(cli.build_parser()._subparsers._group_actions[0].choices) - set(ui_schema.ALIASES)
    listed = {c for cat in sch["categories"] for c in cat["commands"]}
    check("every CLI command is in the window, each under one category", listed == parser_names and len(sch["commands"]) == len(parser_names),
          parser_names ^ listed)
    run = next(c for c in sch["commands"] if c["name"] == "run")
    check("run keeps its option groups", {"inputs and outputs", "resources and assembly", "tools"} <= {a["group"] for a in run["args"]})
    kinds = {a["dest"]: a["kind"] for a in run["args"]}
    check("option kinds: flag, int, choice, path, list", kinds["force_rerun_tools"] == "flag" and kinds["threads"] == "int"
          and kinds["assembler"] == "choice" and kinds["results_dir"] == "path" and kinds["user_tools"] == "list", kinds)
    tools_cmd = next(c for c in sch["commands"] if c["name"] == "tools")
    check("sub-commands are described (tools new/validate/...)", {"new", "validate", "add", "install"} <= {s["name"] for s in tools_cmd["subcommands"]})
    profile = next(a for a in next(c for c in sch["commands"] if c["name"] == "install-tools")["args"] if a["dest"] == "profile")
    check("a name containing 'file' is not mistaken for a path", profile["kind"] == "text")
    check("validate_argv accepts a valid command line", ui_schema.validate_argv(["run", "--threads", "4", "--tool", "x"])[0])
    ok, msg = ui_schema.validate_argv(["run", "--threads", "four"])
    check("validate_argv explains a rejected one", not ok and "invalid int value" in msg, msg)

    project = webui.Project(ROOT)
    jobs = webui.Jobs(project)
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.make_handler(project, jobs))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    token = webui.TOKEN

    def call(path, body=None, headers=None, tok=True):
        h = {"Host": f"127.0.0.1:{server.server_address[1]}"}
        if tok:
            h["X-PlasBench-Token"] = token
        h.update(headers or {})
        data = json.dumps(body).encode() if body is not None else None
        if data is not None:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(base + path, data=data, headers=h, method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return r.status, raw, dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    print("security")
    code, body, hdr = call(f"/?t={token}", tok=False)
    check("the page opens with the printed link and sets an HttpOnly, SameSite=Strict cookie",
          code == 200 and b"PlasBench" in body and "HttpOnly" in hdr.get("Set-Cookie", "") and "SameSite=Strict" in hdr.get("Set-Cookie", ""))
    check("the page carries a restrictive Content-Security-Policy", "frame-ancestors 'none'" in hdr.get("Content-Security-Policy", ""))
    check("without the token the page is refused", call("/", tok=False)[0] == 403)
    check("without the token the API is refused", call("/api/info", tok=False)[0] == 403)
    check("a wrong token is refused", call("/api/info", headers={"X-PlasBench-Token": "nope"})[0] == 403)
    check("a foreign Host header is refused (DNS rebinding)", call("/api/info", headers={"Host": "evil.example:80"})[0] == 403)
    check("a cross-origin POST is refused", call("/api/settings", {"changes": {"X": "1"}}, headers={"Origin": "http://evil.example"})[0] == 403)
    check("the health check needs nothing", call("/healthz", tok=False)[0] == 200)
    try:
        webui.serve(ROOT, host="0.0.0.0", open_browser=False)
        bound = True
    except SystemExit:
        bound = False
    check("the window refuses to listen beyond this computer", not bound)

    print("read-only API")
    code, body, _ = call("/api/info")
    info = json.loads(body)
    check("info reports version, root and resources", code == 200 and info["root"] == str(ROOT.resolve()) and info["cpus"] >= 1)
    env = json.loads(call("/api/env")[1])["checks"]
    check("environment checks have id, label, ok, fix", all({"id", "label", "ok", "fix", "group"} <= set(c) for c in env)
          and {"python", "bash", "conda", "minimap2"} <= {c["id"] for c in env})
    tools = json.loads(call("/api/tools")[1])["tools"]
    check("the tool catalogue lists the registry with task, track and install profile",
          any(t["tool"] == "mob_recon" and t["task"] == "reconstruction" and t["profile"] for t in tools))
    settings = json.loads(call("/api/settings")[1])["settings"]
    keys = {s["key"]: s for s in settings}
    check("settings come from config/config.sh with defaults and sections", "THREADS" in keys and "RESULTS_DIR" in keys
          and keys["THREADS"]["override"] == "2" and keys["RUN_PLATON"]["kind"] == "flag", keys.get("THREADS"))
    check("cohorts are listed", any(c["name"] == "public-v1" for c in json.loads(call("/api/cohorts")[1])["cohorts"]))
    docs = json.loads(call("/api/docs")[1])["docs"]
    check("guides are listed and readable", any(d["name"] == "docs/ADDING_TOOLS.md" for d in docs)
          and b"Adding your own tool" in call("/api/doc?name=docs/ADDING_TOOLS.md")[1])
    check("a file outside the guides is not readable", call("/api/doc?name=config/local.env")[0] == 404)
    listing = json.loads(call("/api/browse?path=" + urllib.request.quote(str(ROOT)))[1])
    check("the folder browser lists folders", any(e["name"] == "config" and e["dir"] for e in listing["entries"]))

    print("settings")
    code, body, _ = call("/api/settings", {"changes": {"THREADS": "6", "NCBI_EMAIL": "me@lab.org", "RESULTS_DIR": "/data/my results"}})
    text = (tmp / "local.env").read_text(encoding="utf-8")
    check("a change is written as export KEY=value, quoted when needed", code == 200 and "export THREADS=6" in text
          and "export NCBI_EMAIL=me@lab.org" in text and "export RESULTS_DIR='/data/my results'" in text, text)
    check("other lines and comments are kept", "# mine" in text and "export KEEP_ME='yes'" in text and text.count("THREADS") == 1)
    call("/api/settings", {"changes": {"THREADS": None}})
    check("clearing a value removes the line (back to the default)", "THREADS" not in (tmp / "local.env").read_text(encoding="utf-8"))
    check("a line break in a value is refused", call("/api/settings", {"changes": {"X_Y": "a\nexport EVIL=1"}})[0] == 400)
    check("a lower-case or odd key is refused", call("/api/settings", {"changes": {"path;rm": "1"}})[0] == 400)

    print("user tools")
    good = ("[tool]\nname = ui_tool\ntask = classification\nanalysis_track = short_read\n[install]\nmethod = none\n"
            "[run]\nmode = command\ncommand = echo {contigs}\nrequires = contigs\n[output]\nformat = contig_labels\npath = x.tsv\nlabel_column = 2\n")
    r = json.loads(call("/api/usertools/validate", {"text": good})[1])
    check("a valid manifest is reported valid, with its registry row", r["ok"] and r["row"]["binning_capable"] == "no", r)
    r = json.loads(call("/api/usertools/validate", {"text": good.replace("task = classification", "task = nope")})[1])
    check("problems come back as a list", not r["ok"] and any("task must be one of" in p for p in r["problems"]), r)
    r = json.loads(call("/api/usertools/validate", {"text": good.replace("ui_tool", "platon")})[1])
    check("a built-in name is refused", not r["ok"] and "built-in" in r["problems"][0], r)
    r = json.loads(call("/api/usertools/save", {"text": good})[1])
    saved = tmp / "home" / ".plasbench" / "tools" / "ui_tool" / "plasbench-tool.ini"
    check("saving writes ~/.plasbench/tools/<name>/plasbench-tool.ini", r["ok"] and saved.is_file(), r)
    r = json.loads(call("/api/usertools/save", {"text": good})[1])
    check("saving again asks before replacing", not r["ok"] and r.get("exists"), r)
    os.environ["PLASBENCH_TOOLS_PATH"] = str(saved.parent.parent)
    lst = json.loads(call("/api/usertools")[1])
    check("the saved tool is listed with the placeholders the form offers", any(t["name"] == "ui_tool" for t in lst["tools"])
          and "contigs" in lst["placeholders"], lst["tools"])

    print("jobs")
    code, body, _ = call("/api/jobs", {"argv": ["run", "--threads", "four"]})
    check("a command the parser rejects never starts", code == 400 and b"invalid int value" in body, body)
    code, body, _ = call("/api/jobs", {"argv": ["tools", "list"], "label": "list user tools"})
    job = json.loads(body)
    check("a valid command starts as a job", code == 200 and job["state"] == "running" and job["command"] == "plasbench tools list", job)
    for _ in range(240):   # up to 60 s: a cold Python start on a busy Windows machine is slow
        state = json.loads(call(f"/api/jobs/{job['id']}")[1])
        if state["state"] != "running":
            break
        time.sleep(0.25)
    check("it finishes, and its log holds the command and its output", state["state"] == "done" and state["exit"] == 0
          and state["log"].startswith("$ plasbench tools list") and "ui_tool" in state["log"], state)
    tail = json.loads(call(f"/api/jobs/{job['id']}?offset={state['offset']}")[1])
    check("the log is read incrementally from an offset", tail["log"] == "")
    code, body, _ = call("/api/jobs", {"argv": ["docs"], "env": {"BAD KEY": "1"}})
    check("job environment keys are checked", code == 400)
    code, body, _ = call("/api/jobs", {"argv": "rm -rf /"})
    check("argv must be a list (nothing goes through a shell)", code == 400)
    slow = json.loads(call("/api/jobs", {"argv": ["test"], "label": "slow"})[1])
    time.sleep(1.5)
    call(f"/api/jobs/{slow['id']}/cancel", {})
    for _ in range(240):
        st = json.loads(call(f"/api/jobs/{slow['id']}")[1])
        if st["state"] not in ("running", "cancelling"):
            break
        time.sleep(0.25)
    check("a running job can be cancelled", st["state"] == "cancelled", st["state"])
    print("answering a command's question from the console")
    call("/api/settings", {"changes": {"RESULTS_DIR": None}})   # the settings test pointed it at /data/my results
    ask = json.loads(call("/api/jobs", {"argv": ["check"], "label": "check without --yes"})[1])
    seen = ""
    for _ in range(480):   # 00_setup.sh lists what is missing, then asks before installing anything
        seen = json.loads(call(f"/api/jobs/{ask['id']}")[1])
        if "[y/N]" in seen["log"] or seen["state"] != "running":
            break
        time.sleep(0.25)
    if "[y/N]" in seen["log"]:
        check("the question is shown in the log (bash's read -p alone would hide it without a terminal)",
              seen["log"].rstrip().endswith("[y/N]"), seen["log"][-200:])
        code, body, _ = call(f"/api/jobs/{ask['id']}/input", {"text": "n"})
        check("an answer is accepted while the command runs", code == 200, body)
        for _ in range(240):
            done = json.loads(call(f"/api/jobs/{ask['id']}")[1])
            if done["state"] != "running":
                break
            time.sleep(0.25)
        check("the command reads the answer and acts on it (n: nothing installed)",
              done["state"] == "failed" and "[you] n" in done["log"] and "Skipped" in done["log"], done["log"][-400:])
        check("an answer to a finished command is refused", call(f"/api/jobs/{ask['id']}/input", {"text": "y"})[0] == 400)
    else:
        print(f"  skip  `plasbench check` asked no question here (state {seen['state']}): ...{seen['log'][-300:]!r}")
    check("an answer must be a single line", call(f"/api/jobs/{ask['id']}/input", {"text": "y\nrm -rf /"})[0] == 400)
    order = [j["id"] for j in json.loads(call("/api/jobs")[1])["jobs"]]
    check("jobs are listed newest first", order.index(slow["id"]) < order.index(job["id"]), order)
    check("the job history survives a restart of the window", job["id"] in webui.Jobs(project).jobs)

    print("result folders")
    results = tmp / "results_x"
    results.mkdir()
    (results / "benchmark.report.html").write_text("<html>report</html>", encoding="utf-8")
    (results / "benchmark.leaderboard.tsv").write_text("rank\tanalysis_track\ttask\ttool\tmean_f1\n1\tshort_read\treconstruction\tt1\t0.9\n", encoding="utf-8")
    (tmp / "secret.txt").write_text("secret", encoding="utf-8")
    runs = json.loads(call("/api/runs/add", {"path": str(results)})[1])["runs"]
    idx = next(i for i, r in enumerate(runs) if r["name"] == "results_x")
    check("an added results folder is listed with its leaders", runs[idx]["leaders"][0]["tool"] == "t1" and runs[idx]["report"])
    code, body, _ = call(f"/view/{idx}/benchmark.report.html")
    check("its report is served", code == 200 and body == b"<html>report</html>")
    check("a path that climbs out of the folder is not served", call(f"/view/{idx}/../secret.txt")[0] == 404
          and call(f"/view/{idx}/..%2Fsecret.txt")[0] == 404)
    check("an unknown run index is not served", call("/view/999/benchmark.report.html")[0] == 404)

    print("page")
    page_file = ROOT / "plasbench" / "data" / "ui.html"
    check("the page ships with the package (a .gitignore rule once kept it out of the repository)", page_file.is_file())
    if (ROOT / ".git").exists() and shutil.which("git"):
        import subprocess
        tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--error-unmatch", "plasbench/data/ui.html"],
                                 capture_output=True).returncode == 0
        check("git tracks plasbench/data/ui.html", tracked)
    html = page_file.read_text(encoding="utf-8")
    views = ["home", "setup", "tools", "addtool", "settings", "wizard", "isolates", "cohorts", "runs", "jobs", "commands", "help"]
    check("every page the rail links to exists", all(f'id="v_{v}"' in html and f'data-view="{v}"' in html for v in views))
    check("the page loads nothing from the network", "http://" not in html.split("<script>")[0].replace("http://www.w3.org", "")
          and "<link " not in html and "src=\"http" not in html)
    check("API calls send the session token header", "X-PlasBench-Token" in html)
    check("[hidden] always hides (no component style overrides it)", "[hidden]{display:none!important}" in html)

    server.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)
    if FAILED:
        print("WEB UI TESTS FAILED")
        return 1
    print("ALL WEB UI TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
