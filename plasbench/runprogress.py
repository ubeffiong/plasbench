"""How far along is a run? Read from the run's own log, so it works for a run started by an earlier window and for one that has already ended.

The pipeline writes a few stable markers (scripts/run_all.sh and the stage scripts):

    Running stages: 0 1 2 3 4 7 5 6                   the stages this run will do, in order
    >>>>> STAGE 4 : 04_run_tools.sh                   a stage starts
    === Run tools on ecoli_b ===                       a step for one isolate inside a stage
    Stage 4 (run tools) complete.                      a stage ends

parse(text) turns them into the stage list, the current stage, the isolates seen, a percentage (every stage counts the same, and a stage counts the isolates it has started out of the
isolates the run has seen so far) and the last line. It is an estimate for a person watching, never a measurement: it says when it does not know, and it never reports 100% for a run
that has not ended.
"""
import re

STAGE_NAMES = {"0": "Set up", "1": "Download", "2": "Truth", "3": "Assemble", "4": "Run tools", "5": "Score", "6": "Aggregate and report", "7": "Long-read tools", "8": "Operational reconstruction"}
_TS = re.compile(r"^\[\d{4}-\d\d-\d\d[ T][\d:]+\]\s*")
_STAGES = re.compile(r"Running stages:\s*([0-9 ]+)")
_START = re.compile(r">>>>>\s*STAGE\s+(\d+)\s*:\s*(\S+)")
_DONE = re.compile(r"Stage\s+(\d+)\s*\(([^)]*)\)\s*complete")
_DONE6 = re.compile(r"Stage\s+(\d+)\s+complete")
_STEP = re.compile(r"^===\s*(.+?)\s*===\s*$")
_ERROR = re.compile(r"\b(ERROR|FAILED|Traceback)\b")
_ISOLATE = re.compile(r"\bon\s+(\S+)$|^(?:Sample|Assemble|Truth for|Score|Building self-assembled hybrid truth for)\s+(\S+)")


def _clean(line):
    return _TS.sub("", line).strip()


def parse(text):
    """{stages, current, done, isolates, current_step, percent, last_line, errors, known} for the log text."""
    stages, current, done = [], None, []
    isolates, per_stage = [], {}
    step = ""
    last = ""
    errors = 0
    for raw in text.splitlines():
        line = _clean(raw)
        if not line or line.startswith("$ ") or line.startswith("with "):
            continue
        last = line
        if _ERROR.search(line):
            errors += 1
        m = _STAGES.search(line)
        if m and not stages:
            stages = m.group(1).split()
            continue
        m = _START.search(line)
        if m:
            current = m.group(1)
            per_stage.setdefault(current, [])
            continue
        m = _DONE.search(line) or _DONE6.search(line)
        if m:
            if m.group(1) not in done:
                done.append(m.group(1))
            if current == m.group(1):
                current = None
            continue
        m = _STEP.match(line)
        if m:
            step = m.group(1)
            who = _ISOLATE.search(step)
            sample = (who.group(1) or who.group(2)) if who else ""
            sample = sample.strip(":") if sample else ""
            if sample and sample not in isolates:
                isolates.append(sample)
            if current and sample and sample not in per_stage.setdefault(current, []):
                per_stage[current].append(sample)
    known = bool(stages)
    percent = None
    if known:
        total = len(stages)
        fraction = len([s for s in stages if s in done])
        if current and current in stages and current not in done:
            seen = len(per_stage.get(current, []))
            fraction += max(0, seen - 1) / len(isolates) if isolates and seen else 0.0
        percent = min(99, int(100 * fraction / total)) if total else None
    return {"stages": [{"id": s, "name": STAGE_NAMES.get(s, f"Stage {s}"), "done": s in done, "current": s == current} for s in stages],
            "current": current, "current_name": STAGE_NAMES.get(current, "") if current else "", "done": done, "isolates": len(isolates),
            "isolates_in_stage": len(per_stage.get(current, [])) if current else 0, "current_step": step, "percent": percent, "last_line": last[:300],
            "errors": errors, "known": known}
