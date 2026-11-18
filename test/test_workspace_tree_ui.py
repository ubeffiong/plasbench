#!/usr/bin/env python3
"""The Workspace page's folder tree, breadcrumb bar and right-click menu (static checks of plasbench/data/ui.html; no browser is available to the suite).

Tree: role=tree / treeitem with aria-level, aria-expanded and aria-selected, a roving tabindex, lazy loading through /api/fs/list one folder at a time, keys (arrows, Enter,
Home/End, Left/Right, *, Delete, F5, Shift+F10 and the Menu key). Breadcrumb: click-to-navigate segments, Up, Workspace, a path box. Menu: role=menu / menuitem, Escape, outside
click, scroll, viewport flip, arrow keys, and the items the brief lists; Delete only for runs and, through Manage, studies. Controls carry tooltips.
"""
import re
import sys
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def has(*needles):
    return all(n in HTML for n in needles)


def main():
    check("tree: role=tree with a label and treeitems with level / expanded / selected", has('role="tree" id="wt_tree"', 'role="treeitem" aria-level=', 'aria-expanded="${open}"', 'aria-selected="${sel}"'))
    check("tree: roving tabindex", 'tabindex="${sel ? 0 : -1}"' in HTML)
    check("tree: lazy, one folder per request", "api(`fs/list?path=${encodeURIComponent(path)}`)" in HTML and "WT.open.has(p)" in HTML)
    for key in ('"ArrowDown"', '"ArrowUp"', '"ArrowRight"', '"ArrowLeft"', '"Home"', '"End"', '"Enter"', '"*"', '"Delete"', '"F5"', '"ContextMenu"', 'e.key === "F10" && e.shiftKey'):
        check(f"tree key {key}", key in HTML.split("(function wtBind()")[1])
    check("breadcrumb: click-to-navigate segments, Up, Workspace, path box", has('id="wt_crumbs"', "data-wtgo", 'id="wt_up"', 'id="wt_home"', 'id="wt_path"', 'aria-label="Folder path"'))
    check("breadcrumb marks the current segment", 'aria-current="location"' in HTML)
    check("context menu: role=menu / menuitem, labelled", has('setAttribute("role", "menu")', 'role="menuitem"', 'setAttribute("aria-label", "Actions")'))
    ctx = HTML.split("function ctxMenu(")[1].split("document.addEventListener(\"contextmenu\"")[0]
    check("context menu: Escape, outside click, scroll, resize close it", all(k in ctx for k in ('e.key === "Escape"', '"mousedown"', '"scroll"', '"resize"')))
    check("context menu: arrow keys, Home, End", all(k in ctx for k in ('"ArrowDown"', '"ArrowUp"', '"Home"', '"End"')))
    check("context menu: flips at the viewport edge", "x + w > innerWidth - 8" in ctx and "y + h > innerHeight - 8" in ctx)
    for label in ("Open folder", "Open report", "Open in terminal here", "Copy full path", "Copy path relative to the workspace", "Properties…", "Refresh", "Expand", "Collapse", "Manage study…", "Delete run folder…"):
        check(f"menu item: {label}", f'"{label}"' in HTML or f'label: "{label}"' in HTML or f"{label}" in HTML.split("function wtItemFor(")[1].split("async function wtOpenFile")[0], label)
    items = HTML.split("function wtItemFor(")[1].split("async function wtOpenFile")[0]
    check("Delete is offered only for results folders (and Manage for studies), never for arbitrary files or folders", items.count("Delete run folder") == 1 and "if (isRes)" in items and "deleteRun(" in items)
    check("studies table rows have the same menu", "tr[data-spath]" in HTML and 'data-spath="${esc(st.path)}"' in HTML)
    check("Open in terminal here uses the terminal's cd", 'command: "cd " + dir' in HTML and 'setCTab("term")' in HTML)
    check("Properties uses the dialog component and shows the facts", "Properties: ${p.name}" in HTML and '"Tracked by git"' in HTML and '"Study notes"' in HTML)
    check("the new controls carry tooltips", all(k in HTML for k in ('title="Up one folder"', 'title="Back to the workspace folder"', 'title="Refresh the tree (F5)"', 'title="Type a folder inside the workspace and press Enter"', 'id="wt_tip"')))
    check("the old directory list still loads (Workspace page refreshes the tree)", "wtInit(!!force);" in HTML)
    check("themed with variables, no library", "var(--surface)" in HTML.split(".ctxmenu{")[1][:200] and not re.search(r"<script[^>]+src=", HTML))
    print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL PASS")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
