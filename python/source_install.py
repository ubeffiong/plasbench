#!/usr/bin/env python3
"""Install the source-distributed tools PlasBench can run, pinned, isolated and verified.

The registry is config/source_tools.json. For a profile in mode "source" this clones the upstream repository, checks out the pinned COMMIT (never a branch
or tag name: those can move), proves it with `git rev-parse`, builds a dedicated environment from the dependency files of that exact commit (or from a
pinned file kept in this repository), runs the tool's verification command, and only then exposes the tool through a small wrapper in the main
environment's bin/ and writes a provenance record. Nothing is left half installed: the clone is staged and moved, an environment that was created is removed
on failure, and a previous working install is put back.

A profile in mode "manual" is one a real investigation found cannot be installed automatically (the evidence is in the registry); it prints the verified
reason and a step-by-step recipe and exits 20, which is information, not a failure.

docs/TOOL_INSTALL_AUDIT.md is generated from the registry by python/generate_install_audit.py.

Exit codes: 0 installed (or already installed at the pinned revision), 1 failed (nothing left half installed), 2 wrong usage or unknown profile,
20 manual steps needed, 21 consent needed (re-run with --yes after reading the plan; nothing was changed).
"""

from __future__ import annotations

import argparse
import io
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "config" / "source_tools.json"
EXIT_FAILED, EXIT_USAGE, EXIT_MANUAL, EXIT_CONSENT = 1, 2, 20, 21
SHA40 = re.compile(r"^[0-9a-f]{40}$")
STEP_TYPES = {"conda_create", "conda_file", "pip_requirements", "pip_install", "clear_execstack"}
WRAPPER_MARK = "# PlasBench source install:"
PROVENANCE = "plasbench-install.json"
SOURCE_DIR = "plasbench-src"
# Services an install needs, by upstream host (config/network_services.tsv).
HOST_SERVICE = {"github.com": "github", "gitlab.com": "gitlab"}


def write_lf(path, text):
    """Write text with LF line endings on every platform (Path.write_text(newline=) needs Python 3.10)."""
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def load(path: Path | None = None) -> dict:
    with open(path or REGISTRY, encoding="utf-8") as handle:
        return json.load(handle)


def _https(url: str) -> bool:
    return isinstance(url, str) and url.startswith("https://") and " " not in url


def validate(registry: dict, root: Path = ROOT) -> list[str]:
    """Every pin is a 40-hex commit, every URL https, every profile has its licence, sources, verification and (manual) evidence."""
    errors: list[str] = []
    profiles = registry.get("profiles") or {}
    if not profiles:
        return ["the registry lists no profiles"]
    for name, entry in profiles.items():
        def bad(message):
            errors.append(f"{name}: {message}")
        if entry.get("mode") not in ("source", "manual"):
            bad("mode must be source or manual")
        if not entry.get("tools"):
            bad("tools is empty")
        if not _https(entry.get("repo", "")) or not entry["repo"].endswith(".git"):
            bad("repo must be an https URL ending in .git")
        if not SHA40.match(entry.get("commit", "")):
            bad("commit must be a 40-character lowercase hex SHA (a tag or branch name can move)")
        if not entry.get("ref") or entry.get("ref") == entry.get("commit"):
            bad("ref must record the release tag or branch the commit was resolved from")
        for key in ("licence", "minutes"):
            if not entry.get(key):
                bad(f"{key} is missing")
        for key in ("download_mb", "disk_gb"):
            if not isinstance(entry.get(key), (int, float)):
                bad(f"{key} must be a number")
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", entry.get("researched", "")):
            bad("researched must be a date (YYYY-MM-DD)")
        verify = entry.get("verify") or {}
        if not verify.get("argv"):
            bad("verify.argv is missing")
        if entry.get("mode") == "source":
            if not entry.get("sources") or not all(_https(u) for u in entry["sources"]):
                bad("sources must be a list of https URLs (where the pin was researched)")
            if not entry.get("commands"):
                bad("commands is empty")
            if not verify.get("why"):
                bad("verify.why is missing")
            conda_steps = [s for s in entry.get("env", {}).get("steps", []) if s.get("type") in ("conda_create", "conda_file")]
            if len(conda_steps) > 1:
                bad("at most one conda step is supported")
            for step in entry.get("env", {}).get("steps", []):
                if step.get("type") not in STEP_TYPES:
                    bad(f"unknown step type {step.get('type')!r}")
                path = step.get("path", "")
                if path.startswith("@") and not (root / path[1:]).is_file():
                    bad(f"pinned file {path[1:]} does not exist in this repository")
            for cmd, spec in entry.get("commands", {}).items():
                if spec.get("kind") not in ("env_bin", "script") or not spec.get("path"):
                    bad(f"command {cmd} needs kind env_bin|script and a path")
                if not isinstance(spec.get("set_env", {}), dict) or not isinstance(spec.get("unset_env", []), list):
                    bad(f"command {cmd}: set_env must be an object and unset_env a list")
        else:
            manual = entry.get("manual") or {}
            if not manual.get("reason") or not manual.get("recipe"):
                bad("a manual profile needs manual.reason and manual.recipe")
            if not manual.get("evidence") or not all(_https(u) for u in manual["evidence"]):
                bad("a manual profile needs https evidence URLs")
    return errors


