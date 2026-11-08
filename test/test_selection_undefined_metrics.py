#!/usr/bin/env python3
"""
tool_quality() must follow the same rule as the scorer and the leaderboard: an
undefined metric is not a zero. And a skipped run is a deployment gap, not a
tool failure.
"""

import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))

import select_operational_method as som  # noqa: E402


def statuses(**counts):
    profiles = defaultdict(lambda: {"counts": Counter(), "runtime_seconds": [], "peak_rss_kb": []})
    profiles["tool"]["counts"].update(counts)
    return profiles


def row(sample, f1, precision=None, recall=None, plasmid_recall=None):
    def text(value):
        return "" if value is None else str(value)
    return {"tool": "tool", "sample": sample, "f1": text(f1),
            "precision": text(precision if precision is not None else f1),
            "recall": text(recall if recall is not None else f1),
            "plasmid_recall": text(plasmid_recall if plasmid_recall is not None else f1)}


def main():
    ok = True

    def check(label, condition):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}")

    print("undefined metrics are not zeros")
    rows = [row("s1", 0.8), row("s2", None)]   # s2 has no true plasmid: F1/precision/recall blank
    result = som.tool_quality(rows, statuses(completed=2), total_samples=2)["tool"]
    check("mean_f1 averages only the defined row (0.8, not 0.4)", abs(result["mean_f1"] - 0.8) < 1e-9)
    check("mean_precision likewise", abs(result["mean_precision"] - 0.8) < 1e-9)
    check("mean_recall likewise", abs(result["mean_recall"] - 0.8) < 1e-9)
    check("both rows still count as scored", result["n_scored"] == 2)

    rows = [row("s1", 0.9), row("s2", 0.5)]
    result = som.tool_quality(rows, statuses(completed=2), total_samples=2)["tool"]
    check("an all-defined stratum is the plain mean (0.7)", abs(result["mean_f1"] - 0.7) < 1e-9)

    rows = [row("s1", None), row("s2", None)]
    result = som.tool_quality(rows, statuses(completed=2), total_samples=2)["tool"]
    check("a stratum with nothing defined falls back rather than crashing", result["mean_f1"] == 0.0)

    print("skipped is not failed")
    rows = [row("s1", 0.8)]
    result = som.tool_quality(rows, statuses(completed=2, skipped=3), total_samples=2)["tool"]
    check("skipped runs do not raise failure_rate", result["failure_rate"] == 0.0)
    result = som.tool_quality(rows, statuses(completed=2, failed=1), total_samples=2)["tool"]
    check("failed runs do (1 of 3)", abs(result["failure_rate"] - 1 / 3) < 1e-9)
    result = som.tool_quality(rows, statuses(completed=2, failed=1, skipped=5), total_samples=2)["tool"]
    check("a failure rate ignores skips entirely", abs(result["failure_rate"] - 1 / 3) < 1e-9)

    print()
    if not ok:
        print("SELECTION UNDEFINED-METRIC TESTS FAILED")
        sys.exit(1)
    print("ALL SELECTION UNDEFINED-METRIC TESTS PASSED")


if __name__ == "__main__":
    main()
