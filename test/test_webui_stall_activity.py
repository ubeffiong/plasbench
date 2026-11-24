#!/usr/bin/env python3
"""A stalled run, explained and actionable; plus the small window fixes (ledger, Quit wording, stage line).

  - jobrunner.recent_activity: a recent file -> "active"; only old files -> "quiet"; a symlinked file or folder is not followed; the entry cap is honoured;
    paths are relative and sorted newest first;
  - Jobs.activity and GET /api/jobs/<id>/activity: session-token protected, 404 for an unknown job;
  - the page says "No new output for N minutes ... Closing this window does NOT stop the run", offers Check activity and Cancel, relabels the chip "Working (quiet log)";
  - cohorts/accepted_accessions.tsv is marked `ledger` and kept out of the wizard's picker; the Quit dialog says what each choice does; the Runs list shows stage and isolate.
"""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp())
os.environ["PLASBENCH_UI_HOME"] = str(tmp / "ui")
os.environ["PLASBENCH_LOCAL_SETTINGS"] = str(tmp / "local.env")
from plasbench import cohort_info, jobrunner, webui  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def age(path, seconds):
    t = time.time() - seconds
    os.utime(path, (t, t))


def main():
    print("recent_activity")
    tree = tmp / "tree"
    (tree / "a" / "b").mkdir(parents=True)
    old = tree / "a" / "old.txt"
    old.write_text("x")
    age(old, 3600)
    out = jobrunner.recent_activity([str(tree)])
    check("only old files -> quiet", out["status"] == "quiet" and out["files"][0]["path"] == "a/old.txt", out)
    part = tree / "a" / "b" / "SRR1.sra.part"
    part.write_bytes(b"x" * 2048)
    out = jobrunner.recent_activity([str(tree)])
    check("a recently written .part file -> active, newest first, relative path, size, age",
          out["status"] == "active" and out["files"][0]["path"] == "a/b/SRR1.sra.part" and out["files"][0]["size"] == 2048 and out["files"][0]["age_seconds"] < 60, out)
    age(part, 120)
    check("2 minutes ago is still active; 4 minutes ago is quiet", jobrunner.recent_activity([str(tree)])["status"] == "active")
    age(part, 240)
    check("quiet once nothing changed for 3 minutes", jobrunner.recent_activity([str(tree)])["status"] == "quiet")
    try:
        outside = tmp / "outside"
        outside.mkdir()
        (outside / "fresh.txt").write_text("fresh")
        (tree / "link_dir").symlink_to(outside, target_is_directory=True)
        (tree / "link_file").symlink_to(outside / "fresh.txt")
        out = jobrunner.recent_activity([str(tree)])
        check("symlinks are not followed (a fresh file behind a link does not make it active)", out["status"] == "quiet" and not any("fresh" in f["path"] or "link" in f["path"] for f in out["files"]), out)
    except (OSError, NotImplementedError):
        print("  skip  symlinks cannot be created here")
    big = tmp / "big"
    big.mkdir()
    for i in range(50):
        (big / f"f{i}.txt").write_text("x")
    out = jobrunner.recent_activity([str(big)], max_entries=10)
    check("the entry cap is honoured and reported", out["truncated"] and out["walked"] <= 10 and len(out["files"]) <= 10, out)
    check("a missing folder is skipped", jobrunner.recent_activity([str(tmp / "nope"), ""])["files"] == [])

    print("endpoint")
    project = webui.Project(ROOT)
    jobs = webui.Jobs(project)
    results = tmp / "results"
    results.mkdir()
    (results / "x.part").write_text("downloading")
    jobs.jobs["j1"] = {"id": "j1", "label": "t", "argv": ["run"], "command": "plasbench run", "env": {}, "kind": "plasbench", "state": "running",
                       "started": time.time(), "ended": None, "exit": None, "pid": 0, "results": str(results)}
    act = jobs.activity("j1")
    check("Jobs.activity reports the results folder", act["status"] == "active" and any(f["path"] == "x.part" for f in act["files"]), act)
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
            return e.code, e.read()
    code, body = get("/api/jobs/j1/activity")
    check("GET /api/jobs/<id>/activity answers", code == 200 and body["status"] == "active", (code, body))
    check("it needs the session token", get("/api/jobs/j1/activity", token=False)[0] == 403)
    check("an unknown job is a 404", get("/api/jobs/nope/activity")[0] == 404)
    server.shutdown()

    print("ledger")
    cohorts = {c["name"]: c for c in project.cohorts()}
    ledger = ROOT / "cohorts" / "accepted_accessions.tsv"
    if ledger.is_file():
        check("accepted_accessions is marked ledger", cohorts["accepted_accessions"]["ledger"] is True)
        check("a real cohort is not", not any(c["ledger"] for n, c in cohorts.items() if n != "accepted_accessions" and not c["metagenomic"]), [n for n, c in cohorts.items() if c["ledger"]])
        check("cohort_info calls it a ledger", cohort_info.info(ROOT, "accepted_accessions")["kind"] == "ledger")
    check("is_ledger: a curated sheet is not one", not cohort_info.is_ledger(["sample_id", "organism", "assembly_accession", "sra_run", "biosample", "source_cohort"]))

    print("a quiet console is not a stall when the tools are working (one signal, no contradiction)")
    study = tmp / "studyA"
    (study / "results").mkdir(parents=True)
    (study / "logs").mkdir()
    (study / "study.json").write_text("{}", encoding="utf-8")
    for old in (study / "results").glob("*"):
        old.unlink()
    job = {"id": "j9", "label": "t", "argv": ["run"], "command": "plasbench run", "env": {}, "kind": "plasbench", "state": "running", "started": time.time(), "ended": None,
           "exit": None, "pid": 0, "results": str(study / "results")}
    jobs.jobs["j9"] = job
    real_stalled, real_status = jobrunner.is_stalled, webui.run_status_json
    jobrunner.is_stalled = lambda *a, **k: True          # the console has printed nothing for the stall window
    try:
        def status(log_idle, cpu):
            return lambda *a, **k: {"state": "running", "newest_log": {"file": "x.spades.log", "idle_seconds": log_idle}, "processes": {"count": 9, "cpu_percent": cpu}}
        webui.run_status_json = status(41, 508)
        check("console quiet, a tool log written 41 s ago: working_quiet, not stalled", jobs.display_state(job) == "working_quiet", jobs.display_state(job))
        ev = jobs._working_evidence(job)
        check("the evidence says why in plain words", ev["working"] and "41 s ago" in ev["why"] and ev["cpu_cores"] == 5.08, ev)
        webui.run_status_json = status(4000, 508)
        check("tool log old but the processes use 5 cores: still working_quiet", jobs.display_state(job) == "working_quiet" and "CPU cores" in jobs._working_evidence(job)["why"])
        webui.run_status_json = status(4000, 3)
        check("everything quiet for an hour and the processes idle: stalled", jobs.display_state(job) == "stalled")
        def boom(*a, **k):
            raise RuntimeError("no status")
        webui.run_status_json = boom
        check("no evidence available (an error): the old rule applies, stalled", jobs.display_state(job) == "stalled")
        webui.run_status_json = status(4000, 3)
        fresh = study / "logs" / "k.spades.log"
        fresh.write_text("INFO collecting k-mer coverage")
        act = jobs.activity("j9")
        check("Check activity looks in the study's logs folder: a log just written counts as active", act["status"] == "active" and any(f["path"].endswith("k.spades.log") for f in act["files"]), act)
        age(fresh, 4000)
        webui.run_status_json = status(41, 508)
        act = jobs.activity("j9")
        check("activity is active when the run's own tool log or CPU says so, even if no file under the roots changed", act["status"] == "active" and act["evidence"]["working"], act)
        webui.run_status_json = status(4000, 3)
        check("and quiet when nothing at all is happening", jobs.activity("j9")["status"] == "quiet")
        check("the scratch and download folders are among the places looked at", any(r.endswith("scratch") for r in jobs._tool_roots(job)) and any(r.endswith("downloads") for r in jobs._tool_roots(job)))
    finally:
        jobrunner.is_stalled, webui.run_status_json = real_stalled, real_status
        jobs.jobs.pop("j9", None)

    print("page")
    html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    check("plain-words stall text", "No new output for ${stallMinutes(secs)} minute" in html and "This is often normal while reads download or a tool assembles. Closing this window does NOT stop the run." in html)
    check("Check activity and Cancel are offered in the console and on the run card", html.count("Check activity") >= 2 and 'data-st-act="cancel"' in html and 'data-sa="cancel"' in html)
    check("the chip is relabelled when the check finds writes", "Working (quiet log)" in html and 'status === "active"' in html)
    check("the page shows 'Working, console quiet' for a quiet console with busy tools (display_state working_quiet), and the activity answer says why", 's.display_state === "working_quiet" ? "Working, console quiet"' in html and "a.evidence.why" in html and "run's processes are idle" in html)
    check("the old 'Stalled: no output' wording is gone", "Stalled: no output" not in html and "Stalled (no output" not in html)
    check("the cohort picker hides ledgers and says so if one is chosen", "!c.metagenomic && !c.ledger" in html and "Not a cohort sheet." in html)
    check("the Cohorts page tags the ledger", 'c.ledger ? `<span class="tag warn"' in html)
    check("the Quit dialog says in one sentence what each choice does", "Quit and keep running closes this window and PlasBench but leaves the run going in the background, while plain Quit (Stop and quit) cancels the run first" in html)
    check("the Runs list shows the current stage and isolate for ongoing runs", "Stage ${pr.stages[idx].id}: ${pr.current_name} (step ${idx + 1} of ${n})" in html and "Stage ${idx + 1} of" not in html and "isolate ${pr.isolates_in_stage} of ${pr.isolates}" in html)
    print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL PASS")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
