#!/usr/bin/env python3
"""The window stays stable: no false 'program files changed' banner, no repeating 'reopen this window' pop-up, one window per server (window stability).

Root causes (v0.5.5, reported on a WSL2 machine with the Edge app window):

  (B) plasbench/data/ui.html tested the server's api level with a regular expression that SPELLED the placeholder (`/^__API_LEVEL__$/.test(level)`). The server fills the placeholders with a
      plain text replace over the whole file (webui.page), so on a correct server that line became `/^2$/.test("2")`, true, i.e. 'this server is older than the page' on every load;
      Restart window could never fix it. CI passed because every test of that helper ran on the UNREPLACED source (node on the pure block, string checks on the file), and the test of the
      served page only asserted that no placeholder was LEFT: it never executed the served JavaScript. THIS file renders the page through the real code path and runs the served function.
  (A) token_ok() took the header or ?t= key first and used the cookie only when neither was present. After a restart on the same port the browser's cookie held the NEW key while an
      older window kept sending its OLD key: refused for ever (HTTP 403), and 'Trying automatically' reused the same old key. Now any matching credential is accepted, the page recovers
      silently, and a window that really belongs to an older session gets ONE persistent bar instead of a dialog that comes back.

Tested: the placeholder audit and the served page; the key matrix; Origin/Host checks; the window registry, /api/window-ping, /api/windows, /api/reopen; `plasbench ui` reusing an open window;
restart rebinding the same port (real sockets, and a real server restarted by itself); `plasbench ui-state`; the page's connection state machine under node with a fake fetch.
Standard library only; node is optional (skipped with a printed reason).
"""
import html.parser
import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp())
os.environ["PLASBENCH_UI_HOME"] = str(tmp / "ui")
os.environ["PLASBENCH_LOCAL_SETTINGS"] = str(tmp / "local.env")
os.environ["PLASBENCH_WORKSPACE"] = str(tmp / "studies")
os.environ["HOME"] = os.environ["USERPROFILE"] = str(tmp / "home")
(tmp / "home").mkdir()
from plasbench import server_state, webui, windowlife  # noqa: E402

SOURCE = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


