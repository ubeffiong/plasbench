#!/usr/bin/env python3
"""Short-read QC and eligibility gate: PASS, WARN or REJECT before a sample is assembled or any tool is run.

PlasBench assembles each isolate's paired Illumina reads and runs every tool on that assembly, so a bad read set changes every
tool's result in the same direction and looks like a tool difference. This gate measures the raw read pair before stage 3 and
decides, with the reason recorded:

  PASS    meets every minimum
  WARN    a quality concern; the sample proceeds, is flagged, and belongs in a sensitivity analysis
  REJECT  fails a critical requirement; with SHORT_READ_QC_MODE=enforce it does not proceed to assembly or the tools and is
          excluded from the primary benchmark (recorded as `rejected`, never scored as a tool failure)

What is measured (from the first --max-pairs read pairs; the total is exact when the files are shorter than that, otherwise an
estimate from how much of the compressed file the sample consumed, and is labelled):
  integrity           readable, not truncated, not empty, well-formed FASTQ, equal read counts (known when a file ends early)
  read pairs, bases and depth     depth uses --genome-size-mb (default 5 Mb, flagged as assumed when not given)
  read quality        mean Phred, share of bases at Q20 and Q30
  read length         median per mate
  composition         GC percent, N fraction, and the GC deviation from --expected-gc when given
  adapters            reads carrying the TruSeq or Nextera adapter (a signal that trimming is needed, not a reason to discard)
  duplication         share of pairs whose first 50 bp on both mates repeat (read cautiously: high depth also duplicates)
  pair synchrony      read names that disagree between the two files at the same position

Not measured: taxonomic contamination (it needs a database, so `contamination_screen` says not_evaluated; the post-assembly
size and GC check in assembly_qc_gate.py is the only mixed-culture signal today).

Thresholds live in config/short_read_qc_thresholds.tsv, each row marked provisional or frozen. The shipped values are PROVISIONAL:
they are conservative starting points, not universal cut-offs, and must be set from pilot data on the intended platform and then
frozen before the main benchmark is run. Integrity failures reject whatever the thresholds say.

  short_read_qc.py qc --sample S --r1 R1.fastq.gz --r2 R2.fastq.gz --out S.short_read_qc.tsv
  short_read_qc.py merge --shards DIR --out results/short_read_qc.tsv --status-out results/short_read_qc_status.tsv

Standard library only.
"""
import argparse
import csv
import gzip
import hashlib
import os
import statistics
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_THRESHOLDS = os.path.join(HERE, "..", "config", "short_read_qc_thresholds.tsv")
ADAPTERS = ("AGATCGGAAGAGC", "CTGTCTCTTATACACATCT")        # TruSeq (read 1 and 2) and Nextera transposase
DEFAULT_GENOME_MB = 5.0
TAB, NL = chr(9), chr(10)
FIELDS = ["sample", "qc_status", "reasons", "integrity", "read_pairs_sampled", "read_pairs_total", "pairs_basis", "estimated_bases",
          "estimated_depth_x", "genome_size_mb", "genome_size_assumed", "r1_median_length", "r2_median_length", "median_read_length",
          "mean_quality", "q20_fraction", "q30_fraction", "gc_percent", "n_fraction", "adapter_fraction", "duplication_fraction",
          "pair_mismatch_fraction", "gc_deviation", "contamination_screen", "policy_status", "thresholds_sha"]
STATUS_FIELDS = ["sample", "qc_status", "reasons", "action"]


class FastqProblem(Exception):
    def __init__(self, kind, detail=""):
        super().__init__(f"{kind}: {detail}")
        self.kind, self.detail = kind, detail


def open_raw(path):
    raw = open(path, "rb")
    if path.endswith(".gz"):
        return raw, gzip.GzipFile(fileobj=raw)
    return raw, raw


def read_record(handle, where):
    """One FASTQ record as bytes (name, sequence, quality), or None at a clean end of file."""
    try:
        header = handle.readline()
        if not header:
            return None
        seq, plus, qual = handle.readline(), handle.readline(), handle.readline()
    except (EOFError, OSError) as exc:                    # BadGzipFile and zlib.error are OSError / EOFError
        raise FastqProblem("truncated_or_corrupt", f"{where}: {exc}")
    if not qual:
        raise FastqProblem("truncated", f"{where}: file ends inside a record")
    seq, qual = seq.rstrip(b"\r\n"), qual.rstrip(b"\r\n")
    if not header.startswith(b"@") or not plus.startswith(b"+") or len(seq) != len(qual):
        raise FastqProblem("malformed_fastq", f"{where}: not a valid FASTQ record")
    return header.rstrip(b"\r\n"), seq, qual


