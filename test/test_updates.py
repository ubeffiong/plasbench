#!/usr/bin/env python3
"""The window's Updates card, with a FAKE GitHub (a local http.server returning release JSON): nothing here touches the real network.

  * release lookup: newer / same / older / malformed / rate-limited / offline / forced offline, release date, notes, the installer asset and its size
  * what is shown from a release is plain text and only https GitHub addresses; the cache keeps the last good answer, is judged against the installed version, and the
    background check runs at most once a day, only in `auto` mode, never with PLASBENCH_OFFLINE=1
  * the plan of an install: no silent downgrade, nothing while a run is active (unless force), never two updates at once, release-file name rules
  * the update job's phases and the classification of its failures (offline, checksum, disk, permission, conda, name, ...)
  * the token-protected routes GET /api/updates, POST /api/updates/check, /archive and /install (the job start is faked: no real upgrade runs)
  * the page: controls, badge in the top bar, tooltips, no browser confirm/alert/prompt; UPDATE_CHECK is a setting with an explanation
"""
from __future__ import annotations

import json
import os
import re
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="pb_updates_"))
os.environ["PLASBENCH_UI_HOME"] = str(TMP / "ui")
os.environ["PLASBENCH_ASSUME_ONLINE"] = "1"
os.environ.pop("PLASBENCH_OFFLINE", None)
os.environ.pop("UPDATE_CHECK", None)
from plasbench import ui_help, updatecheck, updater, webui  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(f"  {'ok  ' if good else 'FAIL'}  {label}{'' if good else ' -> ' + str(detail)}")
    ok &= bool(good)


# ---- a fake GitHub ---------------------------------------------------------------------------------------------------------------------
SCENARIO = {"mode": "newer"}
HITS = []


def release_json(tag, body="", assets=True, published="2026-11-18T10:00:00Z"):
    version = tag.lstrip("v")
    out = {"tag_name": tag, "html_url": f"https://github.com/ubeffiong/plasbench/releases/tag/{tag}", "published_at": published, "body": body}
    if assets:
        base = f"https://github.com/ubeffiong/plasbench/releases/download/{tag}/plasbench-{version}.tar.gz"
        out["assets"] = [{"name": f"plasbench-{version}.tar.gz", "size": 24_000_000, "browser_download_url": base},
                         {"name": f"plasbench-{version}.tar.gz.sha256", "size": 100, "browser_download_url": base + ".sha256"},
                         {"name": "evil.tar.gz", "size": 1, "browser_download_url": "http://evil.example/evil.tar.gz"}]
    return out


NOTES = "## What's new\n\n- **Faster** reports `now`\n- <script>alert(1)</script>Fixed [a bug](https://x.example)\n" + "\n".join(f"- line {i}" for i in range(30))


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        HITS.append((self.path, self.headers.get("User-Agent"), self.headers.get("Authorization"), self.headers.get("Cookie")))
        mode = SCENARIO["mode"]
        if mode == "ratelimit":
            self.send_response(403)
            self.send_header("X-RateLimit-Reset", str(int(time.time()) + 600))
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if mode == "malformed":
            raw = b"<html>not json"
        elif mode == "list":
            raw = b"[1,2,3]"
        elif mode == "notag":
            raw = json.dumps({"name": "x"}).encode()
        else:
            tag = {"newer": "v9.9.9", "same": "v" + updatecheck_current(), "older": "v0.0.1"}[mode]
            raw = json.dumps(release_json(tag, NOTES)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def updatecheck_current():
    from plasbench import __version__
    return __version__


fake = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=fake.serve_forever, daemon=True).start()
REAL_URL = updatecheck.LATEST_URL
updatecheck.LATEST_URL = f"http://127.0.0.1:{fake.server_address[1]}/latest"
CUR = updatecheck_current()


def run_check(mode, current=None):
    SCENARIO["mode"] = mode
    return updatecheck.check(current or CUR, updatecheck.fetch_latest)


