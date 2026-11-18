#!/usr/bin/env python3
"""SYNTHETIC short-read QC and assembly-candidate tables for the six isolates of the offline demonstration. Never for real data.

The offline demo (test/run_demo.sh) fabricates its sequences and scores and has no reads, so the pipeline's QC gate and assembly selection
have nothing to measure. So that the report's QC panel can be shown, this writes the same files the pipeline writes, from fixed hand-written
figures (deterministic: no random numbers, the same bytes every time), with a spread of PASS, WARN and REJECT:

  short_read_qc.tsv            the columns of python/short_read_qc.py; the decision and its reasons are decided by that module's own
                               rule (short_read_qc.decide) against config/short_read_qc_thresholds.tsv, so they follow from the figures
  short_read_qc_status.tsv     the action per sample, as the merge step writes it (mode report)
  assembly_candidates.tsv      the columns of python/assembly_selection.py; eligibility and the choice use that module's rule
  short_read_qc.provenance.json  {"synthetic": true, ...}: the report reads this and labels the panel synthetic

It refuses (writes nothing, exit 2) unless the sample sheet exists and EVERY sample in it is marked synthetic (python/data_nature.py), and it
will not replace a QC table that is not its own. Nothing here is a measurement of any read set.

  make_demo_readqc.py --results-dir results_demo --sample-sheet results_demo/samples.tsv
"""
import argparse
import json
import os
import sys

import assembly_selection as asel
import data_nature
import short_read_qc as qcmod

HERE = os.path.dirname(os.path.abspath(__file__))
TAB, NL = chr(9), chr(10)
GENERATOR = "python/make_demo_readqc.py"

# sample -> (read pairs, pairs basis, read length, genome Mb, genome size given?, mean Phred, Q30, GC %, duplication, adapter, N fraction)
READS = {
    "ecoli_a":  (2450000, "exact",     150, 5.1, True,  35.8, 0.913, 50.7, 0.021, 0.004, 0.0003),
    "ecoli_b":  (1980000, "exact",     150, 5.1, True,  34.9, 0.884, 50.6, 0.034, 0.142, 0.0004),   # adapter share above the warn limit
    "kpneu_a":  (3100000, "estimated", 151, 5.4, True,  36.1, 0.931, 57.2, 0.034, 0.011, 0.0002),
    "kpneu_b":  (780000,  "exact",     150, 5.4, True,  29.4, 0.712, 57.0, 0.122, 0.020, 0.0011),   # Q30 below the warn limit
    "abauma_a": (1420000, "exact",     150, 4.0, True,  33.9, 0.842, 39.0, 0.051, 0.018, 0.0006),
    "abauma_b": (48000,   "exact",     150, 5.0, False, 26.5, 0.618, 39.2, 0.087, 0.009, 0.0031),   # too few pairs, depth and quality: rejected
}

