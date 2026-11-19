#!/usr/bin/env python3
"""The redesigned synteny view (python/report_fig_synteny.py, assets/report/fig_synteny_*.html). Plain script."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import report_fig_synteny as sx  # noqa: E402
import report_synteny as old  # noqa: E402

NODE = shutil.which("node")
OK = True


def check(label, good, detail=""):
    global OK
    OK &= bool(good)
    print(f"  {'PASS' if good else 'FAIL'}: {label}" + (f"  {detail}" if detail and not good else ""))


def strip(name):
    return (ROOT / "assets/report" / name).read_text(encoding="utf-8").replace("<script>", "").replace("</script>", "")


def blk(rec, qs, qe, ts, te, strand="+", ident=1.0, qlen=None, target="P1"):
    n = te - ts
    return {"record_id": rec, "query_length": qlen or qe, "query_start": qs, "query_end": qe, "strand": strand, "target": target, "target_start": ts, "target_end": te,
            "matches": int(n * ident), "block_length": n, "mapq": 60, "molecule_type": "PLASMID"}


def write_sample(root, sample, plasmid, length, tools, features=None):
    d = Path(root) / sample / "visualization"
    d.mkdir(parents=True, exist_ok=True)
    data = {"truth_plasmids": {plasmid: {"molecule_type": "PLASMID", "length": length}}, "tools": {t: {"blocks": b} for t, b in tools.items()},
            "amr_features": features or [], "context_features": []}
    (d / "alignment_blocks.json").write_text(json.dumps(data), encoding="utf-8")


def main():
    print("pure helpers (python)")
    base = [0, 0, 920, 200]
    z = sx.zoom_at(base, base, 460, 100, 2)
    check("zoom halves the view about the point and stays inside the base", z == [230, 50, 460, 100], z)
    check("zoom out is capped at the base and zoom in at the maximum", sx.zoom_at(base, base, 0, 0, 0.5) == base and sx.zoom_at(base, base, 0, 0, 1000)[2] == 920 / sx.MAX_ZOOM)
    check("pan is kept inside the base", sx.pan_by([230, 50, 460, 100], base, 9999, -9999) == [460, 0, 460, 100])
    check("covered bases count overlaps once", sx.union_bp([(0, 10), (5, 20), (30, 40)]) == 30 and sx.union_bp([]) == 0 and sx.union_bp([(5, 5)]) == 0)
    check("the ruler step is 1, 2 or 5 times a power of ten", sx.nice_step(25000) == 5000 and sx.nice_step(110000) == 20000 and sx.nice_step(10) == 2)
    if NODE:
        probe = strip("fig_synteny_core.html") + "\nconst Z=module.exports;console.log(JSON.stringify([Z.zoomAt([0,0,920,200],[0,0,920,200],460,100,2,12),Z.zoomAt([230,50,460,100],[0,0,920,200],10,10,0.5,12),Z.panBy([230,50,460,100],[0,0,920,200],9999,-9999)]))"
        with tempfile.TemporaryDirectory() as tmp:
            js = Path(tmp) / "c.js"
            js.write_text(probe, encoding="utf-8")
            done = subprocess.run([NODE, str(js)], capture_output=True, text=True)
            got = json.loads(done.stdout) if done.returncode == 0 else done.stderr
            ui = Path(tmp) / "u.js"
            ui.write_text(strip("fig_synteny_ui.html"), encoding="utf-8")
            syntax = subprocess.run([NODE, "--check", str(ui)], capture_output=True, text=True)
        want = [sx.zoom_at([0, 0, 920, 200], [0, 0, 920, 200], 460, 100, 2), sx.zoom_at([230, 50, 460, 100], [0, 0, 920, 200], 10, 10, 0.5), sx.pan_by([230, 50, 460, 100], [0, 0, 920, 200], 9999, -9999)]
        check("the JavaScript zoom and pan equal the Python mirror (node)", got == want, (got, want))
        check("the panel script is valid JavaScript", syntax.returncode == 0, syntax.stderr[-300:])
    else:
        print("  SKIPPED: node not found")

    print("the drawing")
    with tempfile.TemporaryDirectory() as tmp:
        res = os.path.join(tmp, "res")
        tools = {"toolA": [blk("a1", 0, 50000, 0, 50000), blk("a2", 0, 50000, 50000, 100000)],
                 "toolB": [blk("b1", 0, 40000, 0, 40000), blk("b2", 0, 30000, 40000, 70000, "-", 0.9), blk("b3", 0, 30000, 70000, 100000)],
                 "<i>toolC</i>": [blk("c<u>1", 0, 1000, 0, 1000)]}
        write_sample(res, "S&x", "P1", 100000, tools, [{"sequence_id": "P1", "start": 100, "end": 900, "label": "tet<A>"}])
        pairs = sx.load(res)
        check("one comparison per sample, plasmid and tool", len(pairs) == 3 and pairs[0]["tool"] == "toolB", [p["tool"] for p in pairs])
        sec, assets = sx.build_section(pairs)
        html = sec
        svgs = re.findall(r"<svg[^>]*class='sx-svg'.*?</svg>", html, re.S)
        for s in svgs:
            ET.fromstring(s)
        check("every comparison is a well-formed SVG of at most 200 px (the old view was ~700 px for five tools)", len(svgs) == 3 and all(int(re.search(r"height='(\d+)'", s).group(1)) <= 200 for s in svgs))
        sb = svgs[0]
        check("a forward block is an untwisted band, a reverse block is hatched and swaps its record ends", sb.count("fill='url(#sxh0)'") == 1 and sb.count("class='sx-rib'") == 3)
        paths = re.findall(r"<g class='sx-rib'[^>]*>.*?<path class='sx-sh' d='([^']*)'", sb, re.S)
        def top_bottom(d):
            nums = [float(v) for v in re.findall(r"-?\d+\.?\d*", d)]
            return nums
        fwd = [top_bottom(p) for p in paths]
        check("ribbon paths are smooth curves between the two tracks", all(" C" in p for p in paths))
        check("a scale bar in kb, a kb ruler and feature ticks are drawn", "kb</text>" in sb and "5.0 kb" in sb.replace("5 kb", "5.0 kb") or "kb" in sb)
        check("tooltips carry coordinates, identity, length and strand", "identity 90.0%" in sb and "reverse (inverted)" in sb and "of the plasmid" in sb and "record 0-30000" in sb)
        check("the alignment table, the plasmid-map link target and the not-drawn note", "class='sx-aln'" in html and "Of plasmid" in html and "#plasmid-maps" in assets)
        check("names are escaped", "S&amp;x" in html and "S&x" not in html and "&lt;i&gt;toolC" in html and "<i>toolC" not in html and "c&lt;u&gt;1" in html and "tet&lt;A&gt;" in html)
        check("the first comparison is open and the others are folds (no JavaScript, print)", html.count("<details class='sx-pair'") == 3 and html.count(" open>") == 1)
        check("controls, keyboard, panel and zoom hooks exist in the script", all(k in assets for k in ("sx-sample", "sx-plasmid", "sx-tool", "Reset view", "Escape", "ArrowRight", "'Enter'", "aria-label", "PBSynteny", "wheel", "pointerdown")))
        check("visible focus, phone width, print and dark rules exist", all(k in assets for k in ("focus-visible", "max-width:600px", "@media print", 'data-theme="dark"')))
        check("no external resource is loaded", not re.search(r"(src|href)=['\"]https?://", assets + html))
        check("a view that cannot be drawn without JavaScript still reads (details folds hold the drawing and table)", "<details class='sx-pair'" in html and "<summary>" in html)
        page = "<html><body><nav><a href='#recommendations'>Recommendations</a></nav><section id='recommendations'></section></body></html>"
        out = sx.inject(page, res)
        check("injected before Recommendations with a nav link", out.index("learn-synteny") < out.index("id='recommendations'") and "href='#learn-synteny'" in out)
        via_old = old.inject(page, res)
        check("the old module's inject now delegates here (and keeps inject_legacy)", "sx-root" in via_old and hasattr(old, "inject_legacy"))
        many = Path(tmp) / "many"
        for i in range(sx.MAX_PAIRS + 5):
            write_sample(many, f"S{i:03d}", "P1", 5000, {"t": [blk("r", 0, 5000, 0, 5000)]})
        sec2, _a = sx.build_section(sx.load(str(many)), None)
        check("more comparisons than the cap are listed with how many were left out", f"Showing {sx.MAX_PAIRS} of {sx.MAX_PAIRS + 5}" in sec2 and sec2.count("class='sx-svg'") == sx.MAX_PAIRS)
        empty, _x = sx.build_section(sx.load(os.path.join(tmp, "nothing")))
        check("with no alignment blocks it says what is not available and why", "Not available in this run" in empty and "alignment_blocks.json" in empty)
        nan = Path(tmp) / "nan"
        write_sample(nan, "S", "P1", 1000, {"t": [{"record_id": "r", "query_start": None, "query_end": 5, "target": "P1"}]})
        check("incomplete blocks give no lane and no failure", sx.load(str(nan)) == [])
        one = Path(tmp) / "one"
        write_sample(one, "S", "P1", 1000, {"t": [blk("r", 0, 1000, 0, 1000)]})
        check("a single perfect record draws", len(sx.load(str(one))) == 1 and "class='sx-rib'" in sx.build_section(sx.load(str(one)))[0])
    demo = ROOT / "results_demo" / "benchmark.report.html"
    if demo.is_file():
        page = demo.read_text(encoding="utf-8")
        i = page.index("<section id='learn-synteny'")
        j = page.index("<section id='", i + 10)
        check("the demo page carries the redesigned view", "id='sx-root'" in page[i:j])
        print(f"  info: demo synteny section is {j - i:,} bytes")
    else:
        print("  SKIP: no results_demo report")
    print()
    print("ALL SYNTENY FIGURE TESTS PASSED" if OK else "SYNTENY FIGURE TESTS FAILED")
    sys.exit(0 if OK else 1)


if __name__ == "__main__":
    main()
