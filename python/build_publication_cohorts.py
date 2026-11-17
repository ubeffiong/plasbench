#!/usr/bin/env python3
"""Build the publication cohorts: the isolates a published benchmark used, as runnable PlasBench cohorts.

Inputs are the candidate ledgers (cohorts/candidates/*_candidates.tsv: the accessions each paper gives, no assembly), the
verified `public-v4` sheet, and optionally the output of resolve_ncbi_accessions.py for the isolates `public-v4` does not hold.
For every candidate the script finds a complete assembly and a paired Illumina run, then CHECKS that the assembly's plasmids are the
plasmids the paper used as truth (by accession, ignoring version and the RefSeq NZ_ prefix), so a published per-plasmid result can be
compared with PlasBench's. It writes

  cohorts/pub-mobsuite.tsv  pub-plsmd-filtered.tsv  pub-plsmd-novel.tsv  [pub-teixeira2025.tsv]   one cohort per study
  cohorts/publication-v1.tsv                                                                      the studies together, each isolate once
  cohorts/<name>.publication.json                                                                 how each cohort was built (shown in the window)
  --audit FILE                                                                                    every candidate and what happened to it

`truth_match` in a cohort row: inferred (Teixeira only: the paper lists no plasmid accessions; the assembly is the prior published hybrid), exact (the assembly's plasmids are the paper's), superset (the assembly has more), subset (it lacks some:
those plasmids are reported as published-only in the comparison, never as zero) . A candidate whose assembly shares NO plasmid with the paper's
truth is left out. A candidate with no assembly, no verified read pair, or no way to check its truth is left out and listed in the audit.

Studies stay separate: use the study cohorts to compare with one paper, and `publication-v1` to run everything once. Do not pool the
studies into one leaderboard (their truth methods and independence differ). Standard library; the online truth check uses NCBI E-utilities
and needs NCBI_EMAIL (and optionally NCBI_API_KEY) in the environment.
"""
import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, OrderedDict
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE)
from truth_provenance import classify_method  # noqa: E402
from validate_cohort import derive_truth_technology  # noqa: E402
TAB, NL = chr(9), chr(10)

STUDIES = OrderedDict([
    ("mobsuite", {"ledger": "mobsuite_benchmark_candidates.tsv", "cohort": "pub-mobsuite", "label": "Robertson and Nash 2018 (MOB-suite benchmark)",
                  "citation": "Robertson and Nash 2018, Microbial Genomics, doi 10.1099/mgen.0.000206", "published": "plsmd2026",
                  "note": "133 closed genomes. Their per-plasmid recall for MOB-suite is the one the plsMD paper reports for the 80 isolates it kept, so only those 80 have a published outcome table here."}),
    ("plsmd_filtered", {"ledger": "plsmd2026_filtered_candidates.tsv", "cohort": "pub-plsmd-filtered", "label": "Lotfi et al. 2026, plsMD filtered benchmark (Dataset A)",
                        "citation": "Lotfi et al. 2026, BMC Bioinformatics, doi 10.1186/s12859-026-06585-y", "published": "plsmd2026",
                        "note": "80 isolates, 244 plasmids; also in the MOB-suite benchmark. Not novel by design."}),
    ("plsmd_novel", {"ledger": "plsmd2026_novel_candidates.tsv", "cohort": "pub-plsmd-novel", "label": "Lotfi et al. 2026, plsMD novel set (Dataset B)",
                     "citation": "Lotfi et al. 2026, BMC Bioinformatics, doi 10.1186/s12859-026-06585-y", "published": "plsmd2026",
                     "note": "68 isolates, 269 plasmids the paper reports absent from PLSDB 2024_05_31_v2 (not verified here; 23 of the 68 runs were public before the stated sequencing date)."}),
    ("teixeira", {"ledger": "teixeira2025_candidates.tsv", "cohort": "pub-teixeira2025", "label": "Teixeira et al. 2025 (Circling in on plasmids)",
                  "citation": "Teixeira et al. 2025, Briefings in Bioinformatics, doi 10.1093/bib/bbaf589", "published": "teixeira2025",
                  "note": "250 isolates, 31 species. Most have no deposited complete assembly; only those that resolve to one are runnable without rebuilding the hybrid truth."}),
])
MIXED = "publication-v1"
EXTRA_COLUMNS = ["published_sample", "published_studies", "truth_match", "paper_run_used"]


