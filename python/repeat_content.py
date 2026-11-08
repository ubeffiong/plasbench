#!/usr/bin/env python3
"""Per-replicon k-mer repeat content of the truth reference (descriptive only).

Repeats make plasmid assembly and binning hard, so the benchmark records how
repetitive each truth replicon is. Idea (not code) from GAEMR's k-mer repeat
content (k=29). Canonical k-mers are used (the smaller of a k-mer and its
reverse complement), so inverted repeats count as repeats.

Per replicon:
  internal_repeat_fraction  share of the replicon's k-mer positions whose
                            canonical k-mer occurs more than once in it
  chromosome_shared_fraction (PLASMID only) share of its k-mer positions whose
                            canonical k-mer is also present in any CHROMOSOME
  shared_with_other_plasmids_fraction (PLASMID only) same, versus the other
                            plasmids of the sample

Memory: plasmid canonical k-mer counts are held (bounded by total plasmid
size). Chromosomes are then STREAMED and only k-mers already in the plasmid
set are recorded, so shared-with-chromosome costs no chromosome-sized memory.
The chromosome's own internal_repeat_fraction needs a count of every k-mer,
so it is computed only for chromosomes of at most --max-chromosome-bp
(default 12,000,000); larger ones get status chromosome_skipped (they are
still streamed for the plasmid-sharing figure).

K-mers containing a non-ACGT base are skipped (and not counted in n_kmers).
This never edits truth; it is a descriptive feature. Subcommand `summary`
merges data/<sample>/truth_repeat_content.tsv shards.
"""
from __future__ import annotations

import argparse
import csv
import glob
import os
import sys
from collections import Counter

FIELDS = ("sample", "sequence_id", "molecule_type", "length", "n_kmers",
          "internal_repeat_fraction", "chromosome_shared_fraction",
          "shared_with_other_plasmids_fraction", "repeat_rich", "status")
_CODE = {"A": 0, "C": 1, "G": 2, "T": 3}


def canonical_kmers(seq, k):
    """Yield the canonical (2-bit packed) k-mer at each ACGT-only position."""
    if k > 32 or k < 1:
        raise ValueError("k must be 1..32")
    mask = (1 << (2 * k)) - 1
    shift = 2 * (k - 1)
    fwd = rev = 0
    valid = 0
    for ch in seq.upper():
        c = _CODE.get(ch)
        if c is None:
            valid = 0
            fwd = rev = 0
            continue
        fwd = ((fwd << 2) | c) & mask
        rev = (rev >> 2) | ((3 - c) << shift)
        valid += 1
        if valid >= k:
            yield fwd if fwd < rev else rev


def read_fasta(path):
    """Yield (id, sequence) streaming; id is the first header token."""
    name, parts = None, []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line.startswith(">"):
                if name is not None:
                    yield name, "".join(parts)
                name = line[1:].split()[0] if line[1:].split() else ""
                parts = []
            elif name is not None:
                parts.append(line)
    if name is not None:
        yield name, "".join(parts)


