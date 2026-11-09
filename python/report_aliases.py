"""Legacy report section ids and where they live now.

The report once had one top-level section per analysis. When sections are merged into a
container (as a tab or panel) the old id is kept on the panel and recorded here as
``LEGACY_IDS[old_id] = (container_id, panel_id)`` so that

  * prose links written as ``href='#old_id'`` (see ``link``) keep resolving,
  * the navigation and the surfaces inventory can open the container on the right tab,
  * test/report_regions.py can find the text of a merged analysis by its old id.

The mapping is empty while every analysis is still its own section; the container merge fills it.
Use ``resolve`` rather than writing a section id by hand in any sentence that points at another
part of the page.
"""

LEGACY_IDS = {}


def resolve(section_id):
    """Return the id an in-page link should target for ``section_id``.

    A legacy id resolves to the panel that now carries it (the panel keeps the old id, so the
    link target stays the same string); an id that is its own section resolves to itself.
    """
    entry = LEGACY_IDS.get(section_id)
    if not entry:
        return section_id
    container, panel = entry
    return panel or container


def container_of(section_id):
    """The top-level container section that holds ``section_id`` (itself when it is top level)."""
    entry = LEGACY_IDS.get(section_id)
    return entry[0] if entry else section_id


def link(section_id, label):
    """An in-page anchor to ``section_id`` that survives a merge: ``<a href='#id'>label</a>``."""
    return f"<a href='#{resolve(section_id)}'>{label}</a>"
