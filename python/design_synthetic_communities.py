#!/usr/bin/env python3
"""Build a deterministic, truth-labelled community simulation design.

This deliberately writes a design and PlasBench manifest, not invented FASTQs.
An approved simulator/container must materialise reads later, with its exact
version and digest recorded.  That keeps synthetic truth construction useful
without presenting a mock community as a real cohort.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


REQUIRED = {"community_id", "sample_id", "reference_fasta", "abundance_percent", "coverage_x", "plasmid_copy_number", "community_complexity", "phage_burden", "contamination_level"}


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None or not REQUIRED.issubset(reader.fieldnames):
            missing = REQUIRED - set(reader.fieldnames or [])
            raise ValueError(f"{path}: missing required columns: {', '.join(sorted(missing))}")
        return [{key: (value or "").strip() for key, value in row.items()} for row in reader]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--members", type=Path, required=True, help="TSV following cohorts/metagenomics.synthetic-members.example.tsv")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--simulator", default="CAMISIM", help="Declared simulator; no simulator is invoked by this command.")
    parser.add_argument("--simulator-version", required=True)
    parser.add_argument("--container-image", required=True)
    parser.add_argument("--container-digest", required=True)
    args = parser.parse_args(argv)
    try:
        members = rows(args.members)
        if not members:
            raise ValueError(f"{args.members}: no community members")
        by_community: dict[str, list[dict[str, str]]] = {}
        for row in members:
            reference = (args.members.parent / row["reference_fasta"]).resolve() if not Path(row["reference_fasta"]).is_absolute() else Path(row["reference_fasta"])
            if not reference.is_file():
                raise ValueError(f"{row['community_id']}/{row['sample_id']}: reference_fasta does not exist: {row['reference_fasta']}")
            for field in ("abundance_percent", "coverage_x", "plasmid_copy_number"):
                if float(row[field]) <= 0:
                    raise ValueError(f"{row['community_id']}/{row['sample_id']}: {field} must be positive")
            by_community.setdefault(row["community_id"], []).append(row)
        for community, values in by_community.items():
            abundance = sum(float(value["abundance_percent"]) for value in values)
            if abs(abundance - 100.0) > 0.01:
                raise ValueError(f"{community}: abundance_percent must sum to 100 (observed {abundance:g})")
        args.out_dir.mkdir(parents=True, exist_ok=True)
        design = []
        manifest = []
        for community, values in sorted(by_community.items()):
            complexity = values[0]["community_complexity"]
            phage = values[0]["phage_burden"]
            contamination = values[0]["contamination_level"]
            for value in values:
                reference = (args.members.parent / value["reference_fasta"]).resolve() if not Path(value["reference_fasta"]).is_absolute() else Path(value["reference_fasta"])
                design.append({**value, "reference_fasta": str(reference), "reference_sha256": sha256(reference), "seed": args.seed, "simulator": args.simulator, "simulator_version": args.simulator_version, "container_image": args.container_image, "container_digest": args.container_digest})
                manifest.append({"community_id": community, "sample_id": value["sample_id"], "information_regime": "multisample", "truth_status": "synthetic", "dataset_class": "synthetic_community", "dataset_license": "local_or_declared_by_curator", "truth_provenance": "truth_constructed_from_declared_complete_references", "independence_status": "synthetic_not_operational", "database_overlap_status": "review_required", "read_depth_x": value["coverage_x"], "tool_mode": "community_benchmark", "comparability_group": f"synthetic/{complexity}/{phage}/{contamination}", "database_identity": "not_applicable_before_tool_run", "container_image": args.container_image, "container_digest": args.container_digest, "input_read_technology": "simulated_short_reads", "preprocessing_profile": "not_materialised", "assembly_profile": "declared_after_materialisation", "assembly_profile_version": "", "coassembly_id": community, "community_complexity": complexity, "phage_burden": phage, "contamination_level": contamination, "reference_cluster_id": f"synthetic:{reference.stem}", "notes": "Synthetic design only; materialise reads with the recorded simulator/container before scoring."})
        fields = list(design[0])
        with (args.out_dir / "synthetic_community.design.tsv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fields); writer.writeheader(); writer.writerows(design)
        fields = list(manifest[0])
        with (args.out_dir / "metagenomics.synthetic.tsv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fields); writer.writeheader(); writer.writerows(manifest)
        (args.out_dir / "synthetic_community.provenance.json").write_text(json.dumps({"seed": args.seed, "simulator": args.simulator, "simulator_version": args.simulator_version, "container_image": args.container_image, "container_digest": args.container_digest, "members_file": str(args.members.resolve()), "design_rows": len(design), "safeguard": "Synthetic community designs must never be merged into a real-world operational leaderboard."}, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"[metagenomics] wrote deterministic synthetic-community design: {args.out_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
