#!/usr/bin/env python3
"""The window must not execute script that comes from a folder, cohort, study or tool name.

esc() HTML-escapes, but an inline handler's attribute value is decoded by the browser BEFORE the script is parsed, so
onclick="f('${esc(name)}')" turns &#39; back into ' and a name like  a');x();('  breaks out of the string. The safe form is
onclick="f(${jsq(name)})": JSON.stringify makes a valid string literal, esc() protects the attribute. data-* attributes that hold JSON
are always double-quoted and escaped (dattr).

Two checks, neither needs a browser:
  1. static: every ${...} inside an on*="..." attribute is jsq(...) (or an allow-listed constant), and no data-*='${...}' remains;
  2. semantic (node, skipped when node is missing): decode what jsq/dattr produce the way a browser does and confirm a hostile name
     arrives as exactly one string / valid JSON.
"""
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = Path(os.environ.get("PLASBENCH_UI_HTML") or ROOT / "plasbench" / "data" / "ui.html")  # the override lets the test be pointed at an older page
SOURCE = UI.read_text(encoding="utf-8")
failures = []


def check(label, ok, detail=""):
    print(("  PASS: " if ok else "  FAIL: ") + label + ("" if ok else f"\n        {detail}"))
    if not ok:
        failures.append(label)


def interpolations_in_handlers(text):
    """Yield (line number, expression) for each ${...} inside an on*="..." attribute value."""
    for match in re.finditer(r'\bon[a-z]+="', text):
        i, expr_list = match.end(), []
        while i < len(text):
            if text.startswith("${", i):
                depth, j = 1, i + 2
                while j < len(text) and depth:
                    depth += {"{": 1, "}": -1}.get(text[j], 0)
                    j += 1
                expr_list.append(text[i + 2:j - 1])
                i = j
                continue
            if text[i] == '"' or text[i] == "\n":
                break
            i += 1
        line = text.count("\n", 0, match.start()) + 1
        for expr in expr_list:
            yield line, expr.strip()


# Constants only (no user data): the Setup page's "Enter" button picks one of two fixed ids.
ALLOWED = ('c.fix.endsWith("KEY") ? "ncbi_key" : "ncbi_email"',)
unsafe = [(n, e) for n, e in interpolations_in_handlers(SOURCE) if not e.startswith("jsq(") and e not in ALLOWED]
check("every ${...} inside an inline on*= handler is jsq(...)", not unsafe, "\n        ".join(f"line {n}: ${{{e}}}" for n, e in unsafe[:8]))

single_quoted = [m.start() for m in re.finditer(r"data-[a-z-]+='\$\{", SOURCE)]
check("no data-*='${...}' (single-quoted attribute with interpolation) remains", not single_quoted,
      ", ".join(str(SOURCE.count("\n", 0, p) + 1) for p in single_quoted))
check("the old esc()-inside-quotes handler pattern is gone", "('${esc(" not in SOURCE, "found ('${esc(")
check("jsq and dattr are defined next to esc", "const jsq =" in SOURCE and "const dattr =" in SOURCE)

# Semantic check with node: copy the helper definitions out of the page and run hostile names through them.
if not shutil.which("node"):
    print("  SKIP: node is not installed; semantic check not run")
else:
    helpers = "\n".join(re.search(rf"^const {name} = .*$", SOURCE, re.M).group(0) for name in ("esc", "jsq", "dattr"))
    hostile = ["O'Neil", "a');window.__pwn=1;('", 'q"uote', "back\\slash\\", "line\nbreak", "</script><img src=x onerror=1>", "C:\\Users\\a b\\x'y"]
    script = helpers + f"""
const hostile = {json.dumps(hostile)};
const out = hostile.map(h => ({{ jsq: jsq(h), dattr: dattr(["run", "--samples", h]) }}));
process.stdout.write(JSON.stringify(out));
"""
    with tempfile.TemporaryDirectory() as tmp:
        js = Path(tmp) / "t.js"
        js.write_text(script, encoding="utf-8")
        result = subprocess.run(["node", str(js)], capture_output=True, text=True)
    check("node ran the helpers", result.returncode == 0, result.stderr[:300])
    if result.returncode == 0:
        produced = json.loads(result.stdout)
        for name, row in zip(hostile, produced):
            decoded = html.unescape(row["jsq"])  # what the JS parser sees after the browser decodes the attribute
            try:
                literal = json.loads(decoded)
            except ValueError as error:
                literal, decoded_ok = None, str(error)
            else:
                decoded_ok = ""
            check(f"handler argument round-trips as ONE string: {name!r}", literal == name and decoded.startswith('"') and decoded.endswith('"'), decoded_ok or repr(decoded))
            check(f"data-run JSON round-trips: {name!r}", json.loads(html.unescape(row["dattr"])) == ["run", "--samples", name])
            check(f"attribute text has no raw quote that could end it: {name!r}", '"' not in row["jsq"] and "'" not in row["jsq"] and '"' not in row["dattr"])

print("ALL WEB UI INLINE-HANDLER TESTS PASSED" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
