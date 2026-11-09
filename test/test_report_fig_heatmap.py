#!/usr/bin/env python3
"""The tool heatmap figure (python/report_fig_heatmap.py, assets/report/fig_heatmap_*.html).

Plain script. Expected values are worked out by hand. Node (when installed) runs the JavaScript core and the results are compared with
the Python mirror number by number; without node that part prints a SKIPPED line.
"""
import json
import math
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
import report_common as rc  # noqa: E402
import report_fig_heatmap as hm  # noqa: E402

NODE = shutil.which("node")
close = lambda a, b, tol=1e-9: (a is None and b is None) or (a is not None and b is not None and abs(a - b) <= tol)  # noqa: E731

RUNNER = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const m = {exports: {}};
new Function('module', src.replace(/^[\s\S]*?<script>/, '').replace(/<\/script>\s*$/, ''))(m);
const P = m.exports, job = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
process.stdout.write(JSON.stringify(job.map(j => P[j.fn].apply(null, j.args))));
"""


def js(calls, tmp):
    job = Path(tmp) / "job.json"
    job.write_text(json.dumps([{"fn": f, "args": a} for f, a in calls]), encoding="utf-8")
    runner = Path(tmp) / "run.js"
    runner.write_text(RUNNER, encoding="utf-8")
    done = subprocess.run([NODE, str(runner), str(ROOT / "assets" / "report" / "fig_heatmap_core.html"), str(job)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_display_modes():
    cv = hm.column_view
    # raw, higher is better: min-max
    assert [x[0] for x in cv("raw", True, [1, 3, None, 2], [None] * 4)] == [0.0, 1.0, None, 0.5]
    # raw, lower is better: flipped so the smallest value is best (t = 1)
    assert [x[0] for x in cv("raw", False, [1, 3, None, 2], [None] * 4)] == [1.0, 0.0, None, 0.5]
    # a flat column is neutral and flagged, never 'good'
    assert cv("raw", True, [0.5, 0.5], [None, None]) == [(0.5, 0.5, True), (0.5, 0.5, True)]
    # a blank stays blank in every mode
    for mode in hm.__dict__["MODES"] if "MODES" in hm.__dict__ else ("raw", "score", "rank", "z"):
        assert cv(mode, True, [None, None], [None, None]) == [(None, None, False)] * 2
    # score mode: score / 100, and no score -> not available (the metric has no bands)
    sc = cv("score", True, [0.9, 0.5], [92.5, None])
    assert sc[0] == (0.925, 92.5, False) and sc[1][0] is None
    # rank: 5, 5, 3 -> ranks 1.5, 1.5, 3 ; t = (3 - r) / 2
    rk = cv("rank", True, [5, 5, 3], [None] * 3)
    assert [x[1] for x in rk] == [1.5, 1.5, 3.0] and [x[0] for x in rk] == [0.75, 0.75, 0.0]
    # rank, lower is better: the smallest is rank 1
    assert [x[1] for x in cv("rank", False, [5, 5, 3], [None] * 3)] == [2.5, 2.5, 1.0]
    # z: values 1, 2, 3 -> population sd sqrt(2/3)
    z = cv("z", True, [1, 2, 3], [None] * 3)
    sd = math.sqrt(2 / 3)
    assert close(z[0][1], -1 / sd) and close(z[1][1], 0.0) and close(z[2][1], 1 / sd)
    assert close(z[2][0], (1 / sd + 2) / 4)
    zl = cv("z", False, [1, 2, 3], [None] * 3)
    assert close(zl[0][1], 1 / sd)                         # lower is better: the smallest value is the best, z positive
    # z clamps at +-2 for colour only
    big = cv("z", True, [0] * 9 + [100], [None] * 10)
    assert close(big[9][0], 1.0) and big[9][1] > 2
    # z with no spread is 0 (flagged flat); with one value it is not available
    assert cv("z", True, [2, 2], [None] * 2)[0] == (0.5, 0.0, True)
    assert cv("z", True, [2, None], [None] * 2) == [(None, None, False)] * 2


def test_clustering():
    # hand example: d01 = 1, d02 = 4, d12 = 3 -> merge (0, 1) at 1, then 2 joins at (4 + 3) / 2 = 3.5; leaf order 2, 0, 1
    tree = hm.cluster([[None, 1, 4], [1, None, 3], [4, 3, None]])
    assert tree["merges"] == [[0, 1, 1, 2], [2, 3, 3.5, 3]], tree
    assert tree["order"] == [2, 0, 1]
    segs = hm.dendrogram_segments(tree)
    assert len(segs) == 2 and segs[0][1][1] == 1 / 3.5 and segs[1][1][1] == 1.0
    # undefined distances take the largest defined one (here 4)
    t2 = hm.cluster([[None, 1, None], [1, None, 4], [None, 4, None]])
    assert t2["merges"][0][:3] == [0, 1, 1]
    assert close(t2["merges"][1][2], (4 + 4) / 2)
    assert hm.cluster([]) == {"order": [], "merges": []}
    assert hm.cluster([[None]])["order"] == [0]
    # pairwise-complete RMS: a = [0, 1, None], b = [1, 3, 5] -> shared 2, sqrt((1 + 4) / 2)
    assert close(hm._rms([0, 1, None], [1, 3, 5], 1), math.sqrt(2.5))
    assert hm._rms([0, None], [None, 1], 1) is None and hm._rms([0, 1], [0, 1], 3) is None
    # axis clustering: a row with no value is appended unclustered
    grid = [[(0.0, 0, False), (1.0, 0, False)], [(0.1, 0, False), (0.9, 0, False)], [None, None]]
    order, elig, _ = hm.cluster_axis(grid, 0)
    assert order == [0, 1, 2] and elig == [0, 1], (order, elig)
    # columns with fewer than two values are left out too
    grid2 = [[(0.0, 0, False), None], [(1.0, 0, False), (0.5, 0, False)]]
    order, elig, _ = hm.cluster_axis(grid2, 1)
    assert elig == [0] and order == [0, 1]


def test_colour():
    assert hm.ramp(["#000000", "#ffffff"], 0.5) == "#808080" and hm.ramp(["#000000", "#ffffff"], 2) == "#ffffff"
    assert hm.ramp(hm.VIRIDIS, 0) == "#440154" and hm.ramp(hm.VIRIDIS, 1) == "#fde725"
    assert hm.text_on("#fde725") == "#111111" and hm.text_on("#440154") == "#ffffff"
    assert hm.colour_for("z", 0.5) == "#f7f7f7" and hm.colour_for("raw", 1.0, "cvd") == "#fee838"


def fixture_block():
    cols = [{"id": "A1", "short": "Identity", "name": "Nucleotide identity", "fam": "A", "dir": "higher", "unit": "percent", "digits": 2,
             "src": "scorecard", "status": "fixed", "bands": None, "weight": 10, "unval": False, "def": "d"},
            {"id": "E1", "short": "Runtime", "name": "Runtime", "fam": "E", "dir": "lower", "unit": "seconds", "digits": 0,
             "src": "scorecard", "status": "proposed", "bands": None, "weight": 4, "unval": False, "def": "d"},
            {"id": "C1", "short": "Structure (NGOC)", "name": "Structural accuracy", "fam": "C", "dir": "higher", "unit": "fraction", "digits": 3,
             "src": "scorecard", "status": "proposed", "bands": None, "weight": 8, "unval": True, "def": "d"}]
    cell = lambda v, s=None: [v, s, None, "" if v is not None else "no value", 1]  # noqa: E731
    block = {"track": "short_read",
             "rows": [{"id": f"short_read|t{i}", "tool": f"t{i}", "label": f"Tool {i}", "task": "", "nsamples": 3, "overall": None, "share": None} for i in range(3)],
             "cells": [[cell(99.0, 90.0), cell(60.0, 100.0), cell(0.9)], [cell(95.0, 60.0), cell(300.0, 85.0), cell(None)], [cell(99.5, 95.0), cell(10.0, 100.0), cell(0.5)]],
             "ps": None, "sig": None}
    return cols, block


def test_static_svg_and_payload():
    cols, block = fixture_block()
    svg = hm.render_block_svg(block, cols, uid="hmt")
    root = ET.fromstring(svg)                                   # well-formed XML
    ids = [e.get("id") for e in root.iter() if e.get("id")]
    assert len(ids) == len(set(ids)), ids
    assert "hmt-hatch" in ids and "hmt-grad" in ids
    nums = [float(x) for x in re.findall(r"-?\d+\.?\d*", " ".join(root.get("viewBox").split()))]
    assert all(math.isfinite(x) for x in nums) and "nan" not in svg.lower() and "inf" not in svg.lower()
    # the missing C1 of tool 1 is a hatched cell, never a number
    assert svg.count("url(#hmt-hatch)") >= 1 and "Tool 1, C1: not available" in svg
    # lower-is-better and unvalidated markers in the header
    assert "E1 Runtime ▼" in svg and "C1 Structure (NGOC) †" in svg
    # dendrograms are drawn when clustering is on, absent when off
    assert "<polyline" in svg and "<polyline" not in hm.render_block_svg(block, cols, cluster_on=False, uid="hmu")
    # a hidden family leaves its columns out
    assert "E1 Runtime" not in hm.render_block_svg(block, cols, uid="hmv", hidden_fams=("E",))
    # every mode renders
    for mode in ("raw", "score", "rank", "z"):
        ET.fromstring(hm.render_block_svg(block, cols, mode=mode, uid="hm" + mode))


def test_leaderboard_and_columns():
    specs = hm.rs.load_config()
    cols = hm._columns(specs)
    ids = [c["id"] for c in cols]
    assert len(ids) == len(set(ids)) == 17 + 7
    assert [c["id"] for c in cols if c["fam"] == "L"] == ["F1", "MCC", "BF1", "LWB", "ARI", "CPRR", "CF1"]
    lower = {c["id"] for c in cols if c["dir"] == "lower"}
    assert lower == {"A2", "E1", "E2"}
    assert next(c for c in cols if c["id"] == "A4")["status"] == "undefined" and next(c for c in cols if c["id"] == "A1")["status"] == "fixed"


def test_node_parity(tmp):
    if not NODE:
        print("SKIPPED: node is not installed, so the heatmap JavaScript parity tests cannot run here (they run wherever node exists)")
        return
    vals, scs = [0.2, 0.9, None, 0.9, 0.5], [20, 90, None, 90, 50]
    calls = [("columnView", [m, h, vals, scs]) for m in ("raw", "score", "rank", "z") for h in (True, False)]
    dist = [[None, 1, 4, 2.5], [1, None, 3, None], [4, 3, None, 0.5], [2.5, None, 0.5, None]]
    grid = [[[0.0, 0, False], [1.0, 0, False], None, [0.5, 0, False]], [[0.1, 0, False], [0.8, 0, False], [0.3, 0, False], None],
            [[0.9, 0, False], [0.2, 0, False], [0.7, 0, False], [0.4, 0, False]], [None, None, None, None]]
    calls += [("cluster", [dist]), ("clusterAxis", [grid, 0]), ("clusterAxis", [grid, 1]), ("avgRanks", [[3, 1, 3, None, 2], False]),
              ("ramp", [hm.VIRIDIS, 0.37]), ("ramp", [hm.CIVIDIS, 0.64]), ("textOn", ["#35b779"]), ("textOn", ["#31688e"])]
    out = js(calls, tmp)
    k = 0
    for mode in ("raw", "score", "rank", "z"):
        for h in (True, False):
            py = hm.column_view(mode, h, vals, scs)
            for a, b in zip(py, out[k]):
                assert (a[0] is None and b is None) or (b is not None and close(a[0], b[0]) and close(a[1], b[1]) and a[2] == b[2]), (mode, h, a, b)
            k += 1
    pyc = hm.cluster(dist)
    assert out[k]["order"] == pyc["order"] and all(a[:2] == b[:2] and a[3] == b[3] and close(a[2], b[2]) for a, b in zip(out[k]["merges"], pyc["merges"])), (out[k], pyc)
    k += 1
    py_grid = [[tuple(c) if c else None for c in r] for r in grid]
    for axis in (0, 1):
        o, elig, tree = hm.cluster_axis(py_grid, axis)
        assert out[k]["order"] == o and out[k]["nElig"] == len(elig), (axis, out[k], o)
        assert all(close(a[2], b[2]) for a, b in zip(out[k]["tree"]["merges"], tree["merges"]))
        k += 1
    assert out[k] == hm.avg_ranks([3, 1, 3, None, 2], False) == [3.5, 1.0, 3.5, None, 2.0]
    k += 1
    assert out[k] == hm.ramp(hm.VIRIDIS, 0.37) and out[k + 1] == hm.ramp(hm.CIVIDIS, 0.64) and out[k + 2] == hm.text_on("#35b779") and out[k + 3] == hm.text_on("#31688e")


def test_node_render_and_hash(tmp):
    if not NODE:
        return
    cols, block = fixture_block()
    for i, c in enumerate(cols):
        c["i"] = i
    data = {"cols": cols, "fams": hm.FAMILIES, "blocks": [block], "samples": [], "notes": {"drill": False, "comparisons": False, "palette": {"viridis": hm.VIRIDIS, "cividis": hm.CIVIDIS, "diverging": hm.DIVERGING}}}
    st = {"mode": "score", "rc": 1, "cc": 1, "ov": 0, "zoom": "natural", "fam": [], "cols": [], "rows": [], "trk": [], "sort": "", "sel": "", "tab": "layout"}
    st_sorted = dict(st, sort="A1:desc", rc=0, cc=0)
    st_hidden = dict(st, rows=["short_read|t1"], fam=["E"])
    out = js([("renderBlock", [data, 0, st, "hmj", {}]), ("renderBlock", [data, 0, st_sorted, "hmk", {}]), ("renderBlock", [data, 0, st_hidden, "hml", {}]),
              ("csvText", [data, st]), ("encodeHash", [dict(st, mode="rank", fam=["E"], rows=["short_read|t1"], sort="A1:asc")]),
              ("decodeHash", ["#fig-heatmap?hmmode=z&hmrc=0&hmfam=B,E&hmsort=A1%3Adesc&hmsel=x.0.1.2&hmbogus=1&hmtab=nope"]), ("decodeHash", [""])], tmp)
    for svg in out[:3]:
        ET.fromstring(svg)
    # score mode: tool 1 has no C1 -> hatched; the tools are in the sorted order by A1 (best first): tool 2 (95 -> 99.5), tool 0, tool 1
    assert out[0].count("url(#hmj-hatch)") >= 2        # the pattern fill of the missing cell (plus the legend swatch)
    order = [m for m in re.findall(r'data-rowhead="(\d)"', out[1])]
    assert order == ["2", "0", "1"], order
    assert 'data-rowhead="1"' not in out[2] and "E1" not in out[2]
    csv = out[3].strip().split("\n")
    assert csv[0].startswith("track,tool,metric_id") and len(csv) == 1 + 9
    row = [l for l in csv if l.startswith("short_read,t1,C1")][0]
    assert "no value" in row and ",0," not in row.split("no value")[0][-12:]     # blank raw value and score, never 0
    assert out[4] == "#fig-heatmap?hmmode=rank&hmfam=E&hmrows=short_read%7Ct1&hmsort=A1%3Aasc"
    d = out[5]
    assert d["mode"] == "z" and d["rc"] == 0 and d["fam"] == ["B", "E"] and d["sort"] == "A1:desc" and d["sel"] == "x.0.1.2" and d["tab"] == "layout"
    assert out[6]["mode"] == "raw" and out[6]["rc"] == 1


def test_fragments_parse(tmp):
    for name in hm.ASSETS:
        text = (ROOT / "assets" / "report" / name).read_text(encoding="utf-8")
        assert text.rstrip().endswith(("</script>", "</style>")), name
        if name.endswith("style.html"):
            assert text.count("{") == text.count("}")
            continue
        body = re.sub(r"^\s*<script>", "", text.strip())
        body = re.sub(r"</script>\s*$", "", body)
        f = Path(tmp) / (name + ".js")
        f.write_text(body, encoding="utf-8")
        if NODE:
            done = subprocess.run([NODE, "--check", str(f)], capture_output=True, text=True)
            assert done.returncode == 0, (name, done.stderr)


def write_tsv(path, rows):
    cols = list(rows[0])
    Path(path).write_text("\n".join(["\t".join(cols)] + ["\t".join(str(r.get(c, "")) for c in cols) for r in rows]) + "\n", encoding="utf-8")


def test_not_run(tmp):
    page = "<html><head></head><body><nav><a href='#recommendations'>Recommendations</a></nav><section id='recommendations'></section></body></html>"
    empty = Path(tmp) / "empty"
    empty.mkdir()
    out = hm.inject(page, str(empty), str(empty), str(empty / "scores.tsv"))
    assert "id='fig-heatmap'" in out and "Not run:" in out and "scores.tsv is absent" in out
    assert "id='hm-data'" not in out
    assert out.index("id='fig-heatmap'") < out.index("<section id='recommendations'>")
    assert "href='#fig-heatmap'" in out


def test_small_build(tmp):
    """A two-tool fixture: leaderboard and scores present, no accuracy/ngoc/performance tables -> those cells are 'not available' with reasons."""
    d = Path(tmp) / "small"
    d.mkdir()
    write_tsv(d / "scores.tsv", [{"sample": s, "tool": t, "analysis_track": "short_read", "recall": r, "plasmid_recall": r, "f1": f, "mcc": 0.5}
                                 for s in ("s1", "s2") for t, r, f in (("mob_like", 1.0, 0.9), ("gplas_like", 0.5, 0.4))])
    write_tsv(d / "benchmark.leaderboard.tsv", [{"rank": 1, "analysis_track": "short_read", "task": "reconstruction", "tool": "mob_like", "n_samples": 2, "mean_f1": 0.9, "mean_mcc": 0.5, "mean_bin_f1": "", "cprr": 0.25},
                                                {"rank": 2, "analysis_track": "short_read", "task": "reconstruction", "tool": "gplas_like", "n_samples": 2, "mean_f1": 0.4, "mean_mcc": 0.5, "mean_bin_f1": 0.3, "cprr": ""}])
    write_tsv(d / "benchmark.paired_comparisons.tsv", [{"tool_a": "gplas_like", "tool_b": "mob_like", "analysis_track": "short_read", "task": "reconstruction", "metric": "f1",
                                                      "wilcoxon_p_value_holm": 0.25, "equivalent": "yes", "smallest_difference": 0.05}])
    data = hm.build(str(d), str(d), str(d / "scores.tsv"))
    ids = [c["id"] for c in data["cols"]]
    blk = data["blocks"][0]
    assert [r["tool"] for r in blk["rows"]] == ["mob_like", "gplas_like"]      # scorecard order: the better tool first
    cell = lambda tool, cid: blk["cells"][[r["tool"] for r in blk["rows"]].index(tool)][ids.index(cid)]  # noqa: E731
    assert cell("mob_like", "B1")[0] == 1.0 and cell("gplas_like", "B1")[0] == 0.5
    assert cell("mob_like", "B1")[1] == 100.0 and cell("mob_like", "B1")[2] == "excellent"       # 1.0 >= 0.99: score 100
    assert cell("gplas_like", "B1")[1] == 0.0 and cell("gplas_like", "B1")[2] == "poor"          # 0.5 is the floor of B1: score 0
    assert cell("mob_like", "A1")[0] is None and "accuracy" in cell("mob_like", "A1")[3]          # missing table: a reason, not 0
    assert cell("mob_like", "A4")[0] is None and "variant" in cell("mob_like", "A4")[3]
    assert cell("mob_like", "BF1")[0] is None and "blank" in cell("mob_like", "BF1")[3]
    assert cell("mob_like", "CPRR")[0] == 0.25 and cell("gplas_like", "CPRR")[0] is None
    assert data["blocks"][0]["ps"][0][ids.index("F1")] == [0.9, 0.9]                              # per-isolate values behind the leaderboard mean
    sig = blk["sig"]["F1"]
    assert sig["best"] == [0] and sig["tested"] and sig["tied"] == [1] and "0.25" in sig["info"][1]
    assert blk["sig"]["B1"]["best"] == [0] and blk["sig"]["B1"]["tested"] is False and blk["sig"]["B1"]["tied"] == []
    json.loads(hm.payload_json(data))                                                              # payload parses (allow_nan=False inside)


def main():
    test_display_modes()
    test_clustering()
    test_colour()
    test_static_svg_and_payload()
    test_leaderboard_and_columns()
    with tempfile.TemporaryDirectory(prefix="hm_test_") as tmp:
        test_not_run(tmp)
        test_fragments_parse(tmp)
        test_node_parity(tmp)
        test_node_render_and_hash(tmp)
        try:
            test_small_build(tmp)
        except AssertionError:
            raise
        demo = ROOT / "results_demo"
        if (demo / "scores.tsv").is_file():
            data = hm.build(str(demo), str(demo), str(demo / "scores.tsv"))
            assert [b["track"] for b in data["blocks"]] and len(data["cols"]) == 24
            text = hm.host_html(data)
            assert "id='hm-data'" in text and "NaN" not in text
            for b in data["blocks"]:
                for row in b["cells"]:
                    assert len(row) == 24 and all(c[0] is None or math.isfinite(c[0]) for c in row)
            ids = re.findall(r"\bid='([^']+)'", text)
            assert len(ids) == len(set(ids))
            page = "<html><head><style></style></head><body><nav><a href='#recommendations'>Recommendations</a></nav><section id='recommendations'></section></body></html>"
            out = hm.inject(page, str(demo), str(demo), str(demo / "scores.tsv"))
            assert "id='fig-heatmap'" in out and "Not run:" not in out.split("id='fig-heatmap'")[1].split("</section>")[0]
            print(f"payload + static + assets added: {len(out) - len(page):,} bytes on results_demo")
        else:
            print("SKIPPED: results_demo is absent, so the real-build check did not run")
    print("ALL HEATMAP FIGURE TESTS PASSED")


if __name__ == "__main__":
    main()
