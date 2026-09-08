#!/usr/bin/env python3
"""Join per-sample bin summaries into the canonical PlasBench score table.

Note on the graded plasmid-recovery completeness tiers
(recovered_plasmid_count_ge50/ge90, complete_circular_plasmid_recall, ...):
those fields are computed and written directly by score_plasmids.py, not
here. This file deliberately needed NO changes for them: `main()` below
reads scores.tsv with `fieldnames = list(rows[0])` (whatever columns are
already present) and only APPENDS the FIELDS this file itself owns (the
bin-matching fields below), so score_plasmids.py's own columns -- old or
new -- pass through this join completely unchanged.
"""

import argparse
import csv
from pathlib import Path

FIELDS = [
    "bin_precision", "bin_recall", "bin_f1", "matched_bins", "unmatched_bins",
    "missed_plasmids", "split_events", "merge_events", "contaminated_bins",
    "chromosome_aligned_bp", "repeat_ambiguity_bp", "bin_total_mapped_bp", "contamination_fraction",
    # Supplementary to bin_f1/split_events/merge_events/contamination_fraction
    # above, never a replacement -- see score_bins.py's clustering_agreement().
    "nmi", "variation_of_information",
    "perfect_reference_recovery", "strict_reference_reconstruction",
]


def value(row, field):
    try:
        return float(row.get(field, ""))
    except (TypeError, ValueError):
        return None


def perfect_metrics(row):
    """Return availability-aware reference-perfect labels.

    These labels are deliberately stricter than high F1, but are not claims of
    nucleotide-identical sequence or circular closure.  The structural label
    is withheld rather than guessed when a tool did not provide bin evidence.
    """
    required = ("f1", "plasmid_recall", "unmapped_pred_bp", "off_truth_pred_bp",
                "ambiguously_mapped_pred_bp")
    if any(value(row, field) is None for field in required):
        return "", ""
    recovery = (value(row, "f1") >= 0.99995 and value(row, "plasmid_recall") >= 0.99995
                and all(value(row, field) == 0 for field in required[2:]))
    recovery_label = "yes" if recovery else "no"
    structural = ("bin_f1", "split_events", "merge_events", "contaminated_bins",
                  "contamination_fraction", "repeat_ambiguity_bp")
    if any(value(row, field) is None for field in structural):
        return recovery_label, ""
    strict = recovery and value(row, "bin_f1") >= 0.99995 and all(
        value(row, field) == 0 for field in structural[1:])
    return recovery_label, "yes" if strict else "no"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scores", required=True)
    parser.add_argument("--results-dir", required=True)
    args = parser.parse_args()
    summaries = {}
    for path in Path(args.results_dir).glob("*/*.bin_summary.tsv"):
        tool = path.name.removesuffix(".bin_summary.tsv")
        sample = path.parent.name
        with open(path) as handle:
            summaries[(sample, tool)] = next(csv.DictReader(handle, delimiter="\t"))
    with open(args.scores) as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
        fieldnames = list(rows[0]) if rows else []
    for field in FIELDS:
        if field not in fieldnames:
            fieldnames.append(field)
    for row in rows:
        summary = summaries.get((row["sample"], row["tool"]), {})
        for field in FIELDS:
            row[field] = summary.get(field, "")
        row["perfect_reference_recovery"], row["strict_reference_reconstruction"] = perfect_metrics(row)
    with open(args.scores, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
