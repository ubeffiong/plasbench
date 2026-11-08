#!/usr/bin/env python3
"""
evaluate_recommender.py -- does recommending a tool per isolate beat simply using
the single best tool? (scoring specification, sections 9-10)

Folds are leave-one-study-out (study_groups.group_samples_by_study, the same
folds validate_recommendations.py uses). In each fold, on the training studies:

  single best   the tool with the highest mean score over all training isolates
  recommender   the tool with the highest mean score in the held-out isolate's
                organism stratum, when that stratum has >= --min-train-samples
                training isolates for the tool; otherwise the single best
  predicted     the recommended tool's training mean (its expected score)

On each held-out isolate (every tool's score is known there, failure = 0, D6):

  regret              best score - recommended tool's score
  near-optimal        regret <= --near-optimal-margin (0.05)
  top-1               the recommended tool is (one of) the best
  oracle gap          mean best score - mean single-best score
  gap closed          1 - recommender regret / single-best regret (1 = oracle,
                      0 = no better than the single best, < 0 = worse)
  Kendall tau         training ranking vs held-out ranking of the tools (per fold)
  floor               predicted < --min-expected-score (0.40, D11) => flagged;
                      reported with how often the true best was also < 0.40

Verdict: when the oracle gap is below --oracle-gap-floor (0.02) no recommender
can add value over the single best, and the verdict is "benchmark_only": report
the leaderboard, do not recommend per isolate. Otherwise "recommender_adds_value"
when gap closed > 0 and "recommender_no_better" when not.

Profiles: regret is computed for F1 (primary) and, when scores.tsv has them,
F2 (recall-weighted) and F0.5 (precision-weighted).

Outputs: <prefix>.recommender_eval.tsv (one row per profile),
<prefix>.recommender_regret.tsv (one row per held-out isolate and profile),
<prefix>.recommender_verdict.json. Standard library only.
"""

import argparse
import csv
import json
import math
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rank_sensitivity import kendall_tau  # noqa: E402
from study_groups import group_samples_by_study  # noqa: E402

PROFILES = (("f1", "f1"), ("f2", "f2"), ("f0_5", "f0_5"))
EVAL_FIELDS = ["profile", "metric", "n_isolates", "n_folds", "n_tools", "mean_regret", "p95_regret",
               "near_optimal_rate", "top1_rate", "mean_kendall_tau", "single_best_mean_regret",
               "oracle_mean_score", "single_best_mean_score", "recommender_mean_score", "oracle_gap", "gap_closed",
               "floor_flagged", "floor_true_best_below_floor", "verdict", "note"]
REGRET_FIELDS = ["profile", "sample", "held_out_study", "organism", "recommended_tool", "recommended_score",
                 "predicted_score", "best_tool", "best_score", "regret", "near_optimal", "single_best_tool",
                 "single_best_score", "single_best_regret", "floor_flag", "basis"]


def read_tsv(path):
    if not path or not os.path.isfile(path):
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader((l for l in handle if l.strip() and not l.lstrip().startswith("#")), delimiter="\t"))


def number(value):
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def ranks(means):
    order = sorted(means, key=lambda t: (-means[t], t))
    return {tool: i for i, tool in enumerate(order, start=1)}


def percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return ordered[lo] if lo == hi else ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def score_table(scores, metric, failed):
    """{sample: {tool: value}} for isolates with a defined metric; failures score 0 (D6)."""
    table = defaultdict(dict)
    plasmid_samples = set()
    for row in scores:
        value = number(row.get(metric))
        if value is not None:
            table[row["sample"]][row["tool"]] = value
            plasmid_samples.add(row["sample"])
    for tool, samples in failed.items():
        for sample in samples:
            if sample in plasmid_samples:
                table[sample].setdefault(tool, 0.0)
    return table


def read_failed(path):
    failed = defaultdict(set)
    for row in read_tsv(path):
        if row.get("status") == "failed" and row.get("sample") and row.get("tool"):
            failed[row["tool"]].add(row["sample"])
    return failed