def read_tsv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        lines = [l for l in handle if l.strip() and not l.startswith("#")]
    reader = csv.DictReader(lines, delimiter=TAB)
    return list(reader), list(reader.fieldnames or [])


def norm_accession(value):
    return re.sub(r"^(NZ_|NC_|AC_)", "", re.sub(r"\.\d+$", "", str(value).strip()))


def accession_set(text):
    return {norm_accession(x) for x in re.split(r"[;,\s|]+", text or "") if x}


def is_plasmid_record(record):
    """A plasmid record of an assembly: titled plasmid, or a short record that is not titled a chromosome or complete genome."""
    title = str(record.get("title", ""))
    if re.search(r"plasmid", title, re.I):
        return True
    return int(record.get("length") or 0) < 1_000_000 and not re.search(r"chromosome|complete genome|genome", title, re.I)


def match_kind(published, assembly):
    if not assembly:
        return "unchecked"
    if published == assembly:
        return "exact"
    if published and published < assembly:
        return "superset"
    if assembly and assembly < published:
        return "subset"
    return "overlap" if published & assembly else "none"


class Entrez:
    """Minimal E-utilities client with a cache file: an assembly's nucleotide accessions."""

    def __init__(self, cache_path, email, api_key):
        self.cache_path, self.email, self.key = cache_path, email, api_key
        self.cache = {}
        if cache_path and os.path.isfile(cache_path):
            with open(cache_path, encoding="utf-8") as handle:
                self.cache = json.load(handle)
        self.last = 0.0

    def _get(self, tool, **params):
        params.update({"retmode": "json", "tool": "plasbench", "email": self.email})
        endpoint = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/{tool}.fcgi"
        if self.key:   # the key goes in the POST body, never in the URL (proxy logs, tracebacks)
            params["api_key"] = self.key
            url = urllib.request.Request(endpoint, data=urllib.parse.urlencode(params).encode("ascii"))
        else:
            url = endpoint + "?" + urllib.parse.urlencode(params)
        for attempt in range(5):
            wait = (0.12 if self.key else 0.36) - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            try:
                with urllib.request.urlopen(url, timeout=60) as response:
                    return json.loads(response.read().decode("utf-8"))
            except Exception:
                time.sleep(2 + 3 * attempt)
        raise RuntimeError(f"NCBI request failed: {tool}")

    def assembly_info(self, assembly_accession):
        """Assembly method and sequencing technology from the NCBI Datasets report, cached under 'info:<accession>'."""
        key = "info:" + assembly_accession
        if key not in self.cache:
            url = f"https://api.ncbi.nlm.nih.gov/datasets/v2/genome/accession/{assembly_accession}/dataset_report"
            request = urllib.request.Request(url, headers={"api-key": self.key} if self.key else {})
            info = {}
            for attempt in range(4):
                try:
                    with urllib.request.urlopen(request, timeout=60) as response:
                        reports = json.loads(response.read().decode("utf-8")).get("reports", [])
                    block = (reports[0].get("assembly_info") if reports else None) or {}
                    info = {"assembly_method": block.get("assembly_method", ""), "sequencing_tech": block.get("sequencing_tech", "")}
                    break
                except Exception:
                    time.sleep(2 + 3 * attempt)
            self.cache[key] = info
            if self.cache_path:
                with open(self.cache_path, "w", encoding="utf-8") as handle:
                    json.dump(self.cache, handle, indent=0)
        return self.cache[key]

    def assembly_records(self, assembly_accession):
        """The assembly's nucleotide records as {accession, title, length}, cached."""
        return self.assembly_accessions(assembly_accession)

    def assembly_accessions(self, assembly_accession):
        if assembly_accession in self.cache:
            return self.cache[assembly_accession]
        found = self._get("esearch", db="assembly", term=f"{assembly_accession}[Assembly Accession]")["esearchresult"].get("idlist", [])
        if not found:
            raise RuntimeError(f"assembly {assembly_accession} not found")
        links = self._get("elink", dbfrom="assembly", db="nuccore", id=found[0], linkname="assembly_nuccore_insdc")
        ids = []
        for linkset in links.get("linksets", []):
            for db in linkset.get("linksetdbs", []):
                ids += db.get("links", [])
        if not ids:
            links = self._get("elink", dbfrom="assembly", db="nuccore", id=found[0])
            for linkset in links.get("linksets", []):
                for db in linkset.get("linksetdbs", []):
                    ids += db.get("links", [])
        records = {}
        for start in range(0, len(ids), 200):
            summary = self._get("esummary", db="nuccore", id=",".join(ids[start:start + 200]))["result"]
            for uid in summary.get("uids", []):
                entry = summary[uid]
                records[entry["accessionversion"]] = {"accession": entry["accessionversion"], "title": entry.get("title", ""), "length": int(entry.get("slen") or 0)}
        self.cache[assembly_accession] = sorted(records.values(), key=lambda r: r["accession"])
        if self.cache_path:
            with open(self.cache_path, "w", encoding="utf-8") as handle:
                json.dump(self.cache, handle, indent=0)
        return self.cache[assembly_accession]


