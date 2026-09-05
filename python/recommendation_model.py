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
"""

import json

CONTINUOUS_FIELDS = ("read_depth_x", "true_plasmid_bp", "true_plasmid_count")
CATEGORICAL_FIELDS = ("tool", "organism", "gram_group", "amr_status")
TARGETS = ("f1", "plasmid_recall")


def decision_score(f1, precision, recall, plasmid, bin_score, failure_rate, structural_penalty, resource_penalty):
    """The exact formula select_operational_method.py's tool_quality() uses.

    Resource terms are deliberately small; scientific recovery is primary.
    """
    return (.45 * f1 + .13 * precision + .13 * recall + .18 * plasmid
            + .06 * (bin_score if bin_score is not None else 1 - failure_rate)
            - .03 * failure_rate - structural_penalty - resource_penalty)


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
    return {"means": means, "stds": stds, "vocab": vocab}


def encode_row(row, spec):
    """Turn one row (a scores.tsv row, or a live isolate's known fields) into
    a feature vector using a fit-time spec. A missing continuous value is
    imputed with the training mean (documented, standard treatment); an
    unseen category maps to all-zero for its one-hot block (falls back to
    the intercept)."""
    vector = []
    for field in CONTINUOUS_FIELDS:
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
            "schema_version": "1.0", "model_ready": model_ready, "reason": reason,
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
