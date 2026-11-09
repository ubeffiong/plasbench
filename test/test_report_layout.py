#!/usr/bin/env python3
"""
Tests for python/report_layout.py: the page shell (top bar, left rail), the views and their order, accordion cards with status chips,
byte-for-byte preservation of every section, idempotence, and the print form. Hand-computed on small stub pages, then run on the real demo
page when results_demo/benchmark.report.html exists (a pure transform of it; no rebuild).

The browser behaviour (routing, rail, search, keyboard, widgets re-fitting when a view is first shown) and the PDF are checked by
test_report_pdf.py and by the headless-browser checks listed in the pull request.
"""
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "python"))
import report_layout as rl  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("  ok: " if cond else "  FAIL: ") + name + ("" if cond else f"  {detail}"))
    ok = ok and bool(cond)


def section(sid, title="", body=""):
    return f"<section id='{sid}'><h2>{title or sid + ' title'}</h2>{body}</section>"


def stub(ids, bodies=None, gap=None, header=True):
    bodies = bodies or {}
    nav = "".join(f"<a href='#{i}'>{i} label</a>" for i in ids)
    secs = "".join(section(i, body=bodies.get(i, "")) + ((gap or "") if k == 0 else "") for k, i in enumerate(ids))
    head = ("<header><p class=\"eyebrow\">Benchmarking plasmid tools.</p><h1>The Report Title</h1>"
            "<p><strong>Run:</strong> demo · cohort c1 · generated 2026-01-01 · offline</p></header>") if header else ""
    kpis = "<div class='metrics'><div class='metric'><small>Samples observed</small><strong>6</strong></div></div>"
    return (f"<!doctype html><html><head><title>t</title><style>body{{margin:0}}</style></head><body>{head}"
            f"<main><nav class='nav'>{nav}</nav>{kpis}{secs}<footer>foot</footer></main><script>var x=1;</script></body></html>")


def sections_of(page):
    return {sid: page[a:b] for sid, a, b in rl.find_sections(page)}


