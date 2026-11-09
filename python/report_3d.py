#!/usr/bin/env python3
"""
report_3d.py -- the server side of the three interactive 3D views in the report.

  Contig layer beside the reference layer (3D bars), the recommender strategies per isolate (3D bars with regret gaps and a
  ribbon) and AMR genes on the right plasmid (a tower of rings).

What lives here
  * the same camera and projection math as assets/report/viz3d_core.html (project, face_visible, sort order), so a STATIC
    SVG of the default camera can be drawn on the server: it is the no-JavaScript and print fallback, shown until the
    script starts and then replaced by the live scene. test/test_report_3d.py runs node on both and checks they agree;
  * scene builders for the default selection of each view (the live builders are in assets/report/viz3d_views.html);
  * payload builders: compact JSON for each view, embedded as <script type='application/json'>;
  * host(): the markup of one view (static SVG, JSON, collapsed raw table) and assets(): the CSS and scripts, once.

Standard library only.
"""
import html
import json
import math
from pathlib import Path

import report_common as rc

RAD = math.pi / 180.0
OI = {"blue": "#0072B2", "orange": "#E69F00", "green": "#009E73", "purple": "#CC79A7", "vermillion": "#D55E00",
      "sky": "#56B4E9", "ink": "#17231d", "grey": "#8c8c8c"}
W, H = 900, 580

PLACE = {
    "correct_plasmid": ("Correct plasmid", OI["green"], "circle"),
    "wrong_plasmid": ("Wrong plasmid", OI["vermillion"], "cross"),
    "shared_contig": ("Shared contig", OI["orange"], "diamond"),
    "unassigned_contig": ("Unassigned contig", OI["sky"], "square"),
    "not_recovered": ("Not recovered", "#555555", "ring"),
}
PLACE_ORDER = ("correct_plasmid", "wrong_plasmid", "shared_contig", "unassigned_contig", "not_recovered")

LAYERS = (
    ("ref_f1", "Reference-base F1", OI["blue"],
     "Base-level F1 against the complete reference: the headline layer, shown here as the yardstick."),
    ("contig_f1", "Contig F1 (by length)", OI["green"],
     "Contigs are labelled against the reference and each tool's calls are scored per contig, weighted by contig length."),
    ("contig_mcc", "Contig MCC (by length)", OI["orange"],
     "Matthews correlation of the contig calls, length-weighted; blank when it is undefined."),
    ("contig_bin_f1", "Contig binning F1 (by length)", OI["purple"],
     "How well the contigs are grouped into one bin per plasmid, length-weighted."),
)
LAYER_COLUMN = {"ref_f1": "mean_f1", "contig_f1": "mean_contig_f1_bp", "contig_mcc": "mean_contig_mcc_bp",
                "contig_bin_f1": "mean_contig_bin_f1_bp"}
XC_HEADER = ["Sample", "Tool", "Contigs", "Low-information (excluded)", "Label agreement", "Kappa", "F1 (minimap2)", "F1 (k-mer)",
             "|delta F1|", "MCC (minimap2)", "MCC (k-mer)", "|delta MCC|", "Status", "Contigs labelled differently"]
XC_FIELDS = ["sample", "tool", "n_contigs", "n_low_information", "label_agreement", "label_kappa", "primary_f1_bp",
             "independent_f1_bp", "delta_f1_bp", "primary_mcc_bp", "independent_mcc_bp", "delta_mcc_bp", "status",
             "differing_contigs"]
XC_THRESHOLD = 0.02

STRATS = (("rec", "Per-isolate recommender", OI["blue"], 4), ("single", "Single best tool", OI["orange"], 11),
          ("oracle", "Oracle best tool", OI["green"], 7))
ISO_FIELDS = ("sample", "organism", "held_out_study", "recommended_tool", "recommended_score", "predicted_score", "best_tool",
              "best_score", "regret", "near_optimal", "single_best_tool", "single_best_score", "single_best_regret", "floor_flag",
              "basis")
ISO_NUMERIC = {4, 5, 7, 8, 11, 12}
EVAL_HEADER = ["Profile", "Isolates", "Folds", "Mean regret", "95th pct regret", "Near-optimal", "Top-1", "Kendall tau",
               "Single-best regret", "Oracle gap", "Gap closed", "Floor flagged", "Verdict"]
EVAL_FIELDS = ["profile", "n_isolates", "n_folds", "mean_regret", "p95_regret", "near_optimal_rate", "top1_rate", "mean_kendall_tau",
               "single_best_mean_regret", "oracle_gap", "gap_closed", "floor_flagged", "verdict"]
WARN_HEADER = ["Warning", "Evaluated", "Fired", "Failed", "Firing rate", "PPV", "Sensitivity", "Could not be applied", "Status"]
WARN_FIELDS = ["warning", "n_evaluated", "n_fired", "n_failed", "firing_rate", "ppv", "sensitivity", "n_could_not_be_applied", "status"]
TAXON_HEADER = ["Level", "Held-out group", "Isolates", "Training isolates", "Mean regret", "Single-best regret", "Near-optimal",
                "Gap closed", "Status", "Note"]
TAXON_FIELDS = ["level", "held_out_group", "n_isolates", "n_training_isolates", "mean_regret", "single_best_mean_regret",
                "near_optimal_rate", "gap_closed", "status", "note"]


# ------------------------------------------------------------------------------------------------ projection (mirror of the JS)
def make_cam(yaw=-32.0, pitch=26.0, zoom=1.0, persp=1, dist=10.0, target=(0.0, 0.0, 0.0), scale=50.0, cx=0.0, cy=0.0):
    return {"yaw": yaw, "pitch": pitch, "zoom": zoom, "persp": persp, "dist": dist, "target": list(target), "scale": scale,
            "cx": cx, "cy": cy}


