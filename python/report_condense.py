#!/usr/bin/env python3
"""
report_condense.py -- shorten the report page from the inside: sub-tabs, windowed long tables, consistent table typography.

One post-processing step (python/report_post.py runs it first), on the finished page. It deletes nothing and changes no <section id>.
Every original byte of the content stays in the page; the step only wraps it and adds attributes.

  1. SUB-TABS. A section whose body has two or more <h3> subsections (an h3 that is a direct child of the section, and the content up
     to the next such h3 or the section end) gets a tab strip. The lead and status boxes before the first h3 stay above it. Each
     subsection is wrapped, verbatim, in a tab panel. Without JavaScript the strip stays hidden and all panels show stacked with their
     headings; in print every panel is shown. Gates (a section that fails any is left stacked):
        - not in SKIP_SECTIONS / SKIP_PREFIXES (the interactive widgets, which measure their own size and own their layout);
        - has an id; no nested section; no <script> or <canvas> of its own (it would measure zero size inside a hidden tab);
        - at least MIN_NONTINY subsections are not tiny (a tiny subsection has fewer than TINY_LINES lines of content, a line being
          a paragraph, list item, body table row, figure, pre, heading-4 or fold-out), and the section has at least MIN_TOTAL_LINES;
        - every h3 has a non-empty label.
  2. LONG TABLES. A table with more than WINDOW_AFTER body rows gets a toolbar (filter box, "Show all N rows", a count) and, once the
     page's script runs, only the first LIMIT rows show. All rows stay in the DOM; the filter searches all of them; print and no-JS
     show all. Rows are hidden with a CSS class, never the `hidden` attribute, so the page's own filters (which set `hidden`) and the
     filtered-CSV export keep working. Gates: not in a skipped section or an info popover, exactly one <tbody>, no rowspan, no nested
     table.
  3. TYPOGRAPHY. Every table that is windowed or sits in a tab panel gets class `rpt-t` (zebra rows, tabular numerals, compact padding,
     sticky header) and, in a regular table (no colspan or rowspan), class `rpt-num` on every cell of a column whose body cells are all
     numbers (placeholders such as "-" or "n/a" allowed, at least one real number).

Nothing to condense means the page comes back unchanged (no style, no script). Running it twice changes nothing.

  transform(page)                 the condensed page
  transform_with_stats(page)      (page, stats): stats counts tables windowed, sections tabbed, tabs, rows hidden by default

The page is scanned with a small tokenizer (comments and script/style bodies skipped whole) and edited by splicing insertions and
open-tag rewrites, so every other byte is untouched.

Standard library only.
"""
import html
import os
import re

LIMIT = 12                  # rows shown before "Show all"
WINDOW_AFTER = 15           # a table with more body rows than this is windowed
TINY_LINES = 3
MIN_NONTINY = 2
MIN_TOTAL_LINES = 8

# Sections never tabbed and whose tables are never windowed, with the reason: each owns an interactive widget or is the entry point.
SKIP_SECTIONS = {
    "summary": "the entry point: headline numbers and 'start here' must stay fully visible",
    "scorecard": "interactive scorecard widget with its own controls",
    "plasmid-maps": "interactive plasmid map viewer; measures its own size",
    "contig-layer": "interactive contig layout widget",
    "recommender-eval": "interactive recommender evaluation widget",
    "amr-placement": "interactive AMR placement widget",
    "enterprise": "interactive enterprise view",
}
SKIP_PREFIXES = {"fig-": "interactive figure sections (heatmap, ladder, landscape, distributions, forest, PR) own their layout and tables"}

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
RAW_TEXT = {"script", "style", "textarea", "title"}
LINE_TAGS = {"p", "li", "tr", "figure", "pre", "h4", "details", "dt"}
STATUS_CLASSES = {"insight", "caution", "warn", "warning", "finding"}
IMPLIED = {"td": {"td", "th"}, "th": {"td", "th"}, "tr": {"td", "th", "tr"}}   # an opening tag that closes an open cell / row

