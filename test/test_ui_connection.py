#!/usr/bin/env python3
"""The window's connection to the PlasBench server is robust (plasbench/webui.py UIServer and Handler, plasbench/data/ui.html api() and the reconnect popup).

The "PlasBench disconnected" popup used to appear at random. Cause: the standard server listens with a backlog of 5 and the page opens many connections at once; on Windows a
connection that finds the backlog full is REFUSED (WinError 10061), which the page took for a dead server. Measured before the fix: 39 of 1,800 concurrent requests refused.

Server (a real one, in a subprocess):
  - a burst of concurrent requests (60 threads x 30) is all answered;
  - HTTP/1.1 keep-alive: many requests on ONE connection;
  - a request repeated with the same X-PlasBench-Req id runs once (a retried "start the benchmark" cannot start it twice) and returns the first run's answer;
  - a refused POST (wrong key, foreign origin) has its body read and discarded before the 403, so the client finishes sending cleanly and the connection stays in step;
  - a client that vanishes mid-request does not hurt the server;
  - /healthz says when a page last loaded and which server instance it is;
  - "This address needs the session key": the bare address is refused with a page that explains how to get back in (and never contains the key); the key cookie is named per port, so two
    PlasBench servers cannot overwrite each other's key; the page recovers a reload of the same tab from that tab's own storage.
Page (static checks; the browser behaviour is exercised by test/ui_connection_browser.mjs when a browser is available):
  - api() retries a network failure quietly with backoff, repeats the same request id, and only then shows the banner; pollers stand down while the connection is down;
  - the popup has a Retry now button that runs a real check (server answering? key valid?) rather than reloading, and the page reconnects by itself.
"""
import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def main():
    tmp = tempfile.mkdtemp()
    env = dict(os.environ, PLASBENCH_UI_HOME=str(Path(tmp) / "ui"), HOME=tmp, USERPROFILE=tmp, PYTHONIOENCODING="utf-8", PLASBENCH_LOCAL_SETTINGS=str(Path(tmp) / "local.env"))
    port = 8840 + os.getpid() % 40
    proc = subprocess.Popen([sys.executable, "-m", "plasbench", "--project-root", str(ROOT), "ui", "--no-browser", "--port", str(port), "--new-instance"], cwd=str(ROOT), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    url = ""
    for _ in range(80):
        line = proc.stdout.readline()
        if "window:" in line:
            url = line.split("window:")[1].strip()
            break
    if not url:
        print("  FAIL  the server did not start")
        proc.kill()
        sys.exit(1)
    base = url.split("/?t=")[0]
    token = url.split("?t=")[1]
    real_port = int(base.rsplit(":", 1)[1])

    def get(path, headers=None):
        req = urllib.request.Request(base + path, headers={"X-PlasBench-Token": token, **(headers or {})})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read(), r.headers

    try:
        print("the server")
        fails, ok = [], [0]
        lock = threading.Lock()

        def worker(n):
            for _ in range(n):
                try:
                    get("/api/jobs")
                    with lock:
                        ok[0] += 1
                except Exception as exc:  # noqa: BLE001
                    with lock:
                        fails.append(f"{type(exc).__name__}: {exc}"[:80])
        threads = [threading.Thread(target=worker, args=(30,)) for _ in range(60)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        check("a burst of 1,800 requests from 60 threads is all answered (the old server refused about 2%)", not fails and ok[0] == 1800, (len(fails), fails[:2]))

        conn = http.client.HTTPConnection("127.0.0.1", real_port, timeout=10)
        statuses, versions = [], set()
        for _ in range(60):
            conn.request("GET", "/api/jobs", headers={"X-PlasBench-Token": token})
            r = conn.getresponse()
            r.read()
            statuses.append(r.status)
            versions.add(r.version)
        check("60 requests share ONE connection (HTTP/1.1 keep-alive)", set(statuses) == {200} and versions == {11}, (set(statuses), versions))

        def post(path, body, rid=None, tok=None, c=None):
            c = c or http.client.HTTPConnection("127.0.0.1", real_port, timeout=60)
            headers = {"X-PlasBench-Token": tok if tok is not None else token, "Content-Type": "application/json"}
            if rid:
                headers["X-PlasBench-Req"] = rid
            c.request("POST", path, body=json.dumps(body), headers=headers)
            r = c.getresponse()
            return r.status, json.loads(r.read().decode("utf-8") or "{}"), c

        rid = "req" + "a1b2c3d4" * 3
        s1, first, _ = post("/api/jobs", {"argv": ["demo", "--help"], "label": "dedupe test"}, rid)
        s2, again, _ = post("/api/jobs", {"argv": ["demo", "--help"], "label": "dedupe test"}, rid)
        jobs = json.loads(get("/api/jobs")[1])["jobs"]
        check("a request repeated with the same id runs once and returns the first answer", s1 == s2 == 200 and first["id"] == again["id"] and sum(1 for j in jobs if j["label"] == "dedupe test") == 1,
              (first.get("id"), again.get("id")))
        s3, other, _ = post("/api/jobs", {"argv": ["demo", "--help"], "label": "dedupe test 2"}, "req" + "e5f6a7b8" * 3)
        check("a request with a different id is a new request", s3 == 200 and other["id"] != first["id"])

        c = http.client.HTTPConnection("127.0.0.1", real_port, timeout=10)
        c.request("POST", "/api/jobs", body=json.dumps({"argv": ["demo"], "pad": "x" * 200000}), headers={"X-PlasBench-Token": "wrong", "Content-Type": "application/json"})
        r = c.getresponse()
        r.read()
        check("a refused POST (wrong key) with a large body answers 403 cleanly (no connection abort)", r.status == 403, r.status)
        c.request("GET", "/api/jobs", headers={"X-PlasBench-Token": token})
        r2 = c.getresponse()
        r2.read()
        check("the next request on the SAME connection then works (the body was drained, so it stayed in step)", r2.status == 200)
        evil = http.client.HTTPConnection("127.0.0.1", real_port, timeout=10)
        evil.request("POST", "/api/settings", body=json.dumps({"changes": {"X": "1"}}), headers={"X-PlasBench-Token": token, "Content-Type": "application/json", "Origin": "http://evil.example"})
        r3 = evil.getresponse()
        r3.read()
        check("a foreign-origin POST is refused with 403 even with a valid key", r3.status == 403, r3.status)

        for _ in range(20):   # clients that go away mid-request, mid-body and straight after connecting
            s = socket.create_connection(("127.0.0.1", real_port), timeout=3)
            s.sendall(b"POST /api/jobs HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 500\r\n\r\n{\"argv\"")
            s.close()
            socket.create_connection(("127.0.0.1", real_port), timeout=3).close()
        check("clients that vanish mid-request do not hurt the server", get("/api/jobs")[0] == 200 and proc.poll() is None)

        _, body, headers = get("/healthz")
        before = float(headers["X-PlasBench-Page-Seen"])
        get("/", {})
        time.sleep(0.05)
        after = float(get("/healthz")[2]["X-PlasBench-Page-Seen"])
        check("/healthz says which server this is and when a window last loaded the page", body.startswith(b"ok") and headers["X-PlasBench-Instance"].isdigit() and after > before, (before, after))

        def bare(cookie=None):
            req = urllib.request.Request(base + "/", headers={"Cookie": cookie} if cookie else {})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return r.status, r.read().decode("utf-8"), r.headers
            except urllib.error.HTTPError as exc:
                return exc.code, exc.read().decode("utf-8"), exc.headers
        code, body, _ = bare()
        check("the bare address (no key) is refused with a page that explains how to get back in, and the page never contains the key",
              code == 403 and "needs to be reopened" in body and "Click the PlasBench icon again" in body and token not in body and "sessionStorage" in body, (code, body[:100]))
        code, _, headers = bare(f"plasbench_token_{real_port}={token}")
        check("the address with this server's key cookie is accepted", code == 200)
        check("a cookie under the old shared name, or another port's name, is not accepted (servers cannot overwrite each other's key)",
              bare(f"plasbench_token={token}")[0] == 403 and bare(f"plasbench_token_{real_port + 1}={token}")[0] == 403)
        with urllib.request.urlopen(urllib.request.Request(base + "/?t=" + token), timeout=10) as r:
            cookie = r.headers.get("Set-Cookie", "")
        check("loading the page with the key sets a cookie named for this port, kept for 30 days, HttpOnly and SameSite=Strict",
              cookie.startswith(f"plasbench_token_{real_port}=") and "Max-Age=2592000" in cookie and "HttpOnly" in cookie and "SameSite=Strict" in cookie, cookie)
        for j in json.loads(get("/api/jobs")[1])["jobs"]:   # tidy
            if j["state"] == "running":
                post(f"/api/jobs/{j['id']}/cancel", {})
    finally:
        try:
            post("/api/shutdown", {"force": True})
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1)
        proc.kill()

    src = (ROOT / "plasbench" / "webui.py").read_text(encoding="utf-8")
    check("closing the terminal that started `plasbench ui` does not stop it (SIGHUP is ignored; Quit and Ctrl+C still stop it)", "signal.signal(signal.SIGHUP, signal.SIG_IGN)" in src)
    check("the launcher script uses only tools PlasBench already declares (no zenity)", "zenity" not in (ROOT / "scripts" / "plasbench_launcher.sh").read_text(encoding="utf-8"))
    print("the page")
    html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    check("api() retries network failures with a growing, jittered delay before it shows the banner", "RETRY_DELAYS = [200, 500, 1000, 2000, 3500]" in html and "Math.random() * 0.4" in html and "attempt >= RETRY_DELAYS.length" in html)
    check("every POST carries a request id and a retry repeats the SAME one", 'opt.headers["X-PlasBench-Req"] = newReqId()' in html and "{...opt, signal: ctl.signal}" in html)
    check("a 3-minute ceiling on one call, so a half-open connection cannot hang the page", "setTimeout(() => ctl.abort(), 180000)" in html)
    check("the pollers stand down while the connection is down", all(f"async function {n}(" in html and html.split(f"async function {n}(")[1].split("\n", 2)[1].strip() == "if (S.conn) return;" for n in ("refreshJobs", "refreshSessions", "pollConsole")))
    check("reconnect probes grow from 2 s to 10 s and run at once on wake, network return and tab focus",
          "Math.min(10000" in html and 'addEventListener("online"' in html and 'addEventListener("visibilitychange"' in html and 'addEventListener("pageshow"' in html)
    check("Retry now runs a real check (server answering, key valid) instead of reloading the page", "async function connCheck()" in html and 'fetch("/healthz"' in html and 'fetch("/api/info"' in html and "async function retryNow()" in html
          and "location.reload()" not in html.split("function showLost")[1].split("async function retryNow")[0])
    check("a refused key (PlasBench restarted) is told apart from an unreachable server, with honest wording for each", '"expired"' in html and "needs to be reopened" in html and "Check again" in html and "Retry now" in html)
    print("ALL UI CONNECTION TESTS PASSED" if not FAILED else f"UI CONNECTION TESTS FAILED: {FAILED}")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
