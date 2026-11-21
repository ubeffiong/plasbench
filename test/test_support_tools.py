#!/usr/bin/env python3
"""The support tools (annotation callers and the tools of optional features) are wired end to end: a switch in config.sh, a Workflow row, an install state and button on the card,
a place in "Install all enabled tools" and the offer before a run, and the annotation stage honouring the switch. Static checks of the page, the registry rows and config.sh."""
import csv
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
OK = True


def check(label, good, detail=""):
    global OK
    print(f"  {label}: {'PASS' if good else 'FAIL'}" + ("" if good else f"  [{detail}]"))
    OK = OK and bool(good)


read = lambda *p: open(os.path.join(ROOT, *p), encoding="utf-8").read()  # noqa: E731
html, webui, cfg = read("plasbench", "data", "ui.html"), read("plasbench", "webui.py"), read("config", "config.sh")
rows = list(csv.DictReader(open(os.path.join(ROOT, "config", "workflow_steps.tsv"), encoding="utf-8"), delimiter="\t"))
items = {r["item_id"]: r for r in rows}
import annotate_reference as ar  # noqa: E402

block = re.search(r"const SUPPORT_OF = \{(.*?)\};", html, re.S)
mapping = dict((k, re.findall(r'"([^"]+)"', v)) for k, v in re.findall(r"(\w+): \[([^\]]*)\]", block.group(1))) if block else {}
check("the page maps nine Workflow items to their support tools", len(mapping) == 9, mapping)
check("every mapped Workflow item exists in config/workflow_steps.tsv with a switch", all(k in items and items[k]["setting_key"] for k in mapping), [k for k in mapping if k not in items])
env_ids = set(re.findall(r'\("([A-Za-z0-9_.]+)", "[^"]*", "(?:reference-annotation|utilities|mobsuite|quast|multiqc|annotation|annotation-prokka)"', webui)) | {"deadends"}
check("every mapped tool is an environment check the Tools page lists", all(t in env_ids for ts in mapping.values() for t in ts), sorted({t for ts in mapping.values() for t in ts} - env_ids))
for key, caller in zip(("ANNOTATE_WITH_MOB_TYPER", "ANNOTATE_WITH_ABRICATE", "ANNOTATE_WITH_AMRFINDER", "ANNOTATE_WITH_ISESCAN", "ANNOTATE_WITH_BARRNAP"), ("mob_typer", "abricate", "amrfinder", "isescan", "barrnap")):
    check(f"{key}: exported on by default in config.sh, a Workflow row that needs RUN_REFERENCE_ANNOTATION, and the stage honours it",
          f'export {key}="${{{key}:-1}}"' in cfg and items.get(key, {}).get("requires") == "RUN_REFERENCE_ANNOTATION" and ar.CALLER_SWITCHES.get(caller) == key, key)
check("the Workflow card shows the install state and an Install button for them", "if (SUPPORT_OF[it.item_id]) return supportWorkflowHTML(it.item_id);" in html and "data-instsup" in html)
check("'Install all enabled tools' and the offer before a run include the missing support tools", html.count(".concat(supportNeeded())") == 2)
check("the cards refresh after an install job and when the workflow loads", html.count("wfRenderAll()") >= 2 and "getEnv(true).then(() => { if (typeof wfRenderAll" in html)
print("ALL SUPPORT-TOOL TESTS PASSED" if OK else "SUPPORT-TOOL TESTS FAILED")
sys.exit(0 if OK else 1)
