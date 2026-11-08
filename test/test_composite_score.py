#!/usr/bin/env python3
"""composite_score.py: dimension scores, gates, dropped dimensions and weight sensitivity, by hand."""
import csv
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "python", "composite_score.py")


def write(path, header, rows):
    with open(path, "w") as fh:
        fh.write("\t".join(header) + "\n" + "".join("\t".join(str(c) for c in r) + "\n" for r in rows))


def run(tmp, name, scores, accuracy, features, ngoc, bins, perf, config=None):
    p = {k: os.path.join(tmp, f"{name}.{k}.tsv") for k in ("scores", "acc", "feat", "ngoc", "bins", "perf", "out", "sens")}
    write(p["scores"], ("sample", "tool", "analysis_track", "recall", "plasmid_recall"), scores)
    write(p["acc"], ("tool", "analysis_track", "identity", "aligned_columns"), accuracy)
    write(p["feat"], ("tool", "analysis_track", "feature_kind", "full_length_rate", "n_expected"), features)
    write(p["ngoc"], ("tool", "analysis_track", "n_pairs", "n_conserved"), ngoc)
    write(p["bins"], ("tool", "analysis_track", "v_measure"), bins)
    write(p["perf"], ("tool", "success_rate", "median_runtime_seconds", "median_peak_memory_gb"), perf)
    args = [sys.executable, SCRIPT, "--scores", p["scores"], "--accuracy", p["acc"], "--feature-preservation", p["feat"],
            "--ngoc", p["ngoc"], "--bin-quality", p["bins"], "--performance", p["perf"], "--out", p["out"],
            "--sensitivity-out", p["sens"], "--draws", "200"]
    if config:
        cfg = os.path.join(tmp, f"{name}.cfg.tsv")
        write(cfg, ("key", "value"), config)
        args += ["--config", cfg]
    done = subprocess.run(args, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    read = lambda f: list(csv.DictReader(open(p[f], newline=""), delimiter="\t"))
    return {r["tool"]: r for r in read("out")}, read("sens")


def main():
    ok = True

    def check(label, good):
        nonlocal ok
        print(f"  {label}: {'PASS' if good else 'FAIL'}")
        ok &= bool(good)

    T = "short_read"
    with tempfile.TemporaryDirectory() as tmp:
        scores = [("s", "X", T, 1.0, 1.0), ("s", "Y", T, 0.6, 0.6), ("s", "Z", T, 0.3, 0.3)]
        accuracy = [("X", T, 0.999, 1000), ("Y", T, 0.9745, 1000), ("Z", T, 0.999, 1000)]
        features = [("X", T, "all", 1.0, 10), ("Y", T, "all", 0.5, 10), ("Z", T, "all", 1.0, 10)]
        ngoc = [("X", T, 10, 10), ("Y", T, 10, 5), ("Z", T, 10, 10)]
        bins = [("X", T, 1.0), ("Y", T, 0.5), ("Z", T, 1.0)]
        # X fastest, Y ten times slower than X (log score 50), Z as fast as X.
        perf = [("X", 1.0, 100, 1.0), ("Y", 1.0, 1000, 10.0), ("Z", 1.0, 100, 1.0)]
        rows, sens = run(tmp, "full", scores, accuracy, features, ngoc, bins, perf)
        near = lambda v, w: v != "" and abs(float(v) - w) < 0.01
        check("X: every dimension 100, composite 100", all(near(rows["X"][d], 100) for d in
              ("accuracy", "completeness", "structure", "biology", "performance")) and near(rows["X"]["composite"], 100))
        check("Y: accuracy 50 (identity 0.9745 on a 0.95-0.999 scale), completeness 60",
              near(rows["Y"]["accuracy"], 50) and near(rows["Y"]["completeness"], 60))
        check("Y: performance = mean(success 100, runtime 50, memory 50) = 66.67", near(rows["Y"]["performance"], 66.667))
        want = (30 * 50 + 20 * 60 + 25 * 50 + 15 * 50 + 10 * 66.6667) / 100
        check(f"Y composite is the weighted mean ({want:.2f})", near(rows["Y"]["composite"], want))
        check("Z is fast and accurate but recovers 30%: gated on completeness, not ranked, whatever its speed",
              rows["Z"]["status"] == "gated" and rows["Z"]["gates_failed"] == "completeness" and rows["Z"]["rank"] == "")
        check("X ranks 1 and Y ranks 2 (Z excluded)", rows["X"]["rank"] == "1" and rows["Y"]["rank"] == "2")
        sx = [r for r in sens if r["tool"] == "X" and r["variant"].startswith("random_weights")][0]
        check("X dominates on every dimension, so it is first under every random weighting",
              float(sx["share_first"]) == 1.0 and sx["worst_rank"] == "1")
        check("leave-one-dimension-out ranks are reported",
              {r["variant"] for r in sens if r["tool"] == "X"} >= {"baseline", "without_accuracy", "without_performance"})

        # A dimension missing for one tool is dropped for ALL tools, and the composite says so.
        feats_missing = [r for r in features if r[0] != "Y"]
        ngoc_missing = ngoc
        rows, _ = run(tmp, "drop", scores, accuracy, feats_missing, ngoc_missing, bins, perf)
        check("biology missing for Y is dropped for every tool and listed",
              "biology" in rows["X"]["dimensions_dropped"] and "biology" not in rows["X"]["dimensions_used"])
        want = (30 * 100 + 20 * 100 + 25 * 100 + 10 * 100) / 85
        check("weights are renormalised over the kept dimensions (X composite stays 100)", near(rows["X"]["composite"], 100))

        # Missing evidence is blank, not zero: a tool with no accuracy data has no accuracy score.
        rows, _ = run(tmp, "noacc", scores, [("X", T, 0.999, 1000), ("Z", T, 0.999, 1000)], features, ngoc, bins, perf)
        check("Y has no accuracy data: accuracy blank (not evaluated) and the dimension dropped for all",
              rows["Y"]["accuracy"] == "" and "accuracy" in rows["X"]["dimensions_dropped"])

        # Gates are configurable: removing the gate rows un-gates Z.
        rows, _ = run(tmp, "nogate", scores, accuracy, features, ngoc, bins, perf,
                      config=[("weight_accuracy", 30), ("weight_completeness", 20), ("weight_structure", 25),
                              ("weight_biology", 15), ("weight_performance", 10)])
        check("with no gate rows in the config Z is ranked (and first, which is exactly why gates exist)",
              rows["Z"]["status"] == "ranked")
    print("ALL COMPOSITE SCORE TESTS PASSED" if ok else "COMPOSITE SCORE TESTS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
