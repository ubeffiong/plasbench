#!/usr/bin/env python3
"""
report_fig_radar.py -- FIGURE 'Fingerprint of each tool' (section fig-radar): a radar chart per analysis track, one polygon per tool.

This is a VIEW over the numbers the tool heatmap already holds (report_fig_heatmap.build: the scorecard and the leaderboard, one block per
analysis track, never pooled); it reads no file of its own and recomputes nothing except the display transform below. The axes are chosen
from metrics that the registry (config/metrics.tsv) lists, one per question, so the shape of a polygon says what a tool is good at:

  Accuracy            mean base F1                     (F1)
  Recovery            share of truth plasmids recovered (B3)
  Reconstruction      CPRR                              (CPRR)
  Structure           SV-PRR                            (SVP)         unvalidated: alignment-derived calls
  Verified sequence   1 - unmapped predicted share      (UNM)         how much of the output is checked by an alignment
  Efficiency          runtime score, 0-100 / 100        (E1)          hardware dependent
  Reliability         share of isolates the tool completed (E3)

Every axis runs 0 (centre) to 1 (rim), bright end good. A fraction is drawn as it is; runtime has no natural 0-1 range, so it is drawn as its
scorecard score divided by 100 (the proposed, not standard, bands). A value that is not available is NOT drawn as 0: the polygon skips that axis
and the table says "not available"; a tool with fewer than three available axes has no polygon. The area of a polygon is not a score and is not
used to rank anything: the table of numbers is the record, the shape is a picture of it.

Standard library only.
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import metric_registry as mr  # noqa: E402
import report_common as rc  # noqa: E402
import report_fig_heatmap as hm  # noqa: E402
import report_svg as sv  # noqa: E402

SECTION_ID = "fig-radar"
TITLE = "Fingerprint of each tool"
# (axis label, heatmap column id, registry metric id that the column shows, invert)
AXES = [
    ("Accuracy", "F1", "base_f1", False),
    ("Recovery", "B3", "plasmid_recall", False),
    ("Reconstruction", "CPRR", "cprr", False),
    ("Structure", "SVP", "sv_prr", False),
    ("Verified sequence", "UNM", "unmapped_fraction", True),
    ("Efficiency", "E1", "runtime", False),
    ("Reliability", "E3", "success_rate", False),
]
PALETTE = ["#0072B2", "#D55E00", "#009E73", "#E69F00", "#CC79A7", "#56B4E9", "#444444", "#9A8700"]
DASHES = ("", "7 3", "2 3")    # a tool past the 8th palette colour repeats a colour with a dash pattern, so two tools never look alike
W, H, CX, CY, R = 560, 470, 280, 235, 150
MIN_AXES = 3

LEAD = ("One radar per analysis track (tracks are never pooled), one polygon per tool, one axis per question: accuracy (F1), recovery of truth plasmids, "
        "reconstruction (CPRR), structure (SV-PRR, alignment-derived and unvalidated), verified sequence (one minus the unmapped predicted share), "
        "efficiency (runtime score) and reliability (share of isolates completed). Every axis runs from 0 at the centre to 1 at the rim, and further out is always better. "
        "An axis that is not available is skipped, never drawn as zero, and a tool with fewer than three available axes has no polygon. Runtime has no natural 0 to 1 "
        "range, so it is drawn as its scorecard score over 100 (proposed bands, hardware dependent). The area of a polygon is not a score and ranks nothing; the "
        "numbers below each chart are the record.")


def axis_value(cell, col, invert):
    """0..1 for one heatmap cell, or None when it is not available (never 0 for a blank)."""
    value, score = cell[0], cell[1]
    if col["unit"] in ("fraction", "-1 to 1"):
        out = value
    else:
        out = None if score is None else score / 100.0
    if out is None:
        return None
    out = 1.0 - out if invert else out
    return max(0.0, min(1.0, out))


def validate():
    """The axes must name real registry metrics (the registry is the one place a metric is defined)."""
    known = {row["id"] for row in mr.load()}
    missing = [metric for _label, _col, metric, _inv in AXES if metric not in known]
    if missing:
        raise ValueError("the radar axes name metrics that are not in config/metrics.tsv: " + ", ".join(missing))


def tool_values(block, columns):
    index = {c["id"]: j for j, c in enumerate(columns)}
    out = []
    for i, row in enumerate(block["rows"]):
        out.append((row, [axis_value(block["cells"][i][index[col]], columns[index[col]], inv) for _l, col, _m, inv in AXES]))
    return out


def radar_svg(track, entries, uid):
    n = len(AXES)
    point = lambda k, frac: sv.polar(CX, CY, R * frac, 360.0 * k / n)  # noqa: E731 (degrees clockwise from 12 o'clock: the first axis points up)
    parts = [sv.svg_open(W, H, f"Fingerprint of each tool, {track} track", "A radar chart: one polygon per tool over seven axes, 0 at the centre and 1 at the rim.", "rd-svg")]
    for level in (0.25, 0.5, 0.75, 1.0):
        pts = " ".join(f"{sv.num(x)},{sv.num(y)}" for x, y in (point(k, level) for k in range(n)))
        parts.append(f"<polygon points='{pts}' fill='none' stroke='#b9bdb4' stroke-width='{1.2 if level == 1.0 else 0.6}'/>")
        x, y = point(0, level)
        parts.append(sv.text(x + 4, y + 3, f"{level:g}", 9, fill="#6a6f66"))
    for k, (label, col, _m, _i) in enumerate(AXES):
        x, y = point(k, 1.0)
        parts.append(sv.line(CX, CY, x, y, "#b9bdb4", 0.6))
        lx, ly = point(k, 1.14)
        anchor = "middle" if abs(lx - CX) < 12 else ("start" if lx > CX else "end")
        parts.append(sv.text(lx, ly + 4, label + (" †" if col == "SVP" else ""), 11, anchor, fill="#17231d"))
    for t, (row, values) in enumerate(entries):
        have = [(k, v) for k, v in enumerate(values) if v is not None]
        if len(have) < MIN_AXES:
            continue
        colour, dash = PALETTE[t % len(PALETTE)], DASHES[(t // len(PALETTE)) % len(DASHES)]
        pts = " ".join(f"{sv.num(x)},{sv.num(y)}" for x, y in (point(k, v) for k, v in have))
        parts.append(f"<polygon points='{pts}' fill='{colour}' fill-opacity='0.10' stroke='{colour}' stroke-width='2' stroke-dasharray='{dash}'><title>{sv.esc(row['label'])}</title></polygon>")
        for k, v in have:
            x, y = point(k, v)
            parts.append(f"<circle cx='{sv.num(x)}' cy='{sv.num(y)}' r='3.2' fill='{colour}'><title>{sv.esc(row['label'] + ', ' + AXES[k][0] + ': ' + format(v, '.3f'))}</title></circle>")
    parts.append(sv.svg_close())
    return "".join(parts)


def block_html(block, columns, k):
    entries = tool_values(block, columns)
    # Kept outside the f-strings: a backslash inside an f-string expression is a
    # SyntaxError before Python 3.12, and PlasBench supports 3.9+.
    too_few = ' <em class="muted">(too few axes for a polygon)</em>'
    line_notes = ("", " (dashed line)", " (dotted line)")
    legend = "".join(
        f"<li style='display:inline-block;margin:0 14px 4px 0'><span style='display:inline-block;width:12px;height:12px;background:{PALETTE[t % len(PALETTE)]};vertical-align:-1px'></span> "
        f"{sv.esc(row['label'])}{line_notes[(t // len(PALETTE)) % len(DASHES)]}"
        f"{'' if sum(v is not None for v in values) >= MIN_AXES else too_few}</li>"
        for t, (row, values) in enumerate(entries))
    head = "".join(f"<th>{sv.esc(label)}</th>" for label, *_ in AXES)
    body = "".join("<tr><td>{}</td>{}</tr>".format(sv.esc(row["label"]), "".join(
        "<td>{}</td>".format(f"{v:.3f}" if v is not None else "not available") for v in values)) for row, values in entries)
    return (f"<div class='rd-block'><h3>{sv.esc(block['track'].replace('_', ' ').capitalize())}</h3>{radar_svg(block['track'], entries, f'rd{k}')}"
            f"<ul class='rd-legend' style='list-style:none;padding:0'>{legend}</ul>"
            f"<details><summary>Numbers behind the chart</summary><table class='sortable'><thead><tr><th>Tool</th>{head}</tr></thead><tbody>{body}</tbody></table></details></div>")


def inject(page, results_dir, data_dir, scores_path):
    import report_fig_fingerprint    # the compact, interactive small-multiples drawing of this figure (this module keeps the axes, the transform and the old large radar)
    return report_fig_fingerprint.inject(page, results_dir, data_dir, scores_path)


def inject_large(page, results_dir, data_dir, scores_path):
    nav = [(SECTION_ID, "Tool fingerprint")]
    try:
        validate()
        data = hm.build(results_dir, data_dir, scores_path)
    except ValueError as exc:
        return rc.inject_sections(page, rc.section(SECTION_ID, TITLE, LEAD, rc.not_run(str(exc)), group="Figures"), nav)
    page = rc.add_style(page)
    body = "".join(block_html(b, data["cols"], k) for k, b in enumerate(data["blocks"]))
    return rc.inject_sections(page, rc.section(SECTION_ID, TITLE, LEAD, rc.Raw(body), group="Figures"), nav)
