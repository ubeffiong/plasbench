"""Is the internet there, and which online service is not? One answer for the whole program.

Everything in PlasBench that needs the network asks this module first (shell: `require_internet` in scripts/lib.sh;
the command line: a pre-flight in plasbench/cli.py; python/ scripts: plasbench_common.net_require) so that an offline
computer gets one plain sentence, before any work starts, instead of a timeout or a library traceback.

    check(services=None, timeout=None, cache_seconds=10) -> {"online", "state", "checked", "services", "advice"}
    require("github", action="Upgrading PlasBench")      # raises NoInternet(service, state, advice, message)
    SERVICE_LABELS                                       # {"github": "GitHub", ...} for the window

The services, their probe addresses, which commands use them and the advice for each live in config/network_services.tsv
(columns: service, label, probe_url, probe_host, used_by, advice): the single source of truth. test/test_network_declared.py
fails when a file uses the network without being listed there.

States: online | offline | dns_broken | limited | forced_offline | assumed_online.
  offline         nothing answers: no network at all.
  dns_broken      a direct connection to an IP address works but names do not resolve (common in WSL2 and behind some VPNs).
  limited         the network works but a requested service does not (that service is down, a captive portal or a proxy is in
                  the way, or a certificate is not accepted). `online` is False: not everything asked for is reachable.
  forced_offline  PLASBENCH_OFFLINE=1: every online-only service is refused at once; scoring and reports keep working.
  assumed_online  PLASBENCH_ASSUME_ONLINE=1 (tests, air-gapped mirrors): nothing is probed.
Each service entry has ok, ms, error and kind (dns | timeout | refused | tls | http | proxy; "forced" under PLASBENCH_OFFLINE).

Environment: PLASBENCH_OFFLINE=1, PLASBENCH_ASSUME_ONLINE=1, PLASBENCH_ONLINE_TIMEOUT=<seconds> (default 5).
Only a DNS lookup, a TCP/TLS connection and one HEAD request per service are made: nothing is downloaded. Never raises
from check(); stdlib only; safe to call from several threads.

Run as a script (used by scripts/lib.sh): python3 -I plasbench/netcheck.py require [--any] [--action TEXT] [--hint TEXT] SERVICE...
exits 0 when reachable, 3 with the message on stderr when not.
"""
from __future__ import annotations

import concurrent.futures
import ipaddress
import os
import socket
import ssl
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_TIMEOUT = 5.0
BASE_SERVICES = ("internet", "dns")
STATES = ("online", "offline", "dns_broken", "limited", "forced_offline", "assumed_online")
CATALOGUE_NAME = "network_services.tsv"

# What the catalogue says when the file cannot be found (a wheel install without config/): enough to still answer for GitHub.
_FALLBACK = [
    {"service": "internet", "label": "The internet", "probe_url": "", "probe_host": "1.1.1.1", "used_by": "", "advice": "Connect this computer to the internet."},
    {"service": "dns", "label": "Name lookup (DNS)", "probe_url": "", "probe_host": "example.com", "used_by": "", "advice": ""},
    {"service": "github", "label": "GitHub", "probe_url": "https://api.github.com/", "probe_host": "github.com", "used_by": "", "advice": ""},
]


