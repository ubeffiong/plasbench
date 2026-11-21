"""PlasBench AI help: the OpenRouter side (sign-in with OAuth PKCE, the person's own key, the models list, streamed chat, usage and errors).

Model access is bring-your-own-account: PlasBench owns no key. "Sign up / Sign in" sends the person to OpenRouter's own sign-up and consent page in a pop-up (OAuth with PKCE,
https://openrouter.ai/auth?callback_url=...&code_challenge=...&code_challenge_method=S256); OpenRouter redirects the pop-up to this window's server with a one-time `code`, which
is exchanged here (POST /api/v1/auth/keys with code, code_verifier and code_challenge_method) for a key that belongs to that person. The key is kept in
~/.plasbench/ai/openrouter.json (mode 0600; folder mode 0700 where the system supports it). It is never returned to the page, never written to a log, a manifest, a job's
environment or an issue report, and never part of an error message: every text that leaves this module passes through `scrub`.

Verified against the OpenRouter documentation (openrouter.ai/docs: OAuth PKCE, API overview, errors, prompt caching, models): the auth address and its parameters, the key exchange,
the `state` parameter (returned unchanged on the callback), localhost callbacks on any port, codes single-use and valid 10 minutes, streaming as server-sent events with a final chunk
that carries `usage`, comment lines to ignore, errors as {"error": {"code", "message", "metadata"}} also inside a 200 stream, 401 / 402 / 429 meaning and Retry-After, the models list
(GET /api/v1/models, no key needed, pricing in dollars per token as strings). Whether the callback may be 127.0.0.1 is not stated by the documentation, so the callback uses `localhost`.

The service address comes from the AI_OPENROUTER_BASE setting (default https://openrouter.ai/api/v1): it exists for the tests (a local stub server) and for a self-hosted gateway that
speaks the same API; the default is the only address the key is ever sent to unless the person changes the setting. Standard library only.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import netcheck   # noqa: F401 - the connectivity layer: every network call below is preceded by netgate.require("openrouter") in the window's routes, and by require_online here

DEFAULT_BASE = "https://openrouter.ai/api/v1"
REFERER = "https://github.com/ubeffiong/plasbench"
APP_TITLE = "PlasBench"
STATE_TTL = 600.0                 # a sign-in attempt is valid for 10 minutes (the same as OpenRouter's code)
MODELS_TTL = 6 * 3600.0
CONNECT_TIMEOUT = 20.0
READ_TIMEOUT = 75.0               # the longest silence tolerated inside a stream
KEY_RE = re.compile(r"(?:sk-or-|hf_)[A-Za-z0-9_\-]{6,}")
KEY_SHAPE = re.compile(r"^[A-Za-z0-9_\-]{16,300}$")
LOOPBACK_ORIGIN = re.compile(r"^http://(?:127\.0\.0\.1|localhost|\[::1\]):\d{2,5}$")


# ------------------------------------------------------------------------------------------------------------------------------- places
def ai_home() -> Path:
    return Path(os.environ.get("PLASBENCH_AI_HOME") or (Path.home() / ".plasbench" / "ai"))


def log_path() -> Path:
    return Path(os.environ.get("PLASBENCH_UI_HOME") or (Path.home() / ".plasbench" / "ui")) / "ai.log"


def base_url(setting: str = "") -> str:
    value = (setting or os.environ.get("AI_OPENROUTER_BASE") or DEFAULT_BASE).strip().rstrip("/")
    if not re.match(r"^https?://", value):
        return DEFAULT_BASE
    return value


def is_default_base(base: str) -> bool:
    return base.rstrip("/") == DEFAULT_BASE


def auth_page(base: str) -> str:
    """https://openrouter.ai/auth for the default base; the same host's /auth for a stub or gateway."""
    root = re.sub(r"/api/v\d+$", "", base.rstrip("/"))
    return root + "/auth"


