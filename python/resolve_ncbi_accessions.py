#!/usr/bin/env python3
"""Resolve BioSample-only candidates to assembly_accession/sra_run via NCBI.

Some candidate sources (e.g. a paper's supplementary table listing BioSample
identifiers but no accession numbers -- see parse_teixeira2025_supplement.py)
give a candidate ledger that curate_cohort.py cannot yet use: it requires
non-empty assembly_accession and sra_run for every row, by design, so an
unresolved ledger is refused rather than silently half-processed. This script
is the resolution step in between: for each row with a biosample and no
assembly_accession, it finds a deposited complete-genome assembly for that
BioSample and a paired Illumina SRA run sharing the assembly's BioProject,
the same linkage rule curate_cohort.py/validate_cohort.py apply everywhere
else. A BioSample with zero or more-than-one complete-genome candidate is
never guessed at -- it is written to rejected.tsv with a specific reason for
manual review, exactly like every other curation step in this project.

This is intentionally generic, not specific to any one paper's ledger: any
BioSample-only candidate source needs the same resolution.

When no complete-genome assembly exists at all, this also checks for a
fallback: a deposited long-read (ONT/PacBio) run plus a paired Illumina run
on the same BioSample -- the raw material PlasBench needs to build its OWN
truth reference via hybrid assembly (see build_hybrid_truth.py), for cohort
sources that deposited reads but never formally submitted an assembly.
These candidates land in a third output file, self_build_candidates.tsv,
distinct from both resolved.tsv (an existing assembly was found) and
unresolved.tsv (neither an assembly nor a usable read pair exists).

Usage:
  resolve_ncbi_accessions.py --candidates cohorts/candidates/teixeira2025_pilot_candidates.tsv \\
      --out-dir results/teixeira2025_pilot_resolution
"""

import argparse
import csv
import os
import time
from pathlib import Path

from discover_ncbi_cohort import long_read_runs_for_biosample, runinfo_for_biosample
from validate_cohort import assembly_metadata, ncbi_json, request_interval

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(
            (line for line in handle if line.strip() and not line.lstrip().startswith("#")),
            delimiter="\t",
        ))


