"""Runs started OUTSIDE the window (the Terminal tab, or a plain `plasbench run` in a shell), shown read-only on the Runs page.

A run started from the window is a job (plasbench/webui.py class Jobs). A run started anywhere else is not, so it can never be in the Jobs list; its only trace is the study folder:
each study's study.json lists the runs started in it (command, start time and, from this version, `via`), and its results folder shows how far it got. This module turns the
LATEST run of every study that was not started from the window into a read-only entry:

    running      .run.lock + .run.lock.heartbeat are fresh (the pipeline's own lock), or the lock's process is alive (POSIX)
    completed    benchmark.report.html or tool_status.tsv is in the results folder
    stopped      none of those: "interrupted or cancelled: it stopped without recording how it ended"

The window cannot cancel such a run (it does not own the process): it only offers Show in terminal and Open folder. Standard library only.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

HEARTBEAT_FRESH_SECONDS = 90
STOPPED_TEXT = "interrupted or cancelled: it stopped without recording how it ended"


def _parse_time(text) -> float | None:
    from datetime import datetime
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(text), fmt).timestamp()
        except ValueError:
            continue
    return None


def run_state(results: Path, now: float | None = None) -> str:
    """running | completed | stopped, from the results folder."""
    now = time.time() if now is None else now
    try:
        from . import jobrunner
        if jobrunner.lock_holder(str(results)):
            return "running"
    except Exception:  # noqa: BLE001
        pass
    lock, beat = results / ".run.lock", results / ".run.lock.heartbeat"
    try:
        if lock.exists() and now - os.path.getmtime(beat) < HEARTBEAT_FRESH_SECONDS:
            return "running"
    except OSError:
        pass
    if (results / "benchmark.report.html").is_file() or (results / "tool_status.tsv").is_file():
        return "completed"
    return "stopped"


def _matches_window_job(command: str, started: float | None, jobs) -> bool:
    """An older record (no `via`) belongs to the window when a job of the window has the same arguments and started within five minutes of it."""
    for j in jobs:
        argv = j.get("argv") or []
        if started is not None and abs((j.get("started") or 0) - started) < 300 and command.strip() == ("plasbench " + " ".join(argv)).strip():
            return True
    return False


def outside_runs(studies_list, jobs=(), now: float | None = None) -> list:
    """One read-only entry per study whose latest run was started outside the window. `studies_list` is studies.list_studies(root); `jobs` the window's jobs."""
    out = []
    for st in studies_list:
        if st.get("available") is False:
            continue
        folder = Path(st["path"])
        try:
            record = json.loads((folder / "study.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        runs = record.get("runs") or []
        if not runs:
            continue
        last = runs[-1]
        command = str(last.get("command") or "")
        started = _parse_time(last.get("started"))
        if last.get("via") == "window" or (last.get("via") is None and _matches_window_job(command, started, jobs)):
            continue
        results = folder / "results"
        state = run_state(results, now)
        out.append({"id": f"outside:{st['name']}", "study": st["name"], "label": st["name"], "command": command, "started": started, "results": str(results), "study_path": str(folder),
                    "state": state, "group": {"running": "ongoing", "completed": "completed", "stopped": "attention"}[state], "outside": True,
                    "note": "started outside the window" + ("" if state != "stopped" else f": {STOPPED_TEXT}"),
                    "report": (results / "benchmark.report.html").is_file(), "earlier_runs": max(0, len(runs) - 1)})
    out.sort(key=lambda e: -(e["started"] or 0))
    return out