print("release lookup")
r = run_check("newer")
check("a newer release: version, relation, date, page", r["newer"] and r["latest"] == "9.9.9" and r["relation"] == "newer" and r["published"] == "2026-11-18" and not r["error"], r)
check("the installer asset and its size come from the release", r["asset"].get("name") == "plasbench-9.9.9.tar.gz" and r["asset"].get("size") == 24_000_000, r["asset"])
check("its checksum file is found too", r["checksum_url"].endswith("plasbench-9.9.9.tar.gz.sha256"), r["checksum_url"])
check("an asset on a non-GitHub http address is dropped", "evil" not in json.dumps(r), r)
check("the notes are a few plain lines: no markup, no HTML, bounded", 1 <= len(r["notes"]) <= updatecheck.NOTES_LINES
      and not any(("<" in n or "**" in n or "`" in n or "](" in n or n.startswith("#")) for n in r["notes"]) and sum(map(len, r["notes"])) <= updatecheck.NOTES_CHARS + 10, r["notes"])
check("nothing but a fixed User-Agent is sent (no cookie, no token, no identifier)", HITS and all(h[1] == "PlasBench" and h[2] is None and h[3] is None for h in HITS), HITS[:1])
check("the same release is not an update", run_check("same")["relation"] == "same" and not run_check("same")["newer"])
check("a development version ahead of the release is 'older': never offered", run_check("older")["relation"] == "older" and not run_check("older")["newer"])
m = run_check("malformed")
check("a malformed answer is reported, not raised", m["error"] and m["error_kind"] == "malformed" and not m["newer"], m)
check("a JSON list is not a release", run_check("list")["error_kind"] == "malformed")
check("a release without a version is reported", run_check("notag")["error_kind"] == "malformed")
rl = run_check("ratelimit")
check("a rate limit is explained and says when it resets", rl["error_kind"] == "rate_limited" and "rate limit" in rl["error"] and "resets" in rl["error"], rl)
updatecheck.LATEST_URL = "http://127.0.0.1:9/latest"        # nothing listens: the connection is refused
off = updatecheck.check(CUR, updatecheck.fetch_latest)
check("offline: a plain reason, never an exception", off["error"] and off["error_kind"] in ("network", "dns") and not off["newer"], off)
updatecheck.LATEST_URL = f"http://127.0.0.1:{fake.server_address[1]}/latest"
os.environ["PLASBENCH_OFFLINE"] = "1"
n_hits = len(HITS)
fo = updatecheck.check(CUR, updatecheck.fetch_latest)
check("PLASBENCH_OFFLINE=1: no request at all, and the reason says so", fo["error_kind"] == "forced_offline" and "PLASBENCH_OFFLINE" in fo["error"] and len(HITS) == n_hits, fo)
del os.environ["PLASBENCH_OFFLINE"]
check("safe_url keeps only https on the GitHub hosts", updatecheck.safe_url("https://github.com/a") and updatecheck.safe_url("https://objects.githubusercontent.com/x")
      and not updatecheck.safe_url("http://github.com/a") and not updatecheck.safe_url("https://evil.example/a") and not updatecheck.safe_url("https://github.com.evil.example/a")
      and not updatecheck.safe_url("file:///etc/passwd"))
check("relation compares numbers, not text", updatecheck.relation("0.9.0", "0.10.0") == "newer" and updatecheck.relation("0.10.0", "0.9.9") == "older" and updatecheck.relation("1.0", "1.0.0") == "same")

