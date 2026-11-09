#!/usr/bin/env python3
"""
The workflow figure lives in the README, not in the HTML report.

  - render_svg() is well-formed XML, scales through its viewBox, has a title and a description, and every box of the figure
    (2 input boxes + 6 truth steps, 1 assembly box + 5 tool groups, 6 scoring layers, 3 statistics boxes, 1 output box
    = 24 boxes) carries its name, so the figure reads without colour;
  - every stage family in the legend is used by at least one box, and no coordinate is NaN or infinite;
  - docs/images/workflow.svg is exactly what the generator draws (a stale committed file fails here), and --check says so;
  - the README embeds that image with alt text;
  - the HTML report builder no longer has a Workflow section: no `report_workflow` import in build_html_report.py, and the
    report modules do not mention a `workflow` section id.
"""
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "python"))

import report_workflow as wf  # noqa: E402

FIGURE = os.path.join(ROOT, "docs", "images", "workflow.svg")


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    svg = wf.render_svg()
    print("the figure")
    try:
        root = ET.fromstring(svg)
        parsed = True
    except ET.ParseError:
        root, parsed = None, False
    check("well-formed XML", parsed)
    if not parsed:
        sys.exit(1)
    ns = "{http://www.w3.org/2000/svg}"
    check("scales through a viewBox, with no fixed width", root.get("viewBox") == "0 0 1000 700" and root.get("width") is None)
    check("has a title and a description for screen readers", root.find(ns + "title") is not None and root.find(ns + "desc") is not None)
    boxes = [e for e in root.iter(ns + "rect") if e.get("class") == "wf-box"]
    check("24 boxes", len(boxes) == 24, len(boxes))
    text = " ".join("".join(t.itertext()) for t in root.iter(ns + "text"))
    names = ([n for n, _ in wf.TRUTH_STEPS] + [n for n, _ in wf.TOOL_GROUPS] + [n for n, _ in wf.SCORING_LAYERS]
             + ["Isolate short reads", "Complete reference genome", "Short-read assembly", "Rank robustness", "Recommendation and report"])
    missing = [n for n in names if n.split()[0] not in text]
    check("every box name appears as text", not missing, missing)
    used = {e.get("stroke") for e in boxes}
    check("every stage family is used by a box", all(f[1] in used for f in wf.FAMILIES.values()))
    check("no NaN or infinity in any coordinate", not re.search(r"[=, ](-?nan|-?inf)[' ,]", svg))
    check("deterministic", wf.render_svg() == svg)

    print("the committed file and the README")
    exists = os.path.isfile(FIGURE)
    check("docs/images/workflow.svg exists", exists)
    if exists:
        with open(FIGURE, encoding="utf-8", newline="") as handle:
            check("it is exactly what the generator draws", handle.read() == svg + "\n")
        done = subprocess.run([sys.executable, os.path.join(ROOT, "python", "report_workflow.py"), "--check", FIGURE],
                              capture_output=True, text=True)
        check("--check passes on the committed file", done.returncode == 0, done.stderr)
    stale = os.path.join(os.environ.get("TMPDIR", os.environ.get("TEMP", ".")), "plasbench_stale_workflow.svg")
    with open(stale, "w", encoding="utf-8") as handle:
        handle.write("<svg/>")
    done = subprocess.run([sys.executable, os.path.join(ROOT, "python", "report_workflow.py"), "--check", stale], capture_output=True, text=True)
    os.remove(stale)
    check("--check fails on a stale file and says how to regenerate it", done.returncode == 1 and "--out" in done.stderr)
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as handle:
        readme = handle.read()
    check("the README embeds the figure with alt text", "docs/images/workflow.svg" in readme and 'alt="PlasBench workflow' in readme)

    print("the report no longer has a Workflow section")
    with open(os.path.join(ROOT, "python", "build_html_report.py"), encoding="utf-8") as handle:
        builder = handle.read()
    check("build_html_report.py does not use report_workflow", "report_workflow" not in builder.replace("python/report_workflow.py", ""))
    wiring = open(os.path.join(ROOT, "python", "report_wiring.py"), encoding="utf-8").read()
    check("the navigation groups do not list a workflow section", '"workflow"' not in wiring and " workflow " not in wiring)

    print()
    if not ok:
        print("REPORT WORKFLOW TESTS FAILED")
        sys.exit(1)
    print("ALL REPORT WORKFLOW TESTS PASSED")


if __name__ == "__main__":
    main()
