#!/usr/bin/env python3
"""
report_fig_pr.py -- the interactive precision-recall figure (section `fig-pr`).

One plot per analysis track (never pooled across tracks). A tool that wrote a per-record probability
(<sample>/<tool>.pr_curve.tsv, adapters/SCORES.md) gets a curve; a tool that gives only hard calls gets a single operating
point (its default call, from scores.tsv); `baseline_*` tools are drawn as hollow reference markers. The pr_curve files carry
BASES only (tp_bp, fp_bp, fn_bp), so curves exist in the bases unit; the contigs unit shows operating points (contig_tp/fp/fn,
only where the contig classification was scored). A plasmid-level precision is not defined by the pipeline (a predicted record
can cover several plasmids), so there is no plasmids unit; plasmid recovery appears in the drill-down and as false positives
per recovered plasmid.

Formulas (all mirrored in assets/report/fig_pr_core.html and parity-tested in test/test_report_fig_pr.py)
  curve rows        (threshold, tp, fp, fn) in bases, threshold descending; threshold None = nothing called (start of curve)
  precision         tp / (tp + fp); 1.0 when nothing is called on a curve (precision_recall_curve convention); None for an operating point
  recall            tp / (tp + fn); None when the sample has no truth plasmid bases (the sample is then skipped)
  F1                2 P R / (P + R); None when P + R = 0
  AP (step sum)     sum_k (R_k - R_{k-1}) * P_k, R_{-1} = 0, points in descending-threshold order
  trapezoid AUC     sum_k (R_k - R_{k-1}) * (P_k + P_{k-1}) / 2   (the pipeline's own pr_auc; shown beside AP, the two differ)
  F-optimal point   first point (highest threshold on a tie) with maximal F1
  iso-F1 contour    P = f R / (2R - f), R from f/(2-f) (P = 1) to 1 (P = f/(2-f)), f = 0.5 .. 0.9
  micro curve       pool tp, fp, fn over samples at each threshold of the union of the samples' thresholds; a sample's state at
                    threshold t is its last row with threshold >= t (nothing called before its first row)
  macro curve       mean of the per-sample P and mean of the per-sample R at the same thresholds; F1 is of those two means
  prevalence line   plasmid bases / reference bases (the precision of a random base call); micro pools bases, macro averages samples
  step drawing      the rectangle tops of the AP sum: (R_{k-1}, P_k) -> (R_k, P_k) -> (R_k, P_{k+1})
  FP per recovered  sum(fp_predicted_record_count) / sum(recovered_plasmid_count) at the default call (a count of wrongly called
  plasmid           predicted records per correctly recovered plasmid); blank when nothing was recovered; not derivable along a
                    curve because the curve files carry no record counts

Standard library only.
"""
import json
import math
import os
from pathlib import Path

import report_common as rc
import report_svg as sv

SECTIONS = [("fig-pr", "Precision-recall")]
TITLE = "Recovering the expected plasmids while limiting false positives"
BASELINE_PREFIX = "baseline_"
ISO_LEVELS = (0.5, 0.6, 0.7, 0.8, 0.9)
PAYLOAD_BUDGET_BYTES = 700_000
VIEW_FULL = (0.0, 1.0, 0.0, 1.0)
VIEW_ZOOM = (0.5, 1.0, 0.5, 1.0)
L = {"W": 760, "H": 640, "ml": 62, "mr": 20, "mt": 18, "mb": 56}
MARKERS = ["circle", "square", "triangle", "diamond", "cross", "plus", "invtriangle", "star"]
DASHES = ["", "7 3", "2 3", "9 3 2 3", "5 2", "1 3 6 3", "", "7 3"]
PALETTE = ["#0072B2", "#D55E00", "#009E73", "#E69F00", "#CC79A7", "#56B4E9", "#444444", "#9A8700"]
NO_CURVE_REASON = ("no <sample>/<tool>.pr_curve.tsv: the tool gives only a hard call (no per-record probability), "
                   "or its threshold sweep was skipped (adapters/SCORES.md)")

