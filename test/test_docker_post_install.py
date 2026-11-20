#!/usr/bin/env python3
"""Docker after the install (python/docker_setup.py): the Windows-side states that tell "installed but not started" from "not installed", read-only evidence from a FAKE
Windows tree under /mnt/c (Docker Desktop.exe, docker.exe, tasklist, winget list, settings-store.json) and recorded outputs, the sequence "winget succeeds, then detect"
(right sentence, exit 20, no 90 s wait: injectable clock and sleep), --start (argv as a list, hostile paths, polling, the licence-pending message), the settings-file shapes,
the plan for an already installed Desktop, and the window's checklist and buttons. Nothing here starts or changes anything on this computer."""
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT))
import docker_setup as ds  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{str(detail)[:600]}]"))
    if not ok:
        FAILED.append(name)


# ---- recorded outputs
STUB_MSG = "The command 'docker' could not be found in this WSL 2 distro. We recommend to activate the WSL integration in Docker Desktop settings.\n\nFor details about using Docker Desktop with WSL 2, visit:\n"
TASKLIST_RUNNING = '"Docker Desktop.exe","12345","Console","1","245,112 K"\r\n'
TASKLIST_NONE = "INFO: No tasks are running which match the specified criteria.\r\n"
WINGET_LIST = ("Name           Id                   Version Source\r\n-------------------------------------------------\r\nDocker Desktop Docker.DockerDesktop 4.99.0  winget\r\n")
WINGET_NONE = "No installed package found matching input criteria.\r\n"
WIN_INFO_DOWN = (1, "Client:\n Version:    28.0.1\n", "failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine; check if the path is correct and if the daemon is running: "
                 "open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.")
WIN_INFO_OK = (0, "Client:\n Version:    28.0.1\nServer:\n Server Version: 28.0.1\n Operating System: Docker Desktop\n", "")
LINUX_INFO_OK = (0, "Client:\n Version: 28.0.1\nServer:\n Server Version: 28.0.1\n", "")
SETTINGS_OFF = json.dumps({"IntegratedWslDistros": ["Debian"], "EnableIntegrationWithDefaultWslDistro": False, "UseWslEngine": True, "LicenseTermsVersion": 2, "AutoStart": False})
SETTINGS_ON = json.dumps({"IntegratedWslDistros": ["Ubuntu-24.04", "Debian"], "UseWslEngine": True, "LicenseTermsVersion": 2})

BASE = "/mnt/c/Program Files/Docker/Docker"
DESK, CLI = BASE + "/Docker Desktop.exe", BASE + "/resources/bin/docker.exe"
WINGET = "/mnt/c/Users/me/AppData/Local/Microsoft/WindowsApps/winget.exe"
PWSH = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
TASKLIST = "/mnt/c/Windows/System32/tasklist.exe"
SETTINGS = "/mnt/c/Users/me/AppData/Roaming/Docker/settings-store.json"
WSL = {"kind": "wsl2", "wsl": True, "interop": True, "winget": WINGET, "powershell": PWSH, "desktop_installed": False, "brew": None, "package_manager": "apt", "distro": "Ubuntu 24.04",
       "distro_id": "ubuntu", "systemd": True, "wsl_distro": "Ubuntu-24.04", "container": False}
NI = {"state": "not_installed", "detail": "docker was not found", "version": ""}


