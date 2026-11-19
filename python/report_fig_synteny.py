#!/usr/bin/env python3
"""
report_fig_synteny.py -- the redesigned synteny view (section learn-synteny): one comparison at a time, truth plasmid on top, one tool's records below.

What it shows. results/<sample>/visualization/alignment_blocks.json (build_visualization_data.py) holds, for every tool, the retained primary alignment
blocks of its predicted records on each truth plasmid (record and plasmid coordinates, strand, matches, block length). A comparison is one
(sample, truth plasmid, tool). It is drawn as two aligned tracks on ONE bp scale with a kb ruler and a scale bar:

  top      the truth plasmid, with its annotated features (resistance genes, replicons) as ticks where the file has them
  bottom   the tool's records, left to right in the order they land on the plasmid, each as long as the record is (same scale), with a gap between records
  ribbon   one smooth band per alignment block from its stretch of plasmid to its stretch of record. A forward block is an untwisted orange band; a
           reverse block (the record is inverted) is a blue hatched band and is the only band that crosses itself, so a twist always means an inversion.
           Opacity is the identity of the block.

The old drawing stacked every tool under every plasmid, 1000 x ~700 px for a few tools, with straight-edged ribbons that crossed whenever records were
placed out of order. This one is at most 200 px tall per comparison, chooses the comparison with sample / plasmid / tool selectors, and does not
change anything that is scored (descriptive only; same data and the same ordering rule as report_synteny).

Static, no JavaScript and print: every comparison is a complete server-drawn SVG plus its alignment table, in a fold (the first one open). With
JavaScript (assets/report/fig_synteny_*.html) the selectors choose the comparison, hover or focus shows a tooltip, click / Enter opens the right-hand
panel (alignment table, definitions, the plasmid-map link), the plot zooms and pans (drag; Ctrl+wheel or wheel while focused; + - 0 and arrows), Escape closes.

Called from report_synteny.inject. Standard library only.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import report_synteny as old  # noqa: E402
from report_svg import esc, num  # noqa: E402
from pathlib import Path  # noqa: E402

SECTION_ID = old.SECTION_ID
FORWARD, REVERSE = old.FORWARD, old.REVERSE
W, H = 920, 200
X0, X1 = 74, 906                  # the plot area of every drawing
TRUTH_Y, TRUTH_H, RIB_TOP, RIB_BOT, REC_Y, REC_H = 30, 14, 48, 128, 128, 16
RULER_Y, BAR_Y = 20, 178
GAP = 6
MAX_PAIRS = 60
MAX_BLOCKS = 60
MAX_ZOOM = 12.0
FEATURE_COLOURS = {"amr": "#B3261E", "replicon": "#17805a"}
DEFAULT_FEATURE = "#555555"

LEAD = ("Coverage and identity do not show whether a plasmid was put back together in the right order and orientation. Choose a sample, a truth plasmid and a tool: "
        "the truth plasmid is the top track and the tool's records are the bottom track, on one scale. Each band joins a stretch of the plasmid to the stretch of a record "
        "that matches it. A forward block is an untwisted orange band; a reverse block (the record is inverted) is a blue hatched band and is the only one that crosses, so a "
        "twist always means an inversion. Opacity is the identity of the block. <strong>Descriptive; it changes no score.</strong> Hover or focus a band or record for its "
        "coordinates, click it (or press Enter) for the alignment table in the side panel, drag to pan, Ctrl+wheel (or +, - and 0 on the focused plot) to zoom.")


# ----------------------------------------------------------------------------------------------- pure helpers (mirrored in the script)
def zoom_at(view, base, fx, fy, factor, max_zoom=MAX_ZOOM):
    """New viewBox [x, y, w, h] after zooming by `factor` about the point (fx, fy); never wider than `base`, never more than `max_zoom` times in, and kept inside `base`."""
    bx, by, bw, bh = base
    w = min(bw, max(bw / max_zoom, view[2] / factor))
    h = w * bh / bw
    x = fx - (fx - view[0]) * (w / view[2])
    y = fy - (fy - view[1]) * (h / view[3])
    x = min(max(x, bx), bx + bw - w)
    y = min(max(y, by), by + bh - h)
    return [x, y, w, h]


def pan_by(view, base, dx, dy):
    """The viewBox moved by (dx, dy) and kept inside `base`."""
    x = min(max(view[0] + dx, base[0]), base[0] + base[2] - view[2])
    y = min(max(view[1] + dy, base[1]), base[1] + base[3] - view[3])
    return [x, y, view[2], view[3]]


def union_bp(intervals):
    """Bases covered by the union of [start, end) intervals (overlaps counted once)."""
    total, end = 0, None
    for a, b in sorted((int(a), int(b)) for a, b in intervals if b > a):
        if end is None or a > end:
            total += b - a
            end = b
        elif b > end:
            total += b - end
            end = b
    return total


def nice_step(length):
    """A ruler step in bp (1, 2 or 5 times a power of ten) giving about 5 to 10 ticks."""
    raw = max(length, 1) / 8.0
    mag = 10 ** (len(str(int(raw))) - 1) if raw >= 1 else 1
    for m in (1, 2, 5, 10):
        if m * mag >= raw:
            return m * mag
    return 10 * mag


def kb(value):
    return f"{value / 1000:.1f} kb" if value >= 1000 else f"{int(value)} bp"


def ident_text(block):
    ident = old.identity(block)
    return f"{ident * 100:.1f}%" if ident is not None else "n/a"


# ----------------------------------------------------------------------------------------------- model
def read_features(data, plasmid):
    out = []
    for key, kind in (("amr_features", "amr"), ("context_features", "other")):
        for f in (data.get(key) or []):
            try:
                if f.get("sequence_id") == plasmid and int(f["end"]) > int(f["start"]):
                    k = f.get("feature_type") or kind
                    out.append({"start": int(f["start"]), "end": int(f["end"]), "label": str(f.get("label") or f.get("gene") or k), "kind": str(k)})
            except (KeyError, TypeError, ValueError):
                continue
    return out[:80]


def load(results_dir):
    """-> list of pairs {sample, plasmid, length, tool, lane, features, key}; most structurally interesting first (reverse blocks, then records)."""
    pairs = []
    if not os.path.isdir(results_dir):
        return pairs
    for sample in sorted(d for d in os.listdir(results_dir) if os.path.isdir(os.path.join(results_dir, d))):
        data = old.read_json(os.path.join(results_dir, sample, "visualization", "alignment_blocks.json"))
        if not data:
            continue
        for plasmid, info in (data.get("truth_plasmids") or {}).items():
            try:
                length = int(info.get("length") or 0)
            except (TypeError, ValueError):
                length = 0
            if str(info.get("molecule_type", "PLASMID")).upper() != "PLASMID" or length <= 0:
                continue
            feats = read_features(data, plasmid)
            for tool, payload in sorted((data.get("tools") or {}).items()):
                lane = old.lane_model(tool, (payload or {}).get("blocks") or [], plasmid)
                if lane:
                    pairs.append({"sample": sample, "plasmid": plasmid, "length": length, "tool": tool, "lane": lane, "features": feats})
    pairs.sort(key=lambda p: (-p["lane"]["reverse"], -len(p["lane"]["records"]), p["sample"], p["plasmid"], p["tool"]))
    return pairs


# ----------------------------------------------------------------------------------------------- drawing
def ribbon_path(t0, t1, q0, q1, reverse):
    """A smooth band from the plasmid stretch [t0, t1] on the top track to the record stretch [q0, q1] on the bottom track. Reverse swaps the record ends (the one twist)."""
    qa, qb = (q1, q0) if reverse else (q0, q1)
    ym = (RIB_TOP + RIB_BOT) / 2.0
    return (f"M{num(t0, 1)},{RIB_TOP} C{num(t0, 1)},{num(ym, 1)} {num(qa, 1)},{num(ym, 1)} {num(qa, 1)},{RIB_BOT} "
            f"L{num(qb, 1)},{RIB_BOT} C{num(qb, 1)},{num(ym, 1)} {num(t1, 1)},{num(ym, 1)} {num(t1, 1)},{RIB_TOP} Z")


def layout(pair):
    """(scale px per bp, {record id: x}, records) with records left to right in plasmid order on the plasmid's own scale."""
    lane = pair["lane"]
    total = sum(r["length"] for r in lane["records"]) + GAP * max(len(lane["records"]) - 1, 0)
    scale = (X1 - X0) / float(max(pair["length"], total, 1))
    x, spans = X0, {}
    for r in lane["records"]:
        spans[r["id"]] = x
        x += max(r["length"] * scale, 2) + GAP
    return scale, spans


