#!/usr/bin/env python3
"""
Every section and tab of the report has a "?" help button that opens a plain-language explanation.

Hand-built page: a section with a heading, a container with a heading-less first tab and a tab with its own heading, a section with no entry, a tab with no entry.
  - the button is inside the first heading of a section and of a tab that has a heading; a tab without a heading gets an 'About this tab' row;
  - a section or tab without an entry gets no button and is listed by report_help.missing();
  - the help texts are in one JSON block ('</' escaped), the style and the script are added once, running twice changes nothing;
  - the button is a real button with an accessible name; the dialog is hidden in print.
Entries: all six parts are filled for every entry, in plain sentences (no entry is a bare word).
The demo report: every section and tab has an entry, every one has a button, and the JSON parses and holds the used entries.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import report_help as rh  # noqa: E402
import report_help_text as ht  # noqa: E402

ENTRIES = {
    "alpha": ht.H("Alpha shows a thing.", "Data A.", "How A.", "Read A </script>.", "Why A.", "Careful A."),
    "box": ht.H("Box groups tabs.", "Data B.", "How B.", "Read B.", "Why B.", "Careful B."),
    "box-main": ht.H("The first tab.", "Data M.", "How M.", "Read M.", "Why M.", "Careful M."),
    "second": ht.H("The second tab.", "Data S.", "How S.", "Read S.", "Why S.", "Careful S."),
}
PAGE = ("<html><body><main>"
        "<section id='alpha'><h2>Alpha<span class='rpt-info'><button class='rpt-info-btn'>i</button><span role='tooltip'>note</span></span></h2><p>x</p></section>"
        "<section id='box'><h2>Box</h2><div class='rpt-mtabs'><button aria-controls='box-main'>Main</button><button aria-controls='second'>Second</button></div>"
        "<div class='rpt-panel' id='box-main' data-tab='Main'><table><tr><th>a</th></tr></table></div>"
        "<div class='rpt-panel' id='second' data-tab='Second'><h3>Second heading</h3><p>y</p></div>"
        "<div class='rpt-panel' id='noentry' data-tab='No entry'><h3>No entry</h3></div></section>"
        "<section id='lonely'><h2>Lonely</h2></section>"
        "</main></body></html>")


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    print("the buttons")
    out = rh.transform(PAGE, ENTRIES)
    check("a section's button sits inside its first heading", re.search(r"<h2>Alpha.*?class='rpt-help-btn' data-help='alpha'.*?</h2>", out, re.S) is not None)
    check("the container's button sits in the container heading", re.search(r"<h2>Box<span class='rpt-help'><button[^>]*data-help='box'", out) is not None)
    check("a tab with a heading gets its button in that heading", re.search(r"<h3>Second heading<span class='rpt-help'><button[^>]*data-help='second'", out) is not None)
    check("a tab without a heading gets an 'About this tab' row", "<div class='rpt-help-row'><span class='rpt-help'><button" in out and "About this tab" in out
          and re.search(r"id='box-main'[^>]*><div class='rpt-help-row'>", out) is not None)
    check("a section and a tab without an entry get no button", "data-help='lonely'" not in out and "data-help='noentry'" not in out)
    check("report_help.missing lists them", sorted(rh.missing(PAGE, ENTRIES)) == ["lonely", "noentry"], rh.missing(PAGE, ENTRIES))
    check("the button is a real button with an accessible name", "type='button' class='rpt-help-btn'" in out and "aria-label='Help: about Alpha'" in out
          and "aria-haspopup='dialog'" in out)
    print("the data, style and script")
    m = re.search(r"<script type='application/json' id='rpt-help-data'>(.*?)</script>", out, re.S)
    check("one JSON block", m is not None and out.count("id='rpt-help-data'") == 1)
    data = json.loads(m.group(1).replace("<\\/", "</")) if m else {}
    check("it holds the used entries with their titles and all six fields", sorted(data.get("items", {})) == ["alpha", "box", "box-main", "second"]
          and data["items"]["alpha"]["title"] == "Alpha" and [f[0] for f in data["fields"]] == ["plain", "data", "how", "read", "why", "careful"])
    check("'</' inside a text cannot close the script", "</script>." not in m.group(1))
    check("the style and the dialog script are added once; the dialog is hidden in print",
          out.count("id='rpt-help-style'") == 1 and out.count("id=\"rpt-help-script\"") == 1 and "@media print{.rpt-help,.rpt-help-row,#rpt-help-dlg{display:none!important}}" in out)
    check("idempotent", rh.transform(out, ENTRIES) == out)
    check("a page with nothing to annotate is unchanged", rh.transform("<main><p>x</p></main>", ENTRIES) == "<main><p>x</p></main>")

    print("the entries")
    bad = [k for k, e in ht.HELP.items() if [f for f, _l in ht.FIELDS if len(e.get(f, "").strip()) < 12]]
    check("every entry fills all six parts with a sentence", not bad, bad)
    check("no part is a bare word like 'None.' or 'Optional.'", all(len(e[f].split()) >= 3 for e in ht.HELP.values() for f, _l in ht.FIELDS),
          [k for k, e in ht.HELP.items() if any(len(e[f].split()) < 3 for f, _l in ht.FIELDS)])

    print("the demo report")
    report = ROOT / "results_demo" / "benchmark.report.html"
    if not report.is_file():
        print("  SKIP: no results_demo report")
    else:
        text = report.read_text(encoding="utf-8")
        check("every section and tab has an entry", rh.missing(text) == [], rh.missing(text))
        sections_and_tabs = len(re.findall(r"<section id='", text)) + len(re.findall(r"<div class='rpt-panel' id='", text))
        buttons = len(re.findall(r"class='rpt-help-btn' data-help='", text))
        check("every section and tab has a button", buttons == sections_and_tabs, (buttons, sections_and_tabs))
        m = re.search(r"<script type='application/json' id='rpt-help-data'>(.*?)</script>", text, re.S)
        payload = json.loads(m.group(1).replace("<\\/", "</")) if m else {"items": {}}
        keys = set(re.findall(r"class='rpt-help-btn' data-help='([^']+)'", text))
        check("the JSON holds every button's entry", keys <= set(payload["items"]), sorted(keys - set(payload["items"])))

    print()
    if not ok:
        print("REPORT HELP TESTS FAILED")
        sys.exit(1)
    print("ALL REPORT HELP TESTS PASSED")


if __name__ == "__main__":
    main()
