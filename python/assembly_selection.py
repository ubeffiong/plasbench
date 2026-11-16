#!/usr/bin/env python3
"""Assembly selection policy: which short-read assembly the tools are run on, chosen by a declared rule and never by benchmark score.

Two different questions are called "choosing the assembly". This module answers the first only:

  INPUT assembly      which short-read assembly is handed to the plasmid tools (this module);
  REFERENCE assembly  which complete assembly is accepted as truth (truth_provenance.py, reference tiers, independence).

The input assembly is chosen from assembly-side evidence only. The policy has no access to the truth, to a tool's output or to any
score, so it cannot favour whichever assembly makes a tool look best. Every candidate is measured and kept; the choice and the reason
are recorded.

Candidate evidence (per assembly):
  contigs, total length, N50, L50, largest contig, GC, bases in contigs >= 1 kb and >= 10 kb
  read support        with --reads1/--reads2 and minimap2: the share of a sample of reads that map to the assembly (otherwise
                      `not_evaluated`, never assumed)

Eligibility (a candidate that fails any of these cannot be selected; the reasons are listed):
  total length inside [--min-total-mb, --max-total-mb]  (default 1 to 10 Mb: a bacterial genome plus plasmids)
  at least one contig
  read support >= --min-mapped-fraction (default 0.80), when evaluated

Policies (declare one before the main benchmark and keep it):
  fixed    the configured primary assembler (default; today's behaviour). Chosen if eligible; if it is not, NO candidate is
           silently substituted: the sample is reported as having no eligible assembly.
  quality  among the eligible candidates the highest N50, then the fewest contigs, then the assembler name. No eligible candidate:
           none is selected.

When assemblers are being COMPARED, do not select: keep each assembly as its own input condition. Selection is for choosing the
assembly a run proceeds with; the alternatives are retained in the candidate table for a sensitivity analysis.

  assembly_selection.py select --sample S --candidate spades=/path/contigs.fasta --candidate unicycler=/path/assembly.fasta \\
      --policy quality --primary spades --out S.assembly_candidates.tsv

Standard library only (minimap2 optional, for read support).
"""
import argparse
import csv
import os
import shutil
import subprocess
import sys
import tempfile

TAB, NL = chr(9), chr(10)
FIELDS = ["sample", "assembler", "path", "eligible", "reasons", "n_contigs", "total_length", "n50", "l50", "largest_contig",
          "gc_percent", "bp_ge_1kb", "bp_ge_10kb", "mapped_read_fraction", "selected", "selection_reason", "policy", "primary"]


def fasta_lengths_gc(path):
    lengths, gc, acgt, current = [], 0, 0, 0
    opener = open
    if path.endswith(".gz"):
        import gzip
        opener = gzip.open
    with opener(path, "rt") as handle:
        for line in handle:
            if line.startswith(">"):
                if current:
                    lengths.append(current)
                current = 0
            else:
                s = line.strip().upper()
                current += len(s)
                gc += s.count("G") + s.count("C")
                acgt += sum(s.count(c) for c in "ACGT")
    if current:
        lengths.append(current)
    return lengths, gc, acgt


def n50_l50(lengths):
    total, running = sum(lengths), 0
    for i, n in enumerate(sorted(lengths, reverse=True), 1):
        running += n
        if running * 2 >= total:
            return n, i
    return 0, 0


def mapped_read_fraction(assembly, r1, r2, sample_reads=100000, threads=2):
    """Share of sampled reads (both mates) with a primary alignment to the assembly, or None when it cannot be measured."""
    if not (r1 and r2 and shutil.which("minimap2")):
        return None
    import gzip
    with tempfile.TemporaryDirectory(prefix="asmsel_") as tmp:
        total = 0
        outs = []
        for mate, path in ((1, r1), (2, r2)):
            out = os.path.join(tmp, f"r{mate}.fq")
            opener = gzip.open if path.endswith(".gz") else open
            with opener(path, "rt") as src, open(out, "w") as dst:
                for i, line in enumerate(src):
                    if i >= sample_reads * 4:
                        break
                    dst.write(line)
            outs.append(out)
        done = subprocess.run(["minimap2", "-x", "sr", "-t", str(threads), assembly, outs[0], outs[1]], capture_output=True, text=True)
        if done.returncode:
            return None
        mapped = set()
        for line in done.stdout.splitlines():
            f = line.split(TAB)
            if len(f) >= 12 and "tp:A:S" not in f[12:]:
                mapped.add(f[0])
        reads = sum(1 for _ in open(outs[0])) // 4
        return min(1.0, len(mapped) / reads) if reads else None


