#!/usr/bin/env python3
"""Regression checks for the CPRR endpoint additions.

1. score_bins.py writes per-threshold correct counts (the CPRR threshold sweep).
2. aggregate_results.py ranks long-read and hybrid reconstruction on isolate-level
   CPRR, keeps short-read reconstruction on lw_bin_f1, and reports the
   isolate-weighted CPRR, the sweep AUC and the sweep table.
3. stratify_recovery.py reports CPRR per stratum, honouring the identity rule.
"""

import csv
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(HERE, "..", "python")
sys.path.insert(0, PY)

from plasbench_common import CPRR_SWEEP_THRESHOLDS, cprr_sweep_auc  # noqa: E402


def run(args):
    done = subprocess.run([sys.executable] + args, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done


def write(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        handle.write(text)


def read(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def test_grid_and_auc():
    assert CPRR_SWEEP_THRESHOLDS[0] == 0.80 and CPRR_SWEEP_THRESHOLDS[-1] == 0.99
    assert len(CPRR_SWEEP_THRESHOLDS) == 20
    assert abs(cprr_sweep_auc([0.5] * 20) - 0.5) < 1e-12
    # A step from 1 to 0 between 0.90 and 0.91: area = 0.10 + 0.005 over a 0.19 range.
    step = [1.0 if t <= 0.90 else 0.0 for t in CPRR_SWEEP_THRESHOLDS]
    assert abs(cprr_sweep_auc(step) - 0.105 / 0.19) < 1e-9
    assert cprr_sweep_auc([0.5] * 19 + [None]) is None
    assert cprr_sweep_auc([0.5] * 5) is None


def test_score_bins_sweep(tmp):
    os.chdir(tmp)
    write("truth.tsv", "sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t100000\n"
                       "p1\tPLASMID\t10000\np2\tPLASMID\t2000\n")
    write("bins.tsv", "sequence_id\tbin_id\nc1\tB1\nc2\tB2\n")
    # p1: whole, 98% identity (fails identity only). p2: 90% covered, 100% identity.
    write("a.paf", "c1\t10000\t0\t10000\t+\tp1\t10000\t0\t10000\t9800\t10000\t60\n"
                   "c2\t1800\t0\t1800\t+\tp2\t2000\t0\t1800\t1800\t1800\t60\n")
    run([os.path.join(PY, "score_bins.py"), "--truth", "truth.tsv", "--paf", "a.paf", "--bins", "bins.tsv",
         "--out", "m.tsv", "--summary", "s.tsv", "--cprr-out", "c.tsv"])
    summary = read("s.tsv")[0]
    with_identity = [int(v) for v in summary["cprr_sweep_correct"].split(",")]
    without_identity = [int(v) for v in summary["cprr_sweep_correct_without_identity"].split(",")]
    expected_without = [2 if t <= 0.90 else 1 for t in CPRR_SWEEP_THRESHOLDS]
    expected_with = [1 if t <= 0.90 else 0 for t in CPRR_SWEEP_THRESHOLDS]
    assert without_identity == expected_without, without_identity
    assert with_identity == expected_with, with_identity
    # The configured 0.95 verdict is unchanged and agrees with the sweep at 0.95.
    assert (summary["cprr_correct"], summary["cprr_correct_without_identity"]) == ("0", "1")
    # Raw sweep helper values never leak into the per-plasmid TSV.
    assert not any(key.startswith("_") for key in read("c.tsv")[0])


def sweep(correct_from):
    """Counts that are `n` up to threshold `correct_from`, 0 after (as a comma list)."""
    return lambda n: ",".join(str(n if t < correct_from else 0) for t in CPRR_SWEEP_THRESHOLDS)


def test_long_read_ranked_on_cprr(tmp):
    os.chdir(tmp)
    samples = [f"s{i}" for i in range(1, 6)]
    write("sheet.tsv", "sample_id\torganism\tbioproject\n" + "".join(f"{s}\tEscherichia coli\tPRJ{s}\n"
                                                                      for s in samples))
    write("caps.tsv", "tool\tmethod_class\tbinning_capable\tanalysis_track\n"
                      "lr_a\tbinning\tyes\tlong_read\nlr_b\tbinning\tyes\tlong_read\n"
                      "sr_a\tbinning\tyes\tshort_read\nsr_b\tbinning\tyes\tshort_read\n")
    header = ["sample", "tool", "analysis_track", "true_plasmid_count", "precision", "recall", "f1",
              "lw_bin_f1", "cprr_plasmids", "cprr_correct", "cprr_correct_without_identity",
              "cprr_sweep_correct", "cprr_sweep_correct_without_identity"]
    rows = []
    for s in samples:
        many = s == "s1"                       # s1 carries 3 plasmids, the rest 1
        n = 3 if many else 1
        # lr_a: high binning F1 but recovers whole plasmids only on s1 (3/7 pooled, 1/5 per isolate).
        a_correct = 3 if many else 0
        rows.append([s, "lr_a", "long_read", n, 0.9, 0.9, 0.9, 0.95, n, a_correct, a_correct,
                     sweep(0.96)(a_correct), sweep(0.96)(a_correct)])
        # lr_b: lower binning F1 but one whole plasmid on every isolate except s1 (4/7, 4/5).
        b_correct = 0 if many else 1
        rows.append([s, "lr_b", "long_read", n, 0.9, 0.9, 0.9, 0.60, n, b_correct, b_correct,
                     sweep(0.96)(b_correct), sweep(0.96)(b_correct)])
        # Short-read pair with the same pattern: must stay ranked on lw_bin_f1.
        rows.append([s, "sr_a", "short_read", n, 0.9, 0.9, 0.9, 0.95, n, a_correct, a_correct, "", ""])
        rows.append([s, "sr_b", "short_read", n, 0.9, 0.9, 0.9, 0.60, n, b_correct, b_correct, "", ""])
    with open("scores.tsv", "w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    run([os.path.join(PY, "aggregate_results.py"), "--scores", "scores.tsv", "--sample-sheet", "sheet.tsv",
         "--capabilities", "caps.tsv", "--out-prefix", "b"])
    board = {r["tool"]: r for r in read("b.leaderboard.tsv")}
    assert board["lr_a"]["ranking_metric"] == "sample_cprr" and board["lr_b"]["ranking_metric"] == "sample_cprr"
    assert board["lr_b"]["rank"] == "1" and board["lr_b"]["ranking_score"] == "0.8000", board["lr_b"]
    assert board["lr_a"]["ranking_score"] == "0.2000"
    assert board["sr_a"]["ranking_metric"] == "lw_bin_f1" and board["sr_a"]["rank"] == "1"
    # Pooled vs isolate-weighted CPRR differ when one isolate carries many plasmids.
    assert board["lr_a"]["cprr"] == "0.4286" and board["lr_a"]["cprr_isolate_mean"] == "0.2000"
    assert board["lr_a"]["cprr_isolates"] == "5"
    # Sweep: correct up to 0.95, zero from 0.96 -> AUC of a step curve.
    rates = [3 / 7 if t < 0.96 else 0.0 for t in CPRR_SWEEP_THRESHOLDS]
    assert board["lr_a"]["cprr_auc"] == f"{cprr_sweep_auc(rates):.4f}", board["lr_a"]["cprr_auc"]
    assert board["sr_a"]["cprr_auc"] == ""          # no sweep columns: never reported as 0
    sweep_rows = [r for r in read("b.cprr_threshold_sweep.tsv") if r["tool"] == "lr_a"]
    assert len(sweep_rows) == 20 and sweep_rows[0]["threshold"] == "0.80"
    assert sweep_rows[0]["cprr"] == "0.4286" and sweep_rows[-1]["cprr"] == "0.0000"
    assert sweep_rows[0]["cprr_isolate_mean"] == "0.2000"
    design = {r["analysis_track"]: r["ranking_metric"] for r in read("b.headline_design.tsv")}
    assert design == {"short_read": "lw_bin_f1", "long_read": "sample_cprr"}, design
    tiers = read("b.reference_tiers.tsv")
    assert any(r["tool"] == "lr_a" and r["cprr"] == "0.4286" for r in tiers)


def test_stratified_cprr(tmp):
    results, data = os.path.join(tmp, "results"), os.path.join(tmp, "data")
    for sample in ("s1", "s2"):
        os.makedirs(os.path.join(data, sample), exist_ok=True)
    write(os.path.join(results, "s1", "toolA.per_plasmid.tsv"),
          "sample\ttool\tanalysis_track\tsequence_id\tlength\tcovered_bp\tcompleteness\trecovered\n"
          "s1\ttoolA\tshort_read\tsmall\t5000\t5000\t1.0000\t1\n"
          "s1\ttoolA\tshort_read\tbig\t80000\t70000\t0.8750\t0\n")
    write(os.path.join(results, "s1", "toolA.cprr.tsv"),
          "true_plasmid\tcorrect_without_identity\tcorrect\nsmall\tyes\tno\nbig\tno\tno\n")
    write(os.path.join(results, "s2", "toolA.per_plasmid.tsv"),
          "sample\ttool\tanalysis_track\tsequence_id\tlength\tcovered_bp\tcompleteness\trecovered\n"
          "s2\ttoolA\tshort_read\tsmall2\t4000\t4000\t1.0000\t1\n")
    write(os.path.join(results, "s2", "toolA.cprr.tsv"),
          "true_plasmid\tcorrect_without_identity\tcorrect\nsmall2\tyes\tyes\n")
    # s1's truth was polished with the benchmark's reads, so identity is dropped there.
    write(os.path.join(tmp, "prov.tsv"), "sample\tbase_level_metrics_valid\ns1\tno\ns2\tyes\n")
    out = os.path.join(tmp, "strat.tsv")
    run([os.path.join(PY, "stratify_recovery.py"), "--results-dir", results, "--data-dir", data,
         "--truth-provenance", os.path.join(tmp, "prov.tsv"), "--out", out])
    bands = {r["label"]: r for r in read(out) if r["feature_type"] == "size_band"}
    assert bands["<10kb"]["cprr"] == "1.0000" and bands["<10kb"]["n_cprr_assessed"] == "2"
    assert bands[">50kb"]["cprr"] == "0.0000"
    # Without provenance the identity criterion applies everywhere: small fails.
    run([os.path.join(PY, "stratify_recovery.py"), "--results-dir", results, "--data-dir", data, "--out", out])
    bands = {r["label"]: r for r in read(out) if r["feature_type"] == "size_band"}
    assert bands["<10kb"]["cprr"] == "0.5000"


def main():
    test_grid_and_auc()
    for test in (test_score_bins_sweep, test_long_read_ranked_on_cprr, test_stratified_cprr):
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                test(tmp)
            finally:
                os.chdir(cwd)
    print("test_cprr_robustness: all checks passed")


if __name__ == "__main__":
    main()
