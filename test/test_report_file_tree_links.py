#!/usr/bin/env python3
"""The report's file explorer never writes the machine's folder names into the page (audit AU-018).

A file in a folder far from the report used to be linked as `../../../home/runner/work/.../logs/x.log`, which puts the builder's home path into a page that is shared.
It surfaced on CI when a run's console log (`logs/run.latest.log`) made the logs folder non-empty. A link one level up (`../logs/x`, the study layout) is fine.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import build_html_report as bhr  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    report = tmp / "a" / "b" / "c" / "study" / "results" / "benchmark.report.html"
    report.parent.mkdir(parents=True)
    report.write_text("<html></html>")
    near = tmp / "a" / "b" / "c" / "study" / "logs"
    near.mkdir()
    (near / "run.latest.log").write_text("near\n")
    far = tmp / "home" / "someone" / "work" / "project" / "logs"
    far.mkdir(parents=True)
    (far / "aggregate.log").write_text("far\n")
    (far / "run.latest.log").write_text("far\n")

    html_near, n_near, _ = bhr.file_tree(near, report)
    check("a log one level up (the study layout) is still linked", "href='../logs/run.latest.log'" in html_near, html_near)
    html_far, n_far, _ = bhr.file_tree(far, report)
    check("files far from the report are listed by name", "aggregate.log" in html_far and "run.latest.log" in html_far and n_far == 2, html_far)
    check("but not linked: no '../../' chain and no folder name of the machine in the page", "href=" not in html_far and "../../" not in html_far and "someone" not in html_far
          and "/home/" not in html_far and "work/project" not in html_far, html_far)
    check("and it says why", "not linked: it is outside this report's folder" in html_far, html_far)

print("ALL REPORT FILE TREE LINK TESTS PASSED" if ok else "REPORT FILE TREE LINK TESTS FAILED")
sys.exit(0 if ok else 1)
