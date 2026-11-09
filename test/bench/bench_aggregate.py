"""Time aggregate_results.py on synthetic score tables of increasing size.

Writes inputs into a temp dir and runs the real script as a subprocess.
usage: python bench_aggregate.py <project>/python <samples> <tools> <workers>
"""
import csv
import os
import random
import subprocess
import sys
import tempfile
import time

py, n_samples, n_tools, workers = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
rng = random.Random(7)
species = ["Escherichia coli", "Klebsiella pneumoniae", "Acinetobacter baumannii"]
with tempfile.TemporaryDirectory() as d:
    sheet, caps, scores = (os.path.join(d, n) for n in ("sheet.tsv", "caps.tsv", "scores.tsv"))
    with open(sheet, "w") as h:
        h.write("sample_id\torganism\tbioproject\n")
        for i in range(n_samples):
            h.write(f"s{i}\t{species[i % 3]}\tPRJ{i // 2}\n")      # pairs of isolates share a study
    tools = [f"tool{t}" for t in range(n_tools)]
    with open(caps, "w") as h:
        h.write("tool\tmethod_class\tbinning_capable\tanalysis_track\n")
        for t in tools:
            h.write(f"{t}\tbinning\tyes\tshort_read\n")
    header = ["sample", "tool", "analysis_track", "true_plasmid_count", "precision", "recall", "f1",
              "lw_bin_f1", "cprr_plasmids", "cprr_correct", "cprr_correct_without_identity", "TP_bp", "FP_bp", "FN_bp"]
    with open(scores, "w", newline="") as h:
        w = csv.writer(h, delimiter="\t", lineterminator="\n")
        w.writerow(header)
        for i in range(n_samples):
            n = rng.randint(1, 4)
            for k, t in enumerate(tools):
                skill = 0.5 + 0.04 * k
                f = min(1.0, max(0.0, rng.gauss(skill, 0.15)))
                c = rng.randint(0, n)
                w.writerow([f"s{i}", t, "short_read", n, f, f, f, f, n, c, c, 50000, 1000, 2000])
    env = dict(os.environ, PLASBENCH_STATS_WORKERS=workers)
    t0 = time.perf_counter()
    done = subprocess.run([sys.executable, os.path.join(py, "aggregate_results.py"), "--scores", scores,
                           "--sample-sheet", sheet, "--capabilities", caps, "--min-species-clusters", "5",
                           "--out-prefix", os.path.join(d, "b")], capture_output=True, text=True, env=env)
    dt = time.perf_counter() - t0
    assert done.returncode == 0, done.stderr[-2000:]
    print(f"samples={n_samples}\ttools={n_tools}\tpairs={n_tools*(n_tools-1)//2}\tworkers={workers}\twall_s={dt:.1f}")
