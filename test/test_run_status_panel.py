#!/usr/bin/env python3
"""The Run status panel (GET /api/runs/status, plasbench/webui.py run_status_json, plasbench/data/ui.html).

The window asks python/run_status.py (written with the logging pipeline) to summarise a results folder; it never computes the status itself. Checked here with a fake run_status
module, because the summary's content belongs to that module:
  - API shape: JSON with `state`, `text` (the render(summary, diagnose=True) text), `results`, `log_dir`; token-protected;
  - confinement: only a study's results folder or a listed run folder; a path outside, the program folder, the workspace are refused (403), a missing one is 404;
  - cache: a second request inside 3 s does not call summarize again; after 3 s it does;
  - failure: a summarize that raises, a missing module, or a result that is not a dict all return {"state": "no-run", "error": ...} with no exception;
  - the page: the panel, its four buttons (Refresh, Copy diagnosis, Open the console log, Open run_events.jsonl), a 5 s poll only while the tab and the panel are visible and not while a dialog or
    menu is open, keyed patching, the first hint instead of the generic stalled text, and the console-log checkbox (RUN_CONSOLE_LOG=0 when unchecked; LOG_RETENTION_RUNS) with tooltips and the allowlist.
"""
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp())
os.environ["PLASBENCH_UI_HOME"] = str(tmp / "ui")
os.environ["PLASBENCH_LOCAL_SETTINGS"] = str(tmp / "local.env")
os.environ["PLASBENCH_WORKSPACE"] = str(tmp / "ws")
from plasbench import ui_help, ui_schema, webui  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


CALLS = []


def fake_module(fail=False, not_dict=False):
    def summarize(results, log_dir, data_dir):
        CALLS.append((str(results), str(log_dir), str(data_dir)))
        if fail:
            raise RuntimeError("boom")
        if not_dict:
            return ["x"]
        return {"state": "running", "now": {"stage": 3, "isolate": "S1", "step": "spades", "seconds": 4980}, "hints": [{"text": "SPAdes is the only busy process", "evidence": "CPU 380%"}]}
    return SimpleNamespace(summarize=summarize, render=lambda s, diagnose=False: "DIAGNOSIS " + s["state"])


