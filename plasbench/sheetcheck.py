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
    return "source_cohort" in cols and "biosample" in cols and "organism" not in cols and "truth_technology" not in cols


def missing_curated(columns) -> list[str]:
    cols = set(columns)
    return [c for c in CURATED_COLUMNS if c not in cols]


def is_benchmark_sheet(path) -> bool:
    """True when the file has every column a curated run needs (so it can appear in a cohort picker)."""
    columns = header(path)
    return bool(columns) and not missing_curated(columns)


def refusal(path, available=None) -> str:
    """'' when the sheet has the curated columns; otherwise one message saying what the file is and what to use instead."""
    path = Path(path)
    columns = header(path)
    if not columns:
        return f"{path} is empty or not readable as a tab-separated sheet"
    missing = missing_curated(columns)
    if not missing:
        return ""
    use = ""
    if available:
        use = f" Use one of the cohort sheets instead, for example: {', '.join(available[:6])}."
    if is_ledger(columns):
        return (f"'{path.stem}' is the accession ledger, not a cohort: it lists the BioSamples that earlier cohort releases already used, "
                f"so that a new cohort does not repeat them (columns: {', '.join(columns)}). A benchmark needs {', '.join(CURATED_COLUMNS)} for every isolate."
                f"{use} Its source_cohort column says which cohort each row came from.")
    return (f"'{path.stem}' is not a benchmark sheet: it has no {', '.join(missing)} column{'s' if len(missing) > 1 else ''} "
            f"(a run needs {', '.join(CURATED_COLUMNS)} for every isolate; see docs/INPUT_GUIDE.md).{use}")


def cohort_sheets(cohorts_dir) -> list[str]:
    """The names in cohorts/ that are benchmark sheets: *.tsv with the curated columns, not the ledger, not metagenomic or auxiliary tables."""
    out = []
    for path in sorted(Path(cohorts_dir).glob("*.tsv")):
        if path.stem.startswith("metagenomics-") or is_ledger(header(path)):
            continue
        if is_benchmark_sheet(path):
            out.append(path.stem)
    return out
