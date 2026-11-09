#!/usr/bin/env python3
"""
report_collapse.py -- fold the tables that a figure now draws into closed <details>, in one place.

A figure (heatmap, forest plot, distributions, precision-recall, 3D landscape ...) shows the same numbers as some of the report's tables.
Rather than edit every producer, this step runs once on the finished page and wraps the table panels of the sections listed in COLLAPSE:

  <div class='panel'>...table...</div>   ->   <details class='rpt-collapsible'><summary>text</summary><div class='panel'>...</div></details>

Nothing is deleted: the table stays in the page (searchable, printable once opened, available without JavaScript), it is just folded
until someone asks for it. A panel that is already inside a <details>, inside a status box (.insight), or inside an info popover is left
alone, and a section whose id is not on the page is skipped. Running it twice changes nothing.

  COLLAPSE        {section id: (summary text, figure section id or '')}; the summary names the figure that shows the same data
  collapse(page, plan=None)   the page with the panels of the planned sections folded

The page is scanned with a small tokenizer (comments and script/style bodies skipped whole) and edited by splicing.

Standard library only.
"""
import re

# section id -> (what the folded table is, the figure section that draws the same numbers). Kept short and literal: each entry is a
# claim that the figure carries the data, and test_report_collapse.py checks that the named figure section exists on a built report.
COLLAPSE = {}

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
RAW_TEXT = {"script", "style", "textarea", "title"}
SKIP_ANCESTORS = {"details"}
SKIP_CLASSES = {"insight", "caution", "warn", "warning", "finding", "rpt-info-pop", "rpt-collapsible"}
_TOKEN = re.compile(r"<!--.*?-->|<(/?)([A-Za-z][A-Za-z0-9:-]*)((?:[^>\"']|\"[^\"]*\"|'[^']*')*)>", re.S)
_CLASS = re.compile(r"""\bclass\s*=\s*(?:'([^']*)'|"([^"]*)")""")
_ID = re.compile(r"""\bid\s*=\s*(?:'([^']*)'|"([^"]*)")""")


def _classes(attrs):
    m = _CLASS.search(attrs)
    return set(((m.group(1) if m.group(1) is not None else m.group(2)) or "").split()) if m else set()


def section_bounds(page, sid):
    """(start, end) of `<section id='sid'>...</section>`, or None."""
    start = page.find(f"<section id='{sid}'")
    if start < 0:
        start = page.find(f'<section id="{sid}"')
    if start < 0:
        return None
    end = page.find("</section>", start)
    return (start, end + len("</section>")) if end >= 0 else None


def _panels(text):
    """[(start, end)] of top-level <div class='panel'> elements in `text` that sit in no details, status box or popover."""
    stack, found, i = [], [], 0
    while True:
        m = _TOKEN.search(text, i)
        if not m:
            return found
        i = m.end()
        if m.group(0).startswith("<!--"):
            continue
        closing, name, attrs = m.group(1), m.group(2).lower(), m.group(3)
        if closing:
            for k in range(len(stack) - 1, -1, -1):
                if stack[k][0] == name:
                    popped = stack[k:]
                    del stack[k:]
                    for tag, start, is_panel, blocked in popped:
                        if tag == name and is_panel and not blocked and not any(t[3] for t in stack):
                            found.append((start, m.end()))
                    break
            continue
        if name in RAW_TEXT:
            close = re.compile(rf"</{name}\s*>", re.I).search(text, i)
            i = close.end() if close else len(text)
            continue
        if name in VOID or attrs.rstrip().endswith("/"):
            continue
        cls = _classes(attrs)
        blocked = name in SKIP_ANCESTORS or bool(cls & SKIP_CLASSES)
        is_panel = name == "div" and "panel" in cls
        stack.append((name, m.start(), is_panel, blocked))


def _fold(text, summary):
    spans = _panels(text)
    # an outer panel contains no inner panel in practice; if one does, keep only the outermost
    spans = [s for s in spans if not any(o != s and o[0] <= s[0] and s[1] <= o[1] for o in spans)]
    spans.sort()
    out, pos, n = [], 0, len(spans)
    for k, (a, b) in enumerate(spans, 1):
        label = summary if n == 1 else f"{summary} ({k} of {n})"
        out.append(text[pos:a])
        out.append(f"<details class='rpt-collapsible'><summary>{label}</summary>{text[a:b]}</details>")
        pos = b
    out.append(text[pos:])
    return "".join(out), n


def collapse(page, plan=None):
    """The page with the table panels of every planned section folded into closed <details>."""
    plan = COLLAPSE if plan is None else plan
    for sid, (what, figure) in plan.items():
        bounds = section_bounds(page, sid)
        if not bounds:
            continue
        if figure and section_bounds(page, figure) is None:
            continue          # the figure is not on this page (not run): the table stays visible, it is then the only view
        where = " (the same numbers are drawn in the Figures group)" if figure else ""
        text = page[bounds[0]:bounds[1]]
        folded, n = _fold(text, f"Show {what}{where}")
        if n:
            page = page[:bounds[0]] + folded + page[bounds[1]:]
    return page