class AiError(Exception):
    """An answer the window can show: `kind` is signin, not_free, no_credits, rate_limit, bad_request, forbidden, model_down, timeout, offline, server, cap or disabled."""

    def __init__(self, kind: str, message: str, status: int = 0, retry_after: float = 0.0, link: str = ""):
        self.kind, self.message, self.status, self.retry_after, self.link = kind, scrub(message), status, retry_after, link
        super().__init__(self.message)

    def payload(self) -> dict:
        out = {"error": self.message, "kind": self.kind}
        if self.retry_after:
            out["retry_after"] = self.retry_after
        if self.link:
            out["link"] = self.link
        return out


def scrub(text, extra_secrets=()) -> str:
    """Text with any OpenRouter-looking key (and any exact secret given) replaced: the last line of defence for everything shown or logged."""
    out = KEY_RE.sub("<key removed>", str(text or ""))
    for s in extra_secrets:
        if s and len(s) >= 8:
            out = out.replace(s, "<key removed>")
    return out


# ------------------------------------------------------------------------------------------------------------------------------ key file
def _private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def write_private(path: Path, data: dict) -> None:
    """Write JSON with owner-only permissions from the first byte (no moment at which the file is world-readable)."""
    _private_dir(path.parent)
    tmp = path.with_name(path.name + f".{os.getpid()}.{threading.get_ident()}.{os.urandom(3).hex()}.tmp")   # unique per writer: two threads or windows never share a temporary file
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    for attempt in range(40):       # on Windows os.replace fails with "Access denied" while another writer or reader has the target open: wait a moment and try again
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 39:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
            time.sleep(0.01 * (attempt + 1))


class KeyStore:
    def __init__(self, home: Path = None, name: str = "openrouter.json"):
        self.path = (home or ai_home()) / name

    def load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            if not (isinstance(data, dict) and isinstance(data.get("key"), str) and data["key"]):
                return {}
            if data.get("expires") and time.time() > float(data["expires"]):    # a sign-in that has run out counts as signed out
                return {}
            return data
        except (OSError, ValueError):
            return {}

    def key(self) -> str:
        return self.load().get("key", "")

    def save(self, key: str, source: str, expires=None) -> None:
        if not KEY_SHAPE.match(key or ""):
            raise AiError("bad_request", "That does not look like a key or token (letters, digits, - and _ only, no spaces).")
        rec = {"key": key, "source": source, "saved": int(time.time())}
        if expires:
            rec["expires"] = int(expires)
        write_private(self.path, rec)

    def delete(self) -> bool:
        try:
            self.path.unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise AiError("server", f"The key file could not be deleted ({exc.__class__.__name__}).")

    def status(self) -> dict:
        d = self.load()
        return {"signed_in": bool(d), "source": d.get("source", "") if d else ""}


# ----------------------------------------------------------------------------------------------------------------------------------- PKCE
def new_verifier() -> str:
    """43 to 128 characters of the unreserved set (RFC 7636 section 4.1): 64 random bytes, base64url, no padding = 86 characters."""
    return base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode("ascii")


def challenge_of(verifier: str) -> str:
    """BASE64URL(SHA256(verifier)) without padding (RFC 7636 section 4.2, method S256)."""
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


class AuthFlows:
    """The sign-in attempts in progress: state -> verifier, opener origin, expiry. A state works once, only before it expires, and only on this server."""

    def __init__(self, clock=time.time):
        self.clock, self.items, self.lock = clock, {}, threading.Lock()
        self.results = {}      # state -> {"ok": bool, "t": time}: what the pop-up's callback found, for the page to poll

    def _prune(self):
        now = self.clock()
        for s in [s for s, v in self.items.items() if v["expires"] <= now]:
            self.items.pop(s, None)
        for s in [s for s, v in self.results.items() if now - v["t"] > STATE_TTL]:
            self.results.pop(s, None)

    def begin(self, callback_url: str, opener_origin: str, base: str, build=None, provider: str = "openrouter") -> dict:
        verifier = new_verifier()
        state = secrets.token_urlsafe(24)
        origin = opener_origin if LOOPBACK_ORIGIN.match(opener_origin or "") else ""
        with self.lock:
            self._prune()
            if len(self.items) >= 20:       # a loop of starts cannot grow the table
                self.items.pop(min(self.items, key=lambda s: self.items[s]["expires"]))
            self.items[state] = {"verifier": verifier, "expires": self.clock() + STATE_TTL, "origin": origin, "provider": provider, "redirect": callback_url}
        if build:
            return {"state": state, "url": build(callback_url, challenge_of(verifier), state)}
        query = urllib.parse.urlencode({"callback_url": callback_url, "code_challenge": challenge_of(verifier), "code_challenge_method": "S256", "state": state,
                                        "key_label": "PlasBench AI help"})
        return {"state": state, "url": auth_page(base) + "?" + query}

    def consume(self, state: str):
        """The attempt for this state (and forget it), or None when it is unknown, used, or expired."""
        with self.lock:
            self._prune()
            return self.items.pop(state or "", None)

    def peek_origin(self, state: str) -> str:
        with self.lock:
            return (self.items.get(state or "") or {}).get("origin", "")

    def finish(self, state: str, ok: bool):
        with self.lock:
            self.results[state] = {"ok": bool(ok), "t": self.clock()}

    def result(self, state: str):
        with self.lock:
            self._prune()
            r = self.results.get(state or "")
            return None if r is None else {"ok": r["ok"]}


