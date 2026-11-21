"""Is the Docker engine fit to pull, build or run? The pre-flight before any `docker pull`, `docker build` or `docker run` of PlasBench, and `plasbench runtime doctor`.

A multi-hour image build on an engine that cannot write is the worst way to find out the engine is broken, so these checks are fast (about 15 seconds in all, each with its own
timeout), read or touch nothing of yours and use no network:

  1. the `docker` command exists;
  2. the engine answers `docker version`;
  3. `docker info` is read: root directory, storage driver, operating system, proxies, memory;
  4. free disk space of Docker's root directory (only where it can be measured from here: a local Linux engine; Docker Desktop's disk is inside its virtual machine), warn below 10 GB,
     block below 2 GB for a pull or build (a build needs several GB: estimated from the Dockerfile);
  5. a WRITE test that never touches the network: `docker volume create pb-health-<random>` then `docker volume rm` (a read-only or damaged metadata database fails here, in a second);
  6. only for `runtime doctor` and only when the image is already local: `docker run --rm --pull=never <image> true`. Nothing is ever pulled for a health check.

Every failure is classified by python/docker_diagnosis.py (cause, evidence, safe steps, copyable commands). Nothing here fixes anything and nothing here deletes anything: the commands are
shown for the person to run. Every system fact (the docker runner, statvfs, the clock) can be injected, so tests use a fake `docker`. Standard library only; Python 3.9 compatible.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from pathlib import Path, PurePosixPath

from . import docker_runtime as dr

WARN_FREE_GB = 10.0
BLOCK_FREE_GB = 2.0
BUDGET_SECONDS = 15.0
CACHE_SECONDS = 30.0
PURPOSES = ("run", "pull", "build", "doctor")
STATVFS = getattr(os, "statvfs", None)      # free space of a folder; tests replace it
_CACHE: dict = {}


def diagnosis_module():
    """python/docker_diagnosis.py (the table-driven classifier), found next to this package like python/docker_setup.py."""
    folder = str(Path(__file__).resolve().parent.parent / "python")
    if folder not in sys.path:
        sys.path.insert(0, folder)
    import docker_diagnosis
    return docker_diagnosis


def diagnose(text, context=None) -> dict:
    return diagnosis_module().diagnose(text, context or {})


def detected_environment():
    """docker_setup.detect_environment() (reads files and the environment only), or {} when it cannot be read."""
    try:
        folder = str(Path(__file__).resolve().parent.parent / "python")
        if folder not in sys.path:
            sys.path.insert(0, folder)
        import docker_setup
        return docker_setup.detect_environment()
    except Exception:  # noqa: BLE001 - advice only; the checks do not depend on it
        return {}


def estimate_build_gb(root) -> tuple:
    """(GB, how it was estimated): 3 GB for the base image plus 3 GB per conda environment the Dockerfile creates. Not measured; always shown as an estimate."""
    try:
        text = (Path(root) / "Dockerfile").read_text(encoding="utf-8")
    except OSError:
        text = ""
    envs = len(re.findall(r"micromamba create", text))
    if not envs:
        return 12.0, "estimated (no Dockerfile found to count its conda environments)"
    return 3.0 + 3.0 * envs, f"estimated from the {envs} conda environments the Dockerfile creates"


def parse_info(out: str) -> dict:
    """The facts of `docker info` (JSON from --format '{{json .}}', else the plain text): {root_dir, driver, os, server_version, proxies, mem_gb, rootless, warnings}."""
    info = {"root_dir": "", "driver": "", "os": "", "server_version": "", "http_proxy": "", "https_proxy": "", "no_proxy": "", "mem_gb": None, "rootless": False, "warnings": [], "cgroup": ""}
    text = (out or "").strip()
    if not text:
        return info
    data = None
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except ValueError:
            data = None
    if isinstance(data, dict):
        info.update(root_dir=str(data.get("DockerRootDir") or ""), driver=str(data.get("Driver") or ""), os=str(data.get("OperatingSystem") or ""),
                    server_version=str(data.get("ServerVersion") or ""), http_proxy=mask_proxy(str(data.get("HttpProxy") or data.get("HTTPProxy") or "")),
                    https_proxy=mask_proxy(str(data.get("HttpsProxy") or data.get("HTTPSProxy") or "")), no_proxy=str(data.get("NoProxy") or ""), cgroup=str(data.get("CgroupDriver") or ""),
                    warnings=[str(w) for w in (data.get("Warnings") or [])][:5])
        mem = data.get("MemTotal")
        info["mem_gb"] = round(mem / 2 ** 30, 1) if isinstance(mem, (int, float)) and mem else None
        info["rootless"] = any("rootless" in str(o).lower() for o in (data.get("SecurityOptions") or []))
        return info
    for line in text.splitlines():
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "docker root dir":
            info["root_dir"] = value
        elif key == "storage driver":
            info["driver"] = value
        elif key == "operating system":
            info["os"] = value
        elif key == "server version":
            info["server_version"] = value
        elif key == "http proxy":
            info["http_proxy"] = mask_proxy(value)
        elif key == "https proxy":
            info["https_proxy"] = mask_proxy(value)
        elif key == "no proxy":
            info["no_proxy"] = value
        elif key == "cgroup driver":
            info["cgroup"] = value
        elif "rootless" in line.lower() and "name=" in line.lower():
            info["rootless"] = True
    return info


def mask_proxy(value: str) -> str:
    """A proxy address without the password in it."""
    return re.sub(r"(//[^/:@\s]+):[^@/\s]+@", r"\1:***@", value or "")


def _free_gb(path, statvfs):
    """(GB, the folder that was measured) for the filesystem holding `path`: the folder itself, else the nearest parent that can be read (Docker's folder is usually root-only: the parent is on the same disk)."""
    target = PurePosixPath(str(path).replace(chr(92), "/"))      # a local engine is a Linux one: its folders are POSIX paths
    tried = 0
    while tried < 6:
        try:
            st = statvfs(str(target))
            return st.f_bavail * st.f_frsize / 2 ** 30, str(target)
        except (OSError, AttributeError):
            if target == target.parent:
                break
            target = target.parent
            tried += 1
    return None, ""


def _local_engine(info: dict, environ) -> bool:
    """True when Docker's root directory is on THIS computer's own filesystem (a Linux engine): not Docker Desktop (a virtual machine), not a remote DOCKER_HOST."""
    if os.name == "nt" or sys.platform == "darwin":
        return False
    host = str(environ.get("DOCKER_HOST") or "")
    if host and not host.startswith("unix://"):
        return False
    if "docker desktop" in (info.get("os") or "").lower() or "desktop" in (info.get("root_dir") or "").lower():
        return False
    return bool(info.get("root_dir"))


def check(root=None, *, purpose="run", run=None, exe=None, environ=None, statvfs=None, budget=BUDGET_SECONDS, clock=time.monotonic, environment=None, image=None, token=None, local=None) -> dict:
    """Run the checks. -> {'healthy', 'purpose', 'checks': [{name, ok, warn, detail, advice, commands, diagnosis}], 'diagnosis' (of the first failure, or None), 'info', 'environment',
    'warnings', 'plan', 'seconds'}. Never raises. `purpose`: run | pull | build | doctor (pull, build and doctor also look at free disk space)."""
    run = run or dr._run
    environ = dict(os.environ if environ is None else environ)
    exe = exe if exe is not None else dr.docker_exe()
    statvfs = statvfs or STATVFS
    environment = environment if environment is not None else detected_environment()
    started = clock()
    deadline = started + budget
    rows, info, ctx = [], {}, {"env": environment, "image": image or ""}

    def left(want):
        return max(1.0, min(float(want), deadline - clock()))

    def add(name, ok, detail, diag=None, warn=False, advice=None, commands=None):
        rows.append({"name": name, "ok": bool(ok), "warn": bool(warn) and bool(ok), "detail": detail, "advice": advice if advice is not None else (diag["advice"] if diag else []),
                     "commands": commands if commands is not None else (diag["commands"] if diag else []), "diagnosis": diag})
        return bool(ok)

    def fail(name, text, prefix=""):
        diag = diagnose(text, dict(ctx, docker_info=ctx.get("docker_info", "")))
        add(name, False, prefix + (diag["title"] if diag["cause"] != "unknown" else "unexpected answer: " + (text.strip().splitlines() or [""])[-1][:200]), diag)

    if not exe:
        add("Docker command", False, "the docker command was not found (not installed, or not on PATH)",
            advice=["Install Docker (the Tools page: Install Docker, or `plasbench install-tools docker`), or use conda: `plasbench runtime use conda`."], commands=["plasbench install-tools docker"])
        return _finish(rows, info, purpose, started, clock, environment, ctx, root)
    add("Docker command", True, exe)
    code, out = run([exe, "version", "--format", "{{.Server.Version}}|{{.Server.Arch}}|{{.Client.Version}}"], left(10))
    if not (code == 0 and out[:1].isdigit()):
        fail("Engine answers", out or "docker did not answer", "")
        return _finish(rows, info, purpose, started, clock, environment, ctx, root)
    parts = (out.splitlines()[0].split("|") + ["", "", ""])[:3]
    info.update(server_version=parts[0], arch=parts[1], client_version=parts[2])
    add("Engine answers", True, f"Docker {parts[0]}" + (f" ({parts[1]})" if parts[1] else "") + (f", client {parts[2]}" if parts[2] else ""))
    if clock() < deadline:
        code, out = run([exe, "info", "--format", "{{json .}}"], left(10))
        if code != 0:
            fail("Engine details (docker info)", out)
        else:
            facts = parse_info(out)
            info.update({k: v for k, v in facts.items() if v not in ("", None, [])})
            ctx["docker_info"] = mask_proxy(out[:4000])
            if facts["rootless"]:
                ctx["rootless"] = True
            shown = [f"root dir {facts['root_dir']}" if facts["root_dir"] else "", f"storage driver {facts['driver']}" if facts["driver"] else "", facts["os"], f"{facts['mem_gb']} GB memory" if facts["mem_gb"] else ""]
            add("Engine details (docker info)", True, ", ".join(s for s in shown if s) or "docker info gave no details", warn=bool(facts["warnings"]))
            if facts["warnings"]:
                rows[-1]["detail"] += ". Warnings: " + "; ".join(w.strip()[:120] for w in facts["warnings"][:3])
    if rows[-1]["name"].startswith("Engine details") and not rows[-1]["ok"]:
        return _finish(rows, info, purpose, started, clock, environment, ctx, root)
    proxies = {k: mask_proxy(info.get(k, "")) for k in ("http_proxy", "https_proxy", "no_proxy")}
    client_proxy = {k: mask_proxy(environ.get(k, "")) for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy") if environ.get(k)}
    info["proxies"] = dict(proxies, client=client_proxy)
    if proxies["http_proxy"] or proxies["https_proxy"]:
        add("Proxy", True, "the engine uses a proxy (" + ", ".join(f"{k.replace('_proxy', '').upper()} {v}" for k, v in proxies.items() if v and k != "no_proxy") + "). Proxies commonly cut or corrupt large layer downloads: if a pull fails with a corrupted layer, check the proxy first.",
            warn=True, advice=["If pulls fail with corrupted or incomplete layers, try without the proxy or ask whoever runs it to exempt ghcr.io."], commands=["docker info | grep -i proxy"])
    if purpose in ("pull", "build", "doctor") and clock() < deadline:
        _disk(rows, add, info, purpose, root, environ, statvfs, ctx, local)
    if clock() < deadline:
        name = "pb-health-" + (token or uuid.uuid4().hex[:8])
        code, out = run([exe, "volume", "create", "--label", "plasbench=health", name], left(10))
        if code != 0:
            fail("Engine can write (create and remove a test volume)", out, "")
        else:
            code2, out2 = run([exe, "volume", "rm", name], left(10))
            if code2 != 0:
                add("Engine can write (create and remove a test volume)", True, f"the test volume {name} was created but could not be removed ({(out2 or '').strip()[:120]}); remove it with: docker volume rm {name}", warn=True,
                    commands=[f"docker volume rm {name}"])
            else:
                add("Engine can write (create and remove a test volume)", True, "created and removed a test volume: the engine's metadata is writable (no network used)")
    else:
        add("Engine can write (create and remove a test volume)", True, "skipped: the time limit of the checks was used up", warn=True)
    if purpose == "doctor" and image and clock() < deadline + 30:
        code, out = run([exe, "image", "inspect", image, "--format", "{{.Id}}"], left(10))
        if code == 0:
            code, out = run([exe, "run", "--rm", "--pull=never", image, "true"], 30)
            if code == 0:
                add("A container starts (local image, nothing pulled)", True, f"`docker run --rm --pull=never {image} true` worked")
            else:
                fail("A container starts (local image, nothing pulled)", out)
        else:
            add("A container starts (local image, nothing pulled)", True, f"skipped: {image} is not on this computer (a health check never pulls)", warn=True)
    return _finish(rows, info, purpose, started, clock, environment, ctx, root)


def _disk(rows, add, info, purpose, root, environ, statvfs, ctx, local=None):
    name = "Free disk space for Docker"
    if purpose == "build" or purpose == "doctor":
        need, how = estimate_build_gb(root) if root is not None else (12.0, "estimated")
    else:
        need, how = WARN_FREE_GB, "a pull needs the image's layers (not measured; a few GB)"
    if not (statvfs and (local if local is not None else _local_engine(info, environ))):
        where = "Docker Desktop keeps its disk inside a virtual machine: see Docker Desktop > Settings > Resources (Disk usage), and the drive that holds it" if "docker desktop" in (info.get("os") or "").lower() or os.name == "nt" or sys.platform == "darwin" \
            else "the engine's disk cannot be measured from here (a remote or unreadable engine); `docker system df` shows what Docker uses"
        extra = " A build needs about {:.0f} GB ({}).".format(need, how) if purpose != "pull" else ""
        add(name, True, "not measured: " + where + "." + extra, warn=True, commands=["docker system df"])
        return
    free, where = _free_gb(info["root_dir"], statvfs)
    if free is None:
        add(name, True, f"could not read the free space of {info['root_dir']} (no permission); try: df -h {info['root_dir']}", warn=True, commands=[f"df -h {info['root_dir']}"])
        return
    note = "" if where == info["root_dir"] else f" (measured on {where}, the same disk)"
    cmds = [f"df -h {info['root_dir']}", "docker system df"]
    if free < BLOCK_FREE_GB and purpose in ("pull", "build", "doctor"):
        diag = diagnose("no space left on device", dict(ctx))
        diag.update(title=f"only {free:.1f} GB are free where Docker keeps its data", evidence_lines=[f"{free:.1f} GB free on the disk of {info['root_dir']}{note}"])
        add(name, False, f"only {free:.1f} GB free{note}: a pull or build would fail or damage a layer (needs more than {BLOCK_FREE_GB:.0f} GB; a build about {need:.0f} GB, {how})", diag)
        info["free_gb"] = round(free, 1)
        return
    info["free_gb"] = round(free, 1)
    low = free < WARN_FREE_GB or (purpose in ("build", "doctor") and free < need)
    add(name, True, f"{free:.1f} GB free{note}" + (f"; a build needs about {need:.0f} GB ({how}): free more space first" if low and purpose in ("build", "doctor") and free < need else
                                                  ("; less than 10 GB: free some space before a large pull" if low else "")), warn=low, commands=cmds if low else [])


def _finish(rows, info, purpose, started, clock, environment, ctx, root) -> dict:
    failed = [r for r in rows if not r["ok"]]
    diag = failed[0]["diagnosis"] if failed else None
    kind = None
    try:
        kind = diagnosis_module().environment_kind("", dict(ctx, env=environment))
    except Exception:  # noqa: BLE001
        kind = "unknown"
    warnings = [f"{r['name']}: {r['detail']}" for r in rows if r.get("warn")]
    result = {"healthy": not failed, "purpose": purpose, "checks": rows, "diagnosis": diag, "info": info, "environment": kind, "environment_label": environment_label(kind), "environment_detail": {k: environment.get(k) for k in ("kind", "wsl", "systemd", "distro", "container") if environment},
              "warnings": warnings, "seconds": round(clock() - started, 2)}
    result["plan"] = plan(result)
    return result


def plan(result: dict) -> list:
    """The numbered next steps, safest first: read-only looks, then what to change. Never a deleting command (those are in diagnosis['last_resort'] with their consequence)."""
    diag = result.get("diagnosis")
    if diag:
        return list(diag["advice"])
    steps = []
    for row in result["checks"]:
        if row.get("warn") and row.get("advice"):
            steps += row["advice"]
    return steps or ["Nothing to fix: the engine answers, can write, and has room. If a pull still fails, its own message names the cause."]


def environment_label(kind: str) -> str:
    return {"desktop_windows": "Docker Desktop on Windows (WSL 2)", "desktop_macos": "Docker Desktop on macOS", "desktop": "Docker Desktop", "linux": "Docker Engine on Linux",
            "rootless": "rootless Docker", "unknown": "Docker (environment not recognised)"}.get(kind, kind)


def render(result: dict, verbose=True) -> str:
    """The checks as text: PASS/FAIL (and NOTE for a warning) per check with its evidence, then the numbered plan."""
    info = result["info"]
    lines = [f"Environment: {environment_label(result['environment'])}"]
    if info.get("server_version"):
        lines.append(f"Docker: server {info['server_version']}" + (f", client {info['client_version']}" if info.get("client_version") else "") + (f", {info['arch']}" if info.get("arch") else ""))
    for key, label in (("root_dir", "Root directory"), ("driver", "Storage driver")):
        if info.get(key):
            lines.append(f"{label}: {info[key]}")
    if info.get("free_gb") is not None:
        lines.append(f"Free space there: {info['free_gb']} GB")
    px = info.get("proxies") or {}
    shown = [f"{k.upper()} {v}" for k, v in (("http", px.get("http_proxy")), ("https", px.get("https_proxy")), ("no proxy", px.get("no_proxy"))) if v]
    shown += [f"{k}={v}" for k, v in (px.get("client") or {}).items()]
    lines.append("Proxies: " + ("; ".join(shown) if shown else "none set in Docker or in this shell"))
    lines.append("")
    for row in result["checks"]:
        lines.append(f"  {'PASS' if row['ok'] and not row['warn'] else ('NOTE' if row['ok'] else 'FAIL')}  {row['name']}: {row['detail']}")
        if verbose and row.get("diagnosis"):
            for ev in row["diagnosis"]["evidence_lines"][:3]:
                lines.append("        evidence: " + ev)
    lines.append("")
    lines.append("Result: " + ("healthy: the engine can pull, build and run." if result["healthy"] else "PROBLEMS FOUND: PlasBench will not pull or build until this is fixed."))
    steps = result["plan"]
    lines.append("Next steps (nothing below is run for you):")
    lines += [f"  {i}. {s}" for i, s in enumerate(steps, 1)]
    cmds = []
    for row in result["checks"]:
        if not row["ok"] or row.get("warn"):
            cmds += row.get("commands") or []
    cmds = list(dict.fromkeys(cmds))
    if cmds:
        lines.append("Commands to copy (read-only unless noted):")
        lines += ["  " + c for c in cmds]
    diag = result.get("diagnosis")
    if diag and diag.get("last_resort"):
        lines.append("Last resort ONLY, after the steps above, if you accept the consequence:")
        for item in diag["last_resort"]:
            lines += ["  " + item["command"], "    WARNING: " + item["warning"]]
    return "\n".join(lines)


def cached(root=None, *, purpose="run", run=None, exe=None, environ=None, ttl=CACHE_SECONDS, **kw) -> dict:
    """check() remembered for `ttl` seconds when it runs against the real docker (a fake docker is never cached, so tests see every call)."""
    if run is not None or exe is not None or environ is not None:
        return check(root, purpose=purpose, run=run, exe=exe, environ=environ, **kw)
    key = (dr.docker_exe(), purpose)
    hit = _CACHE.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < ttl:
        return hit[1]
    value = check(root, purpose=purpose, **kw)
    _CACHE[key] = (time.monotonic(), value)
    return value


def forget() -> None:
    _CACHE.clear()


def show(diag: dict, out=print, prefix="[plasbench] ") -> None:
    """A diagnosis as lines: the evidence, the numbered steps, the commands to copy, the last resorts with their consequences."""
    for ev in diag["evidence_lines"][:3]:
        out("    " + ev)
    for i, step in enumerate(diag["advice"], 1):
        out(f"{prefix}  {i}. {step}")
    if diag["commands"]:
        out(prefix + "Commands you can run yourself (PlasBench never runs these):")
        for c in diag["commands"]:
            out("    " + c)
    if diag.get("last_resort"):
        out(prefix + "Last resort only, after the steps above, and only if you accept the consequence:")
        for item in diag["last_resort"]:
            out("    " + item["command"])
            out("      WARNING: " + item["warning"])


def explain(result: dict, out=print) -> None:
    """The lines a failed pre-flight prints: what is wrong, the evidence, the steps, the commands. (A pass prints only its notes.)"""
    diag = result.get("diagnosis")
    bad = [r for r in result["checks"] if not r["ok"]]
    if not bad:
        for note in result.get("warnings", []):
            out("[plasbench] note: " + note)
        return
    out(f"[plasbench] Docker is not healthy: {bad[0]['name']}: {bad[0]['detail']}")
    if diag:
        show(diag, out)
    out("[plasbench] Nothing was pulled or built. After fixing it run: plasbench runtime doctor")


def enabled(environ=None) -> bool:
    """PLASBENCH_DOCKER_HEALTH=off skips the pre-flight (an escape hatch for a check that is wrong on an unusual setup); `plasbench runtime doctor` always runs."""
    environ = os.environ if environ is None else environ
    return str(environ.get("PLASBENCH_DOCKER_HEALTH", "on")).strip().lower() not in ("off", "0", "no", "false")


def record(root, diag: dict, stage: str, environ=None, env=None) -> None:
    """Remember a diagnosis: a line in RESULTS_DIR/run_events.jsonl (when that folder exists: same format as scripts/lib.sh run_event) and JOB_ID.diagnosis.json in the window's job folder
    (the job's result). Never raises, never creates the results folder, holds no secrets (a cause id and a title)."""
    environ = dict(os.environ if environ is None else environ)
    row = {"cause": diag["cause"], "title": diag["title"], "confidence": diag["confidence"], "engine_unhealthy": bool(diag["engine_unhealthy"]), "build_ok": bool(diag["build_ok"]), "stage": stage}
    try:
        results = dr.effective_paths(root, env or {}, environ).get("RESULTS_DIR", "")
        if results and os.path.isdir(results):
            line = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "epoch": int(time.time()), "pid": os.getpid(), "event": "docker_diagnosis"}
            line.update({k: str(v) for k, v in row.items()})
            with open(os.path.join(results, "run_events.jsonl"), "a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(line) + "\n")
    except (OSError, ValueError):
        pass
    job_dir, job = environ.get("PLASBENCH_JOB_DIR"), re.sub(r"[^A-Za-z0-9_.-]", "", environ.get("PLASBENCH_JOB_ID", ""))
    if job_dir and job:
        try:
            with open(os.path.join(job_dir, job + ".diagnosis.json"), "w", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(dict(row, evidence=diag["evidence_lines"][:3])))
        except OSError:
            pass


def retries(environ=None) -> int:
    """PLASBENCH_DOCKER_PULL_RETRIES: extra pull attempts after a retryable failure (default 2, 0 to 5)."""
    environ = os.environ if environ is None else environ
    try:
        return max(0, min(5, int(str(environ.get("PLASBENCH_DOCKER_PULL_RETRIES", "2")).strip())))
    except ValueError:
        return 2


def backoff(attempt: int, environ=None) -> float:
    """Seconds to wait before pull retry number attempt+1: PLASBENCH_DOCKER_PULL_BACKOFF (default 5) doubled each time, at most 60."""
    environ = os.environ if environ is None else environ
    try:
        base = float(str(environ.get("PLASBENCH_DOCKER_PULL_BACKOFF", "5")).strip())
    except ValueError:
        base = 5.0
    return max(0.0, min(60.0, base * 2 ** attempt))
