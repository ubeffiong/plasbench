#!/usr/bin/env python3
"""Validate an auditable optional orthogonal-validation evidence table.

This records laboratory or independent-technology evidence without upgrading a
computational candidate into a confirmed plasmid.  The summary is intended for
the result folder and HTML artifact explorer, while the source TSV remains the
reviewable evidence record.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REQUIRED = {"sample_id", "evidence_type", "evidence_status", "evidence_reference"}
EVIDENCE_TYPES = {"long_read_confirmation", "hybrid_assembly", "targeted_pcr", "plasmid_extraction", "conjugation", "hic_linkage", "optical_mapping"}
STATUSES = {"confirmed", "supportive", "inconclusive", "contradicted"}


def validate(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None:
            return [], ["evidence TSV has no header"]
        missing = REQUIRED - set(reader.fieldnames)
        if missing:
            return [], [f"missing required columns: {', '.join(sorted(missing))}"]
        rows = [{key: (value or "").strip() for key, value in row.items()} for row in reader]
    errors: list[str] = []
    for index, row in enumerate(rows, start=2):
        if not row["sample_id"]:
            errors.append(f"row {index}: sample_id is required")
        if row["evidence_type"] not in EVIDENCE_TYPES:
            errors.append(f"row {index}: unsupported evidence_type {row['evidence_type']!r}")
        if row["evidence_status"] not in STATUSES:
            errors.append(f"row {index}: evidence_status must be one of {', '.join(sorted(STATUSES))}")
        if not row["evidence_reference"]:
            errors.append(f"row {index}: evidence_reference is required; use a public accession, DOI, protocol ID, or lab record ID")
    return rows, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--out", type=Path, help="Write a safe summary JSON for the result directory.")
    args = parser.parse_args(argv)
    try:
        rows, errors = validate(args.evidence)
    except OSError as exc:
        print(f"ORTHOGONAL EVIDENCE INVALID: {exc}", file=sys.stderr); return 2
    if errors:
        print("ORTHOGONAL EVIDENCE INVALID:", file=sys.stderr)
        print("\n".join(f"  - {error}" for error in errors), file=sys.stderr)
        return 2
    by_sample: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        by_sample[row["sample_id"]][row["evidence_status"]] += 1
    summary = {"schema_version": 1, "claim_boundary": "Evidence is supplementary. It does not change benchmark scores, create host assignment, or prove plasmid transmissibility by itself.", "records": len(rows), "by_evidence_type": dict(Counter(row["evidence_type"] for row in rows)), "by_status": dict(Counter(row["evidence_status"] for row in rows)), "by_sample": {sample: dict(counts) for sample, counts in sorted(by_sample.items())}}
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote orthogonal evidence summary: {args.out}")
    print(f"ORTHOGONAL EVIDENCE VALID: {len(rows)} record(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
