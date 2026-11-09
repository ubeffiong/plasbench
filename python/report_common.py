#!/usr/bin/env python3
"""
report_common.py -- shared building blocks for the report modules added in the HTML overhaul.

  esc / read_tsv / read_json / number / mean / fmt   tolerant readers and formatting (a blank is None, never 0)
  missing(reason)           a cell that is not available, with the reason visible and readable by screen readers
  not_run(reason)           a section-level "Not run: <reason>" note
  band_chip(band)           an Excellent / Good / Moderate / Poor chip that says the word and carries a shape
  panel / section / note    HTML scaffolding in the report's existing classes
  STYLE                     the extra CSS the new sections need (one block, injected once)
  inject_sections           put sections before the Recommendations section and add grouped nav links

Standard library only.
"""
import csv
import html
import json
import os

BANDS = ("excellent", "good", "moderate", "poor")
BAND_LABELS = {"excellent": "Excellent", "good": "Good", "moderate": "Moderate", "poor": "Poor"}
BAND_GLYPH = {"excellent": "●", "good": "◐", "moderate": "▲", "poor": "■"}   # circle, half circle, triangle, square


class Raw(str):
    """A string that is already HTML (not escaped again by panel())."""


def esc(value):
    return html.escape(str(value), quote=True)


def read_tsv(path):
    """Rows of a tab-separated file, or None when it is absent (so callers can say 'Not run'), skipping # comments."""
    if not path or not os.path.isfile(path):
        return None
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader((line for line in handle if line.strip() and not line.startswith("#")), delimiter="\t"))


def read_json(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def number(value):
    """float or None for blank / non-numeric text (a blank is undefined, never zero)."""
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def fmt(value, digits=3, empty=None):
    if value is None:
        return empty if empty is not None else missing("not available")
    return f"{value:.{digits}f}"


def missing(reason, short="—"):
    """A visible dash that carries its reason: hover text for everyone, hidden text for screen readers."""
    return Raw(f"<span class='rpt-missing' title='{esc(reason)}'>{esc(short)}<span class='rpt-sr'> ({esc(reason)})</span></span>")


def not_run(reason):
    return Raw(f"<div class='insight caution'><p><strong>Not run:</strong> {esc(reason)}</p></div>")


def note(message, tone="caution"):
    return Raw(f"<div class='insight {esc(tone)}'><p>{esc(message)}</p></div>")


def band_chip(band, detail=""):
    """The word, a shape and a colour: a band is never colour alone. `detail` is appended (for example a threshold)."""
    if band not in BANDS:
        return missing("not graded")
    extra = f"<span class='rpt-band-detail'>{esc(detail)}</span>" if detail else ""
    return Raw(f"<span class='rpt-band rpt-band-{band}'><span aria-hidden='true'>{BAND_GLYPH[band]}</span> {BAND_LABELS[band]}</span>{extra}")


def cell(value):
    return value if isinstance(value, Raw) else esc(value)


def panel(headers, rows, empty="Nothing to report.", sortable=True, extra_class=""):
    """A table in the report's panel style. Cells that are Raw HTML are kept; everything else is escaped."""
    if not rows:
        return Raw(f"<div class='panel'><p style='padding:12px'>{esc(empty)}</p></div>")
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell(c)}</td>" for c in row) + "</tr>" for row in rows)
    cls = ("sortable " if sortable else "") + extra_class
    return Raw(f"<div class='panel'><table class='{cls.strip()}'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>")


def section(sid, title, lead, body, group=""):
    attr = f" data-nav-group='{esc(group)}'" if group else ""
    return Raw(f"<section id='{esc(sid)}'{attr}><h2>{esc(title)}</h2><p class='lead'>{lead}</p>{body}</section>")


