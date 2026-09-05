#!/usr/bin/env python3
"""The HTML report must rank WITHIN an analysis track, never across tracks.

aggregate_results.py has always written per-track leaderboards beside the
pooled one, with the explicit comment "never mix track claims" -- but the HTML
report was handed only the pooled file, so enabling any long-read or hybrid
tool produced a headline table ranking it against short-read tools on the same
isolates. Those tools were given different inputs, so that is not a
like-for-like comparison, and it is exactly what docs/METHODS.md promises the
benchmark does not do.

This pins both halves: a single-track run still renders one plain ranking
(the overwhelmingly common case, which must not change), and a multi-track run
renders one ranking per track plus an explicit note, with the headline
"winner" metric naming the track it belongs to.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "python" / "build_html_report.py"

# The real stage-5 schema (python/score_plasmids.py), so the fixture exercises
# the same row shape the report actually receives.
SCORE_COLUMNS = ["sample", "tool", "analysis_track", "true_plasmid_bp", "TP_bp", "FP_bp", "FN_bp",
                 "mapped_pred_bp", "unambiguously_mapped_pred_bp", "unmapped_pred_bp",
                 "off_truth_pred_bp", "ambiguously_mapped_pred_bp", "true_plasmid_count",
                 "recovered_plasmid_count", "plasmid_recall", "predicted_record_count",
                 "true_amr_gene_count", "recovered_amr_gene_count", "amr_gene_recall",
                 "true_circular_plasmid_count", "recovered_circular_plasmid_count",
                 "circular_truth_plasmid_recovery", "circular_plasmid_recall", "alignment_total",
                 "alignment_retained", "filtered_alignment_count", "precision", "recall", "f1"]
SCORE_HEADER = "\t".join(SCORE_COLUMNS) + "\n"
LEADER_HEADER = ("rank\ttool\tn_samples\tn_completed\tn_failed\tn_skipped\tmean_precision\t"
                 "mean_recall\tmean_f1\tmean_plasmid_recall\n")


def score_row(sample, tool, track, f1):
    values = {"sample": sample, "tool": tool, "analysis_track": track,
              "true_plasmid_bp": "10000", "TP_bp": "9000", "FP_bp": "100", "FN_bp": "1000",
              "mapped_pred_bp": "9100", "unambiguously_mapped_pred_bp": "9100",
              "unmapped_pred_bp": "0", "off_truth_pred_bp": "0", "ambiguously_mapped_pred_bp": "0",
              "true_plasmid_count": "2", "recovered_plasmid_count": "2", "plasmid_recall": "0.900",
              "predicted_record_count": "2", "precision": "0.900", "recall": "0.900", "f1": f1}
    return "\t".join(values.get(column, "0") for column in SCORE_COLUMNS) + "\n"


def leader_row(rank, tool, f1):
    return f"{rank}\t{tool}\t1\t1\t0\t0\t0.900\t0.900\t{f1}\t0.900\n"


def build(tmp, tracks):
    """Write a minimal results tree; tracks maps track -> [(tool, f1), ...]."""
    results = Path(tmp) / "results"
    results.mkdir(parents=True, exist_ok=True)
    scores, pooled = SCORE_HEADER, []
    status = "sample\ttool\tstatus\toutput\treason\tseconds\trss_kb\n"
    for track, tools in tracks.items():
        for tool, f1 in tools:
            scores += score_row("s1", tool, track, f1)
            status += f"s1\t{tool}\tcompleted\tpred.fasta\t\t1\t1000\n"
            pooled.append((tool, f1))
        with open(results / f"benchmark.{track}.leaderboard.tsv", "w", encoding="utf-8") as handle:
            handle.write(LEADER_HEADER)
            for rank, (tool, f1) in enumerate(sorted(tools, key=lambda p: -float(p[1])), start=1):
                handle.write(leader_row(rank, tool, f1))
    (results / "scores.tsv").write_text(scores, encoding="utf-8")
    (results / "tool_status.tsv").write_text(status, encoding="utf-8")
    with open(results / "benchmark.leaderboard.tsv", "w", encoding="utf-8") as handle:
        handle.write(LEADER_HEADER)
        for rank, (tool, f1) in enumerate(sorted(pooled, key=lambda p: -float(p[1])), start=1):
            handle.write(leader_row(rank, tool, f1))
    sheet = Path(tmp) / "sheet.tsv"
    sheet.write_text("sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR\n", encoding="utf-8")
    out = results / "benchmark.report.html"
    result = subprocess.run(
        [sys.executable, str(REPORT), "--project-root", str(ROOT), "--scores", str(results / "scores.tsv"),
         "--tool-status", str(results / "tool_status.tsv"),
         "--leaderboard", str(results / "benchmark.leaderboard.tsv"),
         "--sample-sheet", str(sheet), "--out", str(out)],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return out.read_text(encoding="utf-8")


def check(name, condition, detail=""):
    if not condition:
        print("FAIL: " + name + "\n" + detail, file=sys.stderr)
        raise SystemExit(1)
    print("  " + name + " -> PASS")


# --- single track: unchanged, one plain ranking table ------------------------
with tempfile.TemporaryDirectory() as tmp:
    html = build(tmp, {"short_read": [("mob_recon", "0.910"), ("platon", "0.700")]})
    check("a single-track run renders exactly one ranking table",
          html.count("<table class='sortable'><thead><tr><th>Rank</th>") == 1)
    check("a single-track run does not claim multiple tracks",
          "analysis tracks. Each is ranked separately" not in html)
    check("the headline winner carries no track qualifier when there is only one track",
          "· Short-read track · method ranking only" not in html)
    check("both tools are still ranked", "mob_recon" in html and "platon" in html)

# --- multiple tracks: one ranking each, never pooled -------------------------
with tempfile.TemporaryDirectory() as tmp:
    html = build(tmp, {"short_read": [("mob_recon", "0.910")],
                       "hybrid": [("plassembler", "0.960")]})
    check("a multi-track run renders one ranking table per track",
          html.count("<table class='sortable'><thead><tr><th>Rank</th>") == 2,
          "expected 2 ranking tables")
    check("it says plainly that tracks are ranked separately and not pooled",
          "analysis tracks. Each is ranked separately" in html and "never pooled" in html)
    check("each track is named", "Short-read track" in html and "Hybrid (long + short) track" in html)
    check("each track links its own leaderboard TSV",
          "benchmark.short_read.leaderboard.tsv" in html and "benchmark.hybrid.leaderboard.tsv" in html)

    # The hybrid tool has the higher F1. Pooling would crown it overall; the
    # headline must instead belong to the track carrying the run, and say so.
    check("the headline winner names the track it belongs to",
          "· Short-read track · method ranking only" in html,
          "the hero metric must be scoped to one track when several were scored")
    # The hero metric specifically -- the per-sample drill-down below it still
    # lists every tool that ran on the sample, across tracks, which is a
    # factual listing rather than a ranking claim.
    check("the headline winner is the headline track's leader, not the pooled top",
          "Benchmark winner: mean F1</small><strong>0.910</strong>" in html,
          "0.960 is the hybrid tool's F1; pooling would have crowned it overall")

# --- no per-track files (older results dir): falls back, still renders -------
with tempfile.TemporaryDirectory() as tmp:
    results = Path(tmp) / "results"; results.mkdir(parents=True)
    (results / "scores.tsv").write_text(SCORE_HEADER + score_row("s1", "mob_recon", "short_read", "0.910"),
                                        encoding="utf-8")
    (results / "tool_status.tsv").write_text("sample\ttool\tstatus\toutput\treason\tseconds\trss_kb\n"
                                             "s1\tmob_recon\tcompleted\tp.fasta\t\t1\t1000\n", encoding="utf-8")
    (results / "benchmark.leaderboard.tsv").write_text(LEADER_HEADER + leader_row(1, "mob_recon", "0.910"),
                                                       encoding="utf-8")
    sheet = Path(tmp) / "sheet.tsv"
    sheet.write_text("sample_id\tassembly_accession\tsra_run\ns1\tNA\tSRR\n", encoding="utf-8")
    out = results / "r.html"
    result = subprocess.run(
        [sys.executable, str(REPORT), "--project-root", str(ROOT), "--scores", str(results / "scores.tsv"),
         "--tool-status", str(results / "tool_status.tsv"),
         "--leaderboard", str(results / "benchmark.leaderboard.tsv"),
         "--sample-sheet", str(sheet), "--out", str(out)],
        capture_output=True, text=True)
    check("a results dir with no per-track leaderboards still builds a report",
          result.returncode == 0, result.stderr)
    check("and still ranks the tool it has",
          "mob_recon" in out.read_text(encoding="utf-8"))

print("ALL REPORT TRACK TESTS PASSED")
