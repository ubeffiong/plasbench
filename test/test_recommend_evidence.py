#!/usr/bin/env python3
"""The recommendation evidence panel (plan D5): what stands behind a recommendation, and a visible reason when there is none."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import report_recommend_evidence as rre  # noqa: E402


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    recs = [{"scope": "overall", "tool": "toolA", "recommendation": "primary", "n_scored": "6", "coverage": "1.0", "mean_f1": "0.91", "decision_score": "0.88"},
            {"scope": "overall", "tool": "toolB", "recommendation": "none", "reason": "insufficient coverage"}]
    board = [{"tool": "toolA", "n_independent_clusters": "4", "ranking_score": "0.91", "ranking_ci_low": "0.8", "ranking_ci_high": "0.95", "significant_vs_runner_up": "yes",
              "primary_status": "available"}]
    prov = [{"reference_tier": "1", "evidence_recorded": "5 of 6"}, {"reference_tier": "3", "evidence_recorded": "1 of 6"}]
    feats = [{"organism": "E. coli"}, {"organism": "K. pneumoniae"}]
    html = rre.panel_html(recs, board, prov, feats, {"arms": {"feature_conditioned": "no_better"}})
    check("all six facts are listed", all(k in html for k in ("Expected performance", "Independent studies", "Reference quality", "Dataset similarity", "Uncertainty", "Reason withheld")))
    check("the numbers come from the tables", "mean F1 0.910 over 6 scored" in html and "4 independent cluster" in html and "95% CI 0.8 to 0.95" in html)
    check("reference quality counts the tiers and the evidence recorded", "tier 1: 1, tier 3: 1" in html and "3.0 of 6 on average" in html)
    check("the dataset line says it is for the cohort and reports the similarity arm", "not a prediction for a new isolate" in html and "choosing by similar isolates: no better" in html and "E. coli" in html)
    check("a met gate says there is nothing withheld", "none: the coverage gate was met" in html)
    bare = rre.panel_html(recs, [], [], [], None)
    check("missing tables are 'not recorded', never a number", bare.count("not recorded") >= 2 and "choosing by similar isolates: not evaluated" in bare)
    none = rre.panel_html([{"scope": "overall", "tool": "toolB", "recommendation": "none", "reason": "insufficient coverage"}], [{"primary_status": "unavailable"}], [], [], {})
    check("with no recommendation the panel says so and why", "No tool is recommended" in none and "insufficient coverage" in none and "primary analysis is unavailable" in none, none)
    check("no recommendations table is a Not run note", "Not run" in rre.panel_html([], [], [], [], {}))
    print()
    if not ok:
        print("RECOMMENDATION EVIDENCE TESTS FAILED")
        sys.exit(1)
    print("ALL RECOMMENDATION EVIDENCE TESTS PASSED")


if __name__ == "__main__":
    main()