STYLE = """
.rpt-missing{color:var(--muted);cursor:help}
.rpt-sr{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden}
.rpt-band{display:inline-block;padding:2px 8px;border-radius:12px;font:bold 11px Arial,sans-serif;white-space:nowrap;border:2px solid}
.rpt-band-excellent{background:#dcefdc;color:#07573e;border-color:#17805a}
.rpt-band-good{background:#e4eef8;color:#17457e;border-color:#2563c9}
.rpt-band-moderate{background:#f6ead1;color:#765000;border-color:#a35c05}
.rpt-band-poor{background:#f7ddda;color:#8c2018;border-color:#b3261e}
.rpt-band-detail{margin-left:6px;font:11px Arial,sans-serif;color:var(--muted)}
.rpt-figure{background:#fff;border:1px solid var(--line);padding:12px;margin:12px 0}
.rpt-figure svg{display:block;width:100%;height:auto;max-width:880px;margin:auto}
.rpt-figure figcaption{font:12px Arial,sans-serif;color:var(--muted);margin-top:8px}
.rpt-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}
.rpt-legend{display:flex;flex-wrap:wrap;gap:6px 16px;font:12px Arial,sans-serif;margin:8px 0}
.rpt-legend i{display:inline-block;width:12px;height:12px;margin-right:5px;vertical-align:-2px;border:1px solid #0003}
.rpt-chips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.rpt-chips label{font:12px Arial,sans-serif;border:1px solid var(--line);border-radius:14px;padding:3px 10px;background:#fff;cursor:pointer}
.rpt-chips input{margin-right:4px}
.rpt-scorecard td,.rpt-scorecard th{white-space:normal}
.rpt-bar{display:inline-block;height:8px;background:var(--green);border-radius:2px;vertical-align:middle}
.rpt-navgroups{display:flex;flex-wrap:wrap;gap:6px 14px;font:13px Arial,sans-serif}
.rpt-navgroups details{background:#fff;border:1px solid var(--line);border-radius:8px;padding:2px 10px}
.rpt-navgroups summary{cursor:pointer;font-weight:bold;padding:4px 0}
.rpt-navgroups a{display:block;padding:2px 0;color:var(--muted);text-decoration:none}
.rpt-collapsible{margin:8px 0}
.rpt-collapsible>summary{cursor:pointer;font:bold 13px Arial,sans-serif;padding:8px 12px;background:#fff;border:1px solid var(--line);border-radius:8px;list-style-position:inside}
.rpt-collapsible[open]>summary{margin-bottom:8px}
@media print{.rpt-chips,.rpt-navgroups{display:none}.rpt-figure{break-inside:avoid}}
/* info popovers (python/report_info.py, assets/report/info_script.html): a quiet circled i that carries a note */
.rpt-info{position:relative;display:inline-block;margin-left:.45em;vertical-align:middle;font-weight:400;font-style:normal;text-transform:none;letter-spacing:normal;float:none!important}
.rpt-info-btn{box-sizing:border-box;width:17px;height:17px;min-width:17px;padding:0;margin:0;border:1px solid #7b8a80;border-radius:50%;background:transparent;color:#4f5f55;font:italic 700 11px/15px Georgia,'Times New Roman',serif;text-align:center;cursor:help;vertical-align:1px}
.rpt-info-btn:hover,.rpt-info-btn:focus-visible,.rpt-info.rpt-show .rpt-info-btn{background:var(--ink,#17231d);border-color:var(--ink,#17231d);color:#fff}
.rpt-info-btn:focus-visible{outline:2px solid #0072B2;outline-offset:2px}
.rpt-info-pop{float:none;position:absolute;left:0;top:calc(100% + 6px);z-index:1000;box-sizing:border-box;width:max-content;max-width:min(420px,90vw);padding:10px 13px;background:#fff;color:#17231d;border:1px solid #9fb0a5;border-radius:8px;box-shadow:0 6px 22px rgba(21,36,28,.22);font:400 13px/1.5 Arial,Helvetica,sans-serif;font-style:normal;text-align:left;text-transform:none;letter-spacing:normal;white-space:normal;visibility:hidden;opacity:0;pointer-events:none}
.rpt-info-pop::before{content:'';position:absolute;left:0;right:0;top:-9px;height:9px}
.rpt-info-pop.rpt-up::before{top:auto;bottom:-9px}
.rpt-info-pop a{color:#0a5a41;text-decoration:underline}
.rpt-info-pop code{font:12px Consolas,Menlo,monospace;background:#eef2ee;padding:0 3px;border-radius:3px}
.rpt-info-para{display:block}.rpt-info-para+.rpt-info-para{margin-top:8px}
.rpt-info:hover>.rpt-info-pop,.rpt-info:focus-within>.rpt-info-pop,.rpt-info.rpt-show>.rpt-info-pop{visibility:visible;opacity:1;pointer-events:auto}
:root.rpt-js .rpt-info-pop{position:fixed;left:0;top:0}
:root.rpt-js .rpt-info:not(.rpt-show)>.rpt-info-pop{visibility:hidden;opacity:0;pointer-events:none}
details summary .rpt-info{float:none;font-size:13px}
figcaption .rpt-info{margin-left:0}
@media (prefers-reduced-motion:no-preference){.rpt-info-pop{transition:opacity .12s ease-out}.rpt-info-btn{transition:background-color .12s,color .12s}}
@media print{.rpt-info{display:block;margin:2px 0 0}.rpt-info-btn{display:none!important}.rpt-info-pop,:root.rpt-js .rpt-info-pop{position:static!important;visibility:visible!important;opacity:1!important;pointer-events:auto;width:auto;max-width:none;padding:0;border:0;box-shadow:none;background:none;color:var(--muted,#627067);font:400 13px/1.5 Georgia,'Times New Roman',serif}.rpt-info-pop::before{display:none}}
"""


def inject_sections(page, sections_html, nav_links, anchor="<section id='recommendations'>",
                    nav_anchor="<a href='#recommendations'>Recommendations</a>"):
    """Insert sections before `anchor` and nav links before `nav_anchor`; the page is returned unchanged if the anchor is absent."""
    if anchor not in page:
        return page
    page = page.replace(anchor, sections_html + anchor, 1)
    links = "".join(f"<a href='#{esc(sid)}'>{esc(label)}</a>" for sid, label in nav_links)
    return page.replace(nav_anchor, links + nav_anchor, 1)


def add_style(page):
    """Add STYLE once, just before the closing </style> of the page's first style block."""
    if "rpt-missing" in page.split("</style>", 1)[0]:
        return page
    return page.replace("</style>", STYLE + "</style>", 1)
