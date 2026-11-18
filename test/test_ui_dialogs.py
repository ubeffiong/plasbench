#!/usr/bin/env python3
"""The window has no browser alert / confirm / prompt: one designed, accessible dialog component (modalDialog, askConfirm, askText, showMessage) serves every call site.

Static checks over plasbench/data/ui.html (no browser is available to the suite): no `alert(`, `confirm(` or `prompt(` outside the component, every former call site
awaits the component, and the component carries role=dialog / alertdialog, aria-modal, aria-labelledby / aria-describedby, a Tab trap, Escape = cancel, Enter = the default
button (the SAFE one for destructive dialogs), a danger style, a type-the-name confirmation, no confirm on a backdrop click, and returns focus to the opener.
The page script is also parsed with `node --check` when node exists.
"""
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


def main():
    start = HTML.index("let DLG_N = 0;")
    end = HTML.index("/* ---- help tooltip: an (i) button")
    component = HTML[start:end]
    outside = HTML[:start] + HTML[end:]
    bad = re.findall(r"(?<![\w.$])(?:alert|confirm|prompt)\s*\(", outside)
    check("no alert( / confirm( / prompt( outside the component", not bad, bad)
    check("the component itself does not call them either", not re.findall(r"(?<![\w.$])(?:alert|confirm|prompt)\s*\(", component))
    check("old call sites are converted (await askConfirm / askText)", outside.count("await askConfirm(") >= 12 and "await askText(" in outside, outside.count("await askConfirm("))
    for needle, what in (('role", o.danger ? "alertdialog" : "dialog"', "role=dialog / alertdialog"), ('"aria-modal", "true"', "aria-modal"), ('"aria-labelledby"', "labelled"),
                         ('"aria-describedby"', "described"), ('e.key === "Tab"', "focus trap"), ('d.addEventListener("cancel"', "Escape cancels"),
                         ('e.key === "Enter"', "Enter = default button"), ("opener.focus", "focus returns to the opener"), ("if (e.target === d) return;", "backdrop click does not confirm"),
                         ("typeToConfirm", "type the name to confirm"), ('class="btn ${b.danger ? "danger"', "danger style"), ("danger ? cancelId", "safe button is the default for destructive dialogs"),
                         ("<dl class=\"facts\">", "facts list")):
        check(f"dialog: {what}", needle in component, needle)
    check("askConfirm: a destructive dialog defaults to cancel", 'defaultId: o.danger ? "cancel" : "ok"' in component)
    check("dark theme and phone width: styled with theme variables and a narrow-screen rule", "dialog.pbdlg{width:min(540px,calc(100vw - 24px))" in HTML and "@media (max-width:480px){dialog.pbdlg" in HTML and "dialog.pbdlg.danger{border-top:3px solid var(--bad)}" in HTML)
    check("no library: no script src", not re.search(r"<script[^>]+src=", HTML))
    check("the cancel-run dialog shows the run and says what is kept", all(k in component for k in ('title: "Cancel this run?"', 'cancelLabel: "Keep running"', 'confirmLabel: "Cancel run"',
                                                                                                         "Finished work is kept and you can Resume it later.", '["Run", j.label]', '["Command"', '["Started"', '["Stage"')))
    check("every way to cancel a run uses it", all(k in HTML for k in ("await askCancelRun(id)", "await askCancelRun(S.consJob)")))
    check("Quit uses the component", "async function askQuit(running) {\n  const r = await modalDialog(" in HTML)
    check("the Runs page offers Remove from list and Delete folder separately", "Remove from list: the files stay on disk" in HTML and "Delete folder: removes everything in it, for good" in HTML)
    node = shutil.which("node")
    if node:
        script = max(re.findall(r"<script[^>]*>(.*?)</script>", HTML, re.S), key=len)
        path = Path(tempfile.mkdtemp()) / "page.js"
        path.write_text(script, encoding="utf-8")
        done = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
        check("node --check of the page script passes", done.returncode == 0, done.stderr[:300])
    else:
        print("  skip  node not found")
    print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL PASS")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
