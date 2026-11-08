#!/usr/bin/env python3
"""Tag each isolate with a benchmark scenario and report tool performance per scenario.

A tool should not look better because it met easier isolates. This script classifies every
isolate from facts already on disk, then summarises each tool within each scenario so a
reader can see where a tool is strong or weak instead of one pooled mean.

Scenarios (one primary label per isolate, first match wins):
  plasmid_free  no truth plasmid
  challenging   read depth below --low-depth (default 30x) when the sample sheet states it
  complex       --complex-plasmids (default 3) or more plasmids, a plasmid of at least
                --large-bp (default 100,000 bp), or repeat-rich (insertion-sequence density
                at least --is-per-10kb, default 1 per 10 kb of plasmid sequence, when IS
                features were annotated)
  annotated     replicon, mobility or AMR features are annotated on the truth plasmids
  simple        none of the above

Tags (all that apply, so the primary label never hides a property): multi_plasmid, large_plasmid,
cryptic_small (a plasmid under --small-bp, default 5,000), repeat_rich, low_depth, annotated.
`repeat_rich` and `annotated` are only claimed when the annotation exists; without it they are
absent, and `is_density` is blank (not evaluated), never zero. `challenging` also needs the
read-depth column; a cohort without it has no challenging scenario here, which is stated in the
output rather than assumed.

Output 1 (--out): one row per isolate. Output 2 (--performance-out): per scenario and tool, the
number of isolates, mean F1, mean per-plasmid recall, and an `underpowered` flag below
--min-samples (default 3). Descriptive only; never changes a score or ranking.
Standard library only.
"""
import argparse
import csv
import os
import statistics
import sys
from collections import defaultdict
from plasbench_common import number  # noqa: E402

SAMPLE_FIELDS = ("sample", "scenario", "tags", "n_plasmids", "largest_plasmid_bp", "smallest_plasmid_bp",
                 "read_depth_x", "is_density_per_10kb", "annotated")
PERF_FIELDS = ("analysis_track", "scenario", "tool", "n_samples", "mean_f1", "mean_precision", "mean_recall",
               "mean_plasmid_recall", "underpowered")


def read_tsv(path, skip_comments=False):
    if not path or not os.path.isfile(path):
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        lines = (line for line in handle if line.strip() and not (skip_comments and line.lstrip().startswith("#")))
        return list(csv.DictReader(lines, delimiter="\t"))


def classify(sample, data_dir, depth, args):
    truth = read_tsv(os.path.join(data_dir, sample, "truth.tsv")) if data_dir else []
    plasmids = {r["sequence_id"]: int(r["length"]) for r in truth if r["molecule_type"].upper() == "PLASMID"}
    features = read_tsv(os.path.join(data_dir, sample, "truth_features.tsv")) if data_dir else []
    on_plasmid = [f for f in features if f.get("sequence_id") in plasmids]
    kinds = {(f.get("feature_type") or "").lower() for f in on_plasmid}
    annotated = bool(kinds & {"replicon", "mob", "amr"})
    is_density = None
    if features:                                    # annotation exists, so IS absence is meaningful
        total_bp = sum(plasmids.values())
        is_count = sum(1 for f in on_plasmid if (f.get("feature_type") or "").lower() in ("is", "isescan", "insertion_sequence"))
        is_density = is_count / (total_bp / 10_000) if total_bp else None
    tags = []
    if len(plasmids) >= args.complex_plasmids:
        tags.append("multi_plasmid")
    if plasmids and max(plasmids.values()) >= args.large_bp:
        tags.append("large_plasmid")
    if plasmids and min(plasmids.values()) < args.small_bp:
        tags.append("cryptic_small")
    if is_density is not None and is_density >= args.is_per_10kb:
        tags.append("repeat_rich")
    if depth is not None and depth < args.low_depth:
        tags.append("low_depth")
    if annotated:
        tags.append("annotated")
    if not plasmids:
        scenario = "plasmid_free"
    elif "low_depth" in tags:
        scenario = "challenging"
    elif {"multi_plasmid", "large_plasmid", "repeat_rich"} & set(tags):
        scenario = "complex"
    elif annotated:
        scenario = "annotated"
    else:
        scenario = "simple"
    return {"sample": sample, "scenario": scenario, "tags": ",".join(tags), "n_plasmids": len(plasmids),
            "largest_plasmid_bp": max(plasmids.values()) if plasmids else None,
            "smallest_plasmid_bp": min(plasmids.values()) if plasmids else None, "read_depth_x": depth,
            "is_density_per_10kb": is_density, "annotated": "true" if annotated else "false"}


def performance(scores, scenario_of, min_samples):
    groups = defaultdict(lambda: defaultdict(list))
    for row in scores:
        scenario = scenario_of.get(row["sample"])
        if not scenario:
            continue
        key = (row.get("analysis_track") or "short_read", scenario, row["tool"])
        for metric in ("f1", "precision", "recall", "plasmid_recall"):
            value = number(row.get(metric))
            if value is not None:
                groups[key][metric].append(value)
        groups[key]["_samples"].append(row["sample"])
    rows = []
    for (track, scenario, tool), data in sorted(groups.items()):
        mean = lambda m: statistics.mean(data[m]) if data[m] else None
        n = len(set(data["_samples"]))
        rows.append({"analysis_track": track, "scenario": scenario, "tool": tool, "n_samples": n,
                     "mean_f1": mean("f1"), "mean_precision": mean("precision"), "mean_recall": mean("recall"),
                     "mean_plasmid_recall": mean("plasmid_recall"),
                     "underpowered": "true" if n < min_samples else "false"})
    return rows


def fmt(value):
    return "" if value is None else (f"{value:.4f}" if isinstance(value, float) else str(value))


def write(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: fmt(row.get(k)) for k in fields})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scores", required=True)
    ap.add_argument("--data-dir", required=True, help="<sample>/truth.tsv and truth_features.tsv")
    ap.add_argument("--sample-sheet", help="for read_depth_x")
    ap.add_argument("--out", required=True)
    ap.add_argument("--performance-out", required=True)
    ap.add_argument("--low-depth", type=float, default=30.0)
    ap.add_argument("--complex-plasmids", type=int, default=3)
    ap.add_argument("--large-bp", type=int, default=100_000)
    ap.add_argument("--small-bp", type=int, default=5_000)
    ap.add_argument("--is-per-10kb", type=float, default=1.0)
    ap.add_argument("--min-samples", type=int, default=3)
    args = ap.parse_args()
    scores = read_tsv(args.scores)
    depth = {r.get("sample_id", "").strip(): number(r.get("read_depth_x"))
             for r in read_tsv(args.sample_sheet, skip_comments=True)}
    samples = sorted({r["sample"] for r in scores})
    classified = [classify(s, args.data_dir, depth.get(s), args) for s in samples]
    write(args.out, SAMPLE_FIELDS, classified)
    write(args.performance_out, PERF_FIELDS, performance(scores, {c["sample"]: c["scenario"] for c in classified},
                                                         args.min_samples))
    counts = defaultdict(int)
    for c in classified:
        counts[c["scenario"]] += 1
    sys.stderr.write("[scenario_tags] " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
