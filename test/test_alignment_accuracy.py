#!/usr/bin/env python3
"""alignment_accuracy.py: identity, mismatch, indel rates and missing regions, by hand-computed cases."""
import csv
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "python", "alignment_accuracy.py")


def run(tmp, paf_lines, name):
    truth = os.path.join(tmp, f"{name}.truth.tsv")
    paf = os.path.join(tmp, f"{name}.paf")
    out, regions = os.path.join(tmp, f"{name}.acc.tsv"), os.path.join(tmp, f"{name}.reg.tsv")
    with open(truth, "w") as fh:
        fh.write("sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t9000\np1\tPLASMID\t3000\n")
    with open(paf, "w") as fh:
        fh.write("".join(line + "\n" for line in paf_lines))
    done = subprocess.run([sys.executable, SCRIPT, "--truth", truth, "--paf", paf, "--sample", "s", "--tool", "t",
                           "--out", out, "--regions-out", regions], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    read = lambda p: list(csv.DictReader(open(p, newline=""), delimiter="\t"))
    return read(out)[0], read(regions)[0]


def paf(q, qlen, tname, tstart, tend, matches, block, mapq=60, tags=""):
    return f"{q}\t{qlen}\t0\t{qlen}\t+\t{tname}\t{9000 if tname == 'chr' else 3000}\t{tstart}\t{tend}\t{matches}\t{block}\t{mapq}{tags}"


def close(value, want):
    return value != "" and abs(float(value) - want) < 1e-6


def main():
    ok = True

    def check(label, good):
        nonlocal ok
        print(f"  {label}: {'PASS' if good else 'FAIL'}")
        ok &= bool(good)

    with tempfile.TemporaryDirectory() as tmp:
        # Exact 1000 bp copy: identity 1, nothing else.
        s, r = run(tmp, [paf("a", 1000, "p1", 0, 1000, 1000, 1000, tags="\tNM:i:0\tcg:Z:1000M")], "exact")
        check("exact copy has identity 1 and zero error rates",
              close(s["identity"], 1.0) and close(s["mismatch_rate"], 0.0) and close(s["insertion_rate"], 0.0))

        # 990 M, 5 I, 5 D: 1000 columns; NM=20 -> 10 mismatches. identity 0.98, 0.01, 0.005, 0.005.
        s, r = run(tmp, [paf("a", 995, "p1", 0, 995, 985, 1000, tags="\tNM:i:20\tcg:Z:400M5I5D590M")], "mixed")
        check("mixed block: identity 0.98", close(s["identity"], 0.98))
        check("mixed block: mismatch 0.01, insertion 0.005, deletion 0.005",
              close(s["mismatch_rate"], 0.01) and close(s["insertion_rate"], 0.005) and close(s["deletion_rate"], 0.005))
        check("the four rates sum to 1",
              abs(sum(float(s[k]) for k in ("identity", "mismatch_rate", "insertion_rate", "deletion_rate")) - 1) < 1e-6)

        # =/X operations give the mismatches directly, without NM.
        s, r = run(tmp, [paf("a", 1000, "p1", 0, 1000, 990, 1000, tags="\tcg:Z:500=10X490=")], "eqx")
        check("=/X CIGAR: identity 0.99", close(s["identity"], 0.99) and close(s["mismatch_bp"], 10))

        # No cg tag: counted, never guessed; accuracy is blank (not evaluated), not zero.
        s, r = run(tmp, [paf("a", 1000, "p1", 0, 1000, 1000, 1000)], "nocigar")
        check("no cg tag: blank accuracy, block counted as undecodable",
              s["identity"] == "" and s["n_blocks_without_cigar"] == "1" and s["n_blocks"] == "1")

        # Filtered (low MAPQ) and chromosome-targeted blocks do not contribute.
        s, r = run(tmp, [paf("a", 1000, "p1", 0, 1000, 1000, 1000, mapq=5, tags="\tNM:i:0\tcg:Z:1000M"),
                         paf("b", 1000, "chr", 0, 1000, 1000, 1000, tags="\tNM:i:0\tcg:Z:1000M")], "filtered")
        check("low-MAPQ and chromosome blocks are excluded", s["n_blocks"] == "0" and s["identity"] == "")

        # Missing regions: plasmid 3000 bp, covered [0,1000) and [2000,2500) -> gaps 1000 and 500.
        s, r = run(tmp, [paf("a", 1000, "p1", 0, 1000, 1000, 1000, tags="\tNM:i:0\tcg:Z:1000M"),
                         paf("b", 500, "p1", 2000, 2500, 500, 500, tags="\tNM:i:0\tcg:Z:500M"),
                         paf("c", 400, "p1", 100, 500, 400, 400, tags="\tNM:i:0\tcg:Z:400M")], "gaps")
        check("two missing regions, 1500 bp missing, longest 1000",
              r["missing_regions"] == "2" and r["missing_bp"] == "1500" and r["longest_missing_bp"] == "1000"
              and r["covered_bp"] == "1500")

        # Nothing aligned: one gap spanning the whole plasmid.
        s, r = run(tmp, [], "empty")
        check("empty PAF: one missing region of 3000 bp", r["missing_regions"] == "1" and r["missing_bp"] == "3000")
    print("ALL ALIGNMENT ACCURACY TESTS PASSED" if ok else "ALIGNMENT ACCURACY TESTS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
