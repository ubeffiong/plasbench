#!/usr/bin/env python3
"""Validate a candidate external tool/dataset before it enters PlasBench work."""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


REQUIRED = {"candidate_id", "kind", "source_url", "license_review", "scope_fit", "truth_quality", "independence_review", "database_leakage_review", "output_contract", "dependency_status", "decision"}
ALLOWED_KIND = {"tool", "dataset", "workflow", "evidence_provider"}
ALLOWED_DECISION = {"approved_for_evaluation", "research_only", "rejected", "pending"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intake", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        with args.intake.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            if reader.fieldnames is None or not REQUIRED.issubset(reader.fieldnames):
                raise ValueError("missing columns: " + ", ".join(sorted(REQUIRED - set(reader.fieldnames or []))))
            rows = list(reader)
        errors = []
        ids = set()
        for index, row in enumerate(rows, 2):
            if not row["candidate_id"] or row["candidate_id"] in ids:
                errors.append(f"row {index}: candidate_id must be present and unique")
            ids.add(row["candidate_id"])
            if row["kind"] not in ALLOWED_KIND:
                errors.append(f"row {index}: unsupported kind {row['kind']!r}")
            if not row["source_url"].startswith("https://"):
                errors.append(f"row {index}: source_url must be HTTPS")
            if row["decision"] not in ALLOWED_DECISION:
                errors.append(f"row {index}: invalid decision {row['decision']!r}")
            if row["decision"] == "approved_for_evaluation":
                for field in ("license_review", "scope_fit", "truth_quality", "independence_review", "database_leakage_review", "output_contract", "dependency_status"):
                    if row[field].strip().lower() not in {"approved", "not_applicable"}:
                        errors.append(f"row {index}: approved candidate has unresolved {field}")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if errors:
        print("METAGENOMIC INTAKE INVALID:", file=sys.stderr); print("\n".join(f"  - {error}" for error in errors), file=sys.stderr)
        return 2
    print(f"METAGENOMIC INTAKE VALID: {len(rows)} candidate records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