LEAD = ("Each plot is one analysis track; tracks are never pooled. Recall (x) is the share of the truth plasmid bases recovered; precision (y) is the "
        "share of the bases called plasmid that really are plasmid. A tool that exposes a score draws a curve (every threshold of its score, higher "
        "threshold = fewer calls, starting at recall 0); a tool that gives only a hard call is one operating point (its default call). Hollow grey "
        "markers are the trivial baselines (baseline_*), the dotted horizontal line is the prevalence (plasmid bases over reference bases), and the "
        "faint contours are F1 = 0.5 to 0.9. The star on a curve is its F1-optimal threshold. Average precision (AP) is the standard step sum, "
        "sum of (R_k - R_k-1) x P_k; the pipeline's own PR-AUC is a trapezoid and is shown beside it, so the two differ. Micro pools bases over "
        "samples, macro averages the samples' precision and recall (F1 is then computed from those two means). Click a legend entry to isolate a tool "
        "(Shift-click hides it), drag on the plot to zoom to a rectangle, hover or focus a point for its threshold, precision, recall, F1 and n, and "
        "click it (or press Enter) for the per-sample drill-down. Curves exist in bases only, because that is what the score files carry; the contigs "
        "unit shows operating points. False positives per recovered plasmid = wrongly called predicted records / plasmids recovered, at the default "
        "call. The demo data are synthetic and flat: they demonstrate the engine, not a biological result. Without JavaScript the static view of the "
        "default settings is shown.")


# ------------------------------------------------------------------------------------------------ maths (mirror of fig_pr_core.html)
def f1(p, r):
    return None if p is None or r is None or p + r <= 0 else 2 * p * r / (p + r)


def prec(tp, fp, conv):
    return tp / (tp + fp) if tp + fp > 0 else (1.0 if conv else None)


def rec(tp, fn):
    return tp / (tp + fn) if tp + fn > 0 else None


def point(t, tp, fp, fn, conv):
    p, r = prec(tp, fp, conv), rec(tp, fn)
    return {"t": t, "tp": tp, "fp": fp, "fn": fn, "p": p, "r": r, "f": f1(p, r)}


def curve_points(rows):
    pts = [point(x[0], x[1], x[2], x[3], True) for x in rows]
    return [q for q in pts if q["r"] is not None]


def ap_step(pts):
    s, prev = 0.0, 0.0
    for q in pts:
        s += (q["r"] - prev) * q["p"]
        prev = q["r"]
    return s


def auc_trapz(pts):
    return sum((pts[k]["r"] - pts[k - 1]["r"]) * (pts[k]["p"] + pts[k - 1]["p"]) / 2 for k in range(1, len(pts)))


def f_optimal(pts):
    best = -1
    for i, q in enumerate(pts):
        if q["f"] is not None and (best < 0 or q["f"] > pts[best]["f"] + 1e-12):
            best = i
    return best


def iso_f1(f, n):
    lo = f / (2 - f)
    return [(lo + (1 - lo) * i / n, f * (lo + (1 - lo) * i / n) / (2 * (lo + (1 - lo) * i / n) - f)) for i in range(n + 1)]


def step_vertices(pts):
    v = []
    for k in range(1, len(pts)):
        v.append((pts[k - 1]["r"], pts[k]["p"]))
        v.append((pts[k]["r"], pts[k]["p"]))
    return v


def state_at(rows, t):
    best = None
    for row in rows:
        if row[0] is None or row[0] >= t:
            best = row
        else:
            break
    if best:
        return (best[1], best[2], best[3])
    return (0, 0, rows[0][1] + rows[0][3])


def union_thresholds(samples):
    return sorted({x[0] for rows in samples.values() for x in rows if x[0] is not None}, reverse=True)


def _total(rows):
    return rows[0][1] + rows[0][3]


def _live(samples):
    return [s for s, rows in samples.items() if rows and _total(rows) > 0]