def evaluate(table, studies, organism, min_train, near_margin, floor, profile, metric):
    tools = sorted({t for per in table.values() for t in per})
    regrets, rows, taus = [], [], []
    for study, held in sorted(studies.items()):
        train = [s for s in table if s not in held]
        test = [s for s in sorted(held) if s in table]
        if not train or not test:
            continue
        overall = {t: statistics.mean(v) for t in tools
                   if len(v := [table[s][t] for s in train if t in table[s]]) >= min_train}
        if not overall:
            continue
        single_best = min(overall, key=lambda t: (-overall[t], t))
        held_means = {t: statistics.mean(v) for t in tools if (v := [table[s][t] for s in test if t in table[s]])}
        tau = kendall_tau(ranks(overall), ranks(held_means))
        if tau is not None:
            taus.append(tau)
        for sample in test:
            per = table[sample]
            if not per:
                continue
            stratum = organism.get(sample, "not_recorded")
            strat_means = {t: statistics.mean(v) for t in tools
                           if len(v := [table[s][t] for s in train if t in table[s]
                                        and organism.get(s, "not_recorded") == stratum]) >= min_train}
            if strat_means and stratum != "not_recorded":
                recommended, basis = min(strat_means, key=lambda t: (-strat_means[t], t)), f"organism={stratum}"
                predicted = strat_means[recommended]
            else:
                recommended, basis, predicted = single_best, "single_best", overall[single_best]
            best_tool = min(per, key=lambda t: (-per[t], t))
            best = per[best_tool]
            rec_score = per.get(recommended, 0.0)
            sb_score = per.get(single_best, 0.0)
            regret = best - rec_score
            regrets.append((regret, best - sb_score, best, rec_score, sb_score, predicted))
            rows.append({"profile": profile, "sample": sample, "held_out_study": study, "organism": stratum,
                         "recommended_tool": recommended, "recommended_score": f"{rec_score:.4f}",
                         "predicted_score": f"{predicted:.4f}", "best_tool": best_tool, "best_score": f"{best:.4f}",
                         "regret": f"{regret:.4f}", "near_optimal": "yes" if regret <= near_margin + 1e-12 else "no",
                         "single_best_tool": single_best, "single_best_score": f"{sb_score:.4f}",
                         "single_best_regret": f"{best - sb_score:.4f}",
                         "floor_flag": "yes" if predicted < floor else "no", "basis": basis})
    return regrets, rows, taus, len(tools)


def summarise(profile, metric, regrets, rows, taus, n_tools, n_folds, near_margin, gap_floor, floor):
    base = {"profile": profile, "metric": metric, "n_isolates": len(regrets), "n_folds": n_folds, "n_tools": n_tools}
    if not regrets:
        return {**base, **{k: "" for k in EVAL_FIELDS if k not in base},
                "verdict": "not_assessed",
                "note": "needs >= 2 studies with scored isolates and a tool meeting --min-train-samples"}
    rec = [r[0] for r in regrets]
    sb = [r[1] for r in regrets]
    oracle_mean, rec_mean, sb_mean = (statistics.mean(r[i] for r in regrets) for i in (2, 3, 4))
    oracle_gap = oracle_mean - sb_mean
    sb_regret = statistics.mean(sb)
    gap_closed = (1 - statistics.mean(rec) / sb_regret) if sb_regret > 0 else None
    flagged = [r for r in regrets if r[5] < floor]
    if oracle_gap < gap_floor:
        verdict, note = "benchmark_only", (f"oracle gap {oracle_gap:.4f} < {gap_floor}: per-isolate recommendation "
                                           "cannot add value over the single best tool; report the leaderboard")
    elif gap_closed is not None and gap_closed > 0:
        verdict, note = "recommender_adds_value", "recommender closes part of the gap to the oracle"
    else:
        verdict, note = "recommender_no_better", "recommender does not beat the single best tool"
    fmt = lambda v: "" if v is None else f"{v:.4f}"  # noqa: E731
    return {**base, "mean_regret": fmt(statistics.mean(rec)), "p95_regret": fmt(percentile(rec, 0.95)),
            "near_optimal_rate": fmt(sum(r <= near_margin + 1e-12 for r in rec) / len(rec)),
            "top1_rate": fmt(sum(r <= 1e-12 for r in rec) / len(rec)),
            "mean_kendall_tau": fmt(statistics.mean(taus) if taus else None),
            "single_best_mean_regret": fmt(sb_regret), "oracle_mean_score": fmt(oracle_mean),
            "single_best_mean_score": fmt(sb_mean), "recommender_mean_score": fmt(rec_mean),
            "oracle_gap": fmt(oracle_gap), "gap_closed": fmt(gap_closed),
            "floor_flagged": len(flagged),
            "floor_true_best_below_floor": fmt(sum(r[2] < floor for r in flagged) / len(flagged) if flagged else None),
            "verdict": verdict, "note": note}


