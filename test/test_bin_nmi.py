#!/usr/bin/env python3
"""Regression for score_bins.py's clustering_agreement(): NMI and Variation
of Information (VI) over a deliberately scoped bp-weighted contingency table
(predicted bins x {true plasmids, CHROMOSOME}, including an "__unassigned__"
row for missed plasmid bp -- see the function's own docstring for why).
Supplementary to bin_f1/split_events/merge_events, never a replacement.

Three hand-computed cases (natural-log entropy, arithmetic-mean NMI
normalization -- matching scikit-learn's normalized_mutual_info_score
convention so a reader can cross-check against a familiar implementation):

  1. Perfect match (one bin, one plasmid, no contamination, nothing missed):
     both sides are a single point mass (H=0) -> NMI=1.0, VI=0.0 by this
     file's own documented zero-entropy convention.
  2. Independent (2 bins each split evenly across 2 plasmids): the joint
     distribution factors exactly as p(row)*p(col) -> mutual information is
     exactly 0 -> NMI=0.0, VI=2*ln(2).
  3. Over-merged (one bin claims BOTH plasmids entirely): row entropy
     collapses to 0 (only one bin exists) -> NMI=0.0 by the same convention
     as case 2, but VI=ln(2) -- strictly better (lower) than case 2's
     2*ln(2) and strictly worse than case 1's 0.0. This is exactly why both
     metrics are reported together: NMI alone cannot distinguish "truly
     independent" from "one giant merged bin" (both hit the same zero-
     entropy shortcut), but VI's unnormalized scale does.
"""

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))

from score_bins import clustering_agreement  # noqa: E402


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


def main():
    ok = True

    # --- Case 1: perfect match. ---
    overlaps = {("bin1", "p1"): 1000}
    plasmids = {"p1": 1000}
    chromosome_bp = {}
    all_bins = {"bin1"}
    nmi, vi = clustering_agreement(overlaps, plasmids, chromosome_bp, all_bins)
    ok &= (nmi is not None and approx(nmi, 1.0) and approx(vi, 0.0))
    print(f"  perfect match -> NMI=1.0, VI=0.0 ? nmi={nmi} vi={vi} -> "
          f"{nmi is not None and approx(nmi, 1.0) and approx(vi, 0.0)}")

    # --- Case 2: independent (no mutual information). ---
    overlaps = {("bin1", "p1"): 500, ("bin1", "p2"): 500,
                ("bin2", "p1"): 500, ("bin2", "p2"): 500}
    plasmids = {"p1": 1000, "p2": 1000}
    chromosome_bp = {}
    all_bins = {"bin1", "bin2"}
    nmi, vi = clustering_agreement(overlaps, plasmids, chromosome_bp, all_bins)
    expected_vi = 2 * math.log(2)
    ok &= (approx(nmi, 0.0) and approx(vi, expected_vi))
    print(f"  independent (evenly split) -> NMI=0.0, VI=2ln(2)={expected_vi:.4f} ? "
          f"nmi={nmi} vi={vi} -> {approx(nmi, 0.0) and approx(vi, expected_vi)}")

    # --- Case 3: over-merged (one bin claims both plasmids entirely). ---
    overlaps = {("bin1", "p1"): 1000, ("bin1", "p2"): 1000}
    plasmids = {"p1": 1000, "p2": 1000}
    chromosome_bp = {}
    all_bins = {"bin1"}
    nmi_merged, vi_merged = clustering_agreement(overlaps, plasmids, chromosome_bp, all_bins)
    expected_vi_merged = math.log(2)
    ok &= (approx(nmi_merged, 0.0) and approx(vi_merged, expected_vi_merged))
    print(f"  over-merged bin -> NMI=0.0, VI=ln(2)={expected_vi_merged:.4f} ? "
          f"nmi={nmi_merged} vi={vi_merged} -> "
          f"{approx(nmi_merged, 0.0) and approx(vi_merged, expected_vi_merged)}")

    # --- VI (not NMI) is what actually distinguishes "over-merged" from
    # "truly independent" -- both hit NMI=0.0 via the same zero-entropy
    # convention, but merging is a smaller information loss than genuine
    # independence, and only VI's unnormalized scale shows that ordering. ---
    ok &= (0.0 < vi_merged < expected_vi)
    print(f"  VI orders merged as better than independent, worse than perfect ? "
          f"0.0 < {vi_merged:.4f} < {expected_vi:.4f} -> {0.0 < vi_merged < expected_vi}")

    # --- An empty contingency table (no true plasmid bp, nothing wrongly
    # claimed as plasmid) is undefined, never a fabricated 0/1. ---
    nmi_empty, vi_empty = clustering_agreement({}, {}, {}, set())
    ok &= (nmi_empty is None and vi_empty is None)
    print(f"  empty contingency table -> (None, None), never fabricated ? "
          f"{(nmi_empty, vi_empty)} -> {nmi_empty is None and vi_empty is None}")

    print("\nALL BIN NMI/VI TESTS PASSED" if ok else "\nTESTS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
