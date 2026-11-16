#!/usr/bin/env python3
"""Binning error profile: why a binner scores as it does, not only how much.

PlasEval (Mane et al. 2024) splits the dissimilarity between a predicted and a true set of plasmid bins into four parts. This
module draws them from the columns `scores.tsv` already carries (dissim_*, bestmatch_*) and from `benchmark.tool_agreement.tsv`,
for any run (a benchmark, or the replication of the paper's own bins). Pure SVG, no JavaScript, colour-blind-safe palette,
text and axes in `currentColor` so the figures follow the report's light and dark themes; every mark has a tooltip.

The four parts, as normalised shares of the dissimilarity (cost / normaliser, so they sum to the dissimilarity):

  extra       contigs the tool put in a plasmid bin that are not plasmid contigs in the truth      (precision-type error)
  missing     plasmid contigs in the truth that no predicted bin contains                          (recall-type error)
  over-merged contigs of different true plasmids placed in one predicted bin; PlasEval calls this the "splits" cost
  fragmented  contigs of one true plasmid spread over several predicted bins; PlasEval calls this the "joins" cost

Charts (each answers one question; none changes a ranking):
  tool_error_bars        which kind of error does each tool make, and how much in total?
  tool_error_heatmap     the same numbers as a tool x error-part grid, to read across tools
  precision_recall       does a tool trade precision for recall? one panel per tool, one dot per isolate
  f1_vs_agreement        do tools with similar F1 differ in how well their bins match the truth?
  sample_composition     which isolates are hard, and is it the same kind of error for every tool?
  sample_heatmap         isolate x tool grid of the dissimilarity
  agreement_matrix       do tools agree with each other, and with the truth? (agreement is not accuracy)

Standard library only (report_svg supplies the SVG helpers).
"""
import math

from report_svg import OKABE_ITO, esc, line, num, svg_close, svg_open, text

PARTS = [
    ("extra", "Extra contigs", "dissim_extra_cost", OKABE_ITO["vermillion"],
     "contigs in a predicted plasmid bin that are not plasmid contigs in the truth"),
    ("missing", "Missing contigs", "dissim_missing_cost", OKABE_ITO["blue"],
     "plasmid contigs of the truth that no predicted bin contains"),
    ("merged", "Over-merged bins", "dissim_split_cost", OKABE_ITO["orange"],
     "contigs of different true plasmids placed in one predicted bin (PlasEval 'splits')"),
    ("fragmented", "Fragmented plasmids", "dissim_join_cost", OKABE_ITO["green"],
     "contigs of one true plasmid spread over several predicted bins (PlasEval 'joins')"),
]
TOOL_COLOURS = [OKABE_ITO["blue"], OKABE_ITO["vermillion"], OKABE_ITO["green"], OKABE_ITO["orange"], OKABE_ITO["purple"],
                OKABE_ITO["sky"], "#882255", "#44AA99", "#999933", "#117733"]
MAX_HEATMAP_ROWS = 120


def number(value):
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


# ----------------------------------------------------------------------------------------------- data
def usable(rows):
    """Rows with a computed dissimilarity (not 'not applicable', not blank)."""
    out = []
    for r in rows or []:
        if (r.get("dissim_status") or "ok") != "ok" or number(r.get("bin_dissimilarity")) is None:
            continue
        norm = number(r.get("dissim_norm"))
        if not norm:
            continue
        out.append(r)
    return out


def parts_of(row):
    """Normalised shares of one row; they add up to the row's dissimilarity."""
    norm = number(row.get("dissim_norm")) or 1.0
    return {key: (number(row.get(col)) or 0.0) / norm for key, _, col, _, _ in PARTS}


def aggregate(rows):
    """Per tool: isolates, mean dissimilarity, mean share of each part, mean best-match precision/recall/F1 (bp), cap count."""
    by = {}
    for r in usable(rows):
        by.setdefault(r["tool"], []).append(r)
    agg = []
    for tool, group in by.items():
        shares = [parts_of(r) for r in group]
        entry = {
            "tool": tool, "n": len(group), "dissim": mean([number(r["bin_dissimilarity"]) for r in group]),
            "precision": mean([number(r.get("bestmatch_precision_bp")) for r in group]),
            "recall": mean([number(r.get("bestmatch_recall_bp")) for r in group]),
            "f1": mean([number(r.get("bestmatch_f1_bp")) for r in group]),
            "capped": sum((r.get("dissim_repeat_search") or "") == "capped" for r in group),
        }
        for key, *_ in PARTS:
            entry[key] = mean([s[key] for s in shares])
        agg.append(entry)
    agg.sort(key=lambda e: (e["dissim"] if e["dissim"] is not None else 9, e["tool"]))
    return agg


def tool_colours(tools):
    return {t: TOOL_COLOURS[i % len(TOOL_COLOURS)] for i, t in enumerate(sorted(tools))}


