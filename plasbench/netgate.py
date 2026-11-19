"""The window's view of the internet: one place that asks the connectivity layer (plasbench/netcheck.py) and decides what needs it.

This module is the window's adapter over plasbench/netcheck.py, the one connectivity layer (also behind `plasbench net` and the command pre-flights):
    netcheck.check(services=None, timeout=None -> netcheck.DEFAULT_TIMEOUT, 5 s) -> {"online", "state": online|offline|dns_broken|limited|forced_offline|assumed_online, "checked", "services": {name: {ok, ms, error, kind}}, "advice": [str]}
    netcheck.require(service_or_list, action="") raises netcheck.NoInternet(service, state, advice, message)
State names and service names are netcheck's (the services are the rows of config/network_services.tsv); PLASBENCH_OFFLINE=1 is forced offline and PLASBENCH_ASSUME_ONLINE=1 skips the probes, both decided
by netcheck. A check that itself breaks answers "assumed_online" so that it never blocks local work. `Offline` is what the window's routes raise:
the server answers 503 {"error": "offline", "service", "state", "advice", "message"} instead of starting a job that cannot work, and never hangs.

`services_for_job` says which services a command needs: a fully local run (--local-inputs, the metagenomics track, or reads already on disk) needs none. Offline must never block local
things: scoring, reports, studies, the folder tree, settings, documents. Standard library only.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

from . import netcheck

SERVICES = tuple(netcheck.SERVICES)         # the rows of config/network_services.tsv
BAD_STATES = ("offline", "dns_broken", "forced_offline")

# Commands that start network work, and the services each needs (checked before the job starts): the `plasbench ...` rows of the catalogue's used_by column, the same table
# the command line's own pre-flight uses (netcheck.command_table), plus the few window-only commands below. `None` means a sub-command table (see SUBCOMMAND_NET); a row that
# applies only with a flag (validate-cohort --online) is in FLAG_NET and is checked when that flag is in the command line.
_EXTRA_COMMANDS = {"install-conda": ["conda"], "reconstruct": ["ncbi", "sra"], "update-check": ["github"]}


def _tables():
    commands, subs, flagged = {k: list(v) for k, v in _EXTRA_COMMANDS.items()}, {}, {}
    for (command, sub), entry in sorted(netcheck.command_table().items()):
        services = sorted(entry["services"])
        if entry["flag"]:
            flagged[(command, sub)] = (entry["flag"], services)
        elif sub:
            commands[command] = None
            subs.setdefault(command, {})[sub] = services
        else:
            commands[command] = services
    return commands, subs, flagged


NET_COMMANDS, SUBCOMMAND_NET, FLAG_NET = _tables()
GIT_NET_OPS = {"fetch", "pull", "push", "clone", "gh_login", "gh_setup_git", "gh_create"}


class Offline(Exception):
    """An internet-dependent action was refused because the service is unreachable. Carries what the 503 answer and the page's dialog show."""

    def __init__(self, service, state, advice=(), message=""):
        self.service, self.state, self.advice = service, state, list(advice or [])
        self.message = message or f"Needs the internet: {service} is unreachable ({state})."
        super().__init__(self.message)

    def payload(self) -> dict:
        return {"error": "offline", "service": self.service, "state": self.state, "advice": self.advice, "message": self.message}


_backend_override = None


def set_backend(module) -> None:
    """Tests (and nothing else) replace the connectivity layer."""
    global _backend_override
    _backend_override = module
    from . import loadcache
    loadcache.clear()               # the window remembers the last answer for a few seconds: a different backend must not be answered from it


def backend():
    return _backend_override if _backend_override is not None else netcheck


def forced_offline() -> bool:
    return netcheck.forced_offline()


def _unknown() -> dict:
    """What a check that itself broke answers: nothing is known to be down, so local work is never blocked."""
    return {"online": True, "state": "assumed_online", "checked": time.time(), "services": {}, "advice": []}


def status(services=None, timeout=None) -> dict:
    """netcheck.check(...) in the contract's shape; never raises."""
    try:
        out = backend().check(services, timeout)
    except Exception:  # noqa: BLE001
        out = _unknown()
    if not isinstance(out, dict):
        out = _unknown()
    out.setdefault("online", out.get("state") not in BAD_STATES)
    out.setdefault("state", "assumed_online")
    out.setdefault("services", {})
    out.setdefault("advice", [])
    out.setdefault("checked", time.time())
    return out


def require(services, action: str = "") -> None:
    """Raise Offline when a needed service is unreachable; return quietly when it is reachable or unknown."""
    names = [services] if isinstance(services, str) else list(services or [])
    if not names:
        return
    try:
        backend().require(names if len(names) > 1 else names[0], action)
    except Exception as exc:  # noqa: BLE001
        if exc.__class__.__name__ == "NoInternet" or hasattr(exc, "service"):
            raise Offline(getattr(exc, "service", names[0]), getattr(exc, "state", "offline"), getattr(exc, "advice", []), getattr(exc, "message", "") or str(exc))
        # any other failure: a failing check must not block local work


def require_any(services, action: str = "") -> None:
    """Refuse only when EVERY listed service is unreachable (reads can come from the SRA Toolkit or from ENA)."""
    last = None
    for name in services:
        try:
            require(name, action)
            return
        except Offline as exc:
            last = exc
    if last is not None:
        raise last


def git_services(remote_url: str = "") -> list:
    host = (remote_url or "").split("//", 1)[-1].split("/", 1)[0].split("@")[-1].split(":")[0].lower()
    return ["github"] if (not host or host.endswith("github.com")) else ["internet"]


