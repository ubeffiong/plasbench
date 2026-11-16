#!/usr/bin/env python3
"""Regression for the publication cohort candidate ledgers (plsMD 2026 filtered
and novel sets, MOB-suite benchmark): each TSV parses, has its required
columns, has unique non-blank isolate ids and source_publication, and its
isolate/plasmid counts equal the numbers recorded in
cohorts/candidates/PUBLICATION_COHORTS.md.
"""
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
CAND = os.path.join(ROOT, "cohorts", "candidates")

REQUIRED = ("sample_id", "assembly_accession", "sra_run", "organism", "biosample", "source_study",
            "source_doi", "source_table", "paper_identifier", "source_publication", "source_url",
            "candidate_status", "notes", "paper_plasmid_count", "truth_plasmid_accessions")
FILES = ("plsmd2026_filtered_candidates.tsv", "plsmd2026_novel_candidates.tsv", "mobsuite_benchmark_candidates.tsv")
STATUSES = {"accession_only", "needs_resolution"}

failures = []


def check(name, condition, detail=""):
    if condition:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name} {detail}")
        failures.append(name)


def read(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(
            (l for l in handle if l.strip() and not l.lstrip().startswith("#")), delimiter="\t"))


def documented_counts():
    counts = {}
    with open(os.path.join(CAND, "PUBLICATION_COHORTS.md"), encoding="utf-8") as handle:
        for line in handle:
            m = re.match(r"\|\s*(\S+_candidates\.tsv)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|", line)
            if m:
                counts[m.group(1)] = (int(m.group(2)), int(m.group(3)))
    return counts


def main():
    documented = documented_counts()
    for name in FILES:
        check(f"{name}: counts documented in PUBLICATION_COHORTS.md", name in documented)
        path = os.path.join(CAND, name)
        try:
            rows = read(path)
        except Exception as exc:  # noqa: BLE001
            check(f"{name}: parses", False, str(exc))
            continue
        check(f"{name}: parses and is non-empty", bool(rows))
        if not rows:
            continue
        missing = [c for c in REQUIRED if c not in rows[0]]
        check(f"{name}: required columns present", not missing, f"missing {missing}")
        ids = [r["sample_id"] for r in rows]
        check(f"{name}: no blank or duplicate sample_id", all(ids) and len(set(ids)) == len(ids))
        check(f"{name}: no duplicate sra_run", len({r["sra_run"] for r in rows}) == len(rows))
        check(f"{name}: no blank source_publication", all(r["source_publication"].strip() for r in rows))
        check(f"{name}: candidate_status valid", all(r["candidate_status"] in STATUSES for r in rows))
        check(f"{name}: assembly_accession never guessed (all blank)", all(not r["assembly_accession"] for r in rows))
        check(f"{name}: plasmid count column equals listed accessions",
              all(int(r["paper_plasmid_count"]) == len([a for a in r["truth_plasmid_accessions"].split(";") if a])
                  for r in rows))
        if name in documented:
            want_iso, want_pl = documented[name]
            check(f"{name}: isolate count {len(rows)} == documented {want_iso}", len(rows) == want_iso)
            got_pl = sum(int(r["paper_plasmid_count"]) for r in rows)
            check(f"{name}: plasmid count {got_pl} == documented {want_pl}", got_pl == want_pl)
    if failures:
        print(f"\n{len(failures)} FAILED: {failures}")
        sys.exit(1)
    print("\nALL PUBLICATION COHORT CANDIDATE TESTS PASSED")


if __name__ == "__main__":
    main()
