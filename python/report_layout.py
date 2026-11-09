#!/usr/bin/env python3
"""
report_layout.py -- the report's page shell: top bar, left rail of views, one view at a time, analytics in story order.

A post-processing step, run once on the finished page (after report_wiring.finish, before report_info). The page has ~70 sections in one very
long column; this step re-orders and wraps them, it never rewrites them:

  * VIEWS      the sections are grouped into views, shown one at a time (hash routing: #view-<id>, or any #<section-id> opens the view that holds it);
               order: Overview -> Scorecard -> Figures -> Plasmid maps -> Diagnostics -> Data quality -> Recommendation -> Methods and limits -> Appendix.
               A section id that no view lists goes to a final "More" view, so nothing disappears.
  * SHELL      a fixed top bar (name, run, shown view, search, colour-blind palette, Print / Save PDF, Expand all), a fixed left rail of the views
               (icons and short labels, collapsible, remembered), a compact title band with the KPI chips that were already in the page.
  * CARDS      the dense views (diagnostics, data quality, ...) show each section as a closed accordion card with a one-line status chip computed from
               the section itself (table rows, "Not run", flag boxes, pass/fail pills). Nothing is deleted: the section is inside the card.
  * PRINT      media print shows every view in order, each on a new page, details expanded, a cover with the contents list; see assets/report/layout_print.html
               and python/export_report_pdf.py for the headless-browser export.

Without JavaScript every view is shown, in the new order, under a plain list of links. Every <section> block is kept byte for byte (only the
text between sections moves with the section before it). The page is scanned with a small tokenizer (comments and script/style bodies skipped
whole) and edited by splicing. Running it twice changes nothing.

  VIEWS                 [(view id, title, rail label, icon, blurb, card mode, [section ids in order])]
  layout_plan(ids)      [(view, [ids])] for a list of section ids (pure; tested)
  status_chips(section) [(text, tone)] for an accordion card (pure; tested)
  transform(page)       the laid-out page

Standard library only.
"""
import html
import os
import re

TOKEN = re.compile(r"<!--.*?-->|<(/?)([A-Za-z][A-Za-z0-9:-]*)((?:[^>\"']|\"[^\"]*\"|'[^']*')*)>", re.S)
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
RAW_TEXT = {"script", "style", "textarea", "title"}
_CLASS = re.compile(r"""\bclass\s*=\s*(?:'([^']*)'|"([^"]*)")""")
_ID = re.compile(r"""\bid\s*=\s*(?:'([^']*)'|"([^"]*)")""")
MARKER = "class='rpt-shell'"

# id, title, rail label, icon, blurb, cards?, section ids in story order. Cards: each section a closed accordion card (the first `open` ids start open).
VIEWS = [
    ("overview", "Overview", "Overview", "grid",
     "The headline result: who leads, by how much, and how stable the ranking is.", False,
     "summary insights leaderboard chart robustness metadata"),
    ("scorecard", "Scorecard", "Scorecard", "list",
     "Every tool against every metric, by scenario, with the definitions and the statistical power behind them.", False,
     "scorecard scorecard-scenarios scorecard-definitions composite power"),
    ("figures", "Figures", "Figures", "chart",
     "The comparison drawn: reconstruction ladder, 3D landscape, heatmap, distributions, differences and precision-recall.", True,
     "fig-ladder fig-landscape fig-heatmap fig-distributions fig-forest fig-pr"),
    ("maps", "Plasmid maps", "Plasmid maps", "ring",
     "Reconstructions drawn back onto the truth plasmids: per plasmid, antimicrobial-resistance gene placement and contig layer.", True,
     "plasmid-maps per-plasmid-detail plasmid-outcomes amr-placement contig-layer selected"),
    ("diagnostics", "Statistical diagnostics", "Diagnostics", "pulse",
     "Paired tests, ranking robustness, recovery by stratum and replicon, accuracy, features, bins and runtime. Open a card for the detail.", True,
     "statistics rank-robustness stratified scenarios replicon-recovery graded-tiers accuracy-dimension feature-preservation bin-diagnostics "
     "bin-quality learn-agreement learn-copynumber learn-plsmd performance baselines-calibration scores"),
    ("quality", "Data quality", "Data quality", "shield",
     "Checks on the inputs and the runs: assemblies, cohort outliers, labels, metadata and run health. Each card carries a status; open it for the detail.", True,
     "assembly-quality learn-adequacy learn-truthqc cohort-qc isolate-difficulty truth-label-audit label-schemes metadata-completeness "
     "database-membership excluded-replicons quast-diagnostics zero-plasmid orthogonal-evidence outcome-states health samples tools"),
    ("recommendation", "Recommendation", "Recommend", "star",
     "Which method to use where, how well that advice held up on held-out data, and how it transfers.", True,
     "recommendations recommender-eval taxon-transfer validation validity"),
    ("methods", "Methods and limits", "Methods", "book",
     "What is measured, how it is scored, and what the numbers do not mean.", True,
     "metric-framework headline-design interpretation-limits prereg scoring-additions keys method scoring-spec"),
    ("appendix", "Appendix", "Appendix", "folder",
     "The interactive explorer, every file the run produced, and what was reproduced.", True,
     "enterprise appendix-reference extended reproducibility data-inventory files"),
]
MORE = ("more", "More", "More", "dots", "Sections that no view lists, kept here so nothing disappears.", True, "")
OPEN_CARDS = {"figures": ("fig-ladder",), "maps": ("plasmid-maps",), "recommendation": ("recommendations",), "appendix": ("enterprise",),
              "diagnostics": ("statistics",), "methods": ("metric-framework",)}

