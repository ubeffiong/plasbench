#!/usr/bin/env python3
"""Three-way recommender comparison (plan C2): the feature-conditioned arm, calibration, abstention and the reproducible-advantage rule.

Cohort: 4 studies x 4 isolates. Isolates differ in a truth-free feature (read depth: LOW=20 or HIGH=100). Tool X is best on low-depth
isolates, tool Y on high-depth ones, with the SAME organism on every isolate, so the organism arm cannot tell them apart but the
feature-conditioned arm can. The single best (X and Y tie on average) cannot either.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import characterise_dataset as cd  # noqa: E402
import evaluate_recommender as er  # noqa: E402


def build(tmp, studies=4):
    sheet, scores, feats = "sample_id\tsource_study\torganism\n", "sample\ttool\tf1\n", "\t".join(cd.COLUMNS) + "\n"
    for s in range(studies):
        for i, depth in enumerate((20, 20, 100, 100)):
            sample = f"S{s}_{i}"
            sheet += f"{sample}\tstudy{s}\tE\n"
            for tool, value in (("X", 0.9 if depth == 20 else 0.4), ("Y", 0.4 if depth == 20 else 0.9)):
                scores += f"{sample}\t{tool}\t{value}\n"
            row = {c: "" for c in cd.COLUMNS}
            row.update(sample=sample, read_depth_x=str(depth + i * 0.01), input_assembly_size_bp=str(5_000_000 + 1000 * i), input_gc_percent="50")
            feats += "\t".join(row[c] for c in cd.COLUMNS) + "\n"
    for name, text in (("samples.tsv", sheet), ("scores.tsv", scores), ("features.tsv", feats)):
        (tmp / name).write_text(text)


def run(tmp):
    done = subprocess.run([sys.executable, str(ROOT / "python" / "evaluate_recommender.py"), "--scores", str(tmp / "scores.tsv"), "--samples", str(tmp / "samples.tsv"),
                           "--dataset-features", str(tmp / "features.tsv"), "--out-prefix", str(tmp / "b"), "--min-train-samples", "2"], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-1500:]
    return {(r["profile"], r["arm"]): r for r in er.read_tsv(str(tmp / "b.recommender_arms.tsv"))}


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        build(tmp)
        arms = run(tmp)
        single, organism, feature = arms[("f1", "single_best")], arms[("f1", "organism")], arms[("f1", "feature_conditioned")]
        check("all three arms are reported", len(arms) >= 3)
        check("the single best is the reference", single["verdict"] == "reference")
        check("the organism arm cannot beat the single best when organism says nothing", organism["verdict"] == "no_better", organism)
        check("the feature-conditioned arm finds the tool for each depth and adds value", feature["verdict"] == "adds_value" and float(feature["mean_regret"]) < 1e-9, feature)
        check("it beat the single best in every study", feature["folds_better"] == feature["folds_assessed"] == "4", feature)
        check("calibration and abstention are reported", feature["calibration_mae"] != "" and feature["abstention_rate"] != "")
        import json
        verdict = json.loads((tmp / "b.recommender_verdict.json").read_text())
        check("the verdict JSON enables the feature arm only on reproducible advantage", verdict["feature_conditioned_enabled"] is True and verdict["arms"]["organism"] == "no_better", verdict)

    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        build(tmp, studies=2)
        feature = run(tmp)[("f1", "feature_conditioned")]
        check("with fewer than three studies an arm is not assessed, never declared better", feature["verdict"] == "not_assessed", feature)

    print("the adds-value rule")
    def items(study, regrets, basis="neighbours"):
        return [{"study": study, "regret": r, "predicted": 0.9, "score": 0.9, "best": 1.0, "basis": basis} for r in regrets]
    single = {f"st{i}": 0.30 for i in range(4)}
    good = sum((items(f"st{i}", [0.10, 0.10]) for i in range(4)), [])
    check("a clear gain in every study of two isolates adds value", er.arm_summary("f1", "feature_conditioned", good, single, 0.4, 0.05)["verdict"] == "adds_value")
    tiny = sum((items(f"st{i}", [0.2999, 0.2999]) for i in range(4)), [])
    check("a negligible gain (0.0001) is not value", er.arm_summary("f1", "feature_conditioned", tiny, single, 0.4, 0.05)["verdict"] == "no_better")
    lonely = sum((items(f"st{i}", [0.10]) for i in range(4)), [])
    check("studies of a single isolate do not count: not assessed, however good", er.arm_summary("f1", "feature_conditioned", lonely, single, 0.4, 0.05)["verdict"] == "not_assessed")
    fell_back = sum((items(f"st{i}", [0.10, 0.10], basis="single_best") for i in range(4)), [])
    check("a feature arm that fell back to the single best for most isolates is not assessed, not 'no better'",
          er.arm_summary("f1", "feature_conditioned", fell_back, single, 0.4, 0.05)["verdict"] == "not_assessed" and "fell back" in er.arm_summary("f1", "feature_conditioned", fell_back, single, 0.4, 0.05)["note"])
    check("the share placed by neighbours is reported", er.arm_summary("f1", "feature_conditioned", good, single, 0.4, 0.05)["share_feature_based"] == "1.000")
    with tempfile.TemporaryDirectory() as t2:
        tmp2 = Path(t2)
        build(tmp2)
        (tmp2 / "features.tsv").write_text("\t".join(cd.COLUMNS) + "\n")
        none = run(tmp2)[("f1", "feature_conditioned")]
        check("with no dataset features at all the feature arm is not assessed (it used to read 'no better')", none["verdict"] == "not_assessed" and none["share_feature_based"] == "0.000", none)

    print("the truth-free boundary")
    try:
        er.rm.assert_truth_free(["true_plasmid_count"])
        check("the feature arm refuses a truth-derived feature", False)
    except ValueError:
        check("the feature arm refuses a truth-derived feature", True)
    check("only truth-free numeric features feed the arm", all(f in cd.TRUTH_FREE for f in er.NUMERIC_FEATURES), [f for f in er.NUMERIC_FEATURES if f not in cd.TRUTH_FREE])
    print()
    if not ok:
        print("RECOMMENDER ARM TESTS FAILED")
        sys.exit(1)
    print("ALL RECOMMENDER ARM TESTS PASSED")


if __name__ == "__main__":
    main()
