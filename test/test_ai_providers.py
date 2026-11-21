#!/usr/bin/env python3
"""AI help providers against local stub servers (no real OpenRouter, Hugging Face or model server is called, and no real key exists here).

PKCE (the RFC 7636 test vector), the one-time sign-in state (single use, expiry, bound to its provider), the callback page (nothing from the query is reflected), the key file
(mode 0600, never in a response, a log or an error), the free-only rule (a paid model, a router, a model that turned paid are never offered or called), the models list, streaming
with usage, the error mapping (401 / 402 / 429 / 500 / mid-stream), the fallback to another FREE model, an abort that closes the upstream connection, Hugging Face sign-in and
pricing, and the local server (present, absent, loopback only)."""
import json
import os
import stat
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "test"))
import ai_stub  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(f"  {'ok  ' if good else 'FAIL'}  {label}{'' if good else ' -> ' + str(detail)[:300]}")
    ok &= bool(good)


stub = ai_stub.Stub()
home = tempfile.mkdtemp(prefix="pb_ai_")
os.environ.update(stub.env())
os.environ["PLASBENCH_AI_HOME"] = home + "/ai"
os.environ["PLASBENCH_UI_HOME"] = home + "/ui"
os.environ["AI_HF_CLIENT_ID"] = "test-client-id"
os.environ["AI_HF_USE_CREDITS"] = "0"

from plasbench import ai_help, ai_openrouter as orr, ai_prompt, ai_providers  # noqa: E402

S = ai_help.Settings(None)
print("PKCE")
check("RFC 7636 appendix B vector", orr.challenge_of("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM")
v = orr.new_verifier()
check("verifier is 43..128 unreserved characters", 43 <= len(v) <= 128 and all(c.isalnum() or c in "-._~" for c in v), v)
check("verifiers differ", orr.new_verifier() != orr.new_verifier())

print("sign-in state")
now = [1000.0]
flows = orr.AuthFlows(clock=lambda: now[0])
b = flows.begin("http://localhost:8770/ai/openrouter/callback", "http://127.0.0.1:8770", "http://x/api/v1")
q = urllib.parse.parse_qs(urllib.parse.urlparse(b["url"]).query)
check("auth address carries S256 challenge, callback and state", q["code_challenge_method"] == ["S256"] and q["callback_url"][0].startswith("http://localhost:8770/") and q["state"] == [b["state"]])
check("the verifier itself is not in the address", flows.items[b["state"]]["verifier"] not in b["url"])
check("state works once", flows.consume(b["state"]) is not None and flows.consume(b["state"]) is None)
b2 = flows.begin("http://localhost:8770/x", "http://127.0.0.1:8770", "http://x/api/v1")
now[0] += orr.STATE_TTL + 1
check("state expires after 10 minutes", flows.consume(b2["state"]) is None)
check("a foreign opener origin is dropped", orr.AuthFlows().begin("http://localhost:1/x", "https://evil.example", "http://x/api/v1") and True)
f3 = orr.AuthFlows()
b3 = f3.begin("http://localhost:1/x", "https://evil.example", "http://x/api/v1")
check("opener origin must be loopback", f3.peek_origin(b3["state"]) == "")

print("OpenRouter sign-in end to end (stub)")
ai_help.FLOWS.items.clear()
begin = ai_help.FLOWS.begin("http://localhost:8770/ai/openrouter/callback", "http://127.0.0.1:8770", S.base(), build=ai_providers.get("openrouter", S).auth_url, provider="openrouter")
req = urllib.request.Request(begin["url"].replace("http://127.0.0.1:%d/auth" % stub.port, "http://127.0.0.1:%d/auth" % stub.port))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


try:
    urllib.request.build_opener(NoRedirect).open(req)
    loc = ""
except urllib.error.HTTPError as e:
    loc = e.headers.get("Location", "")
check("the stub sign-in page redirects to the callback with a code and the state", "code=" in loc and "state=" + begin["state"] in loc, loc)
cq = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(loc).query).items()}
page = ai_help.handle_callback(ai_help.FLOWS, S, cq, ai_providers.OR_CALLBACK).decode()
check("callback page says signed in and posts to the recorded origin only", "Signed in" in page and '"http://127.0.0.1:8770"' in page and "postMessage" in page, page[:200])
kf = Path(home) / "ai" / "openrouter.json"
check("the key file exists", kf.is_file())
if os.name == "posix":
    check("key file mode is 0600", stat.S_IMODE(kf.stat().st_mode) == 0o600, oct(kf.stat().st_mode))
    check("key folder mode is 0700", stat.S_IMODE(kf.parent.stat().st_mode) == 0o700, oct(kf.parent.stat().st_mode))
