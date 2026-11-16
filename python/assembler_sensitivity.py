#!/usr/bin/env python3
"""
assembler_sensitivity.py -- does the tool ranking depend on the assembly the tools were given?

A plasmid tool that works on contigs is judged on the assembly it receives. If changing the short-read assembler (or the
assembly selection policy) changes which tool ranks first, the benchmark is measuring the assembler-and-tool combination,
not the tool. This script answers that from runs that already exist: give it the scores.tsv of two or more runs of the
same cohort that differ only in the assembly condition (for example ASSEMBLY_SELECTION_MODE=fixed with SPAdes, and with
another assembler through ASSEMBLY_ALSO; each run in its own results folder), and it re-ranks the tools in each condition on
the same isolates.

  python python/assembler_sensitivity.py --condition spades=run_a/scores.tsv --condition unicycler=run_b/scores.tsv \\
      --out-prefix out/assembler [--html out/assembler_sensitivity.html]

Per (track, task) it reports, for every condition, the ranking over the isolates ALL conditions and tools share, the leader,
Kendall tau against the first condition and whether the leader changed, plus a verdict. It writes
<prefix>.assembler_sensitivity.tsv (and the HTML page when asked). Descriptive only: it never alters a run's scores.
Isolates missing from a condition are left out of every condition (stated in the table), so the comparison is like for like.
"""

import argparse
import csv
import html
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from headline_design import read_rows  # noqa: E402
from plasbench_common import number  # noqa: E402
from rank_sensitivity import kendall_tau, ranked  # noqa: E402
from ranking_stability import DEFAULT_REGISTRY, describe, order, read_scores, values_by_task  # noqa: E402
from tool_capabilities import evaluation_task  # noqa: E402

TAB, NL = chr(9), chr(10)
COLUMNS = ["analysis_track", "evaluation_task", "metric", "condition", "reference_condition", "isolates_compared", "tools", "leader",
           "reference_leader", "leader_changed", "kendall_tau", "tools_whose_rank_changed", "ranking", "verdict"]


def verdict(rows):
    """One verdict for a (track, task) from its per-condition rows."""
    others = [r for r in rows if r["reference_condition"] != r["condition"]]
    if not others:
        return "not_assessed: only one condition"
    changed = [r["condition"] for r in others if r["leader_changed"] == "yes"]
    taus = [number(r["kendall_tau"]) for r in others if number(r["kendall_tau"]) is not None]
    if changed:
        return ("assembler-dependent: the leader changes with the assembly (" + ", ".join(changed) + "); the ranking measures the "
                "assembler and tool together")
    if taus and min(taus) < 0.7:
        return "partly assembler-dependent: the leader holds but the order moves (tau < 0.7)"
    return "robust: the leader and the order hold across the assembly conditions"


def analyse(conditions, tasks):
    """conditions: [(name, score rows)]; returns the table rows."""
    per_condition = [(name, values_by_task(rows, tasks)) for name, rows in conditions]
    keys = sorted(set.intersection(*(set(v) for _, v in per_condition))) if per_condition else []
    out = []
    for key in keys:
        track, task, metric = key
        tools = set.intersection(*(set(v[key]) for _, v in per_condition))
        if len(tools) < 2:
            continue
        samples = set.intersection(*(set.intersection(*(set(v[key][t]) for t in tools)) for _, v in per_condition))
        if not samples:
            continue
        restricted = [(name, {t: {s: v[key][t][s] for s in samples} for t in tools}) for name, v in per_condition]
        rankings = [(name, ranked(per_tool)) for name, per_tool in restricted]
        ref_name, ref_ranking = rankings[0]
        ref_order = order(ref_ranking)
        block = []
        for name, ranking in rankings:
            rank = order(ranking)
            tau = None if name == ref_name else kendall_tau(ref_order, rank)
            moved = sorted(t for t in rank if ref_order.get(t) != rank[t]) if name != ref_name else []
            block.append({"analysis_track": track, "evaluation_task": task, "metric": metric, "condition": name,
                          "reference_condition": ref_name, "isolates_compared": len(samples), "tools": len(tools),
                          "leader": ranking[0][0], "reference_leader": ref_ranking[0][0],
                          "leader_changed": "" if name == ref_name else ("yes" if ranking[0][0] != ref_ranking[0][0] else "no"),
                          "kendall_tau": "" if tau is None else f"{tau:.3f}", "tools_whose_rank_changed": ";".join(moved),
                          "ranking": describe(ranking), "verdict": ""})
        v = verdict(block)
        for r in block:
            r["verdict"] = v
        out += block
    return out


