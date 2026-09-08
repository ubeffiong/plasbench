#!/usr/bin/env python3
"""Build an auditable candidate-quality training dataset from a PlasBench run.

The output deliberately keeps *candidate features* separate from truth-derived
labels.  Most current adapters score a complete tool output, not individual
plasmid bins, so a bin is never assigned a copied tool-level F1 label.  This
makes the artifact safe for future selection-model research without claiming
that unavailable bin-level truth exists.
"""
import argparse
import csv
import json
from pathlib import Path


def rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader((line for line in handle if line.strip() and not line.lstrip().startswith("#")), delimiter="\t"))


def write(path, fields, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        out = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        out.writeheader(); out.writerows(data)


def metadata(path):
    return {row.get("sample_id"): row for row in rows(path) if row.get("sample_id")}


def statuses(path):
    result = {}
    if not path or not Path(path).is_file():
        return result
    for row in rows(path):
        key = (row.get("sample"), row.get("tool"))
        if all(key): result[key] = row
    return result


def bin_ids(results_dir, sample, tool):
    path = Path(results_dir) / sample / tool / f"pred_{tool}.bins.tsv"
    if not path.is_file():
        return []
    found = []
    for row in rows(path):
        value = row.get("bin") or row.get("bin_id") or row.get("cluster")
        if value and value not in found: found.append(value)
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scores", required=True)
    ap.add_argument("--sample-sheet", required=True)
    ap.add_argument("--results-dir", required=True)
    ap.add_argument("--tool-status")
    ap.add_argument("--out-prefix", required=True,
                    help="Writes <prefix>.candidate_features.tsv, .candidate_labels.tsv, and .candidate_dataset.card.json")
    args = ap.parse_args()
    samples, profile = metadata(args.sample_sheet), statuses(args.tool_status)
    features, labels = [], []
    for score in rows(args.scores):
        sample, tool = score.get("sample"), score.get("tool")
        if not sample or not tool: continue
        meta, status = samples.get(sample, {}), profile.get((sample, tool), {})
        candidates = bin_ids(args.results_dir, sample, tool) or ["tool_output"]
        for candidate in candidates:
            feature = {
                "sample": sample, "tool": tool, "candidate_id": candidate,
                "candidate_scope": "bin" if candidate != "tool_output" else "tool_output",
                "organism": meta.get("organism") or "not_recorded",
                "gram_group": meta.get("gram_group") or "not_recorded",
                "source_study": meta.get("source_study") or meta.get("bioproject") or "not_recorded",
                "country": meta.get("collection_country") or meta.get("country") or "not_recorded",
                "sample_origin": meta.get("sample_origin") or "not_recorded",
                "analysis_track": score.get("analysis_track") or "short_read",
                "read_depth_x": meta.get("read_depth_x") or "",
                "runtime_seconds": status.get("runtime_seconds") or "",
                "peak_rss_kb": status.get("peak_rss_kb") or "",
                "tool_status": status.get("status") or "not_recorded",
            }
            features.append(feature)
            # A bin lacks per-bin truth unless a future adapter emits validated
            # bin-specific labels.  Preserve aggregate labels only at output scope.
            labels.append({"sample": sample, "tool": tool, "candidate_id": candidate,
                           "label_scope": "tool_output" if candidate == "tool_output" else "unavailable_for_bin",
                           "f1": score.get("f1", "") if candidate == "tool_output" else "",
                           "precision": score.get("precision", "") if candidate == "tool_output" else "",
                           "recall": score.get("recall", "") if candidate == "tool_output" else "",
                           "plasmid_recall": score.get("plasmid_recall", "") if candidate == "tool_output" else "",
                           "bin_f1": score.get("bin_f1", "") if candidate == "tool_output" else ""})
    prefix = Path(args.out_prefix)
    feature_path = prefix.with_name(prefix.name + ".candidate_features.tsv")
    label_path = prefix.with_name(prefix.name + ".candidate_labels.tsv")
    feature_fields = ["sample", "tool", "candidate_id", "candidate_scope", "organism", "gram_group", "source_study", "country", "sample_origin", "analysis_track", "read_depth_x", "runtime_seconds", "peak_rss_kb", "tool_status"]
    label_fields = ["sample", "tool", "candidate_id", "label_scope", "f1", "precision", "recall", "plasmid_recall", "bin_f1"]
    write(feature_path, feature_fields, features); write(label_path, label_fields, labels)
    card = {"schema_version": "1.0", "features": str(feature_path), "labels": str(label_path),
            "candidate_rows": len(features), "truth_label_policy": "Only tool_output rows carry aggregate score labels; bin rows remain unlabelled until validated bin-specific truth is available.",
            "intended_use": "Research and validation of future per-candidate selection models; not a clinical model or a replacement for PlasBench selection safeguards."}
    card_path = prefix.with_name(prefix.name + ".candidate_dataset.card.json")
    card_path.write_text(json.dumps(card, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote candidate dataset: {feature_path}, {label_path}, {card_path} ({len(features)} candidates)")


if __name__ == "__main__":
    main()
