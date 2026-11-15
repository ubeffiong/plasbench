#!/usr/bin/env python3
"""Screen truth labels (PLASMID / CHROMOSOME) against replicon and MOB evidence.

Plasmid-versus-chromosome truth comes from the submitter's record, so a chromid,
an integrated plasmid or a mislabelled record is scored as if it were certain.
This script cross-checks each truth sequence against the reference annotation
(`truth_features.tsv`, written by `annotate_reference.py`) and reports where the
label and the annotation disagree.

It is a SCREEN, not a correction. It never edits truth.tsv and never changes a
score. Findings per truth sequence:

  consistent                        label agrees with the annotation
  chromosome_with_plasmid_markers   CHROMOSOME sequence carrying a replicon or MOB
                                    feature (candidate chromid / integrated plasmid /
                                    annotation false positive)
  plasmid_without_markers           PLASMID sequence with neither feature, although the
                                    callers ran (candidate mislabel, or a cryptic
                                    plasmid the databases do not know)
  not_evaluated                     the callers did not run for this sample, so no
                                    statement is made. Never read as "consistent".

Flags (a second column, `flags`, added beside the finding; a sequence can carry several and the finding itself is unchanged):

  integrated_plasmid_candidate   the LARGEST chromosome carries a replicon or MOB marker (a plasmid integrated into the main chromosome, or a false positive)
  chromid_candidate              a SECONDARY chromosome carries a marker (a chromid, or an integrated plasmid)
  secondary_chromosome           a chromosome-labelled replicon that is not the largest and is at least --chromid-min-bp (default 350 kb) with no marker
  large_plasmid                  a PLASMID of at least --large-plasmid-bp (default 500 kb): a megaplasmid, or a chromid labelled plasmid
  multi_replicon_plasmid         a PLASMID with two or more distinct replicon labels (a co-integrate or a fusion)
  marker_free_plasmid            a PLASMID with no marker although both callers ran (excluded from the evidence scheme)
  multimer_<k>x                  a plasmid stored as k identical tandem copies (python/detect_dimers.py: dimers, trimers and higher)
  collapsed_repeat_candidate     the read depth of the replicon has high-depth regions (a collapsed repeat or an amplified element; needs RUN_TRUTH_DEPTH_ANOMALIES)
  low_depth_region               the read depth has low-depth regions (a misjoin or a deletion in the truth; same requirement)

The size thresholds are heuristics (pre-registered as proposed); they flag a sequence to look at, they never relabel it.

Caller status comes from annotation_provenance.json when present; without it the
sample is `not_evaluated`, because an empty feature table cannot tell "found
nothing" from "did not run".
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path

MARKER_TYPES = ("replicon", "mob")
# A marker class counts as evaluated only if a caller that produces it reported ok.
MARKER_CALLERS = {"replicon": ("abricate_replicon",), "mob": ("mob_typer",)}
FIELDS = ("sample", "sequence_id", "molecule_type", "length", "replicon_labels",
          "mob_labels", "finding", "flags")
CHROMID_MIN_BP = 350000
LARGE_PLASMID_BP = 500000


def read_tsv(path: Path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def evaluated_classes(provenance_path: Path):
    """Marker classes whose caller reported status ok; empty set when unknown."""
    if not provenance_path.is_file():
        return set()
    try:
        record = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    callers = record.get("callers", record)
    return {kind for kind, names in MARKER_CALLERS.items()
            if any((callers.get(name) or {}).get("status") == "ok" for name in names)}


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def audit_sample(sample: str, sample_dir: Path, chromid_min_bp: int = CHROMID_MIN_BP, large_plasmid_bp: int = LARGE_PLASMID_BP):
    truth_path = sample_dir / "truth.tsv"
    if not truth_path.is_file():
        return []
    evaluated = evaluated_classes(sample_dir / "annotation_provenance.json")
    labels = {kind: {} for kind in MARKER_TYPES}
    features = sample_dir / "truth_features.tsv"
    if features.is_file() and features.stat().st_size:
        for row in read_tsv(features):
            kind = row.get("feature_type")
            if kind in labels and (row.get("label") or "").strip():
                labels[kind].setdefault(row["sequence_id"], set()).add(row["label"].strip())
    truth_rows = read_tsv(truth_path)
    largest_chromosome = max((_int(r.get("length")) for r in truth_rows if r["molecule_type"].upper() == "CHROMOSOME"), default=0)
    corrections = sample_dir / "truth.corrections.tsv"
    multimers = ({r["sequence_id"]: (r.get("copies") or "2") for r in read_tsv(corrections) if (r.get("multimer") or "") == "yes"}
                 if corrections.is_file() and corrections.stat().st_size else {})
    depth_path = sample_dir / "truth_depth_anomaly_summary.tsv"
    depth = ({r["sequence_id"]: r for r in read_tsv(depth_path)} if depth_path.is_file() and depth_path.stat().st_size else {})
    rows = []
    for row in truth_rows:
        seq, molecule = row["sequence_id"], row["molecule_type"].upper()
        rep = sorted(labels["replicon"].get(seq, ()))
        mob = sorted(labels["mob"].get(seq, ()))
        has_marker = bool(rep or mob)
        if molecule == "CHROMOSOME":
            # A marker found is evidence even if only one caller ran.
            finding = "chromosome_with_plasmid_markers" if has_marker else (
                "consistent" if evaluated else "not_evaluated")
        elif molecule == "PLASMID":
            # Absence is only meaningful when BOTH marker classes were evaluated.
            if has_marker:
                finding = "consistent"
            elif set(MARKER_TYPES) <= evaluated:
                finding = "plasmid_without_markers"
            else:
                finding = "not_evaluated"
        else:
            finding = "not_evaluated"
        length = _int(row.get("length"))
        flags = []
        if molecule == "CHROMOSOME":
            if has_marker:
                flags.append("integrated_plasmid_candidate" if length >= largest_chromosome else "chromid_candidate")
            elif length < largest_chromosome and length >= chromid_min_bp:
                flags.append("secondary_chromosome")
        elif molecule == "PLASMID":
            if len(rep) >= 2:
                flags.append("multi_replicon_plasmid")
            if length >= large_plasmid_bp:
                flags.append("large_plasmid")
            if finding == "plasmid_without_markers":
                flags.append("marker_free_plasmid")
        if seq in multimers:
            flags.append(f"multimer_{multimers[seq]}x")
        record = depth.get(seq)
        if record and (record.get("status") or "") == "flagged":
            if _int(record.get("n_high_regions")) > 0:
                flags.append("collapsed_repeat_candidate")
            if _int(record.get("n_low_regions")) > 0:
                flags.append("low_depth_region")
        rows.append({"sample": sample, "sequence_id": seq, "molecule_type": molecule,
                     "length": row.get("length", ""), "replicon_labels": ",".join(rep),
                     "mob_labels": ",".join(mob), "finding": finding, "flags": ";".join(flags)})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--chromid-min-bp", type=int, default=int(os.environ.get("CHROMID_MIN_BP", CHROMID_MIN_BP)),
                        help="a non-largest chromosome-labelled replicon at least this long is flagged secondary_chromosome (default 350000)")
    parser.add_argument("--large-plasmid-bp", type=int, default=int(os.environ.get("LARGE_PLASMID_BP", LARGE_PLASMID_BP)),
                        help="a PLASMID at least this long is flagged large_plasmid (default 500000)")
    args = parser.parse_args()
    rows = []
    if args.data_dir.is_dir():
        for sample_dir in sorted(p for p in args.data_dir.iterdir() if p.is_dir()):
            rows.extend(audit_sample(sample_dir.name, sample_dir, args.chromid_min_bp, args.large_plasmid_bp))
    else:
        sys.stderr.write(f"[audit_truth_labels] data directory not found: {args.data_dir}; "
                         "nothing audited\n")
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    counts = Counter(r["finding"] for r in rows)
    sys.stderr.write("[audit_truth_labels] " + ", ".join(
        f"{k}={counts[k]}" for k in sorted(counts)) + f" -> {args.out}\n")
    flag_counts = Counter(flag for r in rows for flag in r["flags"].split(";") if flag)
    if flag_counts:
        sys.stderr.write("[audit_truth_labels] flags: " + ", ".join(f"{k}={flag_counts[k]}" for k in sorted(flag_counts)) + "\n")
    flagged = counts["chromosome_with_plasmid_markers"] + counts["plasmid_without_markers"]
    if flagged:
        sys.stderr.write(f"[audit_truth_labels] {flagged} truth sequence(s) need review; "
                         "scores are unchanged (advisory)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
