#!/usr/bin/env python3
"""Runs started outside the window appear under Runs, read-only (plasbench/outside_runs.py, GET /api/run-sessions).

From each study's study.json `runs` and its results folder: running (.run.lock + a fresh .run.lock.heartbeat), completed (benchmark.report.html or tool_status.tsv), else stopped
("interrupted or cancelled: it stopped without recording how it ended"). A run the window started (via=window, or an older record that matches a window job) is not repeated here.
The page labels them "started outside the window" and offers only Show in terminal and Open folder, never Cancel.
"""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp())
os.environ["PLASBENCH_UI_HOME"] = str(tmp / "ui")
os.environ["PLASBENCH_LOCAL_SETTINGS"] = str(tmp / "local.env")
os.environ["PLASBENCH_WORKSPACE"] = str(tmp / "ws")
from plasbench import outside_runs, studies, webui  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def stamp(t=None):
    return datetime.fromtimestamp(t or time.time()).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def study(name, runs):
    folder = tmp / "ws" / name
    (folder / "results").mkdir(parents=True)
    (folder / "study.json").write_text(json.dumps({"name": name, "runs": runs}), encoding="utf-8")
    return folder


def main():
    cmd = "plasbench run -s x.tsv --study "
    done = study("done1", [{"started": stamp(), "command": cmd + "done1", "via": "terminal"}])
    (done / "results" / "benchmark.report.html").write_text("<html>", encoding="utf-8")
    partial = study("partial1", [{"started": stamp(), "command": cmd + "partial1", "via": "terminal"}])
    (partial / "results" / "tool_status.tsv").write_text("a\n", encoding="utf-8")
    running = study("running1", [{"started": stamp(), "command": cmd + "running1", "via": "terminal"}])
    (running / "results" / ".run.lock").write_text("pid=999999\n", encoding="utf-8")
    (running / "results" / ".run.lock.heartbeat").write_text("x", encoding="utf-8")
    stopped = study("stopped1", [{"started": stamp(), "command": cmd + "stopped1", "via": "terminal"}])
    stale = study("stale1", [{"started": stamp(), "command": cmd + "stale1", "via": "terminal"}])
    (stale / "results" / ".run.lock").write_text("pid=999999\n", encoding="utf-8")
    (stale / "results" / ".run.lock.heartbeat").write_text("x", encoding="utf-8")
    old = time.time() - 3600
    os.utime(stale / "results" / ".run.lock.heartbeat", (old, old))
    study("fromwindow", [{"started": stamp(), "command": cmd + "fromwindow", "via": "window"}])
    study("legacy", [{"started": stamp(), "command": "plasbench run --study legacy"}])
    study("norun", [])
    rows = {e["study"]: e for e in outside_runs.outside_runs(studies.list_studies(tmp), jobs=[{"argv": ["run", "--study", "legacy"], "started": time.time()}])}

    print("states")
    check("a report in results: completed", rows["done1"]["state"] == "completed" and rows["done1"]["group"] == "completed" and rows["done1"]["report"], rows.get("done1"))
    check("tool_status.tsv without a report: completed (as the brief says)", rows["partial1"]["state"] == "completed")
    check("a fresh lock heartbeat: running", rows["running1"]["state"] == "running" and rows["running1"]["group"] == "ongoing", rows.get("running1"))
    check("nothing in results: stopped, with the exact explanation", rows["stopped1"]["state"] == "stopped" and "interrupted or cancelled: it stopped without recording how it ended" in rows["stopped1"]["note"], rows.get("stopped1"))
    check("a stale heartbeat is not running", rows["stale1"]["state"] == "stopped")
    check("every entry is marked as started outside the window and read-only", all(r["outside"] and "started outside the window" in r["note"] for r in rows.values()))
    check("a run the window started is not repeated (via=window, or a legacy record matching a window job)", "fromwindow" not in rows and "legacy" not in rows, sorted(rows))
    check("a study with no run is not listed", "norun" not in rows)
    ext = tmp / "drive"
    ext.mkdir()
    gone = studies.prepare(tmp, "ext1", location=ext, argv=["run", "--study", "ext1"])
    shutil_rm = __import__("shutil").rmtree
    shutil_rm(gone)
    check("a study on a disconnected drive does not break the listing", isinstance(outside_runs.outside_runs(studies.list_studies(tmp)), list))

    print("the study record says who started it")
    os.environ.pop("PLASBENCH_STARTED_VIA", None)
    f = studies.prepare(tmp, "via1", argv=["run"])
    check("a run started in a shell is recorded via=terminal", json.loads((f / "study.json").read_text())["runs"][-1]["via"] == "terminal")
    os.environ["PLASBENCH_STARTED_VIA"] = "window"
    f = studies.prepare(tmp, "via2", argv=["run"])
    check("a run the window launched is recorded via=window", json.loads((f / "study.json").read_text())["runs"][-1]["via"] == "window")
    os.environ.pop("PLASBENCH_STARTED_VIA")
    src = (ROOT / "plasbench" / "webui.py").read_text(encoding="utf-8")
    check("the window's launcher sets it for the commands it starts", 'PLASBENCH_STARTED_VIA="window"' in src)

    print("endpoint and page")
    project = webui.Project(ROOT)
    jobs = webui.Jobs(project)
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.make_handler(project, jobs))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/run-sessions", headers={"Host": f"127.0.0.1:{port}", "X-PlasBench-Token": webui.TOKEN})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = json.loads(r.read())
    server.shutdown()
    check("GET /api/run-sessions carries an `outside` list next to `sessions`", "outside" in body and "done1" in {e["study"] for e in body["outside"]}, list(body))
    html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    check("the Runs page shows them labelled 'started outside the window' with Show in terminal and Open folder, and no Cancel", "started outside the window" in html and 'data-oa="terminal"' in html and 'data-oa="folder"' in html
          and "outsideHTML" in html and "data-sa=\"cancel\"" not in html.split("const outsideHTML")[1].split("function renderSessions")[0])
    check("it says the window cannot cancel them", "this window did not start them, so it cannot cancel them" in html)
    print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL PASS")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