# --------------------------------------------------------------------------------------------------------------------------------- network
def require_online(base: str, action: str = "ask the AI help") -> None:
    """Refuse (netgate.Offline) when PLASBENCH_OFFLINE=1, or, for the real service, when openrouter.ai cannot be reached. A local stub or gateway is only checked for forced offline."""
    from . import netgate
    if netgate.forced_offline():
        netgate.require("openrouter", action)      # raises Offline with the standard text
    if is_default_base(base):
        netgate.require("openrouter", action)


def _headers(key: str = "") -> dict:
    h = {"Content-Type": "application/json", "Accept": "application/json", "HTTP-Referer": REFERER, "X-Title": APP_TITLE, "User-Agent": "PlasBench-AI-help"}
    if key:
        h["Authorization"] = "Bearer " + key
    return h


def reset_hint(headers) -> str:
    """"The limit resets in about N hours/minutes" from X-RateLimit-Reset (epoch seconds or milliseconds), or "" when the header is absent or not usable."""
    try:
        v = float((headers or {}).get("X-RateLimit-Reset") or 0)
    except (TypeError, ValueError):
        return ""
    if v <= 0:
        return ""
    if v > 1e11:
        v /= 1000.0
    left = v - time.time()
    if left <= 0 or left > 3 * 86400:
        return ""
    return f"The limit resets in about {int(left // 3600)} h {int(left % 3600 // 60)} min." if left >= 3600 else f"The limit resets in about {max(1, int(left // 60))} min."


def map_error(status: int, body: str = "", headers=None, key: str = "") -> AiError:
    """The window-facing meaning of an HTTP error from the service (the body's own message is kept, scrubbed and shortened)."""
    msg = ""
    try:
        obj = json.loads(body) if body else {}
        err = obj.get("error") if isinstance(obj, dict) else None
        msg = (err.get("message") if isinstance(err, dict) else err) or ""
    except ValueError:
        msg = ""
    msg = scrub(str(msg), (key,))[:300]
    retry = 0.0
    try:
        retry = float((headers or {}).get("Retry-After") or 0)
    except (TypeError, ValueError):
        retry = 0.0
    if status == 401:
        return AiError("signin", "OpenRouter did not accept the key (it was revoked or expired). Sign in again.", 401)
    if status == 402:
        return AiError("no_credits", "Your OpenRouter account has no credits left for this request. Add credits, then ask again.", 402, retry, "https://openrouter.ai/credits")
    if status == 403:
        return AiError("forbidden", msg or "OpenRouter refused this request (permissions or a content check).", 403)
    if status == 408:
        return AiError("timeout", "OpenRouter timed out. Try again.", 408)
    if status == 429:
        reset = reset_hint(headers)
        wait = f" Try again in {int(retry)} s." if retry else (f" {reset}" if reset else " Wait a moment and try again.")
        return AiError("rate_limit", "Free models are rate-limited by OpenRouter: 20 requests a minute, and 50 a day (1000 a day once 10 credits have ever been bought)." + wait
                       + " Another free model may still have room.", 429, retry, FREE_DOCS)
    if status in (502, 503):
        return AiError("model_down", msg or "The chosen model is not available right now. Pick another model or try again.", status, retry)
    if status == 400:
        return AiError("bad_request", msg or "OpenRouter did not accept the request.", 400)
    return AiError("server", msg or f"OpenRouter answered with an error (HTTP {status}).", status)


