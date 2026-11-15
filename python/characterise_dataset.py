#!/usr/bin/env python3
"""Characterise each isolate of the cohort in one table: benchmark.dataset_features.tsv (plan C1).

This COMPOSES the per-isolate measurements the pipeline already makes; it measures nothing itself and replaces no logic:

  contigs.fasta              stage 3 (the assembly the tools are given)  size, contigs, N50, GC of the isolate's OWN assembly, measured here
  assembly_stats.tsv         compute_assembly_stats.py   the REFERENCE's statistics: only the (truth) plasmid count is used
  observed_depth.tsv         measure_depth.py            depth against the labelled reference length
  observed_read_quality.tsv  measure_read_quality.py     mean Phred quality of the long reads
  truth_repeat_content.tsv   repeat_content.py           per-replicon repeat content of the truth
  difficulty_features.tsv    compute_difficulty_features.py  dead ends, depth ratio, Mash distance (RUN_DIFFICULTY_FEATURES)
  the sample sheet                                       organism and Gram group

Every column carries a basis, listed in FEATURES:
  truth_free     knowable for an isolate that has no reference (its reads, its own assembly, its organism). The ONLY columns a live recommendation may use.
                 A truth-free column is never read from a reference-derived file (test_dataset_features.py checks the source of every one)
                 (recommendation_model.TRUTH_DERIVED_FIELDS lists what is forbidden; test_dataset_features.py checks the two agree).
  truth_derived  measured against the reference, so known only in a retrospective benchmark: shown to explain results, never a model input.
A value that was not measured is blank, never zero. Standard library only.

Usage: characterise_dataset.py --data-dir DATA --sample-sheet samples.tsv --out benchmark.dataset_features.tsv
"""
import argparse
import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import recommendation_model as rm  # noqa: E402

# the only sources a truth-free column may come from (the reference-derived files are listed in TRUTH_DERIVED_SOURCES)
TRUTH_FREE_SOURCES = {"sample sheet", "contigs.fasta", "observed_read_quality.tsv"}

# (column, basis, source file, label). The order is the column order.
FEATURES = [
    ("organism", "truth_free", "sample sheet", "Organism"),
    ("gram_group", "truth_free", "sample sheet", "Gram group"),
    ("read_depth_x", "truth_free", "sample sheet", "Read depth (x), as declared"),
    ("input_assembly_size_bp", "truth_free", "contigs.fasta", "Assembly size (bp), own assembly"),
    ("input_contig_count", "truth_free", "contigs.fasta", "Contigs, own assembly"),
    ("input_n50", "truth_free", "contigs.fasta", "N50 (bp), own assembly"),
    ("input_gc_percent", "truth_free", "contigs.fasta", "GC (%), own assembly"),
    ("mean_read_quality", "truth_free", "observed_read_quality.tsv", "Mean long-read Phred quality"),
    ("plasmid_count", "truth_derived", "assembly_stats.tsv", "Truth plasmids"),
    ("max_internal_repeat_fraction", "truth_derived", "truth_repeat_content.tsv", "Largest plasmid internal repeat fraction"),
    ("max_chromosome_shared_fraction", "truth_derived", "truth_repeat_content.tsv", "Largest plasmid fraction shared with the chromosome"),
    ("repeat_rich_plasmids", "truth_derived", "truth_repeat_content.tsv", "Repeat-rich plasmids"),
    ("gfa_dead_end_count", "truth_derived", "difficulty_features.tsv", "Assembly-graph dead ends"),
    ("plasmid_chromosome_depth_ratio", "truth_derived", "difficulty_features.tsv", "Plasmid/chromosome depth ratio"),
    ("plasmid_chromosome_mash_distance", "truth_derived", "difficulty_features.tsv", "Plasmid/chromosome Mash distance"),
]
COLUMNS = ["sample"] + [name for name, *_ in FEATURES]
TRUTH_FREE = [name for name, basis, *_ in FEATURES if basis == "truth_free"]
TRUTH_DERIVED = [name for name, basis, *_ in FEATURES if basis == "truth_derived"]


def read_rows(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        return []
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader((line for line in handle if line.strip() and not line.lstrip().startswith("#")), delimiter="\t"))
    except (OSError, csv.Error):
        return []


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def worst(values):
    values = [v for v in values if v is not None]
    return max(values) if values else None


def characterise(sample, sample_dir, metadata):
    """One row for one isolate; every field that its files do not give stays blank."""
    row = {name: "" for name in COLUMNS}
    row["sample"] = sample
    for field in ("organism", "gram_group", "read_depth_x"):
        row[field] = (metadata.get(field) or "").strip()
    own = {}
    for name in ("contigs.fasta", "contigs.fasta.gz"):
        if (sample_dir / name).is_file():
            own = rm.assembly_stats_of_fasta(sample_dir / name)
            break
    for field in rm.ASSEMBLY_STAT_FIELDS:
        row[field] = own.get(field, "")
    stats = (read_rows(sample_dir / "assembly_stats.tsv") or [{}])[0]
    row["plasmid_count"] = (stats.get("plasmid_count") or "").strip()
    quality = (read_rows(sample_dir / "observed_read_quality.tsv") or [{}])[0]
    row["mean_read_quality"] = (quality.get("mean_phred_quality") or "").strip()
    plasmids = [r for r in read_rows(sample_dir / "truth_repeat_content.tsv") if r.get("molecule_type") == "PLASMID" and r.get("status") != "missing_sequence"]
    internal = worst(number(r.get("internal_repeat_fraction")) for r in plasmids)
    shared = worst(number(r.get("chromosome_shared_fraction")) for r in plasmids)
    row["max_internal_repeat_fraction"] = f"{internal:.4f}" if internal is not None else ""
    row["max_chromosome_shared_fraction"] = f"{shared:.4f}" if shared is not None else ""
    row["repeat_rich_plasmids"] = str(sum(1 for r in plasmids if r.get("repeat_rich") in ("true", "True", "yes", "1"))) if plasmids else ""
    difficulty = (read_rows(sample_dir / "difficulty_features.tsv") or [{}])[0]
    for field in ("gfa_dead_end_count", "plasmid_chromosome_depth_ratio", "plasmid_chromosome_mash_distance"):
        row[field] = (difficulty.get(field) or "").strip()
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--sample-sheet")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    sheet = {r["sample_id"]: r for r in read_rows(args.sample_sheet) if r.get("sample_id")} if args.sample_sheet else {}
    samples = sorted(set(sheet) | {p.parent.name for p in Path(args.data_dir).glob("*/assembly_stats.tsv")} | {p.parent.name for p in Path(args.data_dir).glob("*/contigs.fasta")})
    rows = [characterise(sample, Path(args.data_dir) / sample, sheet.get(sample, {})) for sample in samples]
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    sys.stderr.write(f"[characterise_dataset] {len(rows)} isolate(s) -> {args.out}\n")


if __name__ == "__main__":
    main()
