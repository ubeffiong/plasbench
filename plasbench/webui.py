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

import contextlib
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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from . import __version__
from . import server_state, windowlife
from . import cohort_info, fsutil, ghops, ghsignin, jobrunner, jobs_labels, loadcache, netgate, runfolders, runprogress, ui_help, ui_schema
from .gitops import GitError   # a refused git action is the user's error (400), not the server's
from .terminal import Terminal, TerminalError
from .sessionlog import SessionLog, describe as describe_event

TOKEN = secrets.token_urlsafe(24)
PAGE_FILE = Path(__file__).resolve().parent / "data" / "ui.html"
WINDOWS = windowlife.Registry()   # window stability: the windows that pinged recently
REOPEN_LIMIT = windowlife.RateLimit()   # /api/reopen helps at most once per 10 s
PAGE_SEEN = {"t": 0.0}   # when a window last loaded the page: the launcher uses it to check that clicking the icon really produced a window
LOGO_FILE = Path(__file__).resolve().parent / "data" / "logo.svg"
_SESSION: dict = {}


def session_log() -> SessionLog:
    """This start's session log (one per process; follows UI_HOME, which the tests point elsewhere)."""
    log = _SESSION.get("log")
    if log is None or log.path.parent != UI_HOME:
        log = _SESSION["log"] = SessionLog(UI_HOME / "sessions.jsonl")
    return log
UI_HOME = Path(os.environ.get("PLASBENCH_UI_HOME", Path.home() / ".plasbench" / "ui"))
SERVABLE = {".html": "text/html; charset=utf-8", ".pdf": "application/pdf", ".tsv": "text/tab-separated-values; charset=utf-8",
            ".json": "application/json; charset=utf-8", ".txt": "text/plain; charset=utf-8", ".md": "text/plain; charset=utf-8",
            ".log": "text/plain; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png", ".csv": "text/csv; charset=utf-8",
            ".fasta": "text/plain; charset=utf-8", ".fa": "text/plain; charset=utf-8", ".gz": "application/gzip",
            ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".zip": "application/zip"}
MAX_LOG_CHUNK = 256 * 1024
REPORT_CSP = ("default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'; "
              "font-src data:; form-action 'none'; frame-ancestors 'self'; "
              "sandbox allow-scripts allow-downloads allow-popups allow-popups-to-escape-sandbox")


_signin = [None]
_signin_lock = threading.Lock()


def github_cmd():
    """The GitHub CLI as an argv prefix (replaceable in tests), or None when gh is not installed."""
    from . import gitops
    path = gitops.find_gh()
    return [path] if path else None


def signin() -> "ghsignin.SignIn":
    """The one device-flow sign-in manager of this server (created when first used)."""
    with _signin_lock:
        if _signin[0] is None:
            _signin[0] = ghsignin.SignIn(github_cmd() or ["gh"])
        elif _signin[0].gh_cmd != (github_cmd() or ["gh"]):
            _signin[0].gh_cmd = github_cmd() or ["gh"]
        return _signin[0]


def reads_present(argv, env) -> bool:
    """Are the reads and a reference of every sample of this run's sheet already in the data folder? (Then `plasbench run` needs no download and may start offline.)"""
    root = _PROJECT_ROOT[0]
    if root is None:
        return False
    flag = lambda *names: next((argv[i + 1] for i, a in enumerate(argv[:-1]) if a in names), None)    # noqa: E731
    sheet = flag("-s", "--samples")
    cohort = flag("-c", "--cohort")
    path = Path(sheet) if sheet else (root / "cohorts" / f"{cohort}.tsv" if cohort else Path(os.environ.get("SAMPLE_SHEET") or root / "config" / "accessions.tsv"))
    if not path.is_absolute():
        path = root / path
    header, rows = None, []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("#") or not line.strip():
                continue
            cells = line.rstrip("\r\n").split("\t")
            if header is None:
                header = cells
            else:
                rows.append(dict(zip(header, cells)))
    if not rows or "sample_id" not in (header or []):
        return False
    from .cli import configured_data_dir
    data_dir = Path(flag("-d", "--data-dir")) if flag("-d", "--data-dir") else configured_data_dir(root)
    for row in rows:
        folder = data_dir / row["sample_id"]
        if not folder.is_dir():
            return False
        names = [p.name.lower() for p in folder.iterdir() if p.is_file() and p.stat().st_size > 0]
        if sum(1 for n in names if ".fastq" in n or n.endswith((".fq", ".fq.gz"))) < 2 or not any(n.endswith((".fna", ".fna.gz", ".fa", ".fasta", ".fa.gz", ".fasta.gz")) for n in names):
            return False
    return True


_PROJECT_ROOT = [None]
RELIABILITY_GROUP = "Reliability and downloads"
# Environment settings the window may pass with a job (Jobs.start): the Settings keys of config/config.sh plus the download and reliability
# names the wizard's "Downloads and reliability" card sets. Anything else (LD_PRELOAD, PATH ...) is refused.
EXTRA_ENV_KEYS = frozenset(["READ_SOURCE", "MAX_RUN_DOWNLOAD_GB", "WARN_RUN_DOWNLOAD_GB", "PREFETCH_FAIL_LIMIT", "TOOL_TIMEOUT_SECONDS",
                            "ALLOW_ALL_TOOLS_FAILED", "NETWORK_RETRIES", "ENA_DOWNLOAD_CONNECTIONS", "RUN_CONSOLE_LOG", "LOG_RETENTION_RUNS"])
ENV_KEY = re.compile(r"[A-Z][A-Z0-9_]*")
ENV_FORBIDDEN = frozenset(["PATH", "PYTHONPATH", "PYTHONHOME", "LD_PRELOAD", "LD_LIBRARY_PATH", "PROJECT_ROOT"])
ENV_VALUE_MAX = 200


# -- the Run status panel: python/run_status.py (written with the logging pipeline) summarises a results folder; the window only asks for it -----------
STATUS_CACHE_SECONDS = 3.0
_status_cache: dict = {}
_status_lock = threading.Lock()


def load_run_status(root):
    """python/run_status.py imported by path, or None when this checkout does not have it."""
    import importlib.util
    path = Path(root) / "python" / "run_status.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("plasbench_run_status", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_status_json(root, results: Path, log_dir: Path, data_dir: Path, loader=None, now=time.monotonic) -> dict:
    """run_status.summarize(results, log, data) as JSON-able data plus a `text` field (render(summary, diagnose=True)). Cached for 3 s per folder. Never raises:
    a failure is {"state": "no-run", "error": reason}."""
    key = str(results)
    with _status_lock:
        hit = _status_cache.get(key)
        if hit and now() - hit[0] < STATUS_CACHE_SECONDS:
            return hit[1]
    try:
        module = (loader or load_run_status)(root)
        if module is None:
            out = {"state": "no-run", "error": "this PlasBench has no python/run_status.py"}
        else:
            out = json.loads(json.dumps(module.summarize(results, log_dir, data_dir), default=str))
            if not isinstance(out, dict):
                out = {"state": "no-run", "error": "run_status returned something that is not a summary"}
            else:
                try:
                    out["text"] = module.render(out, diagnose=True)
                except Exception as exc:  # noqa: BLE001 - the summary is still useful without the text
                    out["text"] = f"(the diagnosis text could not be made: {exc})"
    except Exception as exc:  # noqa: BLE001
        out = {"state": "no-run", "error": f"{type(exc).__name__}: {exc}"}
    out.setdefault("state", "no-run")
    out["results"], out["log_dir"] = key, str(log_dir)
    with _status_lock:
        _status_cache[key] = (now(), out)
    return out


def _sheet_header(path: Path) -> list:
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.strip() and not line.startswith("#"):
                return line.rstrip("\r\n").split("\t")
    return []


# --------------------------------------------------------------------------------------------- project facts
# -- Add your own tool: help text, a tool's summary, and the small-file upload ----------------------------------------------------------------------
UPLOAD_MAX_BYTES = 5 * 1024 * 1024      # scripts and adapters only: a large tool binary is located on this computer or downloaded, never uploaded
UPLOAD_BODY_MAX = 8 * 2**20             # the request may be a little larger than the file (JSON escaping), so the size message below is the one the user sees
_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
_UPLOAD_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,99}$")


def user_tool_summary(tool):
    """{"tasks", "install_source", "install_mode", "sha256"} of one user tool for the tool lists: every task it declares, where it comes from
    (installed, conda, pip, script, url, local), the url/local mode and the pinned checksum. Read from the manifest's own source_summary."""
    src = tool.source_summary()
    method = src.get("method") or "none"
    return {"tasks": list(tool.tasks), "install_source": {"none": "installed"}.get(method, method), "install_mode": src.get("mode", ""),
            "sha256": src.get("sha256", "") if method in ("url", "local") else ""}


def store_tool_upload(name, filename, text, home=None):
    """Write `text` as <home>/.plasbench/tools/<name>/<filename> and return {"ok", "path" (the relative path for the manifest), "folder", "bytes"}.
    Refused (ValueError): a tool name that is not a manifest name, a file name that is a path (separator, drive colon, '..', leading dot) or the manifest itself,
    text that is not text, or more than UPLOAD_MAX_BYTES. Line endings are stored as LF so a script runs under bash."""
    if not isinstance(name, str) or not _TOOL_NAME.match(name):
        raise ValueError("give the tool a name first (lower-case letters, digits and _, starting with a letter): the name is its folder")
    if (not isinstance(filename, str) or not filename or any(c in filename for c in "/\\:\x00") or ".." in filename
            or filename.startswith(".") or not _UPLOAD_NAME.match(filename)):
        raise ValueError("the file name must be a plain name: no folders, no '..', no leading dot")
    if filename.lower() == "plasbench-tool.ini":
        raise ValueError("plasbench-tool.ini is the manifest; use Save for that")
    if not isinstance(text, str) or "\x00" in text:
        raise ValueError("only text files (scripts and adapters) can be uploaded; locate a binary on this computer instead")
    raw = text.replace("\r\n", "\n").encode("utf-8")
    if len(raw) > UPLOAD_MAX_BYTES:
        raise ValueError(f"the file is {len(raw) / 2**20:.1f} MB; uploads are limited to {UPLOAD_MAX_BYTES // 2**20} MB. Locate a large file on this computer instead")
    folder = (Path(home) if home else Path.home()) / ".plasbench" / "tools" / name
    target = (folder / filename).resolve()
    if folder.resolve() not in target.parents:
        raise ValueError("the file name must be a plain name")
    folder.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return {"ok": True, "path": filename, "folder": str(folder), "bytes": len(raw)}


class Project:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        _PROJECT_ROOT[0] = self.root
        self.python_dir = self.root / "python"
        if str(self.python_dir) not in sys.path:
            sys.path.insert(0, str(self.python_dir))

    # -- settings: config/config.sh (defaults) + config/local.env (this computer) -----------------------------
    def settings(self) -> list[dict]:
        """Every `export KEY=...` in config/config.sh with its default, comment and section, plus the override in
        config/local.env and the value in this process's environment."""
        cfg = self.root / "config" / "config.sh"
        base = loadcache.memo(("settings", str(cfg)), loadcache.sig(cfg), lambda: self._parse_config_sh(cfg))
        local = self.local_env()
        rows = []
        for row in base:
            row = dict(row)
            row["override"], row["env"] = local.get(row["key"]), os.environ.get(row["key"])
            rows.append(row)
        return rows

    def _parse_config_sh(self, cfg) -> list[dict]:
        """The part of settings() that depends only on config/config.sh (override and env are added fresh on every call)."""
        text = cfg.read_text(encoding="utf-8", errors="replace")
        local = {}
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

    def settings_resolved(self) -> list[dict]:
        """settings(), each location default also resolved to the path it means on this computer."""
        rows = self.settings()
        ranges = self.setting_ranges().load(self.root)
        carried, prev_group = "", None
        for row in rows:
            row.update(self.resolve_setting_default(row))
            if row.get("group") != prev_group:
                carried, prev_group = "", row.get("group")
            row["tooltip"] = ui_help.setting_tooltip(row, carried)
            if row["key"] in ranges:     # the range the code accepts, beside the setting and in its tooltip (config/setting_ranges.tsv)
                row["range"] = self.setting_ranges().public(ranges[row["key"]], row.get("default"))
                row["tooltip"]["summary"] = f"{row['tooltip']['summary']} Range: {row['range']['label']} {ranges[row['key']]['note']}"
            if row.get("comment"):
                carried = row["comment"]
            if row["key"] in ui_help.RELIABILITY_KEYS:
                row["group"] = RELIABILITY_GROUP
        return rows

    def local_env_path(self) -> Path:
        return Path(os.environ.get("PLASBENCH_LOCAL_SETTINGS", self.root / "config" / "local.env"))

    def local_env(self) -> dict:
        path = self.local_env_path()
        return dict(loadcache.memo(("local_env", str(path)), loadcache.sig(path), lambda: self._read_local_env(path)))

    @staticmethod
    def _read_local_env(path) -> dict:
        values = {}
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
        # A numeric Scoring-decision setting outside the range the code accepts is refused with a plain sentence (config/setting_ranges.tsv). Clearing, and a value
        # equal to the one already saved, always pass, so an existing saved value never blocks a save.
        self.setting_ranges().validate_changes(changes, self.local_env(), self.root)
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
        with open(path, "w", encoding="utf-8", newline="\n") as _fh:
            _fh.write("\n".join(kept) + "\n")
        try:
            os.chmod(path, 0o600)     # holds the NCBI key: owner only (a no-op on Windows, where the profile folder's ACL applies)
        except OSError:
            pass
        return self.local_env()

    # -- your own isolates: sheet template, folder scan, staging, quick check (python/intake.py) -------------------------
    def intake(self):
        import importlib
        python_dir = str(self.root / "python")
        if python_dir not in sys.path:
            sys.path.insert(0, python_dir)
        return importlib.import_module("intake")

    def intake_defaults(self) -> dict:
        from .cli import configured_data_dir
        return {"data_dir": str(configured_data_dir(self.root)), "samples": str(self.root / "config" / "local.tsv"),
                "templates": [{"kind": k, "file": v[0], "label": v[1]} for k, v in self.intake().TEMPLATES.items()]}

    def intake_paths(self, data) -> tuple:
        d = self.intake_defaults()
        return Path(str(data.get("data_dir") or d["data_dir"])).expanduser(), Path(str(data.get("samples") or d["samples"])).expanduser()

    def setting_ranges(self):
        import importlib
        python_dir = str(self.root / "python")
        if python_dir not in sys.path:
            sys.path.insert(0, python_dir)
        return importlib.import_module("setting_ranges")

    # -- pre-registered scoring decisions (python/prereg_admin.py) --------------------------------------------------
    def prereg_admin(self):
        import importlib
        python_dir = str(self.root / "python")
        if python_dir not in sys.path:
            sys.path.insert(0, python_dir)
        return importlib.import_module("prereg_admin")

    def prereg(self) -> dict:
        """Every decision with its plain-language text, status, record and (for a setting) the value this computer is actually using, plus the lock state."""
        admin = self.prereg_admin()
        settings = {s["key"]: s for s in self.settings()}
        local = self.local_env()
        ranges = self.setting_ranges().load(self.root)
        rows = []
        for r in admin.load(self.root):
            var = (r.get("config_variable") or "").strip()
            current = None
            if var:
                current = local.get(var)
                if current is None:
                    current = os.environ.get(var)
                if current is None:
                    current = (settings.get(var) or {}).get("default")
            rows.append({k: r[k] for k in ("parameter", "topic", "title", "meaning", "if_changed", "type", "choices", "where", "value", "status", "config_variable", "last_action",
                                           "decided_on", "decided_by", "decision_reason", "note")} | {"current": current,
                         "range": self.setting_ranges().public(ranges[var], r["value"]) if var in ranges else None,
                         "departs": bool(var and current is not None and str(current).strip() != str(r["value"]).strip() and not admin.freeze_prereg_equal(r["value"], current))})
        return {"rows": rows, "status": admin.status(self.root), "topics": list(dict.fromkeys(r["topic"] for r in rows)), "history": admin.history(self.root)[-200:]}

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
    def tools(self, block: bool = True) -> list[dict]:
        """The tool registry. The rows come from the config/*.tsv files and are rebuilt only when one of them changes; `installed` is a PATH probe that is remembered
        (loadcache.which) and refreshed in the background, so this never waits on the PATH once it has been asked once. With block=False a probe that has no answer yet
        gives installed=None and the row is marked checking=True (the page shows 'checking...' and asks again)."""
        cfg = self.root / "config"
        files = [cfg / "tool_capabilities.tsv", cfg / "tool_installers.tsv", cfg / "tool_database_releases.tsv", cfg / "config.sh", self.local_env_path()]
        static = loadcache.memo(("tools", str(self.root)), loadcache.sig(*files), self._tools_static)
        try:
            import source_install
            source_entries = source_install.load(self.root / "config" / "source_tools.json")["profiles"]
        except Exception:  # noqa: BLE001 - the Tools page still lists everything without it
            source_entries = {}
        out = []
        for base in static:
            row = dict(base)
            exe = row.get("executable")
            if exe:
                found, ready = loadcache.which(exe, block)
                row["installed"] = bool(found) if ready else None
                row["checking"] = not ready
            # ==INSTALL-INFO-BEGIN== how this tool is installed (python/source_install.py, config/source_tools.json) and which revision is installed
            entry = source_entries.get(row.get("profile") or "")
            if entry:
                row["install"] = self._install_info(entry, exe, row.get("installed"))
            # ==INSTALL-INFO-END==
            out.append(row)
        return out

    def _install_info(self, entry: dict, exe: str, installed) -> dict:
        """What the Tools page shows for a source-built or verified-manual tool: the pin, the size and licence, the installed revision (read from the wrapper PlasBench wrote,
        never by running the tool) and whether it is the pinned one."""
        info = {"kind": entry["mode"], "ref": entry["ref"], "pinned": entry["commit"], "repo": entry["repo"], "licence": entry["licence"], "download_mb": entry["download_mb"],
                "disk_gb": entry["disk_gb"], "minutes": entry["minutes"], "inputs": entry.get("inputs", []), "revision": "", "current": None}
        if entry["mode"] == "manual":
            info["reason"] = entry["manual"]["reason"]
        elif installed:
            try:
                import source_install
                found = source_install.command_info(exe)
            except Exception:  # noqa: BLE001
                found = None
            if found:
                info.update(revision=found["commit"], installed_ref=found.get("ref", ""), installed_at=found.get("installed_at", ""), current=found["commit"] == entry["commit"])
        return info

    def _tools_static(self) -> list[dict]:
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
        mine = {}
        try:   # your own tools: every task, where the tool comes from, and whether a download or copy is pinned by checksum
            for n, t in self.user_tools().discover().items():
                mine[n] = user_tool_summary(t)
        except Exception:  # noqa: BLE001 - the Tools page still lists everything without it
            mine = {}
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
                "task": row.get("evaluation_task") or ("binning_reconstruction" if row.get("binning_capable") == "yes" else "classification"),
                "track": row.get("analysis_track"), "method_class": row.get("method_class"),
                "input": row.get("primary_input"), "description": row.get("description", ""),
                "profile": inst.get("profile", ""), "automated": inst.get("automated", ""),
                "database_mode": inst.get("database_mode", ""), "verify": inst.get("verify_command", ""),
                "notes": inst.get("notes", ""), "installed": None,
                "executable": exe, "run_flag": flag if flag_row else None, "enabled": enabled == "1" if enabled is not None else None,
                "database": (dbrel.get(name) or {}).get("database", ""),
                "database_release": (dbrel.get(name) or {}).get("database_release_date", ""),
            })
            if name in mine:
                out[-1].update(mine[name])
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
            add("bash", "Bash (runs the pipeline stages)", bool(bash and loadcache.which_path(bash) or Path(str(bash)).exists()), str(bash),
                "" if os.name != "nt" else "install-git")
        except Exception as exc:
            add("bash", "Bash (runs the pipeline stages)", False, str(exc), "install-git" if os.name == "nt" else "")
        from . import platform_info
        solver, solver_exe = platform_info.conda_solver()
        add("conda", "Conda, mamba or micromamba (installs the tools)", solver, solver_exe or "not found",
            "" if solver else "install-conda")
        prefix = platform_info.env_prefix()
        add("plasbench_env", "The plasbench conda environment (holds the tools)", prefix, str(prefix) if prefix else "not created yet",
            "" if prefix else "install-tools core")
        from .terminal import git_path_dirs
        git = loadcache.which_path("git") or shutil.which("git", path=os.pathsep.join(git_path_dirs()))
        add("git", "Git for Windows with Git Bash (version control of your runs, terminal)" if os.name == "nt"
            else "Git (version control of your runs, upgrades)", git, git or "not found", "install-git", optional=True)
        core = [("datasets", "NCBI datasets"), ("prefetch", "SRA toolkit: prefetch"), ("fasterq-dump", "SRA toolkit: fasterq-dump"),
                ("fastp", "fastp (read trimming)"), ("minimap2", "minimap2 (scoring alignments)")]
        for exe, label in core:
            path = loadcache.which_path(exe)
            add(exe, label, path, path or "not on PATH", "" if path else "install-tools core", group="Core tools")
        for exe, label, profile in (("spades.py", "SPAdes (short-read assembly)", "assembly"), ("mash", "Mash (clonal groups)", "utilities")):
            path = loadcache.which_path(exe)
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

    # Run-form fields that name a tool database, with the config variable that overrides
    # it and its path under the machine-wide store (config/config.sh, plasbench_db_path).
    DB_FIELDS = (("platon_db", "PLATON_DB", "platon/db"), ("genomad_db", "GENOMAD_DB", "genomad"),
                 ("plasme_db", "PLASME_DB", "plasme"), ("plasgraph2_model_dir", "PLASGRAPH2_MODEL_DIR", None))

    def databases(self) -> dict:
        """Where a run will find each tool database when its form field is left empty.

        Mirrors config/config.sh: an explicit setting wins; otherwise the machine-wide store
        (PLASBENCH_DB_DIR, default ~/.plasbench/databases), except that a copy already under
        DATA_DIR/db is used while the store has none. The window shows this so a database
        that is already installed is visibly reused instead of looking like a blank to fill in.
        """
        local = self.local_env()
        out = {}
        for dest, var, rel in self.DB_FIELDS:
            explicit = os.environ.get(var) or local.get(var)
            if explicit:
                path, source = Path(os.path.expanduser(explicit)), "setting"
            elif rel is None:
                out[dest] = {"path": "", "found": False, "source": "none"}
                continue
            else:
                path, source = self.db_location(rel)
            out[dest] = {"path": str(path), "found": self.installed(path), "source": source}
        return out

    def db_location(self, rel: str) -> tuple:
        """config.sh's plasbench_db_path: the machine-wide store, unless only DATA_DIR/db has it."""
        local = self.local_env()
        store = Path(os.environ.get("PLASBENCH_DB_DIR") or local.get("PLASBENCH_DB_DIR") or Path.home() / ".plasbench" / "databases")
        data = self.path_setting("DATA_DIR", "data")
        if (data / "db" / rel).exists() and not (store / rel).exists():
            return data / "db" / rel, "project"
        return store / rel, "store"

    @staticmethod
    def installed(path: Path) -> bool:
        """A database folder that exists and is not empty, or a database file that is not empty."""
        try:
            return (path.is_dir() and any(path.iterdir())) or (path.is_file() and path.stat().st_size > 0)
        except OSError:
            return False

    def resolve_setting_default(self, row: dict) -> dict:
        """What a setting left at its default actually points to on this computer.

        config.sh writes several defaults as shell code (``$(plasbench_db_path platon/db)``,
        ``${PLASBENCH_DATA_DIR:-$PROJECT_ROOT/data}``); shown raw, nobody can tell where a database
        is or whether it is installed. Returns {"resolved": path, "found": bool or None}.
        """
        key, default = row["key"], row["default"]
        m = re.fullmatch(r"\$\(plasbench_db_path ([^)]+)\)", default.strip())
        if m:
            path, _ = self.db_location(m.group(1).strip())
            return {"resolved": str(path), "found": self.installed(path)}
        if key == "DATA_DIR":
            return {"resolved": str(self.path_setting("DATA_DIR", "data")), "found": None}
        if key == "PLASBENCH_DB_DIR":
            return {"resolved": str(Path(default.replace("$HOME", str(Path.home()))).expanduser()), "found": None}
        if re.fullmatch(r"\$PROJECT_ROOT/[\w./-]+", default):
            return {"resolved": str(self.root / default[len("$PROJECT_ROOT/"):]), "found": None}
        return {}

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
                "local_env": str(self.local_env_path()), "home": str(Path.home()), "sep": os.sep,
                "databases": self.databases()}

    # -- runs and reports ---------------------------------------------------------------------------------------
    def studies(self) -> list[dict]:
        """studies.list_studies, shared for a moment: the page asks for it from several routes at once (runs, run-sessions, workspace). Anything the window changes clears it."""
        from . import studies
        return [dict(s) for s in loadcache.ttl(("studies", str(self.root)), 1.5, lambda: studies.list_studies(self.root))]

    def runs(self, extra: list[str]) -> list[dict]:
        try:
            from plasbench_common import display_tool_name
        except Exception:
            display_tool_name = lambda t: t  # noqa: E731
        candidates = {self.root / "results", self.root / "results_demo"}
        candidates.update(p for p in self.root.glob("results*") if p.is_dir())
        candidates.update(Path(e) for e in extra)
        from . import studies
        candidates.update(Path(st["results"]) for st in self.studies())
        registered = {loadcache.realpath(e) for e in extra}   # folders added by hand: these (and only these) can be forgotten
        rows = []
        for folder in sorted(candidates):
            report, leaderboard = folder / "benchmark.report.html", folder / "benchmark.leaderboard.tsv"
            # one fingerprint pass answers every "is it there" question (None = missing): the cost on a slow drive is the number of stat calls, not the parsing
            fp = loadcache.sig(report, leaderboard, folder / "tool_status.tsv", folder.parent / "study.json", folder / "benchmark.report.pdf", folder / "benchmark.report.summary.pdf")
            if fp[0] is None and fp[1] is None:
                continue
            parts = loadcache.memo(("run", str(folder)), fp[:4], lambda f=folder: self._run_row(f, display_tool_name))
            rows.append(dict(parts, registered=loadcache.realpath(folder) in registered, pdf=fp[4] is not None, summary_pdf=fp[5] is not None))
        rows.sort(key=lambda r: -r["modified"])
        return rows

    def _run_row(self, folder: Path, display_tool_name) -> dict:
        """One results folder's row: its leaderboard leaders, tool and sample counts. Remembered by runs() until the folder's report, leaderboard or tool_status.tsv changes."""
        import csv
        report = folder / "benchmark.report.html"
        leaderboard = folder / "benchmark.leaderboard.tsv"
        leaders, tools = [], set()
        if leaderboard.is_file():
            with leaderboard.open(encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle, delimiter="	"):
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
                rows_ = list(csv.DictReader(handle, delimiter="	"))
            samples = len({r.get("sample") for r in rows_})
            failed = sum(1 for r in rows_ if r.get("status") in ("failed", "infrastructure_failure"))
        stamp = max((p.stat().st_mtime for p in (report, leaderboard) if p.exists()), default=0)
        # a study's results live in <study>/results: show the study's name
        is_study = folder.name == "results" and (folder.parent / "study.json").is_file()
        return {"path": str(folder), "name": folder.parent.name if is_study else folder.name, "study": is_study,
                "study_dir": str(folder.parent) if is_study else None, "report": report.is_file(),
                "modified": stamp, "tools": len(tools - {None}), "samples": samples, "failed": failed,
                "leaders": leaders, "leaderboard": leaderboard.is_file()}

    def cohorts(self) -> list[dict]:
        out = []
        for path in sorted((self.root / "cohorts").glob("*.tsv")):
            name = path.stem
            sibs = [path.parent / f"{name}.lock.json", path.parent / f"{name}.selection.json", path.parent / f"{name}.publication.json"]
            out.append(dict(loadcache.memo(("cohort", str(path)), loadcache.sig(path, *sibs), lambda p=path: self._cohort_row(p))))
        return out

    @staticmethod
    def _cohort_row(path: Path) -> dict:
        """One cohort's row. Counting its rows reads the whole sheet, so it is remembered until the sheet or its lock/selection/publication file changes."""
        try:
            n = sum(1 for line in path.open(encoding="utf-8") if line.strip() and not line.startswith("#")) - 1
        except OSError:
            n = 0
        name = path.stem
        try:
            header = _sheet_header(path)
        except OSError:
            header = []
        return {"name": name, "path": str(path), "rows": max(n, 0), "ledger": cohort_info.is_ledger(header), "locked": (path.parent / f"{name}.lock.json").is_file(),
                "metagenomic": name.startswith("metagenomics"),
                "selection": (path.parent / f"{name}.selection.json").is_file(),
                "publication": (path.parent / f"{name}.publication.json").is_file()}

    def docs(self) -> list[dict]:
        out = []
        for path in [self.root / "README.md"] + sorted((self.root / "docs").glob("*.md")) + sorted((self.root / "adapters").glob("*.md")):
            if path.is_file():
                title, size = loadcache.memo(("doc", str(path)), loadcache.sig(path), lambda p=path: self._doc_title(p))
                out.append({"name": str(path.relative_to(self.root)).replace("\\", "/"), "title": title, "size": size})
        return out

    @staticmethod
    def _doc_title(path: Path) -> tuple:
        first = next((l.lstrip("# ").strip() for l in path.read_text(encoding="utf-8", errors="replace").splitlines() if l.startswith("#")), path.stem)
        return first, path.stat().st_size


