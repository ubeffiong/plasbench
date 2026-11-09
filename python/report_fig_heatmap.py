#!/usr/bin/env python3
"""
report_fig_heatmap.py -- FIGURE 'Performance of every tool across every metric' (section fig-heatmap).

A heatmap of tools (rows, one block per analysis track, never pooled across tracks) by metrics (columns, grouped by family:
A accuracy, B completeness, C structure, D function, E performance, L leaderboard).  The numbers come from the scorecard module
(report_scorecard.metric_values / score_value / overall, config/scorecard.tsv) and from benchmark.leaderboard.tsv; nothing is recomputed
here except the display transforms below.

Display modes (what the cell shows and how it is coloured; colour is always "good = the bright end", lower-is-better metrics are flipped
and carry a down-triangle marker in the header)
  raw    the value in its own unit; colour = min-max inside the column of the block (relative: a flat column is neutral, not "good")
  score  the scorecard 0-100 score (piecewise linear through the config thresholds); colour = score / 100 (absolute).  A metric with no
         bands (A4, C2 and the leaderboard metrics) has no score: it is drawn as 'not available' in this mode, never as 0
  rank   1 = best in the block, ties share the average rank; colour = (n - rank) / (n - 1)
  z      z-score inside the column of the block (population sd), sign flipped for lower-is-better so positive = better; diverging colour,
         clamped to [-2, 2]; no spread -> z = 0 (all tools equal); fewer than two tools -> not available
Every mode reduces to a colour value t in [0, 1] (z: t = (clamp(z, -2, 2) + 2) / 4); the clustering uses t.

Clustering: average linkage (UPGMA) on t.  Row distance = root-mean-square difference over the columns both rows have (pairwise-complete,
at least one shared); column distance the same over rows (at least two shared).  An undefined distance is replaced by the largest defined
distance (1.0 if none is defined).  Rows with no value, and columns with fewer than two values, are left out of the clustering and appended
unclustered.  Ties are broken by the lowest cluster ids, and the left child of a merge is the lower id, so the order is deterministic.
The same algorithm is implemented in assets/report/fig_heatmap_core.html; test/test_report_fig_heatmap.py checks both agree.

Significance overlay (optional): a ring marks the best tool of each column (within an analysis task; ties in value share it); a dot marks a
tool declared equivalent to the best (benchmark.paired_comparisons.tsv, equivalent == yes, for the columns whose metric was tested).
Failing to find a difference (Holm p >= 0.05) is not equivalence and is not marked; the tooltip quotes the p-value.

Limits: the demo data are synthetic and flat; NGOC / collinear fraction (C1) is alignment-derived and unvalidated.

Standard library only.
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import report_common as rc  # noqa: E402
import report_scorecard as rs  # noqa: E402
import report_svg as sv  # noqa: E402

SECTION_ID = "fig-heatmap"
TITLE = "Performance of every tool across every metric"
ASSETS = ("fig_heatmap_style.html", "fig_heatmap_core.html", "fig_heatmap_ui.html")
MAX_SAMPLES_DRILL = 80

FAMILIES = [("A", "Accuracy"), ("B", "Completeness"), ("C", "Structure"), ("D", "Function"), ("E", "Performance"), ("L", "Leaderboard")]
FAMILY_TINT = {"A": "#cfe6f5", "B": "#cfeadd", "C": "#f6e0b8", "D": "#ead7e4", "E": "#dedede", "L": "#e6e6c8"}

SHORT = {"A1": "Identity", "A2": "Mismatch rate", "A3": "Indel accuracy", "A4": "SNP concordance", "B1": "Ref. coverage",
         "B2": "Completeness", "B3": "Recovery rate", "C1": "Structure (NGOC)", "C2": "SV F1", "C3": "Circularised",
         "C4": "Repeat resolution", "D1": "Gene recovery", "D2": "Annotation", "D3": "Functional elem.", "E1": "Runtime",
         "E2": "Memory", "E3": "Success rate",
         "F1": "F1", "MCC": "MCC", "BF1": "Binning F1", "LWB": "LW binning F1", "ARI": "ARI", "CPRR": "CPRR", "CF1": "Contig F1"}

# leaderboard metric id -> (label, leaderboard column, scores.tsv column or None, definition)
LEADERBOARD = [
    ("F1", "F1", "mean_f1", "f1", "Mean over isolates of the base-pair F1 of the predicted plasmid sequence against the truth plasmids (leaderboard column mean_f1)."),
    ("MCC", "MCC", "mean_mcc", "mcc", "Mean over isolates of the Matthews correlation coefficient of the base-level plasmid / not-plasmid call (mean_mcc; ranges -1 to 1)."),
    ("BF1", "Binning F1", "mean_bin_f1", "bin_f1", "Mean over isolates of the bin-level F1 of predicted bins against truth plasmids (mean_bin_f1); only tools that output bins."),
    ("LWB", "Length-weighted binning F1", "mean_lw_bin_f1", "lw_bin_f1", "Length-weighted bin F1 (mean_lw_bin_f1); only tools that output bins."),
    ("ARI", "Adjusted Rand index of the binning", "mean_bin_ari", "bin_ari", "Mean over isolates of the adjusted Rand index between predicted bins and truth plasmids (mean_bin_ari); only tools that output bins."),
    ("CPRR", "Complete plasmid reconstruction rate", "cprr", None, "Share of truth plasmids reconstructed correctly, pooled over isolates (leaderboard column cprr); see the scoring specification for the exact definition."),
    ("CF1", "Contig-level F1", "mean_contig_f1_count", "contig_f1_count", "Mean over isolates of the contig-level F1 (counts) of the plasmid / chromosome call on assembly contigs; only for assembly-contig tools."),
]
COMPARISON_METRIC = {"f1": "F1", "mcc": "MCC", "bin_f1": "BF1", "lw_bin_f1": "LWB", "ari": "ARI", "bin_ari": "ARI", "cprr": "CPRR"}
UNVALIDATED = {"C1"}

# colour scales (10 stops each, t = 0 worst .. 1 best); the CVD palette toggle swaps viridis for cividis
VIRIDIS = ["#440154", "#482878", "#3e4989", "#31688e", "#26828e", "#1f9e89", "#35b779", "#6ece58", "#b5de2b", "#fde725"]
CIVIDIS = ["#00224e", "#123570", "#3b496c", "#575d6d", "#707173", "#8a8678", "#a69d75", "#c4b56e", "#e4cf5b", "#fee838"]
DIVERGING = ["#D55E00", "#f7f7f7", "#0072B2"]   # worse, neutral, better (Okabe-Ito vermillion and blue)

# geometry shared with the browser renderer
CELL_W, CELL_H, PAD = 40, 30, 8
ROW_LABEL_W, ROW_DENDRO_W, COL_DENDRO_H, COL_LABEL_H, STRIP_H, FAM_GAP, TITLE_H, LEGEND_H = 150, 56, 50, 118, 16, 8, 22, 40
EPS = 1e-12


# ------------------------------------------------------------------------------------------------ colour helpers
def _hex_rgb(h):
    return [int(h[i:i + 2], 16) for i in (1, 3, 5)]


def ramp(stops, t):
    """Linear interpolation through evenly spaced hex stops; t clamped to [0, 1]. Returns '#rrggbb'."""
    t = 0.0 if t != t else max(0.0, min(1.0, t))
    pos = t * (len(stops) - 1)
    i = min(int(pos), len(stops) - 2)
    f = pos - i
    a, b = _hex_rgb(stops[i]), _hex_rgb(stops[i + 1])
    return "#" + "".join(f"{int(math.floor(a[k] + (b[k] - a[k]) * f + 0.5)):02x}" for k in range(3))


def colour_for(mode, t, palette="default"):
    stops = DIVERGING if mode == "z" else (CIVIDIS if palette == "cvd" else VIRIDIS)
    return ramp(stops, t)


def text_on(hexcolour):
    """'#ffffff' or '#111111', whichever contrasts more with the fill (WCAG relative luminance)."""
    def lin(c):
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = _hex_rgb(hexcolour)
    lum = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
    return "#111111" if (lum + 0.05) / 0.05 >= 1.05 / (lum + 0.05) else "#ffffff"


# ------------------------------------------------------------------------------------------------ display transforms
def avg_ranks(vals, higher=True):
    """Average ranks (1 = best) of the non-None entries; None stays None. Entries within 1e-12 are tied."""
    idx = [i for i, v in enumerate(vals) if v is not None]
    key = (lambda i: -vals[i]) if higher else (lambda i: vals[i])
    idx.sort(key=key)
    out = [None] * len(vals)
    pos = 0
    while pos < len(idx):
        end = pos
        while end + 1 < len(idx) and abs(vals[idx[end + 1]] - vals[idx[pos]]) <= EPS:
            end += 1
        rank = (pos + end) / 2.0 + 1.0
        for k in range(pos, end + 1):
            out[idx[k]] = rank
        pos = end + 1
    return out


def column_view(mode, higher, values, scores):
    """Per-row [(t, shown, flat)] for one column of one block; (None, None, False) is not available in this mode."""
    n = len(values)
    out = [(None, None, False)] * n
    ok = [i for i in range(n) if values[i] is not None]
    if mode == "raw":
        if not ok:
            return out
        lo, hi = min(values[i] for i in ok), max(values[i] for i in ok)
        for i in ok:
            if hi - lo <= EPS:
                out[i] = (0.5, values[i], True)
            else:
                out[i] = (((values[i] - lo) if higher else (hi - values[i])) / (hi - lo), values[i], False)
    elif mode == "score":
        for i in range(n):
            if scores[i] is not None:
                out[i] = (scores[i] / 100.0, scores[i], False)
    elif mode == "rank":
        ranks = avg_ranks(values, higher)
        m = len(ok)
        for i in ok:
            out[i] = ((0.5, ranks[i], True) if m < 2 else ((m - ranks[i]) / (m - 1.0), ranks[i], False))
    elif mode == "z":
        if len(ok) >= 2:
            mean = sum(values[i] for i in ok) / len(ok)
            sd = math.sqrt(sum((values[i] - mean) ** 2 for i in ok) / len(ok))
            for i in ok:
                z = 0.0 if sd <= EPS else (values[i] - mean) / sd * (1 if higher else -1)
                out[i] = ((max(-2.0, min(2.0, z)) + 2.0) / 4.0, z, sd <= EPS)
    return out


def matrix_view(block, cols, mode):
    """[row][col] -> (t, shown, flat) for the given column list (dicts with id/dir)."""
    n = len(block["rows"])
    grid = [[None] * len(cols) for _ in range(n)]
    for j, col in enumerate(cols):
        j0 = col["_i"]
        vals = [block["cells"][i][j0][0] for i in range(n)]
        scs = [block["cells"][i][j0][1] for i in range(n)]
        for i, cell in enumerate(column_view(mode, col["dir"] == "higher", vals, scs)):
            grid[i][j] = cell
    return grid


# ------------------------------------------------------------------------------------------------ clustering
def _rms(a, b, need):
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pairs) < need:
        return None
    s = 0.0
    for x, y in pairs:
        s += (x - y) * (x - y)
    return math.sqrt(s / len(pairs))


def cluster(dist):
    """Average-linkage tree of n items from a symmetric matrix with None for undefined.

    Returns {'order': leaf indices, 'merges': [[a, b, height, size], ...]}; a merge creates id n + k."""
    n = len(dist)
    if n == 0:
        return {"order": [], "merges": []}
    defined = [dist[i][j] for i in range(n) for j in range(i + 1, n) if dist[i][j] is not None]
    fill = max(defined) if defined else 1.0
    d = {(i, j): (fill if dist[i][j] is None else dist[i][j]) for i in range(n) for j in range(i + 1, n)}
    ids, size, merges, nxt = list(range(n)), {i: 1 for i in range(n)}, [], n
    key = lambda x, y: (x, y) if x < y else (y, x)  # noqa: E731
    while len(ids) > 1:
        best = None
        for ai in range(len(ids)):
            for bi in range(ai + 1, len(ids)):
                v = d[(ids[ai], ids[bi])]
                if best is None or v < best[0]:
                    best = (v, ids[ai], ids[bi])
        v, a, b = best
        for k in ids:
            if k != a and k != b:
                d[(k, nxt)] = (size[a] * d[key(a, k)] + size[b] * d[key(b, k)]) / (size[a] + size[b])
        size[nxt] = size[a] + size[b]
        ids = [k for k in ids if k != a and k != b] + [nxt]
        merges.append([a, b, v, size[nxt]])
        nxt += 1
    kids = {n + k: (m[0], m[1]) for k, m in enumerate(merges)}
    order, stack = [], [ids[0]]
    while stack:
        node = stack.pop()
        if node in kids:
            stack.append(kids[node][1])
            stack.append(kids[node][0])
        else:
            order.append(node)
    return {"order": order, "merges": merges}


def cluster_axis(grid, axis):
    """Order of rows (axis 0) or columns (axis 1) of a t-matrix with None gaps, plus the tree over the eligible items.

    Returns (order of all items, eligible list, tree over eligible positions)."""
    rows, cols = len(grid), (len(grid[0]) if grid else 0)
    vec = ([[grid[i][j][0] if grid[i][j] else None for j in range(cols)] for i in range(rows)] if axis == 0
           else [[grid[i][j][0] if grid[i][j] else None for i in range(rows)] for j in range(cols)])
    need = 1 if axis == 0 else 2
    elig = [i for i, v in enumerate(vec) if sum(1 for x in v if x is not None) >= need]
    rest = [i for i in range(len(vec)) if i not in elig]
    sub = [[None if p == q else _rms(vec[elig[p]], vec[elig[q]], need if axis == 0 else 2) for q in range(len(elig))]
           for p in range(len(elig))]
    tree = cluster(sub)
    return [elig[p] for p in tree["order"]] + rest, elig, tree


def dendrogram_segments(tree):
    """Polylines of a dendrogram in unit coordinates: [[(leaf position, height 0..1), ...], ...]. Position = index in the leaf order."""
    n = len(tree["order"])
    if n < 2:
        return []
    pos = {leaf: p for p, leaf in enumerate(tree["order"])}
    height = {leaf: 0.0 for leaf in pos}
    top = max(m[2] for m in tree["merges"]) or 1.0
    segs = []
    for k, (a, b, h, _) in enumerate(tree["merges"]):
        node = n + k
        pos[node] = (pos[a] + pos[b]) / 2.0
        height[node] = h / top
        segs.append([(pos[a], height[a]), (pos[a], height[node]), (pos[b], height[node]), (pos[b], height[b])])
    return segs


# ------------------------------------------------------------------------------------------------ data
def _r(v, d=6):
    return None if v is None else round(v, d)


def _resolve_dir(results_dir, data_dir):
    for d in (results_dir, data_dir):
        if d and os.path.isfile(os.path.join(d, "benchmark.leaderboard.tsv")):
            return d
    for d in (results_dir, data_dir):
        if d and os.path.isdir(d):
            return d
    return results_dir


def _columns(specs):
    cols = []
    for s in specs:
        bands = None if s["excellent"] is None else {k: s[k] for k in ("excellent", "good", "moderate", "floor")}
        digits = 0 if s["unit"] == "seconds" else (2 if s["unit"] in ("percent", "GB") else 3)
        cols.append({"id": s["id"], "short": SHORT.get(s["id"], s["id"] + " " + s["name"][:14]), "name": s["name"], "fam": s["group"],
                     "dir": s["direction"], "unit": s["unit"], "status": s["status"], "bands": bands, "weight": s["weight"],
                     "digits": digits, "src": "scorecard", "unval": s["id"] in UNVALIDATED, "def": s.get("rationale", "")})
    for cid, name, column, _scores_col, definition in LEADERBOARD:
        cols.append({"id": cid, "short": SHORT[cid], "name": name, "fam": "L", "dir": "higher", "unit": "fraction" if cid != "MCC" else "-1 to 1",
                     "status": "", "bands": None, "weight": None, "digits": 3, "src": "leaderboard", "unval": False, "def": definition,
                     "lbcol": column})
    return cols


def _per_sample(inp, specs, samples, per_tool):
    """{(track, tool): {metric id: [value per sample or None]}} from the scorecard functions run on one isolate at a time."""
    out = {}
    by_sample = {s: rs.metric_values(inp.dir, None, samples={s}, inputs=inp) for s in samples}
    for key in per_tool:
        entry = {}
        for spec in specs:
            vals = [((by_sample[s].get(key) or {}).get(spec["id"]) or {}).get("value") for s in samples]
            entry[spec["id"]] = vals
        out[key] = entry
    return out


def _leaderboard_per_sample(inp, key, samples, cid):
    scols = {c[0]: c[3] for c in LEADERBOARD}
    rows = {r.get("sample"): r for r in (inp.scores or []) if r.get("tool") == key[1] and rs._track(r) == key[0]}
    vals = []
    for s in samples:
        r = rows.get(s)
        if r is None:
            vals.append(None)
        elif cid == "CPRR":
            plasmids = rc.number(r.get("cprr_plasmids"))
            correct = rc.number(r.get("cprr_correct"))
            vals.append(None if not plasmids or correct is None else correct / plasmids)
        else:
            vals.append(rc.number(r.get(scols[cid])))
    return vals


def _comparisons(d):
    rows = rc.read_tsv(os.path.join(d, "benchmark.paired_comparisons.tsv"))
    return rows


def _significance(block_rows, cells, cols, track, comps):
    """{col id: {'best': [row idx], 'tied': [row idx], 'info': {row idx: text}, 'tested': bool}} (rings for every column; dots only where tested)."""
    sig = {}
    groups = {}
    for i, r in enumerate(block_rows):
        groups.setdefault(r.get("task") or "", []).append(i)
    pair_lookup = {}
    for c in comps or []:
        if (c.get("analysis_track") or "short_read") != track:
            continue
        pair_lookup.setdefault((c.get("task") or "", COMPARISON_METRIC.get((c.get("metric") or "").lower())), []).append(c)
    for j, col in enumerate(cols):
        higher = col["dir"] == "higher"
        entry = {"best": [], "tied": [], "info": {}, "tested": False}
        for task, idxs in groups.items():
            valid = [i for i in idxs if cells[i][j][0] is not None]
            if not valid:
                continue
            target = (max if higher else min)(cells[i][j][0] for i in valid)
            best = [i for i in valid if abs(cells[i][j][0] - target) <= EPS]
            entry["best"].extend(best)
            pairs = pair_lookup.get((task, col["id"]))
            if not pairs:
                continue
            entry["tested"] = True
            tools = {block_rows[i]["tool"]: i for i in idxs}
            best_tools = {block_rows[i]["tool"] for i in best}
            for i in valid:
                if i in best:
                    continue
                note = None
                for p in pairs:
                    a, b = p.get("tool_a"), p.get("tool_b")
                    other = b if a == block_rows[i]["tool"] else (a if b == block_rows[i]["tool"] else None)
                    if other in best_tools and other in tools:
                        holm = rc.number(p.get("wilcoxon_p_value_holm")) if p.get("wilcoxon_p_value_holm") not in (None, "") \
                            else rc.number(p.get("permutation_p_value_holm"))
                        eq = (p.get("equivalent") or "").strip().lower()
                        delta = p.get("smallest_difference") or ""
                        note = (f"versus the best ({block_rows[tools[other]]['label']}): Holm p = "
                                f"{'n/a' if holm is None else format(holm, '.4g')}; equivalent within {delta or 'the margin'}: {eq or 'not assessed'}")
                        if eq == "yes":
                            entry["tied"].append(i)
                        break
                entry["info"][i] = note or "no paired test of this pair is recorded"
        sig[col["id"]] = entry
    return sig


def build(results_dir, data_dir, scores_path):
    """The figure's data, or ValueError('reason') when it cannot be built."""
    try:
        specs = rs.load_config()
    except ValueError as exc:
        raise ValueError(f"the scorecard configuration is invalid ({exc})")
    d = _resolve_dir(results_dir, data_dir)
    inp = rs.Inputs(d, scores_path)
    if not inp.scores:
        raise ValueError("scores.tsv is absent or empty, so no tool was scored.")
    per_tool = rs.metric_values(d, scores_path, inputs=inp)
    if not per_tool:
        raise ValueError("scores.tsv names no tool.")
    lb_rows = rc.read_tsv(os.path.join(d, "benchmark.leaderboard.tsv")) or []
    comps = _comparisons(d)
    cols = _columns(specs)
    samples = sorted({r.get("sample") for r in inp.scores if r.get("sample")})
    drill = len(samples) <= MAX_SAMPLES_DRILL
    sample_vals = _per_sample(inp, specs, samples, per_tool) if drill else {}
    lb = {}
    for r in lb_rows:
        lb.setdefault((rs._track(r), r.get("tool")), r)
    keys = sorted(set(per_tool) | set(lb))
    try:
        from plasbench_common import display_tool_name
    except ImportError:                               # pragma: no cover
        display_tool_name = lambda t: t               # noqa: E731
    blocks = []
    for track in sorted({k[0] for k in keys}):
        tkeys = [k for k in keys if k[0] == track]
        overall = {k: rs.overall(specs, per_tool[k]) for k in tkeys if k in per_tool}
        tkeys.sort(key=lambda k: (k not in overall or overall[k]["score"] is None, -((overall.get(k) or {}).get("score") or 0), k[1]))
        rows, cells, ps = [], [], []
        for k in tkeys:
            lrow = lb.get(k) or {}
            ov = overall.get(k)
            rows.append({"id": f"{k[0]}|{k[1]}", "tool": k[1], "label": display_tool_name(k[1]), "task": lrow.get("task") or "",
                         "nsamples": int(rc.number(lrow.get("n_samples")) or 0) or None, "overall": _r(ov["score"], 1) if ov else None,
                         "share": _r(ov["scored_share"], 3) if ov else None})
            line, pline = [], []
            for col in cols:
                if col["src"] == "scorecard":
                    spec = next(s for s in specs if s["id"] == col["id"])
                    ent = (per_tool.get(k) or {}).get(col["id"]) or {"value": None, "reason": "this tool has no scored isolate in scores.tsv"}
                    v = ent.get("value")
                    sc, band = rs.score_value(spec, v)
                    line.append([_r(v), _r(sc, 2), band, "" if v is not None else (ent.get("reason") or "no data"), ent.get("n") or 0])
                    pline.append(sample_vals.get(k, {}).get(col["id"]) if drill else None)
                else:
                    v = rc.number(lrow.get(col["lbcol"])) if lrow else None
                    why = "" if v is not None else ("this tool is not in benchmark.leaderboard.tsv" if not lrow else
                                                    f"blank in the leaderboard (undefined for this tool, not zero): {col['lbcol']}")
                    line.append([_r(v), None, None, why, int(rc.number(lrow.get("n_samples")) or 0) if lrow else 0])
                    pline.append(_leaderboard_per_sample(inp, k, samples, col["id"]) if drill and k in per_tool else None)
            cells.append(line)
            ps.append([[(_r(x) if x is not None else None) for x in p] if p and any(x is not None for x in p) else None for p in pline])
        block = {"track": track, "rows": rows, "cells": cells, "ps": ps if drill else None}
        block["sig"] = _significance(rows, cells, cols, track, comps) if comps is not None else None
        blocks.append(block)
    return {"cols": cols, "fams": [list(f) for f in FAMILIES], "blocks": blocks, "samples": samples if drill else [],
            "notes": {"drill": drill, "comparisons": comps is not None, "palette": {"viridis": VIRIDIS, "cividis": CIVIDIS, "diverging": DIVERGING}},
            "dir": d}