def catalogue_path() -> Path:
    override = os.environ.get("PLASBENCH_NETWORK_SERVICES", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "config" / CATALOGUE_NAME


def load_catalogue(path: Path | None = None) -> list[dict]:
    """Rows of config/network_services.tsv as dicts (comment lines start with #). Falls back to a tiny built-in list."""
    path = Path(path) if path else catalogue_path()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return [dict(row) for row in _FALLBACK]
    header, rows = None, []
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cells = line.rstrip("\r").split("\t")
        if header is None:
            header = [c.strip() for c in cells]
            continue
        cells += [""] * (len(header) - len(cells))
        rows.append({name: cells[i].strip() for i, name in enumerate(header)})
    return [r for r in rows if r.get("service")] or [dict(row) for row in _FALLBACK]


def command_table(path: Path | None = None) -> dict:
    """{(command, sub): {"flag": str, "services": set}} from the `used_by` column of the catalogue.

    A used_by entry that starts with "plasbench " names a command: "plasbench upgrade", "plasbench tools add" (a sub-command),
    "plasbench validate-cohort --online" (only with that flag). Entries that are file paths are for test/test_network_declared.py.
    The command-line pre-flight (plasbench/cli.py) and the window's gating (plasbench/netgate.py) both read this one table."""
    table: dict = {}
    for row in load_catalogue(path):
        for token in (row.get("used_by") or "").split(";"):
            words = token.split()
            if len(words) < 2 or words[0] != "plasbench":
                continue
            flag = next((w for w in words[2:] if w.startswith("-")), "")
            sub_name = next((w for w in words[2:] if not w.startswith("-")), "")
            entry = table.setdefault((words[1], sub_name), {"flag": flag, "services": set()})
            entry["services"].add(row["service"])
    return table


SERVICES: dict[str, dict] = {row["service"]: row for row in load_catalogue()}
SERVICE_LABELS: dict[str, str] = {name: row.get("label") or name for name, row in SERVICES.items()}


class NoInternet(RuntimeError):
    """An online-only action was asked for while the service it needs is unreachable.

    .service  the first unreachable service name; .state  as in check(); .advice  list of plain sentences;
    str(exc) is the whole message: 'X needs the internet (github.com unreachable: DNS failure). <advice>'."""

    def __init__(self, service: str, state: str, advice: list, message: str):
        super().__init__(message)
        self.service, self.state, self.advice, self.message = service, state, list(advice), message


# -- environment -------------------------------------------------------------------------------------------------------------
def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _timeout(value) -> float:
    if value is not None:
        return float(value)
    try:
        seconds = float(os.environ.get("PLASBENCH_ONLINE_TIMEOUT", "") or DEFAULT_TIMEOUT)
        return seconds if seconds > 0 else DEFAULT_TIMEOUT
    except ValueError:
        return DEFAULT_TIMEOUT


def forced_offline() -> bool:
    """True when PLASBENCH_OFFLINE=1: nothing online may be attempted. Cheap (no probing)."""
    return _flag("PLASBENCH_OFFLINE")


def is_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False


# -- default backends (replaced by tests) -----------------------------------------------------------------------------------
def _default_resolver(host: str) -> list:
    return [info[4][0] for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)]


def _default_connector(address: str, port: int, timeout: float) -> None:
    with socket.create_connection((address, port), timeout=timeout):
        return None


def _default_fetcher(url: str, host: str, timeout: float) -> tuple:
    """One HEAD request, nothing downloaded. Returns (status, location_header, content_type)."""
    import http.client
    parts = urlsplit(url)
    path = (parts.path or "/") + (("?" + parts.query) if parts.query else "")
    if parts.scheme == "https":
        connection = http.client.HTTPSConnection(parts.hostname, parts.port or 443, timeout=timeout, context=ssl.create_default_context())
    else:
        connection = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=timeout)
    try:
        connection.request("HEAD", path, headers={"User-Agent": "PlasBench-netcheck", "Accept": "*/*"})
        response = connection.getresponse()
        return response.status, response.getheader("Location") or "", response.getheader("Content-Type") or ""
    finally:
        connection.close()


class _Backends:
    def __init__(self, resolver=None, connector=None, fetcher=None):
        self.resolver = resolver or _default_resolver
        self.connector = connector or _default_connector
        self.fetcher = fetcher or _default_fetcher


# -- classifying a failure ----------------------------------------------------------------------------------------------------
def classify(exc: BaseException) -> tuple:
    """(kind, short text) for an exception raised by a probe or by a library doing a network call."""
    import errno
    import urllib.error
    if isinstance(exc, urllib.error.URLError) and not isinstance(exc, urllib.error.HTTPError):
        inner = getattr(exc, "reason", None)
        if isinstance(inner, BaseException):
            return classify(inner)
        return "refused", str(inner or exc)
    if isinstance(exc, urllib.error.HTTPError):
        return ("proxy", "proxy authentication required") if exc.code == 407 else ("http", f"HTTP {exc.code}")
    if isinstance(exc, socket.gaierror):
        return "dns", "name does not resolve"
    if isinstance(exc, (ssl.SSLCertVerificationError, ssl.SSLError)):
        return "tls", f"certificate or TLS error ({getattr(exc, 'reason', None) or exc})"
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "timeout", "timed out"
    if isinstance(exc, ConnectionRefusedError):
        return "refused", "connection refused"
    if isinstance(exc, OSError):
        if exc.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH, getattr(errno, "ENETDOWN", -1)):
            return "refused", "network unreachable"
        text = str(exc).lower()
        if "name or service not known" in text or "temporary failure in name resolution" in text or "getaddrinfo" in text or "nodename nor servname" in text:
            return "dns", "name does not resolve"
        if "certificate" in text or "ssl" in text:
            return "tls", "certificate or TLS error"
        if "timed out" in text:
            return "timeout", "timed out"
        return "refused", str(exc) or type(exc).__name__
    text = str(exc).lower()
    if "proxy" in text or "tunnel" in text:
        return "proxy", "proxy refused the connection"
    return "refused", str(exc) or type(exc).__name__


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _same_site(a: str, b: str) -> bool:
    a, b = (a or "").lower(), (b or "").lower()
    return a == b or a.endswith("." + b) or b.endswith("." + a) or ".".join(a.split(".")[-2:]) == ".".join(b.split(".")[-2:])


