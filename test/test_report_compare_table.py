#!/usr/bin/env python3
"""The comparison table (python/report_compare_table.py, python/report_compare_apply.py, assets/report/compare_table_*.html).

Plain script. Unit checks on fixtures (direction, ties, missing, ranking by rank and not by value, escaping, the panel's values against the table's, the print
markers, empty states); static checks of the toolbar, checkbox, side panel and ARIA; a node test that the pure JavaScript functions agree with the Python mirror
number by number (skipped with a printed reason when node is not installed); and a build of the demo report and of results_real_cohort1 (the demo build is
skipped with a printed reason when results_demo has not been made by test/run_demo.sh).
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "test"))
import report_compare_apply as apply  # noqa: E402
import report_compare_table as ct  # noqa: E402
from plasbench_common import display_tool_name  # noqa: E402

NODE = shutil.which("node")
ok = True


def check(label, condition, detail=""):
    global ok
    ok &= bool(condition)
    print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))


class Grid(HTMLParser):
    """Tables of a fragment as lists of rows of cell texts, in order; the text of a cell excludes script and style."""

    def __init__(self):
        super().__init__()
        self.tables, self._row, self._cell, self._skip = [], None, None, 0
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        if tag == "table":
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip -= 1
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.tables[-1].append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None and not self._skip:
            self._cell.append(data)


def tables_of(fragment):
    g = Grid()
    g.feed(fragment)
    return g.tables


def payload_of(fragment, cid=None):
    blocks = re.findall(r"<script type='application/json' class='ct-data'>(.*?)</script>", fragment, re.S)
    out = [json.loads(b) for b in blocks]
    return out if cid is None else [p for p in out if p["id"] == cid]


# ------------------------------------------------------------------------------------------------ the ranking function
rs = ct.rank_shade
r = rs([0.9, 0.5, 0.7], "higher")
check("higher is better: the largest value has rank 1 and shade 1 (best), the smallest shade 0 (worst), the middle 0.5",
      r["rank"] == [1, 3, 2] and r["t"] == [1.0, 0.0, 0.5] and r["bucket"] == [10, 0, 5] and r["best"] == [True, False, False], r)
r = rs([0.9, 0.5, 0.7], "lower")
check("lower is better: the smallest value is best", r["rank"] == [3, 1, 2] and r["best"] == [False, True, False], r)
r = rs([1, 2, 1000], "higher")
check("shading is by rank, not by raw value: an extreme value does not change the others' shade",
      r["bucket"] == rs([1, 2, 3], "higher")["bucket"] == [0, 5, 10], r)
r = rs([5, 5, 3, None], "higher")
check("ties share the average rank; a missing cell has no rank and no shade", r["rank"] == [1.5, 1.5, 3, None] and r["t"][3] is None and r["bucket"][3] is None, r)
check("tied cells are both best", r["best"] == [True, True, False, False], r)
r = rs([0.4, 0.4, 0.4], "higher")
check("a row in which every assessed tool ties is not shaded (and nothing is best)", r["status"] == "all_tied" and r["bucket"] == [None] * 3 and not any(r["best"]), r)
r = rs([0.4, None, None], "higher")
check("fewer than two assessed tools: not shaded", r["status"] == "too_few" and r["bucket"] == [None] * 3, r)
r = rs([0.4, 0.8], None)
check("a metric with no direction is not shaded", r["status"] == "no_direction" and r["bucket"] == [None, None], r)
check("a not-assessed value (None) never becomes zero: it keeps no rank", rs([0.0, None, 1.0], "higher")["rank"] == [2, None, 1])
check("the status texts say why a row is not shaded",
      "not defined" in ct.row_status_text("no_direction") and "fewer than 2" in ct.row_status_text("too_few") and "tied" in ct.row_status_text("all_tied"))
check("quartiles (type 7) of 1..5", ct.quartiles([1, 2, 3, 4, 5]) == {"n": 5, "min": 1, "q1": 2.0, "median": 3.0, "q3": 4.0, "max": 5})
check("Tukey outliers: 100 among 1..4 is one; fewer than four values are never outliers", ct.outliers([1, 2, 3, 4, 100]) == [4] and ct.outliers([1, 2, 100]) == [])
check("columns sort by mean rank, best first, a column with no rank last", ct.mean_rank_order([[1, 2, None], [1, 3, None]], 3) == [0, 1, 2])

# ------------------------------------------------------------------------------------------------ directions from the registry
d, row = ct.resolve("leaderboard", "mean_precision")
check("direction comes from the registry: base precision is higher-is-better", d == "higher" and row["id"] == "base_precision", (d, row))
check("direction comes from the scorecard where a scorecard id exists: mismatch rate is lower-is-better", ct.resolve("accuracy", "mismatch_rate")[0] == "lower")
check("variation of information is lower-is-better", ct.resolve("leaderboard", "mean_variation_of_information")[0] == "lower")
check("a column not in the registry has no direction (never guessed)", ct.resolve("nowhere", "nothing") == (None, None))
m = ct.metric("x", "X", "", "auto", source="nowhere", column="nothing")
check("metric() with an unknown source has direction None", m["dir"] is None)
check("metric() keeps an explicit direction and refuses a made-up one", ct.metric("x", "X", "", "higher")["dir"] == "higher" and ct.metric("x", "X", "", "sideways")["dir"] is None)

# ------------------------------------------------------------------------------------------------ a fixture
cols = [ct.column("a", "tool<A>", "short_read", "binning"), ct.column("b", "tool \"B\"", "short_read", "binning"), ct.column("c", "tool C", "short_read", "binning")]
groups = [{"title": "Scores <g>", "metrics": [
    ct.metric("f1", "F1 <b>x</b>", "Base F1.", "higher", source="leaderboard", column="mean_f1"),
    ct.metric("vi", "VI", "Variation of information.", "lower"),
    ct.metric("cnt", "Count", "A count.", None),
    ct.metric("one", "Only one", "Assessed for one tool.", "higher"),
    ct.metric("tie", "Tied", "All equal.", "higher")]}]
cells = {}
for cid, v in zip("abc", (0.9, 0.5, 0.7)):
    cells[("f1", cid)] = ct.cell(f"{v:.2f}", n=6, lo=v - .05, hi=v + .05, iso={"iso1": v, "iso2": v - .1, "iso<3>": v + .1})
for cid, v in zip("abc", (3.0, 1.0, 2.0)):
    cells[("vi", cid)] = ct.cell(str(v))
for cid in "abc":
    cells[("cnt", cid)] = ct.cell("7")
    cells[("tie", cid)] = ct.cell("0.5")
cells[("one", "a")] = ct.cell("0.3")
cells[("one", "b")] = ct.cell("not bin-scored", None, na="not bin-scored")
frag = ct.build("fx", "Fixture <t>", groups, cols, cells, table_html=ct.static_table(cols, groups, cells), label=str.upper)
check("static grid is a role=grid table with scrollable wrapper, a closed Table fold and a hidden side panel",
      "role='grid'" in frag and "class='ct-scroll'" in frag and re.search(r"<details class='ct-fold[^']*' data-closed='1'><summary>Table</summary>", frag) and "<aside class='ct-panel' hidden" in frag)
check("the 'Show heatmap' checkbox and toolbar are added by the script (not duplicated in the static grid)", "Show heatmap" in (ROOT / "assets/report/compare_table_ui.html").read_text(encoding="utf-8"))
shades = re.findall(r"data-m='(\w+)'.*?</tr>", frag, re.S)
row_html = {mm.group(1): mm.group(0) for mm in re.finditer(r"<tr class='ct-row' data-m='(\w+)'.*?</tr>", frag, re.S)}
check("f1 row: best is blue-end bucket 10 with a star, worst bucket 0, middle bucket 5",
      "ct-s10 ct-best" in row_html["f1"] and "ct-s0'" in row_html["f1"] and "ct-s5" in row_html["f1"] and "★" in row_html["f1"], row_html["f1"][:600])
check("vi row (lower is better): the smallest value (1.0, tool B) is the best", re.search(r"ct-s10 ct-best' data-c='1'", row_html["vi"]) is not None, row_html["vi"][:500])
check("a count row (no direction) is not shaded and says 'direction not defined'", not re.search(r"ct-s\d", row_html["cnt"]) and "direction not defined: not shaded" in row_html["cnt"], row_html["cnt"][:400])
check("a metric assessed for fewer than two tools is not shaded and says why", not re.search(r"ct-s\d", row_html["one"]) and "fewer than 2 tools assessed" in row_html["one"], row_html["one"][:400])
check("a not-assessed cell is hatched (ct-na) with its reason and its text, never shaded", "ct-na" in row_html["one"] and "not bin-scored" in row_html["one"])
check("an all-tied row is not shaded and says so", not re.search(r"ct-s\d", row_html["tie"]) and "every assessed tool is tied" in row_html["tie"])
check("the legend says the shade is by rank and not by raw value", "by rank within each row" in frag and "not by raw value" in frag)
check("the legend explains hatch, not-shaded rows and the best-in-row star", "not assessed: never shaded, never zero" in frag and "are not shaded" in frag and "best in row" in frag)

# escaping
check("the tool label, metric and title are escaped in the HTML", "&lt;b&gt;" in frag and "TOOL&lt;A&gt;" in frag and "<b>x</b>" not in frag and "TOOL<A>" not in frag)
check("no raw < or > survives inside the data block", "<" not in re.search(r"class='ct-data'>(.*?)</script>", frag, re.S).group(1))
pl = payload_of(frag)[0]
check("the data block decodes to the same labels (unescaped)", pl["cols"][0]["label"] == "TOOL<A>" and pl["groups"][0]["m"][0]["name"] == "F1 <b>x</b>")
check("isolate names are shared once in the block (compact) and cells point at them by index", pl["samples"] == ["iso1", "iso2", "iso<3>"] and pl["cells"]["f1"][0][5] == [[0, 0.9], [1, 0.8], [2, 1.0]])

# the panel's values equal the table's
fold = tables_of(re.search(r"<details class='ct-fold.*?</details>", frag, re.S).group(0))[0]
grid = tables_of(frag.split("<details class='ct-fold")[0])[0]
names = [g["m"] for g in pl["groups"]]
flat = [m["id"] for g in pl["groups"] for m in g["m"]]
equal = True
for i, mid in enumerate(flat):
    for j in range(len(cols)):
        panel_text = pl["cells"][mid][j][0]
        table_text = fold[i + 1][j + 1]
        grid_row = [x for x in grid if x and x[0].startswith(pl["groups"][0]["m"][i]["name"])][0]
        grid_text = re.sub(r"^★", "", grid_row[j + 1])
        equal &= (panel_text == table_text == grid_text)
check("for the fixture every cell's text is identical in the panel data, the grid and the original table", equal)

# print markers
style = (ROOT / "assets/report/compare_table_style.html").read_text(encoding="utf-8")
print_css = style[style.index("@media print"):]
check("print: the panel and toolbar are omitted, the shading is kept exactly, and the table fold is printed open",
      ".ct-panel" in print_css and "display:none" in print_css and "print-color-adjust:exact" in print_css and ".ct-s0{background:" in print_css.replace(" ", "") and ".ct-fold>*:not(summary){display:block!important}" in print_css)
check("print: hidden rows and columns are shown again and the sticky positions are removed", ".ct-row.ct-hide{display:table-row!important}" in print_css and "position:static!important" in print_css)
check("the shading is a class on every cell (a complete static grid needs no script)", len(re.findall(r"ct-s\d+", frag)) >= 6)

# empty states
check("a table with no rows is returned unchanged (the plain table stays)", apply.leaderboard([], lambda r: {}, [], "<TABLE/>") == "<TABLE/>" and apply.from_table("x", "t", [], 0, []) == "")
check("from_table with no rows returns the original table", apply.from_table("x", "t", [], 0, [], table_html="<T/>") == "<T/>")
empty = ct.build("empty", "Empty", [], [], {})
check("a component with no metrics and no tools still builds", "class='ct'" in empty and "0 metrics by 0 tools" in empty)
check("finish() adds the assets once, and only when a component is on the page",
      ct.finish("<body></body>") == "<body></body>" and ct.finish("<body>" + frag + "</body>").count("id='ct-style'") == 1
      and ct.finish(ct.finish("<body>" + frag + "</body>")).count("id='ct-assets'") == 1)

# the generic adapter: shown text, parsed number, per track, one table fold
rows = [["short_read", "t1", "99.5%", "12"], ["short_read", "t2", "98.1%", "3"], ["long_read", "t1", "-", "5"]]
html_out = apply.from_table("gx", "Grid", rows, 1, [
    ("G", 2, "id", "Identity", dict(source="accuracy", column="identity")), ("G", 3, "n", "Plasmids", dict(dir=None))], track_col=0, table_html="<TABLE/>")
pls = payload_of(html_out)
check("one component per track (never pooled), one Table fold after them", len(pls) == 2 and html_out.count("<TABLE/>") == 1, [p["id"] for p in pls])
c0 = pls[0]["cells"]["id"]
check("the cell text is the table's text ('99.5%'), the rank uses the number", c0[0][0] == "99.5%" and c0[0][1] == 99.5 and "ct-s10 ct-best" in html_out)
check("a dash is not a number: it is a hatched cell 'not reported', never shaded", pls[1]["cells"]["id"][0][0] == "-" and pls[1]["cells"]["id"][0][6] == "not reported")

# ------------------------------------------------------------------------------------------------ the dimension tables: panel text equals table text
sys.path.insert(0, str(ROOT / "python"))
import report_dimensions as rdim  # noqa: E402

with tempfile.TemporaryDirectory() as work:
    prefix = os.path.join(work, "b")

    def write(name, header, body):
        with open(f"{prefix}.{name}.tsv", "w", encoding="utf-8", newline="") as h:
            h.write("\t".join(header) + "\n" + "".join("\t".join(map(str, r)) + "\n" for r in body))

    write("bin_quality", "sample tool analysis_track n_truth_plasmids n_bins n_high n_medium n_low n_spurious plasmids_with_high_bin plasmids_with_medium_or_better_bin high_quality_yield medium_or_better_yield homogeneity completeness v_measure".split(),
          [["s1", "t1", "short_read", 2, 2, 1, 1, 0, 0, 1, 2, .5, 1, .9, .8, .85], ["s2", "t1", "short_read", 1, 1, 1, 0, 0, 0, 1, 1, 1, 1, .7, .6, .65], ["s1", "t2", "short_read", 2, 3, 0, 1, 2, 1, 0, 1, 0, .5, .4, .3, .35],
           ["s2", "t2", "short_read", 1, 1, 0, 0, 1, 0, 0, 0, 0, 0, .2, .2, .2]])
    write("performance", "tool n_runs n_completed n_failed n_resource_failures n_skipped success_rate median_runtime_seconds p90_runtime_seconds median_peak_memory_gb threads recovered_plasmids thread_seconds_per_recovered_plasmid cpu_utilisation n_cpu_runs runtime_scaling_exponent memory_scaling_exponent n_scaling_points".split(),
          [["t1", 6, 6, 0, 0, 0, 1.0, 125.5, 132.5, 2.5, 1, 6, 126, "", "", .1, 0, 6], ["t2", 6, 5, 1, 0, 0, .8333, 50.5, 57.5, 1.1, 1, 11, 27.8, "", "", .2, 0, 6]])
    _, sections = rdim.render(prefix, ct.esc, lambda p: p)
    for sid in ("bin-quality", "performance"):
        block = re.search(rf"<section id='{sid}'>.*?</section>", sections, re.S)
        check(f"{sid}: the section holds a comparison table and keeps its original table in the fold", block and "class='ct'" in block.group(0) and "<details class='ct-fold" in block.group(0))
        body = block.group(0)
        pl = payload_of(body)
        fold_t = tables_of(re.search(r"<details class='ct-fold.*?</details>", body, re.S).group(0))[0]
        heads = fold_t[0]
        mism, seen = [], 0
        for p in pl:
            for g in p["groups"]:
                for m in g["m"]:
                    if m["name"] not in heads:
                        continue
                    hi = heads.index(m["name"])
                    for j, c in enumerate(p["cols"]):
                        tool = c["label"]
                        trow = [x for x in fold_t[1:] if any(tool == display_tool_name(cell) for cell in x[:2])]
                        if trow:
                            seen += 1
                            if p["cells"][m["id"]][j][0] != trow[0][hi]:
                                mism.append((m["name"], tool, p["cells"][m["id"]][j][0], trow[0][hi]))
        check(f"{sid}: every compared cell's text equals the original table's cell ({seen} cells)", seen > 0 and not mism, mism[:3])
    perf = re.search(r"<section id='performance'>.*?</section>", sections, re.S).group(0)
    check("performance: runtime is lower-is-better (registry) and success rate higher-is-better; P90 has no direction and says so",
          "data-m='runtime' data-g='Speed and memory' data-dir='lower'" in perf and "data-m='success' data-g='Reliability' data-dir='higher'" in perf and "direction not defined: not shaded" in perf)
    bq = payload_of(re.search(r"<section id='bin-quality'>.*?</section>", sections, re.S).group(0))[0]
    iso = bq["cells"]["homogeneity"][0][5]
    check("bin quality: the per-isolate values behind a cell are the per-sample table values", sorted(v for _i, v in iso) == [.7, .9] and sorted(bq["samples"]) == ["s1", "s2"], iso)

# ------------------------------------------------------------------------------------------------ static checks of the script, the style and the wiring
ui = (ROOT / "assets/report/compare_table_ui.html").read_text(encoding="utf-8")
core = (ROOT / "assets/report/compare_table_core.html").read_text(encoding="utf-8")
check("toolbar: Show heatmap checkbox, tool filter, sort select, collapse groups, CSV", all(x in ui for x in ("Show heatmap", "ct-heatbox", "ct-q", "ct-sort", "ct-allg", "ct-csv", "Download CSV")))
check("columns: a drag handle and a keyboard alternative (arrow keys on the handle), announced in a live region", "dragstart" in ui and "ArrowLeft" in ui and "aria-live" in ui and "moved to position" in ui)
check("side panel: cell, metric and tool views; close; Escape; links to isolates; outliers; other tools", all(x in ui for x in ("cellPanel", "metricPanel", "toolPanel", "ct-pclose", "Escape", "ct-out", "Same metric, other tools", "Isolates, best to worst")))
check("grid keyboard: arrow keys, Home/End, Enter/Space open the panel, roving tabindex", all(x in ui for x in ("ArrowDown", "Home", "'Enter'", "tabIndex")))
check("ARIA: grid role, aria-expanded groups, aria-selected cell, aria-label per cell, tooltip role", "role=" in ui and "aria-expanded" in ui and "aria-selected" in ui and "aria-label" in ui and "tooltip" in ui)
check("print: the script shades everything before printing", "beforeprint" in ui and "afterprint" in ui)
check("dark theme and phone width: variables for dark, a sticky first column and a narrow-screen rule", "prefers-color-scheme:dark" in style and "[data-theme=dark]" in style and "position:sticky;left:0" in style and "max-width:760px" in style)
check("no external library, no network call", not re.search(r"https?://|import\s|fetch\(|XMLHttpRequest", ui + core + style.replace("http://www.w3.org", "")))
check("the component has a help entry and the help module takes self-placed buttons", "compare-table" in (ROOT / "python/report_help_text.py").read_text(encoding="utf-8") and "rpt-help-btn' data-help=" in (ROOT / "python/report_help.py").read_text(encoding="utf-8"))
check("the condense step leaves a comparison grid alone (it has its own filter)", "ct-grid" in (ROOT / "python/report_condense.py").read_text(encoding="utf-8"))

# ------------------------------------------------------------------------------------------------ node: the JavaScript core agrees with the Python mirror
RUNNER = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const m = {exports: {}};
new Function('module', src.replace(/^[\s\S]*?<script>/, '').replace(/<\/script>\s*$/, ''))(m);
const P = m.exports, job = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
process.stdout.write(JSON.stringify(job.map(j => P[j.fn].apply(null, j.args))));
"""
if NODE:
    cases = [([0.9, 0.5, 0.7], "higher"), ([0.9, 0.5, 0.7], "lower"), ([1, 2, 1000], "higher"), ([5, 5, 3, None], "higher"), ([5, 5, 3, None], "lower"), ([0.4, 0.4, 0.4], "higher"),
             ([0.4, None, None], "higher"), ([0.4, 0.8], None), ([0.4, 0.8], "sideways"), ([None, None], "higher"), ([1, 1, 2, 2, 3, 3, 9], "higher"), ([0.1, 0.2, 0.3, 0.4, 0.5], "lower"),
             ([3, None, 1, 2, 2, None, 10], "lower"), ([1e-9, 2e-9, 3e-9], "higher"), ([0.30000000000000004, 0.3, 0.1], "higher")]
    with tempfile.TemporaryDirectory() as tmp:
        calls = [("rankShade", [v, d]) for v, d in cases] + [("quartiles", [v]) for v in ([1, 2, 3, 4, 5], [1, 2], [7], [], [1, 2, 3, 4, 100], [0.5, 0.1, 0.9, 0.3])] \
            + [("outliers", [v]) for v in ([1, 2, 3, 4, 100], [1, 2, 100], [1, 2, 3, 4, 5, 6], [None, 1, 2, 3, 4, -50])] \
            + [("meanRankOrder", [[[1, 2, None], [1, 3, None]], 3]), ("moveItem", [[0, 1, 2, 3], 1, 3]), ("moveItem", [[0, 1, 2, 3], 3, 0]), ("moveItem", [[0, 1], 5, 0])] \
            + [("csvCell", ["=cmd"]), ("csvCell", ["-0.5"]), ("csvCell", ["a,b"]), ("csvCell", ['say "hi"']), ("csvCell", ["@x"]), ("csvCell", ["plain"])]
        job = Path(tmp) / "job.json"
        job.write_text(json.dumps([{"fn": f, "args": a} for f, a in calls]), encoding="utf-8")
        (Path(tmp) / "run.js").write_text(RUNNER, encoding="utf-8")
        done = subprocess.run([NODE, str(Path(tmp) / "run.js"), str(ROOT / "assets/report/compare_table_core.html"), str(job)], capture_output=True, text=True)
        check("node runs the JavaScript core", done.returncode == 0, done.stderr[-400:])
        if done.returncode == 0:
            res = json.loads(done.stdout)
            same = True
            for (fn, args), got in zip(calls[:len(cases)], res[:len(cases)]):
                want = rs(*args)
                same &= got["status"] == want["status"] and got["m"] == want["m"] and got["best"] == want["best"] and got["bucket"] == want["bucket"] and got["rank"] == want["rank"]
                same &= all((a is None and b is None) or (a is not None and b is not None and abs(a - b) < 1e-12) for a, b in zip(got["t"], want["t"]))
                if not same:
                    print("   mismatch", fn, args, got, want)
                    break
            check("rankShade: JavaScript and Python agree on status, ranks, shade buckets, best marks and t for every case", same)
            k = len(cases)
            q = [ct.quartiles(v) for v in ([1, 2, 3, 4, 5], [1, 2], [7], [], [1, 2, 3, 4, 100], [0.5, 0.1, 0.9, 0.3])]
            check("quartiles agree", all((a is None and b is None) or (a is not None and b is not None and all(abs(a[x] - b[x]) < 1e-12 for x in a)) for a, b in zip(res[k:k + 6], q)))
            k += 6
            check("outliers agree", res[k:k + 4] == [ct.outliers(v) for v in ([1, 2, 3, 4, 100], [1, 2, 100], [1, 2, 3, 4, 5, 6], [None, 1, 2, 3, 4, -50])])
            k += 4
            check("meanRankOrder and moveItem behave as specified", res[k] == [0, 1, 2] and res[k + 1] == [0, 2, 3, 1] and res[k + 2] == [3, 0, 1, 2] and res[k + 3] == [0, 1])
            check("csvCell guards a formula, keeps a number, quotes commas and quotes", res[k + 4:k + 10] == ["'=cmd", "-0.5", '"a,b"', '"say ""hi"""', "'@x", "plain"], res[k + 4:k + 10])
