#!/usr/bin/env python3
"""Regression checks for structural variant calling and reference annotation."""

import csv
import json
import os
import subprocess
import sys
import tempfile


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SV = os.path.join(ROOT, "python", "call_structural_variants.py")
ANNOTATE = os.path.join(ROOT, "python", "annotate_reference.py")

# Each record encodes exactly one discordance so a miscall is unambiguous.
PAF = """\
inv\t4000\t0\t2000\t+\tpA\t20000\t1000\t3000\t1990\t2000\t60
inv\t4000\t2000\t4000\t-\tpA\t20000\t3000\t5000\t1990\t2000\t60
dup\t3000\t0\t1500\t+\tpA\t20000\t8000\t9500\t1490\t1500\t60
dup\t3000\t1500\t3000\t+\tpA\t20000\t8200\t9700\t1490\t1500\t60
chim\t5000\t0\t2500\t+\tpA\t20000\t12000\t14500\t2490\t2500\t60
chim\t5000\t2500\t5000\t+\tchr1\t50000\t100\t2600\t2490\t2500\t60
del\t4000\t0\t2000\t+\tpB\t9000\t0\t2000\t1990\t2000\t60
del\t4000\t2000\t4000\t+\tpB\t9000\t5000\t7000\t1990\t2000\t60
clean\t3000\t0\t3000\t+\tpB\t9000\t0\t3000\t2990\t3000\t60
lowq\t3000\t0\t3000\t-\tpA\t20000\t100\t3100\t2990\t3000\t0
"""


def main():
    with tempfile.TemporaryDirectory(prefix="sv_test_") as tmp:
        results = os.path.join(tmp, "results")
        sample = os.path.join(results, "s1")
        os.makedirs(sample)
        truth = os.path.join(tmp, "truth.tsv")
        with open(truth, "w", newline="", encoding="utf-8") as handle:
            csv.writer(handle, delimiter="\t").writerows(
                [["sequence_id", "molecule_type", "length"], ["pA", "PLASMID", 20000],
                 ["pB", "PLASMID", 9000], ["chr1", "CHROMOSOME", 50000]])
        with open(os.path.join(sample, "toolx.pred_vs_ref.paf"), "w", encoding="utf-8") as handle:
            handle.write(PAF)

        events_path = os.path.join(tmp, "events.tsv")
        summary_path = os.path.join(tmp, "summary.tsv")
        subprocess.run([sys.executable, SV, "--truth", truth, "--results-dir", results,
                        "--sample", "s1", "--events-out", events_path,
                        "--summary-out", summary_path], check=True)
        events = list(csv.DictReader(open(events_path, encoding="utf-8"), delimiter="\t"))
        summary = next(csv.DictReader(open(summary_path, encoding="utf-8"), delimiter="\t"))

    by_record = {row["record_id"]: row for row in events}
    assert by_record["inv"]["event_type"] == "inversion_junction", by_record["inv"]
    assert by_record["dup"]["event_type"] == "tandem_duplication", by_record["dup"]
    assert by_record["chim"]["event_type"] == "inter_replicon_junction", by_record["chim"]
    assert by_record["del"]["event_type"] == "reference_deletion", by_record["del"]
    # A collinear record must not generate an event, and a below-threshold MAPQ
    # block must be filtered rather than called as an inversion.
    assert "clean" not in by_record, "collinear record produced a spurious call"
    assert "lowq" not in by_record, "low-MAPQ block was not filtered"

    assert by_record["chim"]["left_target"] == "pA" and by_record["chim"]["right_target"] == "chr1"
    assert int(by_record["dup"]["span_bp"]) == 1300, by_record["dup"]["span_bp"]
    assert int(by_record["del"]["span_bp"]) == 3000, by_record["del"]["span_bp"]

    # Collinearity is a real fraction, and nothing claims validation.
    assert summary["events_total"] == "4", summary["events_total"]
    assert 0.0 < float(summary["collinear_fraction"]) < 1.0, summary["collinear_fraction"]
    assert summary["validated"] == "False", "structural calls must not claim validation"
    assert "not distinguish" in summary["meaning"], summary["meaning"]

    # Annotation: with no caller installed every class is 'not evaluated'. An
    # absent caller must never be recorded as an absence of the feature.
    with tempfile.TemporaryDirectory(prefix="annotate_test_") as tmp:
        reference = os.path.join(tmp, "ref.fna")
        with open(reference, "w", encoding="utf-8") as handle:
            handle.write(">pA\n" + "ACGT" * 250 + "\n")
        features = os.path.join(tmp, "truth_features.tsv")
        provenance = os.path.join(tmp, "provenance.json")
        subprocess.run([sys.executable, ANNOTATE, "--reference", reference,
                        "--out", features, "--provenance", provenance], check=True)
        header = open(features, encoding="utf-8").readline().rstrip("\n").split("\t")
        record = json.load(open(provenance, encoding="utf-8"))

    assert header == ["sequence_id", "start", "end", "feature_type", "label", "source", "version"], header
    statuses = {name: value["status"] for name, value in record["callers"].items()}
    assert set(statuses) >= {"mob_typer", "abricate_amr", "amrfinder", "isescan"}, statuses
    assert all(value in ("ok", "not_evaluated", "failed") for value in statuses.values()), statuses
    assert record["feature_classes_not_evaluated"], "absent callers must be reported"
    assert "not evidence that the feature is absent" in record["meaning"]

    print("ALL STRUCTURAL AND ANNOTATION TESTS PASSED")


if __name__ == "__main__":
    main()
