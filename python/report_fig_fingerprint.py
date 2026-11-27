#!/usr/bin/env python3
"""
report_fig_fingerprint.py -- FIGURE 'Fingerprint of each tool' (section fig-radar), compact small-multiples version.

The earlier figure drew one large radar (560 x 470) per analysis track with every tool on top of each other. This module draws the same
numbers as a grid of SMALL radars, one per tool (about 150 px each, several per row), on one shared 0-1 scale, so a tool's shape is read on its
own and the page is much shorter. Nothing is rescored and nothing is recomputed: the axes, the 0-1 transform (including 'not available is
never drawn as zero' and 'fewer than three axes has no polygon') are the ones of report_fig_radar; the numbers come from the heatmap build
(report_fig_heatmap.build), the registry supplies the wording.

Static, no JavaScript and print: every tile is a complete server-drawn SVG (frame, polygon, axis codes), the legend of axis codes is HTML,
and the 'Numbers behind the chart' table of every track is kept in a fold. With JavaScript (assets/report/fig_fingerprint_*.html) the
tiles become buttons: hover or focus shows a tooltip, Enter / Space / click opens the right-hand panel (every dimension with its meaning and
per-isolate spread, the leaderboard link), arrow keys move between tiles, Escape closes, and Compare overlays up to three tools.

The two small pure helpers that the script also implements (the compare list and the grid arrow-key move; the spread summary and the value
format) are mirrored here (toggle_compare, grid_move, spread, fmt_value) and parity-tested against node in test/test_report_fig_fingerprint.py.

Called from report_fig_radar.inject. Standard library only.
"""
import json
import os
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import metric_registry as mr  # noqa: E402
import report_common as rc  # noqa: E402
import report_fig_heatmap as hm  # noqa: E402
import report_fig_radar as rd  # noqa: E402
import report_svg as sv  # noqa: E402

SECTION_ID = rd.SECTION_ID
TITLE = rd.TITLE
AXES = rd.AXES
CODES = {"F1": "ACC", "B3": "RCV", "CPRR": "CPR", "SVP": "STR", "UNM": "VER", "E1": "EFF", "E3": "REL"}
PALETTE, DASHES, MIN_AXES = rd.PALETTE, rd.DASHES, rd.MIN_AXES
MAX_COMPARE = 3
BOX, CX, CY, R = 160, 80, 80, 48          # one tile: a 160 x 160 viewBox, the rim at 48, labels outside it
TILE_PX = 150                              # the width / height attributes of a tile (CSS lets it shrink on a phone)
MAX_TILE_PX = 160

LEAD = ("One small radar per tool, grouped by analysis track (tracks are never pooled), all on the same scale: 0 at the centre, 1 at the rim, further out is better. "
        "The seven axes are accuracy (F1), recovery of truth plasmids, reconstruction (CPRR), structure (SV-PRR, alignment-derived and unvalidated), verified sequence "
        "(one minus the unmapped predicted share), efficiency (runtime score, proposed bands, hardware dependent) and reliability (share of isolates completed). "
        "An axis that is not available is skipped, never drawn as zero, and a tool with fewer than three available axes has no polygon. The area of a polygon is not a "
        "score and ranks nothing; the numbers in the fold under each track are the record. Hover or focus a tool for its values; click it, or press Enter, for "
        "the panel with every dimension, its meaning and the spread across isolates; Compare overlays up to three tools.")


# ----------------------------------------------------------------------------------------------- pure helpers (mirrored in the script)
def toggle_compare(current, tool_id, limit=MAX_COMPARE):
    """The compare list after clicking tool_id: removed when present, else appended; at the limit the OLDEST is dropped."""
    current = list(current)
    if tool_id in current:
        current.remove(tool_id)
        return current
    current.append(tool_id)
    return current[-limit:] if len(current) > limit else current


