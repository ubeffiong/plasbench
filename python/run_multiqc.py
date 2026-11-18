#!/usr/bin/env python3
"""Optional MultiQC companion: run `multiqc` over the fastp (and QUAST) outputs of a run into results/multiqc/. Never fails the run.

MultiQC is not used by PlasBench's own QC (that is fastp plus python/short_read_qc.py, shown in the report's QC panel). This is an optional extra: when
`multiqc` is installed it draws the same fastp (and, when QUAST was run, QUAST) files the community-standard way. The report links to it and does not embed it
(its size, the offline single-file promise and MultiQC's version drift). Install it with `plasbench install-tools multiqc`.

Setting MULTIQC_REPORT:  auto (default) run only when `multiqc` is on PATH;  on  always try, and warn when it is missing;  off  never.
Setting MULTIQC_TIMEOUT_SECONDS (default 600): the limit for the multiqc command.

Whatever happens the exit code is 0: a missing multiqc, no inputs, a timeout or a failing command is recorded as a warning event in run_events.jsonl and in
results/multiqc/multiqc_run.json, which the report's QC panel reads for its note. Nothing outside results/multiqc/ is written except that event line.

  run_multiqc.py --data-dir data --results-dir results [--mode auto|on|off] [--timeout 600]

Standard library only.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

TAB = chr(9)
MODES = ("auto", "on", "off")
TRUE_WORDS, FALSE_WORDS = {"1", "true", "yes", "on"}, {"0", "false", "no", "off", "none"}
RUN_FILE = "multiqc_run.json"
REPORT_NAME = "multiqc_report.html"
DEFAULT_TIMEOUT = 600


def parse_mode(value):
    """(mode, problem): auto | on | off. Blank is auto; 1/true/yes mean on; 0/false/no mean off; anything else is auto with the problem named."""
    word = (value or "").strip().lower()
    if word == "":
        return "auto", ""
    if word in MODES:
        return word, ""
    if word in TRUE_WORDS:
        return "on", ""
    if word in FALSE_WORDS:
        return "off", ""
    return "auto", f"MULTIQC_REPORT={value!r} is not auto, on or off; using auto"


def parse_timeout(value):
    try:
        seconds = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT
    return seconds if seconds > 0 else DEFAULT_TIMEOUT


def find_inputs(data_dir, results_dir):
    """The files and folders MultiQC is given: every sample's fastp.json, and each folder holding a QUAST report.tsv (named explicitly, so MultiQC never scans read files)."""
    found, quast = [], set()
    for base in {d for d in (data_dir, results_dir) if d and os.path.isdir(d)}:
        for here, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d != "multiqc" and not d.startswith(".")]
            if "fastp.json" in files:
                found.append(os.path.join(here, "fastp.json"))
            if "report.tsv" in files and ("quast" in here.lower() or "icarus.html" in files or "report.txt" in files):
                quast.add(here)
    return sorted(set(found)) + sorted(quast)


def write_event(results_dir, event, **fields):
    """One JSON line in run_events.jsonl in the shape scripts/lib.sh writes (never raises)."""
    path = os.environ.get("RUN_EVENTS_FILE") or os.path.join(results_dir, "run_events.jsonl")
    line = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "epoch": int(time.time()), "pid": os.getpid(), "event": event, **fields}
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, sort_keys=False) + "\n")
    except OSError:
        pass


def write_status(out_dir, status):
    try:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, RUN_FILE), "w", encoding="utf-8") as handle:
            json.dump(status, handle, indent=1, sort_keys=True)
            handle.write("\n")
    except OSError:
        pass


