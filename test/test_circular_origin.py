#!/usr/bin/env python3
"""A faithful reconstruction of a circular plasmid may start anywhere on the circle.

The predicted record is the 3000 bp plasmid rotated by 1200 bp, so it wraps the
origin of the reference. Base-level scoring must still give recall 1.0 and no
false positives, and the structural caller should not report a deletion,
duplication or relocation for a pure origin rotation.
"""
import csv
import random
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
random.seed(7)
PLASMID = "".join(random.choice("ACGT") for _ in range(3000))
ROT = 1200
PRED = PLASMID[ROT:] + PLASMID[:ROT]
assert PRED[:1800] == PLASMID[1200:3000] and PRED[1800:] == PLASMID[:1200]

with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    (d / "truth.tsv").write_text("sequence_id\tmolecule_type\tlength\npl1\tPLASMID\t3000\nchr1\tCHROMOSOME\t5000\n")
    (d / "pred.fasta").write_text(f">rot\n{PRED}\n")
    paf = [("rot", 3000, 0, 1800, "+", "pl1", 3000, 1200, 3000, 1800, 1800, 60, "tp:A:P"),
           ("rot", 3000, 1800, 3000, "+", "pl1", 3000, 0, 1200, 1200, 1200, 60, "tp:A:P")]
    pred_dir = d / "results" / "S1"
    pred_dir.mkdir(parents=True)
    paf_path = pred_dir / "tool.pred_vs_ref.paf"
    paf_path.write_text("".join("\t".join(map(str, row)) + "\n" for row in paf))

    out = d / "scores.tsv"
    r = subprocess.run([sys.executable, str(ROOT / "python" / "score_plasmids.py"), "--truth", str(d / "truth.tsv"),
                        "--paf", str(paf_path), "--pred-fasta", str(d / "pred.fasta"), "--sample", "S1",
                        "--tool", "tool", "--out", str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    with open(out, newline="") as handle:
        row = next(csv.DictReader(handle, delimiter="\t"))
    print("  score row:", {k: row[k] for k in ("tp_bp", "fp_bp", "fn_bp", "recall") if k in row})
    assert float(row["recall"]) == 1.0, row
    fp_cols = [k for k in row if k.startswith("fp") or k == "fp"]
    assert fp_cols and all(float(row[k]) == 0 for k in fp_cols if row[k] not in ("", "NA")), row
    print("  base-level recall 1.0, FP 0 ? True")

    events, summary = d / "events.tsv", d / "summary.tsv"
    r = subprocess.run([sys.executable, str(ROOT / "python" / "call_structural_variants.py"), "--truth",
                        str(d / "truth.tsv"), "--results-dir", str(d / "results"), "--sample", "S1",
                        "--events-out", str(events), "--summary-out", str(summary)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    with open(events, newline="") as handle:
        calls = list(csv.DictReader(handle, delimiter="\t"))
    spurious = [c for c in calls if c["event_type"] in
                ("reference_deletion", "tandem_duplication", "relocation")]
    if spurious:
        print("FINDING: call_structural_variants reports a structural event for a pure origin rotation:",
              file=sys.stderr)
        for c in calls:
            print(f"  {c['event_type']} span_bp={c['span_bp']} {c['detail']}", file=sys.stderr)
        raise SystemExit(1)
    print("  no spurious structural event for origin rotation ? True")
print("CIRCULAR ORIGIN TEST PASSED")
