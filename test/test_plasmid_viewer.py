#!/usr/bin/env python3
"""
The interactive plasmid map viewer (assets/report/plasmid_viewer_*.html), tested without a browser.

The geometry, filters, zoom maths, label placement, URL hash and TSV export live in pure functions in plasmid_viewer_core.html. This test
loads that file into node (module.exports) and checks it against python/report_maps.py and python/report_svg.py:

  (a) parity     the JS arrow / sector / tick / GC / event / label output equals the python static SVG (numbers within 1e-3) for forward,
                 reverse and wrap-around genes, and for zoomed and rotated ranges (expected values computed independently here)
  (b) filters    class chips, hidden layers, the size filter, search and the tool selection give the expected element counts
  (c) view maths angle <-> bp round trip, region clamp, wrapped regions, zoom to the cursor, rotation
  (d) payload    every <script type='application/json'> parses, every static map has a payload, ids are unique, no '</script' leaks
  (e) labels     no two label boxes overlap on a crowded synthetic model, and nothing is lost silently
  (f) hash       encode -> decode -> state round trip
  (g) TSV        feature, tool and event exports
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

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))
sys.path.insert(0, HERE)

import report_maps as rm  # noqa: E402
import report_svg as sv  # noqa: E402
import test_report_maps as tm  # noqa: E402  (its model / gene / tool builders)

NODE = shutil.which("node")
CORE = os.path.join(ROOT, "assets", "report", "plasmid_viewer_core.html")
UI = os.path.join(ROOT, "assets", "report", "plasmid_viewer_ui.html")
STYLE = os.path.join(ROOT, "assets", "report", "plasmid_viewer_style.html")
SVG_NS = "{http://www.w3.org/2000/svg}"

RUNNER = r"""
const fs = require('fs'), vm = require('vm');
const html = fs.readFileSync(process.argv[2], 'utf8');
const body = html.replace(/^\s*<script>/, '').replace(/<\/script>\s*$/, '');
const sandbox = {module: {exports: {}}, console: console};
sandbox.globalThis = sandbox; sandbox.window = undefined;
vm.createContext(sandbox);
vm.runInContext(body, sandbox, {filename: 'plasmid_viewer_core.js'});
const PV = sandbox.module.exports;
const job = JSON.parse(fs.readFileSync(0, 'utf8'));
PV.configure(job.config || {});
const fn = new Function('PV', 'input', job.code);
process.stdout.write(JSON.stringify(fn(PV, job.input)));
"""


def js(code, input=None, config=None):
    """Run `code` (a function body with PV and input in scope) in node and return its JSON-able result."""
    with tempfile.TemporaryDirectory() as tmp:
        runner = os.path.join(tmp, "runner.js")
        with open(runner, "w", encoding="utf-8") as handle:
            handle.write(RUNNER)
        job = json.dumps({"code": code, "input": input, "config": config or rm.viewer_config()["core"]})
        done = subprocess.run([NODE, runner, CORE], input=job, capture_output=True, text=True, encoding="utf-8")
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip()[-1500:])
    return json.loads(done.stdout)


NUM = re.compile(r"-?\d+(?:\.\d+)?")


def close(a, b, tol=1e-3):
    """Two path strings or labels are equal when the text around the numbers is equal and every number is within tol."""
    if NUM.sub("#", a) != NUM.sub("#", b):
        return False
    xa, xb = [float(v) for v in NUM.findall(a)], [float(v) for v in NUM.findall(b)]
    return len(xa) == len(xb) and all(abs(p - q) <= tol + 1e-9 for p, q in zip(xa, xb))


def all_close(xs, ys, tol=1e-3):
    return len(xs) == len(ys) and all(close(a, b, tol) for a, b in zip(xs, ys))


def parse_parts(markup):
    return ET.fromstring("<svg xmlns='http://www.w3.org/2000/svg'>" + markup + "</svg>")


def paths(root, k=None, cls=None):
    out = []
    for e in root.iter(SVG_NS + "path"):
        if k is not None and e.get("data-k") != k:
            continue
        if cls is not None and cls not in (e.get("class") or "").split():
            continue
        out.append(e)
    return out


SCENE = """
const m = PV.normalize(input.payload);
const st = Object.assign(PV.defaultState(), input.state || {});
if (input.state && input.state.layers) { st.layers = Object.assign(PV.defaultState().layers, input.state.layers); }
const sc = PV.buildScene(m, st, {maxScale: 1.0});
return {parts: sc.partsSvg, labelsSvg: sc.labelsSvg, counts: sc.counts, ticks: sc.ticks.map(t => ({bp: t.bp, angle: t.angle, label: t.label, shown: t.shown})),
        placed: sc.labels.placed.map(p => ({text: p.text, x: p.x, y: p.y, anchor: p.anchor, box: p.box})), dropped: sc.labels.dropped.map(p => p.text),
        rings: sc.rings, step: sc.step, scale: sc.scale, ids: sc.ids, present: Object.keys(sc.present)};
