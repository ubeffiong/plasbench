#!/usr/bin/env python3
"""
The isolate filter and the plasmid-by-tool matrix (python/report_isolates.py).

Hand-computed on small per-plasmid fixtures (completeness values chosen so every class and tie case occurs):
  isolate s1, plasmid pA (100 kb): toolA 1.00, toolB 0.95, toolC 0.40  -> toolA and toolB are recovered (>= 0.90), toolC is a cross;
                                                                          the best tool is toolA alone (1.00 > 0.95)
  isolate s1, plasmid pB (5 kb):   toolA 0.60, toolB 0.60, toolC 0.60  -> half circles, every tool ties: "all 3 tools tie"
  isolate s2, plasmid pC (8 kb):   toolA 1.00, toolB 1.00, toolC missing -> toolC has no result (a dash); toolA and toolB tie
  matrix footer: recovered = toolA 2 of 3, toolB 2 of 3, toolC 0 of 3; best on = toolA 3 (pA alone, the pB tie, the pC tie), toolB 2 (pB, pC), toolC 1 (pB)
  a second analysis track gets its own table (never pooled)
  no rows at all -> a visible 'Not run', never a blank
  humanise() replaces whole tool ids in text only, not inside attributes, and not part of a longer name
  the report-card rows for one isolate come from the same report_cards() the cohort card uses (stubbed here), sorted best first
  inject(): a second call changes nothing; a page without the report-card slot is returned unchanged; tables in templates are never windowed
  or folded by the condense and collapse steps.
"""
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))

import report_collapse as rcl  # noqa: E402
import report_condense as rcd  # noqa: E402
import report_isolates as ri  # noqa: E402


def row(sample, plasmid, tool, completeness, length="1000", track="short_read", outcome=""):
    return {"sample": sample, "plasmid": plasmid, "tool": tool, "track": track, "length": length, "completeness": completeness,
            "recovered": "", "outcome": outcome}


