#!/usr/bin/env python3
"""Run profiles: fast, standard and thorough (config/run_profiles.tsv).

  standard   today's defaults: nothing is overridden.
  fast       switches off costly optional analyses that never change the leaderboard, the scoring or the truth-label evidence (ISEScan, the ranking-stability and rank-sensitivity
             sweeps, performance drivers, the recommender evaluation, the per-dimension tables, bin agreement, candidate multiplicity, the MultiQC companion).
  thorough   turns the optional extras on (ISEScan over the chromosome too, difficulty descriptors, QUAST, depth anomalies, the replicon baseline).

A profile only sets the keys the table lists, and only where the user did not set that key (an environment variable or --flag always wins). The profile name is written to the run manifest and
the report's run metadata, so a fast run is never mistaken for a standard one.

  python3 run_profiles.py list
  python3 run_profiles.py plan NAME              what NAME switches off or on, and the time it saves (measured or "not measured")
  python3 run_profiles.py export NAME            shell lines for scripts/config.sh (keys not already set)
  python3 run_profiles.py validate               every key exists in config/config.sh and every value is legal
  python3 run_profiles.py record NAME            JSON for run_manifest.json
"""
from __future__ import annotations

import csv
import json
import os
import re
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "config" / "run_profiles.tsv"
PROFILES = ("fast", "standard", "thorough")   # the options of RUN_PROFILE in config/setting_options.tsv (test_setting_options.py compares them)
FLAG_VALUES = {"0", "1"}
sys.path.insert(0, str(Path(__file__).resolve().parent))
import setting_options  # noqa: E402

CHOICE_VALUES = {"ISESCAN_SCOPE": set(setting_options.values("ISESCAN_SCOPE")), "MULTIQC_REPORT": set(setting_options.values("MULTIQC_REPORT"))}


def read_table(path=TABLE):
    rows = []
    with open(path, encoding="utf-8", newline="") as handle:
        lines = [line for line in handle if line.strip() and not line.startswith("#")]
    for row in csv.DictReader(lines, delimiter="\t"):
        rows.append({key: (value or "").strip() for key, value in row.items()})
    return rows


def settings_for(profile, rows=None):
    """{key: value} the profile overrides ({} for standard)."""
    if profile not in PROFILES:
        raise ValueError(f"unknown run profile '{profile}' (choose fast, standard or thorough)")
    if profile == "standard":
        return {}
    rows = read_table() if rows is None else rows
    return {row["key"]: row[profile] for row in rows if row.get(profile)}


def standard_values(config_text):
    """{key: default} read from the `export KEY="${KEY:-default}"` lines of config/config.sh (defaults that are not a plain word are left out)."""
    values = {}
    for match in re.finditer(r'^export ([A-Z][A-Z0-9_]*)="\$\{\1:-([A-Za-z0-9_.-]*)\}"', config_text, re.M):
        values[match.group(1)] = match.group(2)
    return values


def validate(rows=None, config_text=None):
    """A list of problems (empty when the table is sound)."""
    rows = read_table() if rows is None else rows
    config_text = (ROOT / "config" / "config.sh").read_text(encoding="utf-8") if config_text is None else config_text
    problems, defaults, seen = [], standard_values(config_text), set()
    for row in rows:
        key = row["key"]
        if key in seen:
            problems.append(f"{key}: listed twice")
        seen.add(key)
        if not re.search(rf'^export {re.escape(key)}=', config_text, re.M):
            problems.append(f"{key}: not a setting in config/config.sh")
            continue
        legal = CHOICE_VALUES.get(key, FLAG_VALUES)
        for profile in ("fast", "thorough"):
            if row.get(profile) and row[profile] not in legal:
                problems.append(f"{key}: {profile} value '{row[profile]}' is not one of {sorted(legal)}")
            if row.get(profile) and defaults.get(key) == row[profile]:
                problems.append(f"{key}: {profile} value '{row[profile]}' equals the standard value (the row changes nothing)")
        if row.get("affects_headline") != "no":
            problems.append(f"{key}: affects_headline must be 'no' (a profile never changes the leaderboard)")
        if not row.get("basis"):
            problems.append(f"{key}: basis (measured, or 'not measured') is missing")
    return problems


