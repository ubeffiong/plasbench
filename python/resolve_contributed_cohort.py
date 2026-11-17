#!/usr/bin/env python3
"""
resolve_contributed_cohort.py -- verify importer candidates against NCBI, run the
pre-download read-QC check, and pick the final cohort rows.

Input is the importer's candidates.tsv (one or more, e.g. a "recent" and an "older"
arm). For every candidate this script:
  1. fetches the assembly at NCBI (same call `validate-cohort --online` uses) and
     requires a Complete Genome with plasmid replicons, the row's BioSample, and a
     long-read platform in the sequencing evidence (truth_technology is then NCBI's
     derived value, never the importer's guess);
  2. finds the real BioProject. The pool's `bioproject` is the RefSeq umbrella
     PRJNA224116 on every row, so the row's BioProject is the SRA run's, and it must
     also be one of the assembly's BioProjects;
  3. checks every listed SRA run (SRA run-info, no download): same BioSample, platform
     ILLUMINA, layout PAIRED; estimates depth (bases / genome size), read pairs and
     mean read length, and grades them against config/short_read_qc_thresholds.tsv
     (the same provisional limits the post-download QC gate uses: below `reject` the
     run is dropped, below `warn` it is kept and flagged);
  4. keeps the best passing run (pass before warn, then deepest) as sra_run, the
     others as alternate_paired_runs.

This is the CHEAP check. It cannot see read quality, adapters or pair integrity;
stage 3's short_read_qc.py does that on the downloaded reads, and may still reject a
sample. Nothing here is a substitute for it.

Final choice: per species, up to --target-per-species rows, preferring
--min-recent rows from the "recent" arm and filling the rest from the other arm
(then topping up from "recent"), one row per BioProject, in the importer's seeded
order. A species that cannot reach the target is reported, never padded.

Outputs (in --out-dir): resolved.tsv (the cohort sheet to validate and lock),
precheck.tsv (every candidate, with status and reasons), rejected.tsv.

Standard library only; NCBI is called with NCBI_API_KEY / NCBI_EMAIL if set.
"""

import argparse
import concurrent.futures
import csv
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_cohort as vc  # noqa: E402
from plasbench_common import balanced_order  # noqa: E402

UMBRELLA_BIOPROJECT = "PRJNA224116"
SHEET_EXTRA = ["balance_rank", "panel_subset", "selection_arm", "qc_precheck", "qc_precheck_notes", "est_depth_x", "est_read_pairs", "est_mean_read_length"]


def read_tsv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        lines = (line for line in handle if line.strip() and not line.lstrip().startswith("#"))
        return list(csv.DictReader(lines, delimiter="\t"))


def read_thresholds(path):
    """metric -> (direction, warn, reject); blank limits are None."""
    def number(text):
        try:
            return float(text)
        except (TypeError, ValueError):
            return None
    return {row["metric"]: (row["direction"], number(row.get("warn")), number(row.get("reject")))
            for row in read_tsv(path) if row.get("metric")}


def grade(value, limits):
    """pass | warn | reject for one metric (min: must not fall below; max: must not rise above)."""
    direction, warn, reject = limits
    if value is None:
        return "unknown"
    below = direction == "min"
    if reject is not None and (value < reject if below else value > reject):
        return "reject"
    if warn is not None and (value < warn if below else value > warn):
        return "warn"
    return "pass"