ICONS = {
    "grid": "<rect x='3' y='3' width='7' height='7' rx='1'/><rect x='14' y='3' width='7' height='7' rx='1'/><rect x='3' y='14' width='7' height='7' rx='1'/><rect x='14' y='14' width='7' height='7' rx='1'/>",
    "list": "<path d='M9 6h11M9 12h11M9 18h11'/><path d='M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2'/>",
    "chart": "<path d='M4 20V10M10 20V4M16 20v-7M22 20H2'/>",
    "ring": "<circle cx='12' cy='12' r='8.5'/><circle cx='12' cy='12' r='3.5'/><path d='M12 3.5v5'/>",
    "pulse": "<path d='M3 12h4l3-8 4 16 3-8h4'/>",
    "shield": "<path d='M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z'/><path d='M8.5 12l2.5 2.5 4.5-5'/>",
    "star": "<path d='M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z'/>",
    "book": "<path d='M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z'/><path d='M4 21V5M9 7h6'/>",
    "folder": "<path d='M3 7h6l2 2h10v10H3z'/>",
    "dots": "<circle cx='5' cy='12' r='1.5'/><circle cx='12' cy='12' r='1.5'/><circle cx='19' cy='12' r='1.5'/>",
    "chev": "<path d='M15 6l-6 6 6 6'/>",
}


def asset(name):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "report", name)
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def _ids(spec):
    return spec.split()


# ------------------------------------------------------------------------------------------------ tokenizer helpers
def _classes(attrs):
    m = _CLASS.search(attrs)
    return set(((m.group(1) if m.group(1) is not None else m.group(2)) or "").split()) if m else set()


def _id_of(attrs):
    m = _ID.search(attrs)
    return (m.group(1) if m.group(1) is not None else m.group(2)) if m else ""


def _skip_raw(text, name, pos):
    close = re.compile(rf"</{name}\s*>", re.I).search(text, pos)
    return close.end() if close else len(text)


def element_end(text, start):
    """Index just after the element whose open tag starts at `start` (matching close tag of the same name), or -1."""
    m = TOKEN.match(text, start)
    if not m or m.group(1) or m.group(2) is None:
        return -1
    name = m.group(2).lower()
    if name in VOID or m.group(3).rstrip().endswith("/"):
        return m.end()
    depth, i = 1, m.end()
    while True:
        m = TOKEN.search(text, i)
        if not m:
            return -1
        i = m.end()
        if m.group(2) is None:
            continue
        tag = m.group(2).lower()
        if tag in RAW_TEXT and not m.group(1):
            i = _skip_raw(text, tag, i)
            continue
        if tag != name or (tag in VOID) or m.group(3).rstrip().endswith("/"):
            continue
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return i


