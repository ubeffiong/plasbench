#!/usr/bin/env python3
"""PIPELINE_OVERLAP=1 (default 0): start stage 2 (truth and reference annotation) for an isolate as soon as stage 1 has finished it, while stage 1 goes on downloading the others.

Measured case: a 5-isolate laptop run spent 4 h 20 min downloading one 9.5 GB isolate while the CPUs waited; the other four isolates' stage 2 (about 1 h 20 min, measured) could have
run in that time. This is the bounded producer and consumer of docs/PERFORMANCE_AUDIT.md, built so that it cannot change a result or the meaning of a run:

  * Ready means THIS run's stage 1 recorded the isolate as downloaded (a `download_end` event with status ok, after the run started). A file left by an earlier run is never
    taken as ready: stage 1 may still check, re-download or replace it.
  * The follower runs the unchanged scripts/02_truth.sh for one isolate at a time (a one-row sample sheet), at low priority (nice 10), with its own results, events and temporary
    folders, so the run's status, events and tables are not touched; per-isolate files land where stage 2 always writes them (data/<isolate>/) and its log in LOG_DIR.
  * Stage 2 itself still runs after stage 1, over every isolate, exactly as without the overlap. Its steps reuse finished per-isolate work ("already present"), so the result is
    the same files from the same code on the same inputs; anything the follower did not finish, or failed, is simply done (or reported) there. A failure in the follower never
    stops the run or another isolate.
  * Stopping the run (Ctrl+C, `plasbench stop`) stops the follower and the stage-2 process it started (its own process group). It ends when stage 1 has ended and nothing is ready.

  python3 -I python/pipeline_overlap.py ready  --events FILE --since EPOCH --sheet SHEET [--done FILE]   the isolates ready now, in sheet order
  python3 -I python/pipeline_overlap.py follow --events FILE --since EPOCH --sheet SHEET --work DIR --stop FILE [--script scripts/02_truth.sh] [--poll 20]

Standard library only; Python 3.9 compatible.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sheet_rows(sheet):
    """(header_line, [(sample_id, line)]) of a sample sheet: the first non-comment, non-blank line is the header; comment and blank lines are skipped."""
    header, rows = None, []
    with open(sheet, encoding="utf-8") as handle:
        for line in handle:
            text = line.rstrip("\r\n")
            if not text.strip() or text.lstrip().startswith("#"):
                continue
            if header is None:
                header = text
                continue
            rows.append((text.split("\t")[0], text))
    return header, rows


def downloaded(events, since):
    """Samples whose download_end event of this run (epoch >= since) says ok. A later event for the same sample wins (a retry that failed is not ready)."""
    state = {}
    try:
        with open(events, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("event") != "download_end":
                    continue
                try:
                    if float(row.get("epoch", 0)) < float(since):
                        continue
                except (TypeError, ValueError):
                    continue
                sample = row.get("sample")
                if sample:
                    state[sample] = row.get("status") == "ok"
    except OSError:
        pass
    return {s for s, ok in state.items() if ok}


def read_done(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return {ln.split("\t")[0] for ln in handle if ln.strip()}
    except OSError:
        return set()


def ready(events, since, sheet, done=()):
    ok = downloaded(events, since)
    _, rows = sheet_rows(sheet)
    return [s for s, _ in rows if s in ok and s not in set(done)]


_CHILD = {"proc": None}


def _stop(signum, frame):
    proc = _CHILD.get("proc")
    if proc is not None and proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM) if os.name == "posix" else proc.terminate()
        except OSError:
            pass
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL) if os.name == "posix" else proc.kill()
            except OSError:
                pass
    sys.exit(128 + signum)


def run_one(sample, line, header, work, script, log):
    """Stage 2 for one isolate, unchanged script, private results/events/temp folders. Returns the exit status."""
    work = Path(work)
    sheet = work / "sheets" / (sample + ".tsv")
    sheet.parent.mkdir(parents=True, exist_ok=True)
    with open(sheet, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(header + "\n" + line + "\n")
    env = dict(os.environ)
    for key in ("RUN_TMP_DIR", "_RUN_TMP_OWNER", "RUN_EVENTS_FILE", "_STAGE_TIMING_ID", "_PB_SENTINEL_PID"):
        env.pop(key, None)
    env.update(SAMPLE_SHEET=str(sheet), RESULTS_DIR=str(work / "results"), TMP_DIR=str(work / "tmp"), RUN_EVENTS_FILE=str(work / "events.jsonl"),
               MAX_PARALLEL_SAMPLES="1", PLASBENCH_SAMPLES_EXPLICIT="1", AUTO_PARALLEL="0", PIPELINE_OVERLAP_FOLLOWER="1", KEEP_AWAKE="0")
    (work / "results").mkdir(parents=True, exist_ok=True)
    (work / "tmp").mkdir(parents=True, exist_ok=True)
    cmd = (["nice", "-n", "10"] if os.name == "posix" else []) + ["bash", str(script)]
    with open(log, "a", encoding="utf-8") as out:
        out.write("=== %s: stage 2 for %s, started while stage 1 continues (PIPELINE_OVERLAP=1)\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), sample))
        out.flush()
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, env=env, start_new_session=(os.name == "posix"))
        _CHILD["proc"] = proc
        rc = proc.wait()
        _CHILD["proc"] = None
    return rc


def append_event(events, **fields):
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "epoch": int(time.time()), "pid": os.getpid()}
    row.update({k: str(v) for k, v in fields.items()})
    try:
        with open(events, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    except OSError:
        pass


def follow(events, since, sheet, work, stop, script, poll=20.0, log=None, say=print):
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    done_file = work / "done.tsv"
    log = log or str(work / "follower.log")
    header, rows = sheet_rows(sheet)
    lines = dict(rows)
    while True:
        todo = ready(events, since, sheet, read_done(done_file))
        for sample in todo:
            started = time.time()
            rc = run_one(sample, lines[sample], header, work, script, log)
            status = "ok" if rc == 0 else "failed"
            with open(done_file, "a", encoding="utf-8") as handle:
                handle.write("%s\t%s\t%d\n" % (sample, status, int(time.time() - started)))
            append_event(events, event="overlap_stage2", sample=sample, status=status, seconds=int(time.time() - started))
            say("PIPELINE_OVERLAP: stage 2 for %s %s in %d s while stage 1 continued%s" % (
                sample, "done" if rc == 0 else "did not finish", time.time() - started, "" if rc == 0 else " (stage 2 does it again and reports it; see %s)" % log), flush=True)
        if os.path.exists(stop) and not ready(events, since, sheet, read_done(done_file)):
            return 0
        time.sleep(poll)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("ready", "follow"):
        p = sub.add_parser(name)
        p.add_argument("--events", required=True)
        p.add_argument("--since", type=float, required=True)
        p.add_argument("--sheet", required=True)
        if name == "ready":
            p.add_argument("--done", default="")
        else:
            p.add_argument("--work", required=True)
            p.add_argument("--stop", required=True)
            p.add_argument("--script", default=str(ROOT / "scripts" / "02_truth.sh"))
            p.add_argument("--poll", type=float, default=20.0)
            p.add_argument("--log", default="")
    args = ap.parse_args(argv)
    if args.cmd == "ready":
        for sample in ready(args.events, args.since, args.sheet, read_done(args.done) if args.done else ()):
            print(sample)
        return 0
    return follow(args.events, args.since, args.sheet, args.work, args.stop, args.script, args.poll, args.log or None)


if __name__ == "__main__":
    sys.exit(main())