print("the cache and the background check")
check("with no cache nothing is known and a check is due", updatecheck.state(CUR)["checked"] is False and updatecheck.due(CUR, "auto"))
SCENARIO["mode"] = "newer"
res = updatecheck.refresh(CUR)
st = updatecheck.state(CUR)
check("refresh remembers the answer", st["checked"] and st["latest"] == "9.9.9" and st["newer"] and st["checked_at"], st)
check("the cached answer is judged against the version installed now (after an update it is no longer offered)", updatecheck.state("9.9.9")["relation"] == "same" and not updatecheck.state("9.9.9")["newer"])
check("a check made just now is not due again", not updatecheck.due(CUR, "auto"))
check("it is due again after a day", updatecheck.due(CUR, "auto", now=time.time() + updatecheck.CACHE_MAX_AGE + 5))
check("UPDATE_CHECK=off: the background check is never due", not updatecheck.due(CUR, "off", now=time.time() + 10 * updatecheck.CACHE_MAX_AGE))
os.environ["PLASBENCH_OFFLINE"] = "1"
check("PLASBENCH_OFFLINE=1: never due either", not updatecheck.due(CUR, "auto", now=time.time() + 10 * updatecheck.CACHE_MAX_AGE))
del os.environ["PLASBENCH_OFFLINE"]
SCENARIO["mode"] = "ratelimit"
updatecheck.refresh(CUR)
st = updatecheck.state(CUR)
check("a failed check keeps the last good answer and shows the error beside it", st["checked"] and st["latest"] == "9.9.9" and st["error_kind"] == "rate_limited", st)
check("after a failure the next background check waits an hour, not a day", not updatecheck.due(CUR, "auto", now=time.time() + 600) and updatecheck.due(CUR, "auto", now=time.time() + 3700))
raw = json.loads(updatecheck.cache_path().read_text(encoding="utf-8"))
check("the cache file holds only the release facts and the time (no path, name or identifier of this computer)", set(raw) <= {"good", "attempt"} and CUR not in json.dumps(raw.get("attempt")), list(raw))
SCENARIO["mode"] = "newer"
done = threading.Event()
updatecheck.cache_path().unlink(missing_ok=True)
t = updatecheck.start_background(CUR, lambda: "auto", fetch=lambda: release_json("v9.9.8"), on_done=lambda result: done.set())
check("the background check runs in a daemon thread and fills the cache", t.daemon and done.wait(10) and updatecheck.state(CUR)["latest"] == "9.9.8")
updatecheck.cache_path().unlink(missing_ok=True)
t = updatecheck.start_background(CUR, lambda: "off", fetch=lambda: (_ for _ in ()).throw(AssertionError("must not be called")))
t.join(5)
check("UPDATE_CHECK=off: the thread does nothing", not updatecheck.state(CUR)["checked"])

print("the plan of an install")
newer_state = {"checked": True, "latest": "9.9.9", "relation": "newer", "asset": {"name": "plasbench-9.9.9.tar.gz", "size": 5}, "published": "2026-11-18", "url": "u"}


def plan(body, check_state=None, jobs=None, outside=None, root=None, current="0.5.5"):
    return updater.plan(body, current, check_state if check_state is not None else newer_state, jobs or [], outside or [], resolve_path=lambda p: p, root=root)


def refused(body, code, **kw):
    try:
        plan(body, **kw)
    except updater.Refused as exc:
        return exc.code == code, exc.code
    return False, "not refused"


p = plan({})
check("the latest release: `plasbench upgrade --yes --version X` (the one real command)", p["argv"] == ["upgrade", "--yes", "--version", "9.9.9"] and p["kind"] == "latest" and p["to"] == "9.9.9" and not p["forced"], p)
check("the label says what it does", "9.9.9" in p["label"] and p["label"].startswith("Update"))
check("before any check there is nothing to install", refused({}, "needs_check", check_state={"checked": False})[0], refused({}, "needs_check", check_state={"checked": False}))
check("a release that is not newer is refused (no silent downgrade)", refused({}, "older", check_state=dict(newer_state, relation="older"))[0] and refused({}, "same", check_state=dict(newer_state, relation="same"))[0])
check("the consent was for another version: refused, look again", refused({"kind": "latest", "version": "9.9.8"}, "changed")[0])
busy = [{"id": "j1", "state": "running", "argv": ["run", "--cohort", "x"], "label": "Benchmark x"}]
ok_busy, code_busy = refused({}, "busy", jobs=busy)
check("a running job blocks the update", ok_busy, code_busy)
try:
    plan({}, jobs=busy)
except updater.Refused as exc:
    check("the refusal lists what is running", exc.details["active"][0]["label"] == "Benchmark x", exc.details)
