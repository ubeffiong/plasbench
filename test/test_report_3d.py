#!/usr/bin/env python3
"""The 3D report views (python/report_3d.py, assets/report/viz3d_*.html).

Plain script. Node runs the JavaScript engine and scene builders; Python holds the same projection math for the static
no-JS/print fallback, and the two are compared number by number (1e-6). Expected values below are worked out by hand.
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
import report_scoring_spec as rss  # noqa: E402

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
const core = load(root + '/assets/report/viz3d_core.html'), views = load(root + '/assets/report/viz3d_views.html');
const libs = {core, views};
process.stdout.write(JSON.stringify(job.map(j => libs[j.lib][j.fn].apply(null, j.args))));
"""


def js(calls, tmp):
    """calls = [(lib, fn, args)] -> list of results, evaluated by node."""
    job = Path(tmp) / "job.json"
    runner = Path(tmp) / "runner.js"
    runner.write_text(RUNNER, encoding="utf-8")
    job.write_text(json.dumps([{"lib": a, "fn": b, "args": c} for a, b, c in calls]), encoding="utf-8")
    done = subprocess.run([NODE, str(runner), str(ROOT), str(job)], capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def close(a, b, tol=1e-6):
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(close(x, y, tol) for x, y in zip(a, b))
    return abs(a - b) <= tol


def write(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\t".join(header) + "\n" + "".join("\t".join(map(str, r)) + "\n" for r in rows), encoding="utf-8")


def roles(scene):
    out = {}
    for p in scene["prims"]:
        out[p.get("role", "?")] = out.get(p.get("role", "?"), 0) + 1
    return out


# ------------------------------------------------------------------------------------------------ synthetic data
def bars_inputs():
    lb = [{"analysis_track": "short_read", "task": "reconstruction", "tool": "A", "mean_f1": "0.9", "mean_contig_f1_bp": "0.8",
           "mean_contig_mcc_bp": "0.7", "mean_contig_bin_f1_bp": "0.6"},
          {"analysis_track": "short_read", "task": "classification", "tool": "B", "mean_f1": "0.5", "mean_contig_f1_bp": "0.4",
           "mean_contig_mcc_bp": "", "mean_contig_bin_f1_bp": "0.3"}]
    scores = [{"sample": "s1", "tool": "A", "contigs_ambiguous_bp": "1500", "contigs_unplaced_bp": "1200"},
              {"sample": "s2", "tool": "A", "contigs_ambiguous_bp": "500", "contigs_unplaced_bp": "0"}]
    xc = [{"sample": "s1", "tool": "A", "n_contigs": "4", "n_low_information": "0", "label_agreement": "1.0", "label_kappa": "1.0",
           "primary_f1_bp": "0.8", "independent_f1_bp": "0.78", "delta_f1_bp": "0.02", "primary_mcc_bp": "0.7",
           "independent_mcc_bp": "0.69", "delta_mcc_bp": "0.01", "status": "agree", "differing_contigs": ""},
          {"sample": "s2", "tool": "A", "n_contigs": "3", "n_low_information": "1", "label_agreement": "0.7", "label_kappa": "0.4",
           "primary_f1_bp": "0.8", "independent_f1_bp": "0.5", "delta_f1_bp": "0.3", "primary_mcc_bp": "0.7",
           "independent_mcc_bp": "0.2", "delta_mcc_bp": "0.5", "status": "disagree", "differing_contigs": "c2"}]
    return lb, scores, xc


def recs_inputs():
    evaluation = [dict(profile=p, n_isolates=3, n_folds=2, mean_regret="0.05", p95_regret="0.1", near_optimal_rate="0.67",
                       top1_rate="0.5", mean_kendall_tau="0.3", single_best_mean_regret="0.1", oracle_gap="0.1", gap_closed="0.5",
                       floor_flagged=1, verdict="recommender_adds_value") for p in ("f1", "f2")]

    def row(profile, sample, rt, rs, best, ss, near, floor="no"):
        return dict(profile=profile, sample=sample, held_out_study="st", organism="E. coli", recommended_tool=rt, recommended_score=rs,
                    predicted_score=rs, best_tool="x", best_score=best, regret=round(best - rs, 4), near_optimal=near, single_best_tool="y",
                    single_best_score=ss, single_best_regret=round(best - ss, 4), floor_flag=floor, basis="model")

    regret = [row("f1", "i1", "t1", 0.8, 1.0, 0.7, "no", "yes"), row("f1", "i2", "t2", 1.0, 1.0, 0.9, "yes"),
              row("f1", "i3", "t2", 0.95, 1.0, 0.95, "yes"), row("f2", "i1", "t1", 0.5, 0.6, 0.5, "yes"),
              row("f2", "i2", "t1", 0.6, 0.6, 0.5, "yes")]
    verdict = {"verdict": "recommender_adds_value", "note": "closes part of the gap", "oracle_gap": "0.1", "gap_closed": "0.5"}
    warnings = [dict(warning="w", n_evaluated=3, n_fired=1, n_failed=1, firing_rate="0.3", ppv="0.5", sensitivity="0.5",
                     n_could_not_be_applied=0, status="assessed")]
    taxon = [dict(level="genus", held_out_group="Klebsiella", n_isolates=2, n_training_isolates=4, mean_regret="0.05",
                  single_best_mean_regret="0.1", near_optimal_rate="0.7", gap_closed="0.5", status="assessed", note="")]
    return evaluation, regret, verdict, warnings, taxon


def write_rings(root):
    s = root / "s1"
    write(s / "truth.tsv", ["sequence_id", "molecule_type", "length"], [["chr", "CHROMOSOME", 5000], ["pA", "PLASMID", 1000], ["pB", "PLASMID", 1]])
    write(s / "truth_circular.tsv", ["sequence_id"], [["pA"]])
    head = ["sample", "tool", "copy_id", "gene_name", "gene_class", "sequence_id", "start", "end", "covering_record", "assigned_bin",
            "matched_plasmid", "placement", "replicon_type_correct"]

    def r(tool, gene, cls, pid, a, b, place):
        return ["s1", tool, "", gene, cls, pid, a, b, "rec1" if place != "not_recovered" else "", "bin1", "pA", place, "yes"]
    for tool, places in (("toolX", ("correct_plasmid", "wrong_plasmid", "correct_plasmid")),
                         ("toolY", ("not_recovered", "shared_contig", "unassigned_contig"))):
        write(s / f"{tool}.amr_placement.tsv", head, [r(tool, "g1", "ESBL", "pA", 100, 200, places[0]),
                                                       r(tool, "g2", "other", "pA", 900, 100, places[1]),
                                                       r(tool, "g3", "ESBL", "pB", 0, 1, places[2])])


def main():
    if not NODE:
        print("SKIPPED: node is not installed, so the JavaScript parity tests cannot run here (they run wherever node exists)")
        return
    with tempfile.TemporaryDirectory() as tmpname:
        tmp = Path(tmpname)

        # ---------------------------------------------------------------- 1. projection: hand-worked values
        cam = r3.make_cam(yaw=0, pitch=0, persp=0, scale=10, cx=100, cy=100)
        assert close(r3.project([1, 2, 3], cam), [110, 80, 3, 1]), r3.project([1, 2, 3], cam)
        cam90 = r3.make_cam(yaw=90, pitch=0, persp=0, scale=10, cx=100, cy=100)   # x1 = z, depth = -x
        assert close(r3.project([1, 2, 3], cam90), [130, 80, -1, 1]), r3.project([1, 2, 3], cam90)
        campitch = r3.make_cam(yaw=0, pitch=90, persp=0, scale=10, cx=0, cy=0)    # looking straight down: world z -> screen y
        assert close(r3.project([0, 0, 2], campitch)[:2], [0, 20], 1e-9)
        camp = r3.make_cam(yaw=0, pitch=0, persp=1, dist=10, scale=10, cx=0, cy=0)  # point 5 units nearer: factor 10/(10-5)
        assert close(r3.project([1, 0, 5], camp)[:2], [20, 0]) and close(r3.project([1, 0, 5], camp)[3], 2.0)
        print("  PASS: Python projection matches hand-worked values (ortho, yaw 90, top view, perspective)")

        # ---------------------------------------------------------------- 2. parity JS vs Python
        pts = [[0, 0, 0], [1, 2, 3], [-2.5, 4, 1.25], [7, 0.5, -3], [3.3, 1.1, 9.9], [-4, -1, -6], [0.001, 3, 0.002], [10, 10, 10]]
        cams = [r3.make_cam(), r3.make_cam(yaw=0, pitch=88, persp=1, dist=14, scale=37.5, cx=450, cy=290, target=[1, 2, 3]),
                r3.make_cam(yaw=137, pitch=-33, persp=0, scale=61.2, cx=12, cy=-4, zoom=1.7, target=[-3, 1, 2]),
                r3.make_cam(yaw=-211, pitch=63.3, persp=1, dist=9.5, scale=20, cx=0, cy=0, zoom=0.6, target=[0.5, 0.5, 0.5]),
                r3.make_cam(yaw=45, pitch=45, persp=1, dist=30, scale=100, cx=900, cy=580, target=[2, 2, 2])]
        calls = [("core", "project", [p, c]) for c in cams for p in pts]
        calls += [("core", "faceVisible", [f[1], c]) for c in cams for f in r3.box_faces(0, 1, 0, 2, 0, 1)]
        got = js(calls, tmp)
        n = 0
        for c in cams:
            for p in pts:
                assert close(got[n], r3.project(p, c)), (p, c, got[n], r3.project(p, c))
                n += 1
        for c in cams:
            for f in r3.box_faces(0, 1, 0, 2, 0, 1):
                assert got[n] == r3.face_visible(f[1], c), (f[0], c)
                n += 1
        misc = js([("core", "bpToDeg", [250, 1000]), ("core", "bpToDeg", [-250, 1000]), ("core", "ringXZ", [3, 90]), ("core", "ringXZ", [3, 0]),
                   ("core", "geneSpan", [900, 100, 1000]), ("core", "geneSpan", [100, 200, 1000]), ("core", "geneSpan", [0, 1, 1]),
                   ("core", "niceStep", [90000, 8]), ("core", "niceStep", [1, 8]), ("core", "shadeHex", ["#009E73", 0.28]),
                   ("core", "shadeHex", ["#E69F00", -0.3]), ("core", "bpLabel", [20000]), ("core", "bpLabel", [500])], tmp)
        expect = [r3.bp_to_deg(250, 1000), r3.bp_to_deg(-250, 1000), r3.ring_xz(3, 90), r3.ring_xz(3, 0), r3.gene_span(900, 100, 1000),
                  r3.gene_span(100, 200, 1000), r3.gene_span(0, 1, 1), r3.nice_step(90000), r3.nice_step(1), r3.shade_hex("#009E73", 0.28),
                  r3.shade_hex("#E69F00", -0.3), r3.bp_label(20000), r3.bp_label(500)]
        for a, b in zip(misc, expect):
            if isinstance(a, dict):
                assert close([a["mid"], a["span"]], [b["mid"], b["span"]]), (a, b)
            else:
                assert (a == b) if isinstance(a, str) else close(a, b), (a, b)
        print(f"  PASS: JS and Python projection agree to 1e-6 ({len(cams) * len(pts)} points x {len(cams)} cameras), face culling, ring helpers")

        # ---------------------------------------------------------------- 3. ring angle math (hand-worked)
        assert r3.bp_to_deg(250, 1000) == 90.0 and r3.bp_to_deg(-250, 1000) == 270.0       # position 0 at top, clockwise
        assert r3.bp_to_deg(5, 1) == 0.0 and r3.bp_to_deg(0, 1) == 0.0                     # plasmid length 1: always the origin
        assert r3.bp_to_deg(10, 0) == 0.0                                                  # unknown length does not crash
        x, z = r3.ring_xz(3, 90)
        assert close([x, z], [3, 0], 1e-9) and close(r3.ring_xz(3, 0), [0, -3], 1e-9) and close(r3.ring_xz(3, 180), [0, 3], 1e-9)
        wrap = r3.gene_span(900, 100, 1000)                                                # crosses the origin: 200 bp centred on 0
        assert wrap == {"mid": 0.0, "span": 200} or (close(wrap["mid"], 0) and close(wrap["span"], 200)), wrap
        plain = r3.gene_span(100, 200, 1000)
        assert close(plain["mid"], 150) and close(r3.bp_to_deg(plain["mid"], 1000), 54)
        whole = r3.gene_span(0, 1, 1)
        assert whole["span"] == 1 and whole["mid"] == 0
        assert r3.nice_step(90000) == 20000 and r3.nice_step(1) == 1   # 11250 raw -> 1.125 e4 -> 2 e4
        print("  PASS: ring angle math, wrap-around gene (900-100 of 1000 bp is centred on 0 degrees), plasmid length 1")

        # ---------------------------------------------------------------- 4. depth ordering and culling for a known scene
        near_box = r3.box_faces(-1, 1, 0, 1, 4, 6)       # nearer to the viewer (larger z)
        far_box = r3.box_faces(-1, 1, 0, 1, -6, -4)
        prims = ([{"k": "poly", "pts": f[1], "role": "near", "cull": True} for f in near_box]
                 + [{"k": "poly", "pts": f[1], "role": "far", "cull": True} for f in far_box])
        ortho = r3.make_cam(yaw=0, pitch=0, persp=0, scale=10, cx=0, cy=0)
        order = [row[3]["role"] for row in r3.sort_prims(prims, ortho)]
        assert order == ["far"] * 6 + ["near"] * 6, order            # painter's algorithm: far first, near last
        layered = [{"k": "text", "p": [0, 0, -9], "t": "label", "layer": 2, "role": "t"}] + prims
        assert r3.sort_prims(layered, ortho)[-1][3]["role"] == "t", "labels (layer 2) must draw after geometry"
        visible = [f[0] for f in near_box if r3.face_visible(f[1], ortho)]
        assert visible == ["front"], visible                         # straight on: only the front face
        visible = [f[0] for f in r3.box_faces(0, 1, 0, 1, 0, 1) if r3.face_visible(f[1], r3.make_cam(yaw=-30, pitch=30, persp=0))]
        assert sorted(visible) == ["front", "left", "top"] or sorted(visible) == ["front", "right", "top"] or len(visible) == 3, visible
        jsorder = js([("core", "sortPrims", [prims, ortho])], tmp)[0]
        assert [row["p"]["role"] for row in jsorder] == order, "JS and Python sort differently"
        print("  PASS: faces sort far-to-near, labels last; back faces are culled (1 visible face straight on, 3 at the default angle)")

        # ---------------------------------------------------------------- 5. scene builders: counts, geometry, filters (JS and Python)
        lb, scores, xc = bars_inputs()
        bars = r3.bars_payload(lb, scores, xc)
        assert bars and len(bars["tools"]) == 2 and bars["shared"] == 2000 and bars["unassigned"] == 1200
        assert bars["tools"][0]["xc"]["dis"] == 1 and bars["tools"][0]["xc"]["n"] == 2 and bars["tools"][1]["xc"] is None
        assert close(bars["tools"][0]["xc"]["f1"], 0.64) and bars["tools"][1]["v"]["contig_mcc"] is None
        pb = r3.build_bars(bars)
        jb = js([("views", "buildBars", [bars, {}])], tmp)[0]
        assert roles(pb)["bar"] == 7 * 6 and roles(pb)["na"] == 1 and roles(pb)["xc"] == 2, roles(pb)   # 7 bars of 6 faces, 1 n/a slab, 2 markers
        assert roles(jb) == roles(pb), (roles(jb), roles(pb))
        barfaces = [p for p in pb["prims"] if p.get("role") == "bar"]
        heights = [max(q[1] for f in barfaces[i:i + 6] for q in f["pts"]) for i in range(0, len(barfaces), 6)]
        floors = [min(q[1] for f in barfaces[i:i + 6] for q in f["pts"]) for i in range(0, len(barfaces), 6)]
        assert close(heights, [3.6, 3.2, 2.8, 2.4, 2.0, 1.6, 1.2]), heights      # height = value * 4, in tool-then-layer order
        assert all(f == 0 for f in floors), floors                                 # every bar stands on the floor (y = 0)
        assert close(heights[4] / heights[0], 0.5 / 0.9)                           # proportional to the value
        filt = [("views", "buildBars", [bars, {"hidden": {"L:contig_f1": True}}]), ("views", "buildBars", [bars, {"hidden": {"xc": True}}]),
                ("views", "buildBars", [bars, {"group": "short_read / classification"}]), ("views", "buildBars", [bars, {"layer": "contig_mcc"}])]
        fj = js(filt, tmp)
        assert roles(fj[0])["bar"] == 5 * 6 and roles(r3.build_bars(bars, hidden={"L:contig_f1"}))["bar"] == 30   # one layer hidden: 3 layers x 2 tools - 1 n/a
        assert "xc" in roles(fj[0]) and roles(fj[0])["xc"] == 1                                                  # only the MCC marker is left
        assert "xc" not in roles(fj[1]) and "xc" not in roles(r3.build_bars(bars, hidden={"xc"}))
        assert roles(fj[2])["bar"] == 3 * 6 and roles(r3.build_bars(bars, group="short_read / classification"))["bar"] == 18   # tool B: 3 of 4 layers scored
        assert roles(fj[3])["bar"] == 1 * 6 and roles(fj[3])["na"] == 1 and roles(r3.build_bars(bars, layer="contig_mcc"))["bar"] == 6
        for scene in (jb, fj[0]):
            ids = {p["id"] for p in scene["prims"] if p.get("id") is not None}
            assert ids <= set(scene["tips"]), "every hoverable mark needs a tooltip"
        flagged = [t for t in jb["tips"].values() if t["t"].startswith("Independent")]
        assert any("DISAGREE" in dict(t["rows"]).get("Status", "") for t in flagged), "disagreement must be flagged in the tooltip text"
        assert r3.bars_payload([{"tool": "A", "mean_f1": "0.9"}], [], []) is None
        print("  PASS: bar geometry (base on the floor, height proportional), counts, legend/layer/track filters, cross-check flag")

        evaluation, regret, verdict, warnings, taxon = recs_inputs()
        recs = r3.recs_payload(evaluation, regret, verdict, warnings, taxon)
        assert [p["p"] for p in recs["profiles"]] == ["f1", "f2"] and len(recs["iso"]["f1"]) == 3 and len(recs["iso"]["f2"]) == 2
        pr = r3.build_recs(recs)
        jr = js([("views", "buildRecs", [recs, {"profile": "f1"}]), ("views", "buildRecs", [recs, {"profile": "f2"}]),
                 ("views", "buildRecs", [recs, {"profile": "f1", "hidden": {"S:oracle": True}}])], tmp)
        assert roles(pr)["bar"] == 3 * 3 * 6 and roles(pr)["ribbon"] == 3 * 2 and roles(pr)["near"] == 3 and roles(pr)["floorflag"] == 1, roles(pr)
        assert roles(pr)["regret"] == 5, roles(pr)            # i1: rec+single, i2: single, i3: rec+single
        assert roles(jr[0]) == roles(pr), (roles(jr[0]), roles(pr))
        assert roles(jr[1])["bar"] == 2 * 3 * 6 and roles(r3.build_recs(recs, "f2"))["bar"] == 36      # profile selector changes the scene
        assert roles(jr[2])["bar"] == 3 * 2 * 6 and roles(jr[2])["ribbon"] == 3 and roles(r3.build_recs(recs, "f1", {"S:oracle"}))["ribbon"] == 3
        tips = jr[0]["tips"]
        assert dict(tips["s|0|rec"]["rows"])["Tool picked"] == "t1" and dict(tips["s|0|rec"]["rows"])["Near-optimal"] == "no"
        assert dict(tips["s|0|rec"]["rows"])["Floor flagged"] == "yes" and dict(tips["s|0|rec"]["rows"])["Regret"] == "0.2000"
        assert r3.build_recs(r3.recs_payload(evaluation, [], verdict, [], []))["prims"] == [], "no regret table: nothing to draw"
        # regret gap segment spans rec score to oracle score at the recommender row
        seg = [p for p in pr["prims"] if p.get("role") == "regret"][0]
        assert close([seg["pts"][0][1], seg["pts"][1][1]], [0.8 * 4, 1.0 * 4])
        print("  PASS: recommender scene (bars, ribbons, regret gaps, markers), profile selector and strategy filter change the counts")

        data_dir = tmp / "data"
        write_rings(data_dir)
        rings = r3.rings_payload(str(data_dir))
        assert rings and rings["order"] == ["s1"] and rings["classes"] == ["ESBL", "other"] and rings["samples"]["s1"]["pl"]["pB"] == [1, 0]
        assert rings["samples"]["s1"]["pl"]["pA"] == [1000, 1]
        assert r3.rings_defaults(rings) == ("s1", "pA")
        prg = r3.build_rings(rings)
        jg = js([("views", "buildRings", [rings, {"sample": "s1", "plasmid": "pA"}]),
                 ("views", "buildRings", [rings, {"sample": "s1", "plasmid": "pA", "hidden": {"C:ESBL": True}}]),
                 ("views", "buildRings", [rings, {"sample": "s1", "plasmid": "pA", "hidden": {"P:not_recovered": True}}]),
                 ("views", "buildRings", [rings, {"sample": "s1", "plasmid": "pB"}])], tmp)
        assert roles(prg)["ring"] == 3 and roles(prg)["genemark"] == 4 and roles(prg)["truthgene"] == 2 and roles(prg)["connector"] == 2, roles(prg)
        assert roles(prg)["arc"] == 4 and roles(jg[0]) == roles(prg), (roles(jg[0]), roles(prg))
        assert roles(jg[1])["genemark"] == 2 and roles(r3.build_rings(rings, "s1", "pA", {"C:ESBL"}))["genemark"] == 2    # class filter
        assert roles(jg[2])["genemark"] == 3 and roles(r3.build_rings(rings, "s1", "pA", {"P:not_recovered"}))["genemark"] == 3
        assert roles(jg[3])["genemark"] == 2 and roles(jg[3])["ring"] == 3          # plasmid of length 1 still draws, one gene copy per tool
        assert prg["rates"] == {"toolX": [1, 2], "toolY": [0, 2]}
        # the wrap-around gene sits at angle 0: ring point x ~ 0, z = -R (the back of the ring), on every tool ring
        marks = [p for p in prg["prims"] if p.get("role") == "genemark" and abs(p["p"][0]) < 1e-9]
        assert len(marks) == 2 and all(abs(p["p"][2] + 3) < 1e-9 for p in marks), marks
        assert jg[0]["rates"] == prg["rates"]
        for scene in jg:
            assert {p["id"] for p in scene["prims"] if p.get("id") is not None} <= set(scene["tips"])
        # shapes differ by placement, not only colour
        shapes = {p["shape"] for p in prg["prims"] if p.get("role") == "genemark"}
        assert len(shapes) >= 3, shapes
        print("  PASS: ring scene (rings, markers, connectors, arcs), class/placement filters, wrap-around gene at 0 degrees, length-1 plasmid")

        # ---------------------------------------------------------------- 6. prim-by-prim agreement of the Python and JS builders, and of the renderers
        for pyscene, jsscene in ((pb, jb), (pr, jr[0]), (prg, jg[0])):
            assert len(pyscene["prims"]) == len(jsscene["prims"])
            for a, b in zip(pyscene["prims"], jsscene["prims"]):
                assert a["k"] == b["k"] and a.get("role") == b.get("role")
                pa, pbb = (a.get("pts") or [a.get("p")]), (b.get("pts") or [b.get("p")])
                assert close(pa, pbb, 1e-9), (a, b)
        fits = js([("core", "fitCamera", [s, {"yaw": y, "pitch": p}, r3.W, r3.H, 48]) for s, y, p in ((pb, -28, 24), (pr, -24, 36), (prg, -18, 26))], tmp)
        for s, y, p, f in zip((pb, pr, prg), (-28, -24, -18), (24, 36, 26), fits):
            c = r3.fit_camera(s, y, p)
            assert close([f["scale"], f["cx"], f["cy"], f["dist"]] + f["target"], [c["scale"], c["cx"], c["cy"], c["dist"]] + c["target"], 1e-6), (f, c)
        rendered = js([("core", "renderPrims", [s, r3.fit_camera(s, y, p), {}]) for s, y, p in ((pb, -28, 24), (pr, -24, 36), (prg, -18, 26))], tmp)
        for s, y, p, text in zip((pb, pr, prg), (-28, -24, -18), (24, 36, 26), rendered):
            assert text == r3.render_prims(s, r3.fit_camera(s, y, p)), "static SVG differs from the JS render of the same camera"
        print("  PASS: Python and JS builders agree prim by prim; the server-side SVG is identical to the in-browser render")

        # ---------------------------------------------------------------- 7. sections: static fallback, JSON payloads, collapsed tables, Not run
        evaluation_rows = evaluation
        write(tmp / "lb.tsv", list(lb[0]), [[r[k] for k in lb[0]] for r in lb])
        write(tmp / "scores.tsv", list(scores[0]), [[r[k] for k in scores[0]] for r in scores])
        write(tmp / "xc.tsv", list(xc[0]), [[r[k] for k in xc[0]] for r in xc])
        write(tmp / "eval.tsv", list(evaluation_rows[0]), [[r[k] for k in evaluation_rows[0]] for r in evaluation_rows])
        write(tmp / "benchmark.recommender_regret.tsv", list(regret[0]), [[r[k] for k in regret[0]] for r in regret])
        (tmp / "verdict.json").write_text(json.dumps(verdict), encoding="utf-8")
        write(tmp / "warn.tsv", list(warnings[0]), [[r[k] for k in warnings[0]] for r in warnings])
        write(tmp / "lto.tsv", list(taxon[0]), [[r[k] for k in taxon[0]] for r in taxon])
        write(tmp / "amr.tsv", ["tool", "gene_class", "n_gene_copies", "n_recovered", "n_correct_plasmid", "n_wrong_plasmid",
                                "n_shared_contig", "n_unassigned_contig", "correct_plasmid_rate", "replicon_type_correct_rate", "n_samples"],
              [["toolX", "ESBL", 2, 2, 2, 0, 0, 0, "1.0", "1.0", 1]])
        shutil.copy(tmp / "eval.tsv", tmp / "benchmark.recommender_eval.tsv")
        page = rss.inject("<nav><a href='#recommendations'>Recommendations</a></nav><section id='recommendations'></section>",
                          {"leaderboard": tmp / "lb.tsv", "scores": tmp / "scores.tsv", "contig_crosscheck": tmp / "xc.tsv",
                           "recommender_eval": tmp / "benchmark.recommender_eval.tsv", "recommender_verdict": tmp / "verdict.json",
                           "warning_eval": tmp / "warn.tsv", "leave_taxon_out": tmp / "lto.tsv", "amr_placement": tmp / "amr.tsv",
                           "data_dir": data_dir})
        for sid, kind in (("contig-layer", "bars"), ("recommender-eval", "recs"), ("amr-placement", "rings")):
            body = re.search(r"<section id='%s'>(.*?)</section>" % sid, page, re.S).group(1)
            assert f"data-v3='{kind}'" in body and "Show the data table" in body and "rpt-collapsible" in body, sid
            assert "Not run" not in body or sid == "contig-layer", sid
            svg = re.search(r"<svg .*?</svg>", body, re.S).group(0)
            root = ET.fromstring(svg)                                   # the static no-JS/print SVG is well-formed XML
            assert root.tag.endswith("svg") and len(list(root.iter())) > 20
            assert "<table" in body, "the raw table must stay in the page"
        assert "Verdict: Recommending per isolate beats the single best tool." in page, "verdict must show in plain words without JS"
        ids = re.findall(r"<script type='application/json' id='([^']+)'>(.*?)</script>", page, re.S)
        assert [i for i, _ in ids] == ["v3-data-contig", "v3-data-recs", "v3-data-amr"] and len({i for i, _ in ids}) == 3
        sizes = {}
        for sid, text in ids:
            assert "</" not in text and "<!--" not in text
            payload = json.loads(text)                                  # parses; the kinds are as declared
            assert payload["kind"] in ("bars", "recs", "rings")
            sizes[sid] = len(text.encode("utf-8"))
        assert re.findall(r"id='(v3-data-[a-z]+)'", page) == [i for i, _ in ids]
        assert page.count("PlasBench 3D engine") == 1, "the engine is emitted once"
        print(f"  PASS: static fallback SVG is well-formed XML in each section; JSON payloads parse and ids are unique "
              f"(sizes {sizes} bytes); raw tables kept in a collapsed details; verdict readable without JS")

        # Not run
        for html_text in (rss.contig_layer_section([], [], []), rss.recommender_section([], {}, []), rss.amr_section([], None),
                          rss.contig_layer_section([{"tool": "A", "mean_f1": "0.9"}], [], [])):
            assert "Not run" in html_text and "class='v3'" not in html_text and "<svg" not in html_text
        assert "class='v3'" not in rss.amr_section([{"tool": "A", "gene_class": "all", "n_gene_copies": 1, "n_recovered": 1, "n_correct_plasmid": 1,
                                                    "n_wrong_plasmid": 0, "n_shared_contig": 0, "n_unassigned_contig": 0,
                                                    "correct_plasmid_rate": "1.0", "replicon_type_correct_rate": "1.0"}], str(tmp / "nodir"))
        print("  PASS: with no inputs each section says Not run and draws no empty 3D box; missing per-sample files fall back to the table")

        # ---------------------------------------------------------------- 8. CSV export and panel content
        csv_text = js([("core", "csvText", [["a", "b"], [["x,y", 'say "hi"'], [1, None]]])], tmp)[0]
        assert csv_text == 'a,b\n"x,y","say ""hi"""\n1,\n', repr(csv_text)
        panel = js([("views", "barsPanel", [bars, {}, "t|t0"]), ("views", "recsPanel", [recs, {"profile": "f1"}, "i|0"]),
                    ("views", "ringsPanel", [rings, {"sample": "s1", "plasmid": "pA"}, "g|0|0"]), ("views", "ringsAllRows", [rings]),
                    ("views", "ringsRowsFor", [rings, "s1", "pA", None]), ("views", "isoCsvRow", [recs["iso"]["f1"][0]])], tmp)
        bt = panel[0]
        assert bt["title"] == "A" and bt["tabs"][0]["csv"]["header"] == r3.XC_HEADER and len(bt["tabs"][0]["csv"]["rows"]) == 2      # 14-column table, A's rows
        assert len(bt["tabs"][0]["csv"]["header"]) == 14 and len(bt["tabs"][1]["csv"]["rows"]) == 2
        rt = panel[1]
        assert [t["name"] for t in rt["tabs"]] == ["Isolates", "Warnings scored", "Leave-taxon-out", "Profiles"]      # tables became tabs
        assert rt["tabs"][0]["csv"]["rows"][0][0] == "i1" and len(rt["tabs"][0]["csv"]["rows"]) == 3
        assert len(rt["tabs"][2]["csv"]["rows"]) == 1 and len(rt["tabs"][1]["csv"]["rows"]) == 1
        gt = panel[2]
        assert gt["tabs"][0]["csv"]["header"][:4] == ["sample", "tool", "copy_id", "gene_name"] and len(gt["tabs"][0]["csv"]["rows"]) == 2
        assert len(panel[3]) == 6 and len(panel[4]) == 4                      # 2 tools x 3 genes overall; 2 tools x 2 genes on pA
        assert panel[4][0][11] in ("correct_plasmid", "not_recovered") and panel[5][0] == "i1"
        print("  PASS: CSV quoting, per-tool 14-column cross-check rows, recommender tabs (isolates / warnings / leave-taxon / profiles), AMR rows")

        # ---------------------------------------------------------------- 9. verdict words, assets
        words = js([("views", "verdictWords", [{"verdict": v, "oracle_gap": 0.0, "gap_closed": g, "note": "n"}, None])
                    for v, g in (("benchmark_only", None), ("recommender_adds_value", 0.5), ("recommender_no_better", 0.0), ("x", None))], tmp)
        for w, v, g in zip(words, ("benchmark_only", "recommender_adds_value", "recommender_no_better", "x"), (None, 0.5, 0.0, None)):
            assert tuple(w) == r3.verdict_words({"verdict": v, "oracle_gap": 0.0, "gap_closed": g, "note": "n"}), (w, v)
        for name in ("viz3d_style.html", "viz3d_core.html", "viz3d_views.html"):
            text = (ROOT / "assets" / "report" / name).read_text(encoding="utf-8")
            external = [m for m in re.findall(r"https?://[^\s'\")]+", text) if m != "http://www.w3.org/2000/svg"]
            assert not external, f"{name} reaches outside the file: {external}"
            assert not re.search(r"<link|<script[^>]*src=|@import|\bimport\s*\(|fetch\(|XMLHttpRequest", text), name
            assert "</script" not in re.sub(r"</script>\s*$", "", text.strip())
            if name.endswith(("core.html", "views.html")):
                body = re.sub(r"^[\s\S]*?<script>", "", text).replace("</script>", "")
                path = tmp / (name + ".js")
                path.write_text(body, encoding="utf-8")
                done = subprocess.run([NODE, "--check", str(path)], capture_output=True, text=True)
                assert done.returncode == 0, done.stderr
        print("  PASS: verdict text matches in JS and Python; the assets are self-contained and parse")
    print("ALL 3D REPORT TESTS PASSED")


if __name__ == "__main__":
    main()
