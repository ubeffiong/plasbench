#!/usr/bin/env python3
"""Bounded waits on the five Popen pipelines (audit AU-044).

A fake producer (seqtk, filtlong, badread, pigz, minimap2) that closes stdout and then hangs used to hang the stage forever: the producer's
wait() / communicate() had no limit. With PLASBENCH_SUBPROCESS_TIMEOUT_SECONDS=2 each pipeline now stops within seconds and says why.
Needs a POSIX shell for the fake tools, so it is skipped on native Windows (run it in WSL).
"""
import csv
import gzip
import os
import stat
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, "python")
OK = True


def check(label, good, detail=""):
    global OK
    print(f"  {label}: {'PASS' if good else 'FAIL'}" + ("" if good else f"  [{detail}]"))
    OK &= bool(good)


if os.name == "nt":
    print("  SKIP: needs a POSIX shell for fake tools (run in WSL)")
    sys.exit(0)

HANG = "#!/bin/sh\nexec 1>&-\nexec sleep 40\n"          # close stdout (so the consumer finishes), then hang


def fake(directory, name, body=HANG):
    path = os.path.join(directory, name)
    with open(path, "w") as handle:
        handle.write(body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


def run(cmd, env_extra=None, limit=25):
    env = dict(os.environ, PLASBENCH_SUBPROCESS_TIMEOUT_SECONDS="2", **(env_extra or {}))
    start = time.time()
    try:
        done = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=limit)
        return done.returncode, done.stdout + done.stderr, time.time() - start
    except subprocess.TimeoutExpired:
        return None, "HUNG", time.time() - start


def tsv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(header)
        writer.writerows(rows)


with tempfile.TemporaryDirectory(prefix="popen_timeouts_") as tmp:
    bindir = os.path.join(tmp, "bin")
    os.makedirs(bindir)
    data = os.path.join(tmp, "data", "s1")
    os.makedirs(data)
    for name in ("reference.fna",):
        open(os.path.join(data, name), "w").write(">c\nACGT\n")
    tsv(os.path.join(data, "truth.tsv"), ["sequence_id", "molecule_type", "length"], [["c", "CHROMOSOME", "4"]])
    tsv(os.path.join(data, "observed_depth.tsv"), ["observed_depth_x"], [["40"]])
    for mate in (1, 2):
        with gzip.open(os.path.join(data, f"RUN1_{mate}.fastq.gz"), "wt") as handle:
            handle.write("@r\nACGT\n+\n!!!!\n")
    with gzip.open(os.path.join(data, "long_reads.fastq.gz"), "wt") as handle:
        handle.write("@r\nACGT\n+\n!!!!\n")
    sheet = os.path.join(tmp, "samples.tsv")
    tsv(sheet, ["sample_id", "sra_run", "read_depth_x"], [["s1", "RUN1", "40"]])

    seqtk = fake(bindir, "seqtk")
    code, out, took = run([sys.executable, os.path.join(PY, "make_depth_ladder.py"), "--samples", sheet, "--data-dir", os.path.join(tmp, "data"),
                           "--out-dir", os.path.join(tmp, "ladder"), "--depths", "20", "--seqtk", seqtk])
    check("make_depth_ladder: hung seqtk is stopped, not waited on", code not in (None, 0) and "timed out" in out and took < 20, f"{code} {took:.0f}s {out[-200:]}")

    filtlong = fake(bindir, "filtlong")
    code, out, took = run([sys.executable, os.path.join(PY, "make_read_quality_ladder.py"), "--samples", sheet, "--data-dir", os.path.join(tmp, "data"),
                           "--out-dir", os.path.join(tmp, "rq"), "--rungs", "10:5", "--filtlong", filtlong])
    check("make_read_quality_ladder: hung filtlong is stopped", code not in (None, 0) and "timed out" in out and took < 20, f"{code} {took:.0f}s {out[-200:]}")

    # measure_depth: a decompressor that never finishes (pigz first on PATH)
    fake(bindir, "pigz", "#!/bin/sh\nexec sleep 40\n")
    code, out, took = run([sys.executable, os.path.join(PY, "measure_depth.py"), "--truth", os.path.join(data, "truth.tsv"),
                           "--r1", os.path.join(data, "RUN1_1.fastq.gz"), "--r2", os.path.join(data, "RUN1_2.fastq.gz"),
                           "--out", os.path.join(tmp, "depth.tsv")], {"PATH": bindir + os.pathsep + os.environ["PATH"]})
    check("measure_depth: hung decompressor is stopped", code not in (None, 0) and "timed out" in out and took < 20, f"{code} {took:.0f}s {out[-200:]}")

    # simulate_reads.simulate_long_reads
    sys.path.insert(0, PY)
    import simulate_reads
    badread = fake(bindir, "badread")
    os.environ["PLASBENCH_SUBPROCESS_TIMEOUT_SECONDS"] = "2"
    start = time.time()
    ok, _ = simulate_reads.simulate_long_reads(badread, os.path.join(data, "reference.fna"), 10, "m", "q", 1, os.path.join(tmp, "long.fastq.gz"))
    check("simulate_reads: hung badread is stopped and reported as failure", ok is False and time.time() - start < 20, f"{ok} {time.time() - start:.0f}s")

    # compute_difficulty_features.depth_ratio: fake minimap2 hangs, samtools sort drains stdin
    fake(bindir, "minimap2", "#!/bin/sh\nexec sleep 40\n")
    fake(bindir, "samtools", "#!/bin/sh\ncat >/dev/null\n")
    import compute_difficulty_features as cdf
    old_path = os.environ["PATH"]
    os.environ["PATH"] = bindir + os.pathsep + old_path
    start = time.time()
    result = cdf.depth_ratio(os.path.join(data, "reference.fna"), os.path.join(data, "truth.tsv"),
                             os.path.join(data, "RUN1_1.fastq.gz"), os.path.join(data, "RUN1_2.fastq.gz"), 1)
    os.environ["PATH"] = old_path
    check("compute_difficulty_features: hung minimap2 gives a blank ratio within the limit", result == "" and time.time() - start < 20, f"{result!r} {time.time() - start:.0f}s")

print("ALL POPEN PIPELINE TIMEOUT TESTS PASSED" if OK else "POPEN PIPELINE TIMEOUT TESTS FAILED")
sys.exit(0 if OK else 1)
