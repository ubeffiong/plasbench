"""`plasbench ui`: the PlasBench setup and run window, a local web page served from this computer.

Everything the window does is an ordinary `plasbench` command run as a job (the console shows its exact command line
and live output), so the window adds no behaviour of its own that the command line lacks. It reads:
  plasbench.ui_schema   every command and option, generated from the CLI parser
  config/config.sh      every setting and its default; config/local.env holds this computer's overrides
  config/tool_*.tsv     the tool registries, with user tools merged in (python/user_tools.py)

Security, as GenoSuv's window: bound to 127.0.0.1; every request needs this session's token (cookie for the page,
X-PlasBench-Token header for API calls) and a loopback Host header (DNS-rebinding protection); state-changing requests
must be same-origin POSTs. Only `plasbench` itself is ever executed, after its argument list has been parsed by the
real CLI parser; nothing is passed through a shell.
"""
from __future__ import annotations

import json
import os
import platform
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from . import __version__
from . import ui_schema

TOKEN = secrets.token_urlsafe(24)
PAGE_FILE = Path(__file__).resolve().parent / "data" / "ui.html"
UI_HOME = Path(os.environ.get("PLASBENCH_UI_HOME", Path.home() / ".plasbench" / "ui"))
SERVABLE = {".html": "text/html; charset=utf-8", ".pdf": "application/pdf", ".tsv": "text/tab-separated-values; charset=utf-8",
            ".json": "application/json; charset=utf-8", ".txt": "text/plain; charset=utf-8", ".md": "text/plain; charset=utf-8",
            ".log": "text/plain; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png", ".csv": "text/csv; charset=utf-8",
            ".fasta": "text/plain; charset=utf-8", ".fa": "text/plain; charset=utf-8", ".gz": "application/gzip",
            ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".zip": "application/zip"}
MAX_LOG_CHUNK = 256 * 1024