def plan(profile, environ=None, rows=None):
    """What the profile changes for this environment: [{key, from, to, label, saving, basis, user_set}]."""
    environ = os.environ if environ is None else environ
    rows = read_table() if rows is None else rows
    config_text = (ROOT / "config" / "config.sh").read_text(encoding="utf-8")
    defaults = standard_values(config_text)
    out = []
    for row in rows:
        value = row.get(profile) if profile != "standard" else ""
        if not value:
            continue
        user_set = row["key"] in environ and environ[row["key"]] != "" and environ[row["key"]] != value and not environ.get("_PB_PROFILE_APPLIED")
        out.append({"key": row["key"], "from": defaults.get(row["key"], ""), "to": value, "label": row["label"], "saving": row["saving"], "basis": row["basis"], "user_set": bool(user_set)})
    return out


def describe(profile, environ=None):
    """The lines printed at the start of a run: what the profile turned off or on, and the time it saves."""
    if profile == "standard":
        return ["Run profile: standard (today's defaults)."]
    items = plan(profile, environ)
    lines = [f"Run profile: {profile}. The leaderboard, the scoring and the truth-label evidence are the same as in the standard profile; the report says which profile was used."]
    off = [i for i in items if i["to"] in ("0", "off")]
    on = [i for i in items if i["to"] not in ("0", "off")]
    for title, group in (("turned off", off), ("turned on", on)):
        for item in group:
            lines.append(f"  {title}: {item['label']} ({item['key']}={item['to']}); time: {item['saving']} [{item['basis'].split(';')[0]}]")
    measured = [i for i in off if i["basis"].startswith("measured")]
    if profile == "fast":
        lines.append("  Estimated time saved: " + ("about 30 min per isolate on a 5 Mbp genome from ISEScan (measured on a 6-CPU laptop); the other switches save seconds to minutes (not measured)."
                                                   if measured else "not measured."))
    for item in items:
        if item["user_set"]:
            lines.append(f"  note: {item['key']} is set to {os.environ.get(item['key'])} by you, so the profile leaves it as it is.")
    return lines


def export_lines(profile, environ=None):
    """Shell lines that set each profile key only when it is not already set (an explicit setting wins)."""
    environ = os.environ if environ is None else environ
    lines = []
    for key, value in settings_for(profile).items():
        if environ.get(key, "") == "":
            lines.append(f"export {key}={shlex.quote(value)}")
    return lines


def record(profile, environ=None):
    environ = os.environ if environ is None else environ
    items = plan(profile, environ) if profile != "standard" else []
    applied = {i["key"]: environ.get(i["key"], i["to"]) for i in items}
    return {"profile": profile, "overrides": [{"key": i["key"], "standard": i["from"], "value": applied[i["key"]], "label": i["label"], "user_set": i["user_set"]} for i in items],
            "headline_unchanged": True,
            "meaning": ("fast switches off optional analyses that do not change the leaderboard; thorough turns optional extras on; standard changes nothing. "
                        "The headline scores come from the same scoring code in every profile.")}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else "list"
    name = argv[1] if len(argv) > 1 else os.environ.get("RUN_PROFILE", "standard") or "standard"
    if command == "list":
        for profile in PROFILES:
            print(f"{profile}: {len(settings_for(profile))} setting(s) changed")
        return 0
    if command == "validate":
        problems = validate()
        print("\n".join(problems) if problems else "run_profiles.tsv is sound")
        return 1 if problems else 0
    try:
        if command == "plan":
            print("\n".join(describe(name)))
        elif command == "export":
            print("\n".join(export_lines(name)))
        elif command == "record":
            print(json.dumps(record(name), indent=2))
        else:
            print(__doc__)
            return 2
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
