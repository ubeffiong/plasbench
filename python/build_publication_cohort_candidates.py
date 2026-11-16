#!/usr/bin/env python3
"""Build CANDIDATE ledgers for three published plasmid-reconstruction cohorts.

Cohorts (see cohorts/candidates/PUBLICATION_COHORTS.md for provenance):
  plsmd2026_filtered   Lotfi et al. 2026 (doi 10.1186/s12859-026-06585-y), Dataset A
  plsmd2026_novel      Lotfi et al. 2026, Dataset B
  mobsuite_benchmark   Robertson and Nash 2018 (doi 10.1099/mgen.0.000206), Table S1

Inputs are small, version-controlled transcriptions of the publishers' own
supplementary tables (no sequence data is read or written):
  cohorts/candidates/plsmd2026_supplementary_table_1_raw.tsv
  cohorts/candidates/mobsuite2018_table_s1_raw.tsv
plus, optionally, an ENA run-metadata table fetched once with --fetch-ena
(metadata only) to fill BioSample/BioProject for runs that the paper lists by
run accession alone:
  cohorts/candidates/publication_cohorts_ena_run_metadata.tsv

Nothing is guessed: assembly_accession is always left empty (resolve it with
python/resolve_ncbi_accessions.py), and any field a source does not give is
left blank. These files are NOT valid input to `plasbench curate-cohort` until
resolved.

Usage:
  build_publication_cohort_candidates.py --fetch-ena      # network, small
  build_publication_cohort_candidates.py                  # offline build
"""

import argparse
import csv
import re
import time
import urllib.parse
import urllib.request
from collections import OrderedDict
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent / "cohorts" / "candidates"
PLSMD_RAW = DIR / "plsmd2026_supplementary_table_1_raw.tsv"
MOB_RAW = DIR / "mobsuite2018_table_s1_raw.tsv"
ENA_META = DIR / "publication_cohorts_ena_run_metadata.tsv"

ENA_FIELDS = ("run_accession", "sample_accession", "study_accession", "instrument_platform",
              "instrument_model", "library_layout", "scientific_name", "first_public")

OUT_COLUMNS = (
    "sample_id", "assembly_accession", "sra_run", "organism", "biosample", "bioproject",
    "source_study", "source_doi", "source_table", "paper_identifier",
    "paper_plasmid_count", "truth_chromosome_accession", "truth_plasmid_accessions",
    "ena_instrument_model", "ena_library_layout", "biosample_source",
    "source_publication", "source_url", "plsdb_novelty", "candidate_status", "notes",
)

PLSMD_URL = ("https://static-content.springer.com/esm/art%3A10.1186%2Fs12859-026-06585-y/"
             "MediaObjects/12859_2026_6585_MOESM2_ESM.xlsx")
MOB_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC6159552/supplementaryFiles"

COHORTS = {
    "plsmd2026_filtered": dict(
        out="plsmd2026_filtered_candidates.tsv", study="Lotfi_2026_plsMD_filtered",
        doi="10.1186/s12859-026-06585-y", table="Additional file 2, sheet Dataset A",
        pub="Lotfi et al. 2026, BMC Bioinformatics (plsMD), filtered benchmark derived from the MOB-suite benchmark",
        url=PLSMD_URL, novelty="not_applicable_derived_from_2018_mobsuite_benchmark",
        header="Lotfi et al. 2026 (plsMD) filtered benchmark, Dataset A: 80 isolates / 244 plasmids selected from the MOB-suite benchmark."),
    "plsmd2026_novel": dict(
        out="plsmd2026_novel_candidates.tsv", study="Lotfi_2026_plsMD_novel",
        doi="10.1186/s12859-026-06585-y", table="Additional file 2, sheet Dataset B",
        pub="Lotfi et al. 2026, BMC Bioinformatics (plsMD), novel dataset",
        url=PLSMD_URL, novelty="claimed_absent_from_PLSDB_2024_05_31_v2_by_paper_unverified_here",
        header="Lotfi et al. 2026 (plsMD) novel dataset, Dataset B: 68 isolates / 269 plasmids reported absent from PLSDB 2024_05_31_v2."),
    "mobsuite_benchmark": dict(
        out="mobsuite_benchmark_candidates.tsv", study="Robertson_Nash_2018_MOBsuite",
        doi="10.1099/mgen.0.000206", table="Supplementary Table 1",
        pub="Robertson and Nash 2018, Microbial Genomics (MOB-suite), benchmark of 133 closed genomes",
        url=MOB_URL, novelty="not_applicable_published_2018_closed_genomes_in_GenBank",
        header="Robertson and Nash 2018 (MOB-suite) benchmark: 133 closed genomes / 377 plasmids, PacBio plus Illumina."),
}