def _probe(name: str, row: dict, timeout: float, backends: _Backends) -> dict:
    """Probe one service: DNS first, then a TCP/TLS connection and, when the catalogue has a probe_url, one HEAD request."""
    started = time.monotonic()
    result = {"ok": False, "ms": None, "error": "", "kind": ""}

    def done(ok=False, error="", kind=""):
        result.update(ok=ok, error=error, kind=kind, ms=int((time.monotonic() - started) * 1000))
        return result

    hosts = [h.strip() for h in (row.get("probe_host") or "").split(",") if h.strip()]
    url = (row.get("probe_url") or "").strip()
    if not hosts and url:
        hosts = [urlsplit(url).hostname or ""]
    if not hosts:
        return done(False, "no probe address in the catalogue", "refused")
    try:
        if name == "dns":
            backends.resolver(hosts[0])
            return done(True)
        last = ("refused", "")
        for host in hosts:                     # an address list means "any of these answers"
            try:
                if _is_ip(host):
                    backends.connector(host, 443, timeout)
                    return done(True)
                try:
                    addresses = backends.resolver(host)
                except Exception as exc:       # noqa: BLE001 - classified below
                    kind, text = classify(exc)
                    raise _Probe(kind if kind == "dns" else "dns", f"{host}: {text}") from exc
                if not addresses:
                    raise _Probe("dns", f"{host}: no address")
                backends.connector(addresses[0], 443, timeout)
                if url:
                    status, location, ctype = backends.fetcher(url, host, timeout)
                    if status == 407:
                        raise _Probe("proxy", "a proxy wants a login (HTTP 407)")
                    if 300 <= status < 400 and location and urlsplit(location).hostname and not _same_site(urlsplit(location).hostname, urlsplit(url).hostname or host):
                        raise _Probe("proxy", f"redirected to {urlsplit(location).hostname}: a sign-in page or proxy is in the way")
                    if status == 200 and url.endswith("/generate_204"):
                        raise _Probe("proxy", "a sign-in page answered instead of the service")
                    if status >= 500:
                        raise _Probe("http", f"the service answered HTTP {status}")
                return done(True)
            except _Probe as probe:
                last = (probe.kind, probe.text)
            except Exception as exc:           # noqa: BLE001
                kind, text = classify(exc)
                last = (kind, f"{host}: {text}")
        return done(False, last[1], last[0])
    except Exception as exc:                   # noqa: BLE001 - check() must never raise
        kind, text = classify(exc)
        return done(False, text, kind)


class _Probe(Exception):
    def __init__(self, kind: str, text: str):
        super().__init__(text)
        self.kind, self.text = kind, text


# -- the cache -----------------------------------------------------------------------------------------------------------------
_LOCK = threading.Lock()
_CACHE: dict = {}


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()


def _cached(name: str, max_age: float):
    with _LOCK:
        entry = _CACHE.get(name)
    if entry and max_age > 0 and time.monotonic() - entry[0] <= max_age:
        return dict(entry[1])
    return None


def _store(name: str, result: dict) -> None:
    with _LOCK:
        _CACHE[name] = (time.monotonic(), dict(result))


# -- the answer ----------------------------------------------------------------------------------------------------------------
_KIND_TEXT = {"dns": "DNS failure", "timeout": "timed out", "refused": "connection refused", "tls": "TLS or certificate error",
              "http": "the server returned an error", "proxy": "a proxy or sign-in page is in the way", "forced": "PLASBENCH_OFFLINE=1 is set"}


def _host_of(name: str) -> str:
    row = SERVICES.get(name) or {}
    hosts = [h.strip() for h in (row.get("probe_host") or "").split(",") if h.strip()]
    return hosts[0] if hosts else (urlsplit(row.get("probe_url") or "").hostname or name)