# ------------------------------------------------------------------------------------------------ static SVG (default view)
def fmt_value(col, v):
    if v is None:
        return ""
    return f"{v:.{col['digits']}f}"


def fmt_shown(mode, col, shown):
    if mode == "raw":
        return fmt_value(col, shown)
    if mode == "score":
        return f"{shown:.0f}"
    if mode == "rank":
        return f"{shown:g}" if abs(shown - round(shown)) < 1e-9 else f"{shown:.1f}"
    z = round(shown, 1)
    return "0.0" if z == 0 else f"{z:+.1f}"


def _esc(s):
    return sv.esc(s)


def layout_columns(order, cols, cluster_on, visible):
    """x offsets of the visible columns: with clustering off, families are separated by a gap."""
    xs, x, prev = {}, 0, None
    for j in order:
        if not visible[j]:
            continue
        if not cluster_on and prev is not None and cols[j]["fam"] != prev:
            x += FAM_GAP
        xs[j] = x
        x += CELL_W
        prev = cols[j]["fam"]
    return xs, x


def render_block_svg(block, cols, mode="raw", cluster_on=True, uid="hm0", palette="default", hidden_fams=(), overlay=False):
    """The default-view heatmap of one block as a self-contained SVG string (attributes only, no CSS), with dendrograms."""
    for i, c in enumerate(cols):
        c["_i"] = i
    visible = [c["fam"] not in hidden_fams for c in cols]
    vcols = [c for c, v in zip(cols, visible) if v]
    n = len(block["rows"])
    grid = matrix_view(block, vcols, mode)
    if cluster_on:
        row_order, _, row_tree = cluster_axis(grid, 0)
        col_order_v, _, col_tree = cluster_axis(grid, 1)
    else:
        row_order, col_order_v, row_tree, col_tree = list(range(n)), list(range(len(vcols))), {"order": [], "merges": []}, {"order": [], "merges": []}
    vidx = [j for j, v in enumerate(visible) if v]
    col_order = [vidx[p] for p in col_order_v]
    xs, grid_w = layout_columns(col_order, cols, cluster_on, visible)
    xd = PAD + (ROW_DENDRO_W if cluster_on else 0)
    x0 = xd + ROW_LABEL_W
    y_top = TITLE_H + (COL_DENDRO_H if cluster_on else 0)
    y0 = y_top + STRIP_H
    width = x0 + grid_w + PAD
    height = y0 + n * CELL_H + COL_LABEL_H + LEGEND_H
    title = f"Heatmap of {n} tools by {len(vcols)} metrics, analysis track {block['track']}"
    parts = [f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {width} {height}' width='{width}' height='{height}' role='img' "
             f"aria-labelledby='{uid}-t {uid}-d' font-family='Arial,Helvetica,sans-serif'>"
             f"<title id='{uid}-t'>{_esc(title)}</title>"
             f"<desc id='{uid}-d'>Rows are tools, columns are metrics grouped by family. Mode {_esc(mode)}; clustering "
             f"{'on (average linkage)' if cluster_on else 'off (scorecard order)'}. Hatched cells are not available.</desc>"
             f"<defs><pattern id='{uid}-hatch' width='6' height='6' patternUnits='userSpaceOnUse' patternTransform='rotate(45)'>"
             f"<rect width='6' height='6' fill='#f4f4f0'/><line x1='0' y1='0' x2='0' y2='6' stroke='#8a8a84' stroke-width='1.6'/></pattern>"
             f"<linearGradient id='{uid}-grad' x1='0' x2='1' y1='0' y2='0'>"
             + "".join(f"<stop offset='{k / 10:g}' stop-color='{colour_for(mode, k / 10, palette)}'/>" for k in range(11))
             + "</linearGradient></defs>"]
    parts.append(f"<text x='{PAD}' y='14' font-size='12' font-weight='bold' fill='#17231d'>{_esc('Analysis track: ' + block['track'])}</text>")
    # column dendrogram (top) and row dendrogram (left)
    if cluster_on:
        for seg in dendrogram_segments(col_tree):
            pts = " ".join(f"{sv.num(x0 + _interp_x(xs, col_order, p), 2)},{sv.num(y_top - 2 - h * (COL_DENDRO_H - 6), 2)}" for p, h in seg)
            parts.append(f"<polyline points='{pts}' fill='none' stroke='#6c7a72' stroke-width='1'/>")
        for seg in dendrogram_segments(row_tree):
            pts = " ".join(f"{sv.num(xd - 2 - h * (ROW_DENDRO_W - 6), 2)},{sv.num(y0 + p * CELL_H + CELL_H / 2, 2)}" for p, h in seg)
            parts.append(f"<polyline points='{pts}' fill='none' stroke='#6c7a72' stroke-width='1'/>")
    # family strip and column labels
    for pos, j in enumerate(col_order):
        c = cols[j]
        x = x0 + xs[j]
        parts.append(f"<rect x='{x}' y='{y_top}' width='{CELL_W}' height='{STRIP_H - 2}' fill='{FAMILY_TINT[c['fam']]}' stroke='#fff'/>"
                     f"<text x='{x + CELL_W / 2}' y='{y_top + STRIP_H - 5}' font-size='10' text-anchor='middle' fill='#17231d'>{_esc(c['fam'])}</text>")
        mark = (" ▼" if c["dir"] == "lower" else "") + (" †" if c["unval"] else "")
        parts.append(f"<text transform='translate({x + CELL_W / 2 + 4},{y0 + n * CELL_H + 8}) rotate(90)' font-size='11' fill='#17231d'>"
                     f"{_esc((c['id'] if c['id'] == c['short'] else c['id'] + ' ' + c['short']) + mark)}</text>")
    # cells
    for rpos, i in enumerate(row_order):
        y = y0 + rpos * CELL_H
        parts.append(f"<text x='{x0 - 8}' y='{y + CELL_H / 2 + 4}' font-size='12' text-anchor='end' fill='#17231d'>{_esc(block['rows'][i]['label'])}</text>")
        for vpos, j in enumerate(col_order):
            c = cols[j]
            t, shown, flat = grid[i][col_order_v[vpos]] if grid[i][col_order_v[vpos]] else (None, None, False)
            x = x0 + xs[j]
            if t is None:
                parts.append(f"<rect x='{x}' y='{y}' width='{CELL_W}' height='{CELL_H}' fill='url(#{uid}-hatch)' stroke='#fff'>"
                             f"<title>{_esc(block['rows'][i]['label'] + ', ' + c['id'] + ': not available')}</title></rect>")
            else:
                fill = colour_for(mode, t, palette)
                parts.append(f"<rect x='{x}' y='{y}' width='{CELL_W}' height='{CELL_H}' fill='{fill}' stroke='#fff'>"
                             f"<title>{_esc(block['rows'][i]['label'] + ', ' + c['id'] + ' ' + c['name'] + ': ' + fmt_value(c, block['cells'][i][j][0]))}</title></rect>"
                             f"<text x='{x + CELL_W / 2}' y='{y + CELL_H / 2 + 4}' font-size='10.5' text-anchor='middle' fill='{text_on(fill)}'>"
                             f"{_esc(fmt_shown(mode, c, shown))}</text>")
    # legend
    ly = y0 + n * CELL_H + COL_LABEL_H + 8
    parts.append(f"<rect x='{x0}' y='{ly}' width='140' height='10' fill='url(#{uid}-grad)' stroke='#8a8a84'/>"
                 f"<text x='{x0}' y='{ly + 23}' font-size='10' fill='#17231d'>worse</text>"
                 f"<text x='{x0 + 140}' y='{ly + 23}' font-size='10' text-anchor='end' fill='#17231d'>better</text>"
                 f"<rect x='{x0 + 170}' y='{ly}' width='14' height='10' fill='url(#{uid}-hatch)' stroke='#8a8a84'/>"
                 f"<text x='{x0 + 190}' y='{ly + 9}' font-size='10' fill='#17231d'>not available</text>"
                 f"<text x='{x0 + 280}' y='{ly + 9}' font-size='10' fill='#17231d'>▼ lower is better (colour flipped)   "
                 f"† alignment-derived, unvalidated   family letters A-E scorecard, L leaderboard</text>")
    parts.append("</svg>")
    return "".join(parts)


