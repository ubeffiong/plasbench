#!/usr/bin/env python3
"""Materialize the independently released BMock12 contig-level gold standard.

This downloads only the compact benchmark artifacts by default.  The original
Illumina run contains about 64 Gbp of sequence, so the raw-read accession is recorded in the
provenance but never downloaded implicitly.  The resulting manifest is a real
physical-community, truth-scored *negative plasmid control*: the released gold
standard labels source genome bins but does not make a validated positive
plasmid-bin assertion.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


REQUIRED = {"artifact_id", "url", "md5", "role"}


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames or not REQUIRED.issubset(reader.fieldnames):
            missing = REQUIRED - set(reader.fieldnames or [])
            raise ValueError(f"{path}: missing columns: {', '.join(sorted(missing))}")
        return [{key: (value or "").strip() for key, value in row.items()} for row in reader]


def digest(path: Path) -> str:
    hasher = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def fetch(url: str, destination: Path, expected_md5: str, retries: int) -> None:
    """Download atomically and reject corrupted or partially resumed artifacts."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and digest(destination) == expected_md5:
        print(f"[bmock12] reuse verified {destination.name}")
        return
    partial = destination.with_suffix(destination.suffix + ".part")
    partial.unlink(missing_ok=True)
    for attempt in range(1, retries + 1):
        try:
            # Figshare redirects to time-limited object-storage URLs; an explicit
            # agent keeps that public redirect path compatible with strict hosts.
            request = Request(url, headers={"User-Agent": "PlasBench metagenomic-control materializer"})
            with urlopen(request, timeout=60) as response, partial.open("wb") as handle:
                shutil.copyfileobj(response, handle)
            actual = digest(partial)
            if actual != expected_md5:
                raise ValueError(f"checksum mismatch for {destination.name}: expected {expected_md5}, got {actual}")
            os.replace(partial, destination)
            print(f"[bmock12] downloaded and verified {destination.name}")
            return
        except (OSError, URLError, ValueError) as exc:
            partial.unlink(missing_ok=True)
            if attempt == retries:
                raise RuntimeError(f"could not materialize {destination.name}: {exc}") from exc
            delay = min(30, 2 ** (attempt - 1))
            print(f"[bmock12] download attempt {attempt}/{retries} failed; retrying in {delay}s: {exc}", file=sys.stderr)
            time.sleep(delay)


