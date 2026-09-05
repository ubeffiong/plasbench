#!/usr/bin/env python3
"""Advisory-only statistical outlier flagging over a cohort's assembly stats.

Standard library only. This complements validate_cohort.py's rule-based
checks (which catch specific, nameable data-integrity violations) with a
lightweight statistical layer for isolates that are technically valid by
every rule but numerically unusual relative to the rest of the accepted
cohort -- an assembly whose N50, contig count, GC%, or plasmid count is a
robust outlier.

This NEVER blocks or excludes a sample: it is purely advisory, routed to a
human curator, the same way discover_ncbi_cohort.py/curate_cohort.py route a
soft signal (candidate_extra_long_read_runs) to a separate column rather
than the hard accept/reject path. An outlier isolate might be the most
scientifically interesting one in the cohort; the point is triage, not
filtering. Exit code is always 0.

Robust z-score = the modified (Iglewicz-Hoaglin) z-score, 0.6745*(x-median)/MAD
-- median/MAD rather than mean/stdev, since small, skew-prone cohorts are
exactly where mean/stdev breaks down. The 0.6745 scaling is what makes a MAD
threshold comparable to a normal z-score threshold; without it, a plain
(x-median)/MAD is not on the same scale as the conventional |z|>3 cutoff.

Usage:
  flag_cohort_outliers.py --stats-dir DATA_DIR --samples SAMPLE_SHEET \
      --out benchmark.cohort_qc_flags.tsv [--min-cohort-size 8] [--zscore-threshold 3.5]
"""

import argparse
import csv
import statistics
from pathlib import Path

FIELDS = ("assembly_size_bp", "contig_count", "n50", "gc_percent", "plasmid_count")
COLUMNS = ("sample_id", "field", "value", "cohort_median", "cohort_mad", "modified_z_score", "flagged", "note")
MODIFIED_Z_SCALE = 0.6745


def read_samples(path):
    with open(path, newline="", encoding="utf-8") as handle:
        rows = csv.DictReader((line for line in handle if line.strip() and not line.lstrip().startswith("#")), delimiter="\t")
        return [row["sample_id"] for row in rows if row.get("sample_id")]


def read_stats(stats_dir, sample_id):
    path = Path(stats_dir) / sample_id / "assembly_stats.tsv"
    if not path.is_file():
        return None
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    return rows[0] if rows else None


def median_absolute_deviation(values, center):
    return statistics.median(abs(value - center) for value in values)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stats-dir", required=True, help="directory containing <sample_id>/assembly_stats.tsv")
    ap.add_argument("--samples", required=True, help="cohort sample sheet TSV")
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-cohort-size", type=int, default=8,
                    help="withhold outlier detection below this many samples with stats (default: 8)")
    ap.add_argument("--zscore-threshold", type=float, default=3.5,
                    help="modified z-score magnitude beyond which a value is flagged (default: 3.5)")
    args = ap.parse_args()

    sample_ids = read_samples(args.samples)
    stats_by_sample = {}
    for sample_id in sample_ids:
        stats = read_stats(args.stats_dir, sample_id)
        if stats:
            stats_by_sample[sample_id] = stats

    rows = []
    if len(stats_by_sample) < args.min_cohort_size:
        rows.append({
            "sample_id": "", "field": "", "value": "", "cohort_median": "", "cohort_mad": "",
            "modified_z_score": "", "flagged": "false",
            "note": f"cohort has {len(stats_by_sample)} sample(s) with assembly stats; "
                    f"at least {args.min_cohort_size} required for outlier detection",
        })
    else:
        for field in FIELDS:
            values_by_sample = {}
            for sample_id, stats in stats_by_sample.items():
                raw = stats.get(field)
                try:
                    values_by_sample[sample_id] = float(raw)
                except (TypeError, ValueError):
                    continue
            if len(values_by_sample) < args.min_cohort_size:
                continue
            values = list(values_by_sample.values())
            median = statistics.median(values)
            mad = median_absolute_deviation(values, median)
            if mad == 0:
                rows.append({
                    "sample_id": "", "field": field, "value": "", "cohort_median": f"{median:.4f}",
                    "cohort_mad": "0", "modified_z_score": "", "flagged": "false",
                    "note": "MAD is zero for this field in this cohort; z-score not meaningful",
                })
                continue
            for sample_id, value in sorted(values_by_sample.items()):
                z = MODIFIED_Z_SCALE * (value - median) / mad
                flagged = abs(z) > args.zscore_threshold
                rows.append({
                    "sample_id": sample_id, "field": field, "value": f"{value:.4f}",
                    "cohort_median": f"{median:.4f}", "cohort_mad": f"{mad:.4f}",
                    "modified_z_score": f"{z:.4f}", "flagged": "true" if flagged else "false",
                    "note": "robust outlier relative to the rest of the accepted cohort" if flagged else "",
                })

    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    n_flagged = sum(1 for row in rows if row["flagged"] == "true")
    print(f"Wrote cohort QC flags: {args.out} ({n_flagged} flagged value(s), advisory only)")


if __name__ == "__main__":
    main()
