#!/usr/bin/env python3
"""Regression: select_unknown_sample.py must actually select a benchmark
recommendation for a truth-unknown operational sample.

It previously filtered on a "state" column and read a "primary_tool" field
that select_operational_method.py's recommendations.tsv never wrote, so it
always reported "no evidence-gated recommendation matched" even when one
existed. This builds a real recommendations.tsv with the actual writer, the
way an operational run would encounter it, rather than a hand-typed fixture,
so a future column rename in either script is caught here too.
"""
import csv
import json
import os
import random
import subprocess
import sys
import tempfile


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SELECT_METHOD = os.path.join(ROOT, "python", "select_operational_method.py")
SELECT_UNKNOWN = os.path.join(ROOT, "python", "select_unknown_sample.py")
FIT_MODEL = os.path.join(ROOT, "python", "fit_recommendation_model.py")


def test_recommendation_model_integration():
    """§2.2: model disabled -> exactly today's stratum-mean behavior (the
    default, already exercised by every scenario above with no
    --recommendation-model flag); model enabled + ready -> mean_f1 comes from
    the model's own per-row prediction (not the raw mean) and the reason
    field carries the "(model-fitted)" provenance tag, with the exact same
    output schema either way."""
    with tempfile.TemporaryDirectory(prefix="operational_selection_model_") as tmp:
        rng = random.Random(42)
        samples_path = os.path.join(tmp, "samples.tsv")
        scores_path = os.path.join(tmp, "scores.tsv")
        results = os.path.join(tmp, "results")

        sample_rows, score_rows = [], []
        sid = 0
        for study in range(5):
            for _ in range(6):
                sid += 1
                sample = f"s{sid}"
                depth = 10 + sid * 3
                f1 = min(0.99, max(0.01, 0.5 + 0.01 * depth + rng.uniform(-0.01, 0.01)))
                sample_rows.append({"sample_id": sample, "organism": "Example bacterium",
                                    "read_depth_x": str(depth), "source_study": f"study{study}"})
                score_rows.append({"sample": sample, "tool": "mob_recon", "true_plasmid_bp": "10000",
                                   "unmapped_pred_bp": "0", "plasmid_recall": f"{f1:.4f}", "bin_f1": "",
                                   "precision": f"{f1:.4f}", "recall": f"{f1:.4f}", "f1": f"{f1:.4f}",
                                   "split_events": "0", "merge_events": "0", "contamination_fraction": "0"})
                os.makedirs(os.path.join(results, sample), exist_ok=True)

        with open(samples_path, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["sample_id", "organism", "read_depth_x", "source_study"], delimiter="\t")
            writer.writeheader()
            writer.writerows(sample_rows)
        fields = ["sample", "tool", "true_plasmid_bp", "unmapped_pred_bp", "plasmid_recall", "bin_f1",
                  "precision", "recall", "f1", "split_events", "merge_events", "contamination_fraction"]
        with open(scores_path, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
            writer.writeheader()
            writer.writerows(score_rows)

        model_path = os.path.join(results, "benchmark.recommendation_model.json")
        subprocess.run([sys.executable, FIT_MODEL, "--scores", scores_path, "--sample-sheet", samples_path,
                        "--out", model_path, "--min-studies", "3", "--min-training-samples", "20",
                        "--min-relative-improvement", "0.05"], check=True, capture_output=True, text=True)
        model_payload = json.load(open(model_path))
        assert model_payload["model_ready"] is True, model_payload["reason"]

        def run_select(out_prefix, recommendation_model=None):
            args = [sys.executable, SELECT_METHOD, "--scores", scores_path, "--sample-sheet", samples_path,
                    "--results-dir", results, "--out-prefix", out_prefix, "--min-samples", "20", "--min-coverage", "0.80"]
            if recommendation_model:
                args += ["--recommendation-model", recommendation_model]
            subprocess.run(args, check=True, capture_output=True, text=True)
            return list(csv.DictReader(open(out_prefix + ".recommendations.tsv"), delimiter="\t"))

        disabled_rows = run_select(os.path.join(tmp, "disabled"))
        enabled_rows = run_select(os.path.join(tmp, "enabled"), recommendation_model=model_path)

        disabled_row = next(row for row in disabled_rows if row["scope"] == "overall")
        enabled_row = next(row for row in enabled_rows if row["scope"] == "overall")

        # Same schema either way.
        assert list(disabled_row.keys()) == list(enabled_row.keys()), "recommendation-model must never change the output schema"
        assert "model_used" not in disabled_row and "model_used" not in enabled_row, \
            "the internal model_used flag must never leak into the written TSV"

        assert "(model-fitted)" not in disabled_row["reason"], disabled_row["reason"]
        assert "(model-fitted)" in enabled_row["reason"], enabled_row["reason"]

        # "overall" contains every training row, and OLS/ridge's own math
        # guarantees the model's predicted mean over its OWN full training
        # set nearly matches the raw mean there -- that isn't where the
        # accuracy gain shows up. It shows up in a genuine SUBSET stratum
        # (here, the high-read_depth_band isolates), where the model
        # (fit on ALL rows, including the low/moderate ones) extrapolates
        # differently than that subset's own raw mean.
        disabled_high = next(row for row in disabled_rows if row["scope"] == "read_depth_band" and row["group"] == "high")
        enabled_high = next(row for row in enabled_rows if row["scope"] == "read_depth_band" and row["group"] == "high")
        assert disabled_high["mean_f1"] != enabled_high["mean_f1"], \
            "expected the model's per-row predictions to differ from the raw stratum mean for a real subgroup"
        print("model disabled -> unchanged reason/schema; model enabled -> '(model-fitted)' reason, differing mean_f1 for a real stratum -> PASS")


def main():
    with tempfile.TemporaryDirectory(prefix="operational_selection_") as tmp:
        samples = os.path.join(tmp, "samples.tsv")
        scores = os.path.join(tmp, "scores.tsv")
        results = os.path.join(tmp, "results")

        # Five truth-set samples give mob_recon a clean win with full
        # coverage, clearing the default RECOMMENDATION_MIN_SAMPLES=5 /
        # RECOMMENDATION_MIN_COVERAGE=0.80 gates so it becomes the eligible
        # "primary" overall recommendation.
        with open(samples, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["sample_id", "organism"], delimiter="\t")
            writer.writeheader()
            for i in range(5):
                writer.writerow({"sample_id": f"s{i}", "organism": "Example bacterium"})

        fields = ["sample", "tool", "true_plasmid_bp", "unmapped_pred_bp", "plasmid_recall",
                  "bin_f1", "precision", "recall", "f1", "split_events", "merge_events",
                  "contamination_fraction"]
        with open(scores, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
            writer.writeheader()
            for i in range(5):
                os.makedirs(os.path.join(results, f"s{i}"), exist_ok=True)
                writer.writerow({"sample": f"s{i}", "tool": "mob_recon", "true_plasmid_bp": "10000",
                                 "unmapped_pred_bp": "0", "plasmid_recall": "1", "bin_f1": "1",
                                 "precision": "1", "recall": "1", "f1": "1", "split_events": "0",
                                 "merge_events": "0", "contamination_fraction": "0"})
                writer.writerow({"sample": f"s{i}", "tool": "platon", "true_plasmid_bp": "10000",
                                 "unmapped_pred_bp": "500", "plasmid_recall": "0.7", "bin_f1": "",
                                 "precision": "0.7", "recall": "0.7", "f1": "0.7", "split_events": "0",
                                 "merge_events": "0", "contamination_fraction": "0.1"})

        subprocess.run([sys.executable, SELECT_METHOD, "--scores", scores, "--sample-sheet", samples,
                        "--results-dir", results, "--out-prefix", os.path.join(results, "benchmark"),
                        "--min-samples", "5", "--min-coverage", "0.80"], check=True)
        recommendations = os.path.join(results, "benchmark.recommendations.tsv")

        rows = list(csv.DictReader(open(recommendations), delimiter="\t"))
        assert any(row["scope"] == "overall" and row["tool"] == "mob_recon" and row["recommendation"] == "primary"
                   for row in rows), "fixture did not produce an eligible overall recommendation to select"

        # --tool-only: usable before any reconstruction has run, no
        # --sample-id/--results-dir needed.
        tool_only = subprocess.run([sys.executable, SELECT_UNKNOWN, "--recommendations", recommendations,
                                    "--tool-only"], capture_output=True, text=True, check=True)
        assert tool_only.stdout.strip() == "mob_recon", f"expected mob_recon, got {tool_only.stdout!r}"

        # A brand-new operational sample, no prediction FASTA yet: the
        # recommendation must still be identified (this is exactly what was
        # broken), even though there is nothing to copy yet.
        os.makedirs(os.path.join(results, "newsample"))
        report_path = os.path.join(results, "newsample", "selection_report.json")
        subprocess.run([sys.executable, SELECT_UNKNOWN, "--recommendations", recommendations,
                        "--sample-id", "newsample", "--results-dir", results], check=True)
        import json
        report = json.load(open(report_path))
        assert report["selected_tool"] == "mob_recon", report
        assert "selected_candidate_fasta" not in report
        assert "run the nominated tool first" in report["selection_reason"]

        # Once the recommended tool has actually produced its prediction, the
        # candidate must be copied for reuse.
        open(os.path.join(results, "newsample", "pred_mob_recon.plasmid.fasta"), "w").write(">c\nACGT\n")
        subprocess.run([sys.executable, SELECT_UNKNOWN, "--recommendations", recommendations,
                        "--sample-id", "newsample", "--results-dir", results], check=True)
        report = json.load(open(report_path))
        assert report["selected_tool"] == "mob_recon"
        assert report["selected_candidate_fasta"] == "selected_candidate/candidate.plasmid.fasta"
        assert os.path.isfile(os.path.join(results, "newsample", "selected_candidate", "candidate.plasmid.fasta"))

        print("ALL OPERATIONAL SELECTION TESTS PASSED")

    test_recommendation_model_integration()


if __name__ == "__main__":
    main()
