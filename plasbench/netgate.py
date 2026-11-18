"""The window's view of the internet: one place that asks the connectivity layer (plasbench/netcheck.py) and decides what needs it.

netcheck is built separately. This module codes against its contract and works without it:
    netcheck.check(services=None, timeout=3.0) -> {"online", "state": online|offline|dns_broken|limited|forced_offline|assumed_online, "checked", "services": {name: {ok, ms, error, kind}}, "advice": [str]}
    netcheck.require(service_or_list, action="") raises netcheck.NoInternet(service, state, advice, message)
When netcheck is not there, the answer is "assumed_online" (nothing is blocked), except PLASBENCH_OFFLINE=1, which is forced offline. `Offline` is what the window's routes raise:
the server answers 503 {"error": "offline", "service", "state", "advice", "message"} instead of starting a job that cannot work, and never hangs.

`services_for_job` says which services a command needs: a fully local run (--local-inputs, the metagenomics track, or reads already on disk) needs none. Offline must never block local
things: scoring, reports, studies, the folder tree, settings, documents. Standard library only.
"""
from __future__ import annotations

import os
import time

SERVICES = ("internet", "dns", "github", "ncbi", "sra", "ena", "pypi", "conda", "zenodo", "plsdb")
BAD_STATES = ("offline", "dns_broken", "forced_offline")

# Commands that start network work, and the services each needs (checked before the job starts). `None` means a sub-command table (see SUBCOMMAND_NET).
NET_COMMANDS = {
    "install-tools": ["conda"], "install-conda": ["conda"], "upgrade": ["github"],
    "discover-cohort": ["ncbi"], "discover-design-cohort": ["ncbi"], "validate-cohort": ["ncbi"], "resolve-contributed-cohort": ["ncbi"],
    "build-publication-cohorts": ["ncbi"], "collect-truth-provenance": ["ncbi"], "reconstruct": ["ncbi", "sra"],
    "update-check": ["github"], "tools": None,
}
SUBCOMMAND_NET = {"tools": {"add": ["conda"], "install": ["conda"], "new": []}}
GIT_NET_OPS = {"fetch", "pull", "push", "clone", "gh_login", "gh_setup_git", "gh_create"}


class Offline(Exception):
    """An internet-dependent action was refused because the service is unreachable. Carries what the 503 answer and the page's dialog show."""

    def __init__(self, service, state, advice=(), message=""):
        self.service, self.state, self.advice = service, state, list(advice or [])
        self.message = message or f"Needs the internet: {service} is unreachable ({state})."
        super().__init__(self.message)

    def payload(self) -> dict:
        return {"error": "offline", "service": self.service, "state": self.state, "advice": self.advice, "message": self.message}


def _netcheck():
    try:
        from . import netcheck
        return netcheck
    except Exception:  # noqa: BLE001 - the connectivity layer may not be merged yet
        return None


_backend_override = None


def set_backend(module) -> None:
    """Tests (and nothing else) replace the connectivity layer."""
    global _backend_override
    _backend_override = module


def backend():
    return _backend_override if _backend_override is not None else _netcheck()


def forced_offline() -> bool:
    return os.environ.get("PLASBENCH_OFFLINE", "") not in ("", "0", "false", "False")


def _fallback(services=None) -> dict:
    if forced_offline():
        return {"online": False, "state": "forced_offline", "checked": time.time(), "services": {}, "advice": ["PLASBENCH_OFFLINE=1 is set: unset it to use the internet."]}
    return {"online": True, "state": "assumed_online", "checked": time.time(), "services": {}, "advice": []}


def status(services=None, timeout: float = 3.0) -> dict:
    """netcheck.check(...) in the contract's shape; never raises."""
    mod = backend()
    try:
        out = mod.check(services, timeout) if mod is not None and hasattr(mod, "check") else _fallback(services)
    except Exception:  # noqa: BLE001
        out = _fallback(services)
    if not isinstance(out, dict):
        out = _fallback(services)
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
    mod = backend()
    if mod is not None and hasattr(mod, "require"):
        try:
            mod.require(names if len(names) > 1 else names[0], action)
            return
        except Exception as exc:  # noqa: BLE001
            if exc.__class__.__name__ == "NoInternet" or hasattr(exc, "service"):
                raise Offline(getattr(exc, "service", names[0]), getattr(exc, "state", "offline"), getattr(exc, "advice", []), getattr(exc, "message", "") or str(exc))
            return                      # a failing check must not block local work
    if forced_offline():
        raise Offline(names[0], "forced_offline", ["PLASBENCH_OFFLINE=1 is set: unset it to use the internet."], f"Needs the internet: {names[0]} is not used because PLASBENCH_OFFLINE=1 is set.")


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


def command_services(argv) -> list:
    """The services a `plasbench ...` command line needs, from NET_COMMANDS (empty for local commands)."""
    if not argv:
        return []
    table = NET_COMMANDS.get(argv[0], [])
    if table is None:
        sub = argv[1] if len(argv) > 1 else ""
        return list(SUBCOMMAND_NET.get(argv[0], {}).get(sub, []))
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
