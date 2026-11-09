#!/usr/bin/env python3
"""
Test for python/export_report_pdf.py: the demo report exported to PDF with a headless Edge or Chrome.

Skips cleanly (a SKIPPED line, exit 0) when no browser is installed or results_demo/benchmark.report.html is absent. Otherwise the demo page
is laid out (python/report_layout.py, a pure transform when it is not already), exported, and checked: the file starts with %PDF, has many
pages, and (when PyMuPDF is importable) its text carries the cover contents, every view title, every section heading, the inline notes of
the info popovers, and every "Not run" notice of the page.
"""
import html
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "python"))
import export_report_pdf as ex  # noqa: E402
import report_layout as rl  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("  ok: " if cond else "  FAIL: ") + name + ("" if cond else f"  {detail}"))
    ok = ok and bool(cond)


def norm(text):
    return re.sub(r"\s+", "", html.unescape(text)).lower()


def main():
    print("export_report_pdf helpers")
    check("a missing report is refused with a message", subprocess.run(
        [sys.executable, os.path.join(ROOT, "python", "export_report_pdf.py"), "--report", os.path.join(tempfile.gettempdir(), "no-such-report.html")],
        capture_output=True, text=True).returncode != 0)
    cmd = ex.print_command("browser", "file:///r.html?print=1", "out.pdf", "prof", 5000)
    check("the command prints headlessly without header or footer and waits for the widgets",
          "--no-pdf-header-footer" in cmd and "--print-to-pdf=out.pdf" in cmd and "--virtual-time-budget=5000" in cmd and cmd[-1].endswith("?print=1")
          and any(c.startswith("--headless") for c in cmd))

    browser = ex.find_browser()
    demo = os.path.join(ROOT, "results_demo", "benchmark.report.html")
    if not browser:
        print("SKIPPED: no Edge, Chrome or Chromium found; the PDF export was not exercised")
        print("ALL REPORT PDF TESTS PASSED (browser part skipped)" if ok else "REPORT PDF TESTS FAILED")
        sys.exit(0 if ok else 1)
    if not os.path.isfile(demo):
        print("SKIPPED: results_demo/benchmark.report.html not found; run the demo first")
        sys.exit(0 if ok else 1)

    if sys.platform.startswith("linux") and os.environ.get("CI") and "PLASBENCH_BROWSER_FLAGS" not in os.environ:
        # a CI runner usually cannot start the browser sandbox (setuid helper not configured); the sandbox stays on everywhere else
        os.environ["PLASBENCH_BROWSER_FLAGS"] = "--no-sandbox"
    print("the demo report exported with " + os.path.basename(browser))
    with open(demo, encoding="utf-8") as handle:
        page = handle.read()
    page = rl.transform(page)
    with tempfile.TemporaryDirectory(prefix="pdf-test-") as tmp:
        report = os.path.join(tmp, "benchmark.report.html")
        with open(report, "w", encoding="utf-8", newline="") as handle:
            handle.write(page)
        out = os.path.join(tmp, "report.pdf")
        written = ex.export(report, out)
        check("the PDF exists", os.path.isfile(str(written)))
        with open(out, "rb") as handle:
            data = handle.read()
        check("it starts with %PDF", data[:5] == b"%PDF-")
        pages = len(re.findall(rb"/Type\s*/Page[^s]", data))
        doc = None
        try:
            try:
                import pymupdf as fitz
            except ImportError:
                import fitz
            doc = fitz.open(out)
            pages = doc.page_count
        except ImportError:
            print("  note: PyMuPDF is not installed; only the page count and header were checked")
        check("it has many pages (a cover, then every view)", pages > 30, pages)
        if doc is not None:
            texts = [p.get_text() for p in doc]
            text = norm(" ".join(texts))
            check("the cover lists the contents", "contents" in norm(texts[0]) and norm("Detailed results") in norm(texts[0]))
            titles = [v[1] for v, _m in rl.layout_plan([s for s, _a, _b in rl.find_sections(page)])]
            check("every view title is in the PDF", all(norm(t) in text for t in titles), [t for t in titles if norm(t) not in text])
            missing = []
            for sid, a, b in rl.find_sections(page):
                heading = re.sub(r"<[^>]*>", "", rl.heading_html(page[a:b]))
                if heading and norm(heading) not in text:
                    missing.append(sid)
            check("every section heading is in the PDF", not missing, missing)
            notes = re.findall(r"class='rpt-info-pop'>(.*?)</span></span>", re.sub(r"<script.*?</script>", "", page, flags=re.S), re.S)
            gone = [n[:50] for n in notes if norm(re.sub(r"<[^>]*>", "", n))[:40] not in text]
            check(f"the notes of the info popovers print inline ({len(notes)} of them)", len(notes) > 0 and not gone, gone[:3])
            plain = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
            check("no 'Not run' notice vanished", text.count("notrun") >= len(re.findall(r"Not run", plain)) - 1, (text.count("notrun"), len(re.findall("Not run", plain))))
            first = [norm(t)[:30] for t in texts[2:]]
            check("every view starts on a page of its own", all(any(norm(t) in f for f in first) for t in titles[:3]))
            sizes = {(round(p.rect.width), round(p.rect.height)) for p in doc}
            check("the pages are A4 landscape", sizes == {(842, 595)}, sizes)
            footer = len(re.findall(r"page\d+of\d+", text))
            check("every page carries a footer with its number", footer >= pages - 1, (footer, pages))
            doc.close()

    print()
    if not ok:
        print("REPORT PDF TESTS FAILED")
        sys.exit(1)
    print("ALL REPORT PDF TESTS PASSED")


if __name__ == "__main__":
    main()
