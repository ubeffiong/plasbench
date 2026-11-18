#!/usr/bin/env python3
"""The optional MultiQC companion (python/run_multiqc.py, MULTIQC_REPORT), the shared note, the QC panel's MultiQC states and the wiring.

No real MultiQC is needed: a fake `multiqc` executable on PATH stands in for the call. The step must never fail a run, must skip cleanly when multiqc is
absent, must record a failure as a warning event, and the panel must show a link when the report exists and say how to get it when it does not.
"""
import json
import os
import stat
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
import multiqc_note  # noqa: E402
import report_readqc_panel as qp  # noqa: E402
import run_multiqc as rm  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(f"  {'ok  ' if good else 'FAIL'}  {label}{'' if good else ' -> ' + str(detail)[:300]}")
    ok &= bool(good)


def events(results):
    path = os.path.join(results, "run_events.jsonl")
    return [json.loads(line) for line in open(path, encoding="utf-8")] if os.path.exists(path) else []


def make_run(tmp):
    data, results = os.path.join(tmp, "data"), os.path.join(tmp, "results")
    for s in ("s1", "s2"):
        os.makedirs(os.path.join(data, s))
        open(os.path.join(data, s, "fastp.json"), "w").write("{}")
    os.makedirs(os.path.join(data, "s1", "quast_out"))
    open(os.path.join(data, "s1", "quast_out", "report.tsv"), "w").write("Assembly\tx\n")
    os.makedirs(results)
    return data, results


print("setting parsing")
check("auto, on and off are kept; blank is auto", [rm.parse_mode(v)[0] for v in ("auto", "on", "off", "", "  AUTO ")] == ["auto", "on", "off", "auto", "auto"])
check("1/true/yes mean on; 0/false/no mean off", [rm.parse_mode(v)[0] for v in ("1", "true", "Yes", "0", "False", "no")] == ["on", "on", "on", "off", "off", "off"])
mode, problem = rm.parse_mode("sometimes")
check("anything else is auto, with the problem named", mode == "auto" and "sometimes" in problem and "auto" in problem)
check("the timeout parses, and a bad or non-positive value falls back to 600", [rm.parse_timeout(v) for v in ("30", "x", "0", "-5", None)] == [30, 600, 600, 600, 600])
cfg = open(os.path.join(ROOT, "config", "config.sh"), encoding="utf-8").read()
check("config.sh defines MULTIQC_REPORT (default auto) and MULTIQC_TIMEOUT_SECONDS, with an explanation", 'MULTIQC_REPORT="${MULTIQC_REPORT:-auto}"' in cfg
      and 'MULTIQC_TIMEOUT_SECONDS="${MULTIQC_TIMEOUT_SECONDS:-600}"' in cfg and "NOT made with" in cfg)

print("inputs")
with tempfile.TemporaryDirectory() as tmp:
    data, results = make_run(tmp)
    found = rm.find_inputs(data, results)
    check("every fastp.json and each QUAST folder is named, and no read file is", len(found) == 3 and sum(f.endswith("fastp.json") for f in found) == 2
          and any(f.endswith("quast_out") for f in found))

