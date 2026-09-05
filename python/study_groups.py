#!/usr/bin/env python3
"""Shared source_study grouping for leave-one-study-out validation.

Used by both validate_recommendations.py (validating the fixed-weight
method) and fit_recommendation_model.py (validating the learned model), so
both share the exact same folds -- a model can only be trusted if it beats
the fixed-weight method under the identical held-out splits.
"""

from collections import defaultdict


def group_samples_by_study(scores_rows, metadata):
    """Return {source_study: {sample_id, ...}} for every scored sample whose
    sample-sheet row declares a non-blank source_study."""
    studies = defaultdict(set)
    for row in scores_rows:
        study = (metadata.get(row["sample"], {}).get("source_study") or "").strip()
        if study:
            studies[study].add(row["sample"])
    return studies
