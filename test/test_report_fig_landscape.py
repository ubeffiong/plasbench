#!/usr/bin/env python3
"""The 3D landscape figure (python/report_fig_landscape.py, assets/report/fig_landscape_*.html).

Plain script. Hand-computed expectations for ticks, ranks, the Pareto front, stacking and missing values; node runs the JS
scene builder and the result is compared number by number (1e-6) with the Python mirror that draws the static no-JS fallback.
"""
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
import report_3d as r3  # noqa: E402
import report_common as rc  # noqa: E402
import report_fig_landscape as fl  # noqa: E402

NODE = shutil.which("node")
RUNNER = r"""
const fs = require('fs');
function load(file) {
  const src = fs.readFileSync(file, 'utf8');
  const m = {exports: {}};
  new Function('module', src.replace(/^[\s\S]*?<script>/, '').replace(/<\/script>\s*$/, ''))(m);
  return m.exports;
}
const root = process.argv[2], job = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const P = load(root + '/assets/report/viz3d_core.html'), L = load(root + '/assets/report/fig_landscape_core.html');
const out = job.map(j => {
  if (j.fn === 'build') {
    const sc = L.build(j.data, j.vals, j.hidden);
    L.buildTips(sc);
    const cam = P.fitCamera(sc, {yaw: -32, pitch: 26}, 900, 580);
    const m = sc.model;
    return {prims: sc.prims.map(p => ({k: p.k, role: p.role, shape: p.shape, r: p.r, fill: p.fill, t: p.t, p: p.p, pts: p.pts, id: p.id})), cam: cam,
      svg: P.svgDoc(sc, cam, 900, 580, {}), tips: Object.keys(sc.tips).length, legend: sc.legend.map(e => e.key),
      model: {plotted: m.plotted.length, notPlotted: m.notPlotted.map(n => [n.r ? n.r.sample : '', n.r ? n.r.tool : n.tool, n.why]), nFront: m.nFront, nStack: m.nStack,
        ideal: m.ideal, nPts: m.pts.length, csv: L.csvText(L.CSV_HEADER, L.plottedRows(m))}};
  }
  return L[j.fn].apply(null, j.args);
});
process.stdout.write(JSON.stringify(out));
"""


