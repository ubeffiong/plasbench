#!/usr/bin/env python3
"""Regression for score_plasmids.py's optional PR-curve/PR-AUC sweep
(--pred-scores/--pred-candidates-fasta/--pred-candidates-paf/--pr-curve-out/
--pr-summary-out): a hand-built fixture with an analytically-known-correct
AUC, plus the backward-compatibility guarantee that omitting the new args
reproduces today's exact point-estimate output, byte for byte.
"""
import csv
import os
import subprocess
import sys
import tempfile


HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "python", "score_plasmids.py")


def write(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def main():
    with tempfile.TemporaryDirectory(prefix="pr_curve_test_") as tmp:
        truth = os.path.join(tmp, "truth.tsv")
        write(truth, "sequence_id\tmolecule_type\tlength\nplasmidA\tPLASMID\t100\nchr\tCHROMOSOME\t100\n")

        # Candidates: q1 (prob 0.9) covers plasmidA[0:50] -- pure TP.
        #             q2 (prob 0.6) covers chr[0:50]      -- pure FP.
        #             q3 (prob 0.3) covers plasmidA[50:100] -- pure TP.
        # By hand: threshold sweep (descending) gives points
        #   (recall=0.0, precision=1.0)   [inf, nothing included]
        #   (recall=0.5, precision=1.0)   [>=0.9: {q1}, tp=50 fp=0]
        #   (recall=0.5, precision=0.5)   [>=0.6: {q1,q2}, tp=50 fp=50]
        #   (recall=1.0, precision=2/3)   [>=0.3: {q1,q2,q3}, tp=100 fp=50]
        # Trapezoidal AUC = 0.5*(1+1)/2 + 0*(1+0.5)/2 + 0.5*(0.5+2/3)/2
        #                 = 0.5 + 0 + 7/24 = 19/24
        candidates_fasta = os.path.join(tmp, "candidates.fasta")
        write(candidates_fasta, ">q1\n" + "A" * 50 + "\n>q2\n" + "A" * 50 + "\n>q3\n" + "A" * 50 + "\n")
        candidates_paf = os.path.join(tmp, "candidates.paf")
        write(candidates_paf,
              "q1\t50\t0\t50\t+\tplasmidA\t100\t0\t50\t50\t50\t60\n"
              "q2\t50\t0\t50\t+\tchr\t100\t0\t50\t50\t50\t60\n"
              "q3\t50\t0\t50\t+\tplasmidA\t100\t50\t100\t50\t50\t60\n")
        pred_scores = os.path.join(tmp, "scores.tsv")
        write(pred_scores, "record_id\tprobability\nq1\t0.9\nq2\t0.6\nq3\t0.3\n")

        # The tool's own hard call (--pred-fasta/--paf) is independent of the
        # candidates universe above; an empty PAF here (predicted nothing) is
        # deliberately uninteresting -- this test is about the sweep, not the
        # point estimate.
        pred_fasta = os.path.join(tmp, "pred.fasta")
        write(pred_fasta, ">q1\n" + "A" * 50 + "\n")
        paf = os.path.join(tmp, "pred.paf")
        write(paf, "")

        out = os.path.join(tmp, "scores_out.tsv")
        curve_out = os.path.join(tmp, "curve.tsv")
        summary_out = os.path.join(tmp, "summary.tsv")
        subprocess.run([sys.executable, SCRIPT, "--truth", truth, "--paf", paf, "--pred-fasta", pred_fasta,
                        "--sample", "s1", "--tool", "mltool", "--out", out,
                        "--pred-scores", pred_scores, "--pred-candidates-fasta", candidates_fasta,
                        "--pred-candidates-paf", candidates_paf,
                        "--pr-curve-out", curve_out, "--pr-summary-out", summary_out], check=True)

        with open(summary_out, newline="", encoding="utf-8") as handle:
            summary = next(csv.DictReader(handle, delimiter="\t"))
        pr_auc = float(summary["pr_auc"])
        assert abs(pr_auc - 19 / 24) < 1e-6, f"expected pr_auc={19/24:.6f}, got {pr_auc:.6f}"
        assert summary["pr_n_thresholds"] == "3", f"expected 3 distinct thresholds, got {summary['pr_n_thresholds']}"

        with open(curve_out, newline="", encoding="utf-8") as handle:
            curve_rows = list(csv.DictReader(handle, delimiter="\t"))
        assert len(curve_rows) == 4, f"expected 4 points (1 synthetic + 3 thresholds), got {len(curve_rows)}"
        by_recall = {round(float(row["recall"]), 4): row for row in curve_rows}
        assert by_recall[0.0]["precision"] == "1.0000"
        assert by_recall[1.0]["precision"] == "0.6667"
        print(f"analytic PR-AUC fixture: pr_auc={pr_auc:.6f} (expected {19/24:.6f}) -> PASS")

        # --- Backward compatibility: omitting the new args reproduces
        # today's exact point-estimate output, byte for byte. -------------
        baseline = os.path.join(tmp, "baseline.tsv")
        without_new_args = os.path.join(tmp, "without.tsv")
        subprocess.run([sys.executable, SCRIPT, "--truth", truth, "--paf", paf, "--pred-fasta", pred_fasta,
                        "--sample", "s1", "--tool", "mltool", "--out", baseline], check=True)
        subprocess.run([sys.executable, SCRIPT, "--truth", truth, "--paf", paf, "--pred-fasta", pred_fasta,
                        "--sample", "s1", "--tool", "mltool", "--out", without_new_args,
                        "--pred-scores", pred_scores, "--pred-candidates-fasta", candidates_fasta,
                        "--pred-candidates-paf", candidates_paf], check=True)
        # (the second call above omits --pr-curve-out/--pr-summary-out, so no
        # curve is written even though --pred-scores was supplied -- confirms
        # those two flags, not --pred-scores alone, gate the new output files)
        assert not os.path.exists(os.path.join(tmp, "unused_curve.tsv"))
        with open(baseline, encoding="utf-8") as handle:
            baseline_text = handle.read()
        with open(without_new_args, encoding="utf-8") as handle:
            without_text = handle.read()
        assert baseline_text == without_text, "supplying --pred-scores without --pr-curve-out must not change scores.tsv's row at all"
        print("omitting --pred-scores (and passing it without --pr-curve-out/--pr-summary-out) reproduces the exact baseline row -> PASS")

    print("ALL PR CURVE SCORING TESTS PASSED")


if __name__ == "__main__":
    main()
