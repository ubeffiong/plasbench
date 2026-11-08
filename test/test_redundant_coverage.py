#!/usr/bin/env python3
"""redundant_pred_bp exposes duplicated predicted coverage without changing F1."""

import csv
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCORE = os.path.join(HERE, "..", "python", "score_plasmids.py")


def write(path, text):
    with open(path, "w", newline="") as handle:
        handle.write(text)


def main():
    ok = True
    with tempfile.TemporaryDirectory(prefix="redundant_cov_") as tmp:
        truth = os.path.join(tmp, "truth.tsv")
        write(truth, "sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t5000\np1\tPLASMID\t1000\n")
        out = os.path.join(tmp, "scores.tsv")
        cases = {
            "single": [("c1", 0, 1000)],
            "duplicate": [("c1", 0, 1000), ("c2", 0, 1000)],
            "partial_overlap": [("c1", 0, 600), ("c2", 400, 1000)],
        }
        for tool, records in cases.items():
            fasta = os.path.join(tmp, f"{tool}.fa")
            paf = os.path.join(tmp, f"{tool}.paf")
            write(fasta, "".join(f">{name}\n{'A' * (end - start)}\n" for name, start, end in records))
            write(paf, "".join(
                f"{name}\t{end - start}\t0\t{end - start}\t+\tp1\t1000\t{start}\t{end}\t{end - start}\t{end - start}\t60\n"
                for name, start, end in records))
            subprocess.run([sys.executable, SCORE, "--truth", truth, "--paf", paf, "--pred-fasta", fasta,
                            "--sample", "s1", "--tool", tool, "--out", out],
                           check=True, capture_output=True, text=True)
        with open(out, newline="") as handle:
            rows = {r["tool"]: r for r in csv.DictReader(handle, delimiter="\t")}
        expected = {"single": "0", "duplicate": "1000", "partial_overlap": "200"}
        for tool, want in expected.items():
            got = rows[tool]["redundant_pred_bp"]
            check = got == want and rows[tool]["f1"] == "1.0000"
            print(f"  {tool}: redundant_pred_bp={got} (want {want}), f1={rows[tool]['f1']} -> {check}")
            ok &= check
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
