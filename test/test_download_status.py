#!/usr/bin/env python3
"""Download progress in `plasbench status` and the window (results/download_progress.json), and the stage label that no longer disagrees with the log.

The downloader writes bytes actually received, per run, into results/download_progress.json; python/run_status.py shows the fresh active entries ("download: SRR...: 3.2 of 9.5 GB (34%), ..."),
ignores stale or finished ones, and tolerates a damaged file; python/download_progress.py prints that line for the run log and falls back to the old file-size line without it; the end-of-stage
summary adds up bytes, retries and resumes. The window's runs list says "Stage 2: Truth (step 3 of 8)": the stage NUMBER the log and `plasbench status` print, then the position in the list.
"""
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "python"))
import download_progress as dp  # noqa: E402
import run_status as rs  # noqa: E402
from plasbench import runprogress  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(f"  {'PASS' if good else 'FAIL'}: {label}{'' if good else ' -> ' + str(detail)}")
    ok &= bool(good)


def main():
    now = time.time()
    line = "SRR36114699: 3.2 of 9.5 GB (34%), 3.4 MB/s now, 3.1 MB/s average, about 31 min left"
    with tempfile.TemporaryDirectory() as tmp:
        results = Path(tmp)
        (results / "download_progress.json").write_text(json.dumps({"updated": now, "isolates": {
            "SRR36114699": {"state": "downloading", "updated": now - 5, "line": line, "done_bytes": 3_200_000_000, "total_bytes": 9_500_000_000, "sample": "streptomyces_a", "received_bytes": 3_200_000_000,
                            "retries": 2, "resumed_bytes": 0},
            "SRROLD": {"state": "downloading", "updated": now - 3600, "line": "SRROLD: stale", "done_bytes": 1, "total_bytes": 2},
            "SRRDONE": {"state": "done", "updated": now - 1, "line": "SRRDONE: done", "done_bytes": 2, "total_bytes": 2, "received_bytes": 6_000_000_000, "retries": 1, "resumed_bytes": 1_000_000_000}}}))
        active = rs.active_downloads(str(results), now)
        check("only the fresh, still-active download is listed (not a stale one, not a finished one)", [d["run"] for d in active] == ["SRR36114699"], active)
        summary = rs.summarize(str(results), now=now, procs=[], mach={})
        text = rs.render(summary)
        check("`plasbench status` shows the honest line", "download: " + line in text and summary["downloads"][0]["sample"] == "streptomyces_a", text[-400:])
        check("the summary is JSON-able and existing keys are intact (stage, progress, state, hints)", all(k in summary for k in ("state", "stage", "progress", "hints", "downloads")) and json.dumps(summary, default=str))
        (results / "download_progress.json").write_text("{ broken")
        check("a damaged progress file is ignored, never an error", rs.active_downloads(str(results), now) == [])
        check("no file at all is fine", rs.active_downloads(str(results / "nowhere"), now) == [])
        (results / "download_progress.json").write_text(json.dumps({"isolates": {"SRRA": {"state": "downloading", "updated": now, "line": line}}}))
        check("download_progress.py prints the downloader's line for the run log", dp.describe(str(results), "SRRA", None, str(results / "download_progress.json")) == line)
        check("without the file it falls back to the old file-size line (nothing written yet)", dp.describe(str(results), "SRRB", None, str(results / "nope.json")).endswith("starting (nothing written yet)"))
        (results / "download_progress.json").write_text(json.dumps({"isolates": {"SRRA": {"state": "downloading", "updated": now - 1000, "line": line}}}))
        check("a stale line is not repeated", dp.read_progress_file(str(results / "download_progress.json"), "SRRA", now) is None)
        (results / "p.json").write_text(json.dumps({"isolates": {"A": {"received_bytes": 6_000_000_000, "retries": 2, "resumed_bytes": 1_000_000_000}, "B": {"received_bytes": 500_000_000, "retries": 0, "resumed_bytes": 0}}}))
        (results / "via").mkdir()
        (results / "via" / "a.via").write_text("ena\n")
        (results / "via" / "b.via").write_text("ena\n")
        (results / "via" / "c.via").write_text("sra\n")
        out = dp.stage_summary(str(results / "p.json"), str(results / "via"), 3600)
        check("the end-of-stage summary: bytes, time, MB/s, ENA and SRA counts, retries, resumes", out == "Download summary: 6.5 GB of reads fetched from ENA in 60 min (1.8 MB/s on average); "
              "isolates via ENA 2, via the SRA Toolkit 1; 2 chunk retries, 1000 MB resumed from earlier attempts.", out)

    log = "\n".join(["[2026-11-22 10:00:00] Running stages: 0 1 2 3 4 7 5 6", "[2026-11-22 10:00:01] >>>>> STAGE 2 : 02_truth.sh", "[2026-11-22 10:00:02] === Truth for a ==="])
    parsed = runprogress.parse(log)
    idx = next(i for i, x in enumerate(parsed["stages"]) if x["current"])
    html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    check("the log's stage number is 2 and its position in this run's list is 3 (the old label said 'Stage 3 of 8' next to the log's 'stage 2')", parsed["current"] == "2" and idx == 2 and len(parsed["stages"]) == 8)
    check("the window now says 'Stage <number>: <name> (step <position> of <n>)', so it agrees with the log and `plasbench status`",
          "Stage ${pr.stages[idx].id}: ${pr.current_name} (step ${idx + 1} of ${n})" in html and "Stage ${idx + 1} of ${n}" not in html)
    print("ALL DOWNLOAD STATUS TESTS PASSED" if ok else "SOME DOWNLOAD STATUS TESTS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
