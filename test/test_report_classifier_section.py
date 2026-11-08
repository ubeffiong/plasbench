#!/usr/bin/env python3
"""
The HTML report must show the nearest-reference screen result, with its caveat,
and must not invent one when no screen was run.
"""

import html as htmllib
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))

import build_html_report as report  # noqa: E402


def card(selection, sample="opA"):
    with tempfile.TemporaryDirectory() as tmp:
        results = Path(tmp)
        directory = results / "selected_candidates" / sample
        directory.mkdir(parents=True)
        (directory / f"{sample}.selection_report.json").write_text(json.dumps(selection), encoding="utf-8")
        return report.selection_card(sample, results, results / "benchmark.report.html")


BASE = {"selected_tool": "mob_recon", "selection_type": "operational_method_recommendation",
        "confidence_tier": "requires_confirmation", "long_read_confirmation_reasons": ["demo"]}


def main():
    ok = True

    def check(label, condition):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}")

    print("a report with the screen's result")
    html = card(dict(BASE, plasmid_novelty={
        "contig_1": {"cluster_membership_status": "close_reference_match", "best_reference_id": "AP001918.1",
                     "best_reference_plasmid_name": "F", "mash_distance": "0.010000", "mash_p_value": "0",
                     "shared_hashes": "900/1000", "distance_margin": "0.8000"},
        "contig_2": {"cluster_membership_status": "no_close_reference", "best_reference_id": "FN868832.1",
                     "mash_distance": "0.200000", "distance_margin": "1.0000"},
        "contig_3": {"cluster_membership_status": "insufficient_reference"}}))
    check("the block is present and titled experimental", "Nearest-reference screen (experimental, unvalidated)" in html)
    check("each record is listed", all(r in html for r in ("contig_1", "contig_2", "contig_3")))
    check("close match is worded as such", "Close match to a reference plasmid" in html)
    check("no-close-reference is worded without calling the plasmid novel",
          "No close reference in the reference set" in html and "novel plasmid" not in html.lower())
    check("the nearest reference and distance are shown", "AP001918.1 F" in html and "0.010000" in html)
    check("support (p-value, shared hashes) is shown", "p=0" in html and "shared 900/1000" in html)
    check("the caveat is part of the block", "not evidence of relatedness" in html and "not a test of novelty" in html)
    check("the 95% misreading is called out", "does not mean 95% similarity" in html)
    check("an unassessable record is labelled as such", "Could not be assessed" in html)

    print("a report written before the rename still displays")
    html = card(dict(BASE, plasmid_novelty={
        "c1": {"cluster_membership_status": "known_cluster", "confidence_score": "0.5000", "mash_distance": "0.02"},
        "c2": {"cluster_membership_status": "novel", "confidence_score": "0.9000", "mash_distance": "0.3"}}))
    text = htmllib.unescape(html)
    check("old 'known_cluster' shows under today's wording",
          "Close match to a reference plasmid (recorded as 'known_cluster')" in text)
    check("old 'novel' shows under today's wording",
          "No close reference in the reference set (recorded as 'novel')" in text)
    check("the legacy confidence_score is shown as the margin", "0.5000" in html and "0.9000" in html)

    print("no screen was run")
    html = card(dict(BASE))
    check("no block is emitted", "Nearest-reference screen" not in html)
    html = card(dict(BASE, plasmid_novelty={}))
    check("an empty result emits no block either", "Nearest-reference screen" not in html)

    print("the rest of the card is unchanged")
    check("the selected tool still renders", "mob_recon" in card(dict(BASE)))

    print()
    if not ok:
        print("REPORT CLASSIFIER SECTION TESTS FAILED")
        sys.exit(1)
    print("ALL REPORT CLASSIFIER SECTION TESTS PASSED")


if __name__ == "__main__":
    main()