# --------------------------------------------------------------------------------------------- jobs
SESSION_COMMANDS = ("run", "demo", "report", "report-pdf")   # the commands that make a benchmark run session (everything else stays on the Jobs page)
RESUMABLE_STATES = ("failed", "interrupted", "cancelled")
CONSENT_EXIT = 21         # install-tools: a source-built tool waits for --yes (plasbench/exitcodes.py); shown as "Consent needed", not Failed
MANUAL_STEP_EXIT = 20   # install-tools: the profile is installed by hand (plasbench/exitcodes.py); shown as "Manual step needed", not Failed


def is_docker_setup(argv) -> bool:
    """True for `plasbench install-tools docker ...`: the one install whose exit 20 means "steps handed to you" rather than "this tool cannot be installed automatically"."""
    argv = list(argv or [])
    return len(argv) >= 2 and argv[0] == "install-tools" and argv[1] == "docker"


KEEP_JOBS = 500                       # finished (`done`) jobs kept; a failed, interrupted or cancelled job is kept until deleted or past the retention
JOB_RETENTION_DAYS_DEFAULT = 180
LOCK_STALE_SECONDS = 15
STARTUP_GRACE = 60   # seconds a freshly started runner may take to write its first heartbeat
INTERRUPTED_WATCH_SECONDS = 6 * 3600   # how long an "interrupted" run is still watched for its heartbeat to come back (a laptop that slept) before the watcher gives up
SERVER_STARTED = time.time()


