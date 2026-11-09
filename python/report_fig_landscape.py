#!/usr/bin/env python3
"""
report_fig_landscape.py -- the 3D landscape figure: accuracy, completeness and structural fidelity (section id fig-landscape).

Each point is one (tool, isolate) run, or a tool mean. x = accuracy (alignment identity; precision where identity is absent, flagged),
y = completeness (reference-base recall, per-plasmid recall or CPRR), z = structural fidelity (NGOC, collinear fraction or
1/(1+events per Mb); alignment-derived and UNVALIDATED). The 3D view is an illustrative projection of metrics: the axes are metrics,
not a physical structure. A point with a missing axis is never plotted (and never drawn at 0): it is listed as "not plotted: reason".

What lives here
  * load_runs(): the per-run table read from scores.tsv, benchmark.accuracy.tsv, benchmark.ngoc.tsv, <sample>/structural_summary.tsv,
    tool_status.tsv and samples.tsv (each source optional);
  * py_build(): a mirror of build() in assets/report/fig_landscape_core.html, so a static default-camera SVG (the no-JavaScript and print
    fallback, shown until the script starts) uses the same projection as the live scene; the test runs node on both and compares;
  * the section: setup container (side panel with tabs) mounted by assets/report/fig_landscape_ui.html on the 3D engine of report_3d.

Standard library only.
"""
import html
import math
from pathlib import Path

import report_3d as r3
import report_common as rc

SECTION_ID = "fig-landscape"
NAV = [(SECTION_ID, "Accuracy, completeness, structure (3D)")]
ASSETS = ("fig_landscape_style.html", "fig_landscape_core.html", "fig_landscape_ui.html")
ENGINE_MARK = "root.PB3D = api"
S = 6.0
STACK = 0.02
FIELDS = ["sample", "tool", "track", "org", "identity", "precision", "recall", "f1", "plasmid_recall", "cprr", "ngoc", "collinear", "events",
          "aligned_bp", "runtime", "n_truth"]
SHAPE = {"short_read": "circle", "long_read": "triangle", "hybrid": "square"}
TOOL_COLOURS = ["#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#56B4E9", "#555555"]
RAMP = ["#440154", "#3b528b", "#21918c", "#5ec962", "#fde725"]
AXN = {"identity": "accuracy (identity, or precision)", "precision": "precision", "recall": "reference-base recall", "plasmid_recall": "per-plasmid recall",
       "cprr": "CPRR", "ngoc": "NGOC", "collinear": "collinear fraction", "events": "structural events per Mb"}
AXT = {"identity": "Accuracy (identity)", "precision": "Accuracy (precision)", "recall": "Completeness (recall)",
       "plasmid_recall": "Completeness (plasmid recall)", "cprr": "Completeness (CPRR)", "ngoc": "Structure: NGOC*",
       "collinear": "Structure: collinear*", "events": "Structure: 1/(1+events/Mb)*"}
CONT = {"runtime": "runtime", "n_truth": "n_truth", "f1": "f1"}

LEAD = ("A 3D scatter of how accurate, how complete and how structurally faithful each reconstruction is. Each point is one tool run on one isolate "
        "(switch to tool means in the Points tab). Horizontal axis: accuracy (alignment identity, or precision where identity is absent, "
        "ringed). Depth axis: completeness (recall, per-plasmid recall or CPRR). Vertical axis: structural fidelity (NGOC, collinear fraction or "
        "1/(1+events per Mb)); these structural measures are derived from alignments and are not validated against reads or graphs. "
        "The ideal corner is the cross at (1, 1, 1); the Pareto front rings points that no other point beats on all three axes. Colour is the tool, "
        "marker shape is the sequencing track, size is optional. Points at the same position are stacked with a count badge (no jitter). "
        "A run missing any chosen axis is not plotted, never drawn at zero: it is listed under Data as \"not plotted\" with the reason. "
        "Drag to rotate, wheel or +/- to zoom, arrow keys rotate, R resets; hover or focus a point for exact values, click or press Enter "
        "for details; the side panel sets axes, points, view, data and export, and its state is kept in the URL. The 3D view is an "
        "illustrative projection of metrics: the axes are metrics, not a physical structure, and distances along the depth axis are "
        "hard to read, so use the flat accuracy-by-completeness preset to read values. The demo data are synthetic and nearly flat, so many "
        "points coincide. Without JavaScript the static default view below is shown.")


