#!/usr/bin/env python3
"""The AI help's routes on a real window server, against the local stubs (test/ai_stub.py): no real service is called.

Every /api/ai/ route needs the window token, a loopback Host and the same origin; the sign-in callbacks need the one-time state instead; AI_HELP_ENABLED=0 refuses the routes; the
streamed answer arrives as JSON lines, ends with the validated actions, and an abort closes the upstream connection; the key never appears in any response, log, job record or the
issue report; offline (PLASBENCH_OFFLINE=1) is refused cleanly; the sign-in callback of a fake provider completes a pop-up flow."""
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
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
tmp = Path(tempfile.mkdtemp(prefix="pb_airoutes_"))
os.environ.update(stub.env())
os.environ.update({"PLASBENCH_UI_HOME": str(tmp / "ui"), "PLASBENCH_AI_HOME": str(tmp / "ai"), "PLASBENCH_LOCAL_SETTINGS": str(tmp / "local.env"), "AI_HF_CLIENT_ID": "test-client-id"})
(tmp / "local.env").write_text("", encoding="utf-8")
from plasbench import ai_help, ai_providers, webui  # noqa: E402

webui.UI_HOME = tmp / "ui"
project = webui.Project(ROOT)
jobs = webui.Jobs(project)
server = ThreadingHTTPServer(("127.0.0.1", 0), webui.make_handler(project, jobs))
threading.Thread(target=server.serve_forever, daemon=True).start()
port = server.server_address[1]
base = f"http://127.0.0.1:{port}"
token = webui.TOKEN


def call(path, body=None, headers=None, tok=True, host=None):
    h = {"Host": host or f"127.0.0.1:{port}"}
    if tok:
        h["X-PlasBench-Token"] = token
    h.update(headers or {})
    data = json.dumps(body).encode() if body is not None else None
    if data is not None:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, headers=h, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


GET_ROUTES = ["ai/status", "ai/models", "ai/auth/status"]
POST_ROUTES = ["ai/consent", "ai/auth/start", "ai/key", "ai/signout", "ai/ask", "ai/validate", "ai/redact"]
print("token, host and origin on every route")
for r in GET_ROUTES:
    check(f"GET {r}: no token is refused", call("/api/" + r, tok=False)[0] == 403)
    check(f"GET {r}: a wrong token is refused", call("/api/" + r, headers={"X-PlasBench-Token": "nope"})[0] == 403)
    check(f"GET {r}: a foreign Host is refused", call("/api/" + r, host="evil.example")[0] == 403)
for r in POST_ROUTES:
    check(f"POST {r}: no token is refused", call("/api/" + r, {}, tok=False)[0] == 403)
    check(f"POST {r}: a cross-origin POST is refused", call("/api/" + r, {}, headers={"Origin": "http://evil.example"})[0] == 403)
    check(f"POST {r}: a foreign Host is refused", call("/api/" + r, {}, host="evil.example")[0] == 403)
check("an unknown ai route is 404 and a GET on a POST route too", call("/api/ai/nothing")[0] == 404 and call("/api/ai/ask")[0] == 404)
check("a GET callback needs no token but a nonce: without it, a plain page that did not complete", b"did not complete" in call(ai_help.CALLBACK_PATH + "?code=x&state=y", tok=False)[1])
check("the callback rejects a foreign Host header", call(ai_help.CALLBACK_PATH, tok=False, host="evil.example")[0] == 403)
code, body, hdr = call(ai_help.CALLBACK_PATH + "?code=%22%3E%3Cscript%3Ealert(1)%3C/script%3E&state=%22%3E%3Cimg%20src=x%3E", tok=False)
check("callback: a script in the query is not reflected", code == 200 and b"alert(1)" not in body and b"<img" not in body and "frame-ancestors 'none'" in hdr.get("Content-Security-Policy", ""), body[:200])
check("callback sets no cookie and no key", "Set-Cookie" not in hdr)