def find_sections(page):
    """[(id, start, end)] of the top-level <section id=...> blocks, in document order (nested sections stay inside their parent)."""
    found, depth, i, start, sid = [], 0, 0, 0, ""
    while True:
        m = TOKEN.search(page, i)
        if not m:
            return found
        i = m.end()
        if m.group(2) is None:
            continue
        name, closing = m.group(2).lower(), bool(m.group(1))
        if name in RAW_TEXT and not closing:
            i = _skip_raw(page, name, i)
            continue
        if name != "section":
            continue
        if closing:
            if depth:
                depth -= 1
                if depth == 0:
                    found.append((sid, start, m.end()))
        else:
            if depth == 0:
                start, sid = m.start(), _id_of(m.group(3))
            depth += 1


def _strip(fragment):
    fragment = re.sub(r"<(script|style)\b.*?</\1\s*>", "", fragment, flags=re.S | re.I)
    return " ".join(html.unescape(re.sub(r"<[^>]*>", " ", fragment)).split())


def heading_html(section):
    """Inner HTML of the section's first <h2> without any info popover, or ''."""
    m = re.search(r"<h2\b[^>]*>", section)
    if not m:
        return ""
    end = element_end(section, m.start())
    if end < 0:
        return ""
    inner = section[m.end():end - len("</h2>")]
    while True:                               # drop info popovers (report_info) so the label is just the heading
        k = inner.find("<span class='rpt-info'")
        if k < 0:
            break
        e = element_end(inner, k)
        if e < 0:
            break
        inner = inner[:k] + inner[e:]
    return re.sub(r"<[^>]*>", "", inner).strip()


# ------------------------------------------------------------------------------------------------ the plan
def layout_plan(ids):
    """[(view, [section ids])]: each id in exactly one view, views in story order, ids inside a view in the defined order.

    An id that no view lists goes to "More" in document order. A view with no section is left out."""
    index = {}
    for view in VIEWS:
        for rank, sid in enumerate(_ids(view[6])):
            index[sid] = (view[0], rank)
    placed = {view[0]: [] for view in VIEWS + [MORE]}
    for pos, sid in enumerate(ids):
        vid, rank = index.get(sid, ("more", pos))
        placed[vid].append((rank, pos, sid))
    out = []
    for view in VIEWS + [MORE]:
        members = [sid for _r, _p, sid in sorted(placed[view[0]])]
        if members:
            out.append((view, members))
    return out


# ------------------------------------------------------------------------------------------------ status chips
def _scan(section):
    """Counts from one pass over a section: data rows, empty-state rows, flag boxes, pills, failed runs, figures."""
    rows = empty = svgs = failed = 0
    flags, notrun_boxes = [], 0
    pills = []
    stack, in_head, cells, colspan = [], 0, 0, False
    i = 0
    while True:
        m = TOKEN.search(section, i)
        if not m:
            break
        i = m.end()
        if m.group(2) is None:
            continue
        name, closing, attrs = m.group(2).lower(), bool(m.group(1)), m.group(3)
        if name in RAW_TEXT and not closing:
            i = _skip_raw(section, name, i)
            continue
        if closing:
            if name == "thead":
                in_head = max(0, in_head - 1)
            elif name == "tr" and not in_head and cells:
                if cells == 1 and colspan:
                    empty += 1
                else:
                    rows += 1
            continue
        classes = _classes(attrs)
        if name == "thead":
            in_head += 1
        elif name == "tr":
            cells, colspan = 0, False
        elif name in ("td",):
            cells += 1
            colspan = colspan or "colspan" in attrs
        elif name == "svg":
            svgs += 1
        if classes & {"caution", "warn", "warning"} and name in ("div", "p", "section", "aside", "li"):
            end = element_end(section, m.start())
            if end > 0:
                flags.append(_strip(section[m.start():end]))
        if "rpt-band" in classes and name == "span":
            end = element_end(section, m.start())
            if end > 0:
                pills.append(_strip(section[m.start():end]).replace("●", "").strip().lower())
        if "status" in classes and "failed" in classes and name == "span":
            failed += 1
    return rows, empty, flags, pills, failed, svgs


