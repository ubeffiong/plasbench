#!/usr/bin/env python3
"""Contributed-pool importer: selection rules, determinism, the umbrella-BioProject trap, leakage dates."""

import csv
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
from plasbench_common import leakage_release_date, parse_iso_date  # noqa: E402

SCRIPT = os.path.join(ROOT, "python", "import_contributed_cohort.py")
FIELDS = ["assembly_accession", "organism_name", "biosample", "bioproject", "seq_rel_date", "assembly_method",
          "assembly_sequencing_technology", "sra_runs", "sra_studies", "read_bioprojects", "first_matching_read_year",
          "reported_plasmid_count", "plasmid_accessions", "country", "region", "africa_subregion",
          "isolation_source_category", "host"]
HYBRID = ("Flye v. 2.9; Medaka", "Illumina NovaSeq; Oxford Nanopore MinION")
SHORT_FIRST = ("SPAdes v. 3.15", "Illumina HiSeq; Oxford Nanopore MinION")
failures = []


def check(label, condition, detail=""):
    print(f"  {'PASS' if condition else 'FAIL'}: {label}{'' if condition else ' -- ' + str(detail)}")
    if not condition:
        failures.append(label)


def row(acc, species, biosample, date, study, read_year, method=HYBRID, runs="SRR1;SRR2", country="Nigeria"):
    return dict(zip(FIELDS, [acc, species, biosample, "PRJNA224116", date, method[0], method[1], runs, "SRP" + study,
                             study, read_year, "2", "NZ_A.1;NZ_B.1", country, "Africa", "Western Africa", "Human clinical", "Homo sapiens"]))


POOL = [
    row("GCF_1.1", "Escherichia coli", "SAMN1", "2025-03-01", "PRJNA100", "2025"),
    row("GCF_2.1", "Escherichia coli", "SAMN2", "2025-04-01", "PRJNA100", "2025"),            # same cluster as #1
    row("GCF_3.1", "Escherichia coli", "SAMN3", "2025-05-01", "PRJNA101", "2025"),
    row("GCF_4.1", "Escherichia coli", "SAMN3", "2025-05-01", "PRJNA102", "2025"),            # duplicate BioSample
    row("GCF_5.1", "Escherichia coli", "SAMN5", "2025-06-01", "PRJNA103", "2025", method=SHORT_FIRST),
    row("GCF_6.1", "Escherichia coli", "SAMN6", "2025-06-01", "PRJNA104", "2019"),            # reads public in 2019
    row("GCF_7.1", "Klebsiella pneumoniae", "SAMN7", "2020-01-01", "PRJNA105", "2020"),
    row("GCF_8.1", "Klebsiella pneumoniae", "SAMN8", "2025-07-01", "PRJNA106", "2025", runs=""),
    row("GCF_9.1", "Klebsiella pneumoniae", "SAMN9", "2025-07-01", "PRJNA107", "2025", country="Kenya"),
]


