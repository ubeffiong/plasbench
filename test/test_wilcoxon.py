#!/usr/bin/env python3
"""Paired Wilcoxon signed-rank (aggregate_results.wilcoxon_signed_rank) against
known exact values, and the equivalence flag in benchmark.paired_comparisons.tsv.

Exact references (two-sided; agree with scipy.stats.wilcoxon(method="exact")):
  [1, 2, 3, 4, 5]            W+ = 15, P(W+ >= 15) = 1/32 -> p = 0.0625
  [1,-2,3,4,5,6,-7,8]        W- = 9, P(W <= 9 | n = 8) = 32/256 -> p = 0.25
  [0, 0, 0]                  every difference zero -> None (undefined)
  [1, -1, 2, -2]             ties: ranks 1.5,1.5,3.5,3.5; W+ = 5 = n(n+1)/4 -> p = 1.0
Normal approximation (n = 30 > 25): continuity-corrected, finite and in (0, 1].
"""
import csv
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import aggregate_results as ar  # noqa: E402


def main():
    assert abs(ar.wilcoxon_signed_rank([1, 2, 3, 4, 5]) - 0.0625) < 1e-12
    assert abs(ar.wilcoxon_signed_rank([1, -2, 3, 4, 5, 6, -7, 8]) - 0.25) < 1e-12
    assert ar.wilcoxon_signed_rank([0, 0, 0]) is None and ar.wilcoxon_signed_rank([]) is None
    assert abs(ar.wilcoxon_signed_rank([1, -1, 2, -2]) - 1.0) < 1e-12
    print("  PASS: exact p-values 0.0625, 0.25, 1.0 (ties) and None for all-zero differences")
    big = ar.wilcoxon_signed_rank([0.01 * i for i in range(1, 31)])
    assert big is not None and 0 < big < 1e-5, big
    print(f"  PASS: n = 30 all-positive -> normal approximation p = {big:.2e}")

    rows = []
    for i in range(10):
        rows.append({"sample": f"s{i}", "tool": "a", "f1": 0.80 + 0.001 * i})
        rows.append({"sample": f"s{i}", "tool": "b", "f1": 0.80 + 0.001 * i - 0.01})
        rows.append({"sample": f"s{i}", "tool": "c", "f1": 0.40})
    os.environ["SMALLEST_DIFFERENCE"] = "0.05"
    comparisons = {(c["tool_a"], c["tool_b"]): c for c in ar.compute_comparisons(rows)}
    assert comparisons[("a", "b")]["equivalent"] == "yes", comparisons[("a", "b")]
    assert comparisons[("a", "c")]["equivalent"] == "no"
    assert abs(comparisons[("a", "c")]["wilcoxon_p_value"] - 2 / 1024) < 1e-12
    assert comparisons[("a", "c")]["wilcoxon_p_value_holm"] is not None
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "pc.tsv"
        ar.write_comparisons(rows, path, comparisons=list(comparisons.values()))
        with open(path, newline="") as handle:
            written = list(csv.DictReader(handle, delimiter="\t"))
        assert {"wilcoxon_p_value", "wilcoxon_p_value_holm", "equivalent", "smallest_difference"} <= set(written[0])
        assert next(r for r in written if r["tool_b"] == "c")["wilcoxon_p_value"] == "0.001953"
    print("  PASS: |delta| 0.01 < 0.05 -> equivalent; a vs c Wilcoxon p = 2/1024; columns written")
    print("ALL WILCOXON TESTS PASSED")


if __name__ == "__main__":
    main()
