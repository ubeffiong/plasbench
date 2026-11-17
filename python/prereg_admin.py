#!/usr/bin/env python3
"""
prereg_admin.py -- read, confirm and change PlasBench's pre-registered scoring decisions, and keep a record of who decided what and when.

The decisions live in config/prereg.tsv (value, status, technical note). This script adds three things around that file:

  config/prereg_plain.tsv      every decision in plain words: what it decides, what changes if you change it, and what kind of value it takes
  config/prereg_decisions.tsv  the decision record: one line each time a decision was confirmed or changed (date, who, old value, new value, why)
  config/prereg.lock.json      the lock written by `freeze_prereg.py --write --strict`: a fingerprint of prereg.tsv, so a later edit is noticed

Commands
  list [--topic T] [--status S]   every decision with its value and status
  show PARAMETER                  one decision in full, with its history
  history [PARAMETER]             the decision record
  confirm PARAMETER... --by NAME --reason TEXT   confirm proposed decisions as they are (status proposed -> fixed)
  confirm --all-proposed --by NAME --reason TEXT
  set PARAMETER VALUE --by NAME --reason TEXT    change a decision that is a setting (status fixed). Writes prereg.tsv, the record, and this computer's
                                                 settings (config/local.env); --update-default also changes the default in config/config.sh so the change
                                                 travels with the source
  lock                            freeze the decisions (refuses while any is still proposed)
  status                          one JSON line: how many decisions, how many confirmed, whether the lock matches
  check                           consistency of the three files (every decision described, every record names a real decision)
  doc                             the decisions as a Markdown table, grouped by topic (used to build docs/PREREGISTRATION.md)

Which decisions can be changed with `set`
  setting   the decision is a PlasBench setting (it has a config variable): `set` changes the value and the program uses it
  file      the decision is a table in a config file (the scorecard bands): edit that file, then record the change with `confirm`/`set` is refused here
  built-in  the decision is written into the scoring code: changing the text would record something the program does not do, so `set` refuses it

Changing a confirmed decision means results made before the change cannot be compared with results made after it. `set` says so, marks the lock stale, and the report
shows the departure until the decisions are locked again. Standard library only.
"""
import argparse
import csv
import datetime
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import freeze_prereg  # noqa: E402
from plasbench_common import subprocess_timeout  # noqa: E402

PREREG = "config/prereg.tsv"
PLAIN = "config/prereg_plain.tsv"
DECISIONS = "config/prereg_decisions.tsv"
LOCK = "config/prereg.lock.json"
DECISION_FIELDS = ("date", "parameter", "action", "old_value", "new_value", "decided_by", "reason")
TYPES = ("int", "int_or_none", "float", "yesno", "choice", "text")
NONE_WORDS = ("none", "unset", "no limit", "nolimit", "off")   # for a setting that may be switched off: 'unset' is how prereg.tsv writes it, and the program reads it as blank


def _read(path):
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader((l for l in handle if l.strip() and not l.startswith("#")), delimiter="\t"))
    return [{k: (v if v is not None else "") for k, v in row.items()} for row in rows]   # a row with fewer cells than the header reads as empty cells


