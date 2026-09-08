#!/usr/bin/env python3
"""Audit a community manifest for comparability, coverage, and leakage risks."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from metagenomics import read_tsv, validate_manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--release-ready", action="store_true", help="Fail on duplicate reference clusters or non-operational synthetic/mock cohorts.")
    args = parser.parse_args(argv)
    rows, errors = validate_manifest(args.manifest, release_ready=args.release_ready)
    communities = defaultdict(list)
    for row in rows:
        communities[row["community_id"]].append(row)
    clusters = defaultdict(set)
    studies = defaultdict(set)
    for community, values in communities.items():
        for row in values:
            if row.get("reference_cluster_id"):
                clusters[row["reference_cluster_id"]].add(community)
            if row.get("source_study"):
                studies[row["source_study"]].add(community)
    duplicated_clusters = {cluster: sorted(values) for cluster, values in clusters.items() if len(values) > 1}
    if args.release_ready and duplicated_clusters:
        errors.append("release-ready cohort reuses reference_cluster_id across communities: " + "; ".join(f"{key} ({','.join(value)})" for key, value in sorted(duplicated_clusters.items())))
    if args.release_ready and any(row["truth_status"] in {"synthetic", "mock"} for row in rows):
        errors.append("release-ready operational cohort contains synthetic or mock community rows")
    report = {"manifest": str(args.manifest.resolve()), "communities": len(communities), "samples": len(rows), "information_regimes": dict(Counter(row["information_regime"] for row in rows)), "truth_statuses": dict(Counter(row["truth_status"] for row in rows)), "dataset_classes": dict(Counter(row.get("dataset_class") or "unspecified" for row in rows)), "source_studies": {key: sorted(value) for key, value in sorted(studies.items())}, "reused_reference_clusters": duplicated_clusters, "errors": errors, "release_ready": args.release_ready}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if errors:
        print("METAGENOMIC COHORT AUDIT FAILED:", file=sys.stderr)
        print("\n".join(f"  - {error}" for error in errors), file=sys.stderr)
        return 2
    print(f"METAGENOMIC COHORT AUDIT VALID: {len(communities)} communities; report: {args.out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
