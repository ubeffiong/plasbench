#!/usr/bin/env python3
"""
The primary analysis is unavailable, visibly, when no reference qualifies; it never silently falls back to all samples.

Design (python/headline_design.py, headline_selection):
  - no provenance table: unavailable, reason says no sample can be shown to meet the requirement, rows are ALL samples, labelled provisional;
  - provenance with only tier-3 references: unavailable, provisional; a tier-1 or tier-2 sample: available, only those samples are the headline;
  - allow_fallback keeps the numbers as the headline with status 'fallback_allowed' and the warning in the label; it changes nothing when a reference qualifies;
  - headline_rows (the old interface) returns the same rows and the same basis label.
Aggregation (aggregate_results.py, the real script on a tiny scores table):
  - leaderboard rows carry primary_status and population (appended last), the markdown leaderboard says PROVISIONAL, benchmark.headline_design.tsv carries primary_status;
  - with a tier-1 provenance row the status is 'available' and no provisional wording appears; --allow-primary-fallback gives 'fallback_allowed'.
Report (build_html_report.py): the banner above the ranking, the Summary tile and the first finding say provisional / unavailable; a leaderboard without the column
(an older run) is treated as available and unchanged; the headline design table has a Primary analysis column.
"""
import csv
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import headline_design as hd  # noqa: E402

