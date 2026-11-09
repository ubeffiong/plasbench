#!/usr/bin/env python3
"""
report_fig_stats.py -- two statistical figures of the report: CPRR distributions and a forest plot of CPRR differences.

  fig-distributions  CPRR per isolate, per tool, within species / track / plasmid-content band / reference tier: violin or box,
                     with EVERY isolate drawn on top, the cluster-bootstrap CI of the pooled CPRR when the leaderboard has one,
                     n in the axis labels, and a rule that fewer than MIN_VIOLIN isolates are drawn as points only.
  fig-forest         one row per stratum (species, isolate plasmid content, plasmid size, reference tier, optionally MOB type,
                     replicon, AMR carriage) for one tool; contrasts: stratum minus the tool's overall CPRR, the absolute stratum
                     CPRR, or tool A minus tool B.

Unit of analysis. The isolate is the unit: isolate CPRR = cprr_correct / cprr_plasmids (scores.tsv). An isolate without an assessable
plasmid has a blank CPRR; it is EXCLUDED AND COUNTED, never drawn as 0. The leaderboard's cprr_ci_low/high is a cluster bootstrap over
independent clonal groups and is drawn as such. Strata have no cluster bootstrap in the tables, so their interval is a Wilson interval
over plasmids pooled (not cluster-aware, labelled so). The synthetic demo data are flat and tiny: read the figures as an illustration.

Formulas (mirrored in assets/report/fig_stats_core.html; test/test_report_fig_stats.py checks the two agree)
  quartiles     linear interpolation between order statistics (R type 7): h = (n-1)p, Q = x[floor h] + (h - floor h)(x[ceil h] - x[floor h])
  box           median, Q1, Q3; whiskers reach the most extreme observation within 1.5 IQR of the box
  violin        Gaussian kernel density, bandwidth h = max(0.9 min(s, IQR/1.34) n^(-1/5), 0.02) (Silverman's rule; s is the sample SD,
                IQR/1.34 is used only when IQR > 0; the 0.02 floor stops a spike when all isolates tie). Evaluated on 41 grid points in
                [0, 1] and CLIPPED there (not renormalised); each violin is scaled to the same maximum half-width.
  n < 5         points only: no density and no box is drawn from fewer than 5 isolates.
  strip         isolates with an identical value share a row of offsets (i - (k-1)/2) * step, ordered by sample id: no randomness.
  Wilson        centre (p + z^2/2n) / (1 + z^2/n), half width z sqrt(p(1-p)/n + z^2/4n^2) / (1 + z^2/n), z = 1.959964
  Newcombe      difference d = p1 - p2: lower d - sqrt((p1-l1)^2 + (u2-p2)^2), upper d + sqrt((u1-p1)^2 + (p2-l2)^2) (hybrid score)
  vs overall    estimate p_s - p_all; interval = Wilson interval of p_s minus p_all (the overall value is treated as a fixed reference)
  underpowered  fewer than SCORECARD_MIN_SAMPLES (5) isolates in the stratum: hollow marker, labelled.

Standard library only.
"""
import json
import math
import os
from pathlib import Path

import report_common as rc
import report_svg as rs

MIN_VIOLIN = 5
MIN_N = int(os.environ.get("SCORECARD_MIN_SAMPLES", "5"))
GRID = 41
BW_FLOOR = 0.02
Z = 1.959963984540054
SECTIONS = [("fig-distributions", "CPRR distributions"), ("fig-forest", "CPRR differences")]
TOOL_COLOURS = [rs.OKABE_ITO["blue"], rs.OKABE_ITO["vermillion"], rs.OKABE_ITO["green"], rs.OKABE_ITO["orange"],
                rs.OKABE_ITO["purple"], rs.OKABE_ITO["sky"], "#882255", "#117733"]
TIER_NAME = {"1": "Tier 1", "2": "Tier 2", "3": "Tier 3 (provisional)", "unrecorded": "Tier not recorded"}
FAMILIES = [("species", "Species"), ("content", "Isolate plasmid content (total bp)"), ("tier", "Reference tier"),
            ("size", "Plasmid size"), ("mob", "MOB type"), ("replicon", "Replicon"), ("amr", "AMR carriage")]
DEFAULT_FAMILIES = ("species", "content", "tier", "size")
SIZE_ORDER = ["<10kb", "10-50kb", ">50kb"]
CONTENT_ORDER = ["<10 kb", "10-100 kb", ">100 kb"]
GROUPS = [("species", "Species"), ("track", "Track"), ("content", "Plasmid content band"), ("tier", "Reference tier")]
RH, FX0, FXW = 22, 250, 330          # forest row height, plot left, plot width
SW, FG, LM, TOP, PH, BOT = 34, 22, 56, 26, 300, 130   # distribution geometry


# ------------------------------------------------------------------------------------------------ statistics
def quantile7(xs, p):
    s = sorted(xs)
    h = (len(s) - 1) * p
    lo = int(math.floor(h))
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (h - lo) * (s[hi] - s[lo])


