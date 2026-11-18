#!/usr/bin/env python3
"""performance_summary.py uses each run's own thread count (audit AU-032).

It used one global THREADS for every tool, so thread-seconds and CPU utilisation were wrong whenever tools were given different thread counts. Stage 4 now
records each run's threads in tool_run_resources.tsv beside tool_status.tsv, and the summary reads it; a run that recorded none falls back to --threads.
The CPU figure also sums every attempt of a retried run (the runtime in tool_status.tsv covers all of them).
"""
import csv
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "python", "performance_summary.py")
HEAD = "sample\ttool\tstatus\tprediction_fasta\treason\truntime_seconds\tpeak_rss_kb\n"
OK = True


def check(label, good):
    global OK
    print(f"  {label}: {'PASS' if good else 'FAIL'}")
    OK &= bool(good)


def summarise(tmp, name, status, resources, scores, rss_files, threads="4"):
    d = os.path.join(tmp, name)
    logs = os.path.join(d, "logs")
    os.makedirs(logs)
    open(os.path.join(d, "tool_status.tsv"), "w", newline="").write(status)
    if resources is not None:
        open(os.path.join(d, "tool_run_resources.tsv"), "w", newline="").write(resources)
    open(os.path.join(d, "scores.tsv"), "w", newline="").write(scores)
    for fname, content in rss_files.items():
        open(os.path.join(logs, fname), "w").write(content)
    out = os.path.join(d, "perf.tsv")
    subprocess.run([sys.executable, SCRIPT, "--tool-status", os.path.join(d, "tool_status.tsv"), "--scores", os.path.join(d, "scores.tsv"),
                    "--logs-dir", logs, "--threads", threads, "--out", out], check=True, capture_output=True)
    return {r["tool"]: r for r in csv.DictReader(open(out, newline=""), delimiter="\t")}


with tempfile.TemporaryDirectory() as tmp:
    status = HEAD + "s1\tslim\tcompleted\tx\t\t100\t1048576\ns1\twide\tcompleted\tx\t\t100\t1048576\n"
    scores = "sample\ttool\trecovered_plasmid_count\ns1\tslim\t2\ns1\twide\t2\n"
    rss = {"s1.slim.rss": "1048576 100 0\n", "s1.wide.rss": "1048576 100 0\n"}
    resources = ("sample\ttool\tthreads\tattempt_seconds\tpeak_rss_kb\trss_note\n"
                 "s1\tslim\t2\t1:100\t1048576\t\ns1\twide\t8\t1:100\t1048576\t\n")
    rows = summarise(tmp, "per_run", status, resources, scores, rss)
    check("thread-seconds per recovered plasmid use each tool's own threads (slim 2 -> 100, wide 8 -> 400; one global value gave 200 for both)",
          abs(float(rows["slim"]["thread_seconds_per_recovered_plasmid"]) - 100) < 1e-6
          and abs(float(rows["wide"]["thread_seconds_per_recovered_plasmid"]) - 400) < 1e-6)
    check("CPU utilisation uses each tool's own threads (100 cpu-s / (100 s x 2) = 0.5; / (100 x 8) = 0.125)",
          abs(float(rows["slim"]["cpu_utilisation"]) - 0.5) < 1e-6 and abs(float(rows["wide"]["cpu_utilisation"]) - 0.125) < 1e-6)
    check("the threads column shows the count each tool really had", rows["slim"]["threads"] == "2" and rows["wide"]["threads"] == "8")

    rows = summarise(tmp, "legacy", status, None, scores, rss)
    check("results without the resources table fall back to --threads (4 for both: 200)",
          abs(float(rows["slim"]["thread_seconds_per_recovered_plasmid"]) - 200) < 1e-6 and rows["slim"]["threads"] == "4")

    mixed = HEAD + "s1\tmix\tcompleted\tx\t\t100\t1\ns2\tmix\tcompleted\tx\t\t100\t1\n"
    mixed_res = "sample\ttool\tthreads\tattempt_seconds\tpeak_rss_kb\trss_note\ns1\tmix\t2\t1:100\t\t\ns2\tmix\t4\t1:100\t\t\n"
    rows = summarise(tmp, "mixed", mixed, mixed_res, "sample\ttool\trecovered_plasmid_count\ns1\tmix\t1\ns2\tmix\t1\n", {})
    check("a tool given different counts on different runs: thread-seconds sum per run ((200 + 400) / 2 = 300) and the column shows the range",
          abs(float(rows["mix"]["thread_seconds_per_recovered_plasmid"]) - 300) < 1e-6 and rows["mix"]["threads"] == "2-4")

    retried = HEAD + "s1\tretry\tcompleted\tx\t\t100\t1\n"
    rows = summarise(tmp, "retry", retried, "sample\ttool\tthreads\tattempt_seconds\tpeak_rss_kb\trss_note\ns1\tretry\t1\t1:40,2:60\t\t\n",
                     "sample\ttool\trecovered_plasmid_count\ns1\tretry\t1\n", {"s1.retry.rss": "1024 30 10\n1024 35 25\n"})
    check("CPU seconds of every attempt are summed (30+10+35+25 = 100 over 100 s x 1 thread = 1.0)",
          abs(float(rows["retry"]["cpu_utilisation"]) - 1.0) < 1e-6)

print("ALL PER-RUN THREAD TESTS PASSED" if OK else "PER-RUN THREAD TESTS FAILED")
sys.exit(0 if OK else 1)
