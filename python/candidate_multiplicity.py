#!/usr/bin/env python3
"""Candidate multiplicity and redundancy: what happens when a tool reports several sequences for one plasmid.

A tool may output more than one record that looks like the same reference plasmid: fragments of it, near-duplicates,
alternative reconstructions, a record that also carries chromosome or another plasmid, or records that match nothing. Scoring
only the best hit would hide all of that, and adding the candidates up would count shared sequence twice. This module accounts for
EVERY predicted record and, for every truth plasmid, separates three quantities:

  best-candidate coverage     the share of the plasmid the single best candidate covers
  combined coverage           the share covered by the UNION of all candidates' alignments (reference bases counted once; this is
                              the same union the base-level recall uses)
  redundancy                  candidate-aligned bases on the plasmid that other candidates already cover
                              (sum of each candidate's own coverage minus the union), and its share of that sum

and labels each candidate relative to the others (relationship):

  primary                   the candidate covering most of its plasmid
  complementary_fragment    covers reference the primary does not (new bases >= --new-fraction of its own aligned bases)
  redundant                 almost nothing new (duplicate or alternative reconstruction: alignment shows the overlap, not which)
  chimeric                  at least two reference replicons each carry >= --chimera-min-bp and >= --chimera-fraction of its
                            aligned bases (plasmid + chromosome, or two plasmids)
  off_target                most of its aligned bases land on chromosome
  unmapped                  no retained alignment

Everything here is descriptive: it never changes scores.tsv, a rank or the primary endpoint. A tool cannot raise its primary score
by emitting more candidates, and this table is where the extra output shows up. Alignment filters are the scorer's own (it reuses
score_plasmids.parse_paf_intervals), so the candidates are the records the score used. Standard library only.

  candidate_multiplicity.py --truth truth.tsv --paf pred_vs_ref.paf --pred-fasta pred.fasta --sample S --tool T \\
      --out-plasmids T.multiplicity.tsv --out-candidates T.multiplicity_candidates.tsv
"""
import argparse
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import score_plasmids as sp  # noqa: E402
from plasbench_common import read_truth_table  # noqa: E402

PLASMID_FIELDS = ["sample", "tool", "plasmid", "plasmid_length", "outcome", "n_candidates", "n_touching", "best_candidate",
                  "best_candidate_coverage", "combined_coverage", "coverage_gain", "redundant_bp", "redundancy_fraction",
                  "n_fragments", "n_redundant", "n_chimeric_touching", "candidate_bp_to_union_ratio"]
CANDIDATE_FIELDS = ["sample", "tool", "candidate", "length", "aligned_bp", "mapped_fraction", "home_plasmid", "home_share",
                    "plasmid_bp", "chromosome_bp", "relationship", "chimeric_with", "new_bp_on_home", "coverage_of_home"]
INTERVAL_FIELDS = ["sample", "tool", "plasmid", "plasmid_length", "candidate", "start", "end", "relationship"]
TAB, NL = chr(9), chr(10)


def merged_bp(intervals):
    merged = sp.merge_intervals([tuple(i) for i in intervals])[0]
    return merged, sum(e - s for s, e in merged)


def new_bp(intervals, union):
    """Bases of `intervals` (merged) not already in `union` (merged, sorted)."""
    merged, total = merged_bp(intervals)
    return total - sp.overlap_bp(merged, union) if union else total


