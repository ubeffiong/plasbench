#!/usr/bin/env python3
"""
report_compare_table.py -- the comparison table: a QUAST-style grid of metrics (rows, in groups) by tools (columns) that opens into a side panel.

Every plain metric-by-tool table of the report can be turned into this component and keep its original table in a closed "Table" fold beside it.
What the component adds to a table:

  * row-wise shading Worst (red) - Median (white) - Best (blue). The shade is by RANK inside the row, never by raw value, so one very large
    value cannot wash out the rest; tied cells share the average rank. The direction (higher or lower is better) is read from the metric
    registry (config/metrics.tsv, config/scorecard.tsv); where it is not defined the row is not shaded and says "direction not defined".
    A row with fewer than two assessed tools, or in which every assessed tool is tied, is not shaded either, and says why. Missing and
    "not assessed" cells are hatched and are never shaded, never zero;
  * a "Show heatmap" checkbox, collapsible metric groups, a column filter, column sorting (by mean rank, or by one metric) and re-ordering
    (drag handle, or the arrow keys on the handle), a "best in row" mark, a CSV export;
  * metric names with a definition on hover or focus (what it is, which way is better, which table and column it comes from);
  * a side panel (click a cell, a metric name or a tool name): the per-isolate values as a strip with quartiles, the interval, n, the isolates ranked
    best to worst with links to their rows, outliers, and the same metric for every other tool.

The static grid is complete without JavaScript and is what the print / PDF export shows (shading kept, panel omitted, the original table open);
the script (assets/report/compare_table_*.html) makes it interactive and recomputes the same ranks in the browser from the embedded data.

  metric(...), column(...), cell(...)     the three kinds of input
  build(cid, title, groups, columns, cells, ...)   the component as HTML (a string)
  rank_shade(values, direction)           the pure ranking/shading function (mirrored in compare_table_core.html, tested for agreement)
  quartiles(values), outliers(values)     the numbers behind the panel's strip plot
  resolve(source, column)                 (direction, registry row) for a table column, or (None, None)
  finish(page)                            add the style and the scripts once (when the page holds a component)

Honesty rules: a value is the value of the source table (the panel shows the same text as the grid cell and the original table); a direction is never
guessed; a cell that was not assessed says so. Standard library only.
"""
import html
import json
import math
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STEPS = 10
ASSETS = ("compare_table_style.html", "compare_table_core.html", "compare_table_ui.html")
HELP_KEY = "compare-table"

# ------------------------------------------------------------------------------------------------ directions
# config/metrics.tsv names each metric but has no direction column; config/scorecard.tsv has one for A1-E3. The directions below are those the
# metric's own definition states (a share of a reference recovered, a score of agreement: higher; an error, a cost, a mismatch: lower). A metric
# that is in neither place has NO direction: its row is not shaded and says "direction not defined". Keys are metric-registry ids.
REGISTRY_DIRECTION = {
    "base_precision": "higher", "base_f1": "higher", "mcc": "higher", "f_beta": "higher", "pr_auc": "higher", "zero_plasmid_specificity": "higher",
    "base_recall": "higher", "plasmid_recall": "higher", "recall_ge50": "higher", "recall_ge90": "higher", "completeness": "higher",
    "lw_bin_f1": "higher", "bin_f1": "higher", "nmi": "higher", "vi": "lower", "split": "lower", "merge": "lower", "purity": "higher",
    "cprr": "higher", "perfect_recovery": "higher", "strict_reconstruction": "higher", "circular_recall": "higher",
    "chromosomal_contamination": "lower", "unmapped_pred": "lower", "unmapped_fraction": "lower", "off_truth_fraction": "lower",
    "ambiguous_fraction": "lower", "precision_gap": "lower", "sv_prr": "higher", "amr_recovery": "higher", "amr_prr": "higher",
    "amr_colocalisation": "higher", "amr_flank_context": "higher", "amr_placement": "higher", "structural_concordance": "higher", "ngoc": "higher",
    "feature_preservation": "higher", "success_rate": "higher", "runtime": "lower", "memory": "lower",
}
_REG = {}


