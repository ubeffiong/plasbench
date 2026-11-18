"""In-process caches that keep the window's pages fast (see docs/WINDOW_PERFORMANCE.md).

Nothing here is a database or is stored on disk: every value is rebuilt from the plain files (config/*.tsv, config.sh, study folders, ...) when the file's
modification time or size changes, when its time-to-live runs out, or when `clear()` is called (the window does that after anything it changes).

* `memo(key, sig, compute)`   a value that depends on files: recomputed only when `sig` (a stat fingerprint) changes.
* `ttl(key, seconds, compute)` a value that is cheap to share for a moment (the page asks for the same list from several routes at once).
* `which(exe)`               shutil.which, remembered; an expired answer is returned at once and refreshed in the background (stale-while-revalidate).
* `swr(key, seconds, compute)` the same for any slow probe (docker, conda): returns (value, ready); never blocks when `block=False`.

STATS counts computes and hits, so tests can assert "the second call did no work" without timing anything.
"""
from __future__ import annotations

import os
import shutil
import threading
import time

STATS = {"memo_hit": 0, "memo_miss": 0, "ttl_hit": 0, "ttl_miss": 0, "swr_hit": 0, "swr_miss": 0, "swr_refresh": 0}
_LOCK = threading.RLock()
_MEMO: dict = {}
_TTL: dict = {}
_SWR: dict = {}
_INFLIGHT: set = set()
WHICH_TTL = float(os.environ.get("PLASBENCH_PROBE_TTL", "30"))


def sig(*paths) -> tuple:
    """A cheap fingerprint of files: (mtime_ns, size) each, None for a file that is not there."""
    out = []
    for p in paths:
        try:
            st = os.stat(p)
            out.append((st.st_mtime_ns, st.st_size))
        except OSError:
            out.append(None)
    return tuple(out)


def memo(key, signature, compute):
    with _LOCK:
        hit = _MEMO.get(key)
        if hit is not None and hit[0] == signature:
            STATS["memo_hit"] += 1
            return hit[1]
    value = compute()
    with _LOCK:
        STATS["memo_miss"] += 1
        _MEMO[key] = (signature, value)
    return value


def ttl(key, seconds, compute):
    now = time.monotonic()
    with _LOCK:
        hit = _TTL.get(key)
        if hit is not None and now - hit[0] < seconds:
            STATS["ttl_hit"] += 1
            return hit[1]
    value = compute()
    with _LOCK:
        STATS["ttl_miss"] += 1
        _TTL[key] = (time.monotonic(), value)
    return value


def _refresh(key, compute):
    try:
        value = compute()
    except Exception:  # noqa: BLE001 - a probe that fails keeps the last answer
        with _LOCK:
            _INFLIGHT.discard(key)
        return
    with _LOCK:
        _SWR[key] = (time.monotonic(), value)
        _INFLIGHT.discard(key)
        STATS["swr_refresh"] += 1


def swr(key, seconds, compute, block=True, wait=0.0):
    """(value, ready). A fresh answer is returned as it is; a stale one is returned at once and refreshed in the background; with no answer yet the call
    waits for the probe (block=True) or starts it in the background and returns (None, False) so the page can show "checking" and ask again."""
    now = time.monotonic()
    with _LOCK:
        hit = _SWR.get(key)
        if hit is not None:
            if now - hit[0] < seconds:
                STATS["swr_hit"] += 1
                return hit[1], True
            if key not in _INFLIGHT:
                _INFLIGHT.add(key)
                threading.Thread(target=_refresh, args=(key, compute), daemon=True).start()
            STATS["swr_hit"] += 1
            return hit[1], True
    STATS["swr_miss"] += 1
    if block:
        value = compute()
        with _LOCK:
            _SWR[key] = (time.monotonic(), value)
        return value, True
    with _LOCK:
        if key not in _INFLIGHT:
            _INFLIGHT.add(key)
            threading.Thread(target=_refresh, args=(key, compute), daemon=True).start()
    deadline = time.monotonic() + wait   # a probe that is quick (most are) is answered in this very call
    while time.monotonic() < deadline:
        with _LOCK:
            hit = _SWR.get(key)
        if hit is not None:
            return hit[1], True
        time.sleep(0.02)
    return None, False


def which(exe, block=True):
    """shutil.which, remembered for WHICH_TTL seconds per (exe, PATH). Returns (path or None, ready)."""
    path_env = os.environ.get("PATH", "")
    return swr(("which", exe, path_env), WHICH_TTL, lambda: shutil.which(exe), block)


def which_path(exe):
    """Like shutil.which for callers that always want an answer."""
    return which(exe)[0]


def realpath(p) -> str:
    """str(Path(p).resolve()), remembered briefly (a long list of results folders resolves hundreds of paths on every call)."""
    from pathlib import Path
    return ttl(("realpath", str(p)), 10.0, lambda: str(Path(p).resolve()))


def pending_probes() -> int:
    with _LOCK:
        return len(_INFLIGHT)


def clear(probes: bool = True):
    """Forget everything that depends on the outside world. File-fingerprinted memos stay valid by themselves and are kept."""
    with _LOCK:
        _TTL.clear()
        if probes:
            _SWR.clear()


def reset_all():
    with _LOCK:
        _MEMO.clear()
        _TTL.clear()
        _SWR.clear()
        _INFLIGHT.clear()
        for k in STATS:
            STATS[k] = 0
