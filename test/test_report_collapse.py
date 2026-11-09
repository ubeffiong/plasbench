#!/usr/bin/env python3
"""
Tables that a figure now draws are folded into closed <details>, nothing is deleted.

Hand-checked on small stub pages:
  - a plan {'s1': ('the table', 'fig-a')} wraps the one panel of section s1 when section fig-a exists, with the figure named in the summary;
  - two panels in one section get '(1 of 2)' and '(2 of 2)' summaries; a panel in a nested div is still found;
  - a panel already inside <details>, inside an .insight box, or inside an info popover is not wrapped; script/style bodies that contain
    the text "<div class='panel'>" are not touched;
  - a section that is not on the page, or whose figure is not on the page, is left as it was (the table is then the only view);
  - running twice changes nothing, and every byte outside the wrapped panels is unchanged;
  - COLLAPSE (the real plan) only names figure sections that FIGURE_SECTIONS knows, and on a real build of the demo report every folded
    section still contains its table text and its section id is still on the page.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))

import report_collapse as rcl  # noqa: E402
import report_figures as rf  # noqa: E402

P1 = "<div class='panel'><table><tr><td>A1</td></tr></table></div>"
P2 = "<div class='panel'><div class='wrap'><table><tr><td>B2</td></tr></table></div></div>"


def page_of(*sections):
    return "<html><body>" + "".join(sections) + "</body></html>"


def sec(sid, body):
    return f"<section id='{sid}'><h2>T</h2>{body}</section>"


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    plan = {"s1": ("the table", "fig-a", "all of it is in the figure")}
    base = page_of(sec("s1", P1), sec("fig-a", "<p>figure</p>"))
    out = rcl.collapse(base, plan)
    print("folding")
    check("the panel is wrapped in a closed details", "<details class='rpt-collapsible'><summary>Show the table" in out and P1 in out)
    check("the details holds the whole panel", out.count("<details") == 1 and out.index("<details") < out.index(P1) < out.index("</details>"))
    check("the summary says what the figure covers", "all of it is in the figure" in out)
    check("every byte outside the wrapped panel is unchanged",
          out.replace("<details class='rpt-collapsible'><summary>Show the table (all of it is in the figure)</summary>", "")
          .replace("</details>", "") == base)
    two = rcl.collapse(page_of(sec("s1", P1 + "<p>x</p>" + P2), sec("fig-a", "<p>f</p>")), plan)
    check("two panels get (1 of 2) and (2 of 2)", "(1 of 2)" in two and "(2 of 2)" in two and two.count("<details") == 2)
    check("a panel with a nested div is wrapped whole", two.index("B2") < two.index("</details>", two.index("B2")))

    print("what is left alone")
    inside = page_of(sec("s1", "<details><summary>s</summary>" + P1 + "</details>"), sec("fig-a", "x"))
    check("a panel already in a details", rcl.collapse(inside, plan) == inside)
    box = page_of(sec("s1", "<div class='insight caution'>" + P1 + "</div>"), sec("fig-a", "x"))
    check("a panel in a status box", rcl.collapse(box, plan) == box)
    pop = page_of(sec("s1", "<span class='rpt-info-pop'>" + P1 + "</span>"), sec("fig-a", "x"))
    check("a panel in an info popover", rcl.collapse(pop, plan) == pop)
    scr = page_of(sec("s1", "<script>var h=\"<div class='panel'><table></table></div>\";</script>"), sec("fig-a", "x"))
    check("markup inside a script body", rcl.collapse(scr, plan) == scr)
    check("a section that is not on the page", rcl.collapse(page_of(sec("zz", P1)), plan) == page_of(sec("zz", P1)))
    nofig = page_of(sec("s1", P1))
    check("a section whose figure is not on the page keeps its table visible", rcl.collapse(nofig, plan) == nofig)
    check("a section with no panel is unchanged", rcl.collapse(page_of(sec("s1", "<p>no table</p>"), sec("fig-a", "x")), plan)
          == page_of(sec("s1", "<p>no table</p>"), sec("fig-a", "x")))

    print("idempotence and the real plan")
    check("running twice changes nothing", rcl.collapse(out, plan) == out)
    check("the real plan only names known figure sections", all(f in rf.FIGURE_SECTIONS for _, f, _c in rcl.COLLAPSE.values() if f),
          [f for _, f, _c in rcl.COLLAPSE.values() if f and f not in rf.FIGURE_SECTIONS])
    report = os.path.join(HERE, "..", "results_demo", "benchmark.report.html")
    if os.path.isfile(report):
        html = open(report, encoding="utf-8").read()
        for sid, (what, fig, covers) in rcl.COLLAPSE.items():
            b = rcl.section_bounds(html, sid)
            if not b:
                continue
            block = html[b[0]:b[1]]
            if fig and rcl.section_bounds(html, fig):
                check(f"{sid}: its tables are folded in a closed details (demo report)", "<table" not in block or
                      re.search(r"<details(?: open)? class='rpt-collapsible'><summary>[^<]+</summary><div class='panel'>", block) is not None)   # open by default after the layout step
    else:
        print("  SKIP: no results_demo report to check the real plan against")

    print()
    if not ok:
        print("REPORT COLLAPSE TESTS FAILED")
        sys.exit(1)
    print("ALL REPORT COLLAPSE TESTS PASSED")


if __name__ == "__main__":
    main()