_TOKEN = re.compile(r"<!--.*?-->|<(/?)([A-Za-z][A-Za-z0-9:-]*)((?:[^>\"']|\"[^\"]*\"|'[^']*')*)>", re.S)
_CLASS = re.compile(r"""\bclass\s*=\s*(?:'([^']*)'|"([^"]*)")""")
_ID = re.compile(r"""\bid\s*=\s*(?:'([^']*)'|"([^"]*)")""")
_COLSPAN = re.compile(r"""\bcolspan\s*=\s*['"]?(?:[2-9]|\d\d)""", re.I)
_ROWSPAN = re.compile(r"""\browspan\s*=\s*['"]?(?:[2-9]|\d\d)""", re.I)
_TAGS = re.compile(r"<[^>]*>")
_INFO = re.compile(r"<span class='rpt-info'>.*?</span></span>", re.S)
_NUMBER = re.compile(r"^[+\-]?(?:\d{1,3}(?:,\d{3})+|\d+)?(?:\.\d+)?(?:[eE][+\-]?\d+)?\s*%?$")
_PLACEHOLDER = {"", "-", "–", "—", "n/a", "na", "nan", "not applicable", "not assessed", "none"}
_ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "report")


def _attr(rx, attrs):
    m = rx.search(attrs)
    return ((m.group(1) if m.group(1) is not None else m.group(2)) or "") if m else ""


def _text(fragment):
    return " ".join(html.unescape(_TAGS.sub("", fragment)).split())


def parse_number(text):
    """The float a table cell shows, or None (placeholders and units other than % are not numbers)."""
    s = _text(text).replace("−", "-").strip()
    if not s or not re.search(r"\d", s) or not _NUMBER.match(s):
        return None
    try:
        return float(s.replace(",", "").rstrip("%").strip())
    except ValueError:
        return None


def _is_placeholder(text):
    return _text(text).lower().strip(" .") in _PLACEHOLDER


def skip_reason(sid):
    if sid in SKIP_SECTIONS:
        return SKIP_SECTIONS[sid]
    for prefix, why in SKIP_PREFIXES.items():
        if sid.startswith(prefix):
            return why
    return ""


def _retag(name, attrs, add_class, extra=""):
    """A rewritten open tag: `add_class` appended to the class attribute (created if absent) and `extra` attributes appended."""
    m = _CLASS.search(attrs)
    if m:
        quote = "'" if m.group(1) is not None else '"'
        classes = (m.group(1) if m.group(1) is not None else m.group(2)).split()
        if add_class not in classes:
            classes.append(add_class)
        attrs = attrs[:m.start()] + f"class={quote}{' '.join(classes)}{quote}" + attrs[m.end():]
    else:
        attrs = attrs + f" class='{add_class}'"
    return f"<{name}{attrs}{extra}>"


class _Table:
    def __init__(self, start, end, name, attrs, section, nested, blocked):
        self.start, self.end, self.name, self.attrs = start, end, name, attrs
        self.section, self.nested, self.blocked = section, nested, blocked
        self.tbodies = 0
        self.rowspan = False
        self.irregular = False
        self.head = []            # header cells of the first header row (dicts as in rows)
        self.head_tr = None
        self.rows = []            # per body row: [(start, end, name, attrs, content_start, content_end)]
        self.has_inner_table = False

    @property
    def body_rows(self):
        return len(self.rows)


class _Section:
    def __init__(self, start, end, sid, attrs):
        self.start, self.open_end, self.id, self.attrs = start, end, sid, attrs
        self.close_start = None
        self.h3 = []              # [(start, end_of_open_tag)] direct-child h3
        self.h3_close = []        # close end of each
        self.marks = []           # (position, tag, in_thead) line-bearing tags
        self.has_script = False
        self.has_nested = False
        self.has_tabs = False
        self.tables = []


