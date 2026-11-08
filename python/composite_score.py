#!/usr/bin/env python3
"""Optional, descriptive five-dimension view of each tool, with gates and weight sensitivity.

This does NOT replace the pre-specified endpoints (ranking_score and CPRR in the leaderboard)
and never changes them. It is for readers who want one summary of the five dimensions of a
reconstruction benchmark while still seeing every dimension score:

  accuracy      mean alignment identity                              (alignment_accuracy.py)
  completeness  mean base recall and per-plasmid recall              (scores.tsv)
  structure     NGOC, complete-circular recall, V-measure of bins    (feature_preservation.py,
                                                                      bin_quality.py)
  biology       full-length feature recovery, AMR gene recall        (feature_preservation.py)
  performance   success rate, runtime, memory                        (performance_summary.py)

Each component is turned into a 0-100 score (rules below), components are averaged within their
dimension, and the dimension scores are combined with weights. The default weights
(accuracy 30, completeness 20, structure 25, biology 15, performance 10) are an initial proposal,
not a standard: they are in config/composite_weights.tsv and can be changed, and every run
reports how much the ranking moves when they are.

Component rules (all clamped to 0-100):
  identity       0 at 0.95, 100 at 0.999, linear
  recall / per-plasmid recall / NGOC / yields / success rate / feature recovery / AMR recall
                 100 x the fraction
  V-measure      100 x the value
  runtime, memory  100 for the best tool in the track, falling linearly in log10 to 0 at a
                 --log-range (default 2) orders of magnitude worse. Relative, so it moves with
                 the tools compared; it is a within-benchmark view, not an absolute grade.

Honest handling of missing evidence:
  * A component with no value is skipped; a dimension with no component is "not evaluated".
  * A dimension is used in the composite only if EVERY tool in the track has it. Otherwise it is
    dropped for all tools and listed in `dimensions_dropped`; weights are renormalised over the
    kept dimensions and `dimensions_used` says which. A composite is never compared across tools
    that were scored on different dimensions.
  * Gates: a tool whose accuracy or completeness dimension is below its minimum (default 50) is
    marked `gated` and not ranked, however fast it is. Gates are options in the weights file.

Sensitivity (composite_sensitivity.tsv): the baseline rank; the rank with each dimension left
out; and over --draws (default 500) random weight vectors (each weight multiplied by a uniform
factor in [0.5, 1.5], seeded) the mean, best and worst rank and the share of draws in which the
tool is first. A ranking that survives this is robust to the weights; one that does not should
not be reported as a ranking. Standard library only.
"""
import argparse
import csv
import math
import os
import random
import statistics
import sys
from collections import defaultdict
from plasbench_common import read_tsv, number  # noqa: E402

DIMENSIONS = ("accuracy", "completeness", "structure", "biology", "performance")
DEFAULT_WEIGHTS = {"accuracy": 30.0, "completeness": 20.0, "structure": 25.0, "biology": 15.0, "performance": 10.0}
DEFAULT_GATES = {"accuracy": 50.0, "completeness": 50.0}
COMPOSITE_FIELDS = ("analysis_track", "tool", "accuracy", "completeness", "structure", "biology", "performance",
                    "composite", "rank", "status", "gates_failed", "dimensions_used", "dimensions_dropped")
SENS_FIELDS = ("analysis_track", "tool", "variant", "rank", "mean_rank", "best_rank", "worst_rank", "share_first")


def clamp(value):
    return max(0.0, min(100.0, value))


def read_config(path):
    weights, gates = dict(DEFAULT_WEIGHTS), dict(DEFAULT_GATES)
    rows = read_tsv(path)
    if rows:                      # a config file is authoritative about gates: no row, no gate
        gates = {}
    for row in rows:
        key, value = (row.get("key") or "").strip(), number(row.get("value"))
        if value is None:
            continue
        if key.startswith("weight_") and key[7:] in DIMENSIONS:
            weights[key[7:]] = value
        elif key.startswith("gate_") and key[5:] in DIMENSIONS:
            gates[key[5:]] = value
    if any(w < 0 for w in weights.values()) or sum(weights.values()) <= 0:
        raise SystemExit("ERROR: composite weights must be non-negative and not all zero")
    return weights, gates