check("the exchange sent code, verifier and S256 (no key)", any(r["path"].endswith("/auth/keys") and r["body"].get("code_challenge_method") == "S256" for r in stub.requests))
check("the sign-in is recorded as done", ai_help.FLOWS.result(begin["state"]) == {"ok": True})
check("a repeat of the same callback is refused (state used)", b"did not complete" in ai_help.handle_callback(ai_help.FLOWS, S, cq, ai_providers.OR_CALLBACK))
check("status never contains the key", ai_stub.FAKE_KEY not in json.dumps(ai_help.Service(None, "openrouter").status()))
check("status says signed in", ai_help.Service(None, "openrouter").status()["signed_in"])

print("callback page escaping and state binding")
b = ai_help.FLOWS.begin("http://localhost:8770/x", "http://127.0.0.1:8770", S.base(), provider="openrouter")
evil = '"><script>alert(1)</script>&<'
page = ai_help.handle_callback(ai_help.FLOWS, S, {"state": evil, "code": evil, "error": evil, "error_description": evil}, ai_providers.OR_CALLBACK).decode()
check("nothing from the query is reflected", "alert(1)" not in page and "&lt;" not in page.replace("&lt;", "") and evil not in page, page)
page = ai_help.handle_callback(ai_help.FLOWS, S, {"state": b["state"], "code": "x" * 10}, ai_providers.HF_CALLBACK).decode()
check("a state of another provider is refused on this callback", "did not complete" in page)
page = ai_help.handle_callback(ai_help.FLOWS, S, {"code": ai_stub.GOOD_CODE}, ai_providers.OR_CALLBACK).decode()
check("no state means no exchange", "did not complete" in page)

print("free-only models")
info = orr.load_free(S.base(), force=True)
ids = [m["id"] for m in info["models"]]
check("free models are offered", "stub/free-a:free" in ids and "stub/free-b:free" in ids, ids)
for bad in ("stub/paid-x", "openrouter/free", "openrouter/auto", "stub/free-audio:free", "stub/free-small:free", "stub/free-reason:free", "stub/free-priced-request:free", "stub/half-free"):
    check(f"{bad} is not offered", bad not in ids)
check("the default is a free model", info["default"] in ids and info["default"] == "stub/free-a:free", info["default"])
check("a free model passes ensure_free", orr.ensure_free(S.base(), "stub/free-a:free")["id"] == "stub/free-a:free")
for bad in ("stub/paid-x", "openrouter/auto", "openrouter/free", "stub/half-free", "nonsense/none"):
    try:
        orr.ensure_free(S.base(), bad)
        check(f"ensure_free refuses {bad}", False)
    except orr.AiError as e:
        check(f"ensure_free refuses {bad}", e.kind == "not_free", e.kind)
stub.flip_paid.add("stub/turns-paid:free")
orr._MODELS["t"] = 0
try:
    orr.ensure_free(S.base(), "stub/turns-paid:free")
    check("a model that turned paid is refused at request time", False)
except orr.AiError as e:
    check("a model that turned paid is refused at request time", e.kind == "not_free")
stub.flip_paid.clear()

svc = ai_help.Service(None, "openrouter")
ai_help.give_consent("openrouter")
stub.requests.clear()
try:
    list(svc.ask({"question": "how do I check my installation?", "model": "stub/paid-x"}))
    check("asking with a paid model sends nothing", False)
