#!/usr/bin/env python3
"""Hover / focus help for every setup field (plasbench/ui_help.py, exposed by ui_schema.schema() and /api/settings, drawn by plasbench/data/ui.html).

  - every argument of run, demo, reconstruct, report and intake carries a non-empty tooltip, and every `choices` entry of those arguments has a meaning;
  - READ_SOURCE lists auto / sra / ena with the meanings config.sh gives (the test also reads config.sh, so a changed comment is noticed);
  - every wizard control and every setting on the Settings page has tooltip text;
  - the page contains the tooltip component (role=tooltip, aria-describedby, an Escape handler) and node can parse its script.
Standard library only; the node check is skipped when node is missing.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
tmp = tempfile.mkdtemp()
os.environ["PLASBENCH_UI_HOME"] = str(Path(tmp) / "ui")
os.environ["PLASBENCH_LOCAL_SETTINGS"] = str(Path(tmp) / "local.env")
from plasbench import ui_help, ui_schema, webui  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def main():
    sch = ui_schema.schema()
    cmds = {c["name"]: c for c in sch["commands"]}
    for name in ("run", "demo", "reconstruct", "report", "intake", "scan-isolates"):
        args = cmds[name]["args"]
        empty = [a["dest"] for a in args if not (a.get("tooltip") or {}).get("summary")]
        check(f"{name}: every argument has tooltip text", args and not empty, empty)
        unhelped = [(a["dest"], c) for a in args for c in (a["choices"] or []) if not a.get("choice_help", {}).get(c)
                    and not (a["kind"] == "choice" and set(a["choices"]) == {"on", "off"} and c in ("on", "off") and a["choice_help"])]
        # tool on/off choices: both meanings are listed (plus the default meaning under the empty key)
        check(f"{name}: every choice has a meaning", not unhelped, unhelped)
        listed = [a["dest"] for a in args if a["tooltip"]["summary"].endswith("no description is recorded for it.")]
        check(f"{name}: no argument falls back to 'no description'", not listed, listed)

    run = {a["dest"]: a for a in cmds["run"]["args"]}
    check("run: the tool on/off choices explain on, off and the default", set(run["platon"]["choice_help"]) == {"on", "off", ""}, run["platon"]["choice_help"])
    check("run: a tool's tooltip names its RUN_ setting", run["platon"]["tooltip"]["setting"] == "RUN_PLATON" and "--platon" in run["platon"]["tooltip"]["flag"])
    check("run: assembler, mode, isolate_order, analysis_track, decision_profile and flye_read_type list every option",
          all(set(run[d]["choices"]) == set(run[d]["choice_help"]) for d in ("assembler", "mode", "isolate_order", "analysis_track", "decision_profile", "flye_read_type")))
    check("run: no_report_prompt says the run never stops to ask", "never stops to ask" in run["no_report_prompt"]["tooltip"]["summary"])
    check("reconstruct: --tool lists every tool", set(cmds["reconstruct"]["args"][2]["choices"]) == set(cmds["reconstruct"]["args"][2]["choice_help"]))

    print("READ_SOURCE")
    rs = sch["wizard_help"]["read_source"]
    choices = dict(rs["choices"])
    check("READ_SOURCE lists auto, sra and ena", list(choices) == ["auto", "sra", "ena"], choices)
    check("auto = SRA Toolkit then ENA; sra = SRA Toolkit only; ena = ENA only, MD5-verified",
          "ENA" in choices["auto"] and "SRA Toolkit" in choices["auto"] and "only" in choices["sra"] and "ENA only" in choices["ena"] and "MD5" in choices["ena"], choices)
    config = (ROOT / "config" / "config.sh").read_text(encoding="utf-8")
    check("config.sh still says what the tooltip says", "auto (SRA Toolkit, then ENA if prefetch fails)" in config and "ena (ENA only" in config)
    check("READ_SOURCE: default auto and the setting name are shown", rs["default"] == "auto" and rs["setting"] == "READ_SOURCE")

    print("wizard controls")
    need = ["cohort", "sample_sheet", "local_inputs", "stages", "tool_state", "study", "open_report_run", "no_report_prompt", "read_source", "max_run_download_gb",
            "warn_run_download_gb", "prefetch_fail_limit", "tool_timeout_hours", "allow_all_tools_failed", "network_retries", "ena_download_connections"]
    missing = [k for k in need if not (sch["wizard_help"].get(k) or {}).get("summary")]
    check("every wizard control has tooltip text", not missing, missing)
    check("the tool on/off/default control explains all three", {c for c, _ in sch["wizard_help"]["tool_state"]["choices"]} == {"default", "on", "off"})
    check("no_report_prompt tooltip says the run never stops to ask", "never stops to ask" in sch["wizard_help"]["no_report_prompt"]["summary"])

    print("Settings page")
    project = webui.Project(ROOT)
    rows = project.settings_resolved()
    bare = [r["key"] for r in rows if not (r.get("tooltip") or {}).get("summary")]
    check(f"every one of the {len(rows)} settings has tooltip text", rows and not bare, bare[:5])
    ones = {r["key"]: r for r in rows}
    check("READ_SOURCE on the Settings page lists its three options", [c for c, _ in ones["READ_SOURCE"]["tooltip"]["choices"]] == ["auto", "sra", "ena"])
    check("a setting's tooltip uses its config.sh comment", "Network resilience" and "retries each fetch" in ones["NETWORK_RETRIES"]["tooltip"]["summary"])
    check("the Reliability and downloads group is built from the settings config.sh defines",
          {r["key"] for r in rows if r["group"] == webui.RELIABILITY_GROUP} == {k for k in ui_help.RELIABILITY_KEYS if k in ones})

    print("page")
    html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    check("the tooltip box has role=tooltip", 'id="tipbox" role="tooltip"' in html)
    check("triggers point at it with aria-describedby", 'aria-describedby="tipbox"' in html)
    check("Escape closes it", re.search(r'e\.key === "Escape" && cur', html) is not None)
    check("hover, keyboard focus and tap all open it", all(k in html for k in ('"mouseover"', '"focusin"', 'show(b, true)')))
    check("it is a fixed floating box, so no card clips it", "#tipbox{position:fixed" in html)
    check("fieldHTML, the Settings rows and the wizard draw the info button",
          html.count("tipBtn(") >= 5 and "tipBtn(a.tooltip" in html and "tipBtn(r.tooltip" in html and 'wizTip("cohort")' in html)
    check("no external library is loaded for it", not re.search(r'<script[^>]+src=|tippy|popper', html))
    print("Add your own tool")
    uh = sch["usertool_help"]
    bare = [k for k, t in uh.items() if not t.get("summary")]
    check(f"all {len(uh)} Add-your-own-tool controls have tooltip text", uh and not bare, bare)
    html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    used = set(re.findall(r'utTip\("([a-z_0-9]+)"\)', html)) | set(re.findall(r'"(?:src|out)_[a-z_0-9]+"|"(?:task|source|outputs|upload)"', html))
    used = {u.strip('"') for u in used}
    names = set(re.findall(r'"(?:tool|install)\.\w+": "([a-z_0-9]+)"', html)) | set(re.findall(r'\w+: "(out_[a-z_0-9]+)"', html))
    missing = sorted((used | names) - set(uh))
    check("every tooltip key the page asks for exists", not missing, missing)
    check("Task: lists the three tasks, says the first is primary, and mentions native / derived / not possible",
          set(c for c, _ in uh["task"]["choices"]) == {"classification", "binning_reconstruction", "sequence_reassembly"} and "first task chosen is the primary" in uh["task"]["summary"]
          and all(w in uh["task"]["when"] for w in ("native", "derived", "not possible")))
    check("Source: the five sources are listed and the trust warning is in the tooltip", len(uh["source"]["choices"]) == 5 and "only use sources you trust" in uh["source"]["when"].lower())
    check("SHA-256: recommended, 64 hex characters, 'not pinned' is the default", "64 hexadecimal" in uh["src_sha256"]["summary"] and uh["src_sha256"]["default"] == "not pinned" and "Recommended" in uh["src_sha256"]["when"])
    check("URL: https only; kind lists auto, archive, git, file; ref is for git", "https" in uh["src_url"]["summary"] and [c for c, _ in uh["src_kind"]["choices"]] == ["auto", "archive", "git", "file"] and "git" in uh["src_ref"]["summary"])
    check("local: link and copy are explained as the manifest means them", [c for c, _ in uh["src_mode"]["choices"]] == ["link", "copy"] and "checksum" in dict(uh["src_mode"]["choices"])["copy"] and "{src}" in uh["src_path"]["summary"])
    check("upload: up to 5 MB, scripts and adapters; large tools are located, not uploaded", "5 MB" in uh["upload"]["summary"] and "located" in uh["upload"]["summary"])
    check("output: every format has a meaning, plus Detect automatically", set(c for c, _ in uh["out_format"]["choices"]) == {"contig_bins", "contig_labels", "plasmid_fasta", "fasta_dir", "adapter", "auto"})
    check("the tooltips are true to the manifest: the keys they name are real", all(uh[k]["setting"].startswith("[install]") for k in ("src_url", "src_sha256", "src_kind", "src_ref", "src_build", "src_path", "src_mode", "src_script"))
          and uh["task"]["setting"] == "[tool] task" and "candidates" in uh["out_candidates"]["setting"])
    check("the help dictionaries have a sentence for every task, format and install source", set(ui_help.TASK_HELP) >= {"classification", "binning_reconstruction", "sequence_reassembly"}
          and set(ui_help.FORMAT_HELP) >= {"contig_bins", "contig_labels", "plasmid_fasta", "fasta_dir", "adapter", "auto"} and set(ui_help.SOURCE_HELP) >= {"none", "conda", "pip", "url", "local", "script"})

    import user_tools
    check("the tooltip sentences are python/user_tools.py's own (one source, no drift)", ui_help.TASK_HELP == user_tools.TASK_HELP and ui_help.FORMAT_HELP == user_tools.FORMAT_HELP and ui_help.SOURCE_HELP == user_tools.SOURCE_HELP)

    node = shutil.which("node")
    if node:
        script = max(re.findall(r"<script[^>]*>(.*?)</script>", html, re.S), key=len)
        path = Path(tmp) / "page.js"
        path.write_text(script, encoding="utf-8")
        done = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
        check("node --check of the page script passes", done.returncode == 0, done.stderr[:300])
    else:
        print("  skip  node not found: page script not syntax-checked")
    print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL PASS")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