def view_xyz(p, cam):
    t = cam["target"]
    x, y, z = p[0] - t[0], p[1] - t[1], p[2] - t[2]
    cy, sy = math.cos(cam["yaw"] * RAD), math.sin(cam["yaw"] * RAD)
    cp, sp = math.cos(cam["pitch"] * RAD), math.sin(cam["pitch"] * RAD)
    x1, z1 = cy * x + sy * z, -sy * x + cy * z
    return [x1, cp * y - sp * z1, sp * y + cp * z1]


def project(p, cam):
    """World point -> [screen x, screen y, view depth (larger = nearer), perspective factor]."""
    v = view_xyz(p, cam)
    s = 1.0
    if cam["persp"]:
        den = cam["dist"] - v[2]
        if den < 1e-6:
            den = 1e-6
        s = cam["dist"] / den
    k = cam["scale"] * cam["zoom"] * s
    return [cam["cx"] + k * v[0], cam["cy"] - k * v[1], v[2], s]


def face_visible(pts, cam):
    a, b, c = view_xyz(pts[0], cam), view_xyz(pts[1], cam), view_xyz(pts[2], cam)
    u = [b[i] - a[i] for i in range(3)]
    w = [c[i] - a[i] for i in range(3)]
    n = [u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]]
    v = [-a[0], -a[1], cam["dist"] - a[2]] if cam["persp"] else [0, 0, 1]
    return n[0] * v[0] + n[1] * v[1] + n[2] * v[2] > 0