def main():
    print("plan")
    ids = ["files", "method", "summary", "fig-pr", "mystery", "scores", "health", "scorecard", "recommendations", "plasmid-maps", "zzz-other"]
    plan = rl.layout_plan(ids)
    flat = [i for _v, m in plan for i in m]
    check("every id is in exactly one view, once", sorted(flat) == sorted(ids) and len(flat) == len(set(flat)), flat)
    check("views come in the story order, More last",
          [v[0] for v, _m in plan] == ["overview", "scorecard", "figures", "maps", "diagnostics", "quality", "recommendation", "methods", "appendix", "more"],
          [v[0] for v, _m in plan])
    by = {v[0]: m for v, m in plan}
    check("unknown ids land in More, in document order", by["more"] == ["mystery", "zzz-other"], by["more"])
    check("ids known to a view land in it", by["diagnostics"] == ["scores"] and by["quality"] == ["health"] and by["maps"] == ["plasmid-maps"])
    all_ids = [i for v in rl.VIEWS for i in v[6].split()]
    check("the view table lists no id twice", len(all_ids) == len(set(all_ids)), [i for i in all_ids if all_ids.count(i) > 1])
    check("a view with no section is left out", "figures" in by and "recommendation" in by and
          "methods" in by and rl.layout_plan(["summary"])[0][0][0] == "overview" and len(rl.layout_plan(["summary"])) == 1)
    order_in = rl.layout_plan(["leaderboard", "summary", "robustness", "insights", "chart", "metadata"])[0][1]
    check("the order inside a view is the defined order, not the document order",
          order_in == ["summary", "insights", "leaderboard", "chart", "robustness", "metadata"], order_in)
    check("story order of the first sections: headline -> scorecard -> figures -> maps -> diagnostics -> quality -> recommendation -> methods -> appendix",
          [v[0] for v in rl.VIEWS] == ["overview", "scorecard", "figures", "maps", "diagnostics", "quality", "recommendation", "methods", "appendix"])

    print("status chips")
    rows2 = "<div class='panel'><table><thead><tr><th>a</th></tr></thead><tbody><tr><td>1</td></tr><tr><td>2</td></tr></tbody></table></div>"
    check("two data rows -> '2 rows' (the header row is not counted)", rl.status_chips(section("x", body=rows2)) == [("2 rows", "neutral")],
          rl.status_chips(section("x", body=rows2)))
    one = rows2.replace("<tr><td>2</td></tr>", "")
    check("one row is singular", rl.status_chips(section("x", body=one))[0][0] == "1 row")
    nr = "<div class='insight caution'><p><strong>Not run:</strong> the step did not run.</p></div>"
    check("a Not run notice -> 'Not run' (muted), and that caution box is not also a flag",
          rl.status_chips(section("x", body=nr)) == [("Not run", "muted")], rl.status_chips(section("x", body=nr)))
    flag = "<div class='insight caution'><p>One sample is an outlier.</p></div>"
    check("a caution box -> '1 flag'", ("1 flag", "warn") in rl.status_chips(section("x", body=flag + rows2)))
    check("two flags are plural", ("2 flags", "warn") in rl.status_chips(section("x", body=flag + flag)))
    empty = "<div class='panel'><table><thead><tr><th>a</th></tr></thead><tbody><tr><td colspan='7'>No flags were found.</td></tr></tbody></table></div>"
    check("a single colspan 'No ...' row is an empty state, not a row", rl.status_chips(section("x", body=empty)) == [("no data", "muted")],
          rl.status_chips(section("x", body=empty)))
    pill = "<span class='rpt-band rpt-band-excellent'><span aria-hidden='true'>●</span> pass</span>"
    tbl = "<div class='panel'><table><tbody><tr><td>s1</td><td>" + pill + "</td></tr><tr><td>s2</td><td>" + pill + "</td></tr></tbody></table></div>"
    chips = rl.status_chips(section("x", body=tbl))
    check("every pass pill -> 'all pass' (ok) with the row count", chips == [("all pass", "ok"), ("2 rows", "neutral")], chips)
    failp = tbl.replace("pass</span></td></tr></tbody>", "fail</span></td></tr></tbody>")
    check("a fail pill -> '1 fail' and no 'all pass'", ("1 fail", "warn") in rl.status_chips(section("x", body=failp))
          and ("all pass", "ok") not in rl.status_chips(section("x", body=failp)), rl.status_chips(section("x", body=failp)))
    st = "<table><tbody><tr><td><span class='status failed'>failed</span></td></tr><tr><td><span class='status completed'>completed</span></td></tr></tbody></table>"
    check("failed run labels are counted", ("1 failed", "warn") in rl.status_chips(section("x", body=st)))
    check("a section that draws an SVG says 'figure'", rl.status_chips(section("x", body="<svg><rect/></svg>"))[0] == ("figure", "neutral"))
    check("a text-only section says 'text'", rl.status_chips(section("x", body="<p>words</p>")) == [("text", "neutral")])
    check("a Not run text inside a script is ignored", rl.status_chips(section("x", body="<script>var a='Not run';</script><p>fine</p>")) == [("text", "neutral")])

    print("transform on a stub page")
    ids = ["files", "scores", "summary", "health", "method", "fig-pr", "recommendations", "scorecard", "mystery"]
    bodies = {"health": rows2, "scores": rows2}
    page = stub(ids, bodies, gap="<style>.gap{color:red}</style>")
    out = rl.transform(page)
    before, after = sections_of(page), sections_of(out)
    check("every section appears exactly once", sorted(after) == sorted(ids) and len(rl.find_sections(out)) == len(ids))
    check("every section block is kept byte for byte", all(after[i] == before[i] for i in ids), [i for i in ids if after[i] != before[i]])
    check("the style block between sections travels with the section before it", "</section><style>.gap{color:red}</style>" in out and out.count(".gap{color:red}") == 1)
    secs_in_order = [sid for sid, _a, _b in rl.find_sections(out)]
    check("sections are in the story order", secs_in_order == [i for _v, m in rl.layout_plan(ids) for i in m], secs_in_order)
    rail = out[out.index("<nav class='rpt-rail'"):out.index("</nav>", out.index("<nav class='rpt-rail'"))]
    views = re.findall(r"data-view='([a-z]+)'><a", rail)
    check("the rail lists each view once, in story order", views == [v[0] for v, _m in rl.layout_plan(ids)], views)
    counts = dict(re.findall(r"href='#view-([a-z]+)'.*?<span class='rpt-rail-count'[^>]*>(\d+)</span>", rail))
    check("the rail shows the right section count per view", counts == {v[0]: str(len(m)) for v, m in rl.layout_plan(ids)}, counts)
    links = [i for i in re.findall(r"href='#([a-z-]+)'", rail) if not i.startswith("view-")]
    check("the rail links every section once, in document order", links == secs_in_order, links)
    check("the rail carries the label of the old nav link", ">files label<" in rail)
    check("the old flat nav is gone", "<nav class='nav'" not in out)
    check("the title band carries the title, the run line and the KPI chip",
          "<h1>The Report Title</h1>" in out and "<strong>Run:</strong> demo" in out and "<small>Samples observed</small><strong>6</strong>" in out
          and out.count("class='metrics'") == 1)
    check("the old dark <header> is replaced", "<header>" not in out)
    check("the top bar names the run", "<span class='rpt-top-run' title='demo · cohort c1'>" in out)
    check("search, palette, expand and print controls exist", all(x in out for x in ("id='rpt-q'", "id='pb-cvd'", "id='rpt-expand'", "id='pb-print'")))
    check("the first view is the active one and no view is hidden without JavaScript",
          out.count("rpt-view rpt-active") == 1 and not re.search(r"class='rpt-view[^']*'[^>]*hidden", out) and "html.pb-js:not(.pb-printmode) .rpt-view{display:none}" in out)
    check("the page keeps its own scripts and footer", "<script>var x=1;</script>" in out and "<footer>foot</footer>" in out)
    check("the layout script, print stylesheet and per-view named pages are added once",
          out.count("id=\"rpt-layout-script\"") == 1 and out.count("id=\"rpt-layout-print\"") == 1 and "@page pv-overview" in out)
    check("the layout script routes #view-x and #section-id and fires pb-view-shown", "view-" in out and "pb-view-shown" in out and "hashchange" in out)
    check("the print stylesheet shows every view and opens details",
          "@media print" in out and ".rpt-view{break-before:page" in out and "details:not([open])" in out and "A4 landscape" in out)
    check("the rail position is remembered in localStorage inside try/catch", "pb-rail" in out and "try{" in out)
    check("the shell wraps the whole page and closes after </main>", out.count("<div class='rpt-shell'>") == 1 and "</main></div>" in out)
    check("the shell is closed before the layout script, which follows it", out.index("</main></div>") < out.index("id=\"rpt-layout-script\""))

    print("cards and chips in the page")
    quality = out[out.index("id='view-quality'"):]
    quality = quality[:quality.index("id='view-recommendation'")] if "id='view-recommendation'" in quality else quality
    check("the Data quality view is an accordion of closed cards", "<details class='rpt-card' data-card='health'>" in quality)
    check("the card carries the section title and its chip", "<summary><span class='rpt-card-title'>health label</span>" in quality
          and "<span class='rpt-chip rpt-chip-neutral'>2 rows</span>" in quality, quality[:600])
    check("a card wraps its section whole", "<div class='rpt-card-body'><section id='health'>" in quality)
    ov = out[out.index("id='view-overview'"):out.index("id='view-scorecard'")]
    check("the Overview view stacks its sections (no cards)", "rpt-card" not in ov and "<section id='summary'>" in ov)
    check("cards that start open are the ones named in OPEN_CARDS", "data-card='method' open" not in out and "data-card='fig-pr'" in out)

    print("invariants")
    check("running it twice changes nothing", rl.transform(out) == out)
    plain = "<html><body><main><p>no sections</p></main></body></html>"
    check("a page without sections is returned unchanged", rl.transform(plain) == plain)
    nohead = "<style>a{}</style><main>" + section("summary") + section("zzz") + "</main>"
    o2 = rl.transform(nohead)
    check("a page with no header, nav or metrics still lays out", "rpt-rail" in o2 and "id='view-more'" in o2 and sorted(sections_of(o2)) == ["summary", "zzz"])
    check("a heading with an info popover gives a clean label", rl.heading_html(
        "<section id='a'><h2>Title<span class='rpt-info'><button>i</button><span role='tooltip'>a long note</span></span></h2></section>") == "Title")
    nested = "<main>" + "<section id='a'><h2>A</h2><section id='inner'><h2>I</h2></section></section>" + "</main>"
    check("a nested section stays inside its parent", [s for s, _a, _b in rl.find_sections(nested)] == ["a"])
    script_sec = "<main><section id='a'><script>var s=\"</section>\";</script><p>x</p></section><section id='b'></section></main>"
    check("a </section> inside a script does not end the section", [s for s, _a, _b in rl.find_sections(script_sec)] == ["a", "b"])

    print("the demo page (a pure transform of results_demo/benchmark.report.html)")
    demo = os.path.join(ROOT, "results_demo", "benchmark.report.html")
    if not os.path.isfile(demo):
        print("  SKIPPED: results_demo/benchmark.report.html not found")
    else:
        with open(demo, encoding="utf-8") as handle:
            raw = handle.read()
        if "rpt-shell" in raw:
            raw_before = sections_of(raw)
            laid = raw
        else:
            raw_before = sections_of(raw)
            laid = rl.transform(raw)
        after = sections_of(laid)
        found_ids = [s for s, _a, _b in rl.find_sections(laid)]
        check("every demo section id is on the laid-out page exactly once", sorted(found_ids) == sorted(raw_before) and len(found_ids) == len(set(found_ids)),
              set(raw_before) ^ set(found_ids))
        check("every demo section is byte for byte what it was", all(after[i] == raw_before[i] for i in raw_before))
        known = {i for v in rl.VIEWS for i in v[6].split()}
        check("no demo section falls into More", not [i for i in raw_before if i not in known], [i for i in raw_before if i not in known])
        check("laying the demo page out twice changes nothing", rl.transform(laid) == laid)
        rail = laid[laid.index("<nav class='rpt-rail'"):laid.index("</nav>", laid.index("<nav class='rpt-rail'"))]
        check("the demo rail has nine views and every section once",
              len(re.findall(r"data-view='", rail)) == 9 and len([i for i in re.findall(r"href='#([a-z-]+)'", rail) if not i.startswith("view-")]) == len(raw_before))
        check("the demo's views: Overview, Scorecard, Figures, Plasmid maps, Diagnostics, Data quality, Recommendation, Methods and limits, Appendix",
              re.findall(r"class='rpt-view-title' role='heading' aria-level='2'>([^<]+)<", laid) ==
              ["Overview", "Scorecard", "Figures", "Plasmid maps", "Statistical diagnostics", "Data quality", "Recommendation", "Methods and limits", "Appendix"])

    print()
    if not ok:
        print("REPORT LAYOUT TESTS FAILED")
        sys.exit(1)
    print("ALL REPORT LAYOUT TESTS PASSED")


if __name__ == "__main__":
    main()