except orr.AiError as e:
    check("asking with a paid model is refused", e.kind == "not_free")
check("no chat request reached the service for the paid model", not stub.chat_requests())
ev = list(svc.ask({"question": "how do I check my installation?", "model": "stub/free-b:free"}))
check("a free model is used", ev[0]["type"] == "meta" and ev[0]["model"] == "stub/free-b:free" and stub.chat_requests()[0]["body"]["model"] == "stub/free-b:free")
body = stub.chat_requests()[0]["body"]
check("request is streamed, capped, and system prompt first", body["stream"] is True and body["max_tokens"] == ai_prompt.DEFAULT_MAX_TOKENS == 2000 and body["messages"][0]["role"] == "system")
check("the key went in the Authorization header only", stub.chat_requests()[0]["headers"].get("Authorization") == "Bearer " + ai_stub.FAKE_KEY and ai_stub.FAKE_KEY not in json.dumps(body))
done = ev[-1]
check("done carries the answer, usage and a validated action", done["type"] == "done" and done["usage"]["total"] == 1240 and not done["usage"]["estimated"] and done["actions"][0]["runnable"], done)
check("the text without the action block", "pb-action" not in done["text"] and "plasbench status" in done["text"])
check("remaining free requests are shown", done["free_requests"].get("remaining") == 47, done["free_requests"])
check("usage is counted", svc.usage.day()["calls"] >= 1 and svc.usage.day()["prompt"] >= 1200)

print("error mapping")
for mode, kind, status in (("401", "signin", 401), ("402", "no_credits", 402), ("429", "rate_limit", 429), ("500", "server", 500)):
    stub.mode = mode
    ev = list(svc.ask({"question": "what is cprr?", "model": "stub/free-a:free"}))
    last = ev[-1]
    check(f"{mode} -> {kind}", last["type"] == "error" and last["kind"] == kind, last)
    check(f"{mode}: the key is not in the message", ai_stub.FAKE_KEY not in json.dumps(last))
stub.mode = "429"
ev = list(ai_help.Service(None, "openrouter").ask({"question": "what is cprr?", "model": "stub/free-a:free"}))
check("429 carries a retry hint and the limits link", ev[-1].get("retry_after") == 7.0 and "openrouter.ai/docs" in ev[-1].get("link", ""), ev[-1])
stub.mode = "midstream_error"
ev = list(svc.ask({"question": "what is cprr?", "model": "stub/free-a:free"}))
check("an error inside the stream becomes an error event with the partial text", ev[-1]["type"] == "error" and "partial" in ev[-1])

print("fallback to another FREE model")
stub.mode = "429_once"
stub.once["n"] = 0
stub.requests.clear()
ev = list(svc.ask({"question": "what is cprr?", "model": "stub/free-a:free"}))
used = [r["body"]["model"] for r in stub.chat_requests()]
check("the next free model answered", ev[-1]["type"] == "done" and len(used) == 2 and used[0] != used[1], used)
check("a notice told the person", any(e["type"] == "notice" for e in ev))
check("every model tried was free", all(m in ids for m in used), used)
stub.mode = "429"
stub.requests.clear()
os.environ["AI_FREE_FALLBACK"] = "0"
ev = list(ai_help.Service(None, "openrouter").ask({"question": "what is cprr?", "model": "stub/free-a:free"}))
check("with fallback off the first limit stops it", ev[-1]["type"] == "error" and len(stub.chat_requests()) == 1)
os.environ["AI_FREE_FALLBACK"] = "1"
stub.mode = "ok"

print("abort closes the upstream connection")
stub.mode = "slow"
stub.closed_early.clear()
gen = ai_help.Service(None, "openrouter").ask({"question": "what is cprr?", "model": "stub/free-a:free"})
next(gen)
next(gen)
gen.close()
check("the stub saw the connection close early", stub.closed_early.wait(5))
stub.mode = "ok"

print("daily cap and offline")
os.environ["AI_DAILY_TOKEN_CAP"] = "100"
try:
    list(ai_help.Service(None, "openrouter").ask({"question": "what is cprr?"}))
    check("the daily cap stops a call", False)
