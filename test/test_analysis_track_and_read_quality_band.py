#!/usr/bin/env python3
"""Regression for the two new stratification fields select_operational_method.py
gained: analysis_track (already present via score-row pass-through, now
explicit and defaulted) and read_quality_band (new, attached from stage 2's
observed_read_quality.tsv via attach_read_quality_bands(), mirroring
recommendation_model.py's load/attach_assembly_stats pattern)."""

import csv
import os
import sys
import tempfile
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))

from select_operational_method import annotate, attach_read_quality_bands, write_recommendations  # noqa: E402


def test_analysis_track_present_and_defaulted():
    row_with_track = annotate({"sample": "s1", "analysis_track": "long_read", "f1": "0.9"}, {})
    assert row_with_track["analysis_track"] == "long_read"
    row_without_track = annotate({"sample": "s2", "f1": "0.9"}, {})
    assert row_without_track["analysis_track"] == "short_read", "expected the documented default when the column is absent"
    print("analysis_track is present and explicitly defaulted -> PASS")


def test_read_quality_band_defaults_and_attaches():
    row = annotate({"sample": "s1", "f1": "0.9"}, {})
    assert row["read_quality_band"] == "not_recorded", "expected not_recorded before any attach step runs"

    with tempfile.TemporaryDirectory(prefix="read_quality_") as tmp:
        for sample, quality in (("low_q", "8.0"), ("mod_q", "15.0"), ("high_q", "25.0")):
            sample_dir = os.path.join(tmp, sample)
            os.makedirs(sample_dir)
            with open(os.path.join(sample_dir, "observed_read_quality.tsv"), "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=("total_bases", "mean_phred_quality"), delimiter="\t")
                writer.writeheader()
                writer.writerow({"total_bases": "1000", "mean_phred_quality": quality})

        rows = [annotate({"sample": s, "f1": "0.9"}, {}) for s in ("low_q", "mod_q", "high_q", "no_file")]
        attach_read_quality_bands(rows, tmp)
        bands = {row["sample"]: row["read_quality_band"] for row in rows}
        assert bands["low_q"] == "low", bands
        assert bands["mod_q"] == "moderate", bands
        assert bands["high_q"] == "high", bands
        assert bands["no_file"] == "not_recorded", "a sample with no observed_read_quality.tsv keeps the default, not an error"
        print("attach_read_quality_bands bands each sample correctly and defaults an absent file -> PASS")

        # A missing/None data_dir must be a complete no-op (today's unchanged
        # behavior when this feature isn't used at all).
        rows2 = [annotate({"sample": "low_q", "f1": "0.9"}, {})]
        attach_read_quality_bands(rows2, None)
        assert rows2[0]["read_quality_band"] == "not_recorded"
        print("omitting data_dir is a complete no-op -> PASS")


def test_stratification_includes_new_scopes():
    with tempfile.TemporaryDirectory(prefix="strat_") as tmp:
        rows = [
            annotate({"sample": "s1", "tool": "flye_mob_recon", "analysis_track": "long_read", "f1": "0.9",
                     "precision": "0.9", "recall": "0.9"}, {}),
            annotate({"sample": "s2", "tool": "mob_recon", "analysis_track": "short_read", "f1": "0.8",
                     "precision": "0.8", "recall": "0.8"}, {}),
        ]
        out_path = os.path.join(tmp, "recs.tsv")
        statuses = {"flye_mob_recon": {"counts": Counter(), "runtime_seconds": [], "peak_rss_kb": []},
                   "mob_recon": {"counts": Counter(), "runtime_seconds": [], "peak_rss_kb": []}}
        _, written = write_recommendations(rows, statuses, 2, out_path, min_samples=1, min_coverage=0.1)
        scopes = {row["scope"] for row in written}
        assert "analysis_track" in scopes, f"expected analysis_track as a stratification scope, got {scopes}"
        assert "read_quality_band" in scopes, f"expected read_quality_band as a stratification scope, got {scopes}"
        groups_by_track = {row["group"] for row in written if row["scope"] == "analysis_track"}
        assert groups_by_track == {"long_read", "short_read"}, groups_by_track
        print("analysis_track and read_quality_band are real stratification scopes in the output -> PASS")


def main():
    test_analysis_track_present_and_defaulted()
    test_read_quality_band_defaults_and_attaches()
    test_stratification_includes_new_scopes()
    print("ALL ANALYSIS TRACK AND READ QUALITY BAND TESTS PASSED")


if __name__ == "__main__":
    main()
