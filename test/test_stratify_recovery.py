#!/usr/bin/env python3
"""Per-plasmid side file from the scorer, and replicon/MOB stratification."""
import csv
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCORE = os.path.join(ROOT, "python", "score_plasmids.py")
STRAT = os.path.join(ROOT, "python", "stratify_recovery.py")


def run(script, *args):
    return subprocess.run([sys.executable, script, *args], text=True, capture_output=True)


def read(path):
    with open(path, newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def main():
    with tempfile.TemporaryDirectory() as d:
        # Reference: p1 (1000, fully predicted), p2 (1000, half predicted), chr.
        truth = os.path.join(d, "truth.tsv")
        open(truth, "w").write("sequence_id\tmolecule_type\tlength\np1\tPLASMID\t1000\n"
                               "p2\tPLASMID\t1000\nchr\tCHROMOSOME\t5000\n")
        pred = os.path.join(d, "pred.fa")
        open(pred, "w").write(">q1\n" + "A" * 1000 + "\n>q2\n" + "A" * 500 + "\n")
        paf = os.path.join(d, "pred.paf")
        open(paf, "w").write("q1\t1000\t0\t1000\t+\tp1\t1000\t0\t1000\t1000\t1000\t60\n"
                             "q2\t500\t0\t500\t+\tp2\t1000\t0\t500\t500\t500\t60\n")
        results, data = os.path.join(d, "results", "s1"), os.path.join(d, "data", "s1")
        os.makedirs(results); os.makedirs(data)
        per_plasmid = os.path.join(results, "toolA.per_plasmid.tsv")
        scores = os.path.join(d, "scores.tsv")
        done = run(SCORE, "--truth", truth, "--paf", paf, "--pred-fasta", pred, "--sample", "s1",
                   "--tool", "toolA", "--out", scores, "--per-plasmid-out", per_plasmid)
        assert done.returncode == 0, done.stderr
        rows = {r["sequence_id"]: r for r in read(per_plasmid)}
        assert rows["p1"]["completeness"] == "1.0000" and rows["p1"]["recovered"] == "1"
        assert rows["p2"]["completeness"] == "0.5000" and rows["p2"]["recovered"] == "0"

        # The side file must not change scores.tsv.
        baseline = os.path.join(d, "scores_plain.tsv")
        run(SCORE, "--truth", truth, "--paf", paf, "--pred-fasta", pred, "--sample", "s1",
            "--tool", "toolA", "--out", baseline)
        assert open(scores).read() == open(baseline).read()

        # p1 has two replicon labels and one MOB label; p2 has none.
        open(os.path.join(data, "truth_features.tsv"), "w").write(
            "sequence_id\tstart\tend\tfeature_type\tlabel\tsource\tversion\n"
            "p1\t0\t1000\treplicon\tIncFII\tmob_typer\t3\n"
            "p1\t0\t1000\treplicon\tIncFIB\tabricate\t1\n"
            "p1\t0\t1000\tmob\tMOBF\tmob_typer\t3\n")
        out = os.path.join(d, "strat.tsv")
        result = run(STRAT, "--results-dir", os.path.join(d, "results"), "--data-dir",
                     os.path.join(d, "data"), "--out", out, "--min-plasmids", "2")
        assert result.returncode == 0, result.stderr
        strat = {(r["feature_type"], r["label"]): r for r in read(out)}
        assert strat[("replicon", "IncFII")]["n_plasmids"] == "1"
        assert strat[("replicon", "IncFIB")]["recovered_fraction"] == "1.0000"
        assert strat[("replicon", "untyped")]["mean_completeness"] == "0.5000"
        assert strat[("mob", "MOBF")]["underpowered"] == "true"     # n=1 < 2

        # A sample with no annotation file is skipped, never labelled "untyped".
        os.makedirs(os.path.join(d, "results", "s2"))
        open(os.path.join(d, "results", "s2", "toolA.per_plasmid.tsv"), "w").write(
            "sample\ttool\tanalysis_track\tsequence_id\tlength\tcovered_bp\tcompleteness\trecovered\n"
            "s2\ttoolA\tshort_read\tx1\t100\t100\t1.0000\t1\n")
        result = run(STRAT, "--results-dir", os.path.join(d, "results"), "--data-dir",
                     os.path.join(d, "data"), "--out", out)
        assert "1 plasmid row(s) skipped" in result.stderr, result.stderr
        assert strat[("replicon", "untyped")]["n_plasmids"] == "1"
    print("ALL STRATIFY RECOVERY TESTS PASSED")


if __name__ == "__main__":
    main()