def _scan(page):
    """Tokenize once. Returns (sections, tables)."""
    sections, tables = [], []
    stack = []                    # [name, classes, start, attrs, record]
    pos, n = 0, len(page)

    def pop_to(index, close_start):
        popped = stack[index:]
        del stack[index:]
        for name, _classes, _start, _attrs, rec in popped:
            if name in ("td", "th") and rec is not None:
                rec["content_end"] = close_start
            elif name == "section" and rec is not None:
                rec.close_start = close_start

    def section_of_stack():
        for entry in reversed(stack):
            if entry[0] == "section":
                return entry[4]
        return None

    while pos < n:
        m = _TOKEN.search(page, pos)
        if not m:
            break
        pos = m.end()
        if m.group(2) is None:
            continue
        closing, name, attrs = m.group(1) == "/", m.group(2).lower(), m.group(3)
        if closing:
            for i in range(len(stack) - 1, -1, -1):
                if stack[i][0] == name:
                    pop_to(i, m.start())
                    break
            continue
        if name in RAW_TEXT:
            sec = section_of_stack()
            if sec is not None and name == "script":
                sec.has_script = True
            end = re.compile(rf"</{name}\s*>", re.I).search(page, pos)
            pos = end.end() if end else n
            continue
        classes = set(_attr(_CLASS, attrs).split())
        sec = section_of_stack()
        if name == "canvas" and sec is not None:
            sec.has_script = True
        # an opening td/th/tr implies the end of an open cell/row of the same table
        if name in IMPLIED:
            for i in range(len(stack) - 1, -1, -1):
                if stack[i][0] in ("table", "thead", "tbody", "section", "details", "div"):
                    break
                if stack[i][0] in IMPLIED[name]:
                    pop_to(i, m.start())
                    break
        rec = None
        if name == "section":
            sid = _attr(_ID, attrs)
            rec = _Section(m.start(), m.end(), sid, attrs)
            if sec is not None:
                sec.has_nested = True
            sections.append(rec)
        elif name == "h3" and stack and stack[-1][0] == "section":
            rec = (m.start(), m.end())
            stack[-1][4].h3.append(rec)
        elif name == "table":
            in_table = any(e[0] == "table" for e in stack)
            if in_table:
                for e in stack:
                    if e[0] == "table":
                        e[4].has_inner_table = True
            # tables in a popover, or in a <template> (the isolate filter's pre-rendered per-isolate content), are never windowed or tabbed
            blocked = any("rpt-info-pop" in e[1] or e[0] == "template" for e in stack)
            rec = _Table(m.start(), m.end(), name, attrs, sec, in_table, blocked)
            tables.append(rec)
            if sec is not None:
                sec.tables.append(rec)
        elif name in ("td", "th"):
            tbl = next((e[4] for e in reversed(stack) if e[0] == "table"), None)
            in_thead = any(e[0] == "thead" for e in stack)
            in_tbody = any(e[0] == "tbody" for e in stack)
            if tbl is not None:
                if _COLSPAN.search(attrs):
                    tbl.irregular = True
                if _ROWSPAN.search(attrs):
                    tbl.irregular = tbl.rowspan = True
                cell = {"start": m.start(), "open_end": m.end(), "name": name, "attrs": attrs, "content_end": m.end()}
                tr_start = next((e[2] for e in reversed(stack) if e[0] == "tr"), None)
                if in_tbody and tbl.rows:
                    tbl.rows[-1].append(cell)
                    rec = cell
                elif in_thead:
                    if tbl.head_tr is None:
                        tbl.head_tr = tr_start
                    if tr_start == tbl.head_tr:
                        tbl.head.append(cell)
                    else:
                        tbl.irregular = True
                    rec = cell
        elif name == "tbody":
            tbl = next((e[4] for e in reversed(stack) if e[0] == "table"), None)
            if tbl is not None:
                tbl.tbodies += 1
        elif name == "tr":
            tbl = next((e[4] for e in reversed(stack) if e[0] == "table"), None)
            if tbl is not None and any(e[0] == "tbody" for e in stack):
                tbl.rows.append([])
        if sec is not None and name in LINE_TAGS and not (name == "tr" and any(e[0] == "thead" for e in stack)):
            sec.marks.append((m.start(), name))
        if "rpt-tabs" in classes:
            for e in stack:
                if e[0] == "section":
                    e[4].has_tabs = True
        if name not in VOID and not attrs.rstrip().endswith("/"):
            stack.append([name, classes, m.start(), attrs, rec])
    return sections, tables


