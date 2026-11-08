#!/usr/bin/env python3
"""Regression checks for the auto-derived (draft) AMR truth converter."""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DERIVE = os.path.join(ROOT, "python", "derive_amr_truth.py")
VALIDATE = os.path.join(ROOT, "python", "validate_amr_truth.py")


def run(script, *args):
    return subprocess.run([sys.executable, script, *args], text=True, capture_output=True)


def main():
    with tempfile.TemporaryDirectory() as d:
        truth = os.path.join(d, "truth.tsv")
        features = os.path.join(d, "features.tsv")
        draft = os.path.join(d, "truth_amr.draft.tsv")
        open(truth, "w").write("sequence_id\tmolecule_type\tlength\np1\tPLASMID\t1000\nchr\tCHROMOSOME\t5000\n")
        header = "sequence_id\tstart\tend\tfeature_type\tlabel\tsource\tversion\n"
        open(features, "w").write(header + "\n".join([
            "p1\t10\t200\tamr\tblaCTX-M-15\tamrfinderplus\t4.0.3",
            "p1\t10\t200\tamr\tblaCTX-M-15\tamrfinderplus\t4.0.3",     # duplicate copy
            "p1\t300\t400\tamr\tblaTEM-1\tabricate:ncbi\t1.0",          # other source, skipped
            "chr\t10\t200\tamr\tgyrA_S83L\tamrfinderplus\t4.0.3",       # chromosome, skipped
            "p1\t500\t5000\tamr\tbad\tamrfinderplus\t4.0.3",            # outside plasmid, skipped
            "p1\t600\t700\treplicon\tIncFII\tmob_typer\t3.1",           # not AMR, skipped
        ]) + "\n")

        result = run(DERIVE, "--features", features, "--truth", truth, "--out", draft)
        assert result.returncode == 0, result.stderr
        lines = open(draft).read().splitlines()
        assert len(lines) == 2, lines                                    # header + one deduplicated copy
        assert lines[1].split("\t")[-1] == "auto_derived", lines[1]
        assert "DRAFT ONLY" in result.stderr

        # The draft must satisfy the same validator curated truth does.
        valid = run(VALIDATE, "--truth", truth, "--amr-truth", draft)
        assert valid.returncode == 0, valid.stderr

        # It must refuse to overwrite the name the scorer reads.
        refused = run(DERIVE, "--features", features, "--truth", truth, "--out", os.path.join(d, "truth_amr.tsv"))
        assert refused.returncode != 0 and "truth_amr.tsv" in refused.stderr
        assert not os.path.exists(os.path.join(d, "truth_amr.tsv"))

        # --source widens the kept callers.
        both = os.path.join(d, "both.tsv")
        run(DERIVE, "--features", features, "--truth", truth, "--out", both,
            "--source", "amrfinderplus", "--source", "abricate:ncbi")
        assert len(open(both).read().splitlines()) == 3
    print("ALL DERIVE AMR TRUTH TESTS PASSED")


if __name__ == "__main__":
    main()
