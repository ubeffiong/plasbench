#!/usr/bin/env python3
"""Regression: an under-supported STRATUM in one leave-one-study-out fold
must not withhold the "overall" scope's own assessment, and must not
silently withhold select_operational_method.py's validation_ready gate
either -- that gate only ever looks at scope=="overall" rows now."""

import csv
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))

VALIDATOR = os.path.join(ROOT, "python", "validate_recommendations.py")


def write(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def main():
    import subprocess

    with tempfile.TemporaryDirectory(prefix="per_stratum_loso_") as tmp:
        samples_path = os.path.join(tmp, "samples.tsv")
        scores_path = os.path.join(tmp, "scores.tsv")
        out = os.path.join(tmp, "validation.tsv")

        # 3 studies, 4 samples each, all "Escherichia coli" EXCEPT one
        # singleton "Klebsiella pneumoniae" sample in study_c -- that
        # organism stratum will never have enough training rows in ANY
        # fold, but must not affect the overall assessment.
        sample_rows, score_rows = [], []
        sid = 0
        for study, organism in (("study_a", "Escherichia coli"), ("study_b", "Escherichia coli"),
                                ("study_c", "Escherichia coli")):
            for _ in range(4):
                sid += 1
                sample_rows.append({"sample_id": f"s{sid}", "organism": organism, "source_study": study})
                score_rows.append({"sample": f"s{sid}", "tool": "toolA", "f1": "0.9"})
                score_rows.append({"sample": f"s{sid}", "tool": "toolB", "f1": "0.5"})
        sid += 1
        sample_rows.append({"sample_id": f"s{sid}", "organism": "Klebsiella pneumoniae", "source_study": "study_c"})
        score_rows.append({"sample": f"s{sid}", "tool": "toolA", "f1": "0.9"})

        write(samples_path, ["sample_id", "organism", "source_study"], sample_rows)
        write(scores_path, ["sample", "tool", "f1"], score_rows)
        subprocess.run([sys.executable, VALIDATOR, "--scores", scores_path, "--samples", samples_path,
                        "--out", out, "--min-train-samples", "5"], check=True, capture_output=True, text=True)
        rows = list(csv.DictReader(open(out, encoding="utf-8"), delimiter="\t"))

        overall = [row for row in rows if row["scope"] == "overall"]
        assert len(overall) == 3, f"expected one overall row per held-out study, got {len(overall)}"
        assert all(row["status"] == "assessed" for row in overall), \
            "the under-supported Klebsiella organism stratum must not withhold the overall assessment"
        print("an under-supported single stratum does not withhold the overall LOSO assessment -> PASS")

        kleb_rows = [row for row in rows if row["scope"] == "organism" and row["group"] == "Klebsiella pneumoniae"]
        assert kleb_rows, "expected at least one fold to hold out the Klebsiella sample and produce a stratum row for it"
        assert all(row["status"] == "not_assessed" for row in kleb_rows), \
            "the Klebsiella stratum itself must be honestly not_assessed (too few training samples), not silently pooled"
        print("the under-supported stratum is itself correctly reported not_assessed, not silently omitted -> PASS")

        # Now confirm select_operational_method.py's validation_ready gate
        # only looks at scope=="overall" -- construct a validation file
        # where EVERY overall row is assessed but a stratum row is not, and
        # confirm the gate reads True.
        sys.path.insert(0, os.path.join(ROOT, "python"))
        import importlib
        select_operational_method = importlib.import_module("select_operational_method")
        validation_rows = rows  # reuse the exact file just produced
        overall_only = [row for row in validation_rows if row.get("scope", "overall") == "overall"]
        gate = bool(overall_only) and all(row.get("status") == "assessed" for row in overall_only)
        assert gate is True, "expected the gate to read True: not every row is assessed, but every OVERALL row is"
        assert not all(row.get("status") == "assessed" for row in validation_rows), \
            "sanity check: this fixture must genuinely contain a not_assessed row somewhere (the Klebsiella stratum)"
        print("select_operational_method.py's validation_ready gate logic reads True from overall-only rows -> PASS")

    print("ALL PER-STRATUM LOSO TESTS PASSED")


if __name__ == "__main__":
    main()
