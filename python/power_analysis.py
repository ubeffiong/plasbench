#!/usr/bin/env python3
"""How large a difference between two tools can this cohort actually detect?

A leaderboard says tool A scored 0.04 higher than tool B. Whether that is distinguishable
from noise depends on how many independent isolates there are and how much the paired
differences vary. This script answers the planning question directly, per pair of tools in
the same analysis track:

  minimum detectable difference (MDD)   the smallest true mean paired difference the cohort
                                        would detect with the chosen power and significance
  isolates needed for a target          how many independent clusters would be needed to
                                        detect --target-difference (default 0.05)

Method (normal approximation, paired): for each shared sample the paired difference
d = metric(A) - metric(B) is computed; samples from one cluster (shared BioProject or study)
are not independent, so differences are averaged within a cluster first and the cluster means
are the observations. With m clusters and standard deviation sd of those means,
    MDD = (z(1 - alpha/2) + z(power)) * sd / sqrt(m)
    m_needed = ((z(1 - alpha/2) + z(power)) * sd / target)^2
The normal approximation is optimistic for very small m, so a pair with fewer than
--min-clusters (default 5, the pipeline's own minimum for an interval) is reported with
`status = too_few_clusters` and no MDD. An observed difference smaller than the MDD is
`not_distinguishable` at this sample size, however different the means look.

Standard library only. Descriptive planning aid; never changes scores or rankings.
"""
import argparse
import csv
import math
import os
import statistics
import sys
from collections import defaultdict
from statistics import NormalDist

FIELDS = ("analysis_track", "metric", "tool_a", "tool_b", "paired_samples", "clusters", "mean_difference",
          "sd_cluster_differences", "alpha", "power", "min_detectable_difference", "target_difference",
          "clusters_needed_for_target", "observed_vs_mdd", "status")


def read_scores(path, metric):
    values = defaultdict(dict)             # (track, tool) -> sample -> value
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            try:
                value = float(row[metric])
            except (KeyError, ValueError, TypeError):
                continue
            values[(row.get("analysis_track") or "short_read", row["tool"])][row["sample"]] = value
    return values


def read_clusters(path):
    clusters = {}
    if not path or not os.path.isfile(path):
        return clusters
    with open(path, newline="", encoding="utf-8") as handle:
        lines = (line for line in handle if line.strip() and not line.lstrip().startswith("#"))
        for row in csv.DictReader(lines, delimiter="\t"):
            sample = (row.get("sample_id") or "").strip()
            for column in ("bioproject", "source_study"):
                if sample and (row.get(column) or "").strip():
                    clusters[sample] = f"{column}:{row[column].strip()}"
                    break
    return clusters


def analyse(values, clusters, alpha, power, target, min_clusters, metric):
    z = NormalDist().inv_cdf(1 - alpha / 2) + NormalDist().inv_cdf(power)
    by_track = defaultdict(list)
    for (track, tool) in values:
        by_track[track].append(tool)
    rows = []
    for track, tools in sorted(by_track.items()):
        for index, tool_a in enumerate(sorted(tools)):
            for tool_b in sorted(tools)[index + 1:]:
                a, b = values[(track, tool_a)], values[(track, tool_b)]
                shared = sorted(set(a) & set(b))
                groups = defaultdict(list)
                for sample in shared:
                    groups[clusters.get(sample, f"sample:{sample}")].append(a[sample] - b[sample])
                means = [statistics.mean(v) for v in groups.values()]
                row = {"analysis_track": track, "metric": metric, "tool_a": tool_a, "tool_b": tool_b,
                       "paired_samples": len(shared), "clusters": len(means), "alpha": alpha, "power": power,
                       "target_difference": target}
                if means:
                    row["mean_difference"] = statistics.mean(means)
                if len(means) < min_clusters:
                    row["status"] = "too_few_clusters"
                else:
                    sd = statistics.stdev(means)
                    row["sd_cluster_differences"] = sd
                    row["min_detectable_difference"] = z * sd / math.sqrt(len(means))
                    row["clusters_needed_for_target"] = math.ceil((z * sd / target) ** 2) if sd > 0 else len(means)
                    mdd = row["min_detectable_difference"]
                    if abs(row["mean_difference"]) >= mdd:
                        row["observed_vs_mdd"] = "at_or_above"
                        row["status"] = "distinguishable"
                    else:
                        row["observed_vs_mdd"] = "below"
                        row["status"] = "not_distinguishable"
                rows.append(row)
    return rows


def fmt(value):
    return "" if value is None else (f"{value:.6f}" if isinstance(value, float) else str(value))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scores", required=True)
    ap.add_argument("--sample-sheet", help="for the bioproject / source_study clusters")
    ap.add_argument("--metric", default="f1", help="scores.tsv column to compare (default f1)")
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--power", type=float, default=0.80)
    ap.add_argument("--target-difference", type=float, default=0.05)
    ap.add_argument("--min-clusters", type=int, default=5)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    if not (0 < args.alpha < 1 and 0.5 <= args.power < 1):
        raise SystemExit("ERROR: alpha must be in (0, 1) and power in [0.5, 1)")
    rows = analyse(read_scores(args.scores, args.metric), read_clusters(args.sample_sheet), args.alpha,
                   args.power, args.target_difference, args.min_clusters, args.metric)
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: fmt(row.get(k)) for k in FIELDS})
    sys.stderr.write(f"[power_analysis] {len(rows)} tool pair(s) -> {args.out}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
