#!/usr/bin/env python3
"""The visual summary of the comparison tables (assets/report/compare_summary_*.html, python/report_compare_table.py) and the compact multiplicity section.

Plain script. Checks, with node where it is installed (a printed SKIPPED otherwise):
  * the pure view-model functions (axis scale, nice ticks, lanes for overlapping dots, short texts, row model, tool chips, ordering);
  * the honesty rules: a metric that was not assessed is never a number, never positioned, never shaded; a row with no direction, with fewer than two
    assessed tools or in which all tools tie has no shade and no best; ties share a rank; one tool alone is not ranked;
  * on the demo report: every comparison table has its summary slot, the full table is open without JavaScript and is under 'All N metrics', the
    shown number of every cell of the summary's data equals the text of the cell of the grid (and so of the original table), no row repeats a
    long 'not shaded' sentence as text, and the page carries the summary assets once;
  * the multiplicity section is compact: fixed-height rows, a closed drill-down per tool, no chart wider than its container.
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "test"))
import report_compare_table as ct  # noqa: E402
import report_reviewers as rv  # noqa: E402

NODE = shutil.which("node")
ok = True


def check(label, condition, detail=""):
    global ok
    ok &= bool(condition)
    print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))


ASSETS = ROOT / "assets" / "report"
for name in ("compare_summary_style.html", "compare_summary_core.html", "compare_summary_ui.html"):
    check(f"{name} exists and is a self-contained block", (ASSETS / name).is_file())
ui = (ASSETS / "compare_summary_ui.html").read_text(encoding="utf-8")
core = (ASSETS / "compare_summary_core.html").read_text(encoding="utf-8")
style = (ASSETS / "compare_summary_style.html").read_text(encoding="utf-8")
check("no assets are fetched: no URL, no import, no external font", not re.search(r"https?://|@import|\bfetch\(|XMLHttpRequest", ui + core + style))
check("the interface uses roles and keys: Escape closes, arrow keys move, a live region announces", "Escape" in ui and "ArrowRight" in ui and "ArrowDown" in ui and "aria-live" in ui and "role=\"checkbox\"" in ui)
check("focus is visible and touch targets grow on small screens", ":focus-visible" in style and "max-width:720px" in style)
check("dark theme and print are handled", "prefers-color-scheme:dark" in style and "data-theme=dark" in style and "@media print" in style)
check("the interface never formats a displayed cell value itself (it shows the cell's own text)", "toFixed" not in ui and "toPrecision(" not in ui.replace("x.toPrecision(4)", ""))

# ------------------------------------------------------------------------------------------------ pure functions through node
RUNNER = r"""
const fs = require('fs');
const strip = f => fs.readFileSync(f, 'utf8').replace(/^[\s\S]*?<script>/, '').replace(/<\/script>\s*$/, '');
new Function('module', strip(process.argv[2]))({exports: {}});
const m = {exports: {}};
new Function('module', strip(process.argv[3]))(m);
const Q = m.exports, job = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'));
process.stdout.write(JSON.stringify(job.map(j => { try { return Q[j.fn].apply(null, j.args); } catch (e) { return {error: String(e)}; } })));
"""


def run_node(calls):
    with tempfile.TemporaryDirectory() as tmp:
        job = Path(tmp) / "job.json"
        job.write_text(json.dumps([{"fn": f, "args": a} for f, a in calls]), encoding="utf-8")
        (Path(tmp) / "run.js").write_text(RUNNER, encoding="utf-8")
        done = subprocess.run([NODE, str(Path(tmp) / "run.js"), str(ASSETS / "compare_table_core.html"), str(ASSETS / "compare_summary_core.html"), str(job)],
                              capture_output=True, text=True, encoding="utf-8")
        if done.returncode:
            return None, done.stderr[-500:]
        return json.loads(done.stdout), ""


def data_block(rows, direction="higher", metric_id="m"):
    """A minimal data block like report_compare_table.build writes: rows is a list of cells [disp, value, n, lo, hi, [], na] per tool."""
    return {"id": "t", "title": "T", "cols": [{"id": f"c{i}", "label": f"tool{i}", "track": "short_read", "task": f"rank {i + 1}" if i < 2 else ""} for i in range(len(rows))],
            "groups": [{"t": "G", "m": [{"id": metric_id, "name": "Metric", "dir": direction}]}], "samples": [], "cells": {metric_id: rows}}


if NODE:
    D1 = data_block([["0.9", 0.9], ["0.5", 0.5], ["0.5", 0.5], ["not assessed", None, None, None, None, [], "no truth"]])
    D_one = data_block([["0.7", 0.7]])
    D_tied = data_block([["1.0000", 1.0], ["1.0000", 1.0]])
    D_none = data_block([["6", 6], ["6", 6]], direction=None)
    D_two_one = data_block([["0.4", 0.4], ["not bin-scored", None, None, None, None, [], "not bin-scored"]])
    metric = {"id": "m", "name": "Metric", "dir": "higher"}
    calls = [("scaleFor", [[0.2, 0.9], ["0.2", "0.9"]]), ("scaleFor", [[-0.3, 0.8], []]), ("scaleFor", [[12.5, 99.1], ["12.5%", "99.1%"]]), ("scaleFor", [[0.1, 2.38], []]),
             ("scaleFor", [[], []]), ("scaleFor", [[0, 6], []]), ("scaleFor", [[99.96, 99.97, 99.99], ["99.96%", "99.97%", "99.99%"], True]),
             ("scaleFor", [[99.96], ["99.96%"], True]), ("scaleFor", [[0.2, 0.9], [], True]), ("nice", [2.5779]), ("nice", [0.93]), ("nice", [104]), ("nice", [0]),
             ("lanes", [[{"pos": 50, "i": 0}, {"pos": 51, "i": 1}, {"pos": 90, "i": 2}, {"pos": 50.5, "i": 3}], 5]),
             ("lanes", [[{"pos": 10, "i": 0}, {"pos": 40, "i": 1}], 5]),
             ("shortText", ["63.6% (7/11); per isolate 69.4%; SV-PRR 63.6%"]), ("shortText", ["0.8962"]), ("shortText", ["x" * 80, 10]), ("shortText", [None]),
             ("rowModel", [D1, metric, [0, 1, 2, 3]]), ("rowModel", [D_one, metric, [0]]), ("rowModel", [D_tied, metric, [0, 1]]),
             ("rowModel", [D_none, dict(metric, dir=None), [0, 1]]), ("rowModel", [D_two_one, metric, [0, 1]]),
             ("plottable", [D1, metric, [0, 1]]), ("plottable", [D_none, dict(metric, dir=None), [0, 1]]), ("plottable", [data_block([["x", None, None, None, None, [], "na"]]), metric, [0]]),
             ("toolChips", [D1, [0, 1, 2]]), ("orderBy", [D1, metric, [0, 1, 2, 3]]), ("orderBy", [D1, dict(metric, dir="lower"), [0, 1, 2, 3]]),
             ("compositionOf", [{"m": [{"id": "identity"}, {"id": "mismatch"}, {"id": "insertion"}, {"id": "deletion"}]}]), ("compositionOf", [{"m": [{"id": "identity"}]}]),
             ("whyText", ["no_direction"]), ("whyText", ["too_few"]), ("whyText", ["all_tied"]), ("whyText", ["ok"])]
    res, err = run_node(calls)
    check("node runs the summary core", res is not None, err)
    if res is not None:
        i = iter(res)
        nx = lambda: next(i)  # noqa: E731
        s = nx(); check("shares in 0..1 use the fixed 0..1 axis", s["lo"] == 0 and s["hi"] == 1 and s["fixed"], s)
        s = nx(); check("a signed measure (MCC) uses -1..1", s["lo"] == -1 and s["hi"] == 1 and s["kind"] == "signed", s)
        s = nx(); check("percentages use 0..100", s["lo"] == 0 and s["hi"] == 100 and s["kind"] == "percent", s)
        s = nx(); check("another measure runs from 0 to a round tick above its largest value", s["lo"] == 0 and s["hi"] == 2.5 and not s["fixed"], s)
        s = nx(); check("no values gives a harmless 0..1 axis", s["lo"] == 0 and s["hi"] == 1, s)
        s = nx(); check("counts run from 0 to a round tick", s["lo"] == 0 and s["hi"] >= 6, s)
        z = nx(); check("tools packed into a sliver of a percentage axis zoom to them, the axis ends are labelled by the interface", z["kind"] == "zoom" and z["lo"] > 99 and z["hi"] <= 100 and not z["fixed"], z)
        z = nx(); check("one tool alone is never zoomed: it keeps the fixed natural axis", z["kind"] == "percent" and z["lo"] == 0 and z["hi"] == 100, z)
        z = nx(); check("tools that are spread out keep the natural 0..1 axis even when zoom is allowed", z["kind"] == "unit" and z["hi"] == 1, z)
        check("nice ticks round up to 1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10 times a power of ten", [nx(), nx(), nx(), nx()] == [3, 1, 120, 1])
        ln = nx(); check("overlapping dots take different lanes and a far dot keeps lane 0", ln["0"] == 0 and ln["3"] == 1 and ln["1"] == 2 and ln["2"] == 0, ln)
        ln = nx(); check("dots far apart share a lane", ln["0"] == 0 and ln["1"] == 0, ln)
        check("a long cell text is cut at the first semicolon, the full text stays elsewhere", nx() == "63.6% (7/11)")
        check("a short text is unchanged, a too-long one is ellipsised, none gives empty", [nx(), nx(), nx()] == ["0.8962", "x" * 9 + "…", ""])
        r = nx()
        check("row model: the best tool is ranked 1 and flagged, ties share a rank", r["status"] == "ok" and r["cells"][0]["rank"] == 1 and r["cells"][0]["best"]
              and r["cells"][1]["rank"] == r["cells"][2]["rank"] == 2.5 and not r["cells"][1]["best"], r["cells"])
        check("a not-assessed cell has no number, no position, no rank, no shade bucket and is never zero",
              r["cells"][3]["v"] is None and "pos" not in r["cells"][3] and r["cells"][3]["rank"] is None and r["cells"][3]["bucket"] is None and r["cells"][3]["na"] == "no truth"
              and r["assessed"] == 3, r["cells"][3])
        r = nx()
        check("one tool alone: not ranked, nothing is best, the value keeps its position on the fixed scale", r["status"] == "too_few" and not r["cells"][0]["best"] and r["cells"][0]["bucket"] is None
              and r["cells"][0]["pos"] == 70 and r["scale"]["fixed"], r)
        r = nx()
        check("all tied: not shaded, no best", r["status"] == "all_tied" and not any(c["best"] for c in r["cells"]) and all(c["bucket"] is None for c in r["cells"]), r)
        r = nx()
        check("no direction: not shaded, no rank, no best", r["status"] == "no_direction" and all(c["rank"] is None and c["bucket"] is None and not c["best"] for c in r["cells"]), r)
        r = nx()
        check("one of two tools assessed: not ranked, and the other is not a zero", r["status"] == "too_few" and r["cells"][1]["v"] is None and "pos" not in r["cells"][1], r)
        check("plottable: a defined direction and a number; a count without direction or an all-missing metric is not", [nx(), nx(), nx()] == [True, False, False])
        chips = nx()
        check("tool chips give the source table's rank when the column has one and a mean rank otherwise, and never a score",
              chips[0]["official"] == "rank 1" and chips[1]["official"] == "rank 2" and chips[2]["official"] == "" and chips[0]["mean"] == 1 and chips[2]["mean"] == 2.5, chips)
        check("order by a metric: best first, ties keep their order, a tool with no value goes last", nx() == [0, 1, 2, 3])
        check("order by a lower-is-better metric reverses", nx() == [1, 2, 0, 3])
        check("an error composition needs mismatch, insertion and deletion", nx() == ["mismatch", "insertion", "deletion"] and nx() is None)
        why = [nx(), nx(), nx(), nx()]
        check("each reason a row is not ranked has its own short text", "direction" in why[0] and "two tools" in why[1] and "same value" in why[2] and why[3] == "", why)
else:
    print("  SKIPPED: node is not installed, so the summary's pure functions were not run")

# ------------------------------------------------------------------------------------------------ the static component
cells = {("a", "t1"): ct.cell("0.9100", n=6, lo=0.8, hi=0.95), ("a", "t2"): ct.cell("0.5000", n=6), ("a", "t3"): ct.cell("not assessed", None, na="no truth"),
         ("c", "t1"): ct.cell("6"), ("c", "t2"): ct.cell("6"), ("c", "t3"): ct.cell("6")}
groups = [{"title": "Base-level accuracy", "metrics": [ct.metric("a", "Mean F1", "F1.", "higher")]}, {"title": "Run outcome", "metrics": [ct.metric("c", "Scored", "Count.", None)]}]
page = ct.build("demo", "Demo", groups, [ct.column("t1", "T1", "short_read", "rank 1"), ct.column("t2", "T2", "short_read", "rank 2"), ct.column("t3", "T3")], cells, table_html="<table></table>")
check("a summary slot comes first, then the full table under 'All 2 metrics'", page.index("class='cs'") < page.index("<details class='ct-all") < page.index("<table class='ct-grid'"))
check("without JavaScript the full table is open", re.search(r"<details class='ct-all rpt-collapsible' open>", page))
fin = ct.finish(page)
check("the plain-language question and how-to-read line of each group are in the page once, by group title", fin.count("id='cs-groups'") == 1 and "How accurate are the bases?" in fin and "Did the runs finish?" in fin
      and '"q":' not in page.split("class='ct-data'>")[1])
check("a not-shaded row says why with one icon (tooltip), not a sentence of text", "&#9432;" in page and not re.search(r">[^<]*direction not defined: not shaded[^<]*<", page.replace("title='direction not defined: not shaded'", "")))
check("the legend is one compact line", len(re.search(r"<p class='ct-legend'>.*?</p>", page, re.S).group(0)) < 1100)
check("the summary assets are added once with the table assets", all(f"id='{x}'" in ct.finish(page) for x in ("ct-style", "cs-style")) and ct.finish(page).count("PBCS = api") == 1)
check("a group without a registered question keeps its own title", "Other things" not in ct.GROUP_QUESTIONS)

# ------------------------------------------------------------------------------------------------ the demo report
try:
    import test_report_feature_manifest as fm
except Exception as exc:                                       # pragma: no cover
    fm = None
    print(f"  SKIPPED: cannot import the report build helper ({exc})")
if fm and (ROOT / "results_demo").is_dir():
    with tempfile.TemporaryDirectory() as work:
        report, _results = fm.build_report(work)
    comps = re.findall(r"<div class='ct' id='ct-([^']+)'", report)
    check(f"demo report: {len(comps)} comparison tables, each with a summary slot and an open full table", len(comps) >= 10 and report.count("class='cs' data-cs") == len(comps)
          and report.count("<details class='ct-all rpt-collapsible' open>") == len(comps))
    check("demo report: the summary style and scripts are in the page once", report.count("id='cs-style'") == 1 and report.count("PBCS = api") == 1)
    mismatches, compared = [], 0
    for m in re.finditer(r"<div class='ct' id='ct-([^']+)'.*?<script type='application/json' class='ct-data'>(.*?)</script>", report, re.S):
        data = json.loads(m.group(2).replace("\\u003c", "<").replace("\\u003e", ">").replace("\\u0026", "&"))
        body = report[m.start():m.end()]
        for tr in re.finditer(r"<tr class='ct-row' data-m='([^']*)'[^>]*>(.*?)</tr>", body, re.S):
            mid, row = tr.group(1), tr.group(2)
            texts = {int(c): re.sub(r"<[^>]+>", "", t).replace("★", "").strip() for c, t in re.findall(r"<td[^>]* data-c='(\d+)'[^>]*>(.*?)</td>", row, re.S)}
            for ci, cell in enumerate(data["cells"][mid]):
                compared += 1
                shown = cell[0] if cell else ""
                static = texts.get(ci, "")
                if static in ("–", "") and not shown:
                    continue
                if static != shown:
                    mismatches.append((m.group(1), mid, ci, shown, static))
    check(f"demo report: the number or text the summary reads for every cell equals the grid cell, which equals the original table ({compared} cells)", compared > 100 and not mismatches, mismatches[:3])
    stat_texts = set(re.findall(r"<span class='ct-rowstat'[^>]*>([^<]*)</span>", report))
    check("demo report: every row-status mark is an icon with a tooltip, not a sentence of text", stat_texts <= {"&#9432;", ""} and "&#9432;" in stat_texts, sorted(stat_texts)[:3])
    check("demo report: the row-status tooltips still say why (direction, fewer than two tools, tied)", all(w in report for w in (
        "title='direction not defined: not shaded'", "title='fewer than 2 tools assessed: not shaded'", "title='every assessed tool is tied: not shaded'")))
    groups_seen = set()
    for g in re.findall(r"\"groups\":\[(.*?)\],\"samples\"", report):
        groups_seen.update(re.findall(r"\{\"t\":\"([^\"]+)\"", g))
    unmapped = sorted(g for g in groups_seen if g not in ct.GROUP_QUESTIONS and not g.startswith("Feature kind"))
    print(f"  INFO: groups without a plain-language question (keep their own title): {unmapped}")
else:
    print("  SKIPPED: results_demo is absent (run test/run_demo.sh first), so the demo report was not checked")

# ------------------------------------------------------------------------------------------------ multiplicity section
def prow(sample, tool, plasmid, outcome, n_cand, best, comb, red_bp, red_frac, touching):
    return {"sample": sample, "tool": tool, "plasmid": plasmid, "plasmid_length": "100000", "outcome": outcome, "n_candidates": n_cand, "n_touching": touching,
            "best_candidate": "A", "best_candidate_coverage": best, "combined_coverage": comb, "coverage_gain": f"{float(comb) - float(best):.3f}", "redundant_bp": red_bp,
            "redundancy_fraction": red_frac, "n_fragments": "1", "n_redundant": "1", "n_chimeric_touching": "1", "candidate_bp_to_union_ratio": "1.35"}


plasmids = [prow("S1", "toolA", "P1", "fragmented_and_duplicated", "3", "0.60", "1.00", "35000", "0.259", "4"), prow("S1", "toolA", "P2", "single", "1", "1.00", "1.00", "0", "0.0", "1"),
            prow("S1", "toolB", "P1", "single", "1", "0.90", "0.90", "0", "0.0", "1")]
cands = [{"sample": "S1", "tool": "toolA", "candidate": "A", "length": "60000", "aligned_bp": "60000", "plasmid_bp": "60000", "chromosome_bp": "0", "relationship": "primary"},
         {"sample": "S1", "tool": "toolB", "candidate": "X", "length": "90000", "aligned_bp": "90000", "plasmid_bp": "90000", "chromosome_bp": "0", "relationship": "primary"}]
ints = [{"sample": "S1", "tool": "toolA", "plasmid": "P1", "plasmid_length": "100000", "candidate": "A", "start": "0", "end": "60000", "relationship": "primary"},
        {"sample": "S1", "tool": "toolA", "plasmid": "P1", "plasmid_length": "100000", "candidate": "B", "start": "55000", "end": "90000", "relationship": "complementary_fragment"}]
html = rv.multiplicity_section(plasmids, cands, ints)
check("multiplicity: one fixed-height row per tool, each a closed drill-down", html.count("<details class='mx-tool'>") == 2 and "<details class='mx-tool' open" not in html)
check("multiplicity: each row carries its composition bar, coverage dumbbell and outcome bar with accessible names", html.count("class='mx-bar'") == 2 and html.count("class='mx-dumb'") == 2
      and html.count("class='mx-bar mx-oc'") == 2 and "role='img'" in html)
check("multiplicity: the per-plasmid table and the tracks are inside the drill-down, tracks closed and height-limited", "<details class='mx-track'>" in html and "mx-scroll" in html
      and ".mx-track svg{display:block;width:100%;max-height:250px}" in rv.CSS)
check("multiplicity: the full-size charts and the all-values table are kept, closed", "Full-size charts" in html and "All values (one row per tool)" in html and "<td>toolA</td><td>2</td>" in html)
check("multiplicity: a plasmid never becomes zero when a value is missing (no 'nan' in the page)", "nan" not in html.lower().replace("candidates", ""))
check("multiplicity: colour is not the only channel (patterns, counts and a legend)", "repeating-linear-gradient" in rv.CSS and "mx-key" in html)

print()
if not ok:
    print("COMPARE SUMMARY TESTS FAILED")
    sys.exit(1)
print("ALL COMPARE SUMMARY TESTS PASSED")
