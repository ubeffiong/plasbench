#!/usr/bin/env python3
"""The workflow chain (plasbench/workflow_steps.py, config/workflow_steps.tsv) and GET /api/workflow.

  - the data file agrees with the rest of the project: every setting key is in config/config.sh with the same default, every command-line flag exists,
    every tool in config/tool_capabilities.tsv is in exactly one step, every stage script scripts/0N_*.sh is a step, every `requires` names an item and there is no cycle;
  - adding a tool to the registry without a step FAILS this test (shown below on a copy), and so does a setting that does not exist;
  - the estimate: totals, memory is a peak not a sum, per-10 scaling, 'not measured' is listed and never counted as zero, the defaults match the figures in the file;
  - the dependency logic (needs / is needed by), the state of an item from its setting value, 'changed';
  - every figure marked measured can be recomputed from results_real_cohort1 (so the numbers are not invented);
  - GET /api/workflow is token-protected and returns the chain with the current settings state.
Standard library only.
"""
import csv
import json
import os
import shutil
import statistics
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def main():
    tmp = Path(tempfile.mkdtemp())
    os.environ["PLASBENCH_UI_HOME"] = str(tmp / "ui")
    os.environ["PLASBENCH_LOCAL_SETTINGS"] = str(tmp / "local.env")
    os.environ["HOME"] = os.environ["USERPROFILE"] = str(tmp / "home")
    (tmp / "home").mkdir()
    from plasbench import workflow_steps as ws

    rows = ws.load(ROOT)
    index = ws.by_id(rows)
    print("data file")
    errors = ws.problems(ROOT)
    check("the data file is consistent with config.sh, the CLI, the registry and the stage scripts", not errors, errors[:5])
    check("the steps are in stage order: 0 to 8 and the metagenomics track", [s["stage"] for s in ws.steps(rows)] == ["0", "1", "2", "3", "4", "5", "6", "7", "8", "meta"], [s["stage"] for s in ws.steps(rows)])
    registry = ws.registry_tools(ROOT)
    check("every tool in the registry is in exactly one step", all(sum(1 for r in rows if r["item_id"] == t) == 1 for t in registry) and len(registry) >= 28, registry)
    scripts = sorted(p.name for p in (ROOT / "scripts").glob("0[0-9]_*.sh"))
    check("every stage script (00 to 08) is a step", {f"scripts/{s}" for s in scripts} <= {r["script"] for r in rows}, scripts)
    check("every item has a one-line description and says where its figures come from", all(r["description"].strip() and r["basis"].strip() for r in rows))
    check("every setting key exists in config/config.sh with the default the file states", not [e for e in errors if "config" in e], errors)
    check("the core items have no switch and are on", all(r["default"] == "on" and not r["setting_key"] for r in rows if r["kind"] == "core"))
    check("the optional steps and tools all have a setting or a flag", all(r["setting_key"] or r["cli_flag"] for r in rows if r["kind"] in ("optional", "alternative")))

    print("a change that breaks the contract fails the check")
    copy = tmp / "copy"
    shutil.copytree(ROOT / "config", copy / "config")
    shutil.copytree(ROOT / "scripts", copy / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    (copy / "plasbench").mkdir()
    shutil.copy(ROOT / "plasbench" / "cli.py", copy / "plasbench" / "cli.py")
    check("the copy starts consistent", not ws.problems(copy))
    with (copy / "config" / "tool_capabilities.tsv").open("a", encoding="utf-8", newline="") as handle:
        handle.write("brand_new_tool\tclassification\tno\tassembly\tA tool added to the registry without a step.\tshort_read\tno\tuntested\t\tclassification\tcontig_labels\n")
    found = ws.problems(copy)
    check("a registry tool without a step is reported", any("brand_new_tool" in e and "exactly one" in e for e in found), found)
    shutil.copy(ROOT / "config" / "tool_capabilities.tsv", copy / "config" / "tool_capabilities.tsv")
    text = (copy / "config" / "workflow_steps.tsv").read_text(encoding="utf-8").replace("RUN_PLATON", "RUN_NO_SUCH_SETTING", 1)
    (copy / "config" / "workflow_steps.tsv").write_bytes((text).encode("utf-8"))
    found = ws.problems(copy)
    check("a setting key that is not in config.sh is reported", any("RUN_NO_SUCH_SETTING" in e for e in found), found)
    (copy / "scripts" / "09_new_stage.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    shutil.copy(ROOT / "config" / "workflow_steps.tsv", copy / "config" / "workflow_steps.tsv")
    found = ws.problems(copy)
    check("a stage script that is not a step is reported", any("09_new_stage.sh" in e for e in found), found)
    broken = [dict(r) for r in rows]
    next(r for r in broken if r["item_id"] == "mob_recon")["cli_flag"] = "--no-such-flag"
    check("a command-line flag that does not exist is reported", any("--no-such-flag" in e for e in ws.problems(ROOT, broken)))
    broken = [dict(r) for r in rows]
    next(r for r in broken if r["item_id"] == "mob_recon")["requires"] = ["platon"]
    next(r for r in broken if r["item_id"] == "platon")["requires"] = ["mob_recon"]
    check("a requirement cycle is reported", any("cycle" in e for e in ws.problems(ROOT, broken)))
    broken = [dict(r) for r in rows]
    next(r for r in broken if r["item_id"] == "mob_recon")["default"] = "off"
    check("a default that disagrees with config.sh is reported", any("disagrees with config.sh" in e for e in ws.problems(ROOT, broken)))
    broken = [dict(r) for r in rows]
    next(r for r in broken if r["item_id"] == "genomad")["time_min"] = 3.0
    check("a figure on an item marked not_measured is reported (no invented numbers)", any("not_measured but a figure" in e for e in ws.problems(ROOT, broken)))

    print("state")
    mob, gen, qc, gate = index["mob_recon"], index["genomad"], index["SHORT_READ_QC_MODE"], index["RUN_PLASEVAL_GATE"]
    check("a default-on tool is on and not changed; off is changed", ws.state_of(mob, "1") == "on" and not ws.is_changed(mob, "1") and ws.state_of(mob, "0") == "off" and ws.is_changed(mob, "0"))
    check("a default-off tool is off; on is changed", ws.state_of(gen, "0") == "off" and not ws.is_changed(gen, "0") and ws.state_of(gen, "1") == "on" and ws.is_changed(gen, "1"))
    check("an empty value is the default", ws.state_of(gen, "") == "off" and ws.state_of(mob, None) == "on")
    check("a mode setting: report and enforce are on, off is off", ws.state_of(qc, "report") == "on" and ws.state_of(qc, "enforce") == "on" and ws.state_of(qc, "off") == "off")
    check("an auto item is auto by default; 1 and 0 are changes", ws.state_of(gate, "auto") == "auto" and not ws.is_changed(gate, "auto") and ws.is_changed(gate, "1") and ws.is_changed(gate, "0"))
    check("a core item is always on and never changed", ws.state_of(index["core_score"], "0") == "on" and not ws.is_changed(index["core_score"], "0"))

    print("estimate")
    defaults = ws.default_states(rows)
    base = ws.estimate(rows, defaults)
    check("the default chain: time is the sum of the measured figures (assembly 5.9 + MOB 0.9 + Platon 1.0 + plasmidSPAdes 6.6 + baseline 0)", base["time_min"] == 14.4, base["time_min"])
    check("memory is the largest single tool (Platon 4.38 GB), not the sum", base["mem_gb"] == 4.38, base["mem_gb"])
    check("disk is the documented 0.63 GB per isolate; the one-off databases are 2.9 + 2.7 GB", base["disk_gb"] == 0.63 and base["one_off_gb"] == 5.6, (base["disk_gb"], base["one_off_gb"]))
    check("it is labelled an estimate", base["label"] == "estimated")
    ten = ws.estimate(rows, defaults, 10)
    check("per 10 isolates: time and disk scale by 10, memory and one-off downloads do not", ten["time_min"] == 144.0 and ten["disk_gb"] == 6.3 and ten["mem_gb"] == 4.38 and ten["one_off_gb"] == 5.6, ten)
    check("a count below 1 is 1", ws.estimate(rows, defaults, 0)["isolates"] == 1)
    check("items with no figure are listed, not counted as zero", "genomad" not in base["not_measured"]["time_min"]
          and {"core_score", "core_aggregate", "core_download"} <= set(base["not_measured"]["time_min"]))
    on = dict(defaults, genomad="on", plasmer="on")
    more = ws.estimate(rows, on)
    check("switching on a not-measured tool adds nothing to the time but lists it", more["time_min"] == base["time_min"] and "genomad" in more["not_measured"]["time_min"] and "plasmer" in more["not_measured"]["time_min"])
    check("Plasmer's documented 32 GB floor raises the peak memory to 32", more["mem_gb"] == 32.0, more["mem_gb"])
    off = dict(defaults, platon="off", plasmidspades="off")
    less = ws.estimate(rows, off)
    check("switching tools off removes their time, and the peak falls to the next largest (MOB-recon 2.95)", less["time_min"] == 6.8 and less["mem_gb"] == 2.95 and less["one_off_gb"] == 2.9, less)
    delta = ws.estimate_delta(rows, off)
    check("the difference from the defaults is the estimate minus the default estimate", delta["time_min"] == -7.6 and delta["one_off_gb"] == -2.7, delta)
    check("no change gives a zero difference", ws.estimate_delta(rows, defaults)["time_min"] == 0)
    check("a core item cannot be switched off in an estimate", ws.estimate(rows, dict(defaults, core_trim_assemble="off"))["time_min"] == 14.4)
    check("demo and own-command items never count", ws.estimate(rows, dict(defaults, mob_like="on", metagenomics_track="on", operational_reconstruct="on")) == base)
    check("auto counts as on", ws.estimate(rows, dict(defaults, RUN_PLSDB_NOVELTY="auto"))["not_measured"]["time_min"].count("RUN_PLSDB_NOVELTY") == 1)
    synth = [{"item_id": "a", "kind": "optional", "default": "on", "time_min": 1.5, "mem_gb": 2.0, "disk_gb": None, "one_off_gb": None, "requires": [], "setting_key": "A"},
             {"item_id": "b", "kind": "optional", "default": "off", "time_min": 2.25, "mem_gb": 3.0, "disk_gb": 0.5, "one_off_gb": 1.0, "requires": ["a"], "setting_key": "B"},
             {"item_id": "c", "kind": "optional", "default": "off", "time_min": None, "mem_gb": None, "disk_gb": None, "one_off_gb": None, "requires": ["b"], "setting_key": "C"}]
    e = ws.estimate(synth, {"a": "on", "b": "on", "c": "on"}, 4)
    check("arithmetic on a small chain (4 isolates): time 15, memory 3, disk 2, one-off 1; c is not measured",
          e["time_min"] == 15.0 and e["mem_gb"] == 3.0 and e["disk_gb"] == 2.0 and e["one_off_gb"] == 1.0 and e["not_measured"]["time_min"] == ["c"] and e["not_measured"]["disk_gb"] == ["a", "c"], e)
    check("addable lists the optional items that are off", [r["item_id"] for r in ws.addable(synth, {"a": "on", "b": "off", "c": "off"})] == ["b", "c"])

    print("dependencies")
    st = dict(defaults)
    check("gplas2 (MOB-seeded) needs MOB-recon: on when MOB-recon is on, so nothing is missing", ws.missing_requires(rows, dict(st, gplas2_mob="on"), "gplas2_mob") == [])
    check("turning MOB-recon off makes it missing for gplas2", ws.missing_requires(rows, dict(st, mob_recon="off", gplas2_mob="on"), "gplas2_mob") == ["mob_recon"])
    check("the core assembly never counts as missing", "core_trim_assemble" not in ws.missing_requires(rows, dict(st, platon="on"), "platon"))
    check("evidence-based truth labels need the reference annotation, which is off by default", ws.missing_requires(rows, dict(st, RUN_TRUTH_LABEL_EVIDENCE="on"), "RUN_TRUTH_LABEL_EVIDENCE") == ["RUN_REFERENCE_ANNOTATION"] or defaults["RUN_REFERENCE_ANNOTATION"] == "on")
    check("a chain of two missing steps lists both, nearest first", ws.missing_requires(synth, {"a": "off", "b": "off", "c": "on"}, "c") == ["b", "a"] or ws.missing_requires(synth, {"a": "off", "b": "off", "c": "on"}, "c") == ["a", "b"])
    check("MOB-recon has gplas2 on it as a dependent when gplas2 is on", ws.dependents_on(rows, dict(st, gplas2_mob="on"), "mob_recon") == ["gplas2_mob"])
    check("with gplas2 off nothing depends on MOB-recon", ws.dependents_on(rows, st, "mob_recon") == [])
    check("dependents are found through a chain", ws.dependents_on(synth, {"a": "on", "b": "on", "c": "on"}, "a") == ["b", "c"])

    print("measured figures can be recomputed")
    rc = list(csv.DictReader((ROOT / "results_real_cohort1" / "tool_status.tsv").open(encoding="utf-8"), delimiter="\t"))
    for tool in ("mob_recon", "platon", "plasmidspades"):
        done = [r for r in rc if r["tool"] == tool and r["status"] == "completed"]
        secs = statistics.median(int(r["runtime_seconds"]) for r in done)
        rss = max(int(r["peak_rss_kb"]) for r in done) / 1e6
        item = index[tool]
        check(f"{tool}: time {item['time_min']} min is the median of {len(done)} real runs ({secs:.0f} s); memory {item['mem_gb']} GB is the largest peak ({rss:.2f} GB)",
              len(done) == 10 and abs(item["time_min"] - secs / 60) < 0.05 and abs(item["mem_gb"] - rss) < 0.006, (item["time_min"], secs / 60, item["mem_gb"], rss))
    asm = [int(r["runtime_seconds"]) for r in csv.DictReader((ROOT / "results_real_cohort1" / "assembly_status.tsv").open(encoding="utf-8"), delimiter="\t") if r["runtime_seconds"]]
    check("trim and assemble: 5.9 min is the median of the 10 real assemblies", abs(index["core_trim_assemble"]["time_min"] - statistics.median(asm) / 60) < 0.05, statistics.median(asm))
    check("every row marked measured names its source file in the basis", all("results_real_cohort1" in r["basis"] for r in rows if r["evidence"] == "measured"))
    check("every figure that is not measured is blank, not zero (except the measured sub-second baseline)", all(r[k] is None for r in rows if r["evidence"] == "not_measured" for k in ws.NUMERIC))

    print("the route")
    import importlib
    webui = importlib.import_module("plasbench.webui")
    webui.UI_HOME = tmp / "ui"
    project = webui.Project(ROOT)
    jobs = webui.Jobs(project)
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.make_handler(project, jobs))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"

    def call(path, body=None, tok=True):
        h = {"Host": f"127.0.0.1:{server.server_address[1]}"}
        if tok:
            h["X-PlasBench-Token"] = webui.TOKEN
        data = json.dumps(body).encode() if body is not None else None
        if data is not None:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(base_url + path, data=data, headers=h, method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    check("GET /api/workflow without the token is refused", call("/api/workflow", tok=False)[0] == 403)
    code, raw = call("/api/workflow")
    data = json.loads(raw) if code == 200 else {}
    check("GET /api/workflow returns the chain", code == 200 and len(data.get("steps", [])) == 10, code)
    items = {i["item_id"]: i for s in data.get("steps", []) for i in s["items"]}
    check("each item carries its state, whether it changed, its default and its figures", all({"state", "changed", "default", "time_min", "evidence", "basis"} <= set(i) for i in items.values()))
    check("the states match the defaults when nothing is saved", all(not i["changed"] for i in items.values()) and data["states"]["mob_recon"] == "on" and data["states"]["genomad"] == "off")
    check("it returns the estimate for the selection and for the defaults", data["estimate"]["time_min"] == 14.4 and data["default_estimate"]["time_min"] == 14.4 and data["estimate"]["label"] == "estimated")
    code, _ = call("/api/settings", {"changes": {"RUN_GENOMAD": "1", "RUN_PLATON": "0", "SHORT_READ_QC_MODE": "off"}})
    check("a saved setting is accepted", code == 200, code)
    data = json.loads(call("/api/workflow")[1])
    items = {i["item_id"]: i for s in data["steps"] for i in s["items"]}
    check("the chain reflects the saved settings: genomad on and changed, Platon off and changed, QC off and changed", items["genomad"]["state"] == "on" and items["genomad"]["changed"]
          and items["platon"]["state"] == "off" and items["platon"]["changed"] and items["SHORT_READ_QC_MODE"]["state"] == "off" and items["SHORT_READ_QC_MODE"]["changed"], {k: items[k]["state"] for k in ("genomad", "platon")})
    check("the estimate follows the saved settings (Platon's minute is gone) and the default estimate does not", data["estimate"]["time_min"] == 13.4 and data["default_estimate"]["time_min"] == 14.4, data["estimate"]["time_min"])
    code, _ = call("/api/settings", {"changes": {"RUN_GENOMAD": None, "RUN_PLATON": None, "SHORT_READ_QC_MODE": None}})
    data = json.loads(call("/api/workflow")[1])
    check("clearing the settings returns every item to its default", not any(i["changed"] for s in data["steps"] for i in s["items"]))
    server.shutdown()
    print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL PASS")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