def run(pool, *args):
    with tempfile.TemporaryDirectory() as tmp:
        pool_path = os.path.join(tmp, "pool.tsv")
        with open(pool_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(pool)
        ledger = os.path.join(tmp, "ledger.tsv")
        with open(ledger, "w", encoding="utf-8") as handle:
            handle.write("biosample\tsample_id\nSAMN9\told\n")
        out = os.path.join(tmp, "out")
        done = subprocess.run([sys.executable, SCRIPT, "--pool", pool_path, "--ledger", ledger, "--out-dir", out, *args],
                              capture_output=True, text=True)
        if done.returncode:
            return None, None, done.stderr
        read = lambda name: list(csv.DictReader(open(os.path.join(out, name), encoding="utf-8"), delimiter="\t"))
        return read("candidates.tsv"), read("rejected.tsv"), done.stderr


print("leakage release date helper")
check("assembly basis uses the assembly date", leakage_release_date("2025-03-01", "2019", "assembly") == "2025-03-01")
check("read basis uses 1 January of the read year", leakage_release_date("2025-03-01", "2019", "read") == "2019-01-01")
check("earliest_public takes the earlier of the two", leakage_release_date("2025-03-01", "2019") == "2019-01-01")
check("earliest_public falls back to the one value present", leakage_release_date("2025-03-01", "") == "2025-03-01")
check("assembly basis does not silently use the read year", leakage_release_date("", "2019", "assembly") == "")
try:
    leakage_release_date("2025-03-01", "2019", "bogus")
    check("an unknown basis is rejected", False)
except ValueError:
    check("an unknown basis is rejected", True)
check("NCBI timestamps parse", parse_iso_date("2025-03-01T00:00:00Z").isoformat() == "2025-03-01")

print("selection rules")
selected, rejected, err = run(POOL, "--released-after", "2025-01-01", "--date-basis", "assembly")
reasons = {r["assembly_accession"]: r["reason"] for r in rejected}
ids = {r["assembly_accession"] for r in selected}
check("runs", selected is not None, err)
check("one isolate per read-BioProject cluster (the umbrella bioproject is never the key)",
      {"GCF_1.1", "GCF_2.1"} & ids != {"GCF_1.1", "GCF_2.1"} and len({r["cluster_key"] for r in selected}) == len(selected))
check("every selected row's cluster key is the read project", all(r["cluster_key"].startswith("PRJNA10") for r in selected))
check("the umbrella BioProject is left blank for online validation", all(r["bioproject"] == "" for r in selected))
check("duplicate BioSample rejected", "duplicate" in reasons.get("GCF_4.1", ""), reasons)
check("short-read-first truth rejected by default", "long-read-first" in reasons.get("GCF_5.1", ""), reasons)
check("no listed run rejected", "no paired SRA run" in reasons.get("GCF_8.1", ""), reasons)
check("a BioSample already in the ledger is rejected", "already released" in reasons.get("GCF_9.1", ""), reasons)
check("a pre-cutoff genome is rejected", "before 2025-01-01" in reasons.get("GCF_7.1", ""), reasons)
check("alternate runs are kept", all(r["alternate_paired_runs"] == "SRR2" and r["sra_run"] == "SRR1" for r in selected))
check("short-read-first is accepted with the flag",
      "GCF_5.1" in {r["assembly_accession"] for r in run(POOL, "--allow-short-read-first")[0]})

print("leakage basis changes the selection")
by_assembly = {r["assembly_accession"] for r in run(POOL, "--released-after", "2025-01-01", "--date-basis", "assembly")[0]}
by_earliest = {r["assembly_accession"] for r in run(POOL, "--released-after", "2025-01-01", "--date-basis", "earliest_public")[0]}
check("a genome with reads public in 2019 passes on the assembly basis", "GCF_6.1" in by_assembly)
check("and is excluded on the earliest_public basis", "GCF_6.1" not in by_earliest)
older = {r["assembly_accession"] for r in run(POOL, "--released-before", "2024-12-31", "--date-basis", "assembly")[0]}
check("--released-before builds the older comparison arm", older == {"GCF_7.1"}, older)

print("determinism and filters")
first = run(POOL, "--seed", "7")[0]
second = run(list(reversed(POOL)), "--seed", "7")[0]
check("same seed, shuffled input order: identical rows", first == second)
check("--country filters", run(POOL, "--country", "Kenya")[0] == [] and len(run(POOL, "--country", "Nigeria")[0]) > 0)
check("--max-clusters-per-species caps each species",
      sum(r["organism"] == "Escherichia coli" for r in run(POOL, "--max-clusters-per-species", "1")[0]) == 1)
check("a bad date is a usage error", run(POOL, "--released-after", "yesterday")[0] is None)

print("ALL CONTRIBUTED COHORT TESTS PASSED" if not failures else "CONTRIBUTED COHORT TESTS FAILED: " + "; ".join(failures))
sys.exit(1 if failures else 0)
