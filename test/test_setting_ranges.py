#!/usr/bin/env python3
"""The range label, tooltip and validation for numeric Scoring-decision settings come from one table (config/setting_ranges.tsv) that matches the code.

  1. Every numeric setting on the Scoring decisions page has an entry, and every entry is such a setting.
  2. The bounds agree with the validators that exist: python/prereg_admin.py validate_value (what the decision editor accepts) and the scorers' own argument checks
     (score_bins.py, run for real). Where the table says "no limit enforced", the validator really accepts a huge value.
  3. The window gets the range (label, tooltip text, min/max/step) on the decisions and on the Settings page rows.
  4. The settings save refuses an out-of-range value with a plain sentence, and never breaks a value that is already saved or a clear-to-default.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT))
import prereg_admin  # noqa: E402
import setting_ranges as sr  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(("PASS" if ok else "FAIL"), name, "" if ok else f"-> {detail}")
    if not ok:
        fails.append(name)


entries = sr.load(ROOT)
decisions = prereg_admin.load(ROOT)
numeric = sr.numeric_decisions(decisions)
need = {r["config_variable"] for r in numeric}
check("the table loads", len(entries) > 20, len(entries))
check("every numeric setting in the Scoring decisions has a range entry", need <= set(entries), sorted(need - set(entries)))
check("every range entry is a numeric Scoring-decision setting (no stray rows)", set(entries) <= need, sorted(set(entries) - need))
check("every entry says its type, unit and where the limit is enforced", all(e["kind"] in ("integer", "decimal", "flag") and e["unit"] and e["enforced_by"] for e in entries.values()))
by_var = {r["config_variable"]: r for r in numeric}
check("the table's type matches the decision's type (int / float / flag)",
      all({"int": "integer", "int_or_none": "integer", "float": "decimal", "yesno": "flag"}[by_var[k]["type"]] == e["kind"] for k, e in entries.items()), "")


def accepted(entry, text):
    row = by_var[entry["key"]]
    try:
        prereg_admin.validate_value(row, text)
        return True
    except ValueError:
        return False


# 2a. the decision editor's validator (prereg_admin.validate_value) and check() give the same answer at and around every bound
bad = []
for key, e in entries.items():
    lo, hi, step = e["min"], e["max"], e["step"]
    probes = []
    if lo is not None:
        probes += [(lo, not e["min_exclusive"]), (lo - step if e["kind"] == "decimal" else lo - 1, False)]
    if hi is not None:
        probes += [(hi, not e["max_exclusive"]), (hi + step if e["kind"] == "decimal" else hi + 1, False)]
    mid = (lo if lo is not None else 0) + (step if e["min_exclusive"] or e["kind"] == "integer" else 0)
    probes.append((mid, True))
    for value, expect in probes:
        text = str(int(value)) if e["kind"] != "decimal" and float(value) == int(value) else str(value)
        if e["kind"] != "decimal" and float(value) < 0:
            continue          # a negative whole number is refused as "not a whole number" by both
        got_check, got_admin = sr.check(e, text) is None, accepted(e, text)
        if got_check != expect or got_admin != expect:
            bad.append((key, text, "expected", expect, "check", got_check, "prereg_admin", got_admin))
check("check() and prereg_admin.validate_value agree with the table at, just inside and just outside every bound", not bad, bad[:4])

# 2b. 'no limit enforced' is true: a huge value is accepted by the validator
bad = [k for k, e in entries.items() if e["max"] is None and not accepted(e, "1000000" if e["kind"] == "integer" else "1000000.5")]
check("where the table says no maximum is enforced, the validator accepts a huge value", not bad, bad)
bad = [k for k, e in entries.items() if e["min"] is not None and e["min"] > 0 and accepted(e, "0") != (e["min"] <= 0)]
check("where the table has a positive minimum, the validator refuses 0", not bad, bad)

# 2c. the scorers' own checks (score_bins.py runs its argument validation before it reads any file)
def scorer(flag, value):
    argv = [sys.executable, str(ROOT / "python" / "score_bins.py"), "--truth", "x", "--paf", "x", "--bins", "x", "--out", "x", "--summary", "x", flag, str(value)]
    p = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    return "thresholds must" not in (p.stdout + p.stderr)       # True = the range check let it through (it then fails on the missing files)


pairs = {"MIN_ALIGNMENT_IDENTITY": "--min-alignment-identity", "MIN_ALIGNMENT_QUERY_COVERAGE": "--min-alignment-query-coverage", "MIN_ALIGNMENT_LENGTH": "--min-alignment-length",
         "MIN_ALIGNMENT_MAPQ": "--min-alignment-mapq", "PLASMID_RECOVERY_THRESHOLD": "--threshold"}
bad = []
for key, flag in pairs.items():
    e = entries[key]
    assert "score_" in e["enforced_by"], key
    lo, hi = e["min"], e["max"]
    cases = [(lo, not e["min_exclusive"]), ((lo - e["step"]) if e["kind"] == "decimal" else lo - 1, False)]
    if hi is not None:
        cases += [(hi, True), (hi + e["step"], False)]
    for value, expect in cases:
        if scorer(flag, value) != expect:
            bad.append((key, flag, value, "scorer should" + ("" if expect else " not") + " accept it"))
check("the table's bounds are what score_bins.py enforces (run for real: identity, coverage, length, MAPQ, recovery threshold)", not bad, bad)
check("a setting a scorer does not bound has no maximum in the table (no invented bounds)",
      all(e["max"] is None for k, e in entries.items() if "score_" not in e["enforced_by"] and e["kind"] != "flag"))

# 3. what the window gets
from plasbench import webui  # noqa: E402
with tempfile.TemporaryDirectory() as tmp:
    local = Path(tmp) / "local.env"
    os.environ["PLASBENCH_LOCAL_SETTINGS"] = str(local)
    project = webui.Project(ROOT)
    pr = project.prereg()
    rows = {r["config_variable"]: r for r in pr["rows"] if r.get("config_variable")}
    check("every numeric decision row carries a range for the window (label, tooltip text, min, max, step)",
          all(rows[k]["range"] and rows[k]["range"]["label"] and rows[k]["range"]["tooltip"]["summary"] and "step" in rows[k]["range"] for k in need), [k for k in need if not rows[k]["range"]])
    r = rows["MIN_ALIGNMENT_IDENTITY"]["range"]
    check("the range label names type, minimum, maximum and default; it is a slider only when both bounds are enforced",
          "Decimal number" in r["label"] and "minimum 0" in r["label"] and "maximum 1" in r["label"] and "default 0.90" in r["label"] and r["slider"] and r["min"] == 0 and r["max"] == 1
          and not rows["PERFECT_THRESHOLD"]["range"]["slider"] and "no maximum enforced" in rows["PERFECT_THRESHOLD"]["range"]["label"], (r, rows["PERFECT_THRESHOLD"]["range"]))
    check("the tooltip text repeats the range", "maximum 1" in r["tooltip"]["summary"])
    settings = {s["key"]: s for s in project.settings_resolved()}
    check("the Settings page rows have the range, and their tooltip says it", settings["MIN_ALIGNMENT_IDENTITY"]["range"]["max"] == 1
          and "Range:" in settings["MIN_ALIGNMENT_IDENTITY"]["tooltip"]["summary"] and "no limit enforced" not in settings["MIN_ALIGNMENT_IDENTITY"]["tooltip"]["summary"].split("Range:")[0])

    # 4. the server refuses out-of-range values
    def refused(changes):
        try:
            project.save_local_env(changes)
            return None
        except ValueError as exc:
            return str(exc)
    msg = refused({"MIN_ALIGNMENT_IDENTITY": "1.5"})
    check("saving MIN_ALIGNMENT_IDENTITY=1.5 is refused with a plain sentence naming the setting and the range", msg and "MIN_ALIGNMENT_IDENTITY" in msg and "too high" in msg and "maximum 1" in msg, msg)
    check("nothing was written by the refused save", not local.exists() or "1.5" not in local.read_text())
    check("a negative, a non-number and a fraction for a whole-number setting are refused",
          all(refused({"MIN_ALIGNMENT_LENGTH": v}) for v in ("0", "-5", "abc", "2.5")) and all(refused({"PLASMID_RECOVERY_THRESHOLD": v}) for v in ("0", "1.01", "nan", "x")))
    check("one bad value stops the whole save (nothing partial is written)", refused({"CHROMID_MIN_BP": "400000", "MIN_ALIGNMENT_IDENTITY": "2"}) and not local.exists())
    check("in-range values are saved, including both bounds", refused({"MIN_ALIGNMENT_IDENTITY": "0", "MIN_ALIGNMENT_QUERY_COVERAGE": "1", "PLASMID_RECOVERY_THRESHOLD": "1", "TOOL_RETRIES": "3", "PERFECT_THRESHOLD": "7"}) is None)
    check("a setting with no range (and a non-numeric one) is untouched by the check", refused({"NCBI_EMAIL": "a@b.org", "THREADS": "999"}) is None)
    # an existing saved value outside the range must never break saving other things
    local.write_text("export MIN_ALIGNMENT_IDENTITY=5\nexport TOOL_RETRIES=2\n", encoding="utf-8")
    check("an old saved out-of-range value does not block saving another setting", refused({"TOOL_RETRIES": "4"}) is None)
    check("saving the same old value again (the page re-sends what it shows) is allowed", refused({"MIN_ALIGNMENT_IDENTITY": "5"}) is None)
    check("clearing a setting back to its default is always allowed", refused({"MIN_ALIGNMENT_IDENTITY": None, "TOOL_TIMEOUT_SECONDS": ""}) is None)
    check("the existing out-of-range value can still be read and listed (nothing breaks)", isinstance(project.local_env(), dict) and project.settings_resolved())
    # the decision editor refuses the same range, with the same sentence
    row = next(d for d in decisions if d.get("config_variable") == "MIN_ALIGNMENT_IDENTITY")
    try:
        prereg_admin.validate_value(row, "1.5")
        edit_msg = None
    except ValueError as exc:
        edit_msg = str(exc)
    check("the decision editor refuses 1.5 for the same setting, with the range in the sentence", edit_msg and "maximum 1" in edit_msg, edit_msg)

html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
check("the page draws the range label, number/slider inputs with min, max and step, and the inline red message",
      "rangeLine(r.range" in html and "rangeAttrs(r.range)" in html and 'type="range"' in html and 'id="pe_rng"' in html and "rangeProblem(row.range" in html)

print("\nFAILED:" if fails else "\nAll setting-range checks passed.", *fails)
sys.exit(1 if fails else 0)
