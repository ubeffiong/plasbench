#!/usr/bin/env python3
"""
refresh_sample_report.py -- every generated demo report replaces the sample report in the repository.

The sample (docs/sample_report/benchmark.report.html) is the report built from the offline demo. test/run_demo.sh calls this at its end, so `plasbench demo`, the demo
tests and a hand run all leave the sample equal to the newest demo report; nobody has to remember to copy it.

It does nothing, and says why, when:
  * the project has no docs/sample_report/ folder (an installed copy, a container, a release archive without docs);
  * PLASBENCH_SAMPLE_REPORT=0 (or --skip) asks for no refresh;
  * the demo report is missing, or is not one complete HTML document (a failed build must not replace a good sample);
  * the demo report holds a path of a developer's machine (the sample is committed and public).
It never fails the demo: the exit status is 0 in every case, and a refusal is a printed warning.

  python python/refresh_sample_report.py [--project-root DIR] [--report FILE] [--skip]

Standard library only.
"""
import argparse
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

LOCAL_PATH = re.compile(r"[A-Za-z]:\\\\Users\\\\|[A-Za-z]:\\Users\\|[A-Za-z]:/Users/|/home/[A-Za-z0-9._-]+/|/Users/[A-Za-z0-9._-]+/")


def refresh(project_root, report=None, skip=False):
    """(refreshed?, message). Replaces docs/sample_report/benchmark.report.html with `report` (default results_demo/benchmark.report.html) when it is safe to."""
    root = Path(project_root)
    sample_dir = root / "docs" / "sample_report"
    report = Path(report) if report else root / "results_demo" / "benchmark.report.html"
    if skip or os.environ.get("PLASBENCH_SAMPLE_REPORT", "1") == "0":
        return False, "sample report not refreshed (PLASBENCH_SAMPLE_REPORT=0)"
    if not sample_dir.is_dir():
        return False, "sample report not refreshed: no docs/sample_report/ folder in this project"
    if not report.is_file():
        return False, f"sample report not refreshed: {report} was not written"
    text = report.read_text(encoding="utf-8", errors="replace")
    if not (text.lstrip().lower().startswith("<!doctype html") and text.rstrip().endswith("</html>")):
        return False, "sample report not refreshed: the demo report is not one complete HTML document"
    leak = LOCAL_PATH.search(text)
    if leak:
        return False, f"sample report not refreshed: the demo report holds a local path ({leak.group(0)!r}); the sample is public"
    target = sample_dir / "benchmark.report.html"
    handle, temporary = tempfile.mkstemp(dir=str(sample_dir), suffix=".tmp")     # copy beside the target, then rename: a reader never sees half a file
    os.close(handle)
    try:
        shutil.copyfile(report, temporary)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    return True, f"sample report refreshed: {target} ({target.stat().st_size / 1e6:.1f} MB)"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--project-root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--report", default=None)
    ap.add_argument("--skip", action="store_true")
    args = ap.parse_args()
    done, message = refresh(args.project_root, args.report, args.skip)
    print(message if done else f"note: {message}", file=sys.stdout if done else sys.stderr)


if __name__ == "__main__":
    main()
