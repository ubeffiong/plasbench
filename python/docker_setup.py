#!/usr/bin/env python3
"""Docker in PlasBench's tools setup: detect the situation, diagnose it precisely, and install where a user-level process may, handing off where it may not.

PlasBench never runs sudo, never accepts administrator credentials and never pipes a downloaded script to a shell. So this is a consent-based installer:

  * Windows, and WSL2 (through the Windows side): `winget install -e --id Docker.DockerDesktop` is started as the user; Windows shows its OWN approval (UAC) prompt.
    The licence of Docker Desktop is accepted by the person in Docker Desktop on first launch, never by PlasBench.
  * macOS: `brew install --cask docker-desktop` when Homebrew exists, else the official download page. The installer asks for the user's password itself.
  * Linux, and Docker Engine inside WSL: a copyable script from docs.docker.com that the user runs in a terminal with their own sudo (nothing is run for them).

Exit codes of `install`: 0 Docker is verified working, 20 steps were handed to the user (information, not an error: "Waiting for you"), 21 nothing was done because
consent (--yes) is missing, 1 a real failure. Every system fact is an argument (runner, which, exists, read) so tests drive this with recorded outputs and fake programs.
It goes online only for the winget / brew routes and the optional hello-world pull (the shell wrapper env/install_tools.sh checks the internet first: netcheck services
docker, winget and brew in config/network_services.tsv; PLASBENCH_OFFLINE=1 is honoured here too). Standard library only; Python 3.9.
"""
from __future__ import annotations

import argparse
import glob
import json
import ntpath
import os
import posixpath
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

EXIT_OK, EXIT_HANDOFF, EXIT_CONSENT, EXIT_FAIL = 0, 20, 21, 1
WINGET_ID = "Docker.DockerDesktop"
BREW_CASKS = ("docker-desktop", "docker")       # Homebrew renamed the cask `docker` to `docker-desktop`; the old token is the fallback for an older Homebrew
LICENCE_URL = "https://www.docker.com/legal/docker-subscription-service-agreement/"
GUIDE_URL = "https://docs.docker.com/get-started/get-docker/"
DESKTOP_WINDOWS_URL = "https://docs.docker.com/desktop/setup/install/windows-install/"
DESKTOP_MAC_URL = "https://docs.docker.com/desktop/setup/install/mac-install/"
DESKTOP_LINUX_URL = "https://docs.docker.com/desktop/setup/install/linux/"
WSL_INTEGRATION_URL = "https://docs.docker.com/desktop/features/wsl/"
WSL_INSTALL_URL = "https://learn.microsoft.com/windows/wsl/install"
ENGINE_URLS = {"ubuntu": "https://docs.docker.com/engine/install/ubuntu/", "debian": "https://docs.docker.com/engine/install/debian/",
               "fedora": "https://docs.docker.com/engine/install/fedora/", "centos": "https://docs.docker.com/engine/install/centos/"}
ROOTLESS_URL = "https://docs.docker.com/engine/security/rootless/"
POSTINSTALL_URL = "https://docs.docker.com/engine/install/linux-postinstall/"
HELLO_ARGV = ["docker", "run", "--rm", "hello-world"]
DOCKER_KEY_FPR_APT = "9DC858229FC7DD38854AE2D88D81803C0EBFCD88"      # Docker's apt/rpm signing key, as published on docs.docker.com
DOCKER_KEY_FPR_RPM = "060A61C51B558A7F742B77AAC52FEB6B621E9F35"
SERVICES = {"winget": ["winget", "docker"], "brew": ["brew", "docker"]}
# The Windows-side states (Windows, and WSL 2 where Docker Desktop lives on the Windows side): told apart so that "installed but not started" is never reported as "not installed".
WIN_STATES = ("installed_windows_not_running", "desktop_running_engine_down", "engine_up_wsl_integration_off")
HUMAN_STATES = ("engine_up_wsl_integration_off", "permission_denied")      # waiting longer cannot fix these: a person has to act
STATES = ("ready", "not_installed", "daemon_stopped", "permission_denied", "wsl_integration_off", "desktop_not_running", "in_container", "unknown") + WIN_STATES
STAGES = (("installed", "Installed"), ("running", "Running"), ("engine", "Engine answering (licence accepted)"), ("integration", "WSL integration"))
DESKTOP_EXE = "Docker Desktop.exe"
SETTINGS_FILES = ("settings-store.json", "settings.json")      # newer Docker Desktop versions write settings-store.json; settings.json is the older name
INTEGRATION_URI = "docker-desktop://dashboard/settings/resources/wsl-integration"
CHIPS = {"installed_windows_not_running": ("Docker Desktop not started", "warn"), "desktop_running_engine_down": ("Docker Desktop starting", "warn"),
         "engine_up_wsl_integration_off": ("WSL integration off", "warn"),
         "ready": ("Ready", "ok"), "not_installed": ("Not installed", "bad"), "daemon_stopped": ("Installed, daemon stopped", "warn"),
         "permission_denied": ("Permission needed", "warn"), "wsl_integration_off": ("WSL integration off", "warn"),
         "desktop_not_running": ("Docker Desktop not running", "warn"), "in_container": ("Inside a container", "warn"), "unknown": ("Not working", "warn")}
STATUS_NAME = "docker_status.json"

# ---------------------------------------------------------------- small helpers


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


def default_run(argv, timeout=20):
    """(returncode, stdout, stderr), or None when the program is missing / cannot start. Never a shell string."""
    try:
        done = subprocess.run(list(argv), capture_output=True, timeout=timeout)
    except (OSError, ValueError):
        return None
    except subprocess.TimeoutExpired:
        return (124, "", "timed out after %s seconds" % timeout)
    return (done.returncode, done.stdout.decode("utf-8", "replace").replace("\x00", ""), done.stderr.decode("utf-8", "replace").replace("\x00", ""))


def _offline():
    return os.environ.get("PLASBENCH_OFFLINE", "").strip().lower() in ("1", "true", "yes", "on")


def _flag(env, name):
    return str(env.get(name, "")).strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------- the environment
def in_container(env=None, exists=os.path.exists, read=_read):
    env = os.environ if env is None else env
    flag = str(env.get("PLASBENCH_IN_DOCKER", "")).strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    if flag in ("0", "false", "no", "off"):
        return False
    if exists("/.dockerenv") or exists("/run/.containerenv"):
        return True
    return bool(re.search(r"(^|/)(docker|kubepods|containerd|libpod|lxc)(-|/|\.|$)", read("/proc/1/cgroup") or "", re.M))


def parse_os_release(text):
    out = {}
    for line in (text or "").splitlines():
        key, eq, value = line.partition("=")
        if eq and re.match(r"^[A-Z_]+$", key.strip()):
            out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def _family(osr):
    ids = [osr.get("ID", "").lower()] + osr.get("ID_LIKE", "").lower().split()
    for word in ids:
        if word in ("ubuntu", "debian", "linuxmint", "pop", "raspbian", "kali", "elementary", "zorin"):
            return "apt", ("debian" if word in ("debian", "raspbian") else "ubuntu")
        if word in ("fedora", "rhel", "centos", "rocky", "almalinux", "ol", "amzn"):
            return "dnf", ("fedora" if word == "fedora" else "centos")
        if word in ("arch", "manjaro", "endeavouros", "cachyos"):
            return "pacman", "arch"
        if word in ("opensuse", "opensuse-leap", "opensuse-tumbleweed", "suse", "sles"):
            return "zypper", "suse"
    return "", ""


def _windows_tools(plat, env, which, exists):
    """(winget path or None, powershell path or None, docker desktop installed). From WSL the Windows side is reached through interop by absolute path."""
    winget = which("winget.exe") or which("winget")
    shell = which("powershell.exe") or which("pwsh.exe")
    desktop = False
    if plat == "windows":
        for key in ("ProgramFiles", "ProgramW6432"):
            base = env.get(key)
            if base and exists(os.path.join(base, "Docker", "Docker", "Docker Desktop.exe")):
                desktop = True
        local = env.get("LOCALAPPDATA")
        if not winget and local and exists(os.path.join(local, "Microsoft", "WindowsApps", "winget.exe")):
            winget = os.path.join(local, "Microsoft", "WindowsApps", "winget.exe")
        if not shell:
            root = env.get("SystemRoot") or env.get("SYSTEMROOT") or "C:\\Windows"
            cand = os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
            shell = cand if exists(cand) else None
    elif plat == "wsl2":
        desktop = exists("/mnt/c/Program Files/Docker/Docker/Docker Desktop.exe")
        if not winget:
            for cand in sorted(glob.glob("/mnt/c/Users/*/AppData/Local/Microsoft/WindowsApps/winget.exe")):
                if exists(cand):
                    winget = cand
                    break
        if not shell:
            cand = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
            shell = cand if exists(cand) else None
    return winget, shell, desktop