def analyse(truth, covered_by_query, pred_lengths, sample="", tool="", new_fraction=0.10, chimera_min_bp=1000,
            chimera_fraction=0.10, min_home_share=0.5):
    """Return (plasmid_rows, candidate_rows, interval_rows). The intervals are each candidate's merged alignment on each plasmid
    it touches (0-based, half-open), for drawing the candidates against the reference."""
    per = defaultdict(lambda: defaultdict(list))                 # candidate -> target -> intervals
    for target, items in covered_by_query.items():
        for query, start, end in items:
            per[query][target].append((start, end))
    cands = {}
    for q, length in pred_lengths.items():
        targets = {t: merged_bp(iv) for t, iv in per.get(q, {}).items()}
        aligned = min(length, sum(bp for _, bp in targets.values()))
        plasmid_bp = sum(bp for t, (_, bp) in targets.items() if truth[t][0] == "PLASMID")
        chrom_bp = sum(bp for t, (_, bp) in targets.items() if truth[t][0] == "CHROMOSOME")
        plasmid_targets = {t: bp for t, (_, bp) in targets.items() if truth[t][0] == "PLASMID"}
        home = max(sorted(plasmid_targets), key=lambda t: plasmid_targets[t]) if plasmid_targets else ""
        big = [t for t, (_, bp) in sorted(targets.items())
               if bp >= chimera_min_bp and aligned and bp / aligned >= chimera_fraction]
        cands[q] = {"length": length, "targets": targets, "aligned": aligned, "plasmid_bp": plasmid_bp, "chrom_bp": chrom_bp,
                    "home": home, "home_bp": plasmid_targets.get(home, 0), "chimeric_with": big if len(big) >= 2 else [],
                    "relationship": ""}
        if aligned == 0:
            cands[q]["relationship"] = "unmapped"
        elif chrom_bp > plasmid_bp:
            cands[q]["relationship"] = "off_target"
        elif len(big) >= 2:
            cands[q]["relationship"] = "chimeric"

    plasmids = sorted(t for t, (mol, _) in truth.items() if mol == "PLASMID")
    plasmid_rows, spans = [], []
    for plasmid in plasmids:
        length = truth[plasmid][1]
        members, touching = [], []
        for q, c in cands.items():
            if plasmid in c["targets"]:
                touching.append(q)
            if c["home"] == plasmid and c["aligned"] and c["home_bp"] / c["aligned"] >= min_home_share and c["relationship"] not in (
                    "unmapped", "off_target", "chimeric"):
                members.append(q)
        union, union_bp = merged_bp([iv for q in touching for iv in per[q][plasmid]])
        own = {q: merged_bp(per[q][plasmid]) for q in touching}
        spans.extend((plasmid, length, q, s, e) for q in touching for s, e in own[q][0])
        order = sorted(members, key=lambda q: (-own[q][1], q))
        # candidate-aligned bases on this plasmid, counted per candidate; the surplus over the union is the redundancy
        total_own = sum(own[q][1] for q in touching)
        redundant_bp = total_own - union_bp
        seen, n_frag, n_red = [], 0, 0
        for rank, q in enumerate(order):
            fresh = new_bp(per[q][plasmid], seen)
            c = cands[q]
            c["new_bp_on_home"] = fresh
            c["coverage_of_home"] = own[q][1] / length
            if rank == 0:
                rel = "primary"
            elif own[q][1] and fresh / own[q][1] < new_fraction:
                rel = "redundant"
                n_red += 1
            else:
                rel = "complementary_fragment"
                n_frag += 1
            if not c["relationship"]:
                c["relationship"] = rel
            seen = merged_bp(seen + per[q][plasmid])[0]
        n_chim = sum(1 for q in touching if cands[q]["relationship"] == "chimeric")
        if not touching:
            outcome = "missed"
        elif len(members) <= 1 and not n_red and not n_frag:
            outcome = "single" if members else "carried_only_in_other_candidates"
        elif n_frag and n_red:
            outcome = "fragmented_and_duplicated"
        elif n_frag:
            outcome = "fragmented"
        elif n_red:
            outcome = "duplicated"
        else:
            outcome = "single"
        best = order[0] if order else (max(sorted(touching), key=lambda q: own[q][1]) if touching else "")
        best_bp = own[best][1] if best else 0
        plasmid_rows.append({
            "sample": sample, "tool": tool, "plasmid": plasmid, "plasmid_length": length, "outcome": outcome,
            "n_candidates": len(members), "n_touching": len(touching), "best_candidate": best,
            "best_candidate_coverage": best_bp / length, "combined_coverage": union_bp / length,
            "coverage_gain": (union_bp - best_bp) / length, "redundant_bp": redundant_bp,
            "redundancy_fraction": redundant_bp / total_own if total_own else 0.0, "n_fragments": n_frag,
            "n_redundant": n_red, "n_chimeric_touching": n_chim,
            "candidate_bp_to_union_ratio": total_own / union_bp if union_bp else 0.0})
    candidate_rows = []
    for q in sorted(cands):
        c = cands[q]
        candidate_rows.append({
            "sample": sample, "tool": tool, "candidate": q, "length": c["length"], "aligned_bp": c["aligned"],
            "mapped_fraction": c["aligned"] / c["length"] if c["length"] else 0.0, "home_plasmid": c["home"],
            "home_share": c["home_bp"] / c["aligned"] if c["aligned"] else 0.0, "plasmid_bp": c["plasmid_bp"],
            "chromosome_bp": c["chrom_bp"], "relationship": c["relationship"] or "other_plasmid_part",
            "chimeric_with": ",".join(c["chimeric_with"]), "new_bp_on_home": c.get("new_bp_on_home", 0),
            "coverage_of_home": c.get("coverage_of_home", 0.0)})
    interval_rows = [{"sample": sample, "tool": tool, "plasmid": p, "plasmid_length": n, "candidate": q, "start": s, "end": e,
                      "relationship": cands[q]["relationship"] or "other_plasmid_part"} for p, n, q, s, e in spans]
    return plasmid_rows, candidate_rows, interval_rows


