#!/usr/bin/env python3
"""The complexity-vs-performance figure (plan D3): rank correlation guards, truth-free/derived labelling, blanks never zero."""
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import report_fig_complexity as cx  # noqa: E402


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    print("the correlation")
    check("a perfect monotone relation gives +1", abs(cx.spearman([1, 2, 3, 4, 5], [0.1, 0.2, 0.5, 0.6, 0.9]) - 1) < 1e-9)
    check("a perfect inverse gives -1", abs(cx.spearman([1, 2, 3, 4, 5], [0.9, 0.7, 0.5, 0.2, 0.1]) + 1) < 1e-9)
    check("fewer than five isolates is not computed", cx.spearman([1, 2, 3, 4], [1, 2, 3, 4]) is None)
    check("no spread in either variable is not computed", cx.spearman([1, 1, 1, 1, 1], [1, 2, 3, 4, 5]) is None and cx.spearman([1, 2, 3, 4, 5], [0.5] * 5) is None)
    check("ties share the average rank", cx.ranks([3, 1, 3, 2]) == [3.5, 1.0, 3.5, 2.0], cx.ranks([3, 1, 3, 2]))
    print("the points")
    scores = [{"sample": "s1", "tool": "A", "f1": "0.9"}, {"sample": "s2", "tool": "A", "f1": ""}, {"sample": "s3", "tool": "A", "f1": "0.4"}]
    feats = {"s1": {"plasmid_count": "2"}, "s2": {"plasmid_count": "3"}, "s3": {"plasmid_count": ""}}
    pts = cx.points(scores, feats)
    track = next(iter(pts))
    check("an isolate with no F1 is not plotted as 0", [p[0] for p in pts[track]["A"]] == ["s1", "s3"])
    check("a blank characteristic is left out of that isolate, not made 0", pts[track]["A"][1][1] == {})
    print("the drawing")
    by_tool = {"A": [("s1", {"plasmid_count": 2.0, "contig_count": 10.0}, 0.9), ("s2", {"plasmid_count": 4.0}, 0.5)]}
    svg = cx.panel_svg("short_read", "plasmid_count", by_tool, {"A": "#000"})
    ET.fromstring(svg)
    check("the panel is well formed, has a point per measured pair and names its basis", svg.count("<circle") == 2 and "needs the reference: benchmark only" in svg)
    check("a truth-free characteristic says so", "knowable without a reference" in cx.panel_svg("short_read", "contig_count", by_tool, {"A": "#000"}))
    check("a characteristic nobody measured says not available", "Not available" in cx.panel_svg("short_read", "read_depth_x", by_tool, {"A": "#000"}))
    demo = ROOT / "results_demo" / "benchmark.report.html"
    if demo.is_file():
        page = demo.read_text(encoding="utf-8")
        check("the demo page carries the section", "id='fig-complexity'" in page and "Rank correlation of F1" in page)
    else:
        print("  SKIP: no results_demo report")
    print()
    if not ok:
        print("COMPLEXITY FIGURE TESTS FAILED")
        sys.exit(1)
    print("ALL COMPLEXITY FIGURE TESTS PASSED")


if __name__ == "__main__":
    main()
