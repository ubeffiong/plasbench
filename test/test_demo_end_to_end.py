#!/usr/bin/env python3
"""End to end: the offline demo produces every advisory table and the report shows them.

Runs test/run_demo.sh (synthetic data, no downloads), then checks that each layer reached
its output file AND its HTML section, populated rather than showing an empty state.
"""
import csv
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "results_demo"


def rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def section(html, name):
    match = re.search(r"<section id='%s'>(.*?)</section>" % name, html, re.S)
    assert match, f"report has no #{name} section"
    return match.group(1)


def main():
    bash = "bash"
    done = subprocess.run([bash, "test/run_demo.sh"], cwd=ROOT, capture_output=True,
                          text=True, env={**os.environ})
    assert done.returncode == 0, done.stderr[-2000:]
    assert "Traceback" not in done.stderr and "Traceback" not in done.stdout, "demo printed a traceback"

    html = (DEMO / "benchmark.report.html").read_text(encoding="utf-8")

    # Per-plasmid side files exist for scored (sample, tool) pairs and feed the stratifier.
    assert list(DEMO.glob("*/*.per_plasmid.tsv")), "scorer wrote no per-plasmid side file"
    strat = rows(DEMO / "benchmark.recovery_by_replicon.tsv")
    kinds = {r["feature_type"] for r in strat}
    assert {"replicon", "mob", "size_band", "amr"} <= kinds, kinds
    for r in strat:
        assert r["median_completeness"] and r["q1_completeness"] and r["q3_completeness"]
    block = section(html, "replicon-recovery")
    assert "No recovery-by-replicon table" not in block and "Median (IQR)" in block
    assert "size_band" in block and "arg_carrying" in block

    # Ranking robustness: table written, section populated.
    assert len(rows(DEMO / "benchmark.rank_robustness.tsv")) > 0
    assert "No ranking-robustness table" not in section(html, "rank-robustness")

    # Truth-label audit: demo annotation has no caller provenance, so nothing may be called consistent
    # on the strength of absence; the section reports counts rather than an empty-state apology.
    audit = rows(DEMO / "benchmark.truth_label_audit.tsv")
    assert audit and all(r["finding"] in {"consistent", "not_evaluated", "chromosome_with_plasmid_markers",
                                          "plasmid_without_markers"} for r in audit)
    assert "not_evaluated" in section(html, "truth-label-audit")

    # Stratified performance and paired comparisons reach the report.
    assert len(rows(DEMO / "benchmark.stratified.tsv")) > 0
    assert "No stratified table" not in section(html, "stratified")
    assert "id='orthogonal-evidence'" in html

    # Further dimensions: tables written, sections populated (not the empty-state message).
    for table in ("accuracy", "missing_regions", "feature_preservation", "ngoc", "bin_quality", "performance",
                  "power", "scenarios", "scenario_performance", "composite", "composite_sensitivity"):
        assert len(rows(DEMO / f"benchmark.{table}.tsv")) > 0, table
    for sid, empty_text in (("accuracy-dimension", "No accuracy table"), ("feature-preservation", "No feature-preservation"),
                            ("bin-quality", "No bin-quality table"), ("performance", "No performance table"),
                            ("power", "No power table"), ("scenarios", "No scenario table"),
                            ("composite", "No composite table")):
        assert empty_text not in section(html, sid), sid
    assert all(r["accuracy_status"] for r in rows(DEMO / "benchmark.accuracy.tsv")), "accuracy_status missing"
    composite = rows(DEMO / "benchmark.composite.tsv")
    assert all(r["status"] in ("ranked", "gated", "not_evaluated") for r in composite)
    assert "id='reproducibility'" in html and "Run the benchmark twice" in section(html, "reproducibility")

    # Every section is reachable from the nav.
    for name in ("replicon-recovery", "rank-robustness", "truth-label-audit", "stratified",
                 "orthogonal-evidence", "quast-diagnostics", "accuracy-dimension", "feature-preservation",
                 "bin-quality", "performance", "power", "scenarios", "composite", "reproducibility"):
        assert f"href='#{name}'" in html, name
    print("demo run -> per-plasmid files -> stratification, robustness, audit, strata -> HTML: PASS")
    print("ALL DEMO END-TO-END TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