def _registry():
    if "rows" not in _REG:
        rows, by_cell, by_id = [], {}, {}
        try:
            import metric_registry
            rows = metric_registry.load()
        except Exception:                      # a partial checkout: the table still builds, with no registry facts
            rows = []
        for row in rows:
            by_id[row["id"]] = row
            by_cell.setdefault((row["source"], row["column"]), row)
        scorecard = {}
        path = os.path.join(ROOT, "config", "scorecard.tsv")
        if os.path.isfile(path):
            with open(path, encoding="utf-8", newline="") as handle:
                lines = [ln.rstrip("\r\n") for ln in handle if ln.strip() and not ln.startswith("#")]
            head = lines[0].split("\t") if lines else []
            for ln in lines[1:]:
                rec = dict(zip(head, ln.split("\t")))
                scorecard[rec.get("id", "")] = rec
        _REG.update(rows=rows, by_cell=by_cell, by_id=by_id, scorecard=scorecard)
    return _REG


def resolve(source, column="", registry_id=None):
    """(direction, registry row) for a table column. direction is 'higher', 'lower' or None (not defined); the row is the metric-registry row or None."""
    reg = _registry()
    row = reg["by_id"].get(registry_id) if registry_id else reg["by_cell"].get((source, column))
    if row is None:
        return None, None
    direction = None
    sid = (row.get("scorecard_id") or "").strip()
    if sid and sid in reg["scorecard"] and reg["scorecard"][sid].get("direction") in ("higher", "lower"):
        direction = reg["scorecard"][sid]["direction"]
    return direction or REGISTRY_DIRECTION.get(row["id"]), row


_GLOSSARY = {}


def set_glossary(glossary):
    """The report's glossary {term: {what, why}}; a metric with a registry term and no definition of its own takes the glossary's."""
    _GLOSSARY.clear()
    _GLOSSARY.update(glossary or {})


# ------------------------------------------------------------------------------------------------ inputs
def metric(mid, name, definition="", direction="auto", unit="", source="", column="", registry_id=None, note=""):
    """One row of the table. direction: 'higher', 'lower', None (not defined) or 'auto' (from the registry through source/column/registry_id)."""
    reg_direction, row = resolve(source, column, registry_id)
    if direction == "auto":
        direction = reg_direction
    if direction not in ("higher", "lower"):
        direction = None
    text = definition
    if not text and row is not None:
        entry = _GLOSSARY.get(row.get("term") or "")
        if isinstance(entry, dict):
            text = entry.get("what", "")
    if row is not None and not source:
        source, column = row.get("source", ""), row.get("column", "")
    where = f"{source} table, column {column}" if source and column else (f"{source} table" if source else "")
    return {"id": mid, "name": name, "def": text, "dir": direction, "unit": unit, "src": where,
            "reg": (row or {}).get("id", ""), "ev": (row or {}).get("evidence", ""), "lim": (row or {}).get("limitations", ""),
            "shown": (row or {}).get("shown_in", ""), "note": note}


def column(cid, label, track="", task=""):
    return {"id": cid, "label": label, "track": track, "task": task}


def num(value):
    """float or None (a blank, a word or a non-finite number is not a value)."""
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


_NUM = re.compile(r"\s*[-+]?(\d[\d,]*\.?\d*|\.\d+)([eE][-+]?\d+)?\s*%?\s*$")


def num_display(text):
    """The number a table cell shows ('99.91%', '1,234', '0.5'), or None for a word, a dash or a composite text such as '100% (n=6)'."""
    if text is None or not _NUM.match(str(text)):
        return None
    return num(str(text).replace(",", "").replace("%", "").strip())


def cell(disp, value="auto", n=None, lo=None, hi=None, iso=None, na=None):
    """One cell: `disp` the text the table shows, `value` the number it stands for ('auto': parsed from disp; None: not a number), `n` isolates,
    lo/hi the interval, `iso` {isolate: value} behind it, `na` a reason when the cell was not assessed (then it is never shaded)."""
    if value == "auto":
        value = num_display(disp)
    value = num(value)
    return {"disp": "" if disp is None else str(disp), "v": None if na else value, "n": n, "lo": num(lo), "hi": num(hi),
            "iso": {k: num(v) for k, v in (iso or {}).items() if num(v) is not None}, "na": na or ""}


