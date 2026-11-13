#!/usr/bin/env python3
"""
The sample report in the repository is present, honest and linked from the README.

  - docs/sample_report/benchmark.report.html exists, is one HTML document, and carries the report's landmarks (the Overview, the recommendation, the plasmid maps, the
    "?" help dialog data and the shared 3D engine) so a stale or truncated copy is caught;
  - it holds no path of a developer's machine;
  - docs/sample_report/README.md says the data are synthetic and says how to regenerate it;
  - the project README links to the file (a relative link that opens it) and says the numbers are not real results.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "docs" / "sample_report" / "benchmark.report.html"


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    check("the sample report exists", SAMPLE.is_file())
    text = SAMPLE.read_text(encoding="utf-8") if SAMPLE.is_file() else ""
    check("it is one complete HTML document", text.lstrip().lower().startswith("<!doctype html") and text.rstrip().endswith("</html>"))
    check("it has the views, the help data and the 3D engine",
          "id='view-overview'" in text and "id='view-recommendation'" in text and "id='view-maps'" in text
          and "id='rpt-help-data'" in text and "root.PB3D = api" in text)
    check("it holds no path of a developer's machine", not re.search(r"[A-Za-z]:\\\\Users\\\\|/home/[a-z]+/|C:/Users/", text))
    note = (ROOT / "docs" / "sample_report" / "README.md").read_text(encoding="utf-8")
    check("its README says the data are synthetic and how to regenerate it", "synthetic" in note.lower() and "test/run_demo.sh" in note)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    check("the project README links to the sample report", "](docs/sample_report/benchmark.report.html)" in readme)
    check("and says its numbers are not real results", "not real results" in readme)
    top = "\n".join(readme.splitlines()[:12])
    check("the sample report link is at the top of the README (before the first screen ends), not only in the report section",
          "htmlpreview.github.io/?https://github.com/ubeffiong/plasbench/blob/main/docs/sample_report/benchmark.report.html" in top and "Open the sample HTML report" in top)

    print()
    if not ok:
        print("SAMPLE REPORT TESTS FAILED")
        sys.exit(1)
    print("ALL SAMPLE REPORT TESTS PASSED")


if __name__ == "__main__":
    main()
