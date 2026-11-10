#!/usr/bin/env python3
"""
report_help.py -- a "?" help button on every section and every tab of the report, opening one shared help dialog.

The little "i" popovers (report_info.py) carry a section's own lead note on hover. This is different and larger: a click-to-open dialog that explains the analysis for
a reader who is not a specialist, in the same six parts everywhere (python/report_help_text.py): what it shows in plain words, the data used, how it was made, how to
read it, why it matters, and what to keep in mind.

What is added to the finished page, after the layout step and the info popovers:

  * inside the first heading of every `<section id>` and every tab panel (`rpt-panel`) that has an entry: a button
        <span class='rpt-help'><button type='button' class='rpt-help-btn' data-help='KEY' aria-haspopup='dialog' aria-label='Help: about TITLE'>?</button></span>
    A panel with no heading of its own gets a one-line row "About this tab" at its top instead;
  * once, the texts of the entries that are used, as JSON (`<script type='application/json' id='rpt-help-data'>`), the style, and the script that opens the dialog
    (click, Enter or Space; Esc, the Close button or a click outside closes it; focus returns to the button).

A section or tab without an entry gets no button (test/test_report_help.py names it). The button is hidden in print; the texts stay in the JSON, which is also what a
search of the page source finds. Running it twice changes nothing. Standard library only.
"""
import html
import json
import re

import report_help_text as T
import report_layout as L
import report_prune as P

HEADING = re.compile(r"<(h[2-4])\b[^>]*>(.*?)</\1>", re.S)
_POPOVER = re.compile(r"<span class='rpt-info'.*?</span></span>", re.S)
_TAGS = re.compile(r"<[^>]+>")


def _plain(fragment):
    return re.sub(r"\s+", " ", html.unescape(_TAGS.sub("", _POPOVER.sub("", fragment)))).strip()


def _button(key, title):
    label = html.escape(f"Help: about {title}", quote=True)
    return (f"<span class='rpt-help'><button type='button' class='rpt-help-btn' data-help='{html.escape(key, quote=True)}' aria-haspopup='dialog' "
            f"aria-label='{label}' title='Help: what this shows and how to read it'>?</button></span>")


def _already(fragment):
    return "class='rpt-help-btn'" in fragment


def _heading_edit(block, base, key, entries, used):
    """(position, text) to insert the button inside the first heading of `block`, or None. `base` is the offset of `block` in the page."""
    m = HEADING.search(block[:4000])
    if not m:
        return None
    title = _plain(m.group(2)) or key
    close = m.start(2) + len(m.group(2))
    used[key] = title
    return base + close, _button(key, title)


def _panel_edit(section, base, panel, entries, used, labels):
    a, b, pid, label = panel
    if pid not in entries:
        return None
    block = section[a:b]
    if _already(block):
        return None
    inner_start = block.index(">") + 1
    m = HEADING.search(block[:700])
    if m and not block[inner_start:m.start()].strip().startswith(("<table", "<svg", "<div class='rpt-mtabs'")):
        title = _plain(m.group(2)) or label
        used[pid] = label or title
        return base + a + m.start(2) + len(m.group(2)), _button(pid, title)
    used[pid] = label
    row = f"<div class='rpt-help-row'>{_button(pid, label)}<span>About this tab</span></div>"
    return base + a + inner_start, row


def transform(page, entries=None):
    """The page with the help buttons, the help JSON, the style and the script (the last three once)."""
    entries = T.HELP if entries is None else entries
    if "id='rpt-help-data'" in page:
        return page
    used, edits = {}, []
    for sid, start, end in L.find_sections(page):
        if not sid:
            continue
        section = page[start:end]
        panels = P._panels(section)
        head_block = section[:panels[0][0]] if panels else section
        if sid in entries and not _already(head_block):
            edit = _heading_edit(head_block, start, sid, entries, used)
            if edit:
                edits.append(edit)
        for panel in panels:
            edit = _panel_edit(section, start, panel, entries, used, None)
            if edit:
                edits.append(edit)
    if not edits:
        return page
    for pos, text in sorted(edits, key=lambda e: e[0], reverse=True):
        page = page[:pos] + text + page[pos:]
    payload = {"fields": [[k, label] for k, label in T.FIELDS],
               "items": {key: dict(entries[key], title=title) for key, title in sorted(used.items())}}
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    block = (f"<style id='rpt-help-style'>{L.asset('help_style.html')}</style>"
             f"<script type='application/json' id='rpt-help-data'>{data}</script>"
             f"{L.asset('help_script.html')}")
    cut = page.rfind("</body>")
    return page[:cut] + block + page[cut:] if cut >= 0 else page + block


def missing(page, entries=None):
    """Section and tab ids on `page` that have no help entry (and no button): what test_report_help.py reports."""
    entries = T.HELP if entries is None else entries
    out = []
    for sid, start, end in L.find_sections(page):
        if sid and sid not in entries:
            out.append(sid)
        for _a, _b, pid, _l in P._panels(page[start:end]):
            if pid not in entries:
                out.append(pid)
    return out
