#!/usr/bin/env python3
"""Regression for select_unknown_sample.py's §2.3 live per-isolate model
prediction path: absent/not-ready model -> unchanged scope-lookup behavior
(zero risk when this flag is unused); ready model -> predicts directly from
the query isolate's own features and can pick a DIFFERENT tool than the
discrete scope lookup would have, reusing the existing "overall" eligibility
gate so an unvalidated tool is never live-recommended."""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))

from recommendation_model import RecommendationModel  # noqa: E402
from select_unknown_sample import choose_recommendation  # noqa: E402


def make_model(tool_boost):
    """A minimal hand-built ready model: feature layout is
    [depth_z, plasmid_bp_z, plasmid_count_z, tool==toolA, tool==toolB,
     organism==E. coli, gram==negative, amr==not_recorded]. tool_boost
    controls which tool's one-hot coefficient wins, independent of depth."""
    spec = {
        "means": {"read_depth_x": 50.0, "true_plasmid_bp": 10000.0, "true_plasmid_count": 2.0},
        "stds": {"read_depth_x": 20.0, "true_plasmid_bp": 1.0, "true_plasmid_count": 1.0},
        "vocab": {"tool": ["toolA", "toolB"], "organism": ["E. coli"], "gram_group": ["negative"], "amr_status": ["not_recorded"]},
    }
    coefficients = [0.0, 0.0, 0.0] + tool_boost + [0.0, 0.0, 0.0]
    fits = {"f1": (0.5, coefficients), "plasmid_recall": (0.5, coefficients)}
    return RecommendationModel(spec, fits, {"f1": 1.0, "plasmid_recall": 1.0},
                               {"f1": 0.01, "plasmid_recall": 0.01}, {"f1": 0.05, "plasmid_recall": 0.05}, 10, 3)


def base_recommendation_rows():
    return [
        {"scope": "overall", "group": "all", "tool": "toolA", "eligible": "true", "recommendation": "primary",
         "mean_precision": "0.9", "mean_recall": "0.9", "mean_bin_f1": "", "failure_rate": "0.0"},
        {"scope": "overall", "group": "all", "tool": "toolB", "eligible": "true", "recommendation": "none",
         "mean_precision": "0.9", "mean_recall": "0.9", "mean_bin_f1": "", "failure_rate": "0.0"},
    ]


def test_model_absent_unchanged_behavior():
    rows = base_recommendation_rows()
    chosen = choose_recommendation(rows, organism="E. coli", gram_group="negative", model=None, read_depth_x=50.0)
    assert chosen["tool"] == "toolA", "with no model, the scope-lookup's own 'primary' pick must be unchanged"
    assert "reason" not in chosen or not str(chosen.get("reason", "")).startswith("model-fitted")
    print("model absent -> the exact unchanged scope-lookup pick, zero risk when this flag is unused -> PASS")


def test_model_ready_picks_its_own_argmax():
    rows = base_recommendation_rows()
    # toolB's one-hot coefficient (+0.3) outweighs toolA's stratum-primary
    # status -- the model's own prediction, not the discrete lookup, decides.
    model = make_model(tool_boost=[0.0, 0.3])
    chosen = choose_recommendation(rows, organism="E. coli", gram_group="negative", model=model, read_depth_x=50.0)
    assert chosen["tool"] == "toolB", f"expected the model's own argmax (toolB) to win, got {chosen['tool']}"
    assert chosen["reason"].startswith("model-fitted"), chosen["reason"]
    print("a ready model predicts directly from this isolate's own features and can override the scope lookup -> PASS")


def test_model_only_considers_overall_eligible_tools():
    rows = base_recommendation_rows()
    rows[1]["eligible"] = "false"  # toolB was never validated (ineligible)
    model = make_model(tool_boost=[0.0, 10.0])  # a huge boost -- would clearly win if considered
    chosen = choose_recommendation(rows, organism="E. coli", gram_group="negative", model=model, read_depth_x=50.0)
    assert chosen["tool"] == "toolA", \
        "an ineligible tool must never be live-recommended just because the model has an opinion about it"
    print("live prediction reuses the existing 'overall' eligibility gate -- an unvalidated tool is never picked -> PASS")


def test_model_falls_back_when_no_overall_row_is_eligible():
    rows = [{"scope": "overall", "group": "all", "tool": "toolA", "eligible": "false", "recommendation": "none",
            "mean_precision": "0.9", "mean_recall": "0.9", "mean_bin_f1": "", "failure_rate": "0.0"}]
    model = make_model(tool_boost=[0.0, 0.0])
    chosen = choose_recommendation(rows, organism="E. coli", gram_group="negative", model=model, read_depth_x=50.0)
    assert chosen is None, "no eligible overall row exists; the model has nothing sound to choose among"
    print("no eligible overall row -> live prediction correctly returns nothing, no guessing -> PASS")


def main():
    test_model_absent_unchanged_behavior()
    test_model_ready_picks_its_own_argmax()
    test_model_only_considers_overall_eligible_tools()
    test_model_falls_back_when_no_overall_row_is_eligible()
    print("ALL SELECT UNKNOWN SAMPLE MODEL TESTS PASSED")


if __name__ == "__main__":
    main()
