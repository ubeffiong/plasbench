#!/usr/bin/env python3
"""The window's Markdown converter (plasbench/data/ui.html `md`) always finishes, and every guide opens at once.

Opening the README in the Guides page froze the window. The converter knew headings up to level 4; a `##### ...` line matched no rule, and the paragraph rule refused to
take a line starting with '#', so the loop never advanced. README.md has such a heading (line 2168), so that guide could not be opened. The converter now knows levels 1-6, the loop
must consume a line on every pass, and a stuck pass takes the line as plain text.

The real function is cut out of ui.html and run in Node (skipped, with a reason, when node is not installed).
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


NODE = shutil.which("node")
if not NODE:
    print("  skip  node is not installed: the Markdown converter was not run")
    print("ALL UI MARKDOWN TESTS PASSED (skipped)")
    sys.exit(0)

page = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
check("the converter knows headings up to level 6", "#{1,6}" in page and "(#{1,4})" not in page)
check("a pass that consumes nothing is forced on (the loop cannot stall)", "stuck" in page.split("function md(src)")[1].split("function pickPath")[0])

docs = [p for p in [ROOT / "README.md", ROOT / "FAQ.md", ROOT / "CHANGELOG.md", *sorted((ROOT / "docs").glob("*.md"))] if p.is_file()]
script = r"""
const fs = require("fs");
const page = fs.readFileSync(process.argv[2], "utf8");
const start = page.indexOf("function md(src) {");
const end = page.indexOf("/* ====", start);
const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
eval(page.slice(start, end).replace("function md(src)", "globalThis.md = function(src)"));
const out = {};
const time = (name, fn) => { const t = Date.now(); let r; try { r = fn(); } catch (e) { r = "ERROR " + e.message; } out[name] = {ms: Date.now() - t, r: typeof r === "string" ? r.slice(0, 300) : r}; };
time("h5", () => md("##### Metagenomic preparation: full laboratory flow"));
time("h6", () => md("###### Six"));
time("h7", () => md("####### seven hashes is not a heading, but must not hang"));
time("nospace", () => md("#hashtag and more\n#another"));
time("bare hash", () => md("#\n##\n###\n"));
time("mixed", () => md("intro\n##### five\ntext after\n\n- item\n##### five in a list\n1. one\n##### again\n> quote\n##### more\n| a | b |\n|---|---|\n| 1 | 2 |\n##### end"));
time("unclosed fence", () => md("```\ncode never closed\n##### inside\n"));
time("lonely table row", () => md("| only one row |"));
time("many stars and brackets", () => md("*a* **b** [c](d) [e] ( * ) `f` " + "[x ".repeat(2000) + "* ".repeat(2000)));
// randomised stress: 3000 documents of random Markdown-looking lines; every one must return
const toks = ["#", "##", "#####", "######", "####### ", "- ", "* ", "1. ", "> ", "|", "---", "```", "text", " ", "**b**", "`c`", "[l](u)", "\t", "    indent", "", "***", "|---|", "\\"];
let seed = 12345; const rnd = n => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed % n; };
time("fuzz", () => { let n = 0; for (let d = 0; d < 3000; d++) { const lines = []; for (let k = 0, m = 1 + rnd(12); k < m; k++) { let l = ""; for (let t = 0, tm = rnd(5); t < tm; t++) l += toks[rnd(toks.length)] + (rnd(2) ? " " : ""); lines.push(l); } md(lines.join("\n")); n++; } return n; });
for (const f of process.argv.slice(3)) { const text = fs.readFileSync(f, "utf8"); time("doc:" + f, () => { const h = md(text); return h.length; }); }
console.log(JSON.stringify(out));
"""
with tempfile.TemporaryDirectory() as tmp:
    js = Path(tmp) / "run.js"
    js.write_text(script, encoding="utf-8")
    try:
        done = subprocess.run([NODE, str(js), str(ROOT / "plasbench" / "data" / "ui.html")] + [str(d) for d in docs], capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        check("the converter finished every input within 120 s (it hung)", False, "timed out")
        print("UI MARKDOWN TESTS FAILED")
        sys.exit(1)
check("node ran the converter to the end", done.returncode == 0 and done.stdout.strip().startswith("{"), (done.returncode, done.stderr[-300:]))
res = json.loads(done.stdout.strip().splitlines()[-1]) if done.stdout.strip() else {}
check("a ##### heading is an h5", "<h5>" in res["h5"]["r"] and "Metagenomic preparation" in res["h5"]["r"], res.get("h5"))
check("a ###### heading is an h6", "<h6>" in res["h6"]["r"], res.get("h6"))
for name in ("h7", "nospace", "bare hash", "mixed", "unclosed fence", "lonely table row", "many stars and brackets"):
    check(f"'{name}' returns (no hang, no error) in well under a second", not str(res[name]["r"]).startswith("ERROR") and res[name]["ms"] < 1000, res[name])
check("the mixed document keeps its five headings, list, quote and table", all(t in res["mixed"]["r"] for t in ("<h5>five</h5>", "<ul>", "<ol>", "<blockquote>", "<table>")), res["mixed"]["r"][:200])
check("3000 random Markdown-looking documents all return (under 20 s)", res["fuzz"]["r"] == 3000 and res["fuzz"]["ms"] < 20000, res["fuzz"])
slow = {k: v["ms"] for k, v in res.items() if k.startswith("doc:") and v["ms"] > 1000}
check(f"all {sum(1 for k in res if k.startswith('doc:'))} guides in the repo convert in under a second each (README.md used to never finish)", not slow, slow)
check("the README converts", any(k.endswith("README.md") for k in res if k.startswith("doc:")))

print("ALL UI MARKDOWN TESTS PASSED" if ok else "UI MARKDOWN TESTS FAILED")
sys.exit(0 if ok else 1)