ROWS = [row("s1", "pA", "toolA", "1.0000", "100000"), row("s1", "pA", "toolB", "0.9500", "100000"), row("s1", "pA", "toolC", "0.4000", "100000"),
        row("s1", "pB", "toolA", "0.6000", "5000"), row("s1", "pB", "toolB", "0.6000", "5000"), row("s1", "pB", "toolC", "0.6000", "5000"),
        row("s2", "pC", "toolA", "1.0000", "8000"), row("s2", "pC", "toolB", "1.0000", "8000")]


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    html = ri.matrix_html(ROWS, lambda t: t.upper())
    cells = re.findall(r"<td class='pb-c (pb-[a-z]+)'", html)
    print("the matrix")
    check("nine cells: 8 results and one missing", len(cells) == 9, len(cells))
    check("classes: recovered, recovered, missed | partly x3 | recovered, recovered, none",
          cells == ["pb-good", "pb-good", "pb-miss", "pb-part", "pb-part", "pb-part", "pb-good", "pb-good", "pb-none"], cells)
    check("a tick, half circle, cross and dash are printed as well as the number", all(g in html for g in ("✓", "◐", "✕", "–")))
    check("tool columns use the reader-facing label", "<th>TOOLA</th>" in html and "<th>TOOLC</th>" in html)
    found = re.findall(r"<tr><td>(s\d)</td><td><strong>(p[A-C])</strong>.*?<td>([^<]*)</td></tr>", html)
    best = {p: b for _s, p, b in found}
    check("best tool for pA is TOOLA alone (1.00 beats 0.95)", best.get("pA") == "TOOLA", best)
    check("a tie of every tool that has a result says so", best.get("pB") == "all 3 tools tie", best)
    check("a tie of the tools that have a result lists them", best.get("pC") == "TOOLA, TOOLB (tie)", best)
    foot = html[html.index("<tfoot>"):]
    check("recovered counts (at least 90%): TOOLA 2 of 3, TOOLB 2 of 3, TOOLC 0 of 3",
          re.findall(r"<td><strong>(\d)</strong> of 3</td>", foot) == ["2", "2", "0"], foot[:300])
    check("best-on counts: TOOLA 3, TOOLB 2, TOOLC 1", re.findall(r"<td>(\d)</td>", foot) == ["3", "2", "1"], re.findall(r"<td>(\d)</td>", foot))
    check("the stars sit on the best tools only (1 + 3 + 2)", html.count("class='pb-star'") == 1 + 3 + 2, html.count("class='pb-star'"))
    check("every cell carries its meaning in text for screen readers and a tooltip",
          html.count("class='rpt-sr'") >= 9 and "title='pA in s1: TOOLA covered 100%" in html)
    check("well-formed XML", ET.fromstring("<r>" + html.replace("&", "&amp;") + "</r>") is not None)
    two = ri.matrix_html(ROWS + [row("s1", "pA", "toolD", "0.5", track="long_read")], str)
    check("a second analysis track gets its own table", two.count("<h4>Analysis track:") == 2 and "long_read" in two)
    check("no rows gives a visible Not run note", "Not run" in ri.matrix_html([], str))

    print("helpers")
    check("humanise replaces whole ids in text only", ri.humanise("<td title='toolA'>toolA and toolAB</td>", {"toolA": "Tool A"}) == "<td title='toolA'>Tool A and toolAB</td>")
    check("humanise with no labels is a no-op", ri.humanise("<td>x</td>", {}) == "<td>x</td>")

    def fake_cards(leaderboard, scores):
        return [{"tool": r["tool"], "grade": "A", "composite": float(r["mean_f1"] or 0), "parts": {}, "measured": 1.0} for r in leaderboard]
    scores = [{"sample": "s1", "tool": "toolA", "f1": "0.5", "plasmid_recall": "1"}, {"sample": "s1", "tool": "toolB", "f1": "0.9", "plasmid_recall": "1"},
              {"sample": "s2", "tool": "toolA", "f1": "0.1", "plasmid_recall": "0"}]
    status = [{"sample": "s1", "tool": "toolB", "status": "failed"}]
    cards = ri.isolate_report_cards(fake_cards, scores, status, "s1")
    check("report cards for one isolate: only that isolate's rows, best first", [c["tool"] for c in cards] == ["toolB", "toolA"], cards)

    print("injection")
    bare = "<html><body><section id='summary'></section></body></html>"
    check("a page without the report-card slot is returned unchanged", ri.inject(bare, ".", None, None) == bare)
    marked = ("<html><head></head><body><main><section id='summary'><span id='pb-iso-data'></span><h3>Report card</h3>"
              "<table><tbody data-iso-slot='summary-card'><tr><td>row</td></tr></tbody></table></section></main></body></html>")
    check("a second inject changes nothing", ri.inject(marked, ".", None, None, report_cards=fake_cards, grade_rows_html=lambda c: "") == marked)

    print("templates are never windowed or folded")
    rows30 = "".join(f"<tr><td>{i}</td></tr>" for i in range(30))
    big = "<section id='s1x'><template data-iso-for='s1' data-iso-slot='x'><div class='panel'><table><tbody>" + rows30 + "</tbody></table></div></template></section>"
    page_big = "<html><head></head><body>" + big + "</body></html>"
    check("condense leaves a long table inside a template alone", rcd.transform(page_big).count("rpt-wh") == 0)
    check("collapse leaves a panel inside a template alone", rcl.collapse(page_big, {"s1x": ("the table", "", "")}) == page_big)

    print("the real demo report")
    report = os.path.join(HERE, "..", "results_demo", "benchmark.report.html")
    if not os.path.isfile(report):
        print("  SKIP: no results_demo report")
    else:
        text = open(report, encoding="utf-8").read()
        isolates = sorted(set(re.findall(r"<template data-iso-for='([^']+)' data-iso-slot=", text)))
        check("one template per isolate and slot (6 isolates x 4 slots)", len(isolates) == 6 and text.count("<template data-iso-for=") == 24,
              (len(isolates), text.count("<template data-iso-for=")))
        matrix = text[text.index("id='summary-plasmids'"):text.index("<h3>Report card")]
        check("the cohort matrix has one row per truth plasmid (11)", len(re.findall(r"<td><strong>p[A-Z]</strong>", matrix)) == 11)
        check("a per-isolate template does not carry window markers that would hide rows",
              "rpt-wh" not in "".join(re.findall(r"<template data-iso-for.*?</template>", text, re.S)))
        check("the scope label sits on the four views", text.count("data-iso-scope>All isolates") >= 4)
        check("the control payload lists every isolate", len(re.findall(r'"id": "[a-z_]+"', text[text.index("id='pb-iso-data'"):][:600])) == 6)
        check("the top bar has the slot the control mounts into", "id='rpt-isolate-slot'" in text)
        check("the run line is not repeated under the title", "<p class='rpt-runline'>" not in text)

    print()
    if not ok:
        print("REPORT ISOLATES TESTS FAILED")
        sys.exit(1)
    print("ALL REPORT ISOLATES TESTS PASSED")


if __name__ == "__main__":
    main()