def build(args):
    ledger_dir = args.ledger_dir
    v4_rows, v4_header = read_tsv(os.path.join(args.cohorts_dir, "public-v4.tsv"))
    v4 = {r["biosample"]: r for r in v4_rows if r.get("biosample")}
    resolved = {}
    outcomes_dir = {}
    for item in args.resolved:
        study, _, path = item.partition("=")
        if study not in STUDIES or not os.path.isfile(path):
            sys.exit(f"ERROR: --resolved {item!r}: expected STUDY=resolved.tsv with STUDY in {', '.join(STUDIES)} and the file present")
        rows, _ = read_tsv(path)
        resolved[study] = {r.get("biosample"): r for r in rows}
        folder = os.path.dirname(path)
        outcomes_dir[study] = {}
        for name, label in (("unresolved.tsv", "no complete assembly and no usable read pair at NCBI"),
                            ("self_build_candidates.tsv", "no deposited complete assembly (long and short reads exist: the truth must be rebuilt, python/build_hybrid_truth.py)"),
                            ("rejected.tsv", "NCBI resolution rejected it")):
            fpath = os.path.join(folder, name)
            if os.path.isfile(fpath):
                extra, _ = read_tsv(fpath)
                for r in extra:
                    reason = r.get("reason") or r.get("rejection_reason") or label
                    outcomes_dir[study][r.get("biosample")] = f"{label}" if reason == label else f"{label}: {reason}"
    entrez = None
    if args.online:
        entrez = Entrez(args.truth_cache, os.environ.get("NCBI_EMAIL") or "plasbench@example.org", os.environ.get("NCBI_API_KEY"))
    header = list(v4_header) + [c for c in EXTRA_COLUMNS if c not in v4_header]
    audit, per_study = [], OrderedDict()
    for study, info in STUDIES.items():
        ledger_path = os.path.join(ledger_dir, info["ledger"])
        if not os.path.isfile(ledger_path):
            continue
        candidates, _ = read_tsv(ledger_path)
        rows, funnel = [], Counter()
        for cand in candidates:
            biosample, paper_id = cand.get("biosample", ""), cand.get("paper_identifier", "")
            published = accession_set(cand.get("truth_plasmid_accessions", ""))
            funnel["candidates"] += 1
            base = {"study": study, "paper_sample": paper_id, "biosample": biosample, "organism": cand.get("organism", "")}
            row, source, assembly = None, "", set()
            if biosample in v4:
                row, source = dict(v4[biosample]), "public-v4"
                assembly = accession_set(row.get("plasmid_accessions", ""))
            elif biosample in resolved.get(study, {}):
                res = resolved[study][biosample]
                row, source = {c: res.get(c, "") for c in header}, "resolved at NCBI"
                row["truth_quality_tier"] = row.get("truth_quality_tier") or "B"
                row["sample_id"] = row.get("sample_id") or cand.get("sample_id", "")
                if entrez is not None and row.get("assembly_accession"):
                    try:
                        records = entrez.assembly_records(row["assembly_accession"])
                        assembly = {norm_accession(r["accession"]) for r in records if is_plasmid_record(r)}
                        assembly -= accession_set(cand.get("truth_chromosome_accession", ""))
                        info = entrez.assembly_info(row["assembly_accession"])
                        row["assembly_method"] = row.get("assembly_method") or info.get("assembly_method", "")
                        row["assembly_sequencing_technology"] = row.get("assembly_sequencing_technology") or info.get("sequencing_tech", "")
                        row["truth_technology"] = derive_truth_technology(row["assembly_sequencing_technology"]) or ""
                        strategy, polish, _ = classify_method(row["assembly_method"], row["assembly_sequencing_technology"])
                        row["truth_assembly_strategy"], row["truth_polish_reads"] = strategy, polish
                    except Exception as exc:  # noqa: BLE001
                        base["error"] = str(exc)[:120]
            if row is None:
                funnel["no complete assembly or verified pair"] += 1
                audit.append(dict(base, outcome="left out", reason=outcomes_dir.get(study, {}).get(biosample, "not in public-v4 and not resolved (run the resolver, or the isolate has no complete assembly)")))
                continue
            funnel["found a complete assembly and a paired run"] += 1
            if source != "public-v4" and not row.get("truth_technology") and entrez is not None:
                funnel["no long-read platform recorded for the assembly"] += 1
                audit.append(dict(base, source=source, assembly_accession=row.get("assembly_accession", ""), outcome="left out",
                                  reason="NCBI records no long-read sequencing platform for the assembly, so it cannot serve as long-read truth"))
                continue
            if study == "teixeira" and not published:
                # Supplementary Table 1 gives no plasmid accessions. A row whose hybrid truth is a prior published, deposited assembly is
                # taken to match it ("inferred": from the ledger's prior_hybrid_assembly_source, not compared); a newly sequenced one is not.
                prior = (cand.get("prior_hybrid_assembly_source") or "").lower()
                kind = "inferred" if prior and "newly" not in prior and row.get("assembly_accession") else "unchecked"
            else:
                kind = match_kind(published, assembly)
            if kind in ("unchecked", "none"):
                funnel["truth could not be confirmed" if kind == "unchecked" else "assembly's plasmids differ from the paper's truth"] += 1
                audit.append(dict(base, source=source, assembly_accession=row.get("assembly_accession", ""), outcome="left out",
                                  reason="the assembly's plasmids could not be checked against the paper's truth (offline, or no accession list)" if kind == "unchecked"
                                  else "none of the assembly's plasmids is a plasmid the paper used as truth"))
                continue
            funnel[f"truth {kind}"] += 1
            # Use the paper's own run when it is one of the row's verified paired runs, so the reads are the ones the paper used.
            paper_run = cand.get("sra_run", "")
            alternates = [r for r in re.split(r"[;,\s]+", row.get("alternate_paired_runs", "") or "") if r]
            if paper_run and row.get("sra_run") != paper_run and paper_run in alternates:
                alternates = [row["sra_run"]] + [r for r in alternates if r != paper_run]
                row["sra_run"], row["alternate_paired_runs"] = paper_run, ",".join(alternates)
            row["paper_run_used"] = "yes" if paper_run and row.get("sra_run") == paper_run else "no"
            # source_study stays blank on purpose: validate-cohort grades a row tier A when a reviewed source study is named, and the
            # truth provenance of these papers has not been reviewed here (published_studies records the paper instead). Tier B.
            row.update({"published_sample": paper_id, "published_studies": study, "truth_match": kind, "source_study": ""})
            rows.append(row)
            audit.append(dict(base, source=source, assembly_accession=row.get("assembly_accession", ""), outcome="included", reason=f"truth {kind}"))
        per_study[study] = {"rows": rows, "funnel": funnel, "candidates": len(candidates)}
    return header, per_study, audit


