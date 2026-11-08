#!/usr/bin/env python3
"""Plasmid copy-number (PCN) concordance: tool-estimated vs truth, descriptive only.

plsMD estimates PCN as sum(len * contig_depth) / plasmid_length; GAEMR-style tables
report per-contig coverage. Reimplemented here for assembly-contig bins:

  tool PCN  = length-weighted mean depth of the matched bin's contigs, divided by the
              length-weighted MEDIAN depth of the assembly's long contigs (>= --min-chrom-length,
              default 10 kb, not in ANY bin) -- the chromosome estimate.
              Depth is parsed from the assembly headers: SPAdes `NODE_1_length_N_cov_X`
              and Unicycler `1 length=N depth=Xx`. Bin member ids are normalised (trailing
              apostrophe, `_R`, `_reverse`, `_rev` suffix stripped) before lookup.
  truth PCN = observed depth of the truth plasmid / length-weighted median depth of the
              CHROMOSOME truth replicons, from a PER-REPLICON depth table (columns
              sequence_id, length, mean_depth: the table written by long_read_support.py,
              truth_long_read_depth.tsv). The pipeline's observed_depth.tsv holds only one
              genome-wide row (reference_bp, read_bases, observed_depth_x) and cannot give a
              per-plasmid depth: with it the status is no_truth_depth.
  log2_ratio = log2(pcn_pred / pcn_truth).

Bin-to-plasmid matches come from --matches (score_bins.py bin_matches.tsv, rows with
match_status == matched) or, alternatively, from --paf (tool contigs vs truth: each bin is
matched to the truth plasmid with the most aligned bases; no one-to-one constraint).

Status: ok | no_depth_headers | no_truth_depth | no_bins |
not_applicable_not_assembly_contigs | no_chromosome_estimate. Standard library only.
"""
import argparse
import csv
import math
import os
import re
import subprocess
import sys
from collections import defaultdict
from statistics import median

FIELDS = ["sample", "tool", "analysis_track", "true_plasmid", "bin_id", "pcn_pred", "pcn_truth", "log2_ratio", "status"]
SPADES = re.compile(r"length_(\d+)_cov_([0-9.eE+-]+)")
UNICYCLER = re.compile(r"length=(\d+)\s+depth=([0-9.eE+-]+)x?")
SUFFIX = re.compile(r"(?:'|_R|_rev|_reverse)$")
FACTOR = 1.5


def normalise_id(name):
    name = name.strip()
    while True:
        new = SUFFIX.sub("", name)
        if new == name:
            return name
        name = new


def parse_header(header):
    """(length, depth) from a SPAdes or Unicycler header line, else None.
    `NODE_1_length_5000_cov_20.5` -> (5000, 20.5); `1 length=5000 depth=1.50x` -> (5000, 1.5)."""
    for pattern in (SPADES, UNICYCLER):
        m = pattern.search(header)
        if m:
            try:
                return int(m.group(1)), float(m.group(2).rstrip("."))
            except ValueError:
                return None
    return None


def read_contigs(path):
    """id -> {length (sequence), depth (None if header has none)}; id = first header token."""
    contigs, cur, length = {}, None, 0
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.startswith(">"):
                if cur:
                    contigs[cur[0]]["length"] = length
                header = line[1:].strip()
                cid = header.split()[0] if header else ""
                parsed = parse_header(header)
                contigs[cid] = {"length": 0, "hlength": parsed[0] if parsed else None,
                                "depth": parsed[1] if parsed else None}
                cur, length = (cid,), 0
            else:
                length += len(line.strip())
    if cur:
        contigs[cur[0]]["length"] = length
    for c in contigs.values():
        if not c["length"] and c["hlength"]:
            c["length"] = c["hlength"]
    return contigs


def lookup(contigs, name):
    if name in contigs:
        return name
    n = normalise_id(name)
    if n in contigs:
        return n
    for cid in contigs:
        if normalise_id(cid) == n:
            return cid
    return None


