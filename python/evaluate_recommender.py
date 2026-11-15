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

Three arms (plan C2). The same folds also compare, per profile, three ways of choosing a tool for a held-out isolate:
  single_best          the training studies' best tool for everyone
  organism             the recommender above (best tool in the isolate's organism stratum)
  feature_conditioned  the best tool among the --knn nearest training isolates, by the TRUTH-FREE dataset features
                       (benchmark.dataset_features.tsv: depth, read quality, assembly size/contigs/N50/GC; a column that needs the
                       reference is refused). Falls back to the single best when fewer than two neighbours have the tool.
Per arm: mean regret, top-1 and near-optimal rates, improvement over the single best, the share of studies (folds) in which it
beat the single best, calibration (mean |predicted - realised| score and the bias), and abstention (the share whose predicted
score is under the floor, with the regret on the isolates it would have answered). An arm "adds value" only when ALL of these hold: its mean
regret is lower than the single best's by at least MIN_IMPROVEMENT (a negligible gain on noisy data is not value); it beats the single best in a majority
of the studies that count, and at least MIN_FOLDS_ADVANTAGE studies count (a study counts with at least MIN_ISOLATES_PER_FOLD held-out isolates: a
study of one isolate says almost nothing); and, for the feature-conditioned arm, at least MIN_FEATURE_SHARE of the held-out isolates were actually
placed by their neighbours (an arm that fell back to the single best for most isolates has not been tested). Otherwise it is reported as not better, or
not assessed, with the reason. The criteria are descriptive evidence on a handful of studies, not a significance test. The feature-conditioned arm is an EVALUATION: nothing recommends with it unless this says it adds value.
Outputs: <prefix>.recommender_arms.tsv (one row per profile and arm), <prefix>.recommender_eval.tsv (one row per profile),
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
import recommendation_model as rm  # noqa: E402
import characterise_dataset as cd  # noqa: E402
from study_groups import group_samples_by_study  # noqa: E402

PROFILES = (("f1", "f1"), ("f2", "f2"), ("f0_5", "f0_5"))
# Nearest-neighbour arms (second review, section 6A): numeric features alone can make two isolates of unrelated species
# neighbours, so taxonomy is tested as well -- compared with the single best, never assumed to help.
#   feature_conditioned  numeric truth-free features only
#   taxonomy_knn         neighbours from the same species only (none there: the single best)
#   hierarchical_knn     neighbours from the same species, else the same genus, else the same Gram group, else any isolate
KNN_ARMS = {"feature_conditioned": None, "taxonomy_knn": "species", "hierarchical_knn": "hierarchical"}
ARMS = ("single_best", "organism", *KNN_ARMS)
SCALING = "robust"        # feature spread: median and 1.4826 x MAD (read depth is skewed); "standard" = mean and sd, the earlier rule
MISSING_PENALTY = 1.0     # standardised distance charged for each feature present in one isolate and missing in the other (missingness is information)
RANGE_QUANTILE = 0.95     # farther from its nearest training isolate than this quantile of the training isolates' own nearest distances: out of range, abstain
SENSITIVITY_K = (3, 5, 10)
KNN_K = 5                 # neighbours used by the feature-conditioned arm
MIN_NEIGHBOURS = 2        # a tool needs at least this many scored neighbours to be recommended
MIN_FOLDS_ADVANTAGE = 3   # studies needed before an arm can be said to add value (fewer: not_assessed)
MIN_ISOLATES_PER_FOLD = 2 # held-out isolates a study needs to count toward that
MIN_IMPROVEMENT = 0.01    # least drop in mean regret, against the single best, that counts as value
MIN_FEATURE_SHARE = 0.5   # share of held-out isolates the feature arm must place by neighbours (not by the single-best fallback) to be assessed
NUMERIC_FEATURES = ("read_depth_x",) + rm.ASSEMBLY_STAT_FIELDS + ("mean_read_quality",)
ARM_FIELDS = ["profile", "arm", "n_isolates", "n_folds", "mean_regret", "top1_rate", "near_optimal_rate", "improvement_over_single_best",
              "folds_better", "folds_assessed", "calibration_mae", "calibration_bias", "abstention_rate", "mean_regret_when_answering", "verdict", "note",
              "n_feature_based", "share_feature_based", "share_out_of_range", "mean_uncertainty_sd"]
EVAL_FIELDS = ["profile", "metric", "n_isolates", "n_folds", "n_tools", "mean_regret", "p95_regret",
               "near_optimal_rate", "top1_rate", "mean_kendall_tau", "single_best_mean_regret",
               "oracle_mean_score", "single_best_mean_score", "recommender_mean_score", "oracle_gap", "gap_closed",
               "floor_flagged", "floor_true_best_below_floor", "verdict", "note"]
REGRET_FIELDS = ["profile", "sample", "held_out_study", "organism", "recommended_tool", "recommended_score",
                 "predicted_score", "best_tool", "best_score", "regret", "near_optimal", "single_best_tool",
                 "single_best_score", "single_best_regret", "floor_flag", "basis", "single_best_predicted"]


from plasbench_common import number  # noqa: E402,F401


def read_tsv(path):
    if not path or not os.path.isfile(path):
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader((l for l in handle if l.strip() and not l.lstrip().startswith("#")), delimiter="\t"))


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
                         "floor_flag": "yes" if predicted < floor else "no", "basis": basis,
                         "single_best_predicted": f"{overall[single_best]:.4f}"})
    return regrets, rows, taus, len(tools)


