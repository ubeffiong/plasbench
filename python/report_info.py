#!/usr/bin/env python3
"""
report_info.py -- move the report's explanatory notes into hover/focus "info" popovers.

One central post-processing step, run once on the finished page (after every section injector). It rewrites:

  * a section lead   <h2>Title</h2><p class='lead'>note</p>      (also after an h3 or h4)
  * a muted note     <h3>Title</h3><p class='muted'>note</p>      (also directly after a <summary>)
  * a figure caption <figcaption>how to read this figure</figcaption>

into a small circled "i" button inside the heading (or summary, or caption) whose popover carries the same note,
unchanged (links, em, strong and code stay):

  <span class='rpt-info'><button type='button' class='rpt-info-btn' aria-label='About this section: Title'
        aria-describedby='rpt-info-xxxx' aria-expanded='false'>i</button>
        <span role='tooltip' id='rpt-info-xxxx' class='rpt-info-pop'>note</span></span>

What is never moved (it must stay readable on the page): anything inside an .insight / .finding / .selection-card box,
the Summary section's own lead (the notes under its sub-headings do move), "Not run" and empty-state notices, notes that carry a status sentence or a data value
(see STATUS), and notes that are not directly after a heading or summary (there is nothing for the icon to sit beside).
The note stays in the HTML, so searching the page source still finds it, and the print stylesheet shows it inline.

The page is scanned with a small tokenizer (tags, comments, and script/style bodies skipped whole), not with regular
expressions over the markup, and edited by splicing, so every other byte is untouched. Running it again changes nothing.

Standard library only.
"""
import hashlib
import html
import re