# ---- running things -------------------------------------------------------------------------------------------------------------------------------------

def _bash() -> str:
    """Git for Windows' bash (never the WSL shim, which fails when WSL is not running), as plasbench/cli.py does."""
    explicit = os.environ.get("PLASBENCH_BASH")
    if explicit:
        return explicit
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base and (Path(base) / "Git" / "bin" / "bash.exe").is_file():
            return str(Path(base) / "Git" / "bin" / "bash.exe")
    return shutil.which("bash") or "bash"


def _argv(argv: list[str], path: str | None = None) -> list[str]:
    """On Windows a shell script is not an executable; run it through bash (the installer targets Linux and WSL, and the tests use fake scripts)."""
    if os.name == "nt" and argv:
        found = None
        for folder in (path if path is not None else os.environ.get("PATH", "")).split(os.pathsep):
            candidate = Path(folder) / argv[0] if folder else None
            if candidate and candidate.is_file():
                found = str(candidate)
                break
        if found and not found.lower().endswith((".exe", ".bat", ".cmd", ".com")):
            try:
                with open(found, "rb") as handle:
                    if handle.read(2) == b"#!":
                        return [_bash(), found] + argv[1:]
            except OSError:
                pass
    return argv


def run(argv: list[str], env: dict | None = None, cwd: Path | None = None, capture: bool = False):
    merged = dict(os.environ)
    merged.update(env or {})
    return subprocess.run(_argv([str(a) for a in argv], merged.get("PATH")), cwd=str(cwd) if cwd else None, env=merged, check=False,
                          stdout=subprocess.PIPE if capture else None, stderr=subprocess.STDOUT if capture else None, text=True if capture else None)


def _rmtree(path, ignore_errors: bool = True):
    """Remove a tree including read-only files (git's object files are read-only, and Windows refuses to delete those)."""
    def retry(function, target, _info):
        try:
            os.chmod(target, 0o700)
            function(target)
        except OSError:
            pass
    shutil.rmtree(path, onerror=retry) if sys.version_info < (3, 12) else shutil.rmtree(path, onexc=retry)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_digest(root: Path) -> str:
    """SHA-256 over every file of the checkout (relative path and content), .git excluded: what was actually downloaded."""
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and ".git" not in p.relative_to(root).parts):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0" + sha256_file(path).encode() + b"\n")
    return digest.hexdigest()


def effective_repo(name: str, entry: dict) -> str:
    """The registry URL. Tests may point a profile at a local bare repository, but only when PLASBENCH_SOURCE_TEST_OVERRIDES=1 is also set; the pin still has to
    resolve to the same commit, so a redirected URL cannot change what is installed."""
    if os.environ.get("PLASBENCH_SOURCE_TEST_OVERRIDES") == "1":
        override = os.environ.get("PLASBENCH_SOURCE_URL_" + re.sub(r"\W", "_", name).upper())
        if override:
            return override
    return entry["repo"]