class Fake:
    """A fake computer: which files exist, what each program prints; every call is recorded (argv lists only)."""

    def __init__(self, files=(), tasklist=TASKLIST_NONE, win_info=WIN_INFO_DOWN, linux=None, winget_list=WINGET_LIST, settings=None, start_rc=0, uri_rc=0, install=None):
        self.files, self.calls = set(files), []
        self.tasklist, self.win_info, self.linux, self.winget_list, self.settings = tasklist, win_info, linux, winget_list, settings
        self.start_rc, self.uri_rc, self.install = start_rc, uri_rc, install
        self.texts = {SETTINGS: settings} if settings is not None else {}
        if settings is not None:
            self.files.add(SETTINGS)

    def exists(self, path):
        return path in self.files

    def which(self, name):
        return {"tasklist.exe": TASKLIST if TASKLIST in self.files else None}.get(name)

    def read(self, path):
        return self.texts.get(path)

    def glob(self, pattern):
        return ["/mnt/c/Users/me/AppData/Roaming/Docker"] if "Roaming/Docker" in pattern and SETTINGS in self.texts else []

    def run(self, argv, timeout=20):
        self.calls.append(list(argv))
        a = list(argv)
        exe = a[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
        if exe == "docker":
            return self.linux(a) if self.linux else None
        if exe == "docker.exe":
            return self.win_info if a[1:2] == ["info"] else (0, "Docker version 28.0.1, build abc\n", "")
        if exe == "tasklist.exe":
            return (0, self.tasklist, "")
        if exe == "winget.exe":
            if a[1:2] == ["install"]:
                return self.install(self) if self.install else (0, "Successfully installed\n", "")
            return (0, self.winget_list, "") if self.winget_list else (1, WINGET_NONE, "")
        if exe == "powershell.exe":
            joined = " ".join(a)
            if "Start-Process" in joined and "docker-desktop://" in joined:
                return (self.uri_rc, "", "" if self.uri_rc == 0 else "No application is associated")
            if "Start-Process" in joined:
                return (self.start_rc, "", "" if self.start_rc == 0 else "Start-Process : This command cannot be run due to the error: Access is denied.")
            return (0, "0\n", "")
        return None

    def probe(self, deep=False, environment=WSL):
        return ds.probe(environment, run=self.run, which=self.which, exists=self.exists, env={}, read=self.read, globber=self.glob, deep=deep)


INSTALLED = (DESK, CLI, TASKLIST)

# ---- 1. the states, from the fake Windows tree
f = Fake()
p = f.probe()
check("nothing found anywhere: truly 'not_installed' (the only place that wording is left)", p["state"] == "not_installed" and p["chip"] == "Not installed" and p["action"] == "install", p)
check("nothing found: no Windows process was asked (no tasklist, no docker.exe)", not any(c[0].endswith(("tasklist.exe", "docker.exe")) for c in f.calls), f.calls)

f = Fake(INSTALLED)
p = f.probe()
check("Docker Desktop installed on Windows, not running (the user's case): installed_windows_not_running", p["state"] == "installed_windows_not_running", p)
check("... never 'Not installed': chip 'Docker Desktop not started', action 'start'", p["chip"] == "Docker Desktop not started" and p["action"] == "start" and "Not installed" not in json.dumps(p), p["chip"])
check("... evidence: Docker Desktop.exe, docker.exe, running False", p["evidence"]["desktop_exe"] == DESK and p["evidence"]["docker_exe"] == CLI and p["evidence"]["running"] is False, p["evidence"])
check("... the checklist: installed ok, running pending, engine and integration blocked", [s["status"] for s in p["stages"]] == ["ok", "pending", "blocked", "blocked"], p["stages"])
check("... the diagnosis says installed-but-not-running and offers Start", "installed on Windows" in ds.diagnose(p, WSL)["title"] and "not running" in ds.diagnose(p, WSL)["title"] and "--start" in " ".join(ds.diagnose(p, WSL)["steps"]))
check("only read-only programs were run (tasklist, docker.exe info, docker --version): nothing started, nothing installed", all(c[0].endswith(("tasklist.exe", "docker.exe", "docker")) for c in f.calls), f.calls)

f = Fake(INSTALLED, tasklist=TASKLIST_RUNNING)
p = f.probe()
check("Docker Desktop.exe running but docker.exe info fails: desktop_running_engine_down", p["state"] == "desktop_running_engine_down" and p["chip"] == "Docker Desktop starting", p)
check("... checklist: installed, running ok, engine pending", [s["status"] for s in p["stages"]] == ["ok", "ok", "pending", "blocked"], p["stages"])
check("... the diagnosis names the licence window that may be waiting", "licence" in " ".join(ds.diagnose(p, WSL)["steps"]).lower() and "accept" in " ".join(ds.diagnose(p, WSL)["steps"]).lower())

f = Fake(INSTALLED, tasklist=TASKLIST_RUNNING, win_info=WIN_INFO_OK, settings=SETTINGS_OFF)
p = f.probe()
check("docker.exe info works on Windows, `docker` missing in the distro: engine_up_wsl_integration_off", p["state"] == "engine_up_wsl_integration_off" and p["action"] == "integration", p)
check("... settings-store.json says it precisely: integration is off for Ubuntu-24.04 (lists Debian)", "off for Ubuntu-24.04" in p["detail"] and "Debian" in p["detail"] and p["evidence"]["integration"] == "off", p["detail"])
check("... the evidence carries the settings path and the licence terms record", p["evidence"]["settings_path"] == SETTINGS and p["evidence"]["license_terms"] == 2, p["evidence"])
check("... checklist: three ticks, integration pending", [s["status"] for s in p["stages"]] == ["ok", "ok", "ok", "pending"], p["stages"])
d = ds.diagnose(p, WSL)
check("... the exact click path and the stub-message explanation", "Settings > Resources > WSL integration" in " ".join(d["steps"]) and "could not be found in this WSL 2 distro" in " ".join(d["steps"]) and "wsl --shutdown" in " ".join(d["steps"]))

f = Fake(INSTALLED, tasklist=TASKLIST_RUNNING, win_info=WIN_INFO_OK, settings=SETTINGS_OFF, linux=lambda a: (127, "", STUB_MSG))
p = f.probe()
check("the distro's stub message ('could not be found in this WSL 2 distro') with Docker Desktop up is the same integration state", p["state"] == "engine_up_wsl_integration_off", p["state"])

f = Fake(INSTALLED, tasklist=TASKLIST_RUNNING, win_info=WIN_INFO_OK, settings=SETTINGS_ON)
f.which = lambda n, w=f.which: "/usr/bin/docker" if n == "docker" else w(n)
f.linux = lambda a: (0, "Docker version 28.0.1\n", "") if a[1:2] == ["--version"] else ((0, "default\n", "") if a[1:2] == ["context"] else (0, LINUX_INFO_OK[1], ""))
p = f.probe()
check("`docker` answers inside the distro: ready, and the Windows side is not even asked", p["state"] == "ready" and p["chip"] == "Ready" and not any(c[0].endswith(("tasklist.exe",)) for c in f.calls), p)
check("... all four stages done", [s["status"] for s in p["stages"]] == ["ok"] * 4, p["stages"])

f = Fake((), winget_list=WINGET_LIST)
p = f.probe(deep=True)
check("files not in the usual place but winget lists Docker Desktop: installed (via winget), version 4.99.0, still not 'not_installed'", p["state"] == "installed_windows_not_running" and p["evidence"]["installed_via"] == "winget" and p["evidence"]["desktop_version"] == "4.99.0", p.get("evidence"))
check("... and then there is no Docker Desktop.exe to start: the action is Re-check, not Start", p["action"] == "recheck", p["action"])
f = Fake(INSTALLED)
p = f.probe(deep=False)
check("without deep, `winget list` (slow) is not run", not any(c[0].endswith("winget.exe") for c in f.calls) and p["evidence"]["desktop_version"] == "")
p = f.probe(deep=True)
check("with deep the version comes from winget list", p["evidence"]["desktop_version"] == "4.99.0", p["evidence"])
f = Fake((), winget_list=None)
check("winget does not list it and no files: truly not installed", f.probe(deep=True)["state"] == "not_installed")

# native Windows: the same states, no WSL stage
WINDOWS = dict(WSL, kind="windows", wsl=False, package_manager="", wsl_distro="", winget="C:\\Users\\me\\AppData\\Local\\Microsoft\\WindowsApps\\winget.exe", powershell="C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe")
wdesk = "C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe"
wcli = "C:\\Program Files\\Docker\\Docker\\resources\\bin\\docker.exe"
wf = Fake((wdesk, wcli, "tasklist"))
wf.which = lambda n: None
p = ds.probe(WINDOWS, run=wf.run, which=wf.which, exists=wf.exists, env={"ProgramFiles": "C:\\Program Files"}, read=wf.read, globber=wf.glob)
check("native Windows: installed, not running (docker not on PATH right after install)", p["state"] == "installed_windows_not_running" and p["evidence"]["desktop_exe"] == wdesk, p)
check("native Windows: the integration stage is 'na' (no WSL)", [s["status"] for s in p["stages"]][3] == "na", p["stages"])

# ---- 2. settings-store.json shapes
shapes = {
    "list": ('{"IntegratedWslDistros": ["Ubuntu-24.04"]}', ["Ubuntu-24.04"]),
    "dict": ('{"IntegratedWslDistros": {"Ubuntu-24.04": true, "Debian": false}}', ["Ubuntu-24.04"]),
    "lower-case keys (older settings.json)": ('{"integratedWslDistros": ["Debian"], "wslEngineEnabled": true}', ["Debian"]),
    "comma string": ('{"IntegratedWslDistros": "A, B"}', ["A", "B"]),
    "empty list": ('{"IntegratedWslDistros": []}', []),
}
for label, (text, want) in shapes.items():
    got = ds.parse_wsl_settings(text)
    check(f"settings shape: {label}", got["integrated"] == want and got["known"], got)
for label, text in {"missing keys": '{"AutoStart": false}', "malformed JSON": '{"IntegratedWslDistros": [', "empty": "", "not an object": "[1, 2]", "null": "null"}.items():
    got = ds.parse_wsl_settings(text)
    check(f"settings: {label} is 'not known', never a crash", got["known"] is False and got["integrated"] is None, got)
check("settings: IntegratedWslDistros null is not known", ds.parse_wsl_settings('{"IntegratedWslDistros": null}')["integrated"] is None)
check("verdict: listed distro is on (case-insensitive)", ds.integration_verdict(ds.parse_wsl_settings(SETTINGS_ON), "ubuntu-24.04")[0] == "on")
check("verdict: not listed and default integration off is off, with the list", ds.integration_verdict(ds.parse_wsl_settings(SETTINGS_OFF), "Ubuntu-24.04")[0] == "off")
check("verdict: not listed but default-distro integration on is only 'unknown' (we cannot tell the default distro)", ds.integration_verdict(ds.parse_wsl_settings('{"IntegratedWslDistros": [], "EnableIntegrationWithDefaultWslDistro": true}'), "Ubuntu-24.04")[0] == "unknown")
check("verdict: WSL 2 engine switched off is reported as such", "WSL 2 based engine" in ds.integration_verdict(ds.parse_wsl_settings('{"UseWslEngine": false, "IntegratedWslDistros": []}'), "U")[1])
check("verdict: a real settings file without WSL keys (recorded on a machine with no WSL integration) is unknown", ds.integration_verdict(ds.parse_wsl_settings(json.dumps({"AutoStart": False, "LicenseTermsVersion": 2, "SettingsVersion": 43})), "U")[0] == "unknown")
check("settings_path prefers settings-store.json over settings.json, and the winget user's folder", ds.settings_path("wsl2", WSL, {}, lambda p_: p_.endswith(("settings.json", "settings-store.json")), lambda pat: ["/mnt/c/Users/other/AppData/Roaming/Docker", "/mnt/c/Users/me/AppData/Roaming/Docker"]) == "/mnt/c/Users/me/AppData/Roaming/Docker/settings-store.json")
check("tasklist parsing: running", ds.parse_tasklist(TASKLIST_RUNNING) is True and ds.parse_tasklist(TASKLIST_NONE) is False and ds.parse_tasklist("") is False)
check("winget list parsing: version / not listed", ds.parse_winget_list(WINGET_LIST) == "4.99.0" and ds.parse_winget_list(WINGET_NONE) == "" and ds.parse_winget_list("Docker Desktop Docker.DockerDesktop < 4.50.0 4.60.1 winget") == "4.50.0")

# ---- 3. winget succeeds, then detect: the right sentence, exit 20, no blind 90 s wait
log, slept = [], []
f = Fake(INSTALLED)        # after the install the files are there; Desktop was never started
code = ds.install(WSL, NI, yes=True, run=f.run, recheck=lambda: f.probe(deep=True), sleep=lambda s: slept.append(s), log=log.append, env={"PLASBENCH_STATE_DIR": tempfile.mkdtemp()})
text = "\n".join(log)
check("after winget: exit 20 (waiting for you), not a failure", code == 20, code)
check("after winget: 'Docker Desktop was installed on Windows (version 4.99.0). It is not running yet.'", "Docker Desktop was installed on Windows (version 4.99.0). It is not running yet." in text, text[-900:])
check("after winget: no 'Docker state: Not installed' line and no 'Waiting for the Docker engine ... 90 s'", "Not installed" not in text and "up to 90" not in text, text)
check("after winget: no waiting at all (not one sleep: nothing can answer before Docker Desktop is started)", sum(slept) == 0, slept)
check("after winget: the next human step is printed at once, with the --start offer", "--start" in text and "Start Docker Desktop" in text and "Waiting for you to finish in Docker Desktop (exit 20" in text, text[-700:])
check("after winget: nothing was started (no Start-Process)", not any("Start-Process" in " ".join(c) for c in f.calls), f.calls)
check("after winget: the install ran once with the exact winget argv", [c for c in f.calls if c[1:2] == ["install"]] == [ds.winget_argv(WINGET)], f.calls)

# files not visible yet right after the installer: settle a few times, then an honest sentence
log, slept, tries = [], [], []
code = ds.install(WSL, NI, yes=True, run=Fake().run, recheck=lambda: (tries.append(1), NI)[1], sleep=lambda s: slept.append(s), log=log.append, env={"PLASBENCH_STATE_DIR": tempfile.mkdtemp()})
text = "\n".join(log)
check("installer ok but nothing visible: looks a few times (settle), says so honestly, exit 20", code == 20 and len(tries) == 4 and sum(slept) <= 12 and "not visible to PlasBench yet" in text and "Docker state: Not installed" not in text, (code, len(tries), slept, text[-500:]))

# --start: argv, polling with progress, licence pending, errors
class Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


def run_start(fake, states, wait=None, start=True):
    clock, log = Clock(), []
    seq = iter(states)
    last = {}

    def recheck():
        nonlocal last
        last = next(seq, last)
        return last
    first = fake.probe(deep=True)
    code = ds.install(WSL, first, yes=False, start=start, wait=wait, run=fake.run, recheck=recheck, sleep=clock.sleep, clock=clock.now, log=log.append, env={"PLASBENCH_STATE_DIR": tempfile.mkdtemp()})
    return code, "\n".join(log), clock, fake


def st_(state, **kw):
    return dict({"state": state, "detail": "", "version": "", "evidence": {}}, **kw)


f = Fake(INSTALLED)
code, text, clock, _ = run_start(f, [st_("installed_windows_not_running"), st_("desktop_running_engine_down", detail="starting"), st_("desktop_running_engine_down"), st_("ready", server_version="28.0.1", version="28.0.1")])
starts = [c for c in f.calls if "Start-Process" in " ".join(c)]
check("--start: ONE start call, an argv list with powershell.exe, -NoProfile and Start-Process -FilePath 'C:\\...\\Docker Desktop.exe'", len(starts) == 1 and starts[0][0] == PWSH and starts[0][1] == "-NoProfile" and starts[0][-1] == "Start-Process -FilePath 'C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe'", starts)
check("--start then the engine answers: exit 0 and 'Docker is working'", code == 0 and "Docker is working" in text, (code, text[-500:]))
check("--start: state transitions are reported (not started -> starting -> ready)", "Docker Desktop not started" in text or "Docker Desktop starting" in text, text)
code, text, clock, f2 = run_start(Fake(INSTALLED), [st_("desktop_running_engine_down", detail="x")] * 40, wait=60)
check("--start with the engine never answering: polls up to --wait, a progress line about every 10 s, then exit 20 (not an error)", code == 20 and clock.t >= 60 and clock.t <= 70 and len(re.findall(r"Still waiting", text)) >= 4, (code, clock.t, text[-400:]))
check("--start with the engine never answering: the licence-pending message (switch to its window, PlasBench never accepts it)", "accept the licence" in text and "switch to the Docker Desktop window" in text and "never accepts it" in text, text[-700:])
code, text, clock, f3 = run_start(Fake(INSTALLED, start_rc=1), [])
check("--start refused by Windows (access denied): exit 20, a plain sentence, Start menu fallback, no polling", code == 20 and "could not start Docker Desktop" in text and "blocked" in text and "Start menu" in text and clock.t == 0, (code, text[-500:]))
code, text, clock, f4 = run_start(Fake((CLI, TASKLIST)), [])
check("--start when Docker Desktop.exe is not found: says so, exit 20", code == 20 and "Docker Desktop.exe was not found" in text, text[-400:])
code, text, clock, f5 = run_start(Fake(INSTALLED), [], start=False)
check("without --start nothing is started and nothing is polled", code == 20 and not any("Start-Process" in " ".join(c) for c in f5.calls) and clock.t == 0 and "--start" in text)
noshell = dict(WSL, powershell=None)
f6 = Fake(INSTALLED)
log = []
code = ds.install(noshell, ds.probe(noshell, run=f6.run, which=f6.which, exists=f6.exists, env={}, read=f6.read, globber=f6.glob), start=True, run=f6.run, recheck=lambda: NI, sleep=lambda s: None, log=log.append, env={"PLASBENCH_STATE_DIR": tempfile.mkdtemp()})
check("--start without PowerShell on the Windows side (WSL interop off): a plain sentence, exit 20", code == 20 and "not reachable" in "\n".join(log), "\n".join(log))

# Docker Desktop already running, engine down: poll with visible progress, default 90 s, only here
f = Fake(INSTALLED, tasklist=TASKLIST_RUNNING)
code, text, clock, _ = run_start(f, [st_("desktop_running_engine_down")] * 40, start=False)
check("running-engine-down: the default wait is 90 s (and only in the running states), with progress lines every ~10 s", code == 20 and 90 <= clock.t <= 100 and len(re.findall(r"Still waiting", text)) >= 8, (code, clock.t))
code, text, clock, _ = run_start(f, [st_("desktop_running_engine_down")] * 40, wait=0, start=False)
check("--wait 0: no polling at all", clock.t == 0 and code == 20)
code, text, clock, _ = run_start(f, [st_("desktop_running_engine_down"), st_("engine_up_wsl_integration_off", detail="off")] + [st_("engine_up_wsl_integration_off")] * 40, start=False)
check("polling stops as soon as only a person can fix it (integration off): no waiting out the timeout", clock.t <= 10, clock.t)
f = Fake(INSTALLED, tasklist=TASKLIST_RUNNING, win_info=WIN_INFO_OK, settings=SETTINGS_OFF)
code, text, clock, _ = run_start(f, [], start=False)
check("engine up, WSL integration off: exit 20 at once with the click path, no wait", code == 20 and clock.t == 0 and "Settings > Resources > WSL integration" in text, text[-600:])

# --open-integration: URI, fallback, verification loop
f = Fake(INSTALLED, tasklist=TASKLIST_RUNNING, win_info=WIN_INFO_OK, settings=SETTINGS_OFF)
log, clock = [], Clock()
seq = iter([st_("engine_up_wsl_integration_off")] * 3 + [st_("ready", server_version="28", version="28")])
first = f.probe()
code = ds.install(WSL, first, open_integ=True, run=f.run, recheck=lambda: next(seq, st_("ready")), sleep=clock.sleep, clock=clock.now, log=log.append, env={"PLASBENCH_STATE_DIR": tempfile.mkdtemp()})
text = "\n".join(log)
uri = [c for c in f.calls if "docker-desktop://" in " ".join(c)]
check("--open-integration: opens the docker-desktop:// settings link as a quoted literal in an argv list", len(uri) == 1 and uri[0][-1] == "Start-Process 'docker-desktop://dashboard/settings/resources/wsl-integration'", uri)
check("--open-integration: then checks every 5 s and finishes when docker works (exit 0), within the 3 minutes", code == 0 and 10 <= clock.t <= 20 and "Docker is working" in text, (code, clock.t, text[-400:]))
f = Fake(INSTALLED, tasklist=TASKLIST_RUNNING, win_info=WIN_INFO_OK, settings=SETTINGS_OFF, uri_rc=1)
ok, said = ds.open_integration(WSL, f.probe()["evidence"], f.run)
check("--open-integration: when the link does not open, Docker Desktop's main window is opened and the click path is said", ok and "Settings > Resources > WSL integration" in said and sum("Start-Process -FilePath" in " ".join(c) for c in f.calls) == 1, said)
log, clock = [], Clock()
code = ds.install(WSL, f.probe(), open_integ=True, wait=30, run=f.run, recheck=lambda: st_("engine_up_wsl_integration_off", detail="off"), sleep=clock.sleep, clock=clock.now, log=log.append, env={"PLASBENCH_STATE_DIR": tempfile.mkdtemp()})
check("--open-integration: gives up after the wait, exit 20, the steps are listed", code == 20 and 30 <= clock.t <= 40 and "Waiting for you to finish in Docker Desktop (exit 20" in "\n".join(log), (code, clock.t))

# ---- 4. argv safety
HOSTILE = ["C:\\Program Files\\Docker's\\Docker Desktop.exe", "C:\\x'; Remove-Item -Recurse C:\\ ; '\\a.exe", "C:\\a\u2018b\u2019c\\Docker Desktop.exe", "C:\\$(calc)\\`whoami`\\d.exe"]
for hp in HOSTILE:
    a = ds.start_argv(PWSH, hp)
    cmd = a[-1]
    lit = cmd[len("Start-Process -FilePath "):]
    # undo PowerShell's quote doubling: the literal must be ONE string that decodes back to the exact path
    inner = lit[1:-1]
    decoded = re.sub("(['\u2018\u2019\u201a\u201b])\\1", r"\1", inner)
    check(f"hostile path stays one literal and round-trips: {hp[:30]!r}", isinstance(a, list) and a[:4] == [PWSH, "-NoProfile", "-NonInteractive", "-Command"] and lit[0] == "'" and lit[-1] == "'" and decoded == hp and not re.search("(?<!['\u2018\u2019\u201a\u201b])['\u2018\u2019\u201a\u201b](?!['\u2018\u2019\u201a\u201b])", re.sub("(['\u2018\u2019\u201a\u201b])\\1", "", inner)), a)
for bad in ("C:\\a\nb", 'C:\\a"b', "C:\\a\x00b"):
    try:
        ds.start_argv(PWSH, bad)
        refused = False
    except ValueError:
        refused = True
    check(f"control characters and double quotes are refused: {bad!r}", refused)
check("to_windows_path: /mnt/c/Program Files/... -> C:\\Program Files\\...", ds.to_windows_path(DESK) == "C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe" and ds.to_windows_path("/mnt/d/x y/z.exe") == "D:\\x y\\z.exe" and ds.to_windows_path("/usr/bin/docker") == "/usr/bin/docker")
check("no shell string anywhere in the new code: argv lists, no shell=True, no os.system", not re.search(r"shell\s*=\s*True|os\.system|os\.popen", (ROOT / "python" / "docker_setup.py").read_text(encoding="utf-8")))

# ---- 5. the plan when Docker Desktop is already installed
f = Fake(INSTALLED)
p = f.probe(deep=True)
plan = ds.make_plan(WSL, p)
text = ds.render_plan(plan, p, WSL)
check("plan for an installed Desktop: nothing to install, no winget run, no 'not installed'", plan["runs"] is None and plan["route"] == "guide" and "already installed" in plan["installed"] and "nothing to install" in plan["installed"] and "4.99.0" in plan["installed"] and "winget install" not in text and "not installed" not in text.lower().replace("nothing to install", ""), text)
check("plan: 'Docker Desktop 4.99.0 is already installed (winget); nothing to install.' wording", "Docker Desktop 4.99.0 is already installed" in text, text)
check("plan: says what is left (start / licence / integration)", all(w in text for w in ("Start Docker Desktop", "licence", "WSL integration")), text)
check("plan: no internet needed, no licence block for an install", plan["internet"] == [] and plan["licence"] == "")
code = ds.install(WSL, p, yes=True, run=f.run, recheck=lambda: p, sleep=lambda s: None, log=[].append, env={"PLASBENCH_STATE_DIR": tempfile.mkdtemp()})
check("`install-tools docker --yes` on an installed Desktop does not run winget again (exit 20)", code == 20 and not any(c[1:2] == ["install"] for c in f.calls), f.calls)
log = []
ds.install(WSL, p, dry_run=True, run=f.run, log=log.append)
check("dry run on an installed Desktop: the plan, nothing started", "already installed" in "\n".join(log) and not any("Start-Process" in " ".join(c) for c in f.calls))
check("check line names the next command for each state", "--start" in ds.check_line(dict(p)) and "--open-integration" in ds.check_line(dict(p, state="engine_up_wsl_integration_off", action="integration", evidence={})))
check("older states keep their meaning: desktop_not_running / wsl_integration_off have steps", ds.diagnose({"state": "wsl_integration_off", "detail": ""}, WSL)["steps"] and ds.diagnose({"state": "desktop_not_running", "detail": ""}, WSL)["steps"])
check("every state, old and new, has a chip and a diagnosis title", all(s in ds.CHIPS and ds.diagnose({"state": s, "detail": ""}, WSL)["title"] for s in ds.STATES))
check("the 3 new states are registered", set(ds.WIN_STATES) <= set(ds.STATES) and len(ds.WIN_STATES) == 3)

# wait_ready: progress lines and stop states
clock = Clock()
msgs = []
final = ds.wait_ready(lambda: {"state": "daemon_stopped", "detail": ""}, 35, 5, sleep=clock.sleep, log=msgs.append, clock=clock.now, progress=10)
check("wait_ready: a progress line every 10 s, never silent", len([m for m in msgs if "Still waiting" in m]) == 3 and final["state"] == "daemon_stopped", msgs)
clock = Clock()
final = ds.wait_ready(lambda: {"state": "permission_denied", "detail": ""}, 600, 5, sleep=clock.sleep, log=lambda m: None, clock=clock.now, stop=ds.HUMAN_STATES)
check("wait_ready: stops at once for a state only a person can fix", clock.t == 0)

# ---- 6. the CLI and the window
sh = (ROOT / "env" / "install_tools.sh").read_text(encoding="utf-8")
cli = (ROOT / "plasbench" / "cli.py").read_text(encoding="utf-8")
check("CLI: install-tools docker takes --start, --wait and --open-integration and passes them through", all(w in cli for w in ('"--start"', '"--wait"', '"--open-integration"', "PLASBENCH_DOCKER_START", "PLASBENCH_DOCKER_OPEN_INTEGRATION", "PLASBENCH_DOCKER_WAIT")) and all(w in sh for w in ("--start", "--open-integration", "--wait")))
import subprocess  # noqa: E402
helped = subprocess.run([sys.executable, str(ROOT / "python" / "docker_setup.py"), "--help"], capture_output=True, text=True).stdout
check("docker_setup --help documents --start, --wait and --open-integration", all(w in helped for w in ("--start", "--wait", "--open-integration")))
html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
block = html[html.index("==DOCKER-UI-BEGIN=="):html.index("==DOCKER-UI-END==")]
from plasbench import ui_help  # noqa: E402
for needle in ('id="dk_stages"', 'id="dk_enabled"', "Start Docker Desktop", "Open WSL integration settings", "I enabled it", "dockerStart", "dockerIntegration", "dockerEnabled", '"--start"', '"--open-integration"',
               'tabindex="0"', "aria-label"):
    check(f"window: {needle}", needle in html, needle)
check("window: the primary button follows the state (Install / Start / Open WSL integration settings / Re-check)", all(w in block for w in ('"install"', '"start"', '"integration"', '"recheck"', "dockerAction(")))
check("window: the checklist is keyed and shows tick / pending / blocked with the evidence as its tooltip", "applyKeyed($(\"#dk_stages\")" in block and "it.x.evidence" in block and all(w in block for w in ("ok:", "pending:", "blocked:")))
check("window: 'I enabled it' polls every 5 s for up to 3 minutes and stops at ready", "180000" in block and "sleep(5000)" in block and 'state === "ready"' in block)
check("window: the Docker block uses no browser confirm / prompt / alert", not re.search(r"(?<![\w.])(confirm|prompt|alert)\(", block))
check("window: Start Docker Desktop asks first in an in-page dialog and starts a job, never a request on load", "modalDialog(" in block[block.index("async function dockerStart"):block.index("function dockerIntegration")] and "startJob([\"install-tools\", \"docker\", \"--start\"]" in block)
check("window: the Environment card offers the same Start / Open integration actions", 'data-dk="start"' in html and 'data-dk="integration"' in html)
for key in ("docker_start", "docker_integration", "docker_integration_done", "docker_stages", "docker_state"):
    check(f"tooltip text for {key} in ui_help.NATIVE_PICKER", ui_help.NATIVE_PICKER.get(key, {}).get("summary"))
for key in ("start_docker", "open_integration"):
    check(f"tooltip text for {key} in ui_help.ENVIRONMENT", ui_help.ENVIRONMENT.get(key, {}).get("summary"))
check("tooltips say PlasBench never accepts the licence or edits Docker's settings", "never accepts the Docker licence" in ui_help.NATIVE_PICKER["docker_start"]["summary"] and "does not edit Docker Desktop settings" in ui_help.NATIVE_PICKER["docker_integration"]["summary"])
web = (ROOT / "plasbench" / "webui.py").read_text(encoding="utf-8")
check("server: the probe returns the stages and the next action, still a cached background probe (no new spawn on the load path)", '"stages": st.get("stages")' in web and '"action": diag["action"]' in web and 'loadcache.swr(("docker-setup",)' in web)
check("server: the Environment card maps the new states (starting / not started -> daemon_stopped, integration off)", "installed_windows_not_running" in web and "engine_up_wsl_integration_off" in web)
src = (ROOT / "python" / "docker_setup.py").read_text(encoding="utf-8")
check("never edits Docker's settings files: the only open() of a settings path is a read", "open(path" in src and not re.search(r"settings[^\n]*\.write|write\([^\n]*settings", src))
check("Python 3.9 compatible source (annotations future import, no write_text/read_text(newline=))", "from __future__ import annotations" in src and "newline=" not in re.sub(r"open\([^)]*newline=", "", src))

print("ALL DOCKER POST-INSTALL TESTS PASSED" if not FAILED else f"DOCKER POST-INSTALL TESTS FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
