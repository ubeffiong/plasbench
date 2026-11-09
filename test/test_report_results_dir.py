#!/usr/bin/env python3
"""build_html_report.py reads the results from the folder that holds --scores, not from the parent of --out.

Writing the report into another folder used to turn about ten sections (maps, scenario scorecard, selected cards,
bin-match links, the file explorer) into 'Not run'. The section set and the number of 'Not run' notices must not
depend on where the report is written.
"""
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "python"))

import test_report_feature_manifest as fm  # noqa: E402


def sections(page):
    return re.findall(r"<section id=['\"]([^'\"]+)['\"]", page)


def main():
    import build_html_report as bhr
    with tempfile.TemporaryDirectory() as work:
        beside = Path(work) / "results"
        fm.shutil.copytree(fm.ROOT / "results_demo", beside)
        page_beside = fm.build_into(beside, beside / "benchmark.report.html")
        elsewhere = Path(work) / "elsewhere"
        elsewhere.mkdir()
        page_else = fm.build_into(beside, elsewhere / "r.report.html")
        assert sections(page_beside) == sections(page_else), "section set depends on where the report is written"
        assert page_beside.count("Not run") == page_else.count("Not run"), (
            page_beside.count("Not run"), page_else.count("Not run"))
        assert len(page_else) > 0.9 * len(page_beside), "the report written elsewhere is much smaller"

        # the fallback and the warning
        empty = Path(work) / "empty"
        empty.mkdir()
        got = bhr.resolve_results_dir(str(empty / "scores.tsv"), empty / "x.html")
        assert got == empty.resolve(), got
        missing = Path(work) / "nowhere" / "scores.tsv"
        out = Path(work) / "o" / "x.html"
        assert bhr.resolve_results_dir(str(missing), out.resolve()) == out.resolve().parent
    print("PASS: results are read from the folder of --scores; %d sections, %d 'Not run' either way"
          % (len(sections(page_beside)), page_beside.count("Not run")))


if __name__ == "__main__":
    main()