# Section ids whose lead is the report's own "start here" text: never moved.
KEEP_SECTIONS = {"summary"}
# An element with one of these classes above a note means the note is part of a status or warning box.
KEEP_ANCESTOR_CLASSES = {"insight", "caution", "warn", "warning", "finding", "selection-card", "pv-fallback", "rpt-info-pop"}
HEADINGS = {"h2", "h3", "h4"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
RAW_TEXT = {"script", "style", "textarea", "title"}

# A note that says what happened in THIS run, or carries a value, is a status line, not an explanation: keep it visible.
STATUS = re.compile(
    r"Not run\b|Not assessed|\bin this run\b|\bthis run:|\bNot created\b"
    r"|^\s*(?:No|Not|None)\b|^\s*Tier counts|^\s*This card does not|^\s*Excluded\b|^\s*\d"
    r"|<strong>[\d.,%/ -]+</strong>|<strong>[^<]{50,}</strong>", re.I)
# A figure caption is moved only when it explains how to read the figure (a data caption such as "tool: overall 99.8" stays).
HOW_TO_READ = re.compile(r"\b(dashed|diagonal|dots?|read|reads|means|marks?|marked|triangle|axis|axes|colou?r|shaded|each (?:bar|line|point))\b", re.I)

_TOKEN = re.compile(r"<!--.*?-->|<(/?)([A-Za-z][A-Za-z0-9:-]*)((?:[^>\"']|\"[^\"]*\"|'[^']*')*)>", re.S)
_CLASS = re.compile(r"""\bclass\s*=\s*(?:'([^']*)'|"([^"]*)")""")
_ID = re.compile(r"""\bid\s*=\s*(?:'([^']*)'|"([^"]*)")""")
_TAGS = re.compile(r"<[^>]*>")


def _attr(rx, attrs):
    m = rx.search(attrs)
    return (m.group(1) if m.group(1) is not None else m.group(2)) if m else ""


def _text(fragment):
    return " ".join(html.unescape(_TAGS.sub("", fragment)).split())


def _pop_id(key, index, taken):
    base = "rpt-info-" + hashlib.sha1(f"{key}:{index}".encode("utf-8")).hexdigest()[:8]
    ident, n = base, 1
    while ident in taken:
        n += 1
        ident = f"{base}-{n}"
    taken.add(ident)
    return ident


def info_html(ident, label, note_html):
    """The icon and its popover; `note_html` is the original note HTML, kept verbatim."""
    return (f"<span class='rpt-info'><button type='button' class='rpt-info-btn' aria-label='{html.escape(label, quote=True)}' "
            f"aria-describedby='{ident}' aria-expanded='false'>i</button>"
            f"<span role='tooltip' id='{ident}' class='rpt-info-pop'>{note_html}</span></span>")


def classify(kind, inner, ancestors, section_id, anchored, heading=""):
    """Return None when the note should move, else the reason it stays."""
    if not _text(inner):
        return "empty"
    if "rpt-info" in inner:
        return "already moved"
    if any(c in KEEP_ANCESTOR_CLASSES for classes in ancestors for c in classes):
        return "in status box"
    if section_id in KEEP_SECTIONS and kind == "lead" and heading not in ("h3", "h4"):
        return "start-here section"      # the Summary's own lead; the notes under its sub-headings (matrix, report card) are tooltips like everywhere else
    if not anchored:
        return "no heading to sit beside"
    if kind == "figcaption":
        if STATUS.search(inner) or not HOW_TO_READ.search(inner):
            return "data or status caption"
        return None
    if STATUS.search(inner):
        return "status or data"
    return None


def transform_with_records(page):
    """Return (new_page, records). Each record: kind, action ('moved' or 'kept'), reason, id, note, heading, section."""
    taken = set(re.findall(r"id=['\"](rpt-info-[^'\"]*)['\"]", page))
    records, edits = [], []
    stack = []                                   # (name, classes, attrs, start)
    counters = {}
    pos, prev = 0, ("none",)                     # prev: last significant thing at this level
    anchors = {}                                 # close-tag start -> state of the heading/summary being annotated
    n = len(page)

    def section_key():
        for name, _classes, attrs, _start in reversed(stack):
            if name == "section":
                return _attr(_ID, attrs) or "section"
        return "page"

    def next_index(key):
        counters[key] = counters.get(key, 0) + 1
        return counters[key]

    while pos < n:
        m = _TOKEN.search(page, pos)
        if not m:
            break
        if page[pos:m.start()].strip():
            prev = ("text",)
        pos = m.end()
        if m.group(2) is None:                   # a comment
            continue
        closing, name, attrs = m.group(1) == "/", m.group(2).lower(), m.group(3)
        if closing:
            for i in range(len(stack) - 1, -1, -1):
                if stack[i][0] == name:
                    opened = stack[i]
                    del stack[i:]
                    break
            else:
                opened = None
            if name in HEADINGS or name == "summary":
                prev = ("anchor", name, m.start(), opened, anchors.get(opened[3]) if opened else None)
            else:
                prev = ("close", name)
            continue
        classes = set(_attr(_CLASS, attrs).split())
        if name in RAW_TEXT:                     # skip the body whole (the page carries ~10 MB of script and style)
            end = re.compile(rf"</{name}\s*>", re.I).search(page, pos)
            pos = end.end() if end else n
            prev = ("close", name)
            continue
        is_note = (name == "p" and ("lead" in classes or "muted" in classes)) or name == "figcaption"
        if is_note and not attrs.rstrip().endswith("/"):
            close_tag = "</figcaption>" if name == "figcaption" else "</p>"
            end = page.find(close_tag, pos)
            if end < 0:
                continue
            inner = page[pos:end]
            after = end + len(close_tag)
            kind = "figcaption" if name == "figcaption" else ("lead" if "lead" in classes else "muted")
            ancestors = [s[1] for s in stack]
            sid = section_key()
            anchor = None
            if name != "figcaption" and prev[0] == "anchor" and prev[3] is not None:
                if prev[1] in HEADINGS or (prev[1] == "summary" and kind == "muted"):
                    anchor = prev
            reason = classify(kind, inner, ancestors, sid, anchor is not None or kind == "figcaption", anchor[1] if anchor else "")
            record = {"kind": kind, "action": "kept" if reason else "moved", "reason": reason, "note": inner,
                      "section": sid, "id": None, "heading": ""}
            records.append(record)
            if reason is None and kind == "figcaption":
                ident = _pop_id(sid, next_index(sid), taken)
                record["id"], record["heading"] = ident, "figure"
                edits.append((pos, end, info_html(ident, "About this figure", inner)))
            elif reason is None:
                a_start = anchor[2]
                state = anchor[4]
                heading_text = _text(page[anchor[3][3]:a_start]) if anchor[3] else ""
                if state is None:                # first note on this heading: one icon, its popover id from section and index
                    ident = _pop_id(sid, next_index(sid), taken)
                    label = ("About this section: " if anchor[1] in HEADINGS else "About: ") + heading_text
                    state = {"ident": ident, "notes": [], "label": label, "at": a_start}
                    anchors[anchor[3][3]] = state
                    edits.append(("anchor", state))
                state["notes"].append(inner)
                record["id"], record["heading"] = state["ident"], heading_text
                edits.append((m.start(), after, ""))
                prev = ("anchor", anchor[1], a_start, anchor[3], state)
            else:
                prev = ("close", "p")
            pos = after
            continue
        if name not in VOID and not attrs.rstrip().endswith("/"):
            stack.append((name, classes, attrs, m.start()))
        prev = ("open", name)

    spliced = []
    for edit in edits:
        if edit[0] == "anchor":
            state = edit[1]
            notes = state["notes"]
            body = notes[0] if len(notes) == 1 else "".join(f"<span class='rpt-info-para'>{x}</span>" for x in notes)
            spliced.append((state["at"], state["at"], info_html(state["ident"], state["label"], body)))
        else:
            spliced.append(edit)
    spliced.sort(key=lambda e: (e[0], e[1]))
    out, last = [], 0
    for start, end, text in spliced:
        out.append(page[last:start])
        out.append(text)
        last = end
    out.append(page[last:])
    return "".join(out), records


def transform(page, script_html=None):
    """The page with its moved notes as popovers and (once) the positioning script before </body>."""
    page, _records = transform_with_records(page)
    if script_html and "id='rpt-info-script'" not in page:
        cut = page.rfind("</body>")
        page = page[:cut] + script_html + page[cut:] if cut >= 0 else page + script_html
    return page
