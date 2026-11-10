#!/usr/bin/env python3
"""
report_prune.py -- a section or tab that holds only a "Not run" notice is not shown; what was not run is listed once, in Run metadata.

A section that says "Not run: <reason>" and nothing else reports no result: it takes a menu entry, a card and a heading to say what one line can. This step,
run once on the finished page after the sections are merged and before they are laid out, finds

  * top-level sections, and
  * tabs of merged containers (a `rpt-panel` and its tab button)

whose content, once the heading, the lead paragraph, the info popover and scripts are set aside, is only a Not-run notice (and no table, chart, image, list,
fold or frame), removes them, and adds one list to the Run metadata section: "Not run in this run", one item per removed section with its title and reason.
The reasons name the switch that enables each analysis, so nothing is lost: it moves from many headings to one list.

A removed section keeps its id as an anchor on its list item, so old links still land.

Never pruned: the Summary and Run metadata sections, a container's own first panel, a section that has any result at all (a table, a figure, a list), and any
page that has no Run metadata section to receive the list (the sections are then left as they are).

  prune(page)       the pruned page; `pruned_items(page)` lists (id, title, reason) of what would be removed.

Standard library only.
"""
import html
import re

import report_layout as L

KEEP_IDS = {"summary", "metadata"}
RESULT_MARKUP = re.compile(r"<(table|svg|img|canvas|iframe|details|ul|ol|figure|select|button|video)\b", re.I)
NOT_RUN = re.compile(r"Not run\b", re.I)
_POPOVER = re.compile(r"<span class='rpt-info'.*?</span></span>", re.S)
_TAGS = re.compile(r"<[^>]+>")


def _text(fragment):
    return re.sub(r"\s+", " ", html.unescape(_TAGS.sub(" ", fragment))).strip()


def _strip_chrome(inner):
    """Inner html without scripts, styles, the info popover, the heading and the lead paragraph."""
    inner = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", "", inner, flags=re.S | re.I)
    inner = _POPOVER.sub("", inner)
    inner = re.sub(r"<h[1-6]\b[^>]*>.*?</h[1-6]>", "", inner, flags=re.S)
    inner = re.sub(r"<p\b[^>]*class='lead'[^>]*>.*?</p>", "", inner, flags=re.S)
    return inner


def reason_if_empty(inner):
    """The Not-run reason when `inner` holds nothing but a Not-run notice, else None."""
    body = _strip_chrome(inner)
    if RESULT_MARKUP.search(body):
        return None
    text = _text(body)
    if not NOT_RUN.search(text) or len(text) > 600:
        return None
    lead = NOT_RUN.match(text)
    reason = text[lead.end():].lstrip(" :.-").strip() if lead else text      # a notice that does not start with "Not run" keeps its whole text
    return reason or text


def _title(inner):
    m = re.search(r"<h[1-6]\b[^>]*>(.*?)(?:<span class='rpt-info'|</h[1-6]>)", inner, re.S)
    return _text(m.group(1)) if m else ""


def _panels(section):
    """[(start, end, id, label)] of the top-level panels of a merged container section (offsets inside `section`)."""
    out, i = [], 0
    while True:
        k = section.find("<div class='rpt-panel' id='", i)
        if k < 0:
            return out
        end = L.element_end(section, k)
        if end < 0:
            return out
        m = re.match(r"<div class='rpt-panel' id='([^']*)' data-tab='([^']*)'", section[k:])
        out.append((k, end, html.unescape(m.group(1)), html.unescape(m.group(2))))
        i = end


def _tab_button(section, panel_id):
    m = re.search(r"<button\b[^>]*aria-controls='" + re.escape(panel_id) + r"'[^>]*>.*?</button>", section, re.S)
    return (m.start(), m.end()) if m else None


def pruned_items(page):
    """[(section id, panel id or None, title, reason)] of everything prune() would remove."""
    items = []
    for sid, start, end in L.find_sections(page):
        if not sid or sid in KEEP_IDS:
            continue
        section = page[start:end]
        panels = _panels(section)
        if panels:
            for k, (a, b, pid, label) in enumerate(panels):
                if k == 0:
                    continue          # the container's own first panel is never pruned
                inner = section[section.index(">", a) + 1:b - len("</div>")]
                reason = reason_if_empty(inner)
                if reason is not None:
                    items.append((sid, pid, _title(inner) or label, reason))
            continue
        open_end = section.index(">") + 1
        reason = reason_if_empty(section[open_end:section.rindex("</section>")])
        if reason is not None:
            items.append((sid, None, _title(section) or sid.replace("-", " ").capitalize(), reason))
    return items


def _keep(removed):
    """The script and style blocks inside what is removed: a tab can carry, after its content, the page-wide blocks emitted there (the shared 3D engine)."""
    return "".join(re.findall(r"<script\b.*?</script>|<style\b.*?</style>", removed, flags=re.S | re.I))


def _notrun_block(items):
    lis = "".join(f"<li id='{html.escape(pid or sid, quote=True)}' data-notrun='{html.escape(pid or sid, quote=True)}'><strong>{html.escape(title)}:</strong> {html.escape(reason)}</li>"
                  for sid, pid, title, reason in items)
    return (f"<div class='rpt-notrun' style='grid-column:1/-1'><small>Not run in this run</small>"
            f"<ul style='margin:6px 0 0;padding-left:20px'>{lis}</ul></div>")


def prune(page):
    found = L.find_sections(page)
    meta = next(((s, e) for sid, s, e in found if sid == "metadata"), None)
    if not meta:
        return page
    items = pruned_items(page)
    if not items:
        return page
    edits = []                                   # (start, end, replacement), applied from the end backwards
    for sid, pid, title, reason in items:
        s, e = next((s, e) for i, s, e in found if i == sid)
        if pid is None:
            # remove the section element only: the text after it (the shared 3D engine script, style blocks) belongs to the page, not to the section
            end = s + page[s:e].rindex("</section>") + len("</section>")
            edits.append((s, end, _keep(page[s:end])))
            continue
        section = page[s:e]
        panel = next(p for p in _panels(section) if p[2] == pid)
        edits.append((s + panel[0], s + panel[1], _keep(section[panel[0]:panel[1]])))
        button = _tab_button(section, pid)
        if button:
            edits.append((s + button[0], s + button[1], ""))
    # the list goes at the end of the metadata grid (the last closing div before </section>)
    s, e = meta
    block = _notrun_block(items)
    close = page.rfind("</div></section>", s, e)
    if close < 0:
        return page
    edits.append((close, close, block))
    for a, b, r in sorted(edits, key=lambda x: (x[0], x[1]), reverse=True):
        page = page[:a] + r + page[b:]
    return page


def transform(page):
    return prune(page)
