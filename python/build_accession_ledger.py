#!/usr/bin/env python3
"""Regenerate the cross-cohort accession ledger from every released lock file.

The ledger is *generated*, never hand-maintained: it can't drift from what
was actually locked/released, because it is nothing more than a flattened
read of cohorts/*.lock.json's own evidence. This is the identity record
curate_cohort.py/validate_cohort.py check new candidates against, so the
same physical isolate is never accepted into the cohort twice under two
different sample_id labels.

BioSample, not assembly accession, is the identity key: an assembly can be
resubmitted/superseded under a new accession while representing the same
physical isolate, so BioSample is the stable identity across re-releases.
A BioSample appearing in more than one lock file (e.g. a superset release
re-locking an earlier release's isolates) is not an error here -- only the
most recent lock file's record for that BioSample is kept, in filename sort
order, since a lexicographic sort of "public-vN" names is also chronological.

Usage:
  build_accession_ledger.py --cohorts-dir cohorts --out cohorts/accepted_accessions.tsv
"""

import argparse
import csv
import json
from pathlib import Path

COLUMNS = ("biosample", "sample_id", "assembly_accession", "sra_run", "source_cohort")


def read_lock(path):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"ERROR: cannot read lock file {path}: {exc}")
    return payload.get("evidence") or []


def build_ledger(cohorts_dir):
    """BioSample -> ledger row, flattened from every cohorts_dir/*.lock.json.

    Shared by this script's own CLI and prepare_contribution.py, which must
    regenerate the ledger after adding a contribution's evidence to a lock
    file -- reusing this avoids a second, drifting copy of the same
    later-release-wins merge rule.
    """
    cohorts_dir = Path(cohorts_dir)
    lock_files = sorted(cohorts_dir.glob("*.lock.json"))
    if not lock_files:
        raise SystemExit(f"ERROR: no *.lock.json files found under {cohorts_dir}")
    by_biosample = {}
    for lock_path in lock_files:
        cohort_name = lock_path.name.removesuffix(".lock.json")
        for record in read_lock(lock_path):
            assembly = record.get("assembly") or {}
            run = record.get("run") or {}
            biosample = assembly.get("biosample") or run.get("biosample")
            if not biosample:
                continue  # nothing to key on; skip rather than record a bogus entry
            by_biosample[biosample] = {
                "biosample": biosample,
                "sample_id": record.get("sample_id", ""),
                "assembly_accession": assembly.get("accession", ""),
                "sra_run": run.get("run", ""),
                "source_cohort": cohort_name,
            }
    return by_biosample, len(lock_files)


def write_ledger(by_biosample, out_path):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, delimiter="\t")
        writer.writeheader()
        for biosample in sorted(by_biosample):
            writer.writerow(by_biosample[biosample])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cohorts-dir", default="cohorts", help="Directory containing *.lock.json files (default: cohorts).")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    by_biosample, lock_file_count = build_ledger(args.cohorts_dir)
    out_path = Path(args.out)
    write_ledger(by_biosample, out_path)
    print(f"Wrote {out_path}: {len(by_biosample)} accepted isolate(s) across {lock_file_count} lock file(s)")


if __name__ == "__main__":
    main()
