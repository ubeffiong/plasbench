#!/usr/bin/env python3
"""Regression checks for curated, versioned AMR truth requirements."""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "python", "validate_amr_truth.py")


def main():
    with tempfile.TemporaryDirectory() as directory:
        truth = os.path.join(directory, "truth.tsv"); amr = os.path.join(directory, "truth_amr.tsv")
        open(truth, "w").write("sequence_id\tmolecule_type\tlength\np1\tPLASMID\t100\nchr\tCHROMOSOME\t100\n")
        open(amr, "w").write("sequence_id\tstart\tend\tgene_name\tgene_id\tcopy_id\tdatabase\tdatabase_version\np1\t1\t99\tblaCTX-M-15\tARO:3001878\tcopy_1\tCARD\t3.2.9\n")
        good = subprocess.run([sys.executable, SCRIPT, "--truth", truth, "--amr-truth", amr], text=True, capture_output=True)
        assert good.returncode == 0, good.stderr
        open(amr, "w").write("sequence_id\tstart\tend\tgene_name\np1\t1\t99\tblaCTX-M-15\n")
        bad = subprocess.run([sys.executable, SCRIPT, "--truth", truth, "--amr-truth", amr], text=True, capture_output=True)
        assert bad.returncode != 0 and "database_version" in bad.stderr
    print("ALL AMR TRUTH VALIDATION TESTS PASSED")


if __name__ == "__main__": main()