def number(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def run_estimates(run, genome_size):
    bases, spots = number(run.get("bases")), number(run.get("spots"))
    depth = bases / genome_size if bases and genome_size else None
    # SRA spots are read pairs for a PAIRED library; bases / spots is the pair's total length.
    mean_len = bases / (2 * spots) if bases and spots else None
    return depth, spots, mean_len


VERY_DEEP_NOTE = "very deep ({:.0f}x): downloads and assemblies are slow, consider subsampling (depth ladder)"


def check_run(run_id, row, assembly, thresholds, genome_size, api_key, email):
    """(run_info or None, status, notes). status: pass | warn | reject | error."""
    try:
        info = vc.run_metadata(run_id, email, api_key)
    except Exception as exc:  # NCBI hiccup or an unknown run: this run cannot be used, others may be
        return None, "error", f"{run_id}: {exc}"
    notes = []
    if info["biosample"] != row["biosample"]:
        return info, "reject", f"{run_id}: run BioSample {info['biosample']} is not the cohort row's {row['biosample']}"
    if info["platform"].upper() != "ILLUMINA":
        return info, "reject", f"{run_id}: platform {info['platform']} is not ILLUMINA"
    if info["layout"].upper() != "PAIRED":
        return info, "reject", f"{run_id}: library layout {info['layout']} is not PAIRED"
    if info["bioproject"] not in assembly["bioprojects"]:
        return info, "reject", f"{run_id}: run BioProject {info['bioproject']} is not one of the assembly's {assembly['bioprojects']}"
    depth, pairs, length = run_estimates(info, genome_size)
    worst = "pass"
    for label, value, metric in (("estimated depth", depth, "estimated_depth_x"), ("read pairs", pairs, "read_pairs"),
                                 ("mean read length", length, "median_read_length")):
        status = grade(value, thresholds[metric]) if metric in thresholds else "unknown"
        shown = "unknown" if value is None else f"{value:.1f}"
        if status == "reject":
            return info, "reject", f"{run_id}: {label} {shown} is below the reject limit {thresholds[metric][2]:g}"
        if status == "warn":
            worst = "warn"
            notes.append(f"{label} {shown} is below the warn limit {thresholds[metric][1]:g}")
        elif status == "unknown":
            worst = "warn"
            notes.append(f"{label} could not be estimated")
    return info, worst, "; ".join(notes)


def single_replicon(accession, api_key=None):
    """(genome size in bases, number of sequences) of an assembly from the NCBI Datasets report; (None, None) when it cannot be read."""
    try:
        request = vc.Request("https://api.ncbi.nlm.nih.gov/datasets/v2/genome/accession/" + accession + "/dataset_report",
                             headers={"User-Agent": "PlasBench/0.4 cohort resolver", "Accept": "application/json"})
        reports = vc.fetch(request, 60, 4, "NCBI Datasets report request", parse=lambda payload: json.loads(payload.decode("utf-8", "replace"))).get("reports", [])
        stats = reports[0].get("assembly_stats", {})
        return int(stats.get("total_sequence_length") or 0) or None, int(stats.get("number_of_component_sequences") or 0) or None
    except Exception:
        return None, None


MIN_CHROMOSOME_BP = 1_500_000   # a single sequence shorter than this is not a bacterial chromosome (a plasmid recorded alone would be)


def resolve(row, thresholds, api_key, email, pause, max_depth=300.0, negative_controls=False):
    """(sheet_row or None, precheck_row). With negative_controls the assembly must be a plasmid-free, single-sequence chromosome instead of a plasmid-bearing one."""
    out = {"sample_id": row["sample_id"], "assembly_accession": row["assembly_accession"], "organism": row["organism"],
           "selection_arm": row.get("selection_arm", ""), "status": "", "reasons": "", "sra_run": "", "bioproject": "",
           "est_depth_x": "", "est_read_pairs": "", "est_mean_read_length": ""}

    def reject(status, reason):
        out["status"], out["reasons"] = status, reason
        return None, out
    try:
        assembly = vc.assembly_metadata(row["assembly_accession"], email, api_key)
    except Exception as exc:
        return reject("error", f"assembly lookup failed: {exc}")
    time.sleep(pause)
    problems = []
    if assembly["assembly_status"].lower() != "complete genome" or assembly["datasets_assembly_level"].lower() != "complete genome":
        problems.append("assembly is not a Complete Genome")
    if negative_controls:
        size, sequences = single_replicon(row["assembly_accession"], api_key)
        time.sleep(pause)
        if assembly["has_plasmid"]:
            problems.append("assembly declares plasmid replicons, so it is not a negative control")
        if sequences != 1:
            problems.append(f"assembly has {sequences if sequences else 'an unknown number of'} sequences, not exactly one chromosome")
        elif size is None or size < MIN_CHROMOSOME_BP:
            problems.append(f"its single sequence is {size} bases, too short to be a bacterial chromosome")
        if size and not row.get("genome_size"):
            row = dict(row, genome_size=str(size))
    elif not assembly["has_plasmid"]:
        problems.append("assembly does not declare plasmid replicons")
    if not assembly["derived_truth_technology"]:
        problems.append("sequencing evidence has no explicit long-read platform")
    if assembly["biosample"] != row["biosample"]:
        problems.append(f"assembly BioSample {assembly['biosample']} differs from the pool's {row['biosample']}")
    if problems:
        return reject("reject", "; ".join(problems))
    genome_size = number(row.get("genome_size"))
    runs = [row["sra_run"]] + [run for run in (row.get("alternate_paired_runs") or "").split(";") if run]
    results, notes = [], []
    for run_id in runs:
        info, status, note = check_run(run_id, row, assembly, thresholds, genome_size, api_key, email)
        time.sleep(pause)
        if status in ("pass", "warn"):
            depth, pairs, length = run_estimates(info, genome_size)
            # pass before warn; then a run at or under max_depth (deepest of those) before any deeper run (shallowest of those)
            too_deep = bool(depth and depth > max_depth)
            results.append((0 if status == "pass" else 1, 1 if too_deep else 0, (depth or 0) if too_deep else -(depth or 0),
                            run_id, info, status, note, depth, pairs, length))
        else:
            notes.append(note)
    if not results:
        return reject("reject", "no usable run: " + " | ".join(notes))
    results.sort(key=lambda item: item[:4])
    best, info, status, note, depth, pairs, length = results[0][3:]
    others = [item[3] for item in results[1:]]
    if depth and depth > max_depth:
        note = "; ".join(part for part in (note, VERY_DEEP_NOTE.format(depth)) if part)
    out.update(status=status, reasons=note, sra_run=best, bioproject=info["bioproject"],
               est_depth_x=f"{depth:.1f}" if depth else "", est_read_pairs=f"{pairs:.0f}" if pairs else "",
               est_mean_read_length=f"{length:.0f}" if length else "")
    sheet = dict(row, sra_run=best, bioproject=info["bioproject"], truth_technology=assembly["derived_truth_technology"],
                 alternate_paired_runs=";".join(others), read_depth_x=out["est_depth_x"],
                 qc_precheck=status, qc_precheck_notes=note, est_depth_x=out["est_depth_x"],
                 est_read_pairs=out["est_read_pairs"], est_mean_read_length=out["est_mean_read_length"])
    return sheet, out


def species_of(organism):
    return " ".join((organism or "").split()[:2])


def final_choice(sheet_rows, target, min_recent, existing=(), unique_projects=True):
    """Per species: up to `target` rows, `min_recent` from the recent arm first, one per BioProject.

    `existing` rows (an already verified and locked panel being extended) are kept first and count toward the target
    and the recent quota, and their BioProjects are not used again. target 0 keeps every verified row; unique_projects=False
    allows several isolates per BioProject (cluster_key still names the study for the analysis).
    """
    chosen, used_projects, report = [], set(), []
    kept = {}
    for row in existing:
        kept.setdefault(species_of(row["organism"]), []).append(row)
        used_projects.add(row["bioproject"])
    by_species = {}
    for row in sheet_rows:
        by_species.setdefault(species_of(row["organism"]), []).append(row)
    for species in sorted(set(by_species) | set(kept)):
        rows = by_species.get(species, [])
        recent = [r for r in rows if r.get("selection_arm") == "recent"]
        other = [r for r in rows if r.get("selection_arm") != "recent"]
        picked = list(kept.get(species, []))
        have_recent = sum(1 for r in picked if r.get("selection_arm") == "recent")

        def take(pool, upto):
            for row in pool:
                if upto and len(picked) >= upto:
                    return
                if row not in picked and (not unique_projects or row["bioproject"] not in used_projects):
                    picked.append(row)
                    used_projects.add(row["bioproject"])
        take(recent, (len(picked) + max(0, min_recent - have_recent)) if target else 0)
        take(other, target)
        take(recent, target)
        chosen.extend(picked)
        report.append((species, len(rows), len(picked), sum(1 for r in picked if r.get("selection_arm") == "recent")))
    return chosen, report


def write_tsv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidates", action="append", required=True, help="importer candidates.tsv; repeat for the recent and older arms")
    ap.add_argument("--thresholds", default="config/short_read_qc_thresholds.tsv")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--target-per-species", type=int, default=20)
    ap.add_argument("--min-recent", type=int, default=10, help="rows per species taken from the recent arm before filling from the other")
    ap.add_argument("--existing-sheet", help="an already verified and locked panel to extend: its rows are kept, count toward the targets, "
                    "and their BioProjects are not reused")
    ap.add_argument("--preferred-max-depth", type=float, default=300.0,
                    help="runs deeper than this are used only when no shallower run passes, and are noted (default 300)")
    ap.add_argument("--allow-shared-bioproject", action="store_true",
                    help="keep several isolates per BioProject (the analysis clusters on cluster_key / BioProject)")
    ap.add_argument("--negative-controls", action="store_true", help="the candidates are plasmid-free isolates (from discover-cohort --negative-controls): require a plasmid-free, single-sequence chromosome of bacterial size instead of plasmids")
    ap.add_argument("--workers", type=int, default=4, help="parallel NCBI lookups (default 4, about 8 requests/second with a key)")
    ap.add_argument("--cache", help="JSON file of earlier per-candidate results; resolved candidates are not re-queried")
    ap.add_argument("--api-key", default=os.environ.get("NCBI_API_KEY"))
    ap.add_argument("--email", default=os.environ.get("NCBI_EMAIL"))
    args = ap.parse_args()

    candidates = []
    for path in args.candidates:
        candidates.extend(read_tsv(path))
    thresholds = read_thresholds(args.thresholds)
    pause = vc.request_interval(args.api_key)
    cache = {}
    if args.cache and os.path.isfile(args.cache):
        with open(args.cache, encoding="utf-8") as handle:
            cache = json.load(handle)

    sheet_rows, precheck = [], []
    lock = threading.Lock()
    done_count = [0]

    def save_cache():
        if args.cache:
            with lock:
                tmp = args.cache + ".tmp"
                with open(tmp, "w", encoding="utf-8") as handle:
                    json.dump(cache, handle)
                os.replace(tmp, args.cache)

    def work(index, row):
        key = row["assembly_accession"] + "|" + row.get("selection_arm", "")
        if key in cache:
            return index, row, cache[key]["sheet"], cache[key]["precheck"], True
        sheet, out = resolve(row, thresholds, args.api_key, args.email, pause, args.preferred_max_depth, args.negative_controls)
        return index, row, sheet, out, False

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(work, index, row) for index, row in enumerate(candidates)]
        for future in concurrent.futures.as_completed(futures):
            index, row, sheet, out, cached = future.result()
            results[index] = (sheet, out)
            if not cached:
                with lock:
                    cache[row["assembly_accession"] + "|" + row.get("selection_arm", "")] = {"sheet": sheet, "precheck": out}
            done_count[0] += 1
            if done_count[0] % 25 == 0:
                save_cache()
            sys.stderr.write(f"[resolve] {done_count[0]}/{len(candidates)} {row['assembly_accession']} {out['status']}"
                             f"{': ' + out['reasons'] if out['reasons'] and out['status'] != 'pass' else ''}\n")
    save_cache()
    for index in range(len(candidates)):          # candidate order, whatever order the lookups finished in
        sheet, out = results[index]
        precheck.append(out)
        if sheet:
            sheet_rows.append(sheet)

    existing = read_tsv(args.existing_sheet) if args.existing_sheet else []
    chosen, report = final_choice(sheet_rows, args.target_per_species, args.min_recent, existing,
                                  unique_projects=not args.allow_shared_bioproject)
    existing_ids = {r["sample_id"] for r in existing}
    for row in chosen:
        row["panel_subset"] = "core" if row["sample_id"] in existing_ids else "extended"
    # The sheet is written in balanced order (species rotate, recent and older alternate, one isolate per study before
    # a second), so any first N rows, and `plasbench run --max-isolates N`, is a fair miniature of the whole cohort.
    chosen = [chosen[i] for i in balanced_order(chosen)]
    for rank, row in enumerate(chosen, 1):
        row["balance_rank"] = rank
    chosen_ids = {r["sample_id"] for r in chosen}
    os.makedirs(args.out_dir, exist_ok=True)
    fields = list(dict.fromkeys((list(existing[0].keys()) if existing else []) + (list(candidates[0].keys()) if candidates else []) + SHEET_EXTRA))
    write_tsv(os.path.join(args.out_dir, "resolved.tsv"), chosen, fields)
    write_tsv(os.path.join(args.out_dir, "precheck.tsv"), precheck,
              ["sample_id", "assembly_accession", "organism", "selection_arm", "status", "reasons", "sra_run", "bioproject",
               "est_depth_x", "est_read_pairs", "est_mean_read_length"])
    write_tsv(os.path.join(args.out_dir, "rejected.tsv"),
              [dict(p, reasons=p["reasons"] or "not chosen: species already at its target or BioProject already used")
               for p in precheck if p["sample_id"] not in chosen_ids],
              ["sample_id", "assembly_accession", "organism", "selection_arm", "status", "reasons"])
    for species, available, picked, recent in report:
        short = f"  SHORT of {args.target_per_species}" if picked < args.target_per_species else ""
        sys.stderr.write(f"[resolve] {species}: {available} verified, {picked} chosen ({recent} recent){short}\n")
    sys.stderr.write(f"[resolve] {len(chosen)} rows -> {args.out_dir}/resolved.tsv; next: plasbench validate-cohort --online "
                     "--write-lock, then post-download QC (stage 3 short_read_qc.py) decides what runs.\n")


if __name__ == "__main__":
    main()
