#!/usr/bin/env python3
"""
report_merge.py -- fold related analyses into one container section with tabs, deleting nothing.

The report grew one top-level section per analysis (73 in the demo). This step, run once on the finished page right before report_layout
(every section exists by then), moves each absorbed section into the section that answers the same question, as a tab:

  <section id='robustness' class='rpt-merge' ...>
    <h2>Ranking confidence</h2><p class='lead'>...</p>
    <div class='rpt-mtabs' role='tablist' hidden> <button role='tab' ...>Basis and metric checks</button> ... </div>
    <div class='rpt-panel' id='robustness-main' data-tab='Basis and metric checks' role='tabpanel'> the container's own content </div>
    <div class='rpt-panel' id='statistics' data-tab='Paired tests' role='tabpanel'> the absorbed section, every byte of its inner HTML </div>
    ...
  </section>

  * A container keeps its <section id>; its own content is the first panel. When the container gets a new title, the old heading stays as
    a sub-heading at the top of that panel.
  * An absorbed section's inner HTML (lead, tables, svgs, scripts, ids, links) is moved verbatim into a panel whose id is the OLD section
    id, so every href='#old-id' still lands on it. The old <section> wrapper is the only thing that disappears. Text that followed the
    section (style blocks emitted between sections) travels with it. Sections are never nested.
  * Without JavaScript the tab strip stays hidden and every panel shows stacked, each under its own heading; in print every panel shows.
    With the page's script (assets/report/merge_script.html) the first tab is selected, arrow keys / Home / End move between tabs, and a link
    or address that points into a hidden tab opens it first (the old ids work, also through report_layout's hash routing).
  * A missing container leaves its absorbed sections standing alone; a missing absorbed section is skipped; a section that has nested
    sections of its own is never absorbed; a container with no absorbed section present is left unchanged. Running it twice changes nothing.
  * Appendix: five reference sections become tabs of the new container 'appendix-reference' (nothing of its own).

  MERGES                   the table: container id, title, rail label, first tab label, [(absorbed id, tab label)]
  LEGACY_IDS               {absorbed id: (container id, tab label)}, shared with report_aliases
  panels_of(section)       [(panel id, tab label, inner html)] of a merged container (used by report_layout's status chips and the tests)
  transform(page)          the merged page

Standard library only.
"""
import html
import os
import re

import report_aliases
import report_layout as L

MARK = "rpt-merge"

