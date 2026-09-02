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
import math
import statistics
import shutil
from collections import Counter, defaultdict
from pathlib import Path


NUMERIC = ("precision", "recall", "f1", "plasmid_recall", "bin_f1", "unmapped_pred_bp",
           "true_plasmid_bp", "split_events", "merge_events", "contaminated_bins",
           "contamination_fraction", "ambiguously_mapped_pred_bp", "repeat_ambiguity_bp",
           "predicted_record_count", "true_plasmid_count", "fragmentation_excess_records")


def read_tsv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def number(row, key, default=None):
    value = str(row.get(key) or "").strip()
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


def status_profiles(path):
    profiles = defaultdict(lambda: {"counts": Counter(), "runtime_seconds": [], "peak_rss_kb": []})
    if not path or not Path(path).is_file():
        return profiles
    for row in read_tsv(path):
        if row.get("tool") and row.get("status"):
            profile = profiles[row["tool"]]
            profile["counts"][row["status"]] += 1
            for field in ("runtime_seconds", "peak_rss_kb"):
                value = number(row, field)
                if value is not None and value >= 0:
                    profile[field].append(value)
    return profiles


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
    result["collection_country"] = sample.get("collection_country") or sample.get("country") or "not_recorded"
    result["gram_group"] = sample.get("gram_group") or "not_recorded"
    result["plasmid_size_band"] = band(number(row, "true_plasmid_bp"), (10_000, 100_000), ("small", "medium", "large"))
    result["plasmid_count_band"] = band(number(row, "true_plasmid_count"), (2, 5), ("single", "few", "many"))
    result["read_depth_band"] = band(number(sample, "read_depth_x"), (30, 80), ("low", "moderate", "high"))
    result["amr_status"] = "AMR annotated" if number(row, "true_amr_gene_count", 0) > 0 else "AMR not annotated"
    result["fragmentation_excess_records"] = max(0.0, number(row, "predicted_record_count", 0.0) - number(row, "recovered_plasmid_count", 0.0))
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
        profile = statuses[tool]
        completed = profile["counts"]["completed"] + profile["counts"]["reused"]
        failed = profile["counts"]["failed"] + profile["counts"]["skipped"]
        attempted = completed + failed
        failure_rate = failed / attempted if attempted else 0.0
        runtime = statistics.median(profile["runtime_seconds"]) if profile["runtime_seconds"] else None
        memory = statistics.median(profile["peak_rss_kb"]) if profile["peak_rss_kb"] else None
        structural_penalty = min(1.0, mean("split_events") + mean("merge_events")) * .03
        structural_penalty += min(1.0, mean("contamination_fraction")) * .05
        structural_penalty += min(1.0, mean("ambiguously_mapped_pred_bp") / max(1.0, mean("true_plasmid_bp"))) * .02
        structural_penalty += min(1.0, mean("fragmentation_excess_records") / max(1.0, mean("true_plasmid_count"))) * .02
        resource_penalty = 0.0
        if runtime is not None: resource_penalty += .02 * min(1.0, math.log1p(runtime) / math.log1p(3600))
        if memory is not None: resource_penalty += .01 * min(1.0, memory / (16 * 1024 * 1024))
        # Resource terms are deliberately small; scientific recovery is primary.
        quality = (.45 * f1 + .13 * precision + .13 * recall + .18 * plasmid
                   + .06 * (bin_score if bin_score is not None else 1 - failure_rate)
                   - .03 * failure_rate - structural_penalty - resource_penalty)
        output[tool] = {
            "tool": tool, "n_scored": len(values), "coverage": len({row["sample"] for row in values}) / total_samples if total_samples else 0.0,
            "mean_f1": f1, "mean_precision": precision, "mean_recall": recall,
            "mean_plasmid_recall": plasmid, "mean_bin_f1": bin_score,
            "failure_rate": failure_rate, "median_runtime_seconds": runtime,
            "median_peak_rss_kb": memory, "decision_score": quality,
        }
    return output


def eligible(summary, min_samples, min_coverage):
    return summary["n_scored"] >= min_samples and summary["coverage"] >= min_coverage