def pair_svg(pair, pid):
    lane, length = pair["lane"], pair["length"]
    scale, spans = layout(pair)
    px = lambda bp: X0 + bp * scale   # noqa: E731
    hatch = f"sxh{pid}"
    title = f"Synteny of {pair['tool']} on plasmid {pair['plasmid']} in {pair['sample']}"
    out = [f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {W} {H}' width='{W}' height='{H}' class='sx-svg' role='group' tabindex='0' "
           f"data-vb='0 0 {W} {H}' aria-label='{esc(title)}. Press plus or minus to zoom, arrow keys to pan, zero to reset.' preserveAspectRatio='xMidYMid meet'>"
           f"<title>{esc(title)}</title><defs><pattern id='{hatch}' width='5' height='5' patternUnits='userSpaceOnUse' patternTransform='rotate(45)'>"
           f"<line x1='0' y1='0' x2='0' y2='5' stroke='#ffffff' stroke-width='2' stroke-opacity='.75'/></pattern></defs>"]
    out.append("<text x='4' y='41' font-size='11' font-weight='bold' fill='currentColor' font-family='Arial,sans-serif'>Truth</text>")
    out.append(f"<text x='4' y='{REC_Y + 12}' font-size='11' font-weight='bold' fill='currentColor' font-family='Arial,sans-serif'>Tool</text>")
    step = nice_step(length)
    for v in range(0, length + 1, step):
        out.append(f"<line x1='{num(px(v))}' y1='{RULER_Y + 2}' x2='{num(px(v))}' y2='{TRUTH_Y}' stroke='#8a948d' stroke-width='.6'/>"
                   f"<text x='{num(px(v))}' y='{RULER_Y - 3}' font-size='9' text-anchor='middle' fill='currentColor' font-family='Arial,sans-serif'>{v / 1000:g}</text>")
    out.append(f"<text x='{X1 + 2}' y='{RULER_Y - 3}' font-size='9' fill='currentColor' font-family='Arial,sans-serif' text-anchor='end' dx='0'>kb</text>")
    out.append(f"<rect x='{X0}' y='{TRUTH_Y}' width='{num(length * scale)}' height='{TRUTH_H}' rx='2' fill='#8a948d' fill-opacity='.55' stroke='#555' stroke-width='.6'>"
               f"<title>{esc(pair['plasmid'])}, {kb(length)}</title></rect>")
    for f in pair["features"]:
        colour = FEATURE_COLOURS.get(f["kind"], DEFAULT_FEATURE)
        out.append(f"<rect x='{num(px(f['start']))}' y='{TRUTH_Y + TRUTH_H}' width='{num(max((f['end'] - f['start']) * scale, 1.5))}' height='5' fill='{colour}'>"
                   f"<title>{esc(f['label'])} ({esc(f['kind'])}) {f['start']}-{f['end']}</title></rect>")
    shown = sorted((b for b in lane["blocks"] if id(b) in lane["shown"]), key=lambda b: -(b["block_length"] or 0))[:MAX_BLOCKS]
    index = {id(b): i for i, b in enumerate(sorted(lane["blocks"], key=lambda b: (b["target_start"], b["record_id"], b["query_start"])))}
    for r in lane["records"]:
        x = spans[r["id"]]
        w = max(r["length"] * scale, 2)
        covered = union_bp((b["query_start"], b["query_end"]) for b in r["blocks"])
        rev = sum(1 for b in r["blocks"] if b.get("strand") == "-")
        tip = (f"Record {r['id']}\n{kb(r['length'])}, {len(r['blocks'])} aligned block(s) on this plasmid ({rev} reverse)\n"
               f"{covered / max(r['length'], 1) * 100:.0f}% of the record aligns here")
        label = r["id"] if w > 8 * len(r["id"][:12]) * 0.62 + 6 else ""
        out.append(f"<g class='sx-rec' tabindex='0' role='button' data-r='{esc(r['id'])}'>"
                   f"<title>{esc(tip)}</title><rect class='sx-sh' x='{num(x)}' y='{REC_Y}' width='{num(w)}' height='{REC_H}' rx='2' fill='#c9cfc9' stroke='#555' stroke-width='.7'/>"
                   + (f"<text x='{num(x + w / 2)}' y='{REC_Y + 11.5}' font-size='9' text-anchor='middle' fill='#17231d' pointer-events='none' "
                      f"font-family='Arial,sans-serif'>{esc(r['id'][:12])}</text>" if label else "") + "</g>")
    for b in shown:
        rev = b.get("strand") == "-"
        x = spans[b["record_id"]]
        t0, t1 = px(b["target_start"]), px(b["target_end"])
        q0, q1 = x + b["query_start"] * scale, x + b["query_end"] * scale
        ident = old.identity(b)
        op = old.opacity(ident)
        d = ribbon_path(t0, t1, q0, q1, rev)
        blen = b["target_end"] - b["target_start"]
        tip = (f"{lane['tool']}: {'reverse (inverted)' if rev else 'forward'} block of {b['record_id']}\nplasmid {b['target_start']}-{b['target_end']} ({kb(blen)}, "
               f"{blen / length * 100:.1f}% of the plasmid)\nrecord {b['query_start']}-{b['query_end']}\nidentity {ident_text(b)}, mapq {b.get('mapq', 'n/a')}")
        out.append(f"<g class='sx-rib' tabindex='0' role='button' data-b='{index[id(b)]}' data-r='{esc(b['record_id'])}'>"
                   f"<title>{esc(tip)}</title><path class='sx-sh' d='{d}' fill='{REVERSE if rev else FORWARD}' fill-opacity='{op}' "
                   f"stroke='{REVERSE if rev else FORWARD}' stroke-width='.8' stroke-opacity='.9'/>"
                   + (f"<path d='{d}' fill='url(#{hatch})' pointer-events='none'/>" if rev else "") + "</g>")
    bar = nice_step(length) if length > 0 else 1000
    out.append(f"<line x1='{X0}' y1='{BAR_Y}' x2='{num(X0 + bar * scale)}' y2='{BAR_Y}' stroke='currentColor' stroke-width='2'/>"
               f"<text x='{num(X0 + bar * scale + 6)}' y='{BAR_Y + 4}' font-size='10' fill='currentColor' font-family='Arial,sans-serif'>{kb(bar)}</text>")
    if lane["omitted"] or len(shown) < len(lane["blocks"]):
        left = len(lane["blocks"]) - len(shown)
        out.append(f"<text x='{X1}' y='{BAR_Y + 4}' font-size='9' text-anchor='end' fill='currentColor' font-family='Arial,sans-serif'>{left} smaller block(s) not drawn (listed in the table)</text>")
    out.append("</svg>")
    return "".join(out)


