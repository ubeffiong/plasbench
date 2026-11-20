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
import os
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
STATES = ("ready", "not_installed", "daemon_stopped", "permission_denied", "wsl_integration_off", "desktop_not_running", "in_container", "unknown")
CHIPS = {"ready": ("Ready", "ok"), "not_installed": ("Not installed", "bad"), "daemon_stopped": ("Installed, daemon stopped", "warn"),
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
    found = which("docker") or (which("docker.exe") if plat in ("windows", "wsl2") else None)
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


def probe(environment=None, run=default_run, which=shutil.which, exists=os.path.exists, env=None, timeout=20):
    """Ask Docker: {'state', 'detail', 'version', 'server_version', 'context', 'exe', 'chip', 'chip_tone'}. Runs `docker --version`, `docker info` and `docker context show` only."""
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
    plan = {"route": "guide", "place": "", "runs": None, "who_elevates": "", "internet": [], "licence": "", "steps": [], "links": [("The Docker guide", GUIDE_URL)], "scripts": {},
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
    if state in ("daemon_stopped", "desktop_not_running", "permission_denied", "wsl_integration_off", "unknown"):
        plan.update(route="guide", summary=diagnose(st, environment)["title"], steps=diagnose(st, environment)["steps"], place=diagnose(st, environment)["place"])
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
    return {"state": state, "title": title, "detail": st.get("detail", ""), "steps": steps, "place": place, "chip": chip[0], "tone": chip[1]}


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
    return "  [--]   docker (optional): %s Next: plasbench install-tools docker" % d["title"]


# ---------------------------------------------------------------- rendering and installing
def render_plan(plan, st, environment):
    lines = ["[PlasBench] Docker setup plan", "  Computer : " + {"windows": "Windows", "wsl2": "WSL 2 (Linux on Windows)" + (f", distro {environment.get('wsl_distro')}" if environment.get("wsl_distro") else ""), "wsl1": "WSL 1", "macos": "macOS",
                                                           "linux": "Linux" + (f" ({environment.get('distro')})" if environment.get("distro") else ""), "container": "inside a container"}.get(environment["kind"], environment["kind"]),
             "  Docker   : " + diagnose(st, environment)["title"], "  Route    : " + plan["route"] + (" - " + plan["summary"] if plan["summary"] else "")]
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


def wait_ready(check, timeout, interval=5.0, sleep=time.sleep, log=print, clock=time.monotonic):
    """Poll until check() answers a ready state or `timeout` seconds pass; each new state is reported once."""
    start, last, st = clock(), None, None
    while True:
        st = check()
        if st["state"] != last:
            log(f"[PlasBench] Docker state: {CHIPS.get(st['state'], CHIPS['unknown'])[0]}" + (f" ({st['detail']})" if st.get("detail") and st["state"] != "ready" else ""))
            last = st["state"]
        if st["state"] == "ready" or clock() - start >= timeout:
            return st
        sleep(interval)


def install(environment, st, yes=False, dry_run=False, wait=90.0, hello=False, route=None, run=default_run, recheck=None, sleep=time.sleep, log=print, env=None):
    """Do what the plan says where a user-level process may; hand off the rest. Returns 0 (verified working), 20 (handed off), 21 (needs consent) or 1 (failed)."""
    plan = make_plan(environment, st)
    recheck = recheck or (lambda: probe(environment, run=run, env=env))
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
        # the install ran (or Docker Desktop was already there): its first launch, the licence and WSL integration are the user's steps
        log("[PlasBench] Waiting for the Docker engine to answer (up to %d s). Docker Desktop must be started once and its licence accepted by you." % int(wait))
        final = recheck() if wait <= 0 else wait_ready(recheck, wait, 5.0, sleep, log)
        if final["state"] == "ready":
            record(final, env)
            log("[PlasBench] " + diagnose(final, environment)["title"])
            return _hello(run, log) if hello else EXIT_OK
        post = make_plan(environment, final) if final["state"] != "not_installed" else plan
        steps = post["steps"] if final["state"] != "not_installed" else plan["steps"]
        log(f"[PlasBench] Waiting for you to finish in {plan['place'] or 'Docker Desktop'} (exit 20: nothing failed). Docker is installed but not ready yet; what is left only you can do:")
        for i, step in enumerate(steps, 1):
            log(f"  {i}. {step}")
        return EXIT_HANDOFF
    # a hand-off with nothing to run: precise diagnosis and the exact next step
    log(render_plan(plan, st, environment))
    log(f"[PlasBench] Waiting for you to finish in {plan['place'] or 'a terminal'} (exit 20: nothing failed, nothing was run). When you have done the steps above, press Re-check or run `plasbench install-tools docker` again.")
    return EXIT_HANDOFF


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
    p.add_argument("--wait", type=float, default=float(os.environ.get("PLASBENCH_DOCKER_WAIT", "90")), help="seconds to wait for the engine after an install (default 90)")
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
    st = probe(environment, timeout=10 if a.action == "check-line" else 20)
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
    return install(environment, st, yes=a.yes, dry_run=a.dry_run, wait=a.wait, hello=a.hello_world, route=a.route)


if __name__ == "__main__":
    raise SystemExit(main())