# --------------------------------------------------------------------------------------------- project facts
class Project:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.python_dir = self.root / "python"
        if str(self.python_dir) not in sys.path:
            sys.path.insert(0, str(self.python_dir))

    # -- settings: config/config.sh (defaults) + config/local.env (this computer) -----------------------------
    def settings(self) -> list[dict]:
        """Every `export KEY=...` in config/config.sh with its default, comment and section, plus the override in
        config/local.env and the value in this process's environment."""
        text = (self.root / "config" / "config.sh").read_text(encoding="utf-8", errors="replace")
        local = self.local_env()
        out, group, comment = [], "General", []
        for raw in text.splitlines():
            line = raw.strip()
            head = re.match(r"^#\s*-{2,}\s*(.+?)\s*-{2,}", line)
            if head:
                group, comment = head.group(1).strip(" -"), []
                continue
            if line.startswith("#"):
                body = line.lstrip("#").strip()
                if body and not set(body) <= set("=-"):
                    comment.append(body)
                continue
            # A bare `export KEY` publishes a value config.sh computed above (THREADS from the detected cores, for
            # example): a setting whose default is worked out on this computer.
            bare = re.match(r'^export\s+([A-Z][A-Z0-9_]*)\s*$', line)
            if bare:
                key = bare.group(1)
                out.append({"key": key, "default": "worked out on this computer", "comment": " ".join(comment)[:900],
                            "group": group, "override": local.get(key), "env": os.environ.get(key),
                            "kind": "int" if key.endswith(("THREADS", "_GB")) else "text", "computed": True})
                comment = []
                continue
            m = re.match(r'^export\s+([A-Z][A-Z0-9_]*)=(.*)$', line)
            if not m:
                if not line:
                    comment = []
                continue
            key, value = m.group(1), m.group(2)
            inline = ""
            if " # " in value:
                value, inline = value.split(" # ", 1)
            dm = re.match(r'^"?\$\{' + key + r':-(.*)\}"?\s*$', value.strip())
            default = dm.group(1) if dm else value.strip().strip('"')
            note = " ".join(comment + ([inline.strip()] if inline else []))
            out.append({"key": key, "default": default, "comment": note[:900], "group": group,
                        "override": local.get(key), "env": os.environ.get(key),
                        "kind": "flag" if key.startswith("RUN_") or default in ("0", "1") and key.isupper() else
                                ("int" if re.fullmatch(r"\d+", default or "") else "text")})
            comment = []
        seen, unique = set(), []
        for row in out:
            if row["key"] not in seen:
                seen.add(row["key"])
                unique.append(row)
        return unique

    def local_env_path(self) -> Path:
        return Path(os.environ.get("PLASBENCH_LOCAL_SETTINGS", self.root / "config" / "local.env"))

    def local_env(self) -> dict:
        path, values = self.local_env_path(), {}
        if path.is_file():
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
                if m:
                    try:
                        parts = shlex.split(m.group(2))
                        values[m.group(1)] = parts[0] if parts else ""
                    except ValueError:
                        values[m.group(1)] = m.group(2)
        return values

    def save_local_env(self, changes: dict) -> dict:
        """Set (value) or remove (None) keys in config/local.env, keeping every other line and comment as it is."""
        for key, value in changes.items():
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
                raise ValueError(f"not a setting name: {key}")
            if value is not None and ("\n" in str(value) or "\r" in str(value)):
                raise ValueError(f"{key}: a value cannot contain a line break")
        path = self.local_env_path()
        lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else \
            ["# PlasBench settings for this computer (read by config/config.sh). Written by `plasbench ui`; edit freely."]
        done = set()
        kept = []
        for line in lines:
            m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=", line)
            if m and m.group(1) in changes:
                key = m.group(1)
                if changes[key] is not None and key not in done:
                    kept.append(f"export {key}={shlex.quote(str(changes[key]))}")
                done.add(key)
                continue
            kept.append(line)
        for key, value in changes.items():
            if key not in done and value is not None:
                kept.append(f"export {key}={shlex.quote(str(value))}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(kept) + "\n", encoding="utf-8", newline="\n")
        return self.local_env()

    def setting(self, key: str, fallback: str = "") -> str:
        local = self.local_env()
        if os.environ.get(key):
            return os.environ[key]
        if local.get(key):
            return local[key]
        for row in self.settings():
            if row["key"] == key:
                value = row["default"]
                value = value.replace("$PROJECT_ROOT", str(self.root)).replace("${PROJECT_ROOT}", str(self.root))
                value = value.replace("$HOME", str(Path.home()))
                return value if "$" not in value else fallback
        return fallback

    def path_setting(self, key: str, default_rel: str) -> Path:
        value = self.setting(key, "")
        if key == "DATA_DIR":
            value = os.environ.get("DATA_DIR") or self.local_env().get("PLASBENCH_DATA_DIR") or self.local_env().get("DATA_DIR") or ""
        return Path(value).expanduser() if value else self.root / default_rel

    # -- tools ------------------------------------------------------------------------------------------------
    def tools(self) -> list[dict]:
        import csv
        try:
            from tool_capabilities import read_capabilities
            caps = read_capabilities(self.root / "config" / "tool_capabilities.tsv")
        except Exception as exc:  # a broken registry is shown, not fatal to the window
            return [{"tool": "(registry error)", "error": str(exc)}]
        try:
            from tool_installer_registry import read_tsv
            installers = {r["tool"]: r for r in read_tsv(self.root / "config" / "tool_installers.tsv")}
        except Exception:
            installers = {}
        try:
            from plasbench_common import display_tool_name
        except Exception:
            display_tool_name = lambda t: t  # noqa: E731
        dbrel = {}
        path = self.root / "config" / "tool_database_releases.tsv"
        if path.is_file():
            with path.open(encoding="utf-8", newline="") as handle:
                dbrel = {r["tool"]: r for r in csv.DictReader(handle, delimiter="\t") if r.get("tool")}
        defaults = {row["key"]: row for row in self.settings()}
        local = self.local_env()
        out = []
        for name, row in caps.items():
            inst = installers.get(name, {})
            verify = (inst.get("verify_command") or "").split()
            exe = verify[0] if verify and verify[0] not in ("python", "python3", "bash") else (verify[1] if len(verify) > 1 else "")
            flag = "RUN_" + name.upper()
            flag_row = defaults.get(flag)
            enabled = local.get(flag) or os.environ.get(flag) or (flag_row["default"] if flag_row else None)
            out.append({
                "tool": name, "display": display_tool_name(name), "source": row.get("source") or ("demo" if name.endswith("_like") else "builtin"),
                "task": "reconstruction" if row.get("binning_capable") == "yes" else "classification",
                "track": row.get("analysis_track"), "method_class": row.get("method_class"),
                "input": row.get("primary_input"), "description": row.get("description", ""),
                "profile": inst.get("profile", ""), "automated": inst.get("automated", ""),
                "database_mode": inst.get("database_mode", ""), "verify": inst.get("verify_command", ""),
                "notes": inst.get("notes", ""), "installed": bool(exe and shutil.which(exe)) if exe else None,
                "executable": exe, "run_flag": flag if flag_row else None, "enabled": enabled == "1" if enabled is not None else None,
                "database": (dbrel.get(name) or {}).get("database", ""),
                "database_release": (dbrel.get(name) or {}).get("database_release_date", ""),
            })
        return out

    def user_tools(self):
        import user_tools
        user_tools._CACHE.clear()
        return user_tools

    # -- environment ------------------------------------------------------------------------------------------
    def env_checks(self) -> list[dict]:
        from .cli import bash_command
        checks = []

        def add(id_, label, ok, detail, fix="", group="System", optional=False):
            checks.append({"id": id_, "label": label, "ok": bool(ok), "detail": detail, "fix": fix, "group": group,
                           "optional": optional})

        add("python", "Python 3.9 or newer", sys.version_info >= (3, 9), sys.version.split()[0])
        try:
            bash = bash_command()
            add("bash", "Bash (runs the pipeline stages)", bool(bash and shutil.which(bash) or Path(str(bash)).exists()), str(bash),
                "" if os.name != "nt" else "Install Git for Windows (Git Bash) or WSL.")
        except Exception as exc:
            add("bash", "Bash (runs the pipeline stages)", False, str(exc), "Install Git for Windows (Git Bash) or WSL.")
        solver = next((s for s in ("mamba", "conda", "micromamba") if shutil.which(s)), None)
        add("conda", "Conda, mamba or micromamba (installs the tools)", solver, solver or "not found", "" if solver else "install-conda")
        add("git", "Git (upgrades, contributions)", shutil.which("git"), shutil.which("git") or "not found",
            "Install Git from https://git-scm.com/", optional=True)
        core = [("datasets", "NCBI datasets"), ("prefetch", "SRA toolkit: prefetch"), ("fasterq-dump", "SRA toolkit: fasterq-dump"),
                ("fastp", "fastp (read trimming)"), ("minimap2", "minimap2 (scoring alignments)")]
        for exe, label in core:
            path = shutil.which(exe)
            add(exe, label, path, path or "not on PATH", "" if path else "install-tools core", group="Core tools")
        for exe, label, profile in (("spades.py", "SPAdes (short-read assembly)", "assembly"), ("mash", "Mash (clonal groups)", "utilities")):
            path = shutil.which(exe)
            add(exe, label, path, path or "not on PATH", "" if path else f"install-tools {profile}", group="Core tools",
                optional=exe == "mash")
        db = Path(os.environ.get("PLASBENCH_DB_DIR") or self.local_env().get("PLASBENCH_DB_DIR") or Path.home() / ".plasbench" / "databases")
        present = sorted(p.name for p in db.iterdir() if p.is_dir()) if db.is_dir() else []
        add("databases", "Tool databases", bool(present), f"{db}: " + (", ".join(present) if present else "none yet"),
            "" if present else "check", group="Databases", optional=not present)
        local = self.local_env()
        email = os.environ.get("NCBI_EMAIL") or local.get("NCBI_EMAIL")
        key = os.environ.get("NCBI_API_KEY") or local.get("NCBI_API_KEY")
        add("ncbi_email", "NCBI contact email", email, email or "not set", "settings:NCBI_EMAIL", group="NCBI access", optional=True)
        add("ncbi_key", "NCBI API key (faster downloads)", key, "set" if key else "not set", "settings:NCBI_API_KEY",
            group="NCBI access", optional=True)
        data = self.path_setting("DATA_DIR", "data")
        probe = data if data.exists() else self.root
        free = shutil.disk_usage(probe).free
        add("disk", "Free disk space for data", free > 50 * 2**30, f"{free / 2**30:,.0f} GB free at {probe}",
            "A full cohort needs hundreds of GB; free space or set DATA_DIR on a larger drive.", group="System", optional=True)
        return checks

    def info(self) -> dict:
        cpus = os.cpu_count() or 1
        mem = None
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
                mem = ms.total / 2**30
            elif hasattr(os, "sysconf"):
                mem = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
        except (OSError, ValueError, AttributeError):
            mem = None
        return {"version": __version__, "root": str(self.root), "platform": f"{platform.system()} {platform.release()}",
                "python": sys.version.split()[0], "cpus": cpus, "memory_gb": round(mem, 1) if mem else None,
                "data_dir": str(self.path_setting("DATA_DIR", "data")), "results_dir": str(self.root / "results"),
                "local_env": str(self.local_env_path()), "home": str(Path.home()), "sep": os.sep}

    # -- runs and reports ---------------------------------------------------------------------------------------
    def runs(self, extra: list[str]) -> list[dict]:
        import csv
        try:
            from plasbench_common import display_tool_name
        except Exception:
            display_tool_name = lambda t: t  # noqa: E731
        candidates = {self.root / "results", self.root / "results_demo"}
        candidates.update(p for p in self.root.glob("results*") if p.is_dir())
        candidates.update(Path(e) for e in extra)
        from . import studies
        candidates.update(Path(st["results"]) for st in studies.list_studies(self.root))
        rows = []
        for folder in sorted(candidates):
            if not folder.is_dir():
                continue
            report = folder / "benchmark.report.html"
            leaderboard = folder / "benchmark.leaderboard.tsv"
            if not report.is_file() and not leaderboard.is_file():
                continue
            leaders, tools = [], set()
            if leaderboard.is_file():
                with leaderboard.open(encoding="utf-8", newline="") as handle:
                    for row in csv.DictReader(handle, delimiter="\t"):
                        tools.add(row.get("tool"))
                        if row.get("rank") == "1":
                            leaders.append({"task": row.get("task", ""), "track": row.get("analysis_track", ""),
                                            "tool": row.get("tool", ""), "display": display_tool_name(row.get("tool", "")),
                                            "f1": row.get("mean_f1", ""),
                                            "lw": row.get("mean_lw_bin_f1", "")})
            samples = 0
            status = folder / "tool_status.tsv"
            failed = 0
            if status.is_file():
                with status.open(encoding="utf-8", newline="") as handle:
                    rows_ = list(csv.DictReader(handle, delimiter="\t"))
                samples = len({r.get("sample") for r in rows_})
                failed = sum(1 for r in rows_ if r.get("status") in ("failed", "infrastructure_failure"))
            stamp = max((p.stat().st_mtime for p in (report, leaderboard) if p.exists()), default=0)
            # a study's results live in <study>/results: show the study's name
            is_study = folder.name == "results" and (folder.parent / "study.json").is_file()
            rows.append({"path": str(folder), "name": folder.parent.name if is_study else folder.name, "study": is_study,
                         "study_dir": str(folder.parent) if is_study else None, "report": report.is_file(),
                         "pdf": (folder / "benchmark.report.pdf").is_file(),
                         "summary_pdf": (folder / "benchmark.report.summary.pdf").is_file(),
                         "modified": stamp, "tools": len(tools - {None}), "samples": samples, "failed": failed,
                         "leaders": leaders})
        rows.sort(key=lambda r: -r["modified"])
        return rows

    def cohorts(self) -> list[dict]:
        out = []
        for path in sorted((self.root / "cohorts").glob("*.tsv")):
            try:
                n = sum(1 for line in path.open(encoding="utf-8") if line.strip() and not line.startswith("#")) - 1
            except OSError:
                n = 0
            name = path.stem
            out.append({"name": name, "path": str(path), "rows": max(n, 0), "locked": (path.parent / f"{name}.lock.json").is_file(),
                        "metagenomic": name.startswith("metagenomics")})
        return out

    def docs(self) -> list[dict]:
        out = []
        for path in [self.root / "README.md"] + sorted((self.root / "docs").glob("*.md")) + sorted((self.root / "adapters").glob("*.md")):
            if path.is_file():
                first = next((l.lstrip("# ").strip() for l in path.read_text(encoding="utf-8", errors="replace").splitlines()
                              if l.startswith("#")), path.stem)
                out.append({"name": str(path.relative_to(self.root)).replace("\\", "/"), "title": first,
                            "size": path.stat().st_size})
        return out


# --------------------------------------------------------------------------------------------- jobs
class Jobs:
    """Each job is one `plasbench` command in its own process; its output goes to a log file the page tails."""

    def __init__(self, project: Project):
        self.project = project
        self.dir = UI_HOME / "jobs"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.jobs: dict[str, dict] = {}
        self.procs: dict[str, subprocess.Popen] = {}
        self.logs: dict = {}
        index = self.dir / "jobs.json"
        if index.is_file():
            try:
                for job in json.loads(index.read_text(encoding="utf-8")):
                    if job.get("state") == "running":
                        job["state"] = "interrupted"   # the window was closed while it ran
                    self.jobs[job["id"]] = job
            except (ValueError, KeyError):
                pass

    def _save(self):
        recent = sorted(self.jobs.values(), key=lambda j: j["started"])[-100:]
        (self.dir / "jobs.json").write_text(json.dumps(recent, indent=1), encoding="utf-8")

    def start(self, argv: list[str], label: str = "", env: dict | None = None) -> dict:
        ok, message = ui_schema.validate_argv(argv)
        if not ok:
            raise ValueError(message)
        job_id = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
        log = self.dir / f"{job_id}.log"
        command = [sys.executable, "-u", "-m", "plasbench", "--project-root", str(self.project.root)] + list(argv)
        shown = "plasbench " + " ".join(shlex.quote(a) for a in argv)
        child_env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        for key, value in (env or {}).items():
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
                raise ValueError(f"not a setting name: {key}")
            child_env[key] = str(value)
        # Append mode: the command and this server (echoing the answers typed in the window) both write to it.
        handle = open(log, "ab")
        handle.write(f"$ {shown}\n".encode())
        if env:
            handle.write(("  with " + " ".join(f"{k}={shlex.quote(str(v))}" for k, v in env.items()) + "\n").encode())
        handle.flush()
        kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        # stdin is a pipe the window can type into (answer()): a command that asks a question waits for the answer
        # typed in the console instead of being handed an empty one.
        proc = subprocess.Popen(command, cwd=str(self.project.root), stdin=subprocess.PIPE, stdout=handle,
                                stderr=subprocess.STDOUT, env=child_env, **kwargs)
        job = {"id": job_id, "label": label or shown, "argv": list(argv), "command": shown, "env": env or {},
               "state": "running", "started": time.time(), "ended": None, "exit": None, "pid": proc.pid}
        with self.lock:
            self.jobs[job_id] = job
            self.procs[job_id] = proc
            self.logs[job_id] = handle
            self._save()
        threading.Thread(target=self._wait, args=(job_id, proc, handle), daemon=True).start()
        return job

    def _wait(self, job_id, proc, handle):
        code = proc.wait()
        with self.lock:
            self.logs.pop(job_id, None)
            handle.close()
            try:
                proc.stdin.close()
            except (OSError, AttributeError, ValueError):
                pass
            job = self.jobs[job_id]
            job.update(ended=time.time(), exit=code,
                       state="cancelled" if job["state"] == "cancelling" else ("done" if code == 0 else "failed"))
            self.procs.pop(job_id, None)
            self._save()

    def answer(self, job_id: str, text: str, secret: bool = False) -> dict:
        """Type one line into a running command, as if at its terminal, and record it in the log (masked if secret)."""
        if "\n" in text or "\r" in text:
            raise ValueError("one line at a time")
        if len(text) > 4096:
            raise ValueError("answer too long")
        with self.lock:
            proc, handle = self.procs.get(job_id), self.logs.get(job_id)
            if not proc or proc.poll() is not None:
                raise ValueError("this job is not running")
            try:
                proc.stdin.write((text + "\n").encode("utf-8"))
                proc.stdin.flush()
            except (BrokenPipeError, OSError, ValueError) as exc:
                raise ValueError(f"the command is no longer reading input ({exc})")
            if handle:
                shown = "•" * len(text) if secret else text
                handle.write(f"\n[you] {shown}\n".encode("utf-8"))
                handle.flush()
        return {"ok": True}

    def cancel(self, job_id: str) -> dict:
        with self.lock:
            proc = self.procs.get(job_id)
            job = self.jobs.get(job_id)
            if not proc or not job:
                raise KeyError(job_id)
            job["state"] = "cancelling"
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        else:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except OSError:
                proc.terminate()
        return job

    def get(self, job_id: str, offset: int = 0) -> dict:
        job = self.jobs.get(job_id)
        if not job:
            raise KeyError(job_id)
        log = self.dir / f"{job_id}.log"
        text, size = "", 0
        if log.is_file():
            size = log.stat().st_size
            with log.open("rb") as handle:
                handle.seek(max(0, offset))
                text = handle.read(MAX_LOG_CHUNK).decode("utf-8", "replace")
        return dict(job, log=text, offset=min(size, max(0, offset) + MAX_LOG_CHUNK), size=size)

    def list(self) -> list[dict]:
        return sorted(self.jobs.values(), key=lambda j: -j["started"])

    def delete(self, job_id: str):
        with self.lock:
            if job_id in self.procs:
                raise ValueError("cancel the job before removing it")
            self.jobs.pop(job_id, None)
            self._save()
        (self.dir / f"{job_id}.log").unlink(missing_ok=True)


# --------------------------------------------------------------------------------------------- HTTP
def _state_path() -> Path:
    return UI_HOME / "state.json"


def load_state() -> dict:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict):
    _state_path().parent.mkdir(parents=True, exist_ok=True)
    _state_path().write_text(json.dumps(state, indent=1), encoding="utf-8")


