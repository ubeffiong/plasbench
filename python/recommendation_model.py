#!/usr/bin/env python3
"""Shared pure-stdlib toolkit for the decision-support recommendation model.

No new dependency: a hand-rolled ridge regression (closed-form normal
equations via Gauss-Jordan elimination on plain Python lists), used to
predict a candidate tool's F1/plasmid_recall from an isolate's own features
rather than a discrete stratum mean. Deliberately simple and auditable --
the whole point of this feature is a better-fit set of weights a human can
still inspect, not a black-box model.

Also carries decision_score(): the exact multi-objective weighted-sum
formula select_operational_method.py's tool_quality() has always used,
extracted here so both the stratified-table path and the live per-isolate
prediction path (select_unknown_sample.py) call the same one implementation
rather than risking two hand-copied formulas drifting apart.

Note: RUN_RECOMMENDATION_MODEL defaults to 0 and fit_recommendation_model.py
only ever sets model_ready=true once RECOMMENDATION_MODEL_MIN_STUDIES
independent source_study groups show a genuine leave-one-study-out
improvement -- see docs/USER_GUIDE.md's "Decision-support recommendation
model" section for why that keeps this file inactive on the shipped cohorts
regardless of when it was written relative to the cohort's own growth.
"""

import csv
import json
from pathlib import Path

# Per-isolate assembly statistics, computed fresh from the reference by
# python/compute_assembly_stats.py during stage 2 and written to
# data/<sample>/assembly_stats.tsv. These were originally computed only for
# the advisory cohort-QC outlier flagger; feeding them to the model as well is
# the point of having continuous features at all -- GC content and assembly
# fragmentation plausibly bear on which reconstruction method wins, and the
# model can learn its own splits on them rather than being handed a fixed
# band. Absent for a live isolate that has no reference assembly (operational
# mode): encode_row() imputes any missing continuous field with the training
# mean, so a sample without stats simply falls back to average behaviour on
# those axes instead of being unusable.
ASSEMBLY_STAT_FIELDS = ("gc_percent", "n50", "contig_count", "assembly_size_bp")
SCORE_CONTINUOUS_FIELDS = ("read_depth_x", "true_plasmid_bp", "true_plasmid_count")
CONTINUOUS_FIELDS = SCORE_CONTINUOUS_FIELDS + ASSEMBLY_STAT_FIELDS
# Models fitted before assembly stats were added stored three continuous
# fields and no explicit field list. Their coefficient vectors are laid out in
# this order, so an old JSON must be decoded against it -- see encode_row().
LEGACY_CONTINUOUS_FIELDS = SCORE_CONTINUOUS_FIELDS
CATEGORICAL_FIELDS = ("tool", "organism", "gram_group", "amr_status")
TARGETS = ("f1", "plasmid_recall")


def load_assembly_stats(data_dir):
    """Read every data/<sample>/assembly_stats.tsv into {sample_id: {field: value}}.

    Missing files are simply absent from the result (a cohort predating this
    feature, or a sample whose stage 2 did not run) -- never an error.
    """
    stats = {}
    if not data_dir:
        return stats
    for path in sorted(Path(data_dir).glob("*/assembly_stats.tsv")):
        try:
            with open(path, newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle, delimiter="	"):
                    sample = (row.get("sample_id") or path.parent.name).strip()
                    if sample:
                        stats[sample] = {field: row.get(field) for field in ASSEMBLY_STAT_FIELDS}
        except (OSError, csv.Error):
            continue
    return stats


def attach_assembly_stats(rows, stats):
    """Copy each row's own sample's assembly stats onto it, in place.

    A row whose sample has no stats is left untouched; encode_row() then
    imputes those fields with the training mean.
    """
    if not stats:
        return rows
    for row in rows:
        for field, value in stats.get(row.get("sample", ""), {}).items():
            row.setdefault(field, value)
    return rows


