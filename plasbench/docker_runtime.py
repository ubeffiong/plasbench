"""Where PlasBench's tools run: the `plasbench` conda environment on this computer (the default), or a Docker container.

The window and the command line always run on the computer itself. When the runtime is Docker, the heavy commands (`plasbench run`, `report`, `check`,
`install-tools`, `tools install`) are started by the host-side `plasbench` as `docker run --rm ...` with the image's own copy of the pipeline scripts, so the
study folders, study.json records, the window's jobs and the cancel button are unchanged. Design points (docs/USER_GUIDE.md, "Choosing where tools run"):

* Every folder the command needs is bind-mounted at the SAME absolute path inside the container, so every path recorded in run_events.jsonl, manifests and
  the HTML report is valid on the host too. Native Windows cannot do that (a container has no D:\\), so a drive path D:\\x is mounted at /mnt/d/x and paths in the
  container's output are the /mnt/d/x spelling; UNC shares are refused with the reason.
* Extra tools and databases live in persistent storage mounted into every container (a bind mount of ~/.plasbench/docker/<version>/extras, created by the
  host user so files are not root-owned, and the database folder at its own path). The image itself is never modified.
* The image: present locally, else pulled (PLASBENCH_DOCKER_PULL), else built from the checkout's Dockerfile (with consent).
* Everything is an argument list; nothing is built as a shell string. Every system fact (docker, files, environment) can be injected, so tests use a fake `docker`.

Standard library only; Python 3.9 compatible.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import __version__

REPO_IMAGE = "ghcr.io/ubeffiong/plasbench"
RUNTIMES = ("conda", "docker")
PULL_POLICIES = ("missing", "always", "never")
APP_DIR = "/opt/plasbench"
CONTAINER_HOME = "/tmp/plasbench-home"
SETTING_KEYS = ("PLASBENCH_RUNTIME", "PLASBENCH_DOCKER_IMAGE", "PLASBENCH_DOCKER_PULL")
# Folders a command writes (mounted read-write) and files or folders it only reads (mounted read-only).
PATH_RW = ("DATA_DIR", "RESULTS_DIR", "LOG_DIR", "TMP_DIR", "PLASBENCH_DB_DIR", "PLASBENCH_WORKSPACE")
PATH_RO = ("SAMPLE_SHEET", "PLATON_DB", "GENOMAD_DB", "PLASME_DB", "PLASGRAPH2_MODEL_DIR", "GPLAS2_EXTERNAL_PREDICTIONS_DIR", "LONG_READS_FILE",
           "PLASBENCH_LOCAL_SETTINGS", "SHORT_READ_QC_THRESHOLDS")
ALWAYS_PASS = ("NCBI_API_KEY", "NCBI_EMAIL", "USER_TOOLS", "INSTALL_MISSING_TOOLS", "PLASBENCH_STALL_SECONDS", "PLASBENCH_OFFLINE", "PLASBENCH_STARTED_VIA",
               "PLASBENCH_JOB_GROUP", "PLASBENCH_INSTALL_DRY_RUN", "READ_SOURCE", "TZ")
NEVER_PASS = {"PATH", "HOME", "PROJECT_ROOT", "PWD", "OLDPWD", "SHLVL", "PLASBENCH_RUNTIME", "PLASBENCH_DOCKER_IMAGE", "PLASBENCH_DOCKER_PULL", "PLASBENCH_DOCKER_EXTRA",
              "PLASBENCH_HOME", "PLASBENCH_BASH", "DOCKER_HOST", "CONDA_PREFIX", "CONDA_DEFAULT_ENV", "PLASBENCH_JOB_DIR", "PLASBENCH_JOB_ID"}
DRIVE_RE = re.compile(r"^([A-Za-z]):([\\/]|$)")
UNC_RE = re.compile(r"^[\\/]{2}[^\\/]+[\\/]+[^\\/]+")
EXIT_CONSENT = 21


class PathError(ValueError):
    """A host path that cannot be given to a container; the message says why and what to do."""


# ---------------------------------------------------------------- settings
def read_local_env(root, environ=None) -> dict:
    """The `export KEY=value` lines of config/local.env (or PLASBENCH_LOCAL_SETTINGS), read without running anything."""
    environ = os.environ if environ is None else environ
    path = Path(environ.get("PLASBENCH_LOCAL_SETTINGS") or (Path(root) / "config" / "local.env"))
    values = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for line in text.splitlines():
        m = re.match(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)=(.*)$", line)
        if not m:
            continue
        try:
            parts = shlex.split(m.group(2), comments=True)
        except ValueError:
            continue
        values[m.group(1)] = parts[0] if len(parts) == 1 else (" ".join(parts) if parts else "")
    return values


def save_local_setting(root, key, value, environ=None) -> None:
    """Set (or, with None, remove) one `export KEY=value` line in config/local.env, keeping every other line (the window's Settings page writes the same file)."""
    environ = os.environ if environ is None else environ
    path = Path(environ.get("PLASBENCH_LOCAL_SETTINGS") or (Path(root) / "config" / "local.env"))
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else ["# PlasBench settings for this computer (read by config/config.sh). Written by `plasbench ui`; edit freely."]
    kept, done = [], False
    for line in lines:
        m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=", line)
        if m and m.group(1) == key:
            if value is not None and not done:
                kept.append(f"export {key}={shlex.quote(str(value))}")
            done = True
            continue
        kept.append(line)
    if not done and value is not None:
        kept.append(f"export {key}={shlex.quote(str(value))}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(kept) + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def setting(root, key, default="", environ=None, local=None):
    environ = os.environ if environ is None else environ
    if environ.get(key):
        return environ[key]
    local = read_local_env(root, environ) if local is None else local
    return local.get(key) or default


def runtime_setting(root, override=None, environ=None) -> str:
    """conda or docker: the --runtime option, else PLASBENCH_RUNTIME (environment, then config/local.env), else conda. Anything else is an error."""
    value = (override or setting(root, "PLASBENCH_RUNTIME", "conda", environ)).strip().lower()
    if value not in RUNTIMES:
        raise ValueError(f"PLASBENCH_RUNTIME must be conda or docker, not {value!r}")
    return value


def pull_policy(root, environ=None) -> str:
    value = setting(root, "PLASBENCH_DOCKER_PULL", "missing", environ).strip().lower()
    if value not in PULL_POLICIES:
        raise ValueError(f"PLASBENCH_DOCKER_PULL must be missing, always or never, not {value!r}")
    return value


def published_image(version: str = __version__) -> str:
    return f"{REPO_IMAGE}:v{version}"


def local_tag(version: str = __version__) -> str:
    return f"plasbench:{version}-local"


def image_tag_version(image: str):
    """The PlasBench version a tag names (v0.5.4, 0.5.4, 0.5.4-local), or None for latest, a digest or any other name."""
    m = re.search(r":v?(\d+\.\d+\.\d+(?:[.-]?[A-Za-z0-9.]+)?)$", image or "")
    if not m:
        return None
    return re.sub(r"-local$", "", m.group(1))


def extra_home(root, version: str = __version__, environ=None) -> Path:
    environ = os.environ if environ is None else environ
    custom = setting(root, "PLASBENCH_DOCKER_EXTRA", "", environ)
    return Path(custom) if custom else Path(os.path.expanduser("~")) / ".plasbench" / "docker" / version / "extras"


# ---------------------------------------------------------------- running docker
def _run(argv, timeout=20, env=None):
    """(exit code, output) of a short docker command; never raises."""
    try:
        done = subprocess.run(argv, capture_output=True, timeout=timeout, env=env, check=False)
    except FileNotFoundError:
        return 127, "docker was not found"
    except subprocess.TimeoutExpired:
        return 124, "docker did not answer in time"
    except OSError as exc:
        return 126, str(exc)
    out = (done.stdout or b"") + (done.stderr or b"")
    return done.returncode, out.decode("utf-8", "replace").strip()


def docker_exe(which=shutil.which):
    return which("docker")


def stream(argv, env=None, out=None, heartbeat=60.0, what="working"):
    """Run a long docker command, copying its output lines to `out` (default stdout) with a "still working" line when it is quiet.
    Returns (exit code, the last 60 lines)."""
    out = out or (lambda line: (sys.stdout.write(line + "\n"), sys.stdout.flush()))
    tail = []
    started = time.time()
    last = [time.time()]
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    except OSError as exc:
        out(f"[plasbench] could not start docker: {exc}")
        return 127, [str(exc)]
    done = threading.Event()

    def beat():
        while not done.wait(max(0.05, min(5.0, heartbeat / 4))):
            if time.time() - last[0] >= heartbeat:
                out(f"[plasbench] still working: {what} ({int((time.time() - started) / 60)} min so far)")
                last[0] = time.time()
    threading.Thread(target=beat, daemon=True).start()
    try:
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            tail.append(line)
            del tail[:-60]
            last[0] = time.time()
            out(line)
    finally:
        code = proc.wait()
        done.set()
    return code, tail


# ---------------------------------------------------------------- classifying failures
FAILURES = [
    ("disk", r"no space left on device|disk quota|not enough space",
     "The disk Docker uses is full. Free space (docker system prune removes unused images; on Docker Desktop raise the disk limit in Settings > Resources; "
     "on WSL2 the Docker disk grows inside C:, so free space there), then try again."),
    ("permission", r"permission denied.*docker\.sock|got permission denied while trying to connect",
     "This account may not use Docker. Add it to the docker group (sudo usermod -aG docker $USER), then log out and back in; or start Docker Desktop."),
    ("daemon", r"cannot connect to the docker daemon|is the docker daemon running|error during connect|docker daemon is not running",
     "Docker is installed but not running. Start Docker Desktop (or sudo systemctl start docker) and try again."),
    ("registry", r"pull access denied|unauthorized|denied: |manifest unknown|not found: manifest|repository does not exist|requested access to the resource is denied",
     "The registry refused the image (not published for this version, or private). PlasBench can build the image from this folder's Dockerfile instead."),
    ("network", r"could not resolve|temporary failure in name resolution|no such host|i/o timeout|tls handshake|network is unreachable|connection refused|"
               r"dial tcp|connection reset|timeout exceeded|net/http",
     "The internet (or name lookup) failed. Check the connection, a VPN or proxy, or DNS (1.1.1.1), then try again. Finished layers are kept."),
    ("platform", r"exec format error|no matching manifest|platform .* does not match|requested image's platform",
     "The image is built for linux/amd64 and this computer is a different architecture. On Apple Silicon Docker Desktop can emulate amd64 (slow); on other ARM computers use conda."),
]


def classify_failure(text: str) -> dict:
    """{'kind', 'advice', 'step'}: what went wrong in a docker pull or build, from its output (never guesses: kind 'unknown' with the last line)."""
    text = text or ""
    step = ""
    m = re.search(r'process "([^"]{1,200})[^"]*" did not complete successfully', text)
    if m:
        step = m.group(1).strip()
    else:
        m = re.search(r"^.*?(Step \d+/\d+ : [^\n]{1,160})", text, re.M)
        step = m.group(1) if m else ""
    for kind, pattern, advice in FAILURES:
        if re.search(pattern, text, re.I):
            return {"kind": kind, "advice": advice, "step": step}
    last = [l for l in text.splitlines() if l.strip()]
    advice = ("A build step failed" + (f": {step}" if step else "") + ". The last lines of the output above say why; run the same command again to resume from the cached layers."
              if step else "docker stopped with an error that PlasBench does not recognise; the last lines of its output are above.")
    return {"kind": "unknown", "advice": advice, "step": step or (last[-1] if last else "")}


# ---------------------------------------------------------------- the Docker state
def probe(root=None, run=None, exe=None, environ=None, exists=os.path.exists, in_wsl=None) -> dict:
    """What Docker is like on this computer: {'state', 'installed', 'running', 'version', 'hint', 'image': {...}}.
    state: not_installed | wsl_integration_off | permission_needed | daemon_stopped | ready. `docker version` and `docker image inspect` only; no container is started."""
    real = run is None and exe is None and environ is None        # the real computer: the Windows-side check below runs only then, never in a test that fakes docker
    run = run or _run
    environ = os.environ if environ is None else environ
    exe = exe if exe is not None else docker_exe()
    wsl = bool(environ.get("WSL_DISTRO_NAME")) if in_wsl is None else in_wsl
    info = {"state": "not_installed", "installed": False, "running": False, "version": "", "hint": "", "arch": "", "image": {}}
    if not exe:
        if wsl and exists("/mnt/wsl/docker-desktop"):
            info.update(state="wsl_integration_off", hint="Docker Desktop is installed but this Linux (WSL) distribution cannot reach it: in Docker Desktop open Settings > Resources > WSL integration and switch this distribution on.")
        else:
            info["hint"] = "Docker is not installed: install it from the Tools page (Install Docker), or use conda."
        return info
    info["installed"] = True
    code, out = run([exe, "version", "--format", "{{.Server.Version}}|{{.Server.Arch}}"], 15)
    low = out.lower()
    if code == 0 and out[:1].isdigit():
        version, _, arch = out.partition("|")
        info.update(state="ready", running=True, version=version, arch=arch)
    elif "could not be found in this wsl" in low or "wsl 2 distro" in low:
        info.update(state="wsl_integration_off", hint="Docker Desktop's WSL integration is off for this distribution: Docker Desktop > Settings > Resources > WSL integration.")
    elif "permission denied" in low:
        info.update(state="permission_needed", hint="This account may not use Docker: add it to the docker group (sudo usermod -aG docker $USER), then log out and in.")
    else:
        info.update(state="daemon_stopped", hint="Docker is installed but not running: start Docker Desktop (or sudo systemctl start docker).")
    if real and info["state"] != "ready":
        _setup_refine(info)
    if info["running"] and root is not None:
        info["image"] = image_state(root, exe, run, environ)
    return info


def _setup_refine(info: dict) -> None:
    """Windows and WSL 2: the same detector as `plasbench install-tools docker` (python/docker_setup.py) looks at Docker Desktop on the Windows side, so that a Docker Desktop that
    is installed is never reported as 'not installed': it is installed-but-not-started, starting, or running with WSL integration off."""
    try:
        import sys as _sys
        folder = str(Path(__file__).resolve().parent.parent / "python")
        if folder not in _sys.path:
            _sys.path.insert(0, folder)
        import docker_setup
        environment = docker_setup.detect_environment()
        if environment.get("kind") not in ("windows", "wsl2"):
            return
        found = docker_setup.probe(environment)
        diag = docker_setup.diagnose(found, environment)
    except Exception:  # noqa: BLE001 - a refinement only: the plain answer above stands
        return
    if found["state"] in docker_setup.WIN_STATES:
        info.update(state="wsl_integration_off" if found["state"] == "engine_up_wsl_integration_off" else "daemon_stopped", installed=True, hint=diag["title"], setup_state=found["state"])


def image_state(root, exe, run=None, environ=None) -> dict:
    run = run or _run
    image, explicit = configured_image(root, exe=exe, run=run, environ=environ)
    code, out = run([exe, "image", "inspect", image, "--format", "{{.Id}}|{{.Size}}|{{.Created}}|{{len .RepoDigests}}"], 15)
    present = code == 0 and "|" in out
    tag_version = image_tag_version(image)
    row = {"name": image, "explicit": explicit, "present": present, "version": tag_version,
           "matches": (tag_version == __version__) if tag_version else None, "source": "built-locally" if image.endswith("-local") or image.startswith("plasbench:") else "pulled"}
    if present:
        ident, size, created, digests = (out.split("|", 3) + ["", "", ""])[:4]
        row.update(id=ident, size_bytes=int(size) if size.isdigit() else None, created=created)
        if digests.strip().isdigit():     # an image that came from a registry has a repo digest; one built here has none
            row["source"] = "pulled" if int(digests) > 0 else "built-locally"
    return row


def configured_image(root, exe=None, run=None, environ=None):
    """(image name, explicit). PLASBENCH_DOCKER_IMAGE wins; else the published image of this version if it is on this computer, else the one built here, else the published name (to pull)."""
    run = run or _run
    explicit = setting(root, "PLASBENCH_DOCKER_IMAGE", "", environ).strip()
    if explicit:
        return explicit, True
    pub, loc = published_image(), local_tag()
    exe = exe if exe is not None else docker_exe()
    if exe:
        for name in (pub, loc):
            if run([exe, "image", "inspect", name, "--format", "{{.Id}}"], 15)[0] == 0:
                return name, False
    return pub, False


def installed_version(image, exe, run=None):
    """The PlasBench version inside the image, from `docker run --rm IMAGE plasbench --version`, or (None, the output)."""
    run = run or _run
    code, out = run([exe, "run", "--rm", image, "plasbench", "--version"], 120)
    m = re.search(r"plasbench\s+(\S+)", out or "")
    return (m.group(1) if code == 0 and m else None), out


# ---------------------------------------------------------------- the image: present, pulled or built
def build_plan(root, tag) -> dict:
    """What a local build is, in words, read from the Dockerfile: {'tag', 'context', 'lines'}. Nothing is measured, so no size or time is promised."""
    dockerfile = Path(root) / "Dockerfile"
    try:
        text = dockerfile.read_text(encoding="utf-8")
    except OSError:
        text = ""
    envs = len(re.findall(r"micromamba create", text))
    lines = [f"Build the image {tag} from {dockerfile} (build folder: {root}).",
             f"It installs {envs or 'several'} conda environments (the benchmark tools, MOB-suite and gplas2 in their own) on top of the micromamba base image.",
             "This needs the internet (the base image, conda-forge and bioconda, GitLab for gplas2) and is the slow route: not measured; expect from half an hour to several hours "
             "and several GB of disk. Finished layers are cached, so running it again resumes.",
             "Nothing runs as root on this computer: Docker builds inside its own service. Databases are not part of the image; they are downloaded on first use."]
    return {"tag": tag, "context": str(root), "dockerfile": str(dockerfile), "conda_environments": envs, "lines": lines}


def build_argv(root, tag, exe="docker", version=__version__, buildkit=False, extra_args=()):
    """The `docker build` command: an argument list. The build context is the checkout (its .dockerignore is honoured); no --no-cache."""
    argv = [exe, "build", "-t", tag, "-f", str(Path(root) / "Dockerfile"),
            "--build-arg", f"PLASBENCH_VERSION={version}", "--build-arg", f"IMAGE_NAME={tag}",
            "--build-arg", f"BUILD_DATE={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"]
    if buildkit:
        argv.insert(2, "--progress=plain")
    argv += list(extra_args)
    argv.append(str(root))
    return argv


def disk_warning(path, need_gb=12.0, usage=shutil.disk_usage):
    """A warning when the drive that holds `path` has less than need_gb free (Docker keeps images in its own disk; this is the nearest thing a program can check). '' when fine."""
    try:
        target = Path(path)
        while not target.exists() and target != target.parent:
            target = target.parent
        free = usage(str(target)).free / 2 ** 30
    except OSError:
        return ""
    if free < need_gb:
        return f"Only {free:.1f} GB are free on the drive of {path}: building the image needs about {need_gb:.0f} GB (Docker's own disk may be elsewhere; Docker Desktop shows it in Settings > Resources)."
    return ""


def ensure_image(root, *, assume_yes=False, ask=None, out=print, run=None, streamer=None, rebuild=False, policy=None, exe=None, environ=None, net_require=None) -> dict:
    """Make the image ready. -> {'ok', 'image', 'source': 'present'|'pulled'|'built-locally', 'code', 'message'}.
    Order: present locally -> pull (PLASBENCH_DOCKER_PULL) -> build from the Dockerfile after consent (assume_yes, or `ask(question)` returns True).
    Without consent the answer is code 21 (like install-tools) and nothing is built."""
    run = run or _run
    streamer = streamer or stream
    exe = exe if exe is not None else docker_exe()
    if not exe:
        return {"ok": False, "image": "", "source": "", "code": 1, "message": "Docker is not installed (see the Tools page, Install Docker)."}
    policy = policy or pull_policy(root, environ)
    image, explicit = configured_image(root, exe, run, environ)
    present = run([exe, "image", "inspect", image, "--format", "{{.Id}}"], 15)[0] == 0
    if present and not rebuild and policy != "always":
        return {"ok": True, "image": image, "source": "present", "code": 0, "message": f"The image {image} is on this computer."}
    if not rebuild and policy != "never":
        refused = None
        try:
            if net_require:
                net_require(["ghcr"])
        except Exception as exc:  # noqa: BLE001 - netcheck.NoInternet
            refused = str(getattr(exc, "message", exc))
        if refused:
            out("[plasbench] " + refused.splitlines()[0])
        else:
            out(f"[plasbench] Pulling {image} ...")
            code, tail = streamer([exe, "pull", image], None, out, 60.0, f"pulling {image}")
            if code == 0:
                return {"ok": True, "image": image, "source": "pulled", "code": 0, "message": f"Pulled {image}."}
            failure = classify_failure("\n".join(tail))
            out(f"[plasbench] The pull failed ({failure['kind']}): {failure['advice']}")
    if present and not rebuild:
        return {"ok": True, "image": image, "source": "present", "code": 0, "message": f"Could not update {image}; using the copy on this computer."}
    target = image if explicit and "/" not in image else local_tag()
    if explicit and "/" in image and not rebuild:
        return {"ok": False, "image": image, "source": "", "code": 1,
                "message": f"The image {image} (set in PLASBENCH_DOCKER_IMAGE) is not on this computer and could not be pulled. Fix the name, or clear the setting to build one here."}
    if not (Path(root) / "Dockerfile").is_file():
        return {"ok": False, "image": image, "source": "", "code": 1, "message": f"Cannot build: there is no Dockerfile in {root}."}
    plan = build_plan(root, target)
    for line in plan["lines"]:
        out("[plasbench] " + line)
    warn = disk_warning(root)
    if warn:
        out("[plasbench] WARNING: " + warn)
    if net_require:
        try:
            net_require(["docker", "conda"])
        except Exception as exc:  # noqa: BLE001
            msg = str(getattr(exc, "message", exc))
            return {"ok": False, "image": target, "source": "", "code": 3, "message": "Building needs the internet: " + msg.splitlines()[0]}
    if not (assume_yes or (ask is not None and ask(f"Build the image {target} now?"))):
        return {"ok": False, "image": target, "source": "", "code": EXIT_CONSENT, "plan": plan,
                "message": "The image is not available (the pull failed or it is not published). To build it here run: plasbench runtime build --yes   (consent needed; nothing was changed)"}
    buildkit = run([exe, "buildx", "version"], 10)[0] == 0
    env = dict(os.environ, DOCKER_BUILDKIT="1" if buildkit else "0")
    code, tail = streamer(build_argv(root, target, exe, buildkit=buildkit), env, out, 60.0, f"building {target}")
    if code != 0:
        why = classify_failure("\n".join(tail))
        out(f"[plasbench] The build failed ({why['kind']}" + (f", step: {why['step']}" if why["step"] else "") + f"): {why['advice']}")
        out("[plasbench] Last lines of the build output:")
        for line in tail[-12:]:
            out("    " + line)
        return {"ok": False, "image": target, "source": "", "code": 1, "failure": why, "message": why["advice"]}
    return {"ok": True, "image": target, "source": "built-locally", "code": 0, "message": f"Built {target}."}


VERIFIED_FILE = "runtime_verified.json"


def verify_image(image, exe, run=None, ui_home=None) -> dict:
    """The image's PlasBench version equals this one? Cached per image id in ~/.plasbench/ui so a run pays the container start only once per image.
    -> {'ok', 'version', 'message'}."""
    run = run or _run
    home = Path(ui_home or os.environ.get("PLASBENCH_UI_HOME") or Path.home() / ".plasbench" / "ui")
    code, ident = run([exe, "image", "inspect", image, "--format", "{{.Id}}"], 15)
    cache = {}
    try:
        cache = json.loads((home / VERIFIED_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    key = f"{ident}|{__version__}"
    if code == 0 and cache.get(key):
        return {"ok": True, "version": __version__, "message": "verified earlier"}
    version, text = installed_version(image, exe, run)
    if version is None:
        return {"ok": False, "version": None, "message": f"`docker run --rm {image} plasbench --version` failed: {text[-300:] or 'no output'}"}
    if version != __version__:
        return {"ok": False, "version": version, "message": (f"The image {image} holds PlasBench {version} but this is {__version__}. Their scripts differ, so runs would not be what you configured. "
                                                             f"Pull the matching image ({published_image()}) or run: plasbench runtime build --rebuild")}
    if code == 0:
        cache[key] = True
        try:
            home.mkdir(parents=True, exist_ok=True)
            (home / VERIFIED_FILE).write_text(json.dumps(cache), encoding="utf-8")
        except OSError:
            pass
    return {"ok": True, "version": version, "message": "matches"}


# ---------------------------------------------------------------- paths: host -> container
def to_container(path, kind=None) -> str:
    """The path a container sees for a host path. Linux, WSL (/mnt/d/x) and macOS keep the same path (identical mounts). Native Windows D:\\x -> /mnt/d/x.
    A UNC share, a relative path or a path with a colon `docker -v` cannot take raises PathError."""
    kind = kind or ("windows" if os.name == "nt" else "posix")
    text = str(path).strip()
    if not text or re.search(r"[\x00-\x1f]", text):
        raise PathError("an empty or unprintable path cannot be mounted")
    if UNC_RE.match(text):
        raise PathError(f"{text} is a network share, which cannot be mounted into a container directly. Map it to a drive letter first (or mount it in WSL with `mount -t drvfs`).")
    m = DRIVE_RE.match(text)
    if m:
        if kind == "windows":
            rest = text[2:].replace("\\", "/").strip("/")
            return f"/mnt/{m.group(1).lower()}" + ("/" + rest if rest else "")
        raise PathError(f"{text} is a Windows path but PlasBench is running on Linux or macOS: use the Linux form (WSL: /mnt/{m.group(1).lower()}/...).")
    if not text.startswith("/"):
        raise PathError(f"{text} is not a full path (a relative path means a different folder inside the container).")
    if ":" in text:
        raise PathError(f"{text} contains a colon, which `docker run -v` cannot take; rename the folder or use another path.")
    return text.rstrip("/") or "/"


def host_for_mount(path, kind=None) -> str:
    """The host side of `-v`: unchanged on Linux/macOS/WSL; D:\\x (backslashes) on Windows."""
    kind = kind or ("windows" if os.name == "nt" else "posix")
    text = str(path).strip()
    if kind == "windows" and DRIVE_RE.match(text):
        return text[0].upper() + ":" + text[2:].replace("/", "\\")
    return text


def translate_value(value, kind=None):
    """A setting's value as the container should see it: a full path is translated, anything else is returned as it is."""
    if isinstance(value, str) and (value.startswith("/") or DRIVE_RE.match(value) or UNC_RE.match(value)):
        return to_container(value, kind)
    return value


def from_container(path, kind=None) -> str:
    """The inverse of to_container (for messages): /mnt/d/x -> D:\\x on native Windows; unchanged elsewhere."""
    kind = kind or ("windows" if os.name == "nt" else "posix")
    m = re.match(r"^/mnt/([a-z])(/.*)?$", str(path))
    if kind == "windows" and m:
        return m.group(1).upper() + ":" + (m.group(2) or "\\").replace("/", "\\")
    return str(path)


def _inside(child: str, parent: str) -> bool:
    child, parent = child.rstrip("/"), parent.rstrip("/")
    return child == parent or child.startswith(parent + "/")


def effective_paths(root, env=None, environ=None) -> dict:
    """The folders a run uses, as config/config.sh would work them out on the host: {NAME: path string} (explicit env, the environment, config/local.env, the default)."""
    environ = os.environ if environ is None else environ
    env = env or {}
    local = read_local_env(root, environ)
    root = Path(root)

    def pick(name, *alts, default=""):
        for source in (env, environ, local):
            for key in (name,) + alts:
                if source.get(key):
                    return str(source[key])
        return default
    paths = {
        "DATA_DIR": pick("DATA_DIR", "PLASBENCH_DATA_DIR", default=str(root / "data")),
        "RESULTS_DIR": pick("RESULTS_DIR", default=str(root / "results")),
        "LOG_DIR": pick("LOG_DIR", default=str(root / "logs")),
        "TMP_DIR": pick("TMP_DIR", default=str(root / "tmp")),
        "PLASBENCH_DB_DIR": pick("PLASBENCH_DB_DIR", default=str(Path(os.path.expanduser("~")) / ".plasbench" / "databases")),
    }
    for name in ("PLASBENCH_WORKSPACE",) + PATH_RO:
        value = pick(name)
        if value:
            paths[name] = value
    if "SAMPLE_SHEET" not in paths:
        paths["SAMPLE_SHEET"] = str(root / "config" / "accessions.tsv")
    local_file = Path(environ.get("PLASBENCH_LOCAL_SETTINGS") or root / "config" / "local.env")
    if "PLASBENCH_LOCAL_SETTINGS" not in paths and local_file.is_file():
        paths["PLASBENCH_LOCAL_SETTINGS"] = str(local_file)
    return paths


def config_names(root) -> set:
    try:
        text = (Path(root) / "config" / "config.sh").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    return set(re.findall(r"^export\s+([A-Z][A-Z0-9_]*)", text, re.M))


def plan_mounts(paths: dict, kind=None, extras=(), exists=os.path.exists, isdir=os.path.isdir, makedirs=os.makedirs) -> tuple:
    """([{'host', 'container', 'rw', 'file'}], [notes]). Folders a run writes are created (by the current user, so Docker does not create them as root); a read-only input
    that does not exist is left out with a note. A mount inside another that covers it is dropped."""
    wanted, notes = [], []
    for name, value in paths.items():
        rw = name in PATH_RW
        if not value:
            continue
        cont = to_container(value, kind)
        if rw and not exists(value):
            makedirs(value, exist_ok=True)
        if not exists(value):
            notes.append(f"{name} ({value}) does not exist, so it is not mounted")
            continue
        wanted.append({"host": str(value), "container": cont, "rw": rw, "file": not isdir(value), "name": name})
    for host, rw in extras:
        if not exists(host):
            if rw:
                makedirs(host, exist_ok=True)
            else:
                continue
        wanted.append({"host": str(host), "container": to_container(host, kind), "rw": rw, "file": not isdir(host), "name": "extra"})
    wanted.sort(key=lambda m: (len(m["container"]), m["container"]))
    kept = []
    for m in wanted:
        dup = [k for k in kept if k["container"] == m["container"]]
        if dup:
            dup[0]["rw"] = dup[0]["rw"] or m["rw"]
            continue
        cover = [k for k in kept if not k["file"] and _inside(m["container"], k["container"]) and (k["rw"] or not m["rw"])]
        if cover:
            continue
        kept.append(m)
    return kept, notes


def container_name(environ=None) -> str:
    environ = os.environ if environ is None else environ
    job = re.sub(r"[^A-Za-z0-9_.-]", "", environ.get("PLASBENCH_JOB_ID", ""))
    return f"plasbench-{job}" if job else f"plasbench-{os.getpid()}-{int(time.time())}"


def build_run_argv(root, command, env=None, *, image, name, kind=None, uid=None, gid=None, extra=None, cpus=None, memory_gb=None, interactive=True,
                   environ=None, exe="docker", extra_mounts=(), image_id="", image_source="", docker_version="", exists=os.path.exists, isdir=os.path.isdir, makedirs=os.makedirs):
    """The full `docker run` command. -> (argv, run_env, plan). `command` is the argument list to run inside the container (cwd /opt/plasbench).
    Secrets (NCBI_API_KEY) are passed as `-e NAME` and travel in `run_env`, never on the command line."""
    environ = dict(os.environ if environ is None else environ)
    kind = kind or ("windows" if os.name == "nt" else "posix")
    env = {k: str(v) for k, v in (env or {}).items()}
    paths = effective_paths(root, env, environ)
    extra = str(extra) if extra else None
    mounts, notes = plan_mounts(paths, kind, [(extra, True)] if extra is not None else [], exists, isdir, makedirs)
    for host, rw in extra_mounts:
        more, more_notes = plan_mounts({}, kind, [(host, rw)], exists, isdir, makedirs)
        mounts += [m for m in more if all(m["container"] != k["container"] for k in mounts)]
        notes += more_notes
    tools_dir = Path(os.path.expanduser("~")) / ".plasbench" / "tools"
    tools_here = False
    if tools_dir.is_dir():
        try:
            tools_cont = to_container(str(tools_dir), kind)
            tools_here = True
            if not any(_inside(tools_cont, m["container"]) for m in mounts if not m["file"]):
                mounts.append({"host": str(tools_dir), "container": tools_cont, "rw": False, "file": False, "name": "user tools"})
        except PathError:
            tools_here = False
    run_env = dict(environ)
    run_env.update(env)
    argv = [exe, "run", "--rm", "--name", name, "-w", APP_DIR]
    if interactive:
        argv.append("-i")
    if uid is not None and gid is not None and kind == "posix" and sys.platform != "darwin":
        argv += ["--user", f"{uid}:{gid}"]
    if cpus:
        argv += ["--cpus", str(cpus)]
    if memory_gb:
        argv += ["--memory", f"{int(memory_gb)}g", "--memory-swap", f"{int(memory_gb)}g"]
    argv += ["--tmpfs", f"{CONTAINER_HOME}:rw,exec,mode=1777,size=1g"]
    for m in mounts:
        argv += ["-v", f"{host_for_mount(m['host'], kind)}:{m['container']}" + ("" if m["rw"] else ":ro")]
    shown_env = {"HOME": CONTAINER_HOME, "PLASBENCH_RUNTIME": "docker", "CONTAINER_IMAGE": image, "PLASBENCH_IMAGE_SOURCE": image_source or "unknown",
                 "PLASBENCH_DOCKER_VERSION": docker_version or "", "PLASBENCH_IN_DOCKER": "1"}
    if image_id:
        shown_env["CONTAINER_IMAGE_DIGEST"] = image_id
    for key, value in paths.items():
        shown_env[key] = to_container(value, kind)
    if extra is not None:
        base = to_container(extra, kind)
        shown_env.update(PLASBENCH_EXTRA_HOME=base, PLASBENCH_EXTRA_BIN=base + "/bin", PLASBENCH_EXTRA_PREFIX=base + "/envs/extras",
                         CONDA_ENVS_PATH=base + "/envs:/opt/conda/envs", CONDA_PKGS_DIRS=base + "/pkgs")
    if tools_here:
        shown_env["PLASBENCH_TOOLS_PATH"] = tools_cont
    allowed = (config_names(root) | set(ALWAYS_PASS) | set(env)) - NEVER_PASS - set(paths) - set(shown_env)
    for key in sorted(allowed):
        if key in run_env and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            value = run_env[key]
            try:
                moved = translate_value(value, kind)
            except PathError:
                moved = value
            if moved != value:
                shown_env[key] = moved
            else:
                argv += ["-e", key]
    for key, value in sorted(shown_env.items()):
        argv += ["-e", f"{key}={value}"]
    # Precedence on PATH: the extras' own wrappers (extras/bin), then the image (its pinned tools always win), then the extras environment (tools the image lacks).
    wrapper = 'PATH="${PLASBENCH_EXTRA_BIN:+$PLASBENCH_EXTRA_BIN:}$PATH${PLASBENCH_EXTRA_PREFIX:+:$PLASBENCH_EXTRA_PREFIX/bin}"; export PATH; exec "$@"'
    argv += [image, "sh", "-c", wrapper, "plasbench-runtime"] + [str(c) for c in command]
    plan = {"image": image, "name": name, "mounts": [{"host": m["host"], "container": m["container"], "rw": m["rw"]} for m in mounts],
            "identical_paths": all(m["host"].replace("\\", "/") == m["container"] for m in mounts), "notes": notes}
    return argv, run_env, plan


# ---------------------------------------------------------------- running a command in the container
def _marker(name, environ=None):
    environ = os.environ if environ is None else environ
    job_dir, job = environ.get("PLASBENCH_JOB_DIR"), environ.get("PLASBENCH_JOB_ID")
    if job_dir and job:
        return Path(job_dir) / (job + ".container")
    return None


def stop_container(name, exe=None, run=None, timeout=15) -> bool:
    """`docker stop` of a named container (the window's Cancel). True when docker was asked and said ok."""
    exe = exe if exe is not None else docker_exe()
    if not exe or not name:
        return False
    return (run or _run)([exe, "stop", "-t", "10", name], timeout)[0] == 0


def stop_for_job(job_dir, job_id, run=None) -> bool:
    """Cancel support: when the job started a container (it left JOB_ID.container), stop it. Starts no docker process for a job that has none."""
    marker = Path(job_dir) / (job_id + ".container")
    try:
        name = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return stop_container(name, run=run)


def execute(root, command, env=None, *, assume_yes=False, interactive_ok=True, out=print, run=None, streamer=None, exe=None, environ=None, net_require=None,
            allow_build=True, runner=None) -> int:
    """Run `command` (an argument list, e.g. ['bash', 'scripts/run_all.sh', '0', '1']) inside the PlasBench container with the study folders mounted at their own paths.
    Returns the container's exit code (so 0/1/6/20/21 pass straight through), 21 when the image needs a build that was not agreed, or 1 when Docker cannot be used."""
    run = run or _run
    environ = dict(os.environ if environ is None else environ)
    exe = exe if exe is not None else docker_exe()
    state = probe(root, run=run, exe=exe, environ=environ)
    if state["state"] != "ready":
        out(f"[plasbench] ERROR: Docker is not ready ({state['state'].replace('_', ' ')}). {state['hint']}")
        out("[plasbench] To run with conda instead: plasbench runtime use conda  (or add --runtime conda).")
        return 1

    def ask(question):
        if not (interactive_ok and sys.stdin and sys.stdin.isatty()):
            return False
        try:
            return input(f"[plasbench] {question} [y/N] ").strip().lower() in ("y", "yes")
        except EOFError:
            return False
    got = ensure_image(root, assume_yes=assume_yes and allow_build, ask=ask if allow_build else None, out=out, run=run, streamer=streamer, exe=exe, environ=environ, net_require=net_require)
    if not got["ok"]:
        out("[plasbench] " + got["message"])
        return got["code"]
    image = got["image"]
    check = verify_image(image, exe, run)
    if not check["ok"]:
        out("[plasbench] ERROR: " + check["message"])
        return 1
    info = image_state(root, exe, run, environ)
    source = got["source"] if got["source"] != "present" else info.get("source", "pulled")
    name = container_name(environ)
    try:
        cpus = int(env["THREADS"]) if env and env.get("THREADS") else None
    except ValueError:
        cpus = None
    memory = None
    try:
        memory = int(float((env or {}).get("MEMORY_GB") or environ.get("MEMORY_GB") or 0)) or None
    except ValueError:
        pass
    uid = os.getuid() if hasattr(os, "getuid") else None
    gid = os.getgid() if hasattr(os, "getgid") else None
    try:
        argv, run_env, plan = build_run_argv(root, command, env, image=image, name=name, uid=uid, gid=gid, extra=extra_home(root, environ=environ), cpus=cpus, memory_gb=memory,
                                             environ=environ, exe=exe, image_id=info.get("id", ""), image_source=source, docker_version=state["version"])
    except PathError as exc:
        out(f"[plasbench] ERROR: {exc}")
        return 2
    out(f"[plasbench] Runtime: docker  image {image} ({source})  container {name}")
    for note in plan["notes"]:
        out("[plasbench] note: " + note)
    marker = _marker(name, environ)
    if marker:
        try:
            marker.write_text(name, encoding="utf-8")
        except OSError:
            marker = None
    try:
        code = (runner or (lambda a, e: subprocess.run(a, env=e, check=False).returncode))(argv, run_env)
    finally:
        if marker:
            try:
                marker.unlink()
            except OSError:
                pass
    if code in (125, 126, 127):
        out(f"[plasbench] ERROR: docker could not start the container (exit {code}). Run `plasbench runtime check` to find out why.")
    return code


# ---------------------------------------------------------------- `plasbench runtime check`
def check_steps(root, *, run=None, exe=None, environ=None, kind=None, workdir=None) -> list:
    """The self-test, one row per step: [{'step', 'ok', 'detail'}]. Starts only tiny containers (`plasbench --version`, a mount write/read)."""
    run = run or _run
    environ = dict(os.environ if environ is None else environ)
    kind = kind or ("windows" if os.name == "nt" else "posix")
    exe = exe if exe is not None else docker_exe()
    rows = []

    def add(step, ok, detail):
        rows.append({"step": step, "ok": bool(ok), "detail": detail})
        return ok
    state = probe(root, run=run, exe=exe, environ=environ)
    if not add("Docker answers", state["state"] == "ready", (f"Docker {state['version']} ({state.get('arch') or 'unknown architecture'})" if state["state"] == "ready" else state["hint"] or state["state"])):
        return rows
    info = state["image"]
    add("Image on this computer", info.get("present"), (f"{info['name']} ({info.get('size_bytes') or 'size unknown'} bytes), {info.get('source')}" if info.get("present")
                                                          else f"{info.get('name')} is not here: plasbench runtime pull, or plasbench runtime build"))
    if not info.get("present"):
        return rows
    version, text = installed_version(info["name"], exe, run)
    add("`plasbench --version` in the container", version == __version__,
        f"{version}" if version == __version__ else (f"the image holds {version}, this is {__version__}" if version else text[-300:]))
    base = Path(workdir or root)
    probe_dir = base / "data"
    try:
        probe_dir.mkdir(parents=True, exist_ok=True)
        token = f"plasbench-mount-test-{os.getpid()}-{int(time.time())}.txt"
        host_file = probe_dir / token
        cont_dir = to_container(str(probe_dir), kind)
        argv, run_env, _plan = build_run_argv(root, ["sh", "-c", 'echo ok > "$1"; cat "$1"', "t", f"{cont_dir}/{token}"], {"DATA_DIR": str(probe_dir)}, image=info["name"],
                                              name=f"plasbench-check-{os.getpid()}", uid=os.getuid() if hasattr(os, "getuid") else None,
                                              gid=os.getgid() if hasattr(os, "getgid") else None, extra=None, environ=environ, exe=exe, kind=kind)
        code, out = run(argv, 120, run_env)
        wrote = host_file.is_file() and host_file.read_text(encoding="utf-8").strip() == "ok"
        add("Mount test: the container writes a file, the host reads it", code == 0 and wrote, f"{host_file}" if wrote else f"exit {code}: {out[-300:]}")
        try:
            host_file.unlink()
        except OSError:
            pass
    except (OSError, PathError) as exc:
        add("Mount test: the container writes a file, the host reads it", False, str(exc))
    try:
        sample = str(probe_dir)
        back = from_container(to_container(sample, kind), kind).replace("\\", "/")
        add("Path mapping round trip", back == sample.replace("\\", "/"), f"{sample} -> {to_container(sample, kind)} -> {back}")
    except PathError as exc:
        add("Path mapping round trip", False, str(exc))
    return rows


def format_steps(rows) -> str:
    return "\n".join(f"  {'PASS' if r['ok'] else 'FAIL'}  {r['step']}: {r['detail']}" for r in rows)


def extras_listing(root, environ=None) -> dict:
    """What the persistent storage holds, for the manifest and the window: {'home', 'tools': [name...], 'provenance': [{...}]} (names only, read from disk)."""
    home = extra_home(root, environ=environ)
    tools, prov, packages = [], [], []
    try:
        for folder in (home / "bin", home / "envs" / "extras" / "bin"):
            if folder.is_dir():
                tools += [p.name for p in folder.iterdir() if p.name not in tools]
        tools.sort()
        for meta in sorted((home / "envs" / "extras" / "conda-meta").glob("*.json"))[:2000]:
            try:
                rec = json.loads(meta.read_text(encoding="utf-8"))
                packages.append(f"{rec.get('name')}={rec.get('version')}")
            except (OSError, ValueError):
                continue
        for path in sorted(home.glob("*/plasbench-install.json"))[:50] + sorted(home.glob("envs/*/plasbench-install.json"))[:50]:
            try:
                prov.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
    except OSError:
        pass
    return {"home": str(home), "tools": tools, "provenance": prov, "packages": packages}
