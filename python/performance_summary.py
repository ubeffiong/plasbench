#!/usr/bin/env python3
"""Computational performance per tool: speed, memory, reliability, efficiency and scaling.

Everything here comes from what stage 4 already records (tool_status.tsv: runtime_seconds,
peak_rss_kb, status) plus the recovered-plasmid counts in scores.tsv, and optionally the
per-run CPU time that stage 4 now writes beside the memory figure. One row per tool:

  success_rate           completed / (completed + failed); a skipped run is not a failure
  resource_failures      failed runs whose exit code is a timeout or out-of-memory kill
                         (124/137), kept apart from tool failures
  median / p90 runtime   over completed runs, seconds
  median peak memory     GB
  thread_seconds_per_recovered_plasmid
                         sum(runtime x threads) / sum(truth plasmids recovered): the cost of
                         one recovered plasmid, so a fast tool that recovers nothing is not
                         called efficient
  cpu_utilisation        cpu seconds / (runtime x threads), only when CPU times were recorded
  runtime_scaling_exponent / memory_scaling_exponent
                         slope of log(runtime) or log(memory) on log(input size), input size
                         being the reference genome length; about 1 is linear, 2 quadratic.
                         Reported only with at least --min-scaling-points distinct samples
                         spanning at least a 1.5-fold range of input size, else blank.

Wall-clock numbers are only comparable when every tool ran on the same hardware with the same
thread count; the thread count used is a column so a reader can check. Blank means not
evaluated, never zero. Descriptive only. Standard library only.
"""
import argparse
import csv
import math
import os
import re
import statistics
import sys
from collections import defaultdict

EXIT_CODE = re.compile(r"exit_code=(\d+)")
RESOURCE_EXIT_CODES = {124, 137}
FIELDS = ("tool", "n_runs", "n_completed", "n_failed", "n_resource_failures", "n_skipped", "success_rate",
          "median_runtime_seconds", "p90_runtime_seconds", "median_peak_memory_gb", "threads",
          "recovered_plasmids", "thread_seconds_per_recovered_plasmid", "cpu_utilisation",
          "n_cpu_runs", "runtime_scaling_exponent", "memory_scaling_exponent", "n_scaling_points")


def read_tsv(path):
    if not path or not os.path.isfile(path):
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def percentile(values, fraction):
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def read_cpu(logs_dir, sample, tool):
    """CPU seconds (user + system) from the three-number .rss file, or None."""
    if not logs_dir:
        return None
    path = os.path.join(logs_dir, f"{sample}.{tool}.rss")
    try:
        lines = open(path, encoding="utf-8").read().strip().splitlines()
    except OSError:
        return None
    parts = lines[-1].split() if lines else []      # /usr/bin/time's own line is the last one
    if len(parts) >= 3:
        user, system = number(parts[1]), number(parts[2])
        if user is not None and system is not None:
            return user + system
    return None


def reference_length(data_dir, sample):
    if not data_dir:
        return None
    total = 0
    try:
        with open(os.path.join(data_dir, sample, "truth.tsv"), newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                total += int(row["length"])
    except (OSError, KeyError, ValueError):
        return None
    return total or None


def slope(points):
    """OLS slope of y on x in log space; None when degenerate."""
    xs, ys = [math.log(x) for x, _ in points], [math.log(y) for _, y in points]
    mean_x, mean_y = statistics.mean(xs), statistics.mean(ys)
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return None
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom


def summarise(status_rows, score_rows, threads, logs_dir, data_dir, min_points):
    recovered = defaultdict(float)
    for row in score_rows:
        value = number(row.get("recovered_plasmid_count"))
        if value is not None:
            recovered[row["tool"]] += value
    by_tool = defaultdict(list)
    for row in status_rows:
        by_tool[row["tool"]].append(row)
    out = []
    for tool, rows in sorted(by_tool.items()):
        done = [r for r in rows if r["status"] in ("completed", "reused")]
        failed = [r for r in rows if r["status"] == "failed"]
        resource = [r for r in failed if (m := EXIT_CODE.search(r.get("reason") or ""))
                    and int(m.group(1)) in RESOURCE_EXIT_CODES]
        skipped = [r for r in rows if r["status"] == "skipped"]
        runtimes = [v for r in done if (v := number(r.get("runtime_seconds"))) is not None]
        memory = [v for r in done if (v := number(r.get("peak_rss_kb"))) is not None]
        attempts = len(done) + len(failed)
        row = {"tool": tool, "n_runs": len(rows), "n_completed": len(done), "n_failed": len(failed),
               "n_resource_failures": len(resource), "n_skipped": len(skipped),
               "success_rate": len(done) / attempts if attempts else None, "threads": threads}
        if runtimes:
            row["median_runtime_seconds"] = statistics.median(runtimes)
            row["p90_runtime_seconds"] = percentile(runtimes, 0.9)
        if memory:
            row["median_peak_memory_gb"] = statistics.median(memory) / 1_048_576
        if tool in recovered:
            row["recovered_plasmids"] = recovered[tool]
            if runtimes and recovered[tool] > 0:
                row["thread_seconds_per_recovered_plasmid"] = sum(runtimes) * threads / recovered[tool]
        cpu_pairs = [(c, r_time) for r in done
                     if (c := read_cpu(logs_dir, r["sample"], tool)) is not None
                     and (r_time := number(r.get("runtime_seconds")))]
        if cpu_pairs:
            row["n_cpu_runs"] = len(cpu_pairs)
            row["cpu_utilisation"] = sum(c for c, _ in cpu_pairs) / (sum(t for _, t in cpu_pairs) * threads)
        for field, source in (("runtime_scaling_exponent", "runtime_seconds"), ("memory_scaling_exponent", "peak_rss_kb")):
            points = []
            for r in done:
                size, value = reference_length(data_dir, r["sample"]), number(r.get(source))
                if size and value and value > 0:
                    points.append((size, value))
            sizes = {size for size, _ in points}
            if len(sizes) >= min_points and max(sizes) / min(sizes) >= 1.5:
                row[field] = slope(points)
                row["n_scaling_points"] = len(sizes)
        out.append(row)
    return out


def fmt(value):
    return "" if value is None else (f"{value:.6f}" if isinstance(value, float) else str(value))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tool-status", required=True)
    ap.add_argument("--scores", help="scores.tsv, for recovered plasmid counts")
    ap.add_argument("--logs-dir", help="directory of <sample>.<tool>.rss files (memory, user and system CPU)")
    ap.add_argument("--data-dir", help="directory of <sample>/truth.tsv, for input size")
    ap.add_argument("--threads", type=int, default=int(os.environ.get("THREADS", 1)),
                    help="threads each run was given (default: $THREADS or 1)")
    ap.add_argument("--min-scaling-points", type=int, default=5)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    rows = summarise(read_tsv(args.tool_status), read_tsv(args.scores), max(args.threads, 1), args.logs_dir,
                     args.data_dir, args.min_scaling_points)
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: fmt(row.get(k)) for k in FIELDS})
    sys.stderr.write(f"[performance_summary] {len(rows)} tool(s) -> {args.out}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
