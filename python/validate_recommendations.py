#!/usr/bin/env python3
"""Leave-one-study-out validation of simple benchmark method rankings.

This is a release safeguard, not a replacement for a pre-registered external
validation study. Each source study is held out, the leading method is selected
on the remaining independent studies, and its held-out mean F1 is reported --
both "overall" (pooled, today's original behavior) and per-stratum, using the
exact same stratification select_operational_method.py's write_recommendations()
already uses (organism, gram_group, plasmid_size_band, plasmid_count_band,
read_depth_band, amr_status, analysis_track, read_quality_band, ...).

select_operational_method.py's own validation_ready gate only ever looks at
the "overall" scope rows here -- a stratum lacking enough training samples in
one fold is a normal, expected not_assessed outcome for THAT stratum, not a
reason to withhold every operational recommendation across the whole cohort.

selection_method is reserved (always "fixed-weight" today) so a future
learned-model comparison row can slot in against the identical fold without
another schema change.
"""

import argparse
import csv
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aggregate_results import bootstrap_ci  # noqa: E402
from select_operational_method import annotate  # noqa: E402
from study_groups import group_samples_by_study  # noqa: E402

FIELDS = ["scope", "group", "held_out_study", "held_out_samples", "selected_method_from_training",
          "training_samples", "held_out_mean_f1", "held_out_f1_ci_low", "held_out_f1_ci_high",
          "selection_method", "status", "note"]

# Mirrors select_operational_method.py's write_recommendations() scope list
# exactly, so a stratum here is directly comparable to the same stratum's row
# in benchmark.recommendations.tsv.
STRATA = ("organism", "gram_group", "truth_technology", "sample_origin", "collection_country",
          "plasmid_size_band", "plasmid_count_band", "read_depth_band", "amr_status",
          "analysis_track", "read_quality_band")


def rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader((line for line in handle if line.strip() and not line.lstrip().startswith("#")), delimiter="\t"))


def withheld_row(scope, group, note):
    return {"scope": scope, "group": group, "held_out_study": "", "held_out_samples": "0",
            "selected_method_from_training": "", "training_samples": "0", "held_out_mean_f1": "",
            "held_out_f1_ci_low": "", "held_out_f1_ci_high": "", "selection_method": "fixed-weight",
            "status": "not_assessed", "note": note}


def evaluate_fold(scope, group, group_rows, held_samples, min_train_samples, study):
    """One held-out-study x one-stratum evaluation, or None if this stratum
    has no held-out isolates at all in this fold (doesn't apply, not a gap)."""
    training = [row for row in group_rows if row["sample"] not in held_samples]
    held_rows = [row for row in group_rows if row["sample"] in held_samples]
    if not held_rows:
        return None
    by_tool = defaultdict(list)
    for row in training:
        by_tool[row["tool"]].append(float(row["f1"]))
    eligible = {tool: values for tool, values in by_tool.items() if len(values) >= min_train_samples}
    training_samples = len({row["sample"] for row in training})
    held_sample_count = len({row["sample"] for row in held_rows})
    base = {"scope": scope, "group": group, "held_out_study": study, "held_out_samples": held_sample_count,
            "training_samples": training_samples, "selection_method": "fixed-weight"}
    if not eligible:
        return {**base, "selected_method_from_training": "", "held_out_mean_f1": "",
                "held_out_f1_ci_low": "", "held_out_f1_ci_high": "", "status": "not_assessed",
                "note": "No method met the minimum independent training-sample gate for this stratum."}
    selected = max(eligible, key=lambda tool: (statistics.mean(eligible[tool]), tool))
    held = [float(row["f1"]) for row in held_rows if row["tool"] == selected]
    if not held:
        return {**base, "selected_method_from_training": selected, "held_out_mean_f1": "",
                "held_out_f1_ci_low": "", "held_out_f1_ci_high": "", "status": "not_assessed",
                "note": "The training-selected method has no held-out score in this stratum."}
    ci_low, ci_high = bootstrap_ci(held)
    return {**base, "selected_method_from_training": selected,
            "held_out_mean_f1": f"{statistics.mean(held):.4f}",
            "held_out_f1_ci_low": f"{ci_low:.4f}" if ci_low is not None else "",
            "held_out_f1_ci_high": f"{ci_high:.4f}" if ci_high is not None else "",
            "status": "assessed",
            "note": "Training-only mean-F1 selector evaluated on the held-out study; interpret descriptively."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scores", required=True)
    parser.add_argument("--samples", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--min-train-samples", type=int, default=5)
    args = parser.parse_args()
    metadata = {row["sample_id"]: row for row in rows(args.samples) if row.get("sample_id")}
    raw_scores = rows(args.scores)
    for row in raw_scores:
        if row.get("sample") and row["sample"] not in metadata:
            metadata[row["sample"]] = {"sample_id": row["sample"]}
    scores = [annotate(row, metadata) for row in raw_scores]
    studies = group_samples_by_study(scores, metadata)

    output = []
    if len(studies) < 2:
        output.append(withheld_row("overall", "all",
                                   "At least two source_study groups are required for leave-one-study-out validation."))
    else:
        for study, held_samples in sorted(studies.items()):
            overall = evaluate_fold("overall", "all", scores, held_samples, args.min_train_samples, study)
            if overall:
                output.append(overall)
            for field in STRATA:
                groups = defaultdict(list)
                for row in scores:
                    groups[row[field]].append(row)
                for group_value, group_rows in sorted(groups.items()):
                    result = evaluate_fold(field, group_value, group_rows, held_samples, args.min_train_samples, study)
                    if result:
                        output.append(result)
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerows(output)
    print(f"Wrote leave-one-study-out validation: {args.out}")


if __name__ == "__main__": main()