def _is_own_process(pid) -> bool:
    """True when `pid` is this process or the leader of this process's group (a signal to it would stop the window itself)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid == os.getpid():
        return True
    return hasattr(os, "getpgrp") and pid == os.getpgrp()


class Jobs:
    """Each job is one `plasbench` command, started through the detached runner (plasbench/jobrunner.py), so it outlives this server.

    Its output goes to a log file the page tails; its pid, heartbeat and exit code are small files beside the log. When this server starts again it finds the runs that are still going
    (fresh heartbeat), picks up the ones that ended while it was away (an exit file), and only calls a run `interrupted` when the runner is gone without having recorded an exit."""

    def __init__(self, project: Project):
        self.project = project
        self.dir = UI_HOME / "jobs"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self._save_lock = threading.RLock()
        self._meta_sig: dict = {}
        self._dir_stamp = None
        self.jobs: dict[str, dict] = {}
        self.watchers: set[str] = set()
        self.deleted: set[str] = set()
        self._progress_cache: dict = {}
        self._line_cache: dict = {}
        tomb = self._tombstones()
        for job in self._read_index():
            if isinstance(job, dict) and "id" in job and job["id"] not in tomb:
                self.jobs[job["id"]] = job
        self._restore_from_meta(tomb)
        for job in list(self.jobs.values()):
            if job.get("state") == "interrupted" and jobrunner.is_alive(str(self.dir), job["id"]):
                job.update(state="running", ended=None, exit=None)   # an earlier window called it lost before its runner had written a heartbeat; it is plainly going
            if job.get("state") in ("running", "cancelling"):
                self._reconcile(job)
        self._save()

    # -- persistence -------------------------------------------------------------------------------------------
    def _read_index(self) -> list:
        """The saved job list. The file is replaced atomically, but a reader on another filesystem or an older writer could still meet a half-written one: retry briefly before giving up."""
        path = self.dir / "jobs.json"
        for attempt in range(40):
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return []
            except (OSError, ValueError):
                time.sleep(0.05)
        return []

    @contextlib.contextmanager
    def _index_lock(self, timeout: float = 30.0):
        """An exclusive lock around read-merge-write of the shared job list, shared by every thread and every window on this folder: a lock file created with O_EXCL (works on
        Windows, POSIX and WSL). A lock older than LOCK_STALE_SECONDS belongs to a window that died; it is moved aside (an atomic rename, so only one waiter wins) and the wait goes on."""
        path = self.dir / "jobs.lock"
        deadline = time.time() + timeout
        while True:
            try:
                fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                break
            except (FileExistsError, PermissionError):
                try:
                    age = time.time() - os.path.getmtime(path)
                except OSError:
                    continue                      # it was released between the two calls: try again at once
                if age > LOCK_STALE_SECONDS:
                    try:
                        os.replace(path, f"{path}.stale.{os.getpid()}.{threading.get_ident()}")
                        os.unlink(f"{path}.stale.{os.getpid()}.{threading.get_ident()}")
                    except OSError:
                        pass
                    continue
                if time.time() > deadline:
                    raise ValueError("another PlasBench window is saving the job list: try again in a moment")
                time.sleep(0.01)
        try:
            yield
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _tombstones(self) -> set:
        """The ids of jobs the user deleted (in any window): they stay deleted."""
        try:
            return {line.strip() for line in (self.dir / "jobs.deleted").read_text(encoding="utf-8").splitlines() if line.strip()}
        except OSError:
            return set()

    def _meta_path(self, job_id: str) -> Path:
        return self.dir / f"{job_id}.meta.json"

    def _write_meta(self, job: dict):
        """<id>.meta.json beside the log: written at launch and whenever the job changes, so the list can be rebuilt from the folder."""
        text = json.dumps(job, sort_keys=True, indent=1)
        if self._meta_sig.get(job["id"]) == text:
            return
        if job["id"] not in self._meta_sig:   # first look since this window started: a file that already says the same is left alone (start-up used to rewrite every job's file)
            try:
                if self._meta_path(job["id"]).read_text(encoding="utf-8") == text:
                    self._meta_sig[job["id"]] = text
                    return
            except OSError:
                pass
        tmp = self.dir / f"{job['id']}.meta.json.{os.getpid()}.{threading.get_ident()}.tmp"
        tmp.write_text(text, encoding="utf-8")
        for attempt in range(40):
            try:
                os.replace(tmp, self._meta_path(job["id"]))
                break
            except PermissionError:
                if attempt == 39:
                    raise
                time.sleep(0.05)
        self._meta_sig[job["id"]] = text

    def _restore_from_meta(self, tomb: set) -> list:
        """Jobs that have a meta file but are not in memory (the index was lost or is behind, or another window started them) come back, unless the user deleted them."""
        restored = []
        try:
            names = [e.name for e in os.scandir(self.dir) if e.name.endswith(".meta.json")]
        except OSError:
            return restored
        for name in names:
            job_id = name[:-len(".meta.json")]
            if job_id in self.jobs or job_id in tomb:
                continue
            try:
                job = json.loads((self.dir / name).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(job, dict) and job.get("id") == job_id and "started" in job and "state" in job:
                self.jobs[job_id] = job
                restored.append(job)
        return restored

    @staticmethod
    def retention_days() -> float:
        """How long a finished job is kept (PLASBENCH_JOB_RETENTION_DAYS, default 180 days; 0 = for ever). A failed, interrupted or cancelled job is never dropped sooner."""
        try:
            return max(0.0, float(os.environ.get("PLASBENCH_JOB_RETENTION_DAYS", JOB_RETENTION_DAYS_DEFAULT)))
        except ValueError:
            return float(JOB_RETENTION_DAYS_DEFAULT)

    def _prune(self) -> list:
        """Drop jobs past the retention, and `done` jobs beyond the newest KEEP_JOBS. Returns the dropped jobs."""
        now, days = time.time(), self.retention_days()
        ordered = sorted((j for j in self.jobs.values() if j["state"] not in ("running", "cancelling")), key=lambda j: j["started"])
        drop = [j for j in ordered if days > 0 and now - (j.get("ended") or j["started"]) > days * 86400]
        rest_done = [j for j in ordered if j["state"] == "done" and j not in drop]
        drop += rest_done[:-KEEP_JOBS] if len(rest_done) > KEEP_JOBS else []
        for j in drop:
            self.jobs.pop(j["id"], None)
        return drop

    def _register(self, job: dict):
        """A newly launched job: its meta file first (so it can always be found again), then the shared list."""
        self._write_meta(job)
        with self.lock:
            self.jobs[job["id"]] = job
            self._save()

    def _save(self):
        # Another window on the same folder (plasbench ui --new-instance) may have started jobs this one has not seen: keep them, so one window never erases another's runs. The
        # read-merge-write is one step under an exclusive lock (threads of this window and other windows alike); deletions are written down; every job also has a meta file.
        with self._save_lock, self._index_lock():
            tomb = self._tombstones()
            for jid in tomb:
                self.jobs.pop(jid, None)
            try:
                for job in self._read_index():
                    jid = job.get("id")
                    if jid in tomb:
                        continue
                    if jid not in self.jobs:
                        self.jobs[jid] = job
                    elif job.get("state") in ("done", "failed", "cancelled") and self.jobs[jid]["state"] in ("running", "cancelling"):
                        self.jobs[jid].update(job)   # another window already recorded how it ended
            except (OSError, ValueError, KeyError, AttributeError):
                pass
            self._restore_from_meta(tomb)
            for job in list(self.jobs.values()):
                self._write_meta(job)
            for job in self._prune():
                for path in list(self._paths(job["id"]).values()) + [self._meta_path(job["id"])]:
                    try:
                        os.unlink(path)
                    except OSError:
                        pass
                self._meta_sig.pop(job["id"], None)
            ordered = sorted(self.jobs.values(), key=lambda j: j["started"])
            tmp = self.dir / f"jobs.json.{os.getpid()}.{threading.get_ident()}.tmp"   # written whole, then renamed over the index: a reader sees the old file or the new one, never half
            tmp.write_text(json.dumps(ordered, indent=1), encoding="utf-8")
            for attempt in range(40):   # on Windows the rename fails with "Access denied" while another process has the index open to read it: wait a moment and try again
                try:
                    os.replace(tmp, self.dir / "jobs.json")
                    break
                except PermissionError:
                    if attempt == 39:
                        raise
                    time.sleep(0.05)

    def _paths(self, job_id: str) -> dict:
        return jobrunner.paths(str(self.dir), job_id)

    def _alive(self, job: dict) -> bool:
        """Is the job's runner going? A fresh heartbeat says yes. A runner that has not written its first one yet (a slow start on a busy machine) is given STARTUP_GRACE seconds."""
        if jobrunner.is_alive(str(self.dir), job["id"]):
            return True
        p = self._paths(job["id"])
        if os.path.exists(p["alive"]) or os.path.exists(p["exit"]) or time.time() - job["started"] >= STARTUP_GRACE:
            return False
        # No heartbeat yet, inside the grace period: a slow start is still a start, but a runner whose process is already gone is not "starting". Cancelling a run
        # a moment after it began (before the runner wrote its pid file) used to leave it in `cancelling` for the whole grace period.
        pid = job.get("pid")
        return jobrunner.pid_alive(pid) if pid else True

    def _append_log(self, job_id: str, text: str):
        try:
            with open(self._paths(job_id)["log"], "ab") as handle:
                handle.write(text.encode("utf-8"))
        except OSError:
            pass

    # -- finding runs again after a restart --------------------------------------------------------------------
    def _reconcile(self, job: dict):
        """A job the index calls running: still going (watch it), finished while no server was watching (read its exit), or gone (interrupted)."""
        job_id = job["id"]
        exit_info = jobrunner.read_json(self._paths(job_id)["exit"])
        if exit_info is not None:
            self._finish(job_id, exit_info.get("code"), exit_info.get("ended"), save=False)
        elif self._alive(job):
            job["reattached"] = True
            self._watch(job_id)
        else:
            job.update(state="cancelled" if job["state"] == "cancelling" else "interrupted", ended=job.get("ended") or self._last_sign_of_life(job_id), exit=None)
            self._append_log(job_id, "\n[PlasBench] The run stopped without recording how it ended (the computer was shut down or the process was killed). "
                                     "Use Resume: finished work is kept and reused.\n")
            self._reap_orphans(job_id)

    def _last_sign_of_life(self, job_id: str) -> float:
        times = []
        for key in ("alive", "log"):
            try:
                times.append(os.path.getmtime(self._paths(job_id)[key]))
            except OSError:
                pass
        return max(times) if times else time.time()

    def _watch(self, job_id: str):
        if job_id in self.watchers:
            return
        self.watchers.add(job_id)
        threading.Thread(target=self._watch_loop, args=(job_id,), daemon=True).start()

    def _watch_loop(self, job_id: str):
        while True:
            time.sleep(1.0)
            job = self.jobs.get(job_id)
            if not job or job["state"] not in ("running", "cancelling", "interrupted"):
                break
            exit_info = jobrunner.read_json(self._paths(job_id)["exit"])
            if exit_info is not None:
                self._finish(job_id, exit_info.get("code"), exit_info.get("ended"))
                break
            alive = self._alive(job)
            if job["state"] == "interrupted":
                # A stale heartbeat does not prove the runner is gone: when the computer sleeps or hibernates, the runner and this server stop together and
                # the heartbeat file looks old on waking, before the runner has written its next one. If it comes back, the run is plainly still going; calling
                # it interrupted and offering Resume would start a second pipeline in the same results folder. Keep watching for a while before giving up.
                if alive:
                    with self.lock:
                        job.update(state="running", ended=None, exit=None)
                        self._save()
                    self._append_log(job_id, "\n[PlasBench] The run is still going (the computer was probably asleep or busy). It was only paused, so there is nothing to resume.\n")
                    session_log().event("job_resumed_by_heartbeat", job=job_id, label=job["label"])
                elif time.time() - (job.get("ended") or time.time()) > INTERRUPTED_WATCH_SECONDS:
                    break
                else:
                    time.sleep(1.0)
                continue
            if not alive:
                with self.lock:
                    job.update(state="cancelled" if job["state"] == "cancelling" else "interrupted", ended=self._last_sign_of_life(job_id), exit=None)
                    self._save()
                self._append_log(job_id, "\n[PlasBench] " + ("The run was cancelled." if job["state"] == "cancelled" else
                                 "The run stopped without recording how it ended. Use Resume: finished work is kept and reused.") + "\n")
                session_log().event("job_end", job=job_id, label=job["label"], state=job["state"], exit=None, seconds=round(job["ended"] - job["started"], 1))
                self._reap_orphans(job_id)
                if job["state"] == "cancelled":
                    break
                # interrupted: keep watching (see above)
        self.watchers.discard(job_id)

    def _finish(self, job_id: str, code, ended, save: bool = True):
        with self.lock:
            job = self.jobs[job_id]
            code = int(code) if isinstance(code, (int, float)) else None
            state = "cancelled" if job["state"] == "cancelling" else ("done" if code == 0 else "failed")
            warning = self._run_warnings(job) if state == "done" else ""
            if warning:
                job["warnings"] = warning      # before the state flips, so a reader that sees "done" never sees it without the note
            job.update(ended=ended or time.time(), exit=code, state=state)
            try:      # a Docker pull or build that stopped with a diagnosis (plasbench/docker_health.py record()) keeps it in the job's result
                found = Path(self.dir) / (job_id + ".diagnosis.json")
                if found.is_file():
                    job["diagnosis"] = json.loads(found.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
            if save:
                self._save()
        if code not in (0, None):
            # Never end silently: the console's last line says how and why the command stopped.
            from .exitcodes import explain, is_informational
            argv = job.get("argv") or []
            if is_informational(code) and is_docker_setup(argv) and code == MANUAL_STEP_EXIT:
                # Docker's installer handed steps to the user: "Waiting for you to finish in <place>", with a Re-check button. The place is read from the line the installer printed.
                try:
                    tail = _tail_bytes(self._paths(job_id)["log"], 6000).decode("utf-8", "replace")
                except Exception:  # noqa: BLE001
                    tail = ""
                found = re.findall(r"Waiting for you to finish in (.+?) \(exit 20", tail)
                with self.lock:
                    job["waiting_place"] = found[-1] if found else "Docker"
                self._append_log(job_id, f"\n[PlasBench] Waiting for you to finish in {job['waiting_place']} (exit 20): nothing failed. The steps are listed above; press Re-check when you are done.\n")
            elif is_informational(code):
                # Not an error, whatever the command was: a manual step (20) or a consent wait (21). The notice above already lists what to do.
                self._append_log(job_id, f"\n[PlasBench] {'Manual step needed' if code == MANUAL_STEP_EXIT else 'Consent needed'} (exit {code}): nothing failed. {explain(code)}.\n")
            else:
                reason = "cancelled from the window" if state == "cancelled" else explain(code, argv[0] if argv else None)
                self._append_log(job_id, f"\n[PlasBench] ERROR: the command stopped: {reason} (exit {code}).\n")
            if job.get("kind") == "git" and state != "cancelled":      # a git / GitHub failure, in plain words (not signed in, no permission, conflicts ...)
                try:
                    from . import ghops
                    said = ghops.translate_error(_tail_bytes(self._paths(job_id)["log"], 3000).decode("utf-8", "replace"))
                    if said["action"]:
                        self._append_log(job_id, f"[PlasBench] {said['message']}\n")
                except Exception:  # noqa: BLE001
                    pass
        session_log().event("job_end", job=job_id, label=job["label"], state=job["state"], exit=code, seconds=round(job["ended"] - job["started"], 1))

    def display_state(self, job: dict) -> str:
        """What to show: the stored state, except that a run that is going but has printed nothing for the stall window (PLASBENCH_STALL_SECONDS, default 10 minutes) reads
        `stalled` and a run that finished with failed tools reads `completed_with_warnings`. Derived, never stored, so it cannot outlive the condition."""
        state = job.get("state", "")
        if state == "running" and jobrunner.is_stalled(str(self.dir), job["id"]):
            return "stalled"
        if state == "running" and self._is_retrying(job["id"]):
            return "retrying"
        if state == "done" and job.get("warnings"):
            return "completed_with_warnings"
        if state == "failed" and job.get("exit") == MANUAL_STEP_EXIT and is_docker_setup(job.get("argv")):
            return "waiting_for_you"   # Docker's installer handed steps to the user (exit 20): information, shown as "Waiting for you to finish in <place>"
        if state == "failed" and job.get("exit") == MANUAL_STEP_EXIT:
            return "manual_step"   # exit 20 (any command): a manual step, a verified limit; not a failure
        if state == "failed" and job.get("exit") == CONSENT_EXIT:
            return "consent_needed"   # exit 21: nothing was changed, the install waits for consent; not a failure
        return state

    RETRY_LINE = re.compile(r"failed \(exit \d+\); retry (\d+) of (\d+)")

    def _is_retrying(self, job_id: str) -> bool:
        """True when the last line the run printed is stage 4's "<sample> / <tool> failed (exit N); retry K of M" notice: a tool failed and is being run again (AU-010).
        Derived from the output, like `stalled`, so it ends as soon as the run prints anything else. `queued` (waiting for a free slot) is not shown: the window runs one benchmark at a time."""
        try:
            tail = _tail_bytes(self._paths(job_id)["log"], 2000).decode("utf-8", "replace")
        except OSError:
            return False
        lines = [line for line in tail.splitlines() if line.strip()]
        return bool(lines) and self.RETRY_LINE.search(lines[-1]) is not None

    def _reap_orphans(self, job_id: str):
        """The runner is gone (killed with SIGKILL, which nothing can catch) but the command it started may still be going, with nothing watching it. Stop the whole process group
        and say so in the log, so the run is `interrupted` with no orphan left writing into the results folder. A runner that is merely asleep is left alone."""
        state = jobrunner.run_state(str(self.dir), job_id)
        if state["runner_alive"] or not state["group_alive"]:
            return
        stopped = jobrunner.kill_group(state["pgid"])
        self._append_log(job_id, "\n[PlasBench] The runner was killed but its command was still running: " +
                         ("its processes were stopped.\n" if stopped else f"some processes of group {state['pgid']} could not be stopped; Resume stays unavailable until they are gone.\n"))
        session_log().event("job_orphans_stopped", job=job_id, group=state["pgid"], stopped=stopped)

    def _lock_refusal(self, argv: list) -> str:
        """Why a benchmark run cannot start now: its results folder is locked by a live run (pid or any member of its process group alive), or an empty string."""
        results = self._results_dir(argv)
        lock = jobrunner.lock_holder(results) if results else None
        if not lock:
            return ""
        return (f"another run is using this results folder ({results}): pid {lock.get('pid', '?')}, {lock.get('what', 'a stage')}, started {lock.get('started', 'unknown')}. "
                "Wait for it to finish or cancel it first; starting a second one would make them overwrite each other.")

    def _run_warnings(self, job: dict) -> str:
        """The note run_all.sh leaves in the results folder (.completed_with_warnings) when it finished but some tool runs failed, if this run wrote it."""
        results = job.get("results") or ""
        if not results:
            return ""
        marker = Path(results) / ".completed_with_warnings"
        try:
            if marker.stat().st_mtime >= job["started"] - 2:
                return marker.read_text(encoding="utf-8", errors="replace").strip()[:300] or "some tool runs failed"
        except OSError:
            pass
        return ""

    # -- starting, answering, cancelling, resuming -------------------------------------------------------------
    def start(self, argv: list[str], label: str = "", env: dict | None = None) -> dict:
        ok, message = ui_schema.validate_argv(argv)
        if not ok:
            raise ValueError(message)
        env = self.check_env(env)
        refusal = self._lock_refusal(argv)
        if refusal:
            raise ValueError(refusal)
        command = [sys.executable, "-u", "-m", "plasbench", "--project-root", str(self.project.root)] + list(argv)
        shown = "plasbench " + " ".join(shlex.quote(a) for a in argv)
        job = self._launch(command, shown, label, env, list(argv), "plasbench", self.project.root)
        return dict(job, **self.install_fields(job))   # the install fields too, so the window can confirm its optimistic toast from the start response

    def running_results(self) -> list:
        """The results folders of runs that are going (running or cancelling)."""
        return [j.get("results") for j in self.jobs.values() if j.get("state") in ("running", "cancelling") and j.get("results")]

    def env_allowlist(self) -> set:
        """The names a job may carry: every Settings key in config/config.sh plus the download and reliability names, minus a few that would redirect the program itself."""
        try:
            keys = {row["key"] for row in self.project.settings()}
        except OSError:
            keys = set()
        return (keys | EXTRA_ENV_KEYS) - ENV_FORBIDDEN

    def check_env(self, env) -> dict | None:
        """Refuse an environment the window may not set: only UPPER_SNAKE names on the allowlist, values of plain text under 200 characters. Returns the cleaned dict."""
        if env in (None, {}):
            return None
        if not isinstance(env, dict):
            raise ValueError("env must be an object of setting names and values")
        allowed, clean = self.env_allowlist(), {}
        for key, value in env.items():
            if not isinstance(key, str) or not ENV_KEY.fullmatch(key):
                raise ValueError(f"not a setting name: {key!r} (use UPPER_SNAKE_CASE)")
            if key not in allowed:
                raise ValueError(f"{key} is not a setting the window may pass to a run")
            if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                raise ValueError(f"the value of {key} must be text or a number")
            value = str(value)
            if "\n" in value or "\r" in value or "\x00" in value:
                raise ValueError(f"the value of {key} must be one line of plain text")
            if len(value) >= ENV_VALUE_MAX:
                raise ValueError(f"the value of {key} is too long (under {ENV_VALUE_MAX} characters)")
            clean[key] = value
        return clean or None

    def start_git(self, command: list, label: str, cwd, program: str = "git") -> dict:
        """A git (or, with program="gh", GitHub CLI) network operation built by plasbench.gitops.argv / plasbench.ghops (never from the request as text): runs like any job, with
        its command line written first in the log (tokens removed)."""
        from . import gitops
        if any(j.get("kind") == "git" and j["state"] in ("running", "cancelling") for j in self.jobs.values()):
            raise ValueError("another git operation is still running: wait for it to finish")
        shown = gitops.redact(" ".join(shlex.quote(str(a)) for a in [program] + list(command[1:])))
        env = {"GIT_TERMINAL_PROMPT": "0"}
        return self._launch(list(command), shown, label, env, [], "git", cwd)

    def _launch(self, command, shown, label, env, argv, kind, cwd, resumes: str | None = None) -> dict:
        job_id = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
        p = self._paths(job_id)
        child_env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", PLASBENCH_STARTED_VIA="window",
                         PLASBENCH_JOB_ID=job_id, PLASBENCH_JOB_DIR=str(self.dir))
        for key, value in (env or {}).items():
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
                raise ValueError(f"not a setting name: {key}")
            child_env[key] = str(value)
        with open(p["log"], "ab") as handle:   # the command line first; the runner then appends the command's own output
            handle.write(f"$ {shown}\n".encode())
            if env:
                handle.write(("  with " + " ".join(f"{k}={shlex.quote(str(v))}" for k, v in env.items()) + "\n").encode())
        kwargs = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        runner = subprocess.Popen([sys.executable, "-u", "-m", "plasbench.jobrunner", str(self.dir), job_id, str(cwd), "--"] + list(command), cwd=str(cwd),
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=child_env, **kwargs)
        job = {"id": job_id, "label": label or shown, "argv": list(argv), "command": shown, "env": env or {}, "kind": kind,
               "state": "running", "started": time.time(), "ended": None, "exit": None, "pid": runner.pid, "results": self._results_dir(argv)}
        if resumes:
            job["resumes"] = resumes
        self._register(job)
        threading.Thread(target=runner.wait, daemon=True).start()   # reap the runner; the outcome comes from its exit file
        self._watch(job_id)
        session_log().event("job_start", job=job_id, label=job["label"], command=shown, env=env or None, cwd=str(cwd), job_kind=kind)
        return job

    def _results_dir(self, argv: list) -> str:
        """The results folder a run writes to, from its options (empty for a command that does not make one)."""
        if not argv or argv[0] not in SESSION_COMMANDS:
            return ""
        root = self.project.root
        for i, a in enumerate(argv):
            if a == "--results-dir" and i + 1 < len(argv):
                return str((root / argv[i + 1]) if not os.path.isabs(argv[i + 1]) else Path(argv[i + 1]))
            if a.startswith("--results-dir="):
                return str(root / a.split("=", 1)[1])
        for i, a in enumerate(argv):
            if a == "--study" and i + 1 < len(argv):
                try:
                    from . import studies
                    for st in studies.list_studies(root):
                        if st.get("name") == argv[i + 1]:
                            return str(Path(st["results"]))
                except Exception:
                    pass
                return ""
        return str(root / "results_demo") if argv[0] == "demo" else str(root / "results")

    def answer(self, job_id: str, text: str, secret: bool = False) -> dict:
        """Type one line into a running command, as if at its terminal, and record it in the log (masked if secret). Works for a run this window did not start."""
        if "\n" in text or "\r" in text:
            raise ValueError("one line at a time")
        if len(text) > 4096:
            raise ValueError("answer too long")
        job = self.jobs.get(job_id)
        if not job or job["state"] != "running" or not self._alive(job):
            raise ValueError("this job is not running")
        with self.lock:
            shown = "\u2022" * len(text) if secret else text
            try:
                with open(self._paths(job_id)["input"], "ab") as handle:   # the runner forwards it and records `[you] ...` in the log
                    handle.write((json.dumps({"text": text, "shown": shown}) + "\n").encode("utf-8"))
            except OSError as exc:
                raise ValueError(f"the command is no longer reading input ({exc})")
        session_log().event("job_input", job=job_id, label=job.get("label", ""), answer=shown)
        return {"ok": True}

    def _kill(self, job_id: str, job: dict):
        info = jobrunner.read_json(self._paths(job_id)["pid"]) or {}
        pid = int(info.get("runner") or job.get("pid") or 0)
        threading.Thread(target=jobrunner.stop_job_container, args=(str(self.dir), job_id), daemon=True).start()   # a Docker run: stop its container too
        if not pid or _is_own_process(pid):
            return   # never signal this very process (or its group): a stale or foreign record that names our own pid must not make a window kill itself
        if info.get("pgid") and os.name != "nt":
            # the command is in its own process group: stop it (and everything it started) even if the runner is already gone
            threading.Thread(target=jobrunner.kill_group, args=(info["pgid"],), daemon=True).start()
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
        else:
            try:
                os.killpg(pid, signal.SIGTERM)
            except OSError:
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass

    def cancel(self, job_id: str) -> dict:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job["state"] not in ("running", "cancelling"):
                raise KeyError(job_id)
            job["state"] = "cancelling"
            self._save()
        session_log().event("job_cancel", job=job_id, label=job["label"])
        self._kill(job_id, job)
        self._watch(job_id)
        return job

    def resume(self, job_id: str) -> dict:
        """Start the same command again for a run that failed, was interrupted or was cancelled. Finished work is reused (docs/SCIENTIFIC_GUIDE.md: an interrupted run resumes), so this
        picks up where it stopped. The new job is linked to the old one both ways."""
        job = self.jobs.get(job_id)
        if not job:
            raise KeyError(job_id)
        if job["state"] not in RESUMABLE_STATES or job.get("kind") != "plasbench" or not job.get("argv"):
            raise ValueError("only a failed, interrupted or cancelled plasbench run can be resumed")
        if jobrunner.is_alive(str(self.dir), job_id):
            raise ValueError("this run is still going (its runner is alive), so it cannot be resumed; wait for it to finish or cancel it first")
        left = jobrunner.run_state(str(self.dir), job_id)
        if left["runner_alive"] or left["group_alive"]:
            raise ValueError("this run cannot be resumed yet: a process it started is still running (a second run in the same results folder would overwrite its work). "
                             "Cancel it, or wait for it to finish.")
        refusal = self._lock_refusal(job["argv"])
        if refusal:
            raise ValueError(refusal)
        if any(j["state"] in ("running", "cancelling") and j.get("argv") == job["argv"] for j in self.jobs.values()):
            raise ValueError("the same command is already running")
        command = [sys.executable, "-u", "-m", "plasbench", "--project-root", str(self.project.root)] + list(job["argv"])
        label = job["label"] if job["label"].startswith("Resumed: ") else "Resumed: " + job["label"]
        new = self._launch(command, job["command"], label, job.get("env") or None, list(job["argv"]), "plasbench", self.project.root, resumes=job_id)
        with self.lock:
            job["resumed_by"] = new["id"]
            self._save()
        return new

    def running(self) -> list[dict]:
        return [j for j in self.jobs.values() if j["state"] in ("running", "cancelling")]

    # -- reading -----------------------------------------------------------------------------------------------
    def get(self, job_id: str, offset: int = 0) -> dict:
        job = self.jobs.get(job_id)
        if not job:
            raise KeyError(job_id)
        log = self._paths(job_id)["log"]
        text, size = "", 0
        if os.path.isfile(log):
            size = os.path.getsize(log)
            with open(log, "rb") as handle:
                handle.seek(max(0, offset))
                text = handle.read(MAX_LOG_CHUNK).decode("utf-8", "replace")
        return dict(job, log=text, offset=min(size, max(0, offset) + MAX_LOG_CHUNK), size=size, display_state=self.display_state(job),
                    idle_seconds=jobrunner.idle_seconds(str(self.dir), job_id) if job.get("state") == "running" else None)

    def activity(self, job_id: str) -> dict:
        """Which files the run (or the tools it started) wrote most recently, so a quiet log can be told from a stuck run: the job's results folder and the shared data folder."""
        job = self.jobs.get(job_id)
        if not job:
            raise KeyError(job_id)
        roots = []
        if job.get("results"):
            roots.append(job["results"])
        if job.get("kind") == "plasbench":
            roots.append(str(self.project.path_setting("DATA_DIR", "data")))
        out = jobrunner.recent_activity(roots)
        out["state"] = job.get("state")
        out["idle_seconds"] = jobrunner.idle_seconds(str(self.dir), job_id) if job.get("state") == "running" else None
        return out

    def _refresh_from_folder(self):
        """A job another window started, or one the index lost, appears here too: when the job folder changed, jobs with a meta file come back (never a deleted one)."""
        try:
            stamp = os.stat(self.dir).st_mtime_ns
        except OSError:
            return
        if stamp != self._dir_stamp:
            self._dir_stamp = stamp
            with self.lock:
                for job in self._restore_from_meta(self._tombstones()):
                    if job.get("state") in ("running", "cancelling") and job["id"] not in self.watchers:
                        self._reconcile(job)

    def list(self) -> list[dict]:
        self._refresh_from_folder()
        return [dict(j, display_state=self.display_state(j), **self.install_fields(j)) for j in sorted(self.jobs.values(), key=lambda j: -j["started"])]

    # ==INSTALL-LABELS-BEGIN== additive jobs-payload fields for the window's installing toast (labels and the install predicate live in plasbench/jobs_labels.py)
    def install_fields(self, job: dict) -> dict:
        """is_install, install_label, install_tools, install_kind for every job; for an install that is going or ended in the last day also last_line (one line of its log: the phase,
        or the reason when it failed) and, when done, installed_version. Cached on the log's size and time, so a poll of a quiet log reads nothing."""
        info = jobs_labels.describe(job.get("argv"), job.get("kind", "plasbench"))
        out = {"is_install": info["is_install"], "install_label": info["label"], "install_tools": info["install_tools"], "install_kind": info["install_kind"]}
        if not info["is_install"]:
            return out
        state, ended = job.get("state"), job.get("ended")
        if state not in ("running", "cancelling") and not (ended and time.time() - ended < 86400):
            return out
        try:
            stat = os.stat(self._paths(job["id"])["log"])
        except OSError:
            return out
        key = (stat.st_size, stat.st_mtime_ns, state, job.get("exit"))
        cached = self._line_cache.get(job["id"])
        if not cached or cached[0] != key:
            tail = _tail_bytes(self._paths(job["id"])["log"], 6000).decode("utf-8", "replace")
            bad = state in ("failed", "interrupted") and job.get("exit") not in ((MANUAL_STEP_EXIT, CONSENT_EXIT))
            cached = (key, {"last_line": jobs_labels.last_line(tail, failed=bad), "installed_version": jobs_labels.installed_version(tail) if state == "done" else ""})
            self._line_cache[job["id"]] = cached
        out.update(cached[1])
        return out
    # ==INSTALL-LABELS-END==

    def progress(self, job_id: str) -> dict:
        """The parsed progress of a job's log, cached until the log changes."""
        log = self._paths(job_id)["log"]
        try:
            stat = os.stat(log)
        except OSError:
            return runprogress.parse("")
        key = (stat.st_size, int(stat.st_mtime))
        cached = self._progress_cache.get(job_id)
        if cached and cached[0] == key:
            return cached[1]
        with open(log, "rb") as handle:
            data = handle.read(8 * 2**20) if stat.st_size <= 8 * 2**20 else handle.read(2**20) + b"\n" + _tail_bytes(log, 6 * 2**20)
        result = runprogress.parse(data.decode("utf-8", "replace"))
        self._progress_cache[job_id] = (key, result)
        return result

    def sessions(self, run_index: dict | None = None) -> list[dict]:
        """The benchmark run sessions, newest first, each with the group it belongs in, its progress, where its results are and what can be done with it.

        group: ongoing (running or cancelling), attention (failed, interrupted or cancelled: can be resumed), completed. `run_index` maps a results folder to its index in the
        Runs list so the page can open that run's report."""
        out = []
        for job in self.list():
            if job.get("kind") != "plasbench" or not job.get("argv") or job["argv"][0] not in SESSION_COMMANDS:
                continue
            state = job["state"]
            group = "ongoing" if state in ("running", "cancelling") else "completed" if state == "done" else "attention"
            results = job.get("results") or self._results_dir(job["argv"])
            idx = (run_index or {}).get(loadcache.realpath(results)) if results else None
            progress = self.progress(job["id"])
            if state == "done":
                progress = dict(progress, percent=100)
            log = self._paths(job["id"])["log"]
            try:
                activity = os.path.getmtime(log)
            except OSError:
                activity = job["started"]
            out.append(dict(job, group=group, progress=progress, results=results, run_index=idx, last_activity=activity, display_state=self.display_state(job),
                            idle_seconds=jobrunner.idle_seconds(str(self.dir), job["id"]) if state == "running" else None,
                            resumable=state in RESUMABLE_STATES and not any(j["state"] in ("running", "cancelling") and j.get("argv") == job["argv"] for j in self.jobs.values()),
                            reattached=bool(job.get("reattached"))))
        return out

    def delete(self, job_id: str):
        with self.lock:
            job = self.jobs.get(job_id)
            if job and job["state"] in ("running", "cancelling"):
                raise ValueError("cancel the job before removing it")
            self.jobs.pop(job_id, None)
            self.deleted.add(job_id)
            with self._save_lock, self._index_lock():
                with open(self.dir / "jobs.deleted", "a", encoding="utf-8") as handle:   # written down: every window keeps it deleted
                    handle.write(job_id + "\n")
            self._save()
        for path in list(self._paths(job_id).values()) + [self._meta_path(job_id)]:
            try:
                os.unlink(path)
            except OSError:
                pass


