#!/usr/bin/env python3
"""Regression for python/parse_teixeira2025_supplement.py: the one-time
migration of Teixeira et al. 2025's Supplementary Table S1 into a versioned
candidate ledger. Confirms (1) every source-paper provenance field
round-trips, (2) assembly_accession/sra_run are left empty -- this ledger is
explicitly NOT curate-cohort-ready until resolve_ncbi_accessions.py runs --
and (3) a blank footnote-only row (no biosample) is skipped, not turned into
a bogus candidate.
"""
import csv
import os
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))

from parse_teixeira2025_supplement import build_candidates, read_raw_rows, write_candidates  # noqa: E402

RAW_FIXTURE = """# a comment line, matching the real raw file's provenance header
biosample\ttaxon\tidentifier\tprior_illumina_assembly_source\tillumina_instrument\tprior_hybrid_assembly_source\tlong_read_instrument
SAMN00000001\tEscherichia coli\tISO1\tSmith et al., 2020\tHiSeq 2500\tnewly sequenced\tGridION
SAMN00000002\tEnterococcus faecalis\tISO2\tnewly sequenced\tNovaSeq 6000\tnewly sequenced\tGridION
\tstray footnote text, no real biosample\t\t\t\t\t
"""


def main():
    with tempfile.TemporaryDirectory() as tmp:
        raw_path = Path(tmp) / "raw.tsv"
        raw_path.write_text(RAW_FIXTURE, encoding="utf-8")
        raw_rows = read_raw_rows(raw_path)
        assert len(raw_rows) == 3, f"expected 3 raw rows (footnote row has content, so it is not pre-filtered), got {len(raw_rows)}"

        candidates = build_candidates(raw_rows, "2026-09-07")
        assert len(candidates) == 2, f"the empty-biosample footnote row must be skipped, got {len(candidates)}"
        print("a footnote row with no real biosample is skipped, not turned into a bogus candidate -> PASS")

        first = candidates[0]
        assert first["biosample"] == "SAMN00000001"
        assert first["organism"] == "Escherichia coli"
        assert first["paper_identifier"] == "ISO1"
        assert first["source_study"] == "Teixeira_2025_bbaf589"
        assert first["source_doi"] == "10.1093/bib/bbaf589"
        assert first["source_table"] == "ST1"
        assert first["prior_illumina_assembly_source"] == "Smith et al., 2020"
        assert first["illumina_instrument"] == "HiSeq 2500"
        print("source-paper provenance fields round-trip from the raw row -> PASS")

        assert first["assembly_accession"] == "" and first["sra_run"] == "", (
            "assembly_accession/sra_run must stay empty -- this ledger is not "
            "curate-cohort-ready until resolve_ncbi_accessions.py runs"
        )
        print("assembly_accession/sra_run are left empty, pending NCBI resolution -> PASS")

        assert candidates[0]["sample_id"] != candidates[1]["sample_id"]
        assert candidates[0]["sample_id"].endswith("_001") and candidates[1]["sample_id"].endswith("_002")
        print("sample_id is deterministic and unique per row -> PASS")

        out_path = Path(tmp) / "candidates.tsv"
        write_candidates(out_path, candidates, "2026-09-07")
        with open(out_path, newline="", encoding="utf-8") as handle:
            written = list(csv.DictReader(
                (line for line in handle if line.strip() and not line.lstrip().startswith("#")),
                delimiter="\t",
            ))
        assert written == candidates, "written TSV must round-trip back to the same rows"
        out_text = out_path.read_text(encoding="utf-8")
        assert "NOT yet valid input to `plasbench curate-cohort`" in out_text, (
            "the output file's header must warn that resolution is required first"
        )
        print("the written TSV round-trips and carries the curate-cohort warning header -> PASS")

    print("\nALL TEIXEIRA2025 SUPPLEMENT PARSING TESTS PASSED")


if __name__ == "__main__":
    main()