def box_stats(vals):
    s = sorted(vals)
    q1, med, q3 = quantile7(s, 0.25), quantile7(s, 0.5), quantile7(s, 0.75)
    iqr = q3 - q1
    return {"n": len(s), "q1": q1, "med": med, "q3": q3, "wlo": min(v for v in s if v >= q1 - 1.5 * iqr),
            "whi": max(v for v in s if v <= q3 + 1.5 * iqr), "mean": sum(s) / len(s)}


def bandwidth(vals):
    n = len(vals)
    mu = sum(vals) / n
    sd = math.sqrt(sum((v - mu) ** 2 for v in vals) / (n - 1)) if n > 1 else 0.0
    iqr = quantile7(vals, 0.75) - quantile7(vals, 0.25)
    a = min(sd, iqr / 1.34) if iqr > 0 else sd
    return max(0.9 * a * n ** -0.2, BW_FLOOR)


def kde(vals, bw):
    n = len(vals)
    c = 1.0 / (n * bw * math.sqrt(2 * math.pi))
    return [c * sum(math.exp(-0.5 * (((i / (GRID - 1)) - v) / bw) ** 2) for v in vals) for i in range(GRID)]


def jitter(items):
    """items = [(value, id)] -> [(j, k)] in input order: j = i - (k-1)/2 within the k isolates sharing a value (ordered by id)."""
    order = sorted(range(len(items)), key=lambda i: (items[i][0], str(items[i][1])))
    out = [None] * len(items)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and abs(items[order[end + 1]][0] - items[order[start]][0]) < 1e-9:
            end += 1
        k = end - start + 1
        for i in range(k):
            out[order[start + i]] = (i - (k - 1) / 2.0, k)
        start = end + 1
    return out


def wilson(c, n):
    if not n:
        return None
    p = c / n
    d = 1 + Z * Z / n
    centre = (p + Z * Z / (2 * n)) / d
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return [max(0.0, centre - half), min(1.0, centre + half)]


def newcombe(c1, n1, c2, n2):
    if not n1 or not n2:
        return None
    p1, p2 = c1 / n1, c2 / n2
    l1, u1 = wilson(c1, n1)
    l2, u2 = wilson(c2, n2)
    d = p1 - p2
    return [d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2), d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)]


# ------------------------------------------------------------------------------------------------ data
def band_content(bp):
    if bp is None:
        return "not recorded"
    return CONTENT_ORDER[0] if bp < 10000 else CONTENT_ORDER[1] if bp < 100000 else CONTENT_ORDER[2]


def _r(x, d=6):
    return None if x is None else round(x, d)


