#!/usr/bin/env python3
"""Draft an AMR truth table from reference annotation output (opt-in, NOT curated).

`python/annotate_reference.py` already calls AMRFinderPlus / abricate on each
truth reference and writes a `feature_truth` TSV. The scorer's AMR metrics
(`amr_gene_recall`) instead read `data/<sample>/truth_amr.tsv`, which
`python/validate_amr_truth.py` requires to be independently curated. Nothing
converted one into the other, so on real cohorts `amr_gene_recall` stayed blank.

This script closes that gap WITHOUT weakening the curation rule:

  * It writes `truth_amr.draft.tsv` (never `truth_amr.tsv`), so the scorer cannot
    pick it up by accident. Promoting a draft is a deliberate human step
    (review it, then copy/rename it to `truth_amr.tsv`).
  * Every row carries `evidence_tier = auto_derived`.
  * Annotation runs on the REFERENCE, not on any tool's predictions, so the draft
    is not circular with respect to the tools being scored.

Known limitations (stated in the output, not hidden):
  * The feature table has no gene accession, so `gene_id` is the gene symbol.
  * It records the caller's version, not the AMR database version, so
    `database_version` holds the caller version string. Replace it with the real
    database version when curating.
  * Only AMR features on sequences labelled PLASMID in truth.tsv are kept.
  * By default only AMRFinderPlus rows are used, so overlapping calls from other
    databases are not double counted as separate gene copies.

Standard library only.
"""

import argparse
import csv
import re
import sys

GENE = re.compile(r"^[A-Za-z0-9_.:+()/-]+$")
OUT_FIELDS = ("sequence_id", "start", "end", "gene_name", "gene_id", "copy_id",
              "database", "database_version", "evidence_tier")


def read_truth(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return {row["sequence_id"]: row for row in csv.DictReader(handle, delimiter="\t")}


def derive(features_path, truth, sources):
    rows, skipped = [], {"not_plasmid": 0, "bad_gene_name": 0, "bad_coordinates": 0, "other_source": 0}
    seen = set()
    with open(features_path, newline="", encoding="utf-8") as handle:
        for feature in csv.DictReader(handle, delimiter="\t"):
            if feature.get("feature_type") != "amr":
                continue
            if sources and feature.get("source") not in sources:
                skipped["other_source"] += 1
                continue
            sequence = feature["sequence_id"]
            record = truth.get(sequence)
            if record is None or record["molecule_type"].strip().upper() != "PLASMID":
                skipped["not_plasmid"] += 1
                continue
            gene = re.sub(r"\s+", "_", (feature.get("label") or "").strip())
            if not GENE.match(gene):
                skipped["bad_gene_name"] += 1
                continue
            try:
                start, end = int(feature["start"]), int(feature["end"])
            except (TypeError, ValueError):
                skipped["bad_coordinates"] += 1
                continue
            if not 0 <= start < end <= int(record["length"]):
                skipped["bad_coordinates"] += 1
                continue
            copy_id = f"{sequence}:{start}-{end}:{gene}"
            if copy_id in seen:
                continue
            seen.add(copy_id)
            rows.append({"sequence_id": sequence, "start": start, "end": end,
                         "gene_name": gene, "gene_id": gene, "copy_id": copy_id,
                         "database": feature.get("source") or "unknown",
                         "database_version": feature.get("version") or "unreported",
                         "evidence_tier": "auto_derived"})
    rows.sort(key=lambda r: (r["sequence_id"], r["start"], r["end"], r["gene_name"]))
    return rows, skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--features", required=True, help="feature_truth TSV from annotate_reference.py")
    parser.add_argument("--truth", required=True, help="truth.tsv (sequence_id, molecule_type, length)")
    parser.add_argument("--out", required=True, help="draft AMR truth TSV (use a name other than truth_amr.tsv)")
    parser.add_argument("--source", action="append", default=None,
                        help="feature source to keep, repeatable (default: amrfinderplus)")
    args = parser.parse_args()
    if args.out.replace("\\", "/").rsplit("/", 1)[-1] == "truth_amr.tsv":
        raise SystemExit("ERROR: refusing to write truth_amr.tsv. Write a draft (e.g. truth_amr.draft.tsv) "
                         "and promote it after review.")
    sources = set(args.source or ["amrfinderplus"])
    rows, skipped = derive(args.features, read_truth(args.truth), sources)
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUT_FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    detail = ", ".join(f"{k}={v}" for k, v in skipped.items() if v) or "none"
    sys.stderr.write(f"[derive_amr_truth] wrote {len(rows)} auto-derived AMR gene copy/copies to {args.out}; "
                     f"skipped: {detail}. DRAFT ONLY: review before using as truth_amr.tsv.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
