#!/usr/bin/env python3
"""report_synteny.py: ribbons joining each truth plasmid to each tool's records, in order and orientation, from alignment_blocks.json."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))
import report_synteny as sy  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


def block(record, qlen, qs, qe, strand, ts, te, ident=0.999, target="P1", mol="PLASMID"):
    length = te - ts
    return {"record_id": record, "query_length": qlen, "query_start": qs, "query_end": qe, "strand": strand, "target": target, "target_start": ts,
            "target_end": te, "matches": int(length * ident), "block_length": length, "mapq": 60, "molecule_type": mol}


def write(results, sample, tools, plasmids=None):
    path = os.path.join(results, sample, "visualization", "alignment_blocks.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump({"schema_version": "1.0", "sample": sample, "truth_plasmids": plasmids or {"P1": {"length": 100000, "molecule_type": "PLASMID"},
               "C1": {"length": 5000000, "molecule_type": "CHROMOSOME"}}, "tools": {t: {"blocks": b} for t, b in tools.items()}}, open(path, "w"))


tmp = tempfile.mkdtemp(prefix="synteny_")
try:
    res = os.path.join(tmp, "results")
    write(res, "S1", {
        "toolA": [block("a1", 100000, 0, 100000, "+", 0, 100000)],
        "toolB": [block("b1", 60000, 0, 60000, "+", 0, 60000, 0.97), block("b2", 40000, 0, 40000, "-", 60000, 100000, 0.9),
                  block("b1", 60000, 100, 900, "+", 0, 800, target="C1", mol="CHROMOSOME")],
        "toolC": [block("c1", 500, 0, 500, "+", 0, 500, target="C1", mol="CHROMOSOME")],
        "toolD": [{"record_id": "d1", "target": "P1"}],
    })
    views = sy.load(res)
    check("one plasmid view is built, the chromosome is not a view", len(views) == 1 and views[0][1] == "P1", [(v[0], v[1]) for v in views])
    lanes = {l["tool"]: l for l in views[0][3]}
    check("a tool with no block on the plasmid, or with incomplete blocks, has no lane", set(lanes) == {"toolA", "toolB"}, set(lanes))
    check("a chromosome block is not counted as plasmid coverage", lanes["toolB"]["covered"] == 100000 and len(lanes["toolB"]["blocks"]) == 2, lanes["toolB"]["covered"])
    check("records are ordered by where they land on the plasmid", [r["id"] for r in lanes["toolB"]["records"]] == ["b1", "b2"])
    check("reverse blocks are counted", lanes["toolB"]["reverse"] == 1 and lanes["toolA"]["reverse"] == 0)
    check("identity and opacity follow the block", abs(sy.identity(block("x", 1, 0, 1, "+", 0, 1000, 0.97)) - 0.97) < 1e-3 and sy.opacity(0.999) > sy.opacity(0.97) > sy.opacity(0.9))

    page = "<html><nav><a href='#recommendations'>Recommendations</a></nav><section id='recommendations'></section></html>"
    out = sy.inject_legacy(page, res)
    check("the section and navigation link are added before Recommendations", "id='learn-synteny'" in out and "href='#learn-synteny'" in out
          and out.index("learn-synteny") < out.index("id='recommendations'"))
    polys = re.findall(r"<g class='sy-rib'[^>]*data-strand='([+-])'[^>]*>.*?<polygon[^>]*points='([^']*)'", out, flags=re.S)
    rev = [p for s, p in polys if s == "-"]
    fwd = [p for s, p in polys if s == "+"]
    check("forward and reverse ribbons are both drawn", len(rev) == 1 and len(fwd) == 2, (len(rev), len(fwd)))

    def bottom_x(points):
        p = [tuple(float(v) for v in pair.split(",")) for pair in points.split()]
        return p[2][0], p[3][0]
    f0, f1 = bottom_x(fwd[0])
    r0, r1 = bottom_x(rev[0])
    check("a forward ribbon keeps the order on the record, a reverse ribbon crosses (bow-tie)", f0 > f1 and r0 < r1, (f0, f1, r0, r1))
    check("each ribbon carries strand, identity and its details for filtering and hover", "data-ident=" in out and "data-info=" in out and "data-strand='-'" in out)
    check("each region has the numbers behind the picture", "Numbers for this plasmid" in out and "Aligned bases on the plasmid" in out)
    check("controls: plasmid choice, tools, strand, identity, zoom", all(k in out for k in ("sy-select", "sy-tool", "sy-fwd", "sy-rev", "sy-ident", "sy-zoom")))
    svgs = re.findall(r"<svg\b.*?</svg>", out, flags=re.S)
    bad = []
    for s in svgs:
        try:
            ET.fromstring(s)
        except ET.ParseError as exc:
            bad.append(str(exc))
    check("every drawing is well-formed SVG", svgs and not bad, bad[:2])
    script = re.search(r"<script>(.*?)</script>", out, flags=re.S).group(1)
    node = shutil.which("node")
    if node:
        jspath = os.path.join(tmp, "s.js")
        open(jspath, "w", encoding="utf-8").write(script)
        done = subprocess.run([node, "--check", jspath], capture_output=True, text=True)
        check("the page script is valid JavaScript", done.returncode == 0, done.stderr[-300:])
    check("views are hidden only once the script runs, so the page reads without it", "classList.add('sy-js')" in script and ".sy.sy-js .sy-view{display:none}" in out)

    many = [block(f"r{i}", 100000, i * 100, i * 100 + 80, "+", i * 100, i * 100 + 80) for i in range(sy.MAX_RIBBONS + 7)]
    write(res, "S2", {"toolA": many})
    cap = {l["tool"]: l for v in sy.load(res) if v[0] == "S2" for l in v[3]}["toolA"]
    check("blocks beyond the cap are counted as not drawn", cap["omitted"] == 7 and "smaller block(s) not drawn" in sy.inject_legacy(page, res), cap["omitted"])

    for i in range(sy.MAX_VIEWS + 3):
        write(res, f"X{i:03d}", {"toolA": [block("a", 100000, 0, 1000, "+", 0, 1000)]})
    capped = sy.inject_legacy(page, res)
    check("more plasmids than the cap are listed with how many were left out", f"Showing {sy.MAX_VIEWS} of" in capped and capped.count("class='sy-view'") == sy.MAX_VIEWS)

    write(os.path.join(tmp, "esc"), "S&x", {"<i>t</i>": [block("<u>r</u>", 1000, 0, 500, "+", 0, 500)]}, {"P1": {"length": 1000, "molecule_type": "PLASMID"}})
    esc_out = sy.inject_legacy(page, os.path.join(tmp, "esc"))
    check("sample, tool and record names are escaped", "S&amp;x" in esc_out and "S&x" not in esc_out and "<i>t</i>" not in esc_out and "<u>r</u>" not in esc_out)

    empty = sy.inject_legacy(page, os.path.join(tmp, "nothing"))
    check("with no alignment blocks the section says it was not run and why", "Not run" in empty and "alignment_blocks.json" in empty)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("ALL SYNTENY TESTS PASSED" if ok else "SYNTENY TESTS FAILED")
sys.exit(0 if ok else 1)