def micro_curve(samples):
    names = _live(samples)
    out = []
    for t in [None] + union_thresholds(samples):
        tp = fp = fn = 0
        for s in names:
            st = (0, 0, _total(samples[s])) if t is None else state_at(samples[s], t)
            tp, fp, fn = tp + st[0], fp + st[1], fn + st[2]
        q = point(t, tp, fp, fn, True)
        q["n"] = len(names)
        out.append(q)
    return [q for q in out if q["r"] is not None]


def macro_curve(samples):
    names = _live(samples)
    out = []
    if not names:
        return out
    for t in [None] + union_thresholds(samples):
        sp = sr = 0.0
        tp = fp = fn = 0
        for s in names:
            st = (0, 0, _total(samples[s])) if t is None else state_at(samples[s], t)
            sp += prec(st[0], st[1], True)
            sr += rec(st[0], st[2])
            tp, fp, fn = tp + st[0], fp + st[1], fn + st[2]
        p, r = sp / len(names), sr / len(names)
        out.append({"t": t, "tp": tp, "fp": fp, "fn": fn, "p": p, "r": r, "f": f1(p, r), "n": len(names)})
    return out


def op_point(per_sample, mode):
    rows = [x for x in per_sample if x and None not in x]
    if not rows:
        return None
    if mode == "micro":
        tp, fp, fn = (sum(x[i] for x in rows) for i in range(3))
        q = point(None, tp, fp, fn, False)
        q["n"] = len(rows)
        return None if q["p"] is None or q["r"] is None else q
    ps, rs = [], []
    for x in rows:
        p, r = prec(x[0], x[1], False), rec(x[0], x[2])
        if p is not None and r is not None:
            ps.append(p)
            rs.append(r)
    if not ps:
        return None
    mp, mr = sum(ps) / len(ps), sum(rs) / len(rs)
    return {"t": None, "tp": sum(x[0] for x in rows), "fp": sum(x[1] for x in rows), "fn": sum(x[2] for x in rows),
            "p": mp, "r": mr, "f": f1(mp, mr), "n": len(ps)}


def prevalence(per_sample, mode):
    rows = [x for x in per_sample if x and x[1] > 0]
    if not rows:
        return None
    if mode == "micro":
        return sum(x[0] for x in rows) / sum(x[1] for x in rows)
    return sum(x[0] / x[1] for x in rows) / len(rows)


def fp_per_recovered(fp_records, recovered):
    return fp_records / recovered if recovered > 0 else None


# ------------------------------------------------------------------------------------------------ data
def _num(value):
    v = rc.number(value)
    return v if v is not None and math.isfinite(v) else None


def _int(value):
    v = _num(value)
    return None if v is None else int(round(v))


def _first_file(name, sample, *roots):
    for root in roots:
        if root:
            path = os.path.join(root, sample, name)
            if os.path.isfile(path):
                return path
    return None


def read_curve(path):
    """Rows (threshold|None, tp, fp, fn) in bases, threshold descending, consecutive identical states dropped (they draw the same point);
    None when the file is absent or has no usable row."""
    rows = rc.read_tsv(path)
    if not rows:
        return None
    out = []
    for row in rows:
        tp, fp, fn = _int(row.get("tp_bp")), _int(row.get("fp_bp")), _int(row.get("fn_bp"))
        if tp is None or fp is None or fn is None:
            continue
        raw = (row.get("threshold") or "").strip().lower()
        t = None if raw in ("inf", "+inf", "infinity", "") else _num(raw)
        if t is None and raw not in ("inf", "+inf", "infinity", ""):
            continue
        out.append((t, tp, fp, fn))
    if not out:
        return None
    out.sort(key=lambda x: (x[0] is not None, -(x[0] if x[0] is not None else 0)))
    slim = [out[0]]
    for x in out[1:]:
        if x[1:] != slim[-1][1:]:
            slim.append(x)
    return [list(x) for x in slim]


def _truth(sample, results_dir, data_dir):
    path = _first_file("truth.tsv", sample, data_dir, results_dir)
    rows = rc.read_tsv(path) or []
    plasmids, total, plasmid_bp = [], 0, 0
    for row in rows:
        length = _int(row.get("length")) or 0
        total += length
        if (row.get("molecule_type") or "").upper() == "PLASMID":
            plasmids.append([row.get("sequence_id", ""), length])
            plasmid_bp += length
    return {"truth": plasmids, "plasmid_bp": plasmid_bp, "total_bp": total}


