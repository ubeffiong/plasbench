"""The providers the AI help can use, behind one small interface.

    openrouter    free models only (plasbench/ai_openrouter.py); sign-in by OAuth PKCE in a pop-up, or the person's own pasted key
    huggingface   Inference Providers through Hugging Face's OpenAI-compatible router; sign-in by a PUBLIC OAuth app (authorization code with PKCE, client id only, no client secret).
                  The client id is a setting (AI_HF_CLIENT_ID): an app the owner registers, so without it the sign-in button is off and a pasted token still works. Only models that the router's
                  own list marks free (price zero) are used unless AI_HF_USE_CREDITS=1 allows cheap models that spend the person's own Hugging Face credits.
    local         a server on this computer that speaks the OpenAI API (Ollama, LM Studio): no account, no key, nothing leaves the computer

What was checked in the providers' documentation (21 November 2026) is in docs/AI_HELP.md ("Providers considered"). Each provider answers the same questions:
    configured(), models_info(), check(model) (raises AiError "not_free" for a model it must not call), chain(), chat(), auth (begin / exchange), limits(), privacy(), require_online().
Standard library only.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import ai_openrouter as orr   # the connectivity layer (netcheck) is consulted through netgate.require in Provider.require_online
from .ai_openrouter import AiError

HF_ROUTER = "https://router.huggingface.co/v1"
HF_HUB = "https://huggingface.co"
HF_CALLBACK = "/ai/hf/callback"
OR_CALLBACK = "/ai/openrouter/callback"
OLLAMA_BASE = "http://localhost:11434/v1"
LMSTUDIO_BASE = "http://localhost:1234/v1"
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1", "[::1]")
HF_PREFERRED = ("google/gemma-3-4b-it", "meta-llama/Llama-3.1-8B-Instruct", "openai/gpt-oss-20b")
HF_MAX_PRICE = 0.30          # dollars per million tokens (input + output) for a model that spends the person's credits (AI_HF_USE_CREDITS=1)
HF_FREE_NOTE = ("Hugging Face's pricing page (checked 21 November 2026) lists no included credits for free accounts, $2.00 a month for PRO accounts, and pay-as-you-go beyond that. "
                "Models marked free in the router's own list cost nothing; any other model spends your Hugging Face credits.")
HF_BILLING = "https://huggingface.co/settings/billing"


class Provider:
    id = ""
    name = ""
    needs_key = True
    oauth = False
    paste = True
    callback_path = ""
    service = ""            # the row of config/network_services.tsv ("" = no internet needed)

    def __init__(self, settings):
        self.s = settings

    # -- places
    def base(self) -> str:
        raise NotImplementedError

    def keystore(self) -> "orr.KeyStore":
        return orr.KeyStore(name=f"{self.id}.json")

    def usage(self) -> "orr.Usage":
        return orr.Usage(name="usage.json" if self.id == "openrouter" else f"usage-{self.id}.json")

    def configured(self):
        return True, ""

    def require_online(self, action: str) -> None:
        if self.service:
            from . import netgate
            if netgate.forced_offline() or self.default_base():
                netgate.require(self.service, action)

    def default_base(self) -> bool:
        return True

    # -- models
    def models_info(self, force: bool = False) -> dict:
        raise NotImplementedError

    def check(self, model: str) -> dict:
        raise NotImplementedError

    def chain(self, chosen: str) -> list:
        info = self.models_info()
        order = [m["id"] for m in info["models"]]
        first = chosen or self.s.model() or info["default"] or (order[0] if order else "")    # a chosen model that is not usable is refused by check(), never swapped for another
        if not first:
            raise AiError("not_free", f"No usable model is available from {self.name} right now. Try again later.")
        out = [first]
        if self.s.fallback():
            out += [m for m in order if m != first][:2]
        return out

    def error_map(self):
        return None

    def chat(self, key, chain, messages, max_tokens, fallback, info):
        return orr.run_chat(self.base(), key, chain, messages, max_tokens, fallback, info=info, check=self.check, error_map=self.error_map())

    # -- sign-in
    def auth_url(self, callback_url: str, challenge: str, state: str) -> str:
        raise AiError("bad_request", f"{self.name} has no pop-up sign-in.")

    def exchange(self, code: str, verifier: str, redirect: str, opener=orr._open) -> dict:
        raise AiError("bad_request", f"{self.name} has no pop-up sign-in.")

    def limits(self, key: str) -> dict:
        return {}

    def privacy(self) -> dict:
        raise NotImplementedError

    def public(self) -> dict:
        ok, why = self.configured()
        return {"id": self.id, "name": self.name, "configured": ok, "reason": why, "oauth": self.oauth and ok, "paste": self.paste, "needs_key": self.needs_key}


# ------------------------------------------------------------------------------------------------------------------------------ OpenRouter
class OpenRouter(Provider):
    id, name, oauth, service, callback_path = "openrouter", "OpenRouter (free models)", True, "openrouter", OR_CALLBACK

    def base(self):
        return orr.base_url(self.s.get("AI_OPENROUTER_BASE"))

    def default_base(self):
        return orr.is_default_base(self.base())

    def require_online(self, action):
        orr.require_online(self.base(), action)

    def models_info(self, force=False):
        info = orr.load_free(self.base(), force=force)
        return {"models": [{"id": m["id"], "name": m["name"], "context": m["context"], "note": "free"} for m in info["models"]], "default": info["default"], "outdated": info["outdated"],
                "error": info["error"], "docs": orr.FREE_DOCS}

    def check(self, model):
        return orr.ensure_free(self.base(), model)

    def auth_url(self, callback_url, challenge, state):
        q = urllib.parse.urlencode({"callback_url": callback_url, "code_challenge": challenge, "code_challenge_method": "S256", "state": state, "key_label": "PlasBench AI help"})
        return orr.auth_page(self.base()) + "?" + q

    def exchange(self, code, verifier, redirect, opener=orr._open):
        return {"key": orr.exchange_code(self.base(), code, verifier, opener)}

    def limits(self, key):
        return orr.key_info(self.base(), key)

    def privacy(self):
        return {"where": "OpenRouter (openrouter.ai)", "free": orr_free_note(), "links": {"data_policy": orr.PRIVACY_DOCS, "privacy_settings": orr.PRIVACY_SETTINGS, "limits": orr.FREE_DOCS}}


def orr_free_note() -> str:
    return ("Free models are free of charge but limited by OpenRouter: 20 requests a minute and 50 a day (1000 a day once 10 credits have ever been bought). "
            "OpenRouter's documentation says it does not log prompts by default, but a provider of a free model may keep or train on what it receives under its own policy, "
            "and OpenRouter only routes to such providers if you allow it in your OpenRouter privacy settings. The documentation does not say more about free models in particular: "
            "read the model's page before you send anything you consider sensitive.")


# ------------------------------------------------------------------------------------------------------------------------- Hugging Face
_HF = {"t": 0.0, "base": "", "data": None}


def hf_error(status, body="", headers=None, key=""):
    if status == 402:
        return AiError("no_credits", "Hugging Face says this account has no Inference Providers credits left. Free accounts have none included (PRO accounts include $2.00 a month); "
                       "add credits in your Hugging Face billing settings, or use a model marked free.", 402, 0.0, HF_BILLING)
    if status == 401:
        return AiError("signin", "Hugging Face did not accept the sign-in (it expired or was revoked). Sign in again.", 401)
    if status == 429:
        retry = 0.0
        try:
            retry = float((headers or {}).get("Retry-After") or 0)
        except (TypeError, ValueError):
            retry = 0.0
        return AiError("rate_limit", "Hugging Face is rate-limiting this account or model." + (f" Try again in {int(retry)} s." if retry else " Wait a moment and try again."), 429, retry)
    return orr.map_error(status, body, headers, key)


class HuggingFace(Provider):
    id, name, oauth, service, callback_path = "huggingface", "Hugging Face", True, "huggingface", HF_CALLBACK

    def base(self):
        return (self.s.get("AI_HF_BASE") or HF_ROUTER).rstrip("/")

    def hub(self):
        return (self.s.get("AI_HF_HUB") or HF_HUB).rstrip("/")

    def default_base(self):
        return self.base() == HF_ROUTER

    def client_id(self) -> str:
        return re.sub(r"[^A-Za-z0-9._:/-]", "", self.s.get("AI_HF_CLIENT_ID").strip())[:200]

    def configured(self):
        return (True, "") if self.client_id() else (False, "Hugging Face sign-in needs a registered public OAuth app: set AI_HF_CLIENT_ID (see docs/AI_HELP.md). Pasting a token works without it.")

    def public(self):
        d = super().public()
        d["oauth"] = bool(self.client_id())
        d["configured"] = True      # paste works without the app: the choice is offered, its sign-in button is off
        d["reason"] = "" if self.client_id() else self.configured()[1]
        return d

    def use_credits(self) -> bool:
        return str(self.s.get("AI_HF_USE_CREDITS")).strip().lower() not in ("", "0", "off", "false", "no")

    def error_map(self):
        return hf_error

    def fetch(self, force=False, ttl=orr.MODELS_TTL, opener=orr._open) -> list:
        """[{id (model:provider), name, free, price (dollars per million tokens, input+output), context}] for the router's chat models; `free` only when the router lists price zero."""
        if not force and _HF["data"] is not None and _HF["base"] == self.base() and time.time() - _HF["t"] < ttl:
            return _HF["data"]
        req = urllib.request.Request(self.base() + "/models", headers={"Accept": "application/json", "User-Agent": "PlasBench-AI-help"})
        try:
            with opener(req, orr.CONNECT_TIMEOUT) as resp:
                raw = json.loads(resp.read(16 * 2**20).decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            raise hf_error(exc.code, "", getattr(exc, "headers", None)) from None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise orr._transport_error(exc) from None
        out = []
        for m in raw.get("data", []) if isinstance(raw, dict) else []:
            try:
                if (m.get("architecture") or {}).get("output_modalities", ["text"]) != ["text"]:
                    continue
                live = []
                for p in m.get("providers") or []:
                    if p.get("status") not in (None, "live"):
                        continue
                    pr = p.get("pricing")
                    if not isinstance(pr, dict) or "input" not in pr or "output" not in pr:
                        continue
                    price = float(pr["input"]) + float(pr["output"])
                    live.append((price, p.get("is_free") is True and price == 0 or price == 0, str(p["provider"]), int(p.get("context_length") or 0)))
                if not live:
                    continue
                for price, free, prov, ctx in sorted(live):
                    if free:
                        out.append({"id": f"{m['id']}:{prov}", "name": f"{m['id']} (free, via {prov})", "free": True, "price": 0.0, "context": ctx})
                cheapest = sorted(live)[0]
                if not cheapest[1]:
                    out.append({"id": f"{m['id']}:{cheapest[2]}", "name": f"{m['id']} (uses your credits)", "free": False, "price": cheapest[0], "context": cheapest[3]})
            except (KeyError, TypeError, ValueError):
                continue
        _HF.update(t=time.time(), base=self.base(), data=out)
        return out

    def allowed(self, m: dict) -> bool:
        return m["context"] >= 32000 and (m["free"] or (self.use_credits() and 0 < m["price"] <= HF_MAX_PRICE))

    def models_info(self, force=False):
        try:
            allowed = [m for m in self.fetch(force) if self.allowed(m)]
        except AiError as exc:
            return {"models": [], "default": "", "outdated": True, "error": exc.message, "docs": HF_BILLING}
        pref = {i: n for n, i in enumerate(HF_PREFERRED)}
        allowed.sort(key=lambda m: (not m["free"], pref.get(m["id"].rsplit(":", 1)[0], 99), m["price"], -m["context"], m["id"]))
        return {"models": [{"id": m["id"], "name": m["name"], "context": m["context"], "note": "free" if m["free"] else "credits"} for m in allowed[:12]], "default": allowed[0]["id"] if allowed else "",
                "outdated": False, "error": "", "docs": HF_BILLING}

    def check(self, model):
        model = str(model or "")
        try:
            live = self.fetch(ttl=3600.0)
            entry = next((m for m in live if m["id"] == model), None)
            if entry is None:
                entry = next((m for m in self.fetch(force=True) if m["id"] == model), None)
        except AiError:
            raise AiError("not_free", "The Hugging Face model list cannot be loaded, so this model cannot be checked and was not used.") from None
        if entry is None or not self.allowed(entry):
            raise AiError("not_free", "That model is not free in Hugging Face's list (or its price changed), so it was not used. Pick a model marked free"
                          + ("." if self.use_credits() else "; models that spend credits are off (AI_HF_USE_CREDITS=0)."))
        return entry

    def auth_url(self, callback_url, challenge, state):
        q = urllib.parse.urlencode({"client_id": self.client_id(), "redirect_uri": callback_url, "response_type": "code", "scope": "inference-api", "state": state,
                                    "code_challenge": challenge, "code_challenge_method": "S256"})
        return self.hub() + "/oauth/authorize?" + q

    def exchange(self, code, verifier, redirect, opener=orr._open):
        body = urllib.parse.urlencode({"grant_type": "authorization_code", "code": code, "redirect_uri": redirect, "client_id": self.client_id(), "code_verifier": verifier}).encode("ascii")
        req = urllib.request.Request(self.hub() + "/oauth/token", data=body, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json", "User-Agent": "PlasBench-AI-help"})
        try:
            with opener(req, orr.CONNECT_TIMEOUT) as resp:
                data = json.loads(resp.read(65536).decode("utf-8", "replace"))
        except urllib.error.HTTPError:
            raise AiError("signin", "Hugging Face refused the sign-in code. Start the sign-in again.") from None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise orr._transport_error(exc) from None
        tok = data.get("access_token") if isinstance(data, dict) else None
        if not isinstance(tok, str) or not orr.KEY_SHAPE.match(tok):
            raise AiError("signin", "Hugging Face's answer did not contain a token. Start the sign-in again.")
        out = {"key": tok}
        try:
            if float(data.get("expires_in") or 0) > 0:
                out["expires"] = int(time.time() + float(data["expires_in"]))
        except (TypeError, ValueError):
            pass
        return out

    def privacy(self):
        return {"where": "Hugging Face (router.huggingface.co), which passes the request to a model provider", "free": HF_FREE_NOTE,
                "links": {"billing": HF_BILLING, "privacy": "https://huggingface.co/privacy", "providers": "https://huggingface.co/docs/inference-providers/index"}}


# ------------------------------------------------------------------------------------------------------------------------------- local
class Local(Provider):
    id, name, needs_key, paste, service = "local", "This computer (Ollama, LM Studio)", False, False, ""

    def configured(self):
        return (True, "") if self.base_ok() else (False, "AI_LOCAL_BASE points to another computer; set AI_LOCAL_ALLOW_REMOTE=1 if you really want that.")

    def candidates(self) -> list:
        given = (self.s.get("AI_LOCAL_BASE") or "").strip().rstrip("/")
        return [given] if given else [OLLAMA_BASE, LMSTUDIO_BASE]

    def base_ok(self, base: str = "") -> bool:
        if str(self.s.get("AI_LOCAL_ALLOW_REMOTE")).strip().lower() not in ("", "0", "off", "false", "no"):
            return True
        for b in ([base] if base else self.candidates()):
            host = urllib.parse.urlparse(b).hostname or ""
            if host not in ("127.0.0.1", "localhost", "::1"):
                return False
        return True

    def base(self):
        return self._found or self.candidates()[0]

    _found = ""

    def detect(self, opener=orr._open) -> dict:
        """The first local server that lists models: {"found": bool, "base", "models": [ids]}. Only loopback addresses are tried (unless AI_LOCAL_ALLOW_REMOTE=1)."""
        if not self.base_ok():
            return {"found": False, "base": "", "models": [], "error": self.configured()[1]}
        for b in self.candidates():
            try:
                req = urllib.request.Request(b + "/models", headers={"Accept": "application/json"})
                with opener(req, 2.5) as resp:
                    data = json.loads(resp.read(4 * 2**20).decode("utf-8", "replace"))
                ids = [str(m["id"]) for m in (data.get("data") if isinstance(data, dict) else None) or [] if isinstance(m, dict) and m.get("id")]
                if ids:
                    self._found = b
                    return {"found": True, "base": b, "models": ids}
            except (urllib.error.URLError, OSError, ValueError, KeyError):
                continue
        return {"found": False, "base": "", "models": [], "error": ""}

    def models_info(self, force=False):
        d = self.detect()
        names = [{"id": i, "name": i, "context": 0, "note": "local"} for i in d["models"]]
        return {"models": names, "default": names[0]["id"] if names else "", "outdated": False,
                "error": "" if names else "No local server found. Start Ollama (port 11434) or LM Studio (port 1234) and load a model.", "docs": "https://docs.ollama.com/api/openai-compatibility"}

    def check(self, model):
        if not self.base_ok(self.base()):
            raise AiError("not_free", "The local server address is not on this computer.")
        d = self.detect()
        if model not in d["models"]:
            raise AiError("not_free", "That model is not loaded in the local server, or the server is not running.")
        return {"id": model, "effort_none": False}

    def error_map(self):
        def m(status, body="", headers=None, key=""):
            e = orr.map_error(status, body, headers, key)
            if e.kind == "offline" or status >= 500:
                return AiError("offline", "The local model server did not answer. Check that it is running and the model is loaded.")
            return e
        return m

    def chat(self, key, chain, messages, max_tokens, fallback, info):
        return orr.run_chat(self.base(), "", chain[:1], messages, max_tokens, False, info=info, check=self.check, error_map=self.error_map(), extra_body={"stream_options": {"include_usage": True}})

    def privacy(self):
        return {"where": "This computer only", "free": "Nothing is sent anywhere: the question and the documentation excerpts go to the model server running on this computer (Ollama or LM Studio).", "links": {}}


PROVIDERS = {"openrouter": OpenRouter, "huggingface": HuggingFace, "local": Local}
ORDER = ("openrouter", "huggingface", "local")


def get(provider_id: str, settings) -> Provider:
    return PROVIDERS.get(provider_id or "openrouter", OpenRouter)(settings)


def all_public(settings) -> list:
    return [PROVIDERS[i](settings).public() for i in ORDER]