def ramp(value, vmax=1.0):
    """Sequential light-to-dark blue; value 0 is the lightest. Returns (fill, text colour)."""
    t = 0.0 if value is None else max(0.0, min(1.0, value / vmax if vmax else 0.0))
    lo, hi = (247, 251, 255), (8, 48, 107)
    rgb = tuple(round(lo[i] + (hi[i] - lo[i]) * t) for i in range(3))
    return "#%02x%02x%02x" % rgb, ("#ffffff" if t > 0.55 else "#111111")


def _fmt(x, d=3):
    return "-" if x is None else f"{x:.{d}f}"


def _axis_y(x0, y0, y1, vmax, label, ticks=5):
    out = [line(x0, y0, x0, y1, "currentColor", 1, "opacity='0.6'")]
    for i in range(ticks + 1):
        v = vmax * i / ticks
        y = y1 - (y1 - y0) * i / ticks
        out.append(line(x0 - 4, y, x0, y, "currentColor", 1, "opacity='0.6'"))
        out.append(text(x0 - 7, y + 3.5, _fmt(v, 2).rstrip("0").rstrip(".") if v else "0", 9.5, "end"))
    out.append(text(12, (y0 + y1) / 2, label, 10.5, "middle", extra=f"transform='rotate(-90 12 {num((y0 + y1) / 2)})'"))
    return "".join(out)


def legend(items, x, y, step=170):
    out = []
    for i, (colour, label) in enumerate(items):
        out.append(f"<rect x='{num(x + i * step)}' y='{num(y - 9)}' width='11' height='11' rx='2' fill='{colour}'/>")
        out.append(text(x + i * step + 16, y, label, 10.5))
    return "".join(out)


# ----------------------------------------------------------------------------------------------- charts
def tool_error_bars(agg):
    if not agg:
        return ""
    W, left, right, top = 760, 150, 110, 36
    rowh = 34
    H = top + rowh * len(agg) + 56
    vmax = max((e["dissim"] or 0) for e in agg) or 1.0
    vmax = min(1.0, math.ceil(vmax * 20) / 20)
    scale = (W - left - right) / vmax
    out = [svg_open(W, H, "Error profile by tool",
                    "Stacked horizontal bars: each tool's mean dissimilarity from the truth split into extra contigs, missing "
                    "contigs, over-merged bins and fragmented plasmids. Shorter is better.")]
    out.append(legend([(c, lab) for _, lab, _, c, _ in PARTS], left, 16, 150))
    for i, e in enumerate(agg):
        y = top + i * rowh
        out.append(text(left - 10, y + 17, e["tool"], 11.5, "end", "bold"))
        x = left
        for key, label, _, colour, meaning in PARTS:
            v = e[key] or 0.0
            w = v * scale
            if w > 0:
                out.append(f"<rect x='{num(x)}' y='{num(y + 4)}' width='{num(w)}' height='20' fill='{colour}'>"
                           f"<title>{esc(e['tool'])}: {esc(label)} {v:.3f} of the dissimilarity; {esc(meaning)}</title></rect>")
                if w > 34:
                    out.append(text(x + w / 2, y + 18, f"{v:.2f}", 9.5, "middle", fill="#111111" if colour in (
                        OKABE_ITO["orange"], OKABE_ITO["sky"], OKABE_ITO["yellow"]) else "#ffffff"))
            x += w
        out.append(text(x + 6, y + 18, f"{e['dissim']:.3f}  (n={e['n']})", 10.5))
    base = top + rowh * len(agg) + 4
    out.append(line(left, top - 2, left, base, "currentColor", 1, "opacity='0.6'"))
    for i in range(0, 6):
        v = vmax * i / 5
        out.append(line(left + v * scale, base, left + v * scale, base + 4, "currentColor", 1, "opacity='0.6'"))
        out.append(text(left + v * scale, base + 16, f"{v:.2f}", 9.5, "middle"))
    out.append(text(left + (W - left - right) / 2, base + 34, "Mean dissimilarity from the truth (0 = identical bins; lower is better)",
                    10.5, "middle"))
    out.append(svg_close())
    return "".join(out)


