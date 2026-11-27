#!/usr/bin/env python3
"""The dropdown registry (config/setting_options.tsv, python/setting_options.py) against the code that really validates each value.

  1. Every registry key is a setting in config/config.sh, its marked default is the one config.sh uses, and every option has a label and a meaning.
  2. PARITY: for each setting the registry's values equal the values the validating code accepts (argparse choices of the command or script, python constants, config/prereg.tsv choices,
     the keywords a parser understands). Validators that read the registry (short_read_qc.py, assembly_selection.py, annotate_reference.py, run_profiles.py) are checked to do so.
  3. The AI allow-list (config/ai_settable.tsv) offers only values the registry lists.
  4. check() / validate_changes(): a listed value, a combo keyword, a valid number or folder pass; anything else is refused with a plain sentence; clearing, an unchanged value and a saved
     value outside the list (hand-edited, older version) never block a save.
  5. The server: the Settings rows and the workflow items carry the SAME options for the same key; saving writes exactly the stored value; a saved custom value comes back unchanged.
  6. The page: Settings, the workflow rows and the wizard all draw the one optControl; node runs its state logic (selected option, 'Custom: <value>', combo number and folder, validation)."""
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT))
import setting_options as so  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILS.append(name)


reg = so.load(ROOT)
config = (ROOT / "config" / "config.sh").read_text(encoding="utf-8")

# ---- 1. the table itself ----
check("the registry is not empty and has the fields the window needs", len(reg) >= 30 and all(e["options"] for e in reg.values()), len(reg))
missing = [k for k in reg if not re.search(rf"^export {k}=", config, re.M)]
check("every registry key is a setting in config/config.sh", not missing, missing)
bad_default = []
for key, entry in reg.items():
    m = re.search(rf'^export {key}="\$\{{{key}:-([^}}]*)\}}"', config, re.M)
    marked = [o["value"] for o in entry["options"] if o["default"]]
    if len(marked) > 1:
        bad_default.append((key, "two defaults", marked))
    if m and entry["kind"] == "enum" and marked != [m.group(1)]:
        bad_default.append((key, m.group(1), marked))
    if m and entry["kind"] == "combo" and m.group(1) not in [o["value"] for o in entry["options"]] + [""] and not (entry["number"] and re.fullmatch(r"[\d.]+", m.group(1))):
        bad_default.append((key, m.group(1), "combo default is neither a keyword nor a number"))
check("the marked default of each setting is the one config.sh uses", not bad_default, bad_default)
thin = [(k, o["value"]) for k, e in reg.items() for o in e["options"] if not o["label"] or not o["meaning"]]
check("every option has a plain label and a one-sentence meaning", not thin, thin)

# ---- 2. parity with the validating code ----
from plasbench import ui_schema  # noqa: E402
schema = ui_schema.schema()
run_args = {a["dest"]: a for c in schema["commands"] if c["name"] == "run" for a in c["args"]}
runtime_choice = [a for c in schema["commands"] if c["name"] == "runtime" for a in c["args"] if a["dest"] == "choice"][0]["choices"]


def regvals(key):
    return [v for v in so.values(key, ROOT) if v != ""]


def same(a, b):
    return sorted(a) == sorted(b)


def src(path):
    return (ROOT / path).read_text(encoding="utf-8")


def argparse_choices(path, flag):
    """The tuple of strings after `flag` ... choices=(...) in a script's source."""
    m = re.search(re.escape(flag) + r"[^\n]*?choices=\(([^)]*)\)", src(path))
    return re.findall(r'"([^"]+)"', m.group(1)) if m else None


import prereg_admin  # noqa: E402
prereg = {r["config_variable"]: r["choices"] for r in prereg_admin.load(ROOT) if r.get("config_variable") and r.get("choices")}
import tool_capabilities as tc  # noqa: E402
import run_profiles as rp  # noqa: E402
import run_multiqc as rmq  # noqa: E402
import simulate_validation as sv  # noqa: E402
import flag_database_overlap as fdo  # noqa: E402
import annotate_reference as ar  # noqa: E402
import depth_cap as dc  # noqa: E402
import work_dir as wd  # noqa: E402