# ------------------------------------------------------------------------------------------------ data
def _num(value):
    v = rc.number(value)
    return v if v is not None and math.isfinite(v) else None


def _r6(v):
    return None if v is None else round(v, 6)


def _tsv(path):
    return rc.read_tsv(str(path)) if Path(path).is_file() else None


def _per_run(data_dir, suffix):
    """Rows of every <data_dir>/<sample>/<tool><suffix> (the per-run fallback when the pooled benchmark table is absent)."""
    rows = []
    if data_dir and Path(data_dir).is_dir():
        for path in sorted(Path(data_dir).glob(f"*/*{suffix}")):
            rows += rc.read_tsv(str(path)) or []
    return rows or None


def load_runs(results_dir, data_dir, scores_path):
    """({'f': FIELDS, 'rows': [...], 'absent': {...}} or None when there is no scores table)."""
    scores = rc.read_tsv(scores_path) if scores_path and Path(scores_path).is_file() else None
    if not scores:
        return None
    results_dir = results_dir or ""
    base = Path(results_dir) if results_dir else None
    sources = data_dir or results_dir

    def pooled(name, suffix):
        rows = _tsv(base / name) if base else None
        return rows if rows is not None else _per_run(sources, suffix)

    acc = pooled("benchmark.accuracy.tsv", ".accuracy.tsv")
    ngoc = pooled("benchmark.ngoc.tsv", ".ngoc.tsv")
    struct, struct_found = {}, False
    if sources and Path(sources).is_dir():
        for path in sorted(Path(sources).glob("*/structural_summary.tsv")):
            struct_found = True
            for r in rc.read_tsv(str(path)) or []:
                struct[(path.parent.name, r.get("tool"))] = r
    status = _tsv(base / "tool_status.tsv") if base else None
    samples = _tsv(base / "samples.tsv") if base else None
    identity = {(r.get("sample"), r.get("tool")): _num(r.get("identity")) for r in (acc or [])
                if r.get("accuracy_status", "evaluated") in ("evaluated", "")}
    ng = {(r.get("sample"), r.get("tool")): _num(r.get("ngoc")) for r in (ngoc or [])}
    runtime = {(r.get("sample"), r.get("tool")): _num(r.get("runtime_seconds")) for r in (status or [])}
    organism = {r.get("sample_id"): r.get("organism") for r in (samples or [])}
    rows = []
    for r in scores:
        key = (r.get("sample"), r.get("tool"))
        st = struct.get(key, {})
        plasmids, correct = _num(r.get("cprr_plasmids")), _num(r.get("cprr_correct"))
        rows.append([r.get("sample"), r.get("tool"), r.get("analysis_track") or "unspecified", organism.get(r.get("sample")) or "",
                     _r6(identity.get(key)), _r6(_num(r.get("precision"))), _r6(_num(r.get("recall"))), _r6(_num(r.get("f1"))),
                     _r6(_num(r.get("plasmid_recall"))), _r6(correct / plasmids) if plasmids and correct is not None else None,
                     _r6(ng.get(key)), _r6(_num(st.get("collinear_fraction"))), _num(st.get("events_total")), _num(st.get("aligned_bp")),
                     runtime.get(key), _num(r.get("true_plasmid_count"))])
    rows.sort(key=lambda row: (str(row[0]), str(row[1]), str(row[2])))
    absent = {}
    if acc is None:
        absent["identity"] = "benchmark.accuracy.tsv"
    if ngoc is None:
        absent["ngoc"] = "benchmark.ngoc.tsv"
    if not struct_found:
        absent["collinear"] = absent["events"] = "structural_summary.tsv"
    return {"kind": "landscape", "f": FIELDS, "rows": rows, "absent": absent}