def read_features(path):
    """{sample: {feature: float}} from benchmark.dataset_features.tsv, TRUTH-FREE numeric columns only (a reference-derived column is never used)."""
    allowed = [f for f in NUMERIC_FEATURES if f in cd.TRUTH_FREE]
    rm.assert_truth_free(allowed)
    out = {}
    for row in read_tsv(path):
        values = {f: number(row.get(f)) for f in allowed}
        out[row.get("sample", "")] = {f: v for f, v in values.items() if v is not None}
    return out


def standardise(features, train, scaling=None, names=NUMERIC_FEATURES):
    """Per-feature centre and spread from the TRAINING isolates only (nothing from the held-out isolate leaks into the scale).

    robust: median and 1.4826 x MAD (falls back to the sd when the MAD is 0); standard: mean and sd."""
    scaling = scaling or SCALING
    scale = {}
    for name in names:
        values = [features[s][name] for s in train if name in features.get(s, {})]
        if len(values) < 2:
            continue
        if scaling == "robust":
            centre = statistics.median(values)
            spread = 1.4826 * statistics.median(abs(v - centre) for v in values) or statistics.pstdev(values)
        else:
            centre, spread = statistics.mean(values), statistics.pstdev(values)
        if spread > 0:
            scale[name] = (centre, spread)
    return scale


def distance(a, b, scale, missing_penalty=None):
    """Root mean square of standardised differences over the features both isolates have, plus missing_penalty for each
    feature only one of them has (MISSING_PENALTY; 0 ignores missingness, the earlier rule). None with fewer than 2 shared features."""
    penalty = MISSING_PENALTY if missing_penalty is None else missing_penalty
    shared = [f for f in scale if f in a and f in b]
    if len(shared) < 2:
        return None
    one_sided = sum(1 for f in scale if (f in a) != (f in b)) if penalty else 0
    total = sum(((a[f] - b[f]) / scale[f][1]) ** 2 for f in shared) + one_sided * penalty ** 2
    return math.sqrt(total / (len(shared) + one_sided))


def species_of(organism):
    words = (organism or "").replace("[", "").replace("]", "").split()
    return " ".join(words[:2]) if len(words) >= 2 and words[0] != "not_recorded" else ""


def taxonomy_levels(sample, train, organism, gram, taxonomy):
    """[(level, candidate training isolates)] in the order a taxonomy-aware arm tries them."""
    if not taxonomy:
        return [("any", train)]
    species = species_of(organism.get(sample))
    same_species = [s for s in train if species and species_of(organism.get(s)) == species]
    if taxonomy == "species":
        return [("species", same_species)]
    genus = species.split()[0] if species else ""
    g = (gram.get(sample) or "").strip()
    return [("species", same_species),
            ("genus", [s for s in train if genus and species_of(organism.get(s)).split()[:1] == [genus]]),
            ("gram_group", [s for s in train if g and g != "not_recorded" and (gram.get(s) or "").strip() == g]),
            ("any", train)]