# sample -> {assembler: (contigs, total bp, N50, L50, largest, GC %, bp in >=1 kb, bp in >=10 kb, share of reads mapping)}
ASSEMBLIES = {
    "ecoli_a":  {"spades": (92, 5214330, 211904, 8, 512730, 50.62, 5170214, 5008112, 0.991), "unicycler": (14, 5198012, 4731226, 1, 4731226, 50.61, 5198012, 5198012, 0.990),
                 "megahit": (181, 5167550, 96410, 18, 287901, 50.60, 5042115, 4730004, 0.984)},
    "ecoli_b":  {"spades": (121, 5309764, 168337, 11, 401220, 50.55, 5240017, 5011893, 0.987), "unicycler": (23, 5288410, 3920155, 1, 3920155, 50.54, 5288410, 5262877, 0.986),
                 "megahit": (240, 5251730, 72544, 21, 233118, 50.51, 5104420, 4660218, 0.979)},
    "kpneu_a":  {"spades": (68, 5658201, 301442, 6, 744180, 57.31, 5631207, 5502341, 0.993), "unicycler": (11, 5641007, 5107733, 1, 5107733, 57.30, 5641007, 5641007, 0.992),
                 "megahit": (133, 5610872, 132905, 14, 361224, 57.28, 5540112, 5301770, 0.988)},
    "kpneu_b":  {"spades": (412, 5701144, 41210, 38, 160812, 57.12, 5483302, 4620114, 0.931), "unicycler": (97, 5688430, 188221, 9, 502006, 57.10, 5640118, 5412880, 0.927),
                 "megahit": (655, 10408221, 18314, 94, 80122, 56.40, 9811004, 7120886, 0.884)},   # total length over 10 Mb: not eligible
    "abauma_a": {"spades": (74, 4062218, 189004, 7, 391877, 39.07, 4031120, 3920145, 0.978), "unicycler": (19, 4049871, 2984120, 1, 2984120, 39.06, 4049871, 4049871, 0.977),
                 "megahit": (141, 4011003, 88112, 15, 244003, 39.01, 3921556, 3702118, 0.969)},
    "abauma_b": {"spades": (958, 3920114, 9022, 121, 48113, 38.84, 3411208, 1802217, 0.711), "unicycler": (214, 4001552, 33406, 36, 121984, 38.90, 3822104, 3002110, 0.834),
                 "megahit": (1320, 3790220, 5314, 188, 30112, 38.70, 3022110, 981004, 0.690)},    # the poor read set gives a poor assembly: spades lacks read support
}
POLICY, PRIMARY = "quality", "spades"


def fmt(value):
    return qcmod.fmt(value)


def qc_rows(thresholds_path):
    thresholds, policy, sha = qcmod.read_thresholds(thresholds_path)
    rows = []
    for sample, (pairs, basis, length, genome, given, q, q30, gc, dup, ada, nfrac) in READS.items():
        bases = pairs * 2 * length
        m = {"integrity": "ok", "read_pairs_total": pairs, "read_pairs": pairs, "estimated_depth_x": round(bases / (genome * 1e6), 2), "mean_quality": q,
             "q30_fraction": q30, "median_read_length": length, "adapter_fraction": ada, "duplication_fraction": dup, "n_fraction": nfrac,
             "pair_mismatch_fraction": 0.0, "gc_deviation": None}
        status, reasons = qcmod.decide(m, thresholds)
        rows.append({
            "sample": sample, "qc_status": status, "reasons": "; ".join(reasons), "integrity": "ok", "read_pairs_sampled": min(pairs, 200000), "read_pairs_total": pairs,
            "pairs_basis": basis, "estimated_bases": bases, "estimated_depth_x": m["estimated_depth_x"], "genome_size_mb": genome, "genome_size_assumed": "no" if given else "yes",
            "r1_median_length": length, "r2_median_length": length, "median_read_length": length, "mean_quality": q, "q20_fraction": round(min(0.999, q30 + 0.05), 3),
            "q30_fraction": q30, "gc_percent": gc, "n_fraction": nfrac, "adapter_fraction": ada, "duplication_fraction": dup, "pair_mismatch_fraction": 0,
            "gc_deviation": "", "contamination_screen": "not_evaluated", "policy_status": policy, "thresholds_sha": sha})
    return rows


def candidate_rows(min_mb=1.0, max_mb=10.0, min_mapped=0.80):
    out = []
    for sample, assemblers in ASSEMBLIES.items():
        rows = []
        for name, (n, total, n50, l50, largest, gc, b1, b10, mapped) in assemblers.items():
            reasons = []
            if total < min_mb * 1e6:
                reasons.append(f"total length {total / 1e6:.2f} Mb < {min_mb:g} Mb")
            if total > max_mb * 1e6:
                reasons.append(f"total length {total / 1e6:.2f} Mb > {max_mb:g} Mb")
            if mapped < min_mapped:
                reasons.append(f"read support {mapped:.2f} < {min_mapped:g}")
            rows.append({"sample": sample, "assembler": name, "path": f"synthetic/{sample}/{name}/contigs.fasta", "eligible": "no" if reasons else "yes",
                         "reasons": "; ".join(reasons), "n_contigs": n, "total_length": total, "n50": n50, "l50": l50, "largest_contig": largest, "gc_percent": f"{gc:.2f}",
                         "bp_ge_1kb": b1, "bp_ge_10kb": b10, "mapped_read_fraction": f"{mapped:.4f}"})
        chosen, reason = asel.select(rows, POLICY, PRIMARY)
        for r in rows:
            r["selected"] = "yes" if r["assembler"] == chosen else "no"
            r["selection_reason"] = reason if r["assembler"] == chosen or chosen is None else ""
            r["policy"], r["primary"] = POLICY, PRIMARY
        out.extend(rows)
    return out


