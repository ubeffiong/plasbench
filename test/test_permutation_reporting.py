#!/usr/bin/env python3
"""
How a permutation p-value was made, and whether the comparison can reach significance, is reported with it (python/resampling.py, aggregate_results.py, the report).

  - constants: MIN_CLUSTERS_CI 5, MIN_CLUSTERS_TEST 6, EXACT_MAX_UNITS 12; permutation_method / permutation_floor values at the edges (5, 6, 12, 13, 20 units);
  - with 5 independent units there is no p-value (its smallest attainable value, 0.0625, cannot reach 0.05); with 6 to 12 the p-value is exact and reproducible without random numbers;
  - compute_comparisons adds permutation_method, min_attainable_p and p_status to every comparison, write_comparisons writes them last (older columns keep their order);
  - the report's paired-comparison table has a Permutation test column ('exact, smallest attainable p 0.03125', 'underpowered' when the floor is above 0.05, 'not estimated');
  - the shipped pre-registration records the three thresholds.
"""
import csv
import os
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import aggregate_results as ar  # noqa: E402
import build_html_report as report  # noqa: E402
import freeze_prereg  # noqa: E402
import resampling as rs  # noqa: E402


def make_row(sample, tool, f1):
    return {"sample": sample, "tool": tool, "precision": f1, "recall": f1, "f1": f1, "analysis_track": "short_read", "plasmid_recall": f1, "bin_f1": None,
            "pr_auc": None, "perfect_reference_recovery": "", "strict_reference_reconstruction": "", "isolate_specificity": None, "chromosome_fp_bp": None,
            "true_plasmid_count": 1, "nmi": None, "variation_of_information": None, "plasmid_recall_ge50": None, "plasmid_recall_ge90": None,
            "complete_circular_plasmid_recall": None}


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    print("the thresholds")
    check("named constants", (rs.MIN_CLUSTERS_CI, rs.MIN_CLUSTERS_TEST, rs.EXACT_MAX_UNITS) == (5, 6, 12))
    check("method by number of independent units", [rs.permutation_method(n) for n in (1, 5, 6, 12, 13, 20)] == ["not_estimated"] * 2 + ["exact", "exact", "monte_carlo", "monte_carlo"])
    check("smallest attainable p-value: 0.0625 with 5 units, 0.03125 with 6, the Monte Carlo floor at 20", rs.permutation_floor(5) == 0.0625 and rs.permutation_floor(6) == 0.03125
          and abs(rs.permutation_floor(20) - 1 / 10001) < 1e-12 and rs.permutation_floor(0) is None)
    check("5 units can never be significant at 0.05, 6 can", rs.permutation_floor(5) > 0.05 > rs.permutation_floor(6))
    five = [0.4, 0.5, 0.3, 0.6, 0.45]
    six = five + [0.35]
    check("no p-value for 5 independent units", rs.paired_permutation_pvalue(five, groups=list("abcde")) is None)
    p = rs.paired_permutation_pvalue(six, groups=list("abcdef"))
    check("6 consistent units: the exact p-value is the floor, and needs no random numbers", p == 0.03125 and rs.paired_permutation_pvalue(six, groups=list("abcdef")) == p, p)
    check("a clustered design counts independent units, not samples (12 samples in 4 clusters: no test)",
          rs.paired_permutation_pvalue([0.4] * 12, groups=[f"g{i // 3}" for i in range(12)]) is None)

    print("the comparisons")
    def comparisons(n):
        rows = []
        for i in range(n):
            rows.append(make_row(f"s{i}", "good", 0.95))
            rows.append(make_row(f"s{i}", "bad", 0.55))
        return ar.compute_comparisons(rows)

    for n, method, status in ((5, "not_estimated", "not_estimated"), (6, "exact", "ok"), (13, "monte_carlo", "ok")):
        row = comparisons(n)[0]
        check(f"{n} independent units: method {method}, status {status}", row["permutation_method"] == method and row["p_status"] == status
              and row["min_attainable_p"] == rs.permutation_floor(n), row)
    # underpowered is judged on the Holm-adjusted p over every comparison: 6 units give a floor of 0.03125, so 2 comparisons can still reach 0.0625 (not below 0.05)
    many = []
    for t in ("a", "b", "c"):
        for i in range(6):
            many.append(make_row(f"s{i}", t, 0.9 - 0.2 * "abc".index(t)))
    rows3 = ar.compute_comparisons(many)
    check("with several comparisons a 6-unit test cannot be significant after Holm: underpowered, and the Holm floor says why",
          len(rows3) == 3 and all(r["p_status"] == "underpowered" and abs(r["holm_min_attainable_p"] - min(1.0, 3 * rs.permutation_floor(6))) < 1e-12 for r in rows3), rows3[0])
    check("a single 6-unit comparison is still fine (floor 0.03125 x 1)", comparisons(6)[0]["p_status"] == "ok" and abs(comparisons(6)[0]["holm_min_attainable_p"] - 0.03125) < 1e-12)
    nan = float("nan")
    check("a NaN in the differences gives no p-value and no interval, never about 1e-4",
          rs.paired_permutation_pvalue([.1] * 5 + [nan]) is None and rs.stratified_permutation([.1] * 6 + [nan], list(range(7)), ["a"] * 7) is None
          and rs.bootstrap_ci([.1, .2, .3, .4, .5, nan]) == (None, None))
    check("an infinite difference keeps its old behaviour (it is not 'not measured')", rs.paired_permutation_pvalue([.1] * 5 + [float("inf")]) is not None)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "pairs.tsv"
        ar.write_comparisons([], str(path), comparisons=comparisons(6))
        header = open(path, encoding="utf-8").readline().rstrip("\n").split("\t")
        record = next(csv.DictReader(open(path, newline="", encoding="utf-8"), delimiter="\t"))
        check("the written table has the new columns last, older columns in place",
              header[:4] == ["tool_a", "tool_b", "paired_samples", "mean_f1_difference"] and header[-7:-4] == ["wilcoxon_p_value_holm", "equivalent", "smallest_difference"]
              and header[-4:] == ["permutation_method", "min_attainable_p", "p_status", "holm_min_attainable_p"], header)
        check("and the values", record["permutation_method"] == "exact" and float(record["min_attainable_p"]) == 0.03125 and record["p_status"] == "ok", record)

    print("the report and the plan")
    check("permutation_note: exact with its floor", report.permutation_note({"permutation_method": "exact", "min_attainable_p": "0.031250", "p_status": "ok"}) == "exact, smallest attainable p 0.031250")
    check("permutation_note: underpowered is said", "underpowered: cannot reach 0.05" in report.permutation_note({"permutation_method": "monte_carlo", "min_attainable_p": "0.0625", "p_status": "underpowered"})
          and "smallest Holm-adjusted p it can reach is 0.093750" in report.permutation_note({"permutation_method": "exact", "min_attainable_p": "0.031250", "p_status": "underpowered", "holm_min_attainable_p": "0.093750"}))
    check("permutation_note: not estimated, and older runs", report.permutation_note({"permutation_method": "not_estimated", "p_status": "not_estimated"}) == "not estimated"
          and report.permutation_note({}) == "not recorded (older run)")
    rows = {r["parameter"]: r for r in freeze_prereg.read_rows(ROOT / "config" / "prereg.tsv")}
    check("the pre-registration records the three thresholds", rows["min_clusters_ci"]["value"] == "5" and rows["min_clusters_test"]["value"] == "6"
          and rows["exact_permutation_max_units"]["value"] == "12" and all(rows[k]["status"] == "fixed" for k in ("min_clusters_ci", "min_clusters_test", "exact_permutation_max_units")))
    source = (ROOT / "python" / "build_html_report.py").read_text(encoding="utf-8")
    check("the paired table has a Permutation test column and says '6 independent units'", "<th>Permutation test</th>" in source and "fewer than 6 independent units" in source)

    print()
    if not ok:
        print("PERMUTATION REPORTING TESTS FAILED")
        sys.exit(1)
    print("ALL PERMUTATION REPORTING TESTS PASSED")


if __name__ == "__main__":
    main()