def range_threshold(features, train, scale, missing_penalty, quantile=RANGE_QUANTILE):
    """The RANGE_QUANTILE of the training isolates' distances to their own nearest training neighbour (None with too few)."""
    nearest = []
    for s in train:
        ds = [d for t in train if t != s and (d := distance(features.get(s, {}), features.get(t, {}), scale, missing_penalty)) is not None]
        if ds:
            nearest.append(min(ds))
    return percentile(nearest, quantile) if len(nearest) >= 5 else None


def feature_arm(table, studies, features, min_train, near_margin, floor, k=KNN_K, taxonomy=None, organism=None, gram=None,
                scaling=None, missing_penalty=None, drop=None, abstain=True):
    """Per held-out isolate: the tool the nearest training isolates did best with, its predicted and realised score, and how
    much to trust it: the spread of that tool's scores among the neighbours, how many studies they come from, the distance to the
    nearest one and whether the isolate is inside the range the training data covers. Out of range (and abstain): no
    recommendation from neighbours -- the single best is used and the isolate is marked, never a forced answer (section 6C).

    taxonomy None | "species" | "hierarchical" (KNN_ARMS); drop leaves one feature out (the sensitivity analysis)."""
    organism, gram = organism or {}, gram or {}
    names = tuple(f for f in NUMERIC_FEATURES if f != drop)
    study_of = {s: study for study, members in studies.items() for s in members}
    tools = sorted({t for per in table.values() for t in per})
    out = []
    for study, held in sorted(studies.items()):
        train = [s for s in table if s not in held]
        test = [s for s in sorted(held) if s in table]
        overall = {t: statistics.mean(v) for t in tools if len(v := [table[s][t] for s in train if t in table[s]]) >= min_train}
        if not train or not test or not overall:
            continue
        single_best = min(overall, key=lambda t: (-overall[t], t))
        scale = standardise(features, train, scaling, names)
        limit = range_threshold(features, train, scale, missing_penalty) if abstain else None
        for sample in test:
            mine = features.get(sample, {})
            all_d = [d for s in train if (d := distance(mine, features.get(s, {}), scale, missing_penalty)) is not None]
            nearest = min(all_d) if all_d else None
            in_range = "unknown" if nearest is None or limit is None else ("yes" if nearest <= limit else "no")
            tool, basis, predicted, spread, n_studies, level = single_best, "single_best", overall[single_best], None, 0, ""
            if in_range != "no":
                for level_name, pool in taxonomy_levels(sample, train, organism, gram, taxonomy):
                    near = sorted((d, s) for s in pool if (d := distance(mine, features.get(s, {}), scale, missing_penalty)) is not None)[:k]
                    scored = {t: [table[s][t] for _d, s in near if t in table[s]] for t in tools}
                    means = {t: statistics.mean(v) for t, v in scored.items() if len(v) >= MIN_NEIGHBOURS}
                    if means:
                        tool = min(means, key=lambda t: (-means[t], t))
                        basis, predicted, level = f"neighbours:{level_name}" if taxonomy else "neighbours", means[tool], level_name
                        spread = statistics.pstdev(scored[tool]) if len(scored[tool]) > 1 else None
                        n_studies = len({study_of.get(s) for _d, s in near if tool in table[s]})
                        break
            else:
                basis = "abstain_out_of_range"
            per = table[sample]
            best = max(per.values())
            out.append({"sample": sample, "held_out_study": study, "tool": tool, "predicted": predicted, "score": per.get(tool, 0.0), "best": best,
                        "basis": basis, "uncertainty_sd": spread, "n_neighbour_studies": n_studies, "nearest_distance": nearest,
                        "in_range": in_range, "level": level})
    return out