def _dns_advice() -> str:
    if is_wsl():
        return ("DNS is not working; in WSL try `wsl --shutdown` in PowerShell and open the terminal again, check the VPN "
                "(some VPNs break WSL's DNS), or set a DNS server such as 1.1.1.1 in /etc/resolv.conf.")
    return "DNS is not working: names do not resolve although the connection itself is up. Check the VPN, restart the network, or set a DNS server such as 1.1.1.1."


def _advice(state: str, services: dict) -> list:
    out = []
    if state in ("online", "assumed_online"):
        return out
    if state == "forced_offline":
        return ["Online-only actions are switched off on purpose. Scoring, reports and runs on files already on disk keep working. "
                "Unset PLASBENCH_OFFLINE (or set it to 0) to go online again."]
    if state == "offline":
        out.append("This computer has no working internet connection. Connect it (cable, Wi-Fi, VPN or proxy) and try again; "
                   "scoring, reports and runs on files already on disk work without it.")
    elif state == "dns_broken":
        out.append(_dns_advice())
    failed = [(n, r) for n, r in services.items() if not r.get("ok") and n not in BASE_SERVICES]
    for name, result in failed:
        label = SERVICE_LABELS.get(name, name)
        kind = result.get("kind")
        if kind == "tls":
            out.append(f"{label} answered with a certificate or TLS error: a proxy, antivirus or a wrong clock can cause this; check the system date and any corporate proxy.")
        elif kind == "proxy":
            out.append(f"Something is in the way of {label}: a captive-portal sign-in page or a proxy that wants a login. Open a browser, sign in to the network, then retry.")
        elif state == "limited":
            out.append(f"{label} ({_host_of(name)}) is not reachable although the rest of the internet is: it may be down or blocked by a firewall.")
        extra = (SERVICES.get(name) or {}).get("advice", "")
        if extra and extra not in out:
            out.append(extra)
    if state == "limited" and not failed:
        out.append("Some online services are not reachable; try again in a minute.")
    return out


def check(services=None, timeout=None, cache_seconds: float = 10, *, resolver=None, connector=None, fetcher=None) -> dict:
    """Probe the named services in parallel (default: all in the catalogue) and say what state the network is in. Never raises.

    The internet and dns probes are always included, because they are what tells "no network" from "name lookup broken" from
    "this one service is down". resolver/connector/fetcher replace the socket calls (tests)."""
    now = time.time()
    try:
        names = list(SERVICES) if services is None else ([services] if isinstance(services, str) else list(services))
        names = [n for n in names if n in SERVICES]
        wanted = list(dict.fromkeys(list(BASE_SERVICES) + names))
        if _flag("PLASBENCH_OFFLINE"):
            forced = {n: {"ok": False, "ms": None, "error": "PLASBENCH_OFFLINE=1", "kind": "forced"} for n in wanted}
            return {"online": False, "state": "forced_offline", "checked": now, "services": forced, "advice": _advice("forced_offline", forced)}
        if _flag("PLASBENCH_ASSUME_ONLINE"):
            assumed = {n: {"ok": True, "ms": 0, "error": "", "kind": ""} for n in wanted}
            return {"online": True, "state": "assumed_online", "checked": now, "services": assumed, "advice": []}
        limit = _timeout(timeout)
        backends = _Backends(resolver, connector, fetcher)
        results, todo = {}, []
        for name in wanted:
            hit = _cached(name, cache_seconds)
            if hit is not None:
                results[name] = hit
            else:
                todo.append(name)
        if todo:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(12, len(todo))) as pool:
                futures = {pool.submit(_probe, n, SERVICES[n], limit, backends): n for n in todo}
                for future in concurrent.futures.as_completed(futures):
                    name = futures[future]
                    try:
                        results[name] = future.result()
                    except Exception as exc:    # noqa: BLE001
                        results[name] = {"ok": False, "ms": None, "error": str(exc), "kind": "refused"}
                    _store(name, results[name])
        ordered = {n: results[n] for n in wanted}
        state = _state(ordered, names)
        return {"online": state == "online", "state": state, "checked": now, "services": ordered, "advice": _advice(state, ordered)}
    except Exception as exc:                    # noqa: BLE001 - never raise
        return {"online": False, "state": "offline", "checked": now, "services": {},
                "advice": [f"The connection check itself failed ({type(exc).__name__}: {exc})."]}


