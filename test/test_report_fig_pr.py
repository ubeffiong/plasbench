#!/usr/bin/env python3
"""The interactive precision-recall figure (python/report_fig_pr.py, assets/report/fig_pr_*.html).

Plain script. The maths is written twice (Python and JavaScript) and both are checked against values worked out by hand below.
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
import report_fig_pr as fp  # noqa: E402
import report_common as rc  # noqa: E402

NODE = shutil.which("node")


def close(a, b, tol=1e-9):
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(close(x, y, tol) for x, y in zip(a, b))
    if a is None or b is None:
        return a is b
    return abs(a - b) <= tol


# Hand-worked example 1: one curve, bases. Points (P, R): (1, 0) start, (1, .4), (.75, .6), (.5, .8).
CURVE = [[None, 0, 0, 100], [0.9, 40, 0, 60], [0.7, 60, 20, 40], [0.5, 80, 80, 20]]
# Hand-worked example 2: two samples. See the arithmetic in the comments of check_micro_macro.
S1 = [[None, 0, 0, 100], [0.9, 50, 0, 50], [0.5, 100, 100, 0]]
S2 = [[None, 0, 0, 300], [0.8, 150, 50, 150], [0.5, 300, 100, 0]]


def check_maths(P):
    """P is a namespace of the functions (python module or a node bridge returning plain data)."""
    pts = P["curve_points"](CURVE)
    assert close([q["p"] for q in pts], [1, 1, 0.75, 0.5]) and close([q["r"] for q in pts], [0, 0.4, 0.6, 0.8])
    # AP = 0*1 + .4*1 + .2*.75 + .2*.5 = .65 ; trapezoid = .4*1 + .2*.875 + .2*.625 = .7
    assert close(P["ap_step"](pts), 0.65), P["ap_step"](pts)
    assert close(P["auc_trapz"](pts), 0.7), P["auc_trapz"](pts)
    # F1: .5714286, .6666667, .6153846 -> optimal index 2 (threshold .7)
    assert close([q["f"] for q in pts][1:], [2 * .4 / 1.4, 2 / 3, 0.8 / 1.3]), [q["f"] for q in pts]
    assert P["f_optimal"](pts) == 2 and pts[2]["t"] == 0.7
    # iso-F1: f = .5 spans (1/3, 1) to (1, 1/3); f = .8 passes (.8, .8)
    iso = P["iso_f1"](0.5, 4)
    assert close(iso[0], [1 / 3, 1.0]) and close(iso[-1], [1.0, 1 / 3]), iso
    assert close(P["iso_f1"](0.8, 1)[0][0], 0.8 / 1.2)
    r = 0.8
    assert close(0.8 * r / (2 * r - 0.8), 0.8)
    # step vertices: (R0,P1) (R1,P1) (R1,P2) (R2,P2) (R2,P3) (R3,P3)
    v = P["step_vertices"](pts)
    assert close(v[0], [0, 1]) and close(v[1], [0.4, 1]) and close(v[2], [0.4, 0.75]) and close(v[3], [0.6, 0.75]) and close(v[-1], [0.8, 0.5]), v
    # micro: thresholds .9 .8 .5. At .9 -> s1 (50,0,50), s2 nothing (0,0,300): P 1, R 50/400. At .8 -> (50,0,50)+(150,50,150): P .8, R .5.
    # At .5 -> (100,100,0)+(300,100,0): P 2/3, R 1.  AP = .125 + .375*.8 + .5*2/3 = .758333...
    mi = P["micro_curve"]({"s1": S1, "s2": S2})
    assert close([q["r"] for q in mi], [0, .125, .5, 1]) and close([q["p"] for q in mi], [1, 1, .8, 2 / 3]), mi
    assert close(P["ap_step"](mi), .125 + .3 + 1 / 3)
    # macro: at .9 P (1+1)/2, R (.5+0)/2 ; at .8 P (1+.75)/2, R (.5+.5)/2 ; at .5 P (.5+.75)/2, R 1.  AP = .25 + .25*.875 + .5*.625 = .78125
    ma = P["macro_curve"]({"s1": S1, "s2": S2})
    assert close([q["r"] for q in ma], [0, .25, .5, 1]) and close([q["p"] for q in ma], [1, 1, .875, .625]), ma
    assert close(P["ap_step"](ma), .78125)
    assert close(ma[3]["f"], 2 * .625 / 1.625)          # F1 of the two means, not the mean of F1s
    # operating point: s1 (80, 20, 20), s2 (60, 0, 40): micro P 140/160, R 140/200 ; macro P (.8+1)/2, R (.8+.6)/2
    op = P["op_point"]([[80, 20, 20], [60, 0, 40], None], "micro")
    assert close([op["p"], op["r"], op["n"]], [140 / 160, 140 / 200, 2])
    op = P["op_point"]([[80, 20, 20], [60, 0, 40]], "macro")
    assert close([op["p"], op["r"]], [0.9, 0.7]) and close(op["f"], 2 * .9 * .7 / 1.6)
    assert P["op_point"]([[0, 0, 5]], "micro") is None      # nothing called: precision undefined, not 0 and not 1
    # prevalence: s1 plasmid 100 of 1000, s2 plasmid 300 of 600 -> micro 400/1600 = .25 ; macro (.1+.5)/2 = .3
    assert close(P["prevalence"]([[100, 1000], [300, 600]], "micro"), 0.25) and close(P["prevalence"]([[100, 1000], [300, 600]], "macro"), 0.3)
    assert close(P["fp_per_recovered"](6, 4), 1.5) and P["fp_per_recovered"](6, 0) is None
    # a sample with no truth plasmid bases is skipped, not scored as 0
    z = P["micro_curve"]({"s1": S1, "empty": [[None, 0, 0, 0]]})
    assert z[0]["n"] == 1


PY = {k: getattr(fp, k) for k in ("curve_points", "ap_step", "auc_trapz", "f_optimal", "iso_f1", "step_vertices", "micro_curve", "macro_curve",
                                  "op_point", "prevalence", "fp_per_recovered")}

RUNNER = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8').replace(/^[\s\S]*?<script>/, '').replace(/<\/script>\s*$/, '');
const m = {exports: {}}; new Function('module', src)(m); const PR = m.exports;
const job = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const out = job.map(j => {
  const f = {curve_points: a => PR.curvePoints(a), ap_step: PR.apStep, auc_trapz: PR.aucTrapz, f_optimal: PR.fOptimal, iso_f1: PR.isoF1,
    step_vertices: PR.stepVertices, micro_curve: PR.microCurve, macro_curve: PR.macroCurve, op_point: PR.opPoint, prevalence: PR.prevalence,
    fp_per_recovered: PR.fpPerRecovered, other: null}[j.fn];
  return f.apply(null, j.args);
});
process.stdout.write(JSON.stringify(out));
"""


