#!/usr/bin/env python3
"""
build_selection_report.py -- write cohorts/<name>.selection.json: how a cohort was selected.

The window's Cohorts page ("Selection report" pop-up) reads this file. It records, from the files the selection
actually produced (nothing is re-queried and nothing is estimated):

  source      the candidate pool files, their checksums and row counts, and where the pool came from
  criteria    every rule applied, with its parameters
  funnel      how many genomes were available, how many passed each stage, and how many were selected
  failures    why candidates were dropped: offline filters (importer) and the NCBI / read-QC check (resolver)
  species     per species: available in the pool, passed the offline filters, verified, selected, recent / older
  selected    the cohort itself: truth technology and strategy, reference sequencing and assembly methods, read depth,
              read pairs and read length from SRA run-info, QC pre-check grades, plasmids per genome, regions, years
  limits      what the selection does not establish

Inputs are the importer's output directory (rejected.tsv, selection_summary.tsv), the resolver's output directory
(precheck.tsv) and the final sheet. The commands that were run are recorded verbatim with --importer-command and
--resolver-command, and their flags are shown as the criteria.

Standard library only.
"""

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import json
import os
import re
import shlex
import statistics
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plasbench_common import parse_iso_date  # noqa: E402


def open_text(path):
    return gzip.open(path, "rt", encoding="utf-8", newline="") if str(path).endswith(".gz") else open(path, encoding="utf-8", newline="")


def read_tsv(path):
    if not path or not os.path.isfile(path):
        return []
    with open_text(path) as handle:
        return list(csv.DictReader((line for line in handle if line.strip() and not line.lstrip().startswith("#")), delimiter="\t"))


def species_of(organism):
    return " ".join((organism or "").split()[:2])