# container id, container title (None keeps the container's own heading), rail label (None keeps the navigation label), blurb for a new
# title, label of the container's own first tab, [(absorbed section id, tab label)] in tab order.
MERGES = [
    {"id": "leaderboard", "title": None, "rail": "Method ranking", "first": "Headline",
     "tabs": [("chart", "Precision, recall and F1"), ("metric-framework", "Metric framework"), ("scoring-additions", "MCC and F-beta"),
              ("graded-tiers", "Graded recovery"), ("zero-plasmid", "Negative control"), ("baselines-calibration", "Baselines and calibration")]},
    {"id": "robustness", "title": "Ranking confidence", "rail": "Ranking confidence", "first": "Basis and metric checks",
     "blurb": "How far the ranking can be trusted: the basis and the metric checks, the paired tests behind every gap, the sensitivity of the "
              "ranking to filters and metrics, statistical power, leakage from tool databases, and reproducibility across runs.",
     "tabs": [("statistics", "Paired tests"), ("rank-robustness", "Filter and metric sensitivity"), ("power", "Statistical power"),
              ("database-membership", "Truth in tool databases"), ("learn-plsmd", "plsMD leakage"), ("reproducibility", "Reproducibility")]},
    {"id": "scorecard", "title": None, "rail": "Scorecard", "first": "Scorecard",
     "tabs": [("composite", "Weights and sensitivity")]},
    {"id": "scorecard-scenarios", "title": None, "rail": "Scorecard by scenario", "first": "Overlapping tags",
     "tabs": [("scenarios", "Exclusive scenarios")]},
    {"id": "scores", "title": None, "rail": "All scores", "first": "All scores",
     "tabs": [("tools", "By tool"), ("samples", "By sample")]},
    {"id": "bin-diagnostics", "title": None, "rail": "Bin diagnostics", "first": "Matching",
     "tabs": [("bin-quality", "Quality tiers"), ("plasmid-outcomes", "Per-plasmid outcomes"), ("learn-agreement", "Agreement"),
              ("learn-copynumber", "Copy number")]},
    {"id": "cohort-qc", "title": "Cohort and truth quality", "rail": "Cohort and truth quality", "first": "Cohort QC flags",
     "blurb": "Checks on the cohort and on the truth it is scored against: outlier isolates, metadata, difficulty, assembly adequacy, truth "
              "labels, repeats and depth, excluded replicons, labelling schemes and laboratory evidence.",
     "tabs": [("metadata-completeness", "Metadata completeness"), ("isolate-difficulty", "Isolate difficulty"),
              ("learn-adequacy", "Assembly adequacy"), ("truth-label-audit", "Truth labels"), ("learn-truthqc", "Truth repeats and depth"),
              ("excluded-replicons", "Excluded replicons"), ("label-schemes", "Label schemes"), ("orthogonal-evidence", "Orthogonal evidence")]},
    {"id": "health", "title": "Run outcomes and cost", "rail": "Run outcomes and cost", "first": "Every run",
     "blurb": "How every run ended, which runs failed and why, and what they cost in time, memory and threads.",
     "tabs": [("outcome-states", "Outcome counts"), ("performance", "Cost")]},
    {"id": "interpretation-limits", "title": None, "rail": "Interpretation limits", "first": "Limits",
     "tabs": [("validity", "What is validated")]},
    {"id": "recommendations", "title": None, "rail": "Recommendations", "first": "Recommendations",
     "tabs": [("stratified", "Evidence by stratum"), ("selected", "Selected reconstructions")]},
    {"id": "recommender-eval", "title": None, "rail": "Recommender", "first": "Per-isolate selection",
     "tabs": [("taxon-transfer", "Unseen taxa"), ("validation", "Held-out studies")]},
    {"id": "appendix-reference", "title": "Appendix: reference tables and optional analyses", "rail": "Reference tables", "first": None,
     "blurb": "Scorecard component tables, pre-registration, QUAST diagnostics and the optional analyses. Each tab is a full section with its "
              "own downloads.",
     "tabs": [("accuracy-dimension", "Accuracy and missing regions"), ("feature-preservation", "Feature preservation and gene order"),
              ("prereg", "Pre-registration"), ("quast-diagnostics", "QUAST diagnostics"), ("extended", "Optional analyses")]},
]

LEGACY_IDS = report_aliases.LEGACY_IDS
for _spec in MERGES:
    for _old, _label in _spec["tabs"]:
        LEGACY_IDS[_old] = (_spec["id"], _label)

# Links the two big interactive views share (the same isolates drawn two ways).
CROSS_LINKS = {
    "plasmid-maps": "<p class='rpt-xlink'>Open the <a href='#enterprise'>interactive cohort dashboard</a> for the same isolates as a "
                    "bin-to-truth ribbon, dot plot and per-contig drill-down, or the <a href='#pb-explorer-view'>reconstruction evidence "
                    "explorer</a> for one truth plasmid at a time.</p>",
    "enterprise": "<p class='rpt-xlink'>The same reconstructions drawn back onto the truth plasmids: <a href='#plasmid-maps'>Plasmid maps</a> "
                  "and <a href='#per-plasmid-detail'>per-plasmid detail</a>.</p>",
}

_LEAD = re.compile(r"""<p\b[^>]*\bclass\s*=\s*(?:'[^']*\blead\b[^']*'|"[^"]*\blead\b[^"]*")[^>]*>""")


def _asset(name):
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "report", name)
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def _esc(text):
    return html.escape(text, quote=True)


def _has_nested_section(inner):
    """True when the inner html holds a <section> tag (script and style bodies are skipped whole)."""
    i = 0
    while True:
        m = L.TOKEN.search(inner, i)
        if not m:
            return False
        i = m.end()
        if m.group(2) is None:
            continue
        name = m.group(2).lower()
        if name in L.RAW_TEXT and not m.group(1):
            i = L._skip_raw(inner, name, i)
            continue
        if name == "section":
            return True


def _parts(section):
    """(open tag, inner html) of a '<section ...>...</section>' string."""
    m = L.TOKEN.match(section)
    close = section.rindex("</section>")
    return section[:m.end()], section[m.end():close]


