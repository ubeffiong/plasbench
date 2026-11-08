#!/usr/bin/env python3
"""Shared source_study grouping for leave-one-study-out validation.

Used by both validate_recommendations.py (validating the fixed-weight
method) and fit_recommendation_model.py (validating the learned model), so
both share the exact same folds -- a model can only be trusted if it beats
the fixed-weight method under the identical held-out splits.
"""

import sys
from collections import defaultdict


def _text(metadata, sample, field):
    return (metadata.get(sample, {}).get(field) or "").strip()


def group_samples_by_study(scores_rows, metadata):
    """Return {study: {sample_id, ...}} for every scored sample that can be
    assigned to a study.

    A sample's study is, in order:
      1. its sample-sheet source_study, if non-blank;
      2. the source_study of any other sample that shares its bioproject (the
         same study must never be split across folds, or the held-out fold
         leaks into training);
      3. its bioproject accession, if no sibling declares a source_study.
    A sample with neither source_study nor bioproject cannot be assigned. It is
    left out, and the count is written to stderr rather than dropped silently:
    this function used to drop every blank-source_study sample without a word,
    which in a cohort with many such rows quietly shrank the validation set.
    """
    samples = list(dict.fromkeys(row["sample"] for row in scores_rows))

    study_of_bioproject = {}
    for sample in samples:
        study, bioproject = _text(metadata, sample, "source_study"), _text(metadata, sample, "bioproject")
        if study and bioproject:
            study_of_bioproject.setdefault(bioproject, study)

    studies = defaultdict(set)
    unassigned = []
    for sample in samples:
        study = _text(metadata, sample, "source_study")
        if not study:
            bioproject = _text(metadata, sample, "bioproject")
            study = study_of_bioproject.get(bioproject, bioproject)
        if study:
            studies[study].add(sample)
        else:
            unassigned.append(sample)
    if unassigned:
        shown = ", ".join(unassigned[:5]) + (" ..." if len(unassigned) > 5 else "")
        sys.stderr.write(
            f"[study_groups] {len(unassigned)} of {len(samples)} scored sample(s) have neither "
            f"source_study nor bioproject and are excluded from leave-one-study-out folds: {shown}\n")
    return studies
