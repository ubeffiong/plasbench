#!/usr/bin/env python3
"""
export_report_pdf.py -- save the HTML report as one PDF with a headless Edge or Chrome.

    python python/export_report_pdf.py --report results/benchmark.report.html --out results/benchmark.report.pdf
    plasbench report-pdf --report results/benchmark.report.html [--out report.pdf]

The report carries its own print stylesheet (python/report_layout.py, assets/report/layout_print.html): a cover with the contents, then every
view in order, each starting on a new page, every fold open, the notes from the info popovers inline, A4 landscape with page numbers. The browser
prints that stylesheet; this script only finds the browser, opens the report with ?print=1 (which opens the folds and lets the interactive figures
settle before printing), and waits for the widgets with --virtual-time-budget.

Browser lookup: $PLASBENCH_BROWSER, then msedge / chrome / chromium on PATH, then the usual Windows, macOS and Linux install locations.
Exit status: 0 on success, 2 when no browser is found, 1 when the browser ran but wrote no PDF.

Standard library only.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PATH_NAMES = ["msedge", "microsoft-edge", "microsoft-edge-stable", "google-chrome", "google-chrome-stable", "chrome", "chromium", "chromium-browser"]


def candidate_paths():
    """Install locations to try after PATH, most likely first."""
    out = []
    for var in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if base:
            out += [Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                    Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe",
                    Path(base) / "Chromium" / "Application" / "chrome.exe"]
    out += [Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
            Path("/usr/bin/microsoft-edge"), Path("/usr/bin/google-chrome"), Path("/usr/bin/chromium"),
            Path("/usr/bin/chromium-browser"), Path("/snap/bin/chromium"),
            Path("/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
            Path("/mnt/c/Program Files/Google/Chrome/Application/chrome.exe")]
    return out


def find_browser():
    """Path of an Edge / Chrome / Chromium executable, or None."""
    explicit = os.environ.get("PLASBENCH_BROWSER")
    if explicit and Path(explicit).is_file():
        return explicit
    for name in PATH_NAMES:
        found = shutil.which(name)
        if found:
            return found
    for path in candidate_paths():
        if path.is_file():
            return str(path)
    return None


def print_command(browser, url, out_pdf, profile, budget_ms):
    return [browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
            f"--user-data-dir={profile}", "--allow-file-access-from-files", "--window-size=1280,1024",
            "--no-pdf-header-footer", f"--print-to-pdf={out_pdf}",
            f"--virtual-time-budget={budget_ms}", "--run-all-compositor-stages-before-draw", url]


def export(report, out=None, budget_ms=20000, timeout=600):
    """Write the PDF; returns the path. Raises SystemExit with a clear message on failure."""
    report = Path(report).resolve()
    if not report.is_file():
        raise SystemExit(f"ERROR: report not found: {report}")
    out = Path(out).resolve() if out else report.with_suffix(".pdf")
    browser = find_browser()
    if not browser:
        print("ERROR: no Microsoft Edge, Google Chrome or Chromium found. Install one, or set PLASBENCH_BROWSER to its executable. "
              "You can also open the report and use the 'Print / Save PDF' button.", file=sys.stderr)
        raise SystemExit(2)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    url = report.as_uri() + "?print=1"
    with tempfile.TemporaryDirectory(prefix="plasbench-pdf-") as profile:
        cmd = print_command(browser, url, str(out), profile, budget_ms)
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise SystemExit(f"ERROR: {browser} did not finish within {timeout} s")
    if not out.is_file() or out.stat().st_size < 1000:
        tail = (result.stderr or b"").decode("utf-8", "replace").strip().splitlines()[-5:]
        raise SystemExit(f"ERROR: {browser} wrote no PDF (exit {result.returncode}). " + " | ".join(tail))
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description="Save a PlasBench HTML report as a PDF with headless Edge or Chrome.")
    parser.add_argument("--report", required=True, type=Path, help="Path to benchmark.report.html.")
    parser.add_argument("--out", type=Path, help="PDF to write (default: next to the report, .pdf).")
    parser.add_argument("--budget-ms", type=int, default=20000, help="Virtual time the page gets to settle its widgets (default 20000).")
    args = parser.parse_args(argv)
    out = export(args.report, args.out, args.budget_ms)
    print(f"Wrote PDF: {out} ({out.stat().st_size // 1024} KiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