def services(entry: dict) -> list[str]:
    """The network services config/network_services.tsv names that this install needs."""
    host = re.sub(r"^https://([^/]+)/.*", r"\1", entry["repo"])
    needed = [HOST_SERVICE.get(host, "internet")]
    steps = entry.get("env", {}).get("steps", [])
    if any(s["type"] in ("conda_create", "conda_file") for s in steps):
        needed.append("conda")
    if any(s["type"] in ("pip_requirements", "pip_install") for s in steps):
        needed.append("pypi")
    return needed


# ---- layout and provenance ------------------------------------------------------------------------------------------------------------------------------

class Layout:
    def __init__(self, main_prefix: Path, env_name: str, profile: str):
        self.main = Path(main_prefix)
        self.base = self.main.parent
        self.install = self.base / f"{env_name}-{profile}"
        self.src = self.install / SOURCE_DIR
        self.bin = self.main / "bin"
        self.provenance = self.install / PROVENANCE


def read_provenance(path: Path) -> dict | None:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def plan_text(name: str, entry: dict, layout: Layout | None = None) -> str:
    lines = [f"[PlasBench] {name}: what installing it will do",
             f"  Tools        : {', '.join(entry['tools'])}",
             f"  Source       : {entry['repo']}",
             f"  Revision     : {entry['commit']}  (release {entry['ref']}, resolved {entry['researched']}; a fixed commit, never a moving branch)",
             f"  Licence      : {entry['licence']}",
             f"  Size         : about {entry['download_mb']} MB to download, about {entry['disk_gb']} GB on disk",
             f"  Time         : {entry['minutes']}",
             f"  Internet     : needed ({', '.join(services(entry))})"]
    steps = entry.get("env", {}).get("steps", [])
    if steps:
        lines.append("  Environment  : a dedicated, isolated environment" + (f" at {layout.install}" if layout else "") + ", built from:")
        for step in steps:
            what = {"conda_create": lambda s: "conda packages " + " ".join(s["packages"]), "conda_file": lambda s: "the conda environment file " + s["path"] + " of that revision",
                    "pip_requirements": lambda s: "pip requirements " + s["path"].lstrip("@"), "pip_install": lambda s: "pip install of " + s["target"]}[step["type"]](step)
            lines.append(f"      - {what}")
    else:
        lines.append("  Environment  : none (the tool builds its own on first use; see below)")
    lines.append("  No sudo, no 'curl | sh', https only. A failed install is removed completely.")
    for item in entry.get("inputs", []):
        lines.append(f"  Also needed  : {item}")
    return "\n".join(lines)


def manual_text(name: str, entry: dict) -> str:
    manual = entry["manual"]
    lines = [f"[PlasBench] {name} needs a manual install. Nothing failed; this is a verified limit, not a PlasBench error (exit code {EXIT_MANUAL}).",
             f"  Tools it provides: {', '.join(entry['tools'])}",
             f"  Why PlasBench cannot install it for you: {manual['reason']}",
             f"  Checked against upstream on {entry['researched']}:"]
    lines += [f"    {url}" for url in manual["evidence"]]
    lines.append("  Steps:")
    lines += [f"    {i}. {step}" for i, step in enumerate(manual["recipe"], 1)]
    lines.append("  Then run `plasbench check`; it reports whether the tool is found.")
    return "\n".join(lines)


def _confirm(prompt: str) -> bool:
    if not sys.stdin or not sys.stdin.isatty():
        return False
    try:
        return input(prompt).strip().lower() in ("y", "yes")
    except EOFError:
        return False


# ---- the installer --------------------------------------------------------------------------------------------------------------------------------------

PT_GNU_STACK, PF_X = 0x6474E551, 1


