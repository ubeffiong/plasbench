#!/usr/bin/env python3
"""The window's "Check for updates": version comparison, honest failures, a token-protected route, and the UI control.

Nothing here touches the network: the release lookup is replaced by a fake.
"""
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from plasbench import updatecheck, webui  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(f"  {'ok  ' if good else 'FAIL'}  {label}{'' if good else ' -> ' + str(detail)}")
    ok &= bool(good)


def release(tag):
    return lambda: {"tag_name": tag, "html_url": f"https://github.com/ubeffiong/plasbench/releases/tag/{tag}"}


check("versions compare as numbers, not text", updatecheck.parse_version("v0.10.0") > updatecheck.parse_version("0.9.9"))
check("a tag without a number is no version", updatecheck.parse_version("latest") == ())

newer = updatecheck.check("0.4.1", release("v0.4.2"))
check("a newer release is reported with its page", newer["newer"] and newer["latest"] == "0.4.2"
      and newer["url"].endswith("v0.4.2") and not newer["error"], newer)
same = updatecheck.check("0.4.1", release("v0.4.1"))
check("the same release is not an update", not same["newer"] and same["latest"] == "0.4.1", same)
older = updatecheck.check("0.5.0", release("v0.4.1"))
check("a development version ahead of the release is not told to downgrade", not older["newer"], older)


def dns_failure():
    raise urllib.error.URLError("[Errno -3] Temporary failure in name resolution")


dns = updatecheck.check("0.4.1", dns_failure)
check("a DNS failure is explained, not raised", not dns["newer"] and "DNS" in dns["error"] and "wsl --shutdown" in dns["error"], dns)


def refused():
    raise urllib.error.URLError("[Errno 111] Connection refused")


check("another network failure names the connection", "Connection refused" in updatecheck.check("0.4.1", refused)["error"])


def garbage():
    raise ValueError("not json")


check("an unreadable answer is reported", updatecheck.check("0.4.1", garbage)["error"] != "")
check("a release without a version is reported", "version" in updatecheck.check("0.4.1", lambda: {})["error"])

# the route: needs the session key, and returns the check
updatecheck.fetch_latest = release("v9.9.9")
project = webui.Project(ROOT)
server = ThreadingHTTPServer(("127.0.0.1", 0), webui.make_handler(project, webui.Jobs(project)))
threading.Thread(target=server.serve_forever, daemon=True).start()
port = server.server_address[1]


def call(path, token):
    headers = {"Host": f"127.0.0.1:{port}"}
    if token:
        headers["X-PlasBench-Token"] = webui.TOKEN
    try:
        with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers), timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, {}


code, _ = call("/api/update-check", False)
check("the route needs the session key", code == 403, code)
code, body = call("/api/update-check", True)
check("the route returns the comparison", code == 200 and body.get("newer") is True and body.get("latest") == "9.9.9"
      and body.get("current"), (code, body))
server.shutdown()

page = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
check("the window has a Check for updates control and a Download and install button", 'id="updcheck"' in page and 'id="updgo"' in page
      and 'api("updates/check", {})' in page and 'api("updates/install", body)' in page)
check("the page asks GitHub only when the button is pressed (the page itself reads the cached GET /api/updates)", page.count('api("updates/check"') == 1
      and 'api("update-check")' not in page)

print("ALL UPDATE CHECK TESTS PASSED" if ok else "UPDATE CHECK TESTS FAILED")
sys.exit(0 if ok else 1)
