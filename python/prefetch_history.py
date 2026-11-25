#!/usr/bin/env python3
"""Remember, across runs, that the SRA Toolkit's `prefetch` does not work on this computer, so stage 1 stops losing about a minute per isolate to a call that will fail.

The history is a small JSON file, ~/.plasbench/prefetch_history.json (PLASBENCH_STATE_DIR overrides the folder):

  {"version": "<PlasBench version>|<the prefetch program: name, size, date>", "entries": [{"t": <unix time>, "ok": true|false, "reason": "..."}]}

Entries older than 24 hours are ignored (a fixed proxy, certificate or toolkit gets a fresh try the next day), and so is the whole file when it was written by another PlasBench or
another sra-tools version (an upgrade is a new chance). prefetch counts as known-broken when the last PREFETCH_FAIL_LIMIT entries (default 2) all failed; 0 turns that off.

  python3 -I python/prefetch_history.py disabled [--limit N]       exit 0 when prefetch should be skipped, 1 otherwise (prints the reason when skipping)
  python3 -I python/prefetch_history.py record ok|fail [--reason TEXT]
  python3 -I python/prefetch_history.py show

Standard library only; Python 3.9 compatible. A problem with the file never stops a download: every failure here means "no history".
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

MAX_AGE_SECONDS = 24 * 3600
KEEP = 20


def state_dir():
    return os.environ.get("PLASBENCH_STATE_DIR") or os.path.join(os.path.expanduser("~"), ".plasbench")


def history_path():
    return os.path.join(state_dir(), "prefetch_history.json")


def plasbench_version():
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
        from plasbench import __version__
        return str(__version__)
    except Exception:  # noqa: BLE001 - a version we cannot read only makes the history less specific
        return "unknown"


def sra_version():
    """Which SRA Toolkit this is, WITHOUT running it (running prefetch to ask its version would be one more call of the very program whose failures are being counted): its resolved
    path, size and modification time, which change when it is upgraded or replaced. 'none' when it is not installed."""
    path = shutil.which("prefetch")
    if not path:
        return "none"
    try:
        real = os.path.realpath(path)
        info = os.stat(real)
        return f"{os.path.basename(real)}:{info.st_size}:{int(info.st_mtime)}"
    except OSError:
        return "unknown"


def current_version():
    return os.environ.get("PLASBENCH_FORCE_VERSION") or f"{plasbench_version()}|{sra_version()}"


def load(version=None, now=None):
    """The entries that count now: the file's version matches and they are under 24 hours old."""
    now = time.time() if now is None else now
    version = current_version() if version is None else version
    try:
        with open(history_path(), encoding="utf-8") as handle:
            data = json.load(handle)
        if data.get("version") != version:
            return []
        return [e for e in data.get("entries", []) if isinstance(e, dict) and now - float(e.get("t", 0)) <= MAX_AGE_SECONDS]
    except (OSError, ValueError, TypeError, AttributeError):
        return []


def record(ok, reason="", version=None, now=None):
    now = time.time() if now is None else now
    version = current_version() if version is None else version
    entries = load(version, now)
    entries.append({"t": now, "ok": bool(ok), "reason": (reason or "")[:200]})
    try:
        os.makedirs(state_dir(), exist_ok=True)
        tmp = history_path() + f".{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump({"version": version, "entries": entries[-KEEP:]}, handle)
        os.replace(tmp, history_path())
    except OSError:
        pass


def disabled(limit, version=None, now=None):
    """(True, reason) when the last `limit` entries all failed."""
    if limit <= 0:
        return False, ""
    entries = load(version, now)
    last = entries[-limit:]
    if len(last) >= limit and all(not e.get("ok") for e in last):
        age = (time.time() if now is None else now) - float(last[-1]["t"])
        return True, f"prefetch failed on its last {limit} tries ({int(age // 60)} min ago): {last[-1].get('reason') or 'no reason recorded'}"
    return False, ""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("disabled")
    d.add_argument("--limit", type=int, default=int(os.environ.get("PREFETCH_FAIL_LIMIT", "2") or 2))
    r = sub.add_parser("record")
    r.add_argument("result", choices=("ok", "fail"))
    r.add_argument("--reason", default="")
    sub.add_parser("show")
    args = ap.parse_args(argv)
    if args.cmd == "disabled":
        off, why = disabled(args.limit)
        if off:
            print(why)
            return 0
        return 1
    if args.cmd == "record":
        record(args.result == "ok", args.reason)
        return 0
    print(json.dumps({"version": current_version(), "entries": load()}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