def _interp_x(xs, col_order, p):
    lo = int(math.floor(p))
    hi = min(lo + 1, len(col_order) - 1)
    f = p - lo
    a = xs[col_order[lo]] + CELL_W / 2
    b = xs[col_order[hi]] + CELL_W / 2
    return a + (b - a) * f


# ------------------------------------------------------------------------------------------------ section
LEAD = ("Rows are tools (one block per analysis track, never pooled across tracks); columns are the scorecard metrics A1-E3 and the "
        "leaderboard metrics, grouped by family. Each cell shows the value and is coloured so that the bright end is always good: "
        "lower-is-better metrics (marked with a down triangle) are flipped. Raw colours are relative within a column, so a flat column is "
        "neutral; Score colours are absolute (the scorecard 0-100 transform and its bands, mostly <em>proposed</em>, not standards); Rank and "
        "Z-score compare tools inside a track. Hatched cells are not available (the reason is on hover), never zero. Rows and columns can "
        "be clustered (average linkage on the colour values, dendrograms at the margins) or left in scorecard order. Click a cell for the "
        "per-isolate values and the definition; the ring and dot overlay marks the best tool and tools declared equivalent to it. The "
        "structure metric C1 is alignment-derived and unvalidated, and the demo data are synthetic and flat: read the layout, not the biology.")


