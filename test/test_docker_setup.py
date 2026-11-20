#!/usr/bin/env python3
"""Docker in the tools setup (python/docker_setup.py, `plasbench install-tools docker`): state detection from recorded `docker version` / `docker info` outputs, environment
detection, the plan per platform, the winget / Homebrew argument lists (no shell string) with fake programs, exit-code translation, the copyable sudo scripts (static text:
official https URLs, a key check, no piped shell, valid bash), the exit codes 0 / 20 / 21 / 1, the registry and window wiring. Nothing here installs or starts Docker."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT))
import docker_setup as ds  # noqa: E402
import tool_installer_registry as reg  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def out(text, code=0):
    return (code, text, "")


def err(text, code=1):
    return (code, "", text)


VERSION = out("Docker version 27.3.1, build ce12230\n")
INFO_OK = out("Client:\n Version: 27.3.1\nServer:\n Server Version: 27.3.1\n Operating System: Ubuntu 24.04\n")
DAEMON_DOWN = err("Client: Docker Engine\nCannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?")
PERMISSION = err("permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock: Get \"http://%2Fvar%2Frun%2Fdocker.sock/v1.47/info\": dial unix /var/run/docker.sock: connect: permission denied")
WSL_OFF = (127, "", "The command 'docker' could not be found in this WSL 2 distro. We recommend to activate the WSL integration in Docker Desktop settings.\n\nFor details about using Docker Desktop with WSL 2, visit:\n\nhttps://docs.docker.com/go/wsl2/\n")
DESKTOP_DOWN = err("error during connect: Get \"http://%2F%2F.%2Fpipe%2FdockerDesktopLinuxEngine/v1.47/info\": open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.")

LINUX = {"kind": "linux", "wsl": False, "interop": None, "winget": None, "powershell": None, "desktop_installed": False, "brew": None, "package_manager": "apt", "distro": "Ubuntu 24.04",
         "distro_id": "ubuntu", "systemd": True, "wsl_distro": "", "container": False}
WSL = dict(LINUX, kind="wsl2", wsl=True, interop=True, winget="/mnt/c/Users/me/AppData/Local/Microsoft/WindowsApps/winget.exe", powershell="/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
           wsl_distro="Ubuntu-24.04")
WINDOWS = dict(LINUX, kind="windows", package_manager="", distro="", distro_id="", systemd=False, winget="C:\\Users\\me\\AppData\\Local\\Microsoft\\WindowsApps\\winget.exe",
               powershell="C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe")
MAC = dict(LINUX, kind="macos", package_manager="", distro="", distro_id="", systemd=False, brew="/opt/homebrew/bin/brew")


def state(environment, version, info):
    return ds.classify(version, info, environment)["state"]


# ---- 1. the state, from recorded outputs
check("not installed (the program cannot start)", state(LINUX, None, None) == "not_installed")
check("not installed (command not found, exit 127)", state(LINUX, (127, "", "bash: docker: command not found"), None) == "not_installed")
check("daemon not running: 'Cannot connect to the Docker daemon'", state(LINUX, VERSION, DAEMON_DOWN) == "daemon_stopped")
check("permission denied on the daemon socket", state(LINUX, VERSION, PERMISSION) == "permission_denied")
check("WSL integration off (the distro's stub message)", state(WSL, WSL_OFF, None) == "wsl_integration_off")
check("WSL integration off is recognised from the message alone, wherever it appears", state(LINUX, None, WSL_OFF) == "wsl_integration_off")
check("docker missing in WSL while Docker Desktop is on Windows = WSL integration off", state(dict(WSL, desktop_installed=True), None, None) == "wsl_integration_off")
check("Docker Desktop not running on Windows", state(WINDOWS, VERSION, DESKTOP_DOWN) == "desktop_not_running")
check("daemon unreachable on macOS = Docker Desktop not running", state(MAC, VERSION, DAEMON_DOWN) == "desktop_not_running")
check("WSL with Docker Desktop installed and the daemon unreachable = Docker Desktop not running", state(dict(WSL, desktop_installed=True), VERSION, DAEMON_DOWN) == "desktop_not_running")
check("working", state(LINUX, VERSION, INFO_OK) == "ready")
check("an unreadable failure is 'unknown' with its first line", ds.classify(VERSION, err("something odd happened"), LINUX)["state"] == "unknown"
      and "something odd" in ds.classify(VERSION, err("something odd happened"), LINUX)["detail"])
check("client version is read", ds.classify(VERSION, INFO_OK, LINUX)["version"] == "27.3.1")
for st, words in (("not_installed", "not installed"), ("daemon_stopped", "daemon"), ("permission_denied", "docker.sock"), ("wsl_integration_off", "WSL integration"), ("desktop_not_running", "Docker Desktop"),
                  ("in_container", "Docker-in-Docker"), ("unknown", "docker info")):
    d = ds.diagnose({"state": st, "detail": "x"}, WSL)
    check(f"diagnosis for {st} names the problem and gives steps", words in d["title"] + " ".join(d["steps"]) and (d["steps"] or st == "ready"), d)
check("every state has a chip", all(s in ds.CHIPS for s in ds.STATES))


def fake_run(table):
    calls = []

    def run(argv, timeout=20):
        calls.append(list(argv))
        for key, value in table.items():
            if argv[1:len(key) + 1] == list(key):
                return value
        return None
    run.calls = calls
    return run


p = ds.probe(LINUX, run=fake_run({("--version",): VERSION, ("info",): INFO_OK, ("context", "show"): out("default\n")}), which=lambda n: "/usr/bin/docker" if n == "docker" else None)
check("probe: ready with server version and context recorded", p["state"] == "ready" and p["server_version"] == "27.3.1" and p["context"] == "default" and p["chip"] == "Ready", p)
r = fake_run({("--version",): VERSION, ("info",): DAEMON_DOWN})
p = ds.probe(LINUX, run=r, which=lambda n: "/usr/bin/docker")
check("probe: only version, info (and context when ready) are run", p["state"] == "daemon_stopped" and [c[1] for c in r.calls] == ["--version", "info"], r.calls)
p = ds.probe(LINUX, run=fake_run({}), which=lambda n: None)
check("probe: nothing on PATH is 'not installed'", p["state"] == "not_installed")
p = ds.probe(dict(LINUX, container=True, kind="container"), run=fake_run({}), which=lambda n: None)
check("probe: inside a container without docker is 'in_container' (Docker-in-Docker is out of scope)", p["state"] == "in_container")

# ---- 2. the environment
files = {"/etc/os-release": 'NAME="Ubuntu"\nPRETTY_NAME="Ubuntu 24.04 LTS"\nID=ubuntu\nID_LIKE=debian\n', "/run/systemd/system": ""}


def detect(platform="linux", env=None, have=(), read_files=None, exist=()):
    texts = dict(files, **(read_files or {}))
    return ds.detect_environment(env or {}, which=lambda n: "/x/" + n if n in have else None, exists=lambda p_: p_ in exist or p_ in texts,
                                 read=lambda p_: texts.get(p_), platform=platform)


e = detect("windows", env={"ProgramFiles": "C:\\Program Files", "LOCALAPPDATA": "C:\\Users\\me\\AppData\\Local"}, have=("winget.exe", "powershell.exe"))
check("native Windows: winget and PowerShell found", e["kind"] == "windows" and e["winget"] and e["powershell"], e)
e = detect("windows", env={})
check("native Windows without winget", e["kind"] == "windows" and not e["winget"])
wsl_files = {"/proc/version": "Linux version 5.15.153.1-microsoft-standard-WSL2 (root@x)", "/proc/sys/fs/binfmt_misc/WSLInterop": "enabled\ninterpreter /init\n"}
e = detect(env={"WSL_DISTRO_NAME": "Ubuntu-24.04"}, have=("winget.exe", "powershell.exe"), read_files=wsl_files)
check("WSL2 with interop: winget.exe reached", e["kind"] == "wsl2" and e["interop"] is True and e["winget"] and e["wsl_distro"] == "Ubuntu-24.04", e)
e = detect(env={"WSL_DISTRO_NAME": "Ubuntu"}, have=("winget.exe", "powershell.exe"), read_files=dict(wsl_files, **{"/proc/sys/fs/binfmt_misc/WSLInterop": "disabled\n"}))
check("WSL2 with interop off: the Windows side is not reachable", e["kind"] == "wsl2" and e["interop"] is False and not e["winget"] and not e["powershell"], e)
e = detect(env={"WSL_DISTRO_NAME": "Ubuntu"}, read_files={"/proc/version": "Linux version 4.4.0-19041-Microsoft"})
check("WSL1 is told apart", e["kind"] == "wsl1", e)
e = detect("macos", have=("brew",))
check("macOS with Homebrew", e["kind"] == "macos" and e["brew"])
e = detect("macos", exist=())
check("macOS without Homebrew", e["kind"] == "macos" and not e["brew"])
for osr, fam, did in (('ID=ubuntu\nID_LIKE=debian\n', "apt", "ubuntu"), ('ID=debian\n', "apt", "debian"), ('ID=linuxmint\nID_LIKE="ubuntu debian"\n', "apt", "ubuntu"), ('ID=fedora\n', "dnf", "fedora"),
                      ('ID=rocky\nID_LIKE="rhel centos fedora"\n', "dnf", "centos"), ('ID=arch\n', "pacman", "arch"), ('ID=manjaro\nID_LIKE=arch\n', "pacman", "arch"),
                      ('ID="opensuse-leap"\nID_LIKE="suse opensuse"\n', "zypper", "suse"), ('ID=gentoo\n', "", "")):
    e = detect(read_files={"/etc/os-release": osr})
    check(f"Linux family for {osr.splitlines()[0]}", e["package_manager"] == fam and e["distro_id"] == did and e["kind"] == "linux", e)
check("Linux without systemd", detect(exist=(), read_files={"/run/systemd/system": None})["systemd"] in (False, True) and not ds.detect_environment({}, which=lambda n: None, exists=lambda p_: False, read=lambda p_: files.get(p_), platform="linux")["systemd"])
e = detect(env={"PLASBENCH_IN_DOCKER": "1"})
check("inside a container (PLASBENCH_IN_DOCKER)", e["kind"] == "container" and e["container"], e)
e = detect(exist=("/.dockerenv",))
check("inside a container (/.dockerenv)", e["kind"] == "container", e)
check("forced platform for tests", ds.detect_environment({"PLASBENCH_DOCKER_PLATFORM": "wsl2"}, which=lambda n: None, exists=lambda p_: False, read=lambda p_: None)["kind"] == "wsl2")

# ---- 3. the plan per platform
NI = {"state": "not_installed", "detail": "", "version": ""}
plan = ds.make_plan(WINDOWS, NI)
check("Windows: route winget, argv exactly the documented list", plan["route"] == "winget" and plan["runs"] == [WINDOWS["winget"], "install", "-e", "--id", "Docker.DockerDesktop", "--accept-package-agreements", "--accept-source-agreements"], plan["runs"])
check("Windows: the plan says Windows asks you to approve, and the licence is the user's", "approve" in plan["who_elevates"] and "cannot accept the licence for you" in plan["licence"] and ds.LICENCE_URL in plan["licence"])
check("Windows: post-install steps include WSL integration and the licence", any("WSL integration" in s for s in plan["steps"]) and any("accept" in s.lower() for s in plan["steps"]))
check("Windows: winget route needs the winget and docker services", plan["internet"] == ["winget", "docker"])
plan = ds.make_plan(WSL, NI)
check("WSL2: winget.exe on the Windows side, with the same argv", plan["route"] == "winget" and plan["runs"][0].endswith("winget.exe") and plan["runs"][1:4] == ["install", "-e", "--id"])
check("WSL2: the advanced Docker Engine script is offered, with systemd enablement", "advanced" in plan["scripts"] and "systemd=true" in plan["scripts"]["advanced"])
plan = ds.make_plan(dict(WSL, winget=None), NI)
check("WSL2 without winget: links and `wsl --install`, nothing is downloaded silently", plan["route"] == "links" and plan["runs"] is None and any("wsl --install" in s for s in plan["steps"]) and any("docs.docker.com" in s for s in plan["steps"]), plan)
plan = ds.make_plan(dict(WSL, interop=False, winget=None, powershell=None), NI)
check("WSL2 with interop off: hand off, no route to run", plan["route"] == "links" and plan["runs"] is None and "interop" in plan["summary"].lower())
plan = ds.make_plan(dict(WSL, kind="wsl1"), NI)
check("WSL1: told to upgrade to WSL 2", plan["route"] == "links" and "wsl --set-version" in " ".join(plan["steps"]))
plan = ds.make_plan(MAC, NI)
check("macOS with brew: brew install --cask docker-desktop", plan["route"] == "brew" and plan["runs"] == ["/opt/homebrew/bin/brew", "install", "--cask", "docker-desktop"] and "password" in plan["who_elevates"], plan["runs"])
check("macOS: open -a Docker guidance and the licence", any("open -a Docker" in s for s in plan["steps"]) and ds.LICENCE_URL in plan["licence"])
plan = ds.make_plan(dict(MAC, brew=None), NI)
check("macOS without brew: the official download link, nothing run", plan["route"] == "links" and plan["runs"] is None and any(ds.DESKTOP_MAC_URL in s for s in plan["steps"]))
for fam, did, needle in (("apt", "ubuntu", "apt-get install -y docker-ce"), ("apt", "debian", "linux/debian"), ("dnf", "fedora", "dnf config-manager addrepo"), ("pacman", "arch", "pacman -S"),
                         ("zypper", "suse", "zypper")):
    plan = ds.make_plan(dict(LINUX, package_manager=fam, distro_id=did), NI)
    check(f"Linux {fam}/{did}: a copyable sudo script, run by the user", plan["route"] == "script" and plan["runs"] is None and needle in plan["scripts"]["official"] and "PlasBench does not run it" in plan["who_elevates"], plan["who_elevates"])
plan = ds.make_plan(dict(LINUX, package_manager="", distro_id=""), NI)
check("Linux of an unknown family: Docker's own page", plan["route"] == "links" and any("docs.docker.com" in s for s in plan["steps"]))
plan = ds.make_plan(dict(LINUX, systemd=False), NI)
check("Linux without systemd: the plan says to start the daemon another way", any("systemd" in s for s in plan["steps"]))
plan = ds.make_plan(dict(LINUX, kind="container", container=True), {"state": "in_container", "detail": "", "version": ""})
check("inside a container: Docker-in-Docker is out of scope, said plainly", plan["route"] == "container" and "out of scope" in plan["summary"])
plan = ds.make_plan(LINUX, {"state": "ready", "detail": "", "version": "27"})
check("ready: nothing to do", plan["route"] == "ready")
for stt in ("daemon_stopped", "permission_denied", "wsl_integration_off", "desktop_not_running"):
    plan = ds.make_plan(WSL, {"state": stt, "detail": "x", "version": "27"})
    check(f"{stt}: a diagnosis, no installer", plan["route"] == "guide" and plan["runs"] is None and plan["steps"])

# ---- 4. the scripts are static, official and valid
bash = shutil.which("bash")
for fam, did, variant in (("apt", "ubuntu", "official"), ("apt", "debian", "official"), ("apt", "ubuntu", "distro"), ("dnf", "fedora", "official"), ("dnf", "centos", "official"), ("dnf", "fedora", "distro"),
                          ("pacman", "arch", "official"), ("zypper", "suse", "official")):
    for wsl in (False, True):
        text = ds.linux_script(fam, did, variant, wsl)
        name = f"script {fam}/{did}/{variant}{'/wsl' if wsl else ''}"
        check(f"{name}: no piped shell", not re.search(r"\|\s*(sudo\s+)?(ba|z|da)?sh\b", text) and "get.docker.com" not in text)
        urls = re.findall(r"https?://[^\s\"')]+", text)
        check(f"{name}: only https URLs, on docs.docker.com or download.docker.com", all(u.startswith("https://") and re.match(r"https://(docs|download)\.docker\.com/", u) for u in urls), urls)
        check(f"{name}: sudo is the user's (never embedded credentials), service and group steps present", "sudo systemctl enable --now docker" in text and "usermod -aG docker" in text and "newgrp docker" in text)
        if variant == "official" and fam == "apt":
            check(f"{name}: the signing key fingerprint is checked before use", ds.DOCKER_KEY_FPR_APT in text and "gpg --show-keys" in text and "exit 1" in text and "docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin" in text)
        if variant == "official" and fam == "dnf":
            check(f"{name}: the rpm key fingerprint is named", ds.DOCKER_KEY_FPR_RPM in text)
        if bash:
            with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False, newline="\n", encoding="utf-8") as handle:
                handle.write(text)
            res = subprocess.run([bash, "-n", handle.name], capture_output=True, text=True)
            os.unlink(handle.name)
            check(f"{name}: bash -n accepts it", res.returncode == 0, res.stderr)
check("an unknown family has no script", ds.linux_script("nope") == "")
check("the WSL script says how to enable systemd", "[boot]" in ds.linux_script("apt", "ubuntu", "official", True) and "wsl --shutdown" in ds.linux_script("apt", "ubuntu", "official", True))

# ---- 5. exit codes and translation
check("winget 0 is success", ds.translate_winget(0)[0] == "ok")
check("1602 (user cancelled) is a plain sentence about the declined prompt", ds.translate_winget(1602)[0] == "declined" and "declined" in ds.translate_winget(1602)[1])
check("1223 and the signed/unsigned cancelled codes are declined too", ds.translate_winget(1223)[0] == "declined" and ds.translate_winget(2147943623)[0] == "declined" and ds.translate_winget(-2147023673)[0] == "declined")
check("-1978335189 (no upgrade applies) is 'already installed'", ds.translate_winget(-1978335189)[0] == "already" and ds.translate_winget(2316632107)[0] == "already")
check("no package found is a plain sentence", ds.translate_winget(-1978335212)[0] == "notfound" and "winget source update" in ds.translate_winget(-1978335212)[1])
check("3010 means a restart", ds.translate_winget(3010)[0] == "restart")
check("anything else is a failure with the code", ds.translate_winget(7)[0] == "failed" and "7" in ds.translate_winget(7)[1])
check("brew: cask not found is told apart", ds.translate_brew(1, "Error: Cask 'docker-desktop' is unavailable: No Cask with this name exists.")[0] == "notfound")


def run_install(environment, st, runs, rechecks=None, **kw):
    log = []
    state_iter = iter(rechecks or [])
    final = {"state": "not_installed", "detail": "", "version": ""}

    def recheck():
        try:
            return next(state_iter)
        except StopIteration:
            return final
    code = ds.install(environment, st, run=runs, recheck=recheck, sleep=lambda s: None, log=log.append, env={"PLASBENCH_STATE_DIR": tempfile.mkdtemp()}, **kw)
    return code, "\n".join(log)


READY = {"state": "ready", "detail": "docker info answered", "version": "27.3.1", "server_version": "27.3.1", "context": "desktop-linux", "exe": "docker"}
code, text = run_install(WINDOWS, READY, fake_run({}))
check("ready: exit 0, nothing run", code == 0 and "working" in text)
r = fake_run({})
code, text = run_install(WINDOWS, NI, r)
check("no consent: exit 21, nothing was started", code == 21 and not r.calls and "Consent needed" in text and "--yes" in text, (code, r.calls))
r = fake_run({})
code, text = run_install(WINDOWS, NI, r, dry_run=True)
check("dry run: exit 0, plan printed, nothing started", code == 0 and not r.calls and "dry run" in text and "winget" in text)
winget = WINDOWS["winget"]
good = {(): None}


def winget_run(code_, text_="", then=None):
    calls = []

    def run(argv, timeout=20):
        calls.append(list(argv))
        return (code_, text_, "")
    run.calls = calls
    return run


r = winget_run(0, "Found Docker Desktop\nSuccessfully installed\n")
code, text = run_install(WINDOWS, NI, r, yes=True, wait=0)
check("winget success but Docker not ready yet: exit 20, 'Waiting for you', licence step listed", code == 20 and "Waiting for you to finish in Docker Desktop" in text and "accept" in text.lower(), text[-600:])
check("winget was started with the exact argv, once", r.calls == [ds.winget_argv(winget)], r.calls)
r = winget_run(0, "ok")
code, text = run_install(WINDOWS, NI, r, rechecks=[READY], yes=True, wait=30)
check("winget success and Docker answers: exit 0 and verified", code == 0 and "Docker is working" in text, text[-300:])
r = winget_run(1602, "")
code, text = run_install(WINDOWS, NI, r, yes=True, wait=0)
check("UAC declined: exit 1 with a plain sentence", code == 1 and "declined or closed" in text, text[-300:])
r = winget_run(-1978335212, "No package found matching input criteria.")
code, text = run_install(WINDOWS, NI, r, yes=True, wait=0)
check("winget package not found: exit 1, plain sentence", code == 1 and "winget source update" in text)
r = winget_run(-1978335189, "")
code, text = run_install(WINDOWS, NI, r, yes=True, wait=0)
check("already installed per winget: not an error, exit 20 (steps left)", code == 20 and "already installed" in text, (code, text[-300:]))
code, text = run_install(WINDOWS, NI, lambda argv, timeout=20: None, yes=True, wait=0)
check("winget cannot start: exit 1", code == 1)
r = winget_run(0, "ok")
code, text = run_install(WSL, NI, r, yes=True, wait=0)
check("WSL2: the same winget argv through the Windows side, exit 20 until Docker Desktop is set up", code == 20 and r.calls[0][0].endswith("winget.exe") and "Waiting for you" in text)
r = winget_run(0, "ok")
code, text = run_install(MAC, NI, r, yes=True, wait=0)
check("macOS: brew argv, exit 20 until Docker Desktop is started", code == 20 and r.calls == [["/opt/homebrew/bin/brew", "install", "--cask", "docker-desktop"]] and "open -a Docker" in text, r.calls)
calls = []


def brew_old(argv, timeout=20):
    calls.append(list(argv))
    return (1, "", "Error: Cask 'docker-desktop' is unavailable: No Cask with this name exists.") if argv[-1] == "docker-desktop" else (0, "ok", "")


code, text = run_install(MAC, NI, brew_old, yes=True, wait=0)
check("macOS: an older Homebrew falls back to the older cask name", [c[-1] for c in calls] == ["docker-desktop", "docker"] and code == 20, calls)
for fam in ("apt", "dnf", "pacman", "zypper"):
    r = fake_run({})
    code, text = run_install(dict(LINUX, package_manager=fam, distro_id={"apt": "ubuntu", "dnf": "fedora", "pacman": "arch", "zypper": "suse"}[fam]), NI, r)
    check(f"Linux {fam}: exit 20, nothing run (not even with consent), the script is printed", code == 20 and not r.calls and "script: official" in text and "Waiting for you to finish in a terminal" in text)
    code2, _ = run_install(dict(LINUX, package_manager=fam, distro_id="ubuntu"), NI, fake_run({}), yes=True)
    check(f"Linux {fam}: --yes does not change that (no sudo is ever run)", code2 == 20)
for stt in ("daemon_stopped", "permission_denied", "wsl_integration_off", "desktop_not_running", "unknown"):
    r = fake_run({})
    code, text = run_install(WSL, {"state": stt, "detail": "x", "version": "27"}, r, yes=True)
    check(f"{stt}: exit 20, diagnosis shown, nothing run", code == 20 and not r.calls and "Waiting for you" in text)
code, text = run_install(dict(LINUX, kind="container", container=True), {"state": "in_container", "detail": "", "version": ""}, fake_run({}), yes=True)
check("inside a container: exit 20 and the out-of-scope statement", code == 20 and "out of scope" in text)
code, text = run_install(WSL, NI, fake_run({}), yes=True, route="advanced")
check("advanced route in WSL: the Docker Engine script, nothing run", code == 20 and "script: advanced" in text)
r = fake_run({("run", "--rm", "hello-world"): out("Hello from Docker!\n")})
code, text = run_install(LINUX, READY, r, hello=True)
check("hello-world only with the flag, and it runs `docker run --rm hello-world`", code == 0 and r.calls == [["docker", "run", "--rm", "hello-world"]], r.calls)
r = fake_run({})
code, _ = run_install(LINUX, READY, r)
check("hello-world is off by default", not r.calls)
code, text = run_install(LINUX, READY, fake_run({("run", "--rm", "hello-world"): err("pull access denied")}), hello=True)
check("hello-world failure is exit 1", code == 1)
os.environ["PLASBENCH_OFFLINE"] = "1"
code, text = run_install(WINDOWS, NI, winget_run(0), yes=True, wait=0)
check("PLASBENCH_OFFLINE refuses the winget route (exit 1) without starting it", code == 1 and "PLASBENCH_OFFLINE" in text)
del os.environ["PLASBENCH_OFFLINE"]

# wait_ready: reports each state once, stops at ready, honours the timeout
seq = iter([{"state": "not_installed", "detail": ""}, {"state": "desktop_not_running", "detail": "x"}, {"state": "desktop_not_running", "detail": "x"}, {"state": "ready", "detail": ""}])
msgs = []
clock = iter(range(0, 1000, 5))
final = ds.wait_ready(lambda: next(seq), 600, 5, sleep=lambda s: None, log=msgs.append, clock=lambda: next(clock))
check("wait_ready: polls until ready and reports each new state once", final["state"] == "ready" and len(msgs) == 3, msgs)
clock = iter(range(0, 1000, 50))
final = ds.wait_ready(lambda: {"state": "daemon_stopped", "detail": ""}, 100, 5, sleep=lambda s: None, log=lambda m: None, clock=lambda: next(clock))
check("wait_ready: gives up at the timeout", final["state"] == "daemon_stopped")

# recorded status
tmp = tempfile.mkdtemp()
path = ds.record(READY, {"PLASBENCH_STATE_DIR": tmp})
rec = ds.recorded({"PLASBENCH_STATE_DIR": tmp})
check("the verified state (version, server, context) is recorded for `plasbench check` and the manifest", path and rec["version"] == "27.3.1" and rec["context"] == "desktop-linux" and rec["state"] == "ready", rec)
check("check line: ready", "[ok]" in ds.check_line(READY) and "optional" in ds.check_line(READY))
check("check line: not ready names the next step", "plasbench install-tools docker" in ds.check_line(dict(NI)))

# ---- 6. registry and window wiring
rows = reg.read_tsv(ROOT / "config" / "tool_installers.tsv")
check("docker is a known automatic profile", reg.profile_kinds(rows)["docker"] == "automatic" and reg.resolve("docker", rows)[0] == 0)
check("docker gates the internet itself (no conda/pypi/github pre-flight)", reg.needs_network("docker", rows) is False)
listing = subprocess.run([sys.executable, str(ROOT / "python" / "tool_installer_registry.py"), "list"], capture_output=True, text=True).stdout
check("`install-tools list` shows the docker profile", re.search(r"^docker\tdocker\tguided_consent", listing, re.M) is not None)
plan_out = subprocess.run([sys.executable, str(ROOT / "python" / "tool_installer_registry.py"), "plan"], capture_output=True, text=True).stdout
check("`install-tools plan` shows docker with its verification command", "docker\tdocker\tguided_consent\tguided\tcontainer_engine\tnone\tdocker info" in plan_out)
check("validate still passes (docker is a runtime row, not an adapter)", subprocess.run([sys.executable, str(ROOT / "python" / "tool_installer_registry.py"), "validate"], capture_output=True).returncode == 0)
import csv  # noqa: E402
services = {row["service"]: row for row in csv.DictReader((ROOT / "config" / "network_services.tsv").open(encoding="utf-8", newline=""), delimiter="	")}
check("netcheck services winget, brew and docker declare python/docker_setup.py", all("python/docker_setup.py" in services[n]["used_by"] for n in ("winget", "brew", "docker")), services.get("winget"))
html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
block = html[html.index("==DOCKER-UI-BEGIN=="):html.index("==DOCKER-UI-END==")]
for needle in ('id="dk_chip"', 'id="dk_install"', 'id="dk_recheck"', 'id="dk_guide"', "Install Docker", "Re-check", "Open the Docker guide", "Waiting for you to finish in", "Open Terminal with this command prefilled",
               "modalDialog(", 'api("docker/setup', "applyKeyed(", "PlasBench never runs it"):
    check(f"window: {needle}", needle in html, needle)
check("window: the Docker block uses no browser confirm / prompt / alert", not re.search(r"(?<![\w.])(confirm|prompt|alert)\(", block))
check("window: Install Docker first in the folder chooser and Settings", 'id="np_dk_install"' in html and 'id="fs_dkinstall"' in html)
check("window: the consent dialog lists what runs, who elevates and the licence", all(w in block for w in ("What will run", "Who elevates", "Licence.", "Internet", "Size")))
check("window: the terminal prefill does not execute", "dockerTerminal" in block and "termRun" not in block)
check("window: the state is never fetched on the page-load path (only from the Setup and Workflow loaders)", html.count("dockerLoad(") >= 4 and "api(\"docker/setup\"" in block)
check("window: the job state 'waiting_for_you' is styled and worded", "waiting_for_you:\"Waiting for you to finish\"" in html)
from plasbench import ui_help  # noqa: E402
for key in ("docker_state", "docker_install", "docker_recheck", "docker_guide", "docker_install_first"):
    check(f"tooltip text for {key}", ui_help.NATIVE_PICKER.get(key, {}).get("summary"))
src = (ROOT / "plasbench" / "webui.py").read_text(encoding="utf-8")
check("server: docker/setup route is a cached background probe (loadcache.swr, block=False)", 'route == "docker/setup"' in src and 'loadcache.swr(("docker-setup",)' in src and "block=False" in src)
check("server: exit 20 of install-tools docker is 'waiting_for_you', not a failure", "waiting_for_you" in src and "def is_docker_setup" in src)
from plasbench import webui  # noqa: E402
check("is_docker_setup", webui.is_docker_setup(["install-tools", "docker", "--yes"]) and not webui.is_docker_setup(["install-tools", "plsmd"]) and not webui.is_docker_setup(None))
steps = (ROOT / "config" / "workflow_steps.tsv").read_text(encoding="utf-8")
check("workflow: a docker row under the setup step", re.search(r"^0\tsetup\t.*\tdocker\tDocker \(container engine\)\tseparate\t", steps, re.M) is not None)
check("workflow: the item says it is the runtime for mobilome-map", "mobilome-map" in steps.split("\tdocker\t")[1].split("\n")[0])
helper = (ROOT / "scripts" / "docker_run.sh").read_text(encoding="utf-8")
check("scripts/docker_run.sh checks Docker through the same helper before running", "docker_setup.py" in helper and "diagnose" in helper and "install-tools docker" in helper)
setup_sh = (ROOT / "scripts" / "00_setup.sh").read_text(encoding="utf-8")
check("plasbench check lists docker as optional, never as an installed profile", "docker_setup.py" in setup_sh and "check-line" in setup_sh and "check_tool docker" not in setup_sh)
sources = json.loads((ROOT / "config" / "source_tools.json").read_text(encoding="utf-8"))["profiles"]
check("mobilome-map and plsmd point to `plasbench install-tools docker`", "install-tools docker" in json.dumps(sources["mobilome-map"]) and "install-tools docker" in json.dumps(sources["plsmd"]))
manifest_src = (ROOT / "python" / "write_manifest.py").read_text(encoding="utf-8")
check("the run manifest records the container engine", '"container_engine": container_engine_record()' in manifest_src)

print("ALL DOCKER SETUP TESTS PASSED" if not FAILED else f"DOCKER SETUP TESTS FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