def write_recommendations(rows, statuses, total_samples, out_path, min_samples, min_coverage, validation_ready=True):
    scopes = [("overall", "all", rows)]
    for field in ("organism", "gram_group", "truth_technology", "sample_origin", "collection_country",
                  "plasmid_size_band", "plasmid_count_band", "read_depth_band", "amr_status"):
        groups = defaultdict(list)
        for row in rows:
            groups[row[field]].append(row)
        scopes.extend((field, value, group) for value, group in sorted(groups.items()))
    columns = ["scope", "group", "tool", "eligible", "recommendation", "reason", "n_scored", "coverage",
               "mean_f1", "mean_precision", "mean_recall", "mean_plasmid_recall", "mean_bin_f1", "failure_rate",
               "median_runtime_seconds", "median_peak_rss_kb", "decision_score"]
    recommendations, written = {}, []
    for scope, group, group_rows in scopes:
        summaries = tool_quality(group_rows, statuses, total_samples if scope == "overall" else len({row["sample"] for row in group_rows}))
        candidates = [item for item in summaries.values() if eligible(item, min_samples, min_coverage)] if validation_ready else []
        winner = max(candidates, key=lambda item: (item["decision_score"], item["mean_f1"], item["tool"])) if candidates else None
        recommendations[(scope, group)] = winner["tool"] if winner else None
        for item in sorted(summaries.values(), key=lambda value: (-value["decision_score"], value["tool"])):
            item = dict(item)
            item.update({"scope": scope, "group": group, "eligible": str(eligible(item, min_samples, min_coverage)).lower(),
                         "recommendation": "primary" if winner and item["tool"] == winner["tool"] else "none",
                         "reason": ("coverage-gated multi-objective recommendation" if winner and item["tool"] == winner["tool"]
                                    else "independent-study validation unavailable" if not validation_ready
                                    else "insufficient coverage or not the highest eligible decision score")})
            written.append(item)
    with open(out_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t")
        writer.writeheader()
        for row in written:
            row["mean_bin_f1"] = "" if row["mean_bin_f1"] is None else f"{row['mean_bin_f1']:.4f}"
            for key in ("coverage", "mean_f1", "mean_precision", "mean_recall", "mean_plasmid_recall", "failure_rate", "decision_score"):
                row[key] = f"{row[key]:.4f}"
            for key in ("median_runtime_seconds", "median_peak_rss_kb"):
                row[key] = "" if row[key] is None else f"{row[key]:.2f}"
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
    fragmentation = number(row, "fragmentation_excess_records", 0.0)
    return .45 * f1 + .20 * plasmid + .15 * bin_score + .10 * number(row, "precision", 0.0) + .10 * number(row, "recall", 0.0) - .10 * min(1.0, unmapped / truth_bp) - .05 * min(1.0, ambiguous / truth_bp) - .03 * (split + merge + fragmentation) - .10 * contamination


def confirmation_requirement(row):
    reasons = []
    if number(row, "f1", 0.0) < 0.90: reasons.append("base-level F1 below 0.90")
    if number(row, "plasmid_recall", 0.0) < 0.90: reasons.append("plasmid-level recovery below 0.90")
    if number(row, "split_events", 0.0) or number(row, "merge_events", 0.0): reasons.append("split or merge diagnostic")
    if number(row, "contamination_fraction", 0.0) > 0.02: reasons.append("chromosome contamination above 2%")
    if number(row, "unmapped_pred_bp", 0.0) > max(1000, number(row, "true_plasmid_bp", 0.0) * 0.05): reasons.append("substantial unmapped predicted sequence")
    if number(row, "ambiguously_mapped_pred_bp", 0.0) > max(1000, number(row, "true_plasmid_bp", 0.0) * 0.05): reasons.append("substantial plasmid/chromosome mapping ambiguity")
    if number(row, "fragmentation_excess_records", 0.0) > 2: reasons.append("fragmented predicted reconstruction")
    return reasons


def reference_footprint(path):
    """Reference-coordinate coverage for a prediction, used for tool agreement."""
    covered = defaultdict(list)
    if not path.is_file():
        return covered
    for raw in path.read_text(encoding="utf-8").splitlines():
        fields = raw.split("\t")
        if len(fields) < 9: continue
        try: start, stop = sorted((int(fields[7]), int(fields[8])))
        except ValueError: continue
        covered[fields[5]].append((start, stop))
    return {target: merge_intervals(intervals)[0] for target, intervals in covered.items()}


def merge_intervals(intervals):
    merged = []
    for start, stop in sorted(intervals):
        if merged and start <= merged[-1][1]: merged[-1][1] = max(merged[-1][1], stop)
        else: merged.append([start, stop])
    return merged, sum(stop - start for start, stop in merged)


def interval_overlap(left, right):
    i = j = total = 0
    while i < len(left) and j < len(right):
        total += max(0, min(left[i][1], right[j][1]) - max(left[i][0], right[j][0]))
        if left[i][1] <= right[j][1]: i += 1
        else: j += 1
    return total


def cross_tool_agreement(results_dir, sample, selected_tool, candidates):
    """Jaccard agreement of mapped reference footprints among completed tools."""
    if not selected_tool:
        return {"status": "not_assessed", "reason": "no selected method"}
    source_dir = Path(results_dir) / sample
    selected = reference_footprint(source_dir / f"{selected_tool}.pred_vs_ref.paf")
    if not selected:
        return {"status": "not_assessed", "reason": "reference-coordinate maps unavailable"}
    compared, values = [], []
    for row in candidates:
        tool = row["tool"]
        if tool == selected_tool: continue
        other = reference_footprint(source_dir / f"{tool}.pred_vs_ref.paf")
        if not other: continue
        intersection = union = 0
        for target in set(selected) | set(other):
            _, left = merge_intervals(selected.get(target, [])); _, right = merge_intervals(other.get(target, []))
            intersection += interval_overlap(selected.get(target, []), other.get(target, []))
            union += left + right - interval_overlap(selected.get(target, []), other.get(target, []))
        if union:
            value = intersection / union
            values.append(value); compared.append({"tool": tool, "reference_footprint_jaccard": round(value, 4)})
    if not values:
        return {"status": "not_assessed", "reason": "no comparable completed tool maps"}
    mean = sum(values) / len(values)
    return {"status": "high" if mean >= .8 else "moderate" if mean >= .5 else "low",
            "mean_reference_footprint_jaccard": round(mean, 4), "compared_tools": compared,
            "meaning": "Agreement is reference-footprint overlap, not proof of structural identity."}


def structural_evidence(results_dir, sample, tool):
    """Read optional curator/tool evidence without treating it as independently validated."""
    path = Path(results_dir) / sample / f"pred_{tool}.evidence.tsv"
    if not tool or not path.is_file():
        return {"status": "not_supplied", "items": []}
    try:
        rows = read_tsv(path)
    except (OSError, csv.Error):
        return {"status": "unreadable", "items": []}
    required = {"record_id", "evidence_type", "evidence_value"}
    if not rows or not required.issubset(rows[0]):
        return {"status": "invalid_schema", "items": []}
    return {"status": "reported_by_source", "items": [{key: row.get(key, "") for key in required} for row in rows]}


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
        f"pred_{tool}.evidence.tsv": "candidate.evidence.tsv",
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
    parser.add_argument("--recommendation-validation", help="Optional leave-one-study-out validation TSV; gates public operational recommendations.")
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
    statuses = status_profiles(args.tool_status)
    validation_rows = read_tsv(args.recommendation_validation) if args.recommendation_validation and Path(args.recommendation_validation).is_file() else []
    validation_ready = not args.recommendation_validation or bool(validation_rows) and all(row.get("status") == "assessed" for row in validation_rows)
    out_prefix = Path(args.out_prefix)
    recommendations_path = out_prefix.with_name(out_prefix.name + ".recommendations.tsv")
    recommendations, recommendation_rows = write_recommendations(
        rows, statuses, len(metadata), recommendations_path, args.min_samples, args.min_coverage, validation_ready)
    stratified_path = out_prefix.with_name(out_prefix.name + ".stratified.tsv")
    with open(stratified_path, "w", newline="", encoding="utf-8") as handle:
        columns = ["scope", "group", "tool", "eligible", "recommendation", "reason", "n_scored", "coverage",
                   "mean_f1", "mean_precision", "mean_recall", "mean_plasmid_recall", "mean_bin_f1", "failure_rate",
                   "median_runtime_seconds", "median_peak_rss_kb", "decision_score"]
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
        agreement = cross_tool_agreement(args.results_dir, sample, selected_tool, candidates)
        reasons = confirmation_requirement(selected) if selected else ["no complete-reference truth score for this isolate"]
        if agreement.get("status") == "low": reasons.append("low agreement between completed tool reference footprints")
        report = {
            "schema_version": "1.0", "sample_id": sample, "analysis_track": args.analysis_track,
            "selection_type": purpose, "selected_tool": selected_tool,
            "operational_recommendation": operational_tool,
            "operational_recommendation_validation": "assessed" if validation_ready else "candidate_only: independent-study validation unavailable",
            "ensemble": {"requested": args.allow_experimental_ensemble, "generated": False,
                         "reason": "PlasBench does not fabricate a consensus reconstruction without validated structural rules."},
            "truth_available": bool(selected), "candidate_metrics": selected or {},
            "selection_criteria": "multi-objective score: F1, plasmid/bin recovery, precision/recall, and penalties for unmapped sequence, split/merge, and contamination",
            "circularity_reconstruction": "not assessed; circular truth recovery is not evidence that the prediction is closed",
            "structural_evidence": structural_evidence(args.results_dir, sample, selected_tool),
            "cross_tool_agreement": agreement,
            "long_read_confirmation_reasons": reasons,
            "confidence_tier": "high" if selected and not reasons else "requires_confirmation",
            "rejected_candidates": [{"tool": row["tool"], "reason": "lower truth-set candidate quality"} for row in candidates if not selected or row["tool"] != selected["tool"]],
        }
        destination = Path(args.results_dir) / sample / "selected_candidate"
        report["copied_files"] = copy_candidate(args.results_dir, sample, selected_tool, destination) if selected_tool else []
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "selection_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {recommendations_path}, {stratified_path}, and selection reports for {len(metadata)} sample(s).")


if __name__ == "__main__":
    main()