def mean_of(rows, column):
    values = [v for v in (number(r.get(column)) for r in rows) if v is not None]
    return statistics.mean(values) if values else None


def weighted(rows, value_col, weight_col):
    pairs = [(number(r.get(value_col)), number(r.get(weight_col))) for r in rows]
    pairs = [(v, w) for v, w in pairs if v is not None and w]
    total = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / total if total else None


def tool_measures(scores, accuracy, features, ngoc, bins, perf):
    """(track, tool) -> {component: raw value}."""
    by_tool = defaultdict(list)
    for row in scores:
        by_tool[(row.get("analysis_track") or "short_read", row["tool"])].append(row)
    tracks_of = defaultdict(set)
    for (track, tool) in by_tool:
        tracks_of[tool].add(track)
    measures = {}
    for (track, tool), rows in by_tool.items():
        m = {"recall": mean_of(rows, "recall"), "plasmid_recall": mean_of(rows, "plasmid_recall"),
             "circular": mean_of(rows, "complete_circular_plasmid_recall"),
             "amr_recall": mean_of(rows, "amr_gene_recall")}
        acc = [r for r in accuracy if r["tool"] == tool and (r.get("analysis_track") or "short_read") == track]
        m["identity"] = weighted(acc, "identity", "aligned_columns")
        feats = [r for r in features if r["tool"] == tool and r["feature_kind"] == "all"
                 and (r.get("analysis_track") or "short_read") == track]
        m["feature_recovery"] = weighted(feats, "full_length_rate", "n_expected")
        ng = [r for r in ngoc if r["tool"] == tool and (r.get("analysis_track") or "short_read") == track]
        pairs = sum(number(r.get("n_pairs")) or 0 for r in ng)
        m["ngoc"] = sum(number(r.get("n_conserved")) or 0 for r in ng) / pairs if pairs else None
        bq = [r for r in bins if r["tool"] == tool and (r.get("analysis_track") or "short_read") == track]
        m["v_measure"] = mean_of(bq, "v_measure")
        p = [r for r in perf if r["tool"] == tool]
        if p and len(tracks_of[tool]) == 1:
            m["success_rate"] = number(p[0].get("success_rate"))
            m["runtime"] = number(p[0].get("median_runtime_seconds"))
            m["memory"] = number(p[0].get("median_peak_memory_gb"))
        measures[(track, tool)] = m
    return measures


def relative_log_score(value, best, log_range):
    if value is None or best is None or value <= 0 or best <= 0:
        return None
    return clamp(100.0 * (1 - math.log10(value / best) / log_range))


def dimension_scores(measures, log_range):
    """(track, tool) -> {dimension: 0-100 or None}."""
    best = defaultdict(lambda: {"runtime": None, "memory": None})
    for (track, _), m in measures.items():
        for key in ("runtime", "memory"):
            if m.get(key):
                cur = best[track][key]
                best[track][key] = m[key] if cur is None else min(cur, m[key])
    out = {}
    for (track, tool), m in measures.items():
        def avg(*components):
            values = [c for c in components if c is not None]
            return statistics.mean(values) if values else None
        pct = lambda v: None if v is None else clamp(100.0 * v)
        identity = None if m.get("identity") is None else clamp(100.0 * (m["identity"] - 0.95) / (0.999 - 0.95))
        out[(track, tool)] = {
            "accuracy": identity,
            "completeness": avg(pct(m.get("recall")), pct(m.get("plasmid_recall"))),
            "structure": avg(pct(m.get("ngoc")), pct(m.get("circular")), pct(m.get("v_measure"))),
            "biology": avg(pct(m.get("feature_recovery")), pct(m.get("amr_recall"))),
            "performance": avg(pct(m.get("success_rate")),
                               relative_log_score(m.get("runtime"), best[track]["runtime"], log_range),
                               relative_log_score(m.get("memory"), best[track]["memory"], log_range)),
        }
    return out


def combine(dim_scores, weights, used):
    total = sum(weights[d] for d in used)
    return sum(weights[d] * dim_scores[d] for d in used) / total if total else None


def rank_of(composites):
    ordered = sorted((t for t, c in composites.items() if c is not None), key=lambda t: (-composites[t], t))
    return {tool: i + 1 for i, tool in enumerate(ordered)}


