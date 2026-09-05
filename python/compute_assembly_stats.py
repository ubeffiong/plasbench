#!/usr/bin/env python3
"""Compute per-sample reference-assembly stats for cohort QC anomaly flagging.

Standard library only. These numbers are computed fresh from the downloaded
reference FASTA -- not sourced from NCBI's self-reported assembly metadata --
so they reflect the exact file the pipeline actually scores against.

Usage:
  compute_assembly_stats.py --fasta reference.fna --truth truth.tsv --out assembly_stats.tsv
"""

import argparse
import gzip
import sys


def open_maybe_gz(path, mode="rt"):
    return gzip.open(path, mode) if path.endswith(".gz") else open(path, mode)


def scan_fasta(path):
    """Return (list of sequence lengths, gc_count, acgt_count) for one FASTA.

    gc_percent is computed over A/C/G/T bases only (N and other ambiguity
    codes excluded from the denominator, so an N-heavy draft doesn't quietly
    skew composition toward 50%).
    """
    lengths = []
    length = 0
    gc = 0
    acgt = 0
    seen_record = False
    with open_maybe_gz(path) as handle:
        for line in handle:
            if line.startswith(">"):
                if seen_record:
                    lengths.append(length)
                seen_record = True
                length = 0
            else:
                stripped = line.strip()
                length += len(stripped)
                for base in stripped.upper():
                    if base in "ACGT":
                        acgt += 1
                        if base in "GC":
                            gc += 1
        if seen_record:
            lengths.append(length)
    return lengths, gc, acgt


def n50(lengths):
    if not lengths:
        return 0
    ordered = sorted(lengths, reverse=True)
    total = sum(ordered)
    half = total / 2.0
    cumulative = 0
    for value in ordered:
        cumulative += value
        if cumulative >= half:
            return value
    return ordered[-1]


def count_plasmids(truth_path):
    count = 0
    with open(truth_path, encoding="utf-8") as handle:
        header = handle.readline().rstrip("\n").split("\t")
        try:
            type_col = header.index("molecule_type")
        except ValueError:
            raise SystemExit(f"ERROR: {truth_path} has no molecule_type column")
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) > type_col and fields[type_col] == "PLASMID":
                count += 1
    return count


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fasta", required=True, help="reference FASTA (.fna/.fna.gz)")
    ap.add_argument("--truth", required=True, help="truth.tsv already written by stage 2")
    ap.add_argument("--sample-id", help="defaults to the reference FASTA's parent directory name")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    lengths, gc, acgt = scan_fasta(args.fasta)
    if not lengths:
        raise SystemExit(f"ERROR: no sequences found in {args.fasta}")
    plasmid_count = count_plasmids(args.truth)
    sample_id = args.sample_id or args.fasta.replace("\\", "/").rstrip("/").split("/")[-2]

    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write("sample_id\tassembly_size_bp\tcontig_count\tn50\tgc_percent\tplasmid_count\n")
        gc_percent = (100.0 * gc / acgt) if acgt else 0.0
        handle.write(
            f"{sample_id}\t{sum(lengths)}\t{len(lengths)}\t{n50(lengths)}\t{gc_percent:.4f}\t{plasmid_count}\n"
        )
    sys.stderr.write(f"[compute_assembly_stats] wrote {args.out} for {sample_id}\n")


if __name__ == "__main__":
    main()