pf = plan({"force": True}, jobs=busy)
check("force goes ahead and says it was forced", pf["forced"] and pf["argv"][:2] == ["upgrade", "--yes"], pf)
check("a finished job does not block", plan({}, jobs=[{"id": "j0", "state": "done", "argv": ["run"]}])["forced"] is False)
check("a run started in a terminal blocks too", refused({}, "busy", outside=[{"state": "running", "study": "s1"}])[0])
upg = [{"id": "u1", "state": "running", "argv": ["upgrade", "--yes", "--version", "9.9.9"]}]
check("never two updates at once, not even with force", refused({"force": True}, "upgrade_running", jobs=upg)[0])
check("--check-only jobs are not updates", plan({}, jobs=[{"id": "u2", "state": "running", "argv": ["upgrade", "--check-only"]}])["kind"] == "latest")
check("an explicit older version is refused until the downgrade is confirmed", refused({"version": "0.5.0"}, "downgrade")[0] and plan({"version": "0.5.0", "downgrade": True})["relation"] == "older")
check("the same version is refused", refused({"version": "0.5.5"}, "same")[0])
check("a version that is not a number is refused", refused({"version": "../../x"}, "bad_request")[0])
arch = TMP / "plasbench-9.9.9.tar.gz"
arch.write_bytes(b"x" * 2048)
pa = plan({"archive": str(arch)})
check("a release file: --archive with the absolute path, and no check of GitHub needed", pa["argv"] == ["upgrade", "--yes", "--archive", str(arch)] and pa["kind"] == "archive", pa)
check("the file's size and checksum file are reported", pa["facts"]["size"] == 2048 and pa["facts"]["has_sha256"] is False)
(TMP / "plasbench-9.9.9.tar.gz.sha256").write_text("00  plasbench-9.9.9.tar.gz\n")
check("a .sha256 beside the file is noticed", updater.inspect_archive(str(arch))["has_sha256"])
badname = TMP / "plasbench-9.9.9 (1).tar.gz"
badname.write_bytes(b"x")
check("a file not named plasbench-<version>.tar.gz is refused with the likely cause", refused({"archive": str(badname)}, "bad_archive")[0] and "renamed" in updater.inspect_archive(str(badname))["error"])
check("a missing file is refused", refused({"archive": str(TMP / "plasbench-1.2.3.tar.gz")}, "bad_archive")[0])
empty = TMP / "plasbench-1.0.0.tar.gz"
empty.write_bytes(b"")
check("an empty file is refused", refused({"archive": str(empty)}, "bad_archive")[0])
old = TMP / "plasbench-0.1.0.tar.gz"
old.write_bytes(b"x")
check("an older release file is a downgrade that must be confirmed", refused({"archive": str(old)}, "downgrade")[0] and plan({"archive": str(old), "downgrade": True})["relation"] == "older")
same = TMP / "plasbench-0.5.5.tar.gz"
same.write_bytes(b"x")
check("the same version from a file is allowed (a repair) and labelled so", plan({"archive": str(same)})["label"].startswith("Reinstall"))
check("no saved previous release: rollback is refused", refused({"kind": "rollback"}, "no_rollback", root=TMP)[0])
(TMP / ".plasbench-rollback").mkdir()
(TMP / ".plasbench-rollback" / "plasbench-0.5.4.tar.gz").write_bytes(b"x" * 10)
pr = plan({"kind": "rollback"}, root=TMP)
check("rollback uses the saved copy through `plasbench upgrade --rollback`", pr["argv"] == ["upgrade", "--yes", "--rollback"] and pr["to"] == "0.5.4" and updater.rollback_info(TMP)["version"] == "0.5.4", pr)
check("an unknown kind is refused", refused({"kind": "shell"}, "bad_request")[0])
check("default_mode reads local.env, then the environment, defaults to auto and ignores junk",
      updater.default_mode({"UPDATE_CHECK": "off"}, {}) == "off" and updater.default_mode({}, {"UPDATE_CHECK": "OFF"}) == "off" and updater.default_mode({}, {}) == "auto" and updater.default_mode({"UPDATE_CHECK": "maybe"}, {}) == "auto")

print("phases and results")
LOG_OK = "\n".join(["[plasbench-update] current version: 0.5.5", "[plasbench-update] PHASE 1/6 check: which release", "[plasbench-update] PHASE 2/6 download: x", "[plasbench-update] PHASE 3/6 verify: checksum",
                    "[plasbench-update] PHASE 4/6 install: replacing", "[plasbench-update] PHASE 5/6 environment: the installer", "[plasbench-update] PHASE 6/6 done", "[plasbench] Verified: ok"])