# ------------------------------------------------------------------------------------------------ scene builder (mirror of build())
def defaults():
    return {"mode": "runs", "x": "identity", "y": "recall", "z": "ngoc", "scale": "linear", "range": "full", "cx": [0, 1], "cy": [0, 1],
            "cz": [0, 1], "fx": 0, "fy": 0, "fz": 0, "size": "none", "colour": "tool", "shape": 1, "ps": 1, "op": 1, "labels": 0,
            "pareto_only": 0, "grid": 1, "floor": 1, "axlab": 1}


def default_hidden():
    return {"O:cent": True}


def _fin(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def metric(r, key):
    if key == "identity":
        if _fin(r["identity"]):
            return (r["identity"], "identity")
        if _fin(r["precision"]):
            return (r["precision"], "precision")
        return None
    if key == "events":
        if _fin(r["events"]) and _fin(r["aligned_bp"]) and r["aligned_bp"] > 0:
            return (1 / (1 + r["events"] / (r["aligned_bp"] / 1e6)), "events")
        return None
    return (r[key], key) if _fin(r[key]) else None


def nice_ticks(lo, hi):
    span = hi - lo
    steps = [0.5, 0.2, 0.1, 0.05, 0.02, 0.01, 0.005, 0.002, 0.001, 0.0005, 0.0002, 0.0001, 0.00005, 0.00002, 0.00001]
    step = steps[-1]
    for s in steps:
        if span / s >= 4 - 1e-9:
            step = s
            break
    d = 0 if step >= 1 else math.ceil(-math.log10(step) - 1e-9)
    k0, k1 = math.ceil(lo / step - 1e-9), math.floor(hi / step + 1e-9)
    return [k * step for k in range(k0, k1 + 1)], d


def axis_range(vs, mode, custom):
    if mode == "custom":
        lo = custom[0] if custom and _fin(custom[0]) else 0
        hi = custom[1] if custom and _fin(custom[1]) else 1
        return [lo, hi] if hi > lo else [0, 1]
    if mode == "zoom" and vs:
        mn, mx = min(vs), max(vs)
        pad = (mx - mn) * 0.08
        lo, hi = max(0, mn - pad), min(1, mx + pad)
        if hi - lo < 1e-9:
            lo = max(0, hi - 0.1)
            if hi - lo < 1e-9:
                hi = lo + 0.1
        return [lo, hi]
    return [0, 1]


def rank_pos(vs):
    n = len(vs)
    idx = sorted(range(n), key=lambda i: (vs[i], i))
    out = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and vs[idx[j + 1]] == vs[idx[i]]:
            j += 1
        avg = (i + j) / 2.0
        for k in range(i, j + 1):
            out[idx[k]] = avg / (n - 1) if n > 1 else 0.5
        i = j + 1
    return out


def _mean(a):
    return sum(a) / len(a) if a else None


def _sd(a):
    if len(a) < 2:
        return None
    m = _mean(a)
    return math.sqrt(sum((v - m) ** 2 for v in a) / (len(a) - 1))


def _mode(lst):
    cnt = {}
    for v in lst:
        cnt[v] = cnt.get(v, 0) + 1
    best, bc = None, 0
    for v in lst:
        if cnt[v] > bc:
            best, bc = v, cnt[v]
    return best


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def ramp_colour(t):
    t = _clamp(t, 0, 1)
    n = len(RAMP) - 1
    i = min(n - 1, int(math.floor(t * n)))
    u = t * n - i

    def c(h):
        v = int(h[1:], 16)
        return [v >> 16 & 255, v >> 8 & 255, v & 255]
    a, b = c(RAMP[i]), c(RAMP[i + 1])
    return "#" + "".join("%02x" % int(math.floor(a[k] + (b[k] - a[k]) * u + 0.5)) for k in range(3))


def rows_of(data):
    out = []
    for i, a in enumerate(data["rows"]):
        o = {"i": i}
        o.update(dict(zip(data.get("f") or FIELDS, a)))
        o["org"] = o.get("org") or "unknown"
        out.append(o)
    return out


def _uniq(rows, key):
    return sorted({r[key] for r in rows})


def _reason(data, key):
    a = (data.get("absent") or {}).get(key)
    return AXN[key] + " not available" + (f" ({a} not found)" if a else "")


def _size_of(r, key):
    return r["runtime"] if key == "runtime" else r["n_truth"] if key == "n_truth" else None


def py_build(data, vals=None, hidden=None):
    """Same scene as build() in fig_landscape_core.html (prims, legend, model summary); no tooltips."""
    v = defaults()
    v.update(vals or {})
    hidden = default_hidden() if hidden is None else hidden
    rows = rows_of(data)
    tools, tracks, species = _uniq(rows, "tool"), _uniq(rows, "track"), _uniq(rows, "org")
    visible = [r for r in rows if not hidden.get("T:" + r["tool"]) and not hidden.get("K:" + r["track"]) and not hidden.get("S:" + r["org"])]
    plotted, not_plotted = [], []
    for r in visible:
        ks = [v["x"], v["y"], v["z"]]
        m = [metric(r, k) for k in ks]
        why = [_reason(data, ks[a]) for a in range(3) if not m[a]]
        if why:
            not_plotted.append({"r": r, "why": "; ".join(why)})
        else:
            plotted.append({"r": r, "x": m[0][0], "y": m[1][0], "z": m[2][0], "xs": m[0][1]})
    pts = []
    if v["mode"] == "tools":
        for ti, t in enumerate(tools):
            g = [p for p in plotted if p["r"]["tool"] == t]
            if not g:
                if not hidden.get("T:" + t):
                    not_plotted.append({"r": None, "tool": t, "why": "no run of this tool has all three metrics"})
                continue
            sz = [x for x in (_size_of(p["r"], v["size"]) for p in g) if _fin(x)]
            cv = [x for x in (p["r"][CONT[v["colour"]]] if v["colour"] in CONT else None for p in g) if _fin(x)]
            xs, ys, zs = [p["x"] for p in g], [p["y"] for p in g], [p["z"] for p in g]
            pts.append({"id": f"c{ti}", "grp": f"c{ti}", "kind": "tool", "tool": t, "track": _mode([p["r"]["track"] for p in g]),
                        "sp": _mode([p["r"]["org"] for p in g]), "x": _mean(xs), "y": _mean(ys), "z": _mean(zs),
                        "xs": "precision" if any(p["xs"] == "precision" for p in g) else "identity", "n": len(g),
                        "sd": {"x": _sd(xs), "y": _sd(ys), "z": _sd(zs)} if len(g) > 1 else None, "sizeV": _mean(sz), "colV": _mean(cv)})
    else:
        for p in plotted:
            r = p["r"]
            sz = _size_of(r, v["size"])
            cv = r[CONT[v["colour"]]] if v["colour"] in CONT else None
            pts.append({"id": f"r{r['i']}", "grp": f"r{r['i']}", "kind": "run", "r": r, "tool": r["tool"], "track": r["track"], "sp": r["org"],
                        "x": p["x"], "y": p["y"], "z": p["z"], "xs": p["xs"], "n": 1, "sd": None,
                        "sizeV": sz if _fin(sz) else None, "colV": cv if _fin(cv) else None})

    def dominates(a, b):
        return a["x"] >= b["x"] and a["y"] >= b["y"] and a["z"] >= b["z"] and (a["x"] > b["x"] or a["y"] > b["y"] or a["z"] > b["z"])
    for p in pts:
        p["front"] = not any(q is not p and dominates(q, p) for q in pts)
    n_front = sum(1 for p in pts if p["front"])
    if v["pareto_only"]:
        pts = [p for p in pts if p["front"]]

    keys = ["x", "y", "z"]
    cust = {"x": v["cx"], "y": v["cy"], "z": v["cz"]}
    flip = {"x": v["fx"], "y": v["fy"], "z": v["fz"]}
    ax = {}
    for a in keys:
        vs = [p[a] for p in pts]
        rk = v["scale"] == "rank"
        rg = [0, 1] if rk else axis_range(vs, v["range"], cust[a])
        if rk:
            pos = rank_pos(vs)
        else:
            pos = [_clamp((x - rg[0]) / (rg[1] - rg[0]), 0, 1) for x in vs]
        if flip[a]:
            pos = [1 - u for u in pos]
        ax[a] = {"rg": rg, "pos": pos, "rank": rk, "flip": bool(flip[a])}

    def pos_of(a, val):
        g = ax[a]
        if g["rank"]:
            return None
        u = _clamp((val - g["rg"][0]) / (g["rg"][1] - g["rg"][0]), 0, 1)
        return 1 - u if g["flip"] else u

    def W(px, py, pz):
        return [S * px, S * pz, -S * py]

    prims = []
    if v["floor"]:
        prims.append({"k": "poly", "role": "floor", "layer": 0, "cls": "v3-floor", "pts": [[0, 0, 0], [S, 0, 0], [S, 0, -S], [0, 0, -S]]})
        prims.append({"k": "poly", "role": "wall", "layer": 0, "cls": "ls-wall", "pts": [[0, 0, -S], [S, 0, -S], [S, S, -S], [0, S, -S]]})
        prims.append({"k": "poly", "role": "wall", "layer": 0, "cls": "ls-wall", "pts": [[0, 0, 0], [0, 0, -S], [0, S, -S], [0, S, 0]]})
    tk = {}
    for a in keys:
        g = ax[a]
        if g["rank"]:
            tk[a] = [{"u": 1 - f if g["flip"] else f, "t": f"{int(math.floor(f * 100 + 0.5))}%"} for f in (0, 0.25, 0.5, 0.75, 1)]
        else:
            ticks, d = nice_ticks(g["rg"][0], g["rg"][1])
            tk[a] = [{"u": pos_of(a, t), "t": f"{t:.{d}f}"} for t in ticks]
    if v["grid"]:
        for t in tk["x"]:
            prims.append({"k": "line", "role": "grid", "layer": 0, "cls": "v3-grid", "pts": [[S * t["u"], 0, 0], [S * t["u"], 0, -S]]})
            prims.append({"k": "line", "role": "grid", "layer": 0, "cls": "v3-grid", "pts": [[S * t["u"], 0, -S], [S * t["u"], S, -S]]})
        for t in tk["y"]:
            prims.append({"k": "line", "role": "grid", "layer": 0, "cls": "v3-grid", "pts": [[0, 0, -S * t["u"]], [S, 0, -S * t["u"]]]})
            prims.append({"k": "line", "role": "grid", "layer": 0, "cls": "v3-grid", "pts": [[0, 0, -S * t["u"]], [0, S, -S * t["u"]]]})
        for t in tk["z"]:
            prims.append({"k": "line", "role": "grid", "layer": 0, "cls": "v3-grid", "pts": [[0, S * t["u"], -S], [S, S * t["u"], -S]]})
            prims.append({"k": "line", "role": "grid", "layer": 0, "cls": "v3-grid", "pts": [[0, S * t["u"], 0], [0, S * t["u"], -S]]})
    prims.append({"k": "line", "role": "axis", "layer": 0, "cls": "v3-axis", "pts": [[0, 0, 0], [S, 0, 0]]})
    prims.append({"k": "line", "role": "axis", "layer": 0, "cls": "v3-axis", "pts": [[S, 0, 0], [S, 0, -S]]})
    prims.append({"k": "line", "role": "axis", "layer": 0, "cls": "v3-axis", "pts": [[0, 0, 0], [0, S, 0]]})
    if v["axlab"]:
        for t in tk["x"]:
            prims.append({"k": "text", "role": "xtick", "layer": 2, "cls": "v3-t-m", "p": [S * t["u"], 0, 0], "t": t["t"], "dy": 15})
        for t in tk["y"]:
            prims.append({"k": "text", "role": "ytick", "layer": 2, "cls": "v3-t-m", "p": [S, 0, -S * t["u"]], "t": t["t"], "anchor": "start", "dx": 8, "dy": 4})
        for t in tk["z"]:
            prims.append({"k": "text", "role": "ztick", "layer": 2, "cls": "v3-t-m", "p": [0, S * t["u"], 0], "t": t["t"], "anchor": "end", "dx": -7, "dy": 4})

        def sfx(a):
            return (" (rank)" if ax[a]["rank"] else "") + (" (flipped)" if ax[a]["flip"] else "")
        prims.append({"k": "text", "role": "xtitle", "layer": 2, "cls": "v3-t-b", "p": [S / 2, 0, 0], "t": AXT[v["x"]] + sfx("x"), "dy": 42})
        prims.append({"k": "text", "role": "ytitle", "layer": 2, "cls": "v3-t-b", "p": [S, 0, -S / 2], "t": AXT[v["y"]] + sfx("y"), "anchor": "start", "dx": 40, "dy": 4})
        prims.append({"k": "text", "role": "ztitle", "layer": 2, "cls": "v3-t-b", "p": [0, S, 0], "t": AXT[v["z"]] + sfx("z"), "anchor": "start", "dx": -20, "dy": -14})

    groups, gmap = [], {}
    for i, p in enumerate(pts):
        p["w"] = W(ax["x"]["pos"][i], ax["y"]["pos"][i], ax["z"]["pos"][i])
        key = "|".join(str(int(math.floor(p["w"][k] / STACK + 0.5))) for k in range(3))
        if key not in gmap:
            gmap[key] = {"key": key, "w": p["w"], "members": []}
            groups.append(gmap[key])
        gmap[key]["members"].append(p)
    szv = [p["sizeV"] for p in pts if _fin(p["sizeV"])]
    cvv = [p["colV"] for p in pts if _fin(p["colV"])]
    szr = [min(szv), max(szv)] if szv else None
    cvr = [min(cvv), max(cvv)] if cvv else None
    cat_key = {"tool": "tool", "track": "track", "species": "sp"}.get(v["colour"])
    cat_list = tools if v["colour"] == "tool" else tracks if v["colour"] == "track" else species

    def colour_of(p):
        if cat_key:
            ci = cat_list.index(p[cat_key]) if p[cat_key] in cat_list else 0
            return TOOL_COLOURS[ci % len(TOOL_COLOURS)]
        if not _fin(p["colV"]):
            return "#9a9a9a"
        return ramp_colour((p["colV"] - cvr[0]) / (cvr[1] - cvr[0]) if cvr[1] > cvr[0] else 0.5)

    def radius_of(p):
        base = 5.5
        if v["size"] != "none" and _fin(p["sizeV"]) and szr:
            base = 4.5 + 5.5 * (p["sizeV"] - szr[0]) / (szr[1] - szr[0]) if szr[1] > szr[0] else 5.5
        return base * v["ps"]

    def shape_of(p):
        return SHAPE.get(p["track"], "diamond") if v["shape"] else "circle"

    cents = []
    if v["mode"] == "tools":
        cents = list(pts)
    elif not hidden.get("O:cent"):
        for ti, t in enumerate(tools):
            g = [p for p in pts if p["tool"] == t]
            if not g:
                continue
            gi = [i for i, p in enumerate(pts) if p["tool"] == t]
            cents.append({"id": f"c{ti}", "grp": f"c{ti}", "kind": "cent", "tool": t, "track": _mode([p["track"] for p in g]), "n": len(g),
                          "x": _mean([p["x"] for p in g]), "y": _mean([p["y"] for p in g]), "z": _mean([p["z"] for p in g]),
                          "pos": [sum(ax[a]["pos"][j] for j in gi) / len(gi) for a in keys],
                          "sd": {"x": _sd([p["x"] for p in g]), "y": _sd([p["y"] for p in g]), "z": _sd([p["z"] for p in g])} if len(g) > 1 else None})

    if not hidden.get("O:drop"):
        for g in groups:
            prims.append({"k": "line", "role": "drop", "layer": 1, "cls": "v3-conn", "pts": [[g["w"][0], g["w"][1], g["w"][2]], [g["w"][0], 0, g["w"][2]]]})
    if not hidden.get("O:floor"):
        for g in groups:
            prims.append({"k": "mark", "role": "shadow", "shape": "circle", "r": 2.6, "fill": "#8c8c8c", "stroke": "#ffffff", "sw": 0.8,
                          "p": [g["w"][0], 0, g["w"][2]], "bias": -0.01})
    if not hidden.get("O:sd"):
        for c in cents:
            if not c["sd"]:
                continue
            cpos = c.get("pos")
            if cpos is None:
                i = pts.index(c)
                cpos = [ax["x"]["pos"][i], ax["y"]["pos"][i], ax["z"]["pos"][i]]
            col = colour_of(c) if v["colour"] == "tool" else "#17231d"
            for ai, a in enumerate(keys):
                g = ax[a]
                d = c["sd"][a] / (g["rg"][1] - g["rg"][0])
                if g["rank"] or not math.isfinite(d):
                    continue
                lo, hi = _clamp(cpos[ai] - d, 0, 1), _clamp(cpos[ai] + d, 0, 1)
                p0, p1 = list(cpos), list(cpos)
                p0[ai], p1[ai] = lo, hi
                prims.append({"k": "line", "role": "sd", "layer": 1, "cls": "ls-sd", "pts": [W(*p0), W(*p1)], "stroke": col, "w": 2.4, "op": 0.9, "cap": True})
    n_stack = 0
    for g in groups:
        ms = sorted(g["members"], key=lambda p: -radius_of(p))
        if len(ms) > 1:
            n_stack += 1
        for i, p in enumerate(ms):
            r = max(2.6, radius_of(p) - 2.2 * i)
            if not hidden.get("O:pareto") and p["front"] and len(pts) > 0 and n_front < len(pts):
                prims.append({"k": "mark", "role": "pareto", "shape": "ring", "r": r + 5, "fill": "#17231d", "bg": "none", "p": g["w"], "bias": -0.02})
            if p["xs"] == "precision":
                prims.append({"k": "mark", "role": "fallback", "shape": "ring", "r": r + 2.5, "fill": "#777777", "bg": "none", "p": g["w"], "bias": -0.01})
            prims.append({"k": "mark", "role": "pt", "cls": "ls-pt", "id": p["id"], "grp": p["grp"], "p": g["w"], "bias": 0.02 + 0.001 * i,
                          "shape": shape_of(p), "r": r, "fill": colour_of(p), "stroke": "#ffffff", "sw": 1.2})
        if len(ms) > 1:
            prims.append({"k": "text", "role": "badge", "layer": 2, "cls": "v3-t-b ls-badge", "size": 10, "p": g["w"], "t": f"×{len(ms)}", "anchor": "start", "dx": 9, "dy": -9})
        if v["labels"]:
            prims.append({"k": "text", "role": "label", "layer": 2, "cls": "v3-t-m", "size": 10, "p": g["w"], "t": ms[0]["tool"], "anchor": "start", "dx": 9, "dy": 14})
    if v["mode"] != "tools":
        for c in cents:
            w = W(*c["pos"])
            prims.append({"k": "mark", "role": "centroid", "cls": "ls-pt", "id": c["id"], "grp": c["grp"], "p": w, "bias": 0.05, "shape": "cross", "r": 7,
                          "fill": colour_of(c) if v["colour"] == "tool" else "#17231d", "stroke": "#ffffff"})
            prims.append({"k": "text", "role": "clabel", "layer": 2, "cls": "v3-t-b", "size": 10, "p": w, "t": c["tool"], "anchor": "start", "dx": 10, "dy": 3})
    ideal = False
    if not hidden.get("O:ideal"):
        iu = [pos_of("x", 1), pos_of("y", 1), pos_of("z", 1)]
        if all(u is not None for u in iu) and all(ax[a]["rg"][1] >= 1 - 1e-9 for a in keys):
            ideal = True
            wi = W(*iu)
            prims.append({"k": "mark", "role": "ideal", "shape": "cross", "r": 7, "fill": "#17231d", "stroke": "#ffffff", "p": wi, "bias": 0.04})
            prims.append({"k": "text", "role": "ideallabel", "layer": 2, "cls": "v3-t-b", "size": 10, "p": wi, "t": "Ideal (1, 1, 1)", "anchor": "start", "dx": 10, "dy": -8})
    legend = []
    col_list = cat_list if cat_key else tools
    group_name = {"tool": "Tool (colour)", "track": "Track (colour)", "species": "Species (colour)"}.get(v["colour"], "Tool (filter)")
    for i, c in enumerate(col_list):
        legend.append({"group": group_name, "label": c, "color": TOOL_COLOURS[i % len(TOOL_COLOURS)] if cat_key else "#777777", "shape": "circle"})
    if v["shape"]:
        for t in tracks:
            legend.append({"group": "Track (shape)", "label": t.replace("_", " "), "color": "#555555", "shape": SHAPE.get(t, "diamond")})
    return {"prims": prims, "legend": legend, "title": "Accuracy, completeness and structural fidelity: 3D scatter (illustrative projection of metrics)",
            "desc": "Each point is one tool run (or a tool mean). Horizontal axis accuracy, depth axis completeness, vertical axis structural fidelity. "
                    "The axes are metrics, not a physical structure.",
            "model": {"plotted": len(plotted), "not_plotted": [[n["r"]["sample"] if n["r"] else "", n["r"]["tool"] if n["r"] else n["tool"], n["why"]] for n in not_plotted],
                      "visible": len(visible), "total": len(rows), "n_front": n_front, "n_stack": n_stack, "ideal": ideal, "n_pts": len(pts)}}


# ------------------------------------------------------------------------------------------------ markup
def _fmt(v, d=4):
    return "not available" if v is None else f"{v:.{d}f}"


def data_table(data):
    """Collapsed raw table of the default scene: plotted rows, then the not-plotted rows with their reason."""
    scene = py_build(data)
    rows_by_id = {r["i"]: r for r in rows_of(data)}
    body = []
    for p in scene["prims"]:
        if p.get("role") == "pt":
            r = rows_by_id[int(p["id"][1:])]
            x = metric(r, "identity")
            body.append([r["sample"], r["tool"], r["track"], _fmt(x[0]) + (" (precision)" if x[1] == "precision" else ""), _fmt(r["recall"]), _fmt(r["ngoc"])])
    table = rc.panel(["Sample", "Tool", "Track", "Accuracy", "Completeness (recall)", "Structure (NGOC, unvalidated)"], body, "No run has all three metrics.")
    np_rows = scene["model"]["not_plotted"]
    npt = rc.panel(["Sample", "Tool", "Not plotted: reason"], np_rows, "") if np_rows else ""
    return (f"<details class='rpt-collapsible'><summary>Show the data table ({scene['model']['plotted']} plotted, {len(np_rows)} not plotted)</summary>"
            f"{table}{npt}</details>")


def _legend_html(scene):
    return r3._legend_html(scene)


def static_figure(data):
    scene = py_build(data)
    cam = r3.fit_camera(scene, -32.0, 26.0)
    return (f"<div class='v3-static ls-static'>{r3.svg_doc(scene, cam)}{_legend_html(scene)}"
            "<p class='v3-static-note'>Static view of the default camera. With JavaScript on this becomes a rotatable 3D scene with a setup panel "
            "(axes, points, view, data, detail, export). * Structural fidelity is alignment-derived and unvalidated. Ringed markers use precision "
            "because alignment identity is not available. Points at the same position are stacked with a count badge (no jitter).</p>"
            f"{data_table(data)}</div>"), scene


def assets_html(page):
    root = Path(__file__).resolve().parent.parent / "assets" / "report"
    parts = []
    if ENGINE_MARK not in page:
        parts += [(root / n).read_text(encoding="utf-8") for n in ("viz3d_style.html", "viz3d_core.html")]
    parts += [(root / n).read_text(encoding="utf-8") for n in ASSETS]
    return "".join(parts)


def build_section(page, results_dir, data_dir, scores_path):
    data = load_runs(results_dir, data_dir, scores_path)
    if not data:
        return rc.section(SECTION_ID, "Accuracy, completeness and structural fidelity", LEAD,
                          rc.not_run("no scores table was found, so there are no runs to plot."))
    if not data["rows"]:
        return rc.section(SECTION_ID, "Accuracy, completeness and structural fidelity", LEAD, rc.not_run("the scores table has no runs."))
    static, _scene = static_figure(data)
    body = (assets_html(page) + f"<div class='ls' id='ls-root' data-ls='1'>{static}</div>" + r3.json_script("ls-data", data))
    return rc.section(SECTION_ID, "Accuracy, completeness and structural fidelity", LEAD, body)


def inject(page, results_dir, data_dir, scores_path):
    section = str(build_section(page, results_dir, data_dir, scores_path))
    return rc.inject_sections(rc.add_style(page), section, NAV)
