#!/usr/bin/env python3
"""
assembly_qc_gate.py -- flag assemblies that look mixed or contaminated before a
tool is ranked or recommended for them (panel edge case D13).

A tool recommendation assumes one bacterial isolate. Two cheap signals catch the
commonest violations without a database:

  assembly_size  total assembly length > --max-size-mb (8.5 Mb): larger than
                 almost any single bacterial genome plus plasmids.
  gc_spread      the GC content of long contigs (>= --min-contig-length, 10 kb)
                 spreads more than --max-gc-spread (0.12, as a fraction) between
                 the length-weighted 10th and 90th percentiles: two organisms.

status: pass | flagged (one or more reasons) | not_evaluable (no contig long
enough for the GC check; size is still checked). The gate is advisory: stage 8
warns and records it in the operational output, stage 6 writes it for every
cohort assembly (benchmark.assembly_qc.tsv) so evaluate_warnings.py can measure
how well it predicts failed recommendations. Plasmids have their own GC, so the
spread uses long contigs only; a large plasmid can still trip it, which is why it
never blocks a run.

Standard library only.
"""

import argparse
import csv
import gzip
import os
import sys

FIELDS = ["sample", "total_length", "n_contigs", "n_long_contigs", "gc_p10", "gc_p90", "gc_spread", "status",
          "reasons"]


def contigs(path):
    opener = gzip.open if path.endswith(".gz") else open
    name, gc, length = None, 0, 0
    with opener(path, "rt") as handle:
        for line in handle:
            line = line.strip()
            if line.startswith(">"):
                if name is not None:
                    yield name, length, gc
                name, gc, length = line[1:].split()[0], 0, 0
            elif line:
                upper = line.upper()
                gc += upper.count("G") + upper.count("C")
                length += len(line)
    if name is not None:
        yield name, length, gc


def weighted_percentile(pairs, q):
    """pairs: [(value, weight)]; length-weighted percentile."""
    pairs = sorted(pairs)
    total = sum(w for _, w in pairs)
    if not total:
        return None
    target, running = q * total, 0
    for value, weight in pairs:
        running += weight
        if running >= target:
            return value
    return pairs[-1][0]


def assess(sample, path, max_size_mb, max_gc_spread, min_contig_length):
    records = list(contigs(path))
    total = sum(length for _, length, _ in records)
    long = [(gc / length, length) for _, length, gc in records if length >= min_contig_length]
    reasons = []
    if total > max_size_mb * 1e6:
        reasons.append(f"assembly_size {total / 1e6:.2f} Mb > {max_size_mb} Mb")
    p10 = weighted_percentile(long, 0.10) if long else None
    p90 = weighted_percentile(long, 0.90) if long else None
    spread = (p90 - p10) if long else None
    if spread is not None and spread > max_gc_spread:
        reasons.append(f"gc_spread {spread:.3f} > {max_gc_spread}")
    status = "flagged" if reasons else ("not_evaluable" if not long else "pass")
    fmt = lambda v: "" if v is None else f"{v:.4f}"  # noqa: E731
    return {"sample": sample, "total_length": total, "n_contigs": len(records), "n_long_contigs": len(long),
            "gc_p10": fmt(p10), "gc_p90": fmt(p90), "gc_spread": fmt(spread), "status": status,
            "reasons": ";".join(reasons)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--contigs", help="one assembly FASTA (with --sample)")
    ap.add_argument("--sample")
    ap.add_argument("--data-dir", help="cohort mode: every <data-dir>/<sample>/contigs.fasta")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-size-mb", type=float, default=float(os.environ.get("ASSEMBLY_QC_MAX_SIZE_MB", 8.5)))
    ap.add_argument("--max-gc-spread", type=float, default=float(os.environ.get("ASSEMBLY_QC_MAX_GC_SPREAD", 0.12)))
    ap.add_argument("--min-contig-length", type=int, default=10000)
    args = ap.parse_args()
    jobs = []
    if args.contigs:
        jobs.append((args.sample or os.path.basename(os.path.dirname(os.path.abspath(args.contigs))), args.contigs))
    if args.data_dir and os.path.isdir(args.data_dir):
        for sample in sorted(os.listdir(args.data_dir)):
            path = os.path.join(args.data_dir, sample, "contigs.fasta")
            if os.path.isfile(path) and os.path.getsize(path):
                jobs.append((sample, path))
    if not jobs:
        raise SystemExit("ERROR: no assembly to check (give --contigs, or --data-dir with <sample>/contigs.fasta)")
    rows = [assess(s, p, args.max_size_mb, args.max_gc_spread, args.min_contig_length) for s, p in jobs]
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    flagged = [r for r in rows if r["status"] == "flagged"]
    for r in flagged:
        sys.stderr.write(f"[assembly_qc_gate] {r['sample']}: FLAGGED ({r['reasons']}); a tool recommendation "
                         "assumes one isolate -- check for contamination or a mixed culture\n")
    sys.stderr.write(f"[assembly_qc_gate] {len(rows)} assembly(ies), {len(flagged)} flagged -> {args.out}\n")


if __name__ == "__main__":
    main()