def _recovered_flags(sample, tool, truth_ids, results_dir):
    rows = rc.read_tsv(os.path.join(results_dir, sample, f"{tool}.per_plasmid.tsv"))
    if not rows:
        return ""
    flag = {r.get("sequence_id"): ("1" if (r.get("recovered") or "") in ("1", "true", "True") else "0") for r in rows}
    return "".join(flag.get(i, "?") for i in truth_ids)


def build_model(results_dir, data_dir, scores_path):
    """{'tracks': [...]} or None when scores.tsv is absent or empty. Every value is finite or None."""
    scores = rc.read_tsv(scores_path)
    if not scores:
        return None
    leaderboard = {(r.get("analysis_track", ""), r.get("tool")): r for r in (rc.read_tsv(os.path.join(results_dir, "benchmark.leaderboard.tsv")) or [])}
    tracks = {}
    for row in scores:
        tracks.setdefault(row.get("analysis_track") or "all", []).append(row)
    out, spent = [], 0
    for track in sorted(tracks):
        rows = tracks[track]
        samples = {}
        for sample in sorted({r["sample"] for r in rows}):
            samples[sample] = _truth(sample, results_dir, data_dir)
        tools = []
        for name in sorted({r["tool"] for r in rows}, key=lambda n: (n.startswith(BASELINE_PREFIX), n)):
            mine = [r for r in rows if r["tool"] == name]
            lb = leaderboard.get((track, name), {})
            curves, op = {}, {}
            for r in mine:
                s = r["sample"]
                tp, fp, fn = _int(r.get("TP_bp")), _int(r.get("FP_bp")), _int(r.get("FN_bp"))
                ctp, cfp, cfn = (_int(r.get("contig_tp")), _int(r.get("contig_fp")), _int(r.get("contig_fn")))
                contig = [ctp, cfp, cfn] if (r.get("contig_classification_status") == "scored" and None not in (ctp, cfp, cfn)) else None
                true_n, rec_n, fp_rec = _int(r.get("true_plasmid_count")), _int(r.get("recovered_plasmid_count")), _int(r.get("fp_predicted_record_count"))
                op[s] = {"b": [tp, fp, fn] if None not in (tp, fp, fn) else None, "c": contig,
                         "pl": [true_n, rec_n, fp_rec] if None not in (true_n, rec_n, fp_rec) else None,
                         "rec": _recovered_flags(s, name, [t[0] for t in samples[s]["truth"]], results_dir)}
                curve = read_curve(os.path.join(results_dir, s, f"{name}.pr_curve.tsv"))
                if curve:
                    curves[s] = curve
            reason, omitted = None, False
            if curves:
                size = len(json.dumps(curves, separators=(",", ":")))
                if spent + size > PAYLOAD_BUDGET_BYTES:
                    curves, omitted = {}, True
                    reason = "curve omitted to keep the report small; the per-sample pr_curve.tsv files hold it"
                else:
                    spent += size
            if not curves and reason is None:
                reason = NO_CURVE_REASON
            tools.append({"name": name, "task": mine[0].get("task") or lb.get("task") or "", "baseline": name.startswith(BASELINE_PREFIX),
                          "curve": curves or None, "reason": reason, "partial": bool(curves) and len(curves) < len(mine),
                          "n_scored": len(mine), "pipeline_auc": _num(lb.get("mean_pr_auc")), "op": op})
        out.append({"id": track, "samples": samples, "tools": tools})
    return {"tracks": out}


# ------------------------------------------------------------------------------------------------ static SVG
def _ticks(lo, hi):
    span = hi - lo
    step = 10 ** math.floor(math.log10(span / 5))
    m = span / 5 / step
    step *= 1 if m < 1.5 else 2 if m < 3.5 else 5 if m < 7.5 else 10
    out, v = [], math.ceil(lo / step - 1e-9) * step
    while v <= hi + 1e-9:
        out.append(round(round(v / step) * step, 10))
        v += step
    return out


