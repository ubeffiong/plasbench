#!/usr/bin/env python3
"""Boundary and numeric tests for guard conditions that mutation testing showed were unprotected (audit AU-022).

Mutants that survived: the CPRR `>=` turned into `>`, the Holm step-down and multiplier, the minimum-identity comparison. Each assertion below is a hand-computed value."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
from aggregate_results import holm_adjust  # noqa: E402
from score_bins import correct_reconstruction  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


# Holm: p = 0.01, 0.04, 0.03, 0.20 -> sorted 0.01 (x4), 0.03 (x3), 0.04 (x2), 0.20 (x1) = 0.04, 0.09, 0.08 -> monotone 0.09, 0.20 -> 0.20
got = holm_adjust([0.01, 0.04, 0.03, 0.20])
want = [0.04, 0.09, 0.09, 0.20]
check("Holm adjusts 0.01/0.04/0.03/0.20 to 0.04/0.09/0.09/0.20 (multiplier m-rank, running maximum)", all(abs(a - b) < 1e-12 for a, b in zip(got, want)), got)
check("Holm never exceeds 1", holm_adjust([0.6, 0.9]) == [1.0, 1.0], holm_adjust([0.6, 0.9]))
check("Holm keeps a missing p-value missing and does not count it", holm_adjust([0.02, None, 0.04]) == [0.04, None, 0.04], holm_adjust([0.02, None, 0.04]))


# CPRR: exactly at each threshold passes, one base under fails
def verdict(coverage_bp, share_bp, matches):
    plasmids = {"p": 1000}
    matched = [("b", "p", coverage_bp)]
    rows = correct_reconstruction(matched, {("b", "p"): coverage_bp}, plasmids, {"b": share_bp}, {("b", "p"): (matches, 1000)}, {"p": {"b"}}, 0.8, 0.8, 0.9)
    return rows[0]["correct"]


check("CPRR passes exactly at coverage 0.8, share 0.8 and identity 0.9 (>=, not >)", verdict(800, 1000, 900) == "yes", verdict(800, 1000, 900))
check("CPRR fails one base under the coverage threshold", verdict(799, 998, 900) == "no", verdict(799, 998, 900))
check("CPRR fails one base under the identity threshold", verdict(800, 1000, 899) == "no", verdict(800, 1000, 899))
check("CPRR fails when the bin share is under the threshold", verdict(800, 1001, 900) == "no", verdict(800, 1001, 900))

print("ALL GUARD BOUNDARY TESTS PASSED" if ok else "GUARD BOUNDARY TESTS FAILED")
sys.exit(0 if ok else 1)