def measure(sample, assembler, path, reads=None, min_mb=1.0, max_mb=10.0, min_mapped=0.80, sample_reads=100000):
    row = {k: "" for k in FIELDS}
    row.update(sample=sample, assembler=assembler, path=path)
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        row.update(eligible="no", reasons="no assembly file", n_contigs=0)
        return row
    lengths, gc, acgt = fasta_lengths_gc(path)
    total = sum(lengths)
    n50, l50 = n50_l50(lengths)
    mapped = mapped_read_fraction(path, *(reads or (None, None)), sample_reads=sample_reads)
    row.update(n_contigs=len(lengths), total_length=total, n50=n50, l50=l50, largest_contig=max(lengths) if lengths else 0,
               gc_percent=f"{100.0 * gc / acgt:.2f}" if acgt else "", bp_ge_1kb=sum(n for n in lengths if n >= 1000),
               bp_ge_10kb=sum(n for n in lengths if n >= 10000),
               mapped_read_fraction="not_evaluated" if mapped is None else f"{mapped:.4f}")
    reasons = []
    if not lengths:
        reasons.append("no contigs")
    if total and total < min_mb * 1e6:
        reasons.append(f"total length {total / 1e6:.2f} Mb < {min_mb:g} Mb")
    if total > max_mb * 1e6:
        reasons.append(f"total length {total / 1e6:.2f} Mb > {max_mb:g} Mb")
    if mapped is not None and mapped < min_mapped:
        reasons.append(f"read support {mapped:.2f} < {min_mapped:g}")
    row.update(eligible="no" if reasons else "yes", reasons="; ".join(reasons))
    return row


def select(rows, policy, primary):
    """(assembler or None, reason). Uses only the measured columns: no truth, no tool output, no score."""
    eligible = [r for r in rows if r["eligible"] == "yes"]
    if policy == "fixed":
        chosen = next((r for r in eligible if r["assembler"] == primary), None)
        if chosen:
            return chosen["assembler"], f"fixed: the configured assembler {primary} is eligible"
        known = next((r for r in rows if r["assembler"] == primary), None)
        why = known["reasons"] if known else "the primary assembly was not produced"
        return None, f"fixed: the configured assembler {primary} is not eligible ({why}); no other candidate was substituted"
    if not eligible:
        return None, "quality: no candidate is eligible"
    best = sorted(eligible, key=lambda r: (-int(r["n50"]), int(r["n_contigs"]), r["assembler"]))[0]
    return best["assembler"], f"quality: highest N50 ({best['n50']}), then fewest contigs, among {len(eligible)} eligible"


def cmd_select(a):
    candidates = []
    for item in a.candidate:
        name, _, path = item.partition("=")
        candidates.append((name, path))
    reads = (a.reads1, a.reads2) if a.reads1 and a.reads2 else None
    rows = [measure(a.sample, name, path, reads, a.min_total_mb, a.max_total_mb, a.min_mapped_fraction, a.sample_reads)
            for name, path in candidates]
    chosen, reason = select(rows, a.policy, a.primary)
    for r in rows:
        r["selected"] = "yes" if r["assembler"] == chosen else "no"
        r["selection_reason"] = reason if r["assembler"] == chosen or chosen is None else ""
        r["policy"], r["primary"] = a.policy, a.primary
    with open(a.out, "w", newline="", encoding="utf-8") as handle:
        handle.write(TAB.join(FIELDS) + NL)
        for r in rows:
            handle.write(TAB.join(str(r[k]).replace(TAB, " ") for k in FIELDS) + NL)
    if a.selected_out:
        with open(a.selected_out, "w", encoding="utf-8") as handle:
            handle.write((chosen or "") + NL)
    print(f"assembly selection {a.sample}: " + (f"{chosen} ({reason})" if chosen else f"none ({reason})"))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("select")
    p.add_argument("--sample", required=True)
    p.add_argument("--candidate", action="append", required=True, help="ASSEMBLER=path to its contigs FASTA; repeat for each candidate")
    p.add_argument("--policy", choices=("fixed", "quality"), default="fixed")
    p.add_argument("--primary", required=True, help="the configured assembler (the one `fixed` selects)")
    p.add_argument("--out", required=True)
    p.add_argument("--selected-out", help="write the selected assembler's name here (empty when none is eligible)")
    p.add_argument("--reads1")
    p.add_argument("--reads2")
    p.add_argument("--sample-reads", type=int, default=100000)
    p.add_argument("--min-total-mb", type=float, default=1.0)
    p.add_argument("--max-total-mb", type=float, default=10.0)
    p.add_argument("--min-mapped-fraction", type=float, default=0.80)
    p.set_defaults(fn=cmd_select)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