def clear_execstack(path: Path) -> bool:
    """Clear the executable-stack request (PT_GNU_STACK's X flag) of one ELF64 little-endian shared object, in place; True when it changed.
    Recent glibc refuses to load a library that asks for an executable stack (`cannot enable executable stack as shared object requires`), which is what
    PyTorch 1.11's libtorch_cpu.so does; clearing the flag is what `execstack -c` / `patchelf --clear-execstack` do."""
    with open(path, "r+b") as handle:
        head = handle.read(64)
        if head[:4] != b"\x7fELF" or head[4] != 2 or head[5] != 1:
            return False
        phoff, phentsize, phnum = int.from_bytes(head[32:40], "little"), int.from_bytes(head[54:56], "little"), int.from_bytes(head[56:58], "little")
        for index in range(phnum):
            at = phoff + index * phentsize
            handle.seek(at)
            entry = handle.read(8)
            if int.from_bytes(entry[:4], "little") == PT_GNU_STACK:
                flags = int.from_bytes(entry[4:8], "little")
                if flags & PF_X:
                    handle.seek(at + 4)
                    handle.write((flags & ~PF_X).to_bytes(4, "little"))
                    return True
                return False
    return False


def wrapper_env_lines(spec: dict, layout: Layout) -> list[str]:
    """Shell lines a wrapper starts with for a command's `set_env` (name -> value; {install} and {src} are the tool's own folders) and `unset_env` (names)."""
    lines = []
    for name in spec.get("unset_env", []):
        lines.append(f"unset {name}")
    for name, value in spec.get("set_env", {}).items():
        shown = value.replace("{install}", str(layout.install)).replace("{src}", str(layout.src))
        lines += [f'{name}="{shown}"', f"export {name}"]
    return lines


def wrapper_text(name: str, spec: dict, entry: dict, layout: Layout, profile: str) -> str:
    head = ["#!/bin/sh", f"{WRAPPER_MARK} {profile} {entry['commit']} {layout.provenance}",
            f"# Runs {name} from its own pinned, isolated installation (config/source_tools.json, python/source_install.py)."]
    head += wrapper_env_lines(spec, layout)
    if spec["kind"] == "env_bin":
        head += [f'PATH="{layout.install}/bin:$PATH"', "export PATH", f'exec "{layout.install}/bin/{spec["path"]}" "$@"']
    else:
        interpreter = f'"{layout.install}/bin/python"' if spec.get("interpreter") == "python" else spec.get("interpreter", "sh")
        if not spec.get("inherit_path"):
            head += [f'PATH="{layout.install}/bin:$PATH"', "export PATH"]
        head += [f'exec {interpreter} "{layout.src}/{spec["path"]}" "$@"']
    return "\n".join(head) + "\n"


def verify(entry: dict, wrappers_dir: Path, layout: Layout) -> tuple[bool, str]:
    """Run the tool's verification command with the wrappers first on PATH. Returns (ok, first line of what it printed or why it failed)."""
    spec = entry["verify"]
    env = {"PATH": f"{wrappers_dir}{os.pathsep}{layout.install}/bin{os.pathsep}{os.environ.get('PATH', '')}"}
    try:
        result = run(spec["argv"], env=env, capture=True)
    except OSError as exc:
        return False, f"{spec['argv'][0]} could not be started: {exc}"
    text = (result.stdout or "").strip()
    first = text.splitlines()[0] if text else ""
    if result.returncode != 0:
        tail = " | ".join(text.splitlines()[-3:])
        return False, f"`{' '.join(spec['argv'])}` exited {result.returncode}: {tail}"
    if spec.get("expect") and spec["expect"].lower() not in text.lower():
        return False, f"`{' '.join(spec['argv'])}` ran but its output does not contain {spec['expect']!r} ({spec.get('why', '')})"
    return True, first


def _solver_version(solver: str) -> str:
    try:
        out = run([solver, "--version"], capture=True).stdout or ""
        return out.strip().splitlines()[0] if out.strip() else "unreported"
    except OSError:
        return "unreported"


