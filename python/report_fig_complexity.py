#!/usr/bin/env python3
"""
report_fig_complexity.py -- FIGURE 'Does isolate complexity explain performance?' (section fig-complexity).

Small multiples, one set per analysis track (never pooled): for each isolate characteristic of benchmark.dataset_features.tsv
(characterise_dataset.py, plan C1) a scatter of the characteristic (x) against each tool's base F1 on the isolate (y, scores.tsv), one point per
tool and isolate. The x axis says whether the characteristic is knowable without a reference or needs the reference; nothing here feeds a model.

  panels     truth-derived: plasmids in the truth, largest plasmid internal repeat fraction; truth-free: contigs in the assembly, read depth
  trend      per tool and characteristic, the Spearman rank correlation between the characteristic and F1 with its n; shown only for at
             least MIN_POINTS isolates AND some spread in both; otherwise "not computed". A correlation across a handful of isolates of one
             cohort is a description, not evidence that the characteristic causes the difference.
  a point    is drawn only where both the characteristic and the F1 were measured; a blank is never plotted as 0.

Standard library only.
"""
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import characterise_dataset as cd  # noqa: E402
import report_common as rc  # noqa: E402
import report_fig_heatmap as hm  # noqa: E402
import report_scorecard as rs  # noqa: E402
import report_svg as sv  # noqa: E402

SECTION_ID = "fig-complexity"
TITLE = "Does isolate complexity explain performance?"
PANELS = ["plasmid_count", "max_internal_repeat_fraction", "contig_count", "read_depth_x"]
MIN_POINTS = 5
PALETTE = ["#0072B2", "#D55E00", "#009E73", "#E69F00", "#CC79A7", "#56B4E9", "#444444", "#9A8700"]
PW, PH, ML, MR, MT, MB = 300, 230, 46, 14, 26, 40
LABEL = {name: (label, basis) for name, basis, _src, label in cd.FEATURES}

LEAD = ("Each small chart plots one characteristic of the isolates (x) against how well each tool did on them (y, base F1), one point per tool and isolate, per analysis track. "
        "The caption of each chart says whether the characteristic is <strong>knowable without a reference</strong> (an isolate's own reads and assembly) or <strong>needs the "
        "reference</strong> (benchmark only, never a model input). The table gives the Spearman rank correlation per tool, only with at least five isolates and some spread in both. "
        "With few isolates from one cohort this describes the data; it does not show that a characteristic causes the difference. A blank is never drawn as zero.")


def ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    out, i = [0.0] * len(values), 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return out


def spearman(xs, ys):
    """Spearman rank correlation, or None when there are fewer than MIN_POINTS pairs or either side has no spread."""
    if len(xs) < MIN_POINTS or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else None


def points(scores, features):
    """{track: {tool: [(sample, {feature: x}, f1)]}} where F1 was measured; the features of that isolate come along (blank ones are left out)."""
    out = defaultdict(lambda: defaultdict(list))
    for row in scores:
        f1 = rc.number(row.get("f1"))
        feats = features.get(row.get("sample"))
        if f1 is None or feats is None:
            continue
        x = {name: rc.number(feats.get(name)) for name in PANELS}
        out[rs._track(row)][row["tool"]].append((row["sample"], {k: v for k, v in x.items() if v is not None}, f1))
    return out


