#!/usr/bin/env python3
"""docs/IMPLEMENTATION_CATALOGUE.md: complete (every module, tool and output is listed), current (regenerating it changes nothing) and honest (every file it names exists)."""

import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))

import build_implementation_catalogue as bc  # noqa: E402
import report_surfaces as rs  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


with open(os.path.join(ROOT, "docs", "IMPLEMENTATION_CATALOGUE.md"), encoding="utf-8", newline="") as handle:
    page = handle.read()

check("the committed page is exactly what the generator writes now", page == bc.build(), "run python python/build_implementation_catalogue.py")

modules = sorted(os.path.basename(f) for f in glob.glob(os.path.join(ROOT, "python", "*.py")))
check("every module in python/ is listed", all(f"`{m}`" in page for m in modules), [m for m in modules if f"`{m}`" not in page][:5])

with open(os.path.join(ROOT, "config", "tool_capabilities.tsv"), encoding="utf-8") as handle:
    tools = [line.split(chr(9))[0] for line in handle.read().splitlines()[1:] if line.strip()]
check("every registered tool is listed", all(f"`{t}`" in page for t in tools), [t for t in tools if f"`{t}`" not in page][:5])
check("every registered output is listed", all(f"`{s['pattern']}`" in page for s in rs.SURFACES), [s["pattern"] for s in rs.SURFACES if f"`{s['pattern']}`" not in page][:5])

scripts = sorted(os.path.basename(f) for f in glob.glob(os.path.join(ROOT, "scripts", "0*.sh")))
check("every numbered stage script is in the pipeline table", all(f"`scripts/{s}`" in page for s in scripts), scripts)

hand = page.split("## 5. The tools")[0] + page.split("## 10. Tests and how to run them")[1]
paths = set(re.findall(r"`((?:python|test|config|docs|scripts|cohorts|env|plasbench)/[A-Za-z0-9_./*-]+)`", hand))
missing = []
for p in sorted(paths):
    p = p.rstrip(".,:;")
    if p.endswith(("_", "-")) or "*" in p and not glob.glob(os.path.join(ROOT, p)):
        if not glob.glob(os.path.join(ROOT, p + "*")):
            missing.append(p)
        continue
    if not glob.glob(os.path.join(ROOT, p)):
        missing.append(p)
check("every file or folder the hand-written sections name exists", not missing, missing[:8])

bare = set(re.findall(r"`(test_[A-Za-z0-9_]+\.(?:py|sh))`", hand))
gone = sorted(t for t in bare if not os.path.isfile(os.path.join(ROOT, "test", t)))
check("every test file the hand-written sections name exists", not gone, gone[:8])

mod_bare = set(re.findall(r"`([a-z_0-9]+\.py)`", hand))
gone = sorted(m for m in mod_bare if not m.startswith("test_") and not os.path.isfile(os.path.join(ROOT, "python", m)) and not os.path.isfile(os.path.join(ROOT, "plasbench", m)))
check("every module the hand-written sections name exists", not gone, gone[:8])

check("it says what is not implemented", "## 11. What is not implemented" in page and "real-data run" in page)
check("it links the reviewer assessment matrix and the review log", "REVIEWER_ASSESSMENT_MATRIX.md" in page and "EXTERNAL_REVIEW_LOG.md" in page)
readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
check("the README points to the catalogue", "IMPLEMENTATION_CATALOGUE.md" in readme)
faq = open(os.path.join(ROOT, "FAQ.md"), encoding="utf-8").read()
check("the FAQ points to the catalogue", "IMPLEMENTATION_CATALOGUE.md" in faq)

print("ALL IMPLEMENTATION CATALOGUE TESTS PASSED" if ok else "IMPLEMENTATION CATALOGUE TESTS FAILED")
sys.exit(0 if ok else 1)
