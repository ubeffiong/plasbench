"""A local stand-in for OpenRouter, Hugging Face and an Ollama-style server, for the AI help tests (no real service is ever called, no real key exists here).

One HTTP server, three prefixes:
    /api/v1/...        OpenRouter: GET /auth (the sign-in page: redirects to callback_url with a code), POST /auth/keys, GET /models, GET /key, POST /chat/completions
    /hf/v1/...         Hugging Face router: GET /models, POST /chat/completions;  /hf/hub/oauth/authorize and /hf/hub/oauth/token for the sign-in
    /local/v1/...      an OpenAI-compatible local server: GET /models, POST /chat/completions
`Stub.mode` picks what chat completions do: ok, 401, 402, 429, 429_once, 500, slow (sends a few pieces slowly: for abort tests), midstream_error, no_usage.
Every request is recorded in `Stub.requests` (method, path, headers, parsed body) so tests can assert what was and was not sent. Fake values only.
"""
from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

FAKE_KEY = "sk-or-v1-FAKEKEYFORTESTS0123456789abcdef"
FAKE_HF_TOKEN = "hf_oauth_FAKETOKENFORTESTS0123456789"
GOOD_CODE = "good-code-123"


def or_models():
    def m(i, prompt="0", completion="0", ctx=100000, out=("text",), reasoning=None, extra=None):
        d = {"id": i, "name": i, "context_length": ctx, "architecture": {"output_modalities": list(out), "input_modalities": ["text"]},
             "pricing": {"prompt": prompt, "completion": completion}, "supported_parameters": ["max_tokens", "temperature"]}
        if reasoning is not None:
            d["reasoning"] = reasoning
        d.update(extra or {})
        return d
    return {"data": [m("stub/free-a:free", extra={"benchmarks": {"artificial_analysis": {"intelligence_index": 9.0}}}), m("stub/free-b:free"), m("stub/free-c:free"),
                     m("stub/paid-x", "0.000001", "0.000002"), m("stub/turns-paid:free"), m("openrouter/free"), m("openrouter/auto", "-1", "-1"),
                     m("stub/free-audio:free", out=("text", "audio")), m("stub/free-small:free", ctx=8000), m("stub/free-reason:free", reasoning={"mandatory": True}),
                     m("stub/free-priced-request:free", extra={"pricing": {"prompt": "0", "completion": "0", "request": "0.01"}}),
                     m("stub/half-free", "0", "0.000001")]}


def hf_models():
    def p(name, i, o, ctx=64000, live="live", free=False):
        return {"provider": name, "status": live, "context_length": ctx, "pricing": {"input": i, "output": o}, "is_free": free}
    return {"object": "list", "data": [
        {"id": "org/free-model", "architecture": {"output_modalities": ["text"]}, "providers": [p("fakeprov", 0, 0, free=True)]},
        {"id": "org/cheap-model", "architecture": {"output_modalities": ["text"]}, "providers": [p("fakeprov", 0.05, 0.1), p("other", 0.2, 0.3)]},
        {"id": "org/pricey-model", "architecture": {"output_modalities": ["text"]}, "providers": [p("fakeprov", 3.0, 9.0)]},
        {"id": "org/image-model", "architecture": {"output_modalities": ["image"]}, "providers": [p("fakeprov", 0, 0, free=True)]},
        {"id": "org/short-ctx", "architecture": {"output_modalities": ["text"]}, "providers": [p("fakeprov", 0, 0, ctx=4096, free=True)]},
    ]}


