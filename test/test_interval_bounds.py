#!/usr/bin/env python3
"""Intervals for a proportion stay inside [0, 1] (audit AU-052): the cluster-t interval is symmetric and used to run past the range (0.498 to 1.102)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
import resampling  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


check("clamp_interval clips both ends", resampling.clamp_interval(-0.2, 1.3, (0, 1)) == (0, 1))
check("clamp_interval leaves an interval inside the range alone", resampling.clamp_interval(0.2, 0.7, (0, 1)) == (0.2, 0.7))
check("clamp_interval passes None and absent bounds through", resampling.clamp_interval(None, None, (0, 1)) == (None, None) and resampling.clamp_interval(-1, 2, None) == (-1, 2))
check("an interval wholly above the range collapses to the upper bound", resampling.clamp_interval(1.1, 1.4, (0, 1)) == (1, 1))

values = [0.55, 0.62, 0.99, 1.0, 1.0, 0.98, 1.0, 0.97]
groups = [f"g{i}" for i in range(len(values))]
low, high = resampling.cluster_t_ci(values, groups)
check("the raw cluster-t interval does run above 1 on this data (the defect)", high > 1.0, (low, high))
low_b, high_b = resampling.interval(values, groups, method="cluster_t", bounds=(0.0, 1.0))
check("interval(bounds=(0, 1)) is inside [0, 1] and keeps the lower end", 0.0 <= low_b <= high_b <= 1.0 and abs(low_b - low) < 1e-12, (low_b, high_b))
print("ALL INTERVAL BOUND TESTS PASSED" if ok else "INTERVAL BOUND TESTS FAILED")
sys.exit(0 if ok else 1)