def html_page(rows):
    esc = lambda v: html.escape(str(v))
    body = []
    seen = set()
    for r in rows:
        k = (r["analysis_track"], r["evaluation_task"])
        if k in seen:
            continue
        seen.add(k)
        group = [x for x in rows if (x["analysis_track"], x["evaluation_task"]) == k]
        cls = "warn" if group[0]["verdict"].startswith(("assembler", "partly")) else "ok"
        trs = "".join(f"<tr><td>{esc(x['condition'])}</td><td>{esc(x['leader'])}</td><td>{esc(x['kendall_tau'] or '-')}</td>"
                      f"<td>{esc(x['leader_changed'] or '-')}</td><td>{esc(x['ranking'])}</td></tr>" for x in group)
        body.append(f"<h2>{esc(k[0])} / {esc(k[1])}</h2><p class='{cls}'><strong>{esc(group[0]['verdict'])}</strong> "
                    f"({esc(group[0]['isolates_compared'])} isolates shared by every condition, {esc(group[0]['tools'])} tools; headline metric "
                    f"{esc(group[0]['metric'])})</p><table><thead><tr><th>Assembly condition</th><th>Leader</th><th>Kendall tau vs first</th>"
                    f"<th>Leader changed</th><th>Ranking</th></tr></thead><tbody>{trs}</tbody></table>")
    if not body:
        body = ["<p class='warn'>No task had two or more tools and isolates shared by every condition, so nothing was compared.</p>"]
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Assembler sensitivity</title><style>:root{color-scheme:light dark}body{font:15px/1.5 system-ui,sans-serif;max-width:60rem;"
            "margin:2rem auto;padding:0 16px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #8884;padding:4px 8px;text-align:left}"
            ".warn{border-left:4px solid #D55E00;padding-left:10px}.ok{border-left:4px solid #009E73;padding-left:10px}</style></head><body>"
            "<h1>Does the ranking depend on the assembly?</h1><p>Each condition is a run of the same cohort with a different assembly. "
            "Tools are re-ranked on the isolates every condition shares. Descriptive; no run's scores are changed.</p>" + "".join(body) + "</body></html>")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--condition", action="append", required=True, metavar="NAME=scores.tsv",
                    help="one assembly condition and the scores.tsv of its run; give at least two; the first is the reference")
    ap.add_argument("--registry", default=DEFAULT_REGISTRY)
    ap.add_argument("--out-prefix", required=True)
    ap.add_argument("--html")
    a = ap.parse_args(argv)
    conditions = []
    for item in a.condition:
        name, sep, path = item.partition("=")
        if not sep or not name or not os.path.isfile(path):
            raise SystemExit(f"--condition must be NAME=path to an existing scores.tsv, got {item!r}")
        conditions.append((name, read_scores(path)))
    if len({n for n, _ in conditions}) != len(conditions):
        raise SystemExit("condition names must be different")
    tasks = {r["tool"]: evaluation_task(r) for r in read_rows(a.registry) if r.get("tool")}
    rows = analyse(conditions, tasks) if len(conditions) > 1 else []
    with open(a.out_prefix + ".assembler_sensitivity.tsv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, delimiter=TAB, lineterminator=NL)
        writer.writeheader()
        writer.writerows(rows)
    if a.html:
        with open(a.html, "w", encoding="utf-8") as handle:
            handle.write(html_page(rows))
    if len(conditions) < 2:
        print("assembler sensitivity: give at least two --condition runs to compare")
        return 2
    for key in sorted({(r["analysis_track"], r["evaluation_task"], r["verdict"]) for r in rows}):
        print(f"assembler sensitivity {key[0]}/{key[1]}: {key[2]}")
    if not rows:
        print("assembler sensitivity: no task had two tools and isolates shared by every condition")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