# ------------------------------------------------------------------------------------------------ pure functions (mirrored in compare_table_core.html)
def _same(a, b):
    return abs(a - b) <= 1e-12 * max(1.0, abs(a), abs(b))


def rank_shade(values, direction):
    """Row-wise rank shading. Returns {status, m, t, rank, bucket, best}; see compare_table_core.html for the definition (identical)."""
    n = len(values)
    out = {"status": "ok", "m": 0, "t": [None] * n, "rank": [None] * n, "bucket": [None] * n, "best": [False] * n}
    idx = [i for i, v in enumerate(values) if v is not None and isinstance(v, (int, float)) and math.isfinite(v)]
    out["m"] = len(idx)
    if direction not in ("higher", "lower"):
        out["status"] = "no_direction"
        return out
    if len(idx) < 2:
        out["status"] = "too_few"
        return out
    sgn = -1.0 if direction == "higher" else 1.0
    order = sorted(idx, key=lambda i: (sgn * values[i], i))
    groups, cur = [], [order[0]]
    for i in order[1:]:
        if _same(values[i], values[cur[0]]):
            cur.append(i)
        else:
            groups.append(cur)
            cur = [i]
    groups.append(cur)
    m, pos = len(idx), 1
    for k, grp in enumerate(groups):
        avg = pos + (len(grp) - 1) / 2
        for c in grp:
            out["rank"][c] = avg
            if len(groups) > 1:
                t = (m - avg) / (m - 1)
                out["t"][c] = t
                out["bucket"][c] = int(math.floor(t * STEPS + 0.5))
                out["best"][c] = k == 0
        pos += len(grp)
    if len(groups) == 1:
        out["status"] = "all_tied"
    return out


def _quantile(sorted_values, p):
    n = len(sorted_values)
    if not n:
        return None
    h = (n - 1) * p
    lo, hi = int(math.floor(h)), int(math.ceil(h))
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (h - lo)


def quartiles(values):
    v = sorted(x for x in values if x is not None and math.isfinite(x))
    if not v:
        return None
    return {"n": len(v), "min": v[0], "q1": _quantile(v, .25), "median": _quantile(v, .5), "q3": _quantile(v, .75), "max": v[-1]}


def outliers(values):
    """Indexes of values outside the Tukey fences (1.5 x IQR); fewer than four values are never called outliers."""
    idx = [i for i, x in enumerate(values) if x is not None and math.isfinite(x)]
    if len(idx) < 4:
        return []
    q = quartiles(values)
    iqr = q["q3"] - q["q1"]
    lo, hi = q["q1"] - 1.5 * iqr, q["q3"] + 1.5 * iqr
    return [i for i in idx if values[i] < lo - 1e-12 or values[i] > hi + 1e-12]


def mean_rank_order(ranks, ncol):
    """Column indexes by mean rank over the rows, best first; a column with no rank goes last (ties keep their order)."""
    sums, cnt = [0.0] * ncol, [0] * ncol
    for row in ranks:
        for j in range(ncol):
            if row[j] is not None:
                sums[j] += row[j]
                cnt[j] += 1
    return sorted(range(ncol), key=lambda j: (sums[j] / cnt[j] if cnt[j] else math.inf, j))


# ------------------------------------------------------------------------------------------------ rendering
def esc(value):
    return html.escape("" if value is None else str(value), quote=True)


def _json(payload):
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _r6(x):
    return None if x is None else float(f"{x:.6g}")


STATUS_TEXT = {
    "no_direction": "direction not defined: not shaded",
    "too_few": "fewer than 2 tools assessed: not shaded",
    "all_tied": "every assessed tool is tied: not shaded",
}


def row_status_text(status):
    return STATUS_TEXT.get(status, "")


def _tip(m):
    way = {"higher": "higher is better", "lower": "lower is better"}.get(m["dir"], "not defined, so the row is not shaded")
    bits = [m["def"] or "No definition is recorded for this metric.", f"Direction: {way}."]
    if m["unit"]:
        bits.append(f"Unit: {m['unit']}.")
    if m["src"]:
        bits.append(f"Source: {m['src']}.")
    return " ".join(bits)


