#!/usr/bin/env python3
"""Regression for python/recommendation_model.py's hand-rolled (pure stdlib,
no numpy) ridge regression: exact recovery on a hand-solvable system,
shrinkage as lambda grows, and the feature-encoding/model round-trip."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))

from recommendation_model import (  # noqa: E402
    RecommendationModel, decision_score, encode_row, fit_feature_spec,
    mean_absolute_error, solve_ridge,
)


def test_solve_ridge_exact_recovery():
    # y = 2 + 3x exactly, no noise -- lambda=0 must recover the true line.
    X = [[0.0], [1.0], [2.0], [3.0], [4.0]]
    y = [2.0, 5.0, 8.0, 11.0, 14.0]
    intercept, coefficients = solve_ridge(X, y, 0.0)
    assert abs(intercept - 2.0) < 1e-6, intercept
    assert abs(coefficients[0] - 3.0) < 1e-6, coefficients
    print("solve_ridge recovers an exact hand-solvable line at lambda=0 -> PASS")


def test_solve_ridge_shrinkage():
    X = [[0.0], [1.0], [2.0], [3.0], [4.0]]
    y = [2.0, 5.0, 8.0, 11.0, 14.0]
    _, unregularized = solve_ridge(X, y, 0.0)
    _, regularized = solve_ridge(X, y, 10.0)
    assert abs(regularized[0]) < abs(unregularized[0]), (unregularized, regularized)
    print("a positive lambda shrinks the coefficient toward zero relative to lambda=0 -> PASS")


def test_solve_ridge_no_training_rows():
    try:
        solve_ridge([], [], 1.0)
        assert False, "expected ValueError on empty training data"
    except ValueError:
        pass
    print("solve_ridge raises cleanly on no training rows, rather than crashing obscurely -> PASS")


def test_mean_absolute_error():
    assert mean_absolute_error([], []) is None
    assert abs(mean_absolute_error([1.0, 2.0, 3.0], [1.0, 2.0, 5.0]) - (2 / 3)) < 1e-9
    print("mean_absolute_error matches hand computation, and is None (not 0) for empty input -> PASS")


def test_feature_encoding_round_trip():
    rows = [
        {"read_depth_x": 30.0, "true_plasmid_bp": 10000.0, "true_plasmid_count": 2.0,
         "tool": "mob_recon", "organism": "E. coli", "gram_group": "negative", "amr_status": "AMR annotated"},
        {"read_depth_x": 60.0, "true_plasmid_bp": 50000.0, "true_plasmid_count": 3.0,
         "tool": "platon", "organism": "K. pneumoniae", "gram_group": "negative", "amr_status": "AMR not annotated"},
    ]
    spec = fit_feature_spec(rows)
    v1 = encode_row(rows[0], spec)
    v2 = encode_row(rows[1], spec)
    assert len(v1) == len(v2)
    # A missing continuous field is imputed with the training mean -> its
    # standardized contribution is exactly 0.
    missing = {"tool": "mob_recon", "organism": "E. coli", "gram_group": "negative", "amr_status": "AMR annotated"}
    v_missing = encode_row(missing, spec)
    n_continuous = 3
    assert all(abs(value) < 1e-9 for value in v_missing[:n_continuous]), v_missing[:n_continuous]
    print("missing continuous features impute to the training mean (zero standardized contribution) -> PASS")

    # An unseen category maps to an all-zero one-hot block for that field.
    unseen = {"read_depth_x": 30.0, "true_plasmid_bp": 10000.0, "true_plasmid_count": 2.0,
              "tool": "brand_new_tool", "organism": "E. coli", "gram_group": "negative", "amr_status": "AMR annotated"}
    v_unseen = encode_row(unseen, spec)
    tool_block_start = n_continuous
    tool_block_len = len(spec["vocab"]["tool"])
    assert all(x == 0.0 for x in v_unseen[tool_block_start:tool_block_start + tool_block_len])
    print("an unseen category encodes as an all-zero one-hot block (falls back to the intercept) -> PASS")


def test_model_round_trip_and_predict():
    rows = [
        {"read_depth_x": 20.0, "true_plasmid_bp": 5000.0, "true_plasmid_count": 1.0,
         "tool": "mob_recon", "organism": "E. coli", "gram_group": "negative", "amr_status": "AMR annotated"},
        {"read_depth_x": 40.0, "true_plasmid_bp": 20000.0, "true_plasmid_count": 2.0,
         "tool": "mob_recon", "organism": "E. coli", "gram_group": "negative", "amr_status": "AMR annotated"},
        {"read_depth_x": 60.0, "true_plasmid_bp": 40000.0, "true_plasmid_count": 3.0,
         "tool": "mob_recon", "organism": "E. coli", "gram_group": "negative", "amr_status": "AMR annotated"},
    ]
    # f1 rises cleanly with depth: 0.5, 0.7, 0.9
    targets = [0.5, 0.7, 0.9]
    spec = fit_feature_spec(rows)
    features = [encode_row(row, spec) for row in rows]
    intercept, coefficients = solve_ridge(features, targets, 0.1)
    model = RecommendationModel(spec, {"f1": (intercept, coefficients), "plasmid_recall": (intercept, coefficients)},
                                {"f1": 0.1, "plasmid_recall": 0.1}, {"f1": 0.01, "plasmid_recall": 0.01},
                                {"f1": 0.05, "plasmid_recall": 0.05}, 3, 2)
    payload = model.to_dict(True, "model-fitted: test fixture")
    restored = RecommendationModel.from_dict(payload)
    predicted = restored.predict("f1", rows[1])
    assert abs(predicted - 0.7) < 0.15, predicted  # ridge with lambda>0 won't be exact, but close
    print("a fitted model round-trips through to_dict/from_dict and predicts sensibly -> PASS")


def test_decision_score_matches_known_formula():
    # Hand-computed: .45*.9 + .13*.95 + .13*.90 + .18*.85 + .06*.80 - .03*.05 - .02 - .01
    value = decision_score(f1=0.9, precision=0.95, recall=0.90, plasmid=0.85, bin_score=0.80,
                          failure_rate=0.05, structural_penalty=0.02, resource_penalty=0.01)
    expected = .45 * .9 + .13 * .95 + .13 * .90 + .18 * .85 + .06 * .80 - .03 * .05 - .02 - .01
    assert abs(value - expected) < 1e-9
    print("decision_score matches the exact hand-computed weighted-sum formula -> PASS")


def main():
    test_solve_ridge_exact_recovery()
    test_solve_ridge_shrinkage()
    test_solve_ridge_no_training_rows()
    test_mean_absolute_error()
    test_feature_encoding_round_trip()
    test_model_round_trip_and_predict()
    test_decision_score_matches_known_formula()
    print("ALL RIDGE REGRESSION TESTS PASSED")


if __name__ == "__main__":
    main()
