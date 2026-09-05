#!/usr/bin/env python3
"""Fit (and leave-one-study-out validate) the decision-support recommendation
model: a hand-rolled, pure-stdlib ridge regression predicting a tool's F1 and
plasmid_recall from an isolate's own continuous/categorical features, rather
than a discrete stratum mean.

This is a descriptive recommendation, not a scoring change, and is not
validated beyond the cohorts it was fit on -- exactly like every other
recommendation this project produces. It is only ever used by
select_operational_method.py/select_unknown_sample.py when model_ready is
true; otherwise those scripts behave exactly as if this file did not exist.

Always writes the output JSON, ready or not, so downstream scripts have one
unambiguous file to check -- the same "never silently produce nothing"
posture as benchmark.recommendation_validation.tsv.

Usage:
  fit_recommendation_model.py --scores scores.tsv --sample-sheet SHEET \
      --out benchmark.recommendation_model.json \
      [--min-studies 3] [--min-training-samples 20] [--min-relative-improvement 0.05]
"""

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recommendation_model import (  # noqa: E402
    RecommendationModel, TARGETS, encode_row, fit_feature_spec,
    mean_absolute_error, solve_ridge,
)
from select_operational_method import annotate, number, read_tsv, sample_metadata  # noqa: E402
from study_groups import group_samples_by_study  # noqa: E402

LAMBDA_GRID = (0.1, 1.0, 10.0)


def target_value(row, target):
    if target == "f1":
        return number(row, "f1", 0.0)
    return number(row, "plasmid_recall", number(row, "f1", 0.0))


def fold_predict(training_rows, held_rows, target, spec, lambda_):
    features = [encode_row(row, spec) for row in training_rows]
    targets = [target_value(row, target) for row in training_rows]
    intercept, coefficients = solve_ridge(features, targets, lambda_)
    return [intercept + sum(c * v for c, v in zip(coefficients, encode_row(row, spec))) for row in held_rows]


def baseline_predict(training_rows, held_rows, target):
    """The fixed-weight method's implicit prediction: the training studies'
    per-tool mean, applied uniformly to every held-out row of that tool --
    the honest apples-to-apples comparison the model must beat."""
    by_tool = defaultdict(list)
    for row in training_rows:
        by_tool[row["tool"]].append(target_value(row, target))
    overall_mean = statistics.mean(target_value(row, target) for row in training_rows) if training_rows else 0.0
    return [statistics.mean(by_tool[row["tool"]]) if by_tool.get(row["tool"]) else overall_mean for row in held_rows]


def leave_one_study_out(rows, studies, target):
    """Returns (best_lambda, model_mae, baseline_mae), or (None, None, None)
    if no fold produced any held-out predictions (e.g. every study is
    entirely absent from the training run's rows)."""
    best_lambda, best_mae = None, None
    for lambda_ in LAMBDA_GRID:
        predicted, actual = [], []
        for held_samples in studies.values():
            training_rows = [row for row in rows if row["sample"] not in held_samples]
            held_rows = [row for row in rows if row["sample"] in held_samples]
            if not training_rows or not held_rows:
                continue
            spec = fit_feature_spec(training_rows)
            try:
                predicted.extend(fold_predict(training_rows, held_rows, target, spec, lambda_))
            except ValueError:
                continue  # singular fold (too little data for this lambda); skip, try the next
            actual.extend(target_value(row, target) for row in held_rows)
        if not predicted:
            continue
        mae = mean_absolute_error(predicted, actual)
        if best_mae is None or mae < best_mae:
            best_lambda, best_mae = lambda_, mae
    if best_lambda is None:
        return None, None, None
    # Baseline MAE computed once (it doesn't depend on lambda).
    baseline_predicted, baseline_actual = [], []
    for held_samples in studies.values():
        training_rows = [row for row in rows if row["sample"] not in held_samples]
        held_rows = [row for row in rows if row["sample"] in held_samples]
        if not training_rows or not held_rows:
            continue
        baseline_predicted.extend(baseline_predict(training_rows, held_rows, target))
        baseline_actual.extend(target_value(row, target) for row in held_rows)
    baseline_mae = mean_absolute_error(baseline_predicted, baseline_actual)
    return best_lambda, best_mae, baseline_mae


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scores", required=True)
    ap.add_argument("--sample-sheet", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-studies", type=int, default=3)
    ap.add_argument("--min-training-samples", type=int, default=20)
    ap.add_argument("--min-relative-improvement", type=float, default=0.05,
                    help="the model's LOSO MAE must be at least this fraction below the fixed-weight baseline's, for every target")
    args = ap.parse_args()

    metadata = sample_metadata(args.sample_sheet)
    raw_scores = read_tsv(args.scores)
    for row in raw_scores:
        if row.get("sample") and row["sample"] not in metadata:
            metadata[row["sample"]] = {"sample_id": row["sample"]}
    rows = [annotate(row, metadata) for row in raw_scores]
    studies = group_samples_by_study(rows, metadata)

    reasons = []
    if len(studies) < args.min_studies:
        reasons.append(f"only {len(studies)} source_study group(s); at least {args.min_studies} required")
    if len(rows) < args.min_training_samples:
        reasons.append(f"only {len(rows)} training row(s); at least {args.min_training_samples} required")

    lambda_by_target, loso_mae, baseline_mae = {}, {}, {}
    if not reasons:
        for target in TARGETS:
            best_lambda, mae, baseline = leave_one_study_out(rows, studies, target)
            if best_lambda is None:
                reasons.append(f"leave-one-study-out produced no held-out predictions for {target}")
                continue
            lambda_by_target[target], loso_mae[target], baseline_mae[target] = best_lambda, mae, baseline
            if baseline == 0:
                if mae > 0:
                    reasons.append(f"{target}: baseline MAE is exactly 0; model cannot improve on it")
            elif (baseline - mae) / baseline < args.min_relative_improvement:
                reasons.append(
                    f"{target}: model LOSO MAE {mae:.4f} does not beat the fixed-weight baseline's "
                    f"{baseline:.4f} by at least {args.min_relative_improvement:.0%}"
                )

    model_ready = not reasons
    if model_ready:
        spec = fit_feature_spec(rows)
        fits = {}
        for target in TARGETS:
            features = [encode_row(row, spec) for row in rows]
            targets = [target_value(row, target) for row in rows]
            fits[target] = solve_ridge(features, targets, lambda_by_target[target])
        model = RecommendationModel(spec, fits, lambda_by_target, loso_mae, baseline_mae, len(rows), len(studies))
        reason = "model-fitted: " + "; ".join(
            f"{target} LOSO MAE {loso_mae[target]:.4f} vs fixed-weight baseline {baseline_mae[target]:.4f}"
            for target in TARGETS
        )
        payload = model.to_dict(True, reason)
    else:
        payload = {
            "schema_version": "1.0", "model_ready": False, "reason": "; ".join(reasons),
            "n_training_rows": len(rows), "n_studies": len(studies), "spec": None, "targets": {},
        }

    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(f"Wrote recommendation model: {args.out} (model_ready={model_ready})")


if __name__ == "__main__":
    main()
