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

Caller status comes from annotation_provenance.json when present; without it the
sample is `not_evaluated`, because an empty feature table cannot tell "found
nothing" from "did not run".
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

MARKER_TYPES = ("replicon", "mob")
# A marker class counts as evaluated only if a caller that produces it reported ok.
MARKER_CALLERS = {"replicon": ("abricate_replicon",), "mob": ("mob_typer",)}
FIELDS = ("sample", "sequence_id", "molecule_type", "length", "replicon_labels",
          "mob_labels", "finding")


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


def audit_sample(sample: str, sample_dir: Path):
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
    rows = []
    for row in read_tsv(truth_path):
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
        rows.append({"sample": sample, "sequence_id": seq, "molecule_type": molecule,
                     "length": row.get("length", ""), "replicon_labels": ",".join(rep),
                     "mob_labels": ",".join(mob), "finding": finding})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    rows = []
    if args.data_dir.is_dir():
        for sample_dir in sorted(p for p in args.data_dir.iterdir() if p.is_dir()):
            rows.extend(audit_sample(sample_dir.name, sample_dir))
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
    flagged = counts["chromosome_with_plasmid_markers"] + counts["plasmid_without_markers"]
    if flagged:
        sys.stderr.write(f"[audit_truth_labels] {flagged} truth sequence(s) need review; "
                         "scores are unchanged (advisory)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