def read_truth(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def repeated_fraction(counts):
    total = sum(counts.values())
    if not total:
        return None
    return sum(n for n in counts.values() if n > 1) / total


def fmt(value):
    return "" if value is None else f"{value:.6f}"


def compute(reference, truth_rows, sample, k=29, threshold=0.05, max_chromosome_bp=12_000_000):
    types = {r["sequence_id"]: (r.get("molecule_type") or "").upper() for r in truth_rows}
    lengths = {r["sequence_id"]: r.get("length", "") for r in truth_rows}
    rows = {sid: {"sample": sample, "sequence_id": sid, "molecule_type": mt,
                  "length": lengths[sid], "n_kmers": "", "internal_repeat_fraction": "",
                  "chromosome_shared_fraction": "", "shared_with_other_plasmids_fraction": "",
                  "repeat_rich": "", "status": "missing_sequence"}
            for sid, mt in types.items()}
    plasmid_counts = {}
    # Pass 1: plasmids (counts held; bounded by total plasmid size).
    for sid, seq in read_fasta(reference):
        if types.get(sid) != "PLASMID":
            continue
        plasmid_counts[sid] = Counter(canonical_kmers(seq, k))
        rows[sid]["length"] = str(len(seq)) if not lengths[sid] else lengths[sid]
    union = Counter()
    for counts in plasmid_counts.values():
        union.update(counts.keys())  # number of plasmids holding each k-mer
    chrom_hits = set()
    have_chromosome = False
    # Pass 2: chromosomes streamed; only plasmid-set k-mers are remembered.
    for sid, seq in read_fasta(reference):
        if types.get(sid) != "CHROMOSOME":
            continue
        have_chromosome = True
        row = rows[sid]
        small = len(seq) <= max_chromosome_bp
        counts = Counter() if small else None
        n = 0
        for km in canonical_kmers(seq, k):
            n += 1
            if counts is not None:
                counts[km] += 1
            if km in union:
                chrom_hits.add(km)
        row["n_kmers"] = n
        if small:
            frac = repeated_fraction(counts)
            row["internal_repeat_fraction"] = fmt(frac)
            row["repeat_rich"] = ("yes" if frac is not None and frac >= threshold else "no")
            row["status"] = "ok" if n else "too_short"
        else:
            row["status"] = "chromosome_skipped"
        row["length"] = lengths[sid] or str(len(seq))
    for sid, counts in plasmid_counts.items():
        row = rows[sid]
        total = sum(counts.values())
        row["n_kmers"] = total
        if not total:
            row["status"] = "too_short"
            continue
        internal = repeated_fraction(counts)
        row["internal_repeat_fraction"] = fmt(internal)
        shared_other = sum(n for km, n in counts.items() if union[km] > 1) / total
        row["shared_with_other_plasmids_fraction"] = fmt(shared_other)
        if have_chromosome:
            shared_chr = sum(n for km, n in counts.items() if km in chrom_hits) / total
            row["chromosome_shared_fraction"] = fmt(shared_chr)
            row["status"] = "ok"
        else:
            shared_chr = 0.0
            row["status"] = "no_chromosome"
        row["repeat_rich"] = "yes" if (internal >= threshold or shared_chr >= threshold) else "no"
    for sid, row in rows.items():
        if row["status"] == "missing_sequence" and types[sid] not in ("PLASMID", "CHROMOSOME"):
            row["status"] = "not_evaluated_molecule_type"
    return list(rows.values())


def write_rows(path, rows, fields=FIELDS):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def summarize(data_dir, out):
    shards = sorted(glob.glob(os.path.join(data_dir, "*", "truth_repeat_content.tsv")))
    header, merged = None, []
    for shard in shards:
        with open(shard, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            if header is None:
                header = reader.fieldnames
            elif reader.fieldnames != header:
                raise SystemExit(f"ERROR: header mismatch in {shard}")
            merged.extend(reader)
    if header is None:
        print("no truth_repeat_content.tsv shards found; nothing written", file=sys.stderr)
        return 0
    write_rows(out, merged, header)
    print(f"{len(merged)} rows from {len(shards)} shards -> {out}")
    return len(merged)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "summary":
        ap = argparse.ArgumentParser(prog="repeat_content.py summary")
        ap.add_argument("--data-dir", required=True)
        ap.add_argument("--out", required=True)
        a = ap.parse_args(argv[1:])
        summarize(a.data_dir, a.out)
        return 0
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sample", required=True)
    ap.add_argument("--k", type=int, default=29)
    ap.add_argument("--repeat-rich-threshold", type=float, default=0.05)
    ap.add_argument("--max-chromosome-bp", type=int, default=12_000_000)
    a = ap.parse_args(argv)
    rows = compute(a.reference, read_truth(a.truth), a.sample, a.k,
                   a.repeat_rich_threshold, a.max_chromosome_bp)
    write_rows(a.out, rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
