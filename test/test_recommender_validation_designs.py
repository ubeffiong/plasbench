#!/usr/bin/env python3
"""Recommender validation beyond leave-one-study-out (second review, sections 3 and 6).

  - the distance: robust scaling (median / MAD), a penalty for a feature one isolate has and the other lacks;
  - taxonomy: when two species have the same numeric features but different best tools, the numeric arm cannot separate them and
    the taxonomy-aware arms can; the hierarchical arm falls back from species to genus to Gram group;
  - abstention: an isolate far outside the training data is not recommended from neighbours (out of range), never a forced answer;
  - uncertainty: each neighbour recommendation carries the spread of the neighbours' scores and how many studies they come from;
  - validation designs: isolate, study, clonal group, study and clonal together, species, side by side; an arm is enabled only when it
    adds value under the strictest design the run can build;
  - sensitivity to K, scaling, missingness, abstention and each feature left out; feature correlation flags redundant features.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import characterise_dataset as cd  # noqa: E402
import evaluate_recommender as er  # noqa: E402
import study_groups as sg  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}: {name}" + (f" ({detail})" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


def build(tmp, studies=4, clonal=False):
    """Every study holds two E. coli and two K. pneumoniae isolates with the SAME numeric features; X is best on E. coli and Y on
    Klebsiella. N50 and contig count move together (redundant)."""
    sheet = "sample_id\tsource_study\torganism\tgram_group\n"
    scores, feats = "sample\ttool\tf1\n", "\t".join(cd.COLUMNS) + "\n"
    groups = "sample\tclonal_group\n"
    for s in range(studies):
        for i, organism in enumerate(("Escherichia coli", "Escherichia coli", "Klebsiella pneumoniae", "Klebsiella pneumoniae")):
            sample = f"S{s}_{i}"
            sheet += f"{sample}\tstudy{s}\t{organism}\tnegative\n"
            ecoli = organism.startswith("Escherichia")
            for tool, value in (("X", 0.9 if ecoli else 0.4), ("Y", 0.4 if ecoli else 0.9)):
                scores += f"{sample}\t{tool}\t{value}\n"
            row = {c: "" for c in cd.COLUMNS}
            k = s * 4 + i
            row.update(sample=sample, read_depth_x=str(50 + (k % 3)), input_assembly_size_bp=str(5_000_000 + 1000 * (k % 5)),
                       input_gc_percent="50", input_n50=str(100_000 + 1000 * k), input_contig_count=str(200 - k))
            feats += "\t".join(row[c] for c in cd.COLUMNS) + "\n"
            groups += f"{sample}\t{'CG_' + organism.split()[0] if clonal and s < 2 else 'isolate:' + sample}\n"
    for name, text in (("samples.tsv", sheet), ("scores.tsv", scores), ("features.tsv", feats), ("clonal.tsv", groups)):
        (tmp / name).write_text(text)


def run(tmp, *extra):
    done = subprocess.run([sys.executable, str(ROOT / "python" / "evaluate_recommender.py"), "--scores", str(tmp / "scores.tsv"),
                           "--samples", str(tmp / "samples.tsv"), "--dataset-features", str(tmp / "features.tsv"),
                           "--out-prefix", str(tmp / "b"), "--min-train-samples", "2", *extra], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-1500:]
    return {(r["profile"], r["arm"]): r for r in er.read_tsv(str(tmp / "b.recommender_arms.tsv"))}


def main():
    print("the distance")
    scale = {"a": (0.0, 1.0), "b": (0.0, 1.0), "c": (0.0, 1.0)}
    check("missing on one side costs a penalty", er.distance({"a": 0, "b": 0, "c": 0}, {"a": 0, "b": 0}, scale) > 0
          and er.distance({"a": 0, "b": 0, "c": 0}, {"a": 0, "b": 0}, scale, missing_penalty=0.0) == 0)
    check("fewer than two shared features: no distance", er.distance({"a": 1}, {"a": 1, "b": 2}, scale) is None)
    feats = {f"s{i}": {"read_depth_x": v} for i, v in enumerate((10, 11, 12, 13, 500))}
    robust = er.standardise(feats, list(feats), "robust", ("read_depth_x",))["read_depth_x"]
    standard = er.standardise(feats, list(feats), "standard", ("read_depth_x",))["read_depth_x"]
    check("robust scaling is not dragged by one extreme depth", robust[0] == 12 and robust[1] < standard[1], (robust, standard))

    print("taxonomy")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        build(tmp)
        arms = run(tmp)
        numeric, taxonomy, hierarchical = (arms[("f1", a)] for a in ("feature_conditioned", "taxonomy_knn", "hierarchical_knn"))
        check("all five arms are reported", {a for p, a in arms if p == "f1"} == set(er.ARMS))
        check("numeric features alone cannot separate the species", numeric["verdict"] != "adds_value", numeric)
        check("the taxonomy-aware arm finds each species' tool and adds value", taxonomy["verdict"] == "adds_value" and float(taxonomy["improvement_over_single_best"]) > 0.1, taxonomy)
        knn_rows = er.read_tsv(str(tmp / "b.recommender_knn.tsv"))
        placed = [r for r in knn_rows if r["arm"] == "taxonomy_knn" and r["basis"].startswith("neighbours")]
        check("every isolate it placed by neighbours got its species' best tool (zero regret)", placed and all(float(r["regret"]) < 1e-9 for r in placed))
        check("isolates outside the training range abstained instead (the last study's assembly statistics are beyond the others')",
              float(taxonomy["share_out_of_range"]) > 0 and all(r["in_range"] == "no" for r in knn_rows if r["arm"] == "taxonomy_knn" and r["basis"] == "abstain_out_of_range"))
        check("the hierarchical arm too", hierarchical["verdict"] == "adds_value", hierarchical)
        knn = er.read_tsv(str(tmp / "b.recommender_knn.tsv"))
        check("every neighbour recommendation carries its uncertainty, studies and range",
              knn and all(r["n_neighbour_studies"] != "" and r["in_range"] in ("yes", "no", "unknown") for r in knn), knn[:1])
        check("the hierarchical arm says which level placed it", any(r["basis"] == "neighbours:species" for r in knn if r["arm"] == "hierarchical_knn"))
        verdict = json.loads((tmp / "b.recommender_verdict.json").read_text())
        check("the verdict lists every arm's enablement", set(verdict["arms_enabled"]) == {"organism", *er.KNN_ARMS} and verdict["arms_enabled"]["taxonomy_knn"] is True, verdict)
        check("without clonal groups the strictest holdout is the study", verdict["strictest_holdout"] == "study")

        print("validation designs")
        holdouts = er.read_tsv(str(tmp / "b.recommender_holdouts.tsv"))
        designs = {r["design"] for r in holdouts}
        check("every design is reported", designs == set(sg.HOLDOUT_DESIGNS), designs)
        check("clonal designs say why they are not assessed without clonal groups",
              all(r["verdict"] == "not_assessed" and "clonal" in r["note"] for r in holdouts if r["design"] in ("clonal_group", "study_and_clonal")))
        species = {r["arm"]: r for r in holdouts if r["design"] == "species"}
        check("leave-one-species-out: an unseen species gets no same-species neighbour, so the taxonomy arm cannot help there",
              species["taxonomy_knn"]["verdict"] != "adds_value", species.get("taxonomy_knn"))

        print("sensitivity and correlation")
        sens = er.read_tsv(str(tmp / "b.recommender_sensitivity.tsv"))
        check("K, scaling, missingness, abstention and each dropped feature", {r["analysis"] for r in sens} == {"k", "scaling", "missing_penalty", "drop_feature", "abstain_out_of_range"}
              and {r["setting"] for r in sens if r["analysis"] == "drop_feature"} == set(er.NUMERIC_FEATURES), sens[:2])
        corr = {(r["feature_a"], r["feature_b"]): r for r in er.read_tsv(str(tmp / "b.recommender_feature_correlation.tsv"))}
        pair = corr.get(("input_n50", "input_contig_count")) or corr.get(("input_contig_count", "input_n50"))
        check("N50 and contig count are flagged as largely the same information", pair and float(pair["spearman"]) <= -0.8 and "same information" in pair["note"], pair)

    print("clonal holdouts")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        build(tmp, clonal=True)
        run(tmp, "--clonal-groups", str(tmp / "clonal.tsv"))
        verdict = json.loads((tmp / "b.recommender_verdict.json").read_text())
        check("with clonal groups the strictest holdout is study and clonal group together", verdict["strictest_holdout"] == "study_and_clonal", verdict)
        holdouts = er.read_tsv(str(tmp / "b.recommender_holdouts.tsv"))
        clonal = [r for r in holdouts if r["design"] == "study_and_clonal" and r["arm"] == "single_best"]
        study = [r for r in holdouts if r["design"] == "study" and r["arm"] == "single_best"]
        check("joining clonal isolates across studies leaves fewer, larger held-out groups", clonal and study and int(clonal[0]["n_groups"]) < int(study[0]["n_groups"]),
              (clonal, study))

    print("abstention out of range")
    train = [f"t{i}" for i in range(8)]
    features = {s: {"read_depth_x": 50 + i, "input_gc_percent": 50 + i * 0.1} for i, s in enumerate(train)}
    features["far"] = {"read_depth_x": 5000, "input_gc_percent": 80}
    features["near"] = {"read_depth_x": 53.5, "input_gc_percent": 50.35}
    table = {s: {"X": 0.9, "Y": 0.5} for s in features}
    rows = er.feature_arm(table, {"held": {"far", "near"}}, features, 2, 0.05, 0.4)
    by = {r["sample"]: r for r in rows}
    check("an isolate far outside the training data abstains (single best, marked out of range)",
          by["far"]["in_range"] == "no" and by["far"]["basis"] == "abstain_out_of_range", by["far"])
    check("one inside the range is placed by its neighbours", by["near"]["in_range"] == "yes" and by["near"]["basis"] == "neighbours", by["near"])

    print("ALL RECOMMENDER VALIDATION DESIGN TESTS PASSED" if not FAILED else f"RECOMMENDER VALIDATION DESIGN TESTS FAILED: {FAILED}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