def _state(results: dict, requested: list) -> str:
    others = {n: r for n, r in results.items() if n not in BASE_SERVICES}
    internet_ok = results.get("internet", {}).get("ok") or any(r.get("ok") for r in others.values())
    dns_ok = results.get("dns", {}).get("ok")
    failed = {n: r for n, r in others.items() if not r.get("ok")}
    if not internet_ok:
        # Direct IP blocked or absent and no service answered. A resolver that answers while nothing connects is still "offline".
        return "offline"
    if not dns_ok or (failed and others and all(r.get("kind") == "dns" for r in failed.values()) and len(failed) == len(others)):
        return "dns_broken"
    if failed:
        return "limited"
    return "online"


def reason_text(name: str, result: dict) -> str:
    return f"{_host_of(name)} unreachable: {_KIND_TEXT.get(result.get('kind'), result.get('error') or 'not reachable')}"


def require(service_or_list, action: str = "", *, any_of: bool = False, hint: str = "", timeout=None, cache_seconds: float = 10, **backends) -> None:
    """Return None when the named service(s) are reachable, else raise NoInternet.

    any_of=True accepts one reachable service out of several (reads from SRA or ENA). `hint` is appended to the advice
    (what to do instead, for example 'place the files and use --local-inputs'). The message reads
    'X needs the internet (github.com unreachable: DNS failure). <advice>'."""
    names = [service_or_list] if isinstance(service_or_list, str) else list(service_or_list)
    names = [n for n in names if n in SERVICES] or names
    answer = check(names, timeout=timeout, cache_seconds=cache_seconds, **backends)
    got = answer["services"]
    if answer["state"] in ("online", "assumed_online"):
        return None
    if answer["state"] == "forced_offline":
        bad = names
    else:
        bad = [n for n in names if not got.get(n, {}).get("ok")]
        if any_of and len(bad) < len(names):
            return None
        if not bad:
            return None
        if answer["state"] == "limited" and not bad:
            return None
    state = answer["state"]
    who = action or "This action"
    if state == "forced_offline":
        detail = "PLASBENCH_OFFLINE=1 is set"
    elif state == "offline":
        detail = "no network: " + ", ".join(_host_of(n) for n in bad[:3]) + " unreachable"
    else:
        detail = "; ".join(reason_text(n, got.get(n, {})) for n in bad[:3])
    advice = list(answer["advice"])
    if hint:
        advice.append(hint)
    message = f"{who} needs the internet ({detail}). " + " ".join(advice)
    raise NoInternet(bad[0] if bad else names[0], state, advice, message.strip())


def explain(exc: BaseException, service="internet", action: str = "", quiet_if_up: bool = False) -> str:
    """One plain sentence for a network call that just failed, for python/ scripts to print instead of a traceback.

    Asks check() (cached, short timeouts); when the network looks fine the sentence says what the library reported."""
    kind, text = classify(exc)
    try:
        require(service, action=action or "The request")
    except NoInternet as err:
        return err.message
    except Exception:                           # noqa: BLE001
        pass
    if quiet_if_up:
        return ""
    who = action or "The request"
    return f"{who} failed ({text}) although the internet looks reachable; the service may be busy or refusing it. Try again in a few minutes."


def status_table(answer: dict) -> str:
    """Plain-text table for `plasbench net`."""
    rows = [f"{'service':15s} {'state':8s} {'ms':>6s}  detail"]
    for name, r in answer.get("services", {}).items():
        rows.append(f"{name:15s} {'ok' if r.get('ok') else 'DOWN':8s} {'' if r.get('ms') is None else r['ms']:>6}  "
                    f"{SERVICE_LABELS.get(name, name)}{'' if r.get('ok') else ' - ' + (r.get('error') or r.get('kind') or '')}")
    rows.append("")
    rows.append(f"state: {answer.get('state')}")
    for sentence in answer.get("advice", []):
        rows.append(f"  {sentence}")
    return "\n".join(rows)


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="netcheck.py")
    sub = parser.add_subparsers(dest="command", required=True)
    req = sub.add_parser("require", help="exit 0 when the services are reachable; otherwise print why on stderr and exit 3")
    req.add_argument("services", nargs="+")
    req.add_argument("--any", action="store_true", help="one reachable service is enough")
    req.add_argument("--action", default="")
    req.add_argument("--hint", default="")
    args = parser.parse_args(argv)
    try:
        require(args.services, action=args.action, any_of=args.any, hint=args.hint)
    except NoInternet as exc:
        print(f"ERROR: {exc.message}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
