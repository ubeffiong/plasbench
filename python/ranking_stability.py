#!/usr/bin/env python3
"""
ranking_stability.py -- does the leaderboard survive removing a study or a species?

A single ordered list of tools hides how much of it one study or one species carries. For each analysis track and
evaluation task this script re-ranks the tools on the task's pre-registered headline metric (headline_design.py) after

  * leaving out each STUDY in turn            -> <prefix>.study_sensitivity.tsv
  * leaving out each SPECIES in turn          -> <prefix>.species_sensitivity.tsv
  * giving every study the same weight        -> <prefix>.ranking_stability.tsv (equal-study-weighted ranking)

and summarises, per (track, task), whether the leader changes, how far the order moves (Kendall tau against the full
ranking) and how much of the cohort the largest study and species make up. Descriptive only: it reads scores.tsv, never
alters it or the leaderboard, and a missing sample sheet only removes the study and species rows.

Tools are ranked on the isolates all of them share (rank_sensitivity.ranked), as the leaderboard does. A leave-out step that
leaves fewer than --min-isolates isolates is recorded as "too_few_isolates", not ranked.

Usage:
  python python/ranking_stability.py --scores results/scores.tsv --sample-sheet samples.tsv --out-prefix results/benchmark
"""

import argparse
import csv
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from headline_design import ranking_metric, read_rows  # noqa: E402
from plasbench_common import number  # noqa: E402
from rank_sensitivity import kendall_tau, ranked  # noqa: E402
from study_groups import group_samples, _text, species_of  # noqa: E402
from tool_capabilities import evaluation_task  # noqa: E402

TAB, NL = chr(9), chr(10)
LEAVE_COLUMNS = ["analysis_track", "evaluation_task", "metric", "left_out", "isolates_removed", "isolates_remaining", "status",
                 "leader", "baseline_leader", "leader_changed", "kendall_tau", "tools_whose_rank_changed", "ranking"]
STABILITY_COLUMNS = ["analysis_track", "evaluation_task", "metric", "n_tools", "n_isolates", "n_studies", "n_species", "largest_study",
                     "largest_study_share", "largest_species", "largest_species_share", "baseline_leader", "study_leave_outs",
                     "study_leader_changes", "study_min_tau", "species_leave_outs", "species_leader_changes", "species_min_tau",
                     "equal_study_leader", "equal_study_tau", "verdict", "baseline_ranking"]
DEFAULT_REGISTRY = os.path.join(HERE, "..", "config", "tool_capabilities.tsv")


def read_scores(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader((x for x in handle if x.strip() and not x.startswith("#")), delimiter=TAB))


def read_metadata(path):
    if not path or not os.path.isfile(path):
        return {}
    with open(path, newline="", encoding="utf-8") as handle:
        return {r["sample_id"]: r for r in csv.DictReader((x for x in handle if x.strip() and not x.startswith("#")), delimiter=TAB)
                if r.get("sample_id")}


def values_by_task(rows, tasks):
    """{(track, task): {tool: {sample: headline value}}}; a pair without a number is left out."""
    out = defaultdict(lambda: defaultdict(dict))
    for r in rows:
        tool, sample = r.get("tool"), r.get("sample")
        task = tasks.get(tool)
        if not (tool and sample and task):
            continue
        track = r.get("analysis_track") or "short_read"
        metric = ranking_metric(track, task)
        value = number(r.get(metric))
        if value is not None:
            out[(track, task, metric)][tool][sample] = value
    return out


def order(ranking):
    return {tool: rank for tool, _mean, _n, rank in ranking}


def describe(ranking):
    return " > ".join(f"{tool} {mean:.3f}" for tool, mean, _n, _r in ranking)


def restrict(per_tool, keep):
    return {tool: {s: v for s, v in values.items() if s in keep} for tool, values in per_tool.items()}


def leave_one_out(key, per_tool, groups, baseline, base_rank, min_isolates):
    track, task, metric = key
    rows = []
    everyone = set(next(iter(per_tool.values()))) if per_tool else set()
    for name in sorted(groups):
        removed = groups[name] & everyone
        if not removed:
            continue
        kept = everyone - removed
        row = {"analysis_track": track, "evaluation_task": task, "metric": metric, "left_out": name,
               "isolates_removed": len(removed), "isolates_remaining": len(kept)}
        ranking = ranked(restrict(per_tool, kept)) if len(kept) >= min_isolates else []
        if not ranking:
            row.update(status="too_few_isolates", leader="", baseline_leader=baseline[0][0], leader_changed="", kendall_tau="",
                       tools_whose_rank_changed="", ranking="")
        else:
            rank = order(ranking)
            tau = kendall_tau(base_rank, rank)
            moved = sorted(t for t in rank if base_rank.get(t) != rank[t])
            row.update(status="ranked", leader=ranking[0][0], baseline_leader=baseline[0][0],
                       leader_changed="yes" if ranking[0][0] != baseline[0][0] else "no",
                       kendall_tau="" if tau is None else f"{tau:.3f}", tools_whose_rank_changed=";".join(moved), ranking=describe(ranking))
        rows.append(row)
    return rows


def equal_study_ranking(per_tool, studies):
    """Mean over studies of each study's mean score, so a study with 40 isolates counts once, like one with 2."""
    tools = list(per_tool)
    shared = set.intersection(*(set(per_tool[t]) for t in tools)) if tools else set()
    scores = {}
    for tool in tools:
        means = []
        for members in studies.values():
            v = [per_tool[tool][s] for s in members & shared]
            if v:
                means.append(sum(v) / len(v))
        if not means:
            return []
        scores[tool] = sum(means) / len(means)
    ordered = sorted(tools, key=lambda t: (-scores[t], t))
    return [(t, scores[t], len(shared), i) for i, t in enumerate(ordered, 1)]