def box_faces(x0, x1, y0, y1, z0, z1):
    return [
        ("top", [[x0, y1, z1], [x1, y1, z1], [x1, y1, z0], [x0, y1, z0]], 0.28),
        ("front", [[x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], 0),
        ("right", [[x1, y0, z1], [x1, y0, z0], [x1, y1, z0], [x1, y1, z1]], -0.22),
        ("back", [[x1, y0, z0], [x0, y0, z0], [x0, y1, z0], [x1, y1, z0]], -0.12),
        ("left", [[x0, y0, z0], [x0, y0, z1], [x0, y1, z1], [x0, y1, z0]], -0.3),
        ("bottom", [[x0, y0, z0], [x1, y0, z0], [x1, y0, z1], [x0, y0, z1]], -0.4),
    ]


def shade_hex(hexcolor, t):
    if not t or not hexcolor or len(hexcolor) != 7 or hexcolor[0] != "#":
        return hexcolor
    v = int(hexcolor[1:], 16)
    c = [v >> 16 & 255, v >> 8 & 255, v & 255]
    tgt, a = (255 if t > 0 else 0), abs(t)
    return "#" + "".join("%02x" % int(math.floor(x + (tgt - x) * a + 0.5)) for x in c)


def bp_to_deg(pos, length):
    if not length > 0:
        return 0.0
    return (pos % length) / length * 360.0


def ring_xz(radius, deg):
    a = deg * RAD
    return [radius * math.sin(a), -radius * math.cos(a)]


def gene_span(start, end, length):
    """{mid, span} of a gene on a circular molecule; end < start means it wraps through the origin."""
    span = end - start if end >= start else end - start + length
    if not length > 0:
        return {"mid": 0.0, "span": 0.0}
    if span >= length:
        return {"mid": start % length, "span": length}
    return {"mid": (start + span / 2.0) % length, "span": span}


def nice_step(length, want=8):
    raw = length / float(want)
    if not raw > 0:
        return 1.0
    p = 10 ** math.floor(math.log10(raw))
    f = raw / p
    m = 1 if f <= 1 else 2 if f <= 2 else 5 if f <= 5 else 10
    return max(1.0, m * p)


def bp_label(p):
    return f"{num(p / 1000.0)} kb" if p >= 1000 else f"{num(p)} bp"


def num(x):
    text = f"{round(x * 100) / 100:.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def esc(value):
    return html.escape("" if value is None else str(value), quote=True)


def prim_depth(p, cam):
    if "pts" in p:
        return sum(view_xyz(q, cam)[2] for q in p["pts"]) / len(p["pts"])
    return view_xyz(p["p"], cam)[2] + p.get("bias", 0)


def sort_prims(prims, cam):
    rows = [(p.get("layer", 1), round(prim_depth(p, cam), 7), i, p) for i, p in enumerate(prims)]   # near-ties keep scene order
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    return rows


def scene_bounds(prims):
    pts = [q for p in prims for q in (p.get("pts") or [p["p"]])]
    if not pts:
        return {"center": [0, 0, 0], "radius": 1.0}
    lo = [min(q[k] for q in pts) for k in range(3)]
    hi = [max(q[k] for q in pts) for k in range(3)]
    center = [(lo[k] + hi[k]) / 2.0 for k in range(3)]
    radius = math.sqrt(sum((hi[k] - lo[k]) ** 2 for k in range(3))) / 2.0
    return {"center": center, "radius": max(radius, 1e-6)}


def fit_camera(scene, yaw, pitch, width=W, height=H, margin=48, persp=1):
    b = scene_bounds(scene["prims"])
    cam = make_cam(yaw=yaw, pitch=pitch, persp=persp, dist=b["radius"] * 4.2, target=b["center"], scale=1.0)
    xs, ys = [], []
    for p in scene["prims"]:
        for q in (p.get("pts") or [p["p"]]):
            s = project(q, cam)
            xs.append(s[0])
            ys.append(s[1])
    if not xs:
        xs = ys = [0.0]
    bw, bh = max(max(xs) - min(xs), 1e-6), max(max(ys) - min(ys), 1e-6)
    cam["scale"] = min((width - 2 * margin) / bw, (height - 2 * margin) / bh)
    cam["cx"] = width / 2.0 - cam["scale"] * (min(xs) + max(xs)) / 2.0
    cam["cy"] = height / 2.0 - cam["scale"] * (min(ys) + max(ys)) / 2.0
    return cam


def _marker(m, x, y, s):
    r = max(2.5, (m.get("r") or 5) * min(max(s, 0.6), 1.6))
    f, st, sw = m.get("fill") or "#000", m.get("stroke") or "#fff", m.get("sw") or 1.2
    shape = m.get("shape")
    if shape == "square":
        return f'<rect x="{num(x - r)}" y="{num(y - r)}" width="{num(2 * r)}" height="{num(2 * r)}" fill="{f}" stroke="{st}" stroke-width="{sw}"/>'
    if shape == "diamond":
        pts = [(x, y - r * 1.3), (x + r * 1.3, y), (x, y + r * 1.3), (x - r * 1.3, y)]
        return f'<polygon points="{" ".join(num(a) + "," + num(b) for a, b in pts)}" fill="{f}" stroke="{st}" stroke-width="{sw}"/>'
    if shape == "triangle":
        pts = [(x, y - r * 1.25), (x + r * 1.2, y + r * 0.95), (x - r * 1.2, y + r * 0.95)]
        return f'<polygon points="{" ".join(num(a) + "," + num(b) for a, b in pts)}" fill="{f}" stroke="{st}" stroke-width="{sw}"/>'
    if shape == "cross":
        return (f'<path d="M{num(x - r)},{num(y - r)}L{num(x + r)},{num(y + r)}M{num(x - r)},{num(y + r)}L{num(x + r)},{num(y - r)}" '
                f'fill="none" stroke="{f}" stroke-width="3" stroke-linecap="round"/>')
    if shape == "ring":
        return (f'<circle cx="{num(x)}" cy="{num(y)}" r="{num(r)}" fill="{m.get("bg") or "#ffffff"}" fill-opacity="0.85" '
                f'stroke="{f}" stroke-width="2"/>')
    return f'<circle cx="{num(x)}" cy="{num(y)}" r="{num(r)}" fill="{f}" stroke="{st}" stroke-width="{sw}"/>'


def render_prims(scene, cam):
    out = []
    for _layer, _depth, _i, p in sort_prims(scene["prims"], cam):
        cls = p.get("cls", "")
        kind = p["k"]
        if kind == "poly":
            if p.get("cull") and not face_visible(p["pts"], cam):
                continue
            pts = " ".join(f"{num(s[0])},{num(s[1])}" for s in (project(q, cam) for q in p["pts"]))
            fill = shade_hex(p["fill"], p.get("shade", 0)) if p.get("fill") else None
            out.append(f'<polygon class="v3-f {cls}" points="{pts}"' + (f' fill="{fill}"' if fill else "")
                       + (f' stroke="{p["stroke"]}"' if p.get("stroke") else "")
                       + (f' fill-opacity="{p["op"]}"' if p.get("op") is not None else "")
                       + (f' stroke-dasharray="{p["dash"]}"' if p.get("dash") else "") + "/>")
        elif kind == "line":
            pts = " ".join(f"{num(s[0])},{num(s[1])}" for s in (project(q, cam) for q in p["pts"]))
            out.append(f'<polyline class="{cls}" points="{pts}" fill="none"' + (f' stroke="{p["stroke"]}"' if p.get("stroke") else "")
                       + (f' stroke-width="{p["w"]}"' if p.get("w") else "")
                       + (f' stroke-dasharray="{p["dash"]}"' if p.get("dash") else "")
                       + (f' stroke-opacity="{p["op"]}"' if p.get("op") is not None else "")
                       + (' stroke-linecap="round"' if p.get("cap") else "") + "/>")
        elif kind == "mark":
            s = project(p["p"], cam)
            out.append(_marker(p, s[0], s[1], s[3]))
        elif kind == "text":
            t = project(p["p"], cam)
            x, y = t[0] + p.get("dx", 0), t[1] + p.get("dy", 0)
            out.append(f'<text class="v3-t {p.get("cls", "")}" x="{num(x)}" y="{num(y)}" text-anchor="{p.get("anchor", "middle")}"'
                       + (f' font-size="{p["size"]}"' if p.get("size") else "")
                       + (f' transform="rotate({p["rot"]} {num(x)} {num(y)})"' if p.get("rot") else "")
                       + f">{esc(p['t'])}</text>")
    return "".join(out)


def svg_doc(scene, cam, width=W, height=H):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" class="v3-svg" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="{esc(scene.get("title", ""))}"><title>{esc(scene.get("title", ""))}</title>'
            f'<desc>{esc(scene.get("desc", ""))}</desc>{render_prims(scene, cam)}</svg>')