def marker_path(shape, x, y, s):
    if shape == "square":
        return f"M{x - s:.1f},{y - s:.1f}h{2 * s:.1f}v{2 * s:.1f}h{-2 * s:.1f}z"
    if shape == "triangle":
        return f"M{x:.1f},{y - s * 1.15:.1f}L{x + s * 1.1:.1f},{y + s * .85:.1f}L{x - s * 1.1:.1f},{y + s * .85:.1f}z"
    if shape == "invtriangle":
        return f"M{x:.1f},{y + s * 1.15:.1f}L{x + s * 1.1:.1f},{y - s * .85:.1f}L{x - s * 1.1:.1f},{y - s * .85:.1f}z"
    if shape == "diamond":
        return f"M{x:.1f},{y - s * 1.3:.1f}L{x + s * 1.3:.1f},{y:.1f}L{x:.1f},{y + s * 1.3:.1f}L{x - s * 1.3:.1f},{y:.1f}z"
    if shape == "cross":
        return f"M{x - s:.1f},{y - s:.1f}L{x + s:.1f},{y + s:.1f}M{x - s:.1f},{y + s:.1f}L{x + s:.1f},{y - s:.1f}"
    if shape == "plus":
        return f"M{x - s * 1.2:.1f},{y:.1f}h{2.4 * s:.1f}M{x:.1f},{y - s * 1.2:.1f}v{2.4 * s:.1f}"
    if shape == "star":
        d = ""
        for i in range(10):
            a = -math.pi / 2 + i * math.pi / 5
            rr = s * .55 if i % 2 else s * 1.4
            d += ("L" if i else "M") + f"{x + rr * math.cos(a):.2f},{y + rr * math.sin(a):.2f}"
        return d + "z"
    return f"M{x - s:.1f},{y:.1f}a{s},{s} 0 1,0 {2 * s},0a{s},{s} 0 1,0 {-2 * s},0z"


def _style_of(tools):
    """tool name -> (colour, marker, dash). Baselines are grey and hollow; the others cycle palette, marker and dash together."""
    out, i = {}, 0
    for t in tools:
        if t["baseline"]:
            out[t["name"]] = ("#7a7a7a", MARKERS[i % 8], "")
        else:
            out[t["name"]] = (PALETTE[i % 8], MARKERS[i % 8], DASHES[i % 8])
        i += 1
    return out


def tool_stats(track, tool, mode="micro"):
    """Everything the legend and the side table read for one tool: curve, AP, trapezoid, F-optimal, operating point, FP per recovered plasmid."""
    out = {"name": tool["name"], "curve": None, "ap": None, "auc": None, "fopt": None, "n_curve": 0}
    if tool["curve"]:
        pts = (micro_curve if mode == "micro" else macro_curve)(tool["curve"])
        if pts:
            out.update(curve=pts, ap=ap_step(pts), auc=auc_trapz(pts), n_curve=len(tool["curve"]))
            i = f_optimal(pts)
            out["fopt"] = pts[i] if i >= 0 else None
    out["op"] = op_point([v["b"] for v in tool["op"].values()], mode)
    pl = [v["pl"] for v in tool["op"].values() if v["pl"]]
    out["fp_rec"] = fp_per_recovered(sum(x[2] for x in pl), sum(x[1] for x in pl)) if pl else None
    return out