def write_rows(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        # lineterminator="\n": csv's excel dialect otherwise writes "\r\n"
        # regardless of file-open mode, corrupting the LAST column's value
        # for any awk-based exact-match lookup (scripts/lib.sh: sample_column()).
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def assembly_candidates_for_biosample(biosample, email, api_key):
    """Every assembly (any status) NCBI has deposited for one BioSample, as
    esummary records -- never just the first hit, so an ambiguous BioSample
    (more than one complete-genome candidate) can be flagged rather than
    silently resolved to whichever one esearch happened to return first."""
    ids = ncbi_json(ESEARCH, {"db": "assembly", "term": f"{biosample}[BioSample]", "retmax": 10},
                    email, api_key)["esearchresult"].get("idlist", [])
    candidates = []
    for uid in ids:
        candidates.append(ncbi_json(ESUMMARY, {"db": "assembly", "id": uid}, email, api_key)["result"][uid])
        time.sleep(request_interval(api_key))
    return candidates


def resolve_one(candidate, email, api_key):
    """Return (resolved_fields, reason). resolved_fields is None when
    resolution failed; reason is always a human-readable string, populated
    on both success (what was found) and failure (why not)."""
    biosample = candidate.get("biosample", "")
    if not biosample:
        return None, "no biosample to resolve from"
    assemblies = assembly_candidates_for_biosample(biosample, email, api_key)
    complete = [a for a in assemblies if a.get("assemblystatus", "").lower() == "complete genome"]
    if not complete:
        return None, (f"no complete-genome assembly found for BioSample {biosample} "
                       f"({len(assemblies)} non-complete candidate(s) exist)" if assemblies
                       else f"no assembly deposited for BioSample {biosample}")
    if len(complete) > 1:
        accessions = ", ".join(sorted(a["assemblyaccession"] for a in complete))
        return None, f"ambiguous: {len(complete)} complete-genome assemblies for BioSample {biosample} ({accessions}); needs manual review"
    accession = complete[0]["assemblyaccession"]
    time.sleep(request_interval(api_key))
    assembly = assembly_metadata(accession, email, api_key)
    time.sleep(request_interval(api_key))
    runs = runinfo_for_biosample(biosample, email, api_key)
    paired = [run for run in runs if run.get("Platform", "").upper() == "ILLUMINA"
              and run.get("LibraryLayout", "").upper() == "PAIRED"
              and run.get("BioSample") == biosample and run.get("BioProject") in assembly["bioprojects"]]
    if not paired:
        return None, f"assembly {accession} found, but no paired Illumina run matches its BioProject"
    paired.sort(key=lambda run: int(run.get("bases") or 0), reverse=True)
    selected, alternates = paired[0], ",".join(run["Run"] for run in paired[1:])
    return {
        "assembly_accession": accession, "sra_run": selected["Run"],
        "bioproject": selected["BioProject"], "alternate_paired_runs": alternates,
    }, f"resolved to {accession} / {selected['Run']}"


def resolve_self_build_fallback(candidate, email, api_key):
    """When resolve_one() finds no usable complete-genome assembly, check
    whether the raw material for PlasBench to build its OWN hybrid truth
    exists instead (see build_hybrid_truth.py): a long-read (ONT/PacBio) run
    AND a paired Illumina run deposited for this BioSample. Never a
    complete-genome substitute -- this only says the READS exist; whether
    they actually assemble into a trustworthy, fully circularized reference
    is decided later, when build_hybrid_truth.py actually tries.

    Returns (fields, reason), same shape as resolve_one(): fields is None
    when the fallback also fails, with its own specific reason.
    """
    biosample = candidate.get("biosample", "")
    if not biosample:
        return None, "no biosample to resolve from"
    long_runs = long_read_runs_for_biosample(biosample, email, api_key)
    if not long_runs:
        return None, f"no long-read (ONT/PacBio) run deposited for BioSample {biosample} either; cannot self-build truth"
    time.sleep(request_interval(api_key))
    runs = runinfo_for_biosample(biosample, email, api_key)
    paired = [run for run in runs if run.get("Platform", "").upper() == "ILLUMINA"
              and run.get("LibraryLayout", "").upper() == "PAIRED" and run.get("BioSample") == biosample]
    if not paired:
        return None, f"a long-read run exists for BioSample {biosample}, but no paired Illumina run to pair it with"
    # Prefer a short-read run sharing the SAME BioProject as a long-read run
    # (the linkage rule applied everywhere else in this project); fall back
    # to any paired Illumina run on the same BioSample if none share a
    # BioProject, since some submissions split reads across BioProjects.
    long_projects = {run["BioProject"] for run in long_runs}
    same_project = [run for run in paired if run["BioProject"] in long_projects]
    pool = same_project or paired
    pool.sort(key=lambda run: int(run.get("bases") or 0), reverse=True)
    long_runs_sorted = sorted(long_runs, key=lambda run: int(run.get("bases") or 0), reverse=True)
    selected_long, selected_short = long_runs_sorted[0], pool[0]
    return {
        "sra_run": selected_short["Run"], "long_read_sra_run": selected_long["Run"],
        "bioproject": selected_short["BioProject"],
        "alternate_long_read_runs": ",".join(run["Run"] for run in long_runs_sorted[1:]),
        "alternate_paired_runs": ",".join(run["Run"] for run in pool[1:]),
    }, f"self-build candidate: long read {selected_long['Run']} + short read {selected_short['Run']}"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidates", required=True, help="TSV with a biosample column (assembly_accession/sra_run may be empty).")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--email", default=os.environ.get("NCBI_EMAIL"))
    parser.add_argument("--api-key", default=os.environ.get("NCBI_API_KEY"))
    args = parser.parse_args()

    candidates = read_rows(args.candidates)
    if not candidates:
        raise SystemExit(f"ERROR: no rows found in {args.candidates}")
    if "biosample" not in candidates[0]:
        raise SystemExit("ERROR: candidates must contain a biosample column")

    resolved, self_build, unresolved = [], [], []
    for index, candidate in enumerate(candidates, 1):
        label = candidate.get("sample_id") or candidate.get("biosample") or f"row {index}"
        print(f"[resolve] {index}/{len(candidates)} {label} ...", flush=True)
        try:
            fields, reason = resolve_one(candidate, args.email, args.api_key)
        except Exception as exc:
            fields, reason = None, f"NCBI lookup failed: {exc}"
        if fields:
            resolved.append({**candidate, "resolution_reason": reason, **fields})
            time.sleep(request_interval(args.api_key))
            continue
        # No complete-genome assembly -- before giving up, check whether
        # PlasBench could build its own truth from this BioSample's deposited
        # reads instead (see build_hybrid_truth.py).
        try:
            sb_fields, sb_reason = resolve_self_build_fallback(candidate, args.email, args.api_key)
        except Exception as exc:
            sb_fields, sb_reason = None, f"self-build fallback lookup failed: {exc}"
        combined_reason = f"{reason}; {sb_reason}"
        if sb_fields:
            self_build.append({**candidate, "resolution_reason": combined_reason, **sb_fields})
        else:
            unresolved.append({**candidate, "resolution_reason": combined_reason})
        time.sleep(request_interval(args.api_key))

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    resolved_fields = tuple(dict.fromkeys((*candidates[0].keys(), "assembly_accession", "sra_run",
                                            "bioproject", "alternate_paired_runs", "resolution_reason")))
    self_build_fields = tuple(dict.fromkeys((*candidates[0].keys(), "sra_run", "long_read_sra_run",
                                              "bioproject", "alternate_long_read_runs",
                                              "alternate_paired_runs", "resolution_reason")))
    unresolved_fields = tuple(dict.fromkeys((*candidates[0].keys(), "resolution_reason")))
    write_rows(out / "resolved.tsv", resolved, resolved_fields)
    write_rows(out / "self_build_candidates.tsv", self_build, self_build_fields)
    write_rows(out / "unresolved.tsv", unresolved, unresolved_fields)
    print(f"Resolution complete: resolved={len(resolved)} self_build_candidates={len(self_build)} unresolved={len(unresolved)}")
    print(f"{out / 'resolved.tsv'} is curate-cohort-ready.")
    print(f"{out / 'self_build_candidates.tsv'} has raw long+short reads for build_hybrid_truth.py, but no pre-existing assembly -- review before use.")
    print(f"Review {out / 'unresolved.tsv'} for manual follow-up.")


if __name__ == "__main__":
    main()