class Stub:
    def __init__(self):
        self.requests = []
        self.mode = "ok"
        self.pieces = ["Run ", "`plasbench status`", " in the PlasBench Terminal tab [1].\n", "```pb-action\n", '{"cmd":"plasbench status","where":"window","why":"see the state","risk":"safe"}\n', "```\n"]
        self.flip_paid = set()
        self.challenges = {}
        self.used_codes = set()
        self.closed_early = threading.Event()
        self.once = {"n": 0}
        self.lock = threading.Lock()
        stub = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def reply(self, code, obj=None, headers=None, raw=None, ctype="application/json"):
                body = raw if raw is not None else json.dumps(obj).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def record(self, body):
                with stub.lock:
                    stub.requests.append({"method": self.command, "path": self.path, "headers": {k: v for k, v in self.headers.items()}, "body": body})

            def do_GET(self):
                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                self.record(None)
                p = u.path
                if p == "/api/v1/models":
                    data = or_models()
                    for m in data["data"]:
                        if m["id"] in stub.flip_paid:
                            m["pricing"] = {"prompt": "0.000002", "completion": "0.000004"}
                    return self.reply(200, data)
                if p == "/api/v1/key":
                    return self.reply(200, {"data": {"free_model_daily_requests": {"used": 3, "limit": 50, "remaining": 47}}})
                if p == "/api/auth" or p == "/auth":
                    stub.challenges[q.get("state", "")] = q
                    loc = q["callback_url"] + ("&" if "?" in q["callback_url"] else "?") + "code=" + GOOD_CODE + "&state=" + q.get("state", "")
                    return self.reply(302, headers={"Location": loc}, raw=b"")
                if p == "/hf/v1/models":
                    return self.reply(200, hf_models())
                if p == "/hf/hub/oauth/authorize":
                    stub.challenges[q.get("state", "")] = q
                    return self.reply(200, raw=b"authorize", ctype="text/plain")
                if p == "/local/v1/models":
                    return self.reply(200, {"object": "list", "data": [{"id": "llama-local:8b"}, {"id": "qwen-local:4b"}]})
                return self.reply(404, {"error": "no such stub route"})

            def do_POST(self):
                u = urlparse(self.path)
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                try:
                    body = json.loads(raw.decode("utf-8")) if raw and "json" in (self.headers.get("Content-Type") or "") else raw.decode("utf-8")
                except ValueError:
                    body = raw.decode("utf-8", "replace")
                self.record(body)
                p = u.path
                if p == "/api/v1/auth/keys":
                    code = body.get("code")
                    ch = None
                    for st, q in stub.challenges.items():
                        want = base64.urlsafe_b64encode(hashlib.sha256(body.get("code_verifier", "").encode()).digest()).rstrip(b"=").decode()
                        if q.get("code_challenge") == want:
                            ch = q
                    if code != GOOD_CODE or ch is None or body.get("code_challenge_method") != "S256" or code in stub.used_codes:
                        return self.reply(403, {"error": {"message": "Invalid code or code_verifier"}})
                    stub.used_codes.add(code)
                    return self.reply(200, {"key": FAKE_KEY})
                if p == "/hf/hub/oauth/token":
                    form = {k: v[0] for k, v in parse_qs(body).items()} if isinstance(body, str) else {}
                    ch = next((q for q in stub.challenges.values() if q.get("code_challenge") == base64.urlsafe_b64encode(hashlib.sha256(form.get("code_verifier", "").encode()).digest()).rstrip(b"=").decode()), None)
                    if form.get("code") != GOOD_CODE or ch is None or form.get("client_id") != "test-client-id" or "client_secret" in form or form.get("redirect_uri") != ch.get("redirect_uri"):
                        return self.reply(400, {"error": "invalid_grant"})
                    return self.reply(200, {"access_token": FAKE_HF_TOKEN, "token_type": "bearer", "expires_in": 28800, "scope": "inference-api"})
                if p in ("/api/v1/chat/completions", "/hf/v1/chat/completions", "/local/v1/chat/completions"):
                    return self.chat(p, body)
                return self.reply(404, {"error": "no such stub route"})

            def chat(self, path, body):
                mode = stub.mode
                if mode == "429_once":
                    with stub.lock:
                        stub.once["n"] += 1
                        mode = "429" if stub.once["n"] == 1 else "ok"
                if mode == "401":
                    return self.reply(401, {"error": {"code": 401, "message": "No auth credentials found"}})
                if mode == "402":
                    return self.reply(402, {"error": {"code": 402, "message": "Insufficient credits"}})
                if mode == "429":
                    return self.reply(429, {"error": {"code": 429, "message": "Rate limit exceeded"}}, headers={"Retry-After": "7", "X-RateLimit-Reset": str(int((time.time() + 5400) * 1000))})
                if mode == "500":
                    return self.reply(500, {"error": {"code": 500, "message": "boom " + FAKE_KEY}})
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                w = self.wfile

                def ev(obj):
                    w.write(("data: " + json.dumps(obj) + "\n\n").encode())
                    w.flush()
                try:
                    w.write(b": OPENROUTER PROCESSING\n\n")
                    w.flush()
                    for i, piece in enumerate(stub.pieces):
                        ev({"choices": [{"delta": {"content": piece}}]})
                        if mode == "slow":
                            time.sleep(0.15)
                        if mode == "midstream_error" and i == 1:
                            ev({"error": {"code": 502, "message": "provider went away"}, "choices": [{"delta": {"content": ""}, "finish_reason": "error"}]})
                            return
                    if mode != "no_usage":
                        ev({"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1200, "completion_tokens": 40, "total_tokens": 1240, "prompt_tokens_details": {"cached_tokens": 100}}})
                    w.write(b"data: [DONE]\n\n")
                    w.flush()
                except (BrokenPipeError, ConnectionError, OSError):
                    stub.closed_early.set()

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def root(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def env(self) -> dict:
        return {"AI_OPENROUTER_BASE": self.root + "/api/v1", "AI_HF_BASE": self.root + "/hf/v1", "AI_HF_HUB": self.root + "/hf/hub", "AI_LOCAL_BASE": self.root + "/local/v1",
                "PLASBENCH_ASSUME_ONLINE": "1"}

    def chat_requests(self) -> list:
        return [r for r in self.requests if r["path"].endswith("/chat/completions")]

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