def weighted_median(pairs):
    """Length-weighted median of (value, weight): smallest value whose cumulative weight >= half.
    [(50, 10000), (10, 1000)] -> 50."""
    pairs = sorted((v, w) for v, w in pairs if w > 0)
    total = sum(w for _, w in pairs)
    if not total:
        return None
    cum = 0
    for v, w in pairs:
        cum += w
        if cum * 2 >= total:
            return v
    return pairs[-1][0]


def read_bins(path):
    bins = defaultdict(list)
    if not path or not os.path.isfile(path):
        return bins
    with open(path, newline="", encoding="utf-8") as handle:
        for r in csv.DictReader(handle, delimiter="\t"):
            if r.get("bin_id") and r.get("sequence_id"):
                bins[r["bin_id"]].append(r["sequence_id"])
    return bins


def matches_from_file(path):
    out = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for r in csv.DictReader(handle, delimiter="\t"):
            if r.get("match_status") == "matched" and r.get("bin_id") and r.get("true_plasmid"):
                out[r["bin_id"]] = r["true_plasmid"]
    return out


def matches_from_paf(path, bins, plasmids):
    member = {}
    for b, seqs in bins.items():
        for s in seqs:
            member[s] = b
            member[normalise_id(s)] = b
    bp = defaultdict(int)
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            f = line.rstrip("\n").split("\t")
            if len(f) < 12 or f[5] not in plasmids:
                continue
            b = member.get(f[0]) or member.get(normalise_id(f[0]))
            if b:
                bp[(b, f[5])] += abs(int(f[3]) - int(f[2]))
    best = {}
    for (b, p), n in bp.items():
        if n > 0 and (b not in best or n > best[b][1] or (n == best[b][1] and p < best[b][0])):
            best[b] = (p, n)
    return {b: p for b, (p, _) in best.items()}


def read_truth_types(path):
    types = {}
    if path and os.path.isfile(path):
        with open(path, newline="", encoding="utf-8") as handle:
            for r in csv.DictReader(handle, delimiter="\t"):
                types[r["sequence_id"]] = (r["molecule_type"].upper(), int(r["length"]))
    return types