def tool_error_heatmap(agg):
    if not agg:
        return ""
    cw, ch, left, top = 112, 34, 150, 52
    W = left + cw * (len(PARTS) + 1) + 20
    H = top + ch * len(agg) + 16
    vmax = max([e[k] or 0 for e in agg for k, *_ in PARTS] + [0.001])
    out = [svg_open(W, H, "Tool by error part",
                    "Grid of tools by error part; each cell is the mean share of the dissimilarity. Darker means more of that error.")]
    for j, (key, label, _, colour, meaning) in enumerate(PARTS):
        out.append(f"<rect x='{left + j * cw + 4}' y='{top - 22}' width='{cw - 8}' height='4' fill='{colour}'/>")
        out.append(text(left + j * cw + cw / 2, top - 28, label, 10.5, "middle", "bold"))
    out.append(text(left + len(PARTS) * cw + cw / 2, top - 28, "Total", 10.5, "middle", "bold"))
    for i, e in enumerate(agg):
        y = top + i * ch
        out.append(text(left - 10, y + ch / 2 + 4, e["tool"], 11.5, "end", "bold"))
        for j, (key, label, _, _, meaning) in enumerate(PARTS):
            v = e[key]
            fill, ink = ramp(v, vmax)
            out.append(f"<rect x='{left + j * cw + 1}' y='{y + 1}' width='{cw - 2}' height='{ch - 2}' fill='{fill}'>"
                       f"<title>{esc(e['tool'])}: {esc(label)} {_fmt(v)}; {esc(meaning)}</title></rect>")
            out.append(text(left + j * cw + cw / 2, y + ch / 2 + 4, _fmt(v), 11, "middle", fill=ink))
        fill, ink = ramp(e["dissim"], max(vmax * 2, 0.001))
        out.append(f"<rect x='{left + len(PARTS) * cw + 1}' y='{y + 1}' width='{cw - 2}' height='{ch - 2}' fill='{fill}'>"
                   f"<title>{esc(e['tool'])}: mean dissimilarity {_fmt(e['dissim'])} over {e['n']} isolates</title></rect>")
        out.append(text(left + len(PARTS) * cw + cw / 2, y + ch / 2 + 4, _fmt(e["dissim"]), 11, "middle", "bold", fill=ink))
    out.append(svg_close())
    return "".join(out)


