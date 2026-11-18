#!/usr/bin/env python3
"""The window may pass environment settings with a job (the wizard's "Downloads and reliability" card), but only allow-listed ones.

Jobs.start / POST /api/jobs refuse, with a 400 and a clear message: a name that is not UPPER_SNAKE, a name that is not a Settings key of config/config.sh
or one of the download names (LD_PRELOAD, PATH ...), a value with a newline or NUL, a value of 200 characters or more, and a non-text value. Allowed names pass
and reach the job's environment. The page shows the settings in the review command, the Jobs list and says a saved script cannot carry them.
"""
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
tmp = tempfile.mkdtemp()
os.environ["PLASBENCH_UI_HOME"] = str(Path(tmp) / "ui")
os.environ["PLASBENCH_LOCAL_SETTINGS"] = str(Path(tmp) / "local.env")
from plasbench import webui  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def refused(jobs, env):
    try:
        jobs.start(["demo"], "t", env)
    except ValueError as exc:
        return str(exc)
    return None


def main():
    project = webui.Project(ROOT)
    jobs = webui.Jobs(project)
    launched = []
    jobs._launch = lambda command, shown, label, env, argv, kind, cwd, resumes=None: launched.append(env) or {"id": "x", "env": env}   # nothing is really started

    print("refused")
    for key in ("LD_PRELOAD", "PATH", "PYTHONPATH", "BASH_ENV", "HOME"):
        msg = refused(jobs, {key: "x"})
        check(f"{key} is refused", msg and key in msg, msg)
    check("a lower-case or odd name is refused", all(refused(jobs, {k: "1"}) for k in ("read_source", "READ SOURCE", "1READ", "READ-SOURCE", "")))
    check("a value with a newline is refused", "one line" in (refused(jobs, {"READ_SOURCE": "ena\nPATH=/x"}) or ""))
    check("a value with a carriage return or NUL is refused", refused(jobs, {"READ_SOURCE": "a\rb"}) and refused(jobs, {"READ_SOURCE": "a\x00b"}))
    check("a value of 200 characters is refused", "too long" in (refused(jobs, {"READ_SOURCE": "x" * 200}) or ""))
    check("a list or object value is refused", refused(jobs, {"READ_SOURCE": ["ena"]}) and refused(jobs, {"READ_SOURCE": {"a": 1}}))
    check("env that is not an object is refused", refused(jobs, ["READ_SOURCE"]))
    check("nothing refused was launched", not launched, launched)

    print("allowed")
    good = {"READ_SOURCE": "ena", "MAX_RUN_DOWNLOAD_GB": "12.5", "WARN_RUN_DOWNLOAD_GB": 5, "PREFETCH_FAIL_LIMIT": "2", "TOOL_TIMEOUT_SECONDS": "7200",
            "ALLOW_ALL_TOOLS_FAILED": "1", "NETWORK_RETRIES": "3", "ENA_DOWNLOAD_CONNECTIONS": "4", "THREADS": "2"}
    check("the wizard's names and a Settings key pass", refused(jobs, good) is None)
    check("they reach the job as text", launched and launched[-1]["WARN_RUN_DOWNLOAD_GB"] == "5" and launched[-1]["READ_SOURCE"] == "ena", launched)
    check("no env at all passes", refused(jobs, None) is None and refused(jobs, {}) is None)
    allowed = jobs.env_allowlist()
    check("the allowlist is built from config.sh's Settings keys", {r["key"] for r in project.settings()} - {"PROJECT_ROOT"} <= allowed and "LD_PRELOAD" not in allowed)

    print("over HTTP")
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.make_handler(project, jobs))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    def post(body):
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/jobs", data=json.dumps(body).encode(), method="POST",
                                     headers={"Host": f"127.0.0.1:{port}", "X-PlasBench-Token": webui.TOKEN, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    code, body = post({"argv": ["demo"], "env": {"LD_PRELOAD": "/tmp/x.so"}})
    check("POST /api/jobs with LD_PRELOAD answers 400 with a clear message", code == 400 and "LD_PRELOAD" in body.get("error", ""), (code, body))
    code, body = post({"argv": ["demo"], "env": {"READ_SOURCE": "ena"}})
    check("POST /api/jobs with READ_SOURCE=ena is accepted", code == 200, (code, body))
    server.shutdown()

    print("page")
    html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    check("the review shows KEY=value before the command", "envPrefix(wizEnv()) + cmdText(argv)" in html)
    check("Start sends the env with the job", "startJob(argv, W.source === \"demo\" ? \"Offline demo\" : `Benchmark: ${wizSummary()[0][1]}`, wenv)" in html)
    check("the Jobs list shows the settings", "envPrefix(j.env) + j.command" in html)
    check("Save as a script says it cannot carry them", "cannot carry" in html and "export ${k}=" in html)
    check("the card has all eight controls", all(k in html for k in ("READ_SOURCE", "MAX_RUN_DOWNLOAD_GB", "WARN_RUN_DOWNLOAD_GB", "PREFETCH_FAIL_LIMIT", "TOOL_TIMEOUT_SECONDS",
                                                                      "ALLOW_ALL_TOOLS_FAILED", "NETWORK_RETRIES", "ENA_DOWNLOAD_CONNECTIONS")))
    check("hours are sent as seconds (x 3600)", "* 3600" in html)
    check("the report checkbox adds --open-report and --no-report-prompt stays on", 'id="wopen"' in html and "vals.open_report = W.source !== \"meta\"" in html and "vals.no_report_prompt = true;" in html)
    print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL PASS")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
