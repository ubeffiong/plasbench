#!/usr/bin/env python3
"""bin_quality.py: quality-tier yield and homogeneity/completeness, by hand-computed cases."""
import csv
import math
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "python", "bin_quality.py")
TRUTH = "sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t10000\nP1\tPLASMID\t1000\nP2\tPLASMID\t1000\n"


def run(tmp, name, blocks, bins):
    truth, paf, binf, out = (os.path.join(tmp, f"{name}.{x}") for x in ("truth", "paf", "bins", "out"))
    open(truth, "w").write(TRUTH)
    with open(paf, "w") as fh:
        for q, qlen, target, ts, te in blocks:
            tlen = 10000 if target == "chr" else 1000
            fh.write(f"{q}\t{qlen}\t0\t{qlen}\t+\t{target}\t{tlen}\t{ts}\t{te}\t{te - ts}\t{te - ts}\t60\n")
    open(binf, "w").write("sequence_id\tbin_id\n" + "".join(f"{q}\t{b}\n" for q, b in bins))
    done = subprocess.run([sys.executable, SCRIPT, "--truth", truth, "--paf", paf, "--bins", binf, "--sample", "s",
                           "--tool", "t", "--out", out, "--min-alignment-length", "1",
                           "--min-alignment-identity", "0", "--min-alignment-mapq", "0",
                           "--min-alignment-query-coverage", "0"], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return list(csv.DictReader(open(out, newline=""), delimiter="\t"))[0]


def main():
    ok = True

    def check(label, good):
        nonlocal ok
        print(f"  {label}: {'PASS' if good else 'FAIL'}")
        ok &= bool(good)

    with tempfile.TemporaryDirectory() as tmp:
        # Perfect: each plasmid in its own pure bin.
        r = run(tmp, "perfect", [("a", 1000, "P1", 0, 1000), ("b", 1000, "P2", 0, 1000)], [("a", "b1"), ("b", "b2")])
        check("perfect bins: both high quality, yield 1",
              r["n_high"] == "2" and float(r["high_quality_yield"]) == 1.0 and float(r["medium_or_better_yield"]) == 1.0)
        check("perfect bins: homogeneity, completeness and V-measure are 1",
              all(abs(float(r[k]) - 1) < 1e-9 for k in ("homogeneity", "completeness", "v_measure")))

        # Contaminated: P1 bin = 1000 plasmid bp + 200 chromosome bp -> contamination 1/6 > 0.10 -> low.
        r = run(tmp, "contam", [("a", 1000, "P1", 0, 1000), ("a2", 200, "chr", 0, 200), ("b", 1000, "P2", 0, 1000)],
                [("a", "b1"), ("a2", "b1"), ("b", "b2")])
        check("contamination 0.167 pushes the P1 bin below medium (1 high, 1 low)",
              r["n_high"] == "1" and r["n_low"] == "1" and r["plasmids_with_high_bin"] == "1")
        check("homogeneity falls below 1 when a bin mixes plasmid and chromosome", float(r["homogeneity"]) < 1)

        # Medium: 60% complete, pure.
        r = run(tmp, "medium", [("a", 600, "P1", 0, 600), ("b", 1000, "P2", 0, 1000)], [("a", "b1"), ("b", "b2")])
        check("60% complete, pure bin is medium; medium-or-better yield 1, high yield 0.5",
              r["n_medium"] == "1" and float(r["medium_or_better_yield"]) == 1.0 and float(r["high_quality_yield"]) == 0.5)

        # Merge: one bin holds both plasmids -> best match P1 (or P2), contamination 0.5, low; the other plasmid has no bin.
        r = run(tmp, "merge", [("a", 1000, "P1", 0, 1000), ("b", 1000, "P2", 0, 1000)], [("a", "b1"), ("b", "b1")])
        check("merged plasmids: one low bin, zero plasmids with a medium-or-better bin",
              r["n_low"] == "1" and r["plasmids_with_medium_or_better_bin"] == "0")
        # H(truth|bin)=ln2, H(truth)=ln2 -> homogeneity 0. One bin -> H(bin)=0 -> completeness 1.
        check("merged plasmids: homogeneity 0, completeness 1",
              abs(float(r["homogeneity"])) < 1e-9 and abs(float(r["completeness"]) - 1) < 1e-9)

        # Split: P1 in two half bins -> best bin is 50% complete pure = medium; homogeneity 1, completeness < 1.
        r = run(tmp, "split", [("a", 500, "P1", 0, 500), ("a2", 500, "P1", 500, 1000), ("b", 1000, "P2", 0, 1000)],
                [("a", "b1"), ("a2", "b2"), ("b", "b3")])
        check("split plasmid is judged by its best bin (medium) and homogeneity stays 1",
              r["plasmids_with_medium_or_better_bin"] == "2" and abs(float(r["homogeneity"]) - 1) < 1e-9
              and float(r["completeness"]) < 1)

        # Spurious bin: aligns to nothing on a truth plasmid.
        r = run(tmp, "spurious", [("a", 1000, "P1", 0, 1000)], [("a", "b1"), ("z", "b9")])
        check("a bin with no truth-plasmid alignment is spurious", r["n_spurious"] == "1" and r["n_bins"] == "2")
        check("a missed plasmid (P2) lowers the yield to 0.5", float(r["high_quality_yield"]) == 0.5)

        # No bins at all: yields 0, shape metrics blank (not evaluated).
        r = run(tmp, "nobins", [], [])
        check("no bins: yield 0 and homogeneity blank", float(r["high_quality_yield"]) == 0.0 and r["homogeneity"] == "")
    print("ALL BIN QUALITY TESTS PASSED" if ok else "BIN QUALITY TESTS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