pb_rt = importlib.import_module("plasbench.docker_runtime")
PARITY = {
    "SHORT_READ_QC_MODE": ("python/short_read_qc.py reads the registry", lambda: 'setting_options.values("SHORT_READ_QC_MODE")' in src("python/short_read_qc.py") and regvals("SHORT_READ_QC_MODE")),
    "ASSEMBLY_SELECTION_POLICY": ("python/assembly_selection.py reads the registry", lambda: 'values("ASSEMBLY_SELECTION_POLICY")' in src("python/assembly_selection.py") and regvals("ASSEMBLY_SELECTION_POLICY")),
    "ISESCAN_SCOPE": ("annotate_reference.ISESCAN_SCOPES", lambda: list(ar.ISESCAN_SCOPES)),
    "RUN_PROFILE": ("run_profiles.PROFILES and the --profile choices", lambda: list(rp.PROFILES) if same(list(rp.PROFILES), run_args["profile"]["choices"]) else None),
    "MULTIQC_REPORT": ("run_multiqc.MODES", lambda: list(rmq.MODES)),
    "ASSEMBLER": ("plasbench run --assembler choices", lambda: run_args["assembler"]["choices"]),
    "FLYE_READ_TYPE": ("plasbench run --flye-read-type choices", lambda: run_args["flye_read_type"]["choices"]),
    "DECISION_PROFILE": ("plasbench run --decision-profile choices", lambda: run_args["decision_profile"]["choices"]),
    "ANALYSIS_TRACK": ("tool_capabilities.ANALYSIS_TRACKS", lambda: list(tc.ANALYSIS_TRACKS)),
    "ANALYSIS_TRACK_FILTER": ("tool_capabilities.ANALYSIS_TRACKS and run --analysis-track", lambda: list(tc.ANALYSIS_TRACKS) if same(list(tc.ANALYSIS_TRACKS), run_args["analysis_track"]["choices"]) else None),
    "PLASBENCH_RUNTIME": ("plasbench runtime choices", lambda: runtime_choice),
    "PLASBENCH_DOCKER_PULL": ("docker_runtime.PULL_POLICIES", lambda: list(pb_rt.PULL_POLICIES)),
    "STATS_VALIDATION_MODE": ("simulate_validation.SETTINGS", lambda: list(sv.SETTINGS)),
    "DISSIMILARITY_REPEATS": ("python/bin_agreement.py --repeats choices", lambda: argparse_choices("python/bin_agreement.py", '"--repeats"')),
    "LEAKAGE_CUTOFF_POLICY": ("python/flag_database_overlap.py --policy choices", lambda: argparse_choices("python/flag_database_overlap.py", '"--policy"')),
    "LEAKAGE_DATE_BASIS": ("flag_database_overlap.LEAKAGE_DATE_BASES", lambda: list(fdo.LEAKAGE_DATE_BASES)),
    "PROTEIN_ANNOTATION_ENGINE": ("python/annotate_proteins.py --engine choices", lambda: argparse_choices("python/annotate_proteins.py", '"--engine"')),
}
for key in ("TRUTH_LABEL_SCHEME", "HEADLINE_REFERENCE_INDEPENDENCE", "HEADLINE_INDEPENDENCE", "PLASBENCH_CI_METHOD", "PLASBENCH_CI_METHOD_STRATIFIED"):
    PARITY[key] = ("config/prereg.tsv choices", (lambda k=key: list(prereg.get(k) or [])))
for key, (what, getter) in sorted(PARITY.items()):
    try:
        got = getter()
    except Exception as exc:  # noqa: BLE001
        got = None
        what += f" (raised {exc})"
    check(f"parity {key}: the registry offers exactly what {what} accepts", bool(got) and same(regvals(key), got), (regvals(key), got))

