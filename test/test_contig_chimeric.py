#!/usr/bin/env python3
"""
The CHIMERIC contig label and the `plasmids` column of contig_classification.py, hand-built.

Truth: plasmids P1 and P2 (3000 bp each) and one chromosome (20000 bp). Contigs are 2000 bp, thresholds
min-coverage 0.80, chimeric-min-segment 0.20, identity 0.95.

  c1  0..1000 on P1 and 1000..2000 on the chromosome  plasmid 0.50 + chromosome 0.50, union 1.0 -> CHIMERIC
  c2  0..1900 on P1                                    -> PLASMID, plasmids "P1"
  c3  0..300 on P1 and 300..600 on the chromosome      union 0.30                        -> UNPLACED
  c4  0..1900 on P1 and 0..1900 on P2                  -> PLASMID, plasmids "P1,P2" (a repeat shared by two plasmids)
  c5  0..200 on P1 and 200..2000 on the chromosome     chromosome 0.90                   -> CHROMOSOME
  c6  0..300 on P1 and 300..1600 on the chromosome     0.15 + 0.65, union 0.80, plasmid segment < 0.20 -> UNPLACED
  c7  0..1000 on P1 and 600..1700 on the chromosome    0.50 + 0.55, union 0.85 (segments overlap) -> CHIMERIC

The score subcommand counts the chimeric contigs and their bases separately from UNPLACED: with c1 and c7
excluded, contigs_chimeric = 2 and contigs_chimeric_bp = 4000.
"""

import csv
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "python", "contig_classification.py")


def paf(contig, start, end, target, tlen):
    n = end - start
    return f"{contig}\t2000\t{start}\t{end}\t+\t{target}\t{tlen}\t0\t{n}\t{n}\t{n}\t60\n"


def run(*args):
    done = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)
    if done.returncode:
        raise SystemExit(done.stderr)
    return done


def main():
    ok = True

    def check(label, condition):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}")

    tmp = tempfile.mkdtemp(prefix="chimeric_")
    nl = chr(10)
    with open(os.path.join(tmp, "truth.tsv"), "w") as handle:
        handle.write(nl.join(["sequence_id" + chr(9) + "molecule_type" + chr(9) + "length",
                              "P1" + chr(9) + "PLASMID" + chr(9) + "3000",
                              "P2" + chr(9) + "PLASMID" + chr(9) + "3000",
                              "chr" + chr(9) + "CHROMOSOME" + chr(9) + "20000"]) + nl)
    with open(os.path.join(tmp, "contigs.fasta"), "w") as handle:
        for name in ("c1", "c2", "c3", "c4", "c5", "c6", "c7"):
            handle.write(f">{name}{nl}{'A' * 2000}{nl}")
    with open(os.path.join(tmp, "contigs.paf"), "w") as handle:
        handle.write(paf("c1", 0, 1000, "P1", 3000) + paf("c1", 1000, 2000, "chr", 20000)
                     + paf("c2", 0, 1900, "P1", 3000)
                     + paf("c3", 0, 300, "P1", 3000) + paf("c3", 300, 600, "chr", 20000)
                     + paf("c4", 0, 1900, "P1", 3000) + paf("c4", 0, 1900, "P2", 3000)
                     + paf("c5", 0, 200, "P1", 3000) + paf("c5", 200, 2000, "chr", 20000)
                     + paf("c6", 0, 300, "P1", 3000) + paf("c6", 300, 1600, "chr", 20000)
                     + paf("c7", 0, 1000, "P1", 3000) + paf("c7", 600, 1700, "chr", 20000))
    labels_path = os.path.join(tmp, "labels.tsv")
    run("label", "--contigs", os.path.join(tmp, "contigs.fasta"), "--paf", os.path.join(tmp, "contigs.paf"),
        "--truth", os.path.join(tmp, "truth.tsv"), "--labels-out", labels_path)
    with open(labels_path, newline="") as handle:
        labels = {r["contig"]: r for r in csv.DictReader(handle, delimiter=chr(9))}

    print("labels")
    check("c1 plasmid + chromosome segments -> CHIMERIC", labels["c1"]["label"] == "CHIMERIC")
    check("c2 -> PLASMID", labels["c2"]["label"] == "PLASMID")
    check("c3 short union -> UNPLACED", labels["c3"]["label"] == "UNPLACED")
    check("c4 shared by two plasmids -> PLASMID", labels["c4"]["label"] == "PLASMID")
    check("c5 mostly chromosome -> CHROMOSOME", labels["c5"]["label"] == "CHROMOSOME")
    check("c6 plasmid segment too small -> UNPLACED, not CHIMERIC", labels["c6"]["label"] == "UNPLACED")
    check("c7 overlapping segments with union 0.85 -> CHIMERIC", labels["c7"]["label"] == "CHIMERIC")
    check("the reason names the misjoin", "misjoin" in labels["c1"]["reason"])

    print("plasmids column")
    check("c2 lists P1", labels["c2"]["plasmids"] == "P1")
    check("c4 lists P1 and P2", labels["c4"]["plasmids"] == "P1,P2")
    check("a non-plasmid contig lists none", labels["c5"]["plasmids"] == "" and labels["c1"]["plasmids"] == "")
    check("best_plasmid is unchanged for c4 (single valued)", labels["c4"]["best_plasmid"] in ("P1", "P2"))

    print("the score subcommand counts chimeric contigs separately")
    pred = os.path.join(tmp, "pred.fasta")
    with open(pred, "w") as handle:
        handle.write(f">c2{nl}AAAA{nl}")
    out = os.path.join(tmp, "score.tsv")
    run("score", "--labels", labels_path, "--pred-fasta", pred, "--out", out)
    with open(out, newline="") as handle:
        row = next(csv.DictReader(handle, delimiter=chr(9)))
    check("contigs_chimeric == 2", row["contigs_chimeric"] == "2")
    check("contigs_chimeric_bp == 4000", row["contigs_chimeric_bp"] == "4000")
    check("contigs_unplaced == 2 (c3, c6)", row["contigs_unplaced"] == "2")

    print()
    if not ok:
        print("CHIMERIC CONTIG TESTS FAILED")
        sys.exit(1)
    print("ALL CHIMERIC CONTIG TESTS PASSED")


if __name__ == "__main__":
    main()
