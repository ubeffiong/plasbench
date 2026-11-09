#!/usr/bin/env python3
"""
Sub-tabs, windowed long tables and table typography condense the report without deleting anything.

Hand-checked on small stub sections:
  - a section with two or more direct-child <h3> subsections of >= 3 lines each (and >= 8 lines in all) gets a tab strip: role=tablist, one
    tab per h3 text, the first selected, the lead and status box kept above it, the strip hidden until the script runs (no-JS fallback is
    every subsection stacked with its heading); every original byte of the subsections sits inside the panels;
  - it is NOT tabbed with one subsection, with tiny subsections, with only one non-tiny subsection, with h3 inside cards (not direct children),
    with its own script, without an id, nor in the SKIP set (summary, fig-*, scorecard, plasmid-maps, contig-layer, recommender-eval,
    amr-placement, enterprise);
  - a table with more than 15 body rows is windowed (toolbar, data attribute, class rpt-t) and all rows stay in the markup; 15 rows is not;
    a table with rowspan, a nested table, a table in a popover or in a skipped section is left alone;
  - class rpt-num goes only on the columns whose body cells are all numbers (placeholders allowed), never in a table with colspan;
  - a page with nothing to condense comes back byte-identical, and running twice changes nothing;
  - the script's pure functions (node): the first 12 rows show, a query reveals a hidden match, 'show all' reveals all, rows hidden by
    another filter stay hidden and the window applies to the rest, sorting then windowing shows the first 12 of the NEW order,
    tab keys move and wrap;
  - on the real demo report: section ids and counts unchanged, no table row lost, every section's text intact.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "python"))

import report_condense as rc  # noqa: E402


def sec(sid, body, attrs=""):
    return f"<section id='{sid}'{attrs}><h2>Title</h2>{body}</section>"


def page_of(*sections):
    return "<html><head><title>t</title></head><body>" + "".join(sections) + "</body></html>"


def sub(title, n, tag="h3"):
    return f"<{tag}>{title}</{tag}>" + "".join(f"<p>{title} line {i}</p>" for i in range(1, n + 1))


def table(rows, cols=("Name", "Value"), values=None, head_extra=""):
    head = "".join(f"<th>{c}</th>" for c in cols)
    body = ""
    for i in range(rows):
        cells = "".join(f"<td>{(values(i, j) if values else (f'r{i}' if j == 0 else str(i * 10 + j)))}</td>" for j in range(len(cols)))
        body += f"<tr>{cells}</tr>"
    return f"<div class='panel'><table class='sortable'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


LEAD = "<p class='lead'>lead text</p><div class='insight'><p>status box</p></div>"
STYLE_MARK, SCRIPT_MARK = "id='rpt-condense-style'", "id='rpt-condense-script'"


def markup(out):
    """The page without the style and script this step adds."""
    out = re.sub(r"<style id='rpt-condense-style'>.*?</style>\n?", "", out, flags=re.S)
    return re.sub(r"<script id='rpt-condense-script'>.*?</script>\n?", "", out, flags=re.S)


def strip_added(out):
    """The page with everything this step adds removed again, to compare with the input byte for byte."""
    out = re.sub(r"<style id='rpt-condense-style'>.*?</style>\n?", "", out, flags=re.S)
    out = re.sub(r"<script id='rpt-condense-script'>.*?</script>\n?", "", out, flags=re.S)
    out = re.sub(r"<div class='rpt-tablist'.*?</div>", "", out, flags=re.S)
    out = re.sub(r"</div>(?=<div class='rpt-tabpanel')", "", out)
    out = re.sub(r"(<div class='rpt-tabs'.*?)</div></div></section>", lambda m: m.group(1) + "</section>", out, flags=re.S)
    out = re.sub(r"<div class='rpt-tabs'[^>]*>", "", out)
    out = re.sub(r"<div class='rpt-tabpanel'[^>]*>", "", out)
    out = re.sub(r"<div class='rpt-win-bar'.*?</div>", "", out, flags=re.S)
    out = re.sub(r" data-rpt-table='\d+'", "", out)
    def drop(m):
        rest = [c for c in m.group(3).split() if c not in ("rpt-t", "rpt-num")]
        return f"<{m.group(1)}{m.group(2)}" + (f" class='{' '.join(rest)}'" if rest else "")

    out = re.sub(r"<(table|td|th)(?=[ >])([^>]*?) class='([^']*)'", drop, out)
    return out


def node_run(script_body):
    node = shutil.which("node")
    if not node:
        return None
    frag = rc._fragment("condense_script.html")
    code = re.search(r"<script[^>]*>(.*)</script>", frag, re.S).group(1)
    harness = ("var window={};\n" + code + "\nvar C=window.__rptCondense;\nvar out={};\n" + script_body + "\nconsole.log(JSON.stringify(out));")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "t.js")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(harness)
        done = subprocess.run([node, path], capture_output=True, text=True, timeout=60)
    if done.returncode != 0:
        raise RuntimeError(done.stderr)
    return json.loads(done.stdout)


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    print("sub-tabs")
    body = LEAD + sub("Alpha", 4) + sub("Beta gamma", 4)
    base = page_of(sec("s1", body))
    out, st = rc.transform_with_stats(base)
    check("two non-tiny subsections are tabbed", st["sections_tabbed"] == 1 and st["tabs"] == 2 and "role='tablist'" in out, st)
    check("one tab per h3 text, in order", re.findall(r"role='tab'[^>]*>([^<]*)</button>", out) == ["Alpha", "Beta gamma"])
    check("the first tab is selected, the other is not", out.count("aria-selected='true'") == 1
          and re.search(r"aria-selected='true' tabindex='0'>Alpha<", out) is not None)
    check("tabs and panels are wired by id", "aria-controls='rpt-panel-s1-1'" in out and "id='rpt-panel-s1-2'" in out
          and "aria-labelledby='rpt-tab-s1-2'" in out)
    check("the tab strip is hidden until the script runs (no-JS shows every subsection)", re.search(r"role='tablist'[^>]*\shidden>", out) is not None
          and "hidden" not in re.search(r"<div class='rpt-tabpanel'[^>]*>", out).group(0))
    check("lead and status box stay above the tabs", out.index("status box") < out.index("class='rpt-tabs'"))
    check("every original byte is preserved inside the panels", strip_added(out) == base)
    a, b = body.index("<h3>Alpha"), body.index("<h3>Beta")
    check("each subsection is inside its panel verbatim", body[a:b] + "</div>" in out and body[b:] + "</div>" in out)
    check("style and script are added once", out.count(STYLE_MARK) == 1 and out.count(SCRIPT_MARK) == 1)
    check("print shows every panel and heading", "@media print" in out and ".rpt-tabpanel[hidden]{display:block!important}" in out)

    def same(label, page):
        res = rc.transform(page)
        check(label, res == page)

    same("one subsection is not tabbed", page_of(sec("s1", LEAD + sub("Only", 9))))
    same("tiny subsections stay stacked", page_of(sec("s1", sub("A", 2) + sub("B", 2) + sub("C", 2) + sub("D", 2))))
    same("one non-tiny subsection is not enough", page_of(sec("s1", sub("A", 7) + sub("B", 2))))
    same("h3 inside cards (not direct children) are not subsections",
         page_of(sec("s1", "<div class='term-grid'>" + "".join(f"<div class='card'>{sub(f'T{i}', 5)}</div>" for i in range(4)) + "</div>")))
    same("a section with its own script is not tabbed", page_of(sec("s1", sub("A", 4) + sub("B", 4) + "<script>var x=1;</script>")))
    same("a section with a canvas is not tabbed", page_of(sec("s1", sub("A", 4) + "<canvas></canvas>" + sub("B", 4))))
    same("a section without an id is not tabbed", page_of(f"<section><h2>T</h2>{sub('A', 4)}{sub('B', 4)}</section>"))
    for sid in ["summary", "scorecard", "plasmid-maps", "contig-layer", "recommender-eval", "amr-placement", "enterprise",
                "fig-heatmap", "fig-forest", "fig-ladder", "fig-landscape", "fig-distributions", "fig-pr"]:
        same(f"SKIP set: {sid}", page_of(sec(sid, sub("A", 4) + sub("B", 4) + table(20))))
    check("every SKIP entry carries a reason", all(isinstance(v, str) and len(v) > 10 for v in {**rc.SKIP_SECTIONS, **rc.SKIP_PREFIXES}.values()))
    pop = page_of(sec("s2", "<h3>Alpha<span class='rpt-info'><button>i</button><span role='tooltip' class='rpt-info-pop'>note</span></span></h3>"
                      + "<p>1</p><p>2</p><p>3</p><p>4</p>" + sub("Beta", 4)))
    check("an info popover in the heading is not part of the tab label",
          re.findall(r"role='tab'[^>]*>([^<]*)</button>", rc.transform(pop)) == ["Alpha", "Beta"])
    stay = rc.transform(page_of(sec("s3", sub("A", 4) + "<div class='insight caution'><p>box</p></div>" + sub("B", 4))))
    check("a status box between subsections stays in its panel", stay.index("rpt-tabpanel' id='rpt-panel-s3-1'") < stay.index("<p>box</p>") <
          stay.index("id='rpt-panel-s3-2'"))
    tables_in_tabs = rc.transform(page_of(sec("s4", sub("A", 1) + table(3) + "<p>x</p><p>y</p>" + sub("B", 1) + table(3) + "<p>x</p><p>y</p>")))
    check("small tables in tab panels get the typography class", tables_in_tabs.count("<table class='sortable rpt-t'>") == 2
          and "data-rpt-table" not in markup(tables_in_tabs))

    print("long tables")
    t20 = page_of(sec("s1", table(20)))
    out20, st20 = rc.transform_with_stats(t20)
    check("20 rows are windowed", st20["tables_windowed"] == 1 and "data-rpt-table='1'" in out20, st20)
    check("rows hidden by default = 20 - 12", st20["rows_hidden_default"] == 8, st20)
    check("all 20 rows stay in the markup", out20.count("<tr>") == 21 and strip_added(out20) == t20)
    check("the toolbar has a filter box, a show-all button and a readout",
          "type='search'" in out20 and ">Show all 20 rows</button>" in out20 and "rpt-win-n" in out20 and "data-rpt-bar='1'" in out20)
    m20 = markup(out20)
    check("the toolbar sits inside the panel (it folds with the table)", m20.index("rpt-win-bar") > m20.index("<div class='panel'>")
          and m20.index("rpt-win-bar") < m20.index("<table"))
    check("the toolbar is hidden without script", re.search(r"<div class='rpt-win-bar'[^>]*\shidden>", out20) is not None)
    check("windowing hides rows with a class, never the hidden attribute (page filters keep working)",
          "tr.rpt-wh{display:none}" in out20 and "rpt-wh" not in m20)
    check("print shows every row", "tr.rpt-wh:not([hidden]){display:table-row!important}" in out20)
    same("15 rows are not windowed", page_of(sec("s1", table(15))))
    check("16 rows are windowed", rc.transform_with_stats(page_of(sec("s1", table(16))))[1]["tables_windowed"] == 1)
    rowspan = page_of(sec("s1", "<div class='panel'><table><thead><tr><th>a</th><th>b</th></tr></thead><tbody><tr><td rowspan='2'>x</td><td>1</td></tr>"
                          + "<tr><td>2</td></tr>" * 20 + "</tbody></table></div>"))
    same("a table with rowspan is not windowed", rowspan)
    nested = page_of(sec("s1", "<div class='panel'><table><thead><tr><th>a</th></tr></thead><tbody><tr><td><table><tbody><tr><td>i</td></tr></tbody></table></td></tr>"
                         + "<tr><td>2</td></tr>" * 20 + "</tbody></table></div>"))
    same("a table with a nested table is not windowed", nested)
    same("a table in an info popover is left alone", page_of(sec("s1", "<span class='rpt-info-pop'>" + table(20) + "</span>")))
    same("a table in a skipped section is left alone", page_of(sec("fig-pr", table(40))))
    two = rc.transform_with_stats(page_of(sec("s1", table(20) + table(30))))
    check("two tables get their own numbers", "data-rpt-table='1'" in two[0] and "data-rpt-table='2'" in two[0] and two[1]["rows_hidden_default"] == 8 + 18)
    scripty = page_of(sec("s1", "<script>var h=\"<table><tbody>" + "<tr><td>1</td></tr>" * 30 + "</tbody></table>\";</script>"))
    same("markup inside a script body is not a table", scripty)

    print("numeric alignment")

    def cell(i, j):
        return ["name%d" % i, str(i + 1), ("-" if i % 2 else "%.2f" % (i / 3)), "x%d" % i, "1,234" if i % 2 == 0 else "5", "0.9 / 1", "12%"][j]

    num = rc.transform(page_of(sec("s1", table(20, cols=("A", "B", "C", "D", "E", "F", "G"), values=cell))))
    first_row = re.search(r"<tbody><tr>(.*?)</tr>", num, re.S).group(1)
    cells = re.findall(r"<td([^>]*)>", first_row)
    flags = ["rpt-num" in c for c in cells]
    check("numeric columns B, C (placeholders allowed), E, G are right-aligned; text and mixed columns are not",
          flags == [False, True, True, False, True, False, True], flags)
    heads = re.findall(r"<th(?=[ >])([^>]*)>", num)
    check("the header cell of a numeric column is aligned too", ["rpt-num" in h for h in heads] == flags)
    check("every body row carries the class on the same columns", len(re.findall(r"<td class='rpt-num'>", num)) == 20 * 4)
    colspan = rc.transform(page_of(sec("s1", "<div class='panel'><table><thead><tr><th>a</th><th>b</th></tr></thead><tbody>"
                                       + "<tr><td>1</td><td>2</td></tr>" * 19 + "<tr><td colspan='2'>none</td></tr></tbody></table></div>")))
    check("a table with colspan gets no numeric alignment", "rpt-num" not in markup(colspan) and "data-rpt-table" in colspan)
    check("parse_number: 1,234 / -3.5 / 12% / 2e3 are numbers; '-', 'n/a', '1 kb', '0.9 / 1' are not",
          [rc.parse_number(x) for x in ["1,234", "-3.5", "12%", "2e3"]] == [1234.0, -3.5, 12.0, 2000.0]
          and all(rc.parse_number(x) is None for x in ["-", "n/a", "1 kb", "0.9 / 1", "", "abc"]))

    print("unchanged pages and idempotence")
    plain = page_of(sec("s1", LEAD + "<p>nothing</p>" + table(5)))
    check("a page with nothing to condense is unchanged (no style, no script)", rc.transform(plain) == plain)
    for label, page in (("tabs", base), ("tables", t20), ("both", page_of(sec("s1", body + table(20))))):
        once = rc.transform(page)
        check(f"running twice changes nothing ({label})", rc.transform(once) == once)

    print("script (node)")
    if not shutil.which("node"):
        print("  SKIP: node is not installed")
    else:
        res = node_run("""
