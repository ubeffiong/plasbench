"""Is this file a benchmark sample sheet, and if not, what is it?

`plasbench run --cohort accepted_accessions` once failed in stage 0 with one "uncurated sample-sheet row N" error per isolate, because
`cohorts/accepted_accessions.tsv` is the accession LEDGER (the BioSamples already used by a cohort release, written by `plasbench build-ledger`),
not a cohort. This module recognises that file, and any sheet that lacks the columns a run needs, so the command can stop before it creates a
study folder and say what is wrong once.

Standard library only; the stage-0 check in scripts/lib.sh (`validate_sample_sheet`) stays the authority for the per-row rules.
"""
from __future__ import annotations

from pathlib import Path

# What stage 0 requires of every row when REQUIRE_CURATED_METADATA is on (the default): scripts/lib.sh validate_sample_sheet.
CURATED_COLUMNS = ("organism", "truth_technology", "truth_quality_tier", "biosample", "bioproject")
# The accession ledger's header (python/build_accession_ledger.py).
LEDGER_COLUMNS = ("biosample", "sample_id", "assembly_accession", "sra_run", "source_cohort")


def header(path) -> list[str]:
    """The column names of a tab-separated sheet: its first line that is not blank and not a # comment. [] when the file cannot be read."""
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as handle:
            for line in handle:
                if line.strip() and not line.lstrip().startswith("#"):
                    return [c.strip() for c in line.rstrip("\r\n").split("\t")]
    except OSError:
        return []
    return []


def is_ledger(columns) -> bool:
    """The accession ledger: it carries source_cohort and none of the curated truth columns."""
    cols = set(columns)
    return {"biosample", "source_cohort"} <= cols and not cols & {"organism", "truth_technology", "community_id"}


def missing_curated(columns) -> list[str]:
    cols = set(columns)
    return [c for c in CURATED_COLUMNS if c not in cols]


def looks_like_sample_sheet(columns) -> bool:
    """A file a run could use: it has a sample_id column and is neither the accession ledger nor a metagenomic table. Whether it ALSO has the curated columns is stage 0's
    business (REQUIRE_CURATED_METADATA can be switched off in config/local.env, which the command line does not read), so a minimal sheet is never refused here."""
    cols = set(columns)
    return "sample_id" in cols and not is_ledger(cols) and "community_id" not in cols


def is_benchmark_sheet(path) -> bool:
    """True when the file has every column a curated run needs."""
    columns = header(path)
    return bool(columns) and not missing_curated(columns)


def refusal(path, available=None) -> str:
    """'' unless the file certainly cannot be a cohort: the accession ledger, or a table with no sample_id column. A sheet that merely lacks curated columns is left to stage 0."""
    path = Path(path)
    columns = header(path)
    if not columns:
        return f"{path} is empty or not readable as a tab-separated sheet"
    use = f" Use one of the cohort sheets instead, for example: {', '.join(available[:6])}." if available else ""
    if is_ledger(columns):
        return (f"'{path.stem}' is the accession ledger, not a cohort: it lists the BioSamples that earlier cohort releases already used, "
                f"so that a new cohort does not repeat them (columns: {', '.join(columns)}). A benchmark needs {', '.join(CURATED_COLUMNS)} for every isolate."
                f"{use} Its source_cohort column says which cohort each row came from.")
    if "sample_id" not in columns:
        return (f"'{path.stem}' is not a sample sheet: it has no sample_id column (its columns: {', '.join(columns)}). "
                f"A run needs sample_id, assembly_accession and sra_run for every isolate (see docs/INPUT_GUIDE.md).{use}")
    return ""


def cohort_sheets(cohorts_dir) -> list[str]:
    """The names in cohorts/ that a run can use: *.tsv with a sample_id column, not the ledger, not a metagenomic or auxiliary table."""
    out = []
    for path in sorted(Path(cohorts_dir).glob("*.tsv")):
        if path.stem.startswith("metagenomics"):
            continue
        if looks_like_sample_sheet(header(path)):
            out.append(path.stem)
    return out