def _tab_plan(sec, stats_reason=None):
    """None, or the list of (h3_start, h3_open_end, label) when the section qualifies for sub-tabs."""
    if not sec.id or skip_reason(sec.id) or sec.has_nested or sec.has_script or sec.has_tabs or sec.close_start is None:
        return None
    if len(sec.h3) < 2:
        return None
    starts = [h[0] for h in sec.h3] + [sec.close_start]
    lines = [0] * len(sec.h3)
    k = 0
    for pos, _tag in sorted(sec.marks):
        while k < len(sec.h3) and pos >= starts[k + 1]:
            k += 1
        if k < len(sec.h3) and pos >= starts[0]:
            lines[k] += 1
    if sum(1 for x in lines if x >= TINY_LINES) < MIN_NONTINY or sum(lines) < MIN_TOTAL_LINES:
        return None
    return starts, lines


def _stats_blank():
    return {"tables_windowed": 0, "sections_tabbed": 0, "tabs": 0, "rows_hidden_default": 0, "tables_styled": 0}


def _numeric_columns(tbl, page):
    """Column indexes whose body cells are all numbers (placeholders allowed), for a regular table; else []."""
    if tbl.irregular or not tbl.head or not tbl.rows:
        return []
    ncol = len(tbl.head)
    if any(len(r) != ncol for r in tbl.rows):
        return []
    cols = []
    for j in range(ncol):
        real = 0
        ok = True
        for r in tbl.rows:
            cell = r[j]
            body = page[cell["open_end"]:cell["content_end"]]
            if parse_number(body) is not None:
                real += 1
            elif not _is_placeholder(body):
                ok = False
                break
        if ok and real:
            cols.append(j)
    return cols