class Metas(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.metas = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta" and a.get("name"):
            self.metas[a["name"]] = a.get("content")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main():
    webui.UI_HOME = tmp / "ui"
    (tmp / "ui").mkdir(parents=True, exist_ok=True)
    root = tmp / "root"
    (root / "config").mkdir(parents=True)
    project = webui.Project(root)
    jobs = webui.Jobs(project)
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.make_handler(project, jobs))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    token = webui.TOKEN
    cookie_name = f"plasbench_token_{port}"

    def raw(method, path, headers=None, body=None, host=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
        h = {"Host": host or f"127.0.0.1:{port}"}
        h.update(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body)
            h["Content-Type"] = "application/json"
        c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for k, v in h.items():
            c.putheader(k, v)
        c.putheader("Content-Length", str(len(data or "")))
        c.endheaders(data.encode("utf-8") if data else None)
        r = c.getresponse()
        out = r.read()
        c.close()
        return r.status, out, dict(r.getheaders())

    # ------------------------------------------------------------------ (B) placeholders
    print("placeholders: audit of the source")
    found = {t: len(re.findall(re.escape(t), SOURCE)) for t in windowlife.PLACEHOLDERS}
    check("each placeholder appears in ui.html exactly where it is meant to (meta tags and the title line), no more", found == windowlife.ALLOWED_PLACEHOLDER_COUNTS, found)
    other = sorted(set(re.findall(r"__[A-Z][A-Z_]*[A-Z]__", SOURCE)) - set(windowlife.PLACEHOLDERS))
    check("no OTHER __UPPER_CASE__ token in the page (a future placeholder must be added to windowlife.PLACEHOLDERS and audited)", not other, other)
    script = SOURCE.split("<script>", 1)[1]
    check("no placeholder is spelled inside the page's JavaScript (the server would rewrite it)", not any(t in script for t in windowlife.PLACEHOLDERS), [t for t in windowlife.PLACEHOLDERS if t in script])
    check("the meta tags are the placeholders' homes",
          'name="plasbench-version" content="__VERSION__"' in SOURCE and 'name="plasbench-page-version" content="__PAGE_VERSION__"' in SOURCE and 'name="plasbench-api-level" content="__API_LEVEL__"' in SOURCE)
    check("the served page is produced by windowlife.render_page (one place fills the placeholders)", "windowlife.render_page(" in (ROOT / "plasbench" / "webui.py").read_text(encoding="utf-8"))
    # the other served pages: any placeholder-looking token in webui's other HTML (the key page) would be rewritten only if page() served it; check there is none
    check("the key page holds no placeholder", not any(t in webui.KEY_PAGE for t in windowlife.PLACEHOLDERS))

    print("placeholders: the page as the real server serves it")
    status, body, _ = raw("GET", "/?t=" + token)
    served = body.decode("utf-8")
    check("the real code path serves the page", status == 200 and "<title>PlasBench</title>" in served, status)
    check("no placeholder is left in the served page", not any(t in served for t in windowlife.PLACEHOLDERS))
    parser = Metas()
    parser.feed(served)
    check("the meta tags carry the server's version, the files' version and the api level",
          parser.metas.get("plasbench-version") == webui.__version__ and parser.metas.get("plasbench-page-version") == server_state.disk_version() and parser.metas.get("plasbench-api-level") == str(server_state.API_LEVEL), parser.metas)
    src_lines, served_lines = SOURCE.split("\n"), served.split("\n")
    changed = [i for i, (a, b) in enumerate(zip(src_lines, served_lines)) if a != b]
    with_token = [i for i, line in enumerate(src_lines) if any(t in line for t in windowlife.PLACEHOLDERS)]
    check("the substituted values appear ONLY on the lines of the source that carry a placeholder (nothing else in the page was rewritten)", len(src_lines) == len(served_lines) and changed == with_token, (changed, with_token))
    check("the substituted text is exactly the allowed number of times", served.count(f'content="{str(server_state.API_LEVEL)}"') >= 1 and len(changed) == 4, changed)
    fn = re.search(r"^function serverTooOld\(levelMeta\) \{.*\}$", served, re.M)
    check("the served page holds the serverTooOld function, unchanged from the source", bool(fn) and fn.group(0) in SOURCE, fn.group(0) if fn else "missing")
    node = shutil.which("node")
    if not node:
        print("  skip  node not found: the served serverTooOld is not executed")
    else:
        js = fn.group(0) + f"""
const real = {json.dumps(parser.metas.get("plasbench-api-level"))};
console.log(JSON.stringify({{served: serverTooOld(real), old: serverTooOld("__API_" + "LEVEL__"), empty: serverTooOld(""), none: serverTooOld(undefined), n3: serverTooOld("3")}}));
"""
        path = tmp / "toold.js"
        path.write_text(js, encoding="utf-8")
        done = subprocess.run([node, str(path)], capture_output=True, text=True, encoding="utf-8")
        got = json.loads(done.stdout.strip().splitlines()[-1]) if done.returncode == 0 else {"error": done.stderr[:200]}
        check("node runs the SERVED function: with the server-filled meta it is NOT too old (the v0.5.5 false positive is gone)", got.get("served") is False, got)
        check("node runs the SERVED function: with the raw placeholder (an older server) it IS too old", got.get("old") is True, got)
        check("node: a missing or numeric level raises no alarm", got.get("empty") is False and got.get("none") is False and got.get("n3") is False, got)
        # the v0.5.5 bug, reproduced: the same function written the old way and rendered through the same replace
        old_way = 'function serverTooOld(levelMeta) { return /^__API_LEVEL__$/.test(String(levelMeta || "")); }'
        rendered = windowlife.render_page(old_way, webui.__version__, "x", server_state.API_LEVEL)
        check("the old spelling WOULD have broken (regression guard: the render turns it into /^2$/)", rendered.count("/^2$/") == 1)
    check("the stale banner's evidence shows what was compared (the page's meta level and the server's api_level)",
          'meta_api_level: metaContent("plasbench-api-level")' in SOURCE and "Compared: the page declares api level" in SOURCE)

    # ------------------------------------------------------------------ (A) the key matrix
    print("keys: header, ?t= and cookie (any matching credential)")
    good, stale = {"X-PlasBench-Token": token}, {"X-PlasBench-Token": "an-old-key-from-before-the-restart"}
    cookie_ok, cookie_bad = {"Cookie": f"{cookie_name}={token}"}, {"Cookie": f"{cookie_name}=an-old-cookie"}
    code = lambda *a, **k: raw(*a, **k)[0]  # noqa: E731
    check("valid header: 200", code("GET", "/api/server-state", good) == 200)
    check("stale header + valid cookie: 200 (the restarted-on-the-same-port case)", code("GET", "/api/server-state", dict(stale, **cookie_ok)) == 200)
    check("stale header + no cookie: 403", code("GET", "/api/server-state", stale) == 403)
    check("valid header + stale cookie: 200", code("GET", "/api/server-state", dict(good, **cookie_bad)) == 200)
    check("no credential at all: 403", code("GET", "/api/server-state") == 403)
    check("only a stale cookie: 403", code("GET", "/api/server-state", cookie_bad) == 403)
    check("a valid cookie alone: 200 (as before)", code("GET", "/api/server-state", cookie_ok) == 200)
    check("a cookie of another port or the old shared name is not a credential", code("GET", "/api/server-state", {"Cookie": f"plasbench_token_{port + 1}={token}"}) == 403 and code("GET", "/api/server-state", {"Cookie": f"plasbench_token={token}"}) == 403)
    check("stale ?t= + valid cookie: the page loads (200)", code("GET", "/?t=old-key", cookie_ok) == 200)
    check("stale ?t= and no cookie: the key page (403)", code("GET", "/?t=old-key") == 403)
    check("an empty header does not match an empty key", code("GET", "/api/server-state", {"X-PlasBench-Token": ""}) == 403)
    check("several cookies: the right one is found among others", code("GET", "/api/server-state", {"Cookie": f"a=b; {cookie_name}={token}; c=d"}) == 200)
    check("POST: stale header + valid cookie, same origin: accepted", code("POST", "/api/window-ping", dict(stale, **cookie_ok, Origin=f"http://127.0.0.1:{port}"), {"id": "winA", "visible": True}) == 200)
    check("POST: stale header, no cookie: 403", code("POST", "/api/window-ping", dict(stale, Origin=f"http://127.0.0.1:{port}"), {"id": "winA"}) == 403)
    check("POST: a cookie alone from another origin is refused by the Origin check", code("POST", "/api/window-ping", dict(cookie_ok, Origin="http://evil.example"), {"id": "winA"}) == 403)
    check("POST: a valid header from another origin is still refused", code("POST", "/api/window-ping", dict(good, Origin="http://evil.example"), {"id": "winA"}) == 403)
    check("a wrong Host header is refused even with the key and the cookie (DNS rebinding)", code("GET", "/api/server-state", dict(good, **cookie_ok), host="evil.example") == 403 and code("POST", "/api/window-ping", dict(good, **cookie_ok), {"id": "winA"}, host="evil.example") == 403)
    src = (ROOT / "plasbench" / "webui.py").read_text(encoding="utf-8")
    check("the comparison is constant time for every candidate", "secrets.compare_digest(c.encode" in src and "any(" in src.split("def token_ok")[1].split("def reopen_window")[0])
    check("the cookie stays HttpOnly and SameSite=Strict", "SameSite=Strict; HttpOnly" in src)

    # ------------------------------------------------------------------ windows
    print("windows: ping, registry, reopen")
    clock = [1000.0]
    reg = windowlife.Registry(clock=lambda: clock[0])
    reg.ping("a1", True)
    reg.ping("b2", False)
    check("two pinging windows are alive", reg.count() == 2)
    clock[0] += 30
    check("a visible window silent for 30 s is gone, a hidden one (throttled timers) is still alive", reg.alive() == ["b2"])
    clock[0] += 130
    check("a hidden window silent for 160 s is gone", reg.alive() == [])
    for bad in ("", "x" * 65, "a b", "a;b", None):
        try:
            reg.ping(bad)
            check(f"a bad window id is refused ({bad!r})", False)
        except ValueError:
            check(f"a bad window id is refused ({bad!r})", True)
    small = windowlife.Registry(clock=lambda: clock[0], limit=3)
    for i in range(10):
        small.ping(f"w{i}")
        clock[0] += 0.1
    check("the registry is bounded", len(small.seen) <= 3, len(small.seen))
    rl = windowlife.RateLimit(10, clock=lambda: clock[0])
    first, second = rl.allow(), rl.allow()
    clock[0] += 11
    check("the rate limit lets one through per 10 s", first and not second and rl.allow())
    ok_h = dict(good, Origin=f"http://127.0.0.1:{port}")
    webui.WINDOWS.seen.clear()
    check("/api/windows starts at 0", json.loads(raw("GET", "/api/windows", good)[1])["alive"] == 0)
    res = json.loads(raw("POST", "/api/window-ping", ok_h, {"id": "w" + "1" * 20, "visible": True})[1])
    check("POST /api/window-ping records the window", res == {"ok": True, "alive": 1}, res)
    check("/api/windows counts it and never returns a full id", json.loads(raw("GET", "/api/windows", good)[1])["alive"] == 1 and "1" * 20 not in raw("GET", "/api/windows", good)[1].decode())
    check("/api/windows and /api/window-ping need the key", code("GET", "/api/windows") == 403 and code("POST", "/api/window-ping", {"Origin": f"http://127.0.0.1:{port}"}, {"id": "zz"}) == 403)
    check("a malformed id is a 400", code("POST", "/api/window-ping", ok_h, {"id": "bad id!"}) == 400)

    opened, fronted = [], []
    real_open, real_front = None, windowlife.bring_to_front
    from plasbench import appwindow
    real_open = appwindow.open_app_window
    appwindow.open_app_window = lambda url, *a, **k: opened.append(url) or "fake window"
    windowlife.bring_to_front = lambda *a, **k: fronted.append(1) or True
    try:
        webui.REOPEN_LIMIT.last = None
        # a live window exists: nothing is opened, it is brought to the front
        stale_h = {"Origin": f"http://127.0.0.1:{port}"}
        status, body, _ = raw("POST", "/api/reopen", stale_h, {})
        info = json.loads(body)
        check("/api/reopen needs no key (the window asking has none that works)", status == 200 and info["ok"] is True, (status, info))
        check("with a live window it brings that one to the front and opens nothing", info["opened"] is False and fronted and not opened, (info, opened))
        check("it returns nothing private (no key, no path, no address)", token not in body.decode() and "127.0.0.1" not in body.decode() and str(tmp) not in body.decode())
        webui.WINDOWS.seen.clear()
        status, body, _ = raw("POST", "/api/reopen", stale_h, {})
        info = json.loads(body)
        time.sleep(0.4)
        check("with no live window it opens THIS server's own address, once", info["opened"] is True and len(opened) == 1 and opened[0].startswith(f"http://127.0.0.1:{port}/?t="), (info, opened))
        info2 = json.loads(raw("POST", "/api/reopen", stale_h, {})[1])
        time.sleep(0.3)
        check("a second ask within 10 s opens nothing (rate limit)", info2["opened"] is False and info2["ok"] is False and len(opened) == 1, (info2, opened))
        check("another website cannot call it (cross-origin refused)", code("POST", "/api/reopen", {"Origin": "http://evil.example"}, {}) == 403)
        check("a wrong Host cannot call it", code("POST", "/api/reopen", stale_h, {}, host="evil.example") == 403)
        check("GET is not a route for it", code("GET", "/api/reopen", good) == 404 or code("GET", "/api/reopen", good) >= 400)
    finally:
        appwindow.open_app_window, windowlife.bring_to_front = real_open, real_front

    print("`plasbench ui` finds a server already running")
    said = []
    line = webui.reuse_window("http://127.0.0.1:8770/?t=K", lambda: said.append("open") or "a new window", ask=lambda u, r: {"alive": 2}, front=lambda: True)
    check("a live window: 'PlasBench is already open', nothing opened, brought to the front", line == "PlasBench is already open: http://127.0.0.1:8770/?t=K" and not said, (line, said))
    line = webui.reuse_window("http://x/", lambda: said.append("open") or "a new window", ask=lambda u, r: {"alive": 1}, front=lambda: False)
    check("a live window that cannot be raised: still not duplicated, with a hint", "already open" in line and "taskbar" in line and not said, line)
    line = webui.reuse_window("http://x/", lambda: said.append("open") or "a new window", ask=lambda u, r: {"alive": 0}, front=lambda: True)
    check("no live window: one is opened", line == "Opened: a new window" and said == ["open"], (line, said))
    line = webui.reuse_window("http://x/", lambda: "a new window", ask=lambda u, r: None, front=lambda: True)
    check("an older server (no windows route) or one that does not answer: one is opened as before", line == "Opened: a new window", line)

    def boom():
        raise OSError("no powershell")
    check("a failing 'bring to front' never breaks the launch", "already open" in webui.reuse_window("http://x/", lambda: "w", ask=lambda u, r: {"alive": 1}, front=boom))
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="activated\n", stderr="")
    check("Windows/WSL: AppActivate('PlasBench') through the same PowerShell helper the folder window uses",
          windowlife.bring_to_front(platform="wsl", env={}, which=lambda n: None, run=fake_run, find_powershell=lambda env, which, plat: ("/fake/powershell.exe", [])) is True and calls and "-EncodedCommand" in calls[0])
    import base64
    script = base64.b64decode(calls[0][calls[0].index("-EncodedCommand") + 1]).decode("utf-16-le")
    check("the script activates the window titled PlasBench", "AppActivate('PlasBench')" in script)
    check("no PowerShell found: False, no error", windowlife.bring_to_front(platform="wsl", env={}, which=lambda n: None, run=fake_run, find_powershell=lambda env, which, plat: (None, [])) is False)
    check("Linux without wmctrl or xdotool: False, no error", windowlife.bring_to_front(platform="linux", env={}, which=lambda n: None, run=fake_run) is False)

    # ------------------------------------------------------------------ restart keeps the port
    print("restart: the replacement waits for the SAME port")
    port0 = free_port()
    holder = socket.socket()
    holder.bind(("127.0.0.1", port0))
    holder.listen(1)

    def plain(addr):
        s = socket.socket()
        try:
            s.bind(addr)
        except OSError:
            s.close()
            raise
        return s

    t_release = threading.Timer(0.6, holder.close)
    t_release.start()
    ready = tmp / "ready.flag"
    t0 = time.time()
    got = webui.bind_server("127.0.0.1", port0, None, wait=5, ready=str(ready), make=plain)
    check("the replacement binds the same port once the old server lets go (not port+1)", got is not None and got.getsockname()[1] == port0, got and got.getsockname())
    check("it creates the ready file before the first attempt (that is the old server's cue)", ready.exists())
    check("it waited for the release, not for the whole allowance", 0.4 < time.time() - t0 < 4, time.time() - t0)
    got.close()
    holder2 = socket.socket()
    holder2.bind(("127.0.0.1", port0))
    holder2.listen(1)
    t0 = time.time()
    got = webui.bind_server("127.0.0.1", port0, None, wait=0.5, make=plain)
    check("if the port never frees it moves to the next one after the allowance", got is not None and got.getsockname()[1] != port0 and 0.4 < time.time() - t0 < 3, got and got.getsockname())
    got.close()
    got = webui.bind_server("127.0.0.1", port0, None, wait=0, make=plain)
    check("an ordinary start (no wait) takes the next free port at once", got is not None and got.getsockname()[1] > port0)
    got.close()
    holder2.close()
    check("nothing free at all: None", webui.bind_server("127.0.0.1", 1, None, wait=0, make=lambda addr: (_ for _ in ()).throw(OSError("busy"))) is None)

    print("restart: the old server releases its port when the replacement is ready")
    record = tmp / "ui" / "server.json"
    events, spawned = [], []

    class Child:
        pid = 777

        def poll(self):
            return None

    def spawn(cmd, cwd):
        spawned.append(cmd)
        flag = cmd[cmd.index("--handoff-file") + 1] if "--handoff-file" in cmd else None

        def later():
            if flag:
                Path(flag).write_text("ready")
                while "release" not in events:
                    time.sleep(0.05)
            record.write_text(json.dumps({"url": "http://127.0.0.1:9999/?t=NEW", "port": 9999, "pid": 777}), encoding="utf-8")
        threading.Thread(target=later, daemon=True).start()
        return Child()
    res = server_state.restart(root, 8770, record, spawn=spawn, healthy=lambda i: True, wait=10, release=lambda: events.append("release"))
    cmd = spawned[0]
    check("the replacement is told the same port, to wait for it, and where to say it is ready",
          res["ok"] and cmd[cmd.index("--port") + 1] == "8770" and cmd[cmd.index("--port-wait") + 1] == "25" and "--handoff-file" in cmd, (res, cmd))
    check("the old server released its port (once) between the replacement's 'ready' and its answer", events == ["release"], events)
    check("the ready file is cleaned up", not list((tmp / "ui").glob("handoff-*.ready")))
    spawned.clear()
    res = server_state.restart(root, 8770, record, spawn=spawn, healthy=lambda i: True, wait=5)
    check("without a release callback the command is the old one (no wait, no handoff file)", res["ok"] and "--handoff-file" not in spawned[0] and "--port-wait" not in spawned[0], spawned)

    class Dead(Child):
        def poll(self):
            return 5
    res = server_state.restart(root, 8770, record, spawn=lambda c, d: Dead(), healthy=lambda i: True, wait=2, release=lambda: events.append("x"))
    check("a replacement that dies before it is ready never costs the old window its port", res["ok"] is False and "this window is unchanged" in res["message"] and "x" not in events, res)
    check("`plasbench ui` accepts the two hidden options", "--port-wait" in (ROOT / "plasbench" / "cli.py").read_text(encoding="utf-8") and "port_wait=args.port_wait" in (ROOT / "plasbench" / "cli.py").read_text(encoding="utf-8"))

    # ------------------------------------------------------------------ ui-state
    print("plasbench ui-state lists every server")
    (tmp / "ui" / "servers").mkdir(parents=True, exist_ok=True)
    record.unlink()   # the fake restart above wrote a record: the listing below is about the two records written here
    for p_, pid in ((8770, 111), (8771, 222)):
        (tmp / "ui" / "servers" / f"{p_}.json").write_text(json.dumps({"url": f"http://127.0.0.1:{p_}/?t=SECRETKEY{p_}", "port": p_, "pid": pid, "started": 5, "root": "/p", "version": "0.5.5"}), encoding="utf-8")
    pings = {8770: (True, "5", 0.0), 8771: (None, None, 0.0), 8772: (True, "9", 0.0)}
    seen_calls = []

    def ask(url, route, body=None, timeout=4.0):
        seen_calls.append((url, route))
        return {"server-state": {"running_version": "0.5.5", "stale": False, "api_level": 2}, "windows": {"alive": 2}}[route]
    state = webui.running_servers(ping=lambda p_: pings.get(p_, (None, None, 0.0)), ask=ask, ports=range(8770, 8775),
                                  listeners=lambda p_: {8770: [{"pid": 111, "name": "python"}, {"pid": 999, "name": "wslrelay"}], 8771: [{"pid": 4242, "name": "node"}]}.get(p_, []))
    ports = {e["port"]: e for e in state["servers"]}
    check("it lists the recorded servers, the dead record and the unrecorded one answering on the range", sorted(ports) == [8770, 8771, 8772], sorted(ports))
    check("a running server shows pid, version and its alive windows", ports[8770]["running"] and ports[8770]["pid"] == 111 and ports[8770]["windows_alive"] == 2 and ports[8770]["version"] == "0.5.5")
    check("another process listening on the port is named", ports[8770]["other_listeners"] == [{"pid": 999, "name": "wslrelay"}] and any("wslrelay" in w for w in state["warnings"]), state["warnings"])
    check("a record whose server is gone is flagged, with what holds the port", not ports[8771]["running"] and any("port 8771" in w and "node" in w for w in state["warnings"]), state["warnings"])
    check("a server without a record is flagged", not ports[8772]["recorded"] and any("port 8772" in w and "no record" in w for w in state["warnings"]))
    check("the total of alive windows and the multiple-windows warning", state["windows_alive"] == 2 and any("PlasBench windows reported in" in w for w in state["warnings"]) and any("servers are running" in w for w in state["warnings"]), state)
    check("the stale-window advice is there", any("close EVERY PlasBench window" in w for w in state["warnings"]))
    check("no key is in the answer", "SECRETKEY" not in json.dumps(state))
    env = dict(os.environ, PLASBENCH_UI_HOME=str(tmp / "ui"), PYTHONIOENCODING="utf-8")
    done = subprocess.run([sys.executable, "-m", "plasbench", "--project-root", str(ROOT), "ui-state"], cwd=str(ROOT), env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
    check("the command prints the server list and never a key", done.returncode == 0 and "PlasBench servers running on this computer" in done.stdout and "SECRETKEY" not in done.stdout and "?t=" not in done.stdout, done.stdout[-600:] + done.stderr[-300:])
    done = subprocess.run([sys.executable, "-m", "plasbench", "--project-root", str(ROOT), "ui-state", "--json"], cwd=str(ROOT), env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
    check("--json carries the servers and no key", done.returncode == 0 and '"servers"' in done.stdout and "SECRETKEY" not in done.stdout, done.stdout[-300:])
    check("the window's stale banner Details lists the compared values", "Compared: the page declares api level" in SOURCE)

    # ------------------------------------------------------------------ a real server restarted by itself, same port
    print("a real server: restart keeps the port, the old process exits, a stale key is told apart")
    real_server_checks()

    # ------------------------------------------------------------------ the page's state machine
    print("the page: connection state machine (node, fake fetch)")
    page_checks(node)
    print("ALL WINDOW STABILITY TESTS PASSED" if not FAILED else f"WINDOW STABILITY TESTS FAILED: {FAILED}")
    sys.exit(1 if FAILED else 0)


def real_server_checks():
    ui = tmp / "real-ui"
    env = dict(os.environ, PLASBENCH_UI_HOME=str(ui), HOME=str(tmp / "home"), USERPROFILE=str(tmp / "home"), PYTHONIOENCODING="utf-8")
    port = free_port()
    proc = subprocess.Popen([sys.executable, "-m", "plasbench", "--project-root", str(ROOT), "ui", "--no-browser", "--port", str(port), "--new-instance"], cwd=str(ROOT), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    url = ""
    for _ in range(120):
        line = proc.stdout.readline()
        if "window:" in line:
            url = line.split("window:")[1].strip()
            break
    new_pid = None
    try:
        check("a real server started", bool(url), url)
        if not url:
            return
        key1 = url.split("?t=")[1]
        base = f"http://127.0.0.1:{port}"
        origin = {"Origin": base, "Content-Type": "application/json"}

        def call(method, path, key=None, cookie=None, body=None, extra=None, base_=base):
            h = dict(extra or {})
            if key:
                h["X-PlasBench-Token"] = key
            if cookie:
                h["Cookie"] = cookie
            data = None
            if body is not None:
                h.update(origin)
                data = json.dumps(body).encode("utf-8")
            try:
                with urllib.request.urlopen(urllib.request.Request(base_ + path, data=data, headers=h, method=method), timeout=30) as r:
                    return r.status, r.read()
            except urllib.error.HTTPError as exc:
                return exc.code, exc.read()
            except OSError:
                return 0, b""
        check("the real server's page: meta api level is a number and the served stale-check is false", b'name="plasbench-api-level" content="%d"' % server_state.API_LEVEL in call("GET", "/", key1)[1])
        st, body = call("GET", "/api/server-state", key1)
        check("the real server reports stale:false, kind:none (the evidence of the report)", st == 200 and json.loads(body)["stale"] is False and json.loads(body)["kind"] == "none", body[:200])
        check("the real server wrote its own record under servers/", (ui / "servers" / f"{port}.json").exists())
        st, body = call("POST", "/api/restart-never", key1, body={})
        res_code, res_body = call("POST", "/api/server/restart", key1, body={})
        res = json.loads(res_body) if res_code == 200 else {}
        check("Restart window answers with a new address", res_code == 200 and res.get("ok") is True, (res_code, res_body[:300]))
        if not res.get("ok"):
            return
        new_pid = res.get("pid")
        new_url = res["url"]
        check("the replacement kept the SAME port (no 8770 -> 8771 hop)", urllib.request.urlparse(new_url).port == port if hasattr(urllib.request, "urlparse") else (":" + str(port) + "/") in new_url, new_url)
        key2 = new_url.split("?t=")[1]
        check("it has a NEW key (the page is carried over by the cookie/redirect flow, not by reusing the key)", key2 != key1)
        time.sleep(0.5)
        st, _ = call("GET", "/api/server-state", key1)
        check("the old key is refused by the new server (a bare stale window is told so)", st == 403, st)
        st, _ = call("GET", "/api/server-state", key1, cookie=f"plasbench_token_{port}={key2}")
        check("the old key plus the browser's cookie (the new key) is accepted: a window opened before the restart recovers by itself", st == 200, st)
        st, _ = call("GET", "/api/server-state", key2)
        check("the new key works", st == 200)
        for _ in range(40):
            if proc.poll() is not None:
                break
            time.sleep(0.25)
        check("the old server process exits after answering (the new one holds the port alone)", proc.poll() is not None, proc.poll())
        check("exactly one record names the port afterwards", json.loads((ui / "server.json").read_text(encoding="utf-8")).get("pid") == new_pid)
        w = json.loads(call("GET", "/api/windows", key2)[1])
        check("the new server's window registry starts empty", w["alive"] == 0)
        ping = call("POST", "/api/window-ping", key2, body={"id": "abc123abc123", "visible": True})
        check("a window pings the new server", ping[0] == 200 and json.loads(call("GET", "/api/windows", key2)[1])["alive"] == 1)
        # `plasbench ui` with a live window: no second window
        env2 = dict(env, PLASBENCH_NATIVE_PICKER_POWERSHELL=str(tmp / "no-such-powershell"))
        done = subprocess.run([sys.executable, "-m", "plasbench", "--project-root", str(ROOT), "ui", "--port", str(port)], cwd=str(ROOT), env=env2, capture_output=True, text=True, encoding="utf-8", timeout=90)
        check("`plasbench ui` with a live window prints 'already open' and opens no second window", "PlasBench is already open:" in done.stdout and "Opened:" not in done.stdout, done.stdout[-400:] + done.stderr[-300:])
    finally:
        for target in (new_pid,):
            if target:
                try:
                    st = None
                    ui_state = json.loads((ui / "server.json").read_text(encoding="utf-8"))
                    req = urllib.request.Request(f"http://127.0.0.1:{ui_state['port']}/api/shutdown", data=b'{"force": true}', method="POST",
                                                 headers={"X-PlasBench-Token": ui_state["url"].split("?t=")[1], "Origin": f"http://127.0.0.1:{ui_state['port']}", "Content-Type": "application/json"})
                    urllib.request.urlopen(req, timeout=10).read()
                except Exception:  # noqa: BLE001
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/F", "/PID", str(target)], capture_output=True)
                    else:
                        try:
                            os.kill(target, 15)
                        except OSError:
                            pass
        if proc.poll() is None:
            proc.kill()


PAGE_NODE = r"""
const results = [];
const eq = (n, got, want) => results.push([n, JSON.stringify(got) === JSON.stringify(want), JSON.stringify(got)]);
const mkResp = (status) => ({ok: status >= 200 && status < 300, status});

// ---- pure part: the classification and the backoff
(async () => {
  const log = [];
  const fetchOf = (script) => (url, opt) => { log.push({url, headers: opt.headers}); const next = script.shift(); if (next === "net") return Promise.reject(new TypeError("Failed to fetch")); return Promise.resolve(mkResp(next)); };
  eq("answers with the key: up", await connClassify(fetchOf([200]), "K"), "up");
  eq("a network error: down (server unreachable)", await connClassify(fetchOf(["net"]), "K"), "down");
  eq("a server error: down", await connClassify(fetchOf([500]), "K"), "down");
  eq("a 503 (offline gate) is not a refused key", await connClassify(fetchOf([503]), "K"), "down");
  log.length = 0;
  eq("key refused but the cookie alone works: recovered (no UI)", await connClassify(fetchOf([403, 200]), "K"), "recovered");
  eq("the second request carries NO key header (only the cookie can authenticate it)", [log[0].headers, log[1].headers], [{"X-PlasBench-Token": "K"}, {}]);
  eq("key and cookie both refused: refused", await connClassify(fetchOf([403, 403]), "K"), "refused");
  eq("key refused, then the network fails: down, not refused", await connClassify(fetchOf([403, "net"]), "K"), "down");
  log.length = 0;
  eq("a window with no key asks once: refused", await connClassify(fetchOf([403]), ""), "refused");
  eq("...and sends no header", [log.length, log[0].headers], [1, {}]);
  eq("backoff starts at 3 s", connNextDelay(0), 3000);
  let d = connNextDelay(0); const seq = [d]; for (let i = 0; i < 7; i++) { d = connNextDelay(d); seq.push(d); }
  eq("3 s doubling to a 60 s ceiling", seq, [3000, 6000, 12000, 24000, 48000, 60000, 60000, 60000]);
  eq("automatic retries stop after 10 minutes", [connGiveUp(0, 599000), connGiveUp(0, 601000)], [false, true]);
  eq("the constants", [CONN_FIRST, CONN_MAX, CONN_GIVE_UP], [3000, 60000, 600000]);
})().then(runMachine).catch(e => { console.log("ERROR " + e.stack); process.exit(2); });

// ---- the whole machine with a fake DOM, fake timers and a fake fetch
async function runMachine() {
  const timers = []; let now = 1000000; const els = {}; let created = 0, htmlWrites = 0, reloads = [], storage = {pb_t: "STALE"}, toasts = [], closed = 0, apiCalls = 0;
  const el = (id) => els[id] = els[id] || {id, hidden: true, textContent: "", innerHTML: "", dataset: {}, style: {}, disabled: false, remove() { delete els[id]; }, querySelector() { return el("_q_" + id); }, set onclick(f) { this._click = f; }, get onclick() { return this._click; }};
  ["connbar", "oldsession", "connmsg", "v_runs"].forEach(el);
  const document = {getElementById: id => els[id] || (id.startsWith("os_") || id === "lost_status" || id === "lost_retry" ? el(id) : null), createElement: () => { created++; const e = {dataset: {}, style: {}, querySelector: () => el("_q"), set id(v) { this._id = v; els[v] = this; }, get id() { return this._id; }, remove() { delete els[this._id]; }}; Object.defineProperty(e, "innerHTML", {set(v) { htmlWrites++; }, get() { return ""; }}); return e; }, body: {append() {}}, hidden: false};
  const Dnow = Date.now; Date.now = () => now;
  const S = {conn: null, quit: false};
  let script = [];   // fetch answers, in order; a function is called
  const fetch = (u, o) => { const n = script.shift(); if (typeof n === "function") return n(u, o); if (n === "net") return Promise.reject(new TypeError("x")); return Promise.resolve({ok: n >= 200 && n < 300, status: n, clone() { return this; }, text: async () => "no", json: async () => ({})}); };
  const sandbox = {S, document, fetch, location: {replace: u => reloads.push(u)}, sessionStorage: {removeItem: k => delete storage[k], getItem: k => storage[k], setItem: (k, v) => storage[k] = v},
    $: s => el(s.replace("#", "")), icon: () => "", esc: s => String(s), setIfChanged: (e, h) => { htmlWrites++; e.html = h; }, toast: (m) => toasts.push(m), refreshJobs() {}, refreshSessions() {}, loadRuns() {},
    setTimeout: (f, ms) => { const t = {f, ms}; timers.push(t); return t; }, clearTimeout: t => { if (t) t.cleared = true; }, AbortController: class { constructor() { this.signal = {}; } abort() {} }, window: {close() { closed++; }}, console};
  const src = BLOCK + "\nreturn {connLost, connProbe, sessionEnded, retryNow, showRefused, adoptCookie, api: () => api_stub(), getToken: () => TOKEN};";
  const stubApi = "let TOKEN = 'STALE'; async function api_stub() { if (S.conn && S.conn.refused) throw new Error('session ended'); apiCalls++; return {}; }";
  const m = new Function(...Object.keys(sandbox), "apiCalls_ref", stubApi.replace("apiCalls++", "apiCalls_ref.n++") + "\n" + src)(...Object.values(sandbox), {n: 0});
  const flush = async () => { for (let i = 0; i < 6; i++) await Promise.resolve(); await new Promise(r => setImmediate(r)); };

  // 1. a key refused and the cookie refused too: ONE bar, however many polls fail
  script = [403, 403];
  for (let i = 0; i < 6; i++) m.sessionEnded();   // six pollers fail at once
  await flush();
  eq("six failing polls start ONE check (two requests: key, then cookie only)", script.length, 0);
  eq("the bar is shown once, the dialog never", [htmlWrites, created, els.oldsession.hidden], [1, 0, false]);
  eq("the window is marked refused and the reconnect timer is not running", [S.conn.refused, timers.filter(t => !t.cleared && t.ms >= 3000).length], [true, 0]);
  let threw = ""; try { await m.api(); } catch (e) { threw = e.message; }
  eq("while refused, api() sends nothing (pollers are paused)", threw, "session ended");
  m.sessionEnded(); await flush();
  eq("a later failing poll changes nothing (no second bar, no new request)", [htmlWrites, script.length], [1, 0]);
  eq("the buttons exist: close, open the current window, check again", ["os_close", "os_open", "os_check"].every(id => !!els[id].onclick), true);
  els.os_close.onclick(); eq("Close this window calls window.close()", closed, 1);
  // 2. Check again while still refused
  script = [403, 403]; await m.retryNow(); await flush();
  eq("Check again while still refused: still ONE bar and the honest status", [S.conn.refused, els.os_status.textContent.includes("Still refused")], [true, true]);
  // 3. Check again when the server accepts the key again: back, bar hidden, no reload
  script = [200]; await m.retryNow(); await flush();
  eq("Check again once valid: connection state cleared, bar hidden, no page reload", [S.conn, els.oldsession.hidden, reloads.length], [null, true, 0]);
  // 4. recovered: the key is refused but the cookie works -> silent adoption
  const writesBefore = htmlWrites;
  script = [403, 200]; m.sessionEnded(); await flush();
  eq("key refused + cookie valid: the page reloads the BARE address (no ?t=), forgets the old key, shows no UI", [reloads, "pb_t" in storage, htmlWrites - writesBefore, S.quit], [["/"], false, 0, true]);
  eq("the bare address is used, never the dead key", reloads.every(u => u === "/" && !u.includes("t=")), true);
  S.quit = false; S.conn = null; reloads.length = 0;
  // 5. unreachable: backoff 3, 6, 12 ..., ONE dialog, stop after 10 min
  timers.length = 0; htmlWrites = 0; created = 0;
  m.connLost();
  eq("connLost starts one loop with the first delay 3 s", [timers.map(t => t.ms)], [[3000]]);
  m.connLost(); m.connLost();
  eq("more failing polls do not start more loops", timers.length, 1);
  const delays = [];
  for (let i = 0; i < 7; i++) {
    script = ["net"]; const t = timers[timers.length - 1]; t.f(); await flush();
    now += 20000; delays.push(timers[timers.length - 1].ms);
  }
  eq("each failed probe waits longer: 6, 12, 24, 48, 60, 60 s", delays.slice(0, 6), [6000, 12000, 24000, 48000, 60000, 60000]);
  eq("the 'PlasBench is not responding' dialog was created once, not once per probe", created, 1);
  now += 700000;   // past the 10-minute allowance
  const probes = () => timers.filter(t => !t.cleared && String(t.f).includes("connProbe")).length;
  const before = probes(); script = ["net"]; timers.filter(t => String(t.f).includes("connProbe")).pop().f(); await flush();
  eq("after 10 minutes no further automatic retry is scheduled", probes(), before);
  eq("and the status says so", els.lost_status.textContent.includes("stopped after 10 minutes"), true);
  // 6. the network comes back
  script = [200]; await m.retryNow(); await flush();
  eq("Retry now after PlasBench is back: state cleared, dialog removed, 'Reconnected' announced", [S.conn, !!els.ended, toasts.includes("Reconnected to PlasBench")], [null, false, true]);
  Date.now = Dnow;
  // evidence lines for the stale banner
  const ev = evidenceLines({meta_api_level: "__X", api_level: 2});
  eq("the banner's Details carry what was compared", ev, ['Compared: the page declares api level "__X", this server answers api_level 2']);
  eq("a server that reported nothing says so", evidenceLines({meta_api_level: "2"}), ['Compared: the page declares api level "2", this server did not report an api_level']);
  console.log(JSON.stringify(results));
}
"""


def page_checks(node):
    if not node:
        print("  skip  node not found: the state machine is not executed")
        return
    pure_and_machine = SOURCE.split("/* BEGIN window stability")[1].split("/* END window stability */")[0]
    ss_pure = SOURCE.split("/* ==SS-PURE-BEGIN==")[1].split("*/", 1)[1].split("/* ==SS-PURE-END== */")[0]
    # the block needs the stale pure block for evidenceLines (knownVersion etc. are included there)
    block = pure_and_machine.split("\n", 1)[1]
    js = "const BLOCK = " + json.dumps(block) + ";\n" + "const SSPURE = " + json.dumps(ss_pure) + ";\n"
    js += "const pure = new Function(SSPURE + '\\nreturn {evidenceLines};')(); const evidenceLines = pure.evidenceLines;\n"
    js += "const pureConn = new Function(BLOCK.split('/* ==CONN-PURE-END== */')[0].split('/* ==CONN-PURE-BEGIN==')[1].split('*/').slice(1).join('*/') + '\\nreturn {connClassify, connNextDelay, connGiveUp, CONN_FIRST, CONN_MAX, CONN_GIVE_UP};')();\n"
    js += "const {connClassify, connNextDelay, connGiveUp, CONN_FIRST, CONN_MAX, CONN_GIVE_UP} = pureConn;\n"
    js += PAGE_NODE
    path = tmp / "machine.js"
    path.write_text(js, encoding="utf-8")
    done = subprocess.run([node, str(path)], capture_output=True, text=True, encoding="utf-8", timeout=120)
    if done.returncode != 0:
        check("the state machine runs under node", False, (done.stdout + done.stderr)[-600:])
        return
    for name, ok, got in json.loads(done.stdout.strip().splitlines()[-1]):
        check("node: " + name, ok, got)
    print("the page: static wiring")
    check("a refused key adopts the cookie by loading the bare address (the dead key is never reused)", 'location.replace("/")' in SOURCE.split("function adoptCookie")[1].split("\n}")[0] and 'removeItem("pb_t")' in SOURCE.split("function adoptCookie")[1].split("\n}")[0])
    check("api() calls sessionEnded() on a refused key and fast-fails while refused", "sessionEnded();" in SOURCE and "S.conn.refused) throw" in SOURCE)
    check("the pollers stand down while refused too (they test S.conn)", SOURCE.count("if (S.conn) return;") >= 3)
    check("one persistent non-modal bar element exists, outside any dialog", 'id="oldsession"' in SOURCE and "#oldsession{" in SOURCE)
    check("the bar says what to do and offers the three buttons", all(x in SOURCE for x in ("This window belongs to an older PlasBench session", "Close this window", "Open the current window", "close this window from the taskbar")))
    check("window liveness: a random id per window and a ping every 10 s", "const WIN_ID" in SOURCE and 'api("window-ping"' in SOURCE and "setInterval(winPing, 10000)" in SOURCE)
    check("the key page redirects with the tab's stored key only when no valid cookie got the request in (the server accepts the cookie first)", "if (t && !location.search)" in (ROOT / "plasbench" / "webui.py").read_text(encoding="utf-8"))
    check("Restart window navigates THIS window to the new address (no second window is opened by the server: --no-browser)", "location.href = res.url" in SOURCE and '"--no-browser"' in (ROOT / "plasbench" / "server_state.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
