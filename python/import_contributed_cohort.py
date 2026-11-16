#!/usr/bin/env python3
"""
import_contributed_cohort.py -- turn the contributed RefSeq/SRA candidate pool
(cohorts/candidates/contributed-refseq-sra/assemblies.tsv.gz) into a reviewable
PlasBench cohort, offline and deterministically.

This is a SELECTION step, not a verification step. Nothing here proves that an
assembly and a run belong together: `plasbench validate-cohort --online` does
that, and every row this writes is cohort tier B until it has passed.

Rules applied, in order (each rejected row records its reason in rejected.tsv):
  1. a BioSample appears once (13 duplicates in the pool);
  2. BioSamples already released by an earlier cohort (cohorts/accepted_accessions.tsv,
     --existing) are skipped;
  3. truth is long-read-first (truth_provenance.classify_method: long_read_only or
     long_read_first_hybrid) unless --allow-short-read-first;
  4. the release date, on the chosen --date-basis, is inside
     [--released-after, --released-before]  (the same dates and basis the leakage
     settings LEAKAGE_DATE_BASIS / LEAKAGE_CUTOFF_DATE use, see plasbench_common);
  5. optional --country / --region / --species filters;
  6. ONE isolate per independent cluster. The cluster key is `read_bioprojects`
     (the study that deposited the reads), NOT the `bioproject` column, which is
     the RefSeq umbrella PRJNA224116 on every row of the pool.

Selection among the survivors is a seeded hash order, so the same inputs and
--seed always give the same rows; --max-clusters-per-species caps each species.

Outputs (in --out-dir):
  candidates.tsv        cohort-schema rows (the public-v3 columns) plus
                        truth_release_date, first_read_year, cluster_key, region,
                        africa_subregion, isolation_source_category, assembly_method,
                        assembly_sequencing_technology, plasmid_accessions
  rejected.tsv          every pool row not selected, with the reason
  selection_summary.tsv per species: pool, passing, clusters available, selected, short of target

Standard library only.
"""

import argparse
import csv
import gzip
import hashlib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plasbench_common import (LEAKAGE_DATE_BASES, leakage_release_date, parse_iso_date)  # noqa: E402
from truth_provenance import classify_method  # noqa: E402

COLUMNS = ["sample_id", "assembly_accession", "sra_run", "organism", "truth_technology", "truth_quality_tier",
           "biosample", "bioproject", "sample_origin", "read_depth_x", "assembly_plasmid_count", "source_study",
           "truth_assembly_strategy", "truth_polish_reads", "alternate_paired_runs",
           "truth_release_date", "first_read_year", "cluster_key", "region", "africa_subregion",
           "isolation_source_category", "assembly_method", "assembly_sequencing_technology", "plasmid_accessions"]
LONG_READ_FIRST = ("long_read_only", "long_read_first_hybrid")
REQUIRED_POOL_COLUMNS = ("assembly_accession", "organism_name", "biosample", "seq_rel_date", "assembly_method",
                         "assembly_sequencing_technology", "sra_runs", "read_bioprojects", "first_matching_read_year")


def open_text(path):
    if str(path).endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return open(path, encoding="utf-8", newline="")


def read_tsv(path):
    if not path or not os.path.isfile(path):
        return []
    with open_text(path) as handle:
        lines = (line for line in handle if line.strip() and not line.lstrip().startswith("#"))
        return list(csv.DictReader(lines, delimiter="\t"))


def species_of(organism):
    return " ".join((organism or "").split()[:2])


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")


def order_key(seed, accession):
    """Deterministic pseudo-random order that does not depend on file order or Python's hash seed."""
    return hashlib.sha256(f"{seed}:{accession}".encode()).hexdigest()


def cluster_key(row):
    """The study that deposited the reads. `bioproject` is the RefSeq umbrella project on every pool row."""
    for field in ("read_bioprojects", "sra_studies"):
        first = (row.get(field) or "").split(";")[0].strip()
        if first:
            return first
    return ""


def origin_text(row):
    parts = [row.get("country") or "", row.get("isolation_source_category") or "", row.get("host") or ""]
    return "; ".join(part for part in parts if part and part not in ("Unclassified",))