def run(data_dir, results_dir, mode="auto", timeout=DEFAULT_TIMEOUT, which=shutil.which, runner=subprocess.run):
    """Run MultiQC when the mode and the PATH allow it. Returns the status dict (also written to results/multiqc/multiqc_run.json); never raises."""
    mode, problem = parse_mode(mode)
    out_dir = os.path.join(results_dir, "multiqc")
    status = {"mode": mode, "state": "", "note": "", "report": "", "inputs": 0, "version": "", "seconds": 0.0}
    if problem:
        write_event(results_dir, "warning", component="multiqc", message=problem)
    if mode == "off":
        status.update(state="off", note="MULTIQC_REPORT=off")
        return status                                    # nothing written: an earlier results/multiqc is left as it was
    exe = which("multiqc")
    if not exe:
        status.update(state="absent", note="multiqc is not installed" + ("" if mode == "auto" else " (MULTIQC_REPORT=on)"))
        if mode == "on":
            write_event(results_dir, "warning", component="multiqc", message="MULTIQC_REPORT=on but multiqc is not on PATH; install it with: plasbench install-tools multiqc")
            write_status(out_dir, status)
        return status
    inputs = find_inputs(data_dir, results_dir)
    status["inputs"] = len(inputs)
    if not inputs:
        status.update(state="no_inputs", note="no fastp.json or QUAST report was found, so there is nothing for MultiQC to read")
        write_event(results_dir, "warning", component="multiqc", message=status["note"])
        write_status(out_dir, status)
        return status
    try:
        version = runner([exe, "--version"], capture_output=True, text=True, timeout=60)
        status["version"] = (version.stdout or version.stderr or "").strip().splitlines()[-1] if (version.stdout or version.stderr).strip() else ""
    except (OSError, subprocess.SubprocessError):
        pass
    os.makedirs(out_dir, exist_ok=True)
    command = [exe, "-f", "--no-ansi", "-o", out_dir, "-n", REPORT_NAME, "--title", "PlasBench: fastp and QUAST outputs"] + inputs
    started = time.time()
    write_event(results_dir, "command_start", component="multiqc", inputs=str(len(inputs)))
    try:
        done = runner(command, capture_output=True, text=True, timeout=timeout)
        code, tail = done.returncode, ((done.stderr or "") + (done.stdout or "")).strip().splitlines()[-3:]
    except subprocess.TimeoutExpired:
        code, tail = 124, [f"timed out after {timeout} s (MULTIQC_TIMEOUT_SECONDS)"]
    except (OSError, subprocess.SubprocessError) as exc:
        code, tail = 127, [str(exc)]
    status["seconds"] = round(time.time() - started, 1)
    report = os.path.join(out_dir, REPORT_NAME)
    if code == 0 and os.path.isfile(report):
        status.update(state="ok", report=f"multiqc/{REPORT_NAME}", note="")
        write_event(results_dir, "command_end", component="multiqc", exit_code="0", seconds=str(status["seconds"]))
    else:
        message = f"multiqc failed (exit {code}): " + " | ".join(tail)[:300]
        status.update(state="failed", note=message)
        write_event(results_dir, "warning", component="multiqc", message=message)
    write_status(out_dir, status)
    return status


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--results-dir", required=True)
    ap.add_argument("--mode", default=os.environ.get("MULTIQC_REPORT", "auto"), help="auto (default), on or off; default from MULTIQC_REPORT")
    ap.add_argument("--timeout", default=os.environ.get("MULTIQC_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT)))
    a = ap.parse_args(argv)
    try:
        status = run(a.data_dir, a.results_dir, a.mode, parse_timeout(a.timeout))
    except Exception as exc:  # noqa: BLE001 - an optional extra must never stop a run
        print(f"run_multiqc: skipped after an unexpected error: {exc}", file=sys.stderr)
        return 0
    words = {"ok": f"wrote {status['report']} from {status['inputs']} input(s)", "off": "off (MULTIQC_REPORT=off)",
             "absent": "skipped: " + status["note"], "no_inputs": "skipped: " + status["note"], "failed": "WARNING: " + status["note"]}
    print("run_multiqc: " + words.get(status["state"], status["state"]), file=sys.stderr if status["state"] in ("failed",) else sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