def build_payload(results_dir, data_dir, scores_path):
    """The figure data, or (None, reason). Counts are integers; blank CPRR is excluded and counted."""
    scores = rc.read_tsv(scores_path)
    if scores is None:
        return None, "scores.tsv was not found."
    if scores and "cprr_plasmids" not in scores[0]:
        return None, "scores.tsv has no cprr_plasmids / cprr_correct columns (CPRR was not computed)."
    sheet = {}
    for base in (results_dir, data_dir):
        rows = rc.read_tsv(os.path.join(base, "samples.tsv")) if base else None
        if rows:
            sheet = {r.get("sample_id") or r.get("sample"): r for r in rows}
            break
    prov = {r["sample"]: r.get("reference_tier") for r in (rc.read_tsv(os.path.join(results_dir, "benchmark.truth_provenance.tsv")) or [])
            if r.get("sample")}
    samples, sidx, bp = [], {}, {}
    for r in scores:
        bp.setdefault(r["sample"], rc.number(r.get("true_plasmid_bp")))
    for r in scores:
        s = r["sample"]
        if s in sidx:
            continue
        tier = (prov.get(s) or "").strip()
        sidx[s] = len(samples)
        samples.append([s, (sheet.get(s, {}).get("organism") or "not recorded"), band_content(bp.get(s)),
                        tier if tier in ("1", "2", "3") else "unrecorded"])
    tools, tidx = [], {}
    pts, excl, seen = [], [], set()
    for r in scores:
        track = r.get("analysis_track") or "not recorded"
        key = (track, r["tool"])
        if key not in tidx:
            tidx[key] = len(tools)
            tools.append([f"{track}|{r['tool']}", track, r["tool"]])
        t, s = tidx[key], sidx[r["sample"]]
        if (t, s) in seen:
            continue
        seen.add((t, s))
        total, correct = rc.number(r.get("cprr_plasmids")), rc.number(r.get("cprr_correct"))
        if total and correct is not None and total > 0:
            pts.append([t, s, int(round(correct)), int(round(total))])
        else:
            excl.append([t, s])
    lb, best = {}, []
    got_track = set()
    for r in rc.read_tsv(os.path.join(results_dir, "benchmark.leaderboard.tsv")) or []:
        key = (r.get("analysis_track") or "not recorded", r.get("tool"))
        if key not in tidx:
            continue
        total = rc.number(r.get("cprr_plasmids"))
        if not total:
            continue
        t = tidx[key]
        lb[str(t)] = [_r(rc.number(r.get("cprr")), 6), _r(rc.number(r.get("cprr_ci_low")), 6), _r(rc.number(r.get("cprr_ci_high")), 6),
                      int(round(rc.number(r.get("cprr_correct")) or 0)), int(round(total)), rc.number(r.get("n_independent_clusters"))]
        if key[0] not in got_track:
            got_track.add(key[0])
            best.append(t)
    with_pts = {p[0] for p in pts}
    best = [t for t in best if t in with_pts] or sorted(with_pts)[:1]
    strata, overall = {}, {}
    table = {}
    for r in rc.read_tsv(os.path.join(results_dir, "benchmark.recovery_by_replicon.tsv")) or []:
        key = (r.get("analysis_track") or "not recorded", r.get("tool"))
        if key in tidx:
            table.setdefault(tidx[key], []).append(r)
    for t in sorted(with_pts):
        mine = [p for p in pts if p[0] == t]
        rows = []
        for fam, pos, order in (("species", 1, None), ("content", 2, CONTENT_ORDER), ("tier", 3, ["1", "2", "3", "unrecorded"])):
            acc = {}
            for _, s, c, n in mine:
                a = acc.setdefault(samples[s][pos], [0, 0, 0])
                a[0] += c
                a[1] += n
                a[2] += 1
            keys = sorted(acc) if order is None else [k for k in order if k in acc] + sorted(k for k in acc if k not in order)
            for k in keys:
                rows.append([fam, TIER_NAME.get(k, k) if fam == "tier" else k, acc[k][0], acc[k][1], acc[k][2], "isolates"])
        have = {(r.get("feature_type"), r.get("label")): r for r in table.get(t, [])}
        for fam, feat, order in (("size", "size_band", SIZE_ORDER), ("mob", "mob", None), ("replicon", "replicon", None), ("amr", "amr", None)):
            labels = [k[1] for k in have if k[0] == feat]
            labels = [k for k in order if k in labels] + sorted(k for k in labels if k not in (order or [])) if order else sorted(labels)
            for lab in labels:
                r = have[(feat, lab)]
                n, p = rc.number(r.get("n_cprr_assessed")), rc.number(r.get("cprr"))
                ok = bool(n) and p is not None
                rows.append([fam, lab, int(round(p * n)) if ok else None, int(round(n)) if ok else None,
                             int(rc.number(r.get("n_samples")) or 0), "table"])
        strata[str(t)] = rows
        c, n = sum(p[2] for p in mine), sum(p[3] for p in mine)
        overall[str(t)] = [c, n, len(mine)]
    pairs = []
    for r in rc.read_tsv(os.path.join(results_dir, "benchmark.paired_comparisons.tsv")) or []:
        pairs.append([r.get("analysis_track"), r.get("tool_a"), r.get("tool_b"), r.get("metric"), _r(rc.number(r.get("mean_f1_difference")), 4),
                      _r(rc.number(r.get("difference_ci_low")), 4), _r(rc.number(r.get("difference_ci_high")), 4),
                      _r(rc.number(r.get("permutation_p_value_holm")), 4), rc.number(r.get("paired_clusters"))])
    if not pts:
        return None, "no isolate has an assessable plasmid (cprr_plasmids is blank for every row)."
    return {"v": 1, "minN": MIN_N, "minViolin": MIN_VIOLIN, "samples": samples, "tools": tools, "pts": pts, "excl": excl, "lb": lb,
            "best": best, "strata": strata, "overall": overall, "pairs": pairs, "grid": GRID,
            "tierName": TIER_NAME, "families": FAMILIES, "groups": GROUPS, "defaultFamilies": list(DEFAULT_FAMILIES)}, None


# ------------------------------------------------------------------------------------------------ distribution model
def _order_groups(kind, labels):
    if kind == "content":
        return [k for k in CONTENT_ORDER if k in labels] + sorted(k for k in labels if k not in CONTENT_ORDER)
    if kind == "tier":
        o = ["1", "2", "3", "unrecorded"]
        return [k for k in o if k in labels] + sorted(k for k in labels if k not in o)
    return sorted(labels)


def group_label(kind, key):
    return TIER_NAME.get(key, key) if kind == "tier" else key