AGGREGATE = ROOT / "python" / "aggregate_results.py"
REPORT = ROOT / "python" / "build_html_report.py"


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    rows = [{"sample": "s1", "tool": "t"}, {"sample": "s2", "tool": "t"}]

    def provenance(tmp, tiers):
        path = Path(tmp) / "prov.tsv"
        path.write_text("sample\treference_tier\n" + "".join(f"{s}\t{t}\n" for s, t in tiers.items()), encoding="utf-8")
        return str(path)

    print("the design")
    with tempfile.TemporaryDirectory() as tmp:
        sel = hd.Design().headline_selection(rows)
        check("no provenance table: unavailable, all samples, labelled provisional, reason given",
              sel.status == hd.PRIMARY_UNAVAILABLE and sel.rows == rows and sel.basis.startswith("provisional: all samples") and "no truth-provenance table" in sel.reason
              and sel.population.startswith("provisional"), sel)
        d3 = hd.Design(provenance=provenance(tmp, {"s1": "3", "s2": "3"}))
        sel = d3.headline_selection(rows)
        check("only tier-3 references: unavailable, provisional, names the tier requirement",
              sel.status == hd.PRIMARY_UNAVAILABLE and sel.rows == rows and "no sample has a reference in tiers 1-2" in sel.reason, sel)
        d1 = hd.Design(provenance=provenance(tmp, {"s1": "1", "s2": "3"}))
        sel = d1.headline_selection(rows)
        check("a tier-1 sample: available, and only the qualifying sample is the headline",
              sel.status == hd.PRIMARY_AVAILABLE and [r["sample"] for r in sel.rows] == ["s1"] and sel.population == "primary: reference tiers 1-2" and not sel.reason, sel)
        sel = d3.headline_selection(rows, allow_fallback=True)
        check("allow_fallback: status fallback_allowed and the warning stays in the label",
              sel.status == hd.PRIMARY_FALLBACK and "FALLBACK ALLOWED" in sel.basis and sel.rows == rows, sel)
        check("allow_fallback changes nothing when a reference qualifies", d1.headline_selection(rows, allow_fallback=True).status == hd.PRIMARY_AVAILABLE)
        check("headline_rows still returns (rows, basis) with the same labels", d3.headline_rows(rows) == (rows, d3.headline_selection(rows).basis))

    print("aggregation")
    header = ["sample", "tool", "true_plasmid_bp", "TP_bp", "FP_bp", "FN_bp", "unmapped_pred_bp", "precision", "recall", "f1", "bin_precision", "bin_recall", "bin_f1",
              "matched_bins", "unmatched_bins", "missed_plasmids", "split_events", "merge_events", "contaminated_bins"]

    def aggregate(tmp, tiers=None, extra=()):
        scores = Path(tmp) / "scores.tsv"
        with open(scores, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, delimiter="\t")
            writer.writerow(header)
            writer.writerow(["s1", "tool_a", 100, 80, 20, 20, 0, "0.8", "0.8", "0.8", "0.5", "0.5", "0.5", 1, 1, 1, 2, 3, 4])
        prefix = str(Path(tmp) / "benchmark")
        cmd = [sys.executable, str(AGGREGATE), "--scores", str(scores), "--tool-status", str(Path(tmp) / "absent.tsv"), "--out-prefix", prefix, *extra]
        if tiers is not None:
            cmd += ["--truth-provenance", provenance(tmp, tiers)]
        done = subprocess.run(cmd, capture_output=True, text=True)
        board = list(csv.DictReader(open(prefix + ".leaderboard.tsv", newline="", encoding="utf-8"), delimiter="\t"))
        return done, board, prefix

    with tempfile.TemporaryDirectory() as tmp:
        done, board, prefix = aggregate(tmp, {"s1": "3"})
        names = list(board[0])
        check("leaderboard rows carry primary_status and population, appended last", board[0]["primary_status"] == "unavailable" and board[0]["population"].startswith("provisional")
              and names[-2:] == ["primary_status", "population"], names[-3:])
        md = open(prefix + ".leaderboard.md", encoding="utf-8").read()
        check("the markdown leaderboard says PROVISIONAL", "PROVISIONAL: primary analysis unavailable" in md and "not the primary result" in md)
        design = list(csv.DictReader(open(prefix + ".headline_design.tsv", newline="", encoding="utf-8"), delimiter="\t"))
        check("the headline design table carries primary_status", design and design[0]["primary_status"] == "unavailable")
        check("a warning is printed", "PRIMARY ANALYSIS UNAVAILABLE" in done.stdout, done.stdout[-300:])
    with tempfile.TemporaryDirectory() as tmp:
        _done, board, prefix = aggregate(tmp, {"s1": "1"})
        md = open(prefix + ".leaderboard.md", encoding="utf-8").read()
        check("a tier-1 reference: available, no provisional wording", board[0]["primary_status"] == "available" and "PROVISIONAL" not in md and board[0]["population"].startswith("primary"))
    with tempfile.TemporaryDirectory() as tmp:
        _done, board, _prefix = aggregate(tmp, {"s1": "3"}, extra=["--allow-primary-fallback"])
        check("--allow-primary-fallback: status fallback_allowed", board[0]["primary_status"] == "fallback_allowed")
    with tempfile.TemporaryDirectory() as tmp:
        _done, board, _prefix = aggregate(tmp)
        check("no provenance table at all: unavailable (it never claims a primary analysis)", board[0]["primary_status"] == "unavailable")

    print("the report")
    def build(tmp, status):
        results = Path(tmp) / "results"
        results.mkdir()
        scores = results / "scores.tsv"
        with open(scores, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, delimiter="\t")
            writer.writerow(header + ["analysis_track", "true_plasmid_count"])
            for tool, f1 in (("tool_a", "0.9"), ("tool_b", "0.8")):
                writer.writerow(["s1", tool, 100, 80, 20, 20, 0, "0.9", "0.9", f1, "0.5", "0.5", "0.5", 1, 1, 1, 2, 3, 4, "short_read", 2])
        columns = ["rank", "analysis_track", "task", "tool", "n_samples", "n_completed", "n_failed", "n_skipped", "mean_precision", "mean_recall", "mean_f1", "mean_plasmid_recall",
                   "ranking_metric", "ranking_score"]
        extra = ["primary_status", "population"] if status else []
        board = results / "benchmark.leaderboard.tsv"
        with open(board, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, delimiter="\t")
            writer.writerow(columns + extra)
            for rank, (tool, f1) in enumerate((("tool_a", "0.9"), ("tool_b", "0.8")), start=1):
                values = [rank, "short_read", "reconstruction", tool, 1, 1, 0, 0, "0.9", "0.9", f1, "0.9", "lw_bin_f1", f1]
                if status:
                    values += [status, "provisional: all samples (no sample has a reference in tiers 1-2)" if status == "unavailable" else "primary: reference tiers 1-2"]
                writer.writerow(values)
        out = results / "report.html"
        subprocess.run([sys.executable, str(REPORT), "--project-root", str(ROOT), "--scores", str(scores), "--tool-status", str(results / "absent.tsv"),
                        "--leaderboard", str(board), "--out", str(out)], check=True, capture_output=True)
        return out.read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory() as tmp:
        page = build(tmp, "unavailable")
        check("the banner above the ranking says the primary analysis is unavailable and the table is provisional",
              "id='primary-banner'" in page and "Primary analysis unavailable." in page and "PROVISIONAL ranking" in page)
        check("the Summary tile and the first finding say provisional",
              "Leading method (provisional)" in page and "Provisional: highest" in page and "Primary analysis unavailable (no qualifying reference)" in page)
    with tempfile.TemporaryDirectory() as tmp:
        page = build(tmp, "available")
        check("an available primary analysis shows no banner and the plain tile", "id='primary-banner'" not in page and "Leading method (provisional)" not in page)
    with tempfile.TemporaryDirectory() as tmp:
        page = build(tmp, "")
        check("an older leaderboard without the column is treated as available and unchanged", "id='primary-banner'" not in page and "Leading method (provisional)" not in page)

    print()
    if not ok:
        print("PRIMARY ELIGIBILITY TESTS FAILED")
        sys.exit(1)
    print("ALL PRIMARY ELIGIBILITY TESTS PASSED")


if __name__ == "__main__":
    main()