var rows = []; for (var i = 0; i < 20; i++) rows.push({off: false, text: 'Row ' + i + (i === 15 ? ' needle' : '')});
var r0 = C.windowRows(rows, {limit: 12, expanded: false, query: ''});
out.first = r0.show.filter(Boolean).length; out.firstIdx = r0.show.indexOf(false); out.s0 = [r0.shown, r0.eligible, r0.total];
var rq = C.windowRows(rows, {limit: 12, expanded: false, query: 'NEEDLE'});
out.q = rq.show.map(function (v, i) { return v ? i : -1; }).filter(function (v) { return v >= 0; }); out.qn = [rq.shown, rq.matched];
var rq2 = C.windowRows(rows, {limit: 12, expanded: false, query: 'row 1'});
out.q2 = rq2.shown;                       // Row 1, Row 10..19 = 11 matches, all shown although > 12 would be windowed
var ra = C.windowRows(rows, {limit: 12, expanded: true, query: ''});
out.all = ra.show.every(Boolean);
var off = rows.map(function (r, i) { return {off: i < 5, text: r.text}; });
var ro = C.windowRows(off, {limit: 12, expanded: false, query: ''});
out.off = [ro.show.indexOf(true), ro.show.lastIndexOf(true), ro.shown, ro.eligible];
var sorted = rows.slice().reverse();          // what the page's sort does: reorder every row, then the window applies to the new order
var rs = C.windowRows(sorted, {limit: 12, expanded: false, query: ''});
out.sorted = sorted.filter(function (r, i) { return rs.show[i]; }).map(function (r) { return r.text.split(' ')[1]; });
out.keys = [C.nextTab(0, 4, 'ArrowRight'), C.nextTab(3, 4, 'ArrowRight'), C.nextTab(0, 4, 'ArrowLeft'), C.nextTab(2, 4, 'ArrowLeft'),
            C.nextTab(2, 4, 'Home'), C.nextTab(1, 4, 'End'), C.nextTab(1, 4, 'Tab'), C.nextTab(1, 4, 'a')];
