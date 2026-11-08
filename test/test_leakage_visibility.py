#!/usr/bin/env python3
"""
A leakage screen that could not judge anything must say so. "0 possible overlap,
0 after database" with every pair 'unknown' looks like a clean result and is not.
"""

import os
import sys
import tempfile
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))

from aggregate_results import (  # noqa: E402
    LEAKAGE_UNASSESSED_NOTE, leakage_unassessed, overlap_summary, ranked_tracks, write_md, write_tsv,
)
import build_html_report  # noqa: E402


def row(sample, tool, f1):
    return {
        "sample": sample, "tool": tool, "precision": f1, "recall": f1, "f1": f1,
        "analysis_track": "short_read", "plasmid_recall": f1, "bin_f1": None,
        "pr_auc": None, "perfect_reference_recovery": "", "strict_reference_reconstruction": "",
        "isolate_specificity": None, "chromosome_fp_bp": None, "true_plasmid_count": 1,
        "nmi": None, "variation_of_information": None,
        "plasmid_recall_ge50": None, "plasmid_recall_ge90": None,
        "complete_circular_plasmid_recall": None,
    }


def main():
    ok = True

    def check(label, condition):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}")

    samples = [f"s{i}" for i in range(3)]
    rows = [row(s, "mob_recon", 0.9) for s in samples]

    print("when no pair could be judged")
    unknown = {(s, "mob_recon"): "unknown" for s in samples}
    check("leakage_unassessed is True", leakage_unassessed(unknown))
    summary = overlap_summary("mob_recon", rows, unknown)
    check("n_unknown_overlap counts the pairs", summary["n_unknown_overlap"] == 3)
    check("possible/after stay 0", summary["n_possible_db_overlap"] == 0 and summary["n_after_database"] == 0)

    print("when at least one pair was judged")
    mixed = dict(unknown); mixed[("s0", "mob_recon")] = "after_database"
    check("leakage_unassessed is False", not leakage_unassessed(mixed))
    judged = {(s, "mob_recon"): "possible_overlap" for s in samples}
    check("an all-possible-overlap run is not 'unassessed' either", not leakage_unassessed(judged))
    check("a tool-with-no-database run is not 'unassessed'",
          not leakage_unassessed({(s, "plasmidspades"): "no_reference_database" for s in samples}))
    check("no overlap file at all is a different state (not claimed here)", not leakage_unassessed({}))

    print("Markdown leaderboard")
    with tempfile.TemporaryDirectory() as tmp:
        result = ranked_tracks(rows, defaultdict(lambda: {"completed": 0, "reused": 0, "failed": 0, "skipped": 0}),
                               overlap=unknown)
        table = [r for _, _, s, _ in result for r in s]
        path = os.path.join(tmp, "lb.md")
        write_md(table, path, notes=[LEAKAGE_UNASSESSED_NOTE])
        text = open(path, encoding="utf-8").read()
        check("the warning is in the file", "Database leakage was NOT assessed" in text)
        write_md(table, path)
        check("and absent when there is nothing to warn about",
              "Database leakage was NOT assessed" not in open(path, encoding="utf-8").read())
        tsv = os.path.join(tmp, "lb.tsv")
        write_tsv(table, tsv)
        lines = open(tsv, encoding="utf-8").read().splitlines()
        header, values = lines[0].split("\t"), lines[1].split("\t")
        check("the TSV carries n_unknown_overlap", dict(zip(header, values)).get("n_unknown_overlap") == "3")

    print("HTML report cell")
    base = {"tool": "mob_recon", "mean_f1": "0.9", "n_ranking_samples": "3", "ranking_basis": "shared_samples"}
    def cell(**extra):
        html = build_html_report.robustness_section({"short_read": [dict(base, **extra)]}, ["short_read"])
        return html
    html = cell(n_possible_db_overlap="0", n_after_database="0", n_unknown_overlap="3")
    check("says 'not assessed' when pairs are unknown", "not assessed" in html and "3 pair(s) unknown" in html)
    html = cell(n_possible_db_overlap="0", n_after_database="0", n_unknown_overlap="0")
    check("says 'no reference database' only when nothing is unknown", "uses no reference database" in html)
    html = cell(n_possible_db_overlap="1", n_after_database="2", n_unknown_overlap="0")
    check("shows counts when pairs were judged", "1 possible / 2 after" in html)

    print()
    if not ok:
        print("LEAKAGE VISIBILITY TESTS FAILED")
        sys.exit(1)
    print("ALL LEAKAGE VISIBILITY TESTS PASSED")


if __name__ == "__main__":
    main()