def detect_environment(env=None, which=shutil.which, exists=os.path.exists, read=_read, platform=None):
    """See _detect_environment. With PLASBENCH_DOCKER_PLATFORM set (tests only) whether Docker Desktop counts as installed comes from PLASBENCH_DOCKER_DESKTOP, not from this computer."""
    environment = _detect_environment(env, which, exists, read, platform)
    e = os.environ if env is None else env
    if str(e.get("PLASBENCH_DOCKER_PLATFORM", "")).strip():
        environment["desktop_installed"] = _flag(e, "PLASBENCH_DOCKER_DESKTOP")
    return environment


def _detect_environment(env=None, which=shutil.which, exists=os.path.exists, read=_read, platform=None):
    """{'kind': windows|wsl2|wsl1|macos|linux|container, 'wsl', 'interop', 'winget', 'powershell', 'desktop_installed', 'brew', 'package_manager', 'distro', 'distro_id',
    'systemd', 'wsl_distro', 'container'}. `platform` is 'windows', 'macos' or 'linux' (default: this computer)."""
    env = os.environ if env is None else env
    forced = str(env.get("PLASBENCH_DOCKER_PLATFORM", "")).strip().lower()      # tests only: pretend to be windows | wsl2 | macos | linux | container
    if platform is None:
        platform = "windows" if os.name == "nt" else ("macos" if sys.platform == "darwin" else "linux")
    if forced in ("windows", "macos"):
        platform = forced
    elif forced in ("wsl2", "linux", "container"):
        platform = "linux"
    out = {"kind": platform, "wsl": False, "interop": None, "winget": None, "powershell": None, "desktop_installed": False, "brew": None, "package_manager": "", "distro": "",
           "distro_id": "", "systemd": False, "wsl_distro": "", "container": False}
    if platform == "windows":
        out["winget"], out["powershell"], out["desktop_installed"] = _windows_tools("windows", env, which, exists)
        return out
    if platform == "macos":
        out["brew"] = which("brew") or next((p for p in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew") if exists(p)), None)
        out["desktop_installed"] = exists("/Applications/Docker.app")
        return out
    osr = parse_os_release(read("/etc/os-release"))
    out["distro"] = osr.get("PRETTY_NAME") or osr.get("NAME") or ""
    out["package_manager"], out["distro_id"] = _family(osr)
    out["systemd"] = exists("/run/systemd/system")
    version = (read("/proc/version") or "").lower()
    if forced in ("linux", "container"):
        version = ""                      # tests: a pretend plain Linux, even when the test itself runs inside WSL
    if ("microsoft" in version or env.get("WSL_DISTRO_NAME") or env.get("WSL_INTEROP")) and forced not in ("linux", "container"):
        out["wsl"] = True
        out["wsl_distro"] = env.get("WSL_DISTRO_NAME", "")
        out["kind"] = "wsl2" if ("wsl2" in version or "microsoft-standard" in version or env.get("WSL_INTEROP")) else "wsl1"
        interop = read("/proc/sys/fs/binfmt_misc/WSLInterop")
        out["interop"] = None if interop is None and not env.get("WSL_INTEROP") else (interop is None or interop.lstrip().lower().startswith("enabled"))
        out["winget"], out["powershell"], out["desktop_installed"] = _windows_tools("wsl2", env, which, exists)
        if out["interop"] is False:
            out["winget"] = out["powershell"] = None
    if forced == "wsl2" and not out["wsl"]:
        out.update(wsl=True, kind="wsl2", interop=True, wsl_distro=env.get("WSL_DISTRO_NAME", "Ubuntu"))
        out["winget"], out["powershell"], out["desktop_installed"] = _windows_tools("wsl2", env, which, exists)
    if forced == "container" or (not forced and in_container(env, exists, read)):
        out["container"] = True
        if not out["wsl"]:
            out["kind"] = "container"
    return out


# ---------------------------------------------------------------- the Docker state
WSL_OFF_RE = re.compile(r"could not be found in this wsl 2 distro|activate the wsl integration", re.I)
PERMISSION_RE = re.compile(r"permission denied.*(docker daemon socket|docker\.sock)|got permission denied while trying to connect", re.I | re.S)
DAEMON_RE = re.compile(r"cannot connect to the docker daemon|is the docker daemon running|error during connect|docker daemon is not running|dockerdesktoplinuxengine|"
                       r"failed to connect to the docker api|connect: no such file or directory|connection refused", re.I)


def find_docker(env=None, which=shutil.which, exists=os.path.exists, plat="linux"):
    """The docker program: on PATH, or (Windows and macOS, right after an install, before PATH is refreshed) in Docker Desktop's own folder."""
    env = os.environ if env is None else env
    found = which("docker") or (which("docker.exe") if plat == "windows" else None)      # in WSL only a `docker` of the distro counts: docker.exe on the Windows PATH is Windows' (the evidence, not the tool)
    if found:
        return found
    if plat == "windows":
        for key in ("ProgramFiles", "ProgramW6432"):
            base = env.get(key)
            cand = os.path.join(base, "Docker", "Docker", "resources", "bin", "docker.exe") if base else ""
            if cand and exists(cand):
                return cand
    if plat == "macos":
        for cand in ("/Applications/Docker.app/Contents/Resources/bin/docker", "/usr/local/bin/docker"):
            if exists(cand):
                return cand
    return None


# ---------------------------------------------------------------- the Windows side (Docker Desktop lives there, also when PlasBench runs in WSL 2)
def _info_ok(info):
    return bool(info) and info[0] == 0 and not re.search(r"cannot connect|error during connect", (info[1] or "") + (info[2] or ""), re.I)


def to_windows_path(path):
    """/mnt/c/Program Files/x -> C:\\Program Files\\x (what Windows programs understand); anything else is returned unchanged."""
    m = re.match(r"^/mnt/([a-zA-Z])(?:/(.*))?$", path or "")
    if not m:
        return path
    return m.group(1).upper() + ":\\" + (m.group(2) or "").replace("/", "\\")


def desktop_paths(plat, env=None, exists=os.path.exists):
    """(Docker Desktop.exe, resources/bin/docker.exe) as this process sees them; '' for each that is not there. WSL 2 reaches the Windows C: drive at /mnt/c."""
    env = os.environ if env is None else env
    if plat == "wsl2":
        bases = ["/mnt/c/Program Files/Docker/Docker"]
        join = posixpath.join
    elif plat == "windows":
        bases = [ntpath.join(env[k], "Docker", "Docker") for k in ("ProgramFiles", "ProgramW6432") if env.get(k)] or ["C:\\Program Files\\Docker\\Docker"]
        join = ntpath.join
    else:
        return "", ""
    for base in bases:
        desk, cli = join(base, DESKTOP_EXE), join(base, "resources", "bin", "docker.exe")
        have_desk, have_cli = exists(desk), exists(cli)
        if have_desk or have_cli:
            return (desk if have_desk else ""), (cli if have_cli else "")
    return "", ""


def settings_path(plat, environment=None, env=None, exists=os.path.exists, globber=glob.glob):
    """Docker Desktop's settings file (settings-store.json, else settings.json) on the Windows side, or ''. Under WSL the Windows user is not known, so every user's folder is
    looked at; the user whose folder holds winget (the one that installed Docker Desktop) comes first."""
    env = os.environ if env is None else env
    folders, join = [], posixpath.join
    if plat == "windows":
        join = ntpath.join
        if env.get("APPDATA"):
            folders = [ntpath.join(env["APPDATA"], "Docker")]
    elif plat == "wsl2":
        folders = sorted(globber("/mnt/c/Users/*/AppData/Roaming/Docker"))
        who = re.search(r"/Users/([^/]+)/", (environment or {}).get("winget") or "")
        if who:
            folders.sort(key=lambda f: 0 if ("/Users/%s/" % who.group(1)) in f + "/" else 1)
    for name in SETTINGS_FILES:
        for folder in folders:
            if exists(join(folder, name)):
                return join(folder, name)
    return ""


def _truthy(value):
    return value is True or (isinstance(value, str) and value.strip().lower() in ("1", "true", "yes", "on"))


def parse_wsl_settings(text):
    """What Docker Desktop's settings file says about WSL: {'known', 'integrated': [distros] or None, 'default_integration': bool or None, 'wsl_engine': bool or None}.
    Accepts a list, a {distro: bool} map or a comma string for the distros; key names are matched ignoring case; unreadable text is 'not known', never an exception."""
    out = {"known": False, "integrated": None, "default_integration": None, "wsl_engine": None, "license_terms": None}
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return out
    if not isinstance(data, dict):
        return out
    low = {str(k).lower(): v for k, v in data.items()}
    raw = low.get("integratedwsldistros")
    if isinstance(raw, list):
        out["integrated"] = [str(x) for x in raw if isinstance(x, str) and x.strip()]
    elif isinstance(raw, dict):
        out["integrated"] = [str(k) for k, v in raw.items() if v is not False and v is not None and str(v).strip().lower() not in ("false", "0", "no", "off")]
    elif isinstance(raw, str):
        out["integrated"] = [x.strip() for x in raw.split(",") if x.strip()]
    for key, field in (("enableintegrationwithdefaultwsldistro", "default_integration"), ("usewslengine", "wsl_engine"), ("wslengineenabled", "wsl_engine")):
        if key in low and out[field] is None and isinstance(low[key], (bool, str)):
            out[field] = _truthy(low[key])
    terms = low.get("licenseTermsVersion".lower())
    out["license_terms"] = terms if isinstance(terms, (int, str)) and not isinstance(terms, bool) and str(terms).strip() not in ("", "0") else None
    out["known"] = out["integrated"] is not None or out["default_integration"] is not None or out["wsl_engine"] is not None
    return out


def integration_verdict(parsed, distro):
    """('on' | 'off' | 'unknown', one plain sentence) for this WSL distro, from the parsed settings."""
    if not parsed or not parsed.get("known") or not distro:
        return "unknown", ""
    listed = parsed.get("integrated")
    if listed is not None and distro.lower() in [x.lower() for x in listed]:
        return "on", "Docker Desktop's settings list %s under WSL integration." % distro
    if parsed.get("wsl_engine") is False:
        return "off", "Docker Desktop's WSL 2 based engine is switched off (Settings > General > Use the WSL 2 based engine)."
    if listed is not None and not parsed.get("default_integration"):
        return "off", "Docker Desktop's WSL integration is off for %s (integrated distros: %s)." % (distro, ", ".join(listed) or "none")
    if listed is not None or parsed.get("default_integration"):
        return "unknown", "%s is not listed under WSL integration; it is integrated only if it is your default WSL distro." % distro
    return "unknown", ""


def parse_tasklist(text):
    """True when `tasklist /FO CSV /NH` lists Docker Desktop.exe."""
    return any(ln.strip().strip('"').lower().startswith(DESKTOP_EXE.lower()) for ln in (text or "").splitlines())


def parse_winget_list(text):
    """The Docker Desktop version from `winget list --id Docker.DockerDesktop` ('' when it is not listed)."""
    for ln in (text or "").splitlines():
        m = re.search(re.escape(WINGET_ID) + r"\s+(?:[<>]\s*)?(\d[\w.+-]*)", ln)
        if m:
            return m.group(1)
    return ""


def _desktop_running(environment, plat, run, which, exists, timeout):
    """True / False from tasklist (else PowerShell's Get-Process); None when neither could be asked."""
    tl = which("tasklist.exe") or which("tasklist") or ("/mnt/c/Windows/System32/tasklist.exe" if plat == "wsl2" and exists("/mnt/c/Windows/System32/tasklist.exe") else None)
    if tl:
        got = run([tl, "/FI", "IMAGENAME eq " + DESKTOP_EXE, "/FO", "CSV", "/NH"], timeout)
        if got is not None and got[0] == 0:
            return parse_tasklist(got[1])
    ps = environment.get("powershell")
    if ps:
        got = run([ps, "-NoProfile", "-NonInteractive", "-Command", "(Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue | Measure-Object).Count"], timeout)
        if got is not None and got[0] == 0 and (got[1] or "").strip().isdigit():
            return int(got[1].strip()) > 0
    return None


def windows_evidence(environment, run=default_run, which=shutil.which, exists=os.path.exists, env=None, read=_read, globber=glob.glob, timeout=20, deep=False):
    """What can be seen of Docker Desktop on the Windows side, read-only: the files (Docker Desktop.exe, resources/bin/docker.exe), whether Docker Desktop.exe is running, whether
    `docker.exe info` answers, and what its settings file says about WSL integration for this distro. `deep` also asks `winget list` (slow: seconds) for the version, and as a
    fallback for the install when the files are not in the usual place."""
    plat = environment.get("kind")
    desk, cli = desktop_paths(plat, env, exists)
    ev = {"desktop_exe": desk, "docker_exe": cli, "installed": bool(desk or cli), "installed_via": "files" if (desk or cli) else "", "desktop_version": "", "running": None,
          "engine_up": False, "engine_detail": "", "settings_path": "", "integration": "unknown", "integration_text": "", "integrated_distros": None}
    winget = environment.get("winget")
    if deep and winget:
        got = run([winget, "list", "--id", WINGET_ID, "-e", "--accept-source-agreements"], 30)
        version = parse_winget_list(got[1]) if got and got[0] == 0 else ""
        if version:
            ev["desktop_version"] = version
            if not ev["installed"]:
                ev.update(installed=True, installed_via="winget")
    if not ev["installed"]:
        return ev
    if cli:
        info = run([cli, "info"], timeout)
        ev["engine_up"] = _info_ok(info)
        ev["engine_detail"] = "docker.exe info answered" if ev["engine_up"] else (next((ln.strip() for t in ((info[2], info[1]) if info else ()) for ln in (t or "").splitlines() if ln.strip()), "docker.exe could not be run"))
    ev["running"] = True if ev["engine_up"] else _desktop_running(environment, plat, run, which, exists, timeout)
    if plat in ("wsl2", "windows"):
        path = settings_path(plat, environment, env, exists, globber)
        ev["settings_path"] = path
        if path:
            parsed = parse_wsl_settings(read(path) or "")
            ev["license_terms"] = parsed["license_terms"]
            if plat == "wsl2":
                ev["integrated_distros"] = parsed["integrated"]
                ev["integration"], ev["integration_text"] = integration_verdict(parsed, environment.get("wsl_distro") or "")
    return ev


def windows_state(state, ev, environment):
    """Refine a state the in-distro / PATH probe could not explain, with the Windows-side evidence: Docker Desktop on the computer is never 'not installed'."""
    if not ev.get("installed") or environment.get("kind") not in ("windows", "wsl2") or state not in ("not_installed", "wsl_integration_off", "desktop_not_running", "daemon_stopped"):
        return state
    if ev.get("engine_up"):
        return "engine_up_wsl_integration_off" if environment.get("kind") == "wsl2" else state
    return "desktop_running_engine_down" if ev.get("running") else "installed_windows_not_running"


STAGE_LEVEL = {"not_installed": 0, "installed_windows_not_running": 1, "desktop_not_running": 1, "daemon_stopped": 1, "desktop_running_engine_down": 2,
               "engine_up_wsl_integration_off": 3, "wsl_integration_off": 3}


def stages_for(state, environment, ev=None):
    """The four stages as a checklist: [{'id', 'label', 'status': ok|pending|blocked|na, 'evidence'}]. The first stage that is not done is 'pending', the ones after it 'blocked'."""
    ev = ev or {}
    wsl = environment.get("kind") == "wsl2"
    level = 4 if state == "ready" else STAGE_LEVEL.get(state, 1 if state in ("permission_denied", "unknown") else 0)
    path = ev.get("desktop_exe") or ev.get("docker_exe")
    evidence = {"installed": ("Found " + path) if path else ("Docker Desktop %s is installed (winget)" % ev["desktop_version"] if ev.get("installed") else "Docker Desktop was not found in C:\\Program Files\\Docker\\Docker"),
                "running": {True: "Docker Desktop.exe is running", False: "Docker Desktop.exe is not running (tasklist)", None: "not checked"}[ev.get("running")],
                "engine": (ev.get("engine_detail") or ("docker info answered" if state == "ready" else "docker info did not answer")) + ("; Docker Desktop's settings record licence terms version %s as accepted" % ev["license_terms"] if ev.get("license_terms") else ""),
                "integration": ev.get("integration_text") or ("settings: " + ev["settings_path"] if ev.get("settings_path") else "Docker Desktop's settings file was not found")}
    rows = []
    for i, (sid, label) in enumerate(STAGES):
        if sid == "integration" and not wsl:
            status = "na"
        else:
            status = "ok" if i < level else ("pending" if i == level else "blocked")
        rows.append({"id": sid, "label": label, "status": status, "evidence": evidence[sid]})
    return rows


def next_action(state, environment, ev=None):
    """The single next action of a state: install | start | integration | recheck | '' (nothing)."""
    ev = ev or {}
    if state == "ready":
        return ""
    if state == "not_installed":
        return "install"
    if state in ("installed_windows_not_running", "desktop_not_running"):
        return "start" if (ev.get("desktop_exe") or environment.get("kind") == "macos") else "recheck"
    if state in ("engine_up_wsl_integration_off", "wsl_integration_off"):
        return "integration" if environment.get("kind") == "wsl2" else "recheck"
    return "recheck"


# ---------------------------------------------------------------- starting Docker Desktop and opening its WSL integration page (never the licence, never its settings)
def ps_quote(text):
    """A PowerShell single-quoted literal for `text`: every kind of single quote is doubled, so nothing in a path can end the string. Control characters and double quotes
    (never in a real Windows path) are refused."""
    if re.search(r'[\x00-\x1f"]', text or ""):
        raise ValueError("unsafe character in path")
    return "'" + re.sub("(['\u2018\u2019\u201a\u201b])", r"\1\1", text) + "'"


def start_argv(powershell, windows_path):
    """The exact argument list that starts Docker Desktop (no shell string): powershell.exe -NoProfile -Command Start-Process -FilePath '<path>'."""
    return [powershell, "-NoProfile", "-NonInteractive", "-Command", "Start-Process -FilePath " + ps_quote(windows_path)]


def uri_argv(powershell, uri):
    return [powershell, "-NoProfile", "-NonInteractive", "-Command", "Start-Process " + ps_quote(uri)]


def start_desktop(environment, ev, run=default_run, log=print):
    """Start Docker Desktop for this user: (ok, plain sentence). It only starts the program; the licence, its settings and its windows stay the user's."""
    kind = environment.get("kind")
    if kind == "macos":
        got = run(["open", "-a", "Docker"], 30)
        return (True, "Started Docker (open -a Docker).") if got is not None and got[0] == 0 else (False, "Could not start Docker with `open -a Docker`: start it from Applications.")
    exe = (ev or {}).get("desktop_exe") or ""
    if not exe:
        return False, "Docker Desktop.exe was not found in C:\\Program Files\\Docker\\Docker: start Docker Desktop from the Start menu."
    shell = environment.get("powershell")
    if not shell:
        return False, "PowerShell on the Windows side is not reachable (WSL interop may be off): start Docker Desktop from the Start menu."
    try:
        argv = start_argv(shell, to_windows_path(exe))
    except ValueError:
        return False, "The Docker Desktop path has a character PlasBench will not pass to PowerShell: start Docker Desktop from the Start menu."
    log("[PlasBench] Starting Docker Desktop: " + " ".join(argv))
    got = run(argv, 60)
    if got is None:
        return False, "Could not run PowerShell to start Docker Desktop: start it from the Start menu."
    if got[0] != 0:
        said = ((got[2] or got[1] or "").strip().splitlines() or ["no message"])[-1]
        blocked = " Windows or your security software may have blocked it." if re.search(r"access is denied|blocked|operation was canceled|not permitted", said, re.I) else ""
        return False, "Windows could not start Docker Desktop (%s).%s Start it from the Start menu." % (said, blocked)
    return True, "Docker Desktop was started. Its first start can take a few minutes."


def open_integration(environment, ev, run=default_run, log=print):
    """Open the place where WSL integration is switched on: Docker Desktop's own settings page by its docker-desktop:// link, else just its main window. -> (ok, sentence).
    The link's exact path is Docker's and is not verified here, so the sentence always says where to click if the page is not the one shown."""
    shell = environment.get("powershell")
    if not shell:
        return False, "PowerShell on the Windows side is not reachable: open Docker Desktop yourself and go to Settings > Resources > WSL integration."
    got = run(uri_argv(shell, INTEGRATION_URI), 30)
    if got is not None and got[0] == 0:
        return True, "Asked Docker Desktop to open its WSL integration page. If it opened on another page, click Settings > Resources > WSL integration."
    exe = (ev or {}).get("desktop_exe")
    if exe:
        got = run(start_argv(shell, to_windows_path(exe)), 30)
        if got is not None and got[0] == 0:
            return True, "Opened Docker Desktop (its settings link did not open). Click Settings > Resources > WSL integration."
    return False, "Could not open Docker Desktop: open it yourself and go to Settings > Resources > WSL integration."


def classify(version, info, environment=None):
    """The Docker state from the outputs of `docker --version` and `docker info`: each a (returncode, stdout, stderr) tuple, or None when the program could not be started.
    -> {'state', 'detail': the line that decided it, 'version': client version text}"""
    environment = environment or {}
    texts = [(r[1] + "\n" + r[2]) if r else "" for r in (version, info)]
    blob = "\n".join(texts)
    # the line that says what went wrong: docker info's own words when it ran, else docker --version's
    first = next((ln.strip() for text in reversed(texts) for ln in text.splitlines() if ln.strip()), "")
    ver = ""
    if version and version[0] == 0:
        m = re.search(r"Docker version ([^\s,]+)", version[1])
        ver = m.group(1) if m else version[1].strip()
    if WSL_OFF_RE.search(blob):
        return {"state": "wsl_integration_off", "detail": first, "version": ver}
    if version is None or (version[0] in (126, 127) and not re.search(r"docker version", version[1], re.I)):
        if environment.get("kind") == "wsl2" and environment.get("desktop_installed"):
            return {"state": "wsl_integration_off", "detail": "docker is not available in this WSL distro, but Docker Desktop is installed on Windows", "version": ""}
        return {"state": "not_installed", "detail": first or "docker was not found", "version": ""}
    if info is not None and info[0] == 0 and not re.search(r"cannot connect|error during connect", info[1] + info[2], re.I):
        return {"state": "ready", "detail": "docker info answered", "version": ver}
    if PERMISSION_RE.search(blob):
        return {"state": "permission_denied", "detail": first if "permission denied" in first.lower() else next((ln.strip() for ln in blob.splitlines() if "permission denied" in ln.lower()), first), "version": ver}
    if DAEMON_RE.search(blob):
        desktop = environment.get("kind") in ("windows", "macos") or (environment.get("kind") == "wsl2" and environment.get("desktop_installed")) or environment.get("desktop_installed")
        return {"state": "desktop_not_running" if desktop else "daemon_stopped", "detail": next((ln.strip() for ln in blob.splitlines() if DAEMON_RE.search(ln)), first), "version": ver}
    if environment.get("container"):
        return {"state": "in_container", "detail": first, "version": ver}
    return {"state": "unknown", "detail": first or "docker info did not succeed", "version": ver}


def probe(environment=None, run=default_run, which=shutil.which, exists=os.path.exists, env=None, timeout=20, deep=False, read=_read, globber=glob.glob):
    """Ask Docker: {'state', 'detail', 'version', 'server_version', 'context', 'exe', 'chip', 'chip_tone', 'evidence', 'stages', 'action'}. Runs `docker --version`, `docker info` and
    `docker context show`; on Windows and WSL 2 also looks, read-only, at Docker Desktop on the Windows side (files, tasklist, docker.exe info, its settings file; `deep`: winget list)."""
    environment = environment if environment is not None else detect_environment(env, which, exists)
    plat = "wsl2" if environment.get("kind") == "wsl2" else ("windows" if environment.get("kind") == "windows" else ("macos" if environment.get("kind") == "macos" else "linux"))
    exe = find_docker(env, which, exists, plat)
    version = run([exe or "docker", "--version"], timeout)
    info = run([exe or "docker", "info"], timeout) if version and version[0] == 0 else None
    res = classify(version, info, environment)
    if res["state"] == "not_installed" and environment.get("container"):
        res["state"] = "in_container"
    res.update(server_version="", context="", exe=exe or "")
    if res["state"] == "ready":
        sv = re.search(r"^\s*Server Version:\s*(\S+)", info[1], re.M)
        res["server_version"] = sv.group(1) if sv else ""
        ctx = run([exe or "docker", "context", "show"], timeout)
        res["context"] = ctx[1].strip() if ctx and ctx[0] == 0 else ""
    ev = {}
    if environment.get("kind") in ("windows", "wsl2") and res["state"] not in ("ready", "in_container", "permission_denied"):
        ev = windows_evidence(environment, run, which, exists, env, read, globber, timeout, deep)
        refined = windows_state(res["state"], ev, environment)
        if refined != res["state"]:
            res["state"] = refined
            res["detail"] = (ev.get("integration_text") or ev.get("engine_detail") or res["detail"]) if refined == "engine_up_wsl_integration_off" else (ev.get("engine_detail") or res["detail"])
    res["evidence"] = ev
    res["stages"] = stages_for(res["state"], environment, ev)
    res["action"] = next_action(res["state"], environment, ev)
    res["chip"], res["chip_tone"] = CHIPS.get(res["state"], CHIPS["unknown"])
    return res


# ---------------------------------------------------------------- the copyable sudo scripts (static text; nothing here is ever run by PlasBench)
def _wsl_note(wsl):
    return ("# WSL: Docker Engine needs systemd. If /etc/wsl.conf has no [boot] systemd=true, run the next line, then in Windows PowerShell run  wsl --shutdown  and reopen Ubuntu.\n"
            "#   printf '[boot]\\nsystemd=true\\n' | sudo tee -a /etc/wsl.conf\n") if wsl else ""


def linux_script(family, distro_id="ubuntu", variant="official", wsl=False):
    """The commands that install Docker Engine for a distro family (apt, dnf, pacman, zypper): the user runs this in a terminal with their own sudo. `variant`: 'official' is
    Docker's own repository (docs.docker.com/engine/install); 'distro' is the distribution's own package, the simpler alternative."""
    head = ["#!/usr/bin/env bash", "# Install Docker Engine. PlasBench does not run this for you: read it, then run it in a terminal; sudo asks for YOUR password.",
            "set -euo pipefail", ""]
    tail = ["", "# After installing: start the service, then let your user use docker without sudo (log out and back in, or run `newgrp docker`, for the group to apply).",
            "sudo systemctl enable --now docker", 'sudo usermod -aG docker "$USER"', "# newgrp docker    (or log out and back in: the group applies to new sessions)", "",
            "# Check:", "docker --version", "docker info", "# Rootless Docker (no sudo, no root daemon) is an alternative: " + ROOTLESS_URL, "# Post-install steps: " + POSTINSTALL_URL]
    note = _wsl_note(wsl)
    if family == "apt" and variant == "distro":
        body = ["# The distribution's own package (older than Docker's repository, simpler, signed by your distribution's keys).",
                "sudo apt-get update", "sudo apt-get install -y docker.io docker-compose-v2 docker-buildx"]
        return "\n".join(head + ([note.rstrip("\n")] if note else []) + body + tail) + "\n"
    if family == "apt":
        d = "debian" if distro_id == "debian" else "ubuntu"
        codename = '${VERSION_CODENAME}' if d == "debian" else '${UBUNTU_CODENAME:-$VERSION_CODENAME}'
        body = [f"# Docker's own apt repository ({ENGINE_URLS[d]}).", "sudo apt-get update", "sudo apt-get install -y ca-certificates curl gnupg",
                "sudo install -m 0755 -d /etc/apt/keyrings", f"sudo curl -fsSL https://download.docker.com/linux/{d}/gpg -o /etc/apt/keyrings/docker.asc", "sudo chmod a+r /etc/apt/keyrings/docker.asc",
                "# Verify the signing key before trusting it: Docker publishes this fingerprint on its install page.",
                f'EXPECTED="{DOCKER_KEY_FPR_APT}"',
                "ACTUAL=\"$(gpg --show-keys --with-colons /etc/apt/keyrings/docker.asc | awk -F: '/^fpr:/ {print $10; exit}')\"",
                'if [ "$ACTUAL" != "$EXPECTED" ]; then echo "Docker signing key fingerprint does not match: stop." >&2; exit 1; fi',
                f'echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/{d} $(. /etc/os-release && echo "{codename}") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null',
                "sudo apt-get update", "sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin"]
        return "\n".join(head + ([note.rstrip("\n")] if note else []) + body + tail) + "\n"
    if family == "dnf":
        d = "fedora" if distro_id == "fedora" else "centos"
        if variant == "distro":
            body = ["# The distribution's own package (Fedora ships `moby-engine`; RHEL-family systems use Docker's repository instead).", "sudo dnf install -y moby-engine docker-compose"]
        else:
            body = [f"# Docker's own dnf repository ({ENGINE_URLS[d]}).", "sudo dnf -y install dnf-plugins-core",
                    f"sudo dnf config-manager addrepo --from-repofile=https://download.docker.com/linux/{d}/docker-ce.repo",
                    "# Verify the signing key: when dnf asks to import it, the fingerprint must be " + DOCKER_KEY_FPR_RPM + " (060A 61C5 1B55 8A7F 742B 77AA C52F EB6B 621E 9F35).",
                    "sudo dnf install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin"]
        return "\n".join(head + ([note.rstrip("\n")] if note else []) + body + tail) + "\n"
    if family == "pacman":
        body = ["# Arch's own repository (packages signed by the Arch keyring).", "sudo pacman -S --needed docker docker-buildx docker-compose"]
        return "\n".join(head + body + tail) + "\n"
    if family == "zypper":
        body = ["# openSUSE's own repository.", "sudo zypper --non-interactive install docker docker-compose docker-buildx"]
        return "\n".join(head + body + tail) + "\n"
    return ""


# ---------------------------------------------------------------- translating exit codes
def signed(code):
    return code - 2 ** 32 if isinstance(code, int) and code > 2 ** 31 - 1 else code


def translate_winget(code):
    """(kind, plain sentence) for a winget exit code: kind is 'ok', 'restart', 'already', 'declined', 'notfound' or 'failed'."""
    code = signed(code)
    if code == 0:
        return "ok", "winget installed Docker Desktop."
    if code == 3010:
        return "restart", "Docker Desktop is installed; Windows needs a restart to finish."
    if code in (1602, 1223, -2147023673):
        return "declined", "The Windows approval prompt (UAC) was declined or closed, so nothing was installed. Run Install Docker again and choose Yes in the prompt."
    if code == -1978335189:
        return "already", "winget reports Docker Desktop is already installed and up to date (no upgrade applies)."
    if code == -1978335212:
        return "notfound", "winget could not find the package Docker.DockerDesktop (its package sources may need updating: run `winget source update` in Windows)."
    return "failed", f"winget stopped with exit code {code}. The lines above are winget's own words; the Docker Desktop installer page is the manual alternative."


def translate_brew(code, text=""):
    if code == 0:
        return "ok", "Homebrew installed Docker Desktop."
    if re.search(r"No Cask with this name|Cask '.*' is unavailable|not found", text or "", re.I):
        return "notfound", "Homebrew does not know that cask name."
    if re.search(r"password|sudo|authentication", text or "", re.I):
        return "declined", "The macOS installer needed your password and it was not given, so nothing was installed."
    return "failed", f"Homebrew stopped with exit code {code}."


def winget_argv(winget):
    """The exact argument list: no shell string."""
    return [winget, "install", "-e", "--id", WINGET_ID, "--accept-package-agreements", "--accept-source-agreements"]


def brew_argv(brew, cask=BREW_CASKS[0]):
    return [brew, "install", "--cask", cask]


# ---------------------------------------------------------------- the plan
def make_plan(environment, st):
    """What `install` will do in this environment and Docker state, without doing it:
    {'route': ready|winget|brew|script|links|guide|container, 'place', 'runs': argv or None, 'who_elevates', 'internet': [services], 'licence': text, 'steps': [...], 'links': [...],
    'scripts': {name: text}, 'summary'}."""
    kind, state = environment["kind"], st["state"]
    plan = {"route": "guide", "action": "install", "installed": "", "place": "", "runs": None, "who_elevates": "", "internet": [], "licence": "", "steps": [], "links": [("The Docker guide", GUIDE_URL)], "scripts": {},
            "summary": "", "size": "not measured"}
    if state == "ready":
        plan.update(route="ready", summary="Docker is already working; nothing to install.")
        return plan
    if state == "in_container":
        plan.update(route="container", place="the computer that hosts this container",
                    summary="This is inside a container. Docker-in-Docker is out of scope for PlasBench: install Docker on the computer that hosts the container and run PlasBench there (or mount the Docker socket yourself).")
        plan["steps"] = ["Open a terminal on the host computer (outside the container).", "Run `plasbench install-tools docker` there."]
        return plan
    desktop_licence = ("Docker Desktop is covered by Docker's subscription terms (free for personal use, education and small businesses; a paid plan may be required for larger companies). "
                       "PlasBench cannot accept the licence for you: Docker Desktop asks you to accept it the first time you start it. " + LICENCE_URL)
    post_windows = ["Start Docker Desktop from the Start menu (first launch can take a few minutes).", "Read and accept the Docker Subscription Service Agreement when Docker Desktop asks (" + LICENCE_URL + "). PlasBench cannot accept it for you.",
                    "Keep the WSL 2 based engine on (Settings > General > Use the WSL 2 based engine).",
                    "In Docker Desktop: Settings > Resources > WSL integration > turn on your Ubuntu distro, then Apply & restart.",
                    "If Docker Desktop asks for it, restart WSL: in Windows PowerShell run `wsl --shutdown`, then reopen Ubuntu.", "Then press Re-check in PlasBench (or run `plasbench install-tools docker`)."]
    if state in ("daemon_stopped", "desktop_not_running", "permission_denied", "wsl_integration_off", "unknown") + WIN_STATES:
        d = diagnose(st, environment)
        plan.update(route="guide", summary=d["title"], steps=d["steps"], place=d["place"], action=d["action"])
        ev = st.get("evidence") or {}
        if state in WIN_STATES or ev.get("installed"):
            ver = ev.get("desktop_version")
            plan["installed"] = "Docker Desktop%s is already installed (%s); nothing to install." % (" " + ver if ver else "", "winget" if ev.get("installed_via") == "winget" else "found on this computer")
        return plan
    # not installed
    if kind in ("windows", "wsl2"):
        plan.update(licence=desktop_licence, who_elevates="Windows asks you to approve the installer (a UAC prompt on your screen). PlasBench never sees an administrator password.", size="about 600 MB download (not measured)")
        if kind == "wsl2" and environment.get("interop") is False:
            plan.update(route="links", place="Windows", summary="WSL interop is off, so PlasBench cannot start winget on the Windows side.",
                        steps=["Install Docker Desktop from Windows yourself: " + DESKTOP_WINDOWS_URL, "Or run in a Windows PowerShell: winget install -e --id " + WINGET_ID] + post_windows)
        elif environment.get("winget"):
            plan.update(route="winget", place="Docker Desktop", runs=winget_argv(environment["winget"]), internet=SERVICES["winget"],
                        summary="Docker Desktop with the WSL 2 backend, installed through winget on the Windows side.", steps=post_windows)
        else:
            plan.update(route="links", place="Windows", summary="winget was not found" + (" on the Windows side" if kind == "wsl2" else "") + ", so PlasBench cannot start the install for you (it never downloads and runs an installer silently).",
                        steps=["Download Docker Desktop yourself from the official page and run it: " + DESKTOP_WINDOWS_URL, "If WSL is not set up yet, in Windows PowerShell run `wsl --install` first: " + WSL_INSTALL_URL] + post_windows)
        plan["links"] = [("Install Docker Desktop on Windows", DESKTOP_WINDOWS_URL), ("WSL integration", WSL_INTEGRATION_URL), ("Docker Desktop licence", LICENCE_URL)]
        if kind == "wsl2" and environment.get("package_manager") == "apt":
            plan["scripts"]["advanced"] = linux_script("apt", environment.get("distro_id") or "ubuntu", "official", wsl=True)
            plan["links"].append(("Advanced: Docker Engine inside WSL (needs sudo)", ENGINE_URLS.get(environment.get("distro_id") or "ubuntu", ENGINE_URLS["ubuntu"])))
        return plan
    if kind == "wsl1":
        plan.update(route="links", place="Windows", summary="This is WSL 1, which Docker cannot use. Upgrade the distro to WSL 2 (in PowerShell: `wsl --set-version <distro> 2`), then install Docker Desktop on Windows.",
                    steps=["In Windows PowerShell: wsl --set-version <your distro> 2", "Then run `plasbench install-tools docker` again."])
        plan["links"] = [("Install WSL", WSL_INSTALL_URL), ("Install Docker Desktop on Windows", DESKTOP_WINDOWS_URL)]
        return plan
    if kind == "macos":
        plan.update(licence=desktop_licence, who_elevates="The Docker Desktop installer asks for your macOS password itself; PlasBench never sees it.", size="about 700 MB download (not measured)")
        steps = ["Open Docker: `open -a Docker` (first launch can take a few minutes).", "Accept Docker's subscription terms when it asks (" + LICENCE_URL + "). PlasBench cannot accept them for you.",
                 "Wait until the whale icon says Docker Desktop is running, then press Re-check (or run `plasbench install-tools docker`)."]
        if environment.get("brew"):
            plan.update(route="brew", place="Docker Desktop", runs=brew_argv(environment["brew"]), internet=SERVICES["brew"], summary="Docker Desktop through Homebrew.", steps=steps)
        else:
            plan.update(route="links", place="your browser", summary="Homebrew was not found, so PlasBench cannot install Docker Desktop for you.",
                        steps=["Download Docker Desktop for your Mac (Apple silicon or Intel) from the official page and drag it to Applications: " + DESKTOP_MAC_URL] + steps)
        plan["links"] = [("Install Docker Desktop on Mac", DESKTOP_MAC_URL), ("Docker Desktop licence", LICENCE_URL)]
        return plan
    # linux
    fam, did = environment.get("package_manager") or "", environment.get("distro_id") or ""
    plan.update(route="script", place="a terminal", who_elevates="You run the script in a terminal; sudo asks for your own password. PlasBench does not run it.", links=[("Docker Engine install guide", ENGINE_URLS.get(did, GUIDE_URL)), ("Rootless Docker (no sudo)", ROOTLESS_URL), ("Post-install steps", POSTINSTALL_URL), ("Docker Desktop for Linux", DESKTOP_LINUX_URL)])
    if fam:
        plan["scripts"]["official"] = linux_script(fam, did, "official")
        if fam in ("apt", "dnf"):
            plan["scripts"]["distro"] = linux_script(fam, did, "distro")
        plan["summary"] = "Docker Engine from the %s package manager. Run the script in a terminal with your own sudo." % fam
        plan["steps"] = ["Copy the script below into a terminal (or save it and run it with bash) and enter your password when sudo asks.", "Log out and back in (or run `newgrp docker`) so your user can use docker without sudo.", "Press Re-check (or run `plasbench install-tools docker`)."]
        if not environment.get("systemd"):
            plan["steps"].insert(1, "This system does not run systemd: start the Docker daemon with your init system (for example `sudo service docker start`).")
    else:
        plan.update(route="links", place="a terminal", summary="This Linux distribution is not one PlasBench has a script for. Use Docker's own page for it.", steps=["Open " + GUIDE_URL + " and follow the steps for your distribution."])
    return plan


def diagnose(st, environment=None):
    """A precise diagnosis and the next step for a state that is not 'not installed': {'state', 'title', 'detail', 'steps', 'place', 'chip'}."""
    environment = environment or {}
    state, kind = st["state"], environment.get("kind", "linux")
    steps, place, title = [], "", ""
    chip = CHIPS.get(state, CHIPS["unknown"])
    if state == "ready":
        title = "Docker is working" + (f" (client {st.get('version')}, server {st.get('server_version')})" if st.get("version") else "") + "."
    elif state == "not_installed":
        title = "Docker is not installed."
        steps = ["Run `plasbench install-tools docker` (or press Install Docker in the window)."]
    elif state == "daemon_stopped":
        title, place = "Docker is installed but its daemon is not running.", "a terminal"
        steps = ["Start it: `sudo systemctl start docker` (and `sudo systemctl enable docker` to start it at every boot), or `sudo service docker start` without systemd.", "Press Re-check."]
    elif state == "desktop_not_running":
        title, place = "Docker is installed but Docker Desktop is not running.", "Docker Desktop"
        steps = ["Start Docker Desktop (Start menu on Windows, `open -a Docker` on macOS) and wait until it says it is running.", "Accept the licence if Docker Desktop asks (PlasBench cannot accept it for you).", "Press Re-check."]
    elif state == "permission_denied":
        title, place = "Docker is running, but your user may not use it (permission denied on /var/run/docker.sock).", "a terminal"
        steps = ['Add yourself to the docker group: `sudo usermod -aG docker "$USER"`.', "Log out and back in (or run `newgrp docker` in this terminal) so the group applies.", "Press Re-check. Rootless Docker avoids this: " + ROOTLESS_URL]
    elif state == "installed_windows_not_running":
        ver = (st.get("evidence") or {}).get("desktop_version")
        wsl = kind == "wsl2"
        title, place = "Docker Desktop is installed on Windows" + (f" (version {ver})" if ver else "") + " but is not running.", "Docker Desktop"
        steps = ["Start Docker Desktop: press Start Docker Desktop in the window, run `plasbench install-tools docker --start`, or open it from the Start menu. The first start can take a few minutes.",
                 "Read and accept the Docker licence when Docker Desktop asks (" + LICENCE_URL + "). PlasBench never accepts it for you."]
        if wsl:
            steps.append("In Docker Desktop: Settings > Resources > WSL integration > turn on " + (environment.get("wsl_distro") or "your Linux distro") + ", then Apply & restart.")
        steps.append("Press Re-check.")
    elif state == "desktop_running_engine_down":
        title, place = "Docker Desktop is running, but its engine does not answer yet.", "Docker Desktop"
        steps = ["Wait for Docker Desktop to finish starting (the first start can take a few minutes).",
                 "If its window shows the licence (the Docker Subscription Service Agreement), Docker Desktop is waiting for you: switch to its window and accept it. PlasBench cannot accept it for you.",
                 "Press Re-check."]
    elif state == "engine_up_wsl_integration_off":
        distro = environment.get("wsl_distro") or "this Linux distro"
        ev = st.get("evidence") or {}
        title, place = f"Docker Desktop is running on Windows, but its WSL integration is off for {distro}.", "Docker Desktop"
        steps = [f"In Docker Desktop: Settings > Resources > WSL integration > turn on {distro}, then Apply & restart (press Open WSL integration settings to open Docker Desktop).",
                 "This is what `The command 'docker' could not be found in this WSL 2 distro` means: docker.exe works on Windows, the distro has no docker command until it is integrated.",
                 "If `docker` is still not found afterwards, run `wsl --shutdown` in Windows PowerShell and reopen the distro.", "Press I enabled it (PlasBench checks every 5 seconds for 3 minutes) or Re-check."]
        if ev.get("integration_text"):
            steps.insert(1, ev["integration_text"])
    elif state == "wsl_integration_off":
        title, place = "Docker Desktop is installed on Windows, but its WSL integration is off for this Linux distro.", "Docker Desktop"
        steps = ["In Docker Desktop: Settings > Resources > WSL integration > turn on this distro" + (f" ({environment.get('wsl_distro')})" if environment.get("wsl_distro") else "") + ", then Apply & restart.",
                 "If the `docker` command is still not found, run `wsl --shutdown` in Windows PowerShell and reopen the distro.", "Press Re-check."]
    elif state == "in_container":
        title, place = "This is inside a container; Docker-in-Docker is out of scope for PlasBench.", "the host computer"
        steps = ["Install and use Docker on the computer that hosts the container."]
    else:
        title, place = "Docker is installed but `docker info` did not succeed.", "a terminal"
        steps = ["Run `docker info` in a terminal and read its message: " + (st.get("detail") or "no output"), "Press Re-check after fixing it."]
    return {"state": state, "title": title, "detail": st.get("detail", ""), "steps": steps, "place": place, "chip": chip[0], "tone": chip[1], "action": st.get("action") or next_action(state, environment, st.get("evidence"))}


# ---------------------------------------------------------------- recording
def state_dir(env=None):
    env = os.environ if env is None else env
    return Path(env.get("PLASBENCH_STATE_DIR") or (Path(env.get("HOME") or env.get("USERPROFILE") or str(Path.home())) / ".plasbench"))


def record(st, env=None):
    """Write the verified state (version, server version, context) where `plasbench check` and the run manifest read it. Returns the path or None."""
    data = {"state": st["state"], "version": st.get("version", ""), "server_version": st.get("server_version", ""), "context": st.get("context", ""), "exe": st.get("exe", ""),
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        folder = state_dir(env)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / STATUS_NAME
        tmp = folder / (STATUS_NAME + ".tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
        os.replace(tmp, path)
        return path
    except OSError:
        return None


def recorded(env=None):
    try:
        with open(state_dir(env) / STATUS_NAME, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def check_line(st):
    """The one line `plasbench check` prints for Docker (optional: it never makes the check fail)."""
    d = diagnose(st)
    if st["state"] == "ready":
        return "  [ok]   docker (optional): ready, client %s, server %s, context %s" % (st.get("version") or "?", st.get("server_version") or "?", st.get("context") or "?")
    nxt = {"start": "plasbench install-tools docker --start", "integration": "plasbench install-tools docker --open-integration"}.get(d.get("action"), "plasbench install-tools docker")
    return "  [--]   docker (optional): %s Next: %s" % (d["title"], nxt)


# ---------------------------------------------------------------- rendering and installing
def render_plan(plan, st, environment):
    lines = ["[PlasBench] Docker setup plan", "  Computer : " + {"windows": "Windows", "wsl2": "WSL 2 (Linux on Windows)" + (f", distro {environment.get('wsl_distro')}" if environment.get("wsl_distro") else ""), "wsl1": "WSL 1", "macos": "macOS",
                                                           "linux": "Linux" + (f" ({environment.get('distro')})" if environment.get("distro") else ""), "container": "inside a container"}.get(environment["kind"], environment["kind"]),
             "  Docker   : " + diagnose(st, environment)["title"], "  Route    : " + plan["route"] + (" - " + plan["summary"] if plan["summary"] else "")]
    if plan.get("installed"):
        lines.append("  Installed: " + plan["installed"])
    if plan["runs"]:
        lines.append("  Runs     : " + " ".join(plan["runs"]))
    if plan["who_elevates"]:
        lines.append("  Elevation: " + plan["who_elevates"])
    if plan["licence"]:
        lines.append("  Licence  : " + plan["licence"])
    if plan["internet"]:
        lines.append("  Internet : needed (" + ", ".join(plan["internet"]) + "); size " + plan["size"])
    for i, step in enumerate(plan["steps"], 1):
        lines.append(f"  {i}. {step}")
    for name, text in plan["scripts"].items():
        lines += ["", f"  --- script: {name} (run it yourself in a terminal; PlasBench never runs it) ---"] + ["  " + ln for ln in text.splitlines()] + ["  --- end of script ---"]
    for label, url in plan["links"]:
        lines.append(f"  {label}: {url}")
    return "\n".join(lines)


def wait_ready(check, timeout, interval=5.0, sleep=time.sleep, log=print, clock=time.monotonic, progress=0.0, stop=()):
    """Poll until check() answers a ready state, a state in `stop` (one only a person can fix) or `timeout` seconds pass; each new state is reported once, and with
    `progress` > 0 also a line every that many seconds so a long wait is never silent."""
    start, last, st, next_note = clock(), None, None, progress
    while True:
        st = check()
        if st["state"] != last:
            log(f"[PlasBench] Docker state: {CHIPS.get(st['state'], CHIPS['unknown'])[0]}" + (f" ({st['detail']})" if st.get("detail") and st["state"] != "ready" else ""))
            last = st["state"]
        elapsed = clock() - start
        if st["state"] == "ready" or st["state"] in stop or elapsed >= timeout:
            return st
        if progress and elapsed >= next_note:
            log(f"[PlasBench] Still waiting: {CHIPS.get(st['state'], CHIPS['unknown'])[0]} ({int(elapsed)} s of {int(timeout)} s). Press Ctrl+C to stop; nothing is lost.")
            next_note = elapsed + progress
        sleep(interval)


def _settle(recheck, sleep, tries=4, pause=None):
    """Right after an installer finishes its files can take a moment to show up: look again a few times, but only while nothing at all is found."""
    pause = float(os.environ.get("PLASBENCH_DOCKER_SETTLE", "3")) if pause is None else pause
    st = recheck()
    for _ in range(tries - 1):
        if st["state"] != "not_installed":
            break
        sleep(pause)
        st = recheck()
    return st


def _handoff(environment, st, plan, log, show_plan=False):
    """Exit 20: what is left only the user can do. The line `Waiting for you to finish in <place> (exit 20` is parsed by the window."""
    d = diagnose(st, environment)
    if show_plan:
        log(render_plan(plan, st, environment))
    steps = plan["steps"] if st["state"] == "not_installed" else d["steps"]
    place = d["place"] if st["state"] != "not_installed" and d["place"] else (plan["place"] or "Docker Desktop")
    if show_plan and not plan["runs"] and st["state"] != "ready":
        log(f"[PlasBench] Waiting for you to finish in {place or 'a terminal'} (exit 20: nothing failed, nothing was run). When you have done the steps above, press Re-check or run `plasbench install-tools docker` again.")
        return EXIT_HANDOFF
    log(f"[PlasBench] Waiting for you to finish in {place} (exit 20: nothing failed). Docker is installed but not ready yet; what is left only you can do:")
    for i, step in enumerate(steps, 1):
        log(f"  {i}. {step}")
    return EXIT_HANDOFF


def _conclude(environment, plan, final, hello, run, log, env):
    if final["state"] == "ready":
        record(final, env)
        log("[PlasBench] " + diagnose(final, environment)["title"])
        return _hello(run, log) if hello else EXIT_OK
    if final["state"] == "desktop_running_engine_down":
        log("[PlasBench] Docker Desktop is running but its engine still does not answer. It is most likely waiting for you to accept the licence: switch to the Docker Desktop window "
            "(PlasBench never accepts it for you), or give the first start a few more minutes.")
    return _handoff(environment, final, plan, log)


def _continue(environment, plan, st, start, wait, open_integ, hello, run, recheck, sleep, log, env, clock, just_installed, show_plan):
    """From the Docker state now: start Docker Desktop when asked (--start), poll only where polling can succeed, and hand the rest to the user. Returns the exit code."""
    kind, state, ev = environment.get("kind"), st["state"], st.get("evidence") or {}
    if state == "ready":
        return _conclude(environment, plan, st, hello, run, log, env)
    if state in ("installed_windows_not_running", "desktop_not_running") and kind in ("windows", "wsl2", "macos"):
        ver = ev.get("desktop_version")
        if just_installed and state == "installed_windows_not_running":
            log("[PlasBench] Docker Desktop was installed on Windows%s. It is not running yet." % (f" (version {ver})" if ver else ""))
        elif show_plan:
            log(render_plan(plan, st, environment))
            show_plan = False
        if not start:
            log("[PlasBench] Nothing to wait for until Docker Desktop is started. PlasBench can start it for you (it never accepts the licence or changes Docker's settings): "
                "run `plasbench install-tools docker --start`, or press Start Docker Desktop in the window.")
            return _handoff(environment, st, plan, log, show_plan)
        ok, said = start_desktop(environment, ev, run, log)
        log("[PlasBench] " + said)
        if not ok:
            return _handoff(environment, st, plan, log)
        limit = 90.0 if wait is None else float(wait)
        log("[PlasBench] Waiting for the Docker engine to answer (up to %d s); a line is shown every 10 s." % int(limit))
        final = wait_ready(recheck, limit, 5.0, sleep, log, clock, 10.0, HUMAN_STATES) if limit > 0 else recheck()
        return _conclude(environment, plan, final, hello, run, log, env)
    if state == "desktop_running_engine_down":
        limit = 90.0 if wait is None else float(wait)
        if limit > 0:
            log("[PlasBench] Docker Desktop is running; waiting for its engine to answer (up to %d s); a line is shown every 10 s." % int(limit))
            final = wait_ready(recheck, limit, 5.0, sleep, log, clock, 10.0, HUMAN_STATES)
        else:
            final = st
        return _conclude(environment, plan, final, hello, run, log, env)
    if state in ("engine_up_wsl_integration_off", "wsl_integration_off") and kind == "wsl2" and open_integ:
        ok, said = open_integration(environment, ev, run, log)
        log("[PlasBench] " + said)
        limit = 180.0 if wait is None else float(wait)
        if ok and limit > 0:
            log("[PlasBench] Waiting up to %d s for you to switch WSL integration on; checking every 5 s." % int(limit))
            final = wait_ready(recheck, limit, 5.0, sleep, log, clock, 15.0, ("permission_denied",))
            return _conclude(environment, plan, final, hello, run, log, env)
    return _handoff(environment, st, plan, log, show_plan)


def install(environment, st, yes=False, dry_run=False, wait=None, hello=False, route=None, run=default_run, recheck=None, sleep=time.sleep, log=print, env=None, start=False,
            open_integ=False, clock=time.monotonic):
    """Do what the plan says where a user-level process may; hand off the rest. Returns 0 (verified working), 20 (handed off), 21 (needs consent) or 1 (failed).
    `wait` is how long to poll the engine afterwards: by default 90 s only where Docker Desktop is running (it can answer soon), else 0 (a person has to act first)."""
    plan = make_plan(environment, st)
    fast = recheck or (lambda: probe(environment, run=run, env=env))
    deep = recheck or (lambda: probe(environment, run=run, env=env, deep=True))
    if st["state"] == "ready":
        log("[PlasBench] " + diagnose(st, environment)["title"])
        record(st, env)
        if hello:
            return _hello(run, log)
        return EXIT_OK
    if dry_run:
        log(render_plan(plan, st, environment))
        log("[PlasBench] dry run: nothing was installed or started.")
        return EXIT_OK
    if plan["route"] in ("winget", "brew") and route == "advanced" and plan["scripts"].get("advanced"):
        plan.update(route="script", runs=None, place="a terminal")
    if plan["route"] in ("winget", "brew"):
        if not yes:
            log(render_plan(plan, st, environment))
            log("[PlasBench] Consent needed (exit 21): nothing was changed. Read the plan above; run the same command with --yes to start the installer.")
            return EXIT_CONSENT
        if _offline():
            log("[PlasBench] ERROR: PLASBENCH_OFFLINE is set; the installer needs the internet.")
            return EXIT_FAIL
        log(render_plan(plan, st, environment))
        log("[PlasBench] Starting: " + " ".join(plan["runs"]))
        log("[PlasBench] " + plan["who_elevates"])
        argv = plan["runs"]
        got = run(argv, 1800)
        if got is None:
            log("[PlasBench] ERROR: could not start " + argv[0])
            return EXIT_FAIL
        out = (got[1] or "") + (got[2] or "")
        for line in out.splitlines():
            if line.strip():
                log("  | " + line.rstrip())
        kind, sentence = translate_winget(got[0]) if plan["route"] == "winget" else translate_brew(got[0], out)
        if plan["route"] == "brew" and kind == "notfound" and argv[-1] == BREW_CASKS[0]:
            argv = brew_argv(argv[0], BREW_CASKS[1])
            log("[PlasBench] That cask name is unknown to this Homebrew; trying the older name: " + " ".join(argv))
            got = run(argv, 1800)
            out = ((got[1] or "") + (got[2] or "")) if got else ""
            kind, sentence = translate_brew(got[0], out) if got else ("failed", "could not start brew")
        log("[PlasBench] " + sentence)
        if kind == "declined":
            log("[PlasBench] Nothing was installed (exit 1).")
            return EXIT_FAIL
        if kind in ("notfound", "failed"):
            return EXIT_FAIL
        # The install ran (or Docker Desktop was already there). Look at what is really on the computer now, instead of waiting blindly: its first launch, the licence and
        # WSL integration are the user's steps, and nothing can answer before Docker Desktop is started.
        now = _settle(deep, sleep)
        if now["state"] == "not_installed":
            log("[PlasBench] The installer reported success, but Docker Desktop is not visible to PlasBench yet (looked for %s). It may need a minute, or a restart of Windows; "
                "press Re-check in a moment." % ("C:\\Program Files\\Docker\\Docker\\" + DESKTOP_EXE if environment.get("kind") in ("windows", "wsl2") else "Docker"))
        return _continue(environment, plan, now, start, wait, open_integ, hello, run, fast, sleep, log, env, clock, True, False)
    # no installer to run: the precise diagnosis, and what can be done now (start Docker Desktop with --start) or must be done by the user
    return _continue(environment, plan, st, start, wait, open_integ, hello, run, fast, sleep, log, env, clock, False, True)


def _hello(run, log):
    if _offline():
        log("[PlasBench] ERROR: PLASBENCH_OFFLINE is set; the hello-world image must be pulled from the internet.")
        return EXIT_FAIL
    got = run(HELLO_ARGV, 300)
    if got and got[0] == 0 and "Hello from Docker" in (got[1] or "") + (got[2] or ""):
        log("[PlasBench] `docker run --rm hello-world` worked: containers run.")
        return EXIT_OK
    log("[PlasBench] ERROR: `docker run --rm hello-world` did not work: " + ((got[2] or got[1] or "").strip().splitlines() or ["no output"])[-1])
    return EXIT_FAIL


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("state", "diagnose", "plan", "install", "route", "script", "status", "check-line", "services"))
    p.add_argument("name", nargs="?", help="script: apt | dnf | pacman | zypper")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--hello-world", action="store_true", help="also run `docker run --rm hello-world` (needs the internet; off by default)")
    p.add_argument("--wait", type=float, default=(float(os.environ["PLASBENCH_DOCKER_WAIT"]) if os.environ.get("PLASBENCH_DOCKER_WAIT", "").strip() else None),
                   help="seconds to poll the engine afterwards: default 90 where Docker Desktop is running (or was just started), 0 where a person has to act first")
    p.add_argument("--start", action="store_true", help="start Docker Desktop (Windows, WSL 2, macOS) when it is installed but not running, then poll the engine; never accepts the licence")
    p.add_argument("--open-integration", action="store_true", help="WSL 2: open Docker Desktop's WSL integration settings, then check every 5 s (up to 3 min) for you to switch it on")
    p.add_argument("--route", choices=("advanced",), help="advanced: the Docker Engine script instead of Docker Desktop (WSL)")
    p.add_argument("--variant", choices=("official", "distro"), default="official")
    p.add_argument("--distro", default="ubuntu")
    p.add_argument("--wsl", action="store_true")
    a = p.parse_args(argv)
    if a.action == "script":
        text = linux_script(a.name or "apt", a.distro, a.variant, a.wsl)
        if not text:
            print("unknown family", file=sys.stderr)
            return 2
        sys.stdout.write(text)
        return 0
    environment = detect_environment()
    if a.action == "status":
        data = recorded()
        print(json.dumps(data or {}, indent=2))
        return 0
    st = probe(environment, timeout=10 if a.action == "check-line" else 20, deep=a.action in ("state", "diagnose", "plan", "install"))
    if a.action == "services":
        plan = make_plan(environment, st)
        print(" ".join(plan["internet"]))
        return 0
    if a.action == "route":
        print(make_plan(environment, st)["route"])
        return 0
    if a.action == "check-line":
        print(check_line(st))
        return 0
    if a.action == "state":
        if st["state"] == "ready":
            record(st)
        print(json.dumps(dict(st, environment=environment, diagnosis=diagnose(st, environment)), indent=2) if a.json else diagnose(st, environment)["title"])
        return 0 if st["state"] == "ready" else 1
    if a.action == "diagnose":
        d = diagnose(st, environment)
        print(json.dumps(d, indent=2) if a.json else "\n".join([d["title"]] + (["  " + d["detail"]] if d["detail"] else []) + [f"  {i}. {s}" for i, s in enumerate(d["steps"], 1)]))
        return 0
    if a.action == "plan":
        plan = make_plan(environment, st)
        print(json.dumps(dict(plan, state=st["state"], environment=environment), indent=2) if a.json else render_plan(plan, st, environment))
        return 0
    return install(environment, st, yes=a.yes, dry_run=a.dry_run, wait=a.wait, hello=a.hello_world, route=a.route, start=a.start, open_integ=a.open_integration)


if __name__ == "__main__":
    raise SystemExit(main())