def safe_id(value, index):
    """Same shape as curate_cohort.py safe_id()."""
    value = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return (value or "candidate") + f"_{index:03d}"


def read_tsv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(
            (line for line in handle if line.strip() and not line.lstrip().startswith("#")),
            delimiter="\t"))


def fetch_ena(runs, out_path, batch=40):
    """Metadata-only ENA portal query (no read files)."""
    rows = []
    runs = sorted(set(runs))
    for start in range(0, len(runs), batch):
        chunk = runs[start:start + batch]
        query = " OR ".join(f"run_accession={r}" for r in chunk)
        data = urllib.parse.urlencode({"result": "read_run", "query": query,
                                       "fields": ",".join(ENA_FIELDS), "format": "tsv",
                                       "limit": "0"}).encode()
        req = urllib.request.Request("https://www.ebi.ac.uk/ena/portal/api/search", data=data)
        with urllib.request.urlopen(req, timeout=120) as resp:
            text = resp.read().decode("utf-8")
        rows.extend(csv.DictReader(text.splitlines(), delimiter="\t"))
        time.sleep(0.5)
    with open(out_path, "w", newline="", encoding="utf-8") as handle:
        handle.write("# ENA portal API read_run metadata (metadata only; no reads downloaded) for the run accessions\n"
                     "# listed by the three publication cohorts. Fetched by build_publication_cohort_candidates.py --fetch-ena.\n")
        writer = csv.DictWriter(handle, fieldnames=ENA_FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in sorted(rows, key=lambda r: r["run_accession"]):
            writer.writerow({k: row.get(k, "") for k in ENA_FIELDS})
    return len(rows)


def load_ena():
    if not ENA_META.exists():
        return {}
    return {r["run_accession"]: r for r in read_tsv(ENA_META)}


def group_plsmd(raw):
    groups = {"filtered": OrderedDict(), "novel": OrderedDict()}
    for r in raw:
        groups[r["dataset"]].setdefault(r["sample_run"], []).append(r)
    return groups


def build_plsmd(key, dataset, groups, ena):
    spec = COHORTS[key]
    rows = []
    for index, (run, plasmids) in enumerate(groups.items(), 1):
        organisms = sorted({p["organism"] for p in plasmids})
        organism = organisms[0]
        meta = ena.get(run)
        notes = ["assembly_accession blank: paper lists run + plasmid accessions only; chromosome record not listed"]
        if len(organisms) > 1:
            notes.append("paper lists several organism labels: " + "|".join(organisms))
        if meta and meta["scientific_name"] and meta["scientific_name"].split()[:2] != organism.split()[:2]:
            notes.append(f"ENA scientific_name differs: {meta['scientific_name']}")
        if meta and meta["library_layout"] != "PAIRED":
            notes.append(f"ENA library_layout {meta['library_layout']} (PlasBench needs paired-end Illumina)")
        rows.append({
            "sample_id": safe_id(f"{organism}_{run}", index),
            "assembly_accession": "", "sra_run": run, "organism": organism,
            "biosample": meta["sample_accession"] if meta else "",
            "bioproject": meta["study_accession"] if meta else "",
            "source_study": spec["study"], "source_doi": spec["doi"], "source_table": spec["table"],
            "paper_identifier": run, "paper_plasmid_count": str(len(plasmids)),
            "truth_chromosome_accession": "",
            "truth_plasmid_accessions": ";".join(p["truth_plasmid_accession"] for p in plasmids),
            "ena_instrument_model": meta["instrument_model"] if meta else "",
            "ena_library_layout": meta["library_layout"] if meta else "",
            "biosample_source": "ENA_portal_read_run" if meta else "",
            "source_publication": spec["pub"], "source_url": spec["url"],
            "plsdb_novelty": spec["novelty"],
            "candidate_status": "accession_only" if meta else "needs_resolution",
            "notes": "; ".join(notes),
        })
    return rows


def build_mob(raw):
    spec = COHORTS["mobsuite_benchmark"]
    by_biosample = OrderedDict()
    for r in raw:
        by_biosample.setdefault((r["biosample"], r["run_accession"]), []).append(r)
    rows = []
    for index, ((biosample, run), recs) in enumerate(by_biosample.items(), 1):
        chroms = [r for r in recs if r["compartment"] == "chromosome"]
        plasmids = [r for r in recs if r["compartment"] == "plasmid"]
        organism = recs[0]["species"]
        notes = ["assembly_accession blank: table lists nucleotide records, not the GenBank assembly"]
        if len(chroms) != 1:
            notes.append(f"{len(chroms)} chromosome records")
        if not plasmids:
            notes.append("no plasmid record")
        rows.append({
            "sample_id": safe_id(f"{organism}_{run}", index),
            "assembly_accession": "", "sra_run": run, "organism": organism,
            "biosample": biosample, "bioproject": "",
            "source_study": spec["study"], "source_doi": spec["doi"], "source_table": spec["table"],
            "paper_identifier": run, "paper_plasmid_count": str(len(plasmids)),
            "truth_chromosome_accession": ";".join(r["nucleotide_accession"] for r in chroms),
            "truth_plasmid_accessions": ";".join(r["nucleotide_accession"] for r in plasmids),
            "ena_instrument_model": "", "ena_library_layout": "",
            "biosample_source": "paper_table",
            "source_publication": spec["pub"], "source_url": spec["url"],
            "plsdb_novelty": spec["novelty"],
            "candidate_status": "accession_only",
            "notes": "; ".join(notes),
        })
    return rows


def write_cohort(key, rows, extraction_date):
    spec = COHORTS[key]
    path = DIR / spec["out"]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        handle.write(
            f"# CANDIDATE ledger, not a released benchmark. {spec['header']}\n"
            f"# Built on {extraction_date} by python/build_publication_cohort_candidates.py from small supplementary tables\n"
            "# (see cohorts/candidates/PUBLICATION_COHORTS.md). assembly_accession is intentionally empty pending NCBI\n"
            "# resolution (python/resolve_ncbi_accessions.py); NOT valid input to `plasbench curate-cohort` until resolved.\n"
            "# Never merge rows into a public-vN cohort without resolve -> curate-cohort -> validate-cohort --online.\n")
        writer = csv.DictWriter(handle, fieldnames=OUT_COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fetch-ena", action="store_true", help="fetch ENA run metadata (network) and exit")
    parser.add_argument("--extraction-date", default="2026-11-16")
    args = parser.parse_args()

    plsmd = group_plsmd(read_tsv(PLSMD_RAW))
    if args.fetch_ena:
        n = fetch_ena(list(plsmd["filtered"]) + list(plsmd["novel"]), ENA_META)
        print(f"Wrote {ENA_META}: {n} run record(s)")
        return
    ena = load_ena()
    outputs = {
        "plsmd2026_filtered": build_plsmd("plsmd2026_filtered", "filtered", plsmd["filtered"], ena),
        "plsmd2026_novel": build_plsmd("plsmd2026_novel", "novel", plsmd["novel"], ena),
        "mobsuite_benchmark": build_mob(read_tsv(MOB_RAW)),
    }
    for key, rows in outputs.items():
        print(f"Wrote {write_cohort(key, rows, args.extraction_date)}: {len(rows)} isolate(s)")


if __name__ == "__main__":
    main()