def alignment_table(pair):
    lane, length = pair["lane"], pair["length"]
    blocks = sorted(lane["blocks"], key=lambda b: (b["target_start"], b["record_id"], b["query_start"]))
    rows = "".join(
        f"<tr data-b='{i}'><td>{esc(b['record_id'])}</td><td>{b['target_start']}-{b['target_end']}</td><td>{b['query_start']}-{b['query_end']}</td>"
        f"<td>{kb(b['target_end'] - b['target_start'])}</td><td>{'reverse' if b.get('strand') == '-' else 'forward'}</td><td>{ident_text(b)}</td>"
        f"<td>{(b['target_end'] - b['target_start']) / length * 100:.1f}%</td></tr>" for i, b in enumerate(blocks))
    covered = union_bp((b["target_start"], b["target_end"]) for b in blocks)
    return (f"<table class='sx-aln'><caption>{len(blocks)} aligned block(s); {covered / length * 100:.1f}% of the plasmid covered, {lane['reverse']} reverse</caption>"
            "<thead><tr><th scope='col'>Record</th><th scope='col'>Plasmid</th><th scope='col'>Record</th><th scope='col'>Length</th><th scope='col'>Strand</th>"
            f"<th scope='col'>Identity</th><th scope='col'>Of plasmid</th></tr></thead><tbody>{rows}</tbody></table>")