# ------------------------------------------------------------------------------------------------ scene builders
def _floor_and_walls(prims, xmin, xmax, zmin, zmax, h, ticks):
    prims.append({"k": "poly", "role": "floor", "layer": 0, "cls": "v3-floor",
                  "pts": [[xmin, 0, zmax], [xmax, 0, zmax], [xmax, 0, zmin], [xmin, 0, zmin]]})
    for t in range(ticks + 1):
        y = h * t / float(ticks)
        prims.append({"k": "line", "role": "grid", "layer": 0, "cls": "v3-grid", "pts": [[xmin, y, zmin], [xmax, y, zmin]]})
        prims.append({"k": "line", "role": "grid", "layer": 0, "cls": "v3-grid", "pts": [[xmin, y, zmin], [xmin, y, zmax]]})
        label = f"{t / float(ticks):.2f}"
        label = label[:-1] if label.endswith("0") else label
        prims.append({"k": "text", "role": "ytick", "layer": 2, "cls": "v3-t-m", "p": [xmin, y, zmax], "t": label, "anchor": "end",
                      "dx": -7, "dy": 4})
    prims.append({"k": "line", "role": "axis", "layer": 0, "cls": "v3-axis", "pts": [[xmin, 0, zmax], [xmin, h, zmax]]})
    prims.append({"k": "line", "role": "axis", "layer": 0, "cls": "v3-axis", "pts": [[xmin, 0, zmax], [xmax, 0, zmax]]})
    prims.append({"k": "line", "role": "axis", "layer": 0, "cls": "v3-axis", "pts": [[xmax, 0, zmin], [xmax, 0, zmax]]})


def _add_box(prims, x, z, w, d, h, fill, role="bar"):
    for name, pts, shade in box_faces(x - w / 2, x + w / 2, 0, h, z - d / 2, z + d / 2):
        prims.append({"k": "poly", "role": role, "cls": "v3-bar", "pts": pts, "fill": fill, "shade": shade, "cull": True})


def build_bars(data, group="", layer="", hidden=()):
    tools = [t for t in data["tools"] if not group or t["group"] == group]
    layers = [l for l in data["layers"] if f"L:{l['key']}" not in hidden and (not layer or layer == l["key"])]
    nx, nz = len(tools), len(layers)
    scene = {"prims": [], "legend": [], "title": "Contig layer beside the reference layer: 3D bar chart",
             "desc": "Bars: x is the tool, depth is the scoring layer, height is the score from 0 to 1. Markers show the independent k-mer scorer."}
    if not nx or not nz:
        return scene
    gx, gz, bw, h = 1.7, 1.9, 1.05, 4.0
    prims = scene["prims"]
    xmin, xmax, zmin, zmax = -1.1, (nx - 1) * gx + 1.1, -1.1, (nz - 1) * gz + 1.1
    _floor_and_walls(prims, xmin, xmax, zmin, zmax, h, 4)
    for i in range(nx):
        prims.append({"k": "line", "role": "grid", "layer": 0, "cls": "v3-grid", "pts": [[i * gx, 0, zmin], [i * gx, 0, zmax]]})
    for j in range(nz):
        prims.append({"k": "line", "role": "grid", "layer": 0, "cls": "v3-grid", "pts": [[xmin, 0, j * gz], [xmax, 0, j * gz]]})
    for i, t in enumerate(tools):
        prims.append({"k": "text", "role": "xlabel", "layer": 2, "cls": "v3-t-b", "p": [i * gx, 0, zmax + 0.15], "t": t["label"],
                      "anchor": "end" if nx > 5 else "middle", "dy": 16, "rot": -28 if nx > 5 else 0})
    for j, l in enumerate(layers):
        prims.append({"k": "text", "role": "zlabel", "layer": 2, "cls": "v3-t-b", "p": [xmax + 0.1, 0, j * gz], "t": l["label"],
                      "anchor": "start", "dx": 8, "dy": 4})
    prims.append({"k": "text", "role": "axtitle", "layer": 2, "cls": "v3-t-m v3-ital", "p": [xmin, h, zmax], "t": "Score (0 to 1)",
                  "anchor": "end", "dx": -4, "dy": -12})
    labelled = nx * nz <= 40
    for i, t in enumerate(tools):
        for j, l in enumerate(layers):
            x, z, v = i * gx, j * gz, t["v"].get(l["key"])
            if v is None:
                prims.append({"k": "poly", "role": "na", "cls": "v3-na", "fill": "#999999", "op": 0.12,
                              "pts": [[x - bw / 2, 0.03, z + bw / 2], [x + bw / 2, 0.03, z + bw / 2], [x + bw / 2, 0.03, z - bw / 2],
                                      [x - bw / 2, 0.03, z - bw / 2]]})
                continue
            hh = max(v * h, 0.02)
            _add_box(prims, x, z, bw, bw, hh, l["color"])
            if labelled:
                prims.append({"k": "text", "role": "value", "layer": 2, "cls": "v3-t-b", "size": 10, "p": [x, hh, z], "t": f"{v:.2f}", "dy": -7})
            xc = t.get("xc")
            iv = (xc["f1"] if l["key"] == "contig_f1" else xc["mcc"] if l["key"] == "contig_mcc" else None) if xc else None
            if xc and iv is not None and "xc" not in hidden:
                dis = xc["dis"] > 0
                prims.append({"k": "line", "role": "xcwhisker", "cls": "v3-xcw", "pts": [[x, hh, z], [x, iv * h, z]],
                              "stroke": OI["vermillion"] if dis else "#222222", "w": 2, "op": 0.9})
                prims.append({"k": "mark", "role": "xc", "p": [x, iv * h, z], "bias": 0.05, "shape": "triangle" if dis else "diamond",
                              "r": 6, "fill": OI["vermillion"] if dis else "#ffffff", "stroke": "#111111"})
    for l in data["layers"]:
        scene["legend"].append({"group": "Layer", "label": l["label"], "color": l["color"], "shape": "square"})
    scene["legend"] += [{"group": "Independent scorer", "label": "Agrees (diamond)", "color": "#ffffff", "shape": "diamond"},
                        {"group": "Independent scorer", "label": "Flagged: disagrees (triangle)", "color": OI["vermillion"],
                         "shape": "triangle"}]
    return scene