def _mark_open(open_tag, spec):
    """The container's open tag with the merge class and the rail label added."""
    extra = f" data-rail-label='{_esc(spec['rail'])}'" if spec.get("rail") else ""
    m = re.search(r"""\bclass\s*=\s*(?:'([^']*)'|"([^"]*)")""", open_tag)
    if m:
        old = m.group(1) if m.group(1) is not None else m.group(2)
        open_tag = open_tag[:m.start()] + f"class='{_esc(old)} {MARK}'" + open_tag[m.end():]
        return open_tag[:-1] + extra + ">"
    return open_tag[:-1] + f" class='{MARK}'" + extra + ">"


def _split_head(inner):
    """(heading element, lead element, rest) of a section's inner html: the leading <h2> and a lead paragraph that follows it."""
    m = re.match(r"\s*<h2\b[^>]*>", inner)
    if not m:
        return "", "", inner
    start = m.end() - len(m.group(0).lstrip())
    end = L.element_end(inner, start)
    if end < 0:
        return "", "", inner
    head, rest = inner[start:end], inner[end:]
    lead = ""
    lm = _LEAD.match(rest.lstrip())
    if lm:
        off = len(rest) - len(rest.lstrip())
        lend = L.element_end(rest, off)
        if lend > 0:
            lead, rest = rest[off:lend], rest[lend:]
    return head, lead, rest


def _demote(h2):
    """An <h2>...</h2> element as <h3>...</h3>."""
    return re.sub(r"^<h2\b", "<h3", h2, count=1)[:-5] + "</h3>" if h2.endswith("</h2>") else h2


def _tablist(cid, title, panels):
    buttons = "".join(
        f"<button type='button' role='tab' id='rpt-mt-{_esc(pid)}' aria-controls='{_esc(pid)}' aria-selected='{'true' if k == 0 else 'false'}' "
        f"tabindex='{0 if k == 0 else -1}' data-tab='{_esc(label)}'>{_esc(label)}</button>" for k, (pid, label, _h) in enumerate(panels))
    return (f"<div class='rpt-mtabs' role='tablist' aria-label='{_esc(title)}: tabs' data-merge-tabs='{_esc(cid)}' hidden>{buttons}</div>")


def _panel(pid, label, inner):
    return (f"<div class='rpt-panel' id='{_esc(pid)}' data-tab='{_esc(label)}' role='tabpanel' aria-labelledby='rpt-mt-{_esc(pid)}'>"
            f"{inner}</div>")


def build_container(spec, open_tag, inner, absorbed):
    """The container section html: `absorbed` is [(old id, tab label, panel inner html)]; `inner` is the container's own inner html (or None)."""
    cid = spec["id"]
    head = lead = ""
    first_html = None
    if inner is not None:
        head, lead, rest = _split_head(inner)
        if spec.get("title") or not head:
            first_html = (_demote(head) if head else "") + lead + rest
            title_text = spec.get("title") or L.heading_html(f"<section>{inner}</section>") or cid
            head = f"<h2>{_esc(title_text)}</h2>"
            lead = f"<p class='lead'>{spec['blurb']}</p>" if spec.get("blurb") else ""
        else:
            first_html = rest
            title_text = L.heading_html(f"<section>{head}</section>") or cid
    else:
        title_text = spec["title"]
        head = f"<h2>{_esc(title_text)}</h2>"
        lead = f"<p class='lead'>{spec['blurb']}</p>" if spec.get("blurb") else ""
    panels = []
    if first_html is not None:
        panels.append((f"{cid}-main", spec["first"], first_html))
    panels.extend(absorbed)
    body = "".join(_panel(pid, label, h) for pid, label, h in panels)
    return f"{open_tag}{head}{lead}{_tablist(cid, title_text, panels)}{body}</section>"


def panels_of(section):
    """[(panel id, tab label, inner html)] of the top-level panels of a merged container (empty for any other section)."""
    if f"{MARK}" not in section[:section.find(">") + 1]:
        return []
    out, i = [], 0
    while True:
        k = section.find("<div class='rpt-panel' id='", i)
        if k < 0:
            return out
        end = L.element_end(section, k)
        if end < 0:
            return out
        open_end = section.index(">", k) + 1
        m = re.match(r"<div class='rpt-panel' id='([^']*)' data-tab='([^']*)'", section[k:open_end])
        out.append((html.unescape(m.group(1)), html.unescape(m.group(2)), section[open_end:end - len("</div>")]))
        i = end