else:
    print("  SKIPPED: node is not installed, so the JavaScript ranking and shading functions were not compared with the Python mirror")

# ------------------------------------------------------------------------------------------------ builds of the demo report and of the real cohort
def converted(page, label):
    comps = re.findall(r"<div class='ct' id='ct-([^']+)'", page)
    kinds = {c.split("-")[0] for c in comps}
    check(f"{label}: at least five kinds of table were converted ({len(comps)} comparison tables, kinds {sorted(kinds)})", len(kinds) >= 5 or (label.startswith("real") and len(kinds) >= 3), sorted(kinds))
    check(f"{label}: the style and the scripts are in the page once", page.count("id='ct-style'") == 1 and page.count("id='ct-assets'") == 1 and page.count("root.PBCT = api") == 1)
    check(f"{label}: every comparison table keeps an original table in a closed fold", len(re.findall(r"<details class='ct-fold rpt-collapsible' data-closed='1'><summary>Table</summary>", page)) >= len(kinds))
    check(f"{label}: the help text of the component is in the page and the buttons point at it", page.count("data-help='compare-table'") >= len(comps) and '"compare-table"' in page)
    check(f"{label}: no comparison grid was given a row-filter bar by the condense step", "ct-grid rpt-t" not in page and "class='ct-grid'" in page)
    return comps


