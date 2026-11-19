#!/usr/bin/env python3
"""A window server that is older than the files on disk (plasbench/server_state.py; the 'server state' blocks of plasbench/webui.py and plasbench/data/ui.html).

Root cause of 'The workflow could not be loaded: no such API: workflow': webui.page() re-reads ui.html whenever it changes, but the Python code of a RUNNING server is fixed in memory.
After an update while a window was open the NEW page was served by the OLD server, which does not have the route the page calls. Tested here:

  - the reproduction: a server without a route answers 'no such API: X' to a page that calls it; the page of a stale server carries two different versions (server and files);
  - detection: a newer on-disk version, a touched / added / removed module, no false alarm when nothing changed; /api/server-state shape, token required, cached, no process spawned;
  - the page: the friendly 'older version' card text replaces the raw 'no such API' error in api() (node runs the pure block), the banner, Restart window, Details, Why?, polling,
    no confirm/alert; the hard reload (URL built under node, action in the banner, the dialog and the top bar);
  - headers: the page is 'no-cache' with an ETag (a repeat with If-None-Match is a 304), every /api route is 'no-store';
  - POST /api/server/restart with a FAKE launcher (the real server is never started): ok path, refusal when unsupported, a replacement that dies, one restart at a time,
    and detached runs are untouched when the old server exits (the jobs machinery).
Standard library only; node is optional (skipped with a printed reason).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
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
from plasbench import jobrunner, loadcache, server_state, webui  # noqa: E402

HTML = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


class FakeChild:
    def __init__(self, pid=424242, code=None):
        self.pid, self.code = pid, code

    def poll(self):
        return self.code


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

    def call(route, body=None, token=True, page=False, headers=None, full=False):
        h = {"Host": f"127.0.0.1:{port}"}
        if token:
            h["X-PlasBench-Token"] = webui.TOKEN
        h.update(headers or {})
        data = json.dumps(body).encode() if body is not None else None
        if data:
            h["Content-Type"] = "application/json"
            h["Origin"] = f"http://127.0.0.1:{port}"
        url = f"http://127.0.0.1:{port}/" + ("" if page else "api/") + route
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h)) as r:
                raw = r.read()
                out = (r.status, (raw.decode("utf-8") if page else json.loads(raw)))
                return out + (dict(r.headers),) if full else out
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                out = (e.code, json.loads(raw))
            except ValueError:
                out = (e.code, raw.decode("utf-8", "replace"))
            return out + (dict(e.headers),) if full else out

    print("the reproduction: a new page, an old server")
    code, err = call("a-route-this-server-does-not-have")
    check("a server without a route answers 'no such API: <route>'", code >= 400 and "no such API: a-route-this-server-does-not-have" in json.dumps(err), (code, err))
    check("the page calls the workflow route (a server older than it lacks it)", 'api("workflow")' in HTML)
    real_version, real_disk = webui.__version__, server_state.disk_version
    webui.__version__ = "0.5.1"                               # this server was started from 0.5.1 ...
    server_state.disk_version = lambda: "0.5.2"               # ... and the files were updated to 0.5.2 afterwards
    try:
        code, body = call("?t=" + webui.TOKEN, page=True)
    finally:
        webui.__version__, server_state.disk_version = real_version, real_disk
    check("the page the old server serves carries both versions", 'name="plasbench-version" content="0.5.1"' in body and 'name="plasbench-page-version" content="0.5.2"' in body, body[:400])
    check("no placeholder is left in the served page", "__PAGE_VERSION__" not in body and "__VERSION__" not in body)
    check("the source page has both placeholders", 'content="__PAGE_VERSION__"' in HTML and 'name="plasbench-version" content="__VERSION__"' in HTML)

    print("detection")
    cmp = server_state.compare
    base = {"version": "0.5.2", "modules": {}, "at": 1.0}
    one = [{"module": "webui.py", "old": "aaaa", "new": "bbbb"}]
    check("a newer on-disk version is stale, and says both versions", cmp({"version": "0.5.1", "modules": {}, "at": 1.0}, "0.5.2", [])[0]
          and "0.5.2" in cmp({"version": "0.5.1", "modules": {}, "at": 1.0}, "0.5.2", [])[1])
    check("nothing changed: not stale", cmp(base, "0.5.2", []) == (False, ""))
    check("a loaded module whose content changed is stale and names it", cmp(base, "0.5.2", one)[0] and "webui.py" in cmp(base, "0.5.2", one)[1])
    check("disk_version reads __init__.py without importing and equals the package version", server_state.disk_version() == webui.__version__, server_state.disk_version())
    server_state.reset(root=root)
    check("a fresh start is not stale", server_state.state()["stale"] is False, server_state.state())

    print("/api/server-state")
    code, st = call("server-state", token=False)
    check("the route needs the key", code == 403, code)
    code, st = call("server-state")
    check("it answers with the documented shape", code == 200 and set(st) >= {"started_version", "disk_version", "stale", "reason", "started_at", "kind", "running_version", "running_path", "project_root_version", "changed_modules", "server", "api_level"} and st["stale"] is False, st)
    loadcache.reset_all()
    saved = server_state.START["version"]
    server_state.START["version"] = "0.0.1"   # a server started from an older version
    try:
        code, st = call("server-state")
    finally:
        server_state.START["version"] = saved
    check("an older started version reports stale with its reason", st["stale"] is True and st["started_version"] == "0.0.1" and "0.0.1" in st["reason"], st)
    loadcache.reset_all()
    spawned = []
    real_popen, real_run = subprocess.Popen, subprocess.run
    subprocess.Popen = lambda *a, **k: spawned.append(a) or real_popen(*a, **k)
    subprocess.run = lambda *a, **k: spawned.append(a) or real_run(*a, **k)
    try:
        for _ in range(5):
            call("server-state")
    finally:
        subprocess.Popen, subprocess.run = real_popen, real_run
    check("the load path stays cheap: no process is started, and the answer is cached", not spawned, spawned)

    print("headers: a normal reload is never stale")
    code, body, h = call("?t=" + webui.TOKEN, page=True, full=True)
    h = {k.lower(): v for k, v in h.items()}
    check("the page is no-cache with an ETag", h.get("cache-control") == "no-cache" and h.get("etag", "").startswith('"'), h)
    code2, _b, h2 = call("?t=" + webui.TOKEN, page=True, headers={"If-None-Match": h["etag"]}, full=True)
    check("a repeat with the same ETag is a 304 (revalidated, not re-sent)", code2 == 304, code2)
    code3, _b, h3 = call("?t=" + webui.TOKEN, page=True, headers={"If-None-Match": '"other"'}, full=True)
    check("a different ETag gets the page", code3 == 200)
    for route in ("info", "server-state", "workflow"):
        c, _o, hh = call(route, full=True)
        check(f"/api/{route} is no-store", {k.lower(): v for k, v in hh.items()}.get("cache-control") == "no-store", hh)
    check("only the logo and icons may be cached", HTML.count("public, max-age") == 0)

    print("the page")
    check("api() turns 'no such API' into the friendly card text, keeping the original in details",
          "friendlyApiError(err.message)" in HTML and "err.details = err.message" in HTML and "STALE_API_TEXT" in HTML)
    check("the banner says what happened, offers Restart window, Details and Why?, and says runs keep going",
          all(x in HTML for x in ("Restart window", "ss_why", "<summary>Details</summary>", "while this window was open", "Your runs keep going in the background", "detached")))
    check("the page polls server-state at load and every 60 s while visible and compares its own version at once",
          'api("server-state")' in HTML and "setInterval(() => { if (!document.hidden) ssPoll(); }, 60000)" in HTML and "pageServerMismatch(" in HTML)
    block = HTML.split("/* BEGIN server state (stale window server)")[-1].split("/* END server state */")[0]
    check("designed dialogs only (no confirm, prompt or alert)", not re.search(r"\b(confirm|prompt|alert)\(", block.replace("askConfirm(", "")), block[:80])
    check("Reload page (clear cache) is in the banner, the restart dialog and the top bar",
          'id="ss_reload"' in block and 'id: "reload", label: "Reload page (clear cache)"' in block and 'id="reloadbtn"' in HTML)
    check("the dialog gives the keyboard shortcut", "Ctrl+Shift+R (Cmd+Shift+R on a Mac)" in block)
    check("the hard reload clears service workers and Cache Storage, and keeps the session key and preferences",
          "getRegistrations" in block and "caches.delete" in block and "localStorage" not in block.replace("no localStorage key", "").replace("localStorage key", "") and "sessionStorage" not in block.split("async function hardReload")[1].split("try { if (new URLSearchParams")[0])
    check("the page registers no service worker and uses no Cache Storage", "serviceWorker.register" not in HTML and "caches.open" not in HTML)
    check("the restart-lost path still exists (key refused / connection lost)", "LOST_EXPIRED" in HTML and "PlasBench was restarted" in HTML and "sessionEnded();" in HTML)
    node = shutil.which("node")
    if not node:
        print("  skip  node not found: the pure handler is not executed (static checks above still run)")
    else:
        pure = HTML.split("/* ==SS-PURE-BEGIN==")[1].split("*/", 1)[1].split("/* ==SS-PURE-END== */")[0]
        js = pure + r"""