def _dependency_versions(layout: Layout, solver: str) -> list[str]:
    pip = layout.install / "bin" / "pip"
    if not pip.exists():
        return []
    try:
        out = run([str(pip), "freeze"], capture=True).stdout or ""
    except OSError:
        return []
    return [line.strip() for line in out.splitlines() if line.strip() and not line.startswith(("WARNING", "[notice]"))][:400]


def status_of(name: str, entry: dict, main_prefix: Path, env_name: str) -> dict:
    layout = Layout(main_prefix, env_name, name)
    prov = read_provenance(layout.provenance)
    state = "manual" if entry["mode"] == "manual" else "not_installed"
    if prov and entry["mode"] == "source":
        state = "installed" if prov.get("commit") == entry["commit"] else "installed_other_revision"
    return {"profile": name, "state": state, "pinned_commit": entry["commit"], "provenance": prov}


def install(name: str, entry: dict, main_prefix: Path | None, solver: str, env_name: str, assume_yes: bool) -> int:
    if entry["mode"] == "manual":
        print(manual_text(name, entry))
        return EXIT_MANUAL
    if main_prefix is None:
        print(f"ERROR: the main environment '{env_name}' was not found; create it first (bash env/setup_conda.sh), then run:  plasbench install-tools {name} --yes", file=sys.stderr)
        return EXIT_FAILED
    layout = Layout(main_prefix, env_name, name)
    wanted = entry["commit"]
    prov = read_provenance(layout.provenance)
    staging_wrappers = layout.base / f".plasbench-wrappers-{name}-{os.getpid()}"
    if prov and prov.get("commit") == wanted:
        staging_wrappers.mkdir(parents=True, exist_ok=True)
        try:
            for cmd, spec in entry["commands"].items():
                write_lf(staging_wrappers / cmd, wrapper_text(cmd, spec, entry, layout, name))
                os.chmod(staging_wrappers / cmd, 0o755)
            ok, said = verify(entry, staging_wrappers, layout)
        finally:
            _rmtree(staging_wrappers, ignore_errors=True)
        if ok:
            _expose(entry, layout, name)
            print(f"[PlasBench] {name} is already installed at the pinned revision {wanted[:12]} ({entry['ref']}); verified: {said}")
            return 0
        print(f"[PlasBench] {name} is recorded at the pinned revision but does not verify ({said}); reinstalling it.")
    print(plan_text(name, entry, layout))
    if prov and prov.get("commit") != wanted:
        print(f"  Upgrade      : installed revision {str(prov.get('commit'))[:12]} ({prov.get('ref')}) -> pinned {wanted[:12]} ({entry['ref']}); the old one is kept until the new one verifies")
    if not assume_yes:
        if not _confirm("Install it now? [y/N] "):
            print(f"[PlasBench] Consent needed: nothing was installed. Read the plan above, then run:  plasbench install-tools {name} --yes", file=sys.stderr)
            return EXIT_CONSENT
    return _do_install(name, entry, layout, solver, env_name)


def _internet_problem(name: str, entry: dict) -> str:
    """The plain sentence plasbench/netcheck.py gives when a service this install needs is unreachable (nothing is asked when everything is already installed)."""
    if os.environ.get("PLASBENCH_SOURCE_TEST_OVERRIDES") == "1":
        return ""       # a local test upstream: no internet involved
    sys.path.insert(0, str(ROOT))
    try:
        from plasbench import netcheck
    except ImportError:
        return ""
    try:
        netcheck.require(services(entry), action=f"Installing the '{name}' tools")
    except netcheck.NoInternet as exc:
        return exc.message
    return ""


def _expose(entry: dict, layout: Layout, name: str):
    layout.bin.mkdir(parents=True, exist_ok=True)
    for cmd, spec in entry["commands"].items():
        target = layout.bin / cmd
        tmp = layout.bin / f".{cmd}.plasbench-new"
        write_lf(tmp, wrapper_text(cmd, spec, entry, layout, name))
        os.chmod(tmp, 0o755)
        os.replace(tmp, target)


