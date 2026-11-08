#!/usr/bin/env python3
"""Recommender evaluation (python/evaluate_recommender.py) and warning scoring
(python/evaluate_warnings.py), on a hand-built cohort.

Cohort: 3 studies x 2 isolates; organism E on studies A,B,C first isolate,
organism K on the second. Tool X is best on E (0.9 vs 0.5), tool Y best on K
(0.8 vs 0.4). Over all isolates X averages 0.65, Y 0.65 -> single best is X
(tie broken by name). With --min-train-samples 2 the organism stratum always
has 2 training isolates per tool, so the recommender picks X on E and Y on K:
  recommender regret 0 everywhere; single-best regret 0 on E, 0.4 on K
  -> single_best_mean_regret 0.2, gap_closed 1.0, oracle gap 0.85 - 0.65 = 0.2
  -> verdict recommender_adds_value; near-optimal 1.0, top-1 1.0
A second cohort where one tool is best everywhere has oracle gap 0 -> benchmark_only.
Warnings: a fired warning on the two K isolates is checked against failed
recommendations of the single best (regret 0.4 > 0.10).
"""
import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write_inputs(tmp, values):
    sheet = "sample_id\tsource_study\torganism\n"
    scores = "sample\ttool\tf1\n"
    for study in "ABC":
        for organism in "EK":
            sample = f"{study}{organism}"
            sheet += f"{sample}\t{study}\t{organism}\n"
            for tool, value in values[organism].items():
                scores += f"{sample}\t{tool}\t{value}\n"
    (tmp / "samples.tsv").write_text(sheet)
    (tmp / "scores.tsv").write_text(scores)


def run(tmp, *extra):
    subprocess.run([sys.executable, str(ROOT / "python" / "evaluate_recommender.py"), "--scores", str(tmp / "scores.tsv"),
                    "--samples", str(tmp / "samples.tsv"), "--out-prefix", str(tmp / "b"), "--min-train-samples", "2",
                    *extra], check=True, capture_output=True)
    with open(tmp / "b.recommender_eval.tsv", newline="") as handle:
        return next(r for r in csv.DictReader(handle, delimiter="\t") if r["profile"] == "f1")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        write_inputs(tmp, {"E": {"X": 0.9, "Y": 0.5}, "K": {"X": 0.4, "Y": 0.8}})
        row = run(tmp)
        assert row["mean_regret"] == "0.0000" and row["single_best_mean_regret"] == "0.2000", row
        assert row["gap_closed"] == "1.0000" and row["oracle_gap"] == "0.2000", row
        assert row["near_optimal_rate"] == "1.0000" and row["top1_rate"] == "1.0000", row
        assert row["verdict"] == "recommender_adds_value" and row["n_folds"] == "3", row
        verdict = json.loads((tmp / "b.recommender_verdict.json").read_text())
        assert verdict["verdict"] == "recommender_adds_value"
        print("  PASS: organism-aware recommender: regret 0, single-best regret 0.2, gap closed 1.0, adds value")

        (tmp / "extra.tsv").write_text("sample\twarning\tfired\tvalidity_limit_applies\n"
                                       "AE\tdemo\tno\tno\nAK\tdemo\tyes\tno\nBE\tdemo\tyes\tno\nBK\tdemo\tyes\tno\n"
                                       "CE\tdemo\tno\tyes\nCK\tdemo\tno\tno\n")
        # Score the warning against single-best failures: rewrite regret with single_best_regret.
        with open(tmp / "b.recommender_regret.tsv", newline="") as handle:
            regret_rows = list(csv.DictReader(handle, delimiter="\t"))
        for r in regret_rows:
            r["regret"] = r["single_best_regret"]
        with open(tmp / "sb_regret.tsv", "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(regret_rows[0]), delimiter="\t")
            writer.writeheader()
            writer.writerows(regret_rows)
        subprocess.run([sys.executable, str(ROOT / "python" / "evaluate_warnings.py"), "--regret", str(tmp / "sb_regret.tsv"),
                        "--warnings", str(tmp / "extra.tsv"), "--out-prefix", str(tmp / "w")], check=True, capture_output=True)
        with open(tmp / "w.warning_eval.tsv", newline="") as handle:
            demo = next(csv.DictReader(handle, delimiter="\t"))
        # evaluated: AE AK BE BK CK (CE validity limit) ; failed: AK BK CK ; fired: AK BE BK
        assert demo["n_evaluated"] == "5" and demo["n_could_not_be_applied"] == "1", demo
        assert demo["ppv"] == "0.6667" and demo["sensitivity"] == "0.6667" and demo["firing_rate"] == "0.6000", demo
        print("  PASS: warning PPV 2/3, sensitivity 2/3, firing rate 3/5, 1 isolate could not be applied")

        write_inputs(tmp, {"E": {"X": 0.9, "Y": 0.5}, "K": {"X": 0.8, "Y": 0.4}})
        row = run(tmp)
        assert row["oracle_gap"] == "0.0000" and row["verdict"] == "benchmark_only", row
        print("  PASS: one tool best everywhere -> oracle gap 0 < 0.02 -> benchmark_only")

        write_inputs(tmp, {"E": {"X": 0.3, "Y": 0.2}, "K": {"X": 0.35, "Y": 0.1}})
        row = run(tmp)
        assert row["floor_flagged"] == "6" and row["floor_true_best_below_floor"] == "1.0000", row
        print("  PASS: predicted score < 0.40 flags every isolate; the true best was below the floor on all of them")
    print("ALL RECOMMENDER EVALUATION TESTS PASSED")


if __name__ == "__main__":
    main()