def _source_install_services(rest) -> list:
    """The services a source-built profile (config/source_tools.json) needs, joined over a comma list; empty when no named profile is one (then the catalogue's services apply)."""
    words = [w for i, w in enumerate(rest) if not w.startswith("-") and (i == 0 or rest[i - 1] != "--env")]
    if not words:
        return []
    try:
        import source_install
        root = Path(__file__).resolve().parent.parent
        profiles = source_install.load(root / "config" / "source_tools.json")["profiles"]
    except Exception:  # noqa: BLE001
        return []
    found, others = [], False
    for name in words[0].split(","):
        entry = profiles.get(name)
        if entry is not None and entry["mode"] == "source":
            for svc in source_install.services(entry):
                if svc not in found:
                    found.append(svc)
        elif name:
            others = True
    if others:                          # a mix: the catalogue's services plus the git hosts
        for svc in ("conda", "github", "pypi"):
            if svc not in found:
                found.append(svc)
    return found


def _install_goes_online(rest) -> bool:
    """python/tool_installer_registry.needs_network for `install-tools [--env E] [--yes] [PROFILE] [--dry-run]`; an unreadable registry says yes."""
    if "--dry-run" in rest:
        return False
    words = []
    skip = False
    for w in rest:
        if skip:
            skip = False
        elif w == "--env":
            skip = True
        elif not w.startswith("-"):
            words.append(w)
    try:
        import tool_installer_registry as registry
        root = Path(__file__).resolve().parent.parent
        return registry.needs_network(words[0] if words else "core", registry.read_tsv(root / "config" / "tool_installers.tsv") + registry.read_tsv(root / "config" / "metagenomic_tool_installers.tsv"))
    except Exception:  # noqa: BLE001
        return True


def offline_install_profiles() -> list:
    """The `install-tools` profiles that fetch nothing (inspection actions, built-in and manual profiles): the window does not grey those buttons out offline."""
    try:
        import tool_installer_registry as registry
        root = Path(__file__).resolve().parent.parent
        rows = registry.read_tsv(root / "config" / "tool_installers.tsv") + registry.read_tsv(root / "config" / "metagenomic_tool_installers.tsv")
        names = set(registry.profile_kinds(rows)) | set(registry.ACTIONS)
        return sorted(n for n in names if not registry.needs_network(n, rows))
    except Exception:  # noqa: BLE001
        return []


def command_services(argv) -> list:
    """The services a `plasbench ...` command line needs (empty for local commands). `tools add` needs the internet only for a URL; `--online` commands only with that flag."""
    if not argv:
        return []
    command, rest = argv[0], list(argv[1:])
    if command == "install-tools" and not _install_goes_online(rest):
        return []                       # inspection, --dry-run, a built-in or manual profile (exit 20), an unknown name: nothing is fetched
    sub = rest[0] if rest and (command, rest[0]) in {(c, s_) for c, d in SUBCOMMAND_NET.items() for s_ in d} | set(FLAG_NET) else ""
    if (command, sub) in FLAG_NET:
        flag, services = FLAG_NET[(command, sub)]
        return list(services) if flag in rest else []
    if command == "install-tools":
        wanted = _source_install_services(rest)
        if wanted:
            return wanted               # a source-built tool also needs its git host (GitLab for gplas2 and PlasmidEC)
    table = NET_COMMANDS.get(command, [])
    if table is None:
        if command == "tools" and sub == "add" and not re.match(r"^(https?|git|ssh):/|^git@", (rest[1] if len(rest) > 1 else "").replace("\\", "/")):
            return []                   # a folder or manifest on disk
        return list(SUBCOMMAND_NET.get(command, {}).get(sub, []))
    return list(table)


def _flag(argv, *names):
    for i, a in enumerate(argv):
        if a in names and i + 1 < len(argv):
            return argv[i + 1]
        for n in names:
            if a.startswith(n + "="):
                return a.split("=", 1)[1]
    return None


def run_needs_download(argv, env=None, root=None, data_dir=None, reads_present=None) -> bool:
    """Will `plasbench run ...` fetch anything? No for --local-inputs, LOCAL_INPUTS_ONLY=1, the metagenomics track and a report-only run; no when every sample's reads and
    assembly are already in the data folder (`reads_present(sample_id) -> bool`, supplied by the caller, which knows the sheet and the folder); otherwise yes."""
    env = env or {}
    if "--local-inputs" in argv or env.get("LOCAL_INPUTS_ONLY") == "1" or os.environ.get("LOCAL_INPUTS_ONLY") == "1":
        return False
    mode = _flag(argv, "-m", "--mode")
    if mode in ("metagenomics", "meta", "beta"):
        return False
    stages = [a for a in argv[1:] if a.isdigit() and len(a) == 1]
    if stages and "1" not in stages:
        return False
    if reads_present is not None:
        try:
            return not reads_present()
        except Exception:  # noqa: BLE001 - when in doubt the run is allowed to start and the 503 comes from the server's own check
            return True
    return True


def services_for_job(argv, env=None, reads_present=None) -> dict:
    """{"all": [...], "any": [...]} that must be reachable before this job starts. A run that downloads needs NCBI and a read source (SRA or ENA, per READ_SOURCE)."""
    env = env or {}
    if not argv:
        return {"all": [], "any": []}
    if argv[0] == "run":
        if not run_needs_download(argv, env, reads_present=reads_present):
            return {"all": [], "any": []}
        source = (env.get("READ_SOURCE") or os.environ.get("READ_SOURCE") or "auto").lower()
        return {"all": ["ncbi"], "any": ["sra", "ena"] if source == "auto" else [source if source in ("sra", "ena") else "sra"]}
    return {"all": command_services(argv), "any": []}


def require_job(argv, env=None, action: str = "", reads_present=None) -> None:
    need = services_for_job(argv, env, reads_present)
    require(need["all"], action)
    if need["any"]:
        require_any(need["any"], action)
