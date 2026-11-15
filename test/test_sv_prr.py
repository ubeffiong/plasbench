#!/usr/bin/env python3
"""SV-PRR (plan B3): CPRR-correct plasmids that no structural call touches."""
import csv
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import call_structural_variants as csv_calls  # noqa: E402


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    events = [{"left_target": "pA", "right_target": "pA"}, {"left_target": "chr", "right_target": "pB"}]
    check("a call touching a plasmid on either side removes it", csv_calls.sv_free_plasmids(events, {"pA", "pB", "pC"}) == {"pC"})
    check("no calls leaves every plasmid free", csv_calls.sv_free_plasmids([], {"pA", "pB"}) == {"pA", "pB"})
    check("a call elsewhere does not count against a plasmid", csv_calls.sv_free_plasmids([{"left_target": "chr", "right_target": "chr"}], {"pA"}) == {"pA"})
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "t.cprr.tsv"
        with path.open("w", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t")
            writer.writerow(["true_plasmid", "correct"])
            writer.writerows([["pA", "yes"], ["pB", "yes"], ["pC", "no"], ["pD", "yes"]])
        check("only correct and untouched plasmids count; denominator is every plasmid scored", csv_calls.sv_prr_counts(path, events) == (1, 4), csv_calls.sv_prr_counts(path, events))
        check("no CPRR table (not bin-scored) gives None, not zero", csv_calls.sv_prr_counts(Path(tmp) / "none.tsv", events) is None)
    print()
    if not ok:
        print("SV-PRR TESTS FAILED")
        sys.exit(1)
    print("ALL SV-PRR TESTS PASSED")


if __name__ == "__main__":
    main()
