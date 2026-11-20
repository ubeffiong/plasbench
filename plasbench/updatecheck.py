"""Is a newer PlasBench release published? Used by the window's Updates card and its "Check for updates" button.

PlasBench contacts GitHub's public release API (the same address `plasbench upgrade` uses) and nothing else; it sends nothing about the user or the computer
(no identifier, no usage data: one plain GET with a fixed User-Agent) and never installs anything by itself. The install stays a separate, confirmed action
(`plasbench upgrade`, see plasbench/updater.py for how the window runs it).

* The answer is cached in a small file (~/.plasbench/ui/update-check.json) so the window shows it at once, with the time it was checked.
* A background check runs at most once every 24 hours and when the window starts (a daemon thread: it never sits on the page-load path), only when the setting
  UPDATE_CHECK is `auto` (the default) and PLASBENCH_OFFLINE is not set. UPDATE_CHECK=off stops it; the Check button always works (unless PLASBENCH_OFFLINE=1).
* Release notes are shown as plain text (a few lines) and never run or rendered as HTML; every address shown must be https on github.com,
  api.github.com or objects.githubusercontent.com.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = "ubeffiong/plasbench"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
ALLOWED_HOSTS = ("github.com", "api.github.com", "objects.githubusercontent.com")   # the netcheck "github" service and its release-asset host
MAX_RESPONSE_BYTES = 2 * 1024 * 1024        # a release description is a few KB; anything bigger is not one
CACHE_MAX_AGE = 24 * 3600                   # a background check runs at most this often
RETRY_AFTER_ERROR = 3600                    # after a failed background check, wait an hour
NOTES_LINES = 8
NOTES_CHARS = 700
_LOCK = threading.Lock()


def parse_version(text: str) -> tuple:
    """'v0.4.1' -> (0, 4, 1); anything without a dotted number -> ()."""
    match = re.match(r"^\s*v?(\d+(?:\.\d+)*)", str(text or ""))
    return tuple(int(part) for part in match.group(1).split(".")) if match else ()


def relation(current: str, latest: str) -> str:
    """'newer' (the release is newer than the installed version), 'same', 'older' (the installed version is ahead of the release), or '' when either is unknown."""
    a, b = parse_version(latest), parse_version(current)
    if not a or not b:
        return ""
    width = max(len(a), len(b))
    a, b = a + (0,) * (width - len(a)), b + (0,) * (width - len(b))      # 1.0 and 1.0.0 are the same release
    return "newer" if a > b else "same" if a == b else "older"


def safe_url(url: str) -> str:
    """The URL when it is https on one of the GitHub hosts, else an empty string: nothing else is ever shown or followed."""
    try:
        parts = urllib.parse.urlsplit(str(url or ""))
    except ValueError:
        return ""
    return str(url) if parts.scheme == "https" and (parts.hostname or "").lower() in ALLOWED_HOSTS else ""


def fetch_latest(timeout: float = 8.0) -> dict:
    request = urllib.request.Request(LATEST_URL, headers={"Accept": "application/vnd.github+json", "User-Agent": "PlasBench"})
    with urllib.request.urlopen(request, timeout=timeout) as response:   # nosec: fixed https GitHub address
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("the release description is unexpectedly large")
    return json.loads(raw.decode("utf-8"))


def notes_excerpt(body, lines: int = NOTES_LINES, chars: int = NOTES_CHARS) -> list:
    """The first few lines of a release description as plain text: markup marks and HTML are removed, nothing is interpreted or run."""
    out, used = [], 0
    for raw in str(body or "").replace("\r", "").split("\n"):
        text = re.sub(r"<[^>]*>", "", raw)
        text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text)
        text = re.sub(r"^\s*[-*+]\s+", "- ", text)
        text = re.sub(r"[`*_]{1,3}", "", text)
        text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text).strip()
        if not text or set(text) <= set("-=_ "):
            continue
        if used + len(text) > chars:
            text = text[: max(0, chars - used)].rstrip() + "..."
            out.append(text)
            break
        out.append(text)
        used += len(text)
        if len(out) >= lines:
            break
    return out


def _release_fields(release: dict, version: str) -> dict:
    """The part of a release the window shows: date, notes, the installer file and its checksum file."""
    published = str(release.get("published_at") or release.get("created_at") or "")[:10]
    want = f"plasbench-{version}.tar.gz"
    asset, checksum = {}, ""
    for item in release.get("assets") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        url = safe_url(item.get("browser_download_url"))
        if name == want and url:
            size = item.get("size")
            asset = {"name": name, "size": int(size) if isinstance(size, int) and size >= 0 else None, "url": url}
        elif name == want + ".sha256" and url:
            checksum = url
    return {"published": published, "notes": notes_excerpt(release.get("body")), "asset": asset, "checksum_url": checksum}


def check(current: str, fetch=fetch_latest) -> dict:
    """{current, latest, newer, relation, url, error, error_kind, published, notes, asset, checksum_url, checked_at}. A network failure is reported, never raised.

    error_kind: forced_offline, dns, network, rate_limited, not_found, malformed ('' when there is no error)."""
    result = {"current": current, "latest": "", "newer": False, "relation": "", "url": RELEASES_PAGE, "error": "", "error_kind": "",
              "published": "", "notes": [], "asset": {}, "checksum_url": "", "checked_at": time.time()}
    from . import netcheck
    if netcheck.forced_offline():
        result["error"] = "PLASBENCH_OFFLINE=1 is set, so PlasBench does not look for updates. Unset it to check."
        result["error_kind"] = "forced_offline"
        return result
    try:
        release = fetch()
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            reset = ""
            try:
                stamp = int(exc.headers.get("X-RateLimit-Reset", "")) if exc.headers else 0
                reset = f" It resets around {time.strftime('%H:%M', time.localtime(stamp))}." if stamp else ""
            except (ValueError, TypeError):
                reset = ""
            result["error"] = "GitHub is limiting requests from this network (rate limit), so the check was refused." + reset + " Try again later; nothing is wrong with PlasBench."
            result["error_kind"] = "rate_limited"
        elif exc.code == 404:
            result["error"] = "GitHub has no published release to compare with yet."
            result["error_kind"] = "not_found"
        else:
            result["error"] = f"Could not reach GitHub (HTTP {exc.code}). Check the internet connection, VPN or proxy."
            result["error_kind"] = "network"
        return result
    except urllib.error.URLError as exc:
        reason = str(getattr(exc, "reason", exc))
        if "Name or service not known" in reason or "getaddrinfo" in reason or "Temporary failure in name resolution" in reason:
            result["error"] = ("Could not reach GitHub: this computer's DNS is not working (common in WSL2 or behind a VPN). "
                               "Run wsl --shutdown in PowerShell and reopen PlasBench, or turn the VPN off or on.")
            result["error_kind"] = "dns"
        else:
            result["error"] = f"Could not reach GitHub ({reason}). Check the internet connection, VPN or proxy."
            result["error_kind"] = "network"
        return result
    except (OSError, ValueError) as exc:
        result["error"] = f"Could not read the latest release ({type(exc).__name__}: {exc})."
        result["error_kind"] = "malformed" if isinstance(exc, ValueError) else "network"
        return result
    if not isinstance(release, dict):
        result["error"] = "GitHub did not return a release."
        result["error_kind"] = "malformed"
        return result
    tag = str(release.get("tag_name", ""))
    latest = parse_version(tag)
    if not latest:
        result["error"] = "GitHub did not return a release version."
        result["error_kind"] = "malformed"
        return result
    result["latest"] = ".".join(str(part) for part in latest)
    result["url"] = safe_url(release.get("html_url")) or RELEASES_PAGE
    result["relation"] = relation(current, result["latest"])
    result["newer"] = result["relation"] == "newer"
    result.update(_release_fields(release, result["latest"]))
    return result


# ---- the cache ----------------------------------------------------------------------------------------------------------------
def cache_path() -> Path:
    return Path(os.environ.get("PLASBENCH_UI_HOME", Path.home() / ".plasbench" / "ui")) / "update-check.json"


def load_cache() -> dict:
    try:
        data = json.loads(cache_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(result: dict) -> None:
    """Keep the last good answer; a failed check is recorded beside it (when and why) without erasing what was known."""
    cache = load_cache()
    if result.get("error"):
        cache["attempt"] = {"at": result.get("checked_at") or time.time(), "error": result["error"], "error_kind": result.get("error_kind", "")}
    else:
        cache["good"] = result
        cache["attempt"] = {"at": result.get("checked_at") or time.time(), "error": "", "error_kind": ""}
    path = cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(cache, indent=1), encoding="utf-8")
        os.replace(str(tmp), str(path))
    except OSError:
        pass                                  # an unwritable home only means the answer is not remembered


def state(current: str, mode: str = "auto", now: float | None = None) -> dict:
    """What the window shows without any network: the cached answer judged against the version installed NOW, when it was checked, and why a check is not possible."""
    now = time.time() if now is None else now
    cache = load_cache()
    good = cache.get("good") if isinstance(cache.get("good"), dict) else None
    attempt = cache.get("attempt") if isinstance(cache.get("attempt"), dict) else {}
    out = {"current": current, "latest": "", "newer": False, "relation": "", "url": RELEASES_PAGE, "published": "", "notes": [], "asset": {}, "checksum_url": "",
           "checked_at": None, "age_seconds": None, "attempted_at": attempt.get("at"), "error": "", "error_kind": "", "mode": mode, "checked": False}
    if good and good.get("latest"):
        out.update({k: good.get(k, out[k]) for k in ("latest", "url", "published", "notes", "asset", "checksum_url")})
        out["checked_at"] = good.get("checked_at")
        out["age_seconds"] = max(0, int(now - float(good.get("checked_at") or now)))
        out["relation"] = relation(current, out["latest"])        # judged against the installed version now: an update done since is not offered again
        out["newer"] = out["relation"] == "newer"
        out["checked"] = True
    if attempt.get("error") and (not good or float(attempt.get("at") or 0) >= float(good.get("checked_at") or 0)):
        out["error"], out["error_kind"] = attempt["error"], attempt.get("error_kind", "")
    from . import netcheck
    if netcheck.forced_offline():
        out["error"], out["error_kind"] = "PLASBENCH_OFFLINE=1 is set, so PlasBench does not look for updates. Unset it to check.", "forced_offline"
    return out


def due(current: str, mode: str = "auto", now: float | None = None) -> bool:
    """Should the background check run now? Only in auto mode, never with PLASBENCH_OFFLINE=1, at most once a day (an hour after a failure)."""
    from . import netcheck
    if mode != "auto" or netcheck.forced_offline():
        return False
    now = time.time() if now is None else now
    cache = load_cache()
    good = cache.get("good") if isinstance(cache.get("good"), dict) else None
    attempt = cache.get("attempt") if isinstance(cache.get("attempt"), dict) else {}
    last = max(float((good or {}).get("checked_at") or 0), float(attempt.get("at") or 0))
    wait = RETRY_AFTER_ERROR if attempt.get("error") and float(attempt.get("at") or 0) >= float((good or {}).get("checked_at") or 0) else CACHE_MAX_AGE
    return now - last >= wait


def refresh(current: str, fetch=None) -> dict:
    """Check now, remember the answer, return it. One check at a time."""
    with _LOCK:
        result = check(current, fetch or fetch_latest)
        if result.get("error_kind") != "forced_offline":
            save_cache(result)
        return result


def start_background(current: str, mode_of, fetch=None, on_done=None) -> "threading.Thread | None":
    """At window start (and again from the page's own timer): a daemon thread that runs refresh() when due() says so. Returns the thread, or None when nothing is due.
    `mode_of()` is read inside the thread so a slow settings read never delays the caller."""
    def work():
        try:
            mode = mode_of()
            if due(current, mode):
                result = refresh(current, fetch)
                if on_done:
                    on_done(result)
        except Exception:  # noqa: BLE001 - a background courtesy must never break the window
            pass
    thread = threading.Thread(target=work, name="plasbench-update-check", daemon=True)
    thread.start()
    return thread