def main():
    print("run_status_json")
    results = tmp / "r1"
    results.mkdir()
    clock = [100.0]
    now = lambda: clock[0]  # noqa: E731
    webui._status_cache.clear()
    a = webui.run_status_json(ROOT, results, tmp / "logs", tmp / "data", loader=lambda root: fake_module(), now=now)
    check("a summary with state, text, results and log_dir", a["state"] == "running" and a["text"] == "DIAGNOSIS running" and a["results"] == str(results) and a["log_dir"] == str(tmp / "logs"), a)
    check("summarize got the results, log and data folders", CALLS[-1] == (str(results), str(tmp / "logs"), str(tmp / "data")), CALLS)
    n = len(CALLS)
    clock[0] += 1.0
    webui.run_status_json(ROOT, results, tmp / "logs", tmp / "data", loader=lambda root: fake_module(), now=now)
    check("a second request within 3 s is served from the cache", len(CALLS) == n)
    clock[0] += 3.5
    webui.run_status_json(ROOT, results, tmp / "logs", tmp / "data", loader=lambda root: fake_module(), now=now)
    check("after 3 s it asks again", len(CALLS) == n + 1)
    for label, loader in (("a summarize that raises", lambda root: fake_module(fail=True)), ("a missing run_status.py", lambda root: None), ("a result that is not a summary", lambda root: fake_module(not_dict=True)),
                          ("a loader that raises", lambda root: (_ for _ in ()).throw(ImportError("nope")))):
        webui._status_cache.clear()
        out = webui.run_status_json(ROOT, results, tmp / "logs", tmp / "data", loader=loader, now=now)
        check(f"{label} returns no-run JSON, never an exception", out["state"] == "no-run" and out.get("error"), out)

    print("API")
    ws = tmp / "ws"
    study = ws / "s1"
    (study / "results").mkdir(parents=True)
    (study / "study.json").write_text(json.dumps({"name": "s1", "runs": [], "data_dir": str(tmp / "mydata")}), encoding="utf-8")
    (study / "results" / "tool_status.tsv").write_text("a\n", encoding="utf-8")
    plain = tmp / "elsewhere" / "other"
    plain.mkdir(parents=True)
    webui._status_cache.clear()
    webui.load_run_status = lambda root: fake_module()
    project = webui.Project(ROOT)
    jobs = webui.Jobs(project)
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.make_handler(project, jobs))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    def get(path, token=True):
        h = {"Host": f"127.0.0.1:{port}"}
        if token:
            h["X-PlasBench-Token"] = webui.TOKEN
        try:
            with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=h), timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {}
    q = urllib.parse.quote
    code, body = get(f"/api/runs/status?path={q(str(study / 'results'))}")
    check("a study's results folder: 200 and the summary with text", code == 200 and body["state"] == "running" and body["text"].startswith("DIAGNOSIS") and body["log_dir"] == str(study / "logs"), (code, body))
    check("the study's recorded data folder is passed on", CALLS[-1][2] == str(tmp / "mydata"), CALLS[-1])
    check("it needs the session token", get(f"/api/runs/status?path={q(str(study / 'results'))}", token=False)[0] == 403)
    for label, p in (("the PlasBench folder", ROOT), ("the workspace", ws), ("a folder outside", plain), ("home", Path.home()), ("a study folder", study)):
        check(f"{label}: refused (403)", get(f"/api/runs/status?path={q(str(p))}")[0] == 403, label)
    check("a missing folder is a 404", get(f"/api/runs/status?path={q(str(tmp / 'nope'))}")[0] == 404)
    webui.save_state({"runs": [str(plain)]})
    (plain / "scores.tsv").write_text("x\n", encoding="utf-8")
    check("a listed run folder that holds results is allowed", get(f"/api/runs/status?path={q(str(plain))}")[0] == 200)
    server.shutdown()

    print("page")
    html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    check("the panel exists on ongoing run cards and in the stalled console panel", "rsPanel(s.results)" in html and "rsHTML(st.results)" in html and 'aria-label="Run status"' in html)
    check("it shows state chip, Now, CPU and memory, the machine, progress, newest log and 'What this means'", all(k in html for k in ("rsState(d)", "<b>Now:</b>", "this command has run", "CPU ${Math.round", "This computer:", "Newest log:", "What this means")))
    check("hints are a list with their evidence, alarming only for memory or disk", "rsAlarm" in html and "h.evidence" in html and "memory|swap|disk" in html)
    check("buttons: Refresh, Copy diagnosis, Open the console log, Open run_events.jsonl", all(k in html for k in ('data-rsa="refresh"', 'data-rsa="copy"', ">Copy diagnosis<", ">Open the console log<", ">Open run_events.jsonl<", "run.latest.log")))
    check("Copy diagnosis copies the server's text", 'S.rs[path].data || {}).text' in html and "copyText(t, \"Diagnosis copied\")" in html)
    poll = html.split("async function rsPoll() {")[1].split("setInterval(rsPoll")[0]
    check("polls every 5 s", "setInterval(rsPoll, 5000)" in html)
    check("polls only while the tab is visible and not while a dialog or menu is open", "document.hidden || uiBusy([])" in poll)
    check("polls only for panels that are showing (the Runs page, or the visible stalled panel)", '$("#v_runs").hidden' in poll and '$("#cstall").hidden' in poll)
    check("a poll that finds nothing new redraws nothing (signature, then the keyed / skip-if-unchanged render)", "e.sig !== sig" in html and "changed" in poll and "setIfChanged($(\"#sesslist\")" in html)
    check("the stalled chip and panel show the first hint instead of the generic text", "rsFirstHint(s.results)" in html and "hint || STALL_TEXT(st.idle)" in html)
    check("the log files open in the viewer (.jsonl is previewable)", '".jsonl": "text"' in (ROOT / "plasbench" / "webui.py").read_text(encoding="utf-8"))

    print("console log checkbox")
    check("the Downloads and reliability card has the checkbox, on by default", "Keep a console log of the run in the study (logs/run_*.log)" in html and 'E.console_log !== false ? "checked"' in html)
    check("unchecked sends RUN_CONSOLE_LOG=0; the retention field sends LOG_RETENTION_RUNS", 'if (E.console_log === false) d.RUN_CONSOLE_LOG = "0"' in html and "d.LOG_RETENTION_RUNS = String(E.log_runs)" in html)
    allowed = webui.Jobs(webui.Project(ROOT)).env_allowlist()
    check("both names are on the env allowlist", {"RUN_CONSOLE_LOG", "LOG_RETENTION_RUNS"} <= allowed)
    help_ = ui_schema.schema()["wizard_help"]
    check("tooltips: defaults on and 20, with the setting names", help_["console_log"]["default"] == "on" and help_["console_log"]["setting"] == "RUN_CONSOLE_LOG" and help_["log_retention_runs"]["default"] == "20" and help_["log_retention_runs"]["setting"] == "LOG_RETENTION_RUNS")
    check("the Settings page lists them in the reliability group when config.sh defines them", {"RUN_CONSOLE_LOG", "LOG_RETENTION_RUNS"} <= set(ui_help.RELIABILITY_KEYS))
    print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL PASS")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