def dist_model(data, group="species", hidden=()):
    """facets -> slots, each slot with its points (value, strip offset), box statistics and density. Pure; mirrored by distModel() in JS."""
    with_pts = sorted({p[0] for p in data["pts"]})
    vis = [t for t in with_pts if t not in set(hidden)]
    samples = data["samples"]
    pos = {"species": 1, "content": 2, "tier": 3}.get(group)
    facets = []
    if group == "track":
        for tr in sorted({data["tools"][t][1] for t in vis}):
            facets.append({"label": tr, "key": tr, "all": False, "tools": [t for t in vis if data["tools"][t][1] == tr]})
    else:
        facets.append({"label": "All isolates", "key": "*", "all": True, "tools": vis})
        for k in _order_groups(group, {samples[p[1]][pos] for p in data["pts"]} | {samples[e[1]][pos] for e in data["excl"]}):
            facets.append({"label": group_label(group, k), "key": k, "all": False, "tools": vis})
    for f in facets:
        slots = []
        for t in f["tools"]:
            def inside(si):
                return f["all"] or group == "track" or samples[si][pos] == f["key"]
            mine = [p for p in data["pts"] if p[0] == t and inside(p[1])]
            vals = [p[2] / p[3] for p in mine]
            ids = [samples[p[1]][0] for p in mine]
            offs = jitter(list(zip(vals, ids))) if mine else []
            slot = {"tool": t, "n": len(mine), "excl": sum(1 for e in data["excl"] if e[0] == t and inside(e[1])),
                    "full": len(mine) >= MIN_VIOLIN, "stat": None, "bw": None, "dens": None,
                    "pts": [{"si": p[1], "v": v, "c": p[2], "t": p[3], "j": o[0], "k": o[1]} for p, v, o in zip(mine, vals, offs)]}
            slot["pts"].sort(key=lambda q: (q["v"], samples[q["si"]][0]))
            if mine:
                slot["mean"] = sum(vals) / len(vals)
            if slot["full"]:
                slot["stat"] = box_stats(vals)
                slot["bw"] = bandwidth(vals)
                slot["dens"] = kde(vals, slot["bw"])
            slots.append(slot)
        f["slots"] = slots
    return {"facets": facets, "excluded": len(data["excl"])}


# ------------------------------------------------------------------------------------------------ forest model
def forest_rows(data, tool, contrast="diff", tool_b=None, families=DEFAULT_FAMILIES, min_n=MIN_N):
    """Header / stratum / overall rows. est, lo, hi are None when a stratum has no data (never 0). Mirrored by forestRows() in JS."""
    key = str(tool)
    if key not in data["overall"]:
        return []
    oc, on, oi = data["overall"][key]
    lbrow = data["lb"].get(key)
    p_all = oc / on if on else None
    other = None
    if contrast == "tools" and tool_b is not None and str(tool_b) in data["overall"]:
        other = {(r[0], r[1]): r for r in data["strata"].get(str(tool_b), [])}
        bc, bn, _ = data["overall"][str(tool_b)]
    elif contrast == "tools":
        contrast = "diff"
    rows, last = [], None
    for fam, title in FAMILIES:
        if fam not in families:
            continue
        mine = [r for r in data["strata"].get(key, []) if r[0] == fam]
        if not mine:
            continue
        rows.append({"kind": "head", "label": title, "fam": fam})
        for _, label, c, n, units, src in mine:
            row = {"kind": "row", "fam": fam, "label": label, "c": c, "t": n, "units": units, "src": src, "est": None, "lo": None, "hi": None,
                   "ci": "W", "avail": False, "under": units < min_n, "nm": n or 0}
            if contrast == "tools":
                o = other.get((fam, label))
                if n and o and o[3] and p_all is not None:
                    ci = newcombe(c, n, o[2], o[3])
                    row.update(est=c / n - o[2] / o[3], lo=ci[0], hi=ci[1], avail=True, ci="N", nm=min(n, o[3]),
                               under=min(units, o[4]) < min_n)
            elif n:
                w = wilson(c, n)
                row["avail"] = True
                if contrast == "abs":
                    row.update(est=c / n, lo=w[0], hi=w[1])
                elif p_all is not None:
                    row.update(est=c / n - p_all, lo=w[0] - p_all, hi=w[1] - p_all)
            rows.append(row)
    ov = {"kind": "overall", "label": "Overall (all isolates)", "c": oc, "t": on, "units": oi, "src": "isolates", "avail": bool(on),
          "under": oi < min_n, "nm": on, "est": None, "lo": None, "hi": None, "ci": "W"}
    if on:
        if lbrow and lbrow[1] is not None and lbrow[2] is not None:
            w, ov["ci"] = [lbrow[1], lbrow[2]], "B"
        else:
            w = wilson(oc, on)
        if contrast == "abs":
            ov.update(est=p_all, lo=w[0], hi=w[1])
        elif contrast == "tools":
            ci = newcombe(oc, on, bc, bn)
            ov.update(est=p_all - bc / bn, lo=ci[0], hi=ci[1], ci="N")
        else:
            ov.update(est=0.0, lo=w[0] - p_all, hi=w[1] - p_all)
    rows.append(ov)
    return rows