def write(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scores", required=True)
    ap.add_argument("--samples", required=True)
    ap.add_argument("--tool-status", help="tool_status.tsv: failed runs score 0 (D6)")
    ap.add_argument("--out-prefix", required=True)
    ap.add_argument("--min-train-samples", type=int, default=int(os.environ.get("RECOMMENDATION_MIN_SAMPLES", 5)))
    ap.add_argument("--near-optimal-margin", type=float, default=float(os.environ.get("NEAR_OPTIMAL_MARGIN", 0.05)))
    ap.add_argument("--oracle-gap-floor", type=float, default=float(os.environ.get("ORACLE_GAP_FLOOR", 0.02)))
    ap.add_argument("--min-expected-score", type=float,
                    default=float(os.environ.get("RECOMMENDATION_MIN_EXPECTED_SCORE", 0.40)))
    args = ap.parse_args()

    scores = read_tsv(args.scores)
    metadata = {r["sample_id"]: r for r in read_tsv(args.samples) if r.get("sample_id")}
    organism = {s: (m.get("organism") or "not_recorded") for s, m in metadata.items()}
    studies = group_samples_by_study(scores, metadata)
    failed = read_failed(args.tool_status)
    eval_rows, regret_rows = [], []
    for profile, metric in PROFILES:
        if metric != "f1" and not any(number(r.get(metric)) is not None for r in scores):
            continue
        table = score_table(scores, metric, failed)
        regrets, rows, taus, n_tools = evaluate(table, studies, organism, args.min_train_samples,
                                                args.near_optimal_margin, args.min_expected_score, profile, metric)
        n_folds = len({r["held_out_study"] for r in rows})
        eval_rows.append(summarise(profile, metric, regrets, rows, taus, n_tools, n_folds, args.near_optimal_margin,
                                   args.oracle_gap_floor, args.min_expected_score))
        regret_rows.extend(rows)
    write(f"{args.out_prefix}.recommender_eval.tsv", EVAL_FIELDS, eval_rows)
    write(f"{args.out_prefix}.recommender_regret.tsv", REGRET_FIELDS, regret_rows)
    primary = next((r for r in eval_rows if r["profile"] == "f1"), {})
    verdict = {"verdict": primary.get("verdict", "not_assessed"), "note": primary.get("note", ""),
               "oracle_gap": primary.get("oracle_gap", ""), "gap_closed": primary.get("gap_closed", ""),
               "oracle_gap_floor": args.oracle_gap_floor, "near_optimal_margin": args.near_optimal_margin,
               "min_expected_score": args.min_expected_score, "n_isolates": primary.get("n_isolates", 0),
               "n_folds": primary.get("n_folds", 0)}
    Path(f"{args.out_prefix}.recommender_verdict.json").write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8")
    print(f"[evaluate_recommender] verdict {verdict['verdict']} over {verdict['n_isolates']} held-out isolate(s) "
          f"in {verdict['n_folds']} fold(s) -> {args.out_prefix}.recommender_eval.tsv")


if __name__ == "__main__":
    main()