def write_truth(gold_standard: Path, out: Path) -> int:
    """Convert AMBER's GSA membership table into PlasBench contig truth.

    BMock12's released gold standard identifies the source genome for every
    scaffolding contig.  It deliberately does not identify plasmid replicons,
    therefore labels are chromosome and this materialized control evaluates
    specificity/contamination, not plasmid recall.
    """
    rows: list[tuple[str, str]] = []
    seen: dict[str, str] = {}
    with gold_standard.open(encoding="utf-8") as handle:
        for line in handle:
            if not line or line.startswith("@"):
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 2:
                raise ValueError(f"{gold_standard}: malformed GSA row: {line!r}")
            contig_id, source_bin = fields[0], fields[1]
            if not contig_id or not source_bin:
                raise ValueError(f"{gold_standard}: empty contig or source-bin identifier")
            previous = seen.get(contig_id)
            if previous is not None:
                raise ValueError(
                    f"{gold_standard}: duplicate contig membership for {contig_id} "
                    f"({previous}, {source_bin})"
                )
            seen[contig_id] = source_bin
            rows.append((contig_id, source_bin))
    if not rows:
        raise ValueError(f"{gold_standard}: no contig memberships")
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=("contig_id", "truth_bin_id", "biological_class"))
        writer.writeheader()
        writer.writerows({"contig_id": contig, "truth_bin_id": source_bin, "biological_class": "chromosome"} for contig, source_bin in rows)
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True, help="Directory for verified artifacts and generated manifest.")
    parser.add_argument("--source-manifest", type=Path, default=Path("config/metagenomic_truth_sources.tsv"))
    parser.add_argument("--retries", type=int, default=3)
    args = parser.parse_args(argv)
    if args.retries < 1:
        parser.error("--retries must be positive")
    rows = [row for row in read_tsv(args.source_manifest) if row.get("cohort_id") == "bmock12"]
    if not rows:
        raise SystemExit(f"ERROR: {args.source_manifest} has no bmock12 source artifacts")
    root = args.out_dir.resolve() / "bmock12"
    paths: dict[str, Path] = {}
    source_records = []
    for row in rows:
        name = row.get("filename") or row["artifact_id"]
        target = root / name
        fetch(row["url"], target, row["md5"], args.retries)
        paths[row["role"]] = target
        source_records.append({**row, "local_path": str(target), "verified_md5": digest(target)})
    missing = {"assembly_fasta_gz", "assembly_graph_gz", "gold_standard"} - set(paths)
    if missing:
        raise SystemExit(f"ERROR: BMock12 source manifest lacks required roles: {', '.join(sorted(missing))}")
    assembly = root / "scaffolds.fasta"
    if not assembly.is_file():
        with gzip.open(paths["assembly_fasta_gz"], "rb") as source, assembly.open("wb") as target:
            shutil.copyfileobj(source, target)
    graph = root / "assembly_graph_with_scaffolds.gfa"
    if not graph.is_file():
        with gzip.open(paths["assembly_graph_gz"], "rb") as source, graph.open("wb") as target:
            shutil.copyfileobj(source, target)
    truth = root / "truth_contigs.tsv"
    memberships = write_truth(paths["gold_standard"], truth)
    manifest = root / "metagenomics-bmock12-verified.tsv"
    fields = ["community_id", "sample_id", "information_regime", "truth_status", "assembly_fasta", "assembly_graph_gfa", "truth_contigs_tsv", "source_country", "source_environment", "dataset_class", "dataset_license", "truth_provenance", "independence_status", "database_overlap_status", "tool_mode", "comparability_group", "database_identity", "source_study", "input_read_technology", "preprocessing_profile", "assembly_profile", "community_complexity", "phage_burden", "contamination_level", "reference_cluster_id", "notes"]
    with manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fields)
        writer.writeheader()
        writer.writerow({
            "community_id": "bmock12_illumina", "sample_id": "SRR8073716", "information_regime": "single_sample", "truth_status": "verified",
            "assembly_fasta": str(assembly), "assembly_graph_gfa": str(graph), "truth_contigs_tsv": str(truth),
            "source_country": "United_States", "source_environment": "defined_mock_community", "dataset_class": "physical_mock_community",
            "dataset_license": "CC-BY-4.0 gold-standard artifacts; NCBI SRA terms for reads", "truth_provenance": "Figshare BMock12 v2 gold_standard.gsa, checksum-verified and converted without inference",
            "independence_status": "independent_released_gold_standard", "database_overlap_status": "tool_database_review_required", "tool_mode": "community_benchmark",
            "comparability_group": "physical_mock_negative_plasmid_control", "database_identity": "not_applicable_before_tool_run", "source_study": "PRJNA496047",
            "input_read_technology": "Illumina HiSeq 2500", "preprocessing_profile": "published BMock12 artifact", "assembly_profile": "published BMock12 scaffolds and graph",
            "community_complexity": "medium", "phage_burden": "unknown", "contamination_level": "unknown", "reference_cluster_id": "bmock12",
            "notes": "Real physical mock. The released gold standard provides source-genome membership but no validated plasmid-positive labels; use for chromosome specificity and plasmid false-positive assessment, never plasmid-recall ranking.",
        })
    provenance = {"cohort": "BMock12", "raw_read_accession": "SRR8073716", "bioproject": "PRJNA496047", "biosample": "SAMN10236717", "gold_standard_scope": "source-genome membership; chromosome-only PlasBench truth", "truth_rows": memberships, "artifacts": source_records}
    (root / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print(f"BMOCK12 MATERIALIZED: {memberships} verified truth contigs; manifest: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
