"""Where is the PlasBench folder, and is the installed program the one in it?

`plasbench` needs the PlasBench folder (the one with scripts/run_all.sh, config/, python/). It used to take the current directory only, so every command run from another folder (a new
terminal opens in the home folder) failed with the whole command list. The folder is now found in this order, and the one used is named when it was not the current directory:

  1. --project-root            2. the PLASBENCH_HOME environment variable
  3. the current folder or a parent holding scripts/run_all.sh
  4. the folder recorded at install time (~/.plasbench/install.json, written by install.sh / plasbench upgrade)
  5. the checkout the imported package lives in (its parent holds scripts/run_all.sh)       6. ~/PlasBench

The same module records the install (install.json), writes the optional ~/.local/bin/plasbench launcher, and checks after an upgrade that the program Python imports is the version in
the folder (`python -m plasbench.roots record|launcher|verify FOLDER`; install.sh and plasbench upgrade call it). Standard library only; nothing here imports the rest of plasbench.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

MARKER = "plasbench-launcher"
_VERSION_RE = re.compile(r"""^__version__\s*=\s*["']([^"']+)["']""", re.M)


def home_dir() -> Path:
    return Path(os.path.expanduser("~"))


def state_dir() -> Path:
    return home_dir() / ".plasbench"


def install_file() -> Path:
    return state_dir() / "install.json"


def is_root(path) -> bool:
    try:
        return (Path(path) / "scripts" / "run_all.sh").is_file()
    except OSError:
        return False


def read_version(root) -> str:
    try:
        m = _VERSION_RE.search((Path(root) / "plasbench" / "__init__.py").read_text(encoding="utf-8"))
        return m.group(1) if m else ""
    except OSError:
        return ""


def read_install() -> dict:
    try:
        data = json.loads(install_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def resolve(explicit=None, cwd=None, env=None, package_file=None) -> tuple:
    """(root or None, how, tried). `how` is a short phrase for the notice; `tried` lists every place looked at (for the error). explicit: the --project-root the user typed (not validated here)."""
    env = os.environ if env is None else env
    cwd = Path(cwd) if cwd else Path.cwd()
    tried = []
    if explicit:
        return Path(explicit).resolve(), "given with --project-root", [str(explicit)]
    given = env.get("PLASBENCH_HOME")
    if given:
        tried.append(f"PLASBENCH_HOME={given}")
        if is_root(Path(given).expanduser()):
            return Path(given).expanduser().resolve(), "set by PLASBENCH_HOME", tried
    here = cwd.resolve()
    for folder in (here, *here.parents):
        if is_root(folder):
            return folder, "the current folder" if folder == here else f"the parent of the current folder ({folder})", tried
    tried.append(f"the current folder {here} and its parents")
    recorded = read_install().get("root")
    if recorded:
        tried.append(f"{recorded} (recorded at install time in {install_file()})")
        if is_root(recorded):
            return Path(recorded).resolve(), "recorded at install time", tried
    pkg = Path(package_file or __file__).resolve().parent.parent
    if is_root(pkg):
        return pkg, "the folder this plasbench program was imported from", tried
    tried.append(f"the folder of the imported program ({pkg})")
    default = home_dir() / "PlasBench"
    tried.append(str(default))
    if is_root(default):
        return default.resolve(), "the default location ~/PlasBench", tried
    return None, "", tried


def not_found_message(tried) -> str:
    return ("plasbench could not find the PlasBench folder (the one with scripts/run_all.sh). Looked at: " + "; ".join(tried) + ".\n"
            "Fix it one of three ways:\n"
            "  1. cd into your PlasBench folder first (for example: cd ~/PlasBench)\n"
            "  2. pass it: plasbench --project-root /path/to/PlasBench <command>   (or set PLASBENCH_HOME=/path/to/PlasBench)\n"
            "  3. install or upgrade from that folder (./install.sh), which records it for next time\n"
            "Run 'plasbench --help' for the list of commands.")


def record_install(root, version="", python=None) -> Path:
    """Write ~/.plasbench/install.json: the folder, its version, and the Python that was installed into."""
    data = {"root": str(Path(root).resolve()), "version": version or read_version(root), "python": python or sys.executable, "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    folder = state_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = install_file()
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(data, indent=2) + "\n")
    return target


def _sq(text: str) -> str:
    return "'" + str(text).replace("'", "'\\''") + "'"


def launcher_text(python=None) -> str:
    exe = Path(python or sys.executable)
    bindir = exe.parent
    console = bindir / "plasbench"
    return ("#!/bin/sh\n"
            f"# {MARKER}: written by PlasBench (install.sh / plasbench upgrade) so `plasbench` works from any terminal. Safe to delete; PLASBENCH_NO_LAUNCHER=1 stops it being written.\n"
            f"PATH={_sq(bindir)}\"${{PATH:+:$PATH}}\"; export PATH\n"
            f"if [ -x {_sq(console)} ]; then exec {_sq(console)} \"$@\"; fi\n"
            f"exec {_sq(exe)} -m plasbench \"$@\"\n")


def write_launcher(python=None, bindir=None, env=None) -> tuple:
    """(path or None, message). Writes ~/.local/bin/plasbench unless PLASBENCH_NO_LAUNCHER=1, or a file we did not write is already there (never overwritten)."""
    env = os.environ if env is None else env
    if env.get("PLASBENCH_NO_LAUNCHER") == "1":
        return None, "no launcher written (PLASBENCH_NO_LAUNCHER=1)"
    if os.name == "nt":
        return None, "no launcher written on Windows"
    folder = Path(bindir) if bindir else home_dir() / ".local" / "bin"
    target = folder / "plasbench"
    try:
        if target.exists() or target.is_symlink():
            try:
                mine = MARKER in target.read_text(encoding="utf-8", errors="replace")[:600] and not target.is_symlink()
            except OSError:
                mine = False
            if not mine:
                return None, f"{target} already exists and was not made by PlasBench: left alone"
        folder.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(launcher_text(python))
        os.chmod(target, 0o755)
    except OSError as exc:
        return None, f"could not write the launcher {target}: {exc}"
    on_path = str(folder) in [os.path.normpath(p) for p in (env.get("PATH") or "").split(os.pathsep)]
    note = f"launcher written: {target} (type `plasbench` from any terminal)"
    if not on_path:
        note += f"; {folder} is not on your PATH: add it with  export PATH=\"{folder}:$PATH\"  in ~/.bashrc"
    return target, note


def imported_package(python=None, cwd=None) -> tuple:
    """(version, folder) of the plasbench that `python` imports from a neutral directory (what a terminal outside the PlasBench folder gets), or ('', reason)."""
    code = "import plasbench, os; print(plasbench.__version__); print(os.path.dirname(os.path.realpath(plasbench.__file__)))"
    try:
        done = subprocess.run([python or sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60, cwd=str(cwd or home_dir()))
    except (OSError, subprocess.SubprocessError) as exc:
        return "", f"could not run Python: {exc}"
    lines = done.stdout.strip().splitlines()
    if done.returncode != 0 or len(lines) < 2:
        return "", (done.stderr.strip().splitlines() or ["plasbench is not installed in this Python"])[-1]
    return lines[0], lines[1]


def pip_command(root, python=None) -> list:
    return [python or sys.executable, "-m", "pip", "install", "--no-deps", str(root)]


def verify(root, python=None, run=None) -> dict:
    """Is the program Python imports (outside the folder) the version the folder holds? {ok, folder_version, imported_version, imported_path, editable, message}."""
    folder_version = read_version(root)
    version, path = (run or imported_package)(python)
    out = {"ok": False, "folder_version": folder_version, "imported_version": version, "imported_path": path, "root": str(root)}
    if not version:
        out["message"] = f"plasbench is not importable by {python or sys.executable}: {path}"
    elif folder_version and version != folder_version:
        out["message"] = (f"the installed plasbench is {version} (at {path}) but the folder {root} holds {folder_version}. "
                          f"Run: {' '.join(_q(a) for a in pip_command(root, python))}")
    else:
        out["ok"] = True
        out["editable"] = Path(path).resolve().parent == Path(root).resolve()
        out["message"] = f"plasbench {version} at {path}" + (" (the folder itself)" if out["editable"] else " (an installed copy)") + " matches the folder"
    return out


def _q(text: str) -> str:
    text = str(text)
    return text if re.fullmatch(r"[\w@%+=:,./-]+", text) else _sq(text)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2 or argv[0] not in ("record", "launcher", "verify"):
        print("usage: python -m plasbench.roots record|launcher|verify FOLDER", file=sys.stderr)
        return 2
    action, root = argv[0], Path(argv[1])
    if action == "record":
        print(f"recorded {record_install(root)}")
    elif action == "launcher":
        path, message = write_launcher()
        print(message)
    else:
        res = verify(root)
        print(res["message"])
        return 0 if res["ok"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