def name_of(header):
    token = header[1:].split()[0] if len(header) > 1 else b""
    return token[:-2] if token.endswith((b"/1", b"/2")) else token


def read_thresholds(path):
    rows, text = [], open(path, "rb").read()
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader((l for l in handle if l.strip() and not l.startswith("#")), delimiter=TAB):
            rows.append({"metric": row["metric"], "direction": row["direction"], "warn": row["warn"].strip(),
                         "reject": row["reject"].strip(), "status": row["status"].strip()})
    policy = "frozen" if rows and all(r["status"] == "frozen" for r in rows) else "provisional"
    return rows, policy, hashlib.sha256(text).hexdigest()[:12]


EXACT_BELOW_BYTES = 8 * 1024 * 1024     # a compressed file this small is read to the end, so its read count is exact


def measure(r1, r2, max_pairs=200000, genome_mb=None, expected_gc=None, exact_below=EXACT_BELOW_BYTES):
    """Metrics and an integrity verdict for one read pair of files."""
    m = {"integrity": "ok", "pairs_basis": "", "read_pairs_sampled": 0, "read_pairs_total": None}
    sizes = [os.path.getsize(p) for p in (r1, r2)]
    if min(sizes) == 0:
        m["integrity"] = "empty"
        return m
    raw1, h1 = open_raw(r1)
    raw2, h2 = open_raw(r2)
    lengths, counts = ([], []), Counter()
    q_sum = q20 = q30 = bases = gc = acgt = n = adapter_reads = mismatches = pairs = dup = 0
    seen = set()
    ended = [False, False]
    try:
        while pairs < max_pairs:
            a, b = read_record(h1, "R1"), read_record(h2, "R2")
            ended = [a is None, b is None]
            if a is None or b is None:
                break
            pairs += 1
            if name_of(a[0]) != name_of(b[0]):
                mismatches += 1
            for mate, rec in enumerate((a, b)):
                seq, qual = rec[1], rec[2]
                lengths[mate].append(len(seq))
                bases += len(seq)
                for phred in qual:
                    p = phred - 33
                    q_sum += p
                    q20 += p >= 20
                    q30 += p >= 30
                counts.update(seq)
            if any(ad in a[1] or ad in b[1] for ad in (x.encode() for x in ADAPTERS)):
                adapter_reads += 1
            key = hash((a[1][:50], b[1][:50]))
            if key in seen:
                dup += 1
            else:
                seen.add(key)
        if ended[0] != ended[1]:
            raise FastqProblem("unequal_read_counts", "one file ends before the other")
        consumed = [raw1.tell(), raw2.tell()]
        extra = 0
        if not any(ended) and max(sizes) <= exact_below:      # small enough to count every remaining pair (and check its integrity)
            while True:
                a, b = read_record(h1, "R1"), read_record(h2, "R2")
                if a is None or b is None:
                    ended = [a is None, b is None]
                    break
                extra += 1
            if ended[0] != ended[1]:
                raise FastqProblem("unequal_read_counts", "one file ends before the other")
    except FastqProblem as exc:
        m["integrity"] = exc.kind
        m["integrity_detail"] = exc.detail
        return m
    finally:
        h1.close(); h2.close(); raw1.close(); raw2.close()
    if pairs == 0:
        m["integrity"] = "empty"
        return m
    gc, acgt, n = counts[ord("G")] + counts[ord("C")], sum(counts[ord(c)] for c in "ACGT"), counts[ord("N")]
    if all(ended):
        total, basis = pairs + extra, "exact"
    else:                                                  # the sample did not reach the end: scale by the compressed bytes read
        total, basis = round(pairs * max(sizes[0] / max(consumed[0], 1), 1.0)), "estimated"
    mean_len = (statistics.mean(lengths[0]) + statistics.mean(lengths[1]))
    genome = genome_mb if genome_mb else DEFAULT_GENOME_MB
    m.update(
        read_pairs_sampled=pairs, read_pairs_total=total, pairs_basis=basis, estimated_bases=round(total * mean_len),
        genome_size_mb=genome, genome_size_assumed="no" if genome_mb else "yes",
        r1_median_length=statistics.median(lengths[0]), r2_median_length=statistics.median(lengths[1]),
        mean_quality=q_sum / bases, q20_fraction=q20 / bases, q30_fraction=q30 / bases,
        gc_percent=100.0 * gc / acgt if acgt else None, n_fraction=n / bases, adapter_fraction=adapter_reads / pairs,
        duplication_fraction=dup / pairs, pair_mismatch_fraction=mismatches / pairs)
    m["read_pairs"] = total
    m["estimated_depth_x"] = m["estimated_bases"] / (genome * 1e6)
    m["median_read_length"] = min(m["r1_median_length"], m["r2_median_length"])
    m["gc_deviation"] = abs(m["gc_percent"] - expected_gc) / 100.0 if (expected_gc is not None and m["gc_percent"] is not None) else None
    return m