def static_svg(track, mode="micro", view=VIEW_FULL):
    W, H = L["W"], L["H"]
    pw, ph = W - L["ml"] - L["mr"], H - L["mt"] - L["mb"]

    def sx(r):
        return L["ml"] + (r - view[0]) / (view[1] - view[0]) * pw

    def sy(p):
        return L["mt"] + (1 - (p - view[2]) / (view[3] - view[2])) * ph
    styles = _style_of(track["tools"])
    parts = [sv.svg_open(W, H, f"Precision-recall, track {track['id']}",
                         f"Recall against precision at the base level, {mode} averaged, one curve per tool that exposes a score and one marker per hard call.",
                         "pr-static-svg"),
             f"<rect width='{W}' height='{H}' fill='#ffffff'/>", f"<clipPath id='prclip-static-{rc.esc(track['id'])}'><rect x='{L['ml']}' y='{L['mt']}' width='{pw}' height='{ph}'/></clipPath>"]
    for v in _ticks(view[0], view[1]):
        parts.append(sv.line(sx(v), L["mt"], sx(v), L["mt"] + ph, "#e3e8e3"))
        parts.append(sv.text(sx(v), L["mt"] + ph + 18, f"{v:g}", 11, "middle"))
    for v in _ticks(view[2], view[3]):
        parts.append(sv.line(L["ml"], sy(v), L["ml"] + pw, sy(v), "#e3e8e3"))
        parts.append(sv.text(L["ml"] - 8, sy(v) + 4, f"{v:g}", 11, "end"))
    parts.append(f"<rect x='{L['ml']}' y='{L['mt']}' width='{pw}' height='{ph}' fill='none' stroke='#8a948d'/>")
    parts.append(sv.text(L["ml"] + pw / 2, H - 12, "Recall (share of truth plasmid bases recovered)", 12, "middle", "bold"))
    parts.append(sv.text(16, L["mt"] + ph / 2, "Precision (share of called bases that are plasmid)", 12, "middle", "bold",
                         extra=f"transform='rotate(-90 16 {L['mt'] + ph / 2:.1f})'"))
    parts.append(f"<g clip-path='url(#prclip-static-{rc.esc(track['id'])})'>")
    for f in ISO_LEVELS:
        pts = " ".join(f"{sx(r):.1f},{sy(p):.1f}" for r, p in iso_f1(f, 60))
        parts.append(f"<polyline points='{pts}' fill='none' stroke='#b9c5bd' stroke-width='1' stroke-opacity='.8'/>")
    stats = {t["name"]: tool_stats(track, t, mode) for t in track["tools"]}
    prev = prevalence([[v["plasmid_bp"], v["total_bp"]] for v in track["samples"].values()], mode)
    if prev is not None:
        parts.append(f"<line x1='{L['ml']}' x2='{L['ml'] + pw}' y1='{sy(prev):.1f}' y2='{sy(prev):.1f}' stroke='#555' stroke-width='1.2' stroke-dasharray='1 4'/>")
    marks = []
    for t in track["tools"]:
        colour, marker, dash = styles[t["name"]]
        st = stats[t["name"]]
        if st["curve"]:
            v = step_vertices(st["curve"])
            if v:
                pts = " ".join(f"{sx(r):.1f},{sy(p):.1f}" for r, p in v)
                parts.append(f"<polyline points='{pts}' fill='none' stroke='{colour}' stroke-width='2.2' stroke-dasharray='{dash}'/>")
            if st["fopt"]:
                marks.append(f"<path d='{marker_path('star', sx(st['fopt']['r']), sy(st['fopt']['p']), 6)}' fill='{colour}' stroke='#000' stroke-width='.8'/>")
        if st["op"]:
            x, y = sx(st["op"]["r"]), sy(st["op"]["p"])
            fill = "#ffffff" if t["baseline"] else colour
            marks.append(f"<path d='{marker_path(marker, x, y, 6)}' fill='{fill}' stroke='{colour if not t['baseline'] else '#555'}' stroke-width='2'>"
                         f"<title>{rc.esc(t['name'])}: precision {st['op']['p']:.3f}, recall {st['op']['r']:.3f}, F1 {st['op']['f'] or 0:.3f}</title></path>")
    parts.append("</g>")
    parts.extend(marks)
    if prev is not None and view[2] <= prev <= view[3]:
        parts.append(sv.text(L["ml"] + 6, sy(prev) - 4, f"prevalence {prev:.3f}", 10, fill="#444"))
    for f in ISO_LEVELS:
        r = 1.0
        p = f / (2 - f)
        if view[0] <= r <= view[1] and view[2] <= p <= view[3]:
            parts.append(sv.text(sx(r) - 4, sy(p) - 3, f"F1={f:g}", 9.5, "end", fill="#5b665f"))
    parts.append(sv.svg_close())
    return "".join(parts)