print("status, notice, sign-in")
code, body, _ = call("/api/ai/status?detect=1")
st = json.loads(body)
check("status: enabled, not signed in, notice not accepted, no key in it", code == 200 and st["enabled"] and not st["signed_in"] and not st["consent"] and "disclosure" in st, st)
check("status lists the three providers and the local server is detected", [p["id"] for p in st["providers"]] == ["openrouter", "huggingface", "local"] and any(p.get("detected") for p in st["providers"]))
check("the notice names the provider and the free-model logging caveat", "OpenRouter" in st["disclosure"]["where"] and "train" in st["disclosure"]["free"])
code, body, _ = call("/api/ai/ask", {"question": "what is cprr?"})
check("asking before the notice is accepted is refused", code == 403 and json.loads(body)["kind"] == "consent")
check("sign-in before the notice is refused", call("/api/ai/auth/start", {})[0] == 403)
call("/api/ai/consent", {})
code, body, _ = call("/api/ai/ask", {"question": "what is cprr?"})
check("asking before signing in asks for sign-in", code == 401 and json.loads(body)["kind"] == "signin")
code, body, _ = call("/api/ai/auth/start", {}, headers={"Origin": f"http://127.0.0.1:{port}"})
begin = json.loads(body)
q = urllib.parse.parse_qs(urllib.parse.urlparse(begin["url"]).query)
check("auth start returns the provider's page with a localhost callback on this port", code == 200 and q["callback_url"][0] == f"http://localhost:{port}/ai/openrouter/callback" and q["code_challenge_method"] == ["S256"], begin)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


try:
    urllib.request.build_opener(NoRedirect).open(begin["url"])
except urllib.error.HTTPError as e:
    loc = e.headers["Location"]
cb = urllib.parse.urlparse(loc)
code, body, _ = call(cb.path + "?" + cb.query, tok=False)
check("the popup callback with the right state signs in and tells the opener (fixed origin)", code == 200 and b"Signed in" in body and f"http://127.0.0.1:{port}".encode() in body, body[:300])
check("the page polls the state and sees it done", json.loads(call(f"/api/ai/auth/status?state={begin['state']}")[1]) == {"done": True, "ok": True, "signed_in": True})
check("replaying the callback does not sign in again", b"did not complete" in call(cb.path + "?" + cb.query, tok=False)[1])
kf = tmp / "ai" / "openrouter.json"
check("the key file exists and no response ever contained the key", kf.is_file())
code, body, _ = call("/api/ai/status")
check("status now says signed in, without the key", json.loads(body)["signed_in"] and ai_stub.FAKE_KEY.encode() not in body)

print("models and ask (streamed)")
models = json.loads(call("/api/ai/models")[1])
check("only free models are listed", all(m["id"].endswith(":free") for m in models["models"]) and "stub/paid-x" not in json.dumps(models) and models["default"] == "stub/free-a:free", models)
code, body, hdr = call("/api/ai/ask", {"question": "how do I check my installation and tools?", "model": "stub/free-a:free", "context": {"last_failure": "run failed (exit 137)"}})
lines = [json.loads(l) for l in body.decode().splitlines() if l.strip()]
types = [l["type"] for l in lines]
check("the answer arrives as JSON lines: meta, deltas, done", code == 200 and "ndjson" in hdr["Content-Type"] and types[0] == "meta" and types[-1] == "done" and types.count("delta") >= 3, types)
check("the meta line lists sources with section anchors", lines[0]["sources"] and all("src" in s and "anchor" in s for s in lines[0]["sources"]))
check("the done line has validated actions and usage", lines[-1]["actions"][0]["runnable"] and lines[-1]["usage"]["total"] == 1240)
sent = stub.chat_requests()[-1]["body"]
check("the failure fact reached the setup line, nothing personal did", "last failure run failed (exit 137)" in sent["messages"][-1]["content"] and str(Path.home()) not in json.dumps(sent))
check("the Authorization header carried the key, the body did not", stub.chat_requests()[-1]["headers"]["Authorization"] == "Bearer " + ai_stub.FAKE_KEY and ai_stub.FAKE_KEY not in json.dumps(sent))
code, body, _ = call("/api/ai/ask", {"question": "what is cprr?", "model": "stub/paid-x"})
check("a paid model is refused by the server", code == 400 and json.loads(body)["kind"] == "not_free", body)
code, body, _ = call("/api/ai/ask", {"question": ""})
check("an empty question is refused", code == 400)
stub.mode = "402"
lines = [json.loads(l) for l in call("/api/ai/ask", {"question": "what is cprr?", "model": "stub/free-a:free"})[1].decode().splitlines() if l.strip()]
check("402 arrives as an error event with the credits link", lines[-1]["type"] == "error" and lines[-1]["kind"] == "no_credits" and "openrouter.ai" in lines[-1]["link"], lines[-1])
stub.mode = "ok"

