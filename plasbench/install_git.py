"""`plasbench install-git`: install Git (optional), the right way for this computer.

Git is optional for benchmarking. PlasBench uses it for Version control, the source-control drawer, contributing, and
upgrades from a checkout. On **native Windows** the package that provides it, Git for Windows, also provides
**Git Bash**. PlasBench runs its pipeline scripts with Git Bash there, and the console's Terminal offers it as a
shell.

  Windows (native)  Git for Windows (Git + Git Bash) through winget, Windows' own package manager. winget may ask
                    you to accept its source agreements: answer in the console. Without winget, the download page is
                    printed.
  Linux, WSL        the conda-forge `git` package, installed into the plasbench environment (no sudo). Without that
                    environment, the system command is printed (for example `sudo apt install git`).
  macOS             the conda-forge `git` package into the plasbench environment, or Apple's command line tools
                    (`xcode-select --install`, which opens Apple's installer).
Nothing is installed if Git is already there, unless --force is given.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

from . import platform_info

WINGET_ID = "Git.Git"
DOWNLOAD = "https://git-scm.com/downloads"


def _git_for_windows_bash():
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")):
        if base:
            for rel in (("Git", "bin", "bash.exe"), ("Programs", "Git", "bin", "bash.exe")):
                cand = os.path.join(base, *rel)
                if os.path.isfile(cand):
                    return cand
    return None


def status() -> dict:
    git = shutil.which("git")
    out = {"git": git, "os": platform_info.os_kind()}
    if out["os"] == "windows":
        out["git_bash"] = _git_for_windows_bash()
    return out


def plan(force: bool = False) -> dict:
    """{'action': 'none'|'run'|'manual', 'argv': [...], 'say': '...'}"""
    st = status()
    o = st["os"]
    have = st["git"] and (o != "windows" or st.get("git_bash"))
    if have and not force:
        return {"action": "none", "argv": [], "say": f"Git is already installed: {st['git']}"
                + (f"; Git Bash: {st['git_bash']}" if st.get("git_bash") else "")}
    if o == "windows":
        winget = shutil.which("winget")
        if winget:
            return {"action": "run", "argv": [winget, "install", "--id", WINGET_ID, "-e", "--source", "winget"],
                    "say": "Installing Git for Windows (Git and Git Bash) with winget. If winget asks you to accept its "
                           "source agreements, answer in the console. Windows may ask for permission to install."}
        return {"action": "manual", "argv": [],
                "say": f"winget is not available. Download Git for Windows from {DOWNLOAD} and run its installer "
                       "(the defaults are fine; keep 'Git Bash'). Then press Re-check."}
    solver, exe = platform_info.conda_solver()
    prefix = platform_info.env_prefix()
    if exe and prefix:
        return {"action": "run", "argv": [exe, "install", "-y", "-p", str(prefix), "-c", "conda-forge", "git"],
                "say": f"Installing git from conda-forge into the plasbench environment ({prefix}); no sudo needed."}
    if o == "macos":
        xcs = shutil.which("xcode-select")
        if xcs:
            return {"action": "run", "argv": [xcs, "--install"],
                    "say": "Opening Apple's installer for the command line tools, which include git. Follow its window."}
        return {"action": "manual", "argv": [], "say": f"Install git from {DOWNLOAD}."}
    for pm, cmd in (("apt-get", "sudo apt-get install -y git"), ("dnf", "sudo dnf install -y git"),
                    ("yum", "sudo yum install -y git"), ("zypper", "sudo zypper install -y git"),
                    ("pacman", "sudo pacman -S git")):
        if shutil.which(pm):
            return {"action": "manual", "argv": [],
                    "say": f"Create the plasbench environment first (plasbench install-tools core) and run this again to "
                           f"install git without sudo, or install it system-wide in a terminal:  {cmd}"}
    return {"action": "manual", "argv": [], "say": f"Install git from {DOWNLOAD}."}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="plasbench install-git", description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="Install even if git is already found.")
    ap.add_argument("--dry-run", action="store_true", help="Only say what would be done.")
    args = ap.parse_args(argv)
    p = plan(args.force)
    print(p["say"], flush=True)
    if p["action"] == "none":
        return 0
    if p["action"] == "manual":
        return 1
    print("$ " + " ".join(p["argv"]), flush=True)
    if args.dry_run:
        return 0
    try:
        code = subprocess.run(p["argv"], check=False).returncode
    except OSError as exc:
        print(f"Could not start the installer: {exc}", file=sys.stderr)
        return 1
    if code == 0:
        print("Done. Restart PlasBench (Quit, then start it again) so it finds the new git, then press Re-check.", flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
