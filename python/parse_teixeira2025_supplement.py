#!/usr/bin/env python3
"""One-time migration: turn Teixeira et al. 2025's Supplementary Table S1
into a versioned, source-attributed CANDIDATE ledger.

This is deliberately NOT a curate-cohort-ready candidate table yet: ST1 only
gives BioSample, Taxon, and the paper's own isolate Identifier -- it has no
assembly_accession or sra_run column (Table S1 is "Biosample identifiers and
assembly statistics", not an accession table), so this script leaves those
two columns empty, explicitly pending NCBI resolution (see
resolve_ncbi_accessions.py). curate_cohort.py refuses to run against a
candidates file with either column empty, by design -- that refusal is
exactly what stops this ledger from being used as a cohort input before
resolution.

Input is cohorts/candidates/teixeira2025_table_s1_raw.tsv, a raw, unmodified
transcription of ST1 (biosample, taxon, identifier, and four provenance
columns) checked into the repo separately from this script, since ST1 itself
is a small, precise data table (250 rows) worth keeping under version control
and auditable independent of the extraction code -- not the underlying
publisher xlsx itself, which is not committed here (copyrighted supplementary
material; see the paper's own Supplementary data link instead).

Usage:
  parse_teixeira2025_supplement.py \
      --raw cohorts/candidates/teixeira2025_table_s1_raw.tsv \
      --out cohorts/candidates/teixeira2025_candidates.tsv
"""

import argparse
import csv
import re
from pathlib import Path

SOURCE_DOI = "10.1093/bib/bbaf589"
SOURCE_STUDY = "Teixeira_2025_bbaf589"
SOURCE_TABLE = "ST1"

OUT_COLUMNS = (
    "sample_id", "assembly_accession", "sra_run", "organism", "biosample",
    "source_study", "source_doi", "source_table", "paper_identifier",
    "prior_illumina_assembly_source", "illumina_instrument",
    "prior_hybrid_assembly_source", "long_read_instrument",
)


def safe_id(value, index):
    """Matches curate_cohort.py's own safe_id() exactly, so a sample_id
    minted here looks identical in shape to one minted there -- this ledger
    is a preview of what curate-cohort will eventually assign, not a
    competing convention."""
    value = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return (value or "candidate") + f"_{index:03d}"


def read_raw_rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(
            (line for line in handle if line.strip() and not line.lstrip().startswith("#")),
            delimiter="\t",
        ))


def build_candidates(raw_rows, extraction_date):
    candidates = []
    for index, row in enumerate(raw_rows, 1):
        biosample, taxon, identifier = row["biosample"], row["taxon"], row["identifier"]
        if not biosample or not taxon:
            continue  # a blank trailing/footnote row, not a real isolate
        candidates.append({
            "sample_id": safe_id(f"{taxon}_{identifier}", index),
            "assembly_accession": "",  # pending: see resolve_ncbi_accessions.py
            "sra_run": "",             # pending: see resolve_ncbi_accessions.py
            "organism": taxon,
            "biosample": biosample,
            "source_study": SOURCE_STUDY,
            "source_doi": SOURCE_DOI,
            "source_table": SOURCE_TABLE,
            "paper_identifier": identifier,
            "prior_illumina_assembly_source": row.get("prior_illumina_assembly_source", ""),
            "illumina_instrument": row.get("illumina_instrument", ""),
            "prior_hybrid_assembly_source": row.get("prior_hybrid_assembly_source", ""),
            "long_read_instrument": row.get("long_read_instrument", ""),
        })
    return candidates


def write_candidates(path, candidates, extraction_date):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        handle.write(
            f"# Versioned candidate ledger extracted from {SOURCE_TABLE} of "
            f"{SOURCE_STUDY.replace('_', ' ')} (DOI {SOURCE_DOI}) on {extraction_date}.\n"
            "# assembly_accession/sra_run are intentionally empty pending NCBI\n"
            "# resolution (see python/resolve_ncbi_accessions.py) -- this file is\n"
            "# NOT yet valid input to `plasbench curate-cohort`, which requires\n"
            "# both columns populated. Never merge these rows directly into a\n"
            "# public-vN cohort: run resolve_ncbi_accessions.py, then\n"
            "# curate-cohort, then a stratified pilot download/score, before any\n"
            "# release (see docs/FINDING_DATA.md).\n"
        )
        writer = csv.DictWriter(handle, fieldnames=OUT_COLUMNS, delimiter="\t")
        writer.writeheader()
        writer.writerows(candidates)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw", default="cohorts/candidates/teixeira2025_table_s1_raw.tsv")
    parser.add_argument("--out", default="cohorts/candidates/teixeira2025_candidates.tsv")
    parser.add_argument("--extraction-date", default="2026-09-07",
                        help="Recorded in the output header; default matches when this ledger was first built.")
    args = parser.parse_args()

    raw_rows = read_raw_rows(args.raw)
    if not raw_rows:
        raise SystemExit(f"ERROR: no data rows found in {args.raw}")
    candidates = build_candidates(raw_rows, args.extraction_date)
    write_candidates(args.out, candidates, args.extraction_date)
    print(f"Wrote {args.out}: {len(candidates)} candidate(s) from {len(raw_rows)} raw ST1 row(s)")
    print("assembly_accession/sra_run are empty; resolve with resolve_ncbi_accessions.py before curate-cohort.")


if __name__ == "__main__":
    main()