def _block_ends(page, found):
    """End offset of each section's block: the text after a section (style blocks between sections) belongs to it; the last block stops at the footer."""
    last_end = found[-1][2]
    tail = page[last_end:]
    cut = [k for k in (tail.find("<footer"), tail.find("</main>")) if k >= 0]
    cut = min(cut) if cut else 0
    return [found[k + 1][1] if k + 1 < len(found) else last_end + cut for k in range(len(found))]


def _install(page):
    """The style in <head> and the script right after the last container, once."""
    if "id='rpt-merge-style'" in page:
        return page
    style, script = _asset("merge_style.html"), _asset("merge_script.html")
    if "</head>" in page:
        h = page.index("</head>")
        page = page[:h] + style + page[h:]
    else:
        page = style + page
    if "</main>" in page:
        m = page.rindex("</main>")
        return page[:m] + script + page[m:]
    if "</body>" in page:
        b = page.rindex("</body>")
        return page[:b] + script + page[b:]
    return page + script


def _cross_links(page):
    """The deep links between the plasmid maps and the interactive dashboard, once (after the section's heading and lead)."""
    for sid, note in CROSS_LINKS.items():
        start = page.find(f"<section id='{sid}'")
        if start < 0:
            continue
        end = page.find("</section>", start) if sid != "enterprise" else -1
        probe = page[start:start + 3000] if sid == "enterprise" else page[start:end]
        if "rpt-xlink" in probe:
            continue
        open_end = page.index(">", start) + 1
        head_end = L.element_end(page, open_end)
        if not page.startswith("<h2", open_end) or head_end < 0:
            continue
        pos = head_end
        if _LEAD.match(page, pos):
            lend = L.element_end(page, pos)
            if lend > 0:
                pos = lend
        page = page[:pos] + note + page[pos:]
    return page


def transform(page):
    """The page with every container's absorbed sections folded in as tabs; unchanged when there is nothing to merge."""
    found = L.find_sections(page)
    if not found:
        return page
    ends = _block_ends(page, found)
    where = {}
    for k, (sid, _s, _e) in enumerate(found):
        if sid and sid not in where:
            where[sid] = k
    edits = []                                   # (start, end, replacement); the ranges never overlap
    used, merged = set(), False
    for spec in MERGES:
        cid = spec["id"]
        virtual = spec.get("first") is None
        open_tag = inner = None
        if virtual:
            if cid in where:                    # a real section already has the id: leave it alone
                continue
        else:
            if cid not in where or cid in used:
                continue
            s, e = found[where[cid]][1], found[where[cid]][2]
            open_tag, inner = _parts(page[s:e])
            if MARK in open_tag or _has_nested_section(inner):
                continue
        absorbed = []
        for old, label in spec["tabs"]:
            if old not in where or old in used or old == cid:
                continue
            ak = where[old]
            s, e = found[ak][1], found[ak][2]
            _open, ainner = _parts(page[s:e])
            if _has_nested_section(ainner):
                continue
            absorbed.append((old, label, ainner + page[e:ends[ak]], ak))
        if not absorbed:
            continue
        merged = True
        used.update(o for o, _l, _h, _a in absorbed)
        panels = [(o, lab, h) for o, lab, h, _a in absorbed]
        gone = [ak for _o, _l, _h, ak in absorbed]
        if virtual:                              # the new container takes the place of the first absorbed section
            host = min(gone)
            gone.remove(host)
            edits.append((found[host][1], ends[host],
                          build_container(spec, f"<section id='{cid}' class='{MARK}' data-rail-label='{_esc(spec['rail'])}'>", None, panels)))
        else:
            k = where[cid]
            edits.append((found[k][1], ends[k],
                          build_container(spec, _mark_open(open_tag, spec), inner, panels) + page[found[k][2]:ends[k]]))
        edits.extend((found[ak][1], ends[ak], "") for ak in gone)
    if not merged:
        return _cross_links(page)
    for s, e, r in sorted(edits, key=lambda x: x[0], reverse=True):
        page = page[:s] + r + page[e:]
    return _cross_links(_install(page))
