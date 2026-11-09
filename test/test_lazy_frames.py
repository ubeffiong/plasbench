#!/usr/bin/env python3
"""
The two explorers (7 to 8 MB each) are written into their iframes only when needed.

build_html_report.lazy_frame_js(doc_id) defines lazyFrame(f). Run in node against a stub DOM (hand-checked cases):
  - nothing is written at start (srcdoc stays unset) and the placeholder stays visible;
  - an IntersectionObserver callback with isIntersecting=false does nothing; with true it writes the document once, hides the placeholder and
    disconnects; the end-of-script sentinel in the stored text is turned back into '</scr' + 'ipt' ('x' + SENT + 'y' -> 'x</scriptY'... exactly '</script');
  - the Load now button writes it; f.pbLoad() writes it; loading twice writes once;
  - ?print=1 (the PDF export), a beforeprint event, and a browser without IntersectionObserver all write it at once;
  - a missing frame is a no-op.
The built demo report: neither frame assignment is outside the loader, both placeholders and their Load now buttons exist, the observer margin is set.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))

import build_html_report as b  # noqa: E402

NODE = shutil.which("node")

HARNESS = r"""
const fs = require('fs');
const loader = fs.readFileSync(process.argv[2], 'utf8');
function scenario(opts) {
  const log = {srcdocWrites: 0, srcdoc: undefined, observed: 0, disconnected: 0, listeners: {}};
  const noteBtnHandlers = [];
  const note = {hidden: false, querySelector: () => ({addEventListener: (t, fn) => noteBtnHandlers.push(fn)})};
  const frame = {dataset: {}, parentElement: {querySelector: () => (opts.noNote ? null : note)},
                 set srcdoc(v) { log.srcdocWrites++; log.srcdoc = v; }, get srcdoc() { return log.srcdoc; }};
  let observerCb = null;
  const win = {location: {search: opts.search || ''}, addEventListener: (t, fn) => { (log.listeners[t] = log.listeners[t] || []).push(fn); }};
  if (!opts.noIO) {
    win.IntersectionObserver = function (cb, o) { observerCb = cb; log.margin = o && o.rootMargin; this.observe = () => { log.observed++; }; this.disconnect = () => { log.disconnected++; }; };
  }
  const doc = {getElementById: () => ({textContent: 'x' + opts.sentinel + 'y'})};
  const fn = new Function('document', 'location', 'window', 'IntersectionObserver', loader + '; return lazyFrame;');
  const lazyFrame = fn(doc, win.location, win, win.IntersectionObserver);
  lazyFrame(opts.nullFrame ? null : frame);
  return {log, frame, note, noteBtnHandlers, fire: (entries) => observerCb && observerCb(entries)};
}
const sentinel = process.argv[3];
const out = {};
let s = scenario({sentinel});
out.start = {writes: s.log.srcdocWrites, noteHidden: s.note.hidden, observed: s.log.observed, margin: s.log.margin};
s.fire([{isIntersecting: false}]); out.notVisible = s.log.srcdocWrites;
s.fire([{isIntersecting: true}]); out.visible = {writes: s.log.srcdocWrites, srcdoc: s.log.srcdoc, noteHidden: s.note.hidden, disconnected: s.log.disconnected};
s.frame.pbLoad(); out.twice = s.log.srcdocWrites;
s = scenario({sentinel}); s.noteBtnHandlers[0](); out.button = {writes: s.log.srcdocWrites, noteHidden: s.note.hidden};
s = scenario({sentinel}); s.frame.pbLoad(); out.api = s.log.srcdocWrites;
s = scenario({sentinel, search: '?print=1'}); out.print = s.log.srcdocWrites;
s = scenario({sentinel, search: '?foo=1&print'}); out.printLast = s.log.srcdocWrites;
s = scenario({sentinel, search: '?printer=1'}); out.notPrint = s.log.srcdocWrites;
s = scenario({sentinel, noIO: true}); out.noIO = s.log.srcdocWrites;
s = scenario({sentinel}); (s.log.listeners.beforeprint || []).forEach(f => f()); out.beforeprint = s.log.srcdocWrites;
s = scenario({sentinel, nullFrame: true}); out.nullFrame = 'ok';
s = scenario({sentinel, noNote: true}); s.fire([{isIntersecting: true}]); out.noNote = s.log.srcdocWrites;
console.log(JSON.stringify(out));
"""


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    print("the loader (node)")
    if not NODE:
        print("  SKIPPED: node is not installed, so the loader behaviour was not exercised")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            loader = os.path.join(tmp, "loader.js")
            harness = os.path.join(tmp, "harness.js")
            with open(loader, "w", encoding="utf-8") as handle:
                handle.write(b.lazy_frame_js("doc"))
            with open(harness, "w", encoding="utf-8") as handle:
                handle.write(HARNESS)
            done = subprocess.run([NODE, harness, loader, b.SCRIPT_END_SENTINEL], capture_output=True, text=True, encoding="utf-8")
            check("the harness ran", done.returncode == 0, done.stderr[-400:])
            r = json.loads(done.stdout.strip().splitlines()[-1]) if done.returncode == 0 else {}
            check("nothing is written at start; the placeholder stays; the frame is observed with a margin",
                  r.get("start") == {"writes": 0, "noteHidden": False, "observed": 1, "margin": "400px 0px"}, r.get("start"))
            check("an observer callback with isIntersecting=false writes nothing", r.get("notVisible") == 0)
            check("when the frame becomes visible it is written once, the sentinel becomes </script, the placeholder hides and the observer disconnects",
                  r.get("visible") == {"writes": 1, "srcdoc": "x</scripty", "noteHidden": True, "disconnected": 1}, r.get("visible"))
            check("loading a second time writes nothing", r.get("twice") == 1)
            check("the Load now button loads it", r.get("button") == {"writes": 1, "noteHidden": True}, r.get("button"))
            check("f.pbLoad() loads it on demand", r.get("api") == 1)
            check("?print=1 (the PDF export) loads it at once", r.get("print") == 1 and r.get("printLast") == 1)
            check("a query that only starts with 'print' (?printer=1) does not", r.get("notPrint") == 0)
            check("a beforeprint event loads it", r.get("beforeprint") == 1)
            check("a browser without IntersectionObserver loads it at once", r.get("noIO") == 1)
            check("a missing frame is a no-op, and a missing placeholder does not break loading", r.get("nullFrame") == "ok" and r.get("noNote") == 1)

    print("the built demo report")
    report = os.path.join(HERE, "..", "results_demo", "benchmark.report.html")
    if not os.path.isfile(report):
        print("  SKIP: no results_demo report")
    else:
        text = open(report, encoding="utf-8").read()
        loader_js = b.lazy_frame_js("pb-enterprise-doc")
        check("each frame script defines the loader once and calls it for its frame",
              text.count("const lazyFrame=f=>") == 2 and "lazyFrame(f);" in text and text.count("lazyFrame(f);") == 2, text.count("const lazyFrame=f=>"))
        stray = [m.start() for m in re.finditer(r"f\.srcdoc=raw\.split", text)]
        check("the srcdoc assignment exists only inside the loaders (two), never at page load", len(stray) == 2, len(stray))
        check("both placeholders and their Load now buttons are in the page", text.count("class='pb-lazy-note'") == 2 and text.count(">Load now</button>") == 2)
        check("the document text is still in the page (one offline file)", "id='pb-enterprise-doc'" in text and "id='pb-explorer-doc'" in text)
        check("the loader text is identical to the helper's output", loader_js in text)

    print()
    if not ok:
        print("LAZY FRAME TESTS FAILED")
        sys.exit(1)
    print("ALL LAZY FRAME TESTS PASSED")


if __name__ == "__main__":
    main()
