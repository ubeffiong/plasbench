#!/usr/bin/env python3
"""Stratify per-plasmid recovery by replicon, mobility (MOB), size and AMR carriage.
Descriptive only.

Inputs
------
  results/<sample>/<tool>.per_plasmid.tsv   written by score_plasmids.py --per-plasmid-out
  data/<sample>/truth_features.tsv          written by annotate_reference.py
                                            (feature_type `replicon` = Inc/rep type,
                                             `mob` = relaxase/MOB type, `amr` = AMR gene)
  data/<sample>/annotation_provenance.json  which annotation callers actually ran

Output: one row per (analysis_track, tool, feature_type, label):
  n_plasmids, n_samples, mean_completeness, recovered_fraction, underpowered,
  median_completeness, q1_completeness, q3_completeness, n_cprr_assessed, cprr

CPRR by stratum
---------------
  results/<sample>/<tool>.cprr.tsv (score_bins.py --cprr-out) gives each truth
  plasmid's correct-reconstruction verdict. `cprr` is the share of the stratum's
  assessed plasmids that are correct; `n_cprr_assessed` counts them. Both are blank
  for a classification-only tool (no bins, so no CPRR file). With --truth-provenance,
  a sample whose truth was polished with the benchmark's own reads
  (base_level_metrics_valid != yes) uses `correct_without_identity`, the same
  identity rule as the leaderboard CPRR.

Per-plasmid recovery is heavy-tailed (many small plasmids recovered fully, a few large
ones missed), so the median and interquartile range sit next to the mean.

Feature types
-------------
  replicon, mob   labels from truth_features.tsv
  size_band       `<10kb`, `10-50kb`, `>50kb`, from the plasmid length in the side file.
                  Always available; needs no annotation.
  amr             From the curated truth_amr.tsv when present (authoritative: a plasmid
                  absent from it carries no resistance gene). Otherwise `arg_carrying`
                  when an annotation caller found an AMR feature on the plasmid, and
                  `no_arg_detected` only when an AMR caller reported ok in
                  annotation_provenance.json and found none. With neither, the plasmid
                  is not stratified by AMR: absence was never measured.

Rules
-----
  * Never mixes analysis tracks and never alters scores.tsv or any ranking. This is
    a breakdown that helps explain WHY a tool's F1 is what it is.
  * A plasmid with several labels of one type counts once in each label's group.
  * A plasmid in a sample that HAS an annotation file but no label of that type is
    reported as label `untyped` (replicon, mob).
  * A plasmid in a sample with NO annotation file is not stratified by replicon, MOB
    or AMR: its callers did not run, so calling it `untyped` would state an absence
    that was never measured. The count is reported on stderr.
  * Groups with fewer than --min-plasmids plasmids are flagged `underpowered=true`.
    With small cohorts most groups will be. Do not read a rank into them.

Standard library only.
"""

import argparse
import csv
import glob
import json
import os
import sys
from collections import defaultdict

TYPES = ("replicon", "mob")
SIZE_BANDS = ((10_000, "<10kb"), (50_000, "10-50kb"))   # upper bounds; the rest is ">50kb"
AMR_CALLERS = ("amrfinder", "abricate_amr")
OUT_FIELDS = ("analysis_track", "tool", "feature_type", "label", "n_plasmids",
              "n_samples", "mean_completeness", "recovered_fraction", "underpowered",
              "median_completeness", "q1_completeness", "q3_completeness",
              "n_cprr_assessed", "cprr")


def size_band(length):
    for upper, name in SIZE_BANDS:
        if length < upper:
            return name
    return ">50kb"