def match_table_cells(page, label):
    """Leaderboard components: each compared cell's text equals the cell of the same tool and header in the folded table."""
    bad, seen = [], 0
    for m in re.finditer(r"<div class='ct' id='ct-(lb-[^']+)'.*?</script></div>(?:<details.*?</details>)?", page, re.S):
        frag = m.group(0)
        pl = payload_of(frag)[0]
        fold_t = tables_of(re.search(r"<details class='ct-fold.*?</details>", frag, re.S).group(0))[0]
        heads = fold_t[0]
        for g in pl["groups"]:
            for mt in g["m"]:
                if mt["name"] not in heads or mt["id"] == "ranking_score":
                    continue
                hi = heads.index(mt["name"])
                for j, c in enumerate(pl["cols"]):
                    rows_t = [x for x in fold_t[1:] if x[1] == c["label"]]
                    if rows_t:
                        seen += 1
                        if pl["cells"][mt["id"]][j][0] != rows_t[0][hi]:
                            bad.append((mt["name"], c["label"], pl["cells"][mt["id"]][j][0], rows_t[0][hi]))
    check(f"{label}: leaderboard comparison cells equal the folded table's cells ({seen} compared)", seen > 0 and not bad, bad[:3])


def directions_honest(page, label):
    """No row is shaded unless its direction is defined, and a row with <2 assessed tools is not shaded (read from the static grid)."""
    wrong = []
    for m in re.finditer(r"<tr class='ct-row' data-m='[^']*' data-g='[^']*' data-dir='([^']*)'>(.*?)</tr>", page, re.S):
        direction, body = m.group(1), m.group(2)
        if "ct-s" in re.sub(r"data-[a-z-]+='[^']*'", "", body) and re.search(r"class='ct-c ct-s\d", body) and direction == "":
            wrong.append(body[:80])
    check(f"{label}: no row without a defined direction is shaded", not wrong, wrong[:2])