check("running at phase 3: two done, one current, three pending", [s["state"] for s in updater.steps("\n".join(LOG_OK.split("\n")[:4]), "running")] == ["done", "done", "current", "pending", "pending", "pending"])
check("a finished update has every phase done", {s["state"] for s in updater.steps(LOG_OK, "done")} == {"done"})
res = updater.classify(LOG_OK, "done", 0)
check("success: restart the window, studies and settings untouched", res["ok"] and res["restart"] and "Restart" in res["next"], res)
check("running has no verdict yet", updater.classify("", "running")["ok"] is None)
CASES = [
    ("checksum", "[plasbench-update] PHASE 3/6 verify\nplasbench-1.tar.gz: FAILED\nERROR[checksum]: the checksum of plasbench-1.tar.gz does not match", 1, "nothing"),
    ("offline", "[plasbench-update] PHASE 2/6 download\nERROR[offline]: could not download plasbench-1.tar.gz (curl exit status 6)", 1, "nothing"),
    ("offline", "[plasbench-update] PHASE 1/6 check\nERROR: needs the internet", 3, "nothing"),
    ("disk", "[plasbench-update] PHASE 3/6 verify\nERROR[disk]: not enough free disk space for installing", 1, "nothing"),
    ("disk", "[plasbench-update] PHASE 4/6 install\ncp: error writing: No space left on device", 1, "unknown"),
    ("permission", "[plasbench-update] PHASE 4/6 install\nERROR[permission]: could not write the release files", 1, "unknown"),
    ("conda", "[plasbench-update] PHASE 5/6 environment\nERROR: no conda-family package manager is available.", 1, "files"),
    ("name", "[plasbench-update] PHASE 1/6 check\nERROR[name]: --archive must be named plasbench-<version>.tar.gz", 1, "nothing"),
    ("lock", "[plasbench-update] PHASE 1/6\nERROR[lock]: another PlasBench update is already running here (pid 12)", 1, "nothing"),
    ("verify", "[plasbench-update] PHASE 6/6 done\n[plasbench] ERROR: still not matching.", 4, "files"),
    ("unknown", "[plasbench-update] PHASE 2/6 download\nsomething odd", 1, "nothing"),
]
for reason, log, code, changed in CASES:
    c = updater.classify(log, "failed", code)
    check(f"failure classified as {reason} ({changed} changed)", c["ok"] is False and c["reason"] == reason and c["changed"] == changed and c["next"] and c["title"], c)
check("a failure before the install step says nothing was changed", "Nothing was changed" in updater.classify(CASES[0][1], "failed", 1)["next"])
check("a failure at the environment step says the files are in place and offers Roll back", "Roll back" in updater.classify(CASES[6][1], "failed", 1)["next"])
check("the log shown is the tail, without terminal colour codes", updater.tail_lines("\x1b[31mred\x1b[0m\n" + "\n".join(str(i) for i in range(100)), 5) == ["95", "96", "97", "98", "99"])

print("the routes")
project = webui.Project(ROOT)
jobs = webui.Jobs(project)
STARTED = []
jobs.start = lambda argv, label="", env=None: (STARTED.append((list(argv), label)), {"id": "fake1", "argv": list(argv), "label": label, "state": "running"})[1]
server = ThreadingHTTPServer(("127.0.0.1", 0), webui.make_handler(project, jobs))
threading.Thread(target=server.serve_forever, daemon=True).start()
port = server.server_address[1]


def call(route, body=None, token=True):
    headers = {"Host": f"127.0.0.1:{port}"}
    if token:
        headers["X-PlasBench-Token"] = webui.TOKEN
    data = json.dumps(body).encode() if body is not None else None
    if data:
        headers["Content-Type"] = "application/json"
        headers["Origin"] = f"http://127.0.0.1:{port}"
    try:
        with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/api/{route}", data=data, headers=headers), timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except ValueError:
            return exc.code, {}


updatecheck.cache_path().unlink(missing_ok=True)
n_hits = len(HITS)
code, _ = call("updates", token=False)
check("GET /api/updates needs the session key", code == 403, code)
code, _ = call("updates/check", {}, token=False)
check("POST /api/updates/check needs the session key", code == 403, code)
code, _ = call("updates/install", {}, token=False)
check("POST /api/updates/install needs the session key", code == 403, code)
os.environ["UPDATE_CHECK"] = "off"
code, view = call("updates")
time.sleep(0.3)
check("GET /api/updates: cached state, no network call (UPDATE_CHECK=off)", code == 200 and view["check"]["checked"] is False and view["job"] is None and view["mode"] == "off" and len(HITS) == n_hits, (code, view))
del os.environ["UPDATE_CHECK"]
check("the view carries what the card needs", {"current", "running", "needs_restart", "mode", "check", "job", "active", "rollback", "restart_supported", "folder"} <= set(view), sorted(view))
check("the installed version is the one in the PlasBench folder", view["current"] == CUR and view["needs_restart"] is False)
# no real network from this window thread: the on-demand background thread would reach api.github.com; the fake stands in
updatecheck.LATEST_URL = f"http://127.0.0.1:{fake.server_address[1]}/latest"
SCENARIO["mode"] = "newer"
code, view = call("updates")
check("the default mode is auto", view["mode"] == "auto")
check("GET /api/updates (auto) answers at once from the cache and leaves the daily check to a background thread", code == 200 and view["check"]["checked"] is False, view["check"])
for _ in range(50):
    if updatecheck.state(CUR)["checked"]:
        break
    time.sleep(0.1)
