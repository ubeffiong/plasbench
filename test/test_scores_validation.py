#!/usr/bin/env python3
"""Regression for score_plasmids.py's read_pred_scores() validation (the
adapters/SCORES.md contract): an out-of-range probability, a duplicate
record_id, and a record_id set mismatch against --pred-candidates-fasta must
each be flagged with a clear, specific warning -- but, since a malformed
scores/candidates file is an adapter data-quality problem rather than a
caller-contract bug, it must degrade gracefully (skip the curve, keep exit 0
and the point-estimate score) rather than aborting the whole scoring run.
"""
import os
import subprocess
import sys
import tempfile


HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "python", "score_plasmids.py")


def write(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def run(tmp, scores_text, candidates_text="q1\t100\n>q1\nACGT\n"):
    truth = os.path.join(tmp, "truth.tsv")
    write(truth, "sequence_id\tmolecule_type\tlength\nplasmidA\tPLASMID\t100\n")
    candidates_fasta = os.path.join(tmp, "candidates.fasta")
    write(candidates_fasta, ">q1\nACGT\n")
    candidates_paf = os.path.join(tmp, "candidates.paf")
    write(candidates_paf, "q1\t4\t0\t4\t+\tplasmidA\t100\t0\t4\t4\t4\t60\n")
    pred_scores = os.path.join(tmp, "scores.tsv")
    write(pred_scores, scores_text)
    pred_fasta = os.path.join(tmp, "pred.fasta")
    write(pred_fasta, ">q1\nACGT\n")
    paf = os.path.join(tmp, "pred.paf")
    write(paf, "")
    out = os.path.join(tmp, "out.tsv")
    return subprocess.run(
        [sys.executable, SCRIPT, "--truth", truth, "--paf", paf, "--pred-fasta", pred_fasta,
         "--sample", "s1", "--tool", "mltool", "--out", out,
         "--pred-scores", pred_scores, "--pred-candidates-fasta", candidates_fasta,
         "--pred-candidates-paf", candidates_paf],
        text=True, capture_output=True,
    )


def assert_degrades_gracefully(result, expected_message_fragment):
    assert result.returncode == 0, (
        f"a malformed scores/candidates file must not fail the whole run, got rc={result.returncode}: {result.stderr}"
    )
    assert "WARNING: PR-curve sweep skipped" in result.stderr and expected_message_fragment in result.stderr, result.stderr


def main():
    with tempfile.TemporaryDirectory(prefix="scores_validation_") as tmp:
        result = run(tmp, "record_id\tprobability\nq1\t1.5\n")
        assert_degrades_gracefully(result, "must be in [0, 1]")
        print("an out-of-range probability is flagged and gracefully skips the curve -> PASS")

    with tempfile.TemporaryDirectory(prefix="scores_validation_") as tmp:
        result = run(tmp, "record_id\tprobability\nq1\t0.5\nq1\t0.9\n")
        assert_degrades_gracefully(result, "duplicate record_id")
        print("a duplicate record_id is flagged and gracefully skips the curve -> PASS")

    with tempfile.TemporaryDirectory(prefix="scores_validation_") as tmp:
        # q2 is not in candidates.fasta at all (only q1 is).
        result = run(tmp, "record_id\tprobability\nq2\t0.5\n")
        assert_degrades_gracefully(result, "does not match --pred-candidates-fasta")
        print("a record_id absent from --pred-candidates-fasta is flagged and gracefully skips the curve -> PASS")

    with tempfile.TemporaryDirectory(prefix="scores_validation_") as tmp:
        # q1 present in candidates.fasta but never scored -- also a mismatch.
        result = run(tmp, "record_id\tprobability\n")
        assert_degrades_gracefully(result, "does not match --pred-candidates-fasta")
        print("a candidate with no probability row is also flagged and gracefully skips the curve -> PASS")

    with tempfile.TemporaryDirectory(prefix="scores_validation_") as tmp:
        # Missing companion flags is a caller-contract bug, not a data
        # problem -- this one stays a hard failure.
        truth = os.path.join(tmp, "truth.tsv")
        write(truth, "sequence_id\tmolecule_type\tlength\nplasmidA\tPLASMID\t100\n")
        pred_fasta = os.path.join(tmp, "pred.fasta")
        write(pred_fasta, ">q1\nACGT\n")
        paf = os.path.join(tmp, "pred.paf")
        write(paf, "")
        pred_scores = os.path.join(tmp, "scores.tsv")
        write(pred_scores, "record_id\tprobability\nq1\t0.5\n")
        out = os.path.join(tmp, "out.tsv")
        result = subprocess.run(
            [sys.executable, SCRIPT, "--truth", truth, "--paf", paf, "--pred-fasta", pred_fasta,
             "--sample", "s1", "--tool", "mltool", "--out", out, "--pred-scores", pred_scores],
            text=True, capture_output=True,
        )
        assert result.returncode != 0 and "requires --pred-candidates-fasta" in result.stderr, result.stderr
        print("--pred-scores without its companion flags is a hard failure (caller-contract bug) -> PASS")

    print("ALL SCORES VALIDATION TESTS PASSED")


if __name__ == "__main__":
    main()