# keywords a parser understands, checked by running it
check("READ_DEPTH_CAP_X: off and numbers are understood, the minimum and unit are declared",
      dc.parse_cap("off") == 0 and dc.parse_cap("300") == 300 and reg["READ_DEPTH_CAP_X"]["number"]["min"] == 1 and reg["READ_DEPTH_CAP_X"]["number"]["unit"] == "x coverage" and regvals("READ_DEPTH_CAP_X") == ["off"])
with tempfile.TemporaryDirectory() as tmp:
    for key in ("WORK_DIR", "DOWNLOAD_TMP_DIR"):
        good = all(wd.resolve(m, tmp, "study", tmp, 0)["dir"] for m in ("data", "auto", str(Path(tmp) / "folder")))
        check(f"{key}: auto, data and a folder are resolved by the code; the registry lists auto, data and a folder choice", good and regvals(key) == ["auto", "data"] and bool(reg[key]["path"]))
# shell-checked settings: the values appear in the setting's own config.sh comment and the scripts compare against them
shell_checked = {"READ_SOURCE": ["scripts/01_download.sh"], "UPDATE_CHECK": ["plasbench/updatecheck.py"], "ASSEMBLY_SELECTION_MODE": ["scripts/03_assemble.sh"],
                 "RUN_PUBLISHED_COMPARISON": ["scripts/06_aggregate.sh"], "RUN_PLSDB_NOVELTY": ["scripts/06_aggregate.sh"], "RUN_PLASEVAL_GATE": ["scripts/06_aggregate.sh"]}
for key, files in shell_checked.items():
    body = "\n".join(src(f) for f in files) + config
    words_ok = all(re.search(rf"\b{re.escape(v)}\b", body) for v in regvals(key))
    check(f"{key}: every listed value is a word the setting's comment and its scripts use", words_ok, regvals(key))
for key, script in (("MINIMAP2_PRESET", "scripts/05_score.sh"), ("TRUTH_LONG_READ_PRESET", "scripts/02_truth.sh")):
    check(f"{key}: passed to minimap2 -x unchanged (the preset names are minimap2's)", f'"${key}"' in src(script) or f"${key}" in src(script))

# ---- 3. the AI allow-list ----
bad_ai = []
for line in (ROOT / "config" / "ai_settable.tsv").read_text(encoding="utf-8").splitlines():
    cols = line.split("\t")
    if len(cols) >= 3 and cols[1] == "choice" and cols[0] in reg:
        allowed = [v for v in cols[2].split("|")]
        stray = [v for v in allowed if v not in so.values(cols[0], ROOT) and not (reg[cols[0]]["number"] and re.fullmatch(r"\d+", v))]
        if stray:
            bad_ai.append((cols[0], stray))
check("the AI allow-list offers only values the registry lists (or numbers a combo accepts)", not bad_ai, bad_ai)

# ---- 4. checks ----
check("every listed value of every setting passes check()", all(not so.check(k, o["value"], ROOT) for k, e in reg.items() for o in e["options"]))
check("a value outside the list is refused with a plain sentence", "not one of off, report, enforce" in so.check("SHORT_READ_QC_MODE", "strict", ROOT), so.check("SHORT_READ_QC_MODE", "strict", ROOT))
check("case is not changed or forgiven (Report is not report)", bool(so.check("SHORT_READ_QC_MODE", "Report", ROOT)))
check("a combo accepts a valid number, refuses one below its minimum and refuses text", not so.check("READ_DEPTH_CAP_X", "250", ROOT) and "minimum" in so.check("READ_DEPTH_CAP_X", "0", ROOT) and bool(so.check("READ_DEPTH_CAP_X", "lots", ROOT)))
check("a folder combo accepts a folder", not so.check("WORK_DIR", "/fast/scratch", ROOT))
try:
    so.validate_changes({"SHORT_READ_QC_MODE": "strict"}, {}, ROOT)
    check("a new bad value is refused on save", False)
except ValueError as exc:
    check("a new bad value is refused on save", "strict" in str(exc))