def arm_summary(profile, arm, items, single_by_study, floor, near_margin, min_isolates=MIN_ISOLATES_PER_FOLD):
    """items: [{study, regret, predicted, score, best}]; single_by_study: {study: mean regret of the single best on that fold}."""
    base = {"profile": profile, "arm": arm, "n_isolates": len(items)}
    if not items:
        return {**{f: "" for f in ARM_FIELDS}, **base, "verdict": "not_assessed", "note": "no held-out isolates"}
    fmt = lambda v: "" if v is None else f"{v:.4f}"  # noqa: E731
    regrets = [i["regret"] for i in items]
    by_study = defaultdict(list)
    for i in items:
        by_study[i["study"]].append(i["regret"])
    folds = {s: statistics.mean(v) for s, v in by_study.items()}
    counted = {s: v for s, v in folds.items() if len(by_study[s]) >= min_isolates}     # a study of one isolate does not count toward the verdict
    better = sum(1 for s, v in counted.items() if v < single_by_study.get(s, float("inf")) - 1e-12)
    feature_based = [i for i in items if str(i.get("basis", "")).startswith("neighbours")] if arm in KNN_ARMS else None
    out_of_range = [i for i in items if i.get("basis") == "abstain_out_of_range"] if arm in KNN_ARMS else None
    spreads = [i["uncertainty_sd"] for i in items if i.get("uncertainty_sd") is not None] if arm in KNN_ARMS else []
    share = None if feature_based is None else len(feature_based) / len(items)
    single_mean = statistics.mean(single_by_study[i["study"]] for i in items)
    improvement = single_mean - statistics.mean(regrets)
    answering = [i["regret"] for i in items if i["predicted"] >= floor]
    row = {**base, "n_folds": len(folds), "mean_regret": fmt(statistics.mean(regrets)),
           "top1_rate": fmt(sum(r <= 1e-12 for r in regrets) / len(regrets)),
           "near_optimal_rate": fmt(sum(r <= near_margin + 1e-12 for r in regrets) / len(regrets)),
           "improvement_over_single_best": fmt(improvement), "folds_better": better, "folds_assessed": len(counted),
           "calibration_mae": fmt(statistics.mean(abs(i["predicted"] - i["score"]) for i in items)),
           "calibration_bias": fmt(statistics.mean(i["predicted"] - i["score"] for i in items)),
           "abstention_rate": fmt(1 - len(answering) / len(items)),
           "mean_regret_when_answering": fmt(statistics.mean(answering) if answering else None),
           "n_feature_based": "" if feature_based is None else len(feature_based), "share_feature_based": "" if share is None else f"{share:.3f}",
           "share_out_of_range": "" if out_of_range is None else f"{len(out_of_range) / len(items):.3f}",
           "mean_uncertainty_sd": fmt(statistics.mean(spreads)) if spreads else ""}
    if arm == "single_best":
        row.update(verdict="reference", note="the comparison baseline")
    elif share is not None and share < MIN_FEATURE_SHARE:
        row.update(verdict="not_assessed", note=(f"only {share:.0%} of the held-out isolates were placed by their neighbours (the rest fell back to the single best): "
                                                 "no dataset features, or too few shared ones"))
    elif len(counted) < MIN_FOLDS_ADVANTAGE:
        row.update(verdict="not_assessed", note=f"needs at least {MIN_FOLDS_ADVANTAGE} held-out groups with {min_isolates} or more isolates; this design has {len(counted)}")
    elif improvement >= MIN_IMPROVEMENT and better > len(counted) / 2:
        row.update(verdict="adds_value", note=f"lower regret than the single best by {improvement:.3f} on average and in {better} of {len(counted)} studies")
    else:
        row.update(verdict="no_better", note=f"better than the single best in {better} of {len(counted)} studies; improvement {improvement:+.4f} (needs {MIN_IMPROVEMENT:g} or more)")
    return row