def build_recs(data, profile="", hidden=()):
    profile = profile or (data["profiles"][0]["p"] if data["profiles"] else "")
    rows = data["iso"].get(profile, [])
    strs = [s for s in STRATS if f"S:{s[0]}" not in hidden]
    nx, nz = len(rows), len(strs)
    scene = {"prims": [], "legend": [], "title": "Recommender strategies per isolate: 3D bar chart",
             "desc": "Bars: x is the isolate, depth is the strategy (recommender, single best tool, oracle), height is the score. Dashed segments are regret gaps."}
    if not nx or not nz:
        return scene
    gx, gz, bw, h = 1.2, 2.5, 0.7, 4.0
    prims = scene["prims"]
    xmin, xmax, zmin, zmax = -1.0, (nx - 1) * gx + 1.0, -1.1, (nz - 1) * gz + 1.1
    _floor_and_walls(prims, xmin, xmax, zmin, zmax, h, 4)
    for j, s in enumerate(strs):
        zz = (nz - 1 - j) * gz
        prims.append({"k": "line", "role": "grid", "layer": 0, "cls": "v3-grid", "pts": [[xmin, 0, zz], [xmax, 0, zz]]})
        prims.append({"k": "text", "role": "zlabel", "layer": 2, "cls": "v3-t-b", "p": [xmax + 0.1, 0, zz], "t": s[1], "anchor": "start",
                      "dx": 8, "dy": 4})
    many = nx > 5
    for i, r in enumerate(rows):
        x = i * gx
        prims.append({"k": "text", "role": "xlabel", "layer": 2, "cls": "v3-t-b", "p": [x, 0, zmax + 0.15], "t": r[0],
                      "anchor": "end" if many else "middle", "dy": 16, "rot": -35 if many else 0})
        tops = []
        for j, s in enumerate(strs):
            v, z = r[s[3]], (nz - 1 - j) * gz
            if v is None:
                continue
            _add_box(prims, x, z, bw, bw, max(v * h, 0.02), s[2])
            tops.append([x, v * h, z])
            if s[0] == "rec":
                near = r[9] == "yes"
                prims.append({"k": "mark", "role": "near", "p": [x, v * h, z], "bias": 0.05, "shape": "circle" if near else "triangle",
                              "r": 5.5, "fill": "#ffffff" if near else OI["vermillion"], "stroke": "#111111"})
                if r[13] == "yes":
                    prims.append({"k": "mark", "role": "floorflag", "p": [x, v * h, z], "bias": 0.04, "shape": "ring", "r": 10, "fill": "#111111"})
            best = r[7]
            gap = (best - v) if s[0] in ("rec", "single") and best is not None else 0
            if gap > 1e-9:
                prims.append({"k": "line", "role": "regret", "cls": "v3-regret", "cap": True, "pts": [[x, v * h, z], [x, best * h, z]],
                              "stroke": OI["vermillion"], "w": 3, "dash": "5 3"})
        for q in range(len(tops) - 1):
            a, b = tops[q], tops[q + 1]
            prims.append({"k": "poly", "role": "ribbon", "cls": "v3-ribbon", "fill": "#5b6f86", "op": 0.65,
                          "pts": [[a[0] - 0.12, a[1], a[2]], [a[0] + 0.12, a[1], a[2]], [b[0] + 0.12, b[1], b[2]], [b[0] - 0.12, b[1], b[2]]]})
    for s in STRATS:
        scene["legend"].append({"group": "Strategy", "label": s[1], "color": s[2], "shape": "square"})
    scene["legend"] += [{"group": "Markers", "label": "Recommendation near-optimal (circle)", "color": "#17231d", "shape": "ring"},
                        {"group": "Markers", "label": "Not near-optimal (triangle)", "color": OI["vermillion"], "shape": "triangle"},
                        {"group": "Markers", "label": "Dashed segment: regret gap to the oracle", "color": OI["vermillion"], "shape": "line"}]
    return scene


def rings_plasmids(data, sample):
    s = data["samples"].get(sample)
    if not s:
        return []
    counts = {}
    for g in s["g"]:
        counts[g[0]] = counts.get(g[0], 0) + 1
    out = [(p, s["pl"][p][0], counts[p]) for p in s["pl"] if counts.get(p)]
    out.sort(key=lambda r: (-r[2], r[0]))
    return out


def rings_defaults(data):
    best = None
    for sample in data["order"]:
        pl = rings_plasmids(data, sample)
        if pl and (best is None or pl[0][2] > best[2]):
            best = (sample, pl[0][0], pl[0][2])
    if best:
        return best[0], best[1]
    return (data["order"][0] if data["order"] else ""), ""


