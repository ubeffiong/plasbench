#!/usr/bin/env python3
"""Create conservative method recommendations and reusable per-isolate candidates.

This module deliberately separates two claims:
* truth_set_best_candidate: selected with complete-reference metrics and valid
  only for a benchmark isolate; and
* operational_method_recommendation: a coverage-gated method recommendation
  that may be applied to an unknown isolate, but never claims its output is
  biologically confirmed.

It copies an already-produced tool FASTA into ``selected_candidate``. No tool
is rerun and no synthetic consensus sequence is fabricated.
"""

import argparse
import csv
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path


NUMERIC = ("precision", "recall", "f1", "plasmid_recall", "bin_f1", "unmapped_pred_bp",
           "true_plasmid_bp", "split_events", "merge_events", "contaminated_bins",
           "contamination_fraction", "ambiguously_mapped_pred_bp")


def read_tsv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def number(row, key, default=None):
    value = (row.get(key) or "").strip()
    try:
        return float(value) if value else default
    except ValueError:
        return default


def sample_metadata(path):
    # Curated sample sheets may retain explanatory comment rows below the
    # header. csv.DictReader alone would treat those as sample identifiers.
    with open(path, newline="", encoding="utf-8") as handle:
        rows = csv.DictReader((line for line in handle if line.strip() and not line.lstrip().startswith("#")), delimiter="\t")
        return {row["sample_id"]: row for row in rows
                if row.get("sample_id") and not row["sample_id"].lstrip().startswith("#")}


def status_counts(path):
    counts = defaultdict(Counter)
    if not path or not Path(path).is_file():
        return counts
    for row in read_tsv(path):
        if row.get("tool") and row.get("status"):
            counts[row["tool"]][row["status"]] += 1
    return counts


def band(value, limits, labels):
    if value is None:
        return "not_recorded"
    for limit, label in zip(limits, labels):
        if value < limit:
            return label
    return labels[-1]


def annotate(row, metadata):
    result = dict(row)
    sample = metadata.get(row["sample"], {})
    result["organism"] = sample.get("organism") or "not_recorded"
    result["truth_technology"] = sample.get("truth_technology") or "not_recorded"
    result["sample_origin"] = sample.get("sample_origin") or "not_recorded"
    result["plasmid_size_band"] = band(number(row, "true_plasmid_bp"), (10_000, 100_000), ("small", "medium", "large"))
    result["read_depth_band"] = band(number(sample, "read_depth_x"), (30, 80), ("low", "moderate", "high"))
    return result


def tool_quality(rows, statuses, total_samples):
    """Multi-objective descriptive score, only used after eligibility checks."""
    by_tool = defaultdict(list)
    for row in rows:
        by_tool[row["tool"]].append(row)
    output = {}
    for tool, values in by_tool.items():
        mean = lambda key, fallback=0.0: sum(number(row, key, fallback) or fallback for row in values) / len(values)
        f1, precision, recall = mean("f1"), mean("precision"), mean("recall")
        plasmid = mean("plasmid_recall", f1)
        bin_values = [number(row, "bin_f1") for row in values if number(row, "bin_f1") is not None]
        bin_score = sum(bin_values) / len(bin_values) if bin_values else None
        completed = statuses[tool]["completed"] + statuses[tool]["reused"]
        failed = statuses[tool]["failed"] + statuses[tool]["skipped"]
        attempted = completed + failed
        failure_rate = failed / attempted if attempted else 0.0
        # Bin score changes the score only for true binning evidence. A method
        # without bins is not penalised for a metric it cannot supply.
        quality = 0.45 * f1 + 0.15 * precision + 0.15 * recall + 0.20 * plasmid + 0.05 * (bin_score if bin_score is not None else 1 - failure_rate)
        output[tool] = {
            "tool": tool, "n_scored": len(values), "coverage": len({row["sample"] for row in values}) / total_samples if total_samples else 0.0,
            "mean_f1": f1, "mean_precision": precision, "mean_recall": recall,
            "mean_plasmid_recall": plasmid, "mean_bin_f1": bin_score,
            "failure_rate": failure_rate, "decision_score": quality,
        }
    return output


def eligible(summary, min_samples, min_coverage):
    return summary["n_scored"] >= min_samples and summary["coverage"] >= min_coverage