def kendall_free_ranks(tools, dims, weights, used, gated):
    comp = {t: (None if t in gated else combine(dims[t], weights, used)) for t in tools}
    return rank_of(comp)


def analyse(dims_by_key, weights, gates, draws, seed):
    composite_rows, sens_rows = [], []
    by_track = defaultdict(dict)
    for (track, tool), d in dims_by_key.items():
        by_track[track][tool] = d
    for track, tools in sorted(by_track.items()):
        used = [d for d in DIMENSIONS if all(tools[t][d] is not None for t in tools) and weights[d] > 0]
        dropped = [d for d in DIMENSIONS if d not in used]
        gated = {t for t, d in tools.items()
                 if any(d[g] is not None and d[g] < minimum for g, minimum in gates.items())}
        comp = {t: (combine(tools[t], weights, used) if used else None) for t in tools}
        ranked_input = {t: (None if t in gated else c) for t, c in comp.items()}
        ranks = rank_of(ranked_input)
        for tool in sorted(tools):
            d = tools[tool]
            failed = [g for g, minimum in gates.items() if d[g] is not None and d[g] < minimum]
            status = ("gated" if tool in gated else "ranked" if tool in ranks else "not_evaluated")
            composite_rows.append({
                "analysis_track": track, "tool": tool, **{k: d[k] for k in DIMENSIONS}, "composite": comp[tool],
                "rank": ranks.get(tool), "status": status, "gates_failed": ",".join(failed),
                "dimensions_used": ",".join(used), "dimensions_dropped": ",".join(dropped)})
        if not used or len(ranks) < 2:
            continue
        rng = random.Random(seed)
        draw_ranks = defaultdict(list)
        for _ in range(draws):
            w = {k: v * rng.uniform(0.5, 1.5) for k, v in weights.items()}
            r = kendall_free_ranks(tools, tools, w, used, gated)
            for t in ranks:
                draw_ranks[t].append(r[t])
        for tool in sorted(ranks):
            sens_rows.append({"analysis_track": track, "tool": tool, "variant": "baseline", "rank": ranks[tool]})
            for dim in used:
                if len(used) > 1:
                    kept = [x for x in used if x != dim]
                    r = kendall_free_ranks(tools, tools, weights, kept, gated)
                    sens_rows.append({"analysis_track": track, "tool": tool, "variant": f"without_{dim}",
                                      "rank": r.get(tool)})
            values = draw_ranks[tool]
            sens_rows.append({"analysis_track": track, "tool": tool, "variant": f"random_weights_{draws}",
                              "mean_rank": statistics.mean(values), "best_rank": min(values),
                              "worst_rank": max(values), "share_first": sum(v == 1 for v in values) / len(values)})
    return composite_rows, sens_rows


def fmt(value):
    return "" if value is None else (f"{value:.4f}" if isinstance(value, float) else str(value))


def write(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: fmt(row.get(k)) for k in fields})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scores", required=True)
    ap.add_argument("--accuracy", help="accuracy.tsv from alignment_accuracy.py")
    ap.add_argument("--feature-preservation", help="feature preservation TSV")
    ap.add_argument("--ngoc", help="NGOC TSV")
    ap.add_argument("--bin-quality", help="bin quality TSV")
    ap.add_argument("--performance", help="performance_summary.py output")
    ap.add_argument("--config", help="weights and gates TSV (key, value); default config/composite_weights.tsv")
    ap.add_argument("--log-range", type=float, default=2.0)
    ap.add_argument("--draws", type=int, default=500)
    ap.add_argument("--seed", type=int, default=20240607)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sensitivity-out", required=True)
    args = ap.parse_args()
    config = args.config or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config",
                                         "composite_weights.tsv")
    weights, gates = read_config(config)
    measures = tool_measures(read_tsv(args.scores), read_tsv(args.accuracy), read_tsv(args.feature_preservation),
                             read_tsv(args.ngoc), read_tsv(args.bin_quality), read_tsv(args.performance))
    rows, sens = analyse(dimension_scores(measures, args.log_range), weights, gates, args.draws, args.seed)
    write(args.out, COMPOSITE_FIELDS, rows)
    write(args.sensitivity_out, SENS_FIELDS, sens)
    sys.stderr.write(f"[composite_score] {len(rows)} tool row(s); descriptive only, never ranks the leaderboard\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
