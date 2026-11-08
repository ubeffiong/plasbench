#!/usr/bin/env python3
"""Per-plasmid outcome states (score_bins.plasmid_outcomes and --outcomes-out).

Fixture, hand-checked (thresholds perfect 0.95, fragment share 0.20, missed 0.50):
  pA 10 kb, bin1 holds 9.8 kb, nothing else in bin1        -> perfect (r 0.98, p 1.0)
  pB 10 kb, bin2 holds 6 kb and bin3 4 kb                   -> fragmented
  pC 5 kb and pD 5 kb, both wholly in bin4                  -> merged (each)
  pE 10 kb, bin5 holds 3 kb                                 -> missed (r 0.30)
  pF 10 kb, bin6 holds 8 kb plus 2 kb of chromosome         -> partial (r 0.80, p 0.80), contamination 0.20
  pG 10 kb, no bin                                          -> missed
"""
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import score_bins  # noqa: E402

PLASMIDS = {"pA": 10000, "pB": 10000, "pC": 5000, "pD": 5000, "pE": 10000, "pF": 10000, "pG": 10000}
OVERLAPS = {("bin1", "pA"): 9800, ("bin2", "pB"): 6000, ("bin3", "pB"): 4000, ("bin4", "pC"): 5000,
            ("bin4", "pD"): 5000, ("bin5", "pE"): 3000, ("bin6", "pF"): 8000}
CHROMOSOME = {"bin6": 2000}
EXPECTED = {"pA": "perfect", "pB": "fragmented", "pC": "merged", "pD": "merged", "pE": "missed",
            "pF": "partial", "pG": "missed"}


def main():
    total_mapped = {}
    for (bin_id, _), bp in OVERLAPS.items():
        total_mapped[bin_id] = total_mapped.get(bin_id, 0) + bp
    for bin_id, bp in CHROMOSOME.items():
        total_mapped[bin_id] += bp
    rows = {r["true_plasmid"]: r for r in score_bins.plasmid_outcomes(OVERLAPS, PLASMIDS, total_mapped, CHROMOSOME)}
    got = {p: r["outcome"] for p, r in rows.items()}
    assert got == EXPECTED, got
    assert rows["pF"]["contamination_fraction"] == "0.2000" and rows["pF"]["best_bin_precision"] == "0.8000"
    assert rows["pB"]["bins_holding_share"] == 2 and rows["pC"]["merged_with"] == "pD"
    print("  PASS: perfect / fragmented / merged / missed / partial match the hand-checked fixture")

    strict = {r["true_plasmid"]: r["outcome"] for r in
              score_bins.plasmid_outcomes(OVERLAPS, PLASMIDS, total_mapped, CHROMOSOME, perfect=0.99)}
    assert strict["pA"] == "partial"
    print("  PASS: PERFECT_THRESHOLD 0.99 turns pA (recall 0.98) into partial")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "truth.tsv").write_text("sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t100000\n"
                                       "pA\tPLASMID\t10000\npB\tPLASMID\t10000\n")
        (tmp / "bins.tsv").write_text("sequence_id\tbin_id\nc1\tb1\nc2\tb2\nc3\tb3\n")
        (tmp / "a.paf").write_text("c1\t9900\t0\t9900\t+\tpA\t10000\t0\t9900\t9900\t9900\t60\n"
                                   "c2\t6000\t0\t6000\t+\tpB\t10000\t0\t6000\t6000\t6000\t60\n"
                                   "c3\t4000\t0\t4000\t+\tpB\t10000\t6000\t10000\t4000\t4000\t60\n")
        subprocess.run([sys.executable, str(ROOT / "python" / "score_bins.py"), "--truth", str(tmp / "truth.tsv"),
                        "--paf", str(tmp / "a.paf"), "--bins", str(tmp / "bins.tsv"), "--out", str(tmp / "m.tsv"),
                        "--summary", str(tmp / "s.tsv"), "--outcomes-out", str(tmp / "o.tsv")],
                       check=True, capture_output=True)
        with open(tmp / "o.tsv", newline="") as handle:
            outcomes = {r["true_plasmid"]: r["outcome"] for r in csv.DictReader(handle, delimiter="\t")}
        with open(tmp / "s.tsv", newline="") as handle:
            summary = next(csv.DictReader(handle, delimiter="\t"))
        assert outcomes == {"pA": "perfect", "pB": "fragmented"}, outcomes
        assert summary["outcome_perfect"] == "1" and summary["outcome_fragmented"] == "1"
        assert summary["outcome_missed"] == "0" and summary["bin_ari"] != ""
        print("  PASS: score_bins.py --outcomes-out writes the table and the summary carries outcome counts and ARI")
    print("ALL BIN OUTCOME TESTS PASSED")


if __name__ == "__main__":
    main()
