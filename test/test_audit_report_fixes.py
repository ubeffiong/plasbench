#!/usr/bin/env python3
"""The report's headline layer, after the audit (AU-007, 015, 016, 017, 018, 019, 020, 028 and the dangling #enterprise anchor).

Unit checks call the report functions on small fixtures; the end-to-end checks build the report from a copy of results_real_cohort1 (a real run, 10 isolates,
a headline ranking that rests on one isolate) and read the page.

  AU-007  Runs completed is completed / (completed + failed + skipped), never above 100% (it read 1000% on the real cohort)
  AU-015  chromosomal contamination is FP bp / (TP bp + FP bp), as the glossary says
  AU-016  Methods compared counts tools across tasks; Leading method says when it is the only tool of its task; Runs not completed separates failed from skipped
  AU-017  the 'valid for' table and the leaderboard use one unit count and one threshold (resampling.MIN_CLUSTERS_CI)
  AU-018  Run metadata shows the version, databases, container and settings of the manifest, the versions of tools that ran only, no home folders, and no demo-data
          sentences on a real run
  AU-019  circular_plasmid_recall is labelled as coverage of circular truth plasmids, not as circularity
  AU-020  contig-level F1 is shown with the share of contigs excluded and a note that it is not comparable with base F1
  AU-028  a cohort that cannot reach Tier 1 (no curation grade A) says so
  anchor  no #enterprise link without an enterprise section
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PY = os.path.join(ROOT, "python")
sys.path.insert(0, PY)
import build_html_report as bhr  # noqa: E402
import report_common as rcm  # noqa: E402
import report_scoring_spec as rss  # noqa: E402
import report_question_bank as rqb  # noqa: E402
import report_merge  # noqa: E402
import data_nature  # noqa: E402
from resampling import MIN_CLUSTERS_CI  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {str(detail)[:400]}"))
    ok = ok and bool(good)


COHORT = os.path.join(ROOT, "results_real_cohort1")

# ---- AU-007 -------------------------------------------------------------------------------------------------------------------------------------------------
row = {"tool": "t", "n_samples": "1", "n_completed": "10", "n_failed": "0", "n_skipped": "0", "mean_f1": "0.9", "mean_plasmid_recall": "0.9"}
card = bhr.report_cards([row], [])[0]
check("AU-007: 10 completed runs and 1 scored isolate: completion is 100%, not 1000%", card["parts"]["completion"] == 1.0, card["parts"])
card = bhr.report_cards([dict(row, n_failed="2", n_skipped="3")], [])[0]
check("AU-007: numerator and denominator are the same runs: 10 / (10 + 2 + 3)", abs(card["parts"]["completion"] - 10 / 15) < 1e-9, card["parts"])
card = bhr.report_cards([dict(row, n_completed="0", n_failed="0", n_skipped="0", n_samples="1")], [])[0]
check("AU-007: a scored tool with no run in the status table is 0%, never above 100%", 0 <= card["parts"]["completion"] <= 1, card["parts"])
completions = [bhr.report_cards([dict(row, n_samples=str(s), n_completed=str(c), n_failed=str(f), n_skipped="0")], [])[0]["parts"]["completion"]
               for s in (0, 1, 5) for c in (0, 3, 12) for f in (0, 4)]
check("AU-007: never above 100% for any counts", all(v is None or 0 <= v <= 1 for v in completions), completions)
grades = {bhr.report_cards([dict(row, n_completed=str(c))], [])[0]["grade"] for c in (10, 100)}
check("AU-007: the grade does not move with the unclamped count", len(grades) == 1, grades)

# ---- AU-015 -------------------------------------------------------------------------------------------------------------------------------------------------
scores = [{"tool": "t", "sample": "a", "true_plasmid_bp": "5000", "TP_bp": "900", "FP_bp": "100"},
          {"tool": "t", "sample": "b", "true_plasmid_bp": "5000", "TP_bp": "0", "FP_bp": "0"}]
card = bhr.report_cards([dict(row)], scores)[0]
check("AU-015: contamination = FP / (TP + FP) = 10%, an isolate that covers no truth base is left out (the old FP / (true plasmid + FP) gave 1.96%)",
      abs(card["parts"]["contamination"] - 0.10) < 1e-9, card["parts"])
check("AU-015: no TP/FP columns: not measured, not 0", bhr.report_cards([dict(row)], [{"tool": "t", "sample": "a", "true_plasmid_bp": "5000"}])[0]["parts"]["contamination"] is None)
glossary = bhr.GLOSSARY["Chromosomal contamination"]["what"] if hasattr(bhr, "GLOSSARY") else ""
src = Path(PY, "build_html_report.py").read_text(encoding="utf-8")
check("AU-015: the glossary names the formula the card computes", "TP bp + FP bp" in src and "FP bp / (TP bp + FP bp)" in src)

# ---- AU-016 -------------------------------------------------------------------------------------------------------------------------------------------------
board = [{"tool": f"t{i}", "task": "binning_reconstruction", "analysis_track": "short_read", "mean_f1": "0.8", "mean_plasmid_recall": "0.8", "ranking_score": "0.8", "ranking_metric": "lw_bin_f1",
          "n_samples": "5", "n_completed": "5", "n_failed": "0", "n_skipped": "0"} for i in range(1)]
others = board + [dict(board[0], tool=f"x{i}", task="classification") for i in range(3)]
html = bhr.summary_section(board, bhr.report_cards(board, []), [], [], Counter({"failed": 2, "skipped": 3, "completed": 20}), {}, all_leaderboards=others)
tiles = re.findall(r"<small>([^<]*)</small><strong>(.*?)</strong>", html)
tile = {label: value for label, value in tiles}
check("AU-016: Methods compared counts the tools of every task (4), not the headline task's 1", tile.get("Methods compared") == "4", tile)
check("AU-016: Leading method says it is the only tool of its task", "only tool in its task" in tile.get("Leading method", ""), tile)
check("AU-016: Runs not completed separates failed from skipped", "2 failed" in tile.get("Runs not completed", "") and "3 skipped" in tile.get("Runs not completed", "") and tile["Runs not completed"].startswith("5"), tile)
two = [board[0], dict(board[0], tool="t9")]
html2 = bhr.summary_section(two, bhr.report_cards(two, []), [], [], Counter(), {}, all_leaderboards=two)
check("AU-016: no 'only tool' note when the task has several tools", "only tool in its task" not in html2)

# ---- AU-017 -------------------------------------------------------------------------------------------------------------------------------------------------
prov = [{"reference_tier": "1"}, {"reference_tier": "2"}]
evaluation = [{"n_folds": "3"}]
lb3 = [{"tool": "a", "n_ranking_clusters": "3"}]
text = rss.validity_section(lb3, prov, evaluation)
check("AU-017: 3 independent units is not 'validated' (the interval needs MIN_CLUSTERS_CI)", "partially validated" in text and "3 independent unit" in text and f"{MIN_CLUSTERS_CI}" in text and "held-out studies" not in text, text[:600])
text = rss.validity_section([{"tool": "a", "n_ranking_clusters": str(MIN_CLUSTERS_CI)}], prov, evaluation)
check("AU-017: MIN_CLUSTERS_CI units is validated, and says so with the same figure", ">validated<" in text.replace(" ", "") or "validated</td>" in text, text[:600])
check("AU-017: the leaderboard text is built from the same constant", f'f"< {{MIN_CLUSTERS_CI}} independent units"' in src and "< 5 independent units" not in src)

# ---- AU-019, AU-020, AU-028 ---------------------------------------------------------------------------------------------------------------------------------
rows = [{"tool": "t", "contigs_evaluable": "8", "contigs_ambiguous": "1", "contigs_unplaced": "1", "contigs_chimeric": "0", "contigs_short": "0"},
        {"tool": "u", "contigs_evaluable": "10"}]
share = rcm.contig_exclusion(rows, "t")
check("AU-020: the excluded share is ambiguous + unplaced + chimeric + short over all contigs (2 of 10 = 20%)", share == (2, 10, 0.2), share)
check("AU-020: no contig columns: 'not recorded'", rcm.contig_exclusion_text([{"tool": "t"}], "t") == "not recorded")
lbc = [{"tool": "t", "analysis_track": "short_read", "task": "classification", "mean_f1": "0.9", "mean_contig_f1_bp": "0.5", "mean_contig_mcc_bp": "0.4", "mean_contig_bin_f1_bp": "0.3"}]
text = rss.contig_layer_section(lbc, rows, [])
check("AU-020: the contig layer shows the excluded share beside contig F1 and says it is not comparable with base F1",
      "Contigs excluded from contig F1" in text and "20% (2 of 10 contigs)" in text and "Not comparable with base-level F1" in text, text[-900:])
text = rqb.metric_framework_section(lbc, None, rows)
check("AU-020: the metric table carries the same column and note", "Contigs excluded from contig F1" in text and "20% (2 of 10 contigs)" in text and "not comparable with base F1" in text, text[-500:])

b_rows = [{"sample": "s1", "reference_tier": "2", "tier_reason": "long-read-first; cohort truth_quality_tier B"}]
check("AU-028: every curation grade B and no Tier 1 row: the report says no sample can reach Tier 1", "No sample in this run can reach Tier 1" in bhr.tier1_unreachable_note(b_rows, ["B"]))
check("AU-028: the grade is also read from the provenance reasons", "No sample in this run can reach Tier 1" in bhr.tier1_unreachable_note(b_rows))
check("AU-028: a grade A row keeps Tier 1 attainable: no banner", bhr.tier1_unreachable_note(b_rows, ["A", "B"]) == "")
check("AU-028: a Tier 1 row exists: no banner", bhr.tier1_unreachable_note(b_rows + [{"reference_tier": "1"}], ["B"]) == "")

# ---- AU-018 helpers ---------------------------------------------------------------------------------------------------------------------------------------
check("AU-018: a home folder is redacted", bhr.redact_paths("/home/alice/envs/x/bin/tool: warning; C:\\Users\\bob\\data and /Users/carol/z") == "~/envs/x/bin/tool: warning; ~\\data and ~/z",
      bhr.redact_paths("/home/alice/envs/x/bin/tool: warning; C:\\Users\\bob\\data and /Users/carol/z"))
check("AU-018: a version that is a warning blurb is clipped to one redacted line", bhr.clean_version("/home/u/x.py:3: UserWarning: " + "y" * 300 + "\nsecond").startswith("~/x.py:3") and len(bhr.clean_version("z" * 400)) <= 120)
check("AU-018: the demo sentences are stripped from a real page and kept for a synthetic one",
      "synthetic" not in data_nature.strip_demo_boilerplate("a. The bundled demo data are synthetic and flat: counts from them demonstrate the engine, not a biological result. b")
      and data_nature.strip_demo_boilerplate("x, and the demo data are synthetic and flat: read it") == "x: read it")
page = "<section id='plasmid-maps'><h2>Plasmid maps</h2><p class='lead'>lead</p></section>"
check("anchor: the maps cross-link does not point at #enterprise when no enterprise section exists", "#enterprise" not in report_merge._cross_links(page), report_merge._cross_links(page))
check("anchor: it does when the section exists", "#enterprise" in report_merge._cross_links(page + "<section id='enterprise'><h2>x</h2><p class='lead'>l</p></section>"))

# ---- end to end on the real cohort ------------------------------------------------------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as work:
    results = Path(work) / "results_real_cohort1"
    shutil.copytree(COHORT, results, ignore=shutil.ignore_patterns("benchmark.report.html"))
    prefix = str(results / "benchmark")
    cmd = [sys.executable, os.path.join(PY, "build_html_report.py"), "--project-root", ROOT, "--scores", str(results / "scores.tsv"), "--tool-status", str(results / "tool_status.tsv"),
           "--leaderboard", prefix + ".leaderboard.tsv", "--manifest", str(results / "run_manifest.json"), "--comparisons", prefix + ".paired_comparisons.tsv",
           "--score-failures", str(results / "score_failures.tsv"), "--recommendations", prefix + ".recommendations.tsv", "--dimensions-prefix", prefix,
           "--stratified", prefix + ".stratified.tsv", "--rank-robustness", prefix + ".rank_robustness.tsv", "--truth-provenance", prefix + ".truth_provenance.tsv",
           "--outcome-states", prefix + ".outcome_states.tsv", "--out", str(results / "benchmark.report.html")]
    run = subprocess.run(cmd, capture_output=True, text=True)
    check("end to end: the real cohort builds", run.returncode == 0, run.stderr[-500:])
    page = (results / "benchmark.report.html").read_text(encoding="utf-8") if run.returncode == 0 else ""

    cell = re.search(r"data-iso-slot='summary-card'>(.*?)</tbody>", page, re.S)
    percents = [float(p) for p in re.findall(r"([0-9.]+)%", re.sub(r"<[^>]+>", "|", cell.group(1)))] if cell else [9999]
    check("AU-007: the report card on the real cohort has no percentage above 100 (it read 1000%)", cell is not None and max(percents) <= 100, percents)
    stats = re.findall(r"<small>([^<]*)</small><strong>(.*?)</strong>", page[page.find("class='sum-stats'"):][:3000])
    tile = {label: re.sub(r"<[^>]+>", " ", value).strip() for label, value in stats}
    check("AU-016: on the real cohort 4 methods are compared (it read 1)", tile.get("Methods compared") == "4", tile)
    check("AU-016: the leader is marked as the only tool of its task, and skipped runs are split from failed", "only tool in its task" in tile.get("Leading method", "") and "skipped" in tile.get("Runs not completed", ""), tile)
    check("AU-018: the metadata shows the PlasBench version and the databases", "PlasBench version" in page and "PlasBench 0.2.3" in page and "Databases" in page and "Key settings" in page)
    check("AU-018: only the tools that ran are in the version list (not plasmidhunter, which was installed but not run)", "Tool versions (tools that ran)" in page and "plasmidhunter" not in page.split("Tool versions (tools that ran)")[1][:600].lower())
    check("AU-018: no home folder appears anywhere in the page", "/home/" not in page, [page[m.start() - 60:m.start() + 60] for m in re.finditer("/home/", page)][:2])
    check("AU-018: no demo-data sentence on a real run", not re.search(r"demo data are synthetic|demonstrate the engine", page, re.I))
    check("AU-019: the circular column is labelled as coverage of circular truth plasmids", "Coverage of circular truth plasmids" in page and "Circular truth recovery" not in page)
    check("anchor: no #enterprise link when the dashboard is not embedded", "#enterprise" not in page or "id='enterprise'" in page)
    check("AU-017: the leaderboard says '< 5 independent units' from the shared constant", f"&lt; {MIN_CLUSTERS_CI} independent units" in page or f"< {MIN_CLUSTERS_CI} independent units" in page)

print()
print("ALL AUDIT REPORT FIX TESTS PASSED" if ok else "SOME AUDIT REPORT FIX TESTS FAILED")
sys.exit(0 if ok else 1)
