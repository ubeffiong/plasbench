#!/usr/bin/env python3
"""Find plasmid-free negative controls: complete genomes with a single replicon, a long-read truth and a paired Illumina run.

Every genome of the contributed pool and of the published benchmarks carries at least one plasmid, so false-positive behaviour (a tool calling plasmid on
an isolate that has none; `zero_plasmid_specificity`, `isolate_specificity`) could not be measured on a real cohort. This builds one from NCBI:

  1. RefSeq Complete Genome assemblies of the chosen taxa (NCBI Datasets) whose assembly has exactly ONE component sequence and one chromosome,
     so the deposited assembly contains no plasmid.
  2. A recorded long-read sequencing platform (the same rule as `validate-cohort --online`), so the truth is long-read or hybrid.
  3. A paired Illumina run on the same BioSample whose BioProject belongs to the assembly's, at 30x to 400x estimated depth (closest to 100x wins).
  4. At most --per-species isolates per species and --per-bioproject per study, chosen deterministically (SHA-256 of the accession), so no species or study
     dominates.

It writes a cohort sheet (`--out`, valid input to `validate-cohort --online --write-lock`) with `assembly_plasmid_count` 0 and `control_type` plasmid_free,
and an audit of every candidate and why it was not taken (`--audit`).

The other route, `plasbench discover-cohort --negative-controls`, finds plasmid-free candidates for chosen organisms or places and leaves them for a curator to review;
this script builds the ready, verified cohort `negative-controls-v1`.

What this does NOT prove: a single-replicon complete assembly says the submitter deposited no plasmid, not that the strain has none (a plasmid can be lost
or never assembled, especially without long reads). Every row therefore carries `plasmid_free_evidence` stating exactly that, and the stage-2 depth and
truth checks can still flag a hidden replicon. Treat the controls as "no plasmid in the reference", and read a tool's false positives on them with that in mind.

  python python/discover_plasmid_free.py --out cohorts/negative-controls-v1.tsv --audit cohorts/candidates/negative_controls_audit.tsv   (needs NCBI_EMAIL; NCBI_API_KEY optional)
"""
import argparse
import csv
import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from validate_cohort import derive_truth_technology  # noqa: E402
from truth_provenance import classify_method  # noqa: E402

TAB, NL = chr(9), chr(10)
TAXA = [("Escherichia coli", 562), ("Klebsiella pneumoniae", 573), ("Salmonella enterica", 28901), ("Staphylococcus aureus", 1280),
        ("Acinetobacter baumannii", 470), ("Pseudomonas aeruginosa", 287), ("Enterococcus faecium", 1352), ("Enterococcus faecalis", 1351),
        ("Enterobacter hormaechei", 158836), ("Citrobacter freundii", 546), ("Klebsiella oxytoca", 571), ("Serratia marcescens", 615)]
COLUMNS = ["sample_id", "assembly_accession", "sra_run", "organism", "truth_technology", "truth_quality_tier", "biosample", "bioproject", "sample_origin",
           "read_depth_x", "assembly_plasmid_count", "source_study", "alternate_paired_runs", "truth_assembly_strategy", "truth_polish_reads",
           "assembly_method", "assembly_sequencing_technology", "genome_size", "truth_release_date", "control_type", "plasmid_free_evidence"]
EVIDENCE = ("single replicon in the deposited RefSeq complete assembly; absence of plasmids is the submitter's, not independently verified")
AUDIT_COLUMNS = ["organism", "accession", "biosample", "outcome", "reason"]