def build_rings(data, sample="", plasmid="", hidden=()):
    if not sample:
        sample, plasmid = rings_defaults(data)
    s = data["samples"].get(sample)
    scene = {"prims": [], "legend": [], "title": "AMR genes on the right plasmid: stack of rings",
             "desc": "One ring per tool, stacked below the reference ring; markers are AMR gene copies placed by angle along the plasmid.",
             "rates": {}}
    if not s or plasmid not in s["pl"]:
        return scene
    length = s["pl"][plasmid][0]
    tools = sorted(s["tools"])
    n, radius, gap, steps = len(tools) + 1, 3.0, 1.5, 72
    prims = scene["prims"]
    genes = [gi for gi, g in enumerate(s["g"]) if g[0] == plasmid and f"C:{g[2]}" not in hidden]
    step = nice_step(length, 8)

    def ring_pts(y):
        out = []
        for k in range(steps + 1):
            xz = ring_xz(radius, k / float(steps) * 360.0)
            out.append([xz[0], y, xz[1]])
        return out

    for ri in range(n):
        truth = ri == 0
        tool = None if truth else tools[ri - 1]
        y = (n - 1 - ri) * gap
        row_map = {} if truth else {r[0]: r for r in s["tools"][tool]}
        ok = tot = 0
        circ = ring_pts(y)
        prims.append({"k": "poly", "role": "disc", "layer": 1, "cls": "v3-disc", "pts": circ[:steps], "fill": "#8c8c8c",
                      "op": 0.1 if truth else 0.045})
        prims.append({"k": "line", "role": "ring", "layer": 1, "cls": "v3-ring v3-ring-ref" if truth else "v3-ring", "pts": circ,
                      "w": 2.4 if truth else 1.6})
        p = 0.0
        while p < length and p / length < 1:
            a = bp_to_deg(p, length)
            i0, i1 = ring_xz(radius, a), ring_xz(radius + 0.16, a)
            prims.append({"k": "line", "role": "tick", "layer": 1, "cls": "v3-tick", "pts": [[i0[0], y, i0[1]], [i1[0], y, i1[1]]]})
            if truth:
                lb = ring_xz(radius + 0.5, a)
                prims.append({"k": "text", "role": "ticklabel", "layer": 2, "cls": "v3-t-m", "size": 9.5, "p": [lb[0], y, lb[1]],
                              "t": bp_label(p), "dy": 3})
            p += step
        lab = ring_xz(radius, 270)
        lcol = [-(radius + 1.7), y, 0]
        prims.append({"k": "line", "role": "leader", "layer": 1, "cls": "v3-conn", "pts": [[lab[0], y, lab[1]], lcol]})
        prims.append({"k": "text", "role": "rlabel", "layer": 2, "cls": "v3-t-b", "p": lcol,
                      "t": "Reference (truth)" if truth else tool, "anchor": "end", "dx": -4, "dy": 4})
        for gi in genes:
            g = s["g"][gi]
            sp = gene_span(g[3], g[4], length)
            deg = bp_to_deg(sp["mid"], length)
            xz = ring_xz(radius, deg)
            if truth:
                prims.append({"k": "mark", "role": "truthgene", "p": [xz[0], y, xz[1]], "bias": 0.05, "shape": "diamond", "r": 5.5,
                              "fill": "#17231d", "stroke": "#ffffff"})
                if len(genes) <= 14:
                    lp = ring_xz(radius + 0.55, deg)
                    prims.append({"k": "text", "role": "glabel", "layer": 2, "cls": "v3-t-b", "size": 10.5, "p": [lp[0], y + 0.12, lp[1]],
                                  "t": g[1], "anchor": "start" if xz[0] >= 0 else "end", "dx": 4 if xz[0] >= 0 else -4, "dy": -4})
                if n > 1:
                    prims.append({"k": "line", "role": "connector", "layer": 1, "cls": "v3-conn", "pts": [[xz[0], y, xz[1]], [xz[0], 0, xz[1]]]})
                continue
            r = row_map.get(gi)
            if not r:
                continue
            label, color, shape = PLACE.get(r[1], PLACE["not_recovered"])
            tot += 1
            ok += r[1] == "correct_plasmid"
            if f"P:{r[1]}" in hidden:
                continue
            ns = max(2, int(math.ceil(sp["span"] / length * steps)) + 1)
            arc = []
            for k in range(ns):
                q = ring_xz(radius, bp_to_deg(g[3] + sp["span"] * k / (ns - 1), length))
                arc.append([q[0], y, q[1]])
            prims.append({"k": "line", "role": "arc", "layer": 1, "cls": "v3-arc", "pts": arc, "stroke": color, "w": 5, "cap": True})
            prims.append({"k": "mark", "role": "genemark", "p": [xz[0], y, xz[1]], "bias": 0.05, "shape": shape, "r": 6, "fill": color,
                          "stroke": "#ffffff"})
        if not truth:
            scene["rates"][tool] = [ok, tot]
            prims.append({"k": "text", "role": "rate", "layer": 2, "cls": "v3-t-m", "size": 10, "p": lcol,
                          "t": f"{ok}/{tot} correct", "anchor": "end", "dx": -4, "dy": 16})
    for key in PLACE_ORDER:
        label, color, shape = PLACE[key]
        scene["legend"].append({"group": "Placement", "label": label, "color": color, "shape": shape})
    scene["legend"].append({"group": "Reference", "label": "Reference gene (top ring)", "color": "#17231d", "shape": "diamond"})
    return scene


# ------------------------------------------------------------------------------------------------ payloads
def _round(value, digits=4):
    return None if value is None else round(value, digits)


def _dict(rows):
    return rows or []


