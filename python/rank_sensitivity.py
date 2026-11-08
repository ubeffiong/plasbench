#!/usr/bin/env python3
"""
rank_sensitivity.py -- how much does the leaderboard depend on scoring choices?

The leaderboard ranks tools by mean base-level F1 under one set of alignment
filters (MAPQ >= 20, identity >= 0.90, query coverage >= 0.20 by default) and
one definition of precision, in which predicted bases that never produce a
retained alignment are not false positives. A different, equally defensible
choice can change who is on top. This script measures that, so a ranking is
never reported without saying how fragile it is.

Two kinds of variant, per analysis track:

  scoring settings   Re-score every (sample, tool) from the PAF already on disk
                     (no minimap2 re-run) with one setting changed at a time:
                     MAPQ 0 / 30, identity 0.80 / 0.95, query coverage 0.
  metrics            Re-rank from the recorded scores.tsv columns: strict F1
                     (precision charged for unmapped predicted bases), per-
                     plasmid recovery at the configured threshold, and
                     per-plasmid recovery at >= 90% completeness.

For each variant it reports every tool's mean over the samples all tools in
the track share, its rank (ties broken by tool name), the change from baseline,
Kendall's tau between the variant and baseline orderings (1 = identical,
-1 = reversed), and whether the top tool is the same.

Limits, stated so they are not mistaken for features:
  * Samples are those with a PAF on disk. A failed run has none, so the
    failure-as-zero rule of the leaderboard is NOT applied here; this measures
    sensitivity to scoring choices, not to failures.
  * The baseline is re-computed from the PAF and compared with scores.tsv; a
    disagreement is reported, because it means the baseline here is not the
    leaderboard's.
  * It says nothing about truth quality, leakage or sample selection.

Usage:
  rank_sensitivity.py --scores results/scores.tsv --results-dir results \\
      --data-dir data --out-prefix results/benchmark

Standard library only.
"""

import argparse
import csv
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import score_plasmids as sp  # noqa: E402

# One change at a time from the baseline filters.
SETTING_VARIANTS = (
    ("mapq=0", {"min_mapq": 0}),
    ("mapq=30", {"min_mapq": 30}),
    ("identity=0.80", {"min_identity": 0.80}),
    ("identity=0.95", {"min_identity": 0.95}),
    ("query_coverage=0", {"min_query_coverage": 0.0}),
)
METRIC_VARIANTS = ("strict_f1", "plasmid_recall", "plasmid_recall_ge90")
BASELINE = "baseline"
# scores.tsv writes F1 to four decimals, so a faithful re-computation can differ
# from it by up to 5e-5. Anything larger means different scoring options.
BASELINE_TOLERANCE = 1e-4


def number(text):
    try:
        return float(text) if text not in (None, "") else None
    except ValueError:
        return None


def read_score_rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def f1_from_paf(truth_cache, results_dir, data_dir, sample, tool, settings):
    """Base-level F1 for one (sample, tool) from its PAF, or None when it has no
    PAF or the isolate has no true plasmid (F1 is undefined there)."""
    paf = results_dir / sample / f"{tool}.pred_vs_ref.paf"
    if not paf.is_file():
        return None
    if sample not in truth_cache:
        truth_path = next((p for p in (data_dir / sample / "truth.tsv" if data_dir else None,
                                       results_dir / sample / "truth.tsv") if p and p.is_file()), None)
        truth_cache[sample] = sp.read_truth(str(truth_path)) if truth_path else None
    loaded = truth_cache[sample]
    if loaded is None:
        return None
    truth, total_plasmid, _ = loaded
    if total_plasmid == 0:
        return None
    pred = results_dir / sample / f"pred_{tool}.plasmid.fasta"
    pred_lengths = sp.read_fasta_lengths(str(pred)) if pred.is_file() and pred.stat().st_size else {}
    covered = sp.parse_paf_intervals(str(paf), truth, pred_lengths, **settings)[0]
    tp, fp, fn = sp.score(truth, total_plasmid, covered)
    if tp == 0:
        return 0.0
    precision, recall = tp / (tp + fp), tp / (tp + fn)
    return 2 * precision * recall / (precision + recall)