def grid_move(index, key, columns, count):
    """The tile index after an arrow / Home / End key in a grid of `columns` columns and `count` tiles; stays put at an edge."""
    if count <= 0:
        return -1
    columns = max(1, columns)
    target = {"ArrowRight": index + 1, "ArrowLeft": index - 1, "ArrowDown": index + columns, "ArrowUp": index - columns,
              "Home": 0, "End": count - 1}.get(key, index)
    if key == "ArrowRight" and index % columns == columns - 1:
        target = index
    if key == "ArrowLeft" and index % columns == 0:
        target = index
    return target if 0 <= target < count else index


def spread(values):
    """{'n', 'min', 'median', 'max'} over the numeric values (None ignored); n = 0 -> all None. Median of an even count is the mean of the middle two."""
    xs = sorted(float(v) for v in values if v is not None and v == v)
    if not xs:
        return {"n": 0, "min": None, "median": None, "max": None}
    mid = len(xs) // 2
    med = xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2.0
    return {"n": len(xs), "min": xs[0], "median": med, "max": xs[-1]}


def fmt_value(value, digits):
    """A value to a fixed number of digits; None / NaN -> 'not available' (never 0)."""
    if value is None or value != value:
        return "not available"
    return f"{value:.{digits}f}"


# ----------------------------------------------------------------------------------------------- drawing
def point(k, frac):
    return sv.polar(CX, CY, R * frac, 360.0 * k / len(AXES))


def frame_markup():
    """Rings at 0.5 and 1, a spoke and a three-letter code per axis. Shared by every tile and by the compare overlay."""
    n = len(AXES)
    parts = []
    for level in (0.5, 1.0):
        pts = " ".join(f"{sv.num(x)},{sv.num(y)}" for x, y in (point(k, level) for k in range(n)))
        parts.append(f"<polygon points='{pts}' fill='none' stroke='#b9bdb4' stroke-width='{1 if level == 1.0 else 0.5}'/>")
    for k, (_label, col, _m, _i) in enumerate(AXES):
        x, y = point(k, 1.0)
        parts.append(f"<line x1='{CX}' y1='{CY}' x2='{sv.num(x)}' y2='{sv.num(y)}' stroke='#b9bdb4' stroke-width='.5'/>")
        lx, ly = point(k, 1.0 + 9.0 / R)
        anchor = "middle" if abs(lx - CX) < 6 else ("start" if lx > CX else "end")
        parts.append(f"<text x='{sv.num(lx)}' y='{sv.num(ly + 3)}' font-size='8' text-anchor='{anchor}' fill='currentColor' "
                     f"font-family='Arial,Helvetica,sans-serif'>{CODES[col]}{'†' if col == 'SVP' else ''}</text>")
    return "".join(parts)


FRAME = None


def frame():
    global FRAME
    if FRAME is None:
        FRAME = frame_markup()
    return FRAME


def polygon_points(values):
    """('x,y x,y ...', [(k, x, y)...]) for the available axes, or ('', []) when fewer than MIN_AXES are available."""
    have = [(k, v) for k, v in enumerate(values) if v is not None]
    if len(have) < MIN_AXES:
        return "", []
    pts = [(k,) + tuple(point(k, v)) for k, v in have]
    return " ".join(f"{sv.num(x)},{sv.num(y)}" for _k, x, y in pts), pts


