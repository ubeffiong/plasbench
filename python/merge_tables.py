#!/usr/bin/env python3
"""Merge per-run shard TSVs (same header) into one table, in a stable order.

Stage 5 writes one small table per (sample, tool) so parallel jobs never share a file. This
collects `<results-dir>/<sample>/*<suffix>` and puts them together: the header is taken from the first shard, every other shard must agree
(a mismatch is an error, never a silent column shift), and rows keep shard-path order so the
result is the same however the jobs interleaved. No shards is not an error: the output is
simply not written, and a missing table means "not evaluated". Standard library only.
"""
import argparse
import csv
import os
import sys


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results-dir", required=True, help="directory whose sample sub-folders hold the shards")
    ap.add_argument("--suffix", required=True, help="shard file suffix, e.g. .accuracy.tsv")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    shards = []
    for entry in sorted(os.scandir(args.results_dir), key=lambda e: e.name):
        if entry.is_dir():
            shards.extend(sorted(os.path.join(entry.path, f) for f in os.listdir(entry.path)
                                 if f.endswith(args.suffix)))
    header, rows = None, []
    for path in shards:
        if os.path.getsize(path) == 0:
            continue
        with open(path, newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle, delimiter="\t")
            first = next(reader, None)
            if first is None:
                continue
            if header is None:
                header = first
            elif first != header:
                raise SystemExit(f"ERROR: {path} has a different header than {shards[0]}; refusing to merge")
            rows.extend(r for r in reader if r)
    if header is None:
        sys.stderr.write(f"[merge_tables] no *{args.suffix} shards under {args.results_dir}; {args.out} not written\n")
        if os.path.exists(args.out):
            os.remove(args.out)
        return 0
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    sys.stderr.write(f"[merge_tables] {len(rows)} row(s) from {len(shards)} shard(s) -> {args.out}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
