#!/usr/bin/env python3
"""The radar fingerprint (plan D2): axes come from the registry and the heatmap's own columns, a blank is never zero, and the figure is on the demo page."""
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import report_fig_radar as rd  # noqa: E402


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    rd.validate()
    check("every axis names a registry metric", True)
    cols = {c["id"]: c for c in rd.hm._columns(rd.hm.rs.load_config())}
    check("every axis is a column of the heatmap", all(col in cols for _l, col, _m, _i in rd.AXES), [c for _l, c, _m, _i in rd.AXES if c not in cols])
    print("the transform")
    check("a fraction is drawn as it is", rd.axis_value([0.8, None, None, "", 3], cols["F1"], False) == 0.8)
    check("a blank is not available, never 0", rd.axis_value([None, None, None, "x", 0], cols["F1"], False) is None)
    check("the unmapped share is inverted so further out is better", abs(rd.axis_value([0.25, None, None, "", 3], cols["UNM"], True) - 0.75) < 1e-9)
    check("runtime is its scorecard score over 100", rd.axis_value([120, 70.0, "good", "", 3], cols["E1"], False) == 0.7)
    check("runtime with no score is not available", rd.axis_value([120, None, None, "", 3], cols["E1"], False) is None)
    print("the drawing")
    block = {"track": "short_read", "rows": [{"label": "A"}, {"label": "B"}],
             "cells": [[[0.9, None, None, "", 1]] * len(cols), [[None, None, None, "x", 0]] * len(cols)]}
    html = rd.block_html(block, list(cols.values()), 0)
    svg = re.search(r"<svg.*?</svg>", html, re.S).group(0)
    ET.fromstring(svg)
    check("the SVG is well formed with one polygon for the tool that has values", svg.count("<polygon") == 4 + 1, svg.count("<polygon"))
    check("a tool with nothing available has no polygon and says so", "too few axes" in html and "not available" in html)
    demo = ROOT / "results_demo" / "benchmark.report.html"
    if demo.is_file():
        page = demo.read_text(encoding="utf-8")
        check("the demo page carries the section, its axes and the numbers table", "id='fig-radar'" in page and "Verified sequence" in page and "Numbers behind the chart" in page)
    else:
        print("  SKIP: no results_demo report")
    print()
    if not ok:
        print("RADAR TESTS FAILED")
        sys.exit(1)
    print("ALL RADAR TESTS PASSED")


if __name__ == "__main__":
    main()