def tile_svg(label, values, colour, dash, track):
    poly, pts = polygon_points(values)
    name = f"{label}, {track} track"
    avail = sum(v is not None for v in values)
    desc = ("A small radar on a 0 to 1 scale: " + "; ".join(f"{AXES[k][0]} {v:.2f}" for k, v in enumerate(values) if v is not None)) if poly else \
        f"Fewer than {MIN_AXES} axes are available for this tool, so no polygon is drawn."
    out = [f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {BOX} {BOX}' width='{TILE_PX}' height='{TILE_PX}' role='img' class='fpr-svg' "
           f"aria-label='{sv.esc(name + '. ' + desc)}' preserveAspectRatio='xMidYMid meet'><title>{sv.esc(name)}</title>", frame()]
    if poly:
        out.append(f"<polygon points='{poly}' fill='{colour}' fill-opacity='.16' stroke='{colour}' stroke-width='1.8' stroke-linejoin='round' stroke-dasharray='{dash}'/>")
        out.extend(f"<circle cx='{sv.num(x)}' cy='{sv.num(y)}' r='2' fill='{colour}'/>" for _k, x, y in pts)
    else:
        out.append(f"<text x='{CX}' y='{CY + 3}' font-size='8.5' text-anchor='middle' fill='#6a6f66' font-family='Arial,Helvetica,sans-serif'>"
                   f"{'no axis available' if avail == 0 else 'too few axes'}</text>")
    out.append("</svg>")
    return "".join(out)


