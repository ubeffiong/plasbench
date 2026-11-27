#!/usr/bin/env python3
"""The one registry of settings whose valid values are a finite known set (config/setting_options.tsv), and the checks built on it.

The window draws every such setting as a dropdown with these options (Settings, the workflow rows and the wizard offer the same list), the server refuses a new value outside the list when a
setting is saved, and the validators that can read it (short_read_qc.py, run_profiles.py, annotate_reference.py, docker_runtime.py, assembly_selection.py) take their allowed values from
it. For the validators that live in other files (argparse choices elsewhere, prereg.tsv, shell scripts) test/test_setting_options.py compares the table with the code, so they cannot drift.

kind enum  = exactly the listed values (an empty value means "every"/unset where the table lists one).
kind combo = the listed keywords plus "@number" (a number with unit, minimum, maximum and step) or "@path" (a folder).
A value already saved that is not in the list is never rejected on a save that does not change it, and the window shows it as "Custom: <value>". Standard library only; Python 3.9 compatible.
"""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TABLE = "config/setting_options.tsv"
NUMBER, PATH = "@number", "@path"


def load(root=ROOT) -> dict:
    """key -> {"kind", "options": [{"value", "label", "meaning", "default"}], "source", "number": {...} or None, "path": bool}. A missing table is an empty dict, never an error."""
    out = {}
    try:
        with open(Path(root) / TABLE, encoding="utf-8", newline="") as handle:
            lines = [ln for ln in handle if ln.strip() and not ln.startswith("#")]
    except OSError:
        return out
    for row in csv.DictReader(lines, delimiter="\t"):
        key = (row.get("key") or "").strip()
        if not key:
            continue
        entry = out.setdefault(key, {"kind": row.get("kind", "enum"), "options": [], "source": row.get("source", ""), "number": None, "path": False})
        value = row.get("value", "")
        if value == NUMBER:
            def num(name):
                text = (row.get(name) or "").strip()
                return None if not text else (float(text) if "." in text else int(text))
            entry["number"] = {"unit": row.get("number_unit", ""), "min": num("number_min"), "max": num("number_max"), "step": num("number_step") or 1,
                               "label": row.get("label", "Number..."), "meaning": row.get("meaning", "")}
            continue
        if value == PATH:
            entry["path"] = {"label": row.get("label", "Folder..."), "meaning": row.get("meaning", "")}
            continue
        entry["options"].append({"value": value, "label": row.get("label", value), "meaning": row.get("meaning", ""), "default": (row.get("default") or "").strip() == "yes"})
    return out


def values(key, root=ROOT) -> list:
    """The listed values of a setting, in table order (keywords only for a combo)."""
    entry = load(root).get(key)
    return [o["value"] for o in entry["options"]] if entry else []


def default_value(key, root=ROOT):
    entry = load(root).get(key)
    for o in (entry or {}).get("options", []):
        if o["default"]:
            return o["value"]
    return None


def check(key, value, root=ROOT) -> str:
    """"" when `value` is acceptable for `key`, else one plain sentence."""
    entry = load(root).get(key)
    if entry is None:
        return ""
    text = str(value)
    listed = [o["value"] for o in entry["options"]]
    if text in listed:
        return ""
    if entry["number"]:
        n = entry["number"]
        try:
            number = float(text)
        except ValueError:
            number = None
        if number is not None:
            if n["min"] is not None and number < n["min"]:
                return f"{key}: {text} is below the minimum {n['min']}" + (f" ({n['unit']})" if n["unit"] else "") + "."
            if n["max"] is not None and number > n["max"]:
                return f"{key}: {text} is above the maximum {n['max']}" + (f" ({n['unit']})" if n["unit"] else "") + "."
            return ""
    if entry["path"] and text.strip() and text.strip() not in ("0", "1"):
        return ""
    allowed = ", ".join(listed) + (", a number" if entry["number"] else "") + (", or a folder" if entry["path"] else "")
    return f"{key}: '{text}' is not one of {allowed}."


def validate_changes(changes: dict, current: dict | None = None, root=ROOT) -> None:
    """Refuse, with a plain sentence, a changed value outside its options. Clearing (None or empty for a key without an empty option) is always allowed, and a value equal to the one
    already saved is left alone, so a hand-edited or older value never blocks the other changes in the same save."""
    entries = load(root)
    current = current or {}
    for key, value in changes.items():
        if key not in entries or value is None:
            continue
        if str(value).strip() == "" and "" not in [o["value"] for o in entries[key]["options"]]:
            continue
        if key in current and str(current[key]) == str(value):
            continue
        problem = check(key, value, root)
        if problem:
            raise ValueError(problem)


def public(key, root=ROOT):
    """What the window needs for a setting, or None when it has no registry entry."""
    return load(root).get(key)


if __name__ == "__main__":
    for k, e in load().items():
        print(k, [o["value"] for o in e["options"]] + ([NUMBER] if e["number"] else []) + ([PATH] if e["path"] else []))
