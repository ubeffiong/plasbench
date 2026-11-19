#!/usr/bin/env python3
"""The one table of what each numeric Scoring-decision setting accepts (config/setting_ranges.tsv), and the checks built on it.

The window shows it as a range label and tooltip beside each setting, as min/max/step on the input, and the server uses `check()` to refuse an out-of-range value when
a setting is saved. The bounds are read from the code that really refuses values (python/prereg_admin.py validate_value, and the scorers' own argument checks in
score_bins.py and score_plasmids.py); where the code accepts anything, min or max is empty and the label says "no limit enforced". test/test_setting_ranges.py runs those
validators against this table, so the table cannot drift from the code. Standard library only.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TABLE = "config/setting_ranges.tsv"
KINDS = {"integer": "whole number", "decimal": "decimal number", "flag": "whole number (0 or 1)"}


def load(root=ROOT) -> dict:
    """key -> entry (numbers parsed; min/max None when no limit is enforced). A missing or unreadable table is an empty dict, never an error."""
    entries = {}
    try:
        lines = [ln for ln in (Path(root) / TABLE).read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
    except OSError:
        return entries
    head = lines[0].split("\t") if lines else []
    for line in lines[1:]:
        row = dict(zip(head, line.split("\t")))
        key = row.get("key", "").strip()
        if not key:
            continue

        def num(name):
            text = (row.get(name) or "").strip()
            if not text:
                return None
            return float(text) if "." in text else int(text)
        entries[key] = {"key": key, "kind": row.get("kind", ""), "unit": row.get("unit", ""), "min": num("min"), "min_exclusive": row.get("min_exclusive", "") == "yes",
                        "max": num("max"), "max_exclusive": row.get("max_exclusive", "") == "yes", "step": num("step") or 1, "enforced_by": row.get("enforced_by", ""),
                        "note": row.get("note", "")}
    return entries


def _fmt(n) -> str:
    return "" if n is None else (str(int(n)) if float(n) == int(n) and "." not in str(n) else str(n))


def label(entry: dict, default=None) -> str:
    """The range in plain words, for the label and the tooltip: type, unit, minimum, maximum, default."""
    kind = KINDS.get(entry["kind"], entry["kind"])
    lo = (f"above {_fmt(entry['min'])}" if entry["min_exclusive"] else f"minimum {_fmt(entry['min'])}") if entry["min"] is not None else "no minimum enforced"
    hi = (f"below {_fmt(entry['max'])}" if entry["max_exclusive"] else f"maximum {_fmt(entry['max'])}") if entry["max"] is not None else "no maximum enforced"
    unit = f" ({entry['unit']})" if entry["unit"] and entry["unit"] != "0 or 1" else ""
    text = f"{kind[0].upper() + kind[1:]}{unit}; {lo}; {hi}"
    if entry["max"] is None and entry["min"] is None:
        text = f"{kind[0].upper() + kind[1:]}{unit}; no limit enforced"
    if default not in (None, "", "unset"):
        text += f"; default {default}"
    elif default == "unset":
        text += "; default: no limit"
    return text + "."


def public(entry: dict, default=None) -> dict:
    """What the window gets for one setting: bounds for the input, the label, and the tooltip (the label plus the note)."""
    slider = entry["min"] is not None and entry["max"] is not None
    text = label(entry, default)
    return {"kind": entry["kind"], "unit": entry["unit"], "min": entry["min"], "max": entry["max"], "min_exclusive": entry["min_exclusive"], "max_exclusive": entry["max_exclusive"],
            "step": entry["step"], "slider": slider, "enforced_by": entry["enforced_by"], "label": text,
            "tooltip": {"summary": f"{text} {entry['note']}".strip(), "choices": [], "default": "", "flag": "", "setting": entry["key"], "when": ""}}


def check(entry: dict, value) -> str | None:
    """None when the value is acceptable, else a plain sentence. Empty means "back to the default" and is the caller's to allow."""
    text = str(value).strip()
    name = entry["key"]
    if entry["kind"] in ("integer", "flag"):
        if not re.fullmatch(r"\d+", text):
            return f"{name}: enter a whole number" + (f" (minimum {_fmt(entry['min'])})" if entry["min"] is not None else "") + f", not '{text}'."
        number = int(text)
    else:
        try:
            number = float(text)
        except ValueError:
            return f"{name}: enter a number (for example 0.30), not '{text}'."
        if math.isnan(number) or math.isinf(number):
            return f"{name}: enter a finite number, not '{text}'."
    lo, hi = entry["min"], entry["max"]
    if lo is not None and (number <= lo if entry["min_exclusive"] else number < lo):
        return f"{name}: {text} is too low. {label(entry)}"
    if hi is not None and (number >= hi if entry["max_exclusive"] else number > hi):
        return f"{name}: {text} is too high. {label(entry)}"
    return None


def validate_changes(changes: dict, current: dict | None = None, root=ROOT) -> None:
    """Refuse, with a plain sentence, any changed value that is outside its range. Clearing a setting (None or empty) is always allowed; a value equal to the one already saved
    is left alone, so an old saved value that is now out of range does not stop the other changes in the same save."""
    entries = load(root)
    current = current or {}
    for key, value in changes.items():
        if key not in entries or value is None or str(value).strip() == "":
            continue
        if key in current and str(current[key]).strip() == str(value).strip():
            continue
        problem = check(entries[key], value)
        if problem:
            raise ValueError(problem)


def numeric_decisions(rows: list) -> list:
    """The Scoring decisions that are numeric settings (prereg_admin.load rows): the ones that need a range entry."""
    return [r for r in rows if r.get("where") == "setting" and r.get("type") in ("int", "float", "int_or_none", "yesno") and (r.get("config_variable") or "").strip()]