def static_table(track, mode="micro"):
    rows = []
    styles = _style_of(track["tools"])
    glyph = {"circle": "●", "square": "■", "triangle": "▲", "diamond": "◆", "cross": "✕", "plus": "+", "invtriangle": "▼", "star": "★"}
    for t in track["tools"]:
        st = tool_stats(track, t, mode)
        col, marker, _ = styles[t["name"]]
        name = rc.Raw(f"<span style='color:{col}' aria-hidden='true'>{glyph[marker]}</span> {rc.esc(t['name'])}" + (" (baseline)" if t["baseline"] else ""))
        op, fo = st["op"], st["fopt"]
        rows.append([name, t["task"] or rc.missing("not recorded"),
                     rc.fmt(op["p"] if op else None), rc.fmt(op["r"] if op else None), rc.fmt(op["f"] if op else None),
                     rc.fmt(st["ap"]) if st["ap"] is not None else rc.missing(t["reason"] or "no curve"),
                     rc.fmt(st["auc"]) if st["auc"] is not None else rc.missing("no curve"),
                     rc.fmt(fo["t"], 4) if fo and fo["t"] is not None else rc.missing("no curve"),
                     rc.fmt(st["fp_rec"], 2) if st["fp_rec"] is not None else rc.missing("no plasmid recovered or not scored")])
    return rc.panel(["Tool", "Task", "Precision (default call)", "Recall (default call)", "F1 (of P and R)", "AP (step)", "Trapezoid AUC",
                     "F-optimal threshold", "FP records per recovered plasmid"], rows, "No tools.")


def _track_static(track):
    curves = [t["name"] for t in track["tools"] if t["curve"]]
    none = [t for t in track["tools"] if not t["curve"]]
    note = ""
    if not curves:
        note = str(rc.not_run("no tool wrote a pr_curve.tsv for this track, so there are no curves: every tool is shown as its operating point only."))
    nocurve = ("<ul class='pr-nocurve'>" + "".join(f"<li><strong>{rc.esc(t['name'])}</strong>: no curve: {rc.esc(t['reason'])}</li>" for t in none) + "</ul>") if none else ""
    return (f"<div class='pr-static-track' data-track='{rc.esc(track['id'])}'><h3>Track: {rc.esc(track['id'])}</h3>{note}"
            f"<figure class='rpt-figure'>{static_svg(track)}<figcaption>Default view: micro-averaged, bases, step drawing, axes 0 to 1. "
            f"{len(track['samples'])} sample(s). Stars mark F1-optimal thresholds, hollow grey markers are trivial baselines, the dotted line is the prevalence.</figcaption></figure>"
            f"{static_table(track)}{nocurve}</div>")


def build_section(results_dir, data_dir, scores_path):
    model = build_model(results_dir, data_dir, scores_path)
    if model is None or not model["tracks"]:
        return rc.section("fig-pr", TITLE, LEAD, rc.not_run("scores.tsv is absent or empty, so there is nothing to plot."))
    static = "".join(_track_static(t) for t in model["tracks"])
    text = json.dumps(model, separators=(",", ":"), ensure_ascii=True)
    text = text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    body = (_asset("fig_pr_style.html")
            + f"<div class='pr-root' id='pr-root' data-tracks='{len(model['tracks'])}'><div class='pr-static'>{static}</div></div>"
            + f"<script type='application/json' id='pr-data'>{text}</script>"
            + _asset("fig_pr_core.html") + _asset("fig_pr_ui.html"))
    return rc.section("fig-pr", TITLE, LEAD, body)


def _asset(name):
    with open(Path(__file__).resolve().parent.parent / "assets" / "report" / name, encoding="utf-8", newline="") as handle:
        return handle.read()


def inject(page, results_dir, data_dir, scores_path):
    section = str(build_section(results_dir, data_dir, scores_path))
    return rc.inject_sections(rc.add_style(page), section, SECTIONS)