out.limit = C.LIMIT;
""")
        check("12 rows show by default, the 13th is the first hidden", res["first"] == 12 and res["firstIdx"] == 12 and res["s0"] == [12, 20, 20], res)
        check("a query reveals a hidden matching row (and only it)", res["q"] == [15] and res["qn"] == [1, 1], res)
        check("a query lifts the cap on its matches", res["q2"] == 11, res)
        check("'show all' reveals every row", res["all"] is True)
        check("rows hidden by another filter stay hidden; the window applies to the rows that pass", res["off"] == [5, 16, 12, 15], res)
        check("sort then window: the first 12 of the new order show", res["sorted"] == [str(i) for i in range(19, 7, -1)], res)
        check("tab keys: right/left wrap, Home/End jump, others do nothing", res["keys"] == [1, 0, 3, 1, 0, 3, -1, -1], res)

    print("real demo report")
    report = os.path.join(ROOT, "results_demo", "benchmark.report.html")
    if not os.path.isfile(report):
        print("  SKIP: no results_demo report")
    else:
        html = open(report, encoding="utf-8").read()
        out_real, stats = rc.transform_with_stats(html)

        def ids(p):
            return re.findall(r"<section id='([^']+)'", p)

        def rows(p):
            return len(re.findall(r"<tr[ >]", p))

        check("section ids and their count are unchanged", ids(out_real) == ids(html), (len(ids(html)), len(ids(out_real))))
        check("no table row is lost", rows(out_real) == rows(html) and out_real.count("<table") == html.count("<table"), (rows(html), rows(out_real)))
        check("every section's text is intact once the added markup is removed (an empty class attribute aside)",
              strip_added(out_real).replace(" class=''", "") == strip_added(html).replace(" class=''", ""))   # the demo report was condensed once already by the build: compare both sides stripped
        check("something was condensed on the demo", stats["tables_windowed"] > 0 and stats["rows_hidden_default"] > 0, stats)
        check("the real transform is idempotent", rc.transform(out_real) == out_real)
        check("skipped sections' tables are not windowed", all(
            "data-rpt-table" not in out_real[m.start():out_real.find("</section>", m.start())]
            for m in re.finditer(r"<section id='(?:fig-[a-z]+|plasmid-maps|contig-layer|amr-placement|enterprise|summary)'", out_real)))
        print(f"  info: demo stats {stats}")

    print()
    if not ok:
        print("REPORT CONDENSE TESTS FAILED")
        sys.exit(1)
    print("ALL REPORT CONDENSE TESTS PASSED")


if __name__ == "__main__":
    main()