so.validate_changes({"SHORT_READ_QC_MODE": "strict", "ASSEMBLER": "unicycler"}, {"SHORT_READ_QC_MODE": "strict"}, ROOT)
check("a saved custom value does not block a save that leaves it alone", True)
so.validate_changes({"SHORT_READ_QC_MODE": None, "MULTIQC_REPORT": ""}, {}, ROOT)
check("clearing (back to default) always passes", True)

# ---- 5. the server ----
tmp = Path(tempfile.mkdtemp())
os.environ["PLASBENCH_LOCAL_SETTINGS"] = str(tmp / "local.env")
os.environ["PLASBENCH_UI_HOME"] = str(tmp / "ui")
from plasbench import loadcache, webui, workflow_steps  # noqa: E402
project = webui.Project(ROOT)
rows = {r["key"]: r for r in project.settings_resolved()}
check("the Settings rows of a registry key carry its options and the kind", rows["SHORT_READ_QC_MODE"]["kind"] == "enum" and [o["value"] for o in rows["SHORT_READ_QC_MODE"]["options"]["options"]] == ["off", "report", "enforce"])
check("a combo row carries its number spec", rows["READ_DEPTH_CAP_X"]["kind"] == "combo" and rows["READ_DEPTH_CAP_X"]["options"]["number"]["unit"] == "x coverage")
payload = workflow_steps.payload(ROOT, workflow_steps.current_values(project.settings()))
items = {i["setting_key"]: i for s in payload["steps"] for i in s["items"] if i.get("setting_key")}
parity = [k for k, i in items.items() if "options" in i and i["options"] != rows[k]["options"]]
check("a workflow row offers the SAME options as the Settings page (SHORT_READ_QC_MODE offers off, report and enforce in both)",
      not parity and [o["value"] for o in items["SHORT_READ_QC_MODE"]["options"]["options"]] == ["off", "report", "enforce"], parity)
check("every enum-backed workflow row has the dropdown options", all("options" in items[k] for k in ("SHORT_READ_QC_MODE", "ASSEMBLY_SELECTION_MODE", "MULTIQC_REPORT", "READ_DEPTH_CAP_X")))
project.save_local_env({"SHORT_READ_QC_MODE": "enforce", "READ_DEPTH_CAP_X": "300", "WORK_DIR": "/fast/scratch"})
loadcache.clear()   # the window does this after a change; the stat cache lasts half a second
saved = project.local_env()
check("saving writes exactly the stored value (no label text, no case change)", saved.get("SHORT_READ_QC_MODE") == "enforce" and saved.get("READ_DEPTH_CAP_X") == "300" and saved.get("WORK_DIR") == "/fast/scratch", saved)
try:
    project.save_local_env({"ISESCAN_SCOPE": "Plasmids Only"})
    check("the server refuses a label instead of a value", False)
except ValueError:
    check("the server refuses a label instead of a value", True)
(tmp / "local.env").write_text((tmp / "local.env").read_text(encoding="utf-8") + "export ASSEMBLY_SELECTION_POLICY=best\n", encoding="utf-8")
loadcache.clear()
project.save_local_env({"ASSEMBLER": "unicycler"})
loadcache.clear()
check("a hand-edited value outside the list is kept untouched by an unrelated save", project.local_env().get("ASSEMBLY_SELECTION_POLICY") == "best" and project.local_env().get("ASSEMBLER") == "unicycler", project.local_env())
loadcache.clear()
row = {r["key"]: r for r in project.settings_resolved()}["ASSEMBLY_SELECTION_POLICY"]
check("... and the row reports it as the saved value for the window to show as Custom", row["override"] == "best")
shutil.rmtree(tmp, ignore_errors=True)