def _tail_bytes(path: str, n: int) -> bytes:
    with open(path, "rb") as handle:
        handle.seek(0, os.SEEK_END)
        handle.seek(max(0, handle.tell() - n))
        return handle.read()


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


PROBE_TTL = 30.0
NET_TTL = 8.0          # seconds the connection check is reused (netcheck keeps its own 10 s memory below this)
PLATFORM_TTL = 120.0   # seconds a remembered environment probe is fresh; an older one is shown at once and refreshed in the background


def schema_bytes() -> bytes:
    """The window's command schema as ready-made JSON. It only changes with the code, so it is built once per process."""
    return loadcache.memo("schema_bytes", __version__, lambda: json.dumps(ui_schema.schema(), default=str).encode("utf-8"))


_GZ: dict = {}
_GZ_LOCK = threading.Lock()


def gzip_cached(body: bytes) -> bytes:
    """gzip of `body`, remembered for the last few distinct bodies (the page and the schema are the same bytes on every request)."""
    import zlib
    key = (len(body), hash(body))
    with _GZ_LOCK:
        hit = _GZ.get(key)
    if hit is not None:
        return hit
    comp = zlib.compressobj(6, zlib.DEFLATED, 31)
    out = comp.compress(body) + comp.flush()
    with _GZ_LOCK:
        if len(_GZ) >= 16:
            _GZ.pop(next(iter(_GZ)))
        _GZ[key] = out
    return out


def _platform_probe() -> dict:
    from . import platform_info
    info = platform_info.detect()
    return {"info": info, "plan": platform_info.recommend(info)}


def warm(project, jobs=None) -> None:
    """Fill the caches in the background at start-up, so the first page the user opens is served from memory (the PATH probes, docker and conda included)."""
    def run():
        steps = (schema_bytes, lambda: project.tools(block=True), lambda: loadcache.swr(("env", str(project.root)), PROBE_TTL, project.env_checks),
                 lambda: loadcache.swr("platform", PLATFORM_TTL, _platform_probe), project.cohorts, project.docs, project.settings_resolved, project.info,
                 lambda: project.runs([]), lambda: jobs.sessions({}) if jobs else None)
        for step in steps:
            try:
                step()
            except Exception:  # noqa: BLE001 - warming is best effort
                pass
    threading.Thread(target=run, daemon=True, name="plasbench-warm").start()


TEXT_PREVIEW = {".tsv": "table", ".csv": "table", ".txt": "text", ".log": "text", ".md": "text", ".json": "text",
                ".jsonl": "text", ".yaml": "text", ".yml": "text", ".ini": "text", ".sh": "text", ".py": "text", ".gff": "text", ".gff3": "text"}
MAX_PREVIEW = 2 * 2**20


def read_study_file(root, raw: str) -> dict:
    """A text or table file inside the studies workspace, for a read-only tab in the window (at most 2 MB shown)."""
    from . import studies
    ws = Path(os.path.realpath(studies.workspace(root)))
    p = Path(os.path.realpath(Path(raw or "").expanduser()))
    if ws not in p.parents:
        raise PermissionError("only files inside the studies workspace are shown here")
    if not p.is_file():
        raise FileNotFoundError(f"{p} is not a file")
    kind = TEXT_PREVIEW.get(p.suffix.lower())
    if not kind:
        raise ValueError(f"{p.suffix or 'this'} files are not shown in the window; open the folder instead")
    size = p.stat().st_size
    with open(p, "rb") as handle:
        data = handle.read(MAX_PREVIEW)
    return {"path": str(p), "name": p.name, "size": size, "kind": kind, "truncated": size > MAX_PREVIEW,
            "text": data.decode("utf-8", "replace")}


# ---- the folder window's extras (plasbench/native_picker.py, docker_helper.py, picker_check.py): small, additive ----
_selftest_lock = threading.Lock()


def native_picker_extras(caps: dict) -> dict:
    """What the page needs beside the capabilities: in Docker the mounts and the banner; every platform its diagnostics."""
    from . import docker_helper
    out = {"diagnostics": {"platform": caps.get("platform"), "via": caps.get("via"), "tried": caps.get("tried") or [], "interop": caps.get("interop")}}
    if caps.get("docker"):
        mounts = docker_helper.user_mounts()
        out.update(mounts=mounts, mount_roots=docker_helper.mount_roots(mounts),
                   banner="Folders outside these mounts are not visible to the window." if mounts else "No folder is mounted into this container, so no folder of yours is visible to the window.")
    return out


_issue_report_lock = threading.Lock()


def issue_report_state(root, q) -> dict:
    """GET /api/issue-report: the same redacted Markdown as `plasbench issue-report`, one at a time, at most 200 lines of each log, never any network probe. {markdown, truncated, study, new_issue}."""
    from . import issue_report
    if not _issue_report_lock.acquire(blocking=False):
        return {"error": "the diagnostics are already being prepared", "markdown": ""}
    try:
        try:
            lines = max(0, min(200, int(q.get("lines", issue_report.DEFAULT_LOG_LINES))))
        except ValueError:
            lines = issue_report.DEFAULT_LOG_LINES
        study = (q.get("study") or "").strip() or None
        try:
            out = issue_report.collect(root, "this window", study, lines, False, True, False)
        except issue_report.StudyNotFound as exc:
            return {"error": str(exc), "markdown": ""}
        out["new_issue"] = issue_report.NEW_ISSUE_URL + "/choose"
        out.pop("summary", None)
        return out
    finally:
        _issue_report_lock.release()


def native_picker_selftest() -> dict:
    """The same checks as `plasbench picker-check`, for the Settings button: one at a time, bounded (the window it opens closes itself after 2 s)."""
    from . import picker_check
    if not _selftest_lock.acquire(blocking=False):
        return {"error": "a folder window test is already running", "steps": [], "verdict": "", "ok": False}
    try:
        report = picker_check.run_checks(interactive=False, seconds=2)
        report["text"] = picker_check.format_report(report)
        return report
    finally:
        _selftest_lock.release()


def docker_offer_state(root) -> dict:
    """Whether "run PlasBench in Docker instead" is offered: Docker answers `docker info` and scripts/docker_run.sh exists; never inside Docker. The probe runs in the background."""
    from . import docker_helper, platform_info
    if docker_helper.in_docker():
        return {"pending": False, "offered": False, "reason": "this window already runs inside Docker", "in_docker": True}
    state, ready = loadcache.swr(("docker-state",), 60.0, platform_info.docker, block=False)
    if not ready:
        return {"pending": True, "offered": False, "reason": "checking whether Docker is available"}
    offer = docker_helper.switch_offer(state, (Path(root) / "scripts" / "docker_run.sh").is_file())
    return dict(offer, pending=False, in_docker=False, docker=state)
# ---- where the tools run: conda or Docker (plasbench/docker_runtime.py; GET /api/runtime, POST /api/runtime/use|test|pull|ready) ----
RUNTIME_TTL = 20.0
_runtime_test_lock = threading.Lock()


def _docker_probe(root) -> dict:
    from . import docker_runtime
    return docker_runtime.probe(root)


def runtime_state(project) -> dict:
    """The Environment card's data. The Docker probe (`docker version`, `docker image inspect`) runs in the background through loadcache and is never on the page-load path:
    until it has answered the state says pending. Conda's side is the cached platform probe."""
    from . import docker_helper, docker_runtime as dr
    root = project.root
    try:
        chosen = dr.runtime_setting(root)
        problem = ""
    except ValueError as exc:
        chosen, problem = "conda", str(exc)
    inside = docker_helper.in_docker()
    plat, plat_ready = loadcache.swr("platform", PLATFORM_TTL, _platform_probe, block=False)
    info = (plat or {}).get("info") or {}
    conda = {"pending": not plat_ready, "env_found": bool(info.get("env_ready")), "env_prefix": info.get("env_prefix"), "solver": info.get("conda_solver")}
    if inside:
        docker = {"pending": False, "state": "inside_docker", "installed": False, "running": False, "version": "", "image": {},
                  "hint": "This window runs inside a container: choose where tools run from a window on the computer itself."}
    else:
        # The Docker state is the tools setup's own (python/docker_setup.py, one cached background probe: docker_setup_state); only the image facts are added here.
        ds = docker_setup_state(root)
        if ds.get("pending"):
            docker = {"pending": True, "state": "pending", "installed": False, "running": False, "version": "", "image": {}, "hint": "Checking Docker..."}
        else:
            state = {"permission_denied": "permission_needed", "permission_group_not_applied": "permission_needed", "desktop_not_running": "daemon_stopped", "in_container": "inside_docker", "unknown": "daemon_stopped",
                     "installed_windows_not_running": "daemon_stopped", "desktop_running_engine_down": "daemon_stopped", "engine_up_wsl_integration_off": "wsl_integration_off"}.get(ds["state"], ds["state"])
            image = {}
            if state == "ready":
                found, ready = loadcache.swr(("runtime-image", str(root)), RUNTIME_TTL, lambda: _docker_probe(root), block=False)
                image = (found or {}).get("image") or {}
            docker = {"pending": False, "state": state, "setup_state": ds["state"], "action": ds.get("action", ""), "chip": ds.get("chip", ""), "installed": state != "not_installed", "running": state == "ready", "version": ds.get("server_version") or ds.get("version", ""),
                      "image": image, "hint": "" if state == "ready" else (ds.get("title") or ds.get("detail") or "Docker is not ready")}
    reason = ""
    if inside:
        reason = docker["hint"]
    elif not docker["pending"] and docker["state"] != "ready":
        reason = docker["hint"] or "Docker is not ready"
    return {"runtime": chosen, "problem": problem, "version": __version__, "conda": conda, "docker": docker, "docker_usable": not reason and not docker["pending"], "docker_reason": reason,
            "default_image": dr.published_image(), "local_image": dr.local_tag(), "pull_policy": setting_value(project, "PLASBENCH_DOCKER_PULL", "missing"),
            "extras": dr.extras_listing(root), "pull_size": "not measured", "build_note": dr.build_plan(root, dr.local_tag())["lines"]}


def setting_value(project, key, default=""):
    return os.environ.get(key) or project.local_env().get(key) or default


def runtime_use(project, choice: str) -> dict:
    from . import docker_runtime as dr
    if choice not in dr.RUNTIMES:
        raise ValueError("the runtime is conda or docker")
    if choice == "docker":
        state = runtime_state(project)
        if state["docker"]["pending"]:
            raise ValueError("Docker is still being checked: try again in a moment")
        if state["docker_reason"]:
            raise ValueError("Docker cannot be used yet: " + state["docker_reason"])
    project.save_local_env({"PLASBENCH_RUNTIME": choice})
    loadcache.forget(("runtime-image", str(project.root)))
    session_log().event("runtime_use", runtime=choice)
    return runtime_state(project)


def runtime_test(project) -> dict:
    """`plasbench runtime check` for the Test Docker setup button: the same steps, PASS or FAIL each. One at a time."""
    from . import docker_runtime as dr
    if not _runtime_test_lock.acquire(blocking=False):
        return {"error": "a Docker test is already running", "steps": [], "ok": False}
    try:
        rows = dr.check_steps(project.root)
        loadcache.forget(("runtime-image", str(project.root)))
        return {"steps": rows, "ok": all(r["ok"] for r in rows), "text": dr.format_steps(rows)}
    finally:
        _runtime_test_lock.release()
# ---- Docker health (plasbench/docker_health.py): GET /api/runtime/health returns the last result only (never starts anything); POST runs the bounded checks (about 15 s), remembered 30 s ----
HEALTH_TTL = 30.0
_health_lock = threading.Lock()
_health_last = {}


def docker_health_state() -> dict:
    """The last health check of this window session ({'checked': False} before the first one). Starts no process: safe on any path."""
    return dict(_health_last) if _health_last else {"checked": False}


def docker_health_run(project, refresh: bool = False) -> dict:
    """Run the Docker engine health checks once at a time (docker version / info / a test volume created and removed; no network, nothing pulled). A second click within 30 s gets the same answer."""
    from . import docker_health
    if not _health_lock.acquire(blocking=False):
        return dict(docker_health_state(), busy=True, error="a Docker health check is already running")
    try:
        key = ("docker-health", str(project.root))
        if refresh:
            loadcache.forget(key)
        result = loadcache.ttl(key, HEALTH_TTL, lambda: docker_health.check(project.root, purpose="doctor", budget=20.0))
        _health_last.clear()
        _health_last.update(dict(result, checked=True, at=time.time()))
        session_log().event("docker_health", healthy=result["healthy"], cause=(result.get("diagnosis") or {}).get("cause", ""))
        return dict(_health_last)
    finally:
        _health_lock.release()
def _docker_setup_probe(root) -> dict:
    """One answer for the Docker item of the tools setup: the state chip, the diagnosis and the plan (python/docker_setup.py). Runs `docker --version`, `docker info` and
    `docker context show` only, in the background thread loadcache starts; nothing is installed or started."""
    dpy = str(Path(root) / "python")
    if dpy not in sys.path:
        sys.path.insert(0, dpy)
    import docker_setup
    environment = docker_setup.detect_environment()
    st = docker_setup.probe(environment)
    plan = docker_setup.make_plan(environment, st)
    diag = docker_setup.diagnose(st, environment)
    if st["state"] == "ready":
        docker_setup.record(st)
    ev = st.get("evidence") or {}
    return {"state": st["state"], "chip": diag["chip"], "tone": diag["tone"], "title": diag["title"], "detail": st.get("detail", ""), "steps": diag["steps"], "place": diag["place"],
            "action": diag["action"], "stages": st.get("stages") or [], "installed_note": plan.get("installed", ""), "desktop_version": ev.get("desktop_version", ""),
            "version": st.get("version", ""), "server_version": st.get("server_version", ""), "context": st.get("context", ""),
            "environment": {k: environment.get(k) for k in ("kind", "distro", "wsl_distro", "package_manager", "interop", "container")} | {"winget": bool(environment.get("winget")), "brew": bool(environment.get("brew"))},
            "plan": {"route": plan["route"], "place": plan["place"], "runs": plan["runs"], "who_elevates": plan["who_elevates"], "licence": plan["licence"], "internet": plan["internet"],
                     "size": plan["size"], "summary": plan["summary"], "steps": plan["steps"], "links": [list(x) for x in plan["links"]], "scripts": plan["scripts"]},
            "guide_url": docker_setup.GUIDE_URL, "licence_url": docker_setup.LICENCE_URL}


