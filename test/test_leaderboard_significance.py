#!/usr/bin/env python3
"""Regression for aggregate_results.py's significant_vs_runner_up leaderboard
flag: derived from the EXISTING paired, shared-sample, sign-flip permutation
test (Holm-adjusted -- compute_comparisons()/paired_permutation_pvalue()/
holm_adjust()), never a bootstrap-CI-overlap heuristic. Three cases:
  1. The top tool clearly, consistently beats the runner-up on every shared
     sample -> significant (True).
  2. The top tool's advantage is small and inconsistent in sign -> not
     significant (False), even though it still ranks first on mean F1.
  3. Too few shared samples for the permutation test to run at all (below
     paired_permutation_pvalue's own n>=5 gate) -> not_assessed, never a
     fabricated True/False.
"""

import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))

from aggregate_results import attach_significance, compute_comparisons, summarise  # noqa: E402


def empty_status_counts():
    return defaultdict(lambda: {"completed": 0, "reused": 0, "failed": 0, "skipped": 0})


def make_row(sample, tool, f1):
    """A minimal, valid read_scores()-shaped row -- every field summarise()/
    compute_comparisons() might touch, defaulted to "not present"."""
    return {
        "sample": sample, "tool": tool, "precision": f1, "recall": f1, "f1": f1,
        "analysis_track": "short_read", "plasmid_recall": f1, "bin_f1": None,
        "pr_auc": None, "perfect_reference_recovery": "", "strict_reference_reconstruction": "",
        "isolate_specificity": None, "chromosome_fp_bp": None, "true_plasmid_count": 1,
        "nmi": None, "variation_of_information": None,
        "plasmid_recall_ge50": None, "plasmid_recall_ge90": None, "complete_circular_plasmid_recall": None,
    }


def run(rows):
    summary = summarise(rows, empty_status_counts())
    comparisons = compute_comparisons(rows)
    attach_significance(summary, comparisons)
    by_tool = {s["tool"]: s for s in summary}
    return summary, by_tool


def main():
    ok = True
    samples = [f"s{i}" for i in range(10)]

    # --- Case 1: "good" beats "bad" by a large, consistent margin -> significant. ---
    rows = []
    for i, sample in enumerate(samples):
        rows.append(make_row(sample, "good", 0.95))
        rows.append(make_row(sample, "bad", 0.55))
    summary, by_tool = run(rows)
    ok &= (summary[0]["tool"] == "good" and summary[0]["significant_vs_runner_up"] is True)
    print(f"  clear, consistent winner -> significant_vs_runner_up is True ? "
          f"top={summary[0]['tool']!r} sig={summary[0]['significant_vs_runner_up']!r} -> "
          f"{summary[0]['tool'] == 'good' and summary[0]['significant_vs_runner_up'] is True}")

    # --- Case 2: "good2" ranks first on mean F1, but the margin is small and
    # inconsistent in sign -- a real, but not statistically significant, edge. ---
    rows = []
    small_diffs = [0.02, -0.03, 0.01, -0.02, 0.03, -0.01, 0.02, -0.02, 0.01, -0.01]
    base = 0.70
    for sample, diff in zip(samples, small_diffs):
        rows.append(make_row(sample, "good2", base + diff))
        rows.append(make_row(sample, "bad2", base))
    summary, by_tool = run(rows)
    ok &= (summary[0]["tool"] == "good2" and summary[0]["significant_vs_runner_up"] is False)
    print(f"  small, inconsistent margin -> significant_vs_runner_up is False ? "
          f"top={summary[0]['tool']!r} sig={summary[0]['significant_vs_runner_up']!r} -> "
          f"{summary[0]['tool'] == 'good2' and summary[0]['significant_vs_runner_up'] is False}")

    # --- Case 3: only 3 shared samples -- below paired_permutation_pvalue's
    # own n>=5 minimum -- must be not_assessed, never a fabricated verdict. ---
    rows = []
    for sample in samples[:3]:
        rows.append(make_row(sample, "good3", 0.95))
        rows.append(make_row(sample, "bad3", 0.55))
    summary, by_tool = run(rows)
    ok &= (summary[0]["tool"] == "good3" and summary[0]["significant_vs_runner_up"] == "not_assessed")
    print(f"  too few paired samples -> not_assessed ? "
          f"top={summary[0]['tool']!r} sig={summary[0]['significant_vs_runner_up']!r} -> "
          f"{summary[0]['tool'] == 'good3' and summary[0]['significant_vs_runner_up'] == 'not_assessed'}")

    # --- Every non-winning row stays not_assessed -- the claim is only ever
    # made about the top tool vs its specific runner-up. ---
    _, by_tool1 = run([make_row(s, t, f1) for s in samples
                       for t, f1 in (("good", 0.95), ("bad", 0.55))])
    ok &= (by_tool1["bad"]["significant_vs_runner_up"] == "not_assessed")
    print(f"  runner-up's own row stays not_assessed ? "
          f"{by_tool1['bad']['significant_vs_runner_up']!r} -> "
          f"{by_tool1['bad']['significant_vs_runner_up'] == 'not_assessed'}")

    # --- A single-tool leaderboard has no runner-up at all. ---
    summary_single = summarise([make_row(s, "only", 0.9) for s in samples], empty_status_counts())
    attach_significance(summary_single, compute_comparisons([make_row(s, "only", 0.9) for s in samples]))
    ok &= (summary_single[0]["significant_vs_runner_up"] == "not_assessed")
    print(f"  single tool, no runner-up -> not_assessed ? "
          f"{summary_single[0]['significant_vs_runner_up']!r} -> "
          f"{summary_single[0]['significant_vs_runner_up'] == 'not_assessed'}")

    print("\nALL LEADERBOARD SIGNIFICANCE TESTS PASSED" if ok else "\nTESTS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