def fmt(value):
    return f"{value:.6f}" if isinstance(value, float) else str(value)


def write(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        handle.write(TAB.join(fields) + NL)
        for r in rows:
            handle.write(TAB.join(fmt(r[f]) for f in fields) + NL)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--truth", required=True)
    ap.add_argument("--paf", required=True)
    ap.add_argument("--pred-fasta", required=True)
    ap.add_argument("--sample", default="")
    ap.add_argument("--tool", default="")
    ap.add_argument("--out-plasmids", required=True)
    ap.add_argument("--out-candidates", required=True)
    ap.add_argument("--out-intervals", help="where each candidate lies on each plasmid it touches (for the report's tracks)")
    ap.add_argument("--min-alignment-length", type=int, default=1)
    ap.add_argument("--min-alignment-identity", type=float, default=0.0)
    ap.add_argument("--min-alignment-mapq", type=int, default=0)
    ap.add_argument("--min-alignment-query-coverage", type=float, default=0.0)
    ap.add_argument("--new-fraction", type=float, default=0.10,
                    help="a candidate whose own bases are less than this share new is 'redundant' (default 0.10)")
    ap.add_argument("--chimera-min-bp", type=int, default=1000)
    ap.add_argument("--chimera-fraction", type=float, default=0.10)
    a = ap.parse_args(argv)
    truth = read_truth_table(a.truth)[0]
    lengths = sp.read_fasta_lengths(a.pred_fasta) if os.path.getsize(a.pred_fasta) else {}
    covered_by_query = {}
    if lengths and os.path.getsize(a.paf):
        covered_by_query = sp.parse_paf_intervals(a.paf, truth, lengths, a.min_alignment_length, a.min_alignment_identity,
                                                  a.min_alignment_mapq, a.min_alignment_query_coverage)[5]
    plasmid_rows, candidate_rows, interval_rows = analyse(truth, covered_by_query, lengths, a.sample, a.tool, a.new_fraction, a.chimera_min_bp,
                                           a.chimera_fraction)
    write(a.out_plasmids, PLASMID_FIELDS, plasmid_rows)
    write(a.out_candidates, CANDIDATE_FIELDS, candidate_rows)
    if a.out_intervals:
        write(a.out_intervals, INTERVAL_FIELDS, interval_rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