def inject(page, results_dir, data_dir, scores_path):
    try:
        data = build(results_dir, data_dir, scores_path)
    except ValueError as exc:
        body = rc.not_run(str(exc))
        return rc.inject_sections(page, rc.section(SECTION_ID, TITLE, LEAD, body, group="Figures"), [(SECTION_ID, "Tool heatmap")])
    page = rc.add_style(page)
    body = host_html(data) + assets()
    return rc.inject_sections(page, rc.section(SECTION_ID, TITLE, LEAD, rc.Raw(body), group="Figures"), [(SECTION_ID, "Tool heatmap")])


def payload_json(data):
    payload = {k: v for k, v in data.items() if k != "dir"}
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def host_html(data):
    statics = "".join(f"<div class='hm-static-block'>{render_block_svg(b, data['cols'], uid=f'hm-s{k}')}</div>"
                      for k, b in enumerate(data["blocks"]))
    note = ("<p class='hm-static-note'>Static view of the default setting (raw values, rows and columns clustered). With JavaScript on, this becomes an "
            "interactive heatmap with a setup panel, tooltips, drilldown and export.</p>")
    return (f"<div class='hm' id='hm-root' data-hm='1'><div class='hm-static'>{statics}{note}</div><div class='hm-live' hidden></div></div>"
            f"<script type='application/json' id='hm-data'>{payload_json(data)}</script>")


def assets():
    root = os.path.join(HERE, "..", "assets", "report")
    out = []
    for name in ASSETS:
        with open(os.path.join(root, name), encoding="utf-8", newline="") as handle:
            out.append(handle.read())
    return "".join(out)
