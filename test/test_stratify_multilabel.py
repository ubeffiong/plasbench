#!/usr/bin/env python3
"""A plasmid with several replicons counts once in EACH replicon group (documented)."""
import csv
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRAT = os.path.join(ROOT, "python", "stratify_recovery.py")


def main():
    with tempfile.TemporaryDirectory() as d:
        res, data = os.path.join(d, "results"), os.path.join(d, "data")
        os.makedirs(os.path.join(res, "s1"))
        os.makedirs(os.path.join(data, "s1"))
        with open(os.path.join(res, "s1", "t.per_plasmid.tsv"), "w") as fh:
            fh.write("sample\ttool\tanalysis_track\tsequence_id\tlength\tcovered_bp\tcompleteness\trecovered\n")
            fh.write("s1\tt\tshort_read\tpMulti\t1000\t1000\t1.0\t1\n")
            fh.write("s1\tt\tshort_read\tpOne\t1000\t500\t0.5\t0\n")
        with open(os.path.join(data, "s1", "truth_features.tsv"), "w") as fh:
            fh.write("sequence_id\tstart\tend\tfeature_type\tlabel\tsource\tversion\n")
            fh.write("pMulti\t1\t500\treplicon\tIncFIB\tx\t1\n")
            fh.write("pMulti\t600\t900\treplicon\tIncFII\tx\t1\n")
            fh.write("pOne\t1\t900\treplicon\tIncFII\tx\t1\n")
        out = os.path.join(d, "out.tsv")
        subprocess.run([sys.executable, STRAT, "--results-dir", res, "--data-dir", data, "--out", out],
                       check=True, capture_output=True)
        with open(out, newline="") as fh:
            rows = {(r["feature_type"], r["label"]): r for r in csv.DictReader(fh, delimiter="\t")}
        ok = True
        checks = [
            (("replicon", "IncFIB"), "n_plasmids", "1"),
            (("replicon", "IncFII"), "n_plasmids", "2"),   # pMulti AND pOne
            (("replicon", "IncFII"), "recovered_fraction", "0.5000"),
            (("mob", "untyped"), "n_plasmids", "2"),        # no MOB label -> untyped, not dropped
        ]
        for key, field, want in checks:
            got = rows.get(key, {}).get(field)
            print(f"  {key} {field} = {got} (expected {want}) {'PASS' if got == want else 'FAIL'}")
            ok &= got == want
        total_rep = sum(int(r["n_plasmids"]) for k, r in rows.items() if k[0] == "replicon")
        print(f"  group sizes sum to {total_rep} (> 2 real plasmids, by design) "
              f"{'PASS' if total_rep == 3 else 'FAIL'}")
        ok &= total_rep == 3
    print("ALL STRATIFY MULTILABEL TESTS PASSED" if ok else "STRATIFY MULTILABEL TESTS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