def share(groups, samples):
    """(largest group, its share of `samples`)."""
    if not groups or not samples:
        return "", ""
    name = max(groups, key=lambda g: len(groups[g] & samples))
    return name, f"{len(groups[name] & samples) / len(samples):.3f}"


def verdict(changes_study, changes_species, tau_values, n_study, n_species):
    if not n_study and not n_species:
        return "not_assessed: no study or species information"
    changed = (changes_study or 0) + (changes_species or 0)
    low = [t for t in tau_values if t is not None and t < 0.7]
    if changed == 0 and not low:
        return "stable: the leader and the order hold when any one study or species is removed"
    parts = []
    if changed:
        parts.append(f"the leader changes in {changed} leave-out(s)")
    if low:
        parts.append("the order moves substantially (tau < 0.7) in some")
    return "fragile: " + " and ".join(parts) + "; report the ranking with this caveat"


def analyse(rows, metadata, tasks, min_isolates=3):
    study_rows, species_rows, summary = [], [], []
    for key, per_tool in sorted(values_by_task(rows, tasks).items()):
        track, task, metric = key
        baseline = ranked(per_tool)
        if len(per_tool) < 2 or not baseline:
            continue
        base_rank = order(baseline)
        samples = set(next(iter(per_tool.values()))) & set.intersection(*(set(v) for v in per_tool.values()))
        scoped = [{"sample": s} for s in sorted(samples)]
        studies = {k: v & samples for k, v in group_samples("study", scoped, metadata).items()} if metadata else {}
        species = {k: v & samples for k, v in group_samples("species", scoped, metadata).items()} if metadata else {}
        studies = {k: v for k, v in studies.items() if v}
        species = {k: v for k, v in species.items() if v}
        by_study = leave_one_out(key, per_tool, studies, baseline, base_rank, min_isolates) if len(studies) > 1 else []
        by_species = leave_one_out(key, per_tool, species, baseline, base_rank, min_isolates) if len(species) > 1 else []
        study_rows += by_study
        species_rows += by_species
        equal = equal_study_ranking(per_tool, studies) if len(studies) > 1 else []
        equal_tau = kendall_tau(base_rank, order(equal)) if equal else None
        ranked_study = [r for r in by_study if r["status"] == "ranked"]
        ranked_species = [r for r in by_species if r["status"] == "ranked"]
        tau_of = lambda rs: [number(r["kendall_tau"]) for r in rs]  # noqa: E731
        change_study = sum(r["leader_changed"] == "yes" for r in ranked_study) if ranked_study else None
        change_species = sum(r["leader_changed"] == "yes" for r in ranked_species) if ranked_species else None
        taus = tau_of(ranked_study) + tau_of(ranked_species) + ([equal_tau] if equal_tau is not None else [])
        if equal and equal[0][0] != baseline[0][0]:
            change_study = (change_study or 0) + 1
        big_study, big_study_share = share(studies, samples)
        big_species, big_species_share = share(species, samples)
        summary.append({
            "analysis_track": track, "evaluation_task": task, "metric": metric, "n_tools": len(per_tool), "n_isolates": len(samples),
            "n_studies": len(studies), "n_species": len(species), "largest_study": big_study, "largest_study_share": big_study_share,
            "largest_species": big_species, "largest_species_share": big_species_share, "baseline_leader": baseline[0][0],
            "study_leave_outs": len(ranked_study), "study_leader_changes": "" if change_study is None else sum(r["leader_changed"] == "yes" for r in ranked_study),
            "study_min_tau": "" if not ranked_study else f"{min(t for t in tau_of(ranked_study) if t is not None):.3f}" if any(t is not None for t in tau_of(ranked_study)) else "",
            "species_leave_outs": len(ranked_species), "species_leader_changes": "" if change_species is None else change_species,
            "species_min_tau": "" if not ranked_species else f"{min(t for t in tau_of(ranked_species) if t is not None):.3f}" if any(t is not None for t in tau_of(ranked_species)) else "",
            "equal_study_leader": equal[0][0] if equal else "", "equal_study_tau": "" if equal_tau is None else f"{equal_tau:.3f}",
            "verdict": verdict(change_study, change_species, taus, len(studies) > 1, len(species) > 1),
            "baseline_ranking": describe(baseline)})
    return study_rows, species_rows, summary


def write_tsv(path, columns, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter=TAB, lineterminator=NL)
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--scores", required=True)
    ap.add_argument("--sample-sheet")
    ap.add_argument("--registry", default=DEFAULT_REGISTRY)
    ap.add_argument("--out-prefix", required=True)
    ap.add_argument("--min-isolates", type=int, default=3, help="a leave-out step that leaves fewer isolates is not ranked")
    a = ap.parse_args(argv)
    tasks = {r["tool"]: evaluation_task(r) for r in read_rows(a.registry) if r.get("tool")}
    rows = read_scores(a.scores)
    study_rows, species_rows, summary = analyse(rows, read_metadata(a.sample_sheet), tasks, a.min_isolates)
    write_tsv(a.out_prefix + ".study_sensitivity.tsv", LEAVE_COLUMNS, study_rows)
    write_tsv(a.out_prefix + ".species_sensitivity.tsv", LEAVE_COLUMNS, species_rows)
    write_tsv(a.out_prefix + ".ranking_stability.tsv", STABILITY_COLUMNS, summary)
    for s in summary:
        print(f"ranking stability {s['analysis_track']}/{s['evaluation_task']}: {s['verdict']}")
    if not summary:
        print("ranking stability: nothing to rank (no task with two or more tools and a headline value)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
