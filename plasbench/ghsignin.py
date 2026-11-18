"""Signing in to GitHub from the window, in a pop-up, with GitHub's device flow through the GitHub CLI (no app to register).

`gh auth login --hostname github.com --git-protocol https --web` is started in the background with a no-op BROWSER and a closed stdin. Non-interactive, it prints a one-time code
(XXXX-XXXX) and the verification address (https://github.com/login/device) and then waits until the user approves in the browser. This module captures that output, parses the code
and address, and reports a state (waiting, signed_in, failed, cancelled, expired); the page opens the address in a pop-up window it controls and shows the code. The whole attempt is
killed on cancel and after 15 minutes. A token is never printed, stored, logged or sent to the page: the personal-access-token fallback pipes it to `gh auth login --with-token` over
standard input only, never on a command line. After a sign-in `gh auth setup-git` lets plain `git push` and `git pull` use it.

Everything that starts a process takes the command as an argument (`gh_cmd`) and a runner, so the tests drive it with a fake `gh`. Standard library only.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid

EXPIRES_SECONDS = 15 * 60
CODE_WAIT_SECONDS = 25
HOST = "github.com"
CODE_RE = re.compile(r"(?:one-time code|device code|your code)\D{0,12}([A-Z0-9]{4}-[A-Z0-9]{4})", re.I)
BARE_CODE_RE = re.compile(r"\b([A-Z0-9]{4}-[A-Z0-9]{4})\b")
URL_RE = re.compile(r"https://github\.com/login/device\S*")
ALREADY_RE = re.compile(r"already logged in|already signed in|Logged in to github\.com", re.I)
USER_RE = re.compile(r"(?:account|as)\s+([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))\b")
SCOPES_RE = re.compile(r"Token scopes:\s*(.+)")
TOKEN_RE = re.compile(r"(?i)\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")
TOKEN_SHAPE = re.compile(r"^[A-Za-z0-9_\-]{20,255}$")


def redact(text: str) -> str:
    """Remove anything that looks like a GitHub token from text that may be shown or logged."""
    return TOKEN_RE.sub("<token removed>", text or "")


def parse_device_output(text: str) -> dict:
    """{"code", "url", "already", "user"} from what `gh auth login --web` printed so far (any may be None / False)."""
    text = text or ""
    code = None
    m = CODE_RE.search(text)
    if m:
        code = m.group(1).upper()
    else:
        for line in text.splitlines():
            if "code" in line.lower():
                b = BARE_CODE_RE.search(line)
                if b:
                    code = b.group(1).upper()
                    break
    u = URL_RE.search(text)
    user = None
    if ALREADY_RE.search(text):
        um = USER_RE.search(text)
        user = um.group(1) if um else None
    return {"code": code, "url": u.group(0).rstrip(".,)") if u else None, "already": bool(ALREADY_RE.search(text)), "user": user}


def parse_auth_status(text: str) -> dict:
    """{"signed_in", "user", "scopes"} from `gh auth status` output (the account line has changed between gh versions: both forms are read)."""
    text = text or ""
    signed = bool(re.search(r"Logged in to github\.com", text, re.I)) and not re.search(r"not logged in|failed to log in|token .* is invalid", text, re.I)
    user = None
    m = re.search(r"Logged in to github\.com (?:account|as)\s+([A-Za-z0-9-]+)", text, re.I)
    if m:
        user = m.group(1)
    scopes = []
    sm = SCOPES_RE.search(text)
    if sm:
        scopes = [s.strip().strip("'\"") for s in sm.group(1).split(",") if s.strip().strip("'\"")]
    return {"signed_in": signed, "user": user, "scopes": scopes}


def install_commands(platform: str | None = None) -> list:
    """How to install the GitHub CLI on this platform (shown in the window; never run by it)."""
    platform = platform or ("windows" if os.name == "nt" else "mac" if sys.platform == "darwin" else "linux")
    if platform == "windows":
        return ["winget install --id GitHub.cli", "conda install -c conda-forge gh"]
    if platform == "mac":
        return ["brew install gh", "conda install -c conda-forge gh"]
    return ["conda install -c conda-forge gh", "sudo apt install gh"]


def noop_browser() -> str:
    """A BROWSER value that does nothing, so gh never opens the user's own browser."""
    true = shutil.which("true")
    if true and os.name != "nt":
        return true
    return f'"{sys.executable}" -c "pass"'


def clean_env(extra=None) -> dict:
    env = dict(os.environ)
    env.update({"BROWSER": noop_browser(), "GH_BROWSER": noop_browser(), "GH_PROMPT_DISABLED": "1", "GIT_TERMINAL_PROMPT": "0", "NO_COLOR": "1", "GH_NO_UPDATE_NOTIFIER": "1", "LC_ALL": "C"})
    for k in ("GH_TOKEN", "GITHUB_TOKEN"):
        env.pop(k, None)          # a token in the environment would make gh skip the sign-in
    env.update(extra or {})
    return env