def pair_html(pair, k):
    lane = pair["lane"]
    summary = (f"{esc(pair['sample'])} &middot; {esc(pair['plasmid'])} &middot; {esc(pair['tool'])} <small>({kb(pair['length'])}, {len(lane['records'])} record"
               f"{'s' if len(lane['records']) != 1 else ''}, {lane['reverse']} reverse)</small>")
    return (f"<details class='sx-pair' data-k='{k}' data-sample='{esc(pair['sample'])}' data-plasmid='{esc(pair['plasmid'])}' data-tool='{esc(pair['tool'])}'"
            f"{' open' if k == 0 else ''}><summary>{summary}</summary><div class='sx-fig'>{pair_svg(pair, str(k))}</div>"
            f"<div class='sx-alnbox'>{alignment_table(pair)}</div></details>")


def legend_html():
    return (f"<div class='sx-legend'><span><svg width='30' height='12' aria-hidden='true'><path d='M0,0 L10,0 C10,6 20,6 20,12 L30,12 L30,12 C20,6 10,6 10,0 Z' fill='{FORWARD}' fill-opacity='.8'/></svg> forward block</span>"
            f"<span><svg width='30' height='12' aria-hidden='true'><rect width='30' height='12' fill='{REVERSE}' fill-opacity='.8'/><line x1='0' y1='12' x2='12' y2='0' stroke='#fff' stroke-width='2'/>"
            f"<line x1='12' y1='12' x2='24' y2='0' stroke='#fff' stroke-width='2'/></svg> reverse block (inverted, crosses)</span>"
            "<span>opacity: identity about 99% or more, 95 to 99%, below 95%</span>"
            f"<span><i style='background:{FEATURE_COLOURS['amr']}'></i> resistance gene on the plasmid</span><span><i style='background:{FEATURE_COLOURS['replicon']}'></i> replicon</span></div>")