# Named alternate weight sets for decision_score(), a rules-only improvement
# (no ML): different research/operational contexts genuinely value the same
# measured outcomes differently, and a single hidden formula can't express
# that. "accuracy_first" is the exact original formula, unchanged, and stays
# the default -- selecting a profile is opt-in, never a behavior change by
# default. amr_surveillance/rapid_screening reweight the EXISTING terms this
# formula already receives; they do not invent new inputs (e.g. no isolate-
# level "AMR evidence present" signal is fed to this function today), so
# read them as an approximation of those priorities via what's actually
# measured, not a literal AMR-specific rule.
DECISION_PROFILES = {
    "accuracy_first": {  # today's original, unchanged formula
        "f1": .45, "precision": .13, "recall": .13, "plasmid": .18, "bin_or_fallback": .06,
        "failure_rate": -.03, "structural_penalty_scale": 1.0, "resource_penalty_scale": 1.0,
    },
    "amr_surveillance": {  # missing a plasmid (and so its AMR context) is the
        # worst outcome for a surveillance program; a failed/skipped run is
        # also less tolerable than for routine benchmarking.
        "f1": .30, "precision": .10, "recall": .10, "plasmid": .35, "bin_or_fallback": .10,
        "failure_rate": -.08, "structural_penalty_scale": 1.0, "resource_penalty_scale": 1.0,
    },
    "rapid_screening": {  # tolerant of lower F1 for speed; resource_penalty's
        # weight is raised well above every other profile's.
        "f1": .35, "precision": .10, "recall": .10, "plasmid": .15, "bin_or_fallback": .05,
        "failure_rate": -.03, "structural_penalty_scale": 1.0, "resource_penalty_scale": 5.0,
    },
}
DEFAULT_DECISION_PROFILE = "accuracy_first"


def decision_score(f1, precision, recall, plasmid, bin_score, failure_rate, structural_penalty, resource_penalty,
                   profile=DEFAULT_DECISION_PROFILE):
    """The multi-objective weighted-sum formula select_operational_method.py's
    tool_quality() uses. profile picks a named weight set from
    DECISION_PROFILES (see above); the default reproduces the original,
    single hand-picked formula exactly, byte-for-byte, when omitted.
    """
    weights = DECISION_PROFILES[profile]
    return (weights["f1"] * f1 + weights["precision"] * precision + weights["recall"] * recall
            + weights["plasmid"] * plasmid
            + weights["bin_or_fallback"] * (bin_score if bin_score is not None else 1 - failure_rate)
            + weights["failure_rate"] * failure_rate
            - weights["structural_penalty_scale"] * structural_penalty
            - weights["resource_penalty_scale"] * resource_penalty)


# --- Minimal pure-Python linear algebra (no numpy) --------------------------

def _transpose(matrix):
    return [list(col) for col in zip(*matrix)]


def _matmul(a, b):
    b_t = _transpose(b)
    return [[sum(x * y for x, y in zip(row, col)) for col in b_t] for row in a]


def _matvec(a, v):
    return [sum(x * y for x, y in zip(row, v)) for row in a]


def _invert(matrix):
    """Gauss-Jordan inversion with partial pivoting. Raises ValueError on a
    singular (or near-singular) matrix -- e.g. too few training rows relative
    to feature count, or a redundant one-hot column -- rather than returning
    a garbage result."""
    n = len(matrix)
    augmented = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot_row = max(range(col, n), key=lambda r: abs(augmented[r][col]))
        if abs(augmented[pivot_row][col]) < 1e-9:
            raise ValueError("singular matrix; cannot invert (too few training rows, or a redundant feature)")
        augmented[col], augmented[pivot_row] = augmented[pivot_row], augmented[col]
        pivot = augmented[col][col]
        augmented[col] = [x / pivot for x in augmented[col]]
        for r in range(n):
            if r != col:
                factor = augmented[r][col]
                augmented[r] = [a - factor * b for a, b in zip(augmented[r], augmented[col])]
    return [row[n:] for row in augmented]


def solve_ridge(features, targets, lambda_):
    """Closed-form ridge regression: (X^T X + lambda*I) beta = X^T y, with an
    unregularized intercept prepended. features: list of feature vectors
    (no intercept column). targets: list of floats, same length.
    Returns (intercept, coefficients)."""
    if not features:
        raise ValueError("no training rows")
    design = [[1.0] + list(row) for row in features]
    width = len(design[0])
    design_t = _transpose(design)
    gram = _matmul(design_t, design)
    for i in range(1, width):  # never regularize the intercept (index 0)
        gram[i][i] += lambda_
    design_t_y = _matvec(design_t, targets)
    inverse = _invert(gram)
    beta = _matvec(inverse, design_t_y)
    return beta[0], beta[1:]


def mean_absolute_error(predicted, actual):
    if not predicted:
        return None
    return sum(abs(p - a) for p, a in zip(predicted, actual)) / len(predicted)


# --- Feature encoding --------------------------------------------------------

