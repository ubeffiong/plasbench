#!/usr/bin/env python3
"""
clonal_groups.py -- group near-identical (clonal) isolates.

Clonal isolates -- same outbreak, same ST with the same plasmids -- are
pseudo-replicates: counting each as an independent observation narrows
confidence intervals and inflates paired tests. aggregate_results.py
resamples whole clusters, and counts clusters (not isolates) toward each
species' minimum for the species-balanced headline.

Group per isolate, in priority order:
  1. the sample sheet's `clonal_group` column (e.g. ST or a cgMLST cluster
     with plasmid content), when set;
  2. single-linkage clustering of whole-genome Mash distances between the
     isolates' truth references (DATA_DIR/<sample>/reference.fna) at
     --max-distance (default 0.0005, ~99.95% ANI over chromosome AND
     plasmids, so isolates differing in plasmid content stay separate);
  3. otherwise the isolate is its own group.

Output TSV: sample, clonal_group, method.

Standard library only (mash is called when available).
"""

import argparse
import csv
import os
import shutil
import subprocess
import sys
import tempfile


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        lines = (line for line in handle if line.strip() and not line.lstrip().startswith("#"))
        return [row for row in csv.DictReader(lines, delimiter="\t") if row.get("sample_id")]


def mash_pairs(references, max_distance, threads):
    """(sample_a, sample_b) pairs within max_distance, or None when mash is absent."""
    if len(references) < 2 or not shutil.which("mash"):
        return None
    with tempfile.TemporaryDirectory(prefix="plasbench_clonal_") as tmp:
        sketch = os.path.join(tmp, "isolates")
        paths = [references[sample] for sample in sorted(references)]
        build = subprocess.run(["mash", "sketch", "-p", str(threads), "-s", "10000", "-o", sketch] + paths,
                               text=True, capture_output=True)
        if build.returncode != 0:
            return None
        dist = subprocess.run(["mash", "dist", "-p", str(threads), sketch + ".msh", sketch + ".msh"],
                              text=True, capture_output=True)
        if dist.returncode != 0:
            return None
    by_path = {path: sample for sample, path in references.items()}
    pairs = []
    for line in dist.stdout.splitlines():
        fields = line.split("\t")
        if len(fields) < 3:
            continue
        a, b = by_path.get(fields[0]), by_path.get(fields[1])
        if a and b and a < b and float(fields[2]) <= max_distance:
            pairs.append((a, b))
    return pairs


def single_linkage(samples, pairs):
    parent = {sample: sample for sample in samples}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    return {sample: find(sample) for sample in samples}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample-sheet", required=True)
    ap.add_argument("--data-dir")
    ap.add_argument("--max-distance", type=float, default=0.0005)
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    rows = read_rows(args.sample_sheet)
    declared = {row["sample_id"]: (row.get("clonal_group") or "").strip() for row in rows}
    undeclared = [sample for sample, group in declared.items() if not group]
    references = {}
    if args.data_dir:
        for sample in undeclared:
            path = os.path.join(args.data_dir, sample, "reference.fna")
            if os.path.isfile(path) and os.path.getsize(path) > 0:
                references[sample] = path
    pairs = mash_pairs(references, args.max_distance, args.threads)
    clusters = single_linkage(sorted(references), pairs) if pairs is not None else {}
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["sample", "clonal_group", "method"])
        for row in rows:
            sample = row["sample_id"]
            if declared[sample]:
                writer.writerow([sample, f"declared:{declared[sample]}", "sample_sheet"])
            elif sample in clusters:
                writer.writerow([sample, f"mash:{clusters[sample]}", f"mash<={args.max_distance}"])
            else:
                writer.writerow([sample, f"isolate:{sample}", "none (own group)"])
    groups = {}
    for sample, group in clusters.items():
        groups.setdefault(group, []).append(sample)
    merged = sum(len(members) - 1 for members in groups.values())
    method = "mash" if pairs is not None else "no mash/reference"
    sys.stderr.write(f"[clonal_groups] {len(rows)} isolate(s); {merged} merged into clonal groups via {method} "
                     f"-> {args.out}\n")


if __name__ == "__main__":
    main()
