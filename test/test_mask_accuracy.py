#!/usr/bin/env python3
"""mask_accuracy.py blanks base-level accuracy where truth was polished with the benchmark's own reads."""
import csv
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "python", "mask_accuracy.py")
HEAD = ("sample\ttool\tanalysis_track\tn_blocks\tn_blocks_without_cigar\taligned_columns\tidentity\tmismatch_rate\t"
        "insertion_rate\tdeletion_rate\tmismatch_bp\tinserted_bp\tdeleted_bp\n")


def main():
    ok = True

    def check(label, good):
        nonlocal ok
        print(f"  {label}: {'PASS' if good else 'FAIL'}")
        ok &= bool(good)

    with tempfile.TemporaryDirectory() as tmp:
        acc, prov = os.path.join(tmp, "acc.tsv"), os.path.join(tmp, "prov.tsv")
        open(acc, "w").write(HEAD +
                             "polished\tt\tshort_read\t1\t0\t1000\t0.99\t0.01\t0\t0\t10\t0\t0\n"
                             "independent\tt\tshort_read\t1\t0\t1000\t0.98\t0.02\t0\t0\t20\t0\t0\n"
                             "unknown\tt\tshort_read\t1\t0\t1000\t0.97\t0.03\t0\t0\t30\t0\t0\n"
                             "nocigar\tt\tshort_read\t1\t1\t0\t\t\t\t\t0\t0\t0\n")
        open(prov, "w").write("sample\tbase_level_metrics_valid\npolished\tno\nindependent\tyes\nnocigar\tyes\n")
        subprocess.run([sys.executable, SCRIPT, "--accuracy", acc, "--truth-provenance", prov], check=True,
                       capture_output=True)
        rows = {r["sample"]: r for r in csv.DictReader(open(acc, newline=""), delimiter="\t")}
        check("truth polished with the benchmark's reads: every rate blank and flagged not assessable",
              all(rows["polished"][c] == "" for c in ("identity", "mismatch_rate", "insertion_rate", "deletion_rate"))
              and rows["polished"]["accuracy_status"] == "not_assessable_truth_polished_with_benchmark_reads")
        check("independent truth keeps its rates", rows["independent"]["identity"] == "0.98"
              and rows["independent"]["accuracy_status"] == "evaluated")
        check("no provenance record: rates kept (valid by default, as the CPRR rule does)",
              rows["unknown"]["identity"] == "0.97" and rows["unknown"]["accuracy_status"] == "evaluated")
        check("no decodable CIGAR stays blank and says why", rows["nocigar"]["accuracy_status"] == "no_cigar")
        check("the aligned-column and mismatch counts are left alone (only the rates are blanked)",
              rows["polished"]["aligned_columns"] == "1000" and rows["polished"]["mismatch_bp"] == "10")
        # Without any provenance file nothing is masked.
        open(acc, "w").write(HEAD + "polished\tt\tshort_read\t1\t0\t1000\t0.99\t0.01\t0\t0\t10\t0\t0\n")
        subprocess.run([sys.executable, SCRIPT, "--accuracy", acc], check=True, capture_output=True)
        check("no provenance given: nothing is masked",
              list(csv.DictReader(open(acc, newline=""), delimiter="\t"))[0]["identity"] == "0.99")
    print("ALL MASK ACCURACY TESTS PASSED" if ok else "MASK ACCURACY TESTS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