def to_cohort_row(row, strategy, polish):
    species = species_of(row["organism_name"])
    runs = [run for run in (row.get("sra_runs") or "").split(";") if run]
    technology = "hybrid" if re.search(r"illumina|miseq|nextseq|hiseq|novaseq|dnbseq|bgi", row.get("assembly_sequencing_technology") or "", re.I) \
        and strategy != "long_read_only" else "long_read"
    return {
        "sample_id": f"{slug(species)}_{slug(row['biosample'])}",
        "assembly_accession": row["assembly_accession"],
        "sra_run": runs[0] if runs else "",
        "organism": row["organism_name"],
        "truth_technology": technology,
        "truth_quality_tier": "B",
        "biosample": row["biosample"],
        # The pool's `bioproject` is the RefSeq umbrella; the real assembly BioProject is re-derived by
        # `validate-cohort --online`. Left blank rather than recorded wrongly.
        "bioproject": "",
        "sample_origin": origin_text(row),
        "read_depth_x": "",
        "assembly_plasmid_count": row.get("reported_plasmid_count", ""),
        "source_study": "",
        "truth_assembly_strategy": strategy,
        "truth_polish_reads": polish,
        "alternate_paired_runs": ";".join(runs[1:]),
        "truth_release_date": row.get("seq_rel_date", ""),
        "first_read_year": row.get("first_matching_read_year", ""),
        "cluster_key": cluster_key(row),
        "region": row.get("region", ""),
        "africa_subregion": row.get("africa_subregion", ""),
        "isolation_source_category": row.get("isolation_source_category", ""),
        "assembly_method": row.get("assembly_method", ""),
        "assembly_sequencing_technology": row.get("assembly_sequencing_technology", ""),
        "plasmid_accessions": row.get("plasmid_accessions", ""),
    }


def screen(pool, args, taken_biosamples):
    """Yield (row, cohort_row_or_None, reason). Order of rejection reasons is the order of the rules above."""
    after = parse_iso_date(args.released_after)
    before = parse_iso_date(args.released_before)
    wanted_species = {species.lower() for species in args.species}
    seen = set()
    for row in sorted(pool, key=lambda r: r["assembly_accession"]):
        biosample = row.get("biosample", "")
        if not biosample:
            yield row, None, "no BioSample"
            continue
        if biosample in seen:
            yield row, None, "duplicate BioSample in the pool"
            continue
        seen.add(biosample)
        if biosample in taken_biosamples:
            yield row, None, "BioSample already released by an earlier cohort"
            continue
        strategy, polish, _reason = classify_method(row.get("assembly_method", ""), row.get("assembly_sequencing_technology", ""))
        if not args.allow_short_read_first and strategy not in LONG_READ_FIRST:
            yield row, None, f"truth is not long-read-first ({strategy})"
            continue
        if not (row.get("sra_runs") or "").strip():
            yield row, None, "no paired SRA run listed"
            continue
        released = parse_iso_date(leakage_release_date(row.get("seq_rel_date", ""), row.get("first_matching_read_year", ""), args.date_basis))
        if (after or before) and released is None:
            yield row, None, "no usable release date"
            continue
        if after and released < after:
            yield row, None, f"released {released} before {after} on basis {args.date_basis}"
            continue
        if before and released > before:
            yield row, None, f"released {released} after {before} on basis {args.date_basis}"
            continue
        if wanted_species and species_of(row["organism_name"]).lower() not in wanted_species:
            yield row, None, "species not requested"
            continue
        if args.country and (row.get("country") or "").lower() not in {c.lower() for c in args.country}:
            yield row, None, "country not requested"
            continue
        if args.region and (row.get("region") or "").lower() not in {r.lower() for r in args.region}:
            yield row, None, "region not requested"
            continue
        if not cluster_key(row):
            yield row, None, "no read BioProject or SRA study to cluster on"
            continue
        yield row, to_cohort_row(row, strategy, polish), ""