def _write(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def where_kind(row):
    """setting (changeable here), file (the scorecard tables) or built-in (in the scoring code)."""
    if (row.get("config_variable") or "").strip():
        return "setting"
    return "file" if row["parameter"].startswith("scorecard_") else "built-in"


def load(root=ROOT):
    """The decisions, each joined with its plain-language description and its latest record."""
    root = Path(root)
    prereg = {r["parameter"]: r for r in freeze_prereg.read_rows(root / PREREG)}
    plain = {r["parameter"]: r for r in _read(root / PLAIN)} if (root / PLAIN).is_file() else {}
    log = history(root)
    out = []
    for name, row in prereg.items():
        p = plain.get(name, {})
        latest = next((e for e in reversed(log) if e["parameter"] == name), None)
        out.append({**row, "topic": p.get("topic", "Other"), "title": p.get("title", name), "meaning": p.get("meaning", row.get("note", "")),
                    "if_changed": p.get("if_changed", ""), "type": p.get("type", "text"), "choices": [c for c in (p.get("choices") or "").split(",") if c],
                    "where": where_kind(row), "last_action": latest["action"] if latest else "", "decided_on": latest["date"] if latest else "",
                    "decided_by": latest["decided_by"] if latest else "", "decision_reason": latest["reason"] if latest else ""})
    return out


def history(root=ROOT, parameter=None):
    path = Path(root) / DECISIONS
    rows = _read(path) if path.is_file() else []
    return [r for r in rows if not parameter or r["parameter"] == parameter]


def _append_decision(root, entries):
    path = Path(root) / DECISIONS
    rows = _read(path) if path.is_file() else []
    _write(path, DECISION_FIELDS, rows + entries)


def validate_value(row, value):
    """The value as it will be written, or ValueError with a plain sentence."""
    value = str(value).strip()
    kind, choices = row["type"], row["choices"]
    if value == "" and row["type"] != "int_or_none":
        raise ValueError("a value is required")
    if value == "":
        value = "none"
    if kind == "int_or_none":
        if value.lower() in NONE_WORDS:
            return "unset"
        if not re.fullmatch(r"\d+", value) or int(value) == 0:
            raise ValueError(f"{row['title']}: enter a whole number of seconds, or none for no limit")
    elif kind == "int":
        if not re.fullmatch(r"\d+", value):
            raise ValueError(f"{row['title']}: enter a whole number (for example 5)")
    elif kind == "float":
        try:
            if float(value) < 0:
                raise ValueError
        except ValueError:
            raise ValueError(f"{row['title']}: enter a number (for example 0.30)")
    elif kind == "yesno":
        if value not in ("0", "1"):
            raise ValueError(f"{row['title']}: enter 1 for yes or 0 for no")
    elif choices:
        items = [v.strip() for v in value.split(",")] if kind == "text" else [value]
        bad = [v for v in items if v not in choices]
        if bad or not items:
            raise ValueError(f"{row['title']}: choose from {', '.join(choices)}" + (" (several allowed, separated by commas)" if kind == "text" else ""))
        value = ",".join(items)
    if "\n" in value or "\r" in value or "\t" in value:
        raise ValueError("a value cannot contain a line break or a tab")
    return value


def _need(reason, by):
    if len((reason or "").strip()) < 5:
        raise ValueError("say why in at least a few words (the reason is kept in the decision record)")
    if not (by or "").strip():
        raise ValueError("say who is deciding (your name is kept in the decision record)")


def program_value(value):
    """How a decision's value is written into the program's settings: 'unset' (no limit) is a blank setting."""
    return "" if str(value).strip().lower() == "unset" else str(value)


def _local_env_path(root):
    return Path(os.environ.get("PLASBENCH_LOCAL_SETTINGS", Path(root) / "config" / "local.env"))


def _write_local_env(root, key, value):
    path = _local_env_path(root)
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else ["# PlasBench settings for this computer (read by config/config.sh). Written by `plasbench ui`; edit freely."]
    out, done = [], False
    for line in lines:
        if re.match(rf"^\s*(?:export\s+)?{re.escape(key)}=", line):
            if not done:
                out.append(f"export {key}={shlex.quote(value)}")
            done = True
            continue
        out.append(line)
    if not done:
        out.append(f"export {key}={shlex.quote(value)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as _fh:
        _fh.write("\n".join(out) + "\n")


def _update_default(root, key, value):
    path = Path(root) / "config" / "config.sh"
    text = path.read_text(encoding="utf-8")
    new, n = re.subn(rf'(export\s+{re.escape(key)}="\$\{{{re.escape(key)}:-)([^}}]*)(\}}")', lambda m: m.group(1) + value + m.group(3), text)
    if not n:
        raise ValueError(f"could not find the default of {key} in config/config.sh")
    with open(path, "w", encoding="utf-8", newline="") as _fh:
        _fh.write(new)
    return n


def _rewrite_prereg(root, changes):
    """changes: {parameter: {column: value}}; every other cell and row stays as it is."""
    path = Path(root) / PREREG
    text = path.read_text(encoding="utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(newline)
    columns = lines[0].split("\t")
    for number, line in enumerate(lines[1:], start=1):   # edit only the cells that change: every other byte of every row stays as it was
        cells = line.split("\t")
        change = changes.get(cells[0])
        if not change:
            continue
        for column, value in change.items():
            index = columns.index(column)
            cells += [""] * (index + 1 - len(cells))
            cells[index] = value
        lines[number] = "\t".join(cells)
    with open(path, "w", encoding="utf-8", newline="") as _fh:
        _fh.write(newline.join(lines))


def set_value(root, parameter, value, reason, by, update_default=False, today=None):
    """Change one decision that is a setting. Returns the decision-record entry."""
    root = Path(root)
    rows = {r["parameter"]: r for r in load(root)}
    if parameter not in rows:
        raise ValueError(f"no such decision: {parameter}")
    row = rows[parameter]
    if row["where"] != "setting":
        raise ValueError(f"{row['title']} cannot be changed here: " + ("it is a table in config/scorecard.tsv; edit that file" if row["where"] == "file" else
                         "it is written into the scoring code, so changing the text would record something the program does not do. Changing it needs a new version of PlasBench"))
    _need(reason, by)
    new = validate_value(row, value)
    if new == row["value"].strip():
        raise ValueError(f"{row['title']} is already {new}")
    entry = {"date": today or datetime.date.today().isoformat(), "parameter": parameter, "action": "changed", "old_value": row["value"], "new_value": new,
             "decided_by": by.strip(), "reason": reason.strip()}
    _rewrite_prereg(root, {parameter: {"value": new, "status": "fixed"}})
    _write_local_env(root, row["config_variable"], program_value(new))
    if update_default:
        _update_default(root, row["config_variable"], program_value(new))
    _append_decision(root, [entry])
    return entry


def confirm(root, parameters, reason, by, today=None):
    """Confirm proposed decisions as they are (status proposed -> fixed). Returns the entries written."""
    root = Path(root)
    rows = {r["parameter"]: r for r in load(root)}
    _need(reason, by)
    wanted = list(parameters)
    unknown = [p for p in wanted if p not in rows]
    if unknown:
        raise ValueError("no such decision: " + ", ".join(unknown))
    todo = [p for p in wanted if rows[p]["status"] == "proposed"]
    day = today or datetime.date.today().isoformat()
    entries = [{"date": day, "parameter": p, "action": "confirmed", "old_value": rows[p]["value"], "new_value": rows[p]["value"], "decided_by": by.strip(), "reason": reason.strip()} for p in todo]
    if entries:
        _rewrite_prereg(root, {p: {"status": "fixed"} for p in todo})
        _append_decision(root, entries)
    return entries


def freeze_prereg_equal(planned, actual):
    """Do a planned value and a setting's value mean the same (0.30 and 0.3, 5 and 5.0, 'unset' and blank)?"""
    if str(planned).strip().lower() in ("", "unset") and str(actual).strip().lower() in ("", "unset"):
        return True
    try:
        return float(str(planned).strip()) == float(str(actual).strip())
    except ValueError:
        return str(planned).strip() == str(actual).strip()


def lock(root=ROOT):
    done = subprocess.run([sys.executable, str(HERE / "freeze_prereg.py"), "--prereg", str(Path(root) / PREREG), "--lock", str(Path(root) / LOCK), "--write", "--strict"],
                          capture_output=True, text=True, timeout=subprocess_timeout())
    if done.returncode != 0:
        raise ValueError((done.stderr or done.stdout).strip().replace("ERROR: ", ""))
    return status(root)


def status(root=ROOT):
    root = Path(root)
    base = freeze_prereg.status(root / PREREG, root / LOCK)
    rows = load(root)
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in freeze_prereg.STATUSES}
    base.update(decisions=len(rows), counts=counts, confirmed=counts["fixed"] + counts["unavailable"], recorded=len({e["parameter"] for e in history(root)}))
    return base


def check(root=ROOT):
    """Problems with the three files, as sentences (empty when consistent)."""
    root = Path(root)
    problems = []
    prereg = {r["parameter"]: r for r in freeze_prereg.read_rows(root / PREREG)}
    plain = {r["parameter"]: r for r in _read(root / PLAIN)}
    problems += [f"{p} has no plain-language description in {PLAIN}" for p in prereg if p not in plain]
    problems += [f"{p} in {PLAIN} is not a decision in {PREREG}" for p in plain if p not in prereg]
    for name, p in plain.items():
        if p["type"] not in TYPES:
            problems.append(f"{name}: type must be one of {TYPES}")
        for column in ("topic", "title", "meaning", "if_changed"):
            if not (p.get(column) or "").strip():
                problems.append(f"{name}: {column} is empty")
    for e in history(root):
        if e["parameter"] not in prereg:
            problems.append(f"the decision record names {e['parameter']}, which is not a decision")
        if e["action"] not in ("confirmed", "changed"):
            problems.append(f"the decision record has an unknown action {e['action']!r}")
    for r in load(root):
        if r["where"] == "setting" and (r["type"] in ("int", "float", "yesno", "choice") or r["choices"]):
            try:
                validate_value(r, r["value"])
            except ValueError as exc:
                problems.append(f"{r['parameter']}: the value {r['value']!r} does not fit its type ({exc})")
    return problems


def markdown(root=ROOT):
    rows = load(root)
    out = []
    for topic in dict.fromkeys(r["topic"] for r in rows):
        out += [f"### {topic}", "", "| Decision | What it means | Value | Can be changed |", "|---|---|---|---|"]
        for r in (x for x in rows if x["topic"] == topic):
            how = {"setting": "yes, in the window or with `plasbench analysis prereg set`", "file": "by editing `config/scorecard.tsv`", "built-in": "no (written into the program)"}[r["where"]]
            out.append(f"| **{r['title']}** (`{r['parameter']}`) | {r['meaning']} | `{r['value']}` | {how} |")
        out.append("")
    return "\n".join(out)


def _cli_row(r):
    return f"{r['status']:<11} {r['parameter']:<40} {r['value'][:48]}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(ROOT), help="the PlasBench folder (default: this one)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list"); p.add_argument("--topic"); p.add_argument("--status")
    p = sub.add_parser("show"); p.add_argument("parameter")
    p = sub.add_parser("history"); p.add_argument("parameter", nargs="?")
    p = sub.add_parser("confirm"); p.add_argument("parameters", nargs="*"); p.add_argument("--all-proposed", action="store_true"); p.add_argument("--by", required=True); p.add_argument("--reason", required=True)
    p = sub.add_parser("set"); p.add_argument("parameter"); p.add_argument("value"); p.add_argument("--by", required=True); p.add_argument("--reason", required=True); p.add_argument("--update-default", action="store_true")
    for name in ("lock", "status", "check", "doc"):
        sub.add_parser(name)
    args = ap.parse_args(argv)
    root = Path(args.root)
    try:
        if args.cmd == "list":
            for r in load(root):
                if (not args.topic or r["topic"].lower() == args.topic.lower()) and (not args.status or r["status"] == args.status):
                    print(_cli_row(r))
        elif args.cmd == "show":
            r = next((x for x in load(root) if x["parameter"] == args.parameter), None)
            if not r:
                raise ValueError(f"no such decision: {args.parameter}")
            print(f"{r['title']}  ({r['parameter']})\n  status:      {r['status']}\n  value:       {r['value']}\n  topic:       {r['topic']}\n  means:       {r['meaning']}\n  if changed:  {r['if_changed']}\n  changeable:  {r['where']}"
                  + (f" (setting {r['config_variable']})" if r["config_variable"] else ""))
            for e in history(root, args.parameter):
                print(f"  {e['date']}  {e['action']:<9} by {e['decided_by']}: {e['reason']}" + (f"  [{e['old_value']} -> {e['new_value']}]" if e["action"] == "changed" else ""))
        elif args.cmd == "history":
            for e in history(root, args.parameter):
                print(f"{e['date']}  {e['parameter']:<40} {e['action']:<9} {e['decided_by']}: {e['reason']}" + (f"  [{e['old_value']} -> {e['new_value']}]" if e["action"] == "changed" else ""))
        elif args.cmd == "confirm":
            names = [r["parameter"] for r in load(root) if r["status"] == "proposed"] if args.all_proposed else args.parameters
            if not names:
                raise ValueError("name the decisions to confirm, or use --all-proposed")
            done = confirm(root, names, args.reason, args.by)
            print(f"confirmed {len(done)} decision(s); the lock is now out of date: run `plasbench analysis prereg lock`")
        elif args.cmd == "set":
            e = set_value(root, args.parameter, args.value, args.reason, args.by, args.update_default)
            print(f"changed {e['parameter']}: {e['old_value']} -> {e['new_value']}. Results made before this change cannot be compared with results made after it. "
                  "The lock is now out of date: run `plasbench analysis prereg lock` when you are ready to lock the decisions again.")
        elif args.cmd == "lock":
            print(json.dumps(lock(root)))
        elif args.cmd == "status":
            print(json.dumps(status(root)))
        elif args.cmd == "check":
            problems = check(root)
            for problem in problems:
                print("PROBLEM:", problem)
            if problems:
                return 1
            print("pre-registration files are consistent")
        elif args.cmd == "doc":
            print(markdown(root))
    except ValueError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
