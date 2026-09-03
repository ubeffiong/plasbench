#!/usr/bin/env python3
"""Guard against report fragments being defined but never emitted.

A consolidation once left five `*_script()` builders in build_html_report.py
that nothing called: 542 of 1,452 lines produced no output. Nothing failed,
because the suite asserts on rendered markers and the surviving dashboard
happened to satisfy the same ones. This checks the wiring itself.
"""

import ast
import os
import sys


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
REPORT = os.path.join(ROOT, "python", "build_html_report.py")

# Fragment builders that main() deliberately does not compose, with the reason.
ALLOWED_UNUSED = {}


def main():
    source = open(REPORT, encoding="utf-8").read()
    tree = ast.parse(source)

    defined = {node.name for node in ast.walk(tree)
               if isinstance(node, ast.FunctionDef) and node.name.endswith("_script")}
    assert defined, "no *_script fragment builders found; has the module been renamed?"

    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called.add(node.func.id)

    orphaned = sorted(defined - called - set(ALLOWED_UNUSED))
    assert not orphaned, (
        "report fragments are defined but never called, so they emit nothing: "
        + ", ".join(orphaned)
        + ". Either compose them in main() or delete them; do not leave them "
          "looking live. Add to ALLOWED_UNUSED with a reason if intentional.")

    # Anything allowed must still exist, or the exemption is stale.
    stale = sorted(set(ALLOWED_UNUSED) - defined)
    assert not stale, f"ALLOWED_UNUSED names functions that no longer exist: {stale}"

    print(f"ALL REPORT COMPOSITION TESTS PASSED ({len(defined)} fragment builders, all composed)")


if __name__ == "__main__":
    sys.exit(main())