def status_chips(section):
    """[(text, tone)] for an accordion card, computed from the section's own content (never from its id).

    "Not run" when a "Not run" notice is present and no table has data rows; "N flag(s)" counts caution boxes that are not themselves a Not-run
    notice; "N failed" counts failed-run status labels; "all pass" only when every pass/fail pill reads pass; "N rows" counts table rows
    that hold data (a single colspan "No ..." row is an empty state, not a row); "figure" when the section draws an SVG.
    Tones: ok, warn, muted, neutral."""
    rows, empty, flags, pills, failed, svgs = _scan(section)
    text = _strip(section)
    notrun = bool(re.search(r"\bNot run\b", text))
    real_flags = [f for f in flags if not re.search(r"\bNot run\b", f)]
    chips = []
    if svgs:
        chips.append(("figure", "neutral"))
    if notrun and rows == 0:
        chips.append(("Not run", "muted"))
    elif notrun:
        chips.append(("part not run", "warn"))
    if real_flags:
        chips.append((f"{len(real_flags)} flag" + ("" if len(real_flags) == 1 else "s"), "warn"))
    if failed:
        chips.append((f"{failed} failed", "warn"))
    bad = [p for p in pills if p in ("fail", "failed")]
    if bad:
        chips.append((f"{len(bad)} fail", "warn"))
    elif pills and all(p in ("pass", "passed") for p in pills):
        chips.append(("all pass", "ok"))
    if rows:
        chips.append((f"{rows} row" + ("" if rows == 1 else "s"), "neutral"))
    elif empty and not notrun:
        chips.append(("no data", "muted"))
    if not chips:
        chips.append(("text", "neutral"))
    return chips[:3]


# ------------------------------------------------------------------------------------------------ chrome
def _esc(text):
    return html.escape(html.unescape(text), quote=True)


def _icon(name):
    return f"<svg class='rpt-ico' viewBox='0 0 24 24' aria-hidden='true' focusable='false'>{ICONS[name]}</svg>"


def _remove(text, start, end):
    return text[:start] + text[end:]


def _page_parts(page, first_start):
    """Locate the old header, flat nav (and its script) and KPI strip in the text before the first section."""
    body = page.find("<body")
    base = body if 0 <= body < first_start else 0
    pre = page[base:first_start]
    spans = {}
    for key, rx in (("header", r"<header\b"), ("nav", r"<nav class='nav'"), ("metrics", r"<div class='metrics'")):
        m = re.search(rx, pre)
        if m:
            end = element_end(pre, m.start())
            if end > 0:
                spans[key] = (m.start(), end)
    if "nav" in spans:                        # the grouped-nav script that followed the old nav
        tail = pre[spans["nav"][1]:]
        m = re.match(r"\s*<script>.*?</script>", tail, re.S)
        if m and "data-navgroup" in m.group(0):
            spans["nav"] = (spans["nav"][0], spans["nav"][1] + m.end())
    return base, pre, spans


def _header_bits(header_html):
    title = run = eyebrow = ""
    m = re.search(r"<h1\b[^>]*>(.*?)</h1>", header_html, re.S)
    if m:
        title = m.group(1).strip()
    m = re.search(r"<p class=[\"']eyebrow[\"']>(.*?)</p>", header_html, re.S)
    if m:
        eyebrow = m.group(1).strip()
    m = re.search(r"<p>(<strong>Run:</strong>.*?)</p>", header_html, re.S)
    if m:
        run = m.group(1).strip()
    return title, eyebrow, run


def _run_name(run_html):
    text = _strip(run_html)
    text = re.sub(r"^Run:\s*", "", text)
    return text.split(" · generated")[0].split(" · generated")[0].strip()


def named_page_css(views):
    """@page rules that give each view's pages its own running heading (named pages; ignored where unsupported)."""
    rules = []
    for view in views:
        title = view[1].replace("\\", "\\\\").replace('"', '\\"')
        rules.append(f"@page pv-{view[0]}{{@top-left{{content:\"{title}\";font:bold 8pt Arial,Helvetica,sans-serif;color:#183a2d}}"
                     f"@top-right{{content:\"PlasBench\";font:8pt Arial,Helvetica,sans-serif;color:#555}}}}")
        rules.append(f"@media print{{.rpt-view[data-view='{view[0]}']{{page:pv-{view[0]}}}}}")
    return "<style id='rpt-layout-pages'>" + "".join(rules) + "</style>"