const out = [];
const eq = (n, a, b) => out.push([n, JSON.stringify(a) === JSON.stringify(b), JSON.stringify(a)]);
eq("no such API is recognised", friendlyApiError("no such API: workflow").friendly, STALE_API_TEXT);
eq("the original text is kept", friendlyApiError("no such API: workflow").details, "no such API: workflow");
eq("another error is left alone", friendlyApiError("HTTP 500"), null);
eq("an empty message is left alone", friendlyApiError(""), null);
eq("the card text", STALE_API_TEXT, "This window is running an older version of PlasBench than the page. Restart the window.");
eq("banner with versions", staleMessage("0.5.1", "0.5.2"), "PlasBench was updated (0.5.1 -> 0.5.2) while this window was open. Restart the window to use the new version.");
eq("banner without versions", staleMessage("", ""), STALE_API_TEXT);
eq("mismatch", pageServerMismatch("0.5.2", "0.5.1"), true);
eq("same version", pageServerMismatch("0.5.2", "0.5.2"), false);
eq("an old server leaves the placeholder: unknown, no alarm", pageServerMismatch("__PAGE_VERSION__", "0.5.1"), false);
eq("hard reload keeps the key and adds _r", hardReloadUrl("http://127.0.0.1:8770/?t=KEY#tools", 123), "http://127.0.0.1:8770/?t=KEY&_r=123#tools");
eq("hard reload without a query", hardReloadUrl("http://127.0.0.1:8770/", 5), "http://127.0.0.1:8770/?_r=5");
eq("a second hard reload replaces _r", hardReloadUrl("http://127.0.0.1:8770/?t=K&_r=1", 2), "http://127.0.0.1:8770/?t=K&_r=2");
eq("_r is stripped, the key stays", withoutReloadParam("http://127.0.0.1:8770/?t=K&_r=2#x"), "http://127.0.0.1:8770/?t=K#x");
eq("nothing to strip", withoutReloadParam("http://127.0.0.1:8770/?t=K"), "http://127.0.0.1:8770/?t=K");
console.log(JSON.stringify(out));
"""
        path = tmp / "ss.js"
        path.write_text(js, encoding="utf-8")
        done = subprocess.run([node, str(path)], capture_output=True, text=True, encoding="utf-8")
        if done.returncode != 0:
            check("the pure block runs under node", False, done.stderr[:300])
        else:
            for name, ok, got in json.loads(done.stdout.strip().splitlines()[-1]):
                check("node: " + name, ok, got)

    print("restart (a fake launcher: the real server is never started)")
    record = tmp / "ui" / "server.json"
    calls = []
    child = FakeChild()

    def fake_spawn(cmd, cwd):
        calls.append((cmd, str(cwd)))
        record.write_text(json.dumps({"url": "http://127.0.0.1:9999/?t=NEWKEY", "port": 9999, "pid": child.pid}), encoding="utf-8")
        return child

    real_spawn, real_healthy = server_state.spawn_detached, server_state._healthy
    server_state.spawn_detached, server_state._healthy = fake_spawn, lambda info: True
    os.environ["PLASBENCH_NO_RESTART"] = "1"
    try:
        code, res = call("server/restart", {})
        check("refused when unsupported, with the reason, and nothing is spawned", res.get("ok") is False and res.get("manual") and "PLASBENCH_NO_RESTART" in res["message"] and not calls, res)
        loadcache.reset_all()
        check("server-state says it is unsupported", call("server-state")[1]["restart_supported"] is False)
    finally:
        del os.environ["PLASBENCH_NO_RESTART"]
    loadcache.reset_all()
    check("the route needs the key", call("server/restart", {}, token=False)[0] == 403)
    # a run that must survive the old server
    slow = jobs._launch([sys.executable, "-u", "-c", "import time; print('go', flush=True); time.sleep(6); print('done', flush=True)"], "python -c ...", "slow", None, ["demo"], "plasbench", ROOT)
    t0 = time.time()
    while not jobrunner.is_alive(str(jobs.dir), slow["id"]) and time.time() - t0 < 20:
        time.sleep(0.2)
    check("a detached run is going", jobrunner.is_alive(str(jobs.dir), slow["id"]))
    code, res = call("server/restart", {})
    check("restart: starts the same Python on the same package with a new instance and no browser", res.get("ok") is True and res["url"].endswith("?t=NEWKEY") and calls
          and calls[0][0][0] == sys.executable and "--new-instance" in calls[0][0] and "--no-browser" in calls[0][0] and calls[0][0][1] == "-c" and calls[0][0][3] == str(server_state.PKG.parent), (res, calls))
    t0 = time.time()
    while time.time() - t0 < 8:   # the old server shuts down after answering
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1)
            time.sleep(0.3)
        except OSError:
            break
    check("the old server exits after the answer", time.time() - t0 < 8)
    check("the detached run is untouched by the old server leaving", jobrunner.is_alive(str(jobs.dir), slow["id"]) and webui.Jobs(project).jobs[slow["id"]]["state"] == "running")
    t0 = time.time()
    while time.time() - t0 < 30 and webui.Jobs(project).jobs[slow["id"]]["state"] == "running":
        time.sleep(0.3)
    final = webui.Jobs(project).jobs[slow["id"]]
    check("the run finishes under a new server: done, exit 0", final["state"] == "done" and final["exit"] == 0, final)
    child.code = 3
    res = server_state.restart(root, port, record, spawn=fake_spawn, healthy=lambda i: True, wait=3)
    check("a replacement that dies is reported and the old window is unchanged", res["ok"] is False and "exit code 3" in res["message"], res)
    child.code = None
    res = server_state.restart(root, port, record, spawn=lambda c, d: FakeChild(pid=1), healthy=lambda i: True, wait=1)
    check("a replacement that never answers times out with a message", res["ok"] is False and "did not answer" in res["message"], res)

    def boom(c, d):
        raise OSError("no such file")
    res = server_state.restart(root, port, record, spawn=boom)
    check("a launcher failure is a manual-restart message, not a crash", res["ok"] is False and res.get("manual") and "could not start" in res["message"], res)
    src = Path(server_state.__file__).read_text(encoding="utf-8")
    check("the real launcher detaches (own session / process group, no console)", "start_new_session" in src and "CREATE_NEW_PROCESS_GROUP" in src)
    server_state.spawn_detached, server_state._healthy = real_spawn, real_healthy

    shutil.rmtree(tmp, ignore_errors=True)
    if FAILED:
        print(f"\n{len(FAILED)} FAILED: {FAILED}")
        sys.exit(1)
    print("\nALL STALE SERVER CHECKS PASSED")


main()
