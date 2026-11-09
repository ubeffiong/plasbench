"""Legacy report section ids and where they live now.

The report once had one top-level section per analysis. python/report_merge.py folds related analyses into
one container section as tabs; the folded section keeps its old id on the tab panel, and records it here as
``LEGACY_IDS[old_id] = (container_id, tab_label)`` (report_merge fills the table from its MERGES table when it
is imported; this module imports it at the bottom so the table is complete for every caller) so that

  * prose links written as ``href='#old_id'`` (see ``link``) keep resolving: the panel carries the old id,
  * the navigation opens the container's view and selects that tab (report_layout, assets/report/merge_script.html),
  * the surfaces inventory can name the container and the tab (``where``),
  * test/report_regions.py can find the text of a merged analysis by its old id.

Use ``link`` rather than writing ``<a href='#id'>`` by hand in any sentence that points at another part of the
page. An id that was never merged is its own section and resolves to itself.
"""

LEGACY_IDS = {}


def resolve(section_id):
    """The id an in-page link should target for ``section_id``.

    A merged id resolves to itself: the tab panel keeps the old id, so the link target is unchanged.
    """
    return section_id


def container_of(section_id):
    """The top-level container section that holds ``section_id`` (itself when it is top level)."""
    entry = LEGACY_IDS.get(section_id)
    return entry[0] if entry else section_id


def tab_of(section_id):
    """The tab label of a merged section, or '' for a section that is top level."""
    entry = LEGACY_IDS.get(section_id)
    return entry[1] if entry else ""


def is_legacy(section_id):
    return section_id in LEGACY_IDS


def where(section_id, title=None):
    """Where a merged section is shown, e.g. 'Ranking confidence, tab Paired tests' (``title`` names the container)."""
    entry = LEGACY_IDS.get(section_id)
    if not entry:
        return title or section_id
    return f"{title or entry[0]}, tab {entry[1]}"


def link(section_id, label):
    """An in-page anchor to ``section_id`` that survives a merge: ``<a href='#id'>label</a>``."""
    return f"<a href='#{resolve(section_id)}'>{label}</a>"


try:                                  # fill LEGACY_IDS from report_merge.MERGES (a circular import is fine: LEGACY_IDS exists above)
    import report_merge  # noqa: E402,F401
except ModuleNotFoundError as exc:    # a stripped-down install without the merge step keeps the table empty
    if exc.name != "report_merge":
        raise