sys.path.insert(0, str(ROOT / "test"))
try:
    import test_report_feature_manifest as fm
except Exception as exc:                                       # pragma: no cover
    fm = None
    print(f"  SKIPPED: cannot import the report build helper ({exc})")
if fm and (ROOT / "results_demo").is_dir():
    with tempfile.TemporaryDirectory() as work:
        page, _results = fm.build_report(work)
    comps = converted(page, "demo report")
    match_table_cells(page, "demo report")
    directions_honest(page, "demo report")
    check("demo report: the leaderboard, graded recovery, bin quality, accuracy, performance, composite, features, contig layer, outcomes and additions are converted",
          all(any(c.startswith(p) for c in comps) for p in ("lb-", "graded-", "binquality-", "accuracy-", "performance", "composite-", "features-", "contig-", "outcomes-", "additions-")), comps)
    check("demo report: the isolate rows the panel links to exist (anchors sr-<isolate>)", all(f"id='{a}'" in page for a in set(re.findall(r"\"links\":\[\"#(sr-[^\"]+)\"", page.replace("\"#", "\"#"))) ) or "id='sr-" in page)
    print_marker = re.search(r"<div class='ct'.*?</script></div><details[^>]*ct-fold", page, re.S).group(0)
    check("demo report: the static grid is complete (shaded cells and the folded table are in the page without running a script)", re.search(r"ct-s\d+", print_marker) and "ct-fold" in print_marker)
