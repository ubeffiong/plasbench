#!/usr/bin/env python3
"""The installing toast: which jobs are installs and what they are called (plasbench/jobs_labels.py), the additive fields of /api/jobs (webui.Jobs.list), the page's pure state and
markup functions (node, test/install_toast_node.js) and the static contract of the markup (aria-live region, buttons, tooltips, no browser dialogs, no second poller).

The real-browser check is test/test_install_toast_browser.py (opt-in: PLASBENCH_BROWSER_TESTS=1). Standard library only (node is optional: skipped when absent).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
tmp = tempfile.mkdtemp()
os.environ["PLASBENCH_UI_HOME"] = str(Path(tmp) / "ui")
os.environ["HOME"] = os.environ["USERPROFILE"] = str(Path(tmp) / "home")
from plasbench import jobs_labels, ui_help, webui  # noqa: E402

HTML = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


# every start site of the window, with the argv it sends (ui.html) and what the label must be; (argv, is_install, label, tools)
TABLE = [
    (["install-tools", "core", "--yes"], True, "Installing the core tools…", ["core"]),                                   # Setup: Install a tool profile
    (["install-tools", "plsmd", "--yes"], True, "Installing plsmd…", ["plsmd"]),                                          # Tools page: Install / Update on one row, Fix on the Setup list
    (["install-tools", "plsmd,gplas2,genomad", "--yes"], True, "Installing 3 tools…", ["plsmd", "gplas2", "genomad"]),     # Tools page: Install all enabled tools
    (["install-tools", "docker", "--yes"], True, "Installing Docker…", ["docker"]),                                       # Install Docker (dialog), profile "docker"
    (["install-tools", "docker"], True, "Installing Docker…", ["docker"]),                                                # Environment card: Install Docker first
    (["install-tools", "mytool", "--yes"], True, "Installing mytool…", ["mytool"]),                                       # Add your own tool: Save & install
    (["install-tools", "--env", "plasbench", "genomad", "--yes"], True, "Installing genomad…", ["genomad"]),              # an option before the profile
    (["install-tools", "plsmd"], True, "Installing plsmd…", ["plsmd"]),                                                   # Show steps (ends as Manual step needed)
    (["install-tools"], True, "Installing the core tools…", ["core"]),                                                    # the default profile
    (["install-tools", "plan"], False, "", []), (["install-tools", "list"], False, "", []), (["install-tools", "validate"], False, "", []),
    (["install-tools", "locked"], False, "", []), (["install-tools", "core", "--dry-run"], False, "", []),
    (["tools", "install", "mytool"], True, "Installing mytool…", ["mytool"]),
    (["tools", "list"], False, "", []), (["tools", "validate"], False, "", []),
    (["install-conda", "--yes"], True, "Installing conda…", ["conda"]),
    (["install-conda", "--prefix", "/opt/mf", "--yes"], True, "Installing conda…", ["conda"]),
    (["runtime", "pull", "--yes"], True, "Pulling the PlasBench image…", ["image"]),                                      # Environment card: Pull the image
    (["runtime", "build", "--yes"], True, "Building the PlasBench image…", ["image"]),
    (["runtime", "build", "--yes", "--rebuild"], True, "Building the PlasBench image…", ["image"]),
    (["runtime", "status"], False, "", []), (["runtime", "use", "docker"], False, "", []), (["runtime", "check"], False, "", []),
    (["check", "--yes"], True, "Installing missing tools and databases…", []),                                            # Make everything ready; Install tool databases; Check & fix all
    (["check"], False, "", []),
    (["upgrade", "--yes"], True, "Updating PlasBench…", ["plasbench"]),
    (["run", "--study", "s1"], False, "", []), (["demo", "--no-report-prompt"], False, "", []), (["test"], False, "", []), (["report", "--results-dir", "results"], False, "", []),
]


def main():
    # ---- 1. the predicate and the labels (one place) -------------------------------------------------------------------------------------------------
    bad = []
    for argv, want, label, tools in TABLE:
        got = jobs_labels.describe(argv)
        if got["is_install"] != want or got["label"] != label or got["install_tools"] != tools:
            bad.append((argv, got))
    check(f"describe(): {len(TABLE)} real argvs give the expected is_install, label and tools", not bad, bad[:3])
    check("a git job or an empty argv is never an install", not jobs_labels.describe(["install-tools", "core"], "git")["is_install"] and not jobs_labels.describe([])["is_install"])
    check("every install_kind is in JOB_KINDS_INSTALL", {jobs_labels.describe(a)["install_kind"] for a, w, _, _ in TABLE if w} <= set(jobs_labels.JOB_KINDS_INSTALL))
    check("last_line: the last printed line, ANSI removed, truncated, the command line skipped", jobs_labels.last_line("$ plasbench install-tools docker\nstep 1\n\x1b[32mDownloading 42%\x1b[0m\n") == "Downloading 42%"
          and len(jobs_labels.last_line("x" * 400)) == jobs_labels.LINE_MAX and jobs_labels.last_line("") == "")
    check("last_line for a failure picks the line that reads like a reason", jobs_labels.last_line("a\nERROR: could not resolve gplas2\n[exit 1]\n", failed=True) == "ERROR: could not resolve gplas2")
    check("last_line skips the runner wrapper line when the tool said something", jobs_labels.last_line("ERROR: no space left" + chr(10) + "[PlasBench] ERROR: the command stopped (exit 1)." + chr(10), failed=True) == "ERROR: no space left"
          and jobs_labels.last_line("[PlasBench] ERROR: the command stopped (exit 1).", failed=True).startswith("[PlasBench]"))
    check("installed_version reads 'Docker version 27.0.1' and nothing else", jobs_labels.installed_version("ok\nDocker version 27.0.1, build abc\n") == "27.0.1" and jobs_labels.installed_version("done\n") == "")

    # ---- 2. the jobs payload: additive fields, old fields unchanged -----------------------------------------------------------------------------------
    jobs = webui.Jobs(webui.Project(ROOT))
    now = time.time()

    def inject(job_id, argv, state, exit_code=None, started=None, ended=None, log="", kind="plasbench"):
        job = {"id": job_id, "label": "L " + job_id, "argv": argv, "command": "plasbench " + " ".join(argv), "env": {}, "kind": kind, "state": state, "started": started or now - 60,
               "ended": ended, "exit": exit_code, "pid": 0, "results": ""}
        Path(jobs._paths(job_id)["log"]).write_text(log, encoding="utf-8")
        jobs.jobs[job_id] = job
        return job

    inject("t-run", ["install-tools", "plsmd", "--yes"], "running", log="$ plasbench install-tools plsmd --yes\nDownloading plsmd 1.2.3 (40%)\n")
    inject("t-done", ["install-tools", "docker", "--yes"], "done", 0, ended=now - 5, log="starting\nDocker version 27.0.1, build abc\n")
    inject("t-fail", ["install-tools", "gplas2", "--yes"], "failed", 1, ended=now - 5, log="starting\nERROR: conda could not solve gplas2\n[exit 1]\n")
    inject("t-wait", ["install-tools", "docker", "--yes"], "failed", 20, ended=now - 5, log="steps\n")
    inject("t-old", ["install-tools", "core", "--yes"], "failed", 1, ended=now - 3 * 86400, log="ERROR: old\n")
    inject("t-demo", ["demo"], "running", log="stage 1\n")
    inject("t-git", [], "done", 0, ended=now - 5, kind="git")
    by = {j["id"]: j for j in jobs.list()}
    run = by["t-run"]
    check("an install that is going has the four additive fields and its phase line", run["is_install"] and run["install_label"] == "Installing plsmd…" and run["install_tools"] == ["plsmd"]
          and run["install_kind"] == "install-tools" and run["last_line"] == "Downloading plsmd 1.2.3 (40%)" and run.get("installed_version", "") == "", run)
    check("a done install carries the version it reported", by["t-done"]["installed_version"] == "27.0.1" and by["t-done"]["display_state"] == "done")
    check("a failed install carries the one-line reason", by["t-fail"]["last_line"] == "ERROR: conda could not solve gplas2", by["t-fail"].get("last_line"))
    check("the Docker exit-20 handoff is an install in the waiting_for_you display state", by["t-wait"]["is_install"] and by["t-wait"]["display_state"] == "waiting_for_you")
    check("an old finished install has the label fields but no log tail read", by["t-old"]["is_install"] and "last_line" not in by["t-old"])
    check("a benchmark, a git job and an old-format job are not installs and have no tail fields", not by["t-demo"]["is_install"] and "last_line" not in by["t-demo"] and not by["t-git"]["is_install"])
    check("the old fields are unchanged (id, label, argv, command, state, display_state, started, ended, exit, kind)", all(k in by["t-run"] for k in ("id", "label", "argv", "command", "env", "state", "display_state", "started", "ended", "exit", "kind", "results")))
    # the stored job record is not changed by listing
    check("listing does not write the fields into the stored job", "is_install" not in jobs.jobs["t-run"])
    check("install_fields is what start() adds to its response (a plan is not an install)", jobs.install_fields({"argv": ["install-tools", "plan"], "kind": "plasbench", "state": "running", "id": "x"})["is_install"] is False)

    # ---- 3. the page: static contract ------------------------------------------------------------------------------------------------------------------
    a, b = HTML.index("/* ==INSTALL-TOAST-BEGIN=="), HTML.index("/* ==INSTALL-TOAST-END== */")
    block = HTML[a:b]
    check("a region with aria-live=polite, a label and aria-busy lives in the toast area", re.search(r'<div id="toasts" aria-live="polite"><div id="insttoast" class="insttoast" role="region" aria-label="Installations" aria-live="polite" aria-busy="false" hidden>', HTML) is not None)
    check("the top bar has a chip with a spinner and a count, and a tooltip", 'id="instchip"' in HTML and 'id="instchiptx"' in HTML and 'data-tipid="install_chip"' in HTML and 'aria-controls="insttoast"' in HTML)
    check("View log, Cancel, Hide, Re-check, Dismiss are real buttons", all(f'data-it="{k}"' in block for k in ("view", "cancel", "hide", "recheck", "dismiss", "expand", "jobs")) and "<button" in block)
    check("Cancel goes through the designed confirm dialog (askConfirm), danger style", "await askConfirm({title: \"Cancel this installation?\", danger: true" in block)
    check("no browser alert / confirm / prompt in the block", not re.search(r"(?<![\w.$])(?:alert|confirm|prompt)\s*\(", block))
    check("Escape does not dismiss (the block has no keydown handler)", "keydown" not in block and "Escape" not in block)
    check("no second poller: the block's interval only re-renders; the job list comes from refreshJobs", block.count("setInterval(") == 1 and "api(\"jobs\")" not in block and "itOnJobs();" in HTML.split("async function refreshJobs()")[1].split("const WARN_EXPLAIN")[0])
    check("storage is in try/catch", "try { const v = JSON.parse(localStorage.getItem(k))" in block and "try { localStorage.setItem(k, JSON.stringify(v)); } catch {}" in block)
    check("the optimistic toast: startJob and the Docker image routes show it at once and clear it in finally", HTML.count("itPendClear()") >= 4 and "itPend(label || cmdText(argv))" in HTML)
    check("keyed rendering: the DOM changes only when the markup does, and focus is put back", "if (el._html !== html)" in block and "t.focus()" in block)
    check("phone width: a full-width bar with 40 px targets; dark theme through the colour variables", "@media (max-width:640px){#toasts{left:8px;right:8px}.insttoast{width:100%" in HTML and "min-height:40px" in HTML.split("==INSTALL-TOAST-CSS==")[1].split("==INSTALL-TOAST-CSS-END==")[0]
          and "var(--surface)" in HTML.split("==INSTALL-TOAST-CSS==")[1])
    check("reduced motion is honoured", "prefers-reduced-motion:reduce){.it-card .rt-spin" in HTML)
    check("the tooltips the markup uses exist in ui_help.PAGE", {"install_toast", "install_chip"} <= set(ui_help.PAGE) and all(ui_help.PAGE[k]["title"] and ui_help.PAGE[k]["summary"] for k in ("install_toast", "install_chip")))
    check("the guide, the FAQ and the changelog describe it", "installing toast" in (ROOT / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8").lower() and "How do I know an install is still running?" in (ROOT / "FAQ.md").read_text(encoding="utf-8")
          and "installing toast" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").lower())

    # ---- 4. the pure functions in node --------------------------------------------------------------------------------------------------------------
    node = shutil.which("node")
    if node:
        table_path = Path(tmp) / "argv.json"
        table_path.write_text(json.dumps([[argv, want] for argv, want, _, _ in TABLE]), encoding="utf-8")
        done = subprocess.run([node, str(ROOT / "test" / "install_toast_node.js"), str(ROOT / "plasbench" / "data" / "ui.html"), str(table_path)], capture_output=True, text=True, timeout=120)
        print(done.stdout.rstrip())
        check("node: the pure state and markup functions pass", done.returncode == 0, done.stderr[-400:])
    else:
        print("  skip  node not found")
    print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL INSTALL TOAST TESTS PASSED")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
