#!/usr/bin/env python3
"""A tiny results folder for the facet heatmap and presence matrix tests: six isolates, two tools, a handful of plasmids with known features.

make(root) writes it under `root` (which is both the results and the data folder) and returns the scores.tsv path. Designed so each behaviour has a known answer:
  species E. coli (s1-s4) and K. pneumoniae (s5, s6); depth 20, 50, 80, 150, 40, 120 x; studies A, A, B, B, C, C; reference tier 3 for s1-s5, none for s6
  toolA runs on all six; toolB is not run on s6; toolA has a blank F1 on s3 (not 0)
  plasmids: s1 pA (60 kb, IncFIB, MOBF, blaCTX-M-15), pB (5 kb, ColE1, no AMR); s2 pC (30 kb, truth_features.tsv MISSING for the sample: not annotated, tetA);
            s4 pD (60 kb, IncFIB, MOBF, blaCTX-M-15 and sul1); s5 pE (8 kb, ColE1)
"""
import os
from pathlib import Path


def w(path, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("".join("\t".join(str(c) for c in r) + "\n" for r in rows), encoding="utf-8")


def make(root):
    root = Path(root)
    w(root / "samples.tsv", [["sample_id", "organism", "source_study", "sample_origin", "read_depth_x"]] +
      [[s, o, st, "clinical", d] for s, o, st, d in (("s1", "Escherichia coli", "Study A", 20), ("s2", "Escherichia coli", "Study A", 50),
                                                       ("s3", "Escherichia coli", "Study B", 80), ("s4", "Escherichia coli", "Study B", 150),
                                                       ("s5", "Klebsiella pneumoniae", "Study C", 40), ("s6", "Klebsiella pneumoniae", "Study C", 120))])
    w(root / "benchmark.truth_provenance.tsv", [["sample", "reference_tier"]] + [[f"s{i}", "3"] for i in range(1, 6)])
    head = ["sample", "tool", "analysis_track", "true_plasmid_bp", "true_plasmid_count", "precision", "recall", "f1", "plasmid_recall", "cprr_plasmids", "cprr_correct"]
    rows = [head]
    vals = {("toolA", "s1"): (0.9, 0.8, 0.85, 1.0, 2, 1), ("toolA", "s2"): (0.8, 0.6, 0.69, 0.0, 1, 0), ("toolA", "s3"): (0.7, 0.5, "", 0.0, 1, 0),
            ("toolA", "s4"): (0.95, 0.9, 0.92, 1.0, 1, 1), ("toolA", "s5"): (0.6, 0.4, 0.48, 0.0, 1, 0), ("toolA", "s6"): (0.5, 0.3, 0.38, 0.0, 1, 0),
            ("toolB", "s1"): (0.5, 0.9, 0.64, 1.0, 2, 2), ("toolB", "s2"): (0.4, 0.8, 0.53, 1.0, 1, 1), ("toolB", "s3"): (0.6, 0.7, 0.65, 1.0, 1, 1),
            ("toolB", "s4"): (0.7, 0.95, 0.81, 1.0, 1, 1), ("toolB", "s5"): (0.8, 0.5, 0.62, 0.0, 1, 0)}
    bp = {"s1": 65000, "s2": 30000, "s3": 9000, "s4": 60000, "s5": 8000, "s6": 120000}
    for (tool, s), (p, r, f, pr, n, c) in vals.items():
        rows.append([s, tool, "short_read", bp[s], n, p, r, f, pr, n, c])
    w(root / "scores.tsv", rows)
    w(root / "benchmark.leaderboard.tsv", [["analysis_track", "tool", "rank"], ["short_read", "toolB", "1"], ["short_read", "toolA", "2"]])
    truth = {"s1": [("pA", 60000), ("pB", 5000)], "s2": [("pC", 30000)], "s4": [("pD", 60000)], "s5": [("pE", 8000)]}
    for s, plas in truth.items():
        w(root / s / "truth.tsv", [["sequence_id", "molecule_type", "length"], [f"chr_{s}", "CHROMOSOME", 4000000]] + [[p, "PLASMID", ln] for p, ln in plas])
    w(root / "s1" / "truth_amr.tsv", [["sequence_id", "start", "end", "gene_name"], ["pA", 100, 900, "blaCTX-M-15"]])
    w(root / "s2" / "truth_amr.tsv", [["sequence_id", "start", "end", "gene_name"], ["pC", 100, 900, "tetA"]])
    w(root / "s4" / "truth_amr.tsv", [["sequence_id", "start", "end", "gene_name"], ["pD", 100, 900, "blaCTX-M-15"], ["pD", 2000, 2800, "sul1"]])
    w(root / "s5" / "truth_amr.tsv", [["sequence_id", "start", "end", "gene_name"]])             # annotated, no gene: absent, not "not annotated"
    ft = [["sequence_id", "start", "end", "feature_type", "label"]]
    w(root / "s1" / "truth_features.tsv", ft + [["pA", 0, 9, "replicon", "IncFIB"], ["pA", 10, 20, "mob", "MOBF"], ["pB", 0, 9, "replicon", "ColE1"]])
    w(root / "s4" / "truth_features.tsv", ft + [["pD", 0, 9, "replicon", "IncFIB"], ["pD", 10, 20, "mob", "MOBF"]])
    w(root / "s5" / "truth_features.tsv", ft + [["pE", 0, 9, "replicon", "ColE1"]])
    # s2 has no truth_features.tsv at all: its plasmid is "not annotated" for replicon and MOB blocks
    out = {"toolA": {"s1": [("pA", 1.0, "yes"), ("pB", 0.4, "no")], "s2": [("pC", 0.0, "no")], "s4": [("pD", 1.0, "yes")], "s5": [("pE", 0.95, "no")]},
           "toolB": {"s1": [("pA", 0.5, "no"), ("pB", 1.0, "yes")], "s2": [("pC", 1.0, "yes")], "s4": [("pD", 1.0, "yes")], "s5": [("pE", 0.0, "no")]}}
    for tool, per_sample in out.items():
        for s, items in per_sample.items():
            w(root / s / f"{tool}.per_plasmid.tsv", [["sample", "tool", "analysis_track", "sequence_id", "length", "covered_bp", "completeness", "recovered"]] +
              [[s, tool, "short_read", p, 1, 1, c, 1 if c >= 0.9 else 0] for p, c, _ in items])
            w(root / s / f"{tool}.cprr.tsv", [["true_plasmid", "correct"]] + [[p, ok] for p, _, ok in items])
    return str(root / "scores.tsv")