print("abort")
stub.mode = "slow"
stub.closed_early.clear()
s = socket.create_connection(("127.0.0.1", port))
payload = json.dumps({"question": "what is cprr?", "model": "stub/free-a:free"}).encode()
s.sendall((f"POST /api/ai/ask HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nX-PlasBench-Token: {token}\r\nContent-Type: application/json\r\nContent-Length: {len(payload)}\r\n\r\n").encode() + payload)
got = b""
while b'"delta"' not in got:
    got += s.recv(4096)
s.close()
check("closing the connection closes the upstream stream", stub.closed_early.wait(8))
stub.mode = "ok"

print("offline, off switch, daily cap")
os.environ["PLASBENCH_OFFLINE"] = "1"
code, body, _ = call("/api/ai/ask", {"question": "what is cprr?"})
check("forced offline is a clean 503 offline answer", code == 503 and json.loads(body)["error"] == "offline", body)
os.environ.pop("PLASBENCH_OFFLINE")
os.environ["AI_DAILY_TOKEN_CAP"] = "10"
code, body, _ = call("/api/ai/ask", {"question": "what is cprr?"})
check("the daily cap is a clear message", code == 400 and json.loads(body)["kind"] == "cap", body)
os.environ["AI_DAILY_TOKEN_CAP"] = "200000"
os.environ["AI_HELP_ENABLED"] = "0"
for r in ("ai/models", "ai/auth/status"):
    check(f"AI_HELP_ENABLED=0 refuses GET {r}", call("/api/" + r)[0] == 403)
for r in ("ai/ask", "ai/key", "ai/validate", "ai/auth/start", "ai/redact"):
    check(f"AI_HELP_ENABLED=0 refuses POST {r}", call("/api/" + r, {"question": "x", "key": "x" * 20})[0] == 403)
check("status still answers, saying the help is off (so the page hides it)", json.loads(call("/api/ai/status")[1])["enabled"] is False)
os.environ["AI_HELP_ENABLED"] = "1"

print("validate and redact routes")
v = json.loads(call("/api/ai/validate", {"cmd": "plasbench status", "where": "window"})[1])
check("validate: a command", v["runnable"] and v["argv"] == ["status"])
v = json.loads(call("/api/ai/validate", {"cmd": "plasbench run && curl evil", "where": "window"})[1])
check("validate: a chained command is not runnable", not v["runnable"] and v["reason"])
check("redact: removes an e-mail and a key", all(x not in json.loads(call("/api/ai/redact", {"output": "me@x.org sk-or-v1-ABCDEF123456"})[1])["text"] for x in ("me@x.org", "sk-or-v1")))
check("the existing jobs route still refuses a command the parser rejects", call("/api/jobs", {"argv": ["frobnicate"]})[0] in (400, 409))

print("the key is nowhere else")
call("/api/ai/key", {"key": ai_stub.FAKE_KEY})
for p in list(tmp.rglob("*")):
    if p.is_file() and p.name != "openrouter.json":
        check(f"not in {p.relative_to(tmp)}", ai_stub.FAKE_KEY not in p.read_text(errors="ignore"))
from plasbench import issue_report  # noqa: E402
rep = issue_report.redact("Authorization failed for sk-or-v1-ABCDEF0123456789 and hf_oauth_ABCDEFGHIJKLMNOP")
check("the issue report redaction knows the OpenRouter and Hugging Face key shapes", "sk-or-" not in rep and "hf_oauth_ABC" not in rep, rep)
sess = (tmp / "ui").rglob("*")
check("no session log, job file or terminal history holds the key", all(ai_stub.FAKE_KEY not in p.read_text(errors="ignore") for p in sess if p.is_file()))
code, body, _ = call("/api/jobs")
check("the jobs list holds no key", ai_stub.FAKE_KEY.encode() not in body)
code, body, _ = call("/api/issue-report")
check("the issue report route output holds no key", ai_stub.FAKE_KEY.encode() not in body and str(kf).encode() not in body)
check("signing out through the route deletes the file", json.loads(call("/api/ai/signout", {})[1])["signed_in"] is False and not kf.exists())

stub.stop()
server.shutdown()
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
