#!/usr/bin/env python3
"""score_bins.py applies the base scorer's two PAF guards to a user-supplied PAF (audit AU-048).

1. A secondary alignment row (tp:A:S) is ignored, so a repeat cannot claim bases on a second replicon.
   Compared with score_plasmids.py, which ignores the same rows.
2. A target length that disagrees with the truth stops the run (score_plasmids.py raises the same message).
The all-mapping ambiguity PAF is the one place secondary rows ARE read (they are what it measures)."""
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


def run(script, *args):
    return subprocess.run([sys.executable, str(ROOT / "python" / script), *map(str, args)], capture_output=True, text=True)


def summary(tmp, name, paf, *extra):
    done = run("score_bins.py", "--truth", tmp / "truth.tsv", "--paf", paf, "--bins", tmp / "bins.tsv",
               "--out", tmp / f"{name}_m.tsv", "--summary", tmp / f"{name}_s.tsv", *extra)
    if done.returncode:
        return None, done
    with open(tmp / f"{name}_s.tsv", newline="") as handle:
        return next(csv.DictReader(handle, delimiter="\t")), done


with tempfile.TemporaryDirectory() as t:
    tmp = Path(t)
    (tmp / "truth.tsv").write_text("sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t5000\npA\tPLASMID\t1000\n")
    (tmp / "bins.tsv").write_text("sequence_id\tbin_id\nc1\tb1\n")
    (tmp / "pred.fa").write_text(">c1\n" + "A" * 1000 + "\n")
    primary = "c1\t1000\t0\t1000\t+\tpA\t1000\t0\t1000\t1000\t1000\t60\ttp:A:P"
    secondary = "c1\t1000\t0\t1000\t+\tchr\t5000\t100\t1100\t1000\t1000\t0\ttp:A:S"
    (tmp / "primary.paf").write_text(primary + "\n")
    (tmp / "with_secondary.paf").write_text(primary + "\n" + secondary + "\n")

    base, _ = summary(tmp, "base", tmp / "primary.paf")
    sec, done = summary(tmp, "sec", tmp / "with_secondary.paf")
    check("both runs succeed", base is not None and sec is not None, done.stderr[-300:])
    if base and sec:
        check("a secondary row to the chromosome changes no bin score", base == sec, (base, sec))
        check("the ignored secondary row is reported once", "ignored 1 secondary alignment row(s)" in done.stderr, done.stderr)
        check("the bin is still pure plasmid (precision 1.0)", float(sec["bin_precision"]) == 1.0, sec["bin_precision"])

    # The same file through the base scorer: it also ignores the secondary row.
    for name in ("primary", "with_secondary"):
        scored = run("score_plasmids.py", "--truth", tmp / "truth.tsv", "--paf", tmp / f"{name}.paf", "--pred-fasta", tmp / "pred.fa",
                     "--out", tmp / f"sp_{name}.tsv", "--sample", "s", "--tool", "t")
        check(f"score_plasmids.py accepts the {name} PAF (parity check)", scored.returncode == 0, scored.stderr[-300:])

    # Target-length disagreement, plasmid and chromosome targets.
    for target, wrong in (("pA", "c1\t1000\t0\t1000\t+\tpA\t999\t0\t999\t999\t999\t60\ttp:A:P"),
                          ("chr", "c1\t1000\t0\t1000\t+\tchr\t4000\t0\t1000\t1000\t1000\t60\ttp:A:P")):
        (tmp / f"wrong_{target}.paf").write_text(wrong + "\n")
        row, done = summary(tmp, f"wrong_{target}", tmp / f"wrong_{target}.paf")
        check(f"a wrong {target} target length stops score_bins", row is None and "disagrees with truth" in done.stderr, done.stderr[-300:])
    scored = run("score_plasmids.py", "--truth", tmp / "truth.tsv", "--paf", tmp / "wrong_pA.paf", "--pred-fasta", tmp / "pred.fa",
                 "--out", tmp / "sp_wrong.tsv", "--sample", "s", "--tool", "t")
    check("score_plasmids.py refuses the same file with the same message", scored.returncode != 0 and "disagrees with truth" in scored.stderr, scored.stderr[-300:])

    # A row whose query is not in a bin is not checked (nothing to score), matching the early skip.
    (tmp / "unbinned.paf").write_text("zz\t1000\t0\t1000\t+\tpA\t999\t0\t999\t999\t999\t60\ttp:A:P\n")
    row, done = summary(tmp, "unbinned", tmp / "unbinned.paf")
    check("an unbinned query row is skipped before the length check", row is not None, done.stderr[-300:])

    # Ambiguity PAF keeps secondary rows (that is what it measures).
    amb = tmp / "amb.paf"
    amb.write_text("c1\t1000\t0\t1000\t+\tpA\t1000\t0\t1000\t1000\t1000\t0\ttp:A:S\nc1\t1000\t0\t500\t+\tchr\t5000\t0\t500\t500\t500\t0\ttp:A:S\n")
    row, done = summary(tmp, "amb", tmp / "primary.paf", "--ambiguity-paf", amb)
    check("the ambiguity PAF still counts its secondary rows", row is not None and any(
        float(v) > 0 for k, v in row.items() if "ambig" in k and v not in ("", None)), row)

print("ALL SCORE_BINS PAF GUARD TESTS PASSED" if ok else "SCORE_BINS PAF GUARD TESTS FAILED")
sys.exit(0 if ok else 1)
