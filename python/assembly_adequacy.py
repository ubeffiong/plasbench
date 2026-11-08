#!/usr/bin/env python3
"""Per-sample assembly adequacy: can the assembly support plasmid reconstruction at all?

Idea (reimplemented, no code copied): plsMD gates a dataset on whether the assembly
contains the plasmids before any tool is judged; GAEMR reports assembly statistics
(contig counts, N50, GC) beside coverage. Here one row per sample gives

  plasmid_adequacy = assembly-covered plasmid bp / truth plasmid bp
                     (from contig_classification.py `label --coverage-out`)
  contig mix       = counts and bp per contig label (PLASMID, CHROMOSOME, AMBIGUOUS,
                     UNPLACED, CHIMERIC = an assembly misjoin whose plasmid and
                     chromosome segments each fall below the coverage threshold but
                     jointly cover the contig). Unknown or absent labels count as 0.
  assembly stats   = N50, total length, GC percent (contigs FASTA when given).

`adequate` = plasmid_adequacy >= --min-adequacy (default 0.90); "not_assessed" when the
sample has no plasmid or the inputs are missing. Descriptive: it never ranks tools and
never fails on a missing file (the row carries the status and reason).

Subcommands: (default) one sample; `merge` walks <data-dir>/<sample>/.
Standard library only.
"""
import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from compute_assembly_stats import scan_fasta, n50 as _n50
except Exception:  # pragma: no cover - fallback if import fails
    scan_fasta = None
    _n50 = None

FIELDS = ["sample", "assembly_status", "truth_plasmid_bp", "assembly_covered_plasmid_bp", "plasmid_adequacy",
          "n_contigs", "contig_bp", "n_plasmid_contigs", "n_chromosome_contigs", "n_ambiguous", "n_unplaced",
          "n_chimeric", "chimeric_bp", "unplaced_fraction", "chimeric_fraction", "assembly_n50",
          "assembly_total_length", "assembly_gc_percent", "adequate", "reason"]


def n50(lengths):
    """N50: the length L such that contigs of length >= L hold at least half the bases.
    Hand value: [100, 80, 60, 40, 20] total 300, half 150 -> 100+80 >= 150 -> 80."""
    if _n50 is not None:
        return _n50(lengths)
    ordered = sorted(lengths, reverse=True)
    half, cum = sum(ordered) / 2.0, 0
    for value in ordered:
        cum += value
        if cum >= half:
            return value
    return 0


def fasta_stats(path):
    """(lengths, gc_percent) from a FASTA (plain or .gz)."""
    if scan_fasta is not None:
        lengths, gc, acgt = scan_fasta(path)
    else:
        lengths, length, gc, acgt = [], 0, 0, 0
        seen = False
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if line.startswith(">"):
                    if seen:
                        lengths.append(length)
                    seen, length = True, 0
                else:
                    s = line.strip().upper()
                    length += len(s)
                    acgt += sum(s.count(b) for b in "ACGT")
                    gc += s.count("G") + s.count("C")
        if seen:
            lengths.append(length)
    return lengths, (100.0 * gc / acgt if acgt else 0.0)


def _read_tsv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _frac(a, b):
    return f"{a / b:.4f}" if b else ""