def _creation():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _kill(proc) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=10)
        else:
            proc.kill()
    except (OSError, subprocess.SubprocessError):
        pass


class SignIn:
    """At most one device-flow sign-in at a time."""

    def __init__(self, gh_cmd, popen=subprocess.Popen, run=subprocess.run, clock=time.time):
        self.gh_cmd = list(gh_cmd)
        self.popen, self.run, self.clock = popen, run, clock
        self.lock = threading.Lock()
        self.proc = None
        self.reset()

    def reset(self):
        self.id = None
        self.state = "idle"
        self.output = ""
        self.code = self.url = None
        self.user = None
        self.message = ""
        self.started = None
        self.exit = None
        self._cancel = False

    # ---------------------------------------------------------------- start / status / cancel
    def start(self, wait_seconds: float = CODE_WAIT_SECONDS) -> dict:
        """Start the device flow. Returns {code, url, expires_in, pid_id}, or {already_signed_in, user, ...} when gh says so."""
        self.cancel(quiet=True)
        with self.lock:
            self.reset()
            self.id, self.state, self.started = uuid.uuid4().hex[:12], "waiting", self.clock()
            cmd = self.gh_cmd + ["auth", "login", "--hostname", HOST, "--git-protocol", "https", "--web"]
            try:
                self.proc = self.popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=clean_env(), creationflags=_creation())
            except OSError as exc:
                self.state, self.message = "failed", f"the GitHub CLI could not be started: {exc.strerror or exc}"
                raise RuntimeError(self.message)
            sid, proc = self.id, self.proc
        threading.Thread(target=self._read, args=(sid, proc), daemon=True).start()
        threading.Thread(target=self._expire, args=(sid, proc), daemon=True).start()
        end = self.clock() + wait_seconds
        while self.clock() < end:
            with self.lock:
                if self.id != sid:
                    break
                parsed = parse_device_output(self.output)
                if parsed["code"] and parsed["url"]:
                    self.code, self.url = parsed["code"], parsed["url"]
                    return {"code": self.code, "url": self.url, "expires_in": EXPIRES_SECONDS, "pid_id": self.id}
                if self.state in ("signed_in", "failed", "cancelled"):
                    break
            time.sleep(0.05)
        with self.lock:
            parsed = parse_device_output(self.output)
            if self.state == "signed_in" or parsed["already"]:
                return {"already_signed_in": True, "user": self.user or parsed["user"], "pid_id": self.id}
            if parsed["code"]:
                self.code, self.url = parsed["code"], parsed["url"] or "https://github.com/login/device"
                return {"code": self.code, "url": self.url, "expires_in": EXPIRES_SECONDS, "pid_id": self.id}
            message = self.message or "GitHub did not give a one-time code. " + (redact(self.output).strip().splitlines()[-1] if self.output.strip() else "No answer from the GitHub CLI.")
        self.cancel(quiet=True)
        raise RuntimeError(message)

    def _read(self, sid, proc):
        try:
            for raw in iter(proc.stdout.readline, b""):
                line = redact(raw.decode("utf-8", "replace"))
                with self.lock:
                    if self.id != sid:
                        return
                    self.output = (self.output + line)[-4000:]
        except (OSError, ValueError):
            pass
        code = proc.wait()
        with self.lock:
            if self.id != sid:
                return
            self.exit = code
            if self._cancel:
                pass                    # cancel() and _expire() already set the state (cancelled or expired) and the message: do not overwrite it
            elif code == 0:
                self.state = "signed_in"
            elif self.state == "waiting":
                self.state = "failed"
                tail = [l for l in redact(self.output).strip().splitlines() if l.strip()]
                self.message = tail[-1] if tail else f"the GitHub CLI stopped (exit {code})"
        if code == 0 and not self._cancel:
            self._finish_sign_in(sid)

    def _finish_sign_in(self, sid):
        """gh auth setup-git (so plain git push and pull use the sign-in), then find the account name."""
        try:
            self.run(self.gh_cmd + ["auth", "setup-git", "--hostname", HOST], capture_output=True, timeout=30, env=clean_env(), creationflags=_creation())
        except (OSError, subprocess.SubprocessError):
            pass
        info = account_status(self.gh_cmd, run=self.run)
        with self.lock:
            if self.id == sid:
                self.user = info.get("user")

    def _expire(self, sid, proc):
        end = self.clock() + EXPIRES_SECONDS
        while self.clock() < end:
            time.sleep(0.5)
            with self.lock:
                if self.id != sid or self.state != "waiting":
                    return
        with self.lock:
            if self.id != sid or self.state != "waiting":
                return
            self.state, self.message, self._cancel = "expired", "the one-time code expired (15 minutes): start again", True
        _kill(proc)

    def status(self) -> dict:
        with self.lock:
            return {"state": self.state, "user": self.user, "message": redact(self.message), "code": self.code, "url": self.url, "pid_id": self.id}

    def cancel(self, quiet: bool = False) -> dict:
        with self.lock:
            proc, active = self.proc, self.state == "waiting"
            if active:
                self.state, self.message, self._cancel = "cancelled", "sign-in cancelled", True
        if proc is not None and active:
            _kill(proc)
        return self.status()