class Ncbi:
    def __init__(self, email, api_key, pause=None):
        self.email, self.key = email, api_key
        self.pause = pause if pause is not None else (0.11 if api_key else 0.35)
        self.last = 0.0

    def get(self, url, params=None, headers=None, as_json=True):
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        hdrs = {"User-Agent": "PlasBench negative-control discovery"}
        if self.key:
            hdrs["api-key"] = self.key
        hdrs.update(headers or {})
        for attempt in range(5):
            wait = self.pause - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=hdrs), timeout=60) as response:
                    payload = response.read().decode("utf-8")
                return json.loads(payload) if as_json else payload
            except Exception:
                time.sleep(2 + 3 * attempt)
        raise RuntimeError(f"NCBI request failed: {url[:120]}")

    def complete_genomes(self, taxon, max_pages):
        base = f"https://api.ncbi.nlm.nih.gov/datasets/v2/genome/taxon/{taxon}/dataset_report"
        token = None
        for _ in range(max_pages):
            params = {"filters.assembly_level": "complete_genome", "filters.assembly_source": "refseq", "filters.assembly_version": "current", "page_size": 1000}
            if token:
                params["page_token"] = token
            data = self.get(base, params)
            for report in data.get("reports", []):
                yield report
            token = data.get("next_page_token")
            if not token:
                break

    def runs_for_biosample(self, biosample):
        found = self.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                         {"db": "sra", "term": f"{biosample}[BioSample]", "retmax": 50, "retmode": "json", "email": self.email, "tool": "plasbench"})
        ids = found.get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        text = self.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
                        {"db": "sra", "id": ",".join(ids), "rettype": "runinfo", "retmode": "text", "email": self.email, "tool": "plasbench"}, as_json=False)
        return list(csv.DictReader(text.splitlines()))


def single_replicon(report):
    stats = report.get("assembly_stats", {})
    return stats.get("number_of_component_sequences") == 1 and stats.get("total_number_of_chromosomes") == 1


def screen(report):
    """(candidate dict, None) for a usable chromosome-only genome, else (None, reason)."""
    info = report.get("assembly_info", {})
    accession = report.get("accession", "")
    if info.get("assembly_level") != "Complete Genome":
        return None, "not a Complete Genome"
    if not single_replicon(report):
        return None, "has more than one replicon (a plasmid or extra sequence is deposited)"
    biosample = (info.get("biosample") or {}).get("accession", "")
    if not biosample:
        return None, "no BioSample"
    tech = info.get("sequencing_tech", "")
    technology = derive_truth_technology(tech)
    if not technology:
        return None, "no long-read sequencing platform recorded for the assembly"
    projects = {info.get("bioproject_accession", "")}
    for lineage in info.get("bioproject_lineage", []):
        for project in lineage.get("bioprojects", []):
            projects.add(project.get("accession", ""))
    projects.discard("")
    strategy, polish, _ = classify_method(info.get("assembly_method", ""), tech)
    organism = (report.get("organism") or {}).get("organism_name", "")
    return {"accession": accession, "biosample": biosample, "bioproject": info.get("bioproject_accession", ""), "projects": projects, "organism": organism,
            "length": int((report.get("assembly_stats") or {}).get("total_sequence_length") or 0), "technology": technology, "tech": tech,
            "method": info.get("assembly_method", ""), "strategy": strategy, "polish": polish, "release": info.get("release_date", "")}, None


def best_run(rows, projects, genome_length, lo=30.0, hi=400.0, target=100.0):
    """The paired Illumina run on one of the assembly's BioProjects whose depth is within [lo, hi]x and closest to target; plus the others."""
    usable = []
    for r in rows:
        if (r.get("Platform") or "").upper() != "ILLUMINA" or (r.get("LibraryLayout") or "").upper() != "PAIRED":
            continue
        if r.get("BioProject") not in projects:
            continue
        try:
            depth = float(r["bases"]) / genome_length
        except (KeyError, ValueError, ZeroDivisionError):
            continue
        if lo <= depth <= hi:
            usable.append((abs(depth - target), r["Run"], depth))
    usable.sort()
    return (usable[0][1], usable[0][2], [u[1] for u in usable[1:]]) if usable else (None, None, [])


def pick_order(accession):
    return hashlib.sha256(accession.encode()).hexdigest()


