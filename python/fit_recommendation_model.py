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
import hashlib
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recommendation_model import (  # noqa: E402
    RecommendationModel, TARGETS, attach_assembly_stats, encode_row, fit_feature_spec,
    load_assembly_stats, mean_absolute_error, solve_ridge,
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


def select_lambda_loso(rows, studies, target):
    """Select a ridge penalty using only the supplied rows and studies."""
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
        return None, None
    return best_lambda, best_mae


def baseline_loso_mae(rows, studies, target):
    """Evaluate the fixed-weight baseline over the supplied study folds."""
    baseline_predicted, baseline_actual = [], []
    for held_samples in studies.values():
        training_rows = [row for row in rows if row["sample"] not in held_samples]
        held_rows = [row for row in rows if row["sample"] in held_samples]
        if not training_rows or not held_rows:
            continue
        baseline_predicted.extend(baseline_predict(training_rows, held_rows, target))
        baseline_actual.extend(target_value(row, target) for row in held_rows)
    return mean_absolute_error(baseline_predicted, baseline_actual) if baseline_predicted else None


def leave_one_study_out(rows, studies, target):
    """Legacy approximate LOSO validation.

    The same outer folds choose lambda and estimate performance, which is
    useful on small cohorts but optimistically biased.  Callers must label it
    as approximate and must not describe it as an unbiased holdout estimate.
    """
    best_lambda, best_mae = select_lambda_loso(rows, studies, target)
    if best_lambda is None:
        return None, None, None
    return best_lambda, best_mae, baseline_loso_mae(rows, studies, target)


def nested_leave_one_study_out(rows, studies, target):
    """Outer LOSO evaluation with an inner study-level lambda selection.

    Each outer study is never used to choose its penalty or estimate its
    prediction error.  The final full-cohort lambda is selected separately
    after this evaluation solely for fitting the deployable artifact.
    """
    predicted, actual, baseline_predicted, selected_lambdas = [], [], [], []
    for held_study, held_samples in studies.items():
        training_studies = {name: samples for name, samples in studies.items() if name != held_study}
        training_rows = [row for row in rows if row["sample"] not in held_samples]
        held_rows = [row for row in rows if row["sample"] in held_samples]
        if len(training_studies) < 2 or not training_rows or not held_rows:
            continue
        lambda_, _ = select_lambda_loso(training_rows, training_studies, target)
        if lambda_ is None:
            continue
        spec = fit_feature_spec(training_rows)
        try:
            predicted.extend(fold_predict(training_rows, held_rows, target, spec, lambda_))
        except ValueError:
            continue
        baseline_predicted.extend(baseline_predict(training_rows, held_rows, target))
        actual.extend(target_value(row, target) for row in held_rows)
        selected_lambdas.append(lambda_)
    if not predicted:
        return None, None, None, []
    return (mean_absolute_error(predicted, actual),
            mean_absolute_error(baseline_predicted, actual), None, selected_lambdas)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_model_card(path, payload, score_path, sample_sheet, rows):
    """Write a reviewable companion artifact for every fitted-model attempt."""
    validation = payload.get("validation", {})
    observed = {}
    for field in ("organism", "gram_group", "analysis_track", "source_study"):
        values = sorted({str(row.get(field) or "not_recorded") for row in rows})
        observed[field] = ", ".join(values) if values else "not_recorded"
    lines = [
        "# PlasBench recommendation model card", "",
        "## Release status", "",
        f"- **Model ready:** {'yes' if payload.get('model_ready') else 'no'}",
        f"- **Decision:** {payload.get('reason', 'not recorded')}",
        f"- **Validation strategy:** {validation.get('strategy', 'not run')}",
        f"- **Validation claim:** {validation.get('claim', 'not recorded')}", "",
        "## Training cohort snapshot", "",
        f"- **Training rows:** {payload.get('n_training_rows', 0)}",
        f"- **Independent source studies:** {payload.get('n_studies', 0)}",
        f"- **Fit minimums:** {validation.get('min_training_samples', 'not recorded')} rows; {validation.get('min_studies', 'not recorded')} studies; {validation.get('min_relative_improvement', 'not recorded')} relative MAE improvement",
        f"- **Nested-validation threshold:** {validation.get('nested_min_training_samples', 'not recorded')} rows; {validation.get('nested_min_studies', 'not recorded')} studies",
        f"- **Scores input SHA-256:** `{sha256(score_path)}`",
        f"- **Sample sheet SHA-256:** `{sha256(sample_sheet)}`",
        f"- **Observed organisms:** {observed['organism']}",
        f"- **Observed Gram groups:** {observed['gram_group']}",
        f"- **Observed analysis tracks:** {observed['analysis_track']}",
        f"- **Observed source studies:** {observed['source_study']}", "",
        "## Validation results", "",
        "| Target | Final lambda | Model MAE | Fixed-weight baseline MAE |", "|---|---:|---:|---:|",
    ]
    for target, info in sorted(payload.get("targets", {}).items()):
        lines.append("| {target} | {lambda_} | {mae} | {baseline} |".format(
            target=target, lambda_=info.get("lambda", "not fitted"),
            mae=info.get("loso_mean_absolute_error", "not assessed"),
            baseline=info.get("baseline_loso_mean_absolute_error", "not assessed")))
    lines += ["", "## Scope and limitations", "",
              "- This is decision support, not a plasmid reconstruction score or clinical validation.",
              "- Coverage is limited to the observed cohort categories above; unseen organisms, tracks, studies, and feature ranges are not validated.",
              "- Missing continuous features are imputed from the training mean; unseen categorical values use the model intercept fallback.",
              "- A model-ready artifact may be used only with the accompanying cohort, threshold, and confirmation safeguards in PlasBench."]
    if validation.get("strategy") == "approximate_loso":
        lines += ["- **Important:** lambda was selected on the same LOSO folds used for the reported MAE. This is a small-cohort approximation and its improvement estimate may be optimistic; it is not an unbiased nested-validation result."]
    else:
        lines += ["- Lambda selection occurred inside each outer held-study fold. The reported outer-fold MAE is a nested-validation estimate, but remains limited by cohort size and representativeness."]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scores", required=True)
    ap.add_argument("--sample-sheet", required=True)
    ap.add_argument("--data-dir", help="Cohort data directory; per-sample assembly_stats.tsv (stage 2) "
                                       "is joined onto the training rows as extra continuous features. "
                                       "Omit and those features are simply absent.")
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-studies", type=int, default=3)
    ap.add_argument("--min-training-samples", type=int, default=20)
    ap.add_argument("--min-relative-improvement", type=float, default=0.05,
                    help="the model's LOSO MAE must be at least this fraction below the fixed-weight baseline's, for every target")
    ap.add_argument("--nested-min-training-samples", type=int, default=60,
                    help="use unbiased nested LOSO only at or above this many training rows (default: 60)")
    ap.add_argument("--nested-min-studies", type=int, default=5,
                    help="use unbiased nested LOSO only at or above this many source studies (default: 5)")
    ap.add_argument("--model-card", help="Markdown model-card path (default: <out>.card.md)")
    args = ap.parse_args()

    metadata = sample_metadata(args.sample_sheet)
    raw_scores = read_tsv(args.scores)
    for row in raw_scores:
        if row.get("sample") and row["sample"] not in metadata:
            metadata[row["sample"]] = {"sample_id": row["sample"]}
    rows = [annotate(row, metadata) for row in raw_scores]
    attach_assembly_stats(rows, load_assembly_stats(args.data_dir))
    studies = group_samples_by_study(rows, metadata)

    reasons = []
    if len(studies) < args.min_studies:
        reasons.append(f"only {len(studies)} source_study group(s); at least {args.min_studies} required")
    if len(rows) < args.min_training_samples:
        reasons.append(f"only {len(rows)} training row(s); at least {args.min_training_samples} required")

    nested = len(rows) >= args.nested_min_training_samples and len(studies) >= args.nested_min_studies
    validation = {
        "strategy": "nested_loso" if nested else "approximate_loso",
        "claim": ("Outer held-study estimate; lambda is selected only inside each training fold."
                  if nested else
                  "Small-cohort approximation: lambda is selected on the same LOSO folds used to estimate MAE; improvement may be optimistic."),
        "nested_min_training_samples": args.nested_min_training_samples,
        "nested_min_studies": args.nested_min_studies,
        "min_training_samples": args.min_training_samples,
        "min_studies": args.min_studies,
        "min_relative_improvement": args.min_relative_improvement,
    }
    lambda_by_target, loso_mae, baseline_mae = {}, {}, {}
    if not reasons:
        for target in TARGETS:
            final_lambda, _ = select_lambda_loso(rows, studies, target)
            if nested:
                mae, baseline, _, selected_lambdas = nested_leave_one_study_out(rows, studies, target)
                validation.setdefault("outer_fold_lambdas", {})[target] = selected_lambdas
            else:
                _, mae, baseline = leave_one_study_out(rows, studies, target)
            if final_lambda is None or mae is None or baseline is None:
                reasons.append(f"leave-one-study-out produced no held-out predictions for {target}")
                continue
            lambda_by_target[target], loso_mae[target], baseline_mae[target] = final_lambda, mae, baseline
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
        payload["validation"] = validation
    else:
        payload = {
            "schema_version": "1.2", "model_ready": False, "reason": "; ".join(reasons),
            "n_training_rows": len(rows), "n_studies": len(studies), "spec": None, "targets": {}, "validation": validation,
        }

    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(f"Wrote recommendation model: {args.out} (model_ready={model_ready})")
    card_path = args.model_card or str(Path(args.out).with_suffix(".card.md"))
    write_model_card(card_path, payload, args.scores, args.sample_sheet, rows)
    print(f"Wrote recommendation model card: {card_path}")


if __name__ == "__main__":
    main()