check("... which fills the cache a moment later", updatecheck.state(CUR)["checked"] and len(HITS) > n_hits)
updatecheck.cache_path().unlink(missing_ok=True)
code, view = call("updates/check", {})
check("POST /api/updates/check asks the (fake) GitHub now and returns the new state", code == 200 and view["check"]["newer"] and view["check"]["latest"] == "9.9.9" and view["check"]["notes"], (code, view["check"]))
code, view = call("updates")
check("the answer is cached for the next read", view["check"]["latest"] == "9.9.9" and view["check"]["age_seconds"] is not None)
code, info = call("updates/archive", {"path": str(arch)})
check("POST /api/updates/archive describes a release file (name, version, size, relation)", code == 200 and info["ok"] and info["version"] == "9.9.9" and info["size"] == 2048 and info["relation"] == "newer", info)
code, info = call("updates/archive", {"path": str(badname)})
check("... and says what is wrong with a misnamed one", code == 200 and not info["ok"] and "plasbench-<version>.tar.gz" in info["error"], info)
code, out = call("updates/install", {})
check("install: starts exactly `plasbench upgrade --yes --version 9.9.9` as a job", code == 200 and STARTED and STARTED[-1][0] == ["upgrade", "--yes", "--version", "9.9.9"] and out["plan"]["to"] == "9.9.9", (code, out, STARTED))
code, out = call("updates/install", {"kind": "latest", "version": "9.9.8"})
check("install: consent for another version is refused with 409", code == 409 and out["code"] == "changed", (code, out))
n = len(STARTED)
code, out = call("updates/install", {"kind": "archive", "archive": str(arch)})
check("install from a file: --archive, no GitHub needed", code == 200 and STARTED[-1][0] == ["upgrade", "--yes", "--archive", str(arch)], (code, out))
code, out = call("updates/install", {"kind": "archive", "archive": str(badname)})
check("install from a misnamed file: 409 bad_archive, nothing started", code == 409 and out["code"] == "bad_archive" and len(STARTED) == n + 1, (code, out))
code, out = call("updates/install", {"kind": "archive", "archive": str(old)})
check("install of an older file: 409 downgrade until confirmed", code == 409 and out["code"] == "downgrade", (code, out))
code, out = call("updates/install", {"kind": "archive", "archive": str(old), "downgrade": True})
check("... and goes ahead once confirmed", code == 200, (code, out))
# a running job blocks
real_list = jobs.list
jobs.list = lambda: [{"id": "r1", "state": "running", "argv": ["run"], "label": "Benchmark A", "started": time.time()}] + real_list()
n = len(STARTED)
code, out = call("updates/install", {})
check("a running job blocks the install (409 busy) and nothing starts", code == 409 and out["code"] == "busy" and out["details"]["active"][0]["label"] == "Benchmark A" and len(STARTED) == n, (code, out))
code, view = call("updates")
check("the view lists what is running", view["active"] and view["active"][0]["label"] == "Benchmark A", view["active"])
code, out = call("updates/install", {"force": True})
check("with force it starts and says it was forced", code == 200 and out["plan"]["forced"] is True and len(STARTED) == n + 1, (code, out))
jobs.list = real_list
code, out = call("updates/install", {"kind": "rollback"})
check("rollback without a saved copy is refused (409 no_rollback)", code == 409 and out["code"] == "no_rollback", (code, out))
server.shutdown()

