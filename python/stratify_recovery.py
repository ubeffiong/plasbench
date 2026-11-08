#!/usr/bin/env python3
"""Stratify per-plasmid recovery by replicon and mobility (MOB) type. Descriptive only.

Inputs
------
  results/<sample>/<tool>.per_plasmid.tsv   written by score_plasmids.py --per-plasmid-out
  data/<sample>/truth_features.tsv          written by annotate_reference.py
                                            (feature_type `replicon` = Inc/rep type,
                                             `mob` = relaxase/MOB type)

Output: one row per (analysis_track, tool, feature_type, label):
  n_plasmids, mean_completeness, recovered_fraction, underpowered

Rules
-----
  * Never mixes analysis tracks and never alters scores.tsv or any ranking. This is
    a breakdown that helps explain WHY a tool's F1 is what it is.
  * A plasmid with several labels of one type counts once in each label's group.
  * A plasmid in a sample that HAS an annotation file but no label of that type is
    reported as label `untyped`.
  * A plasmid in a sample with NO annotation file is not stratified at all: its
    callers did not run, so its type is unknown, and calling it `untyped` would
    state an absence that was never measured. The count is reported on stderr.
  * Groups with fewer than --min-plasmids plasmids are flagged `underpowered=true`.
    With small cohorts most groups will be. Do not read a rank into them.

Standard library only.
"""

import argparse
import csv
import glob
import os
import sys
from collections import defaultdict

TYPES = ("replicon", "mob")
OUT_FIELDS = ("analysis_track", "tool", "feature_type", "label", "n_plasmids",
              "n_samples", "mean_completeness", "recovered_fraction", "underpowered")


def read_labels(path):
    """sequence_id -> {feature_type: set(labels)}; None when no annotation exists."""
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return None
    labels = defaultdict(lambda: defaultdict(set))
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row.get("feature_type") in TYPES and (row.get("label") or "").strip():
                labels[row["sequence_id"]][row["feature_type"]].add(row["label"].strip())
    return labels


def stratify(results_dir, data_dir, min_plasmids):
    groups = defaultdict(list)          # (track, tool, type, label) -> [(sample, completeness, recovered)]
    skipped_unannotated = 0
    label_cache = {}
    for path in sorted(glob.glob(os.path.join(results_dir, "*", "*.per_plasmid.tsv"))):
        with open(path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                sample = row["sample"]
                if sample not in label_cache:
                    label_cache[sample] = read_labels(os.path.join(data_dir, sample, "truth_features.tsv"))
                labels = label_cache[sample]
                if labels is None:
                    skipped_unannotated += 1
                    continue
                for kind in TYPES:
                    found = labels.get(row["sequence_id"], {}).get(kind) or {"untyped"}
                    for label in found:
                        groups[(row["analysis_track"], row["tool"], kind, label)].append(
                            (sample, float(row["completeness"]), int(row["recovered"])))
    rows = []
    for (track, tool, kind, label), items in sorted(groups.items()):
        n = len(items)
        rows.append({
            "analysis_track": track, "tool": tool, "feature_type": kind, "label": label,
            "n_plasmids": n, "n_samples": len({s for s, _, _ in items}),
            "mean_completeness": f"{sum(c for _, c, _ in items) / n:.4f}",
            "recovered_fraction": f"{sum(r for _, _, r in items) / n:.4f}",
            "underpowered": "true" if n < min_plasmids else "false",
        })
    return rows, skipped_unannotated


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--min-plasmids", type=int, default=5,
                        help="groups smaller than this are flagged underpowered (default: 5)")
    args = parser.parse_args()
    rows, skipped = stratify(args.results_dir, args.data_dir, args.min_plasmids)
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUT_FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    sys.stderr.write(f"[stratify_recovery] wrote {len(rows)} group row(s) to {args.out}; "
                     f"{skipped} plasmid row(s) skipped (sample has no truth_features.tsv)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