def forest_layout(rows, contrast="diff", p_all=None):
    """Axis range and pixel positions: x = FX0 + (v - a0)/(a1 - a0) FXW; CI whiskers beyond the axis are clipped and flagged for an arrow."""
    vals = [r["est"] for r in rows if r["kind"] != "head" and r.get("est") is not None]
    if contrast == "abs":
        a0, a1 = 0.0, 1.0
        ticks = [0, 0.25, 0.5, 0.75, 1.0]
    else:
        m = max([abs(v) for v in vals] + [0.0])
        lim = min(1.0, max(0.25, math.ceil(m * 1.5 / 0.25 - 1e-9) * 0.25))
        a0, a1 = -lim, lim
        ticks = [-lim, -lim / 2, 0.0, lim / 2, lim]

    def x(v):
        return FX0 + (v - a0) / (a1 - a0) * FXW
    tmax = max([r["nm"] for r in rows if r["kind"] != "head" and r.get("avail")] + [1])
    items = []
    for i, r in enumerate(rows):
        it = {"i": i, "y": 40 + i * RH}
        if r["kind"] != "head" and r.get("avail") and r["est"] is not None:
            lo, hi = min(r["lo"], r["hi"]), max(r["lo"], r["hi"])
            it.update(x=x(r["est"]), xl=x(max(lo, a0)), xr=x(min(hi, a1)), cl=lo < a0, cr=hi > a1,
                      size=5 + 9 * math.sqrt(r["nm"] / tmax))
        items.append(it)
    null = x(p_all) if contrast == "abs" and p_all is not None else x(0.0)
    return {"a0": a0, "a1": a1, "ticks": ticks, "null": null, "items": items, "height": 40 + len(rows) * RH + 56}


# ------------------------------------------------------------------------------------------------ static SVG
def n2(x):
    return rs.num(x, 2)


def tool_name(data, t, multi):
    track, name = data["tools"][t][1], data["tools"][t][2]
    return f"{name} ({track})" if multi else name


def facet_width(f):
    """A facet is at least as wide as its label (about 6.8 px per character at 12 px bold), so neighbouring labels never overlap."""
    return max(len(f["slots"]) * SW, int(math.ceil(len(f["label"]) * 6.8)) + 8)