"""


def scene(model, state=None):
    return js(SCENE, {"payload": rm.viewer_payload(model), "state": state or {}})


def main():
    ok = True

    def check(label, condition):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}")

    print("fragments")
    for path in (CORE, UI, STYLE):
        check(f"{os.path.basename(path)} exists and is a single block", os.path.isfile(path) and open(path, encoding="utf-8").read().count("</script>") <= 1)
    check("no fragment contains a closing script tag inside its code",
          all(open(p, encoding="utf-8").read().strip().endswith(("</script>", "</style>")) for p in (CORE, UI, STYLE)))
    if not NODE:
        print("  SKIP: node not found; the JS parity tests need it")
        print("ALL PLASMID VIEWER TESTS PASSED (python checks only)")
        return

    seq = "G" * 5000 + "C" * 5000
    print("(a) parity: JS geometry equals the python static SVG")
    mod = tm.model(seq=seq)
    svg, meta = rm.render_svg(mod, "m")
    py = ET.fromstring(svg)
    js_scene = scene(mod)
    jsr = parse_parts(js_scene["parts"])
    py_genes = [e.get("d") for e in paths(py, cls="gene")]
    js_genes = [e.get("d") for e in paths(jsr, k="g")]
    check("gene arrows: 7 shapes (forward, reverse, one wrapping the origin) with identical paths", len(py_genes) == 7 and all_close(py_genes, js_genes))
    py_cov = [e.get("d") for e in paths(py, cls="cov")]
    js_cov = [e.get("d") for e in paths(jsr, k="t") if "cov" in e.get("class").split()]
    check("tool coverage sectors (including the whole-circle ring)", len(py_cov) == 3 and all_close(py_cov, js_cov))
    py_ev = [(e.get("x1"), e.get("y1"), e.get("x2"), e.get("y2")) for e in py.iter(SVG_NS + "line") if "event" in (e.get("class") or "").split()]
    js_ev = [(e.get("x1"), e.get("y1"), e.get("x2"), e.get("y2")) for e in jsr.iter(SVG_NS + "line") if e.get("data-k") == "e"]
    check("structural event tick", len(py_ev) == 1 and all(close(" ".join(a), " ".join(b)) for a, b in zip(py_ev, js_ev)) and len(js_ev) == 1)
    py_tick = [(e.get("x1"), e.get("y1"), e.get("x2"), e.get("y2")) for e in py.iter(SVG_NS + "line") if e.get("stroke") == "#555"]
    js_tick = [(e.get("x1"), e.get("y1"), e.get("x2"), e.get("y2")) for e in jsr.iter(SVG_NS + "line") if e.get("data-k") == "tick"]
    step, ticks = sv.nice_ticks(10000)
    check("tick marks equal the python scale", len(py_tick) == len(ticks) == len(js_tick) and all(close(" ".join(a), " ".join(b)) for a, b in zip(py_tick, js_tick))
          and js_scene["step"] == step)
    check("tick labels are kb_label", [t["label"] for t in js_scene["ticks"]] == [sv.kb_label(p) for p in ticks])
    py_gc = [e.get("d") for e in paths(py, cls="gc-bars")] + [e.get("d") for e in paths(py, cls="skew-pos")] + [e.get("d") for e in paths(py, cls="skew-neg")]
    js_gc = [e.get("d") for e in paths(jsr, k="gc") if e.get("fill") != "transparent"] + [e.get("d") for e in paths(jsr, k="skew") if e.get("fill") != "transparent"]
    check("GC deviation and skew bars", all_close(py_gc, js_gc))
    check("ring radii equal python's meta['rings']", all(abs(js_scene["rings"][k][0] - v[0]) < 1e-6 and abs(js_scene["rings"][k][1] - v[1]) < 1e-6 for k, v in meta["rings"].items())
          and set(js_scene["rings"]) == set(meta["rings"]))
    py_lab = sorted((p["text"], round(p["x"], 2), round(p["y"], 2), p["anchor"]) for p in meta["placed"])
    js_lab = sorted((p["text"], round(p["x"], 2), round(p["y"], 2), p["anchor"]) for p in js_scene["placed"])
    check("label placement equals python (same labels, same positions)", py_lab == js_lab and len(py_lab) >= 4)

    big = tm.model(seq=seq, tools=[tm.tool(f"t{i}", [(0, 900 * (i + 1))], 0.1 * (i + 1), rank=i + 1) for i in range(10)])
    _, bmeta = rm.render_svg(big, "m")
    bjs = scene(big)
    check("the default tool selection equals the static map's 8-tool cap", sorted(bmeta["rings"]) == sorted(bjs["rings"]) and len(bjs["rings"]) == 12)
    nogc = tm.model()
    _, nmeta = rm.render_svg(nogc, "m")
    check("a plasmid without reference sequence has no GC rings in either", "gc" not in nmeta["rings"] and "gc" not in scene(nogc)["rings"])

    print("(a) parity: zoomed and rotated ranges (angles worked out here from the formula)")
    L, off, sweep = 10000, 10.0, 340.0
    CX, CY = rm.CX, rm.CY

    def ang(bp, start, span):
        return off + ((bp - start) % L) / span * sweep

    rin, rout = js_scene["rings"]["fwd"]
    rin_r, rout_r = js_scene["rings"]["rev"]
    zoom = js("""const m = PV.normalize(input.payload); const v = PV.makeView(m.length, input.start, input.span);
        const out = {}; m.genes.forEach(g => { const b = input.rings[PV.geneRing(g)]; out[g.name] = PV.geneShapes(v, g, b[0], b[1], PV.geneRing(g)).map(s => s.d); });
        const sc = PV.buildScene(m, Object.assign(PV.defaultState(), {view: {start: input.start, span: input.span}}), {maxScale: 1});
        return {shapes: out, ticks: sc.ticks.map(t => ({bp: t.bp, angle: t.angle})), step: sc.step};""",
              {"payload": rm.viewer_payload(mod), "start": 1500, "span": 2500, "rings": js_scene["rings"]})
    # repA 100-1000 is outside the view; blaTEM 2000-3000 (+) is fully inside; traI 4000-5000 is outside (view ends at 4000)
    exp_bla = sv.arrow_path(CX, CY, rin, rout, ang(2000, 1500, 2500), ang(3000, 1500, 2500), True)
    check("zoom 1500..4000: blaTEM (+) is a full arrow at the zoomed angles", len(zoom["shapes"]["blaTEM"]) == 1 and close(zoom["shapes"]["blaTEM"][0], exp_bla))
    check("zoom: genes outside the region are not drawn", zoom["shapes"]["repA"] == [] and zoom["shapes"]["tnpA"] == [])
    # clipped at the left edge: reverse gene 1000-2000 -> visible 1500..2000, the head (at its start) is cut, so a shaft only
    clip = js("""const m = PV.normalize(input.payload); m.genes.push({i: 99, start: 1000, end: 2000, strand: '-', name: 'revX', product: '', cls: 'other', kind: 'gene', ftype: ''});
        const v = PV.makeView(m.length, 1500, 2500); const b = input.rings.rev; return PV.geneShapes(v, m.genes[m.genes.length - 1], b[0], b[1], 'rev').map(s => s.d);""",
              {"payload": rm.viewer_payload(mod), "rings": js_scene["rings"]})
    exp_shaft = sv.sector_path(CX, CY, (rin_r + rout_r) / 2 - (rout_r - rin_r) / 2 * 0.62, (rin_r + rout_r) / 2 + (rout_r - rin_r) / 2 * 0.62, ang(1500, 1500, 2500), ang(2000, 1500, 2500))
    check("a reverse gene cut at the region start loses its head (shaft only)", len(clip) == 1 and close(clip[0], exp_shaft))
    wrap = js("""const m = PV.normalize(input.payload); const v = PV.makeView(m.length, 9000, 2500);
        const g = m.genes.filter(x => x.name === 'merA')[0]; const b = input.rings.fwd; return PV.geneShapes(v, g, b[0], b[1], 'fwd').map(s => s.d);""",
              {"payload": rm.viewer_payload(mod), "rings": js_scene["rings"]})
    exp_w = [sv.sector_path(CX, CY, (rin + rout) / 2 - (rout - rin) / 2 * 0.62, (rin + rout) / 2 + (rout - rin) / 2 * 0.62, ang(9500, 9000, 2500), ang(10000, 9000, 2500) - 0 if False else ang(9500, 9000, 2500) + 500 / 2500 * sweep),
             sv.arrow_path(CX, CY, rin, rout, ang(10000, 9000, 2500), ang(10000, 9000, 2500) + 500 / 2500 * sweep, True)]
    check("a gene wrapping the origin inside a region that wraps: shaft piece then arrow piece", len(wrap) == 2 and all_close(wrap, exp_w))
    st_, tk = sv.nice_ticks(2500, 12)
    first = math.ceil(1500 / st_) * st_
    expect_pos = [p for p in range(first, 1500 + 2500 + 1, st_)]
    check("zoomed ticks: multiples of the nice step across the region, at the zoomed angles", zoom["step"] == st_ and [t["bp"] for t in zoom["ticks"]] == [p % L for p in expect_pos]
          and all(abs(t["angle"] - ang(t["bp"], 1500, 2500)) < 1e-9 for t in zoom["ticks"]))
    rot = js("""const m = PV.normalize(input.payload); const v = PV.makeView(m.length, 2500, m.length); const g = m.genes.filter(x => x.name === 'blaTEM')[0];
        const b = input.rings.fwd; return PV.geneShapes(v, g, b[0], b[1], 'fwd').map(s => s.d);""", {"payload": rm.viewer_payload(mod), "rings": js_scene["rings"]})
    exp_r = sv.arrow_path(CX, CY, rin, rout, (2000 - 2500) % L / L * 360, ((2000 - 2500) % L + 1000) / L * 360, True)
    check("a rotated origin (starts at 2,500): blaTEM straddles the new origin and is split with a head on the end piece",
          len(rot) == 2 and close(rot[1], sv.arrow_path(CX, CY, rin, rout, 0, 500 / L * 360, True)) and close(rot[0], sv.sector_path(CX, CY, (rin + rout) / 2 - (rout - rin) / 2 * 0.62, (rin + rout) / 2 + (rout - rin) / 2 * 0.62, 9500 / L * 360, 360))
          and exp_r)

    print("(b) filters, layers, search and tool selection on a synthetic model")
    genes = [tm.gene("repA", 100, 1000, "+", "replication"), tm.gene("blaTEM", 2000, 3000, "+", "amr"), tm.gene("blaSHV", 3200, 3300, "+", "amr"),
             tm.gene("traI", 4000, 5000, "-", "transfer"), tm.gene("tnpA", 6000, 7000, "-", "mobile"), tm.gene("orfX", 8000, 8500, "-", "other"),
             tm.gene("merA", 9500, 500, "+", "metal"), tm.gene("IncFII", 0, 200, "", "replication", kind="feature", product="replicon"),
             tm.gene("sul1", 7500, 7900, "", "amr", kind="feature")]
    syn = tm.model(genes=genes, seq=seq)
    base = scene(syn)
    check("baseline counts: 3 forward genes (merA is 2 shapes), 3 reverse, 2 feature blocks", base["counts"]["fwd"] == 4 and base["counts"]["rev"] == 3 and base["counts"]["feat"] == 2 and base["counts"]["genes"] == 9
          and base["counts"]["tools"] == 2)
    check("the class chips found the 6 classes", sorted(base["present"]) == ["amr", "mobile", "metal", "other", "replication", "transfer"] or sorted(base["present"]) == sorted(["amr", "mobile", "metal", "other", "replication", "transfer"]))
    s1 = scene(syn, {"hideCls": {"amr": True}})
    check("hiding the AMR class chip removes 3 genes (blaTEM, blaSHV, sul1)", s1["counts"]["genes"] == base["counts"]["genes"] - 3)
    s2 = scene(syn, {"layers": {"rev": False}})
    check("hiding the - strand layer removes that ring and its 3 genes", "rev" not in s2["rings"] and s2["counts"]["rev"] == 0 and s2["counts"]["genes"] == 6)
    s3 = scene(syn, {"layers": {"feat": False, "gc": False, "skew": False}})
    check("hiding feature blocks, GC and skew frees their rings", "feat" not in s3["rings"] and "gc" not in s3["rings"] and "skew" not in s3["rings"] and s3["counts"]["feat"] == 0)
    s4 = scene(syn, {"minBp": 450})
    check("hide-small-features slider (450 bp) removes blaSHV (100), IncFII (200), sul1 (400)", s4["counts"]["genes"] == 6)
    s5 = scene(syn, {"toolsOn": ["tool_b"]})
    check("tool selection: one ring and the coverage of that tool only", s5["counts"]["tools"] == 1 and "t1" in s5["rings"] and "t0" not in s5["rings"])
    s6 = scene(syn, {"toolsOn": [], "layers": {"events": False}})
    check("no tools and no events: zero tool rings and zero event ticks", s6["counts"]["tools"] == 0 and s6["counts"]["events"] == 0)
    s7 = scene(syn, {"layers": {"events": False}})
    check("event ticks follow the Events layer", s7["counts"]["events"] == 0 and base["counts"]["events"] == 1)
    found = js("const m = PV.normalize(input.payload); return {bla: PV.searchGenes(m, 'bla').map(i => m.genes[i].name), none: PV.searchGenes(m, 'zzz'), prod: PV.searchGenes(m, 'replicon').map(i => m.genes[i].name), empty: PV.searchGenes(m, '  ')};",
               {"payload": rm.viewer_payload(syn)})
    check("search finds by name (prefix), by product, and nothing for nonsense or blank", sorted(found["bla"]) == ["blaSHV", "blaTEM"] and found["none"] == [] and found["prod"] == ["IncFII"] and found["empty"] == [])
    lab_amr = scene(syn, {"labelMode": "amr"})
    lab_none = scene(syn, {"labelMode": "none"})
    lab_all = scene(syn, {"labelMode": "all"})
    check("label modes: AMR only -> only AMR names; none -> 0; all >= key", {p["text"] for p in lab_amr["placed"]} <= {"blaTEM", "blaSHV", "sul1"} and len(lab_none["placed"]) == 0
          and len(lab_all["placed"]) + len(lab_all["dropped"]) >= len(base["placed"]) + len(base["dropped"]))
    cvd = js("""const m = PV.normalize(input.payload); const a = PV.buildScene(m, PV.defaultState()).partsSvg; const s = PV.defaultState(); s.cvd = true;
        return {d: a.indexOf('#D55E00') >= 0, c: PV.buildScene(m, s).partsSvg.indexOf('#332288') >= 0};""", {"payload": rm.viewer_payload(syn)})
    check("the colour-blind palette changes the fills", cvd["d"] and cvd["c"])
    cursor = js("""const m = PV.normalize(input.payload); const st = PV.defaultState(); const sc = PV.buildScene(m, st); const order = PV.cursorOrder(m, st, sc.ids);
        let c = null; const seen = []; for (let i = 0; i < order.length + 1; i++) { c = PV.neighbour(order, c, 1); seen.push(c.k + c.i); }
        return {n: order.length, first: seen[0], wrapped: seen[seen.length - 1] === seen[0], back: PV.neighbour(order, order[0], -1).k + PV.neighbour(order, order[0], -1).i};""",
                {"payload": rm.viewer_payload(syn)})
    check("keyboard cursor order wraps in both directions", cursor["n"] > 9 and cursor["wrapped"])

    print("(c) zoom and rotate maths")
    maths = js("""const L = 10000, out = {};
        const full = PV.makeView(L, 0, 0), z = PV.makeView(L, 2500, 2000);
        let worst = 0; [0, 1, 999, 5000, 9999].forEach(bp => { worst = Math.max(worst, Math.abs(PV.angleToBp(full, PV.bpToAngle(full, bp)) - bp)); });
        out.fullRound = worst;
        worst = 0; [2500, 3000, 3999.5, 4500].forEach(bp => { worst = Math.max(worst, Math.abs(PV.angleToBp(z, PV.bpToAngle(z, bp)) - bp)); });
        out.zoomRound = worst;
        out.outside = PV.bpToAngle(z, 100);
        out.gapClamp = [PV.angleToBp(z, 3, true), PV.angleToBp(z, 357, true), PV.angleToBp(z, 3, false)];
        out.region = [PV.clampRegion(L, 100, 5000), PV.clampRegion(L, 9000, 1000), PV.clampRegion(L, 5000, 5000), PV.clampRegion(L, 100, 120), PV.clampRegion(L, -500, 700), PV.clampRegion(L, 12000, 15000)];
        const wr = PV.makeView(L, 9000, 2500); out.wrapAngle = [PV.bpToAngle(wr, 9500), PV.bpToAngle(wr, 500), PV.bpToAngle(wr, 1500), PV.bpToAngle(wr, 2000)];
        const zi = PV.zoomAt(full, 90, 4); out.zoomIn = zi; out.zoomOut = PV.zoomAt(PV.makeView(L, 2500, 2500), 180, 0.001); out.zoomMax = PV.zoomAt(full, 10, 1e9);
        const bpUnder = PV.angleToBp(z, 100); const z3 = PV.zoomAt(z, 100, 2); const z4 = PV.makeView(L, z3.start, z3.span); out.cursorStays = PV.bpToAngle(z4, bpUnder);
        out.cursorSpan = z3.span;
        out.rotate = [PV.rotateView(full, 90), PV.rotateView(full, -90), PV.rotateView(z, 34)];
        out.origin = [PV.originAt(full, 2500), PV.originAt(z, 8000)];
        out.regionFor = [PV.regionFor(L, 3000, 3300, 0.2, 400), PV.regionFor(L, 9900, 100, 0.2, 400), PV.regionFor(L, 0, 9990, 0.2, 400)];
        out.clip = [PV.clipPiece(z, 1000, 3000), PV.clipPiece(z, 6000, 9000), PV.clipPiece(PV.makeView(L, 8000, 5000), 500, 1000)];
        out.lerp = [PV.lerpView(L, {start: 9500, span: 1000}, {start: 500, span: 1000}, 0.5), PV.lerpView(L, {start: 0, span: L}, {start: 100, span: 500}, 1)];
        return out;""")
    check("angle <-> bp round trip, full circle and zoomed (error < 1e-6 bp)", maths["fullRound"] < 1e-6 and maths["zoomRound"] < 1e-6)
    check("bp outside the zoomed region has no angle; the gap clamps to the ends", maths["outside"] is None and abs(maths["gapClamp"][0] - 2500) < 1e-9
          and abs(maths["gapClamp"][1] - 4500) < 1e-9 and maths["gapClamp"][2] is None)
    check("a region that wraps the origin: 9,500 and 500 are both inside, 2,000 is outside (view ends at 1,500)",
          maths["wrapAngle"][0] is not None and maths["wrapAngle"][1] is not None and maths["wrapAngle"][2] is not None and maths["wrapAngle"][3] is None
          and abs(maths["wrapAngle"][2] - 350.0) < 1e-9)
    r = maths["region"]
    check("region clamp: normal, wrapping (9000..1000 spans 2000), start==end is the whole circle, a tiny region grows to the 50 bp minimum, negatives and overshoot wrap",
          r[0]["span"] == 4900 and r[1]["span"] == 2000 and r[1]["start"] == 9000 and r[1]["end"] == 1000 and r[2]["span"] == 10000 and r[3]["span"] == 50
          and r[4]["start"] == 9500 and r[5]["start"] == 2000)
    check("zoom in 4x shrinks the span to a quarter; zoom out is capped at the molecule; zoom in is capped at 50 bp", maths["zoomIn"]["span"] == 2500 and maths["zoomOut"]["span"] == 10000
          and maths["zoomMax"]["span"] == 50)
    check("zoom to the cursor keeps the bp under the cursor under the cursor (100 degrees stays at 100 after a 2x zoom)", maths["cursorStays"] is not None and abs(maths["cursorStays"] - 100) < 1e-9 and maths["cursorSpan"] == 1000)
    check("rotating 90 degrees clockwise moves the origin back a quarter turn; the zoomed view moves by span * degrees / sweep", maths["rotate"][0]["start"] == 7500 and maths["rotate"][1]["start"] == 2500
          and abs(maths["rotate"][2]["start"] - ((2500 - 34 / 340 * 2000) % 10000)) < 1e-9)
    check("set origin: full circle puts the bp at the top, zoomed centres on it", maths["origin"][0]["start"] == 2500 and maths["origin"][1]["start"] == 7000)
    check("fly-to regions are padded, wrap, and become the whole circle when they would exceed it", maths["regionFor"][0]["span"] >= 400 and maths["regionFor"][1]["start"] > 9000 and maths["regionFor"][2]["span"] == 10000)
    cl = maths["clip"]
    check("a feature is clipped to the region: left cut, outside gives nothing, a piece crossing the region start", len(cl[0]) == 1 and cl[0][0]["cutL"] and not cl[0][0]["cutR"] and cl[1] == [] and len(cl[2]) >= 1)
    check("interpolating a view takes the short way round the origin", abs(maths["lerp"][0]["start"] - 0) < 1e-9 and maths["lerp"][1]["span"] == 500)

    print("(e) label placement on a crowded model")
    crowd = [tm.gene(f"bla{i}", 3000 + i * 5, 3004 + i * 5, "+", "amr") for i in range(60)] + [tm.gene(f"IS{i}", 500 + i * 40, 520 + i * 40, "-", "mobile") for i in range(25)]
    cs = scene(tm.model(genes=crowd, seq=seq))
    boxes = [p["box"] for p in cs["placed"]]
    overlaps = sum(1 for i in range(len(boxes)) for j in range(i + 1, len(boxes)) if not (boxes[i][2] <= boxes[j][0] or boxes[j][2] <= boxes[i][0] or boxes[i][3] <= boxes[j][1] or boxes[j][3] <= boxes[i][1]))
    check("no two label boxes overlap on the crowded model (60 AMR + 25 IS genes)", overlaps == 0 and len(boxes) > 10)
    check("every candidate is either placed or reported dropped", len(cs["placed"]) + len(cs["dropped"]) >= 60 and cs["dropped"])
    zs = js("""const m = PV.normalize(input.payload); const st = PV.defaultState(); st.view = {start: 2900, span: 500}; st.labelMode = 'all';
        const sc = PV.buildScene(m, st); const b = sc.labels.placed.map(p => p.box); let o = 0;
        for (let i = 0; i < b.length; i++) for (let j = i + 1; j < b.length; j++) if (!(b[i][2] <= b[j][0] || b[j][2] <= b[i][0] || b[i][3] <= b[j][1] || b[j][3] <= b[i][1])) o++;
        return {placed: b.length, overlaps: o, dropped: sc.labels.dropped.length, tickBoxes: sc.ticks.filter(t => t.shown).length};""", {"payload": rm.viewer_payload(tm.model(genes=crowd, seq=seq))})
    check("zoomed to 500 bp the labels are re-laid out and still do not overlap", zs["overlaps"] == 0 and zs["placed"] > 5)

    print("(f) URL hash round trip")
    hashed = js("""const m = PV.normalize(input.payload); const d = PV.defaultState(), st = PV.defaultState();
        st.sample = 'ecoli a&b'; st.plasmid = 'pA 1'; st.sel = {k: 'g', i: 12}; st.view = {start: 1234, span: 800}; st.layers.gc = false; st.layers.fwd = false; st.layers.labels = false;
        st.toolsOn = ['mob like', 'tool,two']; st.hideCls = {metal: true, other: true}; st.minBp = 150; st.labelMode = 'amr'; st.q = 'bla TEM'; st.toolSort = 'completeness'; st.order = 'tgc';
        st.thGene = 1.4; st.thTool = 0.8; st.cvd = true; st.labelSize = 1.3; st.legend = false; st.hl = 2; st.tab = 'tools';
        const h = PV.encodeHash(st, m); const back = PV.stateFromHash(PV.decodeHash(h), m);
        const h0 = PV.encodeHash(Object.assign(PV.defaultState(), {sample: 's', plasmid: 'p'}), m);
        const wrap = PV.defaultState(); wrap.sample = 's'; wrap.plasmid = 'p'; wrap.view = {start: 9000, span: 1000};
        return {h: h, back: back, st: st, h0: h0, bad: PV.decodeHash('#other'), only: PV.decodeHash('#plasmid-maps'), junk: PV.decodeHash('#plasmid-maps?sel=zz&view=a-b&tab=nope&lab=bad'),
                wrapH: PV.encodeHash(wrap, m), wrapBack: PV.stateFromHash(PV.decodeHash(PV.encodeHash(wrap, m)), m).view};""", {"payload": rm.viewer_payload(syn)})
    check("hash starts with #plasmid-maps? and carries sample, plasmid and selection", hashed["h"].startswith("#plasmid-maps?msample=") and "sel=g12" in hashed["h"] and "mplasmid=pA%201" in hashed["h"])
    keys = ["sample", "plasmid", "sel", "view", "layers", "toolsOn", "hideCls", "minBp", "labelMode", "q", "toolSort", "order", "thGene", "thTool", "cvd", "labelSize", "legend", "hl", "tab"]
    check("every field survives encode -> decode (including & , and spaces in names)", all(hashed["back"][k] == hashed["st"][k] for k in keys))
    check("a default state encodes to just sample and plasmid", hashed["h0"] == "#plasmid-maps?msample=s&mplasmid=p")
    check("foreign hashes are ignored, a bare #plasmid-maps is an empty state, junk values are dropped", hashed["bad"] is None and hashed["only"] == {} and "sel" not in hashed["junk"]
          and "viewRaw" not in hashed["junk"] and "tab" not in hashed["junk"] and "labelMode" not in hashed["junk"])
    check("a view ending exactly at the origin keeps its span", hashed["wrapBack"]["span"] == 1000 and hashed["wrapBack"]["start"] == 9000)

    print("(g) TSV export")
    mm = tm.model(genes=[tm.gene("repA", 100, 1000, "+", "replication", product="Rep\ttab\nnewline"), tm.gene("merA", 9500, 500, "+", "metal")], seq=seq,
                  tools=[dict(tm.tool("tool_a", [(0, 2500)], 0.25, "fragmented", 1, [{"pos": 2500, "type": "reference_deletion", "record": "r1", "detail": "x"}]),
                              outcome_detail={"bin": "b1", "recall": 0.25, "precision": 1.0, "bins": 2, "merged_with": "", "contamination": 0.0},
                              amr_rows=[{"gene": "blaTEM", "cls": "amr", "start": 2000, "end": 3000, "placement": "correct_plasmid", "replicon_ok": "yes", "record": "c1", "bin": "b1"}])])
    tsv = js("""const m = PV.normalize(input.payload); return {f: PV.tsv(PV.FEATURE_COLS, PV.featureRows(m)), t: PV.tsv(PV.TOOL_COLS, PV.toolRows(m)), e: PV.tsv(PV.EVENT_COLS, PV.eventRows(m)),
        one: PV.tsv(PV.FEATURE_COLS, PV.featureRows(m, [1]))};""", {"payload": rm.viewer_payload(mm)})
    flines = tsv["f"].rstrip("\n").split("\n")
    check("features TSV: header, one row per feature, 11 columns, tabs and newlines in a product are flattened",
          flines[0].split("\t") == ["sample", "plasmid", "name", "product", "class", "type", "feature_type", "start", "end", "length_bp", "strand"] and len(flines) == 3
          and all(len(x.split("\t")) == 11 for x in flines) and "Rep tab newline" in flines[1])
    check("features TSV: the wrapped gene has length 1,000 and the subset export has one row", flines[2].split("\t")[8:10] == ["500", "1000"] and len(tsv["one"].strip().split("\n")) == 2)
    tl = tsv["t"].rstrip("\n").split("\n")
    check("tools TSV: completeness, outcome, covered bp, AMR 0/1, events and the outcome detail",
          tl[0].split("\t")[:3] == ["sample", "plasmid", "tool"] and tl[1].split("\t")[2] == "tool_a" and tl[1].split("\t")[5] == "0.2500" and tl[1].split("\t")[6] == "fragmented"
          and tl[1].split("\t")[7] == "2500" and tl[1].split("\t")[10] == "1" and tl[1].split("\t")[11] == "0.25")
    el_ = tsv["e"].rstrip("\n").split("\n")
    check("events TSV: tool, type, position", el_[1].split("\t")[2:5] == ["tool_a", "reference_deletion", "2500"])

    print("(d) payload in the generated report")
    with tempfile.TemporaryDirectory() as tmp:
        res, data = os.path.join(tmp, "results"), os.path.join(tmp, "data")
        for sample in ("sA", "sB"):
            os.makedirs(os.path.join(res, sample, "visualization"))
            os.makedirs(os.path.join(data, sample))
            blocks = {"truth_plasmids": {"pS": {"molecule_type": "PLASMID", "length": 10000}, "pT": {"molecule_type": "PLASMID", "length": 700000}},
                      "circular_truth_plasmids": ["pS"],
                      "tools": {"mob": {"plasmid_recovery": {"pS": {"covered_intervals": [[0, 5000]], "covered_bp": 5000, "completeness": 0.5}}}}}
            with open(os.path.join(res, sample, "visualization", "alignment_blocks.json"), "w") as f:
                json.dump(blocks, f)
            tm.write(os.path.join(data, sample, "truth_proteins.tsv"), ["sequence_id", "start", "end", "strand", "feature_id", "gene", "product", "category"],
                     [["pS", "100", "900", "+", "f1", "repE</script><!--", "replication initiation protein", "replicon"]])
            with open(os.path.join(data, sample, "reference.fna"), "w") as f:
                f.write(">pS\n" + seq + "\n")
        scores = os.path.join(res, "scores.tsv")
        tm.write(scores, ["sample", "tool", "analysis_track"], [["sA", "mob", "short_read"], ["sB", "mob", "short_read"]])
        out = rm.inject(tm.PAGE, res, data, scores)
    section = out[out.index("id='plasmid-maps'"):out.index("id='recommendations'")]
    blocks_ = re.findall(r"<script type='application/json'([^>]*)>(.*?)</script>", section, re.S)
    payloads = []
    for attrs, text in blocks_:
        payloads.append((attrs, json.loads(text)))
    data_blocks = [(a, p) for a, p in payloads if "pv-data" in a]
    check("config and one payload per drawable plasmid parse as JSON (the over-size plasmid has none)", len(payloads) == 3 and len(data_blocks) == 2 and any("pv-config" in a for a, _ in payloads))
    ids = [p["id"] for _, p in data_blocks]
    check("payload ids are unique and equal the element ids", len(ids) == len(set(ids)) and all(f"id='pv-data-{i}'" in section for i in ids))
    static_ids = re.findall(r"<div class='rpt-map-body' id='(map-[^']+)'", section)
    check("every plasmid in the static fallback has a payload, and the fallback is kept", sorted(static_ids) == sorted(ids) and section.count("<svg") >= 2 and "class='pv-static' data-pv='1'" in section)
    check("a gene name that tries to close the script is escaped inside the JSON", "</script><!--" not in section.split("</script>")[0] and all("repE</script>" not in t for _, t in blocks_)
          and any("repE" in p["genes"][0]["n"] for _, p in data_blocks))
    check("the viewer shell, both scripts and the style are in the section once, in the right order",
          section.count("class='pv-root' id='pv-root' hidden") == 1 and section.count("root.PlasmidViewerCore = PV") == 1 and section.count("function savePrefs") == 1
          and section.index("id='pv-root'") < section.index("PlasBench plasmid viewer, pure core") < section.index("PlasBench plasmid viewer, DOM glue"))
    check("the index table is collapsed in a <details>, the first sample's static maps are open",
          "<details class='pv-index'>" in section and section.count("<details open>") == 1)
    check("the open-in-viewer links point at the viewer hash", "href='#plasmid-maps?msample=sA&amp;mplasmid=pS'" in section)
    payload = data_blocks[0][1]
    check("the payload is compact: genes, tools, gc windows and defaults", set(payload) >= {"id", "sample", "plasmid", "length", "genes", "tools", "gc"} and payload["tools"][0].get("d") == 1
          and len(json.dumps(payload)) < 8000)
    demo = os.path.join(ROOT, "results_demo")
    if os.path.isfile(os.path.join(demo, "ecoli_a", "visualization", "alignment_blocks.json")):
        out = rm.inject(tm.PAGE, demo, None, os.path.join(demo, "scores.tsv"))
        dblocks = re.findall(r"<script type='application/json' class='pv-data' id='pv-data-([^']+)'>(.*?)</script>", out, re.S)
        dstatic = re.findall(r"<div class='rpt-map-body' id='(map-[^']+)'", out)
        sizes = sum(len(t) for _, t in dblocks)
        check(f"demo: {len(dblocks)} payloads for {len(dstatic)} static maps, every id matches, all parse", len(dblocks) == len(dstatic) >= 1
              and sorted(i for i, _ in dblocks) == sorted(dstatic) and all(json.loads(t)["id"] == i for i, t in dblocks))
        check(f"demo: payload total {sizes:,} bytes is far below the viewer budget {rm.VIEWER_BUDGET_BYTES:,}", sizes < rm.VIEWER_BUDGET_BYTES // 5)
    else:
        print("  SKIP: results_demo is absent")
    old = rm.VIEWER_BUDGET_BYTES
    try:
        rm.VIEWER_BUDGET_BYTES = 10
        tiny = rm.build_section(os.path.join(ROOT, "results_demo"), None, os.path.join(ROOT, "results_demo", "scores.tsv")) if os.path.isdir(os.path.join(ROOT, "results_demo")) else None
    finally:
        rm.VIEWER_BUDGET_BYTES = old
    if tiny is not None:
        check("over the payload budget no viewer is emitted and every static map stays visible", "id='pv-root'" not in str(tiny) and "data-pv='1'" not in str(tiny) and "<svg" in str(tiny))

    print()
    if not ok:
        print("PLASMID VIEWER TESTS FAILED")
        sys.exit(1)
    print("ALL PLASMID VIEWER TESTS PASSED")


if __name__ == "__main__":
    main()