def select(passing, args):
    """One isolate per cluster, then at most --max-clusters-per-species clusters per species, seeded hash order."""
    by_species = {}
    for source, row in passing:
        by_species.setdefault(species_of(row["organism"]), {}).setdefault(row["cluster_key"], []).append((source, row))
    selected, rejected, summary = [], [], []
    for species in sorted(by_species):
        clusters = by_species[species]
        ranked = sorted(clusters, key=lambda key: order_key(args.seed, key))
        keep = ranked[:args.max_clusters_per_species] if args.max_clusters_per_species else ranked
        for key in ranked:
            members = sorted(clusters[key], key=lambda pair: order_key(args.seed, pair[1]["assembly_accession"]))
            if key in keep:
                selected.append(members[0][1])
                rest = members[1:]
                reason = "another isolate of the same cluster was selected"
            else:
                rest = members
                reason = f"species already has {args.max_clusters_per_species} clusters"
            rejected.extend((source, reason) for source, _row in rest)
        summary.append({"species": species, "passing_rows": sum(len(v) for v in clusters.values()),
                        "clusters_available": len(clusters), "clusters_selected": len(keep),
                        "short_of_target": max(0, args.min_clusters - len(keep)) if args.min_clusters else 0})
    return selected, rejected, summary


def write_tsv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pool", default="cohorts/candidates/contributed-refseq-sra/assemblies.tsv.gz")
    ap.add_argument("--ledger", default="cohorts/accepted_accessions.tsv", help="BioSamples already released")
    ap.add_argument("--existing", action="append", default=[], help="other cohort TSV(s) whose BioSamples to skip")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--date-basis", choices=LEAKAGE_DATE_BASES, default=os.environ.get("LEAKAGE_DATE_BASIS") or "earliest_public")
    ap.add_argument("--released-after", default="", help="YYYY-MM-DD; keep rows released on or after this date (on --date-basis)")
    ap.add_argument("--released-before", default="", help="YYYY-MM-DD; keep rows released on or before this date (an older comparison arm)")
    ap.add_argument("--species", action="append", default=[], help="repeat; default is every species in the pool")
    ap.add_argument("--country", action="append", default=[])
    ap.add_argument("--region", action="append", default=[])
    ap.add_argument("--allow-short-read-first", action="store_true",
                    help="also accept short-read-first hybrid truths (reference tier 3; default is long-read-first only)")
    ap.add_argument("--max-clusters-per-species", type=int, default=0, help="0 = no cap")
    ap.add_argument("--min-clusters", type=int, default=20, help="species below this are listed as short (headline MIN_SPECIES_CLUSTERS)")
    ap.add_argument("--seed", type=int, default=20260916)
    args = ap.parse_args()
    for flag, value in (("--released-after", args.released_after), ("--released-before", args.released_before)):
        if value and parse_iso_date(value) is None:
            ap.error(f"{flag} must be YYYY-MM-DD, got {value!r}")

    pool = read_tsv(args.pool)
    if not pool:
        ap.error(f"pool is empty or missing: {args.pool}")
    missing = [column for column in REQUIRED_POOL_COLUMNS if column not in pool[0]]
    if missing:
        ap.error("pool lacks required columns: " + ", ".join(missing))
    taken = {row.get("biosample", "") for row in read_tsv(args.ledger)}
    for path in args.existing:
        taken |= {row.get("biosample", "") for row in read_tsv(path)}
    taken.discard("")

    passing, rejected = [], []
    for source, cohort_row, reason in screen(pool, args, taken):
        if cohort_row is None:
            rejected.append((source, reason))
        else:
            passing.append((source, cohort_row))
    selected, cluster_rejected, summary = select(passing, args)
    rejected.extend(cluster_rejected)

    os.makedirs(args.out_dir, exist_ok=True)
    selected.sort(key=lambda row: (species_of(row["organism"]), row["cluster_key"]))
    write_tsv(os.path.join(args.out_dir, "candidates.tsv"), selected, COLUMNS)
    pool_fields = list(pool[0].keys()) + ["reason"]
    write_tsv(os.path.join(args.out_dir, "rejected.tsv"), [dict(source, reason=reason) for source, reason in rejected], pool_fields)
    write_tsv(os.path.join(args.out_dir, "selection_summary.tsv"), summary,
              ["species", "passing_rows", "clusters_available", "clusters_selected", "short_of_target"])
    sys.stderr.write(f"[import_contributed_cohort] pool {len(pool)}; selected {len(selected)} in {len(summary)} species; "
                     f"rejected {len(rejected)}; {sum(1 for s in summary if s['short_of_target'])} species short of "
                     f"{args.min_clusters} clusters -> {args.out_dir}\n"
                     "[import_contributed_cohort] these rows are UNVERIFIED: run `plasbench validate-cohort --online` before use.\n")


if __name__ == "__main__":
    main()