def dist_svg(data, model, mode="violin", points=True, sel=None, element_ids=False):
    """The distribution figure as SVG text; the live view in the page is drawn by distSvg() in assets/report/fig_stats_core.html."""
    samples = data["samples"]
    multi = len({t[1] for t in data["tools"]}) > 1
    width = LM + sum(facet_width(f) for f in model["facets"]) + FG * (len(model["facets"]) - 1) + 28
    height = TOP + PH + BOT
    yv = lambda v: TOP + (1 - v) * PH
    out = [rs.svg_open(width, height, "CPRR distributions by tool", "Violin or box plots of per-isolate CPRR with every isolate drawn as a point.")
           if hasattr(rs, "svg_open") else f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {width} {height}'>"]
    out.append(f"<rect width='{width}' height='{height}' fill='#fff'/>")
    for v in (0, 0.25, 0.5, 0.75, 1):
        out.append(f"<line x1='{LM - 4}' x2='{width - 14}' y1='{n2(yv(v))}' y2='{n2(yv(v))}' stroke='#d9e0da' stroke-width='1'/>"
                   f"<text x='{LM - 8}' y='{n2(yv(v) + 4)}' text-anchor='end' font-size='11' fill='#4f5f55'>{v:g}</text>")
    out.append(f"<text transform='translate(14 {TOP + PH / 2}) rotate(-90)' text-anchor='middle' font-size='12' fill='#17231d'>CPRR (correct / assessable plasmids)</text>")
    x0 = LM
    for fi, f in enumerate(model["facets"]):
        fw = facet_width(f)
        pad = (fw - len(f["slots"]) * SW) / 2.0
        if fi % 2 == 1:
            out.append(f"<rect x='{x0}' y='{TOP - 8}' width='{fw}' height='{PH + 16}' fill='#f3f6f3'/>")
        out.append(f"<text x='{n2(x0 + fw / 2)}' y='{TOP + PH + BOT - 8}' text-anchor='middle' font-size='12' font-weight='700' fill='#17231d'>{rc.esc(f['label'])}</text>")
        for si_, s in enumerate(f["slots"]):
            cx = x0 + pad + si_ * SW + SW / 2
            colour = TOOL_COLOURS[s["tool"] % len(TOOL_COLOURS)]
            hw = 13
            if s["full"] and mode == "violin":
                dmax = max(s["dens"]) or 1.0
                right = [(cx + hw * d / dmax, yv(i / (GRID - 1))) for i, d in enumerate(s["dens"])]
                left = [(cx - hw * d / dmax, yv(i / (GRID - 1))) for i, d in reversed(list(enumerate(s["dens"])))]
                path = "M" + " L".join(f"{n2(a)} {n2(b)}" for a, b in right + left) + " Z"
                out.append(f"<path d='{path}' fill='{colour}' fill-opacity='.28' stroke='{colour}' stroke-width='1.2'/>"
                           f"<line x1='{n2(cx - hw * .6)}' x2='{n2(cx + hw * .6)}' y1='{n2(yv(s['stat']['med']))}' y2='{n2(yv(s['stat']['med']))}' stroke='#17231d' stroke-width='2'/>")
            elif s["full"]:
                b = s["stat"]
                out.append(f"<line x1='{n2(cx)}' x2='{n2(cx)}' y1='{n2(yv(b['wlo']))}' y2='{n2(yv(b['whi']))}' stroke='{colour}' stroke-width='1.4'/>"
                           f"<rect x='{n2(cx - hw * .8)}' y='{n2(yv(b['q3']))}' width='{n2(hw * 1.6)}' height='{n2(max(yv(b['q1']) - yv(b['q3']), 0.5))}' fill='{colour}' fill-opacity='.28' stroke='{colour}' stroke-width='1.4'/>"
                           f"<line x1='{n2(cx - hw * .8)}' x2='{n2(cx + hw * .8)}' y1='{n2(yv(b['med']))}' y2='{n2(yv(b['med']))}' stroke='#17231d' stroke-width='2.2'/>"
                           f"<line x1='{n2(cx - hw * .4)}' x2='{n2(cx + hw * .4)}' y1='{n2(yv(b['wlo']))}' y2='{n2(yv(b['wlo']))}' stroke='{colour}' stroke-width='1.4'/>"
                           f"<line x1='{n2(cx - hw * .4)}' x2='{n2(cx + hw * .4)}' y1='{n2(yv(b['whi']))}' y2='{n2(yv(b['whi']))}' stroke='{colour}' stroke-width='1.4'/>")
            if points:
                for q in s["pts"]:
                    step = min(6.0, 0.9 * 2 * hw / max(q["k"], 1))
                    out.append(point_svg(cx + q["j"] * step, yv(q["v"]), samples[q["si"]][3], colour, 3.2, False))
            lb = data["lb"].get(str(s["tool"]))
            if lb and lb[1] is not None and lb[2] is not None and (f["all"] or not model["facets"][0]["all"]):
                out.append(f"<line x1='{n2(cx + hw + 4)}' x2='{n2(cx + hw + 4)}' y1='{n2(yv(lb[2]))}' y2='{n2(yv(lb[1]))}' stroke='#17231d' stroke-width='3'/>")
                if lb[0] is not None:
                    out.append(f"<circle cx='{n2(cx + hw + 4)}' cy='{n2(yv(lb[0]))}' r='2.6' fill='#fff' stroke='#17231d' stroke-width='1.2'/>")
            lab = tool_name(data, s["tool"], multi)
            lab = (lab if len(lab) <= 18 else lab[:17] + "…") + f" (n={s['n']}{'*' if s['n'] < MIN_VIOLIN else ''})"
            out.append(f"<text transform='translate({n2(cx + 3)} {TOP + PH + 14}) rotate(-50)' text-anchor='end' font-size='10.5' fill='#17231d'>{rc.esc(lab)}</text>")
        x0 += fw + FG
    out.append("</svg>")
    return "".join(out)


def point_svg(x, y, tier, colour, r, selected):
    """Tier 1 circle, tier 2 square, tier 3 triangle with a dashed dark outline (provisional), not recorded diamond."""
    stroke = "#17231d" if selected else "#ffffff"
    sw = 2 if selected else 0.9
    if tier == "2":
        return f"<rect x='{n2(x - r)}' y='{n2(y - r)}' width='{n2(2 * r)}' height='{n2(2 * r)}' fill='{colour}' stroke='{stroke}' stroke-width='{sw}'/>"
    if tier == "3":
        d = f"M{n2(x)} {n2(y - r * 1.25)} L{n2(x + r * 1.15)} {n2(y + r * .9)} L{n2(x - r * 1.15)} {n2(y + r * .9)} Z"
        return f"<path d='{d}' fill='{colour}' stroke='#17231d' stroke-width='1.1' stroke-dasharray='2 1.2'/>"
    if tier == "1":
        return f"<circle cx='{n2(x)}' cy='{n2(y)}' r='{n2(r)}' fill='{colour}' stroke='{stroke}' stroke-width='{sw}'/>"
    d = f"M{n2(x)} {n2(y - r * 1.3)} L{n2(x + r * 1.3)} {n2(y)} L{n2(x)} {n2(y + r * 1.3)} L{n2(x - r * 1.3)} {n2(y)} Z"
    return f"<path d='{d}' fill='{colour}' stroke='{stroke}' stroke-width='{sw}'/>"


def fnum(x):
    return "n/a" if x is None else f"{x:+.3f}"


def forest_svg(rows, lay, contrast="diff", p_all=None):
    width = FX0 + FXW + 330
    height = lay["height"]
    ax = lambda v: FX0 + (v - lay["a0"]) / (lay["a1"] - lay["a0"]) * FXW
    out = [f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {width} {height}' role='img' aria-label='Forest plot of CPRR by stratum' font-family='Arial,sans-serif'>"
           "<title>Forest plot of CPRR by stratum</title>", f"<rect width='{width}' height='{height}' fill='#fff'/>"]
    heads = {"diff": "CPRR difference vs overall", "abs": "CPRR", "tools": "CPRR difference, A minus B"}
    out.append(f"<text x='8' y='24' font-size='11' font-weight='700'>Stratum</text><text x='{FX0 + FXW / 2}' y='24' font-size='11' font-weight='700' text-anchor='middle'>{heads[contrast]}</text>"
               f"<text x='{FX0 + FXW + 14}' y='24' font-size='11' font-weight='700'>plasmids / isolates</text><text x='{FX0 + FXW + 150}' y='24' font-size='11' font-weight='700'>estimate [95% CI]</text>")
    out.append(f"<line x1='{n2(lay['null'])}' x2='{n2(lay['null'])}' y1='34' y2='{height - 44}' stroke='#17231d' stroke-dasharray='4 3'/>")
    for it, r in zip(lay["items"], rows):
        y = it["y"]
        if r["kind"] == "head":
            out.append(f"<text x='8' y='{y + 4}' font-size='11.5' font-weight='700' fill='#17231d'>{rc.esc(r['label'])}</text>")
            continue
        bold = " font-weight='700'" if r["kind"] == "overall" else ""
        out.append(f"<text x='{18 if r['kind'] == 'row' else 8}' y='{y + 4}' font-size='11'{bold} fill='#17231d'>{rc.esc(r['label'])}</text>")
        if "x" in it:
            c = TOOL_COLOURS[0]
            if r["kind"] == "overall":
                d = f"M{n2(ax(r['lo']))} {y} L{n2(it['x'])} {y - 7} L{n2(ax(r['hi']))} {y} L{n2(it['x'])} {y + 7} Z"
                out.append(f"<path d='{d}' fill='#17231d'/>")
            else:
                out.append(f"<line x1='{n2(it['xl'])}' x2='{n2(it['xr'])}' y1='{y}' y2='{y}' stroke='{c}' stroke-width='1.6'/>")
                if it["cl"]:
                    out.append(f"<path d='M{n2(it['xl'])} {y} l6 -4 v8 z' fill='{c}'/>")
                if it["cr"]:
                    out.append(f"<path d='M{n2(it['xr'])} {y} l-6 -4 v8 z' fill='{c}'/>")
                s = it["size"]
                fill = "#fff" if r["under"] else c
                out.append(f"<rect x='{n2(it['x'] - s / 2)}' y='{n2(y - s / 2)}' width='{n2(s)}' height='{n2(s)}' fill='{fill}' stroke='{c}' stroke-width='1.6'/>")
            txt = f"{r['est']:.3f} [{r['lo']:.3f}, {r['hi']:.3f}] {r['ci']}" if contrast == "abs" else f"{fnum(r['est'])} [{fnum(r['lo'])}, {fnum(r['hi'])}] {r['ci']}"
        else:
            txt = "not available"
        nn = f"{r['t']} / {r['units']}" if r.get("t") else f"- / {r['units']}"
        if r.get("avail") and r["under"]:
            nn += " underpowered"
        out.append(f"<text x='{FX0 + FXW + 14}' y='{y + 4}' font-size='10.5' fill='#17231d'>{rc.esc(nn)}</text><text x='{FX0 + FXW + 150}' y='{y + 4}' font-size='10.5' fill='#17231d'>{rc.esc(txt)}</text>")
    yb = height - 44
    out.append(f"<line x1='{FX0}' x2='{FX0 + FXW}' y1='{yb}' y2='{yb}' stroke='#17231d'/>")
    for t in lay["ticks"]:
        out.append(f"<line x1='{n2(ax(t))}' x2='{n2(ax(t))}' y1='{yb}' y2='{yb + 4}' stroke='#17231d'/><text x='{n2(ax(t))}' y='{yb + 16}' font-size='10.5' text-anchor='middle'>{t:g}</text>")
    out.append("</svg>")
    return "".join(out)


# ------------------------------------------------------------------------------------------------ section
LEAD_DIST = ("Each point is one isolate: its CPRR is the share of its assessable truth plasmids that the tool reconstructed correctly. "
             "Tools sit side by side inside each group (species by default; switch to track, plasmid-content band or reference tier in the Group tab), "
             "drawn as a violin (Gaussian kernel density, Silverman bandwidth, clipped to 0-1) or a box (median, quartiles, whiskers to 1.5 IQR). "
             "Marker shape is the reference tier (circle tier 1, square tier 2, dashed triangle tier 3 provisional, diamond not recorded). "
             "A group with fewer than 5 isolates shows points only: no density is drawn from so few. Isolates with no assessable plasmid are excluded and counted, never plotted as 0. "
             "Click a point to follow that isolate across tools; hover or focus for details. The bar beside a group, when present, is the leaderboard cluster-bootstrap CI of the pooled CPRR. "
             "Demo data are synthetic and flat; do not read them as a result.")
LEAD_FOREST = ("One row per stratum for the chosen tool. The square is the stratum's CPRR difference from the tool's overall CPRR (or the absolute CPRR, or tool A minus tool B), "
               "sized by plasmids; the line is its 95% interval (an arrow means it runs past the axis) and the dashed line is no difference. "
               "The diamond at the bottom is the overall value. Intervals are Wilson intervals over plasmids pooled (not cluster-aware, so too narrow when isolates are related) "
               "unless marked B (cluster bootstrap, from the leaderboard) or N (Newcombe, difference of two Wilson intervals). Hollow markers are underpowered "
               "(fewer than 5 isolates); a stratum with no CPRR is shown as not available, never as 0. Plasmid-size, MOB, replicon and AMR rows come from the replicon-recovery table.")
STATIC_NOTE = ("Static view of the default selection. With JavaScript on, this becomes an interactive figure with a setup panel, tooltips, "
               "filters, drilldown and export.")


def _default_tool(data):
    return data["best"][0] if data["best"] else sorted({p[0] for p in data["pts"]})[0]


def static_dist(data):
    model = dist_model(data, "species")
    legend = "".join(f"<span class='st-key'><i style='background:{TOOL_COLOURS[t % len(TOOL_COLOURS)]}'></i>{rc.esc(tool_name(data, t, len({x[1] for x in data['tools']}) > 1))}</span>"
                     for t in sorted({p[0] for p in data["pts"]}))
    shapes = "<span class='st-key'>● tier 1</span><span class='st-key'>■ tier 2</span><span class='st-key'>▲ tier 3 provisional (dashed outline)</span><span class='st-key'>◆ tier not recorded</span>"
    rows = []
    for f in model["facets"]:
        for s in f["slots"]:
            if s["n"]:
                vals = [q["v"] for q in s["pts"]]
                rows.append([f["label"], data["tools"][s["tool"]][2], data["tools"][s["tool"]][1], s["n"], s["excl"], f"{quantile7(vals, .5):.3f}", f"{s['mean']:.3f}"])
    table = rc.panel(["Group", "Tool", "Track", "Isolates", "Excluded (no assessable plasmid)", "Median CPRR", "Mean CPRR"], rows, "No isolate has a CPRR.")
    return (f"<div class='st-static'>{dist_svg(data, model)}<div class='rpt-legend'>{legend}{shapes}</div>"
            f"<p class='st-note'>* fewer than {MIN_VIOLIN} isolates: points only. {rc.esc(str(model['excluded']))} tool-isolate pair(s) with no assessable plasmid are excluded and counted, not plotted as 0.</p>"
            f"<details class='rpt-collapsible'><summary>Show the group table</summary>{table}</details><p class='st-note'>{STATIC_NOTE}</p></div>")


def static_forest(data):
    t = _default_tool(data)
    rows = forest_rows(data, t)
    oc, on, _ = data["overall"][str(t)]
    lay = forest_layout(rows, "diff", oc / on if on else None)
    name = f"{data['tools'][t][2]} ({data['tools'][t][1]})"
    return (f"<div class='st-static'><p class='st-note'><strong>{rc.esc(name)}</strong>: stratum CPRR minus the tool's overall CPRR. "
            f"W = Wilson (plasmids pooled, not cluster-aware); B = cluster bootstrap (leaderboard).</p>{forest_svg(rows, lay)}<p class='st-note'>{STATIC_NOTE}</p></div>")


def json_script(sid, payload):
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    return f"<script type='application/json' id='{sid}'>" + text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026") + "</script>"


def asset(name):
    return (Path(__file__).resolve().parent.parent / "assets" / "report" / name).read_text(encoding="utf-8")


def assets():
    return "".join(asset(n) for n in ("fig_stats_style.html", "fig_stats_core.html", "fig_stats_ui.html"))


def build_sections(results_dir, data_dir, scores_path):
    data, reason = build_payload(results_dir, data_dir, scores_path)
    if data is None:
        why = f"CPRR per isolate is not available: {reason}"
        return (rc.section("fig-distributions", "Distribution of CPRR across tools and species", LEAD_DIST, rc.not_run(why), group="Figures"),
                rc.section("fig-forest", "Differences in CPRR across species, plasmid sizes and reference tiers", LEAD_FOREST, rc.not_run(why), group="Figures"))
    host = lambda kind, static: f"<div class='st' data-st='{kind}' id='st-{kind}'>{static}</div>"
    dist_body = json_script("st-data", data) + assets() + host("dist", static_dist(data))
    return (rc.section("fig-distributions", "Distribution of CPRR across tools and species", LEAD_DIST, dist_body, group="Figures"),
            rc.section("fig-forest", "Differences in CPRR across species, plasmid sizes and reference tiers", LEAD_FOREST, host("forest", static_forest(data)), group="Figures"))


def inject(page, results_dir, data_dir, scores_path):
    sections = "".join(str(s) for s in build_sections(results_dir, data_dir, scores_path))
    return rc.inject_sections(rc.add_style(page), sections, SECTIONS)