print("skipped cleanly")
with tempfile.TemporaryDirectory() as tmp:
    data, results = make_run(tmp)
    st = rm.run(data, results, "auto", which=lambda _n: None)
    check("auto with multiqc absent skips, writes nothing and raises no warning", st["state"] == "absent" and not os.path.exists(os.path.join(results, "multiqc")) and events(results) == [])
    st = rm.run(data, results, "off", which=lambda _n: "/x/multiqc")
    check("off never runs it", st["state"] == "off" and not os.path.exists(os.path.join(results, "multiqc")))
    st = rm.run(data, results, "on", which=lambda _n: None)
    ev = events(results)
    check("on with multiqc absent is a warning event and a note, never an error", st["state"] == "absent" and ev and ev[-1]["event"] == "warning" and "install-tools multiqc" in ev[-1]["message"]
          and json.load(open(os.path.join(results, "multiqc", "multiqc_run.json")))["state"] == "absent")
    st = rm.run(data, results, "auto", which=lambda _n: "/x/multiqc")
    empty = os.path.join(tmp, "empty")
    os.makedirs(os.path.join(empty, "r"))
    st2 = rm.run(os.path.join(empty, "d"), os.path.join(empty, "r"), "auto", which=lambda _n: "/x/multiqc", runner=lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
    check("with nothing to read it does not call multiqc and says so", st2["state"] == "no_inputs" and "nothing for MultiQC to read" in st2["note"])

print("the call, with a stand-in runner")
with tempfile.TemporaryDirectory() as tmp:
    data, results = make_run(tmp)
    calls = []

    def runner(cmd, **kw):
        calls.append((cmd, kw))
        if "--version" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "multiqc, version 1.25.2\n", "")
        out = cmd[cmd.index("-o") + 1]
        open(os.path.join(out, "multiqc_report.html"), "w").write("<html></html>")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    st = rm.run(data, results, "auto", 77, which=lambda _n: "/x/multiqc", runner=runner)
    cmd, kw = calls[-1]
    check("it runs multiqc once with -f, the output folder, the report name and the explicit inputs, under the timeout", st["state"] == "ok" and kw["timeout"] == 77
          and "-f" in cmd and cmd[cmd.index("-o") + 1] == os.path.join(results, "multiqc") and "multiqc_report.html" in cmd and sum(c.endswith("fastp.json") for c in cmd) == 2)
    check("the version, input count and link are recorded", st["version"].endswith("1.25.2") and st["inputs"] == 3 and st["report"] == "multiqc/multiqc_report.html")
    check("start and end events are written", [e["event"] for e in events(results)] == ["command_start", "command_end"])

    def failing(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", "boom: bad module\n") if "--version" not in cmd else subprocess.CompletedProcess(cmd, 0, "v", "")

    st = rm.run(data, results, "auto", which=lambda _n: "/x/multiqc", runner=failing)
    ev = events(results)
    check("a failing multiqc is a warning event and a note, state failed, not an exception", st["state"] == "failed" and "boom" in st["note"] and ev[-1]["event"] == "warning" and ev[-1]["component"] == "multiqc")

    def slow(cmd, **kw):
        if "--version" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "v", "")
        raise subprocess.TimeoutExpired(cmd, 1)

    st = rm.run(data, results, "auto", 1, which=lambda _n: "/x/multiqc", runner=slow)
    check("a timeout is a warning that names MULTIQC_TIMEOUT_SECONDS", st["state"] == "failed" and "MULTIQC_TIMEOUT_SECONDS" in st["note"])

    def broken(cmd, **kw):
        raise OSError("exec format error")

    st = rm.run(data, results, "auto", which=lambda _n: "/x/multiqc", runner=broken)
    check("an executable that cannot start is a warning too", st["state"] == "failed" and "exec format" in st["note"])

print("a fake multiqc executable on PATH, through the command line")
with tempfile.TemporaryDirectory() as tmp:
    data, results = make_run(tmp)
    bindir = os.path.join(tmp, "bin")
    os.makedirs(bindir)
    fake = os.path.join(bindir, "fake_multiqc.py")
    open(fake, "w").write("import sys, os\nif '--version' in sys.argv:\n    print('multiqc, version 9.9.9'); sys.exit(0)\n"
                          "out = sys.argv[sys.argv.index('-o') + 1]\nos.makedirs(out, exist_ok=True)\nopen(os.path.join(out, 'multiqc_report.html'), 'w').write('<html>fake</html>')\n")
    if os.name == "nt":
        open(os.path.join(bindir, "multiqc.bat"), "w").write(f'@"{sys.executable}" "{fake}" %*\r\n')
    else:
        wrapper = os.path.join(bindir, "multiqc")
        open(wrapper, "w").write(f'#!/bin/sh\nexec "{sys.executable}" "{fake}" "$@"\n')
        os.chmod(wrapper, os.stat(wrapper).st_mode | stat.S_IEXEC)
    env = dict(os.environ, PATH=bindir + os.pathsep + os.environ.get("PATH", ""), MULTIQC_REPORT="auto")
    done = subprocess.run([sys.executable, os.path.join(ROOT, "python", "run_multiqc.py"), "--data-dir", data, "--results-dir", results], capture_output=True, text=True, env=env)
    report = os.path.join(results, "multiqc", "multiqc_report.html")
    check("the command line runs the fake multiqc, writes the report and exits 0", done.returncode == 0 and os.path.isfile(report), done.stdout + done.stderr)
    info = qp.multiqc_status(results)
    check("the panel reads it as ok, with the version", info["state"] == "ok" and info["version"].endswith("9.9.9"), info)
    env["MULTIQC_REPORT"] = "off"
    os.remove(report)
    done = subprocess.run([sys.executable, os.path.join(ROOT, "python", "run_multiqc.py"), "--data-dir", data, "--results-dir", results], capture_output=True, text=True, env=env)
    check("off through the environment skips it, exit 0", done.returncode == 0 and not os.path.exists(report))
    done = subprocess.run([sys.executable, os.path.join(ROOT, "python", "run_multiqc.py"), "--data-dir", os.path.join(tmp, "nowhere"), "--results-dir", os.path.join(tmp, "nowhere2"),
                           "--mode", "on", "--timeout", "abc"], capture_output=True, text=True, env=dict(os.environ, PATH=os.path.dirname(sys.executable)))
    check("even on a missing folder and a bad timeout it exits 0", done.returncode == 0, done.stderr)

