#!/usr/bin/env python3
"""Regression for python/fit_recommendation_model.py's model_ready gate:
too-few-studies -> not ready; enough data but no real signal -> not ready
(never "ready" on a technicality that's actually worse than the mean);
enough data with a planted real signal -> ready, and the reported LOSO MAE
is genuinely below the fixed-weight baseline's."""

import csv
import json
import os
import random
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SCRIPT = os.path.join(ROOT, "python", "fit_recommendation_model.py")

SAMPLE_FIELDS = ["sample_id", "organism", "gram_group", "read_depth_x", "source_study"]
SCORE_FIELDS = ["sample", "tool", "f1", "precision", "recall", "true_plasmid_bp", "true_plasmid_count", "true_amr_gene_count"]


def write_fixture(tmp, sample_rows, score_rows):
    sheet = os.path.join(tmp, "sheet.tsv")
    scores = os.path.join(tmp, "scores.tsv")
    with open(sheet, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SAMPLE_FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerows(sample_rows)
    with open(scores, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCORE_FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerows(score_rows)
    return sheet, scores


def run_fit(tmp, sheet, scores, **kwargs):
    out = os.path.join(tmp, "model.json")
    args = [sys.executable, SCRIPT, "--scores", scores, "--sample-sheet", sheet, "--out", out]
    for key, value in kwargs.items():
        args += [f"--{key.replace('_', '-')}", str(value)]
    subprocess.run(args, check=True, capture_output=True, text=True)
    with open(out, encoding="utf-8") as handle:
        return json.load(handle)


def make_cohort(n_studies, per_study, f1_of_depth, noise, seed):
    rng = random.Random(seed)
    sample_rows, score_rows, sid = [], [], 0
    for study in range(n_studies):
        for _ in range(per_study):
            sid += 1
            sample = f"s{sid}"
            depth = 10 + sid * 3
            f1 = min(0.99, max(0.01, f1_of_depth(depth) + rng.uniform(-noise, noise)))
            sample_rows.append({"sample_id": sample, "organism": "E. coli", "gram_group": "negative",
                                "read_depth_x": str(depth), "source_study": f"study{study}"})
            score_rows.append({"sample": sample, "tool": "toolA", "f1": f"{f1:.4f}",
                               "precision": f"{f1:.4f}", "recall": f"{f1:.4f}",
                               "true_plasmid_bp": "10000", "true_plasmid_count": "2", "true_amr_gene_count": "0"})
    return sample_rows, score_rows


def main():
    with tempfile.TemporaryDirectory(prefix="fit_model_too_few_") as tmp:
        sample_rows, score_rows = make_cohort(2, 3, lambda d: 0.8, 0.02, seed=1)
        sheet, scores = write_fixture(tmp, sample_rows, score_rows)
        payload = run_fit(tmp, sheet, scores, min_studies=3, min_training_samples=20)
        assert payload["model_ready"] is False
        assert "source_study group" in payload["reason"]
        assert "training row" in payload["reason"]
        print("too few studies and too few training rows -> not ready, reason names both gates -> PASS")

    with tempfile.TemporaryDirectory(prefix="fit_model_no_signal_") as tmp:
        sample_rows, score_rows = make_cohort(5, 6, lambda d: 0.8, 0.05, seed=7)  # depth carries no signal
        sheet, scores = write_fixture(tmp, sample_rows, score_rows)
        payload = run_fit(tmp, sheet, scores, min_studies=3, min_training_samples=20, min_relative_improvement=0.05)
        assert payload["model_ready"] is False, payload["reason"]
        assert "does not beat the fixed-weight baseline" in payload["reason"]
        print("enough data but no real feature signal -> not ready (never worse-than-baseline 'ready') -> PASS")

    with tempfile.TemporaryDirectory(prefix="fit_model_signal_") as tmp:
        sample_rows, score_rows = make_cohort(5, 6, lambda d: min(0.99, 0.5 + 0.01 * d), 0.01, seed=42)
        sheet, scores = write_fixture(tmp, sample_rows, score_rows)
        payload = run_fit(tmp, sheet, scores, min_studies=3, min_training_samples=20, min_relative_improvement=0.05)
        assert payload["model_ready"] is True, payload["reason"]
        f1_target = payload["targets"]["f1"]
        assert f1_target["loso_mean_absolute_error"] < f1_target["baseline_loso_mean_absolute_error"], f1_target
        assert "model-fitted" in payload["reason"]
        print("enough data with a planted real signal -> ready, LOSO MAE genuinely beats the baseline -> PASS")

    print("ALL FIT RECOMMENDATION MODEL TESTS PASSED")


if __name__ == "__main__":
    main()