def decide(m, thresholds):
    """(PASS | WARN | REJECT, reasons). Integrity failures reject; thresholds decide the rest."""
    if m["integrity"] != "ok":
        detail = m.get("integrity_detail", "")
        return "REJECT", [f"integrity: {m['integrity']}" + (f" ({detail})" if detail else "")]
    status, reasons = "PASS", []
    for t in thresholds:
        value = m.get(t["metric"])
        if value is None:
            continue
        for level, word in (("reject", "REJECT"), ("warn", "WARN")):
            if t[level] == "":
                continue
            limit = float(t[level])
            bad = value < limit if t["direction"] == "min" else value > limit
            if bad:
                reasons.append(f"{t['metric']} {value:.4g} {'<' if t['direction'] == 'min' else '>'} {limit:g} ({word.lower()})")
                if word == "REJECT" or status == "PASS":
                    status = word
                break
    return status, reasons


def fmt(value):
    if value is None:
        return ""
    return f"{value:.6g}" if isinstance(value, float) else str(value)


def cmd_qc(a):
    thresholds, policy, sha = read_thresholds(a.thresholds)
    m = measure(a.r1, a.r2, a.max_pairs, a.genome_size_mb, a.expected_gc, int(a.exact_below_mb * 1024 * 1024))
    status, reasons = decide(m, thresholds)
    row = {k: m.get(k) for k in FIELDS}
    row.update(sample=a.sample, qc_status=status, reasons="; ".join(reasons), contamination_screen="not_evaluated",
               policy_status=policy, thresholds_sha=sha)
    with open(a.out, "w", newline="", encoding="utf-8") as handle:
        handle.write(TAB.join(FIELDS) + NL + TAB.join(fmt(row[k]).replace(TAB, " ") for k in FIELDS) + NL)
    print(f"short-read QC {a.sample}: {status}" + (f" ({'; '.join(reasons)})" if reasons else ""))
    return 0


def cmd_merge(a):
    rows = []
    for name in sorted(os.listdir(a.shards)):
        path = os.path.join(a.shards, name)
        if name.endswith(".tsv") and os.path.getsize(path):
            with open(path, newline="", encoding="utf-8") as handle:
                rows.extend(csv.DictReader(handle, delimiter=TAB))
    with open(a.out, "w", newline="", encoding="utf-8") as handle:
        handle.write(TAB.join(FIELDS) + NL)
        for r in rows:
            handle.write(TAB.join(r.get(k, "") for k in FIELDS) + NL)
    if a.status_out:
        mode = a.mode
        with open(a.status_out, "w", newline="", encoding="utf-8") as handle:
            handle.write(TAB.join(STATUS_FIELDS) + NL)
            for r in rows:
                action = ("excluded from the primary benchmark" if r["qc_status"] == "REJECT" and mode == "enforce"
                          else "proceeded (flagged)" if r["qc_status"] in ("WARN", "REJECT") else "proceeded")
                handle.write(TAB.join([r["sample"], r["qc_status"], r["reasons"], action]) + NL)
    counts = Counter(r["qc_status"] for r in rows)
    print(f"short-read QC: {len(rows)} sample(s): " + ", ".join(f"{counts.get(k, 0)} {k}" for k in ("PASS", "WARN", "REJECT")))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("qc", help="measure and decide one sample")
    p.add_argument("--sample", required=True)
    p.add_argument("--r1", required=True)
    p.add_argument("--r2", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--thresholds", default=DEFAULT_THRESHOLDS)
    p.add_argument("--max-pairs", type=int, default=200000)
    p.add_argument("--exact-below-mb", type=float, default=8.0,
                   help="count every pair, exactly, when the larger compressed file is no bigger than this (default 8 MB)")
    p.add_argument("--genome-size-mb", type=float)
    p.add_argument("--expected-gc", type=float, help="expected GC percent of the organism, to flag a deviation")
    p.set_defaults(fn=cmd_qc)
    p = sub.add_parser("merge", help="merge per-sample shards into the run tables")
    p.add_argument("--shards", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--status-out")
    p.add_argument("--mode", default="report", choices=("off", "report", "enforce"))
    p.set_defaults(fn=cmd_merge)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