print("the panel")
with tempfile.TemporaryDirectory() as tmp:
    data, results = make_run(tmp)
    box = qp.note_box(results)
    check("the note box is a collapsible details with the shared text", box.startswith("<details class='qp-note'") and multiqc_note.TITLE in box
          and all(h in box for h, _b in multiqc_note.POINTS))
    check("with no MultiQC report it says so and gives the install command", "not available for this run" in box and "plasbench install-tools multiqc" in box and "<a href" not in box)
    os.makedirs(os.path.join(results, "multiqc"))
    open(os.path.join(results, "multiqc", "multiqc_report.html"), "w").write("x")
    json.dump({"state": "ok", "version": "multiqc, version 1.25.2", "inputs": 3}, open(os.path.join(results, "multiqc", "multiqc_run.json"), "w"))
    box = qp.note_box(results)
    check("with a report it links to it, relatively, names the version and does not embed it", "<a href='multiqc/multiqc_report.html'>Full MultiQC report</a>" in box and "1.25.2" in box
          and "<iframe" not in box and "not embedded" in box)
    far = qp.note_box(results, report_dir=os.path.join(tmp, "a", "b", "c", "d"))
    check("a report far from the page's folder is named, not linked (the file tree's rule)", "<a href" not in far and "multiqc/multiqc_report.html" in far and "not linked" in far)
    json.dump({"state": "failed", "note": "multiqc failed (exit 1): boom"}, open(os.path.join(results, "multiqc", "multiqc_run.json"), "w"))
    os.remove(os.path.join(results, "multiqc", "multiqc_report.html"))
    box = qp.note_box(results)
    check("a failure is a note in the panel and says the built-in panel is unaffected", "MultiQC was tried and failed" in box and "boom" in box and "not affected" in box)
    page = qp.build([{"sample": "a", "qc_status": "PASS", "integrity": "ok", "read_pairs_total": "2000000", "mean_quality": "35", "policy_status": "frozen", "thresholds_sha": "x"}], results, False)
    check("the note is at the top of the built panel, before the reviewer box", page.index("qp-note") < page.index("What the reviewer asked"))
    check("and in the not-measured state", "qp-note" in qp.not_measured(results))
    check("the note covers what the built-in panel is, what MultiQC is, and what to do if they differ", all(w in multiqc_note.text() for w in ("thresholds", "offline", "separate install", "per-base quality",
                                                                                                                                       "knows nothing", "same underlying files", "differ")))
    check("the closed details open in print through the report's print preparation (a details element)", "<details class='qp-note'" in box)

print("help text, the window and the wiring")
sys.path.insert(0, ROOT)
from plasbench import ui_help  # noqa: E402

help_ = ui_help.SETTINGS["MULTIQC_REPORT"]
check("the MULTIQC_REPORT setting help carries the shared note and its three choices", multiqc_note.text() in help_["summary"] and set(help_["choices"]) == {"auto", "on", "off"})
check("the window's QC area note is the same text", ui_help.REPORT_NOTES["qc"]["text"] == multiqc_note.text() and ui_help.REPORT_NOTES["qc"]["title"] == multiqc_note.TITLE)
row = {"key": "MULTIQC_REPORT", "comment": "", "default": "auto"}
check("the Settings page tooltip for it is that help", multiqc_note.text() in ui_help.setting_tooltip(row)["summary"])
inst = open(os.path.join(ROOT, "env", "install_tools.sh"), encoding="utf-8").read()
check("env/install_tools.sh has an isolated, pinned multiqc profile (not in the `all` loop: optional)", "install_isolated multiqc MultiQC" in inst and "multiqc=1.25.2" in inst
      and "plascope quast utilities" in inst and " multiqc utilities" not in inst and "quast multiqc" not in inst)
setup = open(os.path.join(ROOT, "scripts", "00_setup.sh"), encoding="utf-8").read()
check("00_setup.sh checks multiqc as optional (required=0: warns, never fails)", "check_tool multiqc multiqc 0" in setup)
agg = open(os.path.join(ROOT, "scripts", "06_aggregate.sh"), encoding="utf-8").read()
check("stage 6 runs the step before the report is built, and a stop of it only warns", 0 < agg.index("run_multiqc.py") < agg.index("build_html_report.py") and "|| warn" in agg.split("run_multiqc.py")[1][:200])
wiring = open(os.path.join(ROOT, "test", "test_install_wiring.py"), encoding="utf-8").read()
check("test_install_wiring declares multiqc (profile and check routes)", '"multiqc": ("multiqc", {"profile", "check"})' in wiring)

print()
if not ok:
    print("MULTIQC COMPANION TESTS FAILED")
    sys.exit(1)
print("ALL MULTIQC COMPANION TESTS PASSED")