def _do_install(name: str, entry: dict, layout: Layout, solver: str, env_name: str) -> int:
    pid = os.getpid()
    staging = layout.base / f".plasbench-staging-{name}-{pid}"
    staging_wrappers = layout.base / f".plasbench-wrappers-{name}-{pid}"
    backup = layout.base / f"{layout.install.name}.previous-{pid}"
    created_install = False
    moved_backup = False
    started = time.time()
    url = effective_repo(name, entry)
    wanted = entry["commit"]

    def fail(message: str, hint: str) -> int:
        print(f"ERROR: {message}", file=sys.stderr)
        print(f"  Nothing was left half installed. {hint}", file=sys.stderr)
        return EXIT_FAILED

    try:
        for leftover in (staging, staging_wrappers):
            _rmtree(leftover, ignore_errors=True)
        message = _internet_problem(name, entry)
        if message:
            return fail(message, "Connect to the internet and run the same command again; tools already installed keep working offline.")
        staging.mkdir(parents=True)
        src = staging / SOURCE_DIR
        print(f"[PlasBench] cloning {entry['repo']} (staged; it moves into place only after everything verifies)")
        clone = run(["git", "clone", "--quiet", "--no-checkout", url, str(src)])
        if clone.returncode != 0:
            return fail(f"could not clone {entry['repo']} (git exit {clone.returncode}).", "Check the internet connection (plasbench net), then run the same command again.")
        checkout = run(["git", "-C", str(src), "-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", wanted])
        if checkout.returncode != 0:
            return fail(f"revision {wanted} is not in {entry['repo']}.", "Upstream may have rewritten its history; this pin needs to be re-resolved (see config/source_tools.json 'sources').")
        head = (run(["git", "-C", str(src), "rev-parse", "HEAD"], capture=True).stdout or "").strip()
        if head != wanted:
            return fail(f"git rev-parse HEAD printed {head!r}, not the pinned {wanted}.", "The checkout was discarded.")
        tree = (run(["git", "-C", str(src), "rev-parse", "HEAD^{tree}"], capture=True).stdout or "").strip()
        print(f"[PlasBench] checked out {head} (git rev-parse HEAD matches the pin)")
        deps: dict[str, str] = {}
        for step in entry.get("env", {}).get("steps", []):
            if "path" in step:
                path = (ROOT / step["path"][1:]) if step["path"].startswith("@") else (src / step["path"])
                if not path.is_file():
                    return fail(f"{step['path']} is missing from revision {wanted[:12]}.", "The pin does not match what this installer expects; see config/source_tools.json.")
                deps[step["path"].lstrip("@")] = sha256_file(path)
        source_digest = tree_digest(src)
        # The environment goes straight to its final path (conda environments cannot be moved); it is removed again on any failure below.
        if layout.install.exists():
            os.replace(layout.install, backup)
            moved_backup = True
        steps = entry.get("env", {}).get("steps", [])
        conda_step = next((s for s in steps if s["type"] in ("conda_create", "conda_file")), None)
        if conda_step:
            if conda_step["type"] == "conda_create":
                command = [solver, "create", "-y", "-p", str(layout.install)] + [a for ch in conda_step.get("channels", []) for a in ("-c", ch)] + conda_step["packages"]
            else:
                file = src / conda_step["path"]
                command = [solver, "create", "-y", "-p", str(layout.install), "-f", str(file)] if Path(solver).name.startswith("micromamba") \
                    else [solver, "env", "create", "-p", str(layout.install), "-f", str(file)]
            print(f"[PlasBench] creating the isolated environment {layout.install}")
            created_install = True
            made = run(command)
            if made.returncode != 0:
                return fail(f"the conda step failed (exit {made.returncode}).", "The messages above say which package could not be solved; run the same command again once that is fixed.")
        else:
            layout.install.mkdir(parents=True)
            created_install = True
        os.replace(src, layout.src)
        for step in steps:
            if step["type"] == "pip_requirements":
                path = (ROOT / step["path"][1:]) if step["path"].startswith("@") else (layout.src / step["path"])
                label, command = "pip install -r " + step["path"].lstrip("@"), [str(layout.install / "bin" / "pip"), "install", "-r", str(path)]
            elif step["type"] == "pip_install":
                label, command = "pip install " + step["target"], [str(layout.install / "bin" / "pip"), "install"] + step.get("args", []) + [step["target"]]
            elif step["type"] == "clear_execstack":
                changed = [str(f) for f in sorted(layout.install.glob(step["glob"])) if f.is_file() and clear_execstack(f)]
                print(f"[PlasBench] cleared the executable-stack request of {len(changed)} library file(s) ({step['glob']}): recent glibc refuses to load them otherwise")
                continue
            else:
                continue
            print(f"[PlasBench] {label}")
            done = run(command, cwd=layout.src)
            if done.returncode != 0:
                return fail(f"`{label}` failed (exit {done.returncode}).", "The messages above say which package failed; run the same command again once that is fixed.")
        staging_wrappers.mkdir(parents=True)
        for cmd, spec in entry["commands"].items():
            write_lf(staging_wrappers / cmd, wrapper_text(cmd, spec, entry, layout, name))
            os.chmod(staging_wrappers / cmd, 0o755)
        ok, said = verify(entry, staging_wrappers, layout)
        if not ok:
            return fail(f"{name} was installed but its verification failed: {said}", "The installation was removed; the reason above is what upstream reported.")
        record = {
            "profile": name, "tools": entry["tools"], "repo": entry["repo"], "repo_used": url, "ref": entry["ref"], "commit": head, "tree": tree,
            "source_tree_sha256": source_digest, "licence": entry["licence"], "registry_researched": entry["researched"],
            "installed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "install_seconds": round(time.time() - started, 1),
            "env_prefix": str(layout.install), "main_prefix": str(layout.main), "solver": solver, "solver_version": _solver_version(solver),
            "dependency_files_sha256": deps, "dependency_versions": _dependency_versions(layout, solver),
            "commands": sorted(entry["commands"]), "verify": {"argv": entry["verify"]["argv"], "first_line": said},
        }
        tmp = layout.provenance.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, layout.provenance)
        _expose(entry, layout, name)
        if moved_backup:
            _rmtree(backup, ignore_errors=True)
            moved_backup = False
        created_install = False
        print(f"[PlasBench] {name} installed: revision {head[:12]} ({entry['ref']}), verified ({said}). Provenance: {layout.provenance}")
        for item in entry.get("inputs", []):
            print(f"[PlasBench]   still needed: {item}")
        return 0
    except KeyboardInterrupt:
        print("ERROR: interrupted; cleaning up.", file=sys.stderr)
        return 130
    except OSError as exc:
        return fail(f"{exc}", "Free some disk space or check permissions, then run the same command again.")
    finally:
        _rmtree(staging, ignore_errors=True)
        _rmtree(staging_wrappers, ignore_errors=True)
        if created_install:
            _rmtree(layout.install, ignore_errors=True)
        if moved_backup and backup.exists():
            os.replace(backup, layout.install)