def number(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# ------------------------------------------------------------------------------------------------ reasons
IMPORTER_REASONS = [
    (r"^duplicate BioSample", "The BioSample appears more than once in the pool (kept once)"),
    (r"^BioSample already released", "The BioSample is already in an earlier cohort (public-v1 to v3)"),
    (r"no explicit long-read platform", "No long-read platform in the sequencing evidence (cannot serve as long-read truth)"),
    (r"^truth is not long-read-first", "Truth was built short-read-first (excluded unless short-read-first truths are allowed)"),
    (r"^no paired SRA run", "No SRA run is listed for the genome"),
    (r"^released .* before ", "Public before the release cutoff"),
    (r"^released .* after ", "Public after the release window"),
    (r"^no usable release date", "No usable release date"),
    (r"^species not requested", "Species not requested"),
    (r"^country not requested", "Country not requested"),
    (r"^region not requested", "Region not requested"),
    (r"^no read BioProject", "No read BioProject or SRA study to cluster on"),
    (r"^plasmids\.tsv ", "The plasmid table disagrees with the assembly's own plasmid list"),
    (r"^another isolate of the same cluster", "Another isolate of the same study was selected (one per cluster)"),
    (r"^species already has", "The species already reached its cluster cap"),
    (r"^no BioSample", "No BioSample recorded"),
]
NCBI_REASONS = [
    (r"is not one of the assembly's", "The SRA run's BioProject is not one of the assembly's BioProjects (not a verified pair)"),
    (r"is not the cohort row's", "The SRA run belongs to a different BioSample than the genome"),
    (r"is not ILLUMINA", "The SRA run is not Illumina"),
    (r"is not PAIRED", "The SRA run is not paired-end"),
    (r"estimated depth .* below the reject limit", "Estimated read depth under the reject limit (10x)"),
    (r"read pairs .* below the reject limit", "Too few read pairs (under the reject limit)"),
    (r"mean read length .* below the reject limit", "Reads too short (under the reject limit)"),
    (r"not a Complete Genome", "The assembly is not a Complete Genome at NCBI"),
    (r"does not declare plasmid replicons", "NCBI does not record plasmid replicons for the assembly"),
    (r"no explicit long-read platform", "NCBI's sequencing evidence has no explicit long-read platform"),
    (r"assembly BioSample .* differs", "The assembly's BioSample at NCBI differs from the pool's"),
    (r"lookup failed|NCBI request|not found uniquely|could not retrieve", "NCBI lookup failed (retry later)"),
]


def categorise(reason, rules, fallback="Other"):
    first = (reason or "").split(" | ")[0]
    first = re.sub(r"^no usable run: ", "", first)
    first = re.sub(r"^[A-Z]RR\d+: ", "", first)
    for pattern, label in rules:
        if re.search(pattern, first):
            return label
    return fallback


def tally(items):
    return [{"reason": k, "n": v} for k, v in Counter(items).most_common()]


# ------------------------------------------------------------------------------------------------ commands
def flags_of(command):
    """{flag: value or True} from a recorded command line (a repeated flag keeps every value as a list)."""
    out, parts = {}, shlex.split(command or "")
    i = 0
    while i < len(parts):
        part = parts[i]
        if part.startswith("--"):
            nxt = parts[i + 1] if i + 1 < len(parts) and not parts[i + 1].startswith("--") else None
            value = nxt if nxt is not None else True
            i += 2 if nxt is not None else 1
            if part in out:
                out[part] = (out[part] if isinstance(out[part], list) else [out[part]]) + [value]
            else:
                out[part] = value
        else:
            i += 1
    return out


def criteria(importer, resolver, thresholds):
    imp, res = flags_of(importer), flags_of(resolver)
    basis = imp.get("--date-basis", "earliest_public")
    rules = [
        {"id": "pool", "rule": "Start from every RefSeq Complete Genome in the contributed pool that has at least one linked SRA run.", "parameters": {}},
        {"id": "dedupe", "rule": "A BioSample is used once, and never if an earlier cohort (public-v1 to v3) already holds it (cohorts/accepted_accessions.tsv).", "parameters": {}},
        {"id": "long_read", "rule": "The sequencing evidence must name a long-read platform (the rule `validate-cohort --online` enforces), so the genome can serve as long-read truth.", "parameters": {}},
        {"id": "strategy", "rule": ("Long-read-first truths only." if "--allow-short-read-first" not in imp else
                                      "Short-read-first and unclassified truths are also accepted; each row carries truth_assembly_strategy, and the headline analysis uses long-read-first rows only."),
         "parameters": {"allow_short_read_first": "--allow-short-read-first" in imp}},
        {"id": "plasmids", "rule": "When plasmids.tsv is available, its plasmid rows must agree with the assembly's own plasmid list.", "parameters": {}},
        {"id": "dates", "rule": f"Release date for the leakage arms is the {'earlier of the assembly release and the first read run year (read as 1 January)' if basis == 'earliest_public' else basis}.",
         "parameters": {"date_basis": basis, "arm_cutoff": imp.get("--arm-cutoff", "2025-01-01"),
                        "released_after": imp.get("--released-after", ""), "released_before": imp.get("--released-before", "")}},
        {"id": "arms", "rule": f"Rows public on or after {imp.get('--arm-cutoff', '2025-01-01')} are labelled recent, earlier rows older (selection_arm), so recent and older genomes can be compared for database leakage.", "parameters": {}},
    ]
    if "--all-members" in imp:
        rules.append({"id": "members", "rule": "Every passing isolate is kept: no cap per species and no one-per-study rule. cluster_key and bioproject name the study, so the analysis resamples studies, not isolates.", "parameters": {"all_members": True}})
    else:
        rules.append({"id": "members", "rule": "One isolate per independent study (read BioProject), capped per species.", "parameters": {"max_clusters_per_species": imp.get("--max-clusters-per-species", "")}})
    rules += [
        {"id": "ncbi", "rule": "Each candidate is verified at NCBI: Complete Genome, plasmid replicons declared, long-read platform in the sequencing evidence, the genome's BioSample matches.", "parameters": {}},
        {"id": "run", "rule": "Each listed SRA run must be the same BioSample, ILLUMINA and PAIRED, and its BioProject must be one of the assembly's BioProjects (the pool's own bioproject column is the RefSeq umbrella). The row's BioProject is the run's.", "parameters": {}},
        {"id": "qc", "rule": "Pre-download read QC from SRA run-info: estimated depth, read pairs and mean read length are graded against config/short_read_qc_thresholds.tsv. Under reject = dropped; under warn = kept and flagged.",
         "parameters": {k: {"warn": v[1], "reject": v[2]} for k, v in thresholds.items() if k in ("estimated_depth_x", "read_pairs", "median_read_length")}},
        {"id": "run_choice", "rule": f"The best passing run is chosen (pass before warn; at or under {res.get('--preferred-max-depth', '300')}x deepest first, deeper runs only if nothing shallower passes); the others stay in alternate_paired_runs.",
         "parameters": {"preferred_max_depth": res.get("--preferred-max-depth", "300")}},
    ]
    if res.get("--existing-sheet"):
        rules.append({"id": "core", "rule": "The 98 isolates of the first, balanced public-v4 selection are kept as panel_subset=core; everything else verified is panel_subset=extended.", "parameters": {}})
    return rules


# ------------------------------------------------------------------------------------------------ distributions
def quantiles(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    pick = lambda q: values[min(len(values) - 1, int(q * (len(values) - 1) + 0.5))]
    return {"n": len(values), "min": values[0], "p25": pick(0.25), "median": statistics.median(values), "p75": pick(0.75), "max": values[-1]}


def bins(values, edges, labels):
    counts = [0] * len(labels)
    for v in values:
        if v is None:
            continue
        for i, edge in enumerate(edges):
            if v < edge:
                counts[i] += 1
                break
        else:
            counts[-1] += 1
    return [{"value": label, "n": n} for label, n in zip(labels, counts)]


def counts(rows, key, top=12, fn=None):
    c = Counter(((fn(r) if fn else r.get(key)) or "").strip() or "not recorded" for r in rows)
    out = [{"value": k, "n": v} for k, v in c.most_common(top)]
    if len(c) > top:
        out.append({"value": f"{len(c) - top} more", "n": sum(v for _, v in c.most_common()[top:])})
    return out


def method_family(text):
    first = re.split(r"[;,]", text or "")[0].strip()
    first = re.sub(r"\s*v?\.?\s*[\d.]+.*$", "", first).strip()
    return first or "not recorded"


def tech_family(text):
    t = text or ""
    parts = []
    if re.search(r"nanopore|minion|gridion|promethion|ONT", t, re.I):
        parts.append("Oxford Nanopore")
    if re.search(r"pacbio|sequel|RSII", t, re.I):
        parts.append("PacBio")
    if re.search(r"illumina|miseq|nextseq|hiseq|novaseq|miniseq", t, re.I):
        parts.append("Illumina")
    if re.search(r"dnbseq|mgi|bgi|ion torrent", t, re.I):
        parts.append("other short-read")
    return " + ".join(parts) or "not recorded"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True, help="cohort name, e.g. public-v4")
    ap.add_argument("--sheet", required=True, help="the final cohort TSV")
    ap.add_argument("--pool-dir", default="cohorts/candidates/contributed-refseq-sra")
    ap.add_argument("--importer-dir", required=True, help="the importer's output directory (rejected.tsv, candidates.tsv)")
    ap.add_argument("--resolver-dir", required=True, help="the resolver's output directory (precheck.tsv)")
    ap.add_argument("--importer-command", default="", help="the importer command line, recorded verbatim")
    ap.add_argument("--resolver-command", default="", help="the resolver command line, recorded verbatim")
    ap.add_argument("--thresholds", default="config/short_read_qc_thresholds.tsv")
    ap.add_argument("--validate-command", default="", help="the validate-cohort command line, recorded verbatim")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    sheet = read_tsv(args.sheet)
    pool_path = os.path.join(args.pool_dir, "assemblies.tsv.gz")
    pool = read_tsv(pool_path)
    rejected = read_tsv(os.path.join(args.importer_dir, "rejected.tsv"))
    candidates = read_tsv(os.path.join(args.importer_dir, "candidates.tsv"))
    precheck = read_tsv(os.path.join(args.resolver_dir, "precheck.tsv"))
    thresholds = {r["metric"]: (r["direction"], number(r.get("warn")), number(r.get("reject"))) for r in read_tsv(args.thresholds) if r.get("metric")}

    pool_by_species = Counter(species_of(r["organism_name"]) for r in pool)
    cand_by_species = Counter(species_of(r["organism"]) for r in candidates)
    ok_status = {"pass", "warn"}
    verified_by_species = Counter(species_of(r["organism"]) for r in precheck if r["status"] in ok_status)
    selected_by_species = Counter(species_of(r["organism"]) for r in sheet)
    per_species = []
    for species in sorted(set(pool_by_species), key=lambda s: (-selected_by_species.get(s, 0), -pool_by_species[s], s)):
        rows = [r for r in sheet if species_of(r["organism"]) == species]
        per_species.append({"species": species, "pool": pool_by_species[species], "passed_filters": cand_by_species.get(species, 0),
                            "verified": verified_by_species.get(species, 0), "selected": len(rows),
                            "recent": sum(1 for r in rows if r.get("selection_arm") == "recent"),
                            "older": sum(1 for r in rows if r.get("selection_arm") == "older"),
                            "long_read_first": sum(1 for r in rows if r.get("truth_assembly_strategy") in ("long_read_first_hybrid", "long_read_only"))})

    imp_reasons = tally(categorise(r.get("reason", ""), IMPORTER_REASONS) for r in rejected)
    ncbi_rows = [r for r in precheck if r["status"] in ("reject", "error")]
    ncbi_reasons = tally(categorise(r.get("reasons", ""), NCBI_REASONS) for r in ncbi_rows)
    status_counts = Counter(r["status"] for r in precheck)
    funnel = [
        {"stage": "In the contributed pool", "n": len(pool), "note": "RefSeq Complete Genomes with at least one linked SRA run"},
        {"stage": "Passed the offline filters", "n": len(candidates), "note": "BioSample new, long-read platform named, truth strategy allowed, plasmid table agrees"},
        {"stage": "Looked up at NCBI", "n": len(precheck), "note": "every candidate, assembly and SRA run-info"},
        {"stage": "Verified at NCBI", "n": status_counts.get("pass", 0) + status_counts.get("warn", 0),
         "note": f"{status_counts.get('pass', 0)} passed the read-QC pre-check, {status_counts.get('warn', 0)} flagged"},
        {"stage": f"Selected into {args.name}", "n": len(sheet), "note": "all verified rows, then re-checked in full by validate-cohort --online"},
    ]

    depth = [number(r.get("est_depth_x")) or number(r.get("read_depth_x")) for r in sheet]
    pairs = [number(r.get("est_read_pairs")) for r in sheet]
    lengths = [number(r.get("est_mean_read_length")) for r in sheet]
    plasmids = [int(v) for v in (number(r.get("assembly_plasmid_count")) for r in sheet) if v is not None]
    gsize = [number(r.get("genome_size")) for r in sheet]
    released = [parse_iso_date(r.get("truth_release_date")) for r in sheet]
    selected = {
        "n": len(sheet), "species": len({species_of(r["organism"]) for r in sheet}),
        "bioprojects": len({r.get("bioproject") for r in sheet if r.get("bioproject")}),
        "biosamples": len({r.get("biosample") for r in sheet}),
        "arms": counts(sheet, "selection_arm"), "subset": counts(sheet, "panel_subset"),
        "truth_assembly_strategy": counts(sheet, "truth_assembly_strategy"), "truth_technology": counts(sheet, "truth_technology"),
        "truth_polish_reads": counts(sheet, "truth_polish_reads"),
        "reference_sequencing": counts(sheet, "assembly_sequencing_technology", fn=lambda r: tech_family(r.get("assembly_sequencing_technology"))),
        "reference_assembler": counts(sheet, "assembly_method", fn=lambda r: method_family(r.get("assembly_method"))),
        "reads": {"platform": "Illumina, paired-end (verified at NCBI for every row)",
                  "depth_x": quantiles(depth), "depth_bins": bins(depth, (30, 60, 100, 200, 300), ["under 30x", "30-60x", "60-100x", "100-200x", "200-300x", "over 300x"]),
                  "read_pairs": quantiles(pairs), "mean_read_length": quantiles(lengths),
                  "qc_precheck": counts(sheet, "qc_precheck"), "alternate_runs": sum(1 for r in sheet if r.get("alternate_paired_runs"))},
        "plasmids_per_genome": counts([{"p": ("5 or more" if p >= 5 else str(p))} for p in plasmids], "p"),
        "plasmids_total": sum(plasmids), "genome_size_mb": quantiles([g / 1e6 if g else None for g in gsize]),
        "region": counts(sheet, "region"), "source_category": counts(sheet, "isolation_source_category"),
        "released_year": counts([{"y": str(d.year) if d else ""} for d in released], "y", top=16),
    }

    pool_files = []
    for name in ("assemblies.tsv.gz", "plasmids.tsv.gz"):
        path = os.path.join(args.pool_dir, name)
        if os.path.isfile(path):
            pool_files.append({"file": f"{args.pool_dir}/{name}".replace("\\", "/"), "sha256": sha256_file(path), "bytes": os.path.getsize(path)})
    source_md = os.path.join(args.pool_dir, "SOURCE.md")
    report = {
        "schema_version": 1, "cohort": args.name, "generated": dt.date.today().isoformat(),
        "source": {"origin": "RefSeq Complete Genomes paired to SRA short-read runs, contributed by a PlasBench collaborator and copied into the repository with their permission; every row verified again at NCBI by this selection.",
                   "pool_files": pool_files, "pool_rows": len(pool), "source_notes": os.path.relpath(source_md).replace("\\", "/") if os.path.isfile(source_md) else "",
                   "commands": {"importer": args.importer_command, "resolver": args.resolver_command, "validate": args.validate_command}},
        "criteria": criteria(args.importer_command, args.resolver_command, thresholds),
        "funnel": funnel, "failures": {"offline": imp_reasons, "ncbi": ncbi_reasons, "ncbi_status": dict(status_counts)},
        "species": per_species, "selected": selected,
        "limits": [
            "Verified at NCBI means the deposited metadata links the genome and the run; it does not prove the two come from one physical isolate beyond the BioSample.",
            "The pre-download QC reads SRA run-info only. Base quality, adapters and pair integrity are checked after download by stage 3 (short_read_qc.py) and can still exclude a sample.",
            "Truth strategy and polishing are derived from NCBI's assembly method and sequencing technology, not checked by a curator. Short-read-first and unclassified truths are tier 3: described, not used for the headline.",
            "Release dates are public dates, not proof that a tool's training data or database lacks the genome; the leakage screen (LEAKAGE_* settings) compares them with each tool's database date.",
            "Selecting every verified genome is not a designed sample: species and studies are unequal. Use cluster_key / bioproject to resample studies, and the species and panel_subset columns to choose a balanced subset.",
            "No tool has been run on this cohort.",
        ],
    }
    with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, indent=1)
        handle.write("\n")
    sys.stderr.write(f"[selection_report] {args.name}: pool {len(pool)} -> filters {len(candidates)} -> verified "
                     f"{funnel[3]['n']} -> selected {len(sheet)} -> {args.out}\n")


if __name__ == "__main__":
    main()