def _as_float(value):
    """Score rows carry raw CSV string values for fields annotate() didn't
    explicitly convert (e.g. true_plasmid_bp/true_plasmid_count); only
    read_depth_x is pre-converted. Accept either transparently."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fit_feature_spec(rows):
    """Learn training-set feature means/stds (continuous) and vocabulary
    (categorical) from a list of annotated score rows. Stored in the model so
    prediction-time encoding matches fit-time encoding exactly."""
    means, stds = {}, {}
    for field in CONTINUOUS_FIELDS:
        values = [value for row in rows if (value := _as_float(row.get(field))) is not None]
        mean = sum(values) / len(values) if values else 0.0
        variance = sum((v - mean) ** 2 for v in values) / len(values) if values else 0.0
        means[field] = mean
        stds[field] = variance ** 0.5 or 1.0  # avoid division by zero for a constant field
    vocab = {}
    for field in CATEGORICAL_FIELDS:
        vocab[field] = sorted({str(row.get(field) or "not_recorded") for row in rows})
    # Record the exact ordered field list this spec was fitted with. The
    # module constant can grow (it did, when assembly stats were added); a
    # serialized model must keep decoding against the layout its coefficients
    # were actually fitted in.
    return {"continuous": list(CONTINUOUS_FIELDS), "means": means, "stds": stds, "vocab": vocab}


def spec_continuous_fields(spec):
    """The continuous fields this spec was fitted with, in coefficient order.

    New specs carry the list explicitly. A spec written before assembly stats
    existed has no "continuous" key, and its coefficients are laid out in the
    three-field legacy order -- decode it that way rather than against the
    current, longer module constant, which would silently misalign every
    coefficient after the third.
    """
    return spec.get("continuous") or list(LEGACY_CONTINUOUS_FIELDS)


def encode_row(row, spec):
    """Turn one row (a scores.tsv row, or a live isolate's known fields) into
    a feature vector using a fit-time spec. A missing continuous value is
    imputed with the training mean (documented, standard treatment); an
    unseen category maps to all-zero for its one-hot block (falls back to
    the intercept)."""
    vector = []
    for field in spec_continuous_fields(spec):
        value = _as_float(row.get(field))
        value = spec["means"][field] if value is None else value
        vector.append((value - spec["means"][field]) / spec["stds"][field])
    for field in CATEGORICAL_FIELDS:
        value = str(row.get(field) or "not_recorded")
        vector.extend(1.0 if value == category else 0.0 for category in spec["vocab"][field])
    return vector


class RecommendationModel:
    def __init__(self, spec, fits, lambda_by_target, loso_mae, baseline_mae, n_training_rows, n_studies):
        self.spec = spec
        self.fits = fits  # {target: (intercept, coefficients)}
        self.lambda_by_target = lambda_by_target
        self.loso_mae = loso_mae
        self.baseline_mae = baseline_mae
        self.n_training_rows = n_training_rows
        self.n_studies = n_studies

    def predict(self, target, row):
        intercept, coefficients = self.fits[target]
        vector = encode_row(row, self.spec)
        return intercept + sum(c * v for c, v in zip(coefficients, vector))

    def to_dict(self, model_ready, reason):
        return {
            "schema_version": "1.2", "model_ready": model_ready, "reason": reason,
            "n_training_rows": self.n_training_rows, "n_studies": self.n_studies,
            "spec": self.spec,
            "targets": {
                target: {
                    "lambda": self.lambda_by_target[target],
                    "intercept": self.fits[target][0], "coefficients": self.fits[target][1],
                    "loso_mean_absolute_error": self.loso_mae.get(target),
                    "baseline_loso_mean_absolute_error": self.baseline_mae.get(target),
                } for target in TARGETS
            },
        }

    @classmethod
    def from_dict(cls, payload):
        fits = {target: (info["intercept"], info["coefficients"]) for target, info in payload["targets"].items()}
        lambda_by_target = {target: info["lambda"] for target, info in payload["targets"].items()}
        loso_mae = {target: info.get("loso_mean_absolute_error") for target, info in payload["targets"].items()}
        baseline_mae = {target: info.get("baseline_loso_mean_absolute_error") for target, info in payload["targets"].items()}
        return cls(payload["spec"], fits, lambda_by_target, loso_mae, baseline_mae,
                  payload.get("n_training_rows", 0), payload.get("n_studies", 0))


def load_model(path):
    """Read a fit_recommendation_model.py JSON artifact.

    Returns (model_or_None, model_ready, reason). model is None whenever
    model_ready is False (or the file is absent/unreadable) -- callers must
    check model_ready before calling .predict(), never construct a model
    from a not-ready payload."""
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError):
        return None, False, "recommendation model file unavailable or unreadable"
    ready = bool(payload.get("model_ready"))
    reason = payload.get("reason", "")
    return (RecommendationModel.from_dict(payload) if ready else None), ready, reason