# ---- what is installed, from the wrapper on PATH --------------------------------------------------------------------------------------------------------

def command_info(command: str) -> dict | None:
    """{profile, commit, ref, installed_at, ...} for a command whose wrapper on PATH was written by this installer; None for anything else."""
    found = shutil.which(command)
    if not found:
        for folder in os.environ.get("PATH", "").split(os.pathsep):      # a wrapper has no extension: Windows' which() does not find it
            if folder and (Path(folder) / command).is_file():
                found = str(Path(folder) / command)
                break
    if not found:
        return None
    try:
        with open(found, encoding="utf-8", errors="replace") as handle:
            head = handle.read(600)
    except OSError:
        return None
    match = re.search(re.escape(WRAPPER_MARK) + r"\s+(\S+)\s+([0-9a-f]{40})\s+(.+)", head)
    if not match:
        return None
    prov = read_provenance(Path(match.group(3).strip())) or {}
    return {"profile": match.group(1), "commit": match.group(2), "ref": prov.get("ref", ""), "installed_at": prov.get("installed_at", ""),
            "repo": prov.get("repo", ""), "env_prefix": prov.get("env_prefix", ""), "source_tree_sha256": prov.get("source_tree_sha256", ""),
            "dependency_files_sha256": prov.get("dependency_files_sha256", {}), "path": found}


