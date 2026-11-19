#!/usr/bin/env python3
"""The compact, interactive tool fingerprint (python/report_fig_fingerprint.py, assets/report/fig_fingerprint_*.html). Plain script."""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import report_fig_fingerprint as fp  # noqa: E402
import report_fig_radar as rd  # noqa: E402

NODE = shutil.which("node")
OK = True


def check(label, good, detail=""):
    global OK
    OK &= bool(good)
    print(f"  {'PASS' if good else 'FAIL'}: {label}" + (f"  {detail}" if detail and not good else ""))


def strip(name):
    return (ROOT / "assets/report" / name).read_text(encoding="utf-8").replace("<script>", "").replace("</script>", "")


def data_for(rows, samples=("s1", "s2")):
    """A minimal heatmap-shaped dict: one tool per row, each row 7 axis values (None = not available)."""
    cols = rd.hm._columns(rd.hm.rs.load_config())
    index = {c["id"]: j for j, c in enumerate(cols)}
    cells, rws, ps = [], [], []
    for i, vals in enumerate(rows):
        line = [[None, None, None, "x", 0] for _ in cols]
        pl = [None for _ in cols]
        for (_label, col, _m, inv), v in zip(rd.AXES, vals):
            raw = None if v is None else (1 - v if inv else v)
            if col == "E1":
                line[index[col]] = [None if v is None else 100, None if v is None else v * 100, "good", "", 3]
            else:
                line[index[col]] = [raw, None, None, "" if v is not None else "n/a", 3]
            pl[index[col]] = [None if v is None else raw] * len(samples)
        cells.append(line)
        ps.append(pl)
        rws.append({"id": f"t|T{i}", "tool": f"T<{i}>", "label": f"T&<{i}>", "task": "", "nsamples": 2, "overall": (90 - i) if vals[0] is not None else None, "share": 1})
    return {"cols": cols, "blocks": [{"track": "short_read", "rows": rws, "cells": cells, "ps": ps}] if rows else [], "samples": list(samples)}