except orr.AiError as e:
    check("the daily cap stops a call with a clear message", e.kind == "cap" and "100" in e.message, e.message)
os.environ["AI_DAILY_TOKEN_CAP"] = "200000"
os.environ["PLASBENCH_OFFLINE"] = "1"
from plasbench import netgate  # noqa: E402
try:
    list(ai_help.Service(None, "openrouter").ask({"question": "what is cprr?"}))
    check("forced offline refuses with Offline", False)
except netgate.Offline as e:
    check("forced offline refuses with Offline", e.service == "openrouter", e.service)
os.environ.pop("PLASBENCH_OFFLINE")
check("openrouter and huggingface are rows of the network table", {"openrouter", "huggingface"} <= set(netgate.SERVICES))

print("sign out and the key never leaves")
svc.signout()
check("sign out deletes the key file", not kf.exists())
try:
    list(ai_help.Service(None, "openrouter").ask({"question": "what is cprr?"}))
    check("asking when signed out asks for sign-in", False)
except orr.AiError as e:
    check("asking when signed out asks for sign-in", e.kind == "signin")
svc.key_save(ai_stub.FAKE_KEY)
log = Path(home) / "ui" / "ai.log"
check("a log exists and holds counts only", log.is_file() and ai_stub.FAKE_KEY not in log.read_text() and "prompt_tokens=" in log.read_text())
for f in Path(home).rglob("*"):
    if f.is_file() and f.name != "openrouter.json":
        check(f"the key is not in {f.name}", ai_stub.FAKE_KEY not in f.read_text(errors="ignore"))
check("scrub removes keys from text", orr.scrub("oops sk-or-v1-ABCDEF123456 and hf_ABCDEFGHIJ12345") == "oops <key removed> and <key removed>")

print("Hugging Face")
hf = ai_providers.get("huggingface", S)
check("the sign-in button is on with a client id", hf.public()["oauth"])
mi = hf.models_info(force=True)
hids = [m["id"] for m in mi["models"]]
check("only the router-listed free model is offered by default", hids == ["org/free-model:fakeprov"], hids)
for bad in ("org/pricey-model:fakeprov", "org/cheap-model:fakeprov", "org/image-model:fakeprov", "org/short-ctx:fakeprov"):
    try:
        hf.check(bad)
        check(f"{bad} is refused", False)
    except orr.AiError as e:
        check(f"{bad} is refused", e.kind == "not_free")
os.environ["AI_HF_USE_CREDITS"] = "1"
mi = ai_providers.get("huggingface", S).models_info(force=True)
hids = [m["id"] for m in mi["models"]]
check("with AI_HF_USE_CREDITS=1 a cheap model is offered, marked credits, after the free one", hids[0] == "org/free-model:fakeprov" and "org/cheap-model:fakeprov" in hids and "org/pricey-model:fakeprov" not in hids, hids)
check("the credits model is marked", [m["note"] for m in mi["models"] if m["id"] == "org/cheap-model:fakeprov"] == ["credits"])
os.environ["AI_HF_USE_CREDITS"] = "0"
ai_providers._HF["t"] = 0
ai_help.give_consent("huggingface")
begin = ai_help.FLOWS.begin("http://localhost:8770/ai/hf/callback", "http://127.0.0.1:8770", hf.base(), build=hf.auth_url, provider="huggingface")
hq = urllib.parse.parse_qs(urllib.parse.urlparse(begin["url"]).query)
check("authorize address: public client, PKCE S256, inference-api scope, no secret", hq["client_id"] == ["test-client-id"] and hq["code_challenge_method"] == ["S256"] and hq["scope"] == ["inference-api"] and "client_secret" not in hq, hq)
urllib.request.urlopen(begin["url"]).read()
page = ai_help.handle_callback(ai_help.FLOWS, S, {"state": begin["state"], "code": ai_stub.GOOD_CODE}, ai_providers.HF_CALLBACK).decode()
check("the code is exchanged (form body, verifier, same redirect, no client secret)", "Signed in" in page, page[:200])
tok = [r for r in stub.requests if r["path"].endswith("/oauth/token")][-1]
check("token request has no client_secret", "client_secret" not in tok["body"] and "code_verifier=" in tok["body"])
hfk = Path(home) / "ai" / "huggingface.json"
check("token stored privately with an expiry", hfk.is_file() and "expires" in json.loads(hfk.read_text()))
stub.requests.clear()
ev = list(ai_help.Service(None, "huggingface").ask({"question": "what is cprr?", "model": "org/free-model:fakeprov"}))
check("a Hugging Face question streams with the router model id", ev[-1]["type"] == "done" and stub.chat_requests()[0]["body"]["model"] == "org/free-model:fakeprov" and stub.chat_requests()[0]["path"].startswith("/hf/v1/"), ev[-1])
stub.requests.clear()
try:
    list(ai_help.Service(None, "huggingface").ask({"question": "what is cprr?", "model": "org/pricey-model:fakeprov"}))
    check("a priced model is never called", False)