def build(cid, title, groups, columns, cells, table_html="", lead="", samples_link="", label=None, assumptions="", fold_title="Table",
          isolate_href=None):
    """The component as HTML.

    cid          unique id of this component on the page (letters, digits, hyphens)
    groups       [{"title": str, "metrics": [metric(...)]}]  (rows, in groups)
    columns      [column(...)]                               (tools)
    cells        {(metric_id, column_id): cell(...)}         (a missing key is shown as not reported)
    table_html   the original table, kept in the closed Table fold (empty: the fold is left out)
    label        function mapping a column label to its reader-facing name (for tool ids); applied to labels only
    isolate_href function(isolate) -> href of that isolate's row, or None
    """
    cid = re.sub(r"[^A-Za-z0-9-]", "-", cid)
    cols = [dict(c, label=(label(c["label"]) if label else c["label"])) for c in columns]
    samples, sidx = [], {}
    metric_rows, jgroups = [], []
    for g in groups:
        mj = []
        for m in g["metrics"]:
            mj.append({k: m[k] for k in ("id", "name", "def", "dir", "unit", "src", "reg", "ev", "lim", "shown", "note") if m.get(k)} | {"id": m["id"], "name": m["name"]})
            metric_rows.append((g["title"], m))
        jgroups.append({"t": g["title"], "m": mj})
    jcells = {}
    for _grp, m in metric_rows:
        row = []
        for c in cols:
            cl = cells.get((m["id"], c["id"]))
            if cl is None:
                cl = cell("not reported", None, na="not reported for this tool")
            pairs = []
            for k, v in cl["iso"].items():
                if k not in sidx:
                    sidx[k] = len(samples)
                    samples.append(k)
                pairs.append([sidx[k], _r6(v)])
            rec = [cl["disp"], _r6(cl["v"]), cl["n"], _r6(cl["lo"]), _r6(cl["hi"]), pairs, cl["na"]]
            while rec and rec[-1] in (None, "", []):
                rec.pop()
            row.append(rec)
        jcells[m["id"]] = row
    payload = {"id": cid, "title": title, "cols": cols, "groups": jgroups, "samples": samples, "cells": jcells}
    if isolate_href:
        payload["links"] = [isolate_href(s) for s in samples]
    # ---- the static grid
    head = ["<tr><th class='ct-corner' scope='col'>Metric</th>"]
    for j, c in enumerate(cols):
        sub = " · ".join(x for x in (c["track"], c["task"]) if x)
        head.append(f"<th scope='col' class='ct-col' data-c='{j}'>"
                    f"<button type='button' class='ct-tool' data-ct-tool='{j}' title='Open the profile of {esc(c['label'])}'>{esc(c['label'])}</button>"
                    f"{f'<span class=ct-sub>{esc(sub)}</span>' if sub else ''}</th>")
    head.append("</tr>")
    body, ncols = [], len(cols) + 1
    best_total = 0
    for g in groups:
        gid = f"{cid}-g{len(body)}"
        body.append(f"<tr class='ct-grp'><th colspan='{ncols}' scope='colgroup'>"
                    f"<button type='button' class='ct-gbtn' aria-expanded='true' data-ct-g='{esc(g['title'])}'>"
                    f"<span class='ct-caret' aria-hidden='true'></span>{esc(g['title'])}</button></th></tr>")
        for m in g["metrics"]:
            vals = [(cells.get((m["id"], c["id"])) or {}).get("v") for c in cols]
            rs = rank_shade(vals, m["dir"])
            note = row_status_text(rs["status"])
            way = {"higher": "higher is better", "lower": "lower is better"}.get(m["dir"], "direction not defined")
            tds = []
            for j, c in enumerate(cols):
                cl = cells.get((m["id"], c["id"])) or cell("not reported", None, na="not reported for this tool")
                cls, aria = ["ct-c"], []
                if cl["na"]:
                    cls.append("ct-na")
                    aria.append(f"not assessed: {cl['na']}")
                elif cl["v"] is None:
                    cls.append("ct-flat")
                    aria.append("text, not ranked")
                elif rs["bucket"][j] is not None:
                    cls.append(f"ct-s{rs['bucket'][j]}")
                    aria.append(f"rank {rs['rank'][j]:g} of {rs['m']}")
                else:
                    cls.append("ct-flat")
                mark = ""
                if rs["best"][j]:
                    cls.append("ct-best")
                    mark = "<span class='ct-star' aria-hidden='true' title='Best in row'>★</span>"
                    aria.append("best in row")
                    best_total += 1
                text = esc(cl["disp"])
                if cl["na"] and not cl["disp"]:
                    text = "–"
                hover = f" title='{esc(cl['na'])}'" if cl["na"] and cl["na"] != "not reported" else ""
                if len(cl["disp"]) > 24:
                    cls.append("ct-long")
                tds.append(f"<td class='{' '.join(cls)}' data-c='{j}'{hover}>{mark}{text}</td>")
            unit = f" <span class='ct-unit'>{esc(m['unit'])}</span>" if m["unit"] else ""
            arrow = {"higher": "▲", "lower": "▼"}.get(m["dir"], "")
            arrow_html = f"<span class='ct-dir' title='{esc(way)}'>{arrow}</span>" if arrow else ""
            status = f"<span class='ct-rowstat' data-ct-stat>{esc(note)}</span>" if note else "<span class='ct-rowstat' data-ct-stat></span>"
            body.append(f"<tr class='ct-row' data-m='{esc(m['id'])}' data-g='{esc(g['title'])}' data-dir='{esc(m['dir'] or '')}'>"
                        f"<th scope='row' class='ct-m'><button type='button' class='ct-mname' data-ct-metric='{esc(m['id'])}'>{esc(m['name'])}</button>{unit}"
                        f"{arrow_html}{status}</th>"
                        + "".join(tds) + "</tr>")
    n_metrics = sum(len(g["metrics"]) for g in groups)
    summary = f"{n_metrics} metrics by {len(cols)} tools"
    legend = ("<p class='ct-legend'><span class='ct-ramp' aria-hidden='true'></span> Worst &rarr; Median &rarr; Best <span class='ct-legend-x'>within each row. "
              "Cells are shaded by their <strong>rank</strong> among the tools assessed in that row, not by raw value; tied tools share a rank. "
              "<span class='ct-hatch' aria-hidden='true'></span> hatched: not assessed or missing, never shaded and never zero. A row with no defined direction, with fewer "
              "than two assessed tools, or in which every tool ties is left unshaded and says why. &#9733; best in row. &#9650; higher is better, &#9660; lower is better."
              f"{' ' + esc(assumptions) if assumptions else ''}</span></p>")
    fold = (f"<details class='ct-fold rpt-collapsible' data-closed='1'><summary>{esc(fold_title)}</summary>{table_html}</details>" if table_html else "")
    help_btn = (f"<span class='rpt-help'><button type='button' class='rpt-help-btn' data-help='{HELP_KEY}' aria-haspopup='dialog' "
                f"aria-label='Help: about the comparison table' title='Help: what this shows and how to read it'>?</button></span>")
    page = (f"<div class='ct' id='ct-{esc(cid)}' data-ct='{esc(cid)}'>"
            f"<div class='ct-head'><strong class='ct-title'>{esc(title)}</strong> <span class='ct-count'>{esc(summary)}</span>{help_btn}</div>"
            f"{f'<p class=ct-lead>{lead}</p>' if lead else ''}"
            f"<div class='ct-main'><div class='ct-scroll' tabindex='0' aria-label='{esc(title)}: scrollable comparison table'>"
            f"<table class='ct-grid' role='grid' aria-label='{esc(title)}: {esc(summary)}, shaded by rank within each row' aria-rowcount='{n_metrics + 1}' "
            f"aria-colcount='{len(cols) + 1}'><thead>{''.join(head)}</thead><tbody>{''.join(body)}</tbody></table></div>"
            f"<aside class='ct-panel' hidden aria-label='Details' tabindex='-1'></aside></div>"
            f"{legend}{fold}"
            f"<script type='application/json' class='ct-data'>{_json(payload)}</script></div>")
    return page