def build_rail(plan, labels):
    items = []
    for view, ids in plan:
        subs = "".join(f"<li><a href='#{_esc(s)}'>{labels[s]}</a></li>" for s in ids)
        items.append(
            f"<li class='rpt-rail-item' data-view='{view[0]}'>"
            f"<a class='rpt-rail-link' href='#view-{view[0]}' title='{_esc(view[1])}'>{_icon(view[3])}"
            f"<span class='rpt-rail-label'>{_esc(view[2])}</span><span class='rpt-rail-count' title='{len(ids)} sections'>{len(ids)}</span></a>"
            f"<ul class='rpt-rail-sub'>{subs}</ul></li>")
    return ("<nav class='rpt-rail' aria-label='Report views'>"
            "<button type='button' class='rpt-rail-toggle' aria-expanded='true' aria-label='Collapse the view menu' data-needs-js>"
            f"{_icon('chev')}<span>Collapse</span></button>"
            f"<ul class='rpt-rail-list'>{''.join(items)}</ul></nav>")


def build_topbar(run_name, first_view_title):
    return ("<div class='rpt-topbar' role='banner'>"
            "<a class='rpt-brand' href='#view-overview'>Plas<b>Bench</b></a>"
            f"<span class='rpt-top-run' title='{_esc(run_name)}'>{_esc(run_name)}</span>"
            f"<span class='rpt-top-view' id='rpt-view-name' aria-live='polite'>{_esc(first_view_title)}</span>"
            "<span class='rpt-top-gap'></span>"
            "<div class='rpt-search' role='search' data-needs-js>"
            "<label class='rpt-sr' for='rpt-q'>Search the report by section title</label>"
            "<input id='rpt-q' type='search' placeholder='Jump to section  ( / )' autocomplete='off' role='combobox' "
            "aria-expanded='false' aria-controls='rpt-results' aria-autocomplete='list'>"
            "<ul class='rpt-results' id='rpt-results' role='listbox' aria-label='Matching sections' hidden></ul></div>"
            "<div class='rpt-actions' data-needs-js>"
            "<button type='button' id='pb-cvd' aria-pressed='false' title='Swap the green/red status palette for blue/orange, which stays "
            "separable with deuteranopia or protanopia. Every value is also printed as text.'>Colour-blind <span class='rpt-btn-long'>palette</span></button>"
            "<button type='button' id='rpt-expand' aria-pressed='false' title='Open or close every fold in the view that is shown'><span>Expand all</span></button>"
            "<button type='button' id='pb-print' title='Print or save as PDF: every view prints in order, every fold open, each view on a new page'>"
            "Print <span class='rpt-btn-long'>/ Save PDF</span></button>"
            "</div></div>")


def build_band(title, eyebrow, run_html, kpis_html):
    kpis = f"<div class='rpt-kpis'>{kpis_html}</div>" if kpis_html else ""
    eyebrow_html = f"<p class='rpt-eyebrow'>{eyebrow}</p>" if eyebrow else "<p class='rpt-eyebrow'>PlasBench report</p>"
    run = f"<p class='rpt-runline'>{run_html}</p>" if run_html else ""
    return (f"<div class='rpt-titleband'><div class='rpt-title-text'>{eyebrow_html}<h1>{title or 'PlasBench report'}</h1>{run}</div>{kpis}</div>")


def build_cover(plan, labels):
    items = "".join(
        f"<li><b>{_esc(view[1])}</b><ul>{''.join(f'<li><a href=\'#{_esc(s)}\'>{labels[s]}</a></li>' for s in ids)}</ul></li>" for view, ids in plan)
    return f"<div class='rpt-cover' aria-hidden='true'><h2>Contents</h2><ol>{items}</ol></div>"


def build_view(view, ids, blocks, labels, sections, cards, active=False):
    vid = view[0]
    head = (f"<div class='rpt-view-head'><div class='rpt-view-title' role='heading' aria-level='2'>{_esc(view[1])}</div>"
            f"<p class='rpt-view-blurb'>{_esc(view[4])}</p>"
            f"<span class='rpt-view-count'>{len(ids)} section{'s' if len(ids) != 1 else ''}</span></div>")
    body = []
    for sid in ids:
        block = blocks[sid]
        if cards:
            chips = "".join(f"<span class='rpt-chip rpt-chip-{tone}'>{_esc(text)}</span>" for text, tone in status_chips(sections[sid]))
            opened = " open" if sid in OPEN_CARDS.get(vid, ()) else ""
            body.append(f"<details class='rpt-card' data-card='{_esc(sid)}'{opened}><summary><span class='rpt-card-title'>{labels[sid]}</span>"
                        f"<span class='rpt-chips2'>{chips}</span></summary><div class='rpt-card-body'>{block}</div></details>")
        else:
            body.append(block)
    return (f"<div class='rpt-view{' rpt-active' if active else ''}' id='view-{vid}' data-view='{vid}' "
            f"aria-label='{_esc(view[1])}'>{head}<div class='rpt-body'>{''.join(body)}</div></div>")