except orr.AiError:
    check("a priced model is never called", not stub.chat_requests())
stub.mode = "402"
ev = list(ai_help.Service(None, "huggingface").ask({"question": "what is cprr?", "model": "org/free-model:fakeprov"}))
check("402 explains that free accounts have no credits", ev[-1]["kind"] == "no_credits" and "PRO" in ev[-1]["error"] and "huggingface.co" in ev[-1]["link"], ev[-1])
stub.mode = "ok"
os.environ["AI_HF_CLIENT_ID"] = ""
check("without a client id the button is off with a reason, paste still offered", not ai_providers.get("huggingface", ai_help.Settings(None)).public()["oauth"] and "AI_HF_CLIENT_ID" in ai_providers.get("huggingface", ai_help.Settings(None)).public()["reason"])
os.environ["AI_HF_CLIENT_ID"] = "test-client-id"
expired = Path(home) / "ai" / "huggingface.json"
rec = json.loads(expired.read_text())
rec["expires"] = int(time.time()) - 5
expired.write_text(json.dumps(rec))
check("an expired token counts as signed out", not ai_providers.get("huggingface", S).keystore().status()["signed_in"])

print("local server")
lp = ai_providers.get("local", S)
d = lp.detect()
check("a local server is detected from its model list", d["found"] and d["models"] == ["llama-local:8b", "qwen-local:4b"], d)
ai_help.give_consent("local")
stub.requests.clear()
ev = list(ai_help.Service(None, "local").ask({"question": "what is cprr?"}))
check("a local question needs no key and sends no Authorization header", ev[-1]["type"] == "done" and "Authorization" not in stub.chat_requests()[0]["headers"], ev[-1])
check("local asks for usage in the stream", stub.chat_requests()[0]["body"].get("stream_options") == {"include_usage": True})
check("the local disclosure says nothing leaves the computer", "Nothing is sent anywhere" in ai_help.disclosure(lp)["headline"])
os.environ["AI_LOCAL_BASE"] = "http://192.168.1.50:11434/v1"
lp2 = ai_providers.get("local", ai_help.Settings(None))
check("a non-loopback address is refused by default", not lp2.configured()[0] and not lp2.detect()["found"])
os.environ["AI_LOCAL_BASE"] = "http://127.0.0.1:9/v1"
check("an absent server is reported as not found", not ai_providers.get("local", ai_help.Settings(None)).detect()["found"])
os.environ["AI_LOCAL_BASE"] = stub.root + "/local/v1"

print("suggested provider")
ai_help.Service(None, "openrouter").signout()
st = ai_help.Service(None, "openrouter").status(detect=True)
check("with nothing signed in and a local server found, local is suggested", st["suggested"] == "local" and [p["id"] for p in st["providers"] if p["visible"]] , st["suggested"])
ai_help.Service(None, "openrouter").key_save(ai_stub.FAKE_KEY)
check("openrouter is suggested once signed in", ai_help.Service(None, "openrouter").status(detect=True)["suggested"] == "openrouter")

stub.stop()
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
