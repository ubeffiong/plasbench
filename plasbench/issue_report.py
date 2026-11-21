"""`plasbench issue-report`: everything a maintainer needs to understand a problem, in one redacted Markdown block to paste into a GitHub issue.

Read-only and offline-safe: it only looks (version and path of this program, the computer, the Docker and conda versions when those programs exist, the study's run
status and the tail of its logs) and never installs, starts, stops, downloads or changes anything. The only network access is the opt-in `--net` probe (the same
check as `plasbench net`) and, with `--open`, your browser opening the GitHub page. Nothing is ever sent by PlasBench itself.

Everything that goes into the report passes through `redact()`: tokens and keys, passwords, Authorization and Cookie headers, URLs with credentials, e-mail addresses,
IP addresses, the home-folder user name and (unless --hostname) this computer's name. Environment variables are never listed wholesale: only an allow-list is read.
The result is capped (MAX_BYTES) and says where it was shortened.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

from . import __version__, platform_info, roots
from .sessionlog import SECRET_NAME, redact_command

ISSUES_URL = "https://github.com/ubeffiong/plasbench/issues"
NEW_ISSUE_URL = ISSUES_URL + "/new"
MAX_BYTES = 200 * 1024            # the whole report
MAX_URL = 6000                    # a prefilled GitHub address longer than this is not sent; the user pastes the file instead
DEFAULT_LOG_LINES = 60
MAX_LINE = 600                    # one log line is cut here
COMMAND_TIMEOUT = 8               # seconds for each read-only command (docker version, conda --version, ...)
ENV_ALLOW_EXACT = ("READ_SOURCE", "WSL_DISTRO_NAME", "WSL_INTEROP", "CONDA_DEFAULT_ENV", "MAX_ISOLATES", "THREADS", "MAX_PARALLEL_SAMPLES")
ENV_ALLOW_PREFIX = ("PLASBENCH_",)
FAILED_LOGS = 5                   # at most this many failing assembler / tool logs are included

# ----------------------------------------------------------------------------------------------------------------------------------------------- redaction
_TOKEN_SHAPES = re.compile(
    r"(?<![A-Za-z0-9_-])(?:gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,}|sk-[A-Za-z0-9_-]{16,}|(?:AKIA|ASIA)[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}|glpat-[A-Za-z0-9_-]{16,}|hf_[A-Za-z0-9]{30,}|npm_[A-Za-z0-9]{30,}|pypi-[A-Za-z0-9_-]{30,})")
_COOKIE = re.compile(r"(?im)^(\s*(?:set-)?cookie\s*:).*$")
_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S)
_HEX_TOKEN = re.compile(r"(?<![0-9A-Za-z])[0-9a-fA-F]{32,}(?![0-9A-Za-z])")
_LONG_MIXED = re.compile(r"(?<![A-Za-z0-9_/.-])(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{40,}(?![A-Za-z0-9_/.-])")
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_IPV4 = re.compile(r"(?<![\w.-])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\w.-]*\w)")
_IPV6 = re.compile(r"(?<![\w:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:])")
_WIN_HOME = re.compile(r"(?i)\b([A-Za-z]:[\\/]+Users[\\/]+)(?!<user>)([^\\/\s:\"'<>|*?]+)")
_WSL_WIN_HOME = re.compile(r"(?i)(/mnt/[a-z]/Users/)(?!<user>)([^/\s\"']+)")
_UNC_HOME = re.compile(r"(?i)([\\/]{2}wsl(?:\.localhost|\$)[\\/]+[^\\/\s]+[\\/]+home[\\/]+)(?!<user>)([^\\/\s\"']+)")
_LINUX_HOME = re.compile(r"(?<![\w.])(/home/)(?!<user>)([^/\s\"':]+)")
_MAC_HOME = re.compile(r"(?<![\w.])(/Users/)(?!<user>)([^/\s\"':]+)")


def _ipv4(match):
    return match.group(0) if match.group(0).startswith("127.") or match.group(0) in ("0.0.0.0", "255.255.255.255") else "<ip>"


def _ipv6(match):
    text = match.group(0)
    return "<ip>" if "::" in text or text.count(":") >= 5 else text


def _home_forms(home):
    home = str(home or "")
    if not home:
        return []
    forms = {home, home.replace("\\", "/"), home.replace("/", "\\")}
    return sorted((f for f in forms if len(f) > 3), key=len, reverse=True)


def redact(text, home=None, user=None, hostname=None) -> str:
    """The text with every secret shape, address, e-mail, home-folder user name and (when given) host name removed. Idempotent."""
    out = str(text or "")
    out = _PRIVATE_KEY.sub("<private key removed>", out)
    out = _COOKIE.sub(r"\1 <hidden>", out)
    out = redact_command(out)                                   # NAME=secret, --token VALUE, Authorization/Bearer, user:pass@host, ghp_/github_pat_/sk-/AKIA shapes
    out = _TOKEN_SHAPES.sub("<hidden>", out)
    out = _HEX_TOKEN.sub("<hex token removed>", out)
    out = _LONG_MIXED.sub("<token removed>", out)
    for form in _home_forms(home):
        out = out.replace(form, "~")
    out = _WSL_WIN_HOME.sub(r"\1<user>", out)
    out = _WIN_HOME.sub(r"\1<user>", out)
    out = _UNC_HOME.sub(r"\1<user>", out)
    out = _LINUX_HOME.sub(r"\1<user>", out)
    out = _MAC_HOME.sub(r"\1<user>", out)
    out = _EMAIL.sub("<email>", out)
    out = _IPV4.sub(_ipv4, out)
    out = _IPV6.sub(_ipv6, out)
    if user and len(user) >= 3:
        out = re.sub(r"(?<![\w-])" + re.escape(user) + r"(?![\w-])", "<user>", out)
    if hostname and len(hostname) >= 3:
        out = re.sub(r"(?<![\w-])" + re.escape(hostname) + r"(?![\w-])", "<host>", out, flags=re.I)
    return out


def safe_env(environ=None) -> dict:
    """The only environment variables the report may mention: PLASBENCH_* (never one named like a secret), READ_SOURCE-like run settings, WSL_DISTRO_NAME,
    and DOCKER_HOST reduced to its scheme (unix://, npipe://, tcp://: the address after it can hold a host or a password)."""
    environ = os.environ if environ is None else environ
    out = {}
    for name in sorted(environ):
        value = str(environ[name])
        if name == "DOCKER_HOST":
            out[name] = (value.split("://", 1)[0] + "://<address hidden>") if "://" in value else "<set, not a URL>"
        elif name in ENV_ALLOW_EXACT or name.startswith(ENV_ALLOW_PREFIX):
            out[name] = "<hidden>" if SECRET_NAME.search(name) else value[:200]
    return out


# ------------------------------------------------------------------------------------------------------------------------------------------------ helpers
def fence(text: str, lang: str = "") -> str:
    """A fenced code block whose fence is longer than any run of backticks inside the text."""
    text = str(text).rstrip("\n")
    longest = max([len(m) for m in re.findall(r"`+", text)] or [0])
    bar = "`" * max(3, longest + 1)
    return f"{bar}{lang}\n{text}\n{bar}"


def _decode(raw: bytes) -> str:
    if b"\x00" in raw[:200]:                                    # wsl.exe -l -v answers in UTF-16
        try:
            return raw.decode("utf-16-le", "replace").replace("\ufeff", "").replace("\r", "")
        except Exception:  # noqa: BLE001
            pass
    return raw.decode("utf-8", "replace").replace("\r", "")


def run_command(argv, timeout=COMMAND_TIMEOUT, runner=None) -> tuple:
    """(ok, text) of one read-only command, bounded. A missing program or a timeout is an answer, never an exception."""
    runner = runner or subprocess.run
    try:
        done = runner(argv, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError:
        return False, "not found"
    except subprocess.TimeoutExpired:
        return False, f"no answer within {timeout} s"
    except OSError as exc:
        return False, f"could not be run ({exc.strerror or exc})"
    text = (_decode(done.stdout or b"") + ("\n" if done.stdout and done.stderr else "") + _decode(done.stderr or b"")).strip()
    return done.returncode == 0, text or f"(no output, exit {done.returncode})"


def tail_lines(path, count, max_bytes=400_000) -> list:
    try:
        with open(path, "rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            data = handle.read().decode("utf-8", "replace")
    except OSError:
        return []
    lines = [ln.rstrip("\r") for ln in data.splitlines()]
    if size > max_bytes and lines:
        lines = lines[1:]                                       # the first line may be cut in half
    return [ln if len(ln) <= MAX_LINE else ln[:MAX_LINE] + " ...[line cut]" for ln in lines[-count:]]


def _read_tsv(path) -> list:
    try:
        rows = [ln.rstrip("\r\n").split("\t") for ln in Path(path).read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
    except OSError:
        return []
    if not rows:
        return []
    head = rows[0]
    return [dict(zip(head, r + [""] * (len(head) - len(r)))) for r in rows[1:]]


def _gb(n) -> str:
    return f"{n / 2**30:.1f} GB"


def _disk(path) -> str:
    try:
        use = shutil.disk_usage(path)
    except OSError as exc:
        return f"not readable ({exc.strerror or exc})"
    return f"{_gb(use.free)} free of {_gb(use.total)}"


def _first_existing(path):
    p = Path(path)
    for cand in [p] + list(p.parents):
        if cand.exists():
            return cand
    return None


# ----------------------------------------------------------------------------------------------------------------------------------------------- sections
class Report:
    """The sections, each built in its own guard so one failing look never loses the others."""

    def __init__(self, root, how="", study=None, include_logs=DEFAULT_LOG_LINES, net=False, server=True, environ=None, runner=None, which=None,
                 home=None, hostname=False, now=None):
        self.root, self.how, self.study_name = (Path(root) if root else None), how, study
        self.include_logs = max(0, int(include_logs))
        self.net, self.server = net, server
        self.environ = os.environ if environ is None else environ
        self.runner = runner
        self.which = which or shutil.which
        self.home = str(home if home is not None else Path(os.path.expanduser("~")))
        try:
            self.user = os.path.basename(self.home.rstrip("/\\")) or self.environ.get("USER") or self.environ.get("USERNAME") or ""
        except Exception:  # noqa: BLE001
            self.user = ""
        self.hostname = "" if hostname else _safe_hostname()
        self.now = now or time.gmtime()
        self.sections = []          # (title, markdown)
        self.notes = []             # what was left out and why
        self.study_dir = None

    # one place where text becomes safe
    def clean(self, text):
        return redact(text, self.home, self.user, self.hostname)

    def cmd(self, argv, timeout=COMMAND_TIMEOUT):
        if not self.which(argv[0]):
            return False, "not found"
        return run_command(argv, timeout, self.runner)

    def add(self, title, builder):
        try:
            body = builder()
        except Exception as exc:  # noqa: BLE001 - a section that fails says so; the rest still appear
            body = f"(this part could not be collected: {type(exc).__name__}: {exc})"
        if body:
            self.sections.append((title, body))

    # ---- 1. PlasBench itself
    def s_plasbench(self):
        rows = [("version (this command)", __version__), ("program location", str(Path(__file__).resolve().parent))]
        rows.append(("Python running it", f"{platform.python_version()} ({sys.executable})"))
        if getattr(sys, "frozen", False):
            rows.append(("packaged build", "yes"))
        if self.root:
            rows += [("PlasBench folder", f"{self.root} ({self.how or 'found'})"), ("version in that folder", roots.read_version(self.root) or "?")]
            rows.append(("folder kind", "git checkout (source)" if (self.root / ".git").exists() else "release archive or installer copy (no .git)"))
        else:
            rows.append(("PlasBench folder", "NOT FOUND (pass --project-root, or set PLASBENCH_HOME)"))
        rec = roots.read_install()
        rows.append(("install record (~/.plasbench/install.json)",
                     ", ".join(f"{k}={rec[k]}" for k in ("version", "root", "python", "recorded_at") if rec.get(k)) if rec else "none (not installed with install.sh / plasbench upgrade)"))
        via = self.environ.get("PLASBENCH_STARTED_VIA")
        if via:
            rows.append(("started via", via))
        try:
            from . import docker_helper
            if docker_helper.in_docker():
                rows.append(("running inside Docker", "yes"))
        except Exception:  # noqa: BLE001
            pass
        launcher = self.which("plasbench")
        rows.append(("`plasbench` on PATH", launcher or "not on PATH (run as `python -m plasbench`)"))
        return _table(rows)

    # ---- 2. the computer
    def s_system(self):
        kind = "WSL2 (Windows Subsystem for Linux)" if platform_info.in_wsl() else {"windows": "Windows (native)", "macos": "macOS", "linux": "Linux"}[platform_info.os_kind()]
        uname = platform.uname()
        rows = [("environment", kind), ("system", f"{uname.system} {uname.release}"), ("kernel/build", uname.version[:200]), ("machine", platform_info.arch()),
                ("distribution", platform_info.distro()), ("CPU threads", str(os.cpu_count() or "?"))]
        if self.environ.get("WSL_DISTRO_NAME"):
            rows.append(("WSL distribution", self.environ["WSL_DISTRO_NAME"]))
        mem = _meminfo()
        if mem:
            rows.append(("memory", mem))
        for name, argv in (("conda", ["conda", "--version"]), ("mamba", ["mamba", "--version"]), ("micromamba", ["micromamba", "--version"])):
            if self.which(argv[0]):
                ok, text = self.cmd(argv)
                rows.append((name, text.splitlines()[0] if text else "?"))
        if not any(self.which(n) for n in ("conda", "mamba", "micromamba")):
            rows.append(("conda / mamba", "not found on PATH"))
        rows.append(("active conda environment", self.environ.get("CONDA_DEFAULT_ENV") or "none"))
        text = _table(rows)
        if os.name == "nt" or self.which("wsl.exe"):
            ok, out = self.cmd(["wsl.exe", "-l", "-v"])
            text += "\n\n`wsl.exe -l -v`:\n" + fence(out)
        env = safe_env(self.environ)
        if env:
            text += "\n\nSettings seen in the environment (allow-listed names only):\n" + fence("\n".join(f"{k}={v}" for k, v in env.items()))
        return text

    # ---- 3. Docker
    def s_docker(self):
        if not self.which("docker"):
            return "Docker: `docker` not found on PATH."
        lines = []
        for label, argv in (("docker --version", ["docker", "--version"]),
                            ("docker context show", ["docker", "context", "show"]),
                            ("docker version (client / server)", ["docker", "version", "--format", "client {{.Client.Version}} / server {{.Server.Version}}"]),
                            ("docker info (engine, storage, root dir)", ["docker", "info", "--format",
                                                                         "engine {{.ServerVersion}}; os {{.OperatingSystem}}; driver {{.Driver}}; root dir {{.DockerRootDir}}"])):
            ok, text = self.cmd(argv)
            lines.append(f"$ {label}\n{(text or '')[:600]}")
        host = safe_env(self.environ).get("DOCKER_HOST")
        if host:
            lines.append(f"DOCKER_HOST={host}")
        return fence("\n\n".join(lines))

    # ---- 4. the window and ui-state
    def s_window(self):
        try:
            from . import cli
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                cli.ui_state_command(_JsonArgs, self.root, self.how)
            info = json.loads(buf.getvalue() or "{}")
        except Exception as exc:  # noqa: BLE001
            return f"`plasbench ui-state` could not be summarised ({type(exc).__name__}: {exc}). Run it yourself and paste its output."
        rows = [("this process", f"{info.get('running', {}).get('version', '?')}"),
                ("PlasBench folder version", (info.get("project_root") or {}).get("version") or "?"),
                ("pip says", (info.get("pip") or {}).get("version") or "not installed with pip")]
        copies = info.get("copies") or []
        rows.append(("copies of plasbench found", "; ".join(f"{c.get('path')} = {c.get('version') or '?'}" for c in copies) or "none"))
        st = ((info.get("server") or {}).get("state")) or {}
        if st:
            rows.append(("running window", "stale: " + str(st.get("reason") or st.get("kind")) if st.get("stale") else "up to date with its folder"))
        else:
            rows.append(("running window", "no window recorded as running"))
        problems = info.get("problems") or []
        rows.append(("mismatches", "; ".join(problems) if problems else "none"))
        return _table(rows)

    # ---- 5. tools (a read-only look: `plasbench check` can install, so it is not run)
    def s_tools(self):
        if not self.root:
            return ""
        rows = _read_tsv(self.root / "config" / "tool_installers.tsv")
        if not rows:
            return ""
        found, missing = [], []
        for row in rows:
            cmd = (row.get("verify_command") or "").split()
            if not cmd:
                continue
            (found if self.which(cmd[0]) else missing).append(row.get("tool", cmd[0]))
        text = f"{len(found)} of {len(found) + len(missing)} registered tools have their program on this shell's PATH (looked up only; nothing was run).\n"
        text += "Missing from PATH: " + (", ".join(missing) if missing else "none") + "\n"
        text += ("(Tools live in the `plasbench` conda environment: run this inside it, `conda activate plasbench`, for an accurate list. "
                 "For the full tool and database check run `plasbench check`; it asks before installing anything.)")
        return text

    # ---- 6. internet
    def s_net(self):
        offline = self.environ.get("PLASBENCH_OFFLINE")
        head = f"PLASBENCH_OFFLINE={offline}\n" if offline else ""
        if not self.net:
            return head + "Not probed (this report makes no network calls). Run `plasbench net`, or add `--net` to this command, to test NCBI, ENA, GitHub, conda and Docker registries."
        from . import netcheck
        answer = netcheck.check(timeout=4, cache_seconds=30)
        lines = [f"state: {answer.get('state')}"] + [f"{name}: {'ok' if r.get('ok') else 'NOT reachable (' + str(r.get('kind') or r.get('error') or '?') + ')'}" for name, r in sorted((answer.get("services") or {}).items())]
        return head + fence("\n".join(lines))

    # ---- 7. disks
    def s_disk(self):
        places = [("home", self.home), ("temporary folder", os.environ.get("TMPDIR") or os.environ.get("TEMP") or "/tmp")]
        if self.root:
            places.append(("PlasBench folder", str(self.root)))
            try:
                from . import studies
                places.append(("workspace (studies)", str(studies.workspace(self.root))))
            except Exception:  # noqa: BLE001
                pass
        if self.study_dir:
            places.append(("this study", str(self.study_dir)))
        settings = _local_settings(self.root, self.environ) if self.root else {}
        for key in ("DATA_DIR", "PLASBENCH_DB_DIR"):
            if settings.get(key):
                places.append((key, settings[key]))
        rows, seen = [], set()
        for label, path in places:
            real = _first_existing(path)
            sig = str(real)
            if real is None or sig in seen:
                if real is None:
                    rows.append((label, f"{path}: folder does not exist"))
                continue
            seen.add(sig)
            rows.append((label, f"{path}: {_disk(real)}"))
        return _table(rows)

    # ---- 8. settings that differ from defaults
    def s_settings(self):
        if not self.root:
            return ""
        values = _local_settings(self.root, self.environ)
        if not values:
            return "No settings were changed in config/local.env (all defaults)."
        lines = []
        for key in sorted(values):
            lines.append(f"{key}=" + ("<hidden>" if SECRET_NAME.search(key) else values[key][:200]))
        return "Settings changed in config/local.env (secrets are never shown):\n" + fence("\n".join(lines))

    # ---- 9. the study: run status, newest run log, failing assemblies and tools
    def pick_study(self):
        from . import studies
        if self.study_name:
            folder = studies.study_path(self.root, self.study_name)
            if not folder.is_dir():
                known = ", ".join(e["name"] for e in studies.list_studies(self.root)[:20]) or "none"
                raise StudyNotFound(f"there is no study named {self.study_name} (known studies: {known})")
            return folder
        listed = studies.list_studies(self.root)
        for entry in listed:
            if entry.get("available", True):
                return Path(entry["path"])
        return None

    def s_study(self):
        if not self.root:
            return ""
        folder = self.study_dir
        if folder is None:
            return ("No study was found in the workspace, so there is no run to describe. If the problem is with a study kept elsewhere, add `--study NAME`; "
                    "if it happened before any run, the sections above are what matters.")
        results, logs = folder / "results", folder / "logs"
        parts = [f"Study folder: {folder.name}"]
        record = {}
        try:
            record = json.loads((folder / "study.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        if record:
            parts.append(f"cohort/sample sheet: {record.get('cohort') or record.get('sample_sheet') or '?'}; runs recorded: {len(record.get('runs', []))}")
            runs = record.get("runs") or []
            if runs and isinstance(runs[-1], dict) and runs[-1].get("command"):
                parts.append("last command: `" + str(runs[-1]["command"])[:400] + "`")
        status_script = self.root / "python" / "run_status.py"
        if status_script.is_file() and results.is_dir():
            ok, text = run_command([sys.executable, str(status_script), "--results-dir", str(results)], timeout=20, runner=self.runner)
            parts.append("**Run status** (`plasbench status`):\n" + fence("\n".join(text.splitlines()[:60])))
        samples = len(_read_tsv(results / "assembly_status.tsv"))
        if samples:
            counts = {}
            for row in _read_tsv(results / "assembly_status.tsv"):
                counts[row.get("status", "?")] = counts.get(row.get("status", "?"), 0) + 1
            parts.append("Isolates in stage 3: " + ", ".join(f"{n} {s}" for s, n in sorted(counts.items())))
        if self.include_logs:
            parts += self.log_blocks(results, logs)
        else:
            parts.append("(log lines were not included: --include-logs 0)")
        return "\n\n".join(parts)

    def log_blocks(self, results, logs) -> list:
        n = self.include_logs
        parts = []
        runs = sorted(logs.glob("run_*.log"), key=lambda p: p.stat().st_mtime, reverse=True) if logs.is_dir() else []
        if runs:
            lines = tail_lines(runs[0], n)
            parts.append(f"**Last {len(lines)} lines of the newest run log** (`logs/{runs[0].name}`):\n" + fence("\n".join(lines)))
        elif logs.is_dir():
            parts.append("No `logs/run_*.log` file in the study (the run may not have started, or RUN_CONSOLE_LOG=0).")
        errors = logs / "run_errors.log"
        if errors.is_file():
            lines = tail_lines(errors, min(n, 20))
            if lines:
                parts.append("**`logs/run_errors.log`** (last lines):\n" + fence("\n".join(lines)))
        failing = [r for r in _read_tsv(results / "assembly_status.tsv") if r.get("status") == "failed"]
        if failing:
            parts.append(f"**Failed assemblies**: {len(failing)}" + (f" (the first {FAILED_LOGS} are shown)" if len(failing) > FAILED_LOGS else ""))
        for row in failing[:FAILED_LOGS]:
            sample = row.get("sample", "?")
            log = logs / f"{sample}.spades.log"
            body = [f"sample {sample}: {row.get('reason', '')}"]
            if row.get("cause"):
                body.append(f"PlasBench diagnosis: cause={row['cause']}; advice: {row.get('advice', '')}")
            body += self.classify(log, sample)
            lines = tail_lines(log, n)
            body.append(f"--- last {len(lines)} lines of logs/{log.name}" + ("" if log.is_file() else " (file not found)"))
            body += lines
            parts.append(fence("\n".join(body)))
        bad_tools = [r for r in _read_tsv(results / "tool_status.tsv") if r.get("status") == "failed"]
        if bad_tools:
            parts.append(f"**Failed tool runs**: {len(bad_tools)}" + (f" (the first {FAILED_LOGS} are shown)" if len(bad_tools) > FAILED_LOGS else ""))
        for row in bad_tools[:FAILED_LOGS]:
            sample, tool = row.get("sample", "?"), row.get("tool", "?")
            log = logs / f"{sample}.{tool}.log"
            lines = tail_lines(log, n)
            parts.append(fence("\n".join([f"{tool} on {sample}: {row.get('reason', '')}", f"--- last {len(lines)} lines of logs/{log.name}" + ("" if log.is_file() else " (file not found)")] + lines)))
        return parts

    def classify(self, log, sample) -> list:
        script = (self.root / "python" / "assembler_diagnosis.py") if self.root else None
        if not script or not script.is_file() or not log.is_file():
            return []
        try:
            if str(script.parent) not in sys.path:
                sys.path.insert(0, str(script.parent))
            import assembler_diagnosis as ad
            res = ad.diagnose("\n".join(tail_lines(log, 400)), {"sample": sample, "log": f"logs/{log.name}"})
            return [f"classifier: {res['cause']} ({res['confidence']} confidence): {res['title']}"] + [f"  evidence: {e}" for e in res["evidence_lines"][-3:]]
        except Exception as exc:  # noqa: BLE001
            return [f"classifier: not available ({type(exc).__name__})"]

    # ---- assembling
    def build(self, max_bytes=MAX_BYTES) -> dict:
        if self.root:
            try:
                self.study_dir = self.pick_study()
            except ValueError as exc:
                raise StudyNotFound(str(exc))
        self.add("PlasBench", self.s_plasbench)
        self.add("Computer", self.s_system)
        self.add("Docker", self.s_docker)
        self.add("Window and installed copies (`plasbench ui-state`)", self.s_window)
        self.add("Tools (read-only look)", self.s_tools)
        self.add("Internet", self.s_net)
        self.add("Free disk space", self.s_disk)
        self.add("Settings", self.s_settings)
        self.add("Latest study and run", self.s_study)
        stamp = time.strftime("%Y-%m-%d %H:%M UTC", self.now)
        head = (f"<!-- PlasBench issue report, {stamp}, plasbench {__version__}. Generated by `plasbench issue-report`; secrets, e-mail and IP addresses, "
                "your user name and this computer's name were removed. Read it once before posting. -->\n## PlasBench diagnostics\n")
        blocks = [f"\n### {title}\n{self.clean(body)}\n" for title, body in self.sections]
        text, truncated = _cap(head, blocks, max_bytes)
        return {"markdown": text, "truncated": truncated, "bytes": len(text.encode("utf-8")), "study": self.study_dir.name if self.study_dir else None,
                "summary": self.short_summary()}

    def short_summary(self) -> str:
        """A few lines for a prefilled address: version, environment, Python, Docker. Already redacted."""
        kind = "WSL2" if platform_info.in_wsl() else {"windows": "Windows", "macos": "macOS", "linux": "Linux"}[platform_info.os_kind()]
        lines = [f"PlasBench {__version__}", f"{kind}: {platform_info.distro()} ({platform_info.arch()})", f"Python {platform.python_version()}"]
        lines.append("Docker: " + ("present" if self.which("docker") else "not found"))
        return self.clean("\n".join(lines))


class _JsonArgs:
    json = True


class StudyNotFound(ValueError):
    pass


def _cap(head, blocks, max_bytes):
    """The head and blocks joined within max_bytes: later blocks are shortened first, with a note saying so."""
    out, used, cut = [head], len(head.encode("utf-8")), False
    for i, block in enumerate(blocks):
        size = len(block.encode("utf-8"))
        room = max_bytes - used - 400
        if size <= room:
            out.append(block)
            used += size
            continue
        cut = True
        if room > 800:
            piece = block.encode("utf-8")[:room].decode("utf-8", "ignore")
            out.append(piece + "\n[...cut: the report is limited to %d KB]\n" % (max_bytes // 1024))
        out.append(f"\n> {len(blocks) - i - (1 if room > 800 else 0)} later section(s) were left out because the report reached its {max_bytes // 1024} KB limit. "
                   "Attach the log files themselves instead.\n")
        break
    text = "".join(out)
    if cut and text.count("```") % 2:
        text += "\n```\n"
    return text, cut


def _table(rows) -> str:
    return "\n".join(f"- {k}: {v}" for k, v in rows if v not in (None, ""))


def _safe_hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return ""


def _meminfo() -> str:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return f"{int(line.split()[1]) / 2**20:.1f} GB total"
    except (OSError, ValueError, IndexError):
        pass
    return ""


def _local_settings(root, environ) -> dict:
    try:
        from . import docker_runtime
        return {k: str(v) for k, v in docker_runtime.read_local_env(root, environ).items()}
    except Exception:  # noqa: BLE001
        return {}


# ---------------------------------------------------------------------------------------------------------------------------------------------- the browser
def issue_url(title="", fields=None, template="bug_report.yml") -> str:
    """The GitHub new-issue address with the form chosen and `fields` (form field ids) prefilled."""
    query = {"template": template}
    if title:
        query["title"] = title
    query.update({k: v for k, v in (fields or {}).items() if v})
    return NEW_ISSUE_URL + "?" + urllib.parse.urlencode(query, quote_via=urllib.parse.quote)


def prefilled_url(title, version, summary, template="bug_report.yml", limit=MAX_URL) -> tuple:
    """(url, fully): the address with title, version and the short summary when it fits `limit`; otherwise only the title and version (fully False)."""
    full = issue_url(title, {"version": version, "diagnostics": summary}, template)
    if len(full) <= limit:
        return full, True
    return issue_url(title, {"version": version}, template)[:limit], False


def open_url(url, environ=None, which=None, popen=None, webopen=None, osname=None) -> bool:
    """Open the address in the host's browser: Windows start, WSL wslview or explorer.exe, otherwise the default browser. True when something was started."""
    environ = os.environ if environ is None else environ
    which = which or shutil.which
    popen = popen or subprocess.Popen
    try:
        if (osname or os.name) == "nt":
            (getattr(os, "startfile", None) or (lambda u: (_ for _ in ()).throw(OSError("no startfile"))))(url)
            return True
        if environ.get("WSL_DISTRO_NAME"):
            for exe in ("wslview", "explorer.exe"):
                if which(exe):
                    popen([exe, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return True
        import webbrowser
        return bool((webopen or webbrowser.open)(url))
    except Exception:  # noqa: BLE001
        return False


def default_title() -> str:
    kind = "WSL2" if platform_info.in_wsl() else {"windows": "Windows", "macos": "macOS", "linux": "Linux"}[platform_info.os_kind()]
    return f"<command or page> fails with <short message> on {kind}"


# ---------------------------------------------------------------------------------------------------------------------------------------------------- CLI
def collect(root, how="", study=None, include_logs=DEFAULT_LOG_LINES, net=False, server=True, hostname=False, **kw) -> dict:
    return Report(root, how, study, include_logs, net, server, hostname=hostname, **kw).build()


def command(args, root, how) -> int:
    """`plasbench issue-report`: 0 report printed (and written, with --out), 1 the --out file could not be written, 2 the study named by --study does not exist."""
    try:
        result = collect(root, how, getattr(args, "study", None), getattr(args, "include_logs", DEFAULT_LOG_LINES), getattr(args, "net", False), True, getattr(args, "hostname", False))
    except StudyNotFound as exc:
        print(f"[plasbench] ERROR: {exc}", file=sys.stderr)
        return 2
    text = result["markdown"]
    if args.out:
        try:
            with open(Path(args.out).expanduser(), "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text + ("" if text.endswith("\n") else "\n"))
        except OSError as exc:
            print(f"[plasbench] ERROR: could not write {args.out}: {exc.strerror or exc}", file=sys.stderr)
            return 1
        print(f"[plasbench] Wrote {args.out} ({result['bytes'] // 1024 + 1} KB). Read it once, then paste it into the 'Diagnostics' box of the issue form, or attach the file.")
    else:
        print(text)
    if result["truncated"]:
        print("[plasbench] The report was shortened to fit its size limit; attach the study's log files too.", file=sys.stderr)
    if getattr(args, "open", False):
        title = getattr(args, "title", None) or default_title()
        url, fully = prefilled_url(title, __version__, result["summary"])
        if open_url(url):
            print("[plasbench] Opened the GitHub issue form in your browser." + (" The version and a short summary are filled in." if fully else " The text is too long for the address."))
        else:
            print(f"[plasbench] Could not open a browser. Open this address yourself: {NEW_ISSUE_URL}?template=bug_report.yml", file=sys.stderr)
        print("[plasbench] Paste the full report (" + (str(args.out) if args.out else "the text above") + ") into the 'Diagnostics' box before submitting.")
    return 0