def write_sheet(path, header, rows, comment_lines):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        for line in comment_lines:
            handle.write("# " + line + NL)
        writer = csv.DictWriter(handle, fieldnames=header, delimiter=TAB, lineterminator=NL, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cohorts-dir", default=os.path.join(ROOT, "cohorts"))
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "cohorts"))
    ap.add_argument("--ledger-dir", default=os.path.join(ROOT, "cohorts", "candidates"), help="folder holding the candidate ledgers")
    ap.add_argument("--resolved", action="append", default=[], metavar="STUDY=resolved.tsv")
    ap.add_argument("--online", action="store_true", help="check the truth of resolved assemblies at NCBI (needs NCBI_EMAIL)")
    ap.add_argument("--truth-cache", default="", help="JSON cache of assembly -> nucleotide accessions for --online")
    ap.add_argument("--audit", help="write the per-candidate outcome table here")
    args = ap.parse_args()
    header, per_study, audit = build(args)
    today = date.today().isoformat()
    os.makedirs(args.out_dir, exist_ok=True)
    mixed = OrderedDict()
    for study, result in per_study.items():
        info = STUDIES[study]
        rows = result["rows"]
        if not rows:
            print(f"{study}: no isolate could be built; no cohort written")
            continue
        for row in rows:
            key = row.get("biosample") or row["sample_id"]
            if key in mixed:
                mixed[key]["published_studies"] += ";" + study
            else:
                mixed[key] = dict(row)
        write_sheet(os.path.join(args.out_dir, info["cohort"] + ".tsv"), header, rows, [
            f"PlasBench publication cohort: {info['label']} ({info['citation']}).",
            f"Built {today} by python/build_publication_cohorts.py from the candidate ledger {info['ledger']}, public-v4 and NCBI resolution. {len(rows)} of {result['candidates']} published isolates.",
            "Every row is tier B (no source publication reviewed here). truth_match says whether the assembly's plasmids are exactly the plasmids the paper used as truth.",
            info["note"],
            f"Compare with the paper: plasbench compare-published --results-dir <results> --samples cohorts/{info['cohort']}.tsv"])
        counts = result["funnel"]
        meta = {"schema_version": 1, "cohort": info["cohort"], "generated": today, "study": study, "label": info["label"], "citation": info["citation"], "note": info["note"],
                "published_outcomes": info["published"], "isolates": len(rows), "candidates": result["candidates"],
                "funnel": [{"stage": "Isolates in the paper", "n": result["candidates"]},
                           {"stage": "Found a complete assembly and a paired Illumina run", "n": counts["found a complete assembly and a paired run"]},
                           {"stage": "Truth confirmed against the paper (exact, superset, subset) or inferred (Teixeira)", "n": len(rows)}],
                "truth_match": [{"value": k, "n": v} for k, v in Counter(r["truth_match"] for r in rows).most_common()],
                "left_out": [{"reason": k, "n": v} for k, v in Counter(a["reason"] for a in audit if a["study"] == study and a["outcome"] == "left out").most_common()],
                "compare_command": f"plasbench compare-published --results-dir <results> --samples cohorts/{info['cohort']}.tsv"}
        with open(os.path.join(args.out_dir, info["cohort"] + ".publication.json"), "w", encoding="utf-8", newline="") as handle:
            json.dump(meta, handle, indent=2, ensure_ascii=False)
            handle.write(NL)
        print(f"{info['cohort']}: {len(rows)} of {result['candidates']} isolates ({dict(Counter(r['truth_match'] for r in rows))})")
    if mixed:
        rows = list(mixed.values())
        counts_by_study = Counter(s for r in rows for s in r["published_studies"].split(";"))
        write_sheet(os.path.join(args.out_dir, MIXED + ".tsv"), header, rows, [
            "PlasBench mixed publication cohort: the isolates of several published benchmarks, each isolate once.",
            f"Built {today} by python/build_publication_cohorts.py. Studies: " + ", ".join(f"{STUDIES[s]['label']} ({n})" for s, n in counts_by_study.items()) + ".",
            "published_studies lists every study an isolate belongs to (the plsMD filtered set is also in the MOB-suite benchmark). Do not pool the studies into one leaderboard:",
            "their truth methods and independence differ. Compare with each paper separately: plasbench compare-published --results-dir <results> --samples cohorts/publication-v1.tsv",
            "which keeps the studies apart."])
        meta = {"schema_version": 1, "cohort": MIXED, "generated": today, "label": "Mixed publication cohort", "isolates": len(rows),
                "studies": [{"study": s, "label": STUDIES[s]["label"], "isolates": n} for s, n in counts_by_study.items()],
                "truth_match": [{"value": k, "n": v} for k, v in Counter(r["truth_match"] for r in rows).most_common()],
                "compare_command": f"plasbench compare-published --results-dir <results> --samples cohorts/{MIXED}.tsv"}
        with open(os.path.join(args.out_dir, MIXED + ".publication.json"), "w", encoding="utf-8", newline="") as handle:
            json.dump(meta, handle, indent=2, ensure_ascii=False)
            handle.write(NL)
        print(f"{MIXED}: {len(rows)} isolates ({dict(counts_by_study)} study memberships)")
    if args.audit:
        cols = ["study", "paper_sample", "biosample", "organism", "source", "assembly_accession", "outcome", "reason", "error"]
        with open(args.audit, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=cols, delimiter=TAB, lineterminator=NL, extrasaction="ignore", restval="")
            writer.writeheader()
            writer.writerows(audit)


if __name__ == "__main__":
    main()