def docker_setup_state(root, refresh: bool = False) -> dict:
    """The Docker item's state for the Tools page, the Workflow view and the folder chooser's "Run in Docker instead": a cached background probe (loadcache.swr), never on the
    page-load path. `refresh` (the Re-check button) drops the cached answer and probes again."""
    if refresh:
        loadcache.forget(("docker-setup",))
    value, ready = loadcache.swr(("docker-setup",), 30.0, lambda: _docker_setup_probe(root), block=False)
    if not ready:
        return {"pending": True, "state": "checking", "chip": "Checking Docker", "tone": "mut"}
    return dict(value, pending=False)
# ---- end folder window extras ----


def browse(path: str, files: bool, project=None, hidden: bool = False, refresh: bool = False) -> dict:
    """The folder chooser's listing. An empty path is the root view: Quick places (Home, the workspace, the PlasBench folder, the shared data folder) and This PC (drive letters;
    in WSL the Windows drives; on Linux /mnt, /media/$USER; on macOS /Volumes). A typed Windows or \\\\wsl.localhost path is converted to the Linux path in WSL."""
    from . import chooser
    wsl = chooser.in_wsl()
    if not path:
        disks = None
        if wsl or os.name == "nt":      # every Windows volume with its real size (USB, network, unmounted): the same list the computer card reads
            from . import computer_info
            if refresh:
                loadcache.forget("win-disks")
            disks, _ = loadcache.swr("win-disks", 8.0, computer_info.windows_disks)
        places, pc = [], chooser.pc_places(disks=disks)
        if project is not None:
            from . import studies
            from .cli import configured_data_dir
            places = chooser.quick_places(project.root, studies.workspace(project.root), configured_data_dir(project.root), wsl=wsl)
        else:
            places = chooser.quick_places(Path.cwd(), Path.home(), wsl=wsl)
        # ---- Docker: the root is the folders mounted into this container (plasbench/docker_helper.py) ----
        from . import docker_helper
        in_dock = loadcache.ttl(("in-docker",), 60.0, docker_helper.in_docker)
        if in_dock:
            pc = [{"name": r["label"], "path": r["path"], "dir": True, "free": None, "kind": "drive"} for r in docker_helper.mount_roots(docker_helper.user_mounts())]
            places = [p for p in places if p["name"] in ("Workspace (studies)", "PlasBench folder", "Shared data folder")]
        # ---- end Docker ----
        help_text = ("A drive that is not listed is not mounted in Ubuntu. To mount a drive (E: as the example), run this in the Terminal tab; PlasBench never runs it for you: "
                     + chooser.mount_command("E")) if wsl else ""
        if in_dock:
            help_text = "This window runs inside Docker: you can only choose folders mounted into the container. Folders outside these mounts are not visible to the window."
        return {"path": "", "parent": None, "windows": "", "wsl": wsl, "docker": bool(in_dock), "places": places, "pc": pc, "help": help_text, "entries": places + pc}
    path = chooser.to_linux(path)
    p = Path(path).expanduser()
    if not p.exists():
        m = chooser.DRIVE_RE.match(str(path)) or (wsl and re.match(r"^/mnt/([A-Za-z])(/|$)", str(path)))
        if wsl and m and re.match(r"^/mnt/([A-Za-z])(/|$)", str(p)):
            raise FileNotFoundError(chooser.mount_help(re.match(r"^/mnt/([A-Za-z])", str(p)).group(1)))
        raise FileNotFoundError(f"{p} does not exist")
    if p.is_file():
        p = p.parent
    entries = []
    try:
        for child in sorted(p.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):
            if child.name.startswith(".") and not hidden:
                continue
            try:
                is_dir = child.is_dir()
            except OSError:
                continue
            if is_dir or files:
                entry = {"name": child.name, "path": str(child), "dir": is_dir, "mtime": None}
                try:
                    st = child.stat()
                    entry["mtime"] = int(st.st_mtime)
                    if not is_dir:
                        entry["size"] = st.st_size
                except OSError:
                    if not is_dir:
                        entry["size"] = None
                entries.append(entry)
            if len(entries) >= 1500:
                break
    except PermissionError:
        raise PermissionError(f"no permission to list {p}")
    except OSError as exc:
        raise PermissionError(f"cannot list {p}: {exc.strerror or exc}")
    parent = str(p.parent) if p.parent != p else ""
    return {"path": str(p), "parent": parent, "windows": chooser.to_windows(str(p)), "wsl": wsl, "entries": entries}


class UIServer(ThreadingHTTPServer):
    """The window's HTTP server, built not to drop a connection under a burst.

    The standard server listens with a backlog of 5. The page fires many requests at once (and polls every second), and on Windows a connection that finds the backlog full is
    REFUSED outright (WinError 10061), which the page saw as "PlasBench disconnected" at random. A backlog of 256 absorbs any burst a person can cause; keep-alive (below) means
    far fewer connections are opened in the first place. A client that goes away mid-response (a closed tab, a sleeping laptop) is not an error worth a traceback."""
    request_queue_size = 256
    daemon_threads = True

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionError, TimeoutError, BrokenPipeError)) or (isinstance(exc, OSError) and getattr(exc, "winerror", 0) in (10053, 10054, 10058)):
            return   # the other end went away
        try:
            session_log().event("server_error", error=f"{type(exc).__name__}: {exc}"[:300])
        except Exception:
            pass


KEY_PAGE = """<!doctype html><meta charset="utf-8"><title>PlasBench: this window needs its key</title>
<body style="font-family:system-ui,sans-serif;max-width:640px;margin:48px auto;padding:0 20px;line-height:1.5;color:#1d2b25">
<script>
/* A reload of the SAME tab has lost its key from the address (the page removes it for privacy) and, for a browser that forgot its cookie, from the request. The tab itself still holds
   the key in its own session storage, which only this tab on this address can read: use it once. If the key is stale (PlasBench was restarted) the second answer arrives with the key
   in the address and this does not run again, so there is no loop. */
try { var t = sessionStorage.getItem("pb_t"); if (t && !location.search) { document.body.style.visibility = "hidden"; location.replace("/?t=" + encodeURIComponent(t)); } } catch (e) {}
</script>
<h2 style="margin-bottom:4px">This PlasBench window needs to be reopened</h2>
<p>PlasBench is running, but this address does not carry the key that protects it. That happens when PlasBench was restarted (it makes a new key every time it starts), or when this tab was
opened from an old bookmark or from the browser's history.</p>
<h3>To get back in</h3>
<ol>
<li><b>Click the PlasBench icon again.</b> It finds the running PlasBench and opens a new window with the right key. Nothing is lost: runs you started keep going.</li>
<li>Or run <code>plasbench ui</code> in a terminal: if PlasBench is already running it prints the full link and opens the window.</li>
<li>Or open the link PlasBench printed when it started (it ends with <code>?t=</code> and the key). The link is also in <code>~/.plasbench/ui/server.json</code>.</li>
</ol>
<p style="color:#5b6b63;font-size:14px">The key stops other programs and websites on this computer from using PlasBench on your behalf, which is why the bare address is refused.</p>
<p><button onclick="location.reload()" style="padding:6px 14px;font:inherit">Check again</button></p>
</body>"""
REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
REPLAY_SECONDS = 300


