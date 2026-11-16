"""Is a newer PlasBench release published? Used by the window's "Check for updates" button.

Only ever run when the user asks: PlasBench contacts GitHub's public release API (the same address
`plasbench upgrade` uses), sends nothing about the user or the computer, and never installs anything by itself.
The upgrade stays a separate, confirmed action (`plasbench upgrade --yes`).
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

REPO = "ubeffiong/plasbench"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"


def parse_version(text: str) -> tuple:
    """'v0.4.1' -> (0, 4, 1); anything without a dotted number -> ()."""
    match = re.match(r"^\s*v?(\d+(?:\.\d+)*)", str(text or ""))
    return tuple(int(part) for part in match.group(1).split(".")) if match else ()


def fetch_latest(timeout: float = 8.0) -> dict:
    request = urllib.request.Request(LATEST_URL, headers={"Accept": "application/vnd.github+json", "User-Agent": "PlasBench"})
    with urllib.request.urlopen(request, timeout=timeout) as response:   # nosec: fixed https GitHub address
        return json.loads(response.read().decode("utf-8"))


def check(current: str, fetch=fetch_latest) -> dict:
    """{current, latest, newer, url, error}. A network failure is reported, never raised."""
    result = {"current": current, "latest": "", "newer": False, "url": f"https://github.com/{REPO}/releases/latest", "error": ""}
    try:
        release = fetch()
    except urllib.error.URLError as exc:
        reason = str(getattr(exc, "reason", exc))
        if "Name or service not known" in reason or "getaddrinfo" in reason or "Temporary failure in name resolution" in reason:
            result["error"] = ("Could not reach GitHub: this computer's DNS is not working (common in WSL2 or behind a VPN). "
                               "Run wsl --shutdown in PowerShell and reopen PlasBench, or turn the VPN off or on.")
        else:
            result["error"] = f"Could not reach GitHub ({reason}). Check the internet connection, VPN or proxy."
        return result
    except (OSError, ValueError) as exc:
        result["error"] = f"Could not read the latest release ({type(exc).__name__}: {exc})."
        return result
    tag = str((release or {}).get("tag_name", ""))
    latest = parse_version(tag)
    if not latest:
        result["error"] = "GitHub did not return a release version."
        return result
    result["latest"] = ".".join(str(part) for part in latest)
    result["url"] = str((release or {}).get("html_url") or result["url"])
    result["newer"] = latest > parse_version(current)
    return result
