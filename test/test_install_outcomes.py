#!/usr/bin/env python3
"""`plasbench install-tools NAME` reports every outcome honestly: a manual-install profile is not an error.

Before: `install-tools gplas2 --yes` exited 2, and the window printed "a command was given a wrong option or a missing file".
Now every name in `install-tools list` (and every other profile, `all`, and unknown names) resolves, with no network and no conda, to a
sensible exit code and message:  0 = an installer runs / nothing to do,  20 = manual install needed (nothing failed),
2 = unknown name or wrong option (with the nearest names),  1 = a real install failure (not reachable without a solver).
"""
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
sys.path.insert(0, ROOT)
import tool_installer_registry as reg  # noqa: E402
from plasbench.exitcodes import explain  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(("PASS" if ok else "FAIL"), name, "" if ok else f"-> {detail}")
    if not ok:
        fails.append(name)


rows = reg.read_tsv(reg.Path(ROOT, "config", "tool_installers.tsv")) + reg.read_tsv(reg.Path(ROOT, "config", "metagenomic_tool_installers.tsv"))
kinds = reg.profile_kinds(rows)
tool_profile = {r["tool"]: r["profile"] for r in rows}
names = sorted(set(kinds) | set(tool_profile) | {r["profile"] for r in rows})
manual = sorted(p for p, k in kinds.items() if k == "manual")
builtin = sorted(p for p, k in kinds.items() if k == "builtin")


def kind_of(name):
    return kinds.get(name) or kinds.get(tool_profile.get(name, ""), "automatic")


check("the registry has manual and built-in profiles to test", len(manual) >= 6 and builtin == ["baseline"], (manual, builtin))
check("the known source-only profiles are all manual",
      {"gplas2", "plasme", "plasgraph2", "plsmd", "ppr-meta", "mobilome-map", "plasbin_flow", "plasmidec"} <= set(manual), manual)

bad = []
for name in names:
    code, message = reg.resolve(name, rows)
    expected = {"manual": 20, "builtin": 10}.get(kind_of(name), 0)
    if code != expected:
        bad.append((name, code, expected))
    if code in (10, 20) and not message:
        bad.append((name, "no message"))
    if code == 20 and not ("manual" in message and "Nothing failed" in message and "plasbench install-tools plan" in message and "INSTALL.md" in message):
        bad.append((name, "manual notice lacks the steps"))
    if "wrong option or a missing file" in message:
        bad.append((name, "misleading text"))
check("every name in `install-tools list` resolves to 0 (installer), 10 (built in) or 20 (manual) with a notice", not bad, bad)

check("`all`, list, plan, validate resolve to a normal run", all(reg.resolve(n, rows)[0] == 0 for n in ("all", "list", "plan", "validate")))
code, message = reg.resolve("plasmidhuter", rows)
check("a misspelt profile exits 2 and suggests the nearest name", code == 2 and "plasmidhunter" in message, (code, message))
code, message = reg.resolve("gplas3", rows)
check("gplas3 suggests gplas2", code == 2 and "gplas2" in message, (code, message))
check("a name unlike any profile is left to conda as a package name", reg.resolve("zzqq-not-a-profile", rows)[0] == 0)
check("a tool name resolves through its profile (gplas2_mob is manual)", reg.resolve("gplas2_mob", rows)[0] == 20)

check("exit 2 reads as the generic usage text outside install-tools", "wrong option or a missing file" in explain(2))
check("exit 2 of install-tools is about the name, never a missing file",
      "missing file" not in explain(2, "install-tools") and "profile" in explain(2, "install-tools"))
check("exit 20 is 'a manual installation step is needed', not an error", "manual" in explain(20) and "nothing failed" in explain(20))
lib = open(os.path.join(ROOT, "scripts", "lib.sh"), encoding="utf-8").read()
check("lib.sh's shell translator agrees on 20", 'a manual installation step is needed' in lib)

script = open(os.path.join(ROOT, "env", "install_tools.sh"), encoding="utf-8").read()
details = script[script.index("manual_details() {"):script.index("RESOLVE_STATUS=0")]
labels = set(re.findall(r"^\s+([a-z0-9_-]+)\)\s*$", details, re.M))
check("every profile with manual commands in install_tools.sh is a manual profile in the registry", labels <= set(manual), (labels, manual))
flat = {p for item in re.findall(r"^ ([a-z0-9_|-]+)\)", script, re.M) for p in item.split("|")}
check("every script-only profile has a case branch", set(reg.SCRIPT_PROFILES) <= flat, set(reg.SCRIPT_PROFILES) - flat)

from plasbench import webui  # noqa: E402
state = webui.Jobs.display_state(object(), {"state": "failed", "exit": 20, "argv": ["install-tools", "gplas2", "--yes"], "id": "x"})
check("the window's job state for install-tools exit 20 is manual_step", state == "manual_step", state)
state = webui.Jobs.display_state(object(), {"state": "failed", "exit": 20, "argv": ["run"], "id": "x"})
check("exit 20 of another command stays failed", state == "failed", state)
html = open(os.path.join(ROOT, "plasbench", "data", "ui.html"), encoding="utf-8").read()
check("ui.html words and styles the manual_step state", 'manual_step:"Manual step needed"' in html and "#cstate.manual_step" in html)

# The real script, no network: PLASBENCH_INSTALL_DRY_RUN stops before any solver.
bash = shutil.which("bash")
probe = subprocess.run([bash, "-c", "command -v python3"], capture_output=True, text=True) if bash else None
if bash and probe.returncode == 0 and os.name != "nt":
    def run(*args, dry=True):
        env = dict(os.environ, PLASBENCH_INSTALL_DRY_RUN="1" if dry else "0")
        p = subprocess.run([bash, "env/install_tools.sh", *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        return p.returncode, p.stdout + p.stderr
    bad = []
    for name in sorted(set(names) | set(reg.SCRIPT_PROFILES)):
        code, out = run("--yes", name)
        want = 20 if kind_of(name) == "manual" else 0
        if code != want or "wrong option or a missing file" in out or not out.strip():
            bad.append((name, code, want))
    check("env/install_tools.sh --yes NAME gives the right exit code and text for every profile (dry run, no network)", not bad, bad)
    code, out = run("--yes", "gplas2", dry=False)
    check("gplas2 --yes exits 20 with the manual-install notice (not 2, not an error)",
          code == 20 and "needs a manual install" in out and "Nothing failed" in out, (code, out[-300:]))
    code, out = run("plasmidhuter", dry=False)
    check("a misspelt profile exits 2 and names plasmidhunter", code == 2 and "plasmidhunter" in out, (code, out))
else:
    print("SKIP: the shell dry run needs a POSIX bash with python3")

print("\nFAILED:" if fails else "\nAll install-outcome checks passed.", *fails)
sys.exit(1 if fails else 0)
