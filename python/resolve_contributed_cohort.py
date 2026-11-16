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
import csv
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_cohort as vc  # noqa: E402

UMBRELLA_BIOPROJECT = "PRJNA224116"
SHEET_EXTRA = ["selection_arm", "qc_precheck", "qc_precheck_notes", "est_depth_x", "est_read_pairs", "est_mean_read_length"]


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


def resolve(row, thresholds, api_key, email, pause):
    """(sheet_row or None, precheck_row)."""
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
    if not assembly["has_plasmid"]:
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
            results.append((0 if status == "pass" else 1, -(depth or 0), run_id, info, status, note, depth, pairs, length))
        else:
            notes.append(note)
    if not results:
        return reject("reject", "no usable run: " + " | ".join(notes))
    results.sort(key=lambda item: item[:3])
    _, _, best, info, status, note, depth, pairs, length = results[0]
    others = [item[2] for item in results[1:]]
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


def final_choice(sheet_rows, target, min_recent):
    """Per species: up to `target` rows, `min_recent` from the recent arm first, one per BioProject."""
    chosen, used_projects, report = [], set(), []
    by_species = {}
    for row in sheet_rows:
        by_species.setdefault(species_of(row["organism"]), []).append(row)
    for species in sorted(by_species):
        rows = by_species[species]
        recent = [r for r in rows if r.get("selection_arm") == "recent"]
        other = [r for r in rows if r.get("selection_arm") != "recent"]
        picked = []

        def take(pool, upto):
            for row in pool:
                if len(picked) >= upto:
                    return
                if row not in picked and row["bioproject"] not in used_projects:
                    picked.append(row)
                    used_projects.add(row["bioproject"])
        take(recent, min_recent)
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
    for index, row in enumerate(candidates, 1):
        key = row["assembly_accession"] + "|" + row.get("selection_arm", "")
        if key in cache:
            sheet, out = cache[key]["sheet"], cache[key]["precheck"]
        else:
            sheet, out = resolve(row, thresholds, args.api_key, args.email, pause)
            cache[key] = {"sheet": sheet, "precheck": out}
            if args.cache:
                with open(args.cache, "w", encoding="utf-8") as handle:
                    json.dump(cache, handle)
        precheck.append(out)
        if sheet:
            sheet_rows.append(sheet)
        sys.stderr.write(f"[resolve] {index}/{len(candidates)} {row['assembly_accession']} {out['status']}"
                         f"{': ' + out['reasons'] if out['reasons'] and out['status'] != 'pass' else ''}\n")

    chosen, report = final_choice(sheet_rows, args.target_per_species, args.min_recent)
    chosen_ids = {r["sample_id"] for r in chosen}
    os.makedirs(args.out_dir, exist_ok=True)
    fields = list(dict.fromkeys(list(candidates[0].keys()) + SHEET_EXTRA)) if candidates else SHEET_EXTRA
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