def make_node_bridge(tmp):
    runner = Path(tmp) / "r.js"
    runner.write_text(RUNNER, encoding="utf-8")

    def call(fn, *args):
        job = Path(tmp) / "job.json"
        job.write_text(json.dumps([{"fn": fn, "args": list(args)}]), encoding="utf-8")
        done = subprocess.run([NODE, str(runner), str(ROOT / "assets/report/fig_pr_core.html"), str(job)], capture_output=True, text=True, encoding="utf-8")
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)[0]
    out = {}
    for name in PY:
        # the JS point objects use t/p/r/f/tp/fp/fn/n like the Python ones
        out[name] = (lambda n: (lambda *a: call(n, *a)))(name)
    return out


def write(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\t".join(header) + "\n" + "".join("\t".join(map(str, r)) + "\n" for r in rows), encoding="utf-8")


SCORE_HEADER = ["sample", "tool", "analysis_track", "TP_bp", "FP_bp", "FN_bp", "true_plasmid_count", "recovered_plasmid_count",
                "fp_predicted_record_count", "contig_tp", "contig_fp", "contig_fn", "contig_classification_status"]


def make_fixture(root, curves=True):
    """Two samples, one track: probtool (curve), hardtool (hard call), baseline_reference (reference marker); plus a second track."""
    root = Path(root)
    for s, plasmids, chrom in (("s1", [("pA", 100)], 900), ("s2", [("pB", 200), ("pC", 100)], 300)):
        write(root / s / "truth.tsv", ["sequence_id", "molecule_type", "length"], [("chr", "CHROMOSOME", chrom)] + [(i, "PLASMID", n) for i, n in plasmids])
    rows = [["s1", "probtool", "short_read", 80, 20, 20, 1, 1, 1, 2, 0, 0, "scored"], ["s2", "probtool", "short_read", 240, 40, 60, 2, 1, 1, 3, 1, 0, "scored"],
            ["s1", "hardtool", "short_read", 100, 0, 0, 1, 1, 0, 1, 0, 0, "scored"], ["s2", "hardtool", "short_read", 150, 150, 150, 2, 1, 3, 1, 1, 1, "scored"],
            ["s1", "baseline_reference", "short_read", 50, 100, 50, 1, 0, 2, "", "", "", "not_applicable"],
            ["s1", "longtool", "long_read", 90, 10, 10, 1, 1, 0, "", "", "", "not_applicable"]]
    write(root / "scores.tsv", SCORE_HEADER, rows)
    write(root / "benchmark.leaderboard.tsv", ["analysis_track", "tool", "task", "mean_pr_auc"],
          [("short_read", "probtool", "classification", "0.8100"), ("short_read", "hardtool", "reconstruction", ""), ("long_read", "longtool", "reconstruction", "")])
    if curves:
        hdr = ["threshold", "precision", "recall", "tp_bp", "fp_bp", "fn_bp"]
        write(root / "s1" / "probtool.pr_curve.tsv", hdr, [("inf", 1.0, 0.0, 0, 0, 100), ("0.9", 1.0, 0.5, 50, 0, 50), ("0.5", 0.5, 1.0, 100, 100, 0)])
        write(root / "s2" / "probtool.pr_curve.tsv", hdr, [("inf", 1.0, 0.0, 0, 0, 300), ("0.8", 0.75, 0.5, 150, 50, 150), ("0.5", 0.75, 1.0, 300, 100, 0)])
    return root


def check_python_data(tmp):
    res = make_fixture(Path(tmp) / "res")
    model = fp.build_model(str(res), None, str(res / "scores.tsv"))
    ids = [t["id"] for t in model["tracks"]]
    assert ids == ["long_read", "short_read"], ids                      # one entry per track, never pooled
    short = [t for t in model["tracks"] if t["id"] == "short_read"][0]
    names = [t["name"] for t in short["tools"]]
    assert names == ["hardtool", "probtool", "baseline_reference"], names   # baselines last
    prob = short["tools"][1]
    assert set(prob["curve"]) == {"s1", "s2"} and prob["curve"]["s1"][0] == [None, 0, 0, 100] and prob["pipeline_auc"] == 0.81
    hard = short["tools"][0]
    assert hard["curve"] is None and "no <sample>/<tool>.pr_curve.tsv" in hard["reason"]
    assert short["samples"]["s2"]["truth"] == [["pB", 200], ["pC", 100]] and short["samples"]["s2"]["plasmid_bp"] == 300 and short["samples"]["s2"]["total_bp"] == 600
    assert prob["op"]["s2"]["pl"] == [2, 1, 1] and prob["op"]["s1"]["c"] == [2, 0, 0]
    assert short["tools"][2]["op"]["s1"]["c"] is None                    # contig unit not scored: None, never 0
    st = fp.tool_stats(short, hard, "micro")                             # hardtool: fp records 0 + 3, recovered 1 + 1 -> 1.5
    assert close(st["fp_rec"], 1.5) and st["curve"] is None and st["ap"] is None
    st = fp.tool_stats(short, prob, "micro")                             # micro AP from the worked example 2
    assert close(st["ap"], .125 + .3 + 1 / 3)
    # F1 along the micro curve: .2222 (t .9), .6154 (t .8), .8 (t .5) -> F-optimal threshold .5
    assert st["fopt"]["t"] == 0.5 and close(st["fopt"]["f"], 0.8)
    # payload is finite and serialises
    text = json.dumps(model, allow_nan=False)
    assert "NaN" not in text and "Infinity" not in text
    return model


def check_static(tmp, model):
    for track in model["tracks"]:
        svg = fp.static_svg(track)
        ET.fromstring(svg)                                               # well-formed XML
        assert "<title" in svg and "polyline" in svg
    short = [t for t in model["tracks"] if t["id"] == "short_read"][0]
    root = ET.fromstring(fp.static_svg(short))
    ns = "{http://www.w3.org/2000/svg}"
    assert len(root.findall(f".//{ns}polyline")) >= 5 + 1                # 5 iso lines and the probtool curve
    # zoomed static view is well formed too
    ET.fromstring(fp.static_svg(short, "macro", fp.VIEW_ZOOM))


def check_section(tmp):
    res = make_fixture(Path(tmp) / "sec")
    page = "<html><body><section id='recommendations'><h2>R</h2></section></body></html>"
    page = page.replace("<nav", "<nav")
    out = fp.inject("<style></style><nav><a href='#recommendations'>Recommendations</a></nav>" + page, str(res), None, str(res / "scores.tsv"))
    assert "id='fig-pr'" in out and out.index("id='fig-pr'") < out.index("id='recommendations'") and "href='#fig-pr'" in out
    payload = re.search(r"<script type='application/json' id='pr-data'>(.*?)</script>", out, re.S).group(1)
    assert "</" not in payload and isinstance(json.loads(payload), dict)
    ids = re.findall(r"\bid='([^']+)'", out)
    assert len(ids) == len(set(ids)), [i for i in ids if ids.count(i) > 1]
    assert "no curve:" in out and "pr-static" in out
    # Not run cases
    none = fp.inject("<section id='recommendations'></section>", str(res), None, str(res / "missing.tsv"))
    assert "Not run:" in none and "scores.tsv" in none
    nocurve = make_fixture(Path(tmp) / "nocurve", curves=False)
    page2 = fp.inject("<section id='recommendations'></section>", str(nocurve), None, str(nocurve / "scores.tsv"))
    assert "Not run:" in page2 and "no tool wrote a pr_curve.tsv" in page2
    # the demo-like case still draws operating points
    assert "<polyline" in page2 and "<path" in page2
    return out


def check_real_build():
    demo = ROOT / "results_demo"
    scores = demo / "scores.tsv"
    if not scores.is_file():
        print("  skipped real build check: results_demo is absent")
        return
    sec = str(fp.build_section(str(demo), None, str(scores)))
    assert "id='fig-pr'" in sec and "Not run:" in sec and "no curve:" in sec     # demo has no pr_curve files: operating points only
    assert "mob_like" in sec
    payload = re.search(r"id='pr-data'>(.*?)</script>", sec, re.S).group(1)
    model = json.loads(payload)
    assert [t["id"] for t in model["tracks"]] == ["short_read"]
    print(f"  real build ok: section {len(sec):,} bytes, payload {len(payload):,} bytes")


def check_js_syntax(tmp, section_html):
    sys.path.insert(0, str(ROOT / "test"))
    import test_report_javascript as tj
    for name in ("fig_pr_core.html", "fig_pr_ui.html"):
        text = (ROOT / "assets/report" / name).read_text(encoding="utf-8")
        assert tj.unterminated_string(text) is None, (name, tj.unterminated_string(text))   # the report's own string-break checker
        assert "Math.random" not in text
    if not NODE:
        return
    for name in ("fig_pr_core.html", "fig_pr_ui.html"):
        body = (ROOT / "assets/report" / name).read_text(encoding="utf-8")
        assert body.rstrip().endswith("</script>")
        js = re.sub(r"^\s*<script>", "", body).rsplit("</script>", 1)[0]
        p = Path(tmp) / (name + ".js")
        p.write_text(js, encoding="utf-8")
        done = subprocess.run([NODE, "--check", str(p)], capture_output=True, text=True)
        assert done.returncode == 0, name + ": " + done.stderr
    css = (ROOT / "assets/report/fig_pr_style.html").read_text(encoding="utf-8")
    assert css.rstrip().endswith("</style>")


def check_hash(tmp):
    if not NODE:
        return
    code = r"""
const fs=require('fs');const src=fs.readFileSync(process.argv[2],'utf8').replace(/^[\s\S]*?<script>/,'').replace(/<\/script>\s*$/,'');
const m={exports:{}};new Function('module',src)(m);const PR=m.exports;
const S={track:'short_read',unit:'contigs',avg:'macro',samples:true,linear:true,iso:false,base:true,ops:true,view:[0.5,1,0.5,1],hidden:['a','b'],only:'',tab:'tools'};
const h=PR.encodeHash(S);const d=PR.decodeHash(h);
console.log(JSON.stringify({h:h,d:d,bad:PR.decodeHash('#fig-pr?prx=1,2,x,4&pru=weird'),other:PR.decodeHash('#plasmid-maps?x=1'),ticks:PR.niceTicks(0,1),zoom:PR.clampView([2,-1,0.5,0.5])}));
"""
    p = Path(tmp) / "h.js"
    p.write_text(code, encoding="utf-8")
    done = subprocess.run([NODE, str(p), str(ROOT / "assets/report/fig_pr_core.html")], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    r = json.loads(done.stdout)
    assert r["h"].startswith("#fig-pr?prt=short_read&pru=contigs&pra=macro&prs=1&prl=1&pri=0")
    d = r["d"]
    assert d["track"] == "short_read" and d["unit"] == "contigs" and d["avg"] == "macro" and d["samples"] is True and d["iso"] is False
    assert d["view"] == [0.5, 1, 0.5, 1] and d["hidden"] == ["a", "b"] and d["tab"] == "tools"
    assert r["bad"] == {} and r["other"] == {}
    assert r["ticks"] == [0, 0.2, 0.4, 0.6, 0.8, 1], r["ticks"]
    assert r["zoom"][0] == 0 and r["zoom"][1] == 1


def main():
    check_maths(PY)
    print("  python maths ok")
    with tempfile.TemporaryDirectory(prefix="pr_fig_") as tmp:
        model = check_python_data(tmp)
        check_static(tmp, model)
        section = check_section(tmp)
        check_js_syntax(tmp, section)
        if NODE:
            check_maths(make_node_bridge(tmp))
            print("  javascript maths ok and identical to python")
            check_hash(tmp)
        else:
            print("  SKIPPED: node not found (javascript parity, syntax and hash tests)")
    check_real_build()
    print("ALL REPORT PRECISION-RECALL FIGURE TESTS PASSED")


if __name__ == "__main__":
    sys.exit(main())
