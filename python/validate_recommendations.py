#!/usr/bin/env python3
"""Leave-one-study-out validation of simple benchmark method rankings.

This is a release safeguard, not a replacement for a pre-registered external
validation study. Each source study is held out, the leading method is selected
on the remaining independent studies, and its held-out mean F1 is reported.
"""

import argparse
import csv
import statistics
from collections import defaultdict


def rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader((line for line in handle if line.strip() and not line.lstrip().startswith("#")), delimiter="\t"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scores", required=True)
    parser.add_argument("--samples", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--min-train-samples", type=int, default=5)
    args = parser.parse_args()
    metadata = {row["sample_id"]: row for row in rows(args.samples) if row.get("sample_id")}
    scores = rows(args.scores)
    studies = defaultdict(set)
    for row in scores:
        study = (metadata.get(row["sample"], {}).get("source_study") or "").strip()
        if study: studies[study].add(row["sample"])
    fields = ["held_out_study", "held_out_samples", "selected_method_from_training", "training_samples",
              "held_out_mean_f1", "status", "note"]
    output = []
    if len(studies) < 2:
        output.append({"held_out_study": "", "held_out_samples": "0", "selected_method_from_training": "",
                       "training_samples": "0", "held_out_mean_f1": "", "status": "not_assessed",
                       "note": "At least two source_study groups are required for leave-one-study-out validation."})
    else:
        for study, held_samples in sorted(studies.items()):
            training = [row for row in scores if row["sample"] not in held_samples]
            by_tool = defaultdict(list)
            for row in training: by_tool[row["tool"]].append(float(row["f1"]))
            eligible = {tool: values for tool, values in by_tool.items() if len(values) >= args.min_train_samples}
            if not eligible:
                output.append({"held_out_study": study, "held_out_samples": len(held_samples), "selected_method_from_training": "",
                               "training_samples": len({row["sample"] for row in training}), "held_out_mean_f1": "",
                               "status": "not_assessed", "note": "No method met the minimum independent training-sample gate."})
                continue
            selected = max(eligible, key=lambda tool: (statistics.mean(eligible[tool]), tool))
            held = [float(row["f1"]) for row in scores if row["sample"] in held_samples and row["tool"] == selected]
            output.append({"held_out_study": study, "held_out_samples": len(held_samples), "selected_method_from_training": selected,
                           "training_samples": len({row["sample"] for row in training}),
                           "held_out_mean_f1": f"{statistics.mean(held):.4f}" if held else "", "status": "assessed" if held else "not_assessed",
                           "note": "Training-only mean-F1 selector evaluated on the held-out study; interpret descriptively."})
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t"); writer.writeheader(); writer.writerows(output)
    print(f"Wrote leave-one-study-out validation: {args.out}")


if __name__ == "__main__": main()