def arms_for_profile(profile, table, studies, organism, features, rows, min_train, near_margin, floor, gram=None, details=None,
                     only=None, min_isolates=MIN_ISOLATES_PER_FOLD, **knn):
    """Every arm for one profile. single_best and organism come from `rows` (evaluate() output); the nearest-neighbour arms are computed here.

    details: a list that collects one row per held-out isolate and neighbour arm (recommendation, uncertainty, range).
    only: the neighbour arms to compute (default all); knn: options passed to feature_arm (k, scaling, missing_penalty, drop)."""
    by_sample = {r["sample"]: r for r in rows}
    single_by_study = defaultdict(list)
    for r in rows:
        single_by_study[r["held_out_study"]].append(number(r["single_best_regret"]))
    single_by_study = {s: statistics.mean(v) for s, v in single_by_study.items()}
    arms = {arm: [] for arm in ARMS}
    for r in rows:
        best, predicted = number(r["best_score"]), number(r["predicted_score"])
        arms["single_best"].append({"study": r["held_out_study"], "regret": number(r["single_best_regret"]), "predicted": number(r["single_best_predicted"]),
                                    "score": number(r["single_best_score"]), "best": best})
        arms["organism"].append({"study": r["held_out_study"], "regret": number(r["regret"]), "predicted": predicted, "score": number(r["recommended_score"]), "best": best})
    for arm, taxonomy in KNN_ARMS.items():
        if only is not None and arm not in only:
            continue
        for f in feature_arm(table, studies, features, min_train, near_margin, floor, taxonomy=taxonomy, organism=organism, gram=gram, **knn):
            if f["sample"] not in by_sample:
                continue
            arms[arm].append({"study": f["held_out_study"], "regret": f["best"] - f["score"], "predicted": f["predicted"], "score": f["score"], "best": f["best"],
                              "basis": f["basis"], "uncertainty_sd": f["uncertainty_sd"]})
            if details is not None:
                fmt = lambda v: "" if v is None else f"{v:.4f}"  # noqa: E731
                details.append({"profile": profile, "arm": arm, "sample": f["sample"], "held_out_study": f["held_out_study"], "tool": f["tool"],
                                "predicted_score": fmt(f["predicted"]), "uncertainty_sd": fmt(f["uncertainty_sd"]),
                                "n_neighbour_studies": f["n_neighbour_studies"], "nearest_distance": fmt(f["nearest_distance"]),
                                "in_range": f["in_range"], "basis": f["basis"], "realised_score": fmt(f["score"]), "regret": fmt(f["best"] - f["score"])})
    wanted = [a for a in ARMS if only is None or a in ("single_best", "organism") or a in only]
    return [arm_summary(profile, arm, arms[arm], single_by_study, floor, near_margin, min_isolates) for arm in wanted]


KNN_DETAIL_FIELDS = ["profile", "arm", "sample", "held_out_study", "tool", "predicted_score", "uncertainty_sd", "n_neighbour_studies",
                     "nearest_distance", "in_range", "basis", "realised_score", "regret"]
SENSITIVITY_FIELDS = ["analysis", "setting", "arm", "n_isolates", "mean_regret", "improvement_over_single_best", "share_feature_based",
                      "share_out_of_range", "verdict"]
HOLDOUT_FIELDS = ["design", "arm", "n_groups", "n_isolates", "n_folds", "mean_regret", "improvement_over_single_best", "folds_better",
                  "folds_assessed", "verdict", "note"]
CORRELATION_FIELDS = ["feature_a", "feature_b", "n_isolates", "spearman", "note"]


def sensitivity(table, studies, organism, gram, features, rows, min_train, near_margin, floor):
    """How the numeric nearest-neighbour arm moves with K, the scaling, the missingness penalty and each feature left out (section 6C)."""
    settings = ([("k", str(k), {"k": k}) for k in SENSITIVITY_K]
                + [("scaling", name, {"scaling": name}) for name in ("robust", "standard")]
                + [("missing_penalty", str(p), {"missing_penalty": p}) for p in (0.0, MISSING_PENALTY)]
                + [("drop_feature", name, {"drop": name}) for name in NUMERIC_FEATURES]
                + [("abstain_out_of_range", str(flag).lower(), {"abstain": flag}) for flag in (True, False)])
    out = []
    for analysis, setting, options in settings:
        summary = arms_for_profile("f1", table, studies, organism, features, rows, min_train, near_margin, floor, gram=gram,
                                   only=("feature_conditioned",), **options)
        row = next(r for r in summary if r["arm"] == "feature_conditioned")
        out.append({"analysis": analysis, "setting": setting, **{k: row.get(k, "") for k in SENSITIVITY_FIELDS if k not in ("analysis", "setting")}})
    return out