def adequacy_row(sample, labels_path=None, coverage_path=None, contigs_fasta=None, min_adequacy=0.90):
    row = {k: "" for k in FIELDS}
    row["sample"] = sample
    row["adequate"] = "not_assessed"
    reasons = []
    labels = None
    if labels_path and os.path.isfile(labels_path):
        try:
            labels = _read_tsv(labels_path)
        except Exception as exc:  # unreadable file is a status, not a crash
            reasons.append(f"contig labels unreadable: {exc}")
    else:
        reasons.append("contig labels file missing")
    lengths_from_fasta = None
    if contigs_fasta and os.path.isfile(contigs_fasta):
        try:
            lengths_from_fasta, gc = fasta_stats(contigs_fasta)
            if lengths_from_fasta:
                row["assembly_n50"] = n50(lengths_from_fasta)
                row["assembly_total_length"] = sum(lengths_from_fasta)
                row["assembly_gc_percent"] = f"{gc:.4f}"
        except Exception as exc:
            reasons.append(f"contigs fasta unreadable: {exc}")
    if labels is None:
        row["assembly_status"] = "contig_labels_unavailable"
        row["reason"] = "; ".join(reasons)
        return row
    row["assembly_status"] = "ok"
    counts = {"PLASMID": 0, "CHROMOSOME": 0, "AMBIGUOUS": 0, "UNPLACED": 0, "CHIMERIC": 0}
    bp = dict.fromkeys(counts, 0)
    total = 0
    lengths = []
    for r in labels:
        length = _int(r.get("length"))
        lengths.append(length)
        total += length
        label = (r.get("label") or "").strip().upper()
        if label in counts:
            counts[label] += 1
            bp[label] += length
    row.update(n_contigs=len(labels), contig_bp=total, n_plasmid_contigs=counts["PLASMID"],
               n_chromosome_contigs=counts["CHROMOSOME"], n_ambiguous=counts["AMBIGUOUS"],
               n_unplaced=counts["UNPLACED"], n_chimeric=counts["CHIMERIC"], chimeric_bp=bp["CHIMERIC"],
               unplaced_fraction=_frac(bp["UNPLACED"], total), chimeric_fraction=_frac(bp["CHIMERIC"], total))
    if lengths_from_fasta is None and lengths:
        row["assembly_n50"] = n50(lengths)
        row["assembly_total_length"] = total
    if coverage_path and os.path.isfile(coverage_path):
        try:
            cov = _read_tsv(coverage_path)
            truth_bp = sum(_int(r.get("length")) for r in cov)
            covered = sum(min(_int(r.get("assembly_covered_bp")), _int(r.get("length"))) for r in cov)
            row["truth_plasmid_bp"] = truth_bp
            row["assembly_covered_plasmid_bp"] = covered
            if truth_bp > 0:
                adequacy = covered / truth_bp
                row["plasmid_adequacy"] = f"{adequacy:.4f}"
                row["adequate"] = "yes" if adequacy >= min_adequacy else "no"
            else:
                reasons.append("no plasmid in truth")
        except Exception as exc:
            reasons.append(f"assembly coverage unreadable: {exc}")
    else:
        reasons.append("assembly coverage file missing")
    row["reason"] = "; ".join(reasons)
    return row


def write_rows(rows, out):
    with open(out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def cmd_sample(args):
    row = adequacy_row(args.sample, args.contig_labels, args.assembly_coverage, args.contigs_fasta, args.min_adequacy)
    write_rows([row], args.out)
    return 0


def cmd_merge(args):
    rows = []
    for name in sorted(os.listdir(args.data_dir)):
        d = os.path.join(args.data_dir, name)
        if not os.path.isdir(d):
            continue
        fasta = os.path.join(d, "contigs.fasta")
        rows.append(adequacy_row(name, os.path.join(d, "contig_labels.tsv"),
                                 os.path.join(d, "plasmid_assembly_coverage.tsv"),
                                 fasta if os.path.isfile(fasta) else None, args.min_adequacy))
    write_rows(rows, args.out)
    sys.stderr.write(f"[assembly_adequacy] {len(rows)} sample(s) -> {args.out}\n")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "merge":
        ap = argparse.ArgumentParser(prog="assembly_adequacy.py merge")
        ap.add_argument("--data-dir", required=True)
        ap.add_argument("--out", required=True)
        ap.add_argument("--min-adequacy", type=float, default=0.90)
        return cmd_merge(ap.parse_args(argv[1:]))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", required=True)
    ap.add_argument("--contig-labels")
    ap.add_argument("--assembly-coverage")
    ap.add_argument("--contigs-fasta")
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-adequacy", type=float, default=0.90)
    return cmd_sample(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