def make_handler(project: Project, jobs: Jobs):
    page_cache = {"mtime": 0, "body": b""}
    from . import studies
    terminal = Terminal(project.root, UI_HOME / "terminal_history.jsonl", lambda: studies.workspace(project.root),
                        on_record=lambda rec: session_log().event("terminal", **rec))

    # ---- the Updates card (plasbench/updatecheck.py, plasbench/updater.py): cached answer, the update job, what is running now ----
    def update_mode() -> str:
        from . import updater
        return updater.default_mode(project.local_env())

    def outside_running() -> list:
        from . import outside_runs
        try:
            return outside_runs.outside_runs(project.studies(), list(jobs.jobs.values()))
        except Exception:  # noqa: BLE001 - a study folder that cannot be read must not hide the window's own jobs
            return []

    def updates_view() -> dict:
        """Everything the card shows, from files and memory only (no network, no process): the cached check, the newest update job with its phases and result, what is running now."""
        from . import roots, updatecheck, updater
        mode = update_mode()
        installed = roots.read_version(project.root) or __version__   # the version in the PlasBench folder: after an update it is the new one while this server still runs the old code
        listing = jobs.list()
        job = updater.newest_upgrade_job(listing)
        summary = None
        if job:
            try:
                text = _tail_bytes(jobs._paths(job["id"])["log"], 256 * 1024).decode("utf-8", "replace")
            except OSError:
                text = ""
            summary = updater.job_summary(job, text)
        if updatecheck.due(installed, mode):    # a daemon thread, at most once a day: the answer shows up on the next read
            updatecheck.start_background(installed, update_mode)
        return {"current": installed, "running": __version__, "needs_restart": installed != __version__, "mode": mode, "check": updatecheck.state(installed, mode), "job": summary,
                "active": updater.active_work(listing, outside_running()), "rollback": updater.rollback_info(project.root),
                "restart_supported": server_state.restart_support()[0], "folder": str(project.root)}

    def page() -> bytes:
        # BEGIN server state: __PAGE_VERSION__ is the version of the FILES on disk, __VERSION__ stays this server's; the page compares them (a stale server is shown at once)
        disk = server_state.disk_version()
        mtime = (PAGE_FILE.stat().st_mtime, disk)
        if mtime != page_cache["mtime"]:
            html = PAGE_FILE.read_text(encoding="utf-8")
            page_cache.update(etag=f"{mtime[0]:.6f}-{mtime[1]}-{__version__}", mtime=mtime, body=windowlife.render_page(html, __version__, disk, server_state.API_LEVEL).encode("utf-8"))   # window stability: the one place the placeholders are filled
        return page_cache["body"]
        # END server state

    # A request the page repeats after a dropped connection must not run twice (a second "start the benchmark"): the page sends a fresh id with each POST and repeats the SAME id
    # when it retries, and the server answers a repeat with the response of the first run instead of running it again.
    replays: dict = {}
    replay_lock = threading.Lock()

    def replay_prune():
        now = time.time()
        for key in [k for k, v in replays.items() if now - v["t"] > REPLAY_SECONDS]:
            replays.pop(key, None)

    class Handler(BaseHTTPRequestHandler):
        server_version = "PlasBenchUI"
        protocol_version = "HTTP/1.1"   # keep-alive: one connection carries many requests (every response has a Content-Length)
        timeout = 60                    # an idle keep-alive connection is closed after a minute, so threads do not pile up

        def log_message(self, *args):
            pass

        def send(self, code, body: bytes, ctype="application/json; charset=utf-8", cookie=False, extra=None):
            rid = getattr(self, "_rid", None)
            if rid:
                with replay_lock:
                    entry = replays.get(rid)
                if entry is not None:
                    entry["resp"] = (code, body, ctype)
                    entry["event"].set()
            encoded = False
            if len(body) > 1400 and "gzip" in (self.headers.get("Accept-Encoding") or "") and ctype.startswith(("application/json", "text/html")) and not (extra or {}).get("report"):
                body, encoded = gzip_cached(body), True   # the page (470 KB) and the schema (220 KB) shrink about 5x; kept per body so it is compressed once
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            if encoded:
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Vary", "Accept-Encoding")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-PlasBench-Instance", str(int(SERVER_STARTED)))
            if self.close_connection:
                self.send_header("Connection", "close")   # tell the client, or it reuses a connection that is about to be closed
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if (extra or {}).get("etag"):   # server state: the page is revalidated on every load (no-cache + ETag of its file time and versions), so a normal reload is never stale
                self.send_header("ETag", extra["etag"])
                self.send_header("Cache-Control", "no-cache")
            else:
                self.send_header("Cache-Control", "public, max-age=3600" if (extra or {}).get("static") else "no-store")   # the mark is the same for a whole version
            if ctype.startswith("text/html") and not (extra or {}).get("report"):
                self.send_header("Content-Security-Policy",
                                 "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                                 "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            elif (extra or {}).get("report") and (ctype.startswith("text/html") or ctype.startswith("image/svg")):
                # run-file HTML/SVG is data from disk (a study bundle or a results folder can come from someone else): it keeps its inline script and style
                # (filters, 3D) but runs in an opaque origin (sandbox without allow-same-origin) with connect-src 'none', so it cannot call this window's API
                self.send_header("Content-Security-Policy", REPORT_CSP)
            if (extra or {}).get("page_seen") is not None:
                self.send_header("X-PlasBench-Page-Seen", extra["page_seen"])
            if (extra or {}).get("disposition"):
                self.send_header("Content-Disposition", f'attachment; filename="{extra["disposition"]}"')
            if cookie:
                self.send_header("Set-Cookie", f"{self.cookie_name()}={TOKEN}; Path=/; SameSite=Strict; HttpOnly; Max-Age=2592000")
            self.end_headers()
            self.wfile.write(body)

        def jsend(self, code, obj):
            self.send(code, json.dumps(obj, default=str).encode("utf-8"))

        def loopback(self):
            """True when the request comes from this computer itself (the window is localhost-only; the folder window opens on this machine's desktop)."""
            from . import native_picker     # loopback, and under WSL2 the Windows host a localhost-forwarded browser is seen as (see native_picker.is_local_client)
            return native_picker.is_local_client(str(self.client_address[0]), loadcache.ttl(("platform-kind",), 3600.0, native_picker._platform))

        def host_ok(self):
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
            return host in ("127.0.0.1", "localhost", "::1")

        def cookie_name(self):
            """Cookies are shared by every port of 127.0.0.1, so each server keeps its key under its own name: two PlasBench windows (or a stale server) can no longer overwrite each other's key."""
            return f"plasbench_token_{self.server.server_address[1]}"

        def token_ok(self):
            """True when ANY credential the request presents is this server's key: the X-PlasBench-Token header, the ?t= query, or this port's cookie.

            Before, the header or query was taken first and the cookie only when neither was present, so a window that still held the key of an EARLIER run of this server (a restart on the
            same port: the cookie already carried the new key) was refused for ever with a valid cookie in hand. Accepting the cookie when the header is stale is no weaker than accepting it
            when no header is sent, which the server always did: the cookie is HttpOnly (a page script cannot read it) and SameSite=Strict (a request started by another site does not carry
            it); the Host check (DNS rebinding) and the same-origin Origin check on every POST are unchanged and run before this; and every candidate is compared in constant time."""
            candidates = [self.headers.get("X-PlasBench-Token") or "", parse_qs(urlparse(self.path).query).get("t", [""])[0]]
            for part in (self.headers.get("Cookie") or "").split(";"):
                k, _, v = part.strip().partition("=")
                if k == self.cookie_name():
                    candidates.append(v)
            return any(c and secrets.compare_digest(c.encode("utf-8", "replace"), TOKEN.encode("utf-8")) for c in candidates)

        def reopen_window(self) -> dict:
            """What an older window's "Open the current window" asks for. It needs no key (the window asking has none that works), so it is made harmless: it only ever opens THIS server's own
            address, on this computer's desktop, through the same helper `plasbench ui` uses; it returns nothing private (no key, no path); the Host and same-origin checks of do_POST
            already ran (another website cannot call it); a window that is already open is brought to the front instead of a second one being opened; and it acts at most once per 10 s."""
            if WINDOWS.count():
                return {"ok": True, "opened": False, "message": "A current PlasBench window is already open. It was brought to the front: use that one and close this window."
                        if windowlife.bring_to_front() else "A current PlasBench window is already open: use that one and close this window."}
            if not REOPEN_LIMIT.allow():
                return {"ok": False, "opened": False, "message": "PlasBench was just asked to open a window. Wait a few seconds."}
            from . import appwindow
            url = f"http://127.0.0.1:{self.server.server_address[1]}/?t={quote(TOKEN)}"
            threading.Thread(target=lambda: appwindow.open_app_window(url, UI_HOME / "app-window", False, seen=lambda since: PAGE_SEEN["t"] > since), daemon=True).start()
            return {"ok": True, "opened": True, "message": "Opening the current PlasBench window. Close this old one."}

        def same_origin(self):
            origin = self.headers.get("Origin")
            return origin is None or urlparse(origin).netloc == self.headers.get("Host", "")

        def body(self, limit=5 * 2**20) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length > limit:
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
                return self.send(200, b"ok", "text/plain; charset=utf-8", extra={"page_seen": f"{PAGE_SEEN['t']:.3f}"})
            if path in ("/logo.svg", "/favicon.ico", "/icon.png"):   # the PlasBench mark: public, holds nothing private
                if path == "/logo.svg":
                    return self.send(200, loadcache.memo("logo", loadcache.sig(LOGO_FILE), LOGO_FILE.read_bytes), "image/svg+xml", extra={"static": True})
                from . import desktop
                return self.send(200, loadcache.memo(("png", path), __version__, lambda: desktop.png_bytes(64) if path == "/favicon.ico" else desktop.png_bytes(192)), "image/png", extra={"static": True})
            if not self.token_ok():
                return self.send(403, KEY_PAGE.encode("utf-8"), "text/html; charset=utf-8")
            if path == "/":
                PAGE_SEEN["t"] = time.time()   # a window loaded the page
                body = page()
                etag = f'"{page_cache["etag"]}"'   # BEGIN server state: revalidate the page every time
                if self.headers.get("If-None-Match") == etag:
                    self.send_response(304)
                    self.send_header("ETag", etag)
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return None
                return self.send(200, body, "text/html; charset=utf-8", cookie=True, extra={"etag": etag})   # END server state
            if path.startswith("/view/"):
                return self.serve_run_file(path[len("/view/"):])
            if not path.startswith("/api/"):
                return self.send(404, b"not found", "text/plain; charset=utf-8")
            try:
                return self.api_get(path[len("/api/"):], q)
            except netgate.Offline as exc:
                return self.jsend(503, exc.payload())
            except ghops.RiskError as exc:
                return self.jsend(409, {"error": str(exc), "risks": exc.risks, "needs_confirm": True})
            except ghops.GhError as exc:
                return self.jsend(401 if exc.action == "signin" else 400, {"error": str(exc), "action": exc.action, "detail": exc.detail})
            except runfolders.RunFolderError as exc:
                return self.jsend(exc.status, {"error": str(exc), "status": exc.status})
            except (FileNotFoundError, KeyError) as exc:
                return self.jsend(404, {"error": str(exc).strip("'")})
            except (PermissionError, ValueError, GitError) as exc:
                return self.jsend(400, {"error": str(exc)})
            except Exception as exc:  # the window shows it rather than hanging
                return self.jsend(500, {"error": f"{type(exc).__name__}: {exc}"})

        def api_get(self, route, q):
            state = load_state()
            # ---- native folder window (plasbench/native_picker.py): additive block, GET side ----
            if route in ("native-picker/capabilities", "native-picker/status"):
                if not self.loopback():
                    raise PermissionError("the computer's folder window can only be opened from the computer this window runs on")
                from . import native_picker
                if route == "native-picker/status":
                    return self.jsend(200, native_picker.status(q.get("id", "")))
                caps = loadcache.ttl(("native-picker-caps",), 60.0, native_picker.capabilities)     # only looks for programs; starts nothing
                return self.jsend(200, dict(caps, exe=None, **native_picker_extras(caps)))
            if route == "runtime":           # where the tools run; the Docker probe is a background loadcache probe, never on the page-load path
                return self.jsend(200, runtime_state(project))
            if route == "runtime/health":    # the last Docker health result only: starts nothing (POST runs the checks)
                return self.jsend(200, docker_health_state())
            if route == "docker/setup":      # the Docker item of the tools setup: chip, diagnosis, plan; Re-check = ?refresh=1 (a cached background probe, never on the page-load path)
                return self.jsend(200, docker_setup_state(project.root, q.get("refresh") == "1"))
            if route == "docker/offer":      # "run in Docker instead": the docker probe runs in the background (loadcache.swr), never on the page-load path
                return self.jsend(200, docker_offer_state(project.root))
            # ---- end native folder window ----
            if route == "info":
                info = project.info()
                info["token_header"] = "X-PlasBench-Token"
                return self.jsend(200, info)
            if route == "schema":   # built from the argparse parser once (at start-up, in the background), then served as ready-made bytes
                return self.send(200, schema_bytes())
            # ---- Report an issue (plasbench/issue_report.py): the redacted diagnostics block, in-process and bounded ----
            if route == "issue-report":
                if not self.loopback():
                    raise PermissionError("the diagnostics can only be prepared from the computer this window runs on")
                return self.jsend(200, issue_report_state(project.root, q))
            # ---- end Report an issue ----
            if route == "update-check":
                from . import updatecheck
                netgate.require("github", "check for updates")
                return self.jsend(200, updatecheck.check(__version__, updatecheck.fetch_latest))
            if route == "updates":           # the Updates card: cached check + the update job + what is running (never contacts the network)
                return self.jsend(200, updates_view())
            if route == "net/status":              # the Online / Offline indicator and the gating of every internet-dependent control
                names = [n for n in (q.get("services") or "").split(",") if n in netgate.SERVICES] or None
                # The connection check goes over the network (up to the 5 s timeout): it must never sit on the page-load path. A recent answer is served as it is, an old one at once
                # and refreshed in the background; with none yet the page gets a neutral "checking" answer (nothing greyed out) and the probe runs. The Check again button
                # (?t=...) is the only caller that waits for a real probe. Starting a job or a git action still calls netgate.require, which checks for real.
                key = ("net", tuple(names or ()))
                if q.get("t"):
                    loadcache.forget(key)
                    from . import netcheck
                    netcheck.clear_cache()      # netcheck remembers each service for 10 s: the button wants a real probe
                found, ready = loadcache.swr(key, NET_TTL, lambda: netgate.status(names), block=bool(q.get("t")), wait=0.3)
                out = dict(found) if ready else {"online": True, "state": "assumed_online", "checking": True, "checked": time.time(), "services": {}, "advice": []}
                out["commands"] = {k: (v if v is not None else None) for k, v in netgate.NET_COMMANDS.items()}
                out["subcommands"] = netgate.SUBCOMMAND_NET
                out["forced_offline"] = netgate.forced_offline()
                out["offline_install"] = netgate.offline_install_profiles()
                return self.jsend(200, out)
            if route == "github/account":
                return self.jsend(200, ghsignin.account(github_cmd()))
            if route == "github/signin/status":
                return self.jsend(200, signin().status())
            if route == "env":
                if q.get("refresh") == "1":
                    loadcache.clear()   # the Check again button: probe the computer for real
                checks, _ = loadcache.swr(("env", str(project.root)), PROBE_TTL, project.env_checks)
                return self.jsend(200, {"checks": checks})
            if route == "tools":   # rows from the cached registry; `installed` from the remembered PATH probe, never waiting on it (checking=True until it answers)
                if q.get("refresh") == "1":
                    loadcache.clear()
                tools = project.tools(block=False)
                return self.jsend(200, {"tools": tools, "pending": sum(1 for t in tools if t.get("checking"))})
            # -- BEGIN scan a folder for isolates (plasbench/isolate_scan.py) --
            if route == "isolates/scan/status":
                return self.jsend(200, iso_scans().status(q.get("id", "")))
            # -- END scan a folder for isolates --
            # BEGIN window stability
            if route == "windows":   # how many windows pinged recently (ids are random and not returned in full): used by `plasbench ui` and `plasbench ui-state`
                return self.jsend(200, {"alive": WINDOWS.count(), "ids": [w[:6] for w in WINDOWS.alive()], "pid": os.getpid(), "port": self.server.server_address[1]})
            # END window stability
            # BEGIN server state
            if route == "server-state":   # is this server older than the files on disk (an update while the window was open)? Stats a few files, spawns nothing
                return self.jsend(200, loadcache.ttl("server-state", 3.0, lambda: server_state.state(project.root)))
            # END server state
            # BEGIN workflow steps
            if route == "workflow":
                from . import workflow_steps
                # Read from files (the chain, the settings), so remembered for a few seconds; any change made through the window clears it (do_POST), and a saved setting shows at once.
                return self.jsend(200, loadcache.ttl(("workflow", str(project.root)), 5.0, lambda: workflow_steps.payload(project.root, workflow_steps.current_values(project.settings()))))
            # END workflow steps
            if route == "intake/defaults":
                return self.jsend(200, project.intake_defaults())
            if route == "intake/template":
                kind = q.get("kind", "local")
                module = project.intake()
                if kind not in module.TEMPLATES:
                    raise ValueError(f"unknown template '{kind}'")
                return self.jsend(200, {"kind": kind, "file": module.TEMPLATES[kind][0], "text": module.template_text(kind, project.root)})
            if route == "prereg":
                return self.jsend(200, project.prereg())
            if route == "settings":
                return self.jsend(200, {"settings": project.settings_resolved(), "local_env": str(project.local_env_path())})
            if route == "cohorts":
                return self.jsend(200, {"cohorts": project.cohorts()})
            if route == "cohorts/info":
                from . import cohort_info
                return self.jsend(200, cohort_info.info(project.root, q.get("name", "")))
            if route == "runs":
                return self.jsend(200, {"runs": project.runs(state.get("runs", []))})
            if route == "files/read":
                return self.jsend(200, read_study_file(project.root, q.get("path", "")))
            if route == "browse":
                return self.jsend(200, browse(q.get("path", ""), q.get("files") == "1", project, q.get("hidden") == "1", q.get("refresh") == "1"))
            if route == "docs":
                return self.jsend(200, {"docs": project.docs()})
            if route == "doc":
                name = q.get("name", "")
                allowed = {d["name"] for d in project.docs()}
                if name not in allowed:
                    raise FileNotFoundError(name)
                return self.jsend(200, {"name": name, "text": (project.root / name).read_text(encoding="utf-8", errors="replace")})
            if route.startswith("git/"):
                from . import gitops
                repo = self.git_repo(q.get("repo"))
                what = route[len("git/"):]
                if what == "status":
                    info = gitops.info(repo) if repo else {"installed": bool(gitops.find_git()), "is_repo": False}
                    choices = self.git_choices()
                    info["is_workspace"] = bool(repo) and Path(os.path.realpath(repo)) == Path(os.path.realpath(choices["workspace"]))
                    info.update(choices, gh_logged_in=gitops.gh_logged_in() if gitops.find_gh() else False,
                                gh=bool(gitops.find_gh()), repo=str(repo) if repo else "")
                    return self.jsend(200, info)
                if what == "log":
                    return self.jsend(200, {"log": gitops.log(repo, int(q.get("n", 40)))})
                if what == "branches":
                    return self.jsend(200, {"branches": gitops.branches(repo)})
                if what == "files":
                    return self.jsend(200, gitops.files(repo))
                if what == "diff":
                    return self.jsend(200, {"diff": gitops.diff(repo, q.get("path", ""), q.get("staged") == "1")})
                if what == "show":
                    return self.jsend(200, {"text": gitops.show(repo, q.get("rev", ""))})
                if what == "file":
                    return self.jsend(200, gitops.file_state(repo, q.get("path", "")))
                if what == "commit":
                    return self.jsend(200, gitops.commit_detail(repo, q.get("rev", "")))
                if what == "scan":
                    return self.jsend(200, {"findings": gitops.scan_staged(repo)})
                if what == "heavy":
                    return self.jsend(200, {"files": gitops.heavy_tracked(repo)})
                if what == "gitignore":
                    return self.jsend(200, gitops.gitignore_parts(repo))
                if what == "checkignore":
                    return self.jsend(200, gitops.check_ignore(repo, q.get("path", "")))
                raise FileNotFoundError(f"no such API: {route}")
            if route == "terminal":
                return self.jsend(200, terminal.state(block=False))
            if route == "sessions":
                log = session_log()
                events = log.events(q.get("session", ""), int(q.get("limit", 500)))
                for e in events:
                    e["text"] = describe_event(e)
                return self.jsend(200, {"session": log.session, "shown": q.get("session") or log.session,
                                        "sessions": log.sessions()[:30], "events": events, "file": str(log.path)})
            if route == "sessions/script":
                log = session_log()
                sid = q.get("session", "") or log.session
                if not re.fullmatch(r"[0-9]{8}-[0-9]{6}", sid):
                    raise ValueError("not a session id")
                body = log.script(project.root, sid).encode("utf-8")
                return self.send(200, body, "text/x-shellscript; charset=utf-8",
                                 extra={"disposition": f"plasbench-session-{sid}.sh"})
            if route == "platform":
                if q.get("refresh") == "1":
                    loadcache.clear()
                found, ready = loadcache.swr("platform", PLATFORM_TTL, _platform_probe, block=False, wait=0.5)
                return self.jsend(200, found if ready else {"pending": True})
            if route == "computer":
                # CPU, memory, limits, the Windows host behind WSL, and every drive (plasbench/computer_info.py). Each call is a fresh look; the drives that
                # appeared or went away since the previous call come back in "change". Probes fail to "unknown", never to an error.
                from . import computer_info, studies
                where = {"data folder": str(project.path_setting("DATA_DIR", "data")), "workspace": str(studies.workspace(project.root))}
                if q.get("study"):
                    where["current study"] = q["study"]
                local = project.local_env()
                over = {k: os.environ.get(k) or local.get(k) for k in ("THREADS", "MEMORY_GB")}
                if q.get("refresh") == "1":
                    loadcache.forget(("computer-host", True))      # Check again: ask the Windows host (PowerShell / wmic) for real
                    loadcache.forget(("computer-host", False))
                return self.jsend(200, computer_info.report(where, over))
            if route == "workspace":
                from . import studies, workspace
                info = workspace.describe(project.root)
                info["studies"] = project.studies() if info["available"] else []
                info["recent"] = [r for r in state.get("workspaces", []) if r != info["path"]][:8]
                return self.jsend(200, info)
            if route == "workspace/check":
                from . import workspace
                return self.jsend(200, workspace.check(q.get("path", "")))
            if route == "fs/list":
                from . import studies
                return self.jsend(200, runfolders.list_dir(project.root, studies.workspace(project.root), q.get("path", ""), studies.external_folders(project.root)))
            if route == "fs/properties":
                from . import studies
                return self.jsend(200, runfolders.properties(project.root, studies.workspace(project.root), q.get("path", ""), studies.external_folders(project.root)))
            if route == "runs/facts":              # what deleting a run folder would remove, shown before the user confirms
                from . import studies
                ws = studies.workspace(project.root)
                real = runfolders.check_deletable(project.root, ws, Path.home(), q.get("path", ""), state.get("runs", []), jobs.running_results(), studies.external_folders(project.root))
                return self.jsend(200, runfolders.facts(ws, real))
            if route == "runs/status":             # the Run status panel: same confinement as the other run routes (a study's results folder, or a listed run folder)
                from . import studies
                from .cli import configured_data_dir
                ws = studies.workspace(project.root)
                real = runfolders.check_deletable(project.root, ws, Path.home(), q.get("path", ""), state.get("runs", []), (), studies.external_folders(project.root))
                study = real.parent if (real.parent / "study.json").is_file() else None
                log_dir = (study / "logs") if study else real.parent / "logs"
                data_dir = configured_data_dir(project.root)
                if study:
                    try:
                        recorded = json.loads((study / "study.json").read_text(encoding="utf-8")).get("data_dir")
                        data_dir = Path(recorded) if recorded else data_dir
                    except (OSError, ValueError):
                        pass
                return self.jsend(200, run_status_json(project.root, real, log_dir, data_dir))
            if route == "studies/facts":           # what a delete or archive would involve, shown before the user confirms
                from . import study_manage
                return self.jsend(200, study_manage.facts(project.root, q.get("name", "")))
            if route == "studies/archived":
                from . import study_manage
                return self.jsend(200, {"archived": study_manage.list_archived(project.root)})
            if route == "jobs":
                return self.jsend(200, {"jobs": jobs.list()})
            if route == "run-sessions":
                index = {r["path"]: i for i, r in enumerate(project.runs(state.get("runs", [])))}
                index = {loadcache.realpath(k): v for k, v in index.items()}
                from . import outside_runs, studies
                try:
                    outside = outside_runs.outside_runs(project.studies(), list(jobs.jobs.values()))
                except Exception:  # noqa: BLE001 - a study folder that cannot be read must not hide the window's own runs
                    outside = []
                for entry in outside:
                    entry["run_index"] = index.get(loadcache.realpath(entry["results"]))
                return self.jsend(200, {"sessions": jobs.sessions(index), "outside": outside, "server_started": SERVER_STARTED})
            if route.startswith("jobs/") and route.endswith("/activity"):
                return self.jsend(200, jobs.activity(route[len("jobs/"):-len("/activity")]))
            if route.startswith("jobs/"):
                return self.jsend(200, jobs.get(route[len("jobs/"):], int(q.get("offset", 0))))
            if route == "usertools":
                ut = project.user_tools()
                tools = ut.discover()
                return self.jsend(200, {"tools": [dict({"name": n, "display": t.display_name, "task": t.task, "track": t.track,
                                                        "mode": t.get("run", "mode"), "format": t.get("output", "format"), "tasks": t.tasks,
                                                        "formats_list": t.formats, "source": t.source_summary(),
                                                        "install": t.get("install", "method", "none"), "path": str(t.path)}, **user_tool_summary(t))
                                                  for n, t in sorted(tools.items())],
                                        "search_path": [str(p) for p in ut.search_path()], "upload_max_bytes": UPLOAD_MAX_BYTES,
                                        "placeholders": ut.PLACEHOLDERS, "formats": ut.FORMATS, "tasks": ut.TASKS,
                                        "tracks": ut.TRACKS, "install_methods": ut.INSTALL_METHODS, "task_help": ut.TASK_HELP,
                                        "format_help": ut.FORMAT_HELP, "source_help": ut.SOURCE_HELP, "schema": {k: sorted(v) for k, v in ut.SCHEMA.items()}})
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
        def drain_body(self):
            """Read and discard the request body of a request that is about to be refused. A client that is still sending when the server answers and closes sees a connection abort
            (Windows) instead of the 403; reading the body first lets it finish, and keeps the connection in step for the next request. A huge body is not read: the connection closes."""
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length > 5 * 2**20:
                self.close_connection = True
                return
            while length > 0:
                chunk = self.rfile.read(min(length, 65536))
                if not chunk:
                    self.close_connection = True
                    return
                length -= len(chunk)

        def do_POST(self):
            if not self.host_ok() or not self.same_origin():
                self.drain_body()
                return self.jsend(403, {"error": "request refused (not from this window)"})
            if unquote(urlparse(self.path).path) == "/api/reopen":   # window stability: token-free ON PURPOSE (an old window has no valid key to ask with); see reopen_window()
                self.drain_body()
                return self.jsend(200, self.reopen_window())
            if not self.token_ok():
                self.drain_body()
                return self.jsend(403, {"error": "missing or wrong session token"})
            route = unquote(urlparse(self.path).path)[len("/api/"):]
            rid = self.headers.get("X-PlasBench-Req") or ""
            if REQUEST_ID.match(rid):
                with replay_lock:
                    replay_prune()
                    entry = replays.get(rid)
                    if entry is None:
                        replays[rid] = {"t": time.time(), "event": threading.Event(), "resp": None}
                        self._rid = rid
                if entry is not None:   # the page is repeating a request: answer with the first run's response
                    self.body()   # read (and discard) the body so the connection stays in step
                    if entry["event"].wait(REPLAY_SECONDS) and entry["resp"]:
                        code, body, ctype = entry["resp"]
                        return self.send(code, body, ctype)
                    return self.jsend(504, {"error": "the first attempt of this request did not finish"})
            try:
                data = self.body(UPLOAD_BODY_MAX if route == "usertools/upload" else 5 * 2**20)
                try:
                    return self.api_post(route, data)
                finally:
                    loadcache.clear(probes=False)   # the window changed something: the short-lived lists (studies, real paths) are read again
            except netgate.Offline as exc:
                return self.jsend(503, exc.payload())
            except ghops.RiskError as exc:
                return self.jsend(409, {"error": str(exc), "risks": exc.risks, "needs_confirm": True})
            except ghops.GhError as exc:
                return self.jsend(401 if exc.action == "signin" else 400, {"error": str(exc), "action": exc.action, "detail": exc.detail})
            except runfolders.RunFolderError as exc:
                return self.jsend(exc.status, {"error": str(exc), "status": exc.status})
            except (FileNotFoundError, KeyError) as exc:
                return self.jsend(404, {"error": str(exc).strip("'")})
            except (PermissionError, ValueError, GitError) as exc:
                return self.jsend(400, {"error": str(exc)})
            except Exception as exc:
                return self.jsend(500, {"error": f"{type(exc).__name__}: {exc}"})

        def api_post(self, route, data):
            if route == "jobs":
                argv = data.get("argv")
                if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
                    raise ValueError("argv must be a non-empty list of strings")
                netgate.require_job(argv, data.get("env") or {}, "start this command", reads_present=lambda: reads_present(argv, data.get("env") or {}))
                return self.jsend(200, jobs.start(argv, data.get("label", ""), data.get("env") or None))
            if route == "github/signin/start":
                cmd = github_cmd()
                if not cmd:
                    raise ValueError("the GitHub CLI (gh) is not installed: " + " or ".join(ghsignin.install_commands()))
                netgate.require("github", "sign in to GitHub")
                try:
                    out = signin().start()
                except RuntimeError as exc:
                    raise ValueError(str(exc))
                session_log().event("github_signin_started", pid_id=out.get("pid_id"))        # the one-time code is not a secret to log, but nothing else is recorded either
                return self.jsend(200, out)
            if route == "github/op":
                return self.jsend(200, self.github_op(data))
            if route == "github/signin/cancel":
                return self.jsend(200, signin().cancel())
            if route == "github/signout":
                cmd = github_cmd()
                if not cmd:
                    raise ValueError("the GitHub CLI (gh) is not installed")
                out = ghsignin.sign_out(cmd)
                session_log().event("github_signout", ok=out["ok"])
                return self.jsend(200, out)
            if route == "github/signin/token":
                cmd = github_cmd()
                if not cmd:
                    raise ValueError("the GitHub CLI (gh) is not installed: " + " or ".join(ghsignin.install_commands()))
                netgate.require("github", "check the token")
                token = data.get("token")
                if not isinstance(token, str):
                    raise ValueError("send the token as text")
                out = ghsignin.sign_in_with_token(cmd, token)
                session_log().event("github_signin_token", user=out.get("user"))              # never the token
                return self.jsend(200, out)
            if route.startswith("jobs/") and route.endswith("/input"):
                text = data.get("text", "")
                if not isinstance(text, str):
                    raise ValueError("text must be a string")
                return self.jsend(200, jobs.answer(route[len("jobs/"):-len("/input")], text, bool(data.get("secret"))))
            if route.startswith("jobs/") and route.endswith("/resume"):
                return self.jsend(200, jobs.resume(route[len("jobs/"):-len("/resume")]))
            if route.startswith("jobs/") and route.endswith("/cancel"):
                return self.jsend(200, jobs.cancel(route[len("jobs/"):-len("/cancel")]))
            if route.startswith("jobs/") and route.endswith("/delete"):
                jobs.delete(route[len("jobs/"):-len("/delete")])
                return self.jsend(200, {"ok": True})
            if route == "validate":
                ok, message = ui_schema.validate_argv(data.get("argv") or [])
                return self.jsend(200, {"ok": ok, "message": message})
            # -- BEGIN scan a folder for isolates (plasbench/isolate_scan.py): reads only until "add" --
            if route == "isolates/scan":
                folder = str(data.get("path") or "").strip()
                if not folder:
                    raise ValueError("choose a folder to scan")
                if not Path(folder).expanduser().is_dir():
                    raise ValueError(f"{folder} is not a folder that can be read from here")
                depth = max(1, min(int(data.get("max_depth") or 6), 12))
                return self.jsend(200, {"id": iso_scans().start(Path(folder).expanduser(), depth)})
            if route == "isolates/scan/cancel":
                return self.jsend(200, iso_scans().cancel(str(data.get("id") or "")))
            if route == "isolates/add":
                from . import isolate_scan
                item = iso_scans().get(str(data.get("scan_id") or ""))
                if item["state"] != "done":
                    raise ValueError("that scan is not finished; scan again")
                data_dir, samples = project.intake_paths(data)
                chosen = data.get("selections") or {}
                if not isinstance(chosen, dict):
                    raise ValueError("selections must be an object")
                include = {str(x) for x in (data.get("include") or [])}
                link = str(data.get("link") or "copy")
                if link not in ("copy", "symlink", "hardlink"):
                    raise ValueError("link must be copy, symlink or hardlink")
                done = isolate_scan.stage(item["result"]["samples"], data_dir, samples, link=link, confirm=bool(data.get("confirm")),
                                          selections=chosen, root=project.root, include=include)
                session_log().event("isolates_added_from_folder", isolates=len(done["staged"]), samples=str(samples))
                return self.jsend(200, done)
            # -- END scan a folder for isolates --
            if route.startswith("intake/"):
                module = project.intake()
                what = route[len("intake/"):]
                if what == "scan":
                    paths = [str(p).strip() for p in (data.get("paths") or []) if str(p).strip()]
                    if not paths:
                        raise ValueError("choose at least one folder to look in")
                    return self.jsend(200, module.scan(paths, int(data.get("depth") or 3)))
                data_dir, samples = project.intake_paths(data)
                if what == "stage":
                    paths = [str(p).strip() for p in (data.get("paths") or []) if str(p).strip()]
                    if not paths:
                        raise ValueError("choose at least one folder to look in")
                    found = module.scan(paths, int(data.get("depth") or 3))
                    done = module.stage(found, data_dir, samples, data.get("only") or None, data.get("rename") or {}, data.get("organism") or {},
                                        str(data.get("link") or "copy"))
                    session_log().event("intake_staged", isolates=len(done["staged"]), samples=str(samples))
                    return self.jsend(200, done)
                if what == "sheet":
                    from validate_local_inputs import read_sheet
                    if not samples.is_file():
                        return self.jsend(200, {"exists": False, "samples": str(samples), "data_dir": str(data_dir), "rows": []})
                    rows = [{"sample_id": (r.get("sample_id") or "").strip(), "assembly_accession": (r.get("assembly_accession") or "").strip(),
                             "organism": (r.get("organism") or "").strip()} for r in read_sheet(samples) if (r.get("sample_id") or "").strip()]
                    return self.jsend(200, {"exists": True, "samples": str(samples), "data_dir": str(data_dir), "rows": rows})
                if what == "check":
                    return self.jsend(200, module.check(samples, data_dir, str(data.get("sample") or ""), deep=bool(data.get("deep", True)),
                                                        root=project.root, fix=bool(data.get("fix"))))
                if what == "labels":
                    return self.jsend(200, module.truth_rows(data_dir / str(data.get("sample") or "")))
                if what == "labels/save":
                    result = module.save_truth(data_dir / str(data.get("sample") or ""), data.get("labels") or {})
                    if result["ok"]:
                        session_log().event("intake_labels_saved", sample=str(data.get("sample")))
                    return self.jsend(200, result)
                raise FileNotFoundError(f"no such API: {route}")
            if route == "prereg/set":
                admin = project.prereg_admin()
                entry = admin.set_value(project.root, str(data.get("parameter", "")), str(data.get("value", "")), str(data.get("reason", "")), str(data.get("by", "")))
                session_log().event("prereg_changed", parameter=entry["parameter"], old=entry["old_value"], new=entry["new_value"], by=entry["decided_by"])
                return self.jsend(200, {"entry": entry, **project.prereg()})
            if route == "prereg/lock":
                admin = project.prereg_admin()
                admin.lock(project.root)
                session_log().event("prereg_locked")
                return self.jsend(200, project.prereg())
            if route == "settings":
                changes = data.get("changes") or {}
                if not isinstance(changes, dict):
                    raise ValueError("changes must be an object")
                local = project.save_local_env(changes)
                session_log().settings(changes)
                return self.jsend(200, {"local": local})
            if route == "git":
                return self.jsend(200, self.git_op(data))
            if route == "terminal/run":
                command = data.get("command", "")
                if not isinstance(command, str):
                    raise ValueError("command must be a string")
                return self.jsend(200, terminal.run(command))
            if route == "terminal/shell":
                terminal.use_shell(str(data.get("shell", "")))
                return self.jsend(200, terminal.state())
            if route == "shutdown":
                running = [j for j in jobs.list() if j["state"] in ("running", "cancelling")]
                keep = bool(data.get("keep"))   # leave the runs going: they are detached, and the next window finds them again
                if running and not data.get("force") and not keep:
                    return self.jsend(200, {"ok": False, "running": [j["label"] for j in running]})
                for job in ([] if keep else running):
                    try:
                        jobs.cancel(job["id"])
                    except (KeyError, ValueError):
                        pass
                session_log().event("quit", forced=bool(running) and not keep or None, kept_running=len(running) if keep else None)
                threading.Timer(0.3, self.server.shutdown).start()
                return self.jsend(200, {"ok": True})
            if route == "updates/check":     # the Check for updates button: asks GitHub now (a gated, bounded request) and remembers the answer
                from . import updatecheck
                try:
                    netgate.require("github", "check for updates")
                except netgate.Offline as exc:
                    updatecheck.save_cache({"error": exc.message, "error_kind": "offline", "checked_at": time.time()})
                else:
                    updatecheck.refresh(updates_view()["current"])
                return self.jsend(200, updates_view())
            if route == "updates/archive":   # what is known about a release file before the consent dialog: name, version, size, a .sha256 beside it
                from . import updatecheck, updater
                info = updater.inspect_archive(self.linux_path(str(data.get("path", ""))) if data.get("path") else "")
                info["current"] = updates_view()["current"]
                info["relation"] = updatecheck.relation(info["current"], info["version"]) if info["version"] else ""
                return self.jsend(200, info)
            if route == "updates/install":   # starts `plasbench upgrade ...` as a job; refused while anything runs unless force, never while another update runs
                from . import updater
                try:
                    view = updates_view()
                    plan = updater.plan(data, view["current"], view["check"], jobs.list(), outside_running(), resolve_path=lambda text: self.linux_path(text) if text else "", root=project.root)
                except updater.Refused as exc:
                    return self.jsend(409, exc.payload())
                netgate.require_job(plan["argv"], {}, "update PlasBench")
                job = jobs.start(plan["argv"], plan["label"], None)
                session_log().event("update_started", update=plan["kind"], to=plan["to"], forced=plan["forced"] or None)
                return self.jsend(200, {"job": job, "plan": plan})
            # BEGIN window stability
            if route == "window-ping":   # an open window says it is there (random id, no key): `plasbench ui` then brings it back instead of opening a second one
                return self.jsend(200, {"ok": True, "alive": WINDOWS.ping(str(data.get("id", "")), bool(data.get("visible", True)))})
            # END window stability
            # BEGIN server state
            if route == "server/restart":   # start a replacement server, then this one exits like Quit and keep running (detached runs are not touched)
                def release_port():   # window stability: the replacement is loaded and waits for THIS port: stop listening now (requests in flight finish; the process stays until the answer is sent)
                    HANDOFF["active"] = True
                    self.server.shutdown()
                    self.server.server_close()
                try:
                    result = server_state.restart(project.root, self.server.server_address[1], _instance_file(), spawn=server_state.spawn_detached, release=release_port)
                    if result.get("ok"):
                        session_log().event("quit", restart=True)
                        threading.Timer(1.5, self.server.shutdown).start()
                    return self.jsend(200, result)
                finally:
                    HANDOFF["done"].set()
            # END server state
            if route == "workspace/set":
                from . import workspace
                if any(j["state"] in ("running", "cancelling") for j in jobs.list()):
                    raise ValueError("a job is running: wait for it, or cancel it, before changing the workspace")
                report = workspace.check(data.get("path", ""))
                if not report["ok"]:
                    raise ValueError(report["errors"][0] if report["errors"] else "that folder cannot be used")
                path = Path(report["path"])
                if not path.exists():
                    if not data.get("create"):
                        return self.jsend(200, {"needs_create": True, "path": str(path)})
                    path.mkdir(parents=True)
                default = (project.root / "studies").resolve()
                # The default needs no setting; anything else is saved for this computer.
                project.save_local_env({"PLASBENCH_WORKSPACE": None if path.resolve() == default else str(path)})
                state = load_state()
                state["workspaces"] = [str(path)] + [w for w in state.get("workspaces", []) if w != str(path)][:7]
                save_state(state)
                session_log().event("workspace", path=str(path))
                out = workspace.describe(project.root)
                out["warnings"] = report["warnings"]
                return self.jsend(200, out)
            if route == "studies/create":
                from . import studies
                folder = studies.create(project.root, data.get("name", ""), data.get("note", ""), data.get("location") or None)
                session_log().event("study_created", path=str(folder))
                return self.jsend(200, {"path": str(folder)})
            if route == "studies/add_existing":
                from . import studies
                folder = studies.add_existing(project.root, self.linux_path(data.get("path", "")))
                session_log().event("study_added", path=str(folder))
                return self.jsend(200, {"path": str(folder), "name": folder.name})
            # ---- native folder window (plasbench/native_picker.py): additive block, POST side ----
            if route == "runtime/use":
                return self.jsend(200, runtime_use(project, str(data.get("runtime") or "")))
            if route == "runtime/test":
                return self.jsend(200, runtime_test(project))
            if route == "runtime/health":    # the Docker engine health checks: bounded, one at a time, remembered 30 s
                return self.jsend(200, docker_health_run(project, bool(data.get("refresh"))))
            if route in ("runtime/pull", "runtime/ready"):
                if route == "runtime/ready":
                    argv, label = ["check", "--yes"], "Make everything ready in Docker (tools and databases)"
                elif data.get("build"):
                    argv, label = ["runtime", "build", "--yes"] + (["--rebuild"] if data.get("rebuild") else []), "Build the PlasBench image on this computer"
                else:
                    argv, label = ["runtime", "pull", "--yes"], "Pull the PlasBench image"
                netgate.require_job(argv, {}, "start this command")
                return self.jsend(200, jobs.start(argv, label, None))
            if route == "docker/plan":       # the docker run command for chosen folders: built here, shown and copied, never run
                from . import docker_helper
                shell = data.get("shell") if data.get("shell") in ("posix", "powershell") else ("powershell" if os.name == "nt" else "posix")
                if data.get("mode") == "switch":
                    return self.jsend(200, docker_helper.switch_plan(str(project.root), str(data.get("data_dir") or ""), str(data.get("workspace") or ""), shell))
                return self.jsend(200, docker_helper.run_command([e for e in (data.get("folders") or []) if isinstance(e, dict)][:12], shell, str(data.get("image") or "plasbench:local"),
                                                                 str(data.get("command") or "bash")[:200], docker_helper.user_mounts() if docker_helper.in_docker() else None))
            if route in ("native-picker/open", "native-picker/cancel", "native-picker/front", "native-picker/selftest"):
                if not self.loopback():
                    raise PermissionError("the computer's folder window can only be opened from the computer this window runs on")
                from . import native_picker
                if route == "native-picker/selftest":
                    return self.jsend(200, native_picker_selftest())
                if route == "native-picker/cancel":
                    return self.jsend(200, native_picker.cancel(data.get("id")))
                if route == "native-picker/front":
                    return self.jsend(200, native_picker.bring_to_front(data.get("id")))
                kind = data.get("kind", "folder")
                started = native_picker.start(kind if kind in ("folder", "file", "save") else "folder", str(data.get("title", ""))[:200], data.get("initial") or None,
                                              data.get("filters") if isinstance(data.get("filters"), list) else None)
                return self.jsend(409 if started.get("busy") else 200, started)
            # ---- end native folder window ----
            if route == "fs/mkdir":
                from . import chooser
                made = chooser.make_folder(self.linux_path(data.get("parent", "")), data.get("name", ""))
                session_log().event("folder_created", path=made)
                return self.jsend(200, {"path": made})
            if route.startswith("studies/") and route[len("studies/"):] in ("meta", "rename", "clone", "archive", "restore", "delete", "export", "import", "delete_data", "unregister"):
                from . import study_manage as sm, studies, __version__
                action, name = route[len("studies/"):], (data.get("name") or "").strip()

                def busy():          # a run in progress that was started in this study
                    if action in ("restore", "import", "export", "meta", "clone"):
                        return False
                    try:
                        here = str(studies.study_path(project.root, name)).lower()
                    except ValueError:
                        return False
                    for j in jobs.list():
                        if j["state"] in ("running", "cancelling") and (here in (j.get("command") or "").lower() or f"--study {name}".lower() in (j.get("command") or "").lower()
                                                                          or f"--study={name}".lower() in (j.get("command") or "").lower()):
                            return True
                    return False
                if action == "meta":
                    out = sm.update_meta(project.root, name, data.get("note"), data.get("tags"))
                elif action == "rename":
                    out = {"path": str(sm.rename(project.root, name, data.get("new_name", ""), busy()))}
                elif action == "clone":
                    out = {"path": str(sm.clone(project.root, name, data.get("new_name", ""), bool(data.get("with_results"))))}
                elif action == "archive":
                    out = {"path": str(sm.archive(project.root, name, busy()))}
                elif action == "restore":
                    out = {"path": str(sm.restore(project.root, data.get("archive", "")))}
                elif action == "delete":
                    out = sm.delete(project.root, name, data.get("confirm", ""), busy())
                elif action == "delete_data":
                    out = sm.delete_data(project.root, name, data.get("confirm", ""), busy())
                elif action == "unregister":
                    out = {"removed": sm.remove_from_list(project.root, name)}
                elif action == "export":
                    stamp = time.strftime("%Y%m%d-%H%M%S")
                    target = Path(studies.workspace(project.root)) / ".exports" / f"{studies.valid_name(name)}-{stamp}.zip"
                    out = sm.export_bundle(project.root, name, target, bool(data.get("with_results")), __version__)
                else:
                    out = {"path": str(sm.import_bundle(project.root, Path(data.get("path", "")).expanduser(), (data.get("new_name") or "").strip() or None))}
                session_log().event("study_" + action, study=name)
                return self.jsend(200, out)
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
                gone = str(Path(str(data.get("path", ""))).resolve())
                state["runs"] = [r for r in state.get("runs", []) if r != data.get("path") and str(Path(r).resolve()) != gone]
                save_state(state)
                return self.jsend(200, {"ok": True})
            if route == "runs/delete":
                from . import studies
                ws = studies.workspace(project.root)
                state = load_state()
                ext = studies.external_folders(project.root)
                real = runfolders.check_deletable(project.root, ws, Path.home(), data.get("path", ""), state.get("runs", []), jobs.running_results(), ext)
                removed = runfolders.delete(project.root, ws, Path.home(), str(real), data.get("confirm", ""), state.get("runs", []), jobs.running_results(), ext)
                state["runs"] = [r for r in state.get("runs", []) if str(Path(r).resolve()) != str(real) and r != data.get("path")]
                save_state(state)
                session_log().event("run_deleted", path=str(real), files=removed["files"], bytes=removed["bytes"])
                return self.jsend(200, dict(removed, ok=True, freed_files=removed["files"], freed_bytes=removed["bytes"]))
            if route == "usertools/validate":
                return self.jsend(200, self.validate_manifest(data.get("text", "")))
            if route == "usertools/save":
                return self.jsend(200, self.save_manifest(data.get("text", ""), bool(data.get("overwrite"))))
            if route == "usertools/remove":
                ut = project.user_tools()
                try:
                    folder = ut.remove(data.get("name", ""))
                except ut.ManifestError as exc:
                    return self.jsend(400, {"error": str(exc)})
                return self.jsend(200, {"ok": True, "removed": str(folder)})
            if route == "usertools/upload":
                return self.jsend(200, store_tool_upload(data.get("name"), data.get("filename"), data.get("text")))
            if route == "reveal":
                return self.jsend(200, fsutil.reveal_typed(data.get("path", "")))
            raise FileNotFoundError(f"no such API: {route}")

        # ---------------------------------------------------------------- git (plasbench/gitops.py)
        def linux_path(self, text):
            from . import chooser
            return chooser.to_linux(text)

        def git_roots(self):
            from . import studies
            return [project.root, studies.workspace(project.root)] + studies.external_folders(project.root)

        def git_choices(self) -> dict:
            """Version control tracks your runs in ONE repository in the working directory (the workspace that holds every
            study): that is the first choice, marked tracked or not. A study that already has a repository of its own is
            still offered (marked); a study without one is covered by the working-directory repository. The PlasBench
            program folder is listed only when it already is a git checkout of its own (a developer's copy)."""
            from . import studies
            ws = studies.workspace(project.root)
            choices = [{"label": "Working directory: all studies" + ("" if (ws / ".git").exists() else "  (not tracked yet)"),
                        "path": str(ws), "kind": "workspace", "tracked": (ws / ".git").exists()}]
            choices += [{"label": f"Study with its own repository: {st['name']}", "path": st["path"], "kind": "study", "tracked": True}
                        for st in studies.list_studies(project.root) if (Path(st["path"]) / ".git").exists()]
            if (project.root / ".git").exists():
                choices.append({"label": "PlasBench program (developer checkout)", "path": str(project.root), "kind": "program"})
            return {"choices": choices, "workspace": str(studies.workspace(project.root))}

        def git_repo(self, requested=None):
            """The repository the Git page works on: the request's, else the saved one, else the working directory (the
            workspace that holds every study, where `git init` lives).
            Always inside the PlasBench folder or the workspace (gitops.valid_repo)."""
            from . import gitops
            from . import studies
            ws = studies.workspace(project.root)
            ws.mkdir(parents=True, exist_ok=True)
            saved = load_state().get("git_repo")
            if saved and not Path(saved).is_dir():
                saved = None
            chosen = requested or saved or str(ws)
            # a saved choice of the program folder that is not a checkout moves to the working directory
            if not requested and Path(chosen).resolve() == project.root.resolve() and not (project.root / ".git").exists():
                chosen = str(ws)
            try:
                return gitops.valid_repo(chosen, self.git_roots())
            except ValueError:
                if requested:
                    raise
                return gitops.valid_repo(str(ws), self.git_roots())

        def github_op(self, body: dict) -> dict:
            """Every GitHub action of the Version control page (plasbench/ghops.py): reads run now and return parsed data; writes run as jobs in the console; a merge that would go wrong
            is refused (409 with the risks) until the user confirmed them in the dialog."""
            from . import gitops
            op = str(body.get("op") or "")
            args = body.get("args") if isinstance(body.get("args"), dict) else {}
            if op not in ghops.READ_OPS | ghops.WRITE_OPS | ghops.LOCAL_OPS:
                raise ValueError("unknown GitHub action")
            repo = None if op in ("orgs", "repo_list", "repo_search") else self.git_repo(body.get("repo"))
            if op in ghops.LOCAL_OPS:
                if op == "branch_delete":
                    gitops.delete_branch(repo, args.get("name", ""))
                else:
                    gitops.create_tag(repo, args.get("name", ""), args.get("message", ""))
                session_log().event("github_" + op, name=args.get("name"))
                return {"ok": True}
            cmd = github_cmd()
            if not cmd:
                raise ValueError("the GitHub CLI (gh) is not installed: " + " or ".join(ghsignin.install_commands()))
            netgate.require("github", f"GitHub: {op}")
            if op in ghops.READ_OPS:
                if op == "branch_remote_list":
                    raise ValueError("unknown GitHub action")
                result, shown = ghops.run_read(op, cmd, repo, **args)
                return {"op": op, "result": result, "command": shown}
            if op == "pr_merge" and not body.get("risk_confirmed"):
                view, _ = ghops.run_read("pr_view", cmd, repo, number=args.get("number"))
                risks = ghops.merge_risks(view)
                if risks:
                    raise ghops.RiskError("Merging now would go wrong: " + "; ".join(risks) + ".", risks)
            if op in ("branch_delete_remote", "tag_push"):
                command, program = ghops.git_build(op, gitops.find_git() or "git", repo, **args), "git"
            else:
                command, program = ghops.build(op, cmd, repo, **args), "gh"
            job = jobs.start_git(command, f"github {op.replace('_', ' ')}", repo, program=program)
            session_log().event("github_" + op, job=job["id"])
            return {"job": job, "command": ghops.shown(command)}

        def git_op(self, body: dict) -> dict:
            """Every git action. Quick ones run now; fetch/pull/push/clone/GitHub run as jobs in the console."""
            from . import gitops
            op = body.get("op", "")
            repo = self.git_repo(body.get("repo")) if op != "clone" else None
            if op == "repo_set":
                state = load_state()
                state["git_repo"] = str(repo)
                save_state(state)
                return {"repo": str(repo)}
            if op == "init":
                from . import studies
                ws = Path(os.path.realpath(studies.workspace(project.root)))
                here = Path(os.path.realpath(repo))
                if here != ws:
                    where = ("a study is covered by the working-directory repository: start it in the working directory "
                             f"({ws}) and every study is tracked there" if here.parent == ws else
                             "the PlasBench program folder is replaced by updates and is not tracked here")
                    raise ValueError("Version control is for your runs, in one repository in the working directory: " + where + ".")
                return gitops.init(repo, body.get("branch") or "main", bool(body.get("first_commit")),
                                   body.get("message") or "Track PlasBench runs", kind="runs")
            if op == "identity":
                gitops.set_identity(repo, body.get("name"), body.get("email"), body.get("scope") or "local")
                return {"ok": True}
            if op == "stage":
                gitops.stage(repo, body.get("paths") or None)
                return {"ok": True}
            if op == "unstage":
                gitops.unstage(repo, body.get("paths") or None)
                return {"ok": True}
            if op == "untrack":
                return gitops.untrack(repo, body.get("paths") or [])
            if op == "gitignore_save":
                return gitops.save_gitignore(repo, body.get("text", ""))
            if op == "commit":
                return gitops.commit(repo, body.get("message", ""), body.get("override", ""))
            if op == "branch_create":
                gitops.create_branch(repo, body.get("name", ""), bool(body.get("switch", True)))
                return {"ok": True}
            if op == "checkout":
                gitops.checkout(repo, body.get("name", ""))
                return {"ok": True}
            if op == "remote_set":
                gitops.set_remote(repo, body.get("name") or "origin", body.get("url", ""))
                return {"ok": True}
            if op == "remote_remove":
                gitops.remove_remote(repo, body.get("name", ""))
                return {"ok": True}
            if op in ("fetch", "pull", "push", "clone", "gh_login", "gh_setup_git", "gh_create"):
                if op == "push" and not body.get("confirm"):
                    info = gitops.info(repo)
                    raise ValueError(f"confirm the push: {info.get('ahead', 0)} commit(s) on '{info.get('branch')}' will be "
                                     f"sent to " + (info["remotes"][0]["url"] if info.get("remotes") else "the remote"))
                gitops.require_network(op, repo, body.get("url") or "")
                dest = None
                if op == "clone":
                    dest = gitops.valid_repo(str(Path(body.get("dest", "")).parent), self.git_roots()) / Path(body.get("dest", "")).name
                command = gitops.argv(op, repo, url=body.get("url"), dest=str(dest) if dest else None,
                                      name=body.get("name"), visibility=body.get("visibility"))
                job = jobs.start_git(command, f"git {op}", dest.parent if dest else repo)
                if op == "clone":
                    state = load_state()
                    state["git_repo"] = str(dest)
                    save_state(state)
                return {"job": job}
            raise ValueError("unknown git action")

        def validate_manifest(self, text):
            import tempfile
            ut = project.user_tools()
            # The richer, pure result (per-task derivation, source summary, outputs) comes from user_tools.validate_text;
            # the keys the window already reads (ok, problems, warnings, row, plan) keep their meaning.
            rich = ut.validate_text(text)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "plasbench-tool.ini"
                path.write_text(text, encoding="utf-8")
                try:
                    tool = ut.UserTool(path)
                except ut.ManifestError as exc:
                    problems = [l.strip()[2:] for l in str(exc).splitlines()[1:] if l.strip().startswith("- ")] or [str(exc)]
                    return dict(rich, ok=False, problems=problems)
                if tool.name in ut.builtin_tools():
                    return dict(rich, ok=False, problems=[f"'{tool.name}' is a built-in PlasBench tool; choose another name"])
                warnings = list(rich.get("warnings", []))
                for key in ("script",):
                    if tool.get("install", key) and not Path(tool.resolve(tool.get("install", key))).is_file():
                        message = f"[install] {key} = {tool.get('install', key)} must be saved beside the manifest"
                        if message not in warnings:
                            warnings.append(message)
                return dict(rich, ok=True, problems=[], warnings=warnings, row=tool.capability_row(),
                            rows=[tool.capability_row(task) for _, task in tool.task_ids()], plan=tool.install_plan())

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
            with open(target, "w", encoding="utf-8", newline="\n") as _fh:
                _fh.write(text.replace("\r\n", "\n"))
            return {"ok": True, "path": str(target), "folder": str(folder)}

    return Handler


def _instance_file() -> Path:
    return UI_HOME / "server.json"


def _page_seen_of(port: int):
    """(alive, instance, page_seen) of the PlasBench server on `port`, from its /healthz (None, None, 0.0 when it does not answer)."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{int(port)}/healthz", timeout=3) as r:
            if r.status == 200 and r.read(8).startswith(b"ok"):
                return True, r.headers.get("X-PlasBench-Instance"), float(r.headers.get("X-PlasBench-Page-Seen") or 0)
    except (OSError, ValueError):
        pass
    return None, None, 0.0


def _call_old_server(url: str, route: str, body=None, timeout: float = 4.0):
    """GET (or POST with `body`) /api/<route> of a running PlasBench window given its address (with the key). The parsed JSON, or None when it does not answer or has no such route."""
    import urllib.request
    u = urlparse(url)
    key = parse_qs(u.query).get("t", [""])[0]
    headers = {"X-PlasBench-Token": key, "Host": f"127.0.0.1:{u.port}"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers.update({"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{u.port}"})
    try:
        with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{u.port}/api/{route}", data=data, headers=headers), timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError):
        return None


def replace_stale_instance(url: str, ask=None, say=print, wait: float = 10.0) -> bool:
    """A second `plasbench ui` (or a click on the icon) finds a window already running for this folder. If that window runs OLDER code than this command (it was started before an
    upgrade and kept running), reusing it would show the old program again however often the user 'restarts': ask it to exit (like Quit and keep running: runs are detached and keep going)
    and let the caller start a fresh one. True when the old one is gone and a new server should be started; False to reuse it."""
    ask = ask or _call_old_server
    st = ask(url, "server-state")
    old = (st or {}).get("running_version") or (st or {}).get("started_version") or ""
    if st is not None and (st.get("kind") not in ("loaded_code",) and old == __version__):
        return False   # the same version (or a two-installs problem a new process cannot fix): reuse it
    who = f"pid {(st or {}).get('server', {}).get('pid', '?')}, port {urlparse(url).port}"
    say(f"The PlasBench window that is already running ({who}) is older ({old or 'before 0.5.2'}) than this PlasBench ({__version__}); replacing it. Your runs keep going in the background.")
    res = ask(url, "shutdown", {"keep": True})
    if not (res or {}).get("ok"):
        say("It did not agree to close; using it as it is. Close it with Quit in its window, then start PlasBench again.")
        return False
    port = urlparse(url).port
    end = time.time() + wait
    while time.time() < end and _page_seen_of(port)[0]:
        time.sleep(0.2)
    try:
        _instance_file().unlink()
    except OSError:
        pass
    return True


def running_instance(root: Path):
    """The URL of a PlasBench window already serving this PlasBench folder, or None.

    The record file (server.json) can outlive its server, and another program can take over its port; so the server must answer /healthz AND be the one the record names (the
    record holds the server's start time, which /healthz repeats). A record left by a crashed server is removed."""
    try:
        info = json.loads(_instance_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if Path(info.get("root", "")).resolve() != Path(root).resolve():
        return None
    try:
        alive, instance, _seen = _page_seen_of(info["port"])
    except (ValueError, KeyError):
        return None
    if alive and (info.get("started") is None or str(info.get("started")) == str(instance)):
        return info["url"]
    if not alive:
        try:   # nothing is serving: the record is stale
            _instance_file().unlink()
        except OSError:
            pass
    return None


class _LaunchLock:
    """One launch at a time: a second click while the first is still starting PlasBench waits for it (and then only brings the window back) instead of starting a second server."""
    def __init__(self, wait: float = 40.0):
        self.path = UI_HOME / "launch.lock"
        self.wait = wait
        self.held = False

    def __enter__(self):
        UI_HOME.mkdir(parents=True, exist_ok=True)
        end = time.time() + self.wait
        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                self.held = True
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > 60:   # a launch that died: do not wait for it
                        self.path.unlink()
                        continue
                except OSError:
                    continue
                if time.time() > end:
                    return self   # give up waiting; carry on without the lock rather than doing nothing
                time.sleep(0.3)

    def __exit__(self, *exc):
        if self.held:
            self.held = False
            try:
                self.path.unlink()
            except OSError:
                pass


_ISO_SCANS = []


def iso_scans():
    """The window's background folder scans (plasbench/isolate_scan.Scans): start, poll, cancel. Bounded; a scan only reads."""
    if not _ISO_SCANS:
        from .isolate_scan import Scans
        _ISO_SCANS.append(Scans())
    return _ISO_SCANS[0]


# BEGIN window stability
HANDOFF = {"active": False, "done": threading.Event()}   # a restart in progress: this server has released its port and must stay alive until the restart's answer is sent


def servers_dir() -> Path:
    return UI_HOME / "servers"


def write_server_record(port: int, url: str, root) -> Path:
    """One record per running server (server.json is the last one started): `plasbench ui-state` lists them all. It holds the key like server.json does, so it is private (0600)."""
    folder = servers_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{int(port)}.json"
    path.write_text(json.dumps({"url": url, "port": int(port), "pid": os.getpid(), "started": int(SERVER_STARTED), "root": str(Path(root).resolve()), "version": __version__}), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def bind_server(host: str, port: int, handler, wait: float = 0.0, ready=None, sleep=time.sleep, clock=time.time, make=None):
    """The server on `port`, or on the next free one. With `wait` > 0 (the replacement of a restarting window) it keeps trying THAT port for up to `wait` seconds, because the old server
    is releasing it, before it moves to the next port: a restart used to hop 8770 -> 8771 -> 8770. `ready` is a file created just before the first attempt: the old server releases its port
    when it appears (the replacement is loaded and only needs the port), so a replacement that fails to start never costs the old window."""
    make = make or (lambda addr: UIServer(addr, handler))
    if ready:
        try:
            Path(ready).write_text(str(os.getpid()), encoding="utf-8")
        except OSError:
            pass
    end = clock() + wait
    while True:
        try:
            return make((host, port))
        except OSError:
            if clock() >= end:
                break
            sleep(0.2)
    for candidate in range(port + 1, port + 20):
        try:
            return make((host, candidate))
        except OSError:
            continue
    return None


def port_listeners(port: int, run=subprocess.run) -> list:
    """The processes listening on 127.0.0.1:<port> as `ss -ltnp` shows them: [{"pid": int|None, "name": str}] ([] when ss is missing or nothing listens). Best effort, read-only."""
    try:
        done = run(["ss", "-ltnpH", f"sport = :{int(port)}"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    out = []
    for line in (done.stdout or "").splitlines():
        m = re.search(r'users:\(\("([^"]*)",pid=(\d+)', line)
        out.append({"pid": int(m.group(2)) if m else None, "name": m.group(1) if m else "(another user's process)"})
    return out


def running_servers(ping=None, ask=None, listeners=None, ports=range(8770, 8790)) -> dict:
    """Every PlasBench window server on this computer, for `plasbench ui-state`: {"servers": [...], "windows_alive": n, "warnings": [...]}. Keys are never included.
    Sources: the per-server records (UI_HOME/servers/*.json and server.json) and a probe of the ports PlasBench uses (a server started by an older version has no record)."""
    ping = ping or _page_seen_of
    ask = ask or _call_old_server
    listeners = listeners or port_listeners
    records, seen, out = [], set(), []
    for path in sorted(servers_dir().glob("*.json")) + [_instance_file()]:
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
            records.append(rec)
        except (OSError, ValueError):
            continue
    for rec in records:
        try:
            port = int(rec["port"])
        except (KeyError, ValueError, TypeError):
            continue
        if port in seen:
            continue
        seen.add(port)
        alive, instance, _seen = ping(port)
        entry = {"port": port, "pid": rec.get("pid"), "version": rec.get("version") or "", "started": rec.get("started"), "root": rec.get("root"), "recorded": True,
                 "running": bool(alive), "is_recorded_server": bool(alive) and (rec.get("started") is None or str(rec.get("started")) == str(instance))}
        if alive and entry["is_recorded_server"] and rec.get("url"):
            st = ask(rec["url"], "server-state") or {}
            win = ask(rec["url"], "windows")
            entry.update(version=st.get("running_version") or entry["version"], stale=st.get("stale"), api_level=st.get("api_level"), windows_alive=(win or {}).get("alive"))
        out.append(entry)
    todo = [p for p in ports if p not in seen]
    from concurrent.futures import ThreadPoolExecutor   # a closed port on Windows takes ~2 s to refuse: probe them side by side
    with ThreadPoolExecutor(max_workers=max(1, min(10, len(todo)))) as pool:
        probed = list(pool.map(ping, todo))
    for port, (alive, instance, _seen) in zip(todo, probed):
        if alive:
            seen.add(port)
            out.append({"port": port, "pid": None, "version": "", "started": None, "root": None, "recorded": False, "running": True, "is_recorded_server": False, "windows_alive": None})
    warnings = []
    for e in out:
        e["listeners"] = listeners(e["port"])
        e["other_listeners"] = [x for x in e["listeners"] if e["pid"] and x["pid"] != e["pid"]]
        if e["recorded"] and not e["running"]:
            warnings.append(f"port {e['port']}: a record names pid {e['pid']} but nothing answers as PlasBench there" + (f" (something else listens: {', '.join(str(x['name']) for x in e['listeners'])})" if e["listeners"] else " (the server has stopped)"))
        elif e["other_listeners"]:
            warnings.append(f"port {e['port']}: besides PlasBench (pid {e['pid']}), these also listen: " + ", ".join(f"{x['name']} (pid {x['pid']})" for x in e["other_listeners"]))
        if not e["recorded"]:
            warnings.append(f"port {e['port']}: a PlasBench server answers but has no record (started by an older version): stop it with Quit in its window")
    running = [e for e in out if e["running"]]
    if len(running) > 1:
        warnings.append(f"{len(running)} PlasBench servers are running: only the newest window is needed; close the older windows and use Quit in them")
    alive = sum(int(e.get("windows_alive") or 0) for e in running)
    if alive > 1:
        warnings.append(f"{alive} PlasBench windows reported in recently: more than one is open. Close the extra ones")
    if running:
        warnings.append("Windows opened before this version do not report in. If pop-ups keep appearing, close EVERY PlasBench window, then run plasbench ui once.")
    return {"servers": out, "windows_alive": alive, "warnings": warnings}


def reuse_window(url: str, open_window, ask=None, front=None) -> str:
    """`plasbench ui` found a server already running. If one of its windows is alive (it pinged in the last 25 s), do not open another: bring it to the front. Otherwise open one.
    Returns the line to print. `open_window()` -> description; `ask(url, route)` -> the server's answer or None (an older server has no `windows` route: then a window is opened as before)."""
    ask = ask or _call_old_server
    front = front or windowlife.bring_to_front
    live = ask(url, "windows")
    if live and live.get("alive"):
        raised = False
        try:
            raised = bool(front())
        except Exception:   # noqa: BLE001 - raising the window is a courtesy
            pass
        return f"PlasBench is already open: {url}" + ("" if raised else "  (it could not be brought to the front: look for the PlasBench window in the taskbar)")
    return "Opened: " + open_window()
# END window stability


def serve(root: Path, host: str = "127.0.0.1", port: int = 8770, open_browser: bool = True, tab: bool = False,
          new_instance: bool = False, port_wait: float = 0.0, handoff_file: str = ""):
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("ERROR: the PlasBench window only listens on this computer (127.0.0.1).")
    from . import appwindow, platform_info
    # One window per PlasBench folder: a second start (a second click on the desktop icon) brings it back.
    lock = _LaunchLock() if not new_instance else None
    if lock:
        lock.__enter__()
    existing = None if new_instance else running_instance(root)
    if existing and replace_stale_instance(existing):
        existing = None
    if existing:
        if lock:
            lock.__exit__()
        print(f"PlasBench is already running: {existing}", flush=True)
        if open_browser:
            port = int(urlparse(existing).port or 0)
            print(reuse_window(existing, lambda: appwindow.open_app_window(existing, UI_HOME / "app-window", tab, seen=lambda since: _page_seen_of(port)[2] > since)), flush=True)   # window stability
        return
    # Every check and command started from the window finds the plasbench environment's tools, however the window was
    # started (a desktop icon does not run `conda activate`).
    os.environ["PATH"] = platform_info.tools_path()
    if hasattr(signal, "SIGHUP"):
        try:   # closing the terminal that started `plasbench ui` sends SIGHUP and would stop PlasBench (and the window with it); Quit in the window or Ctrl+C still stop it
            signal.signal(signal.SIGHUP, signal.SIG_IGN)
        except (ValueError, OSError):
            pass
    project = Project(root)
    jobs = Jobs(project)
    handler = make_handler(project, jobs)
    warm(project, jobs)
    from . import updatecheck, updater
    updatecheck.start_background(__version__, lambda: updater.default_mode(project.local_env()))   # at most once a day, only with UPDATE_CHECK=auto; a thread, never on the load path
    server = bind_server(host, port, handler, wait=port_wait, ready=handoff_file or None)   # window stability: a restart's replacement waits for the old server's port
    if server is None:
        if lock:
            lock.__exit__()
        raise SystemExit(f"ERROR: no free port between {port} and {port + 19}")
    url = f"http://127.0.0.1:{server.server_address[1]}/?t={quote(TOKEN)}"
    server_state.reset(root=root, port=server.server_address[1])   # the baseline of this server: the version and the content of the modules it has loaded now
    UI_HOME.mkdir(parents=True, exist_ok=True)
    record = _instance_file()
    record.write_text(json.dumps({"url": url, "port": server.server_address[1], "pid": os.getpid(), "started": int(SERVER_STARTED),
                                  "root": str(Path(root).resolve())}), encoding="utf-8")
    server_record = write_server_record(server.server_address[1], url, root)   # window stability
    if lock:
        lock.__exit__()   # the record exists: a second click now finds this server
    try:
        os.chmod(record, 0o600)   # it holds this session's key
    except OSError:
        pass
    session_log().event("server_start", version=__version__, root=str(Path(root).resolve()),
                        port=server.server_address[1])
    print(f"PlasBench {__version__} window: {url}", flush=True)
    print("Keep this running while you use the window; close it with Quit in the window, or Ctrl+C here.", flush=True)
    if open_browser:
        threading.Timer(0.6, lambda: print("Opened: " + appwindow.open_app_window(url, UI_HOME / "app-window", tab, seen=lambda since: PAGE_SEEN["t"] > since),
                                           flush=True)).start()
    try:
        failures = 0
        while True:   # an unexpected error in the accept loop must not take the window down with it
            try:
                server.serve_forever()
                break
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                failures += 1
                session_log().event("server_error", error=f"serve loop: {type(exc).__name__}: {exc}"[:300])
                if failures > 20:
                    raise
                time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nClosed the PlasBench window.")
    finally:
        if lock:
            lock.__exit__()
        server.server_close()
        if HANDOFF["active"]:   # window stability: a restart released the port early; stay until the restart's answer has reached the window
            HANDOFF["done"].wait(40)
            time.sleep(0.3)
        try:
            if json.loads(server_record.read_text(encoding="utf-8")).get("pid") == os.getpid():
                server_record.unlink()
        except (OSError, ValueError):
            pass
        session_log().event("server_stop")
        try:
            if json.loads(record.read_text(encoding="utf-8")).get("pid") == os.getpid():
                record.unlink()
        except (OSError, ValueError):
            pass