def asset(name):
    return (Path(HERE).parent / "assets" / "report" / name).read_text(encoding="utf-8")


def build_section(pairs, total=None):
    if not pairs:
        return (f"<section id='{SECTION_ID}' class='sx'><h2>Synteny ribbons</h2><p class='lead'>{LEAD}</p><div class='insight caution'><p>Not available in this run: no "
                "results/&lt;sample&gt;/visualization/alignment_blocks.json exists with a block on a truth plasmid. It is written by the visual-data step of stage 5 "
                "(build_visualization_data.py); without it the report cannot draw how records sit on each plasmid.</p></div></section>"), ""
    total = total if total is not None else len(pairs)
    shown = pairs[:MAX_PAIRS]
    note = (f"<p class='small'>Showing {len(shown)} of {total} comparisons, those with the most reversed blocks and records first; the rest are in each sample's "
            "visualization/alignment_blocks.json.</p>") if total > len(shown) else ""
    body = "".join(pair_html(p, k) for k, p in enumerate(shown))
    host = (f"<div class='sx-root' id='sx-root'>{legend_html()}<div class='sx-main'><div class='sx-stage'><div class='sx-pairs'>{body}</div>"
            "<div class='sx-tip' id='sx-tip' role='tooltip' hidden></div></div><aside class='sx-panel' id='sx-panel' aria-label='Synteny panel' hidden></aside></div>"
            f"{note}<p class='sx-print'>Printed or without JavaScript, each comparison is a fold with its drawing and its alignment table; the first is open.</p></div>")
    section = f"<section id='{SECTION_ID}' class='sx'><h2>Synteny ribbons</h2><p class='lead'>{LEAD}</p>{host}</section>"
    return section, asset("fig_synteny_style.html") + asset("fig_synteny_core.html") + asset("fig_synteny_ui.html")


def inject(page, results_dir):
    section, scripts = build_section(load(results_dir))
    anchor = "<section id='recommendations'>"
    if anchor in page:
        page = page.replace(anchor, section + scripts + anchor, 1)
        nav = "<a href='#recommendations'>Recommendations</a>"
        page = page.replace(nav, f"<a href='#{SECTION_ID}'>Synteny ribbons</a>" + nav, 1)
    return page
