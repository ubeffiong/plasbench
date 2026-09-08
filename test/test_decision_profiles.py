#!/usr/bin/env python3
"""Regression for recommendation_model.py's named decision-score weight
profiles and select_operational_method.py's applicability_tier(): the
default profile is byte-identical to today's original single formula, a
different profile can change which tool wins only when it should, and
applicability grades eligibility without changing eligible()'s own binary
gate."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))

from recommendation_model import DECISION_PROFILES, DEFAULT_DECISION_PROFILE, decision_score  # noqa: E402
from select_operational_method import applicability_tier, eligible  # noqa: E402


def test_default_profile_matches_original_formula():
    expected = (.45 * 0.9 + .13 * 0.95 + .13 * 0.90 + .18 * 0.85 + .06 * 0.80
                - .03 * 0.05 - 0.02 - 0.01)
    value_no_profile = decision_score(0.9, 0.95, 0.90, 0.85, 0.80, 0.05, 0.02, 0.01)
    value_default_profile = decision_score(0.9, 0.95, 0.90, 0.85, 0.80, 0.05, 0.02, 0.01, profile=DEFAULT_DECISION_PROFILE)
    assert abs(value_no_profile - expected) < 1e-9
    assert value_no_profile == value_default_profile
    print("omitting profile and explicitly passing the default profile both reproduce the original formula exactly -> PASS")


def test_amr_surveillance_weighs_plasmid_recall_more():
    # Two tools: A has higher F1 but lower plasmid recall; B has lower F1 but
    # near-perfect plasmid recall. amr_surveillance's much larger plasmid
    # weight should be ABLE to flip the ranking relative to accuracy_first,
    # even though neither profile guarantees any specific tool wins in
    # general -- this fixture is constructed so it does.
    tool_a = dict(f1=0.95, precision=0.95, recall=0.95, plasmid=0.70, bin_score=None,
                 failure_rate=0.0, structural_penalty=0.0, resource_penalty=0.0)
    tool_b = dict(f1=0.80, precision=0.80, recall=0.80, plasmid=0.99, bin_score=None,
                 failure_rate=0.0, structural_penalty=0.0, resource_penalty=0.0)
    score_a_default = decision_score(**tool_a, profile="accuracy_first")
    score_b_default = decision_score(**tool_b, profile="accuracy_first")
    score_a_amr = decision_score(**tool_a, profile="amr_surveillance")
    score_b_amr = decision_score(**tool_b, profile="amr_surveillance")
    assert score_a_default > score_b_default, "fixture assumption: tool A should lead under accuracy_first"
    assert score_b_amr > score_a_amr, "amr_surveillance's larger plasmid-recall weight should flip the ranking to tool B"
    print("amr_surveillance's larger plasmid-recall weight can flip a ranking accuracy_first would not -> PASS")


def test_rapid_screening_weighs_resource_penalty_more():
    fast = dict(f1=0.85, precision=0.85, recall=0.85, plasmid=0.85, bin_score=None,
               failure_rate=0.0, structural_penalty=0.0, resource_penalty=0.02)
    slow = dict(f1=0.95, precision=0.95, recall=0.95, plasmid=0.95, bin_score=None,
               failure_rate=0.0, structural_penalty=0.0, resource_penalty=0.10)
    score_fast_default = decision_score(**fast, profile="accuracy_first")
    score_slow_default = decision_score(**slow, profile="accuracy_first")
    score_fast_rapid = decision_score(**fast, profile="rapid_screening")
    score_slow_rapid = decision_score(**slow, profile="rapid_screening")
    assert score_slow_default > score_fast_default, "fixture assumption: the slower, more accurate tool should lead under accuracy_first"
    assert score_fast_rapid > score_slow_rapid, "rapid_screening's much larger resource penalty should flip the ranking to the faster tool"
    print("rapid_screening's larger resource-penalty weight can flip a ranking accuracy_first would not -> PASS")


def test_unknown_profile_raises():
    try:
        decision_score(0.9, 0.9, 0.9, 0.9, None, 0.0, 0.0, 0.0, profile="not_a_real_profile")
        assert False, "expected a KeyError for an unrecognized profile name"
    except KeyError:
        pass
    print("an unrecognized profile name fails clearly rather than silently using a default -> PASS")


def test_amr_context_uses_curated_gene_recovery():
    # Both methods are otherwise equal; a profile explicitly selected for AMR
    # context must prefer the method recovering more independently curated
    # truth genes, not invent a preference from a generic database scan.
    shared = dict(f1=.85, precision=.85, recall=.85, plasmid=.85, bin_score=.85,
                  failure_rate=0., structural_penalty=.01, resource_penalty=.01, profile="amr_context")
    low = decision_score(**shared, amr_gene_recall=.20)
    high = decision_score(**shared, amr_gene_recall=.95)
    assert high > low
    print("amr_context gives co-primary weight to curated AMR-gene recovery -> PASS")


def test_applicability_tiers():
    min_samples, min_coverage = 5, 0.80
    unsupported = {"n_scored": 3, "coverage": 0.90}
    low = {"n_scored": 5, "coverage": 0.81}
    moderate = {"n_scored": 8, "coverage": 0.85}
    high = {"n_scored": 12, "coverage": 0.97}

    assert not eligible(unsupported, min_samples, min_coverage)
    assert applicability_tier(unsupported, min_samples, min_coverage) == "unsupported"
    assert eligible(low, min_samples, min_coverage)
    assert applicability_tier(low, min_samples, min_coverage) == "low"
    assert applicability_tier(moderate, min_samples, min_coverage) == "moderate"
    assert applicability_tier(high, min_samples, min_coverage) == "high"
    print("applicability_tier grades unsupported/low/moderate/high correctly, without changing eligible()'s own gate -> PASS")


def main():
    test_default_profile_matches_original_formula()
    test_amr_surveillance_weighs_plasmid_recall_more()
    test_rapid_screening_weighs_resource_penalty_more()
    test_unknown_profile_raises()
    test_amr_context_uses_curated_gene_recovery()
    test_applicability_tiers()
    assert set(DECISION_PROFILES) == {"accuracy_first", "amr_surveillance", "rapid_screening", "amr_context"}
    print("ALL DECISION PROFILE TESTS PASSED")


if __name__ == "__main__":
    main()