def quantile(sorted_values, fraction):
    """Linear-interpolated quantile of an already sorted, non-empty list."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = fraction * (len(sorted_values) - 1)
    low = int(position)
    high = min(low + 1, len(sorted_values) - 1)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (position - low)


def amr_evaluated(sample_dir):
    """True when an AMR caller reported ok in annotation_provenance.json."""
    try:
        with open(os.path.join(sample_dir, "annotation_provenance.json"), encoding="utf-8") as handle:
            callers = json.load(handle).get("callers", {})
    except (OSError, ValueError):
        return False
    return any((callers.get(name) or {}).get("status") == "ok" for name in AMR_CALLERS)


def read_curated_amr(sample_dir):
    """Set of sequence ids carrying a gene in the curated truth_amr.tsv; None when absent.

    A curated table lists every resistance gene on the reference, so a plasmid missing
    from it is genuinely without one. Only the curated file counts: the auto-derived
    truth_amr.draft.tsv is never read here.
    """
    path = os.path.join(sample_dir, "truth_amr.tsv")
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return None
    with open(path, newline="", encoding="utf-8") as handle:
        return {row["sequence_id"] for row in csv.DictReader(handle, delimiter="\t")
                if row.get("sequence_id")}


def read_labels(path):
    """sequence_id -> {feature_type: set(labels)}; None when no annotation exists."""
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return None
    labels = defaultdict(lambda: defaultdict(set))
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            kind = row.get("feature_type")
            if kind in TYPES and (row.get("label") or "").strip():
                labels[row["sequence_id"]][kind].add(row["label"].strip())
            elif kind == "amr":
                labels[row["sequence_id"]]["amr"].add("arg_carrying")
    return labels


def read_identity_validity(path):
    """sample -> True when base-level identity is valid (truth_provenance.py); {} without a file."""
    if not path or not os.path.isfile(path):
        return {}
    with open(path, newline="", encoding="utf-8") as handle:
        return {row["sample"]: row.get("base_level_metrics_valid") == "yes"
                for row in csv.DictReader(handle, delimiter="\t") if row.get("sample")}


def read_cprr_verdicts(path):
    """true_plasmid -> (correct, correct_without_identity) booleans; None when no CPRR file."""
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return None
    with open(path, newline="", encoding="utf-8") as handle:
        return {row["true_plasmid"]: (row.get("correct") == "yes", row.get("correct_without_identity") == "yes")
                for row in csv.DictReader(handle, delimiter="\t") if row.get("true_plasmid")}


def stratify(results_dir, data_dir, min_plasmids, identity_valid=None):
    # (track, tool, type, label) -> [(sample, completeness, recovered, cprr_correct or None)]
    groups = defaultdict(list)
    skipped_unannotated = 0
    label_cache, amr_cache, curated_cache = {}, {}, {}
    identity_valid = identity_valid or {}
    for path in sorted(glob.glob(os.path.join(results_dir, "*", "*.per_plasmid.tsv"))):
        tool_prefix = os.path.basename(path)[:-len(".per_plasmid.tsv")]
        verdicts = read_cprr_verdicts(os.path.join(os.path.dirname(path), f"{tool_prefix}.cprr.tsv"))
        with open(path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                sample = row["sample"]
                verdict = (verdicts or {}).get(row["sequence_id"])
                cprr_correct = None
                if verdict is not None:
                    cprr_correct = verdict[0] if identity_valid.get(sample, True) else verdict[1]
                item = (sample, float(row["completeness"]), int(row["recovered"]), cprr_correct)
                track, tool = row["analysis_track"], row["tool"]
                # Size needs no annotation, so it is always available.
                try:
                    groups[(track, tool, "size_band", size_band(int(row["length"])))].append(item)
                except (KeyError, ValueError):
                    pass
                if sample not in label_cache:
                    sample_dir = os.path.join(data_dir, sample)
                    label_cache[sample] = read_labels(os.path.join(sample_dir, "truth_features.tsv"))
                    amr_cache[sample] = amr_evaluated(sample_dir)
                    curated_cache[sample] = read_curated_amr(sample_dir)
                labels = label_cache[sample]
                curated = curated_cache[sample]
                if curated is not None:     # curated truth is authoritative for ARG carriage
                    state = "arg_carrying" if row["sequence_id"] in curated else "no_arg_detected"
                    groups[(track, tool, "amr", state)].append(item)
                if labels is None:
                    skipped_unannotated += 1
                    continue
                for kind in TYPES:
                    found = labels.get(row["sequence_id"], {}).get(kind) or {"untyped"}
                    for label in found:
                        groups[(track, tool, kind, label)].append(item)
                if curated is None:         # fall back to the annotation callers
                    if labels.get(row["sequence_id"], {}).get("amr"):
                        groups[(track, tool, "amr", "arg_carrying")].append(item)
                    elif amr_cache[sample]:
                        groups[(track, tool, "amr", "no_arg_detected")].append(item)
    rows = []
    for (track, tool, kind, label), items in sorted(groups.items()):
        n = len(items)
        completeness = sorted(c for _, c, _, _ in items)
        assessed = [v for _, _, _, v in items if v is not None]
        rows.append({
            "analysis_track": track, "tool": tool, "feature_type": kind, "label": label,
            "n_plasmids": n, "n_samples": len({s for s, _, _, _ in items}),
            "mean_completeness": f"{sum(completeness) / n:.4f}",
            "recovered_fraction": f"{sum(r for _, _, r, _ in items) / n:.4f}",
            "underpowered": "true" if n < min_plasmids else "false",
            "median_completeness": f"{quantile(completeness, 0.5):.4f}",
            "q1_completeness": f"{quantile(completeness, 0.25):.4f}",
            "q3_completeness": f"{quantile(completeness, 0.75):.4f}",
            "n_cprr_assessed": len(assessed),
            "cprr": f"{sum(assessed) / len(assessed):.4f}" if assessed else "",
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
    parser.add_argument("--truth-provenance",
                        help="truth_provenance.py output; drops the CPRR identity criterion where it is invalid")
    args = parser.parse_args()
    rows, skipped = stratify(args.results_dir, args.data_dir, args.min_plasmids,
                             read_identity_validity(args.truth_provenance))
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUT_FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    sys.stderr.write(f"[stratify_recovery] wrote {len(rows)} group row(s) to {args.out}; "
                     f"{skipped} plasmid row(s) not stratified by replicon/MOB/AMR "
                     "(sample has no truth_features.tsv)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