def main():
    rd.validate()
    print("pure helpers (python)")
    check("compare toggles and caps at three, dropping the oldest",
          fp.toggle_compare([], "a") == ["a"] and fp.toggle_compare(["a", "b"], "a") == ["b"] and fp.toggle_compare(["a", "b", "c"], "d") == ["b", "c", "d"])
    check("grid arrows stay at the edges", fp.grid_move(0, "ArrowLeft", 3, 5) == 0 and fp.grid_move(2, "ArrowRight", 3, 5) == 2 and fp.grid_move(1, "ArrowDown", 3, 5) == 4
          and fp.grid_move(4, "ArrowDown", 3, 5) == 4 and fp.grid_move(4, "Home", 3, 5) == 0 and fp.grid_move(0, "End", 3, 5) == 4 and fp.grid_move(0, "x", 3, 0) == -1)
    check("spread ignores blanks and NaN", fp.spread([3, None, 1, 2, float("nan")]) == {"n": 3, "min": 1.0, "median": 2.0, "max": 3.0}
          and fp.spread([])["n"] == 0 and fp.spread([1, 2])["median"] == 1.5)
    check("a blank or NaN is not available, never 0", fp.fmt_value(None, 3) == "not available" and fp.fmt_value(float("nan"), 2) == "not available" and fp.fmt_value(0.5, 2) == "0.50")
    if NODE:
        js_src = strip("fig_fingerprint_core.html") + ("\nconst FP=module.exports;console.log(JSON.stringify([FP.toggleCompare(['a','b','c'],'d',3),FP.toggleCompare(['a','b'],'a',3),"
                                                       "FP.gridMove(1,'ArrowDown',3,5),FP.gridMove(2,'ArrowRight',3,5),FP.gridMove(0,'End',3,5),FP.spread([3,null,1,2]),FP.spread([]),"
                                                       "FP.fmtValue(null,3),FP.fmtValue(0.5,2)]))")
        with tempfile.TemporaryDirectory() as tmp:
            js = Path(tmp) / "c.js"
            js.write_text(js_src, encoding="utf-8")
            done = subprocess.run([NODE, str(js)], capture_output=True, text=True)
            got = json.loads(done.stdout) if done.returncode == 0 else done.stderr
            ui = Path(tmp) / "u.js"
            ui.write_text(strip("fig_fingerprint_ui.html"), encoding="utf-8")
            syntax = subprocess.run([NODE, "--check", str(ui)], capture_output=True, text=True)
        want = [fp.toggle_compare(["a", "b", "c"], "d"), fp.toggle_compare(["a", "b"], "a"), fp.grid_move(1, "ArrowDown", 3, 5), fp.grid_move(2, "ArrowRight", 3, 5),
                fp.grid_move(0, "End", 3, 5), fp.spread([3, None, 1, 2]), fp.spread([]), fp.fmt_value(None, 3), fp.fmt_value(0.5, 2)]
        check("the JavaScript helpers equal the Python mirror (node)", got == want, (got, want))
        check("the panel script is valid JavaScript", syntax.returncode == 0, syntax.stderr[-300:])
    else:
        print("  SKIPPED: node not found (parity and syntax)")

    print("the drawing")
    d = data_for([[0.9, 0.8, 0.7, 0.6, 0.9, 0.5, 1.0], [0.4, None, None, None, 0.2, None, None], [None] * 7, [1.0] * 7])
    sec, _assets = fp.build_section(d)
    html = str(sec)
    svgs = re.findall(r"<svg.*?</svg>", html, re.S)
    for s in svgs:
        ET.fromstring(s)
    check("one SVG per tool and every SVG is well-formed", len(svgs) == 4, len(svgs))
    hs = [int(re.search(r"height='(\d+)'", s).group(1)) for s in svgs]
    ws = [int(re.search(r"width='(\d+)'", s).group(1)) for s in svgs]
    check("every tile is at most 160 px (the old radar was 560 x 470)", max(hs) <= 160 and max(ws) <= 160, (hs, ws))
    check("fewer than three axes: no polygon and a stated reason; nothing is drawn as zero",
          "fill-opacity='.16'" not in svgs[1] and "too few axes" in svgs[1] and "no axis available" in svgs[2])
    check("a full tool draws one polygon on the shared frame with its axis codes", svgs[3].count("fill-opacity='.16'") == 1 and "ACC" in svgs[3] and "STR" in svgs[3])
    check("names are escaped", "T&amp;&lt;0&gt;" in html and "T&<0>" not in html)
    check("rank, axes available and the numbers table are in the static HTML", "rank 1 of 3" in html and "7/7 axes" in html and "Numbers behind the chart" in html and "not available" in html)
    check("aria: labelled panel, tooltip role, axis-code list", "aria-label='Tool fingerprint panel'" in html and "role='tooltip'" in html and "aria-label='Axis codes'" in html)
    ui = (ROOT / "assets/report/fig_fingerprint_ui.html").read_text(encoding="utf-8")
    check("keyboard: Enter / Space open, arrows move, Escape closes; tiles are buttons with aria-pressed and a roving tabindex",
          all(k in ui for k in ("'Enter'", "' '", "ArrowRight", "Escape", "'button'", "aria-pressed", "tabindex")))
    css = (ROOT / "assets/report/fig_fingerprint_style.html").read_text(encoding="utf-8")
    check("visible focus, phone width, print and dark rules exist", "focus-visible" in css and "max-width:520px" in css and "@media print" in css and 'data-theme="dark"' in css)
    check("print hides the panel and the toolbar and keeps the tiles", re.search(r"@media print\{[^}]*\.fp-panel", css) is not None)
    model = json.loads(re.search(r"id='fp-data'>(.*?)</script>", html, re.S).group(1))
    check("the payload keeps every value and the definitions", len(model["tracks"][0]["tools"]) == 4 and len(model["axes"]) == 7 and all(a["def"] for a in model["axes"]))
    print("edge cases")
    check("no tools: a section with no tiles and no failure", "fp-tile" not in str(fp.build_section(data_for([]))[0]))
    one = str(fp.build_section(data_for([[0.5] * 7]))[0])
    check("one tool", one.count("class='fp-tile'") == 1 and "rank 1 of 1" in one)
    check("many tools stay a grid of small tiles", str(fp.build_section(data_for([[0.5] * 7] * 30))[0]).count("class='fp-tile'") == 30)
    demo = ROOT / "results_demo" / "benchmark.report.html"
    if demo.is_file():
        page = demo.read_text(encoding="utf-8")
        i = page.index("<section id='fig-radar'")
        j = page.index("<section id='", i + 10)
        check("the demo page carries the compact figure and keeps the numbers", "id='fp-root'" in page[i:j] and "Numbers behind the chart" in page[i:j] and "Verified sequence" in page[i:j])
        print(f"  info: demo fig-radar section is {j - i:,} bytes")
    else:
        print("  SKIP: no results_demo report")
    print()
    print("ALL FINGERPRINT TESTS PASSED" if OK else "FINGERPRINT TESTS FAILED")
    sys.exit(0 if OK else 1)


if __name__ == "__main__":
    main()
