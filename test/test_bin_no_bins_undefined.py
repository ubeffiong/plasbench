#!/usr/bin/env python3
"""A binner that bins nothing on an isolate WITH true plasmids: precision is undefined (blank), recall and F1 are 0 (audit AU-048).

score_bins.py wrote bin_precision 0.0 here while score_plasmids.py leaves precision blank when nothing was predicted; both now agree."""
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as t:
    tmp = Path(t)
    (tmp / "truth.tsv").write_text("sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t5000\npA\tPLASMID\t3000\n")
    (tmp / "bins.tsv").write_text("sequence_id\tbin_id\n")
    (tmp / "a.paf").write_text("")
    subprocess.run([sys.executable, str(ROOT / "python" / "score_bins.py"), "--truth", str(tmp / "truth.tsv"), "--paf", str(tmp / "a.paf"), "--bins", str(tmp / "bins.tsv"),
                    "--out", str(tmp / "m.tsv"), "--summary", str(tmp / "s.tsv")], check=True, capture_output=True)
    with open(tmp / "s.tsv", newline="") as handle:
        row = next(csv.DictReader(handle, delimiter="\t"))
assert row["bin_precision"] == "", row["bin_precision"]
assert float(row["bin_recall"]) == 0.0 and float(row["bin_f1"]) == 0.0, (row["bin_recall"], row["bin_f1"])
print("  PASS: nothing binned with a true plasmid present: bin_precision blank, bin_recall and bin_f1 0")
print("ALL BIN NO-BINS TESTS PASSED")