print("the job's result on the card")
job = {"id": "u9", "state": "failed", "argv": ["upgrade", "--yes", "--version", "9.9.9"], "label": "Update PlasBench to 9.9.9", "started": 1.0, "ended": 2.0, "exit": 1}
summary = updater.job_summary(job, CASES[0][1])
check("a job summary has phases, the verdict and the log tail", summary["steps"][2]["state"] == "failed" and summary["result"]["reason"] == "checksum" and summary["lines"], summary)
check("the newest update job is found among others", updater.newest_upgrade_job([{"argv": ["run"], "started": 9}, job, {"argv": ["upgrade", "--check-only"], "started": 5}])["id"] == "u9")

print("the page, settings and help")
page = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
for ident in ("updcard", "updcheck", "updgo", "updrollback", "upd_file", "upd_filego", "upd_restart", "upd_steps", "upd_res", "upd_log", "updmenu", "upd_dot"):
    check(f"the page has #{ident}", f'id="{ident}"' in page)
check("the card sits on Set up this computer", page.index('id="updcard"') > page.index('id="v_setup"') and page.index('id="updcard"') < page.index('id="v_tools"'))
check("the release file is chosen with the native picker (a file Browse button)", 'data-browse="upd_file"' in page and 'data-browse="upd_file" data-dir' not in page)
check("the top-bar badge and the More-menu entry open the card", 'id="upd_dot"' in page and 'id="updmenu"' in page and 'item.onclick = () => { go("setup")' in page)
check("the page reads the cached state after loading (4 s timer), never on the load path", 'setTimeout(() => updLoad(), 4000)' in page)
check("the restart button reuses the existing restart machinery", 'restartWindow(UPD.data && UPD.data.restart_supported === false)' in page and 'api("server/restart"' in page)
card = page[page.index("/* ---- Updates card"):page.index('$("#profgo").onclick')]
check("no browser confirm / alert / prompt in the card", not re.search(r"(?<![A-Za-z.])(confirm|alert|prompt)[(]", card), re.findall(r".{20}(?<![A-Za-z.])(?:confirm|alert|prompt)\(", card))
check("the card uses the designed dialogs (modalDialog / askConfirm / showMessage)", "modalDialog(" in card and "askConfirm(" in card and "showMessage(" in card)
check("the steps are a keyed list", "applyKeyed($(\"#upd_steps\")" in card)
check("every control of the card is keyboard-reachable buttons or inputs (no click-only divs)", "onclick" in card and 'div class="btn' not in page)
check("the ui help has the card and file tooltips", "upd_card" in ui_help.PAGE and "upd_file_help" in ui_help.PAGE and 'data-tipid="upd_card"' in page and 'data-tipid="upd_file_help"' in page)
check("UPDATE_CHECK is a setting in config/config.sh with its explanation", 'export UPDATE_CHECK="${UPDATE_CHECK:-auto}"' in (ROOT / "config" / "config.sh").read_text(encoding="utf-8")
      and set(ui_help.SETTINGS["UPDATE_CHECK"]["choices"]) == {"auto", "off"})
check("the settings list offers UPDATE_CHECK", any(r["key"] == "UPDATE_CHECK" and r["default"] == "auto" for r in project.settings()))
net = (ROOT / "config" / "network_services.tsv").read_text(encoding="utf-8")
check("the update check is declared as a user of the github service", "plasbench/updatecheck.py" in net and "plasbench upgrade" in net)
from plasbench import netgate  # noqa: E402
check("installing from a file or rolling back needs no internet; the others need github", netgate.command_services(["upgrade", "--yes", "--archive", "x"]) == []
      and netgate.command_services(["upgrade", "--yes", "--rollback"]) == [] and netgate.command_services(["upgrade", "--yes", "--version", "1.2.3"]) == ["github"]
      and netgate.command_services(["upgrade", "--check-only"]) == ["github"])
check("the window starts the background check when it starts (a thread)", "updatecheck.start_background(" in (ROOT / "plasbench" / "webui.py").read_text(encoding="utf-8"))
tests = (ROOT / "test" / "run_tests.sh").read_text(encoding="utf-8")
check("these tests are registered in run_tests.sh", "test_updates.py" in tests and "test_upgrade_e2e.sh" in tests)

fake.shutdown()
updatecheck.LATEST_URL = REAL_URL
print("ALL UPDATES TESTS PASSED" if ok else "UPDATES TESTS FAILED")
sys.exit(0 if ok else 1)
