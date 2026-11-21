"""PlasBench AI help: the part that ties retrieval, the prompt, a provider's model, the action checks and the window's routes together.

What happens for one question: the question is searched in PlasBench's own documentation (plasbench/ai_kb.py), a compact prompt is built (plasbench/ai_prompt.py), a model of the
chosen provider answers it (plasbench/ai_providers.py: OpenRouter free models, Hugging Face, or a server on this computer), the answer is streamed back, and any commands in it
are checked (plasbench/ai_actions.py). Nothing runs from here: a proposed command only becomes a button the person can click, and that click goes through the window's consent
dialog and the Jobs machinery.

The routes (all under /api/ai/, all behind the window's token, Host and same-origin checks; the exceptions are the sign-in callbacks, guarded by a one-time `state`):
    GET  ai/status            what the pane needs to draw itself (never a key); ?detect=1 also looks for a local model server
    GET  ai/models            the models of a provider (and whether the list may be out of date)
    POST ai/consent           the person pressed "I understand" on the first-use notice of a provider
    POST ai/auth/start        begin the pop-up sign-in; returns the address to open in the pop-up
    GET  ai/auth/status       did the pop-up finish? (state=...)
    POST ai/key               save a key or token the person pasted
    POST ai/signout           delete the stored key
    POST ai/ask               a question: the answer streams back as JSON lines
    POST ai/validate          check a proposed command (the card's buttons depend on it)
    POST ai/redact            the redacted tail of a command's output, to attach to the next question
Standard library only.
"""
from __future__ import annotations

import html
import json
import platform
import re
import time
from pathlib import Path

from . import __version__, ai_actions, ai_kb, ai_openrouter as orr, ai_prompt, ai_providers

DEFAULTS = {"AI_HELP_ENABLED": "1", "AI_PROVIDER": "openrouter", "AI_MODEL": "", "AI_DAILY_TOKEN_CAP": "200000", "AI_BRIEF": "0", "AI_FREE_FALLBACK": "1", "AI_OPENROUTER_BASE": "",
            "AI_HF_CLIENT_ID": "", "AI_HF_BASE": "", "AI_HF_HUB": "", "AI_HF_USE_CREDITS": "0", "AI_LOCAL_BASE": "", "AI_LOCAL_ALLOW_REMOTE": "0"}
CALLBACK_PATHS = {ai_providers.OR_CALLBACK: "openrouter", ai_providers.HF_CALLBACK: "huggingface"}
CALLBACK_PATH = ai_providers.OR_CALLBACK
DISCLOSURE_VERSION = 3


def truthy(value) -> bool:
    return str(value).strip().lower() not in ("", "0", "off", "false", "no")


class Settings:
    """The AI settings of a project (Settings page, config/local.env or the environment), read fresh each time."""

    def __init__(self, project=None):
        self.project = project

    def get(self, key: str) -> str:
        if self.project is not None:
            try:
                return str(self.project.setting(key, DEFAULTS.get(key, "")))
            except Exception:  # noqa: BLE001 - a settings file that cannot be read must not break the pane
                pass
        import os
        return os.environ.get(key) or DEFAULTS.get(key, "")

    def enabled(self) -> bool:
        return truthy(self.get("AI_HELP_ENABLED"))

    def base(self) -> str:
        return orr.base_url(self.get("AI_OPENROUTER_BASE"))

    def cap(self) -> int:
        try:
            return max(0, int(float(self.get("AI_DAILY_TOKEN_CAP") or 0)))
        except ValueError:
            return 200000

    def brief(self) -> bool:
        return truthy(self.get("AI_BRIEF"))

    def fallback(self) -> bool:
        return truthy(self.get("AI_FREE_FALLBACK"))

    def model(self) -> str:
        return self.get("AI_MODEL").strip()

    def provider(self) -> str:
        p = self.get("AI_PROVIDER").strip().lower()
        return p if p in ai_providers.PROVIDERS else "openrouter"


# ----------------------------------------------------------------------------------------------------------------------------- consent
def consent_path() -> Path:
    return orr.ai_home() / "consent.json"


