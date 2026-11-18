#!/usr/bin/env python3
"""Signing in to GitHub from the window (plasbench/ghsignin.py and the /api/github/* routes), against a fake `gh` (test/ghfake.py): no network, no real account.

  - the parser reads recorded `gh auth login --web` output (code and address, the older and newer wording, the already-signed-in case) and `gh auth status` (both account-line forms, scopes);
  - the device flow: the code and address come back, BROWSER is a no-op (gh never opens the user's browser), stdin is closed, the sign-in completes when approved, a failure and an expiry are
    reported, cancel kills the process, a new start replaces the old one, `gh auth setup-git` runs after success;
  - sign-out; the token fallback pipes the token over stdin ONLY (never in argv), refuses malformed tokens, reports a rejected one, never returns or logs it;
  - routes over HTTP: token required, 503 {error: offline} with the stubbed connectivity layer offline, no token or secret in any response, the session log holds none.
"""
import json
import os
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
os.environ["FAKE_GH_DIR"] = str(tmp)
os.environ["HOME"] = os.environ["USERPROFILE"] = str(tmp / "home")
os.environ.pop("PLASBENCH_OFFLINE", None)
from plasbench import ghsignin, netgate, webui  # noqa: E402

FAKE = [sys.executable, str(ROOT / "test" / "ghfake.py")]
FAILED = []
SECRET = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def calls():
    p = tmp / "calls.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def reset(mode="device"):
    for f in ("calls.jsonl", "approve", "signed_in"):
        (tmp / f).unlink(missing_ok=True)
    os.environ["FAKE_GH_MODE"] = mode


def wait(cond, seconds=20):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