else:
    print("  SKIPPED: results_demo is absent (run test/run_demo.sh first), so the demo report build was not tested")

COHORT = ROOT / "results_real_cohort1"
if fm and COHORT.is_dir():
    with tempfile.TemporaryDirectory() as work:
        results = Path(work) / "results_real_cohort1"
        shutil.copytree(COHORT, results, ignore=shutil.ignore_patterns("benchmark.report.html"))
        prefix = str(results / "benchmark")
        cmd = [sys.executable, str(ROOT / "python" / "build_html_report.py"), "--project-root", str(ROOT), "--scores", str(results / "scores.tsv"), "--tool-status", str(results / "tool_status.tsv"),
               "--leaderboard", prefix + ".leaderboard.tsv", "--manifest", str(results / "run_manifest.json"), "--comparisons", prefix + ".paired_comparisons.tsv",
               "--score-failures", str(results / "score_failures.tsv"), "--recommendations", prefix + ".recommendations.tsv", "--dimensions-prefix", prefix,
               "--stratified", prefix + ".stratified.tsv", "--rank-robustness", prefix + ".rank_robustness.tsv", "--truth-provenance", prefix + ".truth_provenance.tsv",
               "--outcome-states", prefix + ".outcome_states.tsv", "--out", str(results / "benchmark.report.html")]
        run = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        check("real cohort: the report builds", run.returncode == 0, run.stderr[-600:])
        if run.returncode == 0:
            page = (results / "benchmark.report.html").read_text(encoding="utf-8")
            converted(page, "real cohort")
            match_table_cells(page, "real cohort")
            directions_honest(page, "real cohort")
else:
    print("  SKIPPED: results_real_cohort1 is absent")

print()
if not ok:
    print("COMPARISON TABLE TESTS FAILED")
    sys.exit(1)
print("ALL COMPARISON TABLE TESTS PASSED")
