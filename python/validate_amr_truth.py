#!/usr/bin/env python3
"""Validate curated, versioned plasmid AMR truth annotations.

PlasBench does not call AMR genes from the predictions it scores. This validator
requires independently curated reference coordinates and database provenance so
AMR recovery remains a truth-set metric rather than circular evidence.
"""

import argparse
import csv
import re
import sys


REQUIRED = ("sequence_id", "start", "end", "gene_name", "gene_id", "copy_id",
            "database", "database_version")
GENE = re.compile(r"^[A-Za-z0-9_.:+()/-]+$")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--amr-truth", required=True)
    parser.add_argument("--truth", required=True, help="truth.tsv used to ensure annotations are plasmid coordinates")
    args = parser.parse_args()
    with open(args.truth, newline="", encoding="utf-8") as handle:
        truth = {row["sequence_id"]: row for row in csv.DictReader(handle, delimiter="\t")}
    with open(args.amr_truth, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not set(REQUIRED).issubset(reader.fieldnames or []):
            raise SystemExit("ERROR: AMR truth requires columns: " + ", ".join(REQUIRED))
        seen = set()
        for line, row in enumerate(reader, 2):
            copy_id = (row["copy_id"] or "").strip()
            if not copy_id or copy_id in seen: raise SystemExit(f"ERROR: line {line}: copy_id must be unique and nonempty")
            seen.add(copy_id)
            if not GENE.match((row["gene_name"] or "").strip()): raise SystemExit(f"ERROR: line {line}: gene_name is not normalized")
            if not row["gene_id"].strip() or not row["database"].strip() or not row["database_version"].strip():
                raise SystemExit(f"ERROR: line {line}: gene_id, database, and database_version are required")
            sequence = row["sequence_id"]
            if sequence not in truth or truth[sequence]["molecule_type"].upper() != "PLASMID":
                raise SystemExit(f"ERROR: line {line}: sequence_id is not a labelled plasmid")
            try: start, end = int(row["start"]), int(row["end"])
            except ValueError: raise SystemExit(f"ERROR: line {line}: start/end must be integers")
            if not 0 <= start < end <= int(truth[sequence]["length"]):
                raise SystemExit(f"ERROR: line {line}: coordinates fall outside the plasmid reference")
    print(f"AMR TRUTH VALIDATION PASSED: {len(seen)} independently curated gene copy/copies")


if __name__ == "__main__":
    main()
