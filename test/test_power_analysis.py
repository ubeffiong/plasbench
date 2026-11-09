#!/usr/bin/env python3
"""power_analysis.py: minimum detectable difference, by hand-computed cases."""
import csv
import math
import os
import statistics
import subprocess
import sys
import tempfile
from statistics import NormalDist

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "python", "power_analysis.py")


def run(tmp, rows, sheet_rows=None, *extra):
    scores, sheet, out = (os.path.join(tmp, n) for n in ("scores.tsv", "sheet.tsv", "power.tsv"))
    with open(scores, "w") as fh:
        fh.write("sample\ttool\tanalysis_track\tf1\n" + "".join(f"{s}\t{t}\tshort_read\t{v}\n" for s, t, v in rows))
    args = [sys.executable, SCRIPT, "--scores", scores, "--out", out, *extra]
    if sheet_rows is not None:
        with open(sheet, "w") as fh:
            fh.write("sample_id\tbioproject\n" + "".join(f"{s}\t{b}\n" for s, b in sheet_rows))
        args += ["--sample-sheet", sheet]
    done = subprocess.run(args, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return list(csv.DictReader(open(out, newline=""), delimiter="\t"))


def main():
    ok = True

    def check(label, good):
        nonlocal ok
        print(f"  {label}: {'PASS' if good else 'FAIL'}")
        ok &= bool(good)

    z = NormalDist().inv_cdf(0.975) + NormalDist().inv_cdf(0.80)
    with tempfile.TemporaryDirectory() as tmp:
        # 10 independent samples; A - B differences: 0.02 .. 0.11 (sd known).
        diffs = [0.02, 0.04, 0.06, 0.08, 0.10, 0.03, 0.05, 0.07, 0.09, 0.11]
        rows = []
        for i, d in enumerate(diffs):
            rows += [(f"s{i}", "A", 0.5 + d), (f"s{i}", "B", 0.5)]
        r = run(tmp, rows)[0]
        sd = statistics.stdev(diffs)
        want_mdd = z * sd / math.sqrt(10)
        check("10 independent samples: MDD = (z_a + z_b) * sd / sqrt(10)",
              abs(float(r["min_detectable_difference"]) - want_mdd) < 1e-5)
        check("the observed mean difference (0.065) is above the MDD, so distinguishable",
              r["status"] == "distinguishable" and r["observed_vs_mdd"] == "at_or_above")
        need = math.ceil((z * sd / 0.05) ** 2)
        check("clusters needed for a 0.05 target = ((z_a + z_b) * sd / 0.05)^2 rounded up",
              r["clusters_needed_for_target"] == str(need))

        # Same data but all samples in one BioProject: one cluster -> too few, no MDD.
        r = run(tmp, rows, [(f"s{i}", "PRJ1") for i in range(10)])[0]
        check("one BioProject is one cluster: status too_few_clusters and no MDD",
              r["status"] == "too_few_clusters" and r["min_detectable_difference"] == "" and r["clusters"] == "1")

        # Two samples per BioProject (5 clusters): differences are averaged within a cluster first.
        r = run(tmp, rows, [(f"s{i}", f"PRJ{i // 2}") for i in range(10)])[0]
        means = [statistics.mean(diffs[i:i + 2]) for i in range(0, 10, 2)]
        check("clustered: 5 clusters and the SD of cluster means, not of samples",
              r["clusters"] == "5" and abs(float(r["sd_cluster_differences"]) - statistics.stdev(means)) < 1e-5)

        # A tiny, noisy difference is not distinguishable.
        noisy = []
        for i, d in enumerate([0.2, -0.2, 0.15, -0.15, 0.1, -0.1, 0.05, -0.04]):
            noisy += [(f"n{i}", "A", 0.5 + d), (f"n{i}", "B", 0.5)]
        r = run(tmp, noisy)[0]
        check("mean difference near zero with large spread: not distinguishable",
              r["status"] == "not_distinguishable" and r["observed_vs_mdd"] == "below")

        # Fewer than min clusters.
        r = run(tmp, rows[:6])[0]
        check("3 samples: too few clusters", r["status"] == "too_few_clusters")
        # With the leaderboard the pair is compared on the (track, task) ranking metric, the metric the paired-comparison
        # table (aggregate_results.compute_comparisons) uses, so the same pair gives the same mean difference.
        scores, board, out = (os.path.join(tmp, n) for n in ("rs.tsv", "lb.tsv", "rp.tsv"))
        lw = {"A": [0.9, 0.8, 0.7, 0.95, 0.6, 0.85], "B": [0.5, 0.6, 0.4, 0.7, 0.3, 0.65]}
        with open(scores, "w") as fh:
            fh.write("sample\ttool\tanalysis_track\tf1\tlw_bin_f1\n")
            for tool, values in lw.items():
                for i, v in enumerate(values):
                    fh.write(f"s{i}\t{tool}\tshort_read\t0.99\t{v}\n")
        with open(board, "w") as fh:
            fh.write("analysis_track\ttask\ttool\tranking_metric\n")
            for tool in lw:
                fh.write(f"short_read\treconstruction\t{tool}\tlw_bin_f1\n")
        done = subprocess.run([sys.executable, SCRIPT, "--scores", scores, "--leaderboard", board, "--out", out],
                              capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        r = list(csv.DictReader(open(out, newline=""), delimiter="\t"))[0]
        want = statistics.mean(a - b for a, b in zip(lw["A"], lw["B"]))
        check("ranking metric named in the table and its mean difference equals the paired mean of that metric",
              r["metric"] == "lw_bin_f1" and r["task"] == "reconstruction" and abs(float(r["mean_difference"]) - want) < 1e-5)
    print("ALL POWER ANALYSIS TESTS PASSED" if ok else "POWER ANALYSIS TESTS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
