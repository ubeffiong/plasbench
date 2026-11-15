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


# -- further validation designs (second review, section 6B / 3B) -------------------------------------------------------
# Leave-one-study-out alone can leak: two closely related isolates from different studies can sit on either side of a fold.
# These designs answer different questions and are reported side by side, never interchanged:
#   isolate             leave one isolate out: performance on another isolate from represented studies
#   study               leave one study out (group_samples_by_study): generalisation to a new study
#   clonal_group        leave one clonal group out: generalisation beyond closely related isolates
#   study_and_clonal    a study and every isolate clonal with it held out together (union of both relations): the strictest
#   species             leave one species out: transfer to an unseen species (genus and phylum: leave_taxon_out.py)
# Temporal and external-cohort holdouts need collection dates or a second cohort and are not derived here.
HOLDOUT_DESIGNS = ("isolate", "study", "clonal_group", "study_and_clonal", "species")


def read_clonal_groups(path):
    """{sample: clonal group} from benchmark.clonal_groups.tsv; an 'isolate:' group means no clonal partner."""
    import csv
    import os
    if not path or not os.path.isfile(path):
        return {}
    with open(path, newline="", encoding="utf-8") as handle:
        rows = csv.DictReader((l for l in handle if l.strip() and not l.startswith("#")), delimiter="\t")
        return {r["sample"]: (r.get("clonal_group") or "").strip() for r in rows
                if r.get("sample") and (r.get("clonal_group") or "").strip() and not (r.get("clonal_group") or "").startswith("isolate:")}


def species_of(organism):
    words = (organism or "").replace("[", "").replace("]", "").split()
    return " ".join(words[:2]) if len(words) >= 2 else (words[0] if words else "")


def group_samples(design, scores_rows, metadata, clonal=None):
    """{group: {sample, ...}} for one HOLDOUT_DESIGNS entry; samples that cannot be placed are left out (and said so for 'study')."""
    clonal = clonal or {}
    samples = list(dict.fromkeys(row["sample"] for row in scores_rows))
    if design == "isolate":
        return {f"isolate:{s}": {s} for s in samples}
    if design == "study":
        return group_samples_by_study(scores_rows, metadata)
    if design == "species":
        out = defaultdict(set)
        for s in samples:
            species = species_of(_text(metadata, s, "organism"))
            if species:
                out[species].add(s)
        return out
    if design == "clonal_group":
        return {**{f"clonal:{g}": {s for s in samples if clonal.get(s) == g} for g in {clonal[s] for s in samples if s in clonal}},
                **{f"isolate:{s}": {s} for s in samples if s not in clonal}}
    if design == "study_and_clonal":
        from plasbench_common import UnionFind
        uf = UnionFind()
        for study, members in group_samples_by_study(scores_rows, metadata).items():
            for s in members:
                uf.union(f"s:{s}", f"study:{study}")
        for s in samples:
            uf.find(f"s:{s}")
            if s in clonal:
                uf.union(f"s:{s}", f"clonal:{clonal[s]}")
        out = defaultdict(set)
        for s in samples:
            out[uf.find(f"s:{s}")].add(s)
        return dict(out)
    raise ValueError(f"unknown holdout design {design!r}; one of {HOLDOUT_DESIGNS}")