def transform_with_stats(page):
    stats = _stats_blank()
    sections, tables = _scan(page)
    edits = []                    # (position, order, end, text)
    taken_tabs = set(re.findall(r"id='rpt-tabs-([^']*)'", page))
    taken_tables = {int(x) for x in re.findall(r"data-rpt-table='(\d+)'", page)}
    next_table = [max(taken_tables, default=0)]

    tabbed_ranges = []
    for sec in sections:
        plan = _tab_plan(sec)
        if not plan:
            continue
        starts, lines = plan
        base = re.sub(r"[^A-Za-z0-9_-]", "-", sec.id)
        key, n = base, 1
        while key in taken_tabs:
            n += 1
            key = f"{base}-{n}"
        taken_tabs.add(key)
        labels = []
        for h_start, h_end in sec.h3:
            close = page.find("</h3>", h_end)
            labels.append(_text(_INFO.sub("", page[h_end:close])) if close >= 0 else "")
        if not all(labels):
            continue
        sec_title = ""
        tablist = [f"<div class='rpt-tablist' role='tablist' aria-label='Subsections of {html.escape(sec.id, quote=True)}' hidden>"]
        for i, label in enumerate(labels):
            tablist.append(f"<button type='button' role='tab' id='rpt-tab-{key}-{i + 1}' aria-controls='rpt-panel-{key}-{i + 1}' "
                           f"aria-selected='{'true' if i == 0 else 'false'}' tabindex='{0 if i == 0 else -1}'>{html.escape(label)}</button>")
        tablist.append("</div>")
        edits.append((starts[0], 1, starts[0], f"<div class='rpt-tabs' id='rpt-tabs-{key}' data-rpt-tabs='{key}'>"))
        edits.append((starts[0], 2, starts[0], "".join(tablist)))
        for i in range(len(sec.h3)):
            edits.append((starts[i], 3, starts[i], f"<div class='rpt-tabpanel' id='rpt-panel-{key}-{i + 1}' role='tabpanel' "
                                                   f"aria-labelledby='rpt-tab-{key}-{i + 1}'>"))
            edits.append((starts[i + 1], 0, starts[i + 1], "</div>"))
        edits.append((starts[-1], 4, starts[-1], "</div>"))
        tabbed_ranges.append((starts[0], starts[-1]))
        stats["sections_tabbed"] += 1
        stats["tabs"] += len(labels)

    def in_tabbed(pos):
        return any(a <= pos < b for a, b in tabbed_ranges)

    for tbl in tables:
        if tbl.blocked or tbl.nested or tbl.has_inner_table or tbl.tbodies != 1 or tbl.rowspan:
            continue
        sid = tbl.section.id if tbl.section is not None else ""
        if sid and skip_reason(sid):
            continue
        classes = set(_attr(_CLASS, tbl.attrs).split())
        if "rpt-t" in classes or "data-rpt-table" in tbl.attrs:
            continue
        windowed = tbl.body_rows > WINDOW_AFTER
        if not (windowed or in_tabbed(tbl.start)):
            continue
        extra = ""
        if windowed:
            next_table[0] += 1
            number = next_table[0]
            extra = f" data-rpt-table='{number}'"
            total = tbl.body_rows
            bar = (f"<div class='rpt-win-bar' data-rpt-bar='{number}' hidden>"
                   f"<input type='search' placeholder='Filter {total} rows' aria-label='Filter the {total} rows of this table' autocomplete='off'>"
                   f"<button type='button' aria-expanded='false'>Show all {total} rows</button>"
                   f"<span class='rpt-win-n' role='status' aria-live='polite'>{total} rows</span></div>")
            edits.append((tbl.start, 0, tbl.start, bar))
            stats["tables_windowed"] += 1
            stats["rows_hidden_default"] += total - LIMIT
        stats["tables_styled"] += 1
        edits.append((tbl.start, 1, tbl.end, _retag(tbl.name, tbl.attrs, "rpt-t", extra)))
        numeric = _numeric_columns(tbl, page)
        for j in numeric:
            for cell in [tbl.head[j]] + [r[j] for r in tbl.rows]:
                edits.append((cell["start"], 1, cell["open_end"], _retag(cell["name"], cell["attrs"], "rpt-num")))

    if not edits:
        return page, stats
    edits.sort(key=lambda e: (e[0], e[1]))
    out, last = [], 0
    for start, _order, end, text in edits:
        out.append(page[last:start])
        out.append(text)
        last = max(last, end)
    out.append(page[last:])
    page = "".join(out)
    if "id='rpt-condense-style'" not in page:
        page = _insert(page, _fragment("condense_style.html"), "</head>", at_end=False)
    if "id='rpt-condense-script'" not in page:
        page = _insert(page, _fragment("condense_script.html"), "</body>", at_end=True)
    return page, stats


def _fragment(name):
    with open(os.path.join(_ASSETS, name), encoding="utf-8") as fh:
        return fh.read()


def _insert(page, fragment, anchor, at_end):
    # the first </head> is the page's own (a later one can sit inside an embedded string); the last </body> closes the page
    cut = page.find(anchor) if anchor == "</head>" else page.rfind(anchor)
    if cut >= 0:
        return page[:cut] + fragment + page[cut:]
    return page + fragment if at_end else fragment + page


def transform(page):
    """The page with its long tables windowed and its multi-subsection sections tabbed (see the module docstring)."""
    return transform_with_stats(page)[0]