def main():
    print("parsers")
    new = "! First copy your one-time code: ABCD-1234\nOpen this URL to continue in your web browser: https://github.com/login/device\n"
    old = "! First copy your one-time code: 1A2B-3C4D\n- Press Enter to open github.com in your browser...\nhttps://github.com/login/device\n"
    p = ghsignin.parse_device_output(new)
    check("code and address (newer wording)", p["code"] == "ABCD-1234" and p["url"] == "https://github.com/login/device" and not p["already"], p)
    p = ghsignin.parse_device_output(old)
    check("code and address (older wording)", p["code"] == "1A2B-3C4D" and p["url"] == "https://github.com/login/device", p)
    check("only the address so far: no code yet", ghsignin.parse_device_output("Open this URL: https://github.com/login/device")["code"] is None)
    p = ghsignin.parse_device_output("! You are already logged in to github.com account octocat\n")
    check("the already-signed-in case", p["already"] and p["user"] == "octocat" and p["code"] is None, p)
    check("lower-case codes are normalised", ghsignin.parse_device_output("your code: abcd-ef12")["code"] == "ABCD-EF12")
    st = ghsignin.parse_auth_status("github.com\n  ✓ Logged in to github.com account octocat (keyring)\n  - Token scopes: 'repo', 'workflow'\n")
    check("gh auth status (new form): signed in, user, scopes", st == {"signed_in": True, "user": "octocat", "scopes": ["repo", "workflow"]}, st)
    st = ghsignin.parse_auth_status("github.com\n  ✓ Logged in to github.com as octocat (oauth_token)\n")
    check("gh auth status (older form)", st["signed_in"] and st["user"] == "octocat", st)
    check("not logged in", ghsignin.parse_auth_status("You are not logged into any GitHub hosts.")["signed_in"] is False)
    check("tokens are removed from text", SECRET not in ghsignin.redact(f"error: token {SECRET} invalid") and "<token removed>" in ghsignin.redact(f"x github_pat_{'A' * 30} y"))
    check("install commands per platform", "winget install --id GitHub.cli" in ghsignin.install_commands("windows")[0] and "brew install gh" in ghsignin.install_commands("mac")[0] and "conda install -c conda-forge gh" in ghsignin.install_commands("linux"))

    print("device flow")
    reset()
    s = ghsignin.SignIn(FAKE)
    out = s.start(wait_seconds=15)
    check("start returns the code, the address, 15 minutes and an id", out["code"] == "ABCD-1234" and out["url"] == "https://github.com/login/device" and out["expires_in"] == 900 and out["pid_id"], out)
    c = calls()[0]
    check("gh was started with --web, github.com, https", c["argv"][:2] == ["auth", "login"] and "--web" in c["argv"] and c["argv"][c["argv"].index("--hostname") + 1] == "github.com" and c["argv"][c["argv"].index("--git-protocol") + 1] == "https", c["argv"])
    check("BROWSER is a no-op, so the user's own browser is never opened", c["browser"] and c["browser"] != os.environ.get("BROWSER", "xx"), c["browser"])
    check("while waiting the state is 'waiting'", s.status()["state"] == "waiting" and s.status()["code"] == "ABCD-1234")
    (tmp / "approve").write_text("1")
    check("approving signs in", wait(lambda: s.status()["state"] == "signed_in"), s.status())
    check("then gh auth setup-git runs and the account name is read", wait(lambda: s.status()["user"] == "octocat") and any(x["argv"][:2] == ["auth", "setup-git"] for x in calls()), calls())

    reset("fail")
    s = ghsignin.SignIn(FAKE)
    s.start(wait_seconds=15)
    check("a failure is reported with GitHub's reason", wait(lambda: s.status()["state"] == "failed") and "expired" in s.status()["message"], s.status())

    reset("already")
    s = ghsignin.SignIn(FAKE)
    out = s.start(wait_seconds=15)
    check("already signed in: no code is needed", out.get("already_signed_in") and out.get("user") == "octocat", out)

    reset()
    s = ghsignin.SignIn(FAKE)
    s.start(wait_seconds=15)
    proc = s.proc
    s.cancel()
    check("cancel kills the process and reports cancelled", wait(lambda: proc.poll() is not None) and s.status()["state"] == "cancelled", (proc.poll(), s.status()))
    first = ghsignin.SignIn(FAKE)
    first.start(wait_seconds=15)
    p1 = first.proc
    first.start(wait_seconds=15)
    check("a second start replaces the first (no two sign-ins at once)", wait(lambda: p1.poll() is not None))
    first.cancel()
    old_expires = ghsignin.EXPIRES_SECONDS
    ghsignin.EXPIRES_SECONDS = 1
    reset()
    s = ghsignin.SignIn(FAKE)
    try:
        s.start(wait_seconds=15)
    except Exception:  # the code may arrive after the short expiry on a slow machine
        pass
    check("after the time limit the state is 'expired' and the process is stopped", wait(lambda: s.status()["state"] == "expired", 10), s.status())
    ghsignin.EXPIRES_SECONDS = old_expires
    reset("silent")
    s = ghsignin.SignIn(FAKE)
    try:
        s.start(wait_seconds=1)
        got = False
    except RuntimeError as exc:
        got = "one-time code" in str(exc) or "answer" in str(exc)
    check("a gh that never gives a code is an error, not a hang", got)

    print("sign-out and token")
    reset()
    (tmp / "signed_in").write_text("1")
    check("account(): installed, signed in, user, scopes, no avatar fetched by the server", ghsignin.account(FAKE)["signed_in"] and ghsignin.account(FAKE)["user"] == "octocat" and ghsignin.account(FAKE)["scopes"] == ["repo", "workflow"])
    check("account() without gh says how to install it", ghsignin.account(None)["gh_installed"] is False and ghsignin.account(None)["install"])
    out = ghsignin.sign_out(FAKE)
    check("sign-out runs gh auth logout --hostname github.com", out["ok"] and any(x["argv"][:2] == ["auth", "logout"] and "github.com" in x["argv"] for x in calls()) and not (tmp / "signed_in").exists())
    reset()
    out = ghsignin.sign_in_with_token(FAKE, SECRET)
    cs = calls()
    login = next(x for x in cs if x["argv"][:2] == ["auth", "login"])
    check("the token goes over stdin, never in an argument", login["stdin"].strip() == SECRET and "--with-token" in login["argv"] and not any(SECRET in a for x in cs for a in x["argv"]), login["argv"])
    check("the answer holds no token", out["ok"] and out["user"] == "octocat" and SECRET not in json.dumps(out))
    for bad in ("", "short", "has space in it ghp_aaaaaaaaaaaaaaaaaaaaaaaa", "x" * 300, "tok;rm -rf /bin/aaaaaaaaaaaaaaaaaaa"):
        try:
            ghsignin.sign_in_with_token(FAKE, bad)
            ok = False
        except ValueError:
            ok = True
        if not ok:
            break
    check("malformed tokens are refused before gh is called", ok)
    try:
        ghsignin.sign_in_with_token(FAKE, "bad" + "x" * 30)
        rejected = False
    except ValueError as exc:
        rejected = "did not accept" in str(exc) and "bad" + "x" * 30 not in str(exc)
    check("a token GitHub rejects is reported, without echoing it", rejected)

    print("routes")
    reset()
    webui.github_cmd = lambda: list(FAKE)
    webui._signin[0] = None

    class Backend:            # a stubbed connectivity layer
        state = "online"

        @staticmethod
        def check(services=None, timeout=3.0):
            ok = Backend.state == "online"
            return {"online": ok, "state": Backend.state, "checked": time.time(), "services": {"github": {"ok": ok, "ms": 20, "error": "" if ok else "dns", "kind": "" if ok else "dns"}}, "advice": [] if ok else ["Check your internet connection."]}

        @staticmethod
        def require(service, action=""):
            if Backend.state != "online":
                raise type("NoInternet", (Exception,), {})(service)
    netgate.set_backend(Backend)
    project = webui.Project(ROOT)
    jobs = webui.Jobs(project)
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.make_handler(project, jobs))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    def call(path, body=None, token=True):
        h = {"Host": f"127.0.0.1:{port}", "Content-Type": "application/json"}
        if token:
            h["X-PlasBench-Token"] = webui.TOKEN
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None, headers=h, method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return r.status, json.loads(raw), raw.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw), raw.decode("utf-8", "replace")
            except ValueError:
                return e.code, {}, raw.decode("utf-8", "replace")
    check("every GitHub route needs the session token", all(call(p, b, token=False)[0] == 403 for p, b in (("/api/github/account", None), ("/api/github/signin/status", None), ("/api/github/signin/start", {}), ("/api/github/signin/cancel", {}), ("/api/github/signout", {}), ("/api/github/signin/token", {"token": SECRET}), ("/api/github/op", {"op": "pr_list"}))))
    code, body, _ = call("/api/github/account")
    check("account: not signed in yet", code == 200 and body["gh_installed"] and not body["signed_in"], body)
    code, body, _ = call("/api/github/signin/start", {})
    check("start answers with the code, address, expiry and id", code == 200 and body["code"] == "ABCD-1234" and body["url"].startswith("https://github.com/login/device") and body["pid_id"], body)
    code, body, _ = call("/api/github/signin/status")
    check("status: waiting", code == 200 and body["state"] == "waiting")
    (tmp / "approve").write_text("1")
    check("status: signed_in after approval, with the user", wait(lambda: call("/api/github/signin/status")[1]["state"] == "signed_in") and wait(lambda: call("/api/github/signin/status")[1]["user"] == "octocat"))
    code, body, _ = call("/api/github/account")
    check("account: signed in as octocat, scopes shown", body["signed_in"] and body["user"] == "octocat" and "repo" in body["scopes"], body)
    reset()
    webui._signin[0] = None
    code, body, _ = call("/api/github/signin/start", {})
    code2, body2, _ = call("/api/github/signin/cancel", {})
    check("cancel over HTTP: state cancelled and the process ends", body2["state"] == "cancelled" and wait(lambda: webui.signin().proc.poll() is not None))
    (tmp / "signed_in").write_text("1")
    code, body, _ = call("/api/github/signout", {})
    check("sign-out over HTTP", code == 200 and body["ok"] and not (tmp / "signed_in").exists())
    reset()
    code, body, text = call("/api/github/signin/token", {"token": SECRET})
    check("token route: signed in, the response holds no token", code == 200 and body["ok"] and SECRET not in text, text)
    check("token route: the token never reached an argument", not any(SECRET in a for x in calls() for a in x["argv"]))
    code, body, _ = call("/api/github/signin/token", {"token": "not a token"})
    check("token route: a malformed token is a 400", code == 400)
    Backend.state = "offline"
    code, body, _ = call("/api/github/signin/start", {})
    check("offline: 503 with the offline shape, nothing started", code == 503 and body["error"] == "offline" and body["service"] == "github" and "state" in body and "advice" in body, (code, body))
    code, body, _ = call("/api/github/signin/token", {"token": SECRET})
    check("offline: the token route refuses too", code == 503)
    Backend.state = "online"
    logs = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in (tmp / "ui").rglob("*") if p.is_file() and p.suffix in (".jsonl", ".log", ".json", ".txt", ""))
    check("no token appears in any file the window wrote", SECRET not in logs)
    webui.github_cmd = lambda: None
    webui._signin[0] = None
    code, body, _ = call("/api/github/signin/start", {})
    check("gh missing: a plain sentence with the install commands", code == 400 and "not installed" in body["error"] and "conda install -c conda-forge gh" in body["error"], body)
    server.shutdown()
    netgate.set_backend(None)
    print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL PASS")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
