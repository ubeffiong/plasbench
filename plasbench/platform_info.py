"""Where is PlasBench running, and how should its tools run there? (after GenoSuv's envinfo.py)

`detect()` describes the machine: operating system, CPU architecture, whether PlasBench itself runs inside WSL, the Python
and conda environment, the `plasbench` conda environment, Docker, and resources. `recommend()` turns that into a plan:
which way to run the tools (the `plasbench` conda environment, or the release's Docker image) and the steps to get
there, with the limits stated plainly. The window's Set up page shows it; `plasbench ui` uses `tools_path()` so every
command it starts finds the environment's tools, however the window itself was started.

Platform facts this encodes:
  * The benchmark tools (SPAdes, MOB-suite, Platon, minimap2, ...) are Linux/macOS bioconda packages; they do not run on
    native Windows. On Windows, PlasBench is installed and run inside WSL2 (Ubuntu); the window opens in the Windows
    browser (WSL2 forwards localhost), and the desktop icon starts it inside WSL.
  * Linux and WSL2: native. Conda (no sudo) is the primary mode; Docker (`ghcr.io/ubeffiong/plasbench`) runs the
    release image without installing anything else.
  * macOS: native. Intel: conda or Docker. Apple Silicon: conda (some bioconda tools have no osx-arm64 build and need
    Rosetta); the image is linux/amd64 and runs emulated, slowly.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ENV_NAME = "plasbench"
IMAGE = "ghcr.io/ubeffiong/plasbench"


def os_kind() -> str:
    return "windows" if os.name == "nt" else "macos" if sys.platform == "darwin" else "linux"


def in_wsl() -> bool:
    if os_kind() != "linux":
        return False
    try:
        return "microsoft" in Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8").lower()
    except OSError:
        return bool(os.environ.get("WSL_DISTRO_NAME"))


def arch() -> str:
    m = platform.machine().lower()
    return "arm64" if m in ("arm64", "aarch64") else "x86_64" if m in ("x86_64", "amd64") else m


def distro() -> str:
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip('"')
    except OSError:
        pass
    return platform.platform()


def _run(argv, timeout=15) -> tuple:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return p.returncode, (p.stdout or p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def conda_solver():
    for name in ("mamba", "conda", "micromamba"):
        found = shutil.which(name)
        if found:
            return name, found
    for base in ("miniforge3", "mambaforge", "miniconda3", "anaconda3", "micromamba"):
        for exe in ("bin/conda", "bin/micromamba", "condabin/conda.bat", "Scripts/conda.exe"):
            cand = Path.home() / base / exe
            if cand.exists():
                return Path(exe).stem, str(cand)
    return None, None


def env_prefix(name: str = ENV_NAME):
    """The `plasbench` conda environment's folder, wherever the solver keeps it (or None)."""
    if os.environ.get("CONDA_PREFIX") and Path(os.environ["CONDA_PREFIX"]).name == name:
        return Path(os.environ["CONDA_PREFIX"])
    roots = [os.environ.get("MAMBA_ROOT_PREFIX"), os.environ.get("CONDA_ROOT")]
    roots += [str(Path.home() / b) for b in ("miniforge3", "mambaforge", "miniconda3", "anaconda3", "micromamba",
                                                 ".local/share/mamba", ".conda")]
    for root in [r for r in roots if r]:
        cand = Path(root) / "envs" / name
        if (cand / "conda-meta").is_dir():
            return cand
    _solver, exe = conda_solver()
    if exe:
        code, out = _run([exe, "env", "list"])
        if code == 0:
            for line in out.splitlines():
                parts = line.split()
                if parts and parts[0] == name and Path(parts[-1]).is_dir():
                    return Path(parts[-1])
    return None


def tools_path(base_path: str | None = None) -> str:
    """PATH with the `plasbench` environment's tool folders first, so a command started from the window finds the
    environment's tools even when the window was started from a desktop icon without `conda activate`."""
    base_path = base_path if base_path is not None else os.environ.get("PATH", "")
    prefix = env_prefix()
    if not prefix:
        return base_path
    dirs = [prefix / "bin"] if os.name != "nt" else [prefix, prefix / "Library" / "bin", prefix / "Scripts"]
    current = base_path.split(os.pathsep)
    extra = [str(d) for d in dirs if d.is_dir() and str(d) not in current]
    return os.pathsep.join(extra + current)


def docker() -> dict:
    exe = shutil.which("docker")
    if not exe:
        return {"installed": False, "running": False, "image": False}
    code, version = _run([exe, "info", "--format", "{{.ServerVersion}}"], timeout=10)
    running = code == 0 and bool(version) and version[0].isdigit()
    image = False
    if running:
        code, tags = _run([exe, "image", "ls", IMAGE, "--format", "{{.Tag}}"], timeout=10)
        image = code == 0 and bool(tags.strip())
    return {"installed": True, "running": running, "image": image, "version": version if running else ""}


def wsl_installed() -> bool:
    if os_kind() != "windows":
        return False
    code, out = _run(["wsl", "-l", "-q"], timeout=15)
    return code == 0 and bool(out.replace("\x00", "").strip())


