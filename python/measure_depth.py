#!/usr/bin/env python3
"""Measure paired-read coverage against the labelled reference length.

Speed: this reads both FASTQ files in full, so it is written to be fast. The two mates are counted at the same time,
in two processes. Decompression runs in a separate `pigz`/`gzip` process when one is installed, overlapping with the
counting. Only every 4th line (the sequence line) is touched, in C (itertools.islice + map), never as Python text.
"""
import argparse
import csv
import gzip
import io
import itertools
import shutil
import subprocess
from concurrent.futures import ProcessPoolExecutor


def reference_bp(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return sum(int(row["length"]) for row in csv.DictReader(handle, delimiter="\t"))


def _sequence_bases(handle) -> int:
    # FASTQ: header, sequence, '+', quality. bytes.rstrip drops "\n" / "\r\n" (sequence lines hold no spaces).
    return sum(map(len, map(bytes.rstrip, itertools.islice(handle, 1, None, 4))))


def fastq_bp(path):
    path = str(path)
    decompressor = (shutil.which("pigz") or shutil.which("gzip")) if path.endswith(".gz") else None
    if decompressor:
        proc = subprocess.Popen([decompressor, "-dc", path], stdout=subprocess.PIPE, bufsize=1 << 20)
        try:
            total = _sequence_bases(proc.stdout)
        finally:
            proc.stdout.close()
        if proc.wait() != 0:
            raise SystemExit(f"ERROR: could not decompress {path} ({decompressor} exited {proc.returncode})")
        return total
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rb") as raw:
        return _sequence_bases(io.BufferedReader(raw, buffer_size=1 << 20))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--truth", required=True); parser.add_argument("--r1", required=True); parser.add_argument("--r2", required=True); parser.add_argument("--out", required=True)
    args = parser.parse_args()
    reference = reference_bp(args.truth)
    if reference <= 0: raise SystemExit("ERROR: truth table has no reference bases")
    with ProcessPoolExecutor(max_workers=2) as pool:      # the two mates at the same time
        bases = sum(pool.map(fastq_bp, (args.r1, args.r2)))
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("reference_bp", "read_bases", "observed_depth_x"), delimiter="\t")
        writer.writeheader(); writer.writerow({"reference_bp": reference, "read_bases": bases, "observed_depth_x": f"{bases / reference:.6f}"})

if __name__ == "__main__": main()
