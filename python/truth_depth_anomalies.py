#!/usr/bin/env python3
"""Advisory truth QC: coverage-anomaly regions from benchmark-read depth.

Idea (not code) from GAEMR's coverage-anomaly windows. python/measure_depth.py
only yields ONE genome-wide mean (reference_bp, read_bases, observed_depth_x),
so it cannot show where depth departs from the replicon norm. This script adds:

  windows  samtools-style `samtools depth -a` TSV (replicon, pos, depth; the
           pipeline would produce it by mapping the benchmark reads to
           reference.fna; this script does not call samtools) -> window table
           (replicon, start, end, mean_depth), 1-based inclusive coordinates.
  (default) --depth-table window table -> regions TSV + per-replicon summary.

Per replicon: robust centre = median of window means; robust spread =
1.4826*MAD (SD when MAD is 0). Windows beyond --z robust SDs above ('high')
or below ('low') are anomalous; same-direction anomalous windows separated by
less than --cluster-distance bp are merged into one region.

Interpretation (descriptive only; never edits truth): a high region in a
plasmid may be a collapsed repeat or an integrated element; a low region may
be a deletion or misjoin in the truth. A replicon is `flagged` when
anomalous_fraction >= --flag-fraction (0.02), `insufficient_windows` when it
has fewer than --min-windows windows.
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys

REGION_FIELDS = ("sample", "sequence_id", "molecule_type", "start", "end", "direction",
                 "mean_depth", "replicon_median_depth", "fold_change", "n_windows")
SUMMARY_FIELDS = ("sample", "sequence_id", "molecule_type", "n_windows", "n_high_regions",
                  "n_low_regions", "anomalous_bp", "anomalous_fraction", "median_depth",
                  "depth_ratio_to_chromosome", "status")
WINDOW_FIELDS = ("replicon", "start", "end", "mean_depth")


def windows_from_depth(path, window=1000):
    """Stream a `samtools depth -a` TSV into (replicon, start, end, mean) rows.

    Mean is over the positions actually present in each window (the last window
    of a replicon may be shorter than `window`).
    """
    out = []
    cur = None  # [replicon, index, sum, n, first_pos, last_pos]

    def flush():
        if cur and cur[3]:
            out.append((cur[0], cur[4], cur[5], cur[2] / cur[3]))

    with open(path, encoding="utf-8") as handle:
        for line in handle:
            parts = line.rstrip("\r\n").split("\t")
            if len(parts) < 3 or parts[0].startswith("#"):
                continue
            try:
                pos, depth = int(parts[1]), float(parts[2])
            except ValueError:
                continue
            idx = (pos - 1) // window
            if cur is None or cur[0] != parts[0] or cur[1] != idx:
                flush()
                cur = [parts[0], idx, 0.0, 0, pos, pos]
            cur[2] += depth
            cur[3] += 1
            cur[5] = pos
    flush()
    return out


def robust_spread(values):
    med = statistics.median(values)
    mad = statistics.median(abs(v - med) for v in values)
    spread = 1.4826 * mad
    if spread == 0 and len(values) > 1:
        spread = statistics.pstdev(values)
    return med, spread


def cluster(windows, direction, distance):
    """Merge same-direction windows (start, end, mean) with gap < distance."""
    regions = []
    for start, end, mean in sorted(windows):
        if regions and start - regions[-1]["end"] - 1 < distance:
            r = regions[-1]
            r["end"] = max(r["end"], end)
            r["parts"].append((end - start + 1, mean))
        else:
            regions.append({"start": start, "end": end, "parts": [(end - start + 1, mean)]})
    for r in regions:
        bp = sum(w for w, _ in r["parts"])
        r["mean"] = sum(w * m for w, m in r["parts"]) / bp
        r["bp"] = bp
        r["n"] = len(r["parts"])
        r["direction"] = direction
    return regions


def analyse_replicon(wins, z=3.0, distance=100):
    """wins: list of (start, end, mean). Returns (median, regions, anomalous_bp)."""
    means = [m for _, _, m in wins]
    med, spread = robust_spread(means)
    high, low = [], []
    for s, e, m in wins:
        if spread > 0 and m > med + z * spread:
            high.append((s, e, m))
        elif spread > 0 and m < med - z * spread:
            low.append((s, e, m))
    regions = cluster(high, "high", distance) + cluster(low, "low", distance)
    regions.sort(key=lambda r: r["start"])
    return med, regions, sum(r["bp"] for r in regions)


def plasmid_to_chromosome_depth_ratio(window_table, molecule_types):
    """Spec-style unverified-candidate ratio: plasmid median depth / chromosome median depth.

    window_table: iterable of (replicon, start, end, mean_depth); molecule_types:
    {replicon: 'PLASMID'|'CHROMOSOME'}. Returns {plasmid_id: ratio or None}; the
    chromosome median is pooled over all chromosome windows. None when there is
    no chromosome depth or it is zero.
    """
    per = {}
    for rep, _, _, mean in window_table:
        per.setdefault(rep, []).append(mean)
    chrom = [m for rep, v in per.items() if molecule_types.get(rep) == "CHROMOSOME" for m in v]
    chrom_med = statistics.median(chrom) if chrom else 0
    return {rep: (statistics.median(v) / chrom_med if chrom_med > 0 else None)
            for rep, v in per.items() if molecule_types.get(rep) == "PLASMID"}


def read_truth(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_window_table(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as handle:
        for r in csv.DictReader(handle, delimiter="\t"):
            rows.append((r["replicon"], int(r["start"]), int(r["end"]), float(r["mean_depth"])))
    return rows


def detect(window_table, truth_rows, sample, z=3.0, distance=100, min_windows=10, flag_fraction=0.02):
    """Returns (region_rows, summary_rows). window_table None => missing input."""
    types = {r["sequence_id"]: (r.get("molecule_type") or "") for r in truth_rows}
    lengths = {r["sequence_id"]: r.get("length", "") for r in truth_rows}
    by_rep = {}
    for rep, s, e, m in (window_table or []):
        by_rep.setdefault(rep, []).append((s, e, m))
    ratios = plasmid_to_chromosome_depth_ratio(window_table or [], types)
    ids = list(types) if types else list(by_rep)
    regions_out, summary = [], []
    for sid in ids:
        base = {"sample": sample, "sequence_id": sid, "molecule_type": types.get(sid, ""),
                "n_windows": 0, "n_high_regions": 0, "n_low_regions": 0, "anomalous_bp": "",
                "anomalous_fraction": "", "median_depth": "", "depth_ratio_to_chromosome": ""}
        wins = by_rep.get(sid)
        if window_table is None:
            summary.append({**base, "status": "missing_input"})
            continue
        if not wins:
            summary.append({**base, "status": "no_depth_windows"})
            continue
        base["n_windows"] = len(wins)
        if len(wins) < min_windows:
            base["median_depth"] = f"{statistics.median(m for _, _, m in wins):.4f}"
            summary.append({**base, "status": "insufficient_windows"})
            continue
        med, regions, bp = analyse_replicon(wins, z, distance)
        total_bp = sum(e - s + 1 for s, e, _ in wins)
        frac = bp / total_bp if total_bp else 0.0
        for r in regions:
            regions_out.append({
                "sample": sample, "sequence_id": sid, "molecule_type": types.get(sid, ""),
                "start": r["start"], "end": r["end"], "direction": r["direction"],
                "mean_depth": f"{r['mean']:.4f}", "replicon_median_depth": f"{med:.4f}",
                "fold_change": f"{r['mean'] / med:.4f}" if med > 0 else "NA",
                "n_windows": r["n"]})
        ratio = ratios.get(sid)
        summary.append({
            **base, "n_high_regions": sum(r["direction"] == "high" for r in regions),
            "n_low_regions": sum(r["direction"] == "low" for r in regions),
            "anomalous_bp": bp, "anomalous_fraction": f"{frac:.6f}",
            "median_depth": f"{med:.4f}",
            "depth_ratio_to_chromosome": "" if ratio is None else f"{ratio:.4f}",
            "status": "flagged" if frac >= flag_fraction else "ok"})
    return regions_out, summary


def write_tsv(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        w = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "windows":
        ap = argparse.ArgumentParser(prog="truth_depth_anomalies.py windows")
        ap.add_argument("--depth-tsv", required=True, help="samtools depth -a output")
        ap.add_argument("--out", required=True)
        ap.add_argument("--window", type=int, default=1000)
        a = ap.parse_args(argv[1:])
        try:
            wins = windows_from_depth(a.depth_tsv, a.window)
        except OSError as exc:
            print(f"WARNING: cannot read {a.depth_tsv}: {exc}", file=sys.stderr)
            write_tsv(a.out, WINDOW_FIELDS, [])
            return 0
        write_tsv(a.out, WINDOW_FIELDS, [dict(zip(WINDOW_FIELDS, (r, s, e, f"{m:.4f}")))
                                         for r, s, e, m in wins])
        return 0
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--depth-table", required=True, help="window table from the `windows` subcommand")
    ap.add_argument("--truth", help="truth.tsv (sequence_id, molecule_type, length)")
    ap.add_argument("--sample", required=True)
    ap.add_argument("--out", required=True, help="regions TSV")
    ap.add_argument("--summary-out", required=True, help="per-replicon summary TSV")
    ap.add_argument("--z", type=float, default=3.0)
    ap.add_argument("--cluster-distance", type=int, default=100)
    ap.add_argument("--min-windows", type=int, default=10)
    ap.add_argument("--flag-fraction", type=float, default=0.02)
    a = ap.parse_args(argv)
    truth = read_truth(a.truth) if a.truth else []
    try:
        table = read_window_table(a.depth_table)
    except (OSError, KeyError, ValueError) as exc:
        print(f"WARNING: depth table unusable ({exc}); writing status rows", file=sys.stderr)
        table = None
    regions, summary = detect(table, truth, a.sample, a.z, a.cluster_distance,
                              a.min_windows, a.flag_fraction)
    if table is None and not summary:
        summary = [{"sample": a.sample, "sequence_id": "", "molecule_type": "", "n_windows": 0,
                    "n_high_regions": 0, "n_low_regions": 0, "anomalous_bp": "",
                    "anomalous_fraction": "", "median_depth": "",
                    "depth_ratio_to_chromosome": "", "status": "missing_input"}]
    write_tsv(a.out, REGION_FIELDS, regions)
    write_tsv(a.summary_out, SUMMARY_FIELDS, summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