def discover(ncbi, taxa, per_species, per_bioproject, max_pages, audit):
    chosen = []
    for organism, taxon in taxa:
        candidates = []
        for report in ncbi.complete_genomes(taxon, max_pages):
            cand, reason = screen(report)
            if cand is None:
                audit.append({"organism": organism, "accession": report.get("accession", ""), "biosample": "", "outcome": "left out", "reason": reason})
            else:
                candidates.append(cand)
        candidates.sort(key=lambda c: pick_order(c["accession"]))
        taken, per_project = 0, Counter()
        for cand in candidates:
            if taken >= per_species:
                audit.append({"organism": organism, "accession": cand["accession"], "biosample": cand["biosample"], "outcome": "not needed", "reason": f"{per_species} controls already chosen for the species"})
                continue
            if per_project[cand["bioproject"]] >= per_bioproject:
                audit.append({"organism": organism, "accession": cand["accession"], "biosample": cand["biosample"], "outcome": "left out", "reason": f"{per_bioproject} controls already chosen from BioProject {cand['bioproject']}"})
                continue
            run, depth, alternates = best_run(ncbi.runs_for_biosample(cand["biosample"]), cand["projects"], cand["length"])
            if not run:
                audit.append({"organism": organism, "accession": cand["accession"], "biosample": cand["biosample"], "outcome": "left out",
                              "reason": "no paired Illumina run on the assembly's BioProject at 30x to 400x estimated depth"})
                continue
            cand.update(run=run, depth=depth, alternates=alternates, species=organism)
            chosen.append(cand)
            per_project[cand["bioproject"]] += 1
            taken += 1
            audit.append({"organism": organism, "accession": cand["accession"], "biosample": cand["biosample"], "outcome": "included", "reason": f"run {run}, {depth:.0f}x"})
    return chosen


def to_row(index, cand):
    return {"sample_id": f"negctl_{cand['species'].lower().replace(' ', '_')}_{cand['accession'].replace('.', '_').lower()}", "assembly_accession": cand["accession"], "sra_run": cand["run"],
            "organism": cand["species"], "truth_technology": cand["technology"], "truth_quality_tier": "B", "biosample": cand["biosample"], "bioproject": cand["bioproject"],
            "sample_origin": "", "read_depth_x": f"{cand['depth']:.1f}", "assembly_plasmid_count": "0", "source_study": "", "alternate_paired_runs": ",".join(cand["alternates"]),
            "truth_assembly_strategy": cand["strategy"], "truth_polish_reads": cand["polish"], "assembly_method": cand["method"], "assembly_sequencing_technology": cand["tech"],
            "genome_size": str(cand["length"]), "truth_release_date": cand["release"], "control_type": "plasmid_free", "plasmid_free_evidence": EVIDENCE}


def write_outputs(chosen, audit, out, audit_path, per_species, per_bioproject):
    rows = [to_row(i, c) for i, c in enumerate(sorted(chosen, key=lambda c: (c["species"], c["accession"])))]
    with open(out, "w", newline="", encoding="utf-8") as handle:
        handle.write("# PlasBench plasmid-free negative controls: RefSeq complete genomes with a single replicon, a long-read truth and a paired Illumina run.\n")
        handle.write(f"# Built by python/discover_plasmid_free.py (at most {per_species} per species and {per_bioproject} per BioProject, chosen by SHA-256 of the accession).\n")
        handle.write("# assembly_plasmid_count is 0 for every row. A single-replicon assembly shows the submitter deposited no plasmid, not that the strain has none:\n")
        handle.write("# plasmid_free_evidence says so on every row. Tier B (no source publication reviewed). Use to measure false-positive plasmid calling (zero_plasmid_specificity).\n")
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, delimiter=TAB, lineterminator=NL)
        writer.writeheader()
        writer.writerows(rows)
    if audit_path:
        with open(audit_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=AUDIT_COLUMNS, delimiter=TAB, lineterminator=NL, extrasaction="ignore", restval="")
            writer.writeheader()
            writer.writerows(audit)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--audit")
    ap.add_argument("--per-species", type=int, default=15)
    ap.add_argument("--per-bioproject", type=int, default=3)
    ap.add_argument("--max-pages", type=int, default=12, help="pages of 1000 assemblies per taxon")
    ap.add_argument("--taxon", action="append", metavar="NAME=TAXID", help="replace the default taxa (repeatable)")
    args = ap.parse_args()
    taxa = TAXA
    if args.taxon:
        taxa = []
        for item in args.taxon:
            name, _, tid = item.partition("=")
            taxa.append((name, int(tid)))
    ncbi = Ncbi(os.environ.get("NCBI_EMAIL") or "plasbench@example.org", os.environ.get("NCBI_API_KEY"))
    audit = []
    chosen = discover(ncbi, taxa, args.per_species, args.per_bioproject, args.max_pages, audit)
    rows = write_outputs(chosen, audit, args.out, args.audit, args.per_species, args.per_bioproject)
    print(f"{len(rows)} plasmid-free controls from {len({r['organism'] for r in rows})} species -> {args.out}")
    for organism, n in Counter(r["organism"] for r in rows).most_common():
        print(f"  {organism}: {n}")


if __name__ == "__main__":
    main()
