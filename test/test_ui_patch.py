#!/usr/bin/env python3
"""The window must not redraw what did not change (study tree, Runs list, Jobs table, side panel).

Bug: "the study tree keeps refreshing and reloading the screen". The side panel's study tree was rebuilt (and every open folder re-filled behind a "Loading..." row) every 15 s, and the Runs
list, Jobs table, job selector and tables were replaced on every 4 s poll. Now the pure helpers (listSignature, diffKeyed, treeSignature, isBusy, in the PURE block of plasbench/data/ui.html)
decide what changed; rows are patched by key; setIfChanged skips an unchanged container; automatic refresh is suspended while a dialog or menu is open, the pointer is over the tree or focus is in it.

  - node test (skipped with a printed reason when node is missing) of the pure helpers;
  - static checks: no poll handler assigns the tree container's innerHTML, refresh is suspended during dialogs / menus, the timers are slow, the Folders tree is patched by key.
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def body_of(name):
    """The source of `function name` / `async function name` up to its closing brace at column 0."""
    m = re.search(r"^(?:async )?function " + re.escape(name) + r"\b.*?^\}", HTML, re.S | re.M)
    return m.group(0) if m else ""


def main():
    pure = HTML.split("runs this block under node) */")[1].split("/* ==PURE-END== */")[0]
    node = shutil.which("node")
    if not node:
        print("  skip  node not found: the pure helpers are not executed (static checks below still run)")
    else:
        script = pure + r"""
const out = {};
const e1 = [{name: "a", kind: "dir", mtime: 1, size: null, children: 2}, {name: "b", kind: "file", mtime: 2, size: 10, children: null}];
out.sigSame = listSignature(e1) === listSignature(JSON.parse(JSON.stringify(e1)));
out.sigMtime = listSignature(e1) !== listSignature([e1[0], Object.assign({}, e1[1], {mtime: 3})]);
out.sigSize = listSignature(e1) !== listSignature([e1[0], Object.assign({}, e1[1], {size: 11})]);
out.sigName = listSignature(e1) !== listSignature([e1[0]]);
out.sigEmpty = listSignature(undefined) === "";
const d0 = diffKeyed([["a", "1"], ["b", "2"], ["c", "3"]], [{key: "a", sig: "1"}, {key: "b", sig: "2"}, {key: "c", sig: "3"}]);
out.noop = d0.remove.length + d0.insert.length + d0.update.length === 0 && d0.reorder === false;
const d1 = diffKeyed([["a", "1"], ["b", "2"], ["c", "3"]], [{key: "a", sig: "1"}, {key: "b", sig: "X"}, {key: "d", sig: "4"}]);
out.ops = JSON.stringify([d1.remove, d1.insert, d1.update, d1.reorder]);
const d2 = diffKeyed([["a", "1"], ["b", "2"]], [{key: "b", sig: "2"}, {key: "a", sig: "1"}]);
out.reorder = d2.reorder === true && d2.update.length === 0;
out.tree = treeSignature({"/w": {entries: e1}}, ["/w"]) === treeSignature({"/w": {entries: e1}}, ["/w"]) && treeSignature({"/w": {entries: e1}}, ["/w"]) !== treeSignature({"/w": {entries: e1.slice(1)}}, ["/w"]) && treeSignature({}, ["/x"]).endsWith("=?");
out.busy = [isBusy({}), isBusy({dialog: true}), isBusy({menu: true}), isBusy({pointer: true}), isBusy({focus: true})].join();
console.log(JSON.stringify(out));
"""
        path = Path(tempfile.mkdtemp()) / "pure.js"
        path.write_text(script, encoding="utf-8")
        done = subprocess.run([node, str(path)], capture_output=True, text=True)
        try:
            out = json.loads(done.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            out = {}
            check("the pure block runs under node", False, done.stderr[:300])
        if out:
            check("listSignature: equal for equal listings, differs on mtime, size and names", out["sigSame"] and out["sigMtime"] and out["sigSize"] and out["sigName"] and out["sigEmpty"], out)
            check("diffKeyed: an unchanged list needs no operation at all", out["noop"], out)
            check("diffKeyed: removes, inserts and updates exactly the rows that differ", out["ops"] == '[["c"],["d"],["b"],false]', out["ops"])
            check("diffKeyed: a changed order is reported, without updates", out["reorder"], out)
            check("treeSignature: changes when a listing changes, marks an unknown folder", out["tree"], out)
            check("isBusy: false when idle, true for a dialog, a menu, the pointer or focus", out["busy"] == "false,true,true,true,true", out["busy"])

    print("static")
    tree_poll = [body_of(n) for n in ("wtBackground",)]
    check("the background check never assigns the tree container's innerHTML", all("#wt_tree\").innerHTML" not in b and "tree.innerHTML" not in b for b in tree_poll) and bool(tree_poll[0]))
    render = body_of("wtRender")
    check("wtRender patches by key (applyKeyed) and never sets the tree's innerHTML", "applyKeyed(tree, items, wtRowHTML)" in render and "tree.innerHTML" not in render and '$("#wt_tree").innerHTML' not in render)
    check("expansion, selection and focus stay in WT; a refresh moves focus only when asked", "focus) $(\"#wt_tree\")" in render and "const WT = {top: null, root: null, open: new Set()" in HTML)
    bg = body_of("wtBackground")
    check("the background check is suspended while a dialog or menu is open, the pointer is over the tree or focus is in it", 'uiBusy(["#wt_card"])' in bg and "dialog[open]" in body_of("uiBusy") and "CTX" in body_of("uiBusy") and ":hover" in body_of("uiBusy"))
    check("it is slow (25 s) and also runs when the tab becomes visible", "setInterval(() => wtBackground(false), 25000)" in HTML and 'visibilitychange", () => { if (!document.hidden) wtBackground(false)' in HTML)
    check("the tree compares a cheap signature before redrawing", "treeSignature(WT.cache, paths)" in bg and "after !== before" in bg)
    check("the side panel timer is slow and suspended while the tree or a dialog is busy", 'uiBusy(["#ps_list", "#gd_body"])' in HTML and "}, 30000);" in HTML and "}, 15000);" not in HTML)
    panel = body_of("loadPanelStudies")
    check("the side panel's study tree is patched: no innerHTML of the list, headers only, open folders kept", "diffKeyed(" in panel and '$("#ps_list").innerHTML =' not in panel and ":scope > .tn\").outerHTML" in panel)
    check("treeFill leaves an unchanged folder alone", "setIfChanged(ul," in body_of("treeFill") and "ul.innerHTML =" not in body_of("treeFill"))
    check("setIfChanged skips an unchanged container and keeps scroll and focus", "el._html === html" in body_of("setIfChanged") and "scrollTop" in body_of("setIfChanged") and "focus({preventScroll: true})" in body_of("setIfChanged"))
    for what, needle in (("the Runs sessions list", 'setIfChanged($("#sesslist")'), ("the session tabs", 'setIfChanged($("#sesstabs")'), ("the Jobs table", 'setIfChanged($("#jobtb")'), ("the side panel jobs", 'setIfChanged($("#pj_list")'),
                         ("the studies table", 'setIfChanged($("#ws_tb")'), ("the Runs list", 'setIfChanged($("#runlist")')):
        check(f"{what} is only redrawn when its content changed", needle in HTML)
    jobs_poll = body_of("refreshJobs")
    check("the job selector is not rebuilt while the user has it open", "document.activeElement !== sel" in jobs_poll and "sel._html !== selHTML" in jobs_poll)
    print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL PASS")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