def finish(page):
    """Add the style and the scripts once, when the page holds a comparison table (and not again if they are already there)."""
    if "class='ct'" not in page or "id='ct-assets'" in page:
        return page
    parts = []
    for name in ASSETS:
        with open(os.path.join(ROOT, "assets", "report", name), encoding="utf-8", newline="") as handle:
            parts.append(handle.read())
    block = "<div id='ct-assets' hidden></div>" + "".join(parts)
    cut = page.rfind("</body>")
    return page[:cut] + block + page[cut:] if cut >= 0 else page + block


def static_table(columns, groups, cells):
    """A plain table of the same cells (used by tests and by callers with no table of their own): header row of tools, one row per metric."""
    head = "".join(f"<th>{esc(c['label'])}</th>" for c in columns)
    rows = []
    for g in groups:
        for m in g["metrics"]:
            rows.append(f"<tr><th>{esc(m['name'])}</th>" + "".join(f"<td>{esc((cells.get((m['id'], c['id'])) or cell('not reported', None, na='x'))['disp'])}</td>"
                                                                     for c in columns) + "</tr>")
    return f"<div class='panel'><table class='sortable'><thead><tr><th>Metric</th>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


# ------------------------------------------------------------------------------------------------ from rows of a table
def scores_iso(scores, track, tool, column, transform=None):
    """{isolate: value} of one scores.tsv column for one tool in one track (a blank is left out, never zero)."""
    out = {}
    for r in scores or []:
        if r.get("tool") != tool or (track and (r.get("analysis_track") or "short_read") != track):
            continue
        v = num(r.get(column))
        if v is not None:
            out[r.get("sample", "")] = transform(v) if transform else v
    return out