def browse(path: str, files: bool) -> dict:
    if not path:
        if os.name == "nt":
            import string
            drives = [f"{d}:\\" for d in string.ascii_uppercase if Path(f"{d}:\\").exists()]
            return {"path": "", "parent": None, "entries": [{"name": d, "path": d, "dir": True} for d in drives]}
        path = str(Path.home())
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"{p} does not exist")
    if p.is_file():
        p = p.parent
    entries = []
    try:
        for child in sorted(p.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):
            if child.name.startswith("."):
                continue
            try:
                is_dir = child.is_dir()
            except OSError:
                continue
            if is_dir or files:
                entry = {"name": child.name, "path": str(child), "dir": is_dir}
                if not is_dir:
                    try:
                        entry["size"] = child.stat().st_size
                    except OSError:
                        entry["size"] = None
                entries.append(entry)
            if len(entries) >= 1500:
                break
    except PermissionError:
        raise PermissionError(f"no permission to list {p}")
    parent = str(p.parent) if p.parent != p else ("" if os.name == "nt" else None)
    return {"path": str(p), "parent": parent, "entries": entries}


def make_handler(project: Project, jobs: Jobs):
    page_cache = {"mtime": 0, "body": b""}

    def page() -> bytes:
        mtime = PAGE_FILE.stat().st_mtime
        if mtime != page_cache["mtime"]:
            html = PAGE_FILE.read_text(encoding="utf-8")
            page_cache.update(mtime=mtime, body=html.replace("__VERSION__", __version__).encode("utf-8"))
        return page_cache["body"]

    class Handler(BaseHTTPRequestHandler):
        server_version = "PlasBenchUI"

        def log_message(self, *args):
            pass

        def send(self, code, body: bytes, ctype="application/json; charset=utf-8", cookie=False, extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            if ctype.startswith("text/html") and not (extra or {}).get("report"):
                self.send_header("Content-Security-Policy",
                                 "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                                 "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if cookie:
                self.send_header("Set-Cookie", f"plasbench_token={TOKEN}; Path=/; SameSite=Strict; HttpOnly")
            self.end_headers()
            self.wfile.write(body)

        def jsend(self, code, obj):
            self.send(code, json.dumps(obj, default=str).encode("utf-8"))

        def host_ok(self):
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
            return host in ("127.0.0.1", "localhost", "::1")

        def token_ok(self):
            tok = self.headers.get("X-PlasBench-Token") or parse_qs(urlparse(self.path).query).get("t", [""])[0]
            if not tok:
                for part in (self.headers.get("Cookie") or "").split(";"):
                    k, _, v = part.strip().partition("=")
                    if k == "plasbench_token":
                        tok = v
            return secrets.compare_digest(tok or "", TOKEN)

        def same_origin(self):
            origin = self.headers.get("Origin")
            return origin is None or urlparse(origin).netloc == self.headers.get("Host", "")

        def body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length > 5 * 2**20:
                raise ValueError("request too large")
            raw = self.rfile.read(length) if length else b"{}"
            return json.loads(raw.decode("utf-8") or "{}")

        # ---------------------------------------------------------------- GET
        def do_GET(self):
            if not self.host_ok():
                return self.send(403, b"Unexpected Host header.", "text/plain; charset=utf-8")
            u = urlparse(self.path)
            path, q = unquote(u.path), {k: v[0] for k, v in parse_qs(u.query).items()}
            if path == "/healthz":
                return self.send(200, b"ok", "text/plain; charset=utf-8")
            if not self.token_ok():
                return self.send(403, ("<!doctype html><title>PlasBench</title><body style='font-family:system-ui;padding:40px'>"
                                       "<h2>Open PlasBench from the link <code>plasbench ui</code> printed</h2><p>This address "
                                       "needs the session key that was printed with it.</p></body>").encode(), "text/html; charset=utf-8")
            if path == "/":
                return self.send(200, page(), "text/html; charset=utf-8", cookie=True)
            if path.startswith("/view/"):
                return self.serve_run_file(path[len("/view/"):])
            if not path.startswith("/api/"):
                return self.send(404, b"not found", "text/plain; charset=utf-8")
            try:
                return self.api_get(path[len("/api/"):], q)
            except (FileNotFoundError, KeyError) as exc:
                return self.jsend(404, {"error": str(exc).strip("'")})
            except (PermissionError, ValueError) as exc:
                return self.jsend(400, {"error": str(exc)})
            except Exception as exc:  # the window shows it rather than hanging
                return self.jsend(500, {"error": f"{type(exc).__name__}: {exc}"})

        def api_get(self, route, q):
            state = load_state()
            if route == "info":
                info = project.info()
                info["token_header"] = "X-PlasBench-Token"
                return self.jsend(200, info)
            if route == "schema":
                return self.jsend(200, ui_schema.schema())
            if route == "env":
                return self.jsend(200, {"checks": project.env_checks()})
            if route == "tools":
                return self.jsend(200, {"tools": project.tools()})
            if route == "settings":
                return self.jsend(200, {"settings": project.settings(), "local_env": str(project.local_env_path())})
            if route == "cohorts":
                return self.jsend(200, {"cohorts": project.cohorts()})
            if route == "runs":
                return self.jsend(200, {"runs": project.runs(state.get("runs", []))})
            if route == "browse":
                return self.jsend(200, browse(q.get("path", ""), q.get("files") == "1"))
            if route == "docs":
                return self.jsend(200, {"docs": project.docs()})
            if route == "doc":
                name = q.get("name", "")
                allowed = {d["name"] for d in project.docs()}
                if name not in allowed:
                    raise FileNotFoundError(name)
                return self.jsend(200, {"name": name, "text": (project.root / name).read_text(encoding="utf-8", errors="replace")})
            if route == "jobs":
                return self.jsend(200, {"jobs": jobs.list()})
            if route.startswith("jobs/"):
                return self.jsend(200, jobs.get(route[len("jobs/"):], int(q.get("offset", 0))))
            if route == "usertools":
                ut = project.user_tools()
                tools = ut.discover()
                return self.jsend(200, {"tools": [{"name": n, "display": t.display_name, "task": t.task, "track": t.track,
                                                   "mode": t.get("run", "mode"), "format": t.get("output", "format"),
                                                   "install": t.get("install", "method", "none"), "path": str(t.path)}
                                                  for n, t in sorted(tools.items())],
                                        "search_path": [str(p) for p in ut.search_path()],
                                        "placeholders": ut.PLACEHOLDERS, "formats": ut.FORMATS, "tasks": ut.TASKS,
                                        "tracks": ut.TRACKS, "install_methods": ut.INSTALL_METHODS, "schema": {k: sorted(v) for k, v in ut.SCHEMA.items()}})
            if route == "usertools/get":
                ut = project.user_tools()
                tool = ut.discover().get(q.get("name", ""))
                if not tool:
                    raise FileNotFoundError(q.get("name", ""))
                return self.jsend(200, {"name": tool.name, "text": tool.path.read_text(encoding="utf-8"), "path": str(tool.path)})
            raise FileNotFoundError(f"no such API: {route}")

        def serve_run_file(self, rest):
            """/view/<index>/<relative path>: a file inside one of the run folders listed on the Runs page (reports
            link to their own downloads by relative path, so the whole folder is served, read-only)."""
            idx, _, rel = rest.partition("/")
            runs = project.runs(load_state().get("runs", []))
            try:
                base = Path(runs[int(idx)]["path"]).resolve()
            except (ValueError, IndexError):
                return self.send(404, b"no such run", "text/plain; charset=utf-8")
            target = (base / rel).resolve()
            if base not in target.parents and target != base or not target.is_file():
                return self.send(404, b"not found", "text/plain; charset=utf-8")
            ctype = SERVABLE.get(target.suffix.lower())
            if not ctype:
                return self.send(415, b"this file type is not shown in the window", "text/plain; charset=utf-8")
            return self.send(200, target.read_bytes(), ctype, extra={"report": True})

        # ---------------------------------------------------------------- POST
        def do_POST(self):
            if not self.host_ok() or not self.same_origin():
                return self.jsend(403, {"error": "request refused (not from this window)"})
            if not self.token_ok():
                return self.jsend(403, {"error": "missing or wrong session token"})
            route = unquote(urlparse(self.path).path)[len("/api/"):]
            try:
                data = self.body()
                return self.api_post(route, data)
            except (FileNotFoundError, KeyError) as exc:
                return self.jsend(404, {"error": str(exc).strip("'")})
            except (PermissionError, ValueError) as exc:
                return self.jsend(400, {"error": str(exc)})
            except Exception as exc:
                return self.jsend(500, {"error": f"{type(exc).__name__}: {exc}"})

        def api_post(self, route, data):
            if route == "jobs":
                argv = data.get("argv")
                if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
                    raise ValueError("argv must be a non-empty list of strings")
                return self.jsend(200, jobs.start(argv, data.get("label", ""), data.get("env") or None))
            if route.startswith("jobs/") and route.endswith("/input"):
                text = data.get("text", "")
                if not isinstance(text, str):
                    raise ValueError("text must be a string")
                return self.jsend(200, jobs.answer(route[len("jobs/"):-len("/input")], text, bool(data.get("secret"))))
            if route.startswith("jobs/") and route.endswith("/cancel"):
                return self.jsend(200, jobs.cancel(route[len("jobs/"):-len("/cancel")]))
            if route.startswith("jobs/") and route.endswith("/delete"):
                jobs.delete(route[len("jobs/"):-len("/delete")])
                return self.jsend(200, {"ok": True})
            if route == "validate":
                ok, message = ui_schema.validate_argv(data.get("argv") or [])
                return self.jsend(200, {"ok": ok, "message": message})
            if route == "settings":
                changes = data.get("changes") or {}
                if not isinstance(changes, dict):
                    raise ValueError("changes must be an object")
                return self.jsend(200, {"local": project.save_local_env(changes)})
            if route == "runs/add":
                folder = Path(data.get("path", "")).expanduser()
                if not folder.is_dir():
                    raise FileNotFoundError(f"{folder} is not a folder")
                state = load_state()
                state["runs"] = sorted(set(state.get("runs", [])) | {str(folder.resolve())})
                save_state(state)
                return self.jsend(200, {"runs": project.runs(state["runs"])})
            if route == "runs/forget":
                state = load_state()
                state["runs"] = [r for r in state.get("runs", []) if r != data.get("path")]
                save_state(state)
                return self.jsend(200, {"ok": True})
            if route == "usertools/validate":
                return self.jsend(200, self.validate_manifest(data.get("text", "")))
            if route == "usertools/save":
                return self.jsend(200, self.save_manifest(data.get("text", ""), bool(data.get("overwrite"))))
            if route == "reveal":
                target = Path(data.get("path", ""))
                if not target.exists():
                    raise FileNotFoundError(str(target))
                if os.name == "nt":
                    subprocess.Popen(["explorer", "/select,", str(target)] if target.is_file() else ["explorer", str(target)])
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", "-R", str(target)])
                else:
                    subprocess.Popen(["xdg-open", str(target if target.is_dir() else target.parent)])
                return self.jsend(200, {"ok": True})
            raise FileNotFoundError(f"no such API: {route}")

        def validate_manifest(self, text):
            import tempfile
            ut = project.user_tools()
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "plasbench-tool.ini"
                path.write_text(text, encoding="utf-8")
                try:
                    tool = ut.UserTool(path)
                except ut.ManifestError as exc:
                    problems = [l.strip()[2:] for l in str(exc).splitlines()[1:] if l.strip().startswith("- ")] or [str(exc)]
                    return {"ok": False, "problems": problems}
                warnings = []
                if tool.name in ut.builtin_tools():
                    return {"ok": False, "problems": [f"'{tool.name}' is a built-in PlasBench tool; choose another name"]}
                for key in ("script",):
                    if tool.get("install", key) and not Path(tool.resolve(tool.get("install", key))).is_file():
                        warnings.append(f"[install] {key} = {tool.get('install', key)} must be saved beside the manifest")
                return {"ok": True, "problems": [], "warnings": warnings, "row": tool.capability_row(),
                        "plan": tool.install_plan()}

        def save_manifest(self, text, overwrite):
            ut = project.user_tools()
            check = self.validate_manifest(text)
            # A script-installed tool or a custom adapter needs its file beside the manifest; saving the manifest
            # first is how the user gets the folder to put it in, so those two problems do not block saving.
            blocking = [p for p in check.get("problems", []) if "needs script" not in p and "needs adapter" not in p]
            if blocking:
                return {"ok": False, "problems": blocking}
            import configparser
            parser = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=("#", ";"))
            parser.read_string(text)
            name = parser.get("tool", "name").strip()
            folder = Path.home() / ".plasbench" / "tools" / name
            target = folder / ut.MANIFEST
            if target.exists() and not overwrite:
                return {"ok": False, "exists": True, "problems": [f"{target} already exists"], "path": str(target)}
            folder.mkdir(parents=True, exist_ok=True)
            target.write_text(text.replace("\r\n", "\n"), encoding="utf-8", newline="\n")
            return {"ok": True, "path": str(target), "folder": str(folder)}

    return Handler


def serve(root: Path, host: str = "127.0.0.1", port: int = 8770, open_browser: bool = True):
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("ERROR: the PlasBench window only listens on this computer (127.0.0.1).")
    project = Project(root)
    jobs = Jobs(project)
    handler = make_handler(project, jobs)
    server = None
    for candidate in range(port, port + 20):
        try:
            server = ThreadingHTTPServer((host, candidate), handler)
            break
        except OSError:
            continue
    if server is None:
        raise SystemExit(f"ERROR: no free port between {port} and {port + 19}")
    url = f"http://127.0.0.1:{server.server_address[1]}/?t={quote(TOKEN)}"
    print(f"PlasBench {__version__} window: {url}", flush=True)
    print("Keep this terminal open while you use the window; press Ctrl+C here to close it.", flush=True)
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nClosed the PlasBench window.")
    finally:
        server.server_close()