def holdout_designs(scores, metadata, clonal, failed, organism, gram, features, min_train, near_margin, floor):
    """The arms under every validation design (study_groups.HOLDOUT_DESIGNS), F1 profile. They answer different questions and are not interchangeable."""
    from study_groups import HOLDOUT_DESIGNS, group_samples
    table = score_table(scores, "f1", failed)
    out = []
    for design in HOLDOUT_DESIGNS:
        if design in ("clonal_group", "study_and_clonal") and not clonal:
            out.append({"design": design, "arm": "all", "verdict": "not_assessed", "note": "no clonal groups (benchmark.clonal_groups.tsv) for this run"})
            continue
        groups = group_samples(design, scores, metadata, clonal)
        if len(groups) < 2:
            out.append({"design": design, "arm": "all", "n_groups": len(groups), "verdict": "not_assessed", "note": "fewer than two held-out groups"})
            continue
        regrets, rows, _taus, _n = evaluate(table, groups, organism, min_train, near_margin, floor, "f1", "f1")
        if not rows:
            out.append({"design": design, "arm": "all", "n_groups": len(groups), "verdict": "not_assessed", "note": "no held-out predictions"})
            continue
        for row in arms_for_profile("f1", table, groups, organism, features, rows, min_train, near_margin, floor, gram=gram,
                                    min_isolates=1 if design == "isolate" else MIN_ISOLATES_PER_FOLD):
            out.append({"design": design, "n_groups": len(groups), **{k: row.get(k, "") for k in HOLDOUT_FIELDS if k not in ("design", "n_groups")}})
    return out


