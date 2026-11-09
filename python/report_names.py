#!/usr/bin/env python3
"""
report_names.py -- reader-facing tool names, applied when the report is built.

The tables carry tool ids (spades_like, mob_recon ...). A script at the end of the page used to rename them in the browser, so a printout, a PDF made
without running scripts, a reader with JavaScript off, and a search of the page source all saw the raw ids. humanise(page, labels) does the same renaming
once, at build time, in the text of the page:

  * text nodes only: attribute values (ids, hrefs, data-* keys, titles) are never touched, so links and filters keep working;
  * not inside <script>, <style> or <textarea> (raw text), nor inside <code>, <pre>, <option> or <template> (the same places the browser script skipped;
    template content is renamed where it is rendered, see report_isolates.humanise; an <option>'s text can be its value);
  * inside a link (<a>) only when the whole link text is a tool id: "spades_like" becomes "SPAdes-like", but a file name such as
    "spades_like.per_plasmid.tsv" is left alone;
  * SVG <title> tooltips are text and are renamed;
  * whole ids only: 'toolA' is not replaced inside 'toolAB' or 'my-toolA';
  * idempotent: a display name is not itself an id, and running it twice changes nothing.

The page script stays as a fallback for content built in the browser.

Standard library only.
"""
import re

SKIP_TAGS = {"code", "pre", "option", "template"}
RAW_TEXT = {"script", "style", "textarea"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_TOKEN = re.compile(r"<!--.*?-->|<(/?)([A-Za-z][A-Za-z0-9:-]*)((?:[^>\"']|\"[^\"]*\"|'[^']*')*)>", re.S)


def _pattern(labels):
    names = sorted((n for n in labels if n and labels[n] != n), key=len, reverse=True)
    if not names:
        return None
    return re.compile(r"(?<![A-Za-z0-9_-])(" + "|".join(re.escape(n) for n in names) + r")(?![A-Za-z0-9_-])")


def humanise(page, labels):
    """`page` with every whole tool id in its text nodes replaced by labels[id]; the page itself when there is nothing to rename."""
    pattern = _pattern(labels)
    if pattern is None or not page:
        return page
    out, pos, skip, in_link = [], 0, [], 0

    def rename(text):
        if skip:
            return text
        if in_link:                                   # a link's text is renamed only when it is exactly one tool id
            core = text.strip()
            return text.replace(core, labels[core], 1) if core in labels and labels[core] != core else text
        return pattern.sub(lambda t: labels[t.group(1)], text)

    i = 0
    while True:
        m = _TOKEN.search(page, i)
        if not m:
            break
        out.append(rename(page[pos:m.start()]))
        out.append(m.group(0))
        pos = i = m.end()
        if m.group(0).startswith("<!--"):
            continue
        closing, name, attrs = m.group(1), m.group(2).lower(), m.group(3)
        if name in RAW_TEXT and not closing:
            close = re.compile(r"</" + name + r"\s*>", re.I).search(page, i)
            end = close.start() if close else len(page)
            out.append(page[i:end])          # a raw-text body is never renamed
            pos = i = end
            continue
        if name in VOID or attrs.rstrip().endswith("/"):
            continue
        if name == "a":
            in_link = max(0, in_link - 1) if closing else in_link + 1
            continue
        if name in SKIP_TAGS:
            if closing:
                for k in range(len(skip) - 1, -1, -1):
                    if skip[k] == name:
                        del skip[k:]
                        break
            else:
                skip.append(name)
    out.append(rename(page[pos:]))
    return "".join(out)
