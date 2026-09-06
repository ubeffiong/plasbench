#!/usr/bin/env python3
"""Regression checks for leave-one-study-out recommendation safeguards."""
import csv
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "python", "validate_recommendations.py")


def write(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t"); writer.writeheader(); writer.writerows(rows)


def main():
    with tempfile.TemporaryDirectory() as directory:
        samples, scores, out = (os.path.join(directory, name) for name in ("samples.tsv", "scores.tsv", "validation.tsv"))
        write(samples, ["sample_id", "source_study"], [{"sample_id": "a", "source_study": "study_a"}, {"sample_id": "b", "source_study": "study_b"}])
        write(scores, ["sample", "tool", "f1"], [{"sample": "a", "tool": "x", "f1": ".9"}, {"sample": "a", "tool": "y", "f1": ".5"}, {"sample": "b", "tool": "x", "f1": ".8"}, {"sample": "b", "tool": "y", "f1": ".6"}])
        subprocess.run([sys.executable, SCRIPT, "--scores", scores, "--samples", samples, "--out", out, "--min-train-samples", "1"], check=True)
        output = list(csv.DictReader(open(out), delimiter="\t"))

        # The original pooled behavior, now explicitly scope=="overall": one
        # row per held-out study, both assessed, both selecting tool x.
        overall = [row for row in output if row["scope"] == "overall"]
        assert len(overall) == 2 and all(row["status"] == "assessed" for row in overall)
        assert all(row["selected_method_from_training"] == "x" for row in overall)
        assert all(row["selection_method"] == "fixed-weight" for row in overall), \
            "selection_method is reserved for a future model-based comparison; today it must always read fixed-weight"

        # Per-stratum rows are new: this fixture supplies no organism/
        # gram_group/etc. columns, so every row's stratification collapses
        # to "not_recorded" -- but that IS a real stratum, and must still
        # produce its own scope=="organism" (etc.) rows alongside "overall".
        scopes = {row["scope"] for row in output}
        assert "organism" in scopes and "read_depth_band" in scopes and "analysis_track" in scopes, \
            f"expected per-stratum scopes alongside overall, got {scopes}"
        organism_rows = [row for row in output if row["scope"] == "organism"]
        assert len(organism_rows) == 2  # one per held-out study, same as overall
        assert all(row["selected_method_from_training"] == "x" for row in organism_rows)
    print("ALL RECOMMENDATION VALIDATION TESTS PASSED")


if __name__ == "__main__": main()