def _transport_error(exc: Exception) -> AiError:
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return AiError("timeout", "OpenRouter did not answer in time. Check the connection and try again.")
    return AiError("offline", "OpenRouter could not be reached. Check the internet connection (or a proxy or VPN) and try again.")


def _open(req, timeout):
    return urllib.request.urlopen(req, timeout=timeout)   # noqa: S310 - http(s) only: base_url() accepts nothing else


def exchange_code(base: str, code: str, verifier: str, opener=_open) -> str:
    """The user's own key for a one-time code (POST {base}/auth/keys). Raises AiError."""
    body = json.dumps({"code": code, "code_verifier": verifier, "code_challenge_method": "S256"}).encode("utf-8")
    req = urllib.request.Request(base + "/auth/keys", data=body, headers=_headers(), method="POST")
    try:
        with opener(req, CONNECT_TIMEOUT) as resp:
            data = json.loads(resp.read(65536).decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        text = exc.read(4096).decode("utf-8", "replace") if hasattr(exc, "read") else ""
        raise AiError("signin", "OpenRouter refused the sign-in code (it may have expired or been used already). Start the sign-in again.", exc.code) from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise _transport_error(exc) from None
    key = data.get("key") if isinstance(data, dict) else None
    if not isinstance(key, str) or not KEY_SHAPE.match(key):
        raise AiError("signin", "OpenRouter's answer did not contain a key. Start the sign-in again.")
    return key


# ------------------------------------------------------------------------------------------------------------------------------ models
# Only FREE models are ever offered or called. "Free" is read from the pricing fields of the live list (every price field zero), never from the ':free' suffix alone, and it is
# checked again when a request is made. A router (openrouter/...) can pick a paid model, so it is never offered or called.
PRICE_FIELDS = ("prompt", "completion", "request", "image", "web_search", "internal_reasoning", "input_cache_read", "input_cache_write")
FREE_DOCS = "https://openrouter.ai/docs/api-reference/limits"
PRIVACY_DOCS = "https://openrouter.ai/docs/guides/privacy/data-collection"
PRIVACY_SETTINGS = "https://openrouter.ai/settings/privacy"
# Preferred default among the free models that the live list contains: instruction-tuned, no hidden reasoning switched on by default (so the answer budget is not spent on it).
PREFERRED_FREE = ("google/gemma-4-31b-it:free", "google/gemma-4-26b-a4b-it:free", "nvidia/nemotron-3-ultra-550b-a55b:free", "nvidia/nemotron-3.5-lightning:free")
# Used only when the live list cannot be read, and then marked "may be out of date" in the window. Every id is a ':free' variant, which OpenRouter defines as the free version.
BUILTIN_FREE = PREFERRED_FREE
_MODELS = {"t": 0.0, "base": "", "data": None}


def fetch_models(base: str, opener=_open, force: bool = False, ttl: float = MODELS_TTL) -> list:
    """The public models list (no key needed), cached: [{id, name, free, context, reasoning_default, effort_none, intelligence}]. `free` is true only when every price field is zero."""
    if not force and _MODELS["data"] is not None and _MODELS["base"] == base and time.time() - _MODELS["t"] < ttl:
        return _MODELS["data"]
    req = urllib.request.Request(base + "/models", headers={"Accept": "application/json", "User-Agent": "PlasBench-AI-help"})
    try:
        with opener(req, CONNECT_TIMEOUT) as resp:
            raw = json.loads(resp.read(8 * 2**20).decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        raise map_error(exc.code, "", getattr(exc, "headers", None)) from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise _transport_error(exc) from None
    out = []
    for m in raw.get("data", []) if isinstance(raw, dict) else []:
        try:
            pr = m.get("pricing") or {}
            prices = [float(pr[k]) for k in PRICE_FIELDS if pr.get(k) not in (None, "")]
            arch = m.get("architecture") or {}
            rs = m.get("reasoning") or {}
            aa = (m.get("benchmarks") or {}).get("artificial_analysis") or {}
            mid = str(m["id"])
            out.append({"id": mid, "name": str(m.get("name") or mid), "free": bool(prices) and "prompt" in pr and "completion" in pr and all(p == 0 for p in prices),
                        "context": int(m.get("context_length") or 0), "text_only_out": (arch.get("output_modalities") or ["text"]) == ["text"],
                        "max_tokens": "max_tokens" in (m.get("supported_parameters") or ["max_tokens"]), "reasoning_mandatory": bool(rs.get("mandatory")),
                        "reasoning_default": bool(rs.get("default_enabled")), "effort_none": "none" in (rs.get("supported_efforts") or []),
                        "intelligence": float(aa.get("intelligence_index") or 0)})
        except (KeyError, TypeError, ValueError):
            continue
    _MODELS.update(t=time.time(), base=base, data=out)
    return out


def usable(m: dict) -> bool:
    """A model the window may offer: free by its pricing fields, text out, long enough context, not a router, no mandatory reasoning."""
    i = m["id"]
    return bool(m["free"] and m["text_only_out"] and m["max_tokens"] and m["context"] >= 32000 and not m["reasoning_mandatory"]
                and not i.startswith(("openrouter/", "~")) and not i.endswith((":batch", ":extended", ":nitro", ":floor", ":online")))


def free_models(models: list) -> list:
    """The free, usable models: the preferred ones first (in the order of PREFERRED_FREE), then by benchmark index and context."""
    ok = [m for m in models if usable(m)]
    rank = {i: n for n, i in enumerate(PREFERRED_FREE)}
    return sorted(ok, key=lambda m: (rank.get(m["id"], 99), m["reasoning_default"], -m["intelligence"], -m["context"], m["id"]))


def shortlist(models: list, limit: int = 10) -> list:
    return free_models(models)[:limit]


def default_model(models: list) -> str:
    """The best-suited free model in the live list; "" when the list has none."""
    f = free_models(models)
    return f[0]["id"] if f else ""


def builtin_list() -> list:
    return [{"id": i, "name": i, "free": True, "context": 0, "text_only_out": True, "max_tokens": True, "reasoning_mandatory": False, "reasoning_default": False, "effort_none": False,
             "intelligence": 0.0} for i in BUILTIN_FREE]


def load_free(base: str, opener=_open, force: bool = False) -> dict:
    """{"models": [...free...], "default": id, "outdated": bool, "error": str}. A list that cannot be read gives the built-in list marked outdated (never silently)."""
    try:
        live = fetch_models(base, opener, force)
        return {"models": shortlist(live), "default": default_model(live), "outdated": False, "error": ""}
    except AiError as exc:
        return {"models": builtin_list(), "default": BUILTIN_FREE[0], "outdated": True, "error": exc.message}


def ensure_free(base: str, model: str, opener=_open) -> dict:
    """Refuse (AiError "not_free") unless `model` is free in a list read within the last hour; a model that turned paid is therefore never called. Returns the list entry.

    When the list cannot be read at all, only a built-in ':free' id passes (the list is then known to be possibly out of date)."""
    model = str(model or "")
    try:
        live = fetch_models(base, opener, ttl=3600.0)
        entry = next((m for m in live if m["id"] == model), None)
        if entry is None:      # new since the cached list: read it again once before refusing
            live = fetch_models(base, opener, force=True)
            entry = next((m for m in live if m["id"] == model), None)
    except AiError:
        if model in BUILTIN_FREE and model.endswith(":free"):
            return builtin_list()[BUILTIN_FREE.index(model)]
        raise AiError("not_free", "The list of free models cannot be loaded, so this model cannot be checked and was not used. Try again when the connection is back.")
    if entry is None or not usable(entry):
        raise AiError("not_free", "That model is not a free model (or is no longer free), so it was not used. PlasBench AI help only uses free OpenRouter models; pick one from the list.")
    return entry


# ------------------------------------------------------------------------------------------------------------------------------- usage
class Usage:
    """Tokens and cost per day, kept in ~/.plasbench/ai/usage.json (counts only)."""

    def __init__(self, home: Path = None, today=lambda: time.strftime("%Y-%m-%d"), name: str = "usage.json"):
        self.path = (home or ai_home()) / name
        self.today = today
        self.lock = threading.Lock()

    def _read(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as fh:
                d = json.load(fh)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def day(self) -> dict:
        d = self._read().get(self.today(), {})
        return {"prompt": int(d.get("prompt", 0)), "completion": int(d.get("completion", 0)), "cost": float(d.get("cost", 0.0)), "calls": int(d.get("calls", 0))}

    def total_today(self) -> int:
        d = self.day()
        return d["prompt"] + d["completion"]

    def add(self, prompt: int, completion: int, cost: float = 0.0) -> dict:
        with self.lock:
            data = self._read()
            d = data.get(self.today(), {})
            d = {"prompt": int(d.get("prompt", 0)) + int(prompt), "completion": int(d.get("completion", 0)) + int(completion), "cost": round(float(d.get("cost", 0.0)) + float(cost or 0), 6),
                 "calls": int(d.get("calls", 0)) + 1}
            data[self.today()] = d
            for old in sorted(data)[:-31]:
                data.pop(old, None)
            try:
                write_private(self.path, data)
            except OSError:
                pass
            return d

    def check_cap(self, cap: int) -> None:
        if cap and self.total_today() >= cap:
            raise AiError("cap", f"The daily token limit ({cap:,} tokens) is reached. It resets tomorrow; raise AI_DAILY_TOKEN_CAP in Settings to continue today.")


MAX_LINE = 1 << 20          # one event line
MAX_STREAM = 8 << 20        # one whole streamed answer


def log_event(status, model="", prompt=0, completion=0, note=""):
    """One line of counts and a status code: never a prompt, an answer, a key or a path."""
    try:
        p = log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} status={status} model={re.sub(r'[^A-Za-z0-9_./:-]', '', model)[:60]} prompt_tokens={int(prompt)} completion_tokens={int(completion)} {re.sub(r'[^a-z_ ]', '', note)[:30]}\n".rstrip() + "\n")
    except OSError:
        pass


# ------------------------------------------------------------------------------------------------------------------------------- chat
def stream_chat(base: str, key: str, model: str, messages: list, max_tokens: int, opener=_open, no_reasoning: bool = False, headers_out: dict = None, error_map=None, extra_body: dict = None):
    """Yield ("delta", text) for each piece of the answer, then ("usage", dict) when the service reports it, then ("done", None).

    Raises AiError for an HTTP error before the first byte or an `error` object inside the stream. Closing the generator (the page aborted) closes the connection to the service.
    Server-sent events: lines `data: {...}`, comment lines starting with `:` are ignored, `data: [DONE]` ends the stream."""
    body = {"model": model, "messages": messages, "stream": True, "max_tokens": int(max_tokens), "temperature": 0.2}
    if extra_body:
        body.update(extra_body)
    if no_reasoning:        # only for a model whose list entry offers effort "none": the answer budget is not spent on hidden reasoning
        body["reasoning"] = {"effort": "none"}
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode("utf-8"), headers=dict(_headers(key), Accept="text/event-stream"), method="POST")
    try:
        resp = opener(req, READ_TIMEOUT)
    except urllib.error.HTTPError as exc:
        text = exc.read(8192).decode("utf-8", "replace") if hasattr(exc, "read") else ""
        raise (error_map or map_error)(exc.code, text, getattr(exc, "headers", None), key) from None
    except (urllib.error.URLError, OSError) as exc:
        raise _transport_error(exc) from None
    usage = None
    finished = False
    got_text = False
    if headers_out is not None:
        for h in ("X-RateLimit-Remaining", "X-RateLimit-Limit", "X-RateLimit-Reset"):
            v = resp.headers.get(h) if getattr(resp, "headers", None) else None
            if v:
                headers_out[h] = v
    try:
        total = 0
        while True:
            raw = resp.readline(MAX_LINE + 1)           # a line is bounded: a hostile or broken service cannot make the window read an endless line into memory
            if not raw:
                break
            total += len(raw)
            if len(raw) > MAX_LINE or total > MAX_STREAM:
                raise AiError("server", "The service sent more data than an answer can be. The answer was stopped.", 502)
            line = raw.decode("utf-8", "replace").strip()
            if not line or line.startswith(":") or not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                finished = True
                break
            try:
                obj = json.loads(payload)
            except ValueError:
                continue
            if isinstance(obj, dict) and obj.get("error"):
                err = obj["error"]
                code = err.get("code") if isinstance(err, dict) else 0
                try:
                    code = int(code)
                except (TypeError, ValueError):
                    code = 500
                raise (error_map or map_error)(code if code in (401, 402, 403, 408, 429, 502, 503) else 500, json.dumps({"error": err}), None, key)
            for ch in (obj.get("choices") or []) if isinstance(obj, dict) else []:
                piece = (ch.get("delta") or {}).get("content")
                if piece:
                    got_text = True
                    yield ("delta", piece)
                if ch.get("finish_reason"):
                    finished = True
                if ch.get("finish_reason") and headers_out is not None:
                    headers_out["finish_reason"] = ch["finish_reason"]       # "length" = the answer hit the output limit
                if ch.get("error"):
                    raise (error_map or map_error)(500, json.dumps({"error": ch["error"]}), None, key)
            if isinstance(obj, dict) and obj.get("usage"):
                usage = obj["usage"]
    except (socket.timeout, TimeoutError):
        raise AiError("timeout", "The answer stopped arriving (OpenRouter went quiet). Try again.") from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise _transport_error(exc) from None
    finally:
        try:
            resp.close()
        except Exception:  # noqa: BLE001
            pass
    if got_text and not finished and headers_out is not None:
        headers_out["finish_reason"] = "cut"            # the connection ended with no [DONE] and no finish reason: the answer may be incomplete (shown with a Continue button)
    if usage:
        yield ("usage", usage)
    yield ("done", None)


def key_info(base: str, key: str, opener=_open) -> dict:
    """{"used", "limit", "remaining"} of the free-model daily requests from GET {base}/key (documented: free_model_daily_requests), or {} when not available."""
    req = urllib.request.Request(base + "/key", headers=_headers(key), method="GET")
    try:
        with opener(req, CONNECT_TIMEOUT) as resp:
            data = json.loads(resp.read(65536).decode("utf-8", "replace"))
        d = (data.get("data") if isinstance(data, dict) else None) or {}
        f = d.get("free_model_daily_requests") or {}
        return {k: f[k] for k in ("used", "limit", "remaining") if isinstance(f.get(k), (int, float))}
    except (urllib.error.URLError, OSError, ValueError, AttributeError):
        return {}


def run_chat(base: str, key: str, models: list, messages: list, max_tokens: int, fallback: bool = True, opener=_open, info: dict = None, check=None, error_map=None, extra_body: dict = None):
    """Yield ("delta"|"usage"|"model"|"notice"|"done", value) for the first free model in `models` that answers.

    Every model is checked free (ensure_free) right before it is called. When a model fails on a limit (429) or is down (502/503) BEFORE any text was streamed, and `fallback` is on,
    the next free model is tried; the window is told with a "notice". A paid model is never in `models` and never reached: ensure_free refuses it."""
    last = None
    tried = []
    for n, model in enumerate(models):
        entry = (check or (lambda m: ensure_free(base, m, opener)))(model)
        headers = {} if info is None else info.setdefault("headers", {})
        started = False
        try:
            yield ("model", model)
            for kind, value in stream_chat(base, key, model, messages, max_tokens, opener, no_reasoning=bool(entry.get("effort_none")), headers_out=headers, error_map=error_map, extra_body=extra_body):
                if kind == "delta":
                    started = True
                yield (kind, value)
            return
        except AiError as exc:
            last = exc
            tried.append(model)
            if started or not fallback or exc.kind not in ("rate_limit", "model_down", "timeout") or n + 1 >= len(models):
                raise
            yield ("notice", f"{model} is limited or unavailable ({exc.kind.replace('_', ' ')}); trying another free model.")
    if last:
        raise last
