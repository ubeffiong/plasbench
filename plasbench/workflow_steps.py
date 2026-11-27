"""The PlasBench workflow as one ordered chain of steps: the single source of truth for the window's Workflow view.

The data is config/workflow_steps.tsv: one row per item (a core stage, an optional analysis, a tool), grouped into the stages
scripts/00 to 08 and the metagenomics track. Each row says what the item does, which setting switches it (key and on/off values) or which
command-line flag, what it needs (an earlier item, a database, the internet, an input) and what it ADDS in run time, memory and disk per isolate.

Every resource figure carries an `evidence` class and a `basis`:
  measured      taken from a real run in this repository (results_real_cohort1/), the basis names the file and the isolates
  documented    taken from the README or config.sh (a stated requirement or size), not re-measured here
  not_measured  no figure exists; the field is blank and is never replaced by a guess
A total over the items you switch on is always labelled an estimate, and a blank field is listed as "not measured" instead of counting as zero.

The same arithmetic is written again in JavaScript in plasbench/data/ui.html (the block marked WF-PURE), and test/test_workflow_steps.py runs both on the same
cases so the page and this module cannot disagree.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

TSV = Path("config") / "workflow_steps.tsv"
KINDS = ("core", "optional", "alternative", "separate", "demo")
EVIDENCE = ("measured", "documented", "not_measured")
INTERNET = ("no", "yes", "first_use")
STATES = ("on", "off", "auto", "demo")
NUMERIC = ("time_min", "mem_gb", "disk_gb", "one_off_gb")
# What each item field means; the window prints these in its help.
RESOURCE_RULES = ("Time and disk add up over the items that are on; memory is the largest single item (the tools run one after another unless you raise the parallel settings).",
                  "Figures are per isolate and labelled estimated; a blank field is 'not measured' and is listed, never counted as zero.")


def _num(text):
    text = (text or "").strip()
    return float(text) if text else None


def load(root) -> list[dict]:
    """Every row of the chain as a dict with numbers parsed (blank = None) and requires split into a list."""
    path = Path(root) / TSV
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    for row in rows:
        row["step_order"] = int(row["step_order"])
        for key in NUMERIC:
            row[key] = _num(row.get(key))
        row["requires"] = [r for r in re.split(r"[,\s]+", row.get("requires") or "") if r]
    return rows


def steps(rows) -> list[dict]:
    """The rows grouped by step, in order."""
    out, index = [], {}
    for row in rows:
        sid = row["step_id"]
        if sid not in index:
            index[sid] = {"id": sid, "order": row["step_order"], "name": row["step_name"], "stage": row["stage"], "script": row["script"],
                          "blurb": row["step_blurb"], "items": []}
            out.append(index[sid])
        index[sid]["items"].append(row)
    return sorted(out, key=lambda s: s["order"])


# ---- state -------------------------------------------------------------------------------------------------------------------------------------------------------
def default_state(item) -> str:
    """'on', 'off', 'auto' (runs when its inputs exist) or 'demo' (no switch)."""
    return item["default"] if item["default"] in STATES else "off"


def state_of(item, value=None) -> str:
    """The state an item is in given the value of its setting ('' or None = the default). A core item is always on; an item without a setting stays at its default."""
    if item["kind"] == "core":
        return "on"
    if item["kind"] == "demo":
        return "demo"
    if item["kind"] == "separate":
        return default_state(item)
    if value is None or value == "":
        return default_state(item)
    if not item.get("setting_key") and not item.get("cli_flag"):
        return default_state(item)
    if value == (item.get("off_value") or "0") or value == "off":
        return "off"
    if value == "auto":
        return "auto"
    return "on"


def is_changed(item, value=None) -> bool:
    """True when the item is in another state than its default."""
    return state_of(item, value) != default_state(item) and item["kind"] not in ("core", "demo")


def _counts(state) -> bool:
    return state in ("on", "auto")


# ---- dependencies ------------------------------------------------------------------------------------------------------------------------------------------------
def by_id(rows) -> dict:
    return {r["item_id"]: r for r in rows}


def missing_requires(rows, states, item_id) -> list[str]:
    """The items `item_id` needs (directly or through others) that are off, nearest first. Core items count as on."""
    index, found, seen = by_id(rows), [], set()

    def walk(node):
        for req in index[node]["requires"]:
            if req in seen or req not in index:
                continue
            seen.add(req)
            walk(req)
            if index[req]["kind"] != "core" and not _counts(states.get(req, default_state(index[req]))):
                found.append(req)

    walk(item_id)
    return found


def dependents_on(rows, states, item_id) -> list[str]:
    """The items that are on and need `item_id` (directly or through others)."""
    index = by_id(rows)
    direct: dict[str, list[str]] = {}
    for row in rows:
        for req in row["requires"]:
            direct.setdefault(req, []).append(row["item_id"])
    out, stack, seen = [], [item_id], {item_id}
    while stack:
        for dep in direct.get(stack.pop(), []):
            if dep in seen:
                continue
            seen.add(dep)
            stack.append(dep)
            if _counts(states.get(dep, default_state(index[dep]))):
                out.append(dep)
    return out


# ---- estimate ----------------------------------------------------------------------------------------------------------------------------------------------------
def estimate(rows, states, isolates=1) -> dict:
    """What the selection costs for `isolates` isolates. states: item id -> on / off / auto (a missing id is its default; a core item is always on).

    time_min and disk_gb add up and scale with the number of isolates; mem_gb is the largest single item and does not scale; one_off_gb (a database installed once)
    adds up and does not scale. not_measured lists the enabled items with no figure, per field: those items are NOT counted as zero.
    """
    total = {"time_min": 0.0, "mem_gb": 0.0, "disk_gb": 0.0, "one_off_gb": 0.0}
    missing = {key: [] for key in NUMERIC}
    for row in rows:
        if row["kind"] in ("demo", "separate"):
            continue
        state = "on" if row["kind"] == "core" else states.get(row["item_id"], default_state(row))
        if not _counts(state):
            continue
        for key in NUMERIC:
            value = row.get(key)
            if value is None:
                if key != "one_off_gb":
                    missing[key].append(row["item_id"])
                continue
            total[key] = max(total[key], value) if key == "mem_gb" else total[key] + value
    n = max(1, int(isolates))
    return {"isolates": n, "time_min": round(total["time_min"] * n, 3), "mem_gb": round(total["mem_gb"], 3), "disk_gb": round(total["disk_gb"] * n, 3),
            "one_off_gb": round(total["one_off_gb"], 3), "not_measured": missing, "label": "estimated"}


def default_states(rows) -> dict:
    return {r["item_id"]: default_state(r) for r in rows}


def estimate_delta(rows, states, isolates=1) -> dict:
    """The estimate of the selection minus the estimate of the defaults (what you changed adds or saves). Memory is the difference of the peaks."""
    now, base = estimate(rows, states, isolates), estimate(rows, default_states(rows), isolates)
    return {key: round(now[key] - base[key], 3) for key in ("time_min", "mem_gb", "disk_gb", "one_off_gb")} | {"isolates": now["isolates"], "label": "estimated"}


def addable(rows, states) -> list[dict]:
    """The optional items and alternative tools that are off, with their cost: the 'What can I add?' list."""
    return [r for r in rows if r["kind"] in ("optional", "alternative") and (r.get("setting_key") or r.get("cli_flag"))
            and not _counts(states.get(r["item_id"], default_state(r)))]


# ---- consistency (the test calls this; a registry tool without a step, a setting that does not exist ... is an error) --------------------------------------------
def config_defaults(root) -> dict:
    """KEY -> default text of every `export KEY="${KEY:-default}"` in config/config.sh."""
    text = (Path(root) / "config" / "config.sh").read_text(encoding="utf-8", errors="replace")
    return {m.group(1): m.group(2) for m in re.finditer(r'^export ([A-Z][A-Z0-9_]*)="\$\{\1:-(.*?)\}"', text, re.M)}


def registry_tools(root) -> list[str]:
    with (Path(root) / "config" / "tool_capabilities.tsv").open(encoding="utf-8", newline="") as handle:
        return [r["tool"] for r in csv.DictReader(handle, delimiter="\t") if r.get("tool")]


def problems(root, rows=None) -> list[str]:
    """Every way the chain disagrees with the rest of the project. Empty = consistent."""
    root = Path(root)
    rows = load(root) if rows is None else rows
    errors, seen = [], set()
    defaults = config_defaults(root)
    cli_text = (root / "plasbench" / "cli.py").read_text(encoding="utf-8", errors="replace")
    ids = {r["item_id"] for r in rows}
    step_meta: dict[str, tuple] = {}
    for row in rows:
        item = row["item_id"]
        if item in seen:
            errors.append(f"{item}: listed twice")
        seen.add(item)
        meta = (row["step_order"], row["step_name"], row["stage"], row["script"])
        if step_meta.setdefault(row["step_id"], meta) != meta:
            errors.append(f"{row['step_id']}: its rows disagree about the step's order, name, stage or script")
        if row["kind"] not in KINDS:
            errors.append(f"{item}: kind {row['kind']!r} is not one of {KINDS}")
        if row["evidence"] not in EVIDENCE:
            errors.append(f"{item}: evidence {row['evidence']!r} is not one of {EVIDENCE}")
        if row["needs_internet"] not in INTERNET:
            errors.append(f"{item}: needs_internet {row['needs_internet']!r} is not one of {INTERNET}")
        if row["default"] not in STATES:
            errors.append(f"{item}: default {row['default']!r} is not one of {STATES}")
        if not row["description"].strip() or not row["basis"].strip():
            errors.append(f"{item}: description and basis are required")
        figures = [row[k] for k in NUMERIC]
        if row["evidence"] == "not_measured" and any(v is not None for v in figures):
            errors.append(f"{item}: evidence is not_measured but a figure is given")
        if row["evidence"] in ("measured", "documented") and all(v is None for v in figures):
            errors.append(f"{item}: evidence is {row['evidence']} but no figure is given")
        if any(v is not None and v < 0 for v in figures):
            errors.append(f"{item}: a negative figure")
        key = row["setting_key"]
        if key:
            if key not in defaults:
                errors.append(f"{item}: setting {key} is not in config/config.sh")
            else:
                value = defaults[key]
                state = "auto" if value == "auto" else "on" if value == row["on_value"] else "off" if value == row["off_value"] else "?"
                if state != row["default"]:
                    errors.append(f"{item}: default {row['default']} disagrees with config.sh ({key} defaults to {value!r})")
            if not row["on_value"] or not row["off_value"]:
                errors.append(f"{item}: a setting needs both on_value and off_value")
        flag = row["cli_flag"]
        if flag and not re.search(r'["\']' + re.escape(flag) + r'["\']', cli_text):
            errors.append(f"{item}: command-line flag {flag} is not defined in plasbench/cli.py")
        if row["kind"] in ("optional", "alternative") and not key and not flag:
            errors.append(f"{item}: an optional item needs a setting_key or a cli_flag")
        for req in row["requires"]:
            if req not in ids:
                errors.append(f"{item}: requires {req}, which is not an item")
    # cycles
    index = {r["item_id"]: r for r in rows}

    def cyclic(node, path):
        if node in path:
            return True
        return any(cyclic(r, path | {node}) for r in index.get(node, {"requires": []})["requires"] if r in index)

    for item in index:
        if cyclic(item, frozenset()):
            errors.append(f"{item}: requires itself through a cycle")
    # every registry tool in exactly one step; every item that is a tool is in the registry
    tools = registry_tools(root)
    for tool in tools:
        n = sum(1 for r in rows if r["item_id"] == tool)
        if n != 1:
            errors.append(f"registry tool {tool} is in {n} steps (it must be in exactly one): add it to config/workflow_steps.tsv")
    # every stage script is a step
    scripts = {f"scripts/{p.name}" for p in (root / "scripts").glob("0[0-9]_*.sh")}
    listed = {r["script"] for r in rows if r["script"]}
    for script in sorted(scripts - listed):
        errors.append(f"{script} is not a step in config/workflow_steps.tsv")
    for script in sorted(listed - scripts):
        errors.append(f"{script} is named by a step but does not exist")
    return errors


# ---- the chain with the current settings (GET /api/workflow) ------------------------------------------------------------------------------------------------------
def payload(root, values: dict) -> dict:
    """The chain, each item with its current value, state, whether it changed from its default, plus the default and current estimates.

    values: setting key -> the value in force now (local.env, then the process environment, then config.sh's default). Only the keys of the chain are read.
    """
    rows = load(root)
    states, out_steps = {}, steps(rows)
    try:                                    # the same option list the Settings page offers (config/setting_options.tsv)
        import sys as _sys
        _py = str(Path(root) / "python")
        if _py not in _sys.path:
            _sys.path.insert(0, _py)
        import setting_options
        registry = setting_options.load(root)
    except Exception:  # noqa: BLE001 - a missing table only means no mode dropdowns
        registry = {}
    for row in rows:
        key = row["setting_key"]
        value = values.get(key) if key else None
        row["value"] = value
        if key in registry:
            row["options"] = registry[key]
        row["state"] = state_of(row, value)
        row["changed"] = is_changed(row, value)
        states[row["item_id"]] = row["state"]
    return {"steps": out_steps, "defaults": default_states(rows), "states": states, "estimate": estimate(rows, states), "default_estimate": estimate(rows, default_states(rows)),
            "rules": list(RESOURCE_RULES)}


def current_values(setting_rows) -> dict:
    """key -> the value in force, from the window's settings rows: the saved override (config/local.env), then the process environment, then config.sh's default."""
    return {r["key"]: (r.get("override") or r.get("env") or r.get("default") or "") for r in setting_rows}