def from_rows(cid, title, rows, specs, col_id=lambda r: r.get("tool", ""), col_label=lambda r: r.get("tool", ""), col_track=lambda r: "", col_task=lambda r: "",
              table_html="", label=None, lead="", assumptions="", isolate_href=None, fold_title="Table"):
    """Build a component from one dict per tool (a row of the source table) and a list of metric specs.

    spec keys: group, id, name, and `get` (a key of the row, or a function row -> text) for the text shown, which is the text the source table shows;
    optional `value` (function row -> number; default: the shown text parsed), `dir` ('auto' reads the registry through source/column/registry_id),
    source, column, registry_id, definition, unit, note, `n` (key or function row -> isolates), `lo`/`hi` (key or function: the interval),
    `iso` (function row -> {isolate: value}). A text that is not a number (for example 'not bin-scored') is a cell that was not assessed: hatched, never shaded.
    """
    cols = [column(col_id(r), col_label(r), col_track(r), col_task(r)) for r in rows]
    groups, order = {}, []
    cells = {}
    for sp in specs:
        if sp["group"] not in groups:
            groups[sp["group"]] = []
            order.append(sp["group"])
        m = metric(sp["id"], sp["name"], sp.get("definition", ""), sp.get("dir", "auto"), sp.get("unit", ""), sp.get("source", ""), sp.get("column", ""),
                   sp.get("registry_id"), sp.get("note", ""))
        groups[sp["group"]].append(m)

        def pull(r, key):
            return key(r) if callable(key) else (r.get(key) if key else None)

        for r, c in zip(rows, cols):
            shown = pull(r, sp["get"])
            shown = "" if shown is None else str(shown)
            val = sp["value"](r) if sp.get("value") else num_display(shown)
            na = "" if (val is not None or sp.get("text")) else (shown if shown not in ("", "-") else "not reported")
            n = pull(r, sp.get("n"))
            cells[(sp["id"], c["id"])] = cell(shown, val, n=int(num(n)) if num(n) is not None else None, lo=pull(r, sp.get("lo")), hi=pull(r, sp.get("hi")),
                                              iso=sp["iso"](r) if sp.get("iso") else None, na=na)
    return build(cid, title, [{"title": g, "metrics": groups[g]} for g in order], cols, cells, table_html=table_html, lead=lead, label=label,
                 assumptions=assumptions, isolate_href=isolate_href, fold_title=fold_title)