def status_rows(rows):
    return [{"sample": r["sample"], "qc_status": r["qc_status"], "reasons": r["reasons"],
             "action": "proceeded (flagged)" if r["qc_status"] in ("WARN", "REJECT") else "proceeded"} for r in rows]


def write_tsv(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        handle.write(TAB.join(fields) + NL)
        for r in rows:
            handle.write(TAB.join(fmt(r.get(k, "")) if not isinstance(r.get(k, ""), str) else r.get(k, "").replace(TAB, " ") for k in fields) + NL)


def refusal(results_dir, sheet_path):
    """A reason this must not run, or ''. Real samples, an unreadable sheet or someone else's QC table all refuse."""
    sheet = data_nature.read_sheet(sheet_path)
    if not sheet:
        return f"no readable sample sheet at {sheet_path}: cannot show that every sample is synthetic"
    real = sorted(s for s, row in sheet.items() if not data_nature.is_synthetic(row))
    if real:
        return "the sample sheet has samples that are not marked synthetic (" + ", ".join(real[:5]) + "): synthetic QC is never written beside real data"
    if not set(READS) & set(sheet):
        return "none of the sample ids in the sheet is a demo isolate"
    existing = os.path.join(results_dir, "short_read_qc.tsv")
    marker = os.path.join(results_dir, "short_read_qc.provenance.json")
    if os.path.exists(existing) and not os.path.exists(marker):
        return f"{existing} exists and was not written by this generator: it is not replaced"
    return ""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--results-dir", required=True)
    ap.add_argument("--sample-sheet", required=True)
    ap.add_argument("--thresholds", default=qcmod.DEFAULT_THRESHOLDS)
    a = ap.parse_args(argv)
    why = refusal(a.results_dir, a.sample_sheet)
    if why:
        print(f"make_demo_readqc: refused: {why}", file=sys.stderr)
        return 2
    sheet = data_nature.read_sheet(a.sample_sheet)
    keep = set(sheet)
    rows = [r for r in qc_rows(a.thresholds) if r["sample"] in keep]
    cands = [r for r in candidate_rows() if r["sample"] in keep]
    os.makedirs(a.results_dir, exist_ok=True)
    write_tsv(os.path.join(a.results_dir, "short_read_qc.tsv"), qcmod.FIELDS, rows)
    write_tsv(os.path.join(a.results_dir, "short_read_qc_status.tsv"), qcmod.STATUS_FIELDS, status_rows(rows))
    write_tsv(os.path.join(a.results_dir, "assembly_candidates.tsv"), asel.FIELDS, cands)
    with open(os.path.join(a.results_dir, "short_read_qc.provenance.json"), "w", encoding="utf-8") as handle:
        json.dump({"synthetic": True, "generator": GENERATOR, "note": "Fabricated for the offline demonstration; no reads were measured.",
                   "samples": [r["sample"] for r in rows]}, handle, indent=1, sort_keys=True)
        handle.write(NL)
    counts = {k: sum(1 for r in rows if r["qc_status"] == k) for k in ("PASS", "WARN", "REJECT")}
    print(f"make_demo_readqc: wrote SYNTHETIC QC for {len(rows)} demo isolates ({counts['PASS']} PASS, {counts['WARN']} WARN, {counts['REJECT']} REJECT) and "
          f"{len(cands)} assembly candidates to {a.results_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
