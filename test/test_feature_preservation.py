#!/usr/bin/env python3
"""feature_preservation.py: feature recovery (full length vs truncated vs missed) and NGOC, by hand."""
import csv
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "python", "feature_preservation.py")
FEATURES = [("A", 100, 400, "amr"), ("B", 1000, 1300, "replicon"), ("C", 2000, 2300, "mob"), ("D", 3000, 3300, "is")]


def run(tmp, name, blocks, circular=False):
    truth, paf, feats = (os.path.join(tmp, f"{name}.{x}") for x in ("truth", "paf", "feat"))
    out, ngoc_out, circ = (os.path.join(tmp, f"{name}.{x}") for x in ("out", "ngoc", "circ"))
    with open(truth, "w") as fh:
        fh.write("sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t9000\np1\tPLASMID\t10000\n")
    with open(feats, "w") as fh:
        fh.write("sequence_id\tstart\tend\tfeature_type\tlabel\tsource\tversion\n")
        for label, start, end, kind in FEATURES:
            fh.write(f"p1\t{start}\t{end}\t{kind}\t{label}\tx\t1\n")
        fh.write("chr\t10\t200\tamr\tchrGene\tx\t1\n")                  # chromosome feature: ignored
    with open(paf, "w") as fh:
        for q, qlen, qs, qe, strand, ts, te in blocks:
            fh.write(f"{q}\t{qlen}\t{qs}\t{qe}\t{strand}\tp1\t10000\t{ts}\t{te}\t{te - ts}\t{te - ts}\t60\n")
    args = [sys.executable, SCRIPT, "--truth", truth, "--paf", paf, "--features", feats, "--sample", "s",
            "--tool", "t", "--out", out, "--ngoc-out", ngoc_out]
    if circular:
        with open(circ, "w") as fh:
            fh.write("sequence_id\np1\n")
        args += ["--circular-plasmids", circ]
    done = subprocess.run(args, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    read = lambda p: list(csv.DictReader(open(p, newline=""), delimiter="\t"))
    return {r["feature_kind"]: r for r in read(out)}, read(ngoc_out)[0]


def main():
    ok = True

    def check(label, good):
        nonlocal ok
        print(f"  {label}: {'PASS' if good else 'FAIL'}")
        ok &= bool(good)

    with tempfile.TemporaryDirectory() as tmp:
        whole = [("q1", 10000, 0, 10000, "+", 0, 10000)]
        pres, ng = run(tmp, "perfect", whole)
        check("perfect: all four features full length, chromosome feature ignored",
              pres["all"]["n_expected"] == "4" and pres["all"]["n_full_length"] == "4")
        check("perfect: NGOC 1 over 3 adjacent pairs", ng["n_pairs"] == "3" and float(ng["ngoc"]) == 1.0)

        pres, ng = run(tmp, "circ", whole, circular=True)
        check("circular truth adds the last-first pair and it is conserved (4 of 4)",
              ng["n_pairs"] == "4" and ng["n_conserved"] == "4")

        pres, ng = run(tmp, "reverse", [("q1", 10000, 0, 10000, "-", 0, 10000)])
        check("whole plasmid on the opposite strand conserves order (NGOC 1)", float(ng["ngoc"]) == 1.0)

        pres, ng = run(tmp, "split", [("q1", 2500, 0, 2500, "+", 0, 2500), ("q2", 7500, 0, 7500, "+", 2500, 10000)])
        check("split across two records breaks only the pair that spans them (2 of 3)",
              ng["n_conserved"] == "2" and ng["n_pairs"] == "3")

        pres, ng = run(tmp, "inverted", [("q1", 3500, 0, 1500, "+", 0, 1500), ("q1", 3500, 1500, 3500, "-", 1500, 3500)])
        check("an inverted segment breaks the pair across the junction but not the pair inside it (2 of 3)",
              ng["n_conserved"] == "2")

        pres, ng = run(tmp, "missed", [("q1", 900, 0, 900, "+", 0, 900), ("q1", 8600, 900, 9500, "+", 1400, 10000)])
        check("a missed feature breaks both its pairs (1 of 3)",
              ng["n_conserved"] == "1" and pres["replicon"]["n_missed"] == "1")

        pres, ng = run(tmp, "trunc", [("q1", 1150, 0, 1150, "+", 0, 1150)])
        check("half-covered B is truncated, not recovered; C and D are missed",
              pres["replicon"]["n_truncated"] == "1" and pres["replicon"]["n_full_length"] == "0"
              and pres["mobility"]["n_missed"] == "1" and pres["amr"]["n_full_length"] == "1")
        check("mean covered fraction is reported per kind",
              abs(float(pres["replicon"]["mean_covered_fraction"]) - 0.5) < 1e-6)
        check("full-length rate over all features is 1 of 4", float(pres["all"]["full_length_rate"]) == 0.25)

        # No features at all: nothing is written (not evaluated, never zero).
        empty_feats = os.path.join(tmp, "none.feat")
        open(empty_feats, "w").write("sequence_id\tstart\tend\tfeature_type\tlabel\nchr\t1\t5\tamr\tx\n")
        out = os.path.join(tmp, "none.out")
        subprocess.run([sys.executable, SCRIPT, "--truth", os.path.join(tmp, "perfect.truth"),
                        "--paf", os.path.join(tmp, "perfect.paf"), "--features", empty_feats, "--sample", "s",
                        "--tool", "t", "--out", out], check=True, capture_output=True)
        check("no feature on a truth plasmid: nothing written", not os.path.exists(out))
    print("ALL FEATURE PRESERVATION TESTS PASSED" if ok else "FEATURE PRESERVATION TESTS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