def bars_payload(leaderboard, scores, crosscheck):
    """Payload for the contig-layer bars, or None when no tool was scored at contig level."""
    rows = [r for r in leaderboard if r.get("tool")]
    if not any(rc.number(r.get("mean_contig_f1_bp")) is not None for r in rows):
        return None
    by_tool_ex, xc_by_tool = {}, {}
    for r in scores:
        e = by_tool_ex.setdefault(r.get("tool"), {"shared": 0, "unassigned": 0})
        e["shared"] += int(rc.number(r.get("contigs_ambiguous_bp")) or 0)
        e["unassigned"] += int(rc.number(r.get("contigs_unplaced_bp")) or 0)
    for r in crosscheck:
        xc_by_tool.setdefault(r.get("tool"), []).append(r)
    labels = {}
    for r in rows:
        labels[r["tool"]] = labels.get(r["tool"], 0) + 1
    tools, groups = [], []
    for r in rows:
        values = {key: _round(rc.number(r.get(col))) for key, col in LAYER_COLUMN.items()}
        if all(v is None for v in values.values()):
            continue
        group = " / ".join(x for x in (r.get("analysis_track"), r.get("task")) if x)
        if group and group not in groups:
            groups.append(group)
        xrows = xc_by_tool.get(r["tool"], [])
        xc = None
        if xrows:
            def mean(col):
                vals = [rc.number(x.get(col)) for x in xrows]
                vals = [v for v in vals if v is not None]
                return _round(sum(vals) / len(vals)) if vals else None
            xc = {"n": len(xrows), "f1": mean("independent_f1_bp"), "mcc": mean("independent_mcc_bp"), "d_f1": mean("delta_f1_bp"),
                  "d_mcc": mean("delta_mcc_bp"), "dis": sum(x.get("status") == "disagree" for x in xrows)}
        ex = by_tool_ex.get(r["tool"], {"shared": 0, "unassigned": 0})
        label = r["tool"] if labels[r["tool"]] == 1 or not group else f"{r['tool']} ({group})"
        tools.append({"id": f"t{len(tools)}", "tool": r["tool"], "label": label, "group": group, "v": values, "xc": xc, "ex": ex})
    status, basis = crosscheck_summary(crosscheck)
    return {"kind": "bars", "thr": XC_THRESHOLD, "groups": groups,
            "layers": [{"key": k, "label": l, "color": c, "def": d} for k, l, c, d in LAYERS], "tools": tools,
            "shared": sum(int(rc.number(r.get("contigs_ambiguous_bp")) or 0) for r in scores),
            "unassigned": sum(int(rc.number(r.get("contigs_unplaced_bp")) or 0) for r in scores),
            "xcStatus": status, "xcBasis": basis, "xcHeader": XC_HEADER,
            "xcRows": [[x.get(f, "") for f in XC_FIELDS] for x in crosscheck]}


def crosscheck_summary(rows):
    """(status text, basis) for the contig layer from contig_crosscheck.py compare rows."""
    if not rows:
        return "implemented, not cross-checked in this run", "no independent-scorer table (RUN_CONTIG_CROSSCHECK=0, or no contigs)"
    deltas = [float(r["delta_f1_bp"]) for r in rows if r.get("delta_f1_bp")]
    disagree = sum(r.get("status") == "disagree" for r in rows)
    worst = f"max |delta F1| {max(deltas):.4f}" if deltas else "no defined F1"
    if disagree:
        return "cross-checked: disagreements", f"{disagree} of {len(rows)} (sample, tool) pairs differ beyond 0.02; {worst}"
    return "cross-checked against an independent scorer", f"{len(rows)} (sample, tool) pairs agree within 0.02; {worst}"


def recs_payload(evaluation, regret, verdict, warnings, taxon):
    """Payload for the recommender strategies view; `regret` (the per-isolate table) may be empty."""
    profiles = []
    for r in evaluation:
        profiles.append({"p": r.get("profile", ""), "n": r.get("n_isolates", ""), "folds": r.get("n_folds", ""),
                         "mean_regret": _round(rc.number(r.get("mean_regret"))), "p95": _round(rc.number(r.get("p95_regret"))),
                         "near": _round(rc.number(r.get("near_optimal_rate"))), "top1": _round(rc.number(r.get("top1_rate"))),
                         "tau": _round(rc.number(r.get("mean_kendall_tau"))), "sb_regret": _round(rc.number(r.get("single_best_mean_regret"))),
                         "oracle_gap": _round(rc.number(r.get("oracle_gap"))), "gap_closed": _round(rc.number(r.get("gap_closed"))),
                         "floor": r.get("floor_flagged", ""), "verdict": r.get("verdict", "")})
    iso = {}
    for r in regret:
        row = []
        for idx, f in enumerate(ISO_FIELDS):
            v = r.get(f, "")
            row.append(_round(rc.number(v)) if idx in ISO_NUMERIC else v)
        iso.setdefault(r.get("profile", ""), []).append(row)
    for rows in iso.values():
        rows.sort(key=lambda x: x[0])
    v = dict(verdict or {})
    for k in ("oracle_gap", "gap_closed"):
        v[k] = _round(rc.number(v.get(k)))
    return {"kind": "recs", "profiles": profiles, "iso": iso, "verdict": v,
            "warnings": {"header": WARN_HEADER, "rows": [[r.get(f, "") for f in WARN_FIELDS] for r in warnings]},
            "taxon": {"header": TAXON_HEADER, "rows": [[r.get(f, "") for f in TAXON_FIELDS] for r in taxon]},
            "evalHeader": EVAL_HEADER, "evalRows": [[r.get(f, "") for f in EVAL_FIELDS] for r in evaluation]}