# ---- 6. the page ----
html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
check("Settings, the workflow rows (so the wizard) all draw the one optControl", html.count("optControl(") >= 3 and "r.options ? optControl(r.options, r.key, cur" in html and "optControl(it.options, it.setting_key" in html)
check("a flag-free text box is no longer used for a registry setting (the options branch comes first)", html.index("r.options ? optControl") < html.index('<input type="text" data-key="${r.key}"'))
node = shutil.which("node")
if node:
    start, end = html.index("/* ---- Dropdowns for settings"), html.index("/* One handler for every option control")
    script = ("const esc = s => String(s ?? '').replace(/[&<>\"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));\nconst SET = {};\n" + html[start:end] +
              "\nconst reg = " + json.dumps({k: v for k, v in reg.items()}) + ";\nconst out = {};\n"
              "const q = reg.SHORT_READ_QC_MODE; out.saved = optState(q, 'enforce').sel; out.empty = optState(q, '').sel; out.custom = optState(q, 'strict'); "
              "const d = reg.READ_DEPTH_CAP_X; out.cap = [optState(d, 'off').sel, optState(d, '300'), optState(d, '').sel, optState(d, 'weird').sel, optProblem(d, '0'), optProblem(d, '250'), optProblem(d, ''), optProblem(d, 'x')]; "
              "const w = reg.WORK_DIR; out.work = [optState(w, 'data').sel, optState(w, '/fast/x'), optState(w, '').sel]; "
              "out.html = optControl(q, 'SHORT_READ_QC_MODE', 'enforce', 'settings', 's'); out.htmlCustom = optControl(q, 'SHORT_READ_QC_MODE', 'strict', 'settings', 's'); out.htmlCombo = optControl(d, 'READ_DEPTH_CAP_X', '300', 'settings', 's'); "
              "console.log(JSON.stringify(out));")
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    try:
        res = json.loads(done.stdout)
    except ValueError:
        res = {}
        check("the option logic runs in node", False, done.stderr[-300:])
    if res:
        check("node: the saved value is the selected option; nothing saved selects Default", res["saved"] == "enforce" and res["empty"] == "")
        check("node: a saved value not in the list is Custom: <value>, kept", res["custom"] == {"sel": "__custom", "custom": "strict"} and "Custom: strict" in res["htmlCustom"] and 'value="__custom" selected' in res["htmlCustom"])
        check("node: a combo shows the keyword, the number with its unit, or Custom", res["cap"][0] == "off" and res["cap"][1] == {"sel": "@number", "num": "300"} and res["cap"][2] == "" and res["cap"][3] == "__custom")
        check("node: the number is validated with the unit and minimum", "minimum is 1" in res["cap"][4] and "x coverage" in res["cap"][4] and res["cap"][5] == "" and res["cap"][6] == "Enter a value." and res["cap"][7] == "Enter a number.", res["cap"])
        check("node: a folder combo shows data, a folder, or Default", res["work"][0] == "data" and res["work"][1] == {"sel": "@path", "path": "/fast/x"} and res["work"][2] == "")
        check("node: every option's meaning is printed beside the select (not hover-only) and the default is marked",
              "Also exclude an isolate whose reads are a threshold REJECT" in res["html"] and "Skip the short-read QC gate" in res["html"] and 'class="tag rec">default' in res["html"] and "<select" in res["html"])
        check("node: the select is labelled and keyboard operable (a native select with an aria-label)", 'aria-label="SHORT_READ_QC_MODE"' in res["html"])
        check("node: the combo's number input has a unit, a minimum and an alert region", 'min="1"' in res["htmlCombo"] and "x coverage" in res["htmlCombo"] and 'role="alert"' in res["htmlCombo"])
    page = "\n".join(m for m in re.findall(r"<script>([\s\S]*?)</script>", html))
    (Path(tempfile.gettempdir()) / "pb_page_check.js").write_text(page, encoding="utf-8")
    syn = subprocess.run([node, "--check", str(Path(tempfile.gettempdir()) / "pb_page_check.js")], capture_output=True, text=True, timeout=60)
    check("the page script passes node --check", syn.returncode == 0, syn.stderr[-300:])
else:
    print("  note  node is not installed: the page logic checks were skipped")

print("\nALL SETTING OPTION TESTS PASSED" if not FAILS else f"\n{len(FAILS)} FAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