def missing_inputs(name: str, entry: dict) -> list[str]:
    """What the installed runtime still lacks that PlasBench cannot install, so `check` can say 'runtime installed, input X missing'."""
    missing = []
    if name == "mobilome-map" and not any(shutil.which(c) for c in ("docker", "singularity", "apptainer")):
        missing.append("a container engine (Docker, Singularity or Apptainer)")
    if name == "plasbin_flow" and not (os.environ.get("GRB_LICENSE_FILE") or os.environ.get("GRB_WLSACCESSID") or (Path.home() / "gurobi.lic").is_file()):
        missing.append("a Gurobi licence (free for academics)")
    if name == "plasme":
        db = os.environ.get("PLASME_DB", "")
        if not db or not Path(db).is_dir() or not any(Path(db).iterdir()):
            missing.append("the PLASME database (plasbench check --yes installs it)")
    return missing


# ---- command line ---------------------------------------------------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("validate", "plan", "kind", "services", "install", "status", "command-info", "path", "missing-inputs", "profiles"))
    parser.add_argument("name", nargs="?")
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--main-prefix", type=Path, help="The main environment's prefix (its bin/ receives the wrappers; the isolated environment is its sibling).")
    parser.add_argument("--env-name", default="plasbench")
    parser.add_argument("--solver", default="conda")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    registry = load(args.registry)
    problems = validate(registry)
    if args.action == "validate":
        if problems:
            print("SOURCE TOOL REGISTRY INVALID:", file=sys.stderr)
            print("\n".join(f"  - {p}" for p in problems), file=sys.stderr)
            return 1
        count = {"source": 0, "manual": 0}
        for entry in registry["profiles"].values():
            count[entry["mode"]] += 1
        print(f"SOURCE TOOL REGISTRY VALID: {count['source']} installable source profile(s), {count['manual']} verified-manual profile(s)")
        return 0
    if args.action == "profiles":
        print("\n".join(f"{n}\t{e['mode']}" for n, e in registry["profiles"].items()))
        return 0
    if args.action == "command-info":
        info = command_info(args.name or "")
        if args.json or info:
            print(json.dumps(info))
        return 0 if info else 1
    if not args.name:
        print("ERROR: a profile name is needed", file=sys.stderr)
        return EXIT_USAGE
    entry = registry["profiles"].get(args.name)
    if entry is None:
        by_tool = {t: n for n, e in registry["profiles"].items() for t in e["tools"]}
        entry = registry["profiles"].get(by_tool.get(args.name, ""))
        if entry is None:
            print(f"ERROR: '{args.name}' is not a source-installed profile (config/source_tools.json)", file=sys.stderr)
            return EXIT_USAGE
        args.name = by_tool[args.name]
    if problems:
        print("ERROR: config/source_tools.json is invalid:\n" + "\n".join(f"  - {p}" for p in problems), file=sys.stderr)
        return EXIT_FAILED
    if args.action == "kind":
        print(entry["mode"])
    elif args.action == "plan":
        print(manual_text(args.name, entry) if entry["mode"] == "manual" else plan_text(args.name, entry))
    elif args.action == "services":
        print(" ".join(services(entry)))
    elif args.action == "missing-inputs":
        print("\n".join(missing_inputs(args.name, entry)))
    elif args.action == "path":
        if not args.main_prefix:
            return EXIT_USAGE
        layout = Layout(args.main_prefix, args.env_name, args.name)
        if layout.provenance.is_file():
            print(layout.src)
            return 0
        return 1
    elif args.action == "status":
        if not args.main_prefix:
            return EXIT_USAGE
        answer = status_of(args.name, entry, args.main_prefix, args.env_name)
        print(json.dumps(answer, indent=2) if args.json else f"{args.name}: {answer['state']}")
    elif args.action == "install":
        return install(args.name, entry, args.main_prefix, args.solver, args.env_name, args.yes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
