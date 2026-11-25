#!/usr/bin/env python3
"""The console follows new output only while you are at the bottom: scroll up and it stays where you are (the button says "Jump to latest"), scroll back down or press the button and it
follows again; a scroll the page makes itself is not taken for yours; the Terminal tab behaves the same except that a command you just typed is always shown. The page's own functions run
under node against a simulated scroll box."""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
OK = True


def check(label, good, detail=""):
    global OK
    print(f"  {label}: {'PASS' if good else 'FAIL'}" + ("" if good else f"  [{detail}]"))
    OK = OK and bool(good)


check("the poll scrolls only when following (no unconditional jump to the end)", 'if (S.follow) toBottom($("#clog"));' in html and '$("#clog").scrollTop = $("#clog").scrollHeight' not in html)
check("a scroll by the person turns following off or on by position", '$("#clog").addEventListener("scroll", () => { if (!S._progScroll) setFollow(nearBottom($("#clog"))); }' in html)
check("a new job follows again", 'S.consOffset = 0; S.tail = ""; $("#clog").innerHTML = ""; setFollow(true); }' in html)
check("the button reads 'Jump to latest' when not following and jumps then follows", "Jump to latest" in html and 'setFollow(true); toBottom($("#clog"));' in html)
check("the Terminal output follows only near the bottom, but always shows a command you typed", "stay = nearBottom(b) || html.indexOf('class=\"t-cmd\"') >= 0" in html)
node = shutil.which("node")
if not node:
    print("  n/a   node is not installed: the behaviour under a simulated scroll box is not run here")
else:
    a = html.index("const SCROLL_NEAR")
    b = html.index("let polling = false;")
    code = html[a:b]
    harness = """
const S = {follow: true, _progScroll: false};
const els = {"#cfollow": {textContent: "Follow", style: {}, attrs: {}, title: "", setAttribute(k, v) { this.attrs[k] = v; }}};
const $ = sel => els[sel];
let raf = []; const requestAnimationFrame = f => raf.push(f); const flush = () => { const r = raf; raf = []; r.forEach(f => f()); };
""" + code + """
const box = {scrollHeight: 1000, clientHeight: 200, scrollTop: 800};
const out = [];
const t = (label, ok) => out.push(label + ": " + (ok ? "PASS" : "FAIL"));
t("at the bottom counts as near", nearBottom(box));
box.scrollTop = 300; t("scrolled up is not near", !nearBottom(box));
box.scrollTop = 770; t("within 40 px of the end is still near", nearBottom(box));
// the person scrolls up: following turns off, the button changes
box.scrollTop = 300; setFollow(nearBottom(box)); t("scrolling up turns following off", S.follow === false && els["#cfollow"].textContent.includes("Jump to latest"));
// new output arrives: the page does not move the box while not following
const before = box.scrollTop; if (S.follow) toBottom(box); t("new output does not move a box you scrolled up", box.scrollTop === before);
// the person scrolls back to the bottom: following turns on
box.scrollTop = 800; setFollow(nearBottom(box)); t("scrolling back to the bottom turns following on", S.follow === true && els["#cfollow"].textContent === "Follow");
// following: the page scrolls itself, and its own scroll event is ignored
box.scrollHeight = 1400; if (S.follow) toBottom(box); t("while following, new output scrolls to the end", box.scrollTop === 1400 && S._progScroll === true);
const ignored = S._progScroll; if (!S._progScroll) setFollow(false); t("the page's own scroll event is not taken as the person's", ignored === true && S.follow === true);
flush(); t("the guard clears after the frame", S._progScroll === false);
// the button
setFollow(false); t("pressing the button while following pauses it", S.follow === false);
setFollow(true); toBottom(box); t("pressing it again follows and jumps to the end", S.follow === true && box.scrollTop === box.scrollHeight);
console.log(out.join("|"));
"""
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "h.js"
        f.write_text(harness, encoding="utf-8")
        done = subprocess.run([node, str(f)], capture_output=True, text=True, timeout=60)
    lines = [l for l in done.stdout.strip().split("|") if l.strip()]
    check("node ran the page's scroll functions", done.returncode == 0 and len(lines) >= 9, done.stderr[:500])
    for line in lines:
        label, _, verdict = line.rpartition(": ")
        check(label, verdict == "PASS")
print("ALL CONSOLE SCROLL TESTS PASSED" if OK else "CONSOLE SCROLL TESTS FAILED")
sys.exit(0 if OK else 1)
