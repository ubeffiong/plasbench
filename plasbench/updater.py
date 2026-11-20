"""The window's Updates card, server side: what an install would do, whether it may start now, and what its log means.

There is ONE upgrade implementation: `plasbench upgrade` (cli.py, which runs update.sh). The window only builds that command line, starts it as an ordinary job
(so it has a live log, can be found again in Jobs and survives a closed window) and reads the job's log to show phases and, when it fails, a plain reason.

    plan(...)            the command line, the label and the facts for the consent dialog; refuses (Refused) what must not start: another update is running,
                         a run or job is active (unless force), the release is not newer (no silent downgrade), the file is not a PlasBench release file
    inspect_archive(...) what is known about a release file without opening it (name, version, size, a .sha256 beside it)
    steps(log, state)    the six phases update.sh announces (check, download, verify, install, environment, done) and which is current
    classify(...)        the result: ok, or a reason (offline, checksum, disk, permission, conda, name, extract, notfound, lock) with the next step
    rollback_info(root)  the release kept by the last update (.plasbench-rollback/plasbench-<version>.tar.gz), if any

Standard library only; no network access and no process is started here.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from . import updatecheck

ARCHIVE_RE = re.compile(r"^plasbench-([0-9][0-9A-Za-z.+-]*)\.tar\.gz$")
VERSION_RE = re.compile(r"^[0-9][0-9A-Za-z.+-]*$")
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024      # the same limit update.sh applies (PLASBENCH_UPDATE_MAX_MB)
PHASES = [("check", "Check the release"), ("download", "Download"), ("verify", "Verify checksum and contents"), ("install", "Replace the program files"),
          ("environment", "Update the environment"), ("done", "Finished")]
ACTIVE = ("running", "cancelling")


class Refused(ValueError):
    """An install that must not start. `code` is a short machine word the page switches on; `details` carries what the dialog lists."""

    def __init__(self, message: str, code: str, details: dict | None = None):
        super().__init__(message)
        self.code, self.details = code, details or {}

    def payload(self) -> dict:
        return {"error": str(self), "code": self.code, "details": self.details}


def archive_version(name: str) -> str:
    match = ARCHIVE_RE.match(str(name or ""))
    return match.group(1) if match else ""


def is_upgrade_job(job: dict) -> bool:
    argv = job.get("argv") or []
    return bool(argv) and argv[0] == "upgrade" and "--check-only" not in argv


def active_work(jobs: list, outside: list | None = None) -> list:
    """What is going on now that an update would disturb: running jobs (any kind) and runs started in a terminal."""
    out = []
    for job in jobs or []:
        if job.get("state") in ACTIVE and not is_upgrade_job(job) and (job.get("argv") or [""])[0] != "upgrade":   # an update check changes nothing
            out.append({"id": job.get("id", ""), "label": job.get("label") or job.get("command") or " ".join(job.get("argv") or [])[:80], "kind": "job"})
    for run in outside or []:
        if run.get("state") == "running":
            out.append({"id": "", "label": f"a run started in a terminal ({run.get('study') or run.get('results') or 'unknown study'})", "kind": "outside"})
    return out


def running_upgrade(jobs: list) -> dict | None:
    for job in jobs or []:
        if is_upgrade_job(job) and job.get("state") in ACTIVE:
            return job
    return None


def rollback_info(root) -> dict:
    """{version, path, size} of the release the last update kept, or {}."""
    folder = Path(root) / ".plasbench-rollback"
    try:
        found = sorted(p for p in folder.iterdir() if p.is_file() and ARCHIVE_RE.match(p.name))
    except OSError:
        return {}
    for path in found:
        try:
            return {"version": archive_version(path.name), "path": str(path), "size": path.stat().st_size}
        except OSError:
            continue
    return {}


def inspect_archive(path: str) -> dict:
    """What can be said about a release file by looking at its name and size only (update.sh opens and verifies it later)."""
    out = {"ok": False, "path": str(path), "name": "", "version": "", "size": None, "has_sha256": False, "error": ""}
    if not str(path or "").strip():
        out["error"] = "Choose the release file you downloaded (plasbench-<version>.tar.gz)."
        return out
    p = Path(str(path).strip().strip('"'))
    out["path"], out["name"] = str(p), p.name
    out["version"] = archive_version(p.name)
    if not out["version"]:
        out["error"] = (f"The file must be named plasbench-<version>.tar.gz exactly as downloaded (for example plasbench-0.5.6.tar.gz); this one is {p.name or 'not a file'}. "
                        "A browser may have renamed it, for example to plasbench-0.5.6(1).tar.gz: rename it back.")
        return out
    try:
        if not p.is_file():
            out["error"] = f"No file at {p}. Check the path, or choose the file with Browse."
            return out
        out["size"] = p.stat().st_size
    except OSError as exc:
        out["error"] = f"Cannot read {p}: {exc}"
        return out
    if out["size"] > MAX_ARCHIVE_BYTES:
        out["error"] = f"This file is {out['size'] // 1048576} MB, far larger than a PlasBench release; it is not one."
        return out
    if out["size"] == 0:
        out["error"] = "This file is empty (an interrupted download). Download it again."
        return out
    out["has_sha256"] = Path(str(p) + ".sha256").is_file()
    out["ok"] = True
    return out


def _label(kind: str, current: str, target: str, relation: str) -> str:
    if kind == "rollback":
        return f"Roll back PlasBench to {target}"
    if relation == "older":
        return f"Downgrade PlasBench to {target}"
    if relation == "same":
        return f"Reinstall PlasBench {target}"
    return f"Update PlasBench to {target}"


def plan(body: dict, current: str, check: dict, jobs: list, outside: list | None, resolve_path=None, root=None) -> dict:
    """The job for an install request, or Refused.

    body: {kind: latest|version|archive|rollback (default: archive when `archive` is given, version when `version` is, else latest), version, archive, force, downgrade}."""
    body = body or {}
    kind = str(body.get("kind") or ("archive" if body.get("archive") else "version" if body.get("version") else "latest"))
    if kind not in ("latest", "version", "archive", "rollback"):
        raise Refused(f"unknown kind of update: {kind}", "bad_request")
    other = running_upgrade(jobs)
    if other:
        raise Refused("An update is already running (see its log in this card). Only one can run at a time.", "upgrade_running", {"job": other.get("id", "")})
    argv = ["upgrade", "--yes"]
    target, rel, facts = "", "", {}
    if kind == "latest":
        if not check.get("checked"):
            raise Refused("PlasBench has not looked for the latest release yet. Press Check for updates first, so you see what you are installing.", "needs_check")
        target, rel = str(check.get("latest") or ""), check.get("relation", "")
        if body.get("version") and str(body["version"]) != target:
            raise Refused(f"The latest release is now {target}, not {body['version']}. Look at the new version and confirm again.", "changed", {"latest": target})
        if rel == "same":
            raise Refused(f"PlasBench {current} is already the latest release.", "same")
        if rel != "newer":
            raise Refused(f"The installed version ({current}) is newer than the latest release ({target}); PlasBench never offers a downgrade here. "
                          "To go back deliberately, use Install from a file with an older release file.", "older")
        argv += ["--version", target]
        facts = {"asset": check.get("asset") or {}, "published": check.get("published", ""), "url": check.get("url", "")}
    elif kind == "version":
        target = str(body.get("version") or "").lstrip("v")
        if not VERSION_RE.match(target):
            raise Refused(f"{target!r} is not a release number (expected something like 0.5.6).", "bad_request")
        rel = updatecheck.relation(current, target)
        if rel == "same":
            raise Refused(f"PlasBench {current} is already installed.", "same")
        if rel == "older" and not body.get("downgrade"):
            raise Refused(f"{target} is older than the installed {current}. Installing it is a downgrade; confirm that you want one.", "downgrade", {"from": current, "to": target})
        argv += ["--version", target]
    elif kind == "archive":
        path = str(body.get("archive") or "")
        if resolve_path:
            path = resolve_path(path)
        info = inspect_archive(path)
        if not info["ok"]:
            raise Refused(info["error"], "bad_archive")
        target = info["version"]
        rel = updatecheck.relation(current, target)
        if rel == "older" and not body.get("downgrade"):
            raise Refused(f"{info['name']} is older than the installed {current}. Installing it is a downgrade; confirm that you want one.", "downgrade", {"from": current, "to": target})
        argv += ["--archive", info["path"]]
        facts = {"archive": info["path"], "size": info["size"], "has_sha256": info["has_sha256"]}
    else:
        saved = rollback_info(root) if root else {}
        if not saved:
            raise Refused("There is no saved previous release to go back to (the next update saves one). You can still install an older release file with Install from a file.", "no_rollback")
        target, rel = saved["version"], updatecheck.relation(current, saved["version"])
        argv += ["--rollback"]
        facts = {"archive": saved["path"], "size": saved["size"]}
    active = active_work(jobs, outside)
    if active and not body.get("force"):
        raise Refused("A run or job is going now. An update replaces PlasBench's program files while it works, so it is not started until that is finished.", "busy", {"active": active})
    return {"argv": argv, "label": _label(kind, current, target, rel), "kind": kind, "from": current, "to": target, "relation": rel, "facts": facts, "forced": bool(active)}


# ---- reading the job's log ---------------------------------------------------------------------------------------------------------
_PHASE_RE = re.compile(r"^\[plasbench-update\] PHASE (\d)/6\b", re.M)
_ERROR_RE = re.compile(r"ERROR\[(\w+)\]:\s*(.*)")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def clean(log: str) -> str:
    return _ANSI.sub("", str(log or "")).replace("\r\n", "\n").replace("\r", "\n")


def current_phase(log: str) -> int:
    seen = [int(n) for n in _PHASE_RE.findall(clean(log))]
    return max(seen) if seen else 0


def steps(log: str, state: str) -> list:
    """[{id, label, state}] for the six phases. state is the job state: running, done, failed, cancelled, interrupted..."""
    phase = current_phase(log)
    out = []
    for i, (ident, label) in enumerate(PHASES, 1):
        if state == "done":
            st = "done"
        elif i < phase:
            st = "done"
        elif i == phase:
            st = "current" if state in ACTIVE else "failed"
        else:
            st = "pending"
        out.append({"id": ident, "label": label, "state": st})
    return out


REASONS = {
    "offline": ("PlasBench could not reach GitHub", "Check the internet connection, VPN or proxy and try again, or download the release file on a computer with internet and use Install from a file (no internet needed)."),
    "checksum": ("The downloaded file did not match its checksum", "The file is damaged or was changed. Download it again (or download it again on another computer and use Install from a file)."),
    "disk": ("There is not enough free disk space", "Free some space on the disk that holds your home folder and PlasBench, then try again."),
    "permission": ("PlasBench could not write to its program folder", "Check that the PlasBench folder belongs to you and is not read-only (or locked by a program), then try again."),
    "conda": ("The conda environment could not be updated", "Install Miniforge/conda first (Set up this computer > Maintenance > Install conda), then try the update again."),
    "name": ("This is not the release file it should be", "Use the file exactly as downloaded: plasbench-<version>.tar.gz from the release page."),
    "extract": ("The file is not a valid PlasBench release", "Download plasbench-<version>.tar.gz again from the release page."),
    "notfound": ("A file that is needed was not found", "Check the path of the release file, or press Check for updates and install the latest release."),
    "verify": ("The new files are in place but the installed program does not match them", "In a terminal run plasbench ui-state: it prints the exact repair command for this computer (or press Roll back)."),
    "lock": ("Another update is already running in this folder", "Wait for it to finish (it may be running in a terminal or another window), then try again."),
}
_FALLBACK_PATTERNS = [
    ("verify", re.compile(r"still not matching|does not match the folder", re.I)),
    ("checksum", re.compile(r"FAILED|did NOT match|checksum .* does not match", re.I)),
    ("disk", re.compile(r"No space left on device|not enough free disk", re.I)),
    ("permission", re.compile(r"Permission denied|Read-only file system|Operation not permitted", re.I)),
    ("conda", re.compile(r"no conda-family package manager|conda: command not found|conda is required", re.I)),
    ("offline", re.compile(r"Could not resolve host|could not reach GitHub|needs the internet|Connection (timed out|refused)|exit status 6", re.I)),
]


def classify(log: str, state: str, exit_code=None) -> dict:
    """The outcome of an update job: {ok, reason, title, detail, next, changed, restart} (changed: 'nothing' | 'files' | 'unknown')."""
    text = clean(log)
    phase = current_phase(text)
    if state == "done":
        return {"ok": True, "reason": "", "title": "Update finished", "detail": "", "next": "Restart the window to use the new version.", "changed": "files", "restart": True}
    if state in ACTIVE or not state:
        return {"ok": None, "reason": "", "title": "Update running", "detail": "", "next": "", "changed": "unknown", "restart": False}
    reason, detail = "", ""
    match = None
    for match in _ERROR_RE.finditer(text):
        pass                                                        # the last tagged error is the one that stopped it
    if match:
        reason, detail = match.group(1), match.group(2).strip()
    if not reason:
        for name, pattern in _FALLBACK_PATTERNS:
            if pattern.search(text):
                reason = name
                break
    if not reason and exit_code == 3:
        reason = "offline"
    if state in ("cancelled", "interrupted"):
        title, nxt = ("Update cancelled" if state == "cancelled" else "Update interrupted"), "Press Update again. If the program no longer starts, use Roll back."
        reason = reason or state
    else:
        title, nxt = REASONS.get(reason, ("The update did not finish", "Read the log below; it names the step that failed. Nothing about your studies, settings or databases is touched by an update."))
        if reason in REASONS:
            nxt = REASONS[reason][1]
    if phase >= 5 and reason != "lock":
        changed = "files"
        nxt += " The new program files are already in place; to use the old release instead press Roll back."
    elif phase == 4:
        changed = "unknown"
        nxt += " The program files may be partly replaced: repeat the update, or press Roll back."
    elif phase:
        changed = "nothing"
        nxt += " Nothing was changed."
    else:
        changed = "nothing"
    return {"ok": False, "reason": reason or "unknown", "title": title, "detail": detail, "next": nxt, "changed": changed, "restart": False}


def tail_lines(log: str, count: int = 40) -> list:
    lines = [ln for ln in clean(log).split("\n") if ln.strip()]
    return lines[-count:]


def job_summary(job: dict, log: str) -> dict:
    """What the card shows about an update job."""
    state = job.get("state", "")
    return {"id": job.get("id", ""), "state": state, "display_state": job.get("display_state", state), "started": job.get("started"), "ended": job.get("ended"),
            "exit": job.get("exit"), "label": job.get("label", ""), "argv": job.get("argv") or [], "steps": steps(log, state),
            "result": classify(log, state, job.get("exit")), "lines": tail_lines(log)}


def newest_upgrade_job(jobs: list) -> dict | None:
    mine = [j for j in jobs or [] if is_upgrade_job(j)]
    return max(mine, key=lambda j: j.get("started") or 0) if mine else None


def default_mode(local_env: dict, environ=None) -> str:
    """UPDATE_CHECK from config/local.env, then the environment: auto (default) or off."""
    environ = os.environ if environ is None else environ
    value = str((local_env or {}).get("UPDATE_CHECK") or environ.get("UPDATE_CHECK") or "auto").strip().lower()
    return value if value in ("auto", "off") else "auto"
