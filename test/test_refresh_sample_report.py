#!/usr/bin/env python3
"""
Every generated demo report replaces the sample report (python/refresh_sample_report.py, called at the end of test/run_demo.sh).

Hand-built project folders:
  - a complete demo report replaces the old sample, byte for byte, and no temporary file is left behind;
  - no docs/sample_report/ folder: nothing is written (an installed copy), with a reason;
  - PLASBENCH_SAMPLE_REPORT=0 and --skip: nothing is written;
  - a missing demo report, a truncated one (a failed build) and one with a developer's local path never replace a good sample;
  - the script exits 0 in every case (a refusal must not fail the demo);
  - test/run_demo.sh calls the script after it writes the report, and the sample README says the refresh is automatic.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import refresh_sample_report as rs  # noqa: E402

GOOD = "<!doctype html><html><body><p>new demo report</p></body></html>"
OLD = "<!doctype html><html><body><p>old sample</p></body></html>"


def project(tmp, sample=True, report=GOOD):
    root = Path(tmp)
    if sample:
        (root / "docs" / "sample_report").mkdir(parents=True)
        (root / "docs" / "sample_report" / "benchmark.report.html").write_text(OLD, encoding="utf-8")
    if report is not None:
        (root / "results_demo").mkdir()
        (root / "results_demo" / "benchmark.report.html").write_text(report, encoding="utf-8")
    return root


def sample_text(root):
    return (root / "docs" / "sample_report" / "benchmark.report.html").read_text(encoding="utf-8")


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    os.environ.pop("PLASBENCH_SAMPLE_REPORT", None)
    print("a generated demo report replaces the sample")
    with tempfile.TemporaryDirectory() as tmp:
        root = project(tmp)
        done, message = rs.refresh(root)
        check("the sample now equals the new demo report", done and sample_text(root) == GOOD, message)
        check("no temporary file is left in the sample folder", [p.name for p in (root / "docs" / "sample_report").iterdir()] == ["benchmark.report.html"])
        (root / "results_demo" / "benchmark.report.html").write_text(GOOD.replace("new", "newer"), encoding="utf-8")
        check("a second demo run replaces it again", rs.refresh(root)[0] and "newer demo report" in sample_text(root))
    print("when it does nothing")
    with tempfile.TemporaryDirectory() as tmp:
        root = project(tmp, sample=False)
        done, message = rs.refresh(root)
        check("no docs/sample_report folder: nothing is written and the folder is not created", not done and not (root / "docs").exists() and "no docs/sample_report" in message, message)
    with tempfile.TemporaryDirectory() as tmp:
        root = project(tmp)
        os.environ["PLASBENCH_SAMPLE_REPORT"] = "0"
        try:
            check("PLASBENCH_SAMPLE_REPORT=0 leaves the sample alone", not rs.refresh(root)[0] and sample_text(root) == OLD)
        finally:
            os.environ.pop("PLASBENCH_SAMPLE_REPORT")
        check("--skip leaves the sample alone", not rs.refresh(root, skip=True)[0] and sample_text(root) == OLD)
    print("a bad demo report never replaces a good sample")
    for label, report in (("a missing report", None), ("a truncated report", "<!doctype html><html><body><p>half"),
                          ("a report with a developer's local path", GOOD.replace("new demo", "C:\\Users\\someone\\x new demo")),
                          ("a report with a unix home path", GOOD.replace("new demo", "/home/someone/x new demo"))):
        with tempfile.TemporaryDirectory() as tmp:
            root = project(tmp, report=report)
            done, message = rs.refresh(root)
            check(f"{label}: the sample is unchanged and a reason is given", not done and sample_text(root) == OLD and message, message)
    print("the command line and the demo script")
    with tempfile.TemporaryDirectory() as tmp:
        root = project(tmp, report="<!doctype html><html><body><p>half")
        run = subprocess.run([sys.executable, str(ROOT / "python" / "refresh_sample_report.py"), "--project-root", str(root)], capture_output=True, text=True)
        check("a refusal exits 0 (the demo does not fail) and prints a note", run.returncode == 0 and "note:" in run.stderr, run.stderr)
        root2 = project(tempfile.mkdtemp(dir=tmp))
        run = subprocess.run([sys.executable, str(ROOT / "python" / "refresh_sample_report.py"), "--project-root", str(root2)], capture_output=True, text=True)
        check("a refresh exits 0 and says so", run.returncode == 0 and "sample report refreshed" in run.stdout and sample_text(root2) == GOOD, run.stdout + run.stderr)
    script = (ROOT / "test" / "run_demo.sh").read_text(encoding="utf-8")
    check("run_demo.sh calls the refresh after it writes the report",
          "refresh_sample_report.py" in script and script.index("--out \"$DEMO/benchmark.report.html\"") < script.index("refresh_sample_report.py"))
    check("the sample README says the refresh is automatic",
          "replaced automatically" in (ROOT / "docs" / "sample_report" / "README.md").read_text(encoding="utf-8"))

    print()
    if not ok:
        print("REFRESH SAMPLE REPORT TESTS FAILED")
        sys.exit(1)
    print("ALL REFRESH SAMPLE REPORT TESTS PASSED")


if __name__ == "__main__":
    main()