def consent_given(provider: str = "openrouter") -> bool:
    try:
        with open(consent_path(), encoding="utf-8") as fh:
            return int((json.load(fh).get("providers") or {}).get(provider, 0)) >= DISCLOSURE_VERSION
    except (OSError, ValueError, AttributeError, TypeError):
        return False


def give_consent(provider: str = "openrouter") -> None:
    try:
        with open(consent_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    provs = data.get("providers") if isinstance(data.get("providers"), dict) else {}
    provs[provider] = DISCLOSURE_VERSION
    orr.write_private(consent_path(), {"providers": provs, "t": int(time.time())})


def disclosure(p: "ai_providers.Provider") -> dict:
    """What the first-use notice says, for one provider: what is sent, what is not, where it goes, where the key lives, how to delete it."""
    pr = p.privacy()
    local = p.id == "local"
    return {"version": DISCLOSURE_VERSION, "provider": p.id, "name": p.name, "where": pr["where"],
            "sent": ["your question", "the few documentation excerpts found for it", "the last few turns of this chat", "a short setup line (PlasBench version, system type, WSL or not, conda or Docker, the stage or the failure the window knows)",
                     "command output only when you press Send result, after removing your folder names, user name, e-mail addresses, keys and IP addresses"],
            "not_sent": ["file names and folder paths", "your user name or e-mail address", "accession lists or your data", "any key or password"],
            "stored": "Nothing is stored: no key is needed." if local else "Your key or sign-in token is stored only on this computer, in a private file under your home folder (.plasbench/ai). It is never shown in this window or written to a log.",
            "delete": "Nothing to delete." if local else "Sign out deletes it. You can also delete the folder .plasbench/ai in your home folder, and revoke the key or app access at the provider.",
            "free": pr["free"], "links": pr["links"], "headline": "Nothing is sent anywhere: the model runs on this computer." if local else f"Your questions and the excerpts leave this computer and go to {pr['where']}."}


# ------------------------------------------------------------------------------------------------------------------------- the service
class Service:
    def __init__(self, project=None, provider: str = ""):
        self.settings = Settings(project)
        self.project = project
        self.p = ai_providers.get(provider or self.settings.provider(), self.settings)
        self.keys = self.p.keystore()
        self.usage = self.p.usage()

    def setup(self, page: dict = None) -> dict:
        """The non-personal facts the model gets: PlasBench version, system type, WSL, runtime, and (from the window) the stage or last failure as short plain text."""
        from . import netcheck
        page = page or {}
        os_name = {"Windows": "Windows", "Darwin": "macOS", "Linux": "Linux"}.get(platform.system(), platform.system() or "unknown")
        out = {"version": __version__, "os": os_name, "wsl": "yes" if netcheck.is_wsl() else "no", "runtime": self.settings.get("PLASBENCH_RUNTIME") or "conda"}
        for key in ("stage", "last_failure"):
            if page.get(key):
                out[key] = str(page[key])[:90]
        return out

    # ------------------------------------------------------------------------------------------------ status
    def provider_rows(self, detect: bool = False) -> list:
        rows = []
        for pid in ai_providers.ORDER:
            pv = ai_providers.get(pid, self.settings)
            row = pv.public()
            st = pv.keystore().status()
            row["signed_in"] = st["signed_in"] or (not pv.needs_key and row["configured"])
            row["source"] = st["source"]
            if pid == "local" and detect:
                d = pv.detect()
                row["detected"] = d["found"]
                row["models_found"] = len(d["models"])
            row["visible"] = bool(row["configured"] and (pid != "huggingface" or pv.client_id() or st["signed_in"]) and (pid != "local" or row.get("detected", False) or pid == self.p.id))
            rows.append(row)
        return rows

    def status(self, detect: bool = False) -> dict:
        s = self.settings
        key = self.keys.status()
        day = self.usage.day()
        rows = self.provider_rows(detect)
        signed = {r["id"]: r["signed_in"] for r in rows}
        suggested = s.provider()
        if not signed.get(suggested) or (suggested == "local" and not any(r["id"] == "local" and r.get("detected") for r in rows)):
            if signed.get("openrouter"):
                suggested = "openrouter"
            elif any(r["id"] == "local" and r.get("detected") for r in rows):
                suggested = "local"
            else:
                suggested = "openrouter"
        return {"enabled": s.enabled(), "provider": self.p.id, "suggested": suggested, "providers": rows, "signed_in": key["signed_in"] or not self.p.needs_key, "source": key["source"],
                "consent": consent_given(self.p.id), "model": s.model(), "brief": s.brief(), "fallback": s.fallback(), "cap": s.cap(),
                "used_today": {"tokens": day["prompt"] + day["completion"], "prompt": day["prompt"], "completion": day["completion"], "requests": day["calls"]},
                "kb": ai_kb.available(), "custom_base": not self.p.default_base(), "disclosure": disclosure(self.p), "version": __version__, "needs_key": self.p.needs_key,
                "oauth": self.p.public()["oauth"], "paste": self.p.paste}

    def models(self, force: bool = False) -> dict:
        info = self.p.models_info(force)
        chosen = self.settings.model()
        if chosen and not any(m["id"] == chosen for m in info["models"]):
            chosen = ""
        out = dict(info)
        out["selected"] = chosen or info["default"]
        out["provider"] = self.p.id
        return out

    def key_save(self, key: str) -> dict:
        self.keys.save((key or "").strip(), "pasted")
        return self.keys.status()

    def signout(self) -> dict:
        self.keys.delete()
        return self.keys.status()

    # ------------------------------------------------------------------------------------------------ asking
    def preflight(self) -> str:
        """Everything that can refuse a question before anything is sent. Returns the key ("" for a local server). Raises AiError (or netgate.Offline)."""
        s = self.settings
        if not s.enabled():
            raise orr.AiError("disabled", "AI help is off (the AI_HELP_ENABLED setting is 0).", 403)
        if not consent_given(self.p.id):
            raise orr.AiError("consent", "Read the notice about what is sent, and press I understand, before the first question.", 403)
        ok, why = self.p.configured()
        if not ok:
            raise orr.AiError("bad_request", why, 400)
        key = self.keys.key()
        if self.p.needs_key and not key:
            raise orr.AiError("signin", f"Sign in to {self.p.name} first (Sign in), or paste your own key under Advanced.", 401)
        if self.p.id != "local":
            self.usage.check_cap(s.cap())
        self.p.require_online("ask the AI help")
        return key

    def plan(self, question: str, history: list, page: dict, brief: bool, result_text: str, model: str) -> dict:
        kb = ai_kb.load()
        hint = "fail" if (page or {}).get("last_failure") else ""
        hits = kb.search(question + (" " + str(history[-1].get("content", ""))[:200] if history and len(question.split()) < 4 else ""), 5, hint)
        return ai_prompt.build(question, hits, history, self.setup(page), brief, result_text, model)

    def ask(self, payload: dict):
        """Yield event dicts for one question: meta, notice, delta, done (or error). Raises AiError/Offline only BEFORE the first event (pre-flight); later problems are error events."""
        question = str(payload.get("question") or "").strip()
        if not question:
            raise orr.AiError("bad_request", "Type a question first.", 400)
        history = [t for t in (payload.get("history") or []) if isinstance(t, dict)][-12:]
        brief = bool(payload.get("brief", self.settings.brief()))
        page = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        result = payload.get("result") if isinstance(payload.get("result"), dict) else None
        result_text = ""
        if result:
            try:
                code = int(result.get("exit") or 0)
            except (TypeError, ValueError):
                code = 0
            result_text = f"Command: {ai_actions.redact_output(str(result.get('command') or '')[:200], 1)}\nExit code: {code}\n" + ai_actions.redact_output(str(result.get("output") or ""))
        key = self.preflight()
        chain = self.p.chain(str(payload.get("model") or ""))
        self.p.check(chain[0])                      # a model that may not be called stops here, before anything is sent
        built = self.plan(question, history, page, brief, result_text, chain[0])
        yield {"type": "meta", "sources": built["sources"], "model": chain[0], "provider": self.p.id, "tokens_est": built["tokens"]["total"], "max_tokens": built["max_tokens"]}
        parts, usage, info, used_model = [], None, {}, chain[0]
        gen = self.p.chat(key, chain, built["messages"], built["max_tokens"], self.settings.fallback(), info)
        try:
            for kind, value in gen:
                if kind == "delta":
                    parts.append(value)
                    yield {"type": "delta", "text": value}
                elif kind == "usage":
                    usage = value
                elif kind == "model":
                    used_model = value
                elif kind == "notice":
                    yield {"type": "notice", "text": value}
        except orr.AiError as exc:
            orr.log_event(exc.status or 0, used_model, built["tokens"]["total"], 0, exc.kind)
            yield dict(exc.payload(), type="error", partial="".join(parts))
            return
        finally:
            gen.close()
        reply = "".join(parts)
        pt = int((usage or {}).get("prompt_tokens") or built["tokens"]["total"])
        ct = int((usage or {}).get("completion_tokens") or ai_prompt.estimate_tokens(reply))
        self.usage.add(pt, ct, 0.0)
        orr.log_event(200, used_model, pt, ct)
        parsed = ai_actions.parse_reply(reply)
        remaining = {}
        hdr = info.get("headers") or {}
        if hdr.get("X-RateLimit-Remaining"):
            remaining["remaining"] = hdr["X-RateLimit-Remaining"]
        remaining.update(self.p.limits(key) if key else {})
        day = self.usage.day()
        yield {"type": "done", "text": parsed["text"], "actions": parsed["actions"], "model": used_model, "provider": self.p.id, "free": self._is_free(used_model),
               "usage": {"prompt": pt, "completion": ct, "total": pt + ct, "estimated": not usage, "cached": int(((usage or {}).get("prompt_tokens_details") or {}).get("cached_tokens") or 0)},
               "today": {"tokens": day["prompt"] + day["completion"], "requests": day["calls"], "cap": self.settings.cap()}, "free_requests": remaining}

    def _is_free(self, model: str) -> bool:
        if self.p.id == "local":
            return True
        try:
            e = self.p.check(model)
            return bool(e.get("free", True))
        except Exception:  # noqa: BLE001
            return False


# ---------------------------------------------------------------------------------------------------------------------- callback page
def _page(ok: bool, origin: str, state: str) -> bytes:
    """The one static page the pop-up shows after the provider sends the person back. It reflects nothing from the request: the message is one of two fixed texts, and the only values
    in the script are the opener's origin and the state that this server itself issued (both JSON-escaped)."""
    msg = "Signed in. This window closes by itself; you can return to PlasBench." if ok else "The sign-in did not complete. Close this window and try again in PlasBench."
    data = json.dumps({"type": "plasbench-ai-auth", "ok": bool(ok), "state": state}).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    target = json.dumps(origin).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026") if origin else "null"
    script = ("try{var o=" + target + ";if(o&&window.opener){window.opener.postMessage(" + data + ",o);}}catch(e){}setTimeout(function(){try{window.close();}catch(e){}},900);")
    return ('<!doctype html><meta charset="utf-8"><title>PlasBench</title><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<body style="font:16px system-ui,sans-serif;margin:32px;max-width:30em"><h2>PlasBench</h2><p>' + html.escape(msg) + "</p><script>" + script + "</script></body>").encode("utf-8")


def handle_callback(flows: "orr.AuthFlows", settings: Settings, query: dict, path: str = ai_providers.OR_CALLBACK, opener=orr._open) -> bytes:
    """The sign-in callback: validate the single-use state, exchange the code with the stored verifier, save the key, and return the static page. Never raises."""
    state = str(query.get("state") or "")
    code = str(query.get("code") or "")
    origin = flows.peek_origin(state)
    flow = flows.consume(state)
    provider = CALLBACK_PATHS.get(path, "")
    if flow is None or flow.get("provider") != provider or not code or not re.match(r"^[A-Za-z0-9._~\-]{4,2048}$", code):
        if flow is not None:
            flows.finish(state, False)
        return _page(False, origin, state if flow is not None else "")
    try:
        pv = ai_providers.get(provider, settings)
        got = pv.exchange(code, flow["verifier"], flow["redirect"], opener)
        pv.keystore().save(got["key"], "oauth", got.get("expires"))
    except Exception:  # noqa: BLE001 - the page only says it did not complete; the reason is never reflected
        flows.finish(state, False)
        return _page(False, origin, state)
    flows.finish(state, True)
    return _page(True, origin, state)


# -------------------------------------------------------------------------------------------------------------------- route glue
FLOWS = orr.AuthFlows()
ROUTES_GET = ("ai/status", "ai/models", "ai/auth/status")
ROUTES_POST = ("ai/consent", "ai/auth/start", "ai/key", "ai/signout", "ai/ask", "ai/validate", "ai/redact")


def is_ai_route(route: str) -> bool:
    return route.startswith("ai/")


def write_event(handler, obj: dict) -> None:
    handler.wfile.write((json.dumps(obj, default=str) + "\n").encode("utf-8"))
    handler.wfile.flush()


def serve(handler, method: str, route: str, data: dict, q: dict, project) -> None:
    """Answer one /api/ai/ request on the window's handler (token, Host and same-origin were checked by the caller)."""
    from . import netgate
    data = data if isinstance(data, dict) else {}
    svc = Service(project, str(data.get("provider") or q.get("provider") or ""))
    try:
        if route not in ROUTES_GET + ROUTES_POST or (method == "GET") != (route in ROUTES_GET):
            return handler.jsend(404, {"error": f"no such API: {route}"})
        if not svc.settings.enabled() and route != "ai/status":
            return handler.jsend(403, {"error": "AI help is off (the AI_HELP_ENABLED setting is 0).", "kind": "disabled"})
        if route == "ai/status":
            return handler.jsend(200, svc.status(q.get("detect") == "1"))
        if route == "ai/models":
            return handler.jsend(200, svc.models(force=q.get("refresh") == "1"))
        if route == "ai/auth/status":
            r = FLOWS.result(q.get("state", ""))
            return handler.jsend(200, {"done": r is not None, "ok": bool(r and r["ok"]), "signed_in": svc.keys.status()["signed_in"]})
        if route == "ai/consent":
            give_consent(svc.p.id)
            return handler.jsend(200, {"ok": True})
        if route == "ai/signout":
            return handler.jsend(200, svc.signout())
        if route == "ai/key":
            if not svc.p.paste:
                raise orr.AiError("bad_request", f"{svc.p.name} does not use a key.", 400)
            return handler.jsend(200, svc.key_save(str(data.get("key") or "")))
        if route == "ai/auth/start":
            if not consent_given(svc.p.id):
                raise orr.AiError("consent", "Read the notice about what is sent, and press I understand, first.", 403)
            if not svc.p.public()["oauth"]:
                raise orr.AiError("bad_request", svc.p.configured()[1] or f"{svc.p.name} has no pop-up sign-in.", 400)
            svc.p.require_online("sign in")
            host = (handler.headers.get("Host") or "").rsplit(":", 1)
            port = host[1] if len(host) == 2 and host[1].isdigit() else "8770"
            origin = handler.headers.get("Origin") or ""
            return handler.jsend(200, FLOWS.begin(f"http://localhost:{port}{svc.p.callback_path}", origin, svc.p.base(), build=svc.p.auth_url, provider=svc.p.id))
        if route == "ai/validate":
            return handler.jsend(200, ai_actions.validate(str(data.get("cmd") or ""), str(data.get("where") or "terminal"), str(data.get("risk") or "")))
        if route == "ai/redact":
            return handler.jsend(200, {"text": ai_actions.redact_output(str(data.get("output") or ""))})
        if route == "ai/ask":
            events = svc.ask(data)
            first = next(events)                      # pre-flight errors surface here, before any byte is streamed
            handler.send_response(200)
            handler.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            handler.send_header("Cache-Control", "no-store")
            handler.send_header("X-Content-Type-Options", "nosniff")
            handler.send_header("Connection", "close")
            handler.close_connection = True
            handler.end_headers()
            try:
                write_event(handler, first)
                for ev in events:
                    write_event(handler, ev)
            except (BrokenPipeError, ConnectionError, OSError):
                pass                                   # the page aborted: closing the generator closes the connection to the service
            finally:
                events.close()
            return None
        return handler.jsend(404, {"error": f"no such API: {route}"})
    except orr.AiError as exc:
        return handler.jsend(exc.status if exc.status in (400, 401, 402, 403, 429) else 502 if exc.kind in ("model_down", "offline", "timeout", "server") else 400, exc.payload())
    except netgate.Offline as exc:
        return handler.jsend(503, exc.payload())
