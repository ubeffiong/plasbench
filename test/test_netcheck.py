#!/usr/bin/env python3
"""plasbench/netcheck.py: every state and failure kind (injected resolver/connector/fetcher), caching, environment overrides,
the NoInternet message, and `plasbench net --json`. Nothing touches the network."""
import json
import os
import socket
import ssl
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from plasbench import netcheck  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(f"  {'ok  ' if good else 'FAIL'}  {label}{'' if good else ' -> ' + str(detail)}")
    ok &= bool(good)


for var in ("PLASBENCH_OFFLINE", "PLASBENCH_ASSUME_ONLINE", "PLASBENCH_ONLINE_TIMEOUT"):
    os.environ.pop(var, None)


def run(resolver=None, connector=None, fetcher=None, services=("github",), **kw):
    netcheck.clear_cache()
    return netcheck.check(list(services), resolver=resolver or (lambda h: ["192.0.2.1"]), connector=connector or (lambda a, p, t: None),
                          fetcher=fetcher or (lambda u, h, t: (200, "", "")), cache_seconds=kw.get("cache_seconds", 0))


a = run()
check("online", a["state"] == "online" and a["online"] and a["services"]["github"]["ok"] and not a["advice"], a)
check("json shape", set(a) == {"online", "state", "checked", "services", "advice"} and set(a["services"]["github"]) == {"ok", "ms", "error", "kind"}, a)


def nores(h):
    raise socket.gaierror(-2, "Name or service not known")


def noconn(addr, port, t):
    raise OSError(101, "Network is unreachable")


a = run(resolver=nores, connector=lambda addr, p, t: (_ for _ in ()).throw(OSError("x")) if addr != "1.1.1.1" else None)
check("dns_broken: IP works, names do not", a["state"] == "dns_broken" and a["services"]["github"]["kind"] == "dns" and any("DNS is not working" in s for s in a["advice"]), a)
a = run(resolver=nores, connector=noconn)
check("offline: nothing connects", a["state"] == "offline" and not a["online"], a)
a = run(fetcher=lambda u, h, t: (503, "", ""))
check("limited: one service answers an error", a["state"] == "limited" and a["services"]["github"]["kind"] == "http" and not a["online"], a)
a = run(fetcher=lambda u, h, t: (302, "http://login.hotel.example/portal", ""))
check("captive portal is a proxy kind", a["services"]["github"]["kind"] == "proxy" and any("sign-in" in s for s in a["advice"]), a)


def badtls(addr, port, t):
    if addr == "1.1.1.1":
        return None
    raise ssl.SSLCertVerificationError("certificate verify failed")


a = run(connector=badtls)
check("certificate error is a tls kind", a["services"]["github"]["kind"] == "tls" and a["state"] == "limited" and any("certificate" in s for s in a["advice"]), a)


def slow(addr, port, t):
    if addr == "1.1.1.1":
        return None
    raise socket.timeout("timed out")


check("timeout kind", run(connector=slow)["services"]["github"]["kind"] == "timeout")


def refused(addr, port, t):
    if addr == "1.1.1.1":
        return None
    raise ConnectionRefusedError()


check("refused kind", run(connector=refused)["services"]["github"]["kind"] == "refused")
check("407 is a proxy kind", run(fetcher=lambda u, h, t: (407, "", ""))["services"]["github"]["kind"] == "proxy")

calls = []
netcheck.clear_cache()
for _ in range(2):
    netcheck.check(["github"], resolver=lambda h: calls.append(h) or ["192.0.2.1"], connector=lambda a_, p, t: None, fetcher=lambda u, h, t: (200, "", ""), cache_seconds=60)
check("results are cached per service", len(calls) == 2, calls)   # dns and github resolve once each; the second call is served from the cache
netcheck.clear_cache()

os.environ["PLASBENCH_ASSUME_ONLINE"] = "1"
a = netcheck.check(["github"])
check("assume online: no probing", a["state"] == "assumed_online" and a["online"] and netcheck.require("github") is None, a)
os.environ.pop("PLASBENCH_ASSUME_ONLINE")
os.environ["PLASBENCH_OFFLINE"] = "1"
a = netcheck.check(["github"])
check("forced offline", a["state"] == "forced_offline" and not a["online"] and a["services"]["github"]["kind"] == "forced", a)
try:
    netcheck.require("github", action="Upgrading PlasBench")
    check("require refuses when forced offline", False)
except netcheck.NoInternet as exc:
    check("require refuses when forced offline", exc.state == "forced_offline" and exc.service == "github" and "Upgrading PlasBench needs the internet" in str(exc), str(exc))
os.environ.pop("PLASBENCH_OFFLINE")

try:
    netcheck.clear_cache()
    netcheck.require("github", action="Upgrading", resolver=nores, connector=lambda addr, p, t: None if addr == "1.1.1.1" else (_ for _ in ()).throw(OSError()), cache_seconds=0)
    check("NoInternet message", False)
except netcheck.NoInternet as exc:
    check("NoInternet message has the documented form", str(exc).startswith("Upgrading needs the internet (") and "unreachable: DNS failure" in str(exc) and "DNS is not working" in str(exc), str(exc))
    check("NoInternet carries state and advice", exc.state == "dns_broken" and exc.advice, exc.state)
try:
    netcheck.require(["sra", "ena"], any_of=True, resolver=lambda h: ["192.0.2.1"], fetcher=lambda u, h, t: (200, "", ""), connector=lambda a_, p, t: None, cache_seconds=0)
    check("any_of passes when one is up", True)
except netcheck.NoInternet as exc:
    check("any_of passes when one is up", False, exc)
os.environ["PLASBENCH_ONLINE_TIMEOUT"] = "2.5"
check("timeout from the environment", netcheck._timeout(None) == 2.5)
os.environ.pop("PLASBENCH_ONLINE_TIMEOUT")
check("default timeout", netcheck._timeout(None) == netcheck.DEFAULT_TIMEOUT == 5.0)
check("check never raises on a bad service name", netcheck.check(["nope"], resolver=lambda h: ["192.0.2.1"], connector=lambda a_, p, t: None)["state"] in netcheck.STATES)

env = dict(os.environ, PLASBENCH_OFFLINE="1")
out = subprocess.run([sys.executable, "-m", "plasbench", "net", "--json", "--service", "ena"], cwd=ROOT, env=env, capture_output=True, text=True)
data = json.loads(out.stdout)
check("plasbench net --json: shape and exit 3 offline", out.returncode == 3 and data["state"] == "forced_offline" and "ena" in data["services"], out.stdout[:200] + out.stderr[:200])
out = subprocess.run([sys.executable, "-m", "plasbench", "upgrade"], cwd=ROOT, env=env, capture_output=True, text=True)
check("plasbench upgrade refuses at once when offline", out.returncode == 3 and "needs the internet" in out.stderr, out.stderr)
out = subprocess.run([sys.executable, "-m", "plasbench", "net"], cwd=ROOT, env=dict(os.environ, PLASBENCH_ASSUME_ONLINE="1"), capture_output=True, text=True)
check("plasbench net exits 0 online", out.returncode == 0 and "assumed_online" in out.stdout, out.stdout)
sys.exit(0 if ok else 1)