def tool_colours(data):
    names = sorted({row["tool"] for block in data["blocks"] for row in block["rows"]})
    return {n: (PALETTE[i % len(PALETTE)], DASHES[(i // len(PALETTE)) % len(DASHES)]) for i, n in enumerate(names)}


def ranks(rows):
    """Competition rank by the scorecard overall (1 = highest); None when a tool has no overall score."""
    scored = sorted((r["overall"] for r in rows if r.get("overall") is not None), reverse=True)
    return [None if r.get("overall") is None else 1 + sum(1 for s in scored if s > r["overall"]) for r in rows]


def model(data):
    """The JSON the script reads. Every value is finite or None."""
    cols = {c["id"]: c for c in data["cols"]}
    index = {c["id"]: j for j, c in enumerate(data["cols"])}
    reg = {r["id"]: r for r in mr.load()}
    colour = tool_colours(data)
    axes = []
    for k, (label, col, metric, inv) in enumerate(AXES):
        c, r = cols[col], reg.get(metric, {})
        axes.append({"k": k, "code": CODES[col], "label": label, "col": col, "metric": metric, "name": c["name"], "unit": c["unit"], "digits": c["digits"],
                     "inv": inv, "unval": bool(c.get("unval")) or col == "SVP", "def": c.get("def") or "", "limit": r.get("limitations", ""),
                     "evidence": r.get("evidence", "")})
    tracks = []
    for b, block in enumerate(data["blocks"]):
        rk = ranks(block["rows"])
        tools = []
        for i, row in enumerate(block["rows"]):
            values = [rd.axis_value(block["cells"][i][index[col]], cols[col], inv) for _l, col, _m, inv in AXES]
            raw = [block["cells"][i][index[col]][0] for _l, col, _m, _inv in AXES]
            ps = [(block["ps"][i][index[col]] if block.get("ps") else None) for _l, col, _m, _inv in AXES]
            poly, _pts = polygon_points(values)
            c, d = colour[row["tool"]]
            tools.append({"id": f"{block['track']}|{row['tool']}", "tool": row["tool"], "label": row["label"], "task": row.get("task") or "", "rank": rk[i],
                          "n": row.get("nsamples"), "overall": row.get("overall"),
                          "v": [None if v is None else round(v, 4) for v in values], "raw": [None if x is None else round(x, 6) for x in raw], "ps": ps,
                          "poly": poly, "colour": c, "dash": d, "naxes": sum(v is not None for v in values)})
        tracks.append({"id": block["track"], "label": block["track"].replace("_", " ").capitalize(), "of": sum(r is not None for r in rk), "tools": tools})
    return {"axes": axes, "samples": data.get("samples") or [], "tracks": tracks, "frame": frame(), "box": BOX, "max_compare": MAX_COMPARE,
            "leaderboard": "leaderboard"}


def numbers_table(block, cols_by_id, index, entries):
    head = "".join(f"<th>{sv.esc(label)}</th>" for label, *_ in AXES)
    body = "".join("<tr><td>{}</td>{}</tr>".format(sv.esc(row["label"]), "".join(
        "<td>{}</td>".format(f"{v:.3f}" if v is not None else "not available") for v in values)) for row, values in entries)
    return (f"<details><summary>Numbers behind the chart</summary><table class='sortable'><thead><tr><th>Tool</th>{head}</tr></thead>"
            f"<tbody>{body}</tbody></table></details>")


def track_html(block, track_model, data, colour):
    cols_by_id = {c["id"]: c for c in data["cols"]}
    index = {c["id"]: j for j, c in enumerate(data["cols"])}
    entries = rd.tool_values(block, data["cols"])
    tiles = []
    for (row, values), t in zip(entries, track_model["tools"]):
        c, d = colour[row["tool"]]
        sub = (f"rank {t['rank']} of {track_model['of']}" if t["rank"] else "not ranked") + f" &middot; {t['naxes']}/{len(AXES)} axes"
        tiles.append(f"<div class='fpr-tile' data-id='{sv.esc(t['id'])}' data-track='{sv.esc(block['track'])}'>{tile_svg(row['label'], values, c, d, block['track'])}"
                     f"<span class='fpr-name'><i style='background:{c}'></i>{sv.esc(row['label'])}</span><span class='fpr-sub'>{sub}</span></div>")
    return (f"<div class='fpr-track' data-track='{sv.esc(block['track'])}'><h3>{sv.esc(track_model['label'])} <small>{len(entries)} tool{'s' if len(entries) != 1 else ''}</small></h3>"
            f"<div class='fpr-grid' role='group' aria-label='Fingerprints, {sv.esc(track_model['label'])} track'>{''.join(tiles)}</div>"
            f"{numbers_table(block, cols_by_id, index, entries)}</div>")


def key_html():
    items = "".join(f"<li><b>{CODES[col]}</b> {sv.esc(label)}{' &dagger; unvalidated' if col == 'SVP' else ''}</li>" for label, col, _m, _i in AXES)
    return (f"<ul class='fpr-key' aria-label='Axis codes'>{items}</ul>"
            "<p class='fpr-scale'>Scale (every tile): 0 at the centre, 0.5 at the inner ring, 1 at the rim; further out is better. "
            "A missing axis is skipped, never zero.</p>")


def asset(name):
    return (Path(HERE).parent / "assets" / "report" / name).read_text(encoding="utf-8")


def json_script(sid, payload):
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return f"<script type='application/json' id='{sid}'>" + text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026") + "</script>"


def build_section(data):
    colour = tool_colours(data)
    payload = model(data)
    tracks = "".join(track_html(b, t, data, colour) for b, t in zip(data["blocks"], payload["tracks"]))
    host = (f"<div class='fpr-root' id='fpr-root'>{key_html()}<div class='fpr-main'><div class='fpr-stage'>{tracks}"
            "<div class='fpr-tip' id='fpr-tip' role='tooltip' hidden></div></div>"
            "<aside class='fpr-panel' id='fpr-panel' aria-label='Tool fingerprint panel' hidden></aside></div></div>"
            + json_script("fpr-data", payload))
    return rc.section(SECTION_ID, TITLE, LEAD, rc.Raw(host), group="Figures"), asset("fig_fingerprint_style.html") + asset("fig_fingerprint_core.html") + asset("fig_fingerprint_ui.html")


def inject(page, results_dir, data_dir, scores_path):
    nav = [(SECTION_ID, "Tool fingerprint")]
    try:
        rd.validate()
        data = hm.build(results_dir, data_dir, scores_path)
    except ValueError as exc:
        return rc.inject_sections(page, rc.section(SECTION_ID, TITLE, LEAD, rc.not_run(str(exc)), group="Figures"), nav)
    section, scripts = build_section(data)
    return rc.inject_sections(rc.add_style(page), str(section) + scripts, nav)
