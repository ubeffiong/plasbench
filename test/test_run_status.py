#!/usr/bin/env python3
"""`plasbench status` / `diagnose` (python/run_status.py): what a run is doing, and why it may look stuck, from its event log, lock, tables and processes.

The scenario that prompted it: public-v4 with a 9.5 GB isolate went quiet for hours inside stage 3, because trimming and assembling wrote to their own logs. The
fixtures here are that run at different moments, with the process table and the machine's figures injected, so nothing depends on the host.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import run_status as rs  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


NOW = 1_800_000_000.0


def ev(offset, event, **kw):
    return {"ts": "t", "epoch": NOW + offset, "pid": 1, "event": event, **kw}


def write_run(results, events, lock=None, heartbeat_age=None, tables=None):
    results.mkdir(parents=True, exist_ok=True)
    with open(results / "run_events.jsonl", "w", encoding="utf-8") as handle:
        for e in events:
            handle.write(json.dumps(e) + "\n")
        handle.write('{"ts": "cut off mid-wr')          # a write that was cut off must not break reading
    if lock:
        (results / ".run.lock").write_text("".join(f"{k}={v}\n" for k, v in lock.items()), encoding="utf-8")
        hb = results / ".run.lock.heartbeat"
        hb.write_text("x")
        if heartbeat_age is not None:
            os.utime(hb, (NOW - heartbeat_age, NOW - heartbeat_age))
    for name, rows in (tables or {}).items():
        (results / name).write_text("\n".join("\t".join(r) for r in rows) + "\n", encoding="utf-8")


def procs(*rows):
    return [{"pid": p, "ppid": pp, "cpu": c, "rss_kb": r * 1024, "seconds": s, "args": a} for p, pp, c, r, s, a in rows]


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    study = tmp / "study"
    results, logs, data = study / "results", study / "logs", tmp / "data"
    (data / "streptomyces_sp").mkdir(parents=True)
    for mate in (1, 2):
        (data / "streptomyces_sp" / f"SRR1_{mate}.fastq.gz").write_bytes(b"x" * 3000)   # small files and a lowered threshold: no big files on the test disk
    rs.BIG_READS_BYTES = 5000
    logs.mkdir(parents=True)
    (logs / "streptomyces_sp.spades.log").write_text("== Running read error correction ==\n  0:41:12  3.9G / 6G   INFO   General (main.cpp)\n")
    os.utime(logs / "streptomyces_sp.spades.log", (NOW - 2400, NOW - 2400))

    events = [ev(-9000, "run_start", stages="0 1 2 3"), ev(-8990, "stage_start", stage="3"),
              ev(-7200, "command_start", stage="3", what="streptomyces_sp / fastp trimming"),
              ev(-5000, "command_end", stage="3", what="streptomyces_sp / fastp trimming", seconds="2200", exit="0"),
              ev(-4990, "sample_start", stage="3", sample="streptomyces_sp", step="spades"),
              ev(-4980, "command_start", stage="3", what="streptomyces_sp / SPAdes assembly"),
              ev(-60, "heartbeat", stage="3", what="streptomyces_sp / SPAdes assembly", elapsed="4920", stats="cpu=1850% rss=6900MB procs=22", system="mem_avail=180MB swap_used=3100MB disk_free=40GB")]
    write_run(results, events, lock={"pid": "4242", "pgid": "4242", "started": "2026-11-18 08:00:00", "what": "run_all.sh"}, heartbeat_age=5,
              tables={"download_status.tsv": [("sample", "status", "reason"), ("a", "ok", ""), ("streptomyces_sp", "ok", "")],
                      "assembly_status.tsv": [("sample", "status", "contigs", "reason", "runtime_seconds"), ("a", "completed", "x", "", "1")]})
    table = procs((4242, 1, 0.0, 10, 9000, "bash run_all.sh"), (4300, 4242, 0.0, 5, 8000, "bash 03_assemble.sh"),
                  (4400, 4300, 1850.0, 6900, 4900, "python spades.py -1 t1 -2 t2 -o out --threads 20"), (999, 1, 3.0, 50, 100, "unrelated"))
    s = rs.summarize(results, log_dir=logs, data_dir=data, now=NOW, procs=table, mach={"mem_avail_mb": 180, "swap_used_mb": 3100, "disk_free_gb": 40})

    # --- a run deep in an assembly, short of memory ------------------------------------------------------------------------------------
    check("a lock with a fresh heartbeat and live processes is RUNNING", s["state"] == "running", s["state"])
    check("it reads the stage, isolate and step from the events", s["stage"] == "3" and s["sample"] == "streptomyces_sp" and s["step"] == "spades", (s["stage"], s["sample"], s["step"]))
    check("it knows the open command and how long it has run (about 83 minutes)", s["command"] == "streptomyces_sp / SPAdes assembly" and 4900 < s["step_seconds"] < 5000, (s["command"], s["step_seconds"]))
    check("only the run's own processes are counted (not the unrelated one)", s["processes"]["count"] == 3 and s["processes"]["cpu_percent"] == 1850, s["processes"])
    check("progress comes from the status tables", s["progress"]["download"]["ok"] == 2 and s["progress"]["assembly"]["ok"] == 1, s["progress"])
    check("the isolate's reads are measured from the data folder", s["reads_bytes"] == 6000, s["reads_bytes"])
    text = " ".join(s["hints"])
    check("a large read set is named with its size, and the way out", "6 KB compressed" in text and "MAX_RUN_DOWNLOAD_GB" in text, text)
    check("low memory is named with the figure", "180 MB of memory is available" in text, text)
    check("swap is named with the figure", "3100 MB of swap" in text, text)
    check("a busy run is said to be working, with the CPU figure", "using 1850% CPU" in text or "1850% CPU" in text, text)
    check("the newest log of the isolate and its age are shown", s["newest_log"]["idle_seconds"] == 2400 and "General" in s["newest_log"]["last_line"], s.get("newest_log"))
    out = rs.render(s, diagnose=True)
    check("the text names stage, isolate, step and the heartbeat figures", "stage 3, isolate streptomyces_sp, step spades" in out and "cpu=1850%" in out, out)
    check("diagnose lists the busiest process", "spades.py" in out and "pid    4400" in out, out)
    check("status (without diagnose) does not list processes", "spades.py" not in rs.render(s, diagnose=False))

    # --- the window reads this summary: every field it uses must exist in the real thing (the panel was first written against guessed names) ---------------
    page = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    contract = {"d.stage": s.get("stage"), "d.sample": s.get("sample"), "d.step": s.get("step"), "d.step_seconds": s.get("step_seconds"),
                "pr.cpu_percent": s["processes"].get("cpu_percent"), "pr.rss_mb": s["processes"].get("rss_mb"), "pr.count": s["processes"].get("count"),
                "mach.mem_avail_mb": s["machine"].get("mem_avail_mb"), "mach.swap_used_mb": s["machine"].get("swap_used_mb"), "mach.disk_free_gb": s["machine"].get("disk_free_gb"),
                "v.ok": s["progress"]["download"].get("ok"), "v.rows": s["progress"]["download"].get("rows"),
                "last_line": s["newest_log"].get("last_line"), "idle_seconds": s["newest_log"].get("idle_seconds")}
    check("the page reads the real summary's field names", all(k in page for k in contract), [k for k in contract if k not in page])
    check("and each of those fields has a value in a real summary", all(v is not None for v in contract.values()), [k for k, v in contract.items() if v is None])
    check("a folder with no run does not get the Running chip (its state name contains 'run')", 'v === "no-run" ? ["No run here"' in page)
    check("every state the summary can have is one the page names", {"running", "finished", "stopped", "no-run"} <= {"running", "finished", "stopped", "no-run"} and all(f'"{x}"' in page for x in ("running", "finished", "stopped", "no-run")))

    # --- the same run after the machine was switched off ---------------------------------------------------------------------------
    s2 = rs.summarize(results, log_dir=logs, data_dir=data, now=NOW + 7200, procs=[], mach={"mem_avail_mb": 6000, "disk_free_gb": 40})
    check("a lock with a stale heartbeat and no live process is STOPPED, not running", s2["state"] == "stopped", s2["state"])
    check("it says the run was cut off and that re-running resumes", any("cut off" in h and "resumes" in h for h in s2["hints"]), s2["hints"])

    # --- a finished run --------------------------------------------------------------------------------------------------------------
    done = tmp / "done" / "results"
    write_run(done, [ev(-100, "run_start"), ev(-10, "run_end", status="finished")])
    s3 = rs.summarize(done, now=NOW, procs=[], mach={})
    check("run_end after run_start is FINISHED", s3["state"] == "finished", s3["state"])

    # --- nothing there; a run from an older version (no events) ---------------------------------------------------------------------------
    empty = tmp / "empty" / "results"
    empty.mkdir(parents=True)
    check("a folder with no run is reported as such", rs.summarize(empty, now=NOW, procs=[], mach={})["state"] == "no-run")
    old = tmp / "old" / "results"
    old.mkdir(parents=True)
    (old / ".run_in_progress").write_text("started x, stage 3 (03_assemble.sh), pid 1\n")
    s4 = rs.summarize(old, now=NOW, procs=[], mach={})
    check("a leftover marker with no process is STOPPED, and the missing event log is explained", s4["state"] == "stopped" and "No run_events.jsonl" in rs.render(s4), rs.render(s4))

    # --- quiet but alive: a process that lives while no event comes ------------------------------------------------------------------------
    quiet = tmp / "quiet" / "results"
    write_run(quiet, [ev(-3000, "stage_start", stage="1"), ev(-2990, "sample_start", stage="1", sample="s1", step="download")],
              lock={"pid": "7", "pgid": "7", "started": "x", "what": "run_all.sh"}, heartbeat_age=3)
    s5 = rs.summarize(quiet, now=NOW, procs=procs((7, 1, 0.0, 5, 3000, "bash run_all.sh"), (8, 7, 4.0, 90, 2900, "python fetch_ena_reads.py")), mach={"mem_avail_mb": 5000, "disk_free_gb": 100})
    text5 = " ".join(s5["hints"])
    check("a live run with no recent event says a long step writes to its own log", "No event for" in text5 and "own log" in text5, text5)
    check("a busy-less process is described as waiting on the network, not as an error", "4% CPU" in text5 and "network" in text5, text5)

    # --- a run that stopped in stage 3 because SPAdes failed: the cause and advice stage 3 recorded, or the classifier on the log for an old status file -----------------
    page_text = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    new_run = tmp / "asmfail" / "results"
    write_run(new_run, [ev(-50, "stage_start", stage="3"), ev(-40, "assembly_failed", stage="3", sample="a", cause="disk_full")],
              tables={"assembly_status.tsv": [("sample", "status", "contigs", "reason", "runtime_seconds", "cause", "advice"),
                                               ("a", "failed", "", "spades: disk_full", "3", "disk_full", "Free disk space on C:, then run the same command again."),
                                               ("b", "skipped", "", "not attempted", "", "disk_full", "fix it"),
                                               ("c", "failed", "", "spades: disk_full", "2", "disk_full", "Free disk space on C:, then run the same command again.")]})
    s6 = rs.summarize(new_run, log_dir=tmp / "nologs", now=NOW, procs=[], mach={})
    af = s6["assembly_failures"]
    check("the summary carries the assembly failures with their recorded cause and advice", af["failed"] == 2 and af["items"][0]["cause"] == "disk_full" and "Free disk space" in af["items"][0]["advice"], af)
    check("failures with one cause are summarised as the same reason", af["same_cause"] == "disk_full", af)
    check("a hint says the cause is the computer, not the isolates, with the advice", any("same cause (disk_full)" in h and "Free disk space on C:" in h for h in s6["hints"]), s6["hints"])
    check("the text output lists the failures", "assembly failures: 2, all for the same reason: disk_full" in rs.render(s6), rs.render(s6))
    check("the window reads these fields (assembly_failures, same_cause, items, advice)", all(k in page_text for k in ("d.assembly_failures", "af.same_cause", "af.items", "i.advice", "i.cause")))
    check("and each exists in a real summary", set(af) >= {"failed", "items", "same_cause"} and set(af["items"][0]) >= {"sample", "cause", "advice"}, af)
    logs_old = tmp / "asmfail_logs"
    logs_old.mkdir()
    (logs_old / "a.spades.log").write_text("some progress\n  0:00:03  ERROR  General  Failed to write: No space left on device\n", encoding="utf-8")
    old_run = tmp / "asmfail_old" / "results"
    write_run(old_run, [ev(-50, "stage_start", stage="3")],
              tables={"assembly_status.tsv": [("sample", "status", "contigs", "reason", "runtime_seconds"), ("a", "failed", "", "spades: see log", "3")]})
    s7 = rs.summarize(old_run, log_dir=logs_old, now=NOW, procs=[], mach={})
    check("an old status file (no cause column) is still read: the classifier reads the isolate's log", s7["assembly_failures"]["items"][0]["cause"] == "disk_full" and s7["progress"]["assembly"]["failed"] == 1, s7["assembly_failures"])
    check("a status file with nothing failed has no assembly_failures", rs.summarize(results, log_dir=logs, now=NOW, procs=[], mach={})["assembly_failures"] == {})

    # --- helpers ------------------------------------------------------------------------------------------------------------------------------
    check("events survive a cut-off last line", len(rs.read_events(results / "run_events.jsonl")) == len(events))
    check("human_seconds", rs.human_seconds(30) == "30 s" and rs.human_seconds(600) == "10 min" and rs.human_seconds(8100) == "2 h 15 min")
    check("descendants stops on a cycle", len(rs.descendants(procs((1, 2, 0, 1, 1, "a"), (2, 1, 0, 1, 1, "b")), 1)) == 2)

    # --- the command line ---------------------------------------------------------------------------------------------------------------------
    cli = subprocess.run([sys.executable, "-m", "plasbench", "status", "--results-dir", str(empty)], capture_output=True, text=True, cwd=str(ROOT), timeout=120)
    check("`plasbench status` on a folder with no run exits 0 and says so", cli.returncode == 0 and "no run found here" in cli.stdout, (cli.returncode, cli.stdout, cli.stderr[-300:]))
    cli = subprocess.run([sys.executable, "-m", "plasbench", "diagnose", "--results-dir", str(results), "--json"], capture_output=True, text=True, cwd=str(ROOT), timeout=120)
    parsed = json.loads(cli.stdout) if cli.returncode == 0 else {}
    check("`plasbench diagnose --json` prints the summary as JSON", cli.returncode == 0 and parsed.get("stage") == "3" and "hints" in parsed, (cli.returncode, cli.stdout[:200], cli.stderr[-300:]))

print("ALL RUN STATUS TESTS PASSED" if ok else "RUN STATUS TESTS FAILED")
sys.exit(0 if ok else 1)