def strict_f1(row):
    precision, recall = number(row.get("strict_precision")), number(row.get("recall"))
    if precision is None or recall is None:
        return None
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def ranked(values_by_tool):
    """[(tool, mean, n, rank)] over the samples every tool has, best first; ties by name."""
    tools = [tool for tool, values in values_by_tool.items() if values]
    if not tools:
        return []
    shared = set.intersection(*(set(values_by_tool[tool]) for tool in tools))
    if not shared:
        return []
    means = {tool: sum(values_by_tool[tool][s] for s in shared) / len(shared) for tool in tools}
    order = sorted(tools, key=lambda tool: (-means[tool], tool))
    return [(tool, means[tool], len(shared), rank) for rank, tool in enumerate(order, start=1)]


def kendall_tau(rank_a, rank_b):
    """Kendall's tau over the tools both rankings contain; None if fewer than two."""
    tools = sorted(set(rank_a) & set(rank_b))
    if len(tools) < 2:
        return None
    concordant = discordant = 0
    for i, a in enumerate(tools):
        for b in tools[i + 1:]:
            product = (rank_a[a] - rank_a[b]) * (rank_b[a] - rank_b[b])
            concordant += product > 0
            discordant += product < 0
    return (concordant - discordant) / (len(tools) * (len(tools) - 1) / 2)


def build_variants(rows, results_dir, data_dir, base_settings):
    """{variant: {track: {tool: {sample: value}}}} plus baseline-vs-recorded drift."""
    variants = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    truth_cache = {}
    drift = []
    for row in rows:
        sample, tool = row.get("sample"), row.get("tool")
        track = row.get("analysis_track") or "short_read"
        if not sample or not tool:
            continue
        baseline = f1_from_paf(truth_cache, results_dir, data_dir, sample, tool, base_settings)
        if baseline is not None:
            variants[BASELINE][track][tool][sample] = baseline
            recorded = number(row.get("f1"))
            if recorded is not None:
                drift.append((abs(recorded - baseline), sample, tool))
            for name, change in SETTING_VARIANTS:
                value = f1_from_paf(truth_cache, results_dir, data_dir, sample, tool, dict(base_settings, **change))
                if value is not None:
                    variants[name][track][tool][sample] = value
        for metric in METRIC_VARIANTS:
            value = strict_f1(row) if metric == "strict_f1" else number(row.get(metric))
            if value is not None:
                variants[f"metric:{metric}"][track][tool][sample] = value
    return variants, drift


def analyse(variants):
    """Rows for the output table, one per (track, variant, tool)."""
    out = []
    for track in sorted({t for per_track in variants.values() for t in per_track}):
        baseline = {tool: rank for tool, _, _, rank in ranked(variants[BASELINE].get(track, {}))}
        baseline_top = min(baseline, key=baseline.get) if baseline else None
        for variant in [BASELINE] + [name for name, _ in SETTING_VARIANTS] + [f"metric:{m}" for m in METRIC_VARIANTS]:
            result = ranked(variants.get(variant, {}).get(track, {}))
            if not result:
                continue
            ranks = {tool: rank for tool, _, _, rank in result}
            tau = kendall_tau(baseline, ranks) if baseline else None
            top = result[0][0]
            for tool, mean, n, rank in result:
                out.append({
                    "analysis_track": track, "variant": variant, "tool": tool,
                    "mean_value": f"{mean:.4f}", "n_samples": n, "rank": rank,
                    "baseline_rank": baseline.get(tool, ""),
                    "rank_change": (baseline[tool] - rank) if tool in baseline else "",
                    "kendall_tau_vs_baseline": "" if tau is None else f"{tau:.3f}",
                    "top_tool": top,
                    "top_matches_baseline": "" if baseline_top is None else ("yes" if top == baseline_top else "no"),
                })
    return out