def rings_payload(data_dir):
    """Payload for the AMR ring tower read from <sample>/<tool>.amr_placement.tsv and truth files, or None."""
    if not data_dir or not Path(data_dir).is_dir():
        return None
    samples, order, classes = {}, [], set()
    for sample_dir in sorted(p for p in Path(data_dir).iterdir() if p.is_dir()):
        files = sorted(sample_dir.glob("*.amr_placement.tsv"))
        if not files:
            continue
        pl = {}
        for r in rc.read_tsv(str(sample_dir / "truth.tsv")) or []:
            length = rc.number(r.get("length"))
            if r.get("molecule_type") == "PLASMID" and length:
                pl[r["sequence_id"]] = [int(length), 0]
        for r in rc.read_tsv(str(sample_dir / "truth_circular.tsv")) or []:
            if r.get("sequence_id") in pl:
                pl[r["sequence_id"]][1] = 1
        genes, index, tools = [], {}, {}
        for path in files:
            tool = path.name[:-len(".amr_placement.tsv")]
            rows = []
            for r in rc.read_tsv(str(path)) or []:
                start, end = rc.number(r.get("start")), rc.number(r.get("end"))
                if start is None or end is None or not r.get("sequence_id"):
                    continue
                key = (r["sequence_id"], r.get("gene_name", ""), int(start), int(end), r.get("copy_id", ""))
                if key not in index:
                    index[key] = len(genes)
                    genes.append([r["sequence_id"], r.get("gene_name", ""), r.get("gene_class", "") or "other", int(start), int(end),
                                  r.get("copy_id", "")])
                    classes.add(genes[-1][2])
                rows.append([index[key], r.get("placement", "not_recovered"), r.get("covering_record", ""), r.get("assigned_bin", ""),
                             r.get("matched_plasmid", ""), r.get("replicon_type_correct", "")])
            tools[tool] = rows
        for g in genes:
            if g[0] not in pl:
                pl[g[0]] = [max(g[4], g[3]) + 1, 0]   # length unknown: just past the gene, so the ring still draws
        samples[sample_dir.name] = {"pl": pl, "g": genes, "tools": tools}
        order.append(sample_dir.name)
    if not samples:
        return None
    return {"kind": "rings", "order": order, "classes": sorted(classes), "samples": samples}


# ------------------------------------------------------------------------------------------------ markup
def json_script(sid, payload):
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    text = text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return f"<script type='application/json' id='{esc(sid)}'>{text}</script>"


def _legend_html(scene):
    glyph = {"square": "■", "circle": "●", "ring": "○", "diamond": "◆", "triangle": "▲", "cross": "✕", "line": "┅"}
    groups = {}
    for e in scene["legend"]:
        groups.setdefault(e["group"], []).append(e)
    out = []
    for g, items in groups.items():
        out.append("<span class='v3-ltitle'>" + esc(g) + "</span> " + " ".join(
            f"<span class='v3-lbtn v3-lstatic'><span style='color:{esc(e['color'])};text-shadow:0 0 1px #000'>{glyph.get(e['shape'], '■')}</span> {esc(e['label'])}</span>"
            for e in items))
    return "<div class='v3-legend'>" + "".join(f"<div class='v3-lgroup'>{x}</div>" for x in out) + "</div>"


def static_figure(scene, yaw, pitch):
    cam = fit_camera(scene, yaw, pitch)
    return (f"<div class='v3-static'>{svg_doc(scene, cam)}{_legend_html(scene)}"
            "<p class='v3-static-note'>Static view of the default camera. With JavaScript on, this becomes a rotatable 3D scene "
            "(drag, wheel, keyboard) with tooltips, filters and a detail panel.</p></div>")


def host(kind, sid, payload, scene, yaw, pitch, banner="", table_html=""):
    """One view: banner (always visible), the static SVG, the JSON payload and the collapsed raw table."""
    return (f"<div class='v3' data-v3='{esc(kind)}' data-src='{esc(sid)}'>{banner}{static_figure(scene, yaw, pitch)}</div>"
            + json_script(sid, payload)
            + (f"<details class='rpt-collapsible'><summary>Show the data table</summary>{table_html}</details>" if table_html else ""))


def verdict_words(v):
    """(tone, glyph, headline, detail) for the verdict banner; mirrored by verdictWords() in the JS."""
    gap = v.get("oracle_gap")
    gap = "n/a" if gap is None or gap == "" else f"{float(gap):g}"
    closed = v.get("gap_closed")
    closed = "not defined" if closed is None or closed == "" else f"{round(float(closed) * 1000) / 10:g}%"
    floor = f"{float(v.get('oracle_gap_floor', 0.02)):g}"
    kind = v.get("verdict")
    if kind == "benchmark_only":
        return ("neutral", "■", "Use the leaderboard: recommending per isolate cannot add value here.",
                f"The best single tool is already within {gap} F1 of the per-isolate oracle, below the {floor} floor, so choosing a tool per isolate has nothing left to gain.")
    if kind == "recommender_adds_value":
        return ("good", "●", "Recommending per isolate beats the single best tool.", f"It closes {closed} of the gap to the oracle (oracle gap {gap} F1).")
    if kind == "recommender_no_better":
        return ("caution", "▲", "Recommending per isolate does not beat the single best tool.",
                f"Gap closed {closed} of an oracle gap of {gap} F1: use the single best tool.")
    return ("neutral", "○", "Verdict not assessed.", v.get("note") or "The evaluation did not reach a verdict.")


def verdict_banner(v, profile_row=None):
    tone, glyph, head, detail = verdict_words(v or {})
    note = f" <span class='v3-muted'>({esc(v['note'])})</span>" if v and v.get("note") else ""
    return (f"<div class='v3-verdict v3-verdict-{tone}' role='status'><span class='v3-vglyph' aria-hidden='true'>{glyph}</span>"
            f"<div><strong>Verdict: {esc(head)}</strong> {esc(detail)}{note}</div></div>")


def assets():
    """CSS and scripts of the engine, emitted once per report (kept in assets/report/, loaded like the other fragments)."""
    root = Path(__file__).resolve().parent.parent / "assets" / "report"
    return "".join((root / name).read_text(encoding="utf-8") for name in ("viz3d_style.html", "viz3d_core.html", "viz3d_views.html"))
