#!/usr/bin/env python3
"""
report_regenerated.py -- the Run metadata item that says which files of a results folder were rebuilt after the run.

`plasbench regenerate-visuals` writes <results>/regenerated_inputs.json (python/regenerate_visuals.py). When it exists, the report's Run metadata
section says so, so a figure drawn from a rebuilt file is never mistaken for one the original run wrote.

  note_html(results_dir) -> '' when nothing was regenerated, else one Run metadata item (a <div> in the report's metadata grid)

Standard library only.
"""
import html
import json
import os

PROVENANCE_FILE = "regenerated_inputs.json"
SHOWN = 8


def read(results_dir):
    try:
        with open(os.path.join(str(results_dir), PROVENANCE_FILE), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, TypeError):
        return []
    entries = data.get("entries") if isinstance(data, dict) else None
    return [e for e in entries if isinstance(e, dict) and e.get("file")] if isinstance(entries, list) else []


def note_html(results_dir):
    entries = read(results_dir)
    if not entries:
        return ""
    esc = html.escape
    files = sorted({e["file"] for e in entries})
    when = sorted({str(e.get("regenerated_at") or "")[:10] for e in entries} - {""})
    versions = sorted({str(e.get("plasbench_version") or "") for e in entries} - {""})
    kinds = sorted({str(e.get("kind") or "") for e in entries} - {""})
    shown = ", ".join(esc(f) for f in files[:SHOWN]) + (f" and {len(files) - SHOWN} more" if len(files) > SHOWN else "")
    text = (f"These files were regenerated after the run, not written by it: {len(files)} file(s) ({shown}). Rebuilt "
            + (f"on {esc(', '.join(when))} " if when else "") + (f"by PlasBench {esc(', '.join(versions))} " if versions else "")
            + (f"({esc(', '.join(kinds))}) " if kinds else "")
            + f"from the inputs and hashes listed in {PROVENANCE_FILE}. Scores and the benchmark tables are the run's own.")
    return f"<div><small>Regenerated files</small>{text}</div>"