COLUMNS = ["analysis_track", "variant", "tool", "mean_value", "n_samples", "rank", "baseline_rank",
           "rank_change", "kendall_tau_vs_baseline", "top_tool", "top_matches_baseline"]


def summarise(rows):
    """Human-readable lines: one per track and variant, and an overall verdict."""
    lines, sensitive = [], False
    seen = set()
    for row in rows:
        key = (row["analysis_track"], row["variant"])
        if key in seen or row["variant"] == BASELINE:
            continue
        seen.add(key)
        tau = row["kendall_tau_vs_baseline"] or "n/a"
        flag = ""
        if row["top_matches_baseline"] == "no" or (tau != "n/a" and float(tau) < 1.0):
            sensitive = True
            flag = "  <-- ranking changes"
        lines.append(f"  [{row['analysis_track']}] {row['variant']:<22} tau={tau:<6} top={row['top_tool']}"
                     f" (same as baseline: {row['top_matches_baseline'] or 'n/a'}){flag}")
    return lines, sensitive


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scores", required=True, help="scores.tsv from stage 5")
    ap.add_argument("--results-dir", required=True)
    ap.add_argument("--data-dir", help="per-sample data dir holding <sample>/truth.tsv (else results/<sample>/truth.tsv)")
    ap.add_argument("--out-prefix", required=True, help="writes <prefix>.rank_robustness.tsv")
    ap.add_argument("--min-alignment-length", type=int, default=int(os.environ.get("MIN_ALIGNMENT_LENGTH", 200)))
    ap.add_argument("--min-alignment-identity", type=float, default=float(os.environ.get("MIN_ALIGNMENT_IDENTITY", 0.90)))
    ap.add_argument("--min-alignment-mapq", type=int, default=int(os.environ.get("MIN_ALIGNMENT_MAPQ", 20)))
    ap.add_argument("--min-alignment-query-coverage", type=float,
                    default=float(os.environ.get("MIN_ALIGNMENT_QUERY_COVERAGE", 0.20)))
    args = ap.parse_args()

    base = {"min_length": args.min_alignment_length, "min_identity": args.min_alignment_identity,
            "min_mapq": args.min_alignment_mapq, "min_query_coverage": args.min_alignment_query_coverage}
    rows = read_score_rows(args.scores)
    variants, drift = build_variants(rows, Path(args.results_dir),
                                     Path(args.data_dir) if args.data_dir else None, base)
    if not variants.get(BASELINE):
        raise SystemExit("ERROR: no (sample, tool) pair had a PAF and a truth table with plasmid under "
                         f"{args.results_dir}; nothing to re-score. Expected "
                         "<results>/<sample>/<tool>.pred_vs_ref.paf and a truth.tsv.")
    worst = max(drift) if drift else None
    if worst and worst[0] > BASELINE_TOLERANCE:
        print(f"[rank_sensitivity] WARNING: the re-computed baseline F1 differs from scores.tsv by up to "
              f"{worst[0]:.6f} ({worst[1]} / {worst[2]}). The scoring options used for scores.tsv were "
              f"probably not these filters, so this baseline is not the leaderboard's. Pass the same "
              f"--min-alignment-* values.", file=sys.stderr)

    table = analyse(variants)
    out_path = f"{args.out_prefix}.rank_robustness.tsv"
    with open(out_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(table)
    lines, sensitive = summarise(table)
    print(f"[rank_sensitivity] wrote {out_path}")
    print("\n".join(lines))
    print("[rank_sensitivity] " + ("The ranking CHANGES under at least one defensible scoring choice; "
                                   "do not present it as settled." if sensitive else
                                   "The ranking is unchanged under every variant tried."))


if __name__ == "__main__":
    main()