def spearman(xs, ys):
    def rank(values):
        order = sorted(range(len(values)), key=lambda i: values[i])
        ranks = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            for k in range(i, j + 1):
                ranks[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return ranks
    rx, ry = rank(xs), rank(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else None


def feature_correlation(features):
    """Spearman correlation between every pair of numeric features: two that measure the same thing (N50 and contig count both
    measure fragmentation) would count twice in the distance (section 6C). Descriptive; |rho| >= 0.8 is flagged."""
    out = []
    for i, a in enumerate(NUMERIC_FEATURES):
        for b in NUMERIC_FEATURES[i + 1:]:
            pairs = [(f[a], f[b]) for f in features.values() if a in f and b in f]
            rho = spearman([p[0] for p in pairs], [p[1] for p in pairs]) if len(pairs) >= 5 else None
            out.append({"feature_a": a, "feature_b": b, "n_isolates": len(pairs), "spearman": "" if rho is None else f"{rho:.3f}",
                        "note": "fewer than 5 isolates" if rho is None and len(pairs) < 5 else
                                ("largely the same information: consider dropping one (see the drop_feature sensitivity rows)" if rho is not None and abs(rho) >= 0.8 else "")})
    return out


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
    ap.add_argument("--dataset-features", help="benchmark.dataset_features.tsv (characterise_dataset.py): the truth-free features of the feature-conditioned arm")
    ap.add_argument("--out-prefix", required=True)
    ap.add_argument("--min-train-samples", type=int, default=int(os.environ.get("RECOMMENDATION_MIN_SAMPLES", 5)))
    ap.add_argument("--near-optimal-margin", type=float, default=float(os.environ.get("NEAR_OPTIMAL_MARGIN", 0.05)))
    ap.add_argument("--oracle-gap-floor", type=float, default=float(os.environ.get("ORACLE_GAP_FLOOR", 0.02)))
    ap.add_argument("--min-expected-score", type=float,
                    default=float(os.environ.get("RECOMMENDATION_MIN_EXPECTED_SCORE", 0.40)))
    ap.add_argument("--clonal-groups", help="benchmark.clonal_groups.tsv: adds the leave-one-clonal-group-out and the study-and-clonal holdouts")
    ap.add_argument("--no-sensitivity", action="store_true", help="skip the K / scaling / missingness / drop-one-feature sensitivity table (faster)")
    args = ap.parse_args()

    from study_groups import read_clonal_groups
    scores = read_tsv(args.scores)
    metadata = {r["sample_id"]: r for r in read_tsv(args.samples) if r.get("sample_id")}
    organism = {s: (m.get("organism") or "not_recorded") for s, m in metadata.items()}
    gram = {s: (m.get("gram_group") or "") for s, m in metadata.items()}
    clonal = read_clonal_groups(args.clonal_groups)
    studies = group_samples_by_study(scores, metadata)
    failed = read_failed(args.tool_status)
    eval_rows, regret_rows, arm_rows, knn_rows = [], [], [], []
    features = read_features(args.dataset_features) if args.dataset_features else {}
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
        if rows:
            arm_rows.extend(arms_for_profile(profile, table, studies, organism, features, rows, args.min_train_samples, args.near_optimal_margin,
                                             args.min_expected_score, gram=gram, details=knn_rows if profile == "f1" else None))
    write(f"{args.out_prefix}.recommender_arms.tsv", ARM_FIELDS, arm_rows)
    write(f"{args.out_prefix}.recommender_eval.tsv", EVAL_FIELDS, eval_rows)
    write(f"{args.out_prefix}.recommender_regret.tsv", REGRET_FIELDS, regret_rows)
    write(f"{args.out_prefix}.recommender_knn.tsv", KNN_DETAIL_FIELDS, knn_rows)
    f1_rows = [r for r in regret_rows if r["profile"] == "f1"]
    sensitivity_rows = [] if args.no_sensitivity or not f1_rows else sensitivity(
        score_table(scores, "f1", failed), studies, organism, gram, features, f1_rows, args.min_train_samples, args.near_optimal_margin, args.min_expected_score)
    write(f"{args.out_prefix}.recommender_sensitivity.tsv", SENSITIVITY_FIELDS, sensitivity_rows)
    holdout_rows = holdout_designs(scores, metadata, clonal, failed, organism, gram, features, args.min_train_samples, args.near_optimal_margin,
                                   args.min_expected_score) if f1_rows else []
    write(f"{args.out_prefix}.recommender_holdouts.tsv", HOLDOUT_FIELDS, holdout_rows)
    write(f"{args.out_prefix}.recommender_feature_correlation.tsv", CORRELATION_FIELDS, feature_correlation(features))
    primary = next((r for r in eval_rows if r["profile"] == "f1"), {})
    arm_verdicts = {r["arm"]: r["verdict"] for r in arm_rows if r["profile"] == "f1"}
    by_design = defaultdict(dict)
    for r in holdout_rows:
        by_design[r["design"]][r["arm"]] = r["verdict"]
    # A per-isolate arm is enabled only when it adds value under leave-one-study-out AND under the strictest design this run can
    # build (study and clonal group held out together, when clonal groups exist): closely related isolates across studies must
    # not carry the evidence (section 6B).
    strict = "study_and_clonal" if clonal else "study"
    enabled = {arm: arm_verdicts.get(arm) == "adds_value" and by_design.get(strict, {}).get(arm, arm_verdicts.get(arm)) == "adds_value"
               for arm in ("organism", *KNN_ARMS)}
    verdict = {"verdict": primary.get("verdict", "not_assessed"), "note": primary.get("note", ""),
               "oracle_gap": primary.get("oracle_gap", ""), "gap_closed": primary.get("gap_closed", ""),
               "oracle_gap_floor": args.oracle_gap_floor, "near_optimal_margin": args.near_optimal_margin,
               "min_expected_score": args.min_expected_score, "n_isolates": primary.get("n_isolates", 0),
               "n_folds": primary.get("n_folds", 0), "arms": arm_verdicts, "holdouts": dict(by_design), "strictest_holdout": strict,
               "arms_enabled": enabled, "any_per_isolate_arm_enabled": any(enabled.values()),
               "feature_conditioned_enabled": enabled["feature_conditioned"]}
    Path(f"{args.out_prefix}.recommender_verdict.json").write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8")
    print(f"[evaluate_recommender] verdict {verdict['verdict']} over {verdict['n_isolates']} held-out isolate(s) "
          f"in {verdict['n_folds']} fold(s) -> {args.out_prefix}.recommender_eval.tsv")


if __name__ == "__main__":
    main()
