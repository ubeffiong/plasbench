"""Find a region of the built report by its (old or current) id, for the feature-manifest test.

region(html, id) returns the markup of
  * the <section id=...> with that id, or
  * any other element with that id (a panel or tab pane inside a container), or
  * the panel/container an alias in python/report_aliases.LEGACY_IDS points at.
Sections are never nested, so a section ends at the next </section>; any other element is
balanced by counting same-name tags.
"""
import html as _html
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))

import report_aliases  # noqa: E402

ID_RE = r"""<([a-zA-Z][a-zA-Z0-9]*)\b[^>]*?\bid\s*=\s*(?:'%s'|"%s")[^>]*>"""


def strip_scripts(page):
    return re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", page, flags=re.S | re.I)


def text_of(markup):
    """Visible text: scripts, styles and tags removed, entities decoded, whitespace collapsed."""
    plain = re.sub(r"<[^>]+>", " ", strip_scripts(markup))
    return re.sub(r"\s+", " ", _html.unescape(plain)).strip()


def _balanced(page, start, tag):
    depth = 0
    for match in re.finditer(r"<(/?)%s\b[^>]*>" % re.escape(tag), page[start:], re.I):
        if match.group(1):
            depth -= 1
            if depth == 0:
                return page[start:start + match.end()]
        elif not match.group(0).endswith("/>"):
            depth += 1
    return page[start:]


def _find(page, ident):
    match = re.search(ID_RE % (re.escape(ident), re.escape(ident)), page)
    if not match:
        return None
    tag = match.group(1).lower()
    if tag == "section":
        end = page.find("</section>", match.start())
        return page[match.start(): end + len("</section>")] if end >= 0 else page[match.start():]
    return _balanced(page, match.start(), tag)


def region(page, ident):
    """Markup for ``ident``; '' when neither the id nor an alias resolves."""
    found = _find(page, ident)
    if found is not None:
        return found
    entry = report_aliases.LEGACY_IDS.get(ident)
    if entry:
        container, panel = entry
        for candidate in (panel, container):
            found = _find(page, candidate) if candidate else None
            if found is not None:
                return found
    return ""


def id_exists(page, ident):
    return bool(region(page, ident))


def hrefs(markup):
    from urllib.parse import unquote
    return [unquote(_html.unescape(a or b))
            for a, b in re.findall(r"""<a\s[^>]*?href\s*=\s*(?:'([^']*)'|"([^"]*)")""", markup)]


def tables(markup):
    """Each <table> as (open_tag, [header texts])."""
    out = []
    for m in re.finditer(r"<table\b([^>]*)>(.*?)</table>", strip_scripts(markup), re.S | re.I):
        heads = [text_of(x) for x in re.findall(r"<th\b[^>]*>(.*?)</th>", m.group(2), re.S | re.I)]
        out.append((m.group(1), [h for h in heads if h]))
    return out
