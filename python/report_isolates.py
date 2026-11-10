#!/usr/bin/env python3
"""
report_isolates.py -- the isolate filter, and "which tool recovered which plasmid".

The Summary and the Scorecard used to show cohort-wide numbers only, so they could not say which tool did better on which isolate or which plasmid.
This module adds, once, after the scorecard sections exist:

  * a "Which tool recovered which plasmid" matrix in the Summary: one row per truth plasmid, one column per tool, each cell the share of that plasmid
    the tool covered (a tick, half circle or cross as well as the number, never colour alone), the best tool marked with a star, and a footer row that
    counts the plasmids each tool recovered (>= 90% covered) and the plasmids on which it was best. One matrix per analysis track (never pooled);
  * an isolate filter in the top bar (default "All isolates"): choosing one isolate swaps four views to that isolate's own numbers: the report-card
    table, the scorecard overall table, the whole Scorecard (every metric re-scored on that isolate alone) and the plasmid matrix;
  * a scope label next to each of those headings, so a printed page says which isolate it shows.

The default (and the no-JavaScript view, and the print view) is "All isolates": the cohort-wide content already on the page. The per-isolate content is
rendered here in Python (the same functions that render the cohort view, applied to one isolate's rows) and kept in <template> elements inside the
Summary section; assets/report/isolates_script.html copies a template into its slot when the filter changes. Nothing is computed in the browser.

  matrix_html(rows, label, downloads)   the plasmid matrix for per-plasmid rows (dicts from report_wiring.per_plasmid_rows); `downloads` maps an isolate to
                                        the relative path of its selected reconstruction FASTA (or None): see DOWNLOAD BUTTON below
  isolate_report_cards(...)             the report-card rows for one isolate (the same report_cards() the cohort card uses)
  build(...)                            {isolate: {slot: html}}, the isolate list and the "All isolates" matrix
  inject(page, results_dir, data_dir, scores_path, ...)

Standard library only.
"""
import html
import json
import os
import re

import report_common as rc
import report_scorecard as sc
import report_wiring as rw

COMPLETE = 0.90          # a plasmid with at least this share covered counts as recovered (the pipeline's graded-recovery threshold)
PARTIAL = 0.50
SLOTS = ("summary-card", "summary-scorecard", "scorecard", "plasmid-matrix")
MATRIX_HEADING = "<h3 id='summary-plasmids'>Which tool recovered which plasmid <span class='pb-scope' data-iso-scope>All isolates</span></h3>"
MATRIX_LEAD = ("<p class='lead'>One row per truth plasmid, one column per tool: the share of that plasmid the tool covered. A tick means at least 90% "
               "covered (recovered), a half circle 50 to 90%, a cross under 50%, a dash that the tool produced no result for it. A star marks the best "
               "tool for the plasmid. Coverage of the truth sequence is alignment-derived; it does not say the plasmid was assembled in one piece, "
               "ordered or oriented correctly (see the reconstruction ladder). Choose an isolate in the top bar to see one isolate's plasmids; "
               "the default is all isolates.</p>")


def _esc(value):
    return html.escape(str(value), quote=True)