def resources() -> dict:
    cpus = os.cpu_count() or 1
    ram = None
    try:
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                            ("avail", ctypes.c_ulonglong), ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong),
                            ("c", ctypes.c_ulonglong), ("d", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]
            ms = MS()
            ms.l = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
            ram = ms.total / 2**30
        elif hasattr(os, "sysconf"):
            ram = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    except (OSError, ValueError, AttributeError):
        pass
    return {"cpus": cpus, "ram_gb": round(ram, 1) if ram else None}


def detect(fast: bool = False) -> dict:
    o = os_kind()
    solver, solver_exe = conda_solver()
    prefix = env_prefix()
    info = {"os": o, "os_label": {"windows": "Windows", "macos": "macOS", "linux": "Linux"}[o], "arch": arch(),
            "in_wsl": in_wsl(), "distro": distro() if o == "linux" else platform.platform(),
            "python": sys.version.split()[0], "conda_solver": solver, "conda_exe": solver_exe,
            "env_prefix": str(prefix) if prefix else None, "env_ready": bool(prefix),
            "active_env": os.environ.get("CONDA_DEFAULT_ENV") or None, "resources": resources()}
    if info["in_wsl"]:
        info["os_label"] = f"Linux (WSL2 inside Windows: {os.environ.get('WSL_DISTRO_NAME', 'Ubuntu')})"
    if not fast:
        info["docker"] = docker()
        info["wsl_installed"] = wsl_installed() if o == "windows" else None
    return info


def recommend(info: dict) -> dict:
    """{'mode': 'conda'|'docker'|'wsl', 'summary', 'reasons', 'steps', 'warnings', 'alternatives'}"""
    o, a = info["os"], info["arch"]
    dock = info.get("docker") or {}
    reasons, steps, warns, alts = [], [], [], []
    mode = "conda"
    if o == "windows":
        mode = "wsl"
        summary = "Windows: install and run PlasBench inside WSL2 (Ubuntu)."
        reasons.append("The benchmark tools are Linux bioconda packages; they cannot run on native Windows. Inside WSL2 "
                       "everything is native Linux, and the window still opens in your Windows browser.")
        if not info.get("wsl_installed"):
            steps.append("Install WSL2 with Ubuntu: open PowerShell as administrator, run  wsl --install , restart the computer.")
        steps.append("In Ubuntu: curl -fL -O https://raw.githubusercontent.com/ubeffiong/plasbench/main/scripts/install_latest.sh "
                     "&& bash install_latest.sh --tools")
        steps.append("The installer puts a PlasBench icon on your Windows desktop; it starts PlasBench inside WSL.")
        warns.append("This window is running natively on Windows: setup, tools, settings, studies and Git work here, "
                     "but benchmark runs need the tools that only WSL provides.")
        alts.append("Docker Desktop (WSL2 backend) with the release image " + IMAGE + ": runs without installing conda.")
    elif info["in_wsl"]:
        summary = "Linux inside WSL2: everything runs natively here; the window opens in the Windows browser."
        reasons.append("The tools come from the plasbench conda environment (no sudo).")
        warns.append("Speed: keep the workspace on WSL's own disk (under /home) rather than /mnt/c, which is much slower "
                     "for many small files.")
        if dock.get("running"):
            alts.append(f"Docker is available: the release image {IMAGE} runs PlasBench without the conda environment.")
    elif o == "linux":
        summary = "Linux: everything runs natively."
        reasons.append("The tools come from the plasbench conda environment, installed in your home folder without sudo.")
        alts.append(f"Docker: the release image {IMAGE} runs PlasBench with every tool pinned"
                    + ("" if dock.get("installed") else " (installing Docker Engine needs sudo)") + ".")
        if a == "arm64":
            warns.append("ARM64 Linux: some bioconda tools have no linux-aarch64 build; the image is x86_64 only.")
    else:
        summary = "macOS: runs natively with the plasbench conda environment."
        if a == "arm64":
            reasons.append("Apple Silicon: conda uses native osx-arm64 builds where bioconda has them.")
            warns.append("Some bioconda tools have no osx-arm64 build: install Rosetta (softwareupdate --install-rosetta) "
                         "and they run as x86_64. The Docker image is linux/amd64 and runs emulated (slow).")
        else:
            reasons.append("Intel Mac: conda or Docker Desktop both work.")
            alts.append(f"Docker Desktop with the release image {IMAGE}.")
    if o != "windows":
        if not info.get("conda_solver"):
            steps.append("Install conda (Set up this computer > Install conda, or plasbench install-conda).")
        if not info.get("env_ready"):
            steps.append("Create the plasbench environment and the core tools: plasbench install-tools core.")
        if dock.get("installed") and not dock.get("running"):
            warns.append("Docker is installed but not running: start Docker Desktop (or the docker service) to use the image.")
    res = info.get("resources") or {}
    if res.get("ram_gb") and res["ram_gb"] < 16:
        warns.append(f"{res['ram_gb']} GB RAM: assembly (SPAdes) is comfortable with 16 GB or more; set a lower memory "
                     "limit on New benchmark > Resources.")
    return {"mode": mode, "summary": summary, "reasons": reasons, "steps": steps, "warnings": warns,
            "alternatives": alts, "docker_command": f"docker pull {IMAGE}:latest && PLASBENCH_IMAGE={IMAGE}:latest "
                                                   "scripts/docker_run.sh plasbench run --cohort public-v1"}
