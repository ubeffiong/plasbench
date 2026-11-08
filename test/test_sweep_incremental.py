#!/usr/bin/env python3
"""score_plasmids.sweep_thresholds is incremental (O(E log E)). It must return
exactly what the original rebuild-per-threshold algorithm returned, so this test
keeps that original as a reference and compares every point on random inputs
(tied probabilities, touching/nested/duplicate intervals, intervals clipped at
the target length, records with no alignment)."""
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))
import score_plasmids as sp  # noqa: E402


def reference_sweep(covered_by_query, probabilities, truth, total_plasmid):
    thresholds = sorted(set(probabilities.values()), reverse=True)
    points = [{"threshold": "inf", "precision": 1.0, "recall": 0.0,
               "tp_bp": 0, "fp_bp": 0, "fn_bp": total_plasmid}]
    for threshold in thresholds:
        included = {q for q, p in probabilities.items() if p >= threshold}
        covered_subset = sp.filter_covered_by_qname(covered_by_query, included)
        tp, fp, fn = sp.score(truth, total_plasmid, covered_subset)
        points.append({"threshold": threshold, "precision": sp.safe_div(tp, tp + fp),
                       "recall": sp.safe_div(tp, tp + fn), "tp_bp": tp, "fp_bp": fp, "fn_bp": fn})
    return points


def random_case(rng):
    n_targets = rng.randint(1, 5)
    truth = {f"t{i}": (rng.choice(["PLASMID", "CHROMOSOME"]), rng.randint(1, 400)) for i in range(n_targets)}
    total_plasmid = sum(length for mol, length in truth.values() if mol == "PLASMID")
    n_records = rng.randint(0, 25)
    probabilities = {f"q{i}": rng.choice([0.0, 0.25, 0.5, 1.0, round(rng.random(), 3)]) for i in range(n_records)}
    covered_by_query = {name: [] for name in truth}
    for _ in range(rng.randint(0, 60)):
        target = rng.choice(list(truth))
        length = truth[target][1]
        start = rng.randint(0, length)
        end = min(length, start + rng.choice([0, 1, 2, 5, 20, 100, 500]))   # includes zero-length, clipped
        covered_by_query[target].append((f"q{rng.randrange(max(1, n_records))}", start, end))
    return covered_by_query, probabilities, truth, total_plasmid


def main():
    rng = random.Random(20261108)
    for case in range(4000):
        args = random_case(rng)
        assert sp.sweep_thresholds(*args) == reference_sweep(*args), f"case {case} differs: {args}"
    # Records scored but absent from covered_by_query, and no records at all.
    truth = {"p": ("PLASMID", 100)}
    assert sp.sweep_thresholds({}, {"a": 0.9}, truth, 100) == reference_sweep({}, {"a": 0.9}, truth, 100)
    assert sp.sweep_thresholds({}, {}, truth, 100) == reference_sweep({}, {}, truth, 100)
    print("sweep_thresholds incremental == reference on 4000 random cases: OK")


if __name__ == "__main__":
    main()
