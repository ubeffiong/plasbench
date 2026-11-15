#!/usr/bin/env python3
"""
The anti-silo guard: every metric in config/metrics.tsv is wired through the pipeline into the report, and the registry is documented.

Against the offline demo (results_demo) and its report, for every registered metric:
  - a metric whose source is `leaderboard` has its column in benchmark.leaderboard.tsv, one whose source is `scores` has its column in scores.tsv (a column that the
    aggregation stops writing, or a registry typo, fails here);
  - the report section named in `shown_in` is on the page;
  - the glossary on the page explains its term and shows its ladder rung;
  - the metric-framework section carries the evaluation ladder: every rung, every ranking metric, and the gaps.
And the documentation: the Scientific guide and the README name config/metrics.tsv, the guide lists the five rungs.
Skipped (with a reason) when the demo has not been built; test/run_tests.sh builds it first.
"""
import csv
import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import metric_registry as mr  # noqa: E402


def header(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle, delimiter="\t"))


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    rows = mr.load()
    guide = (ROOT / "docs" / "SCIENTIFIC_GUIDE.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    print("the documentation")
    check("the Scientific guide and the README name the registry", "config/metrics.tsv" in guide and "config/metrics.tsv" in readme)
    check("the guide lists the five rungs of the ladder", all(title in guide for _r, title, _q in mr.RUNGS), [t for _r, t, _q in mr.RUNGS if t not in guide])

    demo = ROOT / "results_demo"
    report = demo / "benchmark.report.html"
    if not report.is_file() or not (demo / "benchmark.leaderboard.tsv").is_file():
        print("  SKIP: no results_demo report (run test/run_demo.sh first)")
    else:
        print("the demo")
        leaderboard, scores = header(demo / "benchmark.leaderboard.tsv"), header(demo / "scores.tsv")
        missing = [(r["id"], r["column"]) for r in rows if (r["source"] == "leaderboard" and r["column"] not in leaderboard) or (r["source"] == "scores" and r["column"] not in scores)]
        check("every leaderboard and scores column named in the registry exists in the demo output", not missing, missing)
        page = report.read_text(encoding="utf-8")
        absent = sorted({r["shown_in"] for r in rows if f"id='{r['shown_in']}'" not in page and f'id="{r["shown_in"]}"' not in page})
        check("every section named in shown_in is on the report page", not absent, absent)
        glossary = page[re.search(r"<table class='sortable glossary[^']*'", page).start():]
        glossary = glossary[:glossary.index("</table>")]
        text = html.unescape(re.sub(r"<[^>]+>", "|", glossary))
        lacking = [r["term"] for r in rows if r["term"] and r["term"] not in text]
        check("the glossary on the page explains every registered term", not lacking, lacking)
        check("and shows each metric's ladder rung and use", "Ladder rung" in glossary and "ranks tools" in glossary and "Sequence reconstruction" in glossary and "reported only" in glossary)
        start = page.index("id='metric-framework'")
        framework = html.unescape(re.sub(r"<[^>]+>", " ", page[start:start + 40000]))
        check("the metric-framework section carries the ladder, every rung, and the gaps", "The reconstruction evaluation ladder" in framework
              and all(title in framework for _r, title, _q in mr.RUNGS) and "Computational efficiency" in framework and "Gaps, stated plainly" in framework)
        ranked = [r["term"] or r["id"] for r in rows if r["rankable"] == "yes"]
        check("every ranking metric is on the ladder, marked as ranking tools", all(name in framework for name in ranked) and "ranks tools" in framework, ranked)

    print()
    if not ok:
        print("METRIC WIRING TESTS FAILED")
        sys.exit(1)
    print("ALL METRIC WIRING TESTS PASSED")


if __name__ == "__main__":
    main()