def precision_recall(rows):
    data = {}
    for r in usable(rows):
        p, q = number(r.get("bestmatch_precision_bp")), number(r.get("bestmatch_recall_bp"))
        if p is not None and q is not None:
            data.setdefault(r["tool"], []).append((q, p, r["sample"]))
    if not data:
        return ""
    tools = sorted(data)
    col = tool_colours(tools)
    per_row = 3 if len(tools) > 4 else 2
    pw, ph, pad_l, pad_t, gap = 300, 250, 44, 26, 30
    n_rows = math.ceil(len(tools) / per_row)
    W = per_row * (pw + gap) + 20
    H = n_rows * (ph + 52) + 8
    out = [svg_open(W, H, "Precision against recall, one panel per tool",
                    "Each dot is one isolate: best-match recall on the horizontal axis and best-match precision on the vertical "
                    "axis, base-pair weighted. The cross is the tool mean. A tool near the top left over-predicts nothing but "
                    "misses plasmid; near the bottom right it finds plasmid but adds chromosome.")]
    for k, tool in enumerate(tools):
        ox, oy = 10 + (k % per_row) * (pw + gap), 6 + (k // per_row) * (ph + 52)
        x0, y0, x1, y1 = ox + pad_l, oy + pad_t, ox + pw - 8, oy + ph - 30
        out.append(text(ox + pad_l, oy + 14, tool, 12, "start", "bold"))
        out.append(f"<rect x='{x0}' y='{y0}' width='{x1 - x0}' height='{y1 - y0}' fill='none' stroke='currentColor' stroke-opacity='0.35'/>")
        for t in (0, 0.25, 0.5, 0.75, 1):
            gx, gy = x0 + (x1 - x0) * t, y1 - (y1 - y0) * t
            out.append(line(gx, y1, gx, y1 + 3, "currentColor", 1, "opacity='0.6'"))
            out.append(line(x0 - 3, gy, x0, gy, "currentColor", 1, "opacity='0.6'"))
            if t in (0, 0.5, 1):
                out.append(text(gx, y1 + 14, f"{t:g}", 9.5, "middle"))
                out.append(text(x0 - 6, gy + 3.5, f"{t:g}", 9.5, "end"))
        out.append(text((x0 + x1) / 2, y1 + 27, "Recall (share of truth plasmid bp found)", 10, "middle"))
        out.append(text(ox + 10, (y0 + y1) / 2, "Precision", 10, "middle", extra=f"transform='rotate(-90 {ox + 10} {num((y0 + y1) / 2)})'"))
        for rec, prec, sample in data[tool]:
            out.append(f"<circle cx='{num(x0 + (x1 - x0) * rec)}' cy='{num(y1 - (y1 - y0) * prec)}' r='3.4' fill='{col[tool]}' "
                       f"fill-opacity='0.45' stroke='{col[tool]}' stroke-width='0.8'><title>{esc(sample)}: recall {rec:.3f}, "
                       f"precision {prec:.3f}</title></circle>")
        mr, mp = mean([d[0] for d in data[tool]]), mean([d[1] for d in data[tool]])
        cx, cy = x0 + (x1 - x0) * mr, y1 - (y1 - y0) * mp
        out.append(f"<path d='M{num(cx - 6)} {num(cy)}H{num(cx + 6)}M{num(cx)} {num(cy - 6)}V{num(cy + 6)}' stroke='currentColor' "
                   f"stroke-width='2.2'><title>{esc(tool)} mean: recall {mr:.3f}, precision {mp:.3f}</title></path>")
    out.append(svg_close())
    return "".join(out)


def f1_vs_agreement(agg, rows):
    pts = {}
    for r in usable(rows):
        f1, d = number(r.get("bestmatch_f1_bp")), number(r.get("bin_dissimilarity"))
        if f1 is not None and d is not None:
            pts.setdefault(r["tool"], []).append((f1, 1 - d, r["sample"]))
    if not pts:
        return ""
    tools = sorted(pts)
    col = tool_colours(tools)
    W, H, l, t, r_, b = 560, 420, 62, 24, 20, 56
    x0, y0, x1, y1 = l, t, W - r_, H - b
    out = [svg_open(W, H, "Best-match F1 against agreement with the truth",
                    "Each faint dot is one isolate and each large dot is a tool mean. Horizontal: best-match F1 (base-pair "
                    "weighted). Vertical: agreement with the truth, one minus the dissimilarity. Tools at the same F1 but at "
                    "different heights make different kinds of error.")]
    out.append(f"<rect x='{x0}' y='{y0}' width='{x1 - x0}' height='{y1 - y0}' fill='none' stroke='currentColor' stroke-opacity='0.35'/>")
    for tt in (0, 0.25, 0.5, 0.75, 1):
        gx, gy = x0 + (x1 - x0) * tt, y1 - (y1 - y0) * tt
        out.append(line(gx, y1, gx, y1 + 3, "currentColor", 1, "opacity='0.6'"))
        out.append(line(x0 - 3, gy, x0, gy, "currentColor", 1, "opacity='0.6'"))
        out.append(text(gx, y1 + 15, f"{tt:g}", 10, "middle"))
        out.append(text(x0 - 7, gy + 3.5, f"{tt:g}", 10, "end"))
    out.append(text((x0 + x1) / 2, y1 + 34, "Best-match F1 (base-pair weighted)", 11, "middle"))
    out.append(text(14, (y0 + y1) / 2, "Agreement with truth (1 - dissimilarity)", 11, "middle",
                    extra=f"transform='rotate(-90 14 {num((y0 + y1) / 2)})'"))
    for tool in tools:
        for f1, ag, sample in pts[tool]:
            out.append(f"<circle cx='{num(x0 + (x1 - x0) * f1)}' cy='{num(y1 - (y1 - y0) * ag)}' r='3' fill='{col[tool]}' "
                       f"fill-opacity='0.25'><title>{esc(tool)} {esc(sample)}: F1 {f1:.3f}, agreement {ag:.3f}</title></circle>")
    for i, tool in enumerate(tools):
        mf, ma = mean([p[0] for p in pts[tool]]), mean([p[1] for p in pts[tool]])
        cx, cy = x0 + (x1 - x0) * mf, y1 - (y1 - y0) * ma
        out.append(f"<circle cx='{num(cx)}' cy='{num(cy)}' r='7.5' fill='{col[tool]}' stroke='currentColor' stroke-width='1.4'>"
                   f"<title>{esc(tool)} mean: F1 {mf:.3f}, agreement {ma:.3f} over {len(pts[tool])} isolates</title></circle>")
        out.append(text(cx + 11, cy + 4, tool, 10.5, "start", "bold"))
    out.append(svg_close())
    return "".join(out)


def _sample_order(rows, tools):
    by = {}
    for r in usable(rows):
        by.setdefault(r["sample"], []).append(number(r["bin_dissimilarity"]))
    return sorted(by, key=lambda s: (mean(by[s]), s))


def sample_composition(rows):
    use = usable(rows)
    tools = sorted({r["tool"] for r in use})
    samples = _sample_order(rows, tools)
    if not tools or not samples:
        return ""
    cell = {(r["tool"], r["sample"]): parts_of(r) for r in use}
    vmax = max(sum(v.values()) for v in cell.values()) or 1.0
    vmax = min(1.0, math.ceil(vmax * 10) / 10)
    W, left, right = 780, 52, 14
    ph, gap = 120, 34
    H = len(tools) * (ph + gap) + 70
    bw = (W - left - right) / len(samples)
    out = [svg_open(W, H, "Error composition per isolate",
                    "One panel per tool; isolates are in the same order in every panel, easiest on the left to hardest on the "
                    "right by mean dissimilarity across tools. Each bar is split into extra, missing, over-merged and "
                    "fragmented shares.")]
    out.append(legend([(c, lab) for _, lab, _, c, _ in PARTS], left, 14, 160))
    for k, tool in enumerate(tools):
        top = 34 + k * (ph + gap)
        bottom = top + ph
        out.append(text(left, top - 6, tool, 11.5, "start", "bold"))
        out.append(_axis_y(left, top, bottom, vmax, "Dissimilarity", 4))
        for i, s in enumerate(samples):
            v = cell.get((tool, s))
            x = left + i * bw
            if v is None:
                out.append(f"<rect x='{num(x + 0.5)}' y='{bottom - 6}' width='{num(max(bw - 1, 1))}' height='6' fill='#999' "
                           f"fill-opacity='0.4'><title>{esc(s)}: not scored for {esc(tool)}</title></rect>")
                continue
            y = bottom
            for key, label, _, colour, _m in PARTS:
                h = v[key] / vmax * ph
                if h > 0:
                    y -= h
                    out.append(f"<rect x='{num(x + 0.5)}' y='{num(y)}' width='{num(max(bw - 1, 1))}' height='{num(h)}' fill='{colour}'>"
                               f"<title>{esc(s)} / {esc(tool)}: {esc(label)} {v[key]:.3f} (total {sum(v.values()):.3f})</title></rect>")
        out.append(line(left, bottom, W - right, bottom, "currentColor", 1, "opacity='0.6'"))
    out.append(text(left + (W - left - right) / 2, H - 8,
                    f"Isolates ({len(samples)}), easiest to hardest by mean dissimilarity across tools", 10.5, "middle"))
    out.append(svg_close())
    return "".join(out)


def sample_heatmap(rows):
    use = usable(rows)
    tools = sorted({r["tool"] for r in use})
    samples = _sample_order(rows, tools)
    if not tools or not samples:
        return "", 0
    shown = samples[:MAX_HEATMAP_ROWS]
    cell = {(r["tool"], r["sample"]): number(r["bin_dissimilarity"]) for r in use}
    ch, cw, left, top = 13, 90, 150, 46
    W = left + cw * len(tools) + 70
    H = top + ch * len(shown) + 20
    out = [svg_open(W, H, "Dissimilarity per isolate and tool",
                    "Grid of isolates by tool, coloured by dissimilarity from the truth: lighter is closer to the truth. "
                    "Isolates are sorted from easiest to hardest by mean across tools; grey hatching means not scored.")]
    out.append("<defs><pattern id='na' width='5' height='5' patternUnits='userSpaceOnUse' patternTransform='rotate(45)'>"
               "<line x1='0' y1='0' x2='0' y2='5' stroke='#999' stroke-width='1.4'/></pattern></defs>")
    for j, tool in enumerate(tools):
        out.append(text(left + j * cw + cw / 2, top - 10, tool, 11, "middle", "bold"))
    for i, s in enumerate(shown):
        y = top + i * ch
        out.append(text(left - 6, y + ch - 3, s, 9, "end"))
        for j, tool in enumerate(tools):
            v = cell.get((tool, s))
            if v is None:
                out.append(f"<rect x='{left + j * cw + 1}' y='{y + 0.5}' width='{cw - 2}' height='{ch - 1}' fill='url(#na)'>"
                           f"<title>{esc(s)} / {esc(tool)}: not scored</title></rect>")
            else:
                fill, _ = ramp(v, 1.0)
                out.append(f"<rect x='{left + j * cw + 1}' y='{y + 0.5}' width='{cw - 2}' height='{ch - 1}' fill='{fill}'>"
                           f"<title>{esc(s)} / {esc(tool)}: dissimilarity {v:.3f}</title></rect>")
    lx, ly = left + cw * len(tools) + 18, top
    for i in range(0, 6):
        fill, _ = ramp(i / 5, 1.0)
        out.append(f"<rect x='{lx}' y='{ly + i * 16}' width='14' height='15' fill='{fill}' stroke='currentColor' stroke-opacity='0.2'/>")
        out.append(text(lx + 20, ly + i * 16 + 12, f"{i / 5:.1f}", 9.5))
    out.append(svg_close())
    return "".join(out), len(samples) - len(shown)


def agreement_matrix(matrix):
    """matrix: rows of tool_a, tool_b, n_samples, mean_dissimilarity (tool_b may be 'truth')."""
    cells, tools = {}, set()
    for r in matrix or []:
        d = number(r.get("mean_dissimilarity"))
        if d is None:
            continue
        a, b = r["tool_a"], r["tool_b"]
        cells[(a, b)] = cells[(b, a)] = (d, r.get("n_samples", ""))
        tools.update([a, b])
    if len(tools) < 2:
        return ""
    names = sorted(t for t in tools if t != "truth") + (["truth"] if "truth" in tools else [])
    cw, left, top = 92, 130, 78
    W, H = left + cw * len(names) + 16, top + cw * 0.5 * len(names) + 30
    rh = cw * 0.5
    out = [svg_open(W, H, "Agreement between tools and with the truth",
                    "Symmetric grid of mean dissimilarity between each pair of tools and between each tool and the truth. "
                    "Lighter means the two bin sets are more alike. Two tools can agree and both be wrong.")]
    for j, n in enumerate(names):
        out.append(text(left + j * cw + cw / 2, top - 8, n, 10.5, "middle", "bold" if n == "truth" else "normal",
                        extra=f"transform='rotate(-30 {num(left + j * cw + cw / 2)} {num(top - 8)})'"))
    for i, a in enumerate(names):
        y = top + i * rh
        out.append(text(left - 8, y + rh / 2 + 4, a, 10.5, "end", "bold" if a == "truth" else "normal"))
        for j, b in enumerate(names):
            if a == b:
                out.append(f"<rect x='{left + j * cw + 1}' y='{y + 1}' width='{cw - 2}' height='{rh - 2}' fill='none' "
                           f"stroke='currentColor' stroke-opacity='0.15'/>")
                continue
            v = cells.get((a, b))
            if v is None:
                continue
            fill, ink = ramp(v[0], 1.0)
            out.append(f"<rect x='{left + j * cw + 1}' y='{y + 1}' width='{cw - 2}' height='{rh - 2}' fill='{fill}'>"
                       f"<title>{esc(a)} vs {esc(b)}: mean dissimilarity {v[0]:.3f} over {esc(v[1])} isolates</title></rect>")
            out.append(text(left + j * cw + cw / 2, y + rh / 2 + 4, f"{v[0]:.2f}", 10.5, "middle", fill=ink))
    out.append(svg_close())
    return "".join(out)


# ----------------------------------------------------------------------------------------------- reading the figures
def alpha_stability(rows):
    """Tool order by mean dissimilarity at length exponent 0, the configured one and 1, and whether the order changes."""
    use = [r for r in usable(rows) if number(r.get("bin_dissimilarity_alpha0")) is not None
           and number(r.get("bin_dissimilarity_alpha1")) is not None]
    if not use:
        return None
    by = {}
    for r in use:
        by.setdefault(r["tool"], []).append(r)
    table = {t: (mean([number(r["bin_dissimilarity_alpha0"]) for r in g]), mean([number(r["bin_dissimilarity"]) for r in g]),
                 mean([number(r["bin_dissimilarity_alpha1"]) for r in g])) for t, g in by.items()}
    orders = [tuple(sorted(table, key=lambda t: (table[t][k], t))) for k in range(3)]
    return {"table": table, "orders": orders, "stable": len(set(orders)) == 1}


def findings(agg, rows):
    """Plain-language reading of the figures, computed from the data, with the cautions a reader needs."""
    out = []
    if not agg:
        return out
    best = agg[0]
    out.append(f"{best['tool']} has the lowest mean dissimilarity from the truth ({best['dissim']:.3f}, {best['n']} isolates).")
    for e in agg:
        shares = {key: e[key] or 0.0 for key, *_ in PARTS}
        main = max(shares, key=shares.get)
        label = next(lab for k, lab, *_ in PARTS if k == main)
        if e["dissim"]:
            out.append(f"{e['tool']}: the largest part of its error is {label.lower()} "
                       f"({shares[main] / e['dissim'] * 100:.0f}% of its dissimilarity).")
    for i, a in enumerate(agg):
        for b in agg[i + 1:]:
            if a["f1"] is None or b["f1"] is None:
                continue
            if abs(a["f1"] - b["f1"]) <= 0.03 and abs((a["dissim"] or 0) - (b["dissim"] or 0)) >= 0.03:
                out.append(f"{a['tool']} and {b['tool']} have nearly the same best-match F1 ({a['f1']:.3f} and {b['f1']:.3f}) but "
                           f"differ in dissimilarity ({a['dissim']:.3f} and {b['dissim']:.3f}): F1 alone would not separate them.")
    stab = alpha_stability(rows)
    if stab:
        if stab["stable"]:
            out.append("The tool order is the same whether contig length is ignored (alpha 0), partly weighted or fully weighted (alpha 1).")
        else:
            out.append("The tool order changes with how contig length is weighted (alpha 0, configured, alpha 1): "
                       + "; ".join(" < ".join(o) for o in stab["orders"]) + ". Report the length exponent with the result.")
    capped = sum(e["capped"] for e in agg)
    if capped:
        out.append(f"{capped} comparison(s) reached the repeat-matching search cap; those dissimilarities are upper bounds.")
    return out


def comparison_rows(rows, mine="bin_dissimilarity", theirs="original_dissimilarity", tolerance=1e-3):
    """Rows that carry the original program's answer, with the verdict for each: agree, capped_upper_bound, disagree or not_compared."""
    out = []
    for r in rows or []:
        status = r.get("original_status") or ("ok" if number(r.get(theirs)) is not None else "")
        if not status and number(r.get(theirs)) is None:
            continue
        a, b = number(r.get(mine)), number(r.get(theirs))
        if status != "ok" or a is None or b is None:
            verdict = "not_compared"
        elif abs(a - b) < tolerance:
            verdict = "agree"
        elif r.get("dissim_repeat_search") == "capped" and a > b:
            verdict = "capped_upper_bound"
        else:
            verdict = "disagree"
        out.append({"sample": r.get("sample", ""), "tool": r.get("tool", ""), "mine": a, "theirs": b, "verdict": verdict, "status": status,
                    "families": r.get("dissim_repeat_families", ""), "search": r.get("dissim_repeat_search", "")})
    return out


def agreement_scatter(items):
    pts = [i for i in items if i["mine"] is not None and i["theirs"] is not None]
    if not pts:
        return ""
    tools = sorted({i["tool"] for i in pts})
    col = tool_colours(tools)
    W, H, l, t, r_, b = 520, 470, 62, 20, 20, 58
    x0, y0, x1, y1 = l, t, W - r_, H - b
    out = [svg_open(W, H, "PlasBench against the original program",
                    "Each point is one isolate-tool pair: the original program's normalised dissimilarity on the horizontal axis and PlasBench's on "
                    "the vertical axis. Points on the diagonal agree. A hollow point is a PlasBench search that reached its cap, which is an upper bound.")]
    out.append(f"<rect x='{x0}' y='{y0}' width='{x1 - x0}' height='{y1 - y0}' fill='none' stroke='currentColor' stroke-opacity='0.35'/>")
    for tt in (0, 0.25, 0.5, 0.75, 1):
        gx, gy = x0 + (x1 - x0) * tt, y1 - (y1 - y0) * tt
        out.append(line(gx, y1, gx, y1 + 3, "currentColor", 1, "opacity='0.6'"))
        out.append(line(x0 - 3, gy, x0, gy, "currentColor", 1, "opacity='0.6'"))
        out.append(text(gx, y1 + 15, f"{tt:g}", 10, "middle"))
        out.append(text(x0 - 7, gy + 3.5, f"{tt:g}", 10, "end"))
    out.append(line(x0, y1, x1, y0, "currentColor", 1, "opacity='0.55' stroke-dasharray='5 4'"))
    out.append(text((x0 + x1) / 2, y1 + 36, "Original program: normalised dissimilarity", 11, "middle"))
    out.append(text(14, (y0 + y1) / 2, "PlasBench: normalised dissimilarity", 11, "middle", extra=f"transform='rotate(-90 14 {num((y0 + y1) / 2)})'"))
    for i in pts:
        cx, cy = x0 + (x1 - x0) * i["theirs"], y1 - (y1 - y0) * i["mine"]
        hollow = i["verdict"] == "capped_upper_bound"
        fill = "none" if hollow else col[i["tool"]]
        stroke = "#000000" if i["verdict"] == "disagree" else col[i["tool"]]
        out.append(f"<circle cx='{num(cx)}' cy='{num(cy)}' r='3.6' fill='{fill}' fill-opacity='0.55' stroke='{stroke}' stroke-width='{1.8 if hollow or i['verdict'] == 'disagree' else 0.8}'>"
                   f"<title>{esc(i['sample'])} / {esc(i['tool'])}: original {i['theirs']:.4f}, PlasBench {i['mine']:.4f} ({esc(i['verdict'].replace('_', ' '))})</title></circle>")
    for k, tool in enumerate(tools):
        out.append(f"<circle cx='{x0 + 12 + k * 118}' cy='{y0 + 12}' r='4.5' fill='{col[tool]}'/>" + text(x0 + 22 + k * 118, y0 + 16, tool, 10.5))
    out.append(svg_close())
    return "".join(out)


def original_comparison_html(rows, tolerance=1e-3, mine="bin_dissimilarity", theirs="original_dissimilarity"):
    """The replication's comparison with the original program: verdict, per-tool table, scatter and the pairs that could not be compared."""
    items = comparison_rows(rows, mine, theirs, tolerance)
    if not items:
        return ("<div class='insight caution'><p>The original PlasEval program was not run on these bins, so PlasBench's agreement with it here is "
                "not shown. Run it with a PlasEval checkout (see docs/PLASEVAL_REPLICATION.md).</p></div>")
    n = len(items)
    c = {v: sum(1 for i in items if i["verdict"] == v) for v in ("agree", "capped_upper_bound", "disagree", "not_compared")}
    compared = n - c["not_compared"]
    diffs = [abs(i["mine"] - i["theirs"]) for i in items if i["mine"] is not None and i["theirs"] is not None]
    worst = max(diffs) if diffs else 0.0
    if c["disagree"]:
        verdict, cls = "FAIL", "insight caution"
    elif c["not_compared"] and not compared:
        verdict, cls = "NOT RUN", "insight caution"
    elif c["not_compared"]:
        verdict, cls = "PARTIAL", "insight caution"
    else:
        verdict, cls = "PASS", "insight"
    head = (f"<div class='{cls}'><p><strong>Comparison with the original PlasEval program: {verdict}.</strong> {compared} of {n} isolate-tool pairs were compared "
            f"({c['agree']} agree within {tolerance:g}, {c['capped_upper_bound']} PlasBench upper bound(s) from a capped search, {c['disagree']} disagree); "
            f"largest absolute difference {worst:.6f}. {c['not_compared']} pair(s) could not be compared because the original timed out or failed.</p></div>")
    tools = sorted({i["tool"] for i in items})
    body = []
    for tool in tools:
        g = [i for i in items if i["tool"] == tool]
        d = [abs(i["mine"] - i["theirs"]) for i in g if i["mine"] is not None and i["theirs"] is not None]
        body.append(f"<tr><td>{esc(tool)}</td><td>{len(g)}</td><td>{len(d)}</td><td>{sum(1 for i in g if i['verdict'] == 'agree')}</td>"
                    f"<td>{sum(1 for i in g if i['verdict'] == 'capped_upper_bound')}</td><td>{sum(1 for i in g if i['verdict'] == 'disagree')}</td>"
                    f"<td>{sum(1 for i in g if i['verdict'] == 'not_compared')}</td><td>{max(d) if d else 0:.6f}</td><td>{(sum(d) / len(d)) if d else 0:.6f}</td></tr>")
    table = ("<div class='panel'><table><thead><tr><th>Tool</th><th>Pairs</th><th>Compared</th><th>Agree</th><th>Capped (upper bound)</th><th>Disagree</th>"
             "<th>Not compared</th><th>Max difference</th><th>Mean difference</th></tr></thead><tbody>" + "".join(body) + "</tbody></table></div>")
    missed = [i for i in items if i["verdict"] == "not_compared"]
    listing = ""
    if missed:
        listing = ("<h3>Pairs the original program did not finish</h3><div class='panel'><table><thead><tr><th>Isolate</th><th>Tool</th><th>Result</th>"
                   "<th>Repeat families (PlasBench)</th></tr></thead><tbody>"
                   + "".join(f"<tr><td>{esc(i['sample'])}</td><td>{esc(i['tool'])}</td><td>{esc(i['status'])}</td><td>{esc(i['families'])}</td></tr>" for i in missed)
                   + "</tbody></table></div><p class='small'>These are the pairs with the largest repeat families: the original's exhaustive pairing search is slow in "
                     "pure Python. Their absence is stated, not filled in.</p>")
    scatter = agreement_scatter(items)
    return head + table + (f"<figure class='binfig'><div style='overflow-x:auto'>{scatter}</div></figure>" if scatter else "") + listing


def figure(svg, title, caption):
    if not svg:
        return ""
    return (f"<figure class='binfig'><figcaption><strong>{esc(title)}</strong> {esc(caption)}</figcaption>"
            f"<div class='binfig-body' style='overflow-x:auto'>{svg}</div></figure>")


def section_html(scores, matrix=None):
    """All charts plus the reading notes, as an HTML fragment; says what is missing instead of staying silent."""
    agg = aggregate(scores)
    if not agg:
        return ("<div class='insight caution'><p>No error profile: no tool has a computed dissimilarity (tools that output "
                "reassembled sequences are not applicable, and the contig labels may be missing).</p></div>")
    heat, hidden = sample_heatmap(scores)
    parts = ["<div class='binfigs'>"]
    reading = "".join(f"<li>{esc(t)}</li>" for t in findings(agg, scores))
    parts.append(f"<div class='insight'><p><strong>What the figures say</strong> (computed from this run; secondary evidence that "
                 f"never changes a ranking)</p><ul>{reading}</ul></div>")
    parts.append(figure(tool_error_bars(agg), "Error profile by tool.",
                        "Each bar is a tool's mean dissimilarity from the truth, split into the four parts. Same length = same "
                        "total error; different colours = different kinds of error."))
    parts.append(figure(tool_error_heatmap(agg), "Tool by error part.", "The same shares as a grid, for reading across tools."))
    parts.append(figure(precision_recall(scores), "Precision against recall.",
                        "One panel per tool, one dot per isolate (best-match, base-pair weighted); the cross is the tool mean."))
    parts.append(figure(f1_vs_agreement(agg, scores), "F1 against agreement with the truth.",
                        "Tools at the same F1 but at different heights differ in the kind of binning error."))
    parts.append(figure(sample_composition(scores), "Error composition per isolate.",
                        "Which isolates are hard, and whether the same kind of error recurs across tools."))
    parts.append(figure(heat, "Isolate by tool.", "Dissimilarity per isolate and tool"
                        + (f" (hardest {MAX_HEATMAP_ROWS} shown; {hidden} easier isolates omitted)." if hidden else ".")))
    parts.append(figure(agreement_matrix(matrix), "Do tools agree?",
                        "Mean dissimilarity between each pair of tools and with the truth. Agreement is not accuracy: two tools "
                        "can agree and both be wrong."))
    stab = alpha_stability(scores)
    if stab:
        rows = "".join(f"<tr><td>{esc(t)}</td>" + "".join(f"<td>{v:.3f}</td>" for v in vals) + "</tr>"
                       for t, vals in sorted(stab["table"].items(), key=lambda kv: kv[1][1]))
        parts.append("<figure class='binfig'><figcaption><strong>Does the length exponent matter?</strong> Mean dissimilarity at "
                     "alpha 0 (contig length ignored), the configured alpha and alpha 1 (fully length weighted).</figcaption>"
                     "<div class='panel'><table class='sortable'><thead><tr><th>Tool</th><th>alpha 0</th><th>configured</th>"
                     f"<th>alpha 1</th></tr></thead><tbody>{rows}</tbody></table></div></figure>")
    parts.append("</div>")
    return "".join(p for p in parts)
