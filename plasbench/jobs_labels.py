"""Which window jobs are installations, and what to call them (the installing toast in the window reads these fields from /api/jobs).

One place decides it, from the job's argv alone (the same list the window started it with), so a job started from the Tools page, the Environment card, a run's pre-flight
or the terminal is labelled the same way:

  install-tools <profile[,profile]> ...   tools and profiles (docker is the container engine); plan / list / validate / locked and --dry-run only inspect
  tools install <name>                    a tool you added
  install-conda                           Miniforge
  runtime pull | build                    the PlasBench image
  check --yes                             "Make everything ready" and the database downloads (without --yes it only checks)
  upgrade                                 PlasBench itself

`describe` returns {is_install, label, install_tools, install_kind}; the fields are additive in the jobs payload. `last_line` and `installed_version` read a job's log tail.
"""
from __future__ import annotations

import re

INSPECT_PROFILES = frozenset({"plan", "list", "validate", "locked"})            # `install-tools <word>` that changes nothing
GROUP_PROFILES = {"core": "the core tools", "all": "all tools", "assembly": "the assembly tools", "metagenomics": "the metagenomics tools",
                  "reconstruction": "the reconstruction tools", "simulate": "the simulation tools", "long-read": "the long-read tools", "annotation": "the annotation tools",
                  "baseline": "the baseline tools"}
DISPLAY = {"docker": "Docker", "conda": "conda", "plasbench": "PlasBench"}
JOB_KINDS_INSTALL = ("install-tools", "tools-install", "install-conda", "runtime-pull", "runtime-build", "check-yes", "upgrade")   # the install_kind values below
NOT_INSTALL = {"is_install": False, "label": "", "install_tools": [], "install_kind": ""}


def _positional(args: list, value_options=("--env", "--prefix")) -> list:
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a in value_options:
            skip = True
        elif not a.startswith("-"):
            out.append(a)
    return out


def _result(kind: str, label: str, tools: list) -> dict:
    return {"is_install": True, "label": label, "install_tools": tools, "install_kind": kind}


def _tools_label(names: list) -> str:
    shown = [GROUP_PROFILES.get(n) or DISPLAY.get(n, n) for n in names]
    if len(names) == 1:
        return f"Installing {shown[0]}…"
    return f"Installing {len(names)} tools…"


def describe(argv, kind: str = "plasbench") -> dict:
    """{is_install, label, install_tools, install_kind} for a job's argv. A git job or an empty argv is never an install."""
    argv = [str(a) for a in (argv or [])]
    if kind != "plasbench" or not argv:
        return dict(NOT_INSTALL)
    cmd, rest = argv[0], argv[1:]
    if cmd == "install-tools":
        if "--dry-run" in rest:
            return dict(NOT_INSTALL)
        pos = _positional(rest)
        profile = pos[0] if pos else "core"
        if profile in INSPECT_PROFILES:
            return dict(NOT_INSTALL)
        names = [p for p in profile.split(",") if p] or ["core"]
        return _result("install-tools", _tools_label(names), names)
    if cmd == "tools" and rest[:1] == ["install"]:
        pos = _positional(rest[1:])
        names = pos[:1] or ["your tool"]
        return _result("tools-install", _tools_label(names), names)
    if cmd == "install-conda":
        return _result("install-conda", "Installing conda…", ["conda"])
    if cmd == "runtime":
        pos = _positional(rest)
        if pos[:1] == ["pull"]:
            return _result("runtime-pull", "Pulling the PlasBench image…", ["image"])
        if pos[:1] == ["build"]:
            return _result("runtime-build", "Building the PlasBench image…", ["image"])
        return dict(NOT_INSTALL)
    if cmd == "check" and "--yes" in rest:
        return _result("check-yes", "Installing missing tools and databases…", [])
    if cmd == "upgrade":
        return _result("upgrade", "Updating PlasBench…", ["plasbench"])
    return dict(NOT_INSTALL)


_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_BAD = re.compile(r"\b(error|failed|fatal|denied|cannot|could not|not found|unable|refused|timed out)\b", re.I)
_VERSION = re.compile(r"\b(?:version|installed|now at)\b[^\n\d]{0,24}v?(\d+\.\d+(?:\.\d+)*)", re.I)
LINE_MAX = 160
RUNNER_PREFIXES = ("[PlasBench]", "[exit")


def _lines(tail: str) -> list:
    out = []
    for raw in _ANSI.sub("", tail).replace("\r", "\n").split("\n"):
        line = raw.strip()
        if line and not line.startswith("$ "):
            out.append(line)
    return out


def last_line(tail: str, failed: bool = False) -> str:
    """One line of a job's log tail for the toast: the last line printed; for a failure the last line that reads like a reason (else the last line). Truncated."""
    lines = _lines(tail)
    if not lines:
        return ""
    lines = [ln for ln in lines if not ln.startswith(RUNNER_PREFIXES)] or lines   # the tool's own words, not the runner's "[PlasBench] ... (exit 1)" wrapper, unless that is all there is
    pick = lines[-1]
    if failed:
        pick = next((ln for ln in reversed(lines) if _BAD.search(ln)), pick)
    return pick if len(pick) <= LINE_MAX else pick[:LINE_MAX - 1] + "…"


def installed_version(tail: str) -> str:
    """The version a finished install reported ("Docker version 27.0.1", "installed ... 1.4.2"), or "" when the log does not say."""
    for line in reversed(_lines(tail)):
        m = _VERSION.search(line)
        if m:
            return m.group(1)
    return ""