# ---------------------------------------------------------------- account, sign-out, token fallback
def account_status(gh_cmd, run=subprocess.run) -> dict:
    """{"signed_in", "user", "scopes"} from `gh auth status` (never raises)."""
    try:
        done = run(list(gh_cmd) + ["auth", "status", "--hostname", HOST], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, env=clean_env(), creationflags=_creation())
    except (OSError, subprocess.SubprocessError):
        return {"signed_in": False, "user": None, "scopes": []}
    text = (getattr(done, "stdout", "") or "") + (getattr(done, "stderr", "") or "")
    info = parse_auth_status(text)
    if getattr(done, "returncode", 1) != 0:
        info["signed_in"] = False
    return info


def git_helper_configured(run=subprocess.run, git="git") -> bool:
    try:
        done = run([git, "config", "--global", "--get-regexp", r"^credential\..*helper$"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10, creationflags=_creation())
    except (OSError, subprocess.SubprocessError):
        return False
    return "gh auth git-credential" in (getattr(done, "stdout", "") or "") or "gh.exe auth git-credential" in (getattr(done, "stdout", "") or "")


def account(gh_cmd, run=subprocess.run, git="git") -> dict:
    """What the window shows: {gh_installed, signed_in, user, name, avatar_url, git_helper_configured, scopes}."""
    if not gh_cmd:
        return {"gh_installed": False, "signed_in": False, "user": None, "name": None, "avatar_url": None, "git_helper_configured": False, "scopes": [], "install": install_commands()}
    info = account_status(gh_cmd, run)
    out = {"gh_installed": True, "signed_in": info["signed_in"], "user": info["user"], "name": None, "avatar_url": None, "git_helper_configured": git_helper_configured(run, git), "scopes": info["scopes"], "install": []}
    if info["signed_in"] and info["user"]:
        out["avatar_url"] = f"https://github.com/{info['user']}.png?size=64"
    return out


def sign_out(gh_cmd, run=subprocess.run) -> dict:
    try:
        done = run(list(gh_cmd) + ["auth", "logout", "--hostname", HOST], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, env=clean_env(), stdin=subprocess.DEVNULL, creationflags=_creation())
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"could not sign out: {exc}")
    ok = getattr(done, "returncode", 1) == 0
    tail = redact(((getattr(done, "stderr", "") or "") + (getattr(done, "stdout", "") or "")).strip()).splitlines()
    return {"ok": ok, "message": "" if ok else (tail[-1] if tail else "sign-out failed")}


def sign_in_with_token(gh_cmd, token: str, run=subprocess.run) -> dict:
    """The personal-access-token fallback: the token goes to `gh auth login --with-token` over standard input ONLY (never on a command line), is never logged and is not returned."""
    token = (token or "").strip()
    if not TOKEN_SHAPE.match(token):
        raise ValueError("that does not look like a GitHub token (letters, digits, - and _ only, no spaces)")
    cmd = list(gh_cmd) + ["auth", "login", "--hostname", HOST, "--git-protocol", "https", "--with-token"]
    try:
        done = run(cmd, input=token + "\n", capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, env=clean_env(), creationflags=_creation())
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"the GitHub CLI could not check the token: {type(exc).__name__}")
    finally:
        token = ""
    if getattr(done, "returncode", 1) != 0:
        tail = redact(((getattr(done, "stderr", "") or "") + (getattr(done, "stdout", "") or "")).strip()).splitlines()
        raise ValueError("GitHub did not accept the token" + (f": {tail[-1]}" if tail else ""))
    try:
        run(list(gh_cmd) + ["auth", "setup-git", "--hostname", HOST], capture_output=True, timeout=30, env=clean_env(), creationflags=_creation())
    except (OSError, subprocess.SubprocessError):
        pass
    info = account_status(gh_cmd, run)
    return {"ok": True, "user": info.get("user"), "scopes": info.get("scopes", [])}