def js(calls, tmp):
    job, runner = Path(tmp) / "job.json", Path(tmp) / "runner.js"
    runner.write_text(RUNNER, encoding="utf-8")
    job.write_text(json.dumps(calls), encoding="utf-8")
    done = subprocess.run([NODE, str(runner), str(ROOT), str(job)], capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def close(a, b, tol=1e-6):
    if a is None or b is None:
        return a is b
    if isinstance(a, dict):
        return all(close(a.get(k), b.get(k), tol) for k in set(a) | set(b))
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(close(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= tol
    return a == b


def run(sample, tool, track="short_read", org="E. coli", identity=0.99, precision=0.9, recall=0.8, f1=0.85, plr=0.5, cprr=0.5, ngoc=0.7,
        collinear=0.9, events=1, aligned=1000000, runtime=100, n_truth=2):
    return [sample, tool, track, org, identity, precision, recall, f1, plr, cprr, ngoc, collinear, events, aligned, runtime, n_truth]


def payload(rows, absent=None):
    return {"kind": "landscape", "f": fl.FIELDS, "rows": rows, "absent": absent or {}}


def prim_view(p):
    return {"k": p["k"], "role": p.get("role"), "shape": p.get("shape"), "r": p.get("r"), "fill": p.get("fill"), "t": p.get("t"), "p": p.get("p"), "pts": p.get("pts"),
            "id": p.get("id")}


def main():
    # ---- hand-computed pure functions (Python mirror)
    ticks, d = fl.nice_ticks(0, 1)
    assert d == 1 and close(ticks, [0, 0.2, 0.4, 0.6, 0.8, 1.0]), (ticks, d)
    ticks, d = fl.nice_ticks(0.9, 1.0)
    assert d == 2 and close(ticks, [0.9, 0.92, 0.94, 0.96, 0.98, 1.0]), ticks
    assert close(fl.rank_pos([3, 1, 2, 2]), [1, 0, 0.5, 0.5])          # ties share the average rank: (1+2)/2/3
    assert close(fl.rank_pos([5]), [0.5])
    assert fl.metric({"identity": None, "precision": 0.8}, "identity") == (0.8, "precision")      # fallback is labelled
    assert fl.metric({"identity": None, "precision": None}, "identity") is None                  # never zero
    assert close(fl.metric({"events": 1, "aligned_bp": 1e6}, "events")[0], 0.5)                  # 1/(1+1 event per Mb)
    assert fl.metric({"events": 1, "aligned_bp": 0}, "events") is None
    assert fl.axis_range([1.0, 1.0], "zoom", None) == [0.9, 1]                                   # flat data: still a readable axis
    assert fl.axis_range([0.5, 0.7], "custom", [0.2, 0.9]) == [0.2, 0.9]

    # ---- Pareto, stacking, missing values (Python builder)
    pareto = payload([run("s1", "A", identity=1.0, recall=1.0, ngoc=1.0), run("s1", "B", identity=0.9, recall=1.0, ngoc=1.0),
                      run("s1", "C", identity=1.0, recall=0.5, ngoc=1.0)])
    m = fl.py_build(pareto)["model"]
    assert m["n_front"] == 1 and m["plotted"] == 3, m
    flat = payload([run(f"s{i}", t, identity=1.0, precision=1.0, recall=1.0, ngoc=1.0, collinear=1.0, events=0) for i in range(3) for t in ("A", "B")])
    sc = fl.py_build(flat)
    badge = [p for p in sc["prims"] if p.get("role") == "badge"]
    assert len(badge) == 1 and badge[0]["t"] == "×6", badge                     # six coincident runs: one stack, count badge, no jitter
    assert sc["model"]["ideal"] and sc["model"]["n_stack"] == 1
    ideal = [p for p in sc["prims"] if p.get("role") == "ideal"][0]
    pt = [p for p in sc["prims"] if p.get("role") == "pt"][0]
    assert close(ideal["p"], pt["p"]), "with flat data every point sits on the ideal corner"
    assert close(ideal["p"], [6, 6, -6])
    miss = payload([run("s1", "A"), run("s1", "B", ngoc=None), run("s2", "B", identity=None, precision=None)], {"ngoc": "benchmark.ngoc.tsv"})
    mm = fl.py_build(miss)["model"]
    assert mm["plotted"] == 1 and len(mm["not_plotted"]) == 2, mm
    assert "NGOC not available (benchmark.ngoc.tsv not found)" in mm["not_plotted"][0][2]
    assert "accuracy" in mm["not_plotted"][1][2], mm
    fb = fl.py_build(payload([run("s1", "A", identity=None, precision=0.75)]))
    assert [p for p in fb["prims"] if p.get("role") == "fallback"], "precision fallback is ringed"
    only = fl.py_build(pareto, {"pareto_only": 1})
    assert only["model"]["n_pts"] == 1

    # ---- static fallback and payload
    data = fl.load_runs(str(ROOT / "results_demo"), str(ROOT / "results_demo"), str(ROOT / "results_demo" / "scores.tsv"))
    assert data and len(data["rows"]) == 29, len(data["rows"] if data else [])
    json.dumps(data, allow_nan=False)                                                 # numbers finite
    static, scene = fl.static_figure(data)
    ET.fromstring(re.search(r"<svg.*?</svg>", static, re.S).group(0))                 # well-formed XML
    assert "Show the data table" in static and "not plotted" in static

    # ---- section on the real demo results, and Not-run cases
    page = "<html><style></style><nav><a href='#recommendations'>Recommendations</a></nav><section id='recommendations'></section></html>"
    out = fl.inject(page, str(ROOT / "results_demo"), str(ROOT / "results_demo"), str(ROOT / "results_demo" / "scores.tsv"))
    assert out.count("id='fig-landscape'") == 1 and "href='#fig-landscape'" in out and out.index("fig-landscape'") < out.index("id='recommendations'")
    tag = re.search(r"<script type='application/json' id='ls-data'>(.*?)</script>", out, re.S)
    json.loads(tag.group(1))
    ids = re.findall(r"\sid='([^']+)'", out)
    assert len(ids) == len(set(ids)), "ids must be unique"
    assert "root.PB3D = api" in out and out.count("root.PBLandscape = api") == 1
    out2 = fl.inject(out.replace("id='fig-landscape'", "id='x'"), str(ROOT / "results_demo"), None, str(ROOT / "results_demo" / "scores.tsv"))
    assert out2.count("root.PB3D = api") == 1, "the engine is loaded once"
    nr = str(fl.build_section(page, str(ROOT / "results_demo"), None, str(ROOT / "results_demo" / "no_such_scores.tsv")))
    assert "Not run" in nr
    with tempfile.TemporaryDirectory() as tmp:
        empty = Path(tmp) / "scores.tsv"
        empty.write_text("sample\ttool\n", encoding="utf-8")
        assert "Not run" in str(fl.build_section(page, tmp, tmp, str(empty)))
        bare = Path(tmp) / "bare.tsv"      # scores only: every other source absent, so the reasons name the missing files
        bare.write_text("sample\ttool\tanalysis_track\tprecision\trecall\tf1\ts1\tA\tshort_read\t1\t1\t1\n".replace("\tf1\ts1", "\tf1\ns1"), encoding="utf-8")
        d2 = fl.load_runs(tmp, tmp, str(bare))
        assert d2["absent"].get("ngoc") == "benchmark.ngoc.tsv" and d2["rows"][0][10] is None
        assert fl.py_build(d2)["model"]["plotted"] == 0

    # ---- no random data, fragments parse
    for name in fl.ASSETS:
        text = (ROOT / "assets" / "report" / name).read_text(encoding="utf-8")
        assert "Math.random" not in text, name
        assert text.rstrip().endswith(("</script>", "</style>")), name

    if not NODE:
        print("SKIPPED: node not found; JavaScript parity and hash tests not run")
        print("ALL LANDSCAPE FIGURE TESTS PASSED (python only)")
        return
    with tempfile.TemporaryDirectory() as tmp:
        for name in ("fig_landscape_core.html", "fig_landscape_ui.html"):
            body = re.sub(r"^<script>|</script>\s*$", "", (ROOT / "assets" / "report" / name).read_text(encoding="utf-8").strip())
            path = Path(tmp) / (name + ".js")
            path.write_text(body, encoding="utf-8")
            done = subprocess.run([NODE, "--check", str(path)], capture_output=True, text=True)
            assert done.returncode == 0, done.stderr

        # JS vs Python scene parity over several settings
        combos = [({}, None), ({"mode": "tools"}, None), ({"range": "zoom"}, None), ({"scale": "rank"}, None), ({"fx": 1, "fz": 1}, None),
                  ({"pareto_only": 1}, None), ({"size": "runtime", "colour": "runtime"}, None), ({"colour": "track", "labels": 1, "grid": 0}, None),
                  ({"z": "events", "y": "cprr", "range": "custom", "cx": [0.9, 1], "cy": [0, 0.8], "cz": [0.1, 1]}, None),
                  ({}, {"T:A": True, "O:drop": True, "O:cent": False}), ({"mode": "tools"}, {"O:sd": True})]
        datasets = [data, flat, miss, pareto]
        calls = [{"fn": "build", "data": ds, "vals": vals, "hidden": hid if hid is not None else fl.default_hidden()} for ds in datasets for vals, hid in combos]
        results = js(calls, tmp)
        for call, res in zip(calls, results):
            py = fl.py_build(call["data"], call["vals"], call["hidden"])
            jp = res["prims"]
            assert len(jp) == len(py["prims"]), (call["vals"], len(jp), len(py["prims"]))
            for a, b in zip(jp, py["prims"]):
                assert close(a, prim_view(b)), (call["vals"], a, prim_view(b))
            assert res["model"]["plotted"] == py["model"]["plotted"] and res["model"]["nFront"] == py["model"]["n_front"]
            assert res["model"]["nStack"] == py["model"]["n_stack"] and res["model"]["ideal"] == py["model"]["ideal"]
            assert [n[2] for n in res["model"]["notPlotted"]] == [n[2] for n in py["model"]["not_plotted"]]
            cam = r3.fit_camera({"prims": py["prims"]}, -32.0, 26.0)
            for k in ("yaw", "pitch", "zoom", "persp", "dist", "scale", "cx", "cy"):
                assert close(res["cam"][k], cam[k]), (k, res["cam"][k], cam[k])
            assert close(res["cam"]["target"], cam["target"])
            if call["vals"] == {} and call["data"] is data:
                svg = r3.render_prims({"prims": py["prims"]}, cam)
                assert len(re.findall(r"<circle|<polygon|<path", svg)) > 20
        assert results[0]["tips"] > 0

        # JS pure functions
        a = js([{"fn": "rankPos", "args": [[3, 1, 2, 2]]}, {"fn": "niceTicks", "args": [0.9, 1.0]}, {"fn": "csvText", "args": [["a", "b"], [["x,y", 'say "hi"'], [None, 1]]]},
                {"fn": "rampColour", "args": [0]}, {"fn": "rampColour", "args": [1]},
                {"fn": "encodeHash", "args": [fl.defaults(), fl.default_hidden(), "axes", None]},
                {"fn": "encodeHash", "args": [dict(fl.defaults(), x="precision", fz=1, range="custom", cx=[0.5, 1]), {"O:cent": False, "T:A": True}, "data", None]}], tmp)
        assert close(a[0], [1, 0, 0.5, 0.5]) and a[1]["d"] == 2
        assert a[2] == 'a,b\n"x,y","say ""hi"""\n,1\n', repr(a[2])
        assert a[3] == "#440154" and a[4] == "#fde725"
        assert a[5] == "#fig-landscape?", a[5]
        h = a[6]
        assert h.startswith("#fig-landscape?") and "lsx=precision" in h and "lsf=z" in h and "lsr=custom" in h and "lscx=0.5,1" in h and "lstab=data" in h and "lshide=T%3AA" in h and "lsshow=O%3Acent" in h, h
        back = js([{"fn": "decodeHash", "args": [h]}, {"fn": "decodeHash", "args": ["#plasmid-maps?msample=x"]}, {"fn": "decodeHash", "args": ["#fig-landscape?lsx=bogus&lsp=99&lstab=nope"]}], tmp)
        assert back[0]["vals"]["x"] == "precision" and back[0]["vals"]["fz"] == 1 and back[0]["vals"]["cx"] == [0.5, 1] and back[0]["tab"] == "data"
        assert back[0]["hidden"]["T:A"] is True and "O:cent" not in back[0]["hidden"]
        assert back[1]["vals"] == {} and back[1]["hidden"] is None                    # other sections' hashes are ignored
        assert "x" not in back[2]["vals"] and back[2]["vals"]["ps"] == 2.5 and back[2]["tab"] is None   # invalid values are dropped or clamped
        # JS CSV of the plotted points carries one row per plotted point
        csv_res = results[0]["model"]["csv"].strip().split("\n")
        assert len(csv_res) == 1 + results[0]["model"]["nPts"]
    print("ALL LANDSCAPE FIGURE TESTS PASSED")


if __name__ == "__main__":
    main()