def panel_svg(track, feature, by_tool, colours):
    label, basis = LABEL[feature]
    xs_all = [x[feature] for pts in by_tool.values() for _s, x, _f in pts if feature in x]
    if not xs_all:
        return f"<p class='muted'>Not available: no isolate has a measured {sv.esc(label.lower())}.</p>"
    lo, hi = min(xs_all), max(xs_all)
    span = (hi - lo) or 1.0
    px = lambda v: ML + (v - lo) / span * (PW - ML - MR) if hi > lo else ML + (PW - ML - MR) / 2  # noqa: E731
    py = lambda v: MT + (1 - v) * (PH - MT - MB)  # noqa: E731
    parts = [sv.svg_open(PW, PH, f"{label} against base F1, {track} track", "A scatter of one isolate characteristic against base F1; one point per tool and isolate.", "cx-svg")]
    for g in (0, 0.5, 1):
        parts.append(sv.line(ML, py(g), PW - MR, py(g), "#d5ddd6", 0.6))
        parts.append(sv.text(ML - 5, py(g) + 3, f"{g:g}", 9, "end", fill="#6a6f66"))
    parts.append(sv.line(ML, PH - MB, PW - MR, PH - MB, "#6a6f66", 1))
    parts.append(sv.text(ML, PH - MB + 13, f"{lo:g}", 9, "start", fill="#6a6f66"))
    parts.append(sv.text(PW - MR, PH - MB + 13, f"{hi:g}", 9, "end", fill="#6a6f66"))
    parts.append(sv.text((ML + PW - MR) / 2, PH - 5, label, 10, "middle", fill="#17231d"))
    parts.append(sv.text(ML, 14, "knowable without a reference" if basis == "truth_free" else "needs the reference: benchmark only", 9.5, "start", fill="#314238", extra="font-style='italic'"))
    for tool, pts in by_tool.items():
        for sample, x, f1 in pts:
            if feature in x:
                parts.append(f"<circle cx='{sv.num(px(x[feature]))}' cy='{sv.num(py(f1))}' r='3.4' fill='{colours[tool]}' fill-opacity='0.75'>"
                             f"<title>{sv.esc(tool + ', ' + sample + ': F1 ' + format(f1, '.3f') + ', ' + label + ' ' + format(x[feature], 'g'))}</title></circle>")
    parts.append(sv.svg_close())
    return "".join(parts)


def track_html(track, by_tool, display):
    tools = sorted(by_tool)
    colours = {t: PALETTE[i % len(PALETTE)] for i, t in enumerate(tools)}
    legend = "".join(f"<li style='display:inline-block;margin:0 14px 4px 0'><span style='display:inline-block;width:11px;height:11px;border-radius:50%;background:{colours[t]};vertical-align:-1px'></span> {sv.esc(display(t))}</li>" for t in tools)
    panels = "".join(f"<div style='flex:1 1 300px;max-width:340px'>{panel_svg(track, f, by_tool, colours)}</div>" for f in PANELS)
    rows = []
    for t in tools:
        cells = []
        for f in PANELS:
            pairs = [(x[f], f1) for _s, x, f1 in by_tool[t] if f in x]
            rho = spearman([p[0] for p in pairs], [p[1] for p in pairs])
            cells.append(f"{rho:+.2f} (n={len(pairs)})" if rho is not None else f"not computed (n={len(pairs)})")
        rows.append("<tr><td>{}</td>{}</tr>".format(sv.esc(display(t)), "".join(f"<td>{c}</td>" for c in cells)))
    head = "".join(f"<th>{sv.esc(LABEL[f][0])}<br><small class='muted'>{'knowable without a reference' if LABEL[f][1] == 'truth_free' else 'needs the reference'}</small></th>" for f in PANELS)
    return (f"<div class='cx-block'><h3>{sv.esc(track.replace('_', ' ').capitalize())}</h3><div style='display:flex;flex-wrap:wrap;gap:10px'>{panels}</div>"
            f"<ul style='list-style:none;padding:0'>{legend}</ul><details><summary>Rank correlation of F1 with each characteristic, per tool</summary>"
            f"<table class='sortable'><thead><tr><th>Tool</th>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></details></div>")


def inject(page, results_dir, data_dir, scores_path):
    nav = [(SECTION_ID, "Complexity")]
    d = hm._resolve_dir(results_dir, data_dir)
    feature_rows = rc.read_tsv(os.path.join(d, "benchmark.dataset_features.tsv")) if d else None
    scores = rc.read_tsv(scores_path) if scores_path else None
    if not feature_rows or not scores:
        reason = ("benchmark.dataset_features.tsv is absent or empty (stage 6 writes it with python/characterise_dataset.py)." if not feature_rows
                  else "scores.tsv is absent or empty, so no tool was scored.")
        return rc.inject_sections(page, rc.section(SECTION_ID, TITLE, LEAD, rc.not_run(reason), group="Figures"), nav)
    features = {r["sample"]: r for r in feature_rows if r.get("sample")}
    data = points(scores, features)
    try:
        from plasbench_common import display_tool_name as display
    except ImportError:                                 # pragma: no cover
        display = lambda t: t                           # noqa: E731
    if not data:
        return rc.inject_sections(page, rc.section(SECTION_ID, TITLE, LEAD, rc.not_run("no isolate has both a dataset characteristic and a scored F1."), group="Figures"), nav)
    page = rc.add_style(page)
    body = "".join(track_html(track, data[track], display) for track in sorted(data))
    return rc.inject_sections(page, rc.section(SECTION_ID, TITLE, LEAD, rc.Raw(body), group="Figures"), nav)