def _num(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def download_button(isolate, href):
    """A small button in the Isolate cell: download the isolate's best reconstructed plasmid(s), the selected candidate FASTA.

    With a path (the file exists in the results folder the report was built from) the button is a link; assets/report/download_script.html checks, when the page opens,
    that the file can be reached from where the page is open, and greys the button out when it cannot (the report was copied away from its results folder).
    With no path (no selected reconstruction was produced for the isolate) it is grey from the start."""
    name = _esc(isolate)
    icon = "<svg viewBox='0 0 12 12' width='11' height='11' aria-hidden='true'><path d='M6 1v6.5M3 5l3 3 3-3M1.5 10.5h9' fill='none' stroke='currentColor' stroke-width='1.6'/></svg>"
    if not href:
        return (f"<span class='pb-dl pb-dl-off' aria-disabled='true' role='link' title='No selected reconstruction was produced for {name}.'>{icon}<span>FASTA</span></span>")
    return (f"<a class='pb-dl' href='{_esc(href)}' download data-pb-dl='{_esc(href)}' title='Download the best reconstructed plasmid(s) of {name} (the selected candidate, FASTA)' "
            f"aria-label='Download the best reconstructed plasmid of {name}'>{icon}<span>FASTA</span></a>")


def _cls(completeness):
    if completeness is None:
        return "pb-none", "–", "no result"
    if completeness >= COMPLETE:
        return "pb-good", "✓", "recovered (at least 90% covered)"
    if completeness >= PARTIAL:
        return "pb-part", "◐", "partly covered (50 to 90%)"
    return "pb-miss", "✕", "mostly missed (under 50% covered)"


def humanise(markup, labels):
    """Tool ids in the text of `markup` (not in attributes) replaced by their reader-facing names (the page script cannot reach <template> content)."""
    if not labels:
        return markup
    names = sorted(labels, key=len, reverse=True)
    pattern = re.compile(r"(?<![A-Za-z0-9_-])(" + "|".join(re.escape(n) for n in names) + r")(?![A-Za-z0-9_-])")
    return re.sub(r">([^<>]+)<", lambda m: ">" + pattern.sub(lambda t: labels[t.group(1)], m.group(1)) + "<", markup)


def matrix_html(rows, label=lambda tool: tool, downloads=None):
    """The plasmid matrix (one table per analysis track) for per-plasmid `rows`; a visible Not run note when there are none."""
    rows = [r for r in rows if r.get("tool") and r.get("plasmid")]
    if not rows:
        return str(rc.not_run("no <sample>/<tool>.per_plasmid.tsv for this selection (the scoring stage writes it), so the per-plasmid results are not available."))
    out = []
    for track in sorted({r.get("track") or "unspecified" for r in rows}):
        sub = [r for r in rows if (r.get("track") or "unspecified") == track]
        tools = sorted({r["tool"] for r in sub})
        plasmids = sorted({(r["sample"], r["plasmid"]) for r in sub})
        length = {}
        cover = {}
        for r in sub:
            key = (r["sample"], r["plasmid"])
            length[key] = r.get("length", "")
            cover[(key, r["tool"])] = r
        best_on = {t: 0 for t in tools}
        recovered = {t: 0 for t in tools}
        body = []
        for key in plasmids:
            values = {t: _num((cover.get((key, t)) or {}).get("completeness")) for t in tools}
            top = max((v for v in values.values() if v is not None), default=None)
            winners = [t for t, v in values.items() if top is not None and top > 0 and v is not None and abs(v - top) < 1e-9]
            cells = []
            for t in tools:
                v = values[t]
                klass, glyph, words = _cls(v)
                if v is not None and v >= COMPLETE:
                    recovered[t] += 1
                star = ""
                if t in winners:
                    best_on[t] += 1
                    star = "<span class='pb-star' title='best tool for this plasmid'>★</span>"
                row = cover.get((key, t)) or {}
                outcome = row.get("outcome") or ""
                text = "–" if v is None else f"{v:.0%}"
                tip = f"{key[1]} in {key[0]}: {label(t)} {('covered ' + text) if v is not None else 'no result'} ({words})" + (f", outcome {outcome}" if outcome else "")
                cells.append(f"<td class='pb-c {klass}' title='{_esc(tip)}' data-v='{'' if v is None else f'{v:.4f}'}'>"
                             f"<span aria-hidden='true'>{glyph}</span> {_esc(text)}{star}"
                             f"<span class='rpt-sr'> ({_esc(words)}{', best tool' if t in winners else ''})</span></td>")
            with_result = [t for t, v in values.items() if v is not None]
            if winners:
                if len(winners) > 2 and len(winners) == len(with_result):
                    best = f"all {len(winners)} tools tie"
                else:
                    best = ", ".join(label(t) for t in winners) + (" (tie)" if len(winners) > 1 else "")
            else:
                best = "none recovered it" if any(v is not None for v in values.values()) else "no result"
            button = download_button(key[0], downloads.get(key[0])) if downloads is not None else ""
            body.append(f"<tr><td>{_esc(key[0])}{button}</td><td><strong>{_esc(key[1])}</strong></td><td class='rpt-num'>{_esc(length.get(key, ''))}</td>"
                        + "".join(cells) + f"<td>{_esc(best)}</td></tr>")
        total = len(plasmids)
        head = ("<tr><th>Isolate</th><th>Plasmid</th><th>Length (bp)</th>" + "".join(f"<th>{_esc(label(t))}</th>" for t in tools) + "<th>Best tool</th></tr>")
        foot = (f"<tr><th colspan='3'>Plasmids recovered (at least 90% covered), of {total}</th>"
                + "".join(f"<td><strong>{recovered[t]}</strong> of {total}</td>" for t in tools) + "<td></td></tr>"
                f"<tr><th colspan='3'>Plasmids on which the tool was best</th>" + "".join(f"<td>{best_on[t]}</td>" for t in tools) + "<td></td></tr>")
        out.append(f"<h4>Analysis track: {_esc(track)}</h4><div class='panel'><table class='pb-matrix rpt-nowindow'><thead>{head}</thead>"
                   f"<tbody>{''.join(body)}</tbody><tfoot>{foot}</tfoot></table></div>")
    return "".join(out)


def isolate_report_cards(report_cards, scores, status, isolate):
    """The report-card cards for one isolate: the same report_cards() the cohort card uses, fed this isolate's rows as a one-sample leaderboard."""
    rows = [r for r in scores if r.get("sample") == isolate]
    done = {(r.get("sample"), r.get("tool")): (r.get("status") or "") for r in status}
    by_tool = {}
    for r in rows:
        by_tool.setdefault(r["tool"], []).append(r)
    leaderboard = []
    for tool, trs in sorted(by_tool.items()):
        f1 = [_num(r.get("f1")) for r in trs if _num(r.get("f1")) is not None]
        rec = [_num(r.get("plasmid_recall")) for r in trs if _num(r.get("plasmid_recall")) is not None]
        state = done.get((isolate, tool), "completed")
        leaderboard.append({"tool": tool, "n_samples": "1", "n_completed": "1" if state in ("completed", "reused", "") else "0",
                            "mean_f1": "" if not f1 else str(sum(f1) / len(f1)), "mean_plasmid_recall": "" if not rec else str(sum(rec) / len(rec))})
    cards = report_cards(leaderboard, rows)
    return sorted(cards, key=lambda c: (c["composite"] is None, -(c["composite"] or 0)))


def selected_fasta(results_dir, isolate):
    """The path, relative to the report (which sits in the results folder), of the isolate's selected reconstruction FASTA, or None when none was written."""
    relative = f"selected_candidates/{isolate}/{isolate}.candidate.plasmid.fasta"
    return relative if os.path.isfile(os.path.join(results_dir, *relative.split("/"))) else None


def build(results_dir, data_dir, scores_path, specs, report_cards, grade_rows_html, label, inputs=None):
    """({isolate: {slot: html}}, [isolate ids], the 'All isolates' matrix) from the files of one run."""
    inp = inputs or sc.Inputs(results_dir, scores_path)
    scores = inp.scores or []
    isolates = sorted({r["sample"] for r in scores if r.get("sample")})
    status = rc.read_tsv(os.path.join(results_dir, "tool_status.tsv")) or []
    per_plasmid = rw.per_plasmid_rows(results_dir, data_dir)
    tools = sorted({r["tool"] for r in scores if r.get("tool")} | {r["tool"] for r in per_plasmid})
    labels = {t: label(t) for t in tools}
    downloads = {iso: selected_fasta(results_dir, iso) for iso in isolates}
    slots = {}
    for iso in isolates:
        per_tool = sc.metric_values(results_dir, scores_path, samples=[iso], inputs=inp)
        cards = isolate_report_cards(report_cards, scores, status, iso)
        slots[iso] = {
            "summary-card": humanise(grade_rows_html(cards) or "<tr><td colspan='6'>No scored tool for this isolate.</td></tr>", labels),
            "summary-scorecard": humanise(sc.summary_table(specs, per_tool), labels),
            "scorecard": humanise(sc.scorecard_body(specs, per_tool), labels),
            "plasmid-matrix": matrix_html([r for r in per_plasmid if r["sample"] == iso], label, downloads),
        }
    return slots, isolates, matrix_html(per_plasmid, label, downloads), per_plasmid


def _asset(name):
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "report", name)
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def inject(page, results_dir, data_dir, scores_path, config_path=None, report_cards=None, grade_rows_html=None, label=None):
    """Add the plasmid matrix and the isolate filter. Unchanged when the page has no Summary report card, or no scorecard configuration."""
    if "data-iso-slot='summary-card'" not in page or report_cards is None or grade_rows_html is None:
        return page
    label = label or (lambda tool: tool)
    try:
        specs = sc.load_config(config_path)
    except ValueError:
        return page
    slots, isolates, all_matrix, per_plasmid = build(results_dir, data_dir, scores_path, specs, report_cards, grade_rows_html, label)
    if not isolates:
        return page
    plasmid_counts = {iso: len({r["plasmid"] for r in per_plasmid if r["sample"] == iso}) for iso in isolates}
    payload = {"isolates": [{"id": iso, "plasmids": plasmid_counts[iso]} for iso in isolates]}
    # the matrix goes in the Summary, above the report card; the all-isolates content is what the page shows until a filter is chosen
    block = MATRIX_HEADING + MATRIX_LEAD + f"<div data-iso-slot='plasmid-matrix'>{all_matrix}</div>"
    anchor = "<h3>Report card"
    if anchor not in page:
        return page
    page = page.replace(anchor, block + anchor, 1)
    templates = "".join(f"<template data-iso-for='{_esc(iso)}' data-iso-slot='{slot}'>{content}</template>"
                        for iso, by_slot in slots.items() for slot, content in by_slot.items())
    store = (f"<div hidden id='pb-iso-templates'><script type='application/json' id='pb-iso-data'>{json.dumps(payload).replace('</', '<' + chr(92) + '/')}</script>"
             f"{templates}</div>")
    end = page.find("</section>", page.find("<section id='summary'"))
    if end < 0:
        return page
    page = page[:end] + store + page[end:]
    page = rc.add_style(page)
    if "id='pb-iso-style'" not in page:
        style, script = _asset("isolates_style.html") + _asset("download_style.html"), _asset("isolates_script.html") + _asset("download_script.html")
        if "</head>" in page:
            h = page.index("</head>")
            page = page[:h] + style + page[h:]
        else:
            page = style + page
        body_end = page.rfind("</body>")
        page = (page[:body_end] + script + page[body_end:]) if body_end >= 0 else page + script
    return page