# ------------------------------------------------------------------------------------------------ the transform
def transform(page):
    """The page laid out as views behind a top bar and a left rail; unchanged when it has no sections or is already laid out."""
    if MARKER in page:
        return page
    found = find_sections(page)
    if not found:
        return page
    first_start = found[0][1]
    base, pre, spans = _page_parts(page, first_start)
    # section blocks: each carries the text that followed it (style blocks emitted between sections); the last stops at the footer
    last_end = found[-1][2]
    tail = page[last_end:]
    cut = [k for k in (tail.find("<footer"), tail.find("</main>")) if k >= 0]
    cut = min(cut) if cut else 0
    order, blocks, sections, labels = [], {}, {}, {}
    old_labels = {}
    if "nav" in spans:
        old_labels = {sid: lab for sid, lab in re.findall(r"href='#([A-Za-z0-9_-]+)'>([^<]*)<", pre[spans["nav"][0]:spans["nav"][1]])}
    for k, (sid, start, end) in enumerate(found):
        stop = found[k + 1][1] if k + 1 < len(found) else last_end + cut
        sid = sid or f"section-{k + 1}"
        if sid in blocks:                                  # a duplicated id would otherwise lose a block
            sid = f"{sid}-{k + 1}"
        order.append(sid)
        blocks[sid] = page[start:stop]
        sections[sid] = page[start:end]
        labels[sid] = old_labels.get(sid) or heading_html(page[start:end]) or sid.replace("-", " ").capitalize()
    plan = layout_plan(order)
    views = [view for view, _ids in plan]
    # chrome pieces from the old header / metrics strip
    header = pre[spans["header"][0]:spans["header"][1]] if "header" in spans else ""
    title, eyebrow, run_html = _header_bits(header)
    kpis = pre[spans["metrics"][0]:spans["metrics"][1]] if "metrics" in spans else ""
    run_name = _run_name(run_html) if run_html else ""
    # what stays of the old prefix: everything except the header, nav and KPI strip
    cuts = sorted(spans.values(), reverse=True)
    kept = pre
    for a, b in cuts:
        kept = _remove(kept, a, b)
    insert_at = spans["header"][0] if "header" in spans else (pre.find("<main") if "<main" in pre else len(pre))
    # position of the insertion inside `kept`: count the removed bytes that sat before it
    removed_before = sum(b - a for a, b in cuts if b <= insert_at)
    insert_at -= removed_before
    pb = ("<script>(function(){var r=document.documentElement;r.classList.add('pb-js');if(/[?&]print(=|&|$)/.test(location.search))r.classList.add('pb-printmode');"
          "try{var s=localStorage.getItem('pb-rail');if(s==='min')r.classList.add('pb-rail-min')}catch(e){}})();</script>")
    chrome = (pb + build_topbar(run_name or "", views[0][1]) + build_rail(plan, labels)
              + f"<div {MARKER}>" + build_band(title, eyebrow, run_html, kpis) + build_cover(plan, labels))
    kept = kept[:insert_at] + chrome + kept[insert_at:]
    if "<main" not in kept:
        kept += "<main>"
        close_main = True
    else:
        close_main = False
    views_html = "".join(build_view(view, ids, blocks, labels, sections, view[5], k == 0) for k, (view, ids) in enumerate(plan))
    rest = tail[cut:]
    style = asset("layout_style.html") + asset("layout_print.html") + named_page_css(views)
    script = asset("layout_script.html")
    # the shell closes after </main>; the script follows it directly (every section exists by then), then the rest of the page
    m = re.search(r"</main>", rest)
    if m:
        rest = rest[:m.end()] + "</div>" + script + rest[m.end():]
    else:
        rest = ("</main>" if close_main else "") + "</div>" + script + rest
    head = page[:base]
    if "</head>" in head:
        h = head.rindex("</head>")
        head = head[:h] + style + head[h:]
    else:
        kept = style + kept
    return head + kept + views_html + rest