def truth_pcn(truth_path, depth_path):
    """{plasmid: pcn_truth} from a per-replicon depth table; {} if unavailable."""
    types = read_truth_types(truth_path)
    if not depth_path or not os.path.isfile(depth_path) or not types:
        return {}
    with open(depth_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        cols = reader.fieldnames or []
        if "sequence_id" not in cols or "mean_depth" not in cols:
            return {}  # e.g. observed_depth.tsv: genome-wide only
        depth = {}
        for r in reader:
            try:
                depth[r["sequence_id"]] = float(r["mean_depth"])
            except (TypeError, ValueError):
                pass
    chrom = weighted_median([(depth[s], types[s][1]) for s in depth if s in types and types[s][0] == "CHROMOSOME"])
    if not chrom:
        return {}
    return {s: depth[s] / chrom for s in depth if s in types and types[s][0] == "PLASMID"}


def compute_rows(sample, tool, track, truth, bins_path, contigs_path, truth_depth, paf=None, matches=None,
                 min_chrom_length=10000):
    def row(plasmid="", bin_id="", pred="", tru="", status="ok"):
        ratio = ""
        if pred != "" and tru not in ("", 0):
            ratio = f"{math.log2(pred / tru):.4f}"
        fmt = lambda v: f"{v:.4f}" if v != "" else ""
        return {"sample": sample, "tool": tool, "analysis_track": track, "true_plasmid": plasmid,
                "bin_id": bin_id, "pcn_pred": fmt(pred), "pcn_truth": fmt(tru), "log2_ratio": ratio, "status": status}

    bins = read_bins(bins_path)
    if not bins:
        return [row(status="no_bins")]
    if not contigs_path or not os.path.isfile(contigs_path):
        return [row(status="not_applicable_not_assembly_contigs")]
    contigs = read_contigs(contigs_path)
    resolved = {b: [lookup(contigs, s) for s in seqs] for b, seqs in bins.items()}
    if not any(c for cs in resolved.values() for c in cs):
        return [row(status="not_applicable_not_assembly_contigs")]
    plasmids = read_truth_types(truth)
    plasmids = {k for k, v in plasmids.items() if v[0] == "PLASMID"}
    if matches and os.path.isfile(matches):
        matched = matches_from_file(matches)
    elif paf and os.path.isfile(paf):
        matched = matches_from_paf(paf, bins, plasmids)
    else:
        matched = {}
    if not matched:
        return []
    binned = {c for cs in resolved.values() for c in cs if c}
    chrom = weighted_median([(c["depth"], c["length"]) for cid, c in contigs.items()
                             if cid not in binned and c["length"] >= min_chrom_length and c["depth"] is not None])
    tpcn = truth_pcn(truth, truth_depth)
    rows = []
    for bin_id in sorted(matched):
        plasmid = matched[bin_id]
        members = [contigs[c] for c in resolved.get(bin_id, []) if c and contigs[c]["depth"] is not None]
        total = sum(m["length"] for m in members)
        if not members or not total:
            rows.append(row(plasmid, bin_id, status="no_depth_headers"))
            continue
        mean = sum(m["length"] * m["depth"] for m in members) / total
        if not chrom:
            rows.append(row(plasmid, bin_id, status="no_chromosome_estimate"))
            continue
        pred = mean / chrom
        if plasmid not in tpcn:
            rows.append(row(plasmid, bin_id, pred, "", "no_truth_depth"))
            continue
        rows.append(row(plasmid, bin_id, pred, tpcn[plasmid]))
    return rows


def summarize(rows):
    """Per tool: n (status ok), median |log2_ratio|, fraction within a factor of 1.5. Descriptive only."""
    by_tool = defaultdict(list)
    for r in rows:
        if r.get("status") == "ok" and r.get("log2_ratio") not in ("", None):
            by_tool[r["tool"]].append(abs(float(r["log2_ratio"])))
    limit = math.log2(FACTOR)
    return {t: {"n": len(v), "median_abs_log2_ratio": median(v),
                "fraction_within_1.5x": sum(1 for x in v if x <= limit + 1e-12) / len(v)}
            for t, v in sorted(by_tool.items())}


def write_rows(rows, out):
    with open(out, "w", newline="", encoding="utf-8") as handle:
        w = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "merge":
        ap = argparse.ArgumentParser(prog="copy_number.py merge")
        ap.add_argument("--results-dir", required=True)
        ap.add_argument("--out", required=True)
        a = ap.parse_args(argv[1:])
        here = os.path.dirname(os.path.abspath(__file__))
        return subprocess.call([sys.executable, os.path.join(here, "merge_tables.py"), "--results-dir", a.results_dir,
                                "--suffix", ".copy_number.tsv", "--out", a.out])
    if argv and argv[0] == "summary":
        ap = argparse.ArgumentParser(prog="copy_number.py summary")
        ap.add_argument("--table", required=True)
        a = ap.parse_args(argv[1:])
        with open(a.table, newline="", encoding="utf-8") as handle:
            res = summarize(list(csv.DictReader(handle, delimiter="\t")))
        print("tool\tn\tmedian_abs_log2_ratio\tfraction_within_1.5x")
        for t, s in res.items():
            print(f"{t}\t{s['n']}\t{s['median_abs_log2_ratio']:.4f}\t{s['fraction_within_1.5x']:.4f}")
        return 0
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--bins", required=True)
    ap.add_argument("--paf")
    ap.add_argument("--matches")
    ap.add_argument("--contigs-fasta")
    ap.add_argument("--truth-depth")
    ap.add_argument("--sample", required=True)
    ap.add_argument("--tool", required=True)
    ap.add_argument("--analysis-track", default="short_read")
    ap.add_argument("--min-chrom-length", type=int, default=10000)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    rows = compute_rows(a.sample, a.tool, a.analysis_track, a.truth, a.bins, a.contigs_fasta, a.truth_depth,
                        a.paf, a.matches, a.min_chrom_length)
    write_rows(rows, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