def write_recommendations(rows, statuses, total_samples, out_path, min_samples, min_coverage):
    scopes = [("overall", "all", rows)]
    for field in ("organism", "truth_technology", "sample_origin", "plasmid_size_band", "read_depth_band"):
        groups = defaultdict(list)
        for row in rows:
            groups[row[field]].append(row)
        scopes.extend((field, value, group) for value, group in sorted(groups.items()))
    columns = ["scope", "group", "tool", "eligible", "recommendation", "reason", "n_scored", "coverage",
               "mean_f1", "mean_precision", "mean_recall", "mean_plasmid_recall", "mean_bin_f1", "failure_rate", "decision_score"]
    recommendations, written = {}, []
    for scope, group, group_rows in scopes:
        summaries = tool_quality(group_rows, statuses, total_samples if scope == "overall" else len({row["sample"] for row in group_rows}))
        candidates = [item for item in summaries.values() if eligible(item, min_samples, min_coverage)]
        winner = max(candidates, key=lambda item: (item["decision_score"], item["mean_f1"], item["tool"])) if candidates else None
        recommendations[(scope, group)] = winner["tool"] if winner else None
        for item in sorted(summaries.values(), key=lambda value: (-value["decision_score"], value["tool"])):
            item = dict(item)
            item.update({"scope": scope, "group": group, "eligible": str(eligible(item, min_samples, min_coverage)).lower(),
                         "recommendation": "primary" if winner and item["tool"] == winner["tool"] else "none",
                         "reason": "coverage-gated multi-objective recommendation" if winner and item["tool"] == winner["tool"] else "insufficient coverage or not the highest eligible decision score"})
            written.append(item)
    with open(out_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t")
        writer.writeheader()
        for row in written:
            row["mean_bin_f1"] = "" if row["mean_bin_f1"] is None else f"{row['mean_bin_f1']:.4f}"
            for key in ("coverage", "mean_f1", "mean_precision", "mean_recall", "mean_plasmid_recall", "failure_rate", "decision_score"):
                row[key] = f"{row[key]:.4f}"
            writer.writerow(row)
    return recommendations, written


def candidate_quality(row):
    f1 = number(row, "f1", 0.0)
    plasmid = number(row, "plasmid_recall", f1)
    bin_score = number(row, "bin_f1", f1)
    unmapped = number(row, "unmapped_pred_bp", 0.0)
    truth_bp = max(1.0, number(row, "true_plasmid_bp", 1.0))
    split = number(row, "split_events", 0.0)
    merge = number(row, "merge_events", 0.0)
    contamination = number(row, "contamination_fraction", 0.0)
    ambiguous = number(row, "ambiguously_mapped_pred_bp", 0.0)
    return 0.45 * f1 + 0.20 * plasmid + 0.15 * bin_score + 0.10 * number(row, "precision", 0.0) + 0.10 * number(row, "recall", 0.0) - 0.10 * min(1.0, unmapped / truth_bp) - 0.05 * min(1.0, ambiguous / truth_bp) - 0.03 * (split + merge) - 0.10 * contamination


def confirmation_requirement(row):
    reasons = []
    if number(row, "f1", 0.0) < 0.90: reasons.append("base-level F1 below 0.90")
    if number(row, "plasmid_recall", 0.0) < 0.90: reasons.append("plasmid-level recovery below 0.90")
    if number(row, "split_events", 0.0) or number(row, "merge_events", 0.0): reasons.append("split or merge diagnostic")
    if number(row, "contamination_fraction", 0.0) > 0.02: reasons.append("chromosome contamination above 2%")
    if number(row, "unmapped_pred_bp", 0.0) > max(1000, number(row, "true_plasmid_bp", 0.0) * 0.05): reasons.append("substantial unmapped predicted sequence")
    if number(row, "ambiguously_mapped_pred_bp", 0.0) > max(1000, number(row, "true_plasmid_bp", 0.0) * 0.05): reasons.append("substantial plasmid/chromosome mapping ambiguity")
    return reasons


def copy_candidate(results_dir, sample, tool, destination):
    source_dir = Path(results_dir) / sample
    destination.mkdir(parents=True, exist_ok=True)
    copied = []
    mapping = {
        f"pred_{tool}.plasmid.fasta": "candidate.plasmid.fasta",
        f"pred_{tool}.bins.tsv": "candidate.bins.tsv",
        f"{tool}.pred_vs_ref.paf": "candidate.pred_vs_ref.paf",
        f"{tool}.pred_vs_ref.all.paf": "candidate.pred_vs_ref.all.paf",
        f"{tool}.bin_summary.tsv": "candidate.bin_summary.tsv",
        f"{tool}.bin_matches.tsv": "candidate.bin_matches.tsv",
    }
    for name, output_name in mapping.items():
        path = source_dir / name
        if path.is_file():
            shutil.copy2(path, destination / output_name)
            copied.append(output_name)
    return copied


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scores", required=True)
    parser.add_argument("--sample-sheet", required=True)
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--out-prefix", required=True)
    parser.add_argument("--tool-status")
    parser.add_argument("--min-samples", type=int, default=5)
    parser.add_argument("--min-coverage", type=float, default=0.80)
    parser.add_argument("--analysis-track", choices=("short_read", "long_read", "hybrid"), default="short_read")
    parser.add_argument("--allow-experimental-ensemble", action="store_true", help="Record an experimental request; no consensus FASTA is fabricated.")
    args = parser.parse_args()
    if args.min_samples < 1 or not 0 < args.min_coverage <= 1:
        raise SystemExit("ERROR: --min-samples must be positive and --min-coverage must be in (0, 1].")
    metadata = sample_metadata(args.sample_sheet)
    raw_scores = read_tsv(args.scores)
    # A legacy or externally supplied score table may contain samples absent
    # from the active sheet. Retain their already-produced candidates rather
    # than silently dropping them; their strata remain explicitly unrecorded.
    for row in raw_scores:
        if row.get("sample") and row["sample"] not in metadata:
            metadata[row["sample"]] = {"sample_id": row["sample"]}
    rows = [annotate(row, metadata) for row in raw_scores]
    statuses = status_counts(args.tool_status)
    out_prefix = Path(args.out_prefix)
    recommendations_path = out_prefix.with_name(out_prefix.name + ".recommendations.tsv")
    recommendations, recommendation_rows = write_recommendations(
        rows, statuses, len(metadata), recommendations_path, args.min_samples, args.min_coverage)
    stratified_path = out_prefix.with_name(out_prefix.name + ".stratified.tsv")
    with open(stratified_path, "w", newline="", encoding="utf-8") as handle:
        columns = ["scope", "group", "tool", "eligible", "recommendation", "reason", "n_scored", "coverage",
                   "mean_f1", "mean_precision", "mean_recall", "mean_plasmid_recall", "mean_bin_f1", "failure_rate", "decision_score"]
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t")
        writer.writeheader()
        for row in recommendation_rows:
            if row["scope"] != "overall":
                writer.writerow({key: row.get(key, "") for key in columns})
    by_sample = defaultdict(list)
    for row in rows:
        by_sample[row["sample"]].append(row)
    for sample in sorted(metadata):
        candidates = by_sample.get(sample, [])
        operational_tool = recommendations.get(("organism", metadata[sample].get("organism") or "not_recorded")) or recommendations.get(("overall", "all"))
        selected = max(candidates, key=candidate_quality) if candidates else None
        purpose = "truth_set_best_candidate" if selected else "operational_method_recommendation_only"
        selected_tool = selected["tool"] if selected else operational_tool
        report = {
            "schema_version": "1.0", "sample_id": sample, "analysis_track": args.analysis_track,
            "selection_type": purpose, "selected_tool": selected_tool,
            "operational_recommendation": operational_tool,
            "ensemble": {"requested": args.allow_experimental_ensemble, "generated": False,
                         "reason": "PlasBench does not fabricate a consensus reconstruction without validated structural rules."},
            "truth_available": bool(selected), "candidate_metrics": selected or {},
            "selection_criteria": "multi-objective score: F1, plasmid/bin recovery, precision/recall, and penalties for unmapped sequence, split/merge, and contamination",
            "circularity_reconstruction": "not assessed; circular truth recovery is not evidence that the prediction is closed",
            "long_read_confirmation_reasons": confirmation_requirement(selected) if selected else ["no complete-reference truth score for this isolate"],
            "confidence_tier": "high" if selected and not confirmation_requirement(selected) else "requires_confirmation",
            "rejected_candidates": [{"tool": row["tool"], "reason": "lower truth-set candidate quality"} for row in candidates if not selected or row["tool"] != selected["tool"]],
        }
        destination = Path(args.results_dir) / sample / "selected_candidate"
        report["copied_files"] = copy_candidate(args.results_dir, sample, selected_tool, destination) if selected_tool else []
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "selection_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {recommendations_path}, {stratified_path}, and selection reports for {len(metadata)} sample(s).")


if __name__ == "__main__":
    main()
