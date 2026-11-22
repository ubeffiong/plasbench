#!/usr/bin/env python3
"""A resumable, chunked, parallel HTTP downloader for the big read files stage 1 fetches from ENA.

Why it exists. A 9.5 GB read set used to be fetched as a few big parallel byte ranges (or by aria2c). When ONE connection failed near the end, the whole partial file
was deleted and the download restarted from byte 0 as a single slow stream: about 9 GB of work thrown away. This module never does that.

How it works
  * The file is cut into fixed-size chunks (ENA_CHUNK_MIB, default 32 MiB). A bounded pool of workers fetches chunks with HTTP Range into `<file>.part`, each at its own
    offset, so nothing has to be joined afterwards.
  * A chunk that fails is retried on its own (exponential back-off with jitter, resuming inside the chunk from the bytes already written). A chunk that keeps failing
    stops the download with a clear error, and every finished chunk stays on disk.
  * Every response is checked: status 206, and a Content-Range whose start, end and total are the ones asked for. A read that goes quiet for ENA_STALL_SECONDS (default 45)
    is abandoned and retried. 429 and 503 are honoured (Retry-After), and make the connection budget smaller for the rest of the run.
  * Which chunks are finished is saved atomically in `<file>.part.state` (JSON: url, total, chunk size, validators, finished chunk numbers). A later attempt, a later
    `plasbench run` or a crashed process resumes from it and fetches only the missing chunks.
  * If the remote file changes (size, ETag or Last-Modified differ from the first answer) the partial data is useless and the download restarts cleanly. Only that, a
    state that does not match the file on disk, or a wrong final MD5 may delete data.
  * ENA publishes only a whole-file MD5, so a mismatch cannot be blamed on a chunk: the file is discarded, said plainly in the log, and fetched again ONCE in the same way.
  * A server that does not honour Range is read as a single stream, resuming from the bytes on disk where it can.
  * Every connection counts against one budget (`Budget`) shared fairly by the files being fetched; the budget only ever shrinks during a run.

This module only makes requests for its callers, which check the internet first (net_require in python/fetch_ena_reads.py and python/net_bench.py, PLASBENCH_OFFLINE honoured there).
Standard library only; Python 3.9 compatible.
"""
from __future__ import annotations

import email.utils
import hashlib
import http.client
import json
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque

DEFAULT_CHUNK_MIB = 32
# The most connections one PlasBench download process ever opens in total, whatever the settings say. ENA does not publish a connection limit for its HTTPS file server;
# aria2c itself refuses more than 16 per server, and a measured speed test (docs/USER_GUIDE.md, "My downloads are slow or restart") kept scaling up to 16. 24 leaves
# headroom for a person who knows their link while staying far below the numbers (50+) that download managers use and that get addresses throttled.
HARD_MAX_CONNECTIONS = 24
DEFAULT_MAX_CONNECTIONS = 16
BLOCK = 256 * 1024


def _env_num(name, default, cast=float):
    try:
        raw = os.environ.get(name, "")
        return cast(raw) if str(raw).strip() != "" else default
    except ValueError:
        return default


def settings():
    """The tunables, read from the environment each time (so tests and `plasbench` can change them between calls)."""
    return {
        "chunk": max(1 << 20, int(_env_num("ENA_CHUNK_MIB", DEFAULT_CHUNK_MIB) * (1 << 20))),
        "stall": max(0.2, _env_num("ENA_STALL_SECONDS", 45.0)),
        "retries": max(1, int(_env_num("ENA_CHUNK_RETRIES", 8, int))),
        "backoff": max(0.0, _env_num("ENA_CHUNK_BACKOFF_SECONDS", 1.0)),
        "backoff_max": max(0.0, _env_num("ENA_CHUNK_BACKOFF_MAX_SECONDS", 60.0)),
        "retry_after_max": max(0.0, _env_num("ENA_RETRY_AFTER_MAX_SECONDS", 300.0)),
        "per_file": max(0, int(_env_num("ENA_DOWNLOAD_CONNECTIONS", 0, int))),
        "budget": max(1, min(HARD_MAX_CONNECTIONS, int(_env_num("ENA_MAX_CONNECTIONS", DEFAULT_MAX_CONNECTIONS, int)))),
    }


def log(message):
    sys.stderr.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [fetch_ena_reads] {message}\n")
    sys.stderr.flush()


def human_bytes(n):
    n = float(n)
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB" if n >= 1e6 else f"{n / 1e3:.0f} KB"


def human_duration(seconds):
    seconds = int(max(0, seconds))
    if seconds < 90:
        return f"{seconds} s"
    if seconds < 5400:
        return f"{round(seconds / 60)} min"
    return f"{seconds / 3600:.1f} h"


# --- errors ----------------------------------------------------------------------------------------------------------------------
class DownloadError(OSError):
    """The download cannot go on; finished chunks are kept on disk."""


class RangeUnsupported(OSError):
    """The server answered a byte-range request with the whole file (status 200)."""


class RemoteChanged(OSError):
    """The file at the URL is not the one the first answer described."""


class Fatal(OSError):
    """Retrying cannot help (404, 403, ...)."""


class Throttled(OSError):
    def __init__(self, message, wait=0.0):
        super().__init__(message)
        self.wait = wait


# --- connection budget -----------------------------------------------------------------------------------------------------------
class Budget:
    """The total number of simultaneous connections, shared fairly by the files being fetched, and only ever lowered during a run.

    `limit` (default ENA_MAX_CONNECTIONS, never above HARD_MAX_CONNECTIONS) is the most connections open at once. Each registered file may hold at most its fair share
    (ceil(limit / files)), so one mate cannot starve the other, and when a file ends the other may use the whole budget. `reduce()` is called on 429/503/refusals; the lower
    figure is written to `memo_path` (when given) so the next process of the same run starts from it.
    """

    def __init__(self, limit=None, memo_path=None):
        cfg = settings()
        self.hard = HARD_MAX_CONNECTIONS
        self.limit = max(1, min(self.hard, int(limit if limit else cfg["budget"])))
        self.memo_path = memo_path
        self.cond = threading.Condition()
        self.active = 0
        self.peak = 0
        self.owners = {}
        self.reduced_from = None
        remembered = self._read_memo()
        if remembered and remembered < self.limit:
            self.limit = remembered
            self.reduced_from = "an earlier download of this run"

    def _read_memo(self):
        try:
            if self.memo_path and os.path.exists(self.memo_path):
                with open(self.memo_path, encoding="utf-8") as handle:
                    return max(1, int(json.load(handle).get("connections", 0)))
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return None

    def register(self, owner):
        with self.cond:
            self.owners.setdefault(owner, 0)
            self.cond.notify_all()

    def unregister(self, owner):
        with self.cond:
            self.active -= self.owners.pop(owner, 0)
            self.cond.notify_all()

    def share(self):
        return max(1, -(-self.limit // max(1, len(self.owners))))

    def acquire(self, owner, cap=0, stop=None):
        """Wait for a connection slot; False when `stop` (an Event) is set first."""
        with self.cond:
            while True:
                if stop is not None and stop.is_set():
                    return False
                mine = self.owners.get(owner, 0)
                if self.active < self.limit and mine < min(self.share(), cap or 10 ** 6):
                    self.owners[owner] = mine + 1
                    self.active += 1
                    self.peak = max(self.peak, self.active)
                    return True
                self.cond.wait(0.25)

    def release(self, owner):
        with self.cond:
            if self.owners.get(owner, 0) > 0:
                self.owners[owner] -= 1
                self.active -= 1
            self.cond.notify_all()

    def reduce(self, reason):
        """Lower the budget (to three quarters, at least 2) and remember it. Returns the new limit."""
        with self.cond:
            new = max(min(2, self.limit), (self.limit * 3) // 4)
            if new < self.limit:
                log(f"{reason}: lowering the connection budget from {self.limit} to {new} for the rest of this run")
                self.limit = new
                self._write_memo()
            self.cond.notify_all()
            return self.limit

    def _write_memo(self):
        if not self.memo_path:
            return
        try:
            tmp = f"{self.memo_path}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump({"connections": self.limit, "time": time.time()}, handle)
            os.replace(tmp, self.memo_path)
        except OSError:
            pass


# --- honest progress -------------------------------------------------------------------------------------------------------------
class Progress:
    """Bytes actually received (never the size of a preallocated file) for one run's files; the numbers only grow unless the file changed (then reset() says so)."""

    STALL_SECONDS = 60.0

    def __init__(self, run, total=0, clock=time.time):
        self.run = run
        self.clock = clock
        self.lock = threading.Lock()
        self.files = {}          # name -> {"total", "have", "state"}
        self.session_start = clock()
        self.received = 0        # bytes received by this process
        self.last_byte = clock()
        self.samples = deque(maxlen=400)   # (time, cumulative bytes received)
        self.ewma = None
        self._ewma_at = None
        self._ewma_bytes = 0
        self.retries = 0
        self.resumed_bytes = 0
        self.restarts = []
        self.notes = []
        self.last_fraction = 0.0

    def add_file(self, name, total, have=0):
        """Register a file. A file already registered (a second attempt) keeps its count, so the figure never goes down."""
        with self.lock:
            if name in self.files:
                self.files[name]["total"] = int(total or self.files[name]["total"])
                self.files[name]["state"] = "downloading"
                return
            self.files[name] = {"total": int(total or 0), "have": int(have), "state": "downloading"}
            self.resumed_bytes += int(have)

    def add(self, name, n):
        now = self.clock()
        with self.lock:
            self.files[name]["have"] += n
            self.received += n
            self.last_byte = now
            self.samples.append((now, self.received))
            if self._ewma_at is None:
                self._ewma_at, self._ewma_bytes = now, self.received
            elif now - self._ewma_at >= 2.0:
                inst = (self.received - self._ewma_bytes) / (now - self._ewma_at)
                self.ewma = inst if self.ewma is None else 0.3 * inst + 0.7 * self.ewma
                self._ewma_at, self._ewma_bytes = now, self.received

    def set_state(self, name, state):
        with self.lock:
            if name in self.files:
                self.files[name]["state"] = state

    def reset(self, name, reason):
        """The file changed or the download restarted: say so, and only now may the figure go down."""
        with self.lock:
            if name in self.files:
                self.files[name]["have"] = 0
            self.restarts.append(reason)
            self.notes.append(reason)

    def snapshot(self):
        now = self.clock()
        with self.lock:
            total = sum(f["total"] for f in self.files.values())
            have = sum(f["have"] for f in self.files.values())
            recent = [s for s in self.samples if now - s[0] <= 30.0]
            if len(recent) >= 2 and recent[-1][0] > recent[0][0]:
                rate_now = (recent[-1][1] - recent[0][1]) / (recent[-1][0] - recent[0][0])
            else:
                rate_now = 0.0
            if now - self.last_byte > 10.0:
                rate_now = 0.0
            elapsed = max(1e-6, now - self.session_start)
            average = self.received / elapsed
            states = {f["state"] for f in self.files.values()}
            quiet = now - self.last_byte
            state = "downloading"
            if self.files and states <= {"done"}:
                state = "done"
            elif self.files and all(s in ("done", "verifying", "moving") for s in states):
                state = "moving" if "moving" in states else "verifying"
            elif quiet >= self.STALL_SECONDS and have < total:
                state = "stalled"
            eta = None
            smooth = self.ewma if self.ewma else (average or None)
            if state == "downloading" and smooth and total > have:
                eta = (total - have) / smooth
            return {"run": self.run, "done_bytes": have, "total_bytes": total, "rate_now": rate_now, "rate_average": average, "eta_seconds": eta,
                    "state": state, "quiet_seconds": quiet, "retries": self.retries, "resumed_bytes": self.resumed_bytes, "received_bytes": self.received,
                    "seconds": elapsed, "restarts": list(self.restarts), "updated": now}

    def line(self, snap=None):
        s = snap or self.snapshot()
        total, have = s["total_bytes"], s["done_bytes"]
        pct = f" ({int(100 * have / total)}%)" if total else ""
        size = f"{human_bytes(have)} of {human_bytes(total)}" if total else human_bytes(have)
        if s["state"] == "done":
            return f"{s['run']}: {size}{pct}, done"
        if s["state"] == "verifying":
            return f"{s['run']}: {size}{pct}, downloaded, checking the checksum"
        if s["state"] == "moving":
            return f"{s['run']}: {size}{pct}, checksum verified, moving the files into the data folder"
        if s["state"] == "stalled":
            return f"{s['run']}: {size}{pct}, stalled (no bytes for {human_duration(s['quiet_seconds'])}), still retrying"
        rate = f"{s['rate_now'] / 1e6:.1f} MB/s now, {s['rate_average'] / 1e6:.1f} MB/s average"
        eta = f", about {human_duration(s['eta_seconds'])} left" if s["eta_seconds"] is not None else ""
        return f"{s['run']}: {size}{pct}, {rate}{eta}"


def write_progress_file(path, run, snap, line, sample=""):
    """Merge one run's entry into the shared progress JSON (results/download_progress.json), atomically, tolerating several writers."""
    if not path:
        return
    lock = path + ".lock"
    fd = None
    for _ in range(100):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock) > 10:
                    os.remove(lock)
            except OSError:
                pass
            time.sleep(0.02)
        except OSError:
            return
    try:
        data = {}
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            data = {}
        isolates = data.get("isolates") if isinstance(data.get("isolates"), dict) else {}
        entry = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in snap.items()}
        entry.update(line=line, sample=sample)
        isolates[run] = entry
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump({"updated": time.time(), "isolates": isolates}, handle, indent=1)
        os.replace(tmp, path)
    except OSError:
        pass
    finally:
        if fd is not None:
            os.close(fd)
            try:
                os.remove(lock)
            except OSError:
                pass



# --- a quiet log -----------------------------------------------------------------------------------------------------------------------------------
def short_line(entry):
    """The log's line for one run, from its progress-JSON entry: short, plain, no repeated fields ('SRR36114699: 34% of 9.5 GB, 3.4 MB/s, about 31 min left').
    The live detail (rate now and average, bytes, state) stays in results/download_progress.json for `plasbench status` and the window."""
    run, total, have = entry.get("run") or entry.get("sample") or "download", int(entry.get("total_bytes") or 0), int(entry.get("done_bytes") or 0)
    if not total:
        return f"{run}: starting"
    if have == 0:
        return f"{run}: starting, {human_bytes(total)} to download"
    pct = int(100 * have / total)
    rate = float(entry.get("rate_now") or 0)
    eta = entry.get("eta_seconds")
    tail = f", {rate / 1e6:.1f} MB/s" if rate else ""
    tail += f", about {human_duration(eta)} left" if eta is not None else ""
    return f"{run}: {pct}% of {human_bytes(total)}{tail}"


class LogGate:
    """Decides which progress lines reach the log, so a 9.5 GB isolate is a dozen lines and not two hundred.

    A line is printed (1) for the first look at a run, (2) when at least `interval` seconds (default 300) have passed AND the run has moved on by `step` percent (default 10) since the
    last line, whichever of the two comes later, and (3) when something changes: a chunk retry (at most one such line a minute), a stall, a restart of a file, a lower connection
    budget, the file being checked or moved. `state` is a dict the caller keeps (and, between processes, saves)."""

    def __init__(self, state=None, interval=None, step=None, clock=time.time):
        self.state = state if state is not None else {}
        self.interval = _env_num("ENA_LOG_INTERVAL_SECONDS", 300.0) if interval is None else interval
        self.step = _env_num("ENA_LOG_STEP_PERCENT", 10.0) if step is None else step
        self.clock = clock

    def check(self, entry):
        """Lines (a list of str, possibly empty) to log now for this progress entry."""
        st, now = self.state, self.clock()
        run = entry.get("run") or entry.get("sample") or "download"
        total, have = int(entry.get("total_bytes") or 0), int(entry.get("done_bytes") or 0)
        pct = (100.0 * have / total) if total else 0.0
        lines = []
        if not st.get("started"):
            st.update(started=True, t=now, pct=pct, retries=int(entry.get("retries") or 0), restarts=len(entry.get("restarts") or []), conn=entry.get("connections"),
                      state=entry.get("state"), retry_t=0.0)
            first = short_line(entry)
            if entry.get("resumed_bytes"):
                first += f" ({human_bytes(entry['resumed_bytes'])} already on disk from an earlier attempt)"
            return [first]
        state = entry.get("state")
        if state != st.get("state"):
            text = {"stalled": f"{run}: no bytes for a minute, still retrying", "verifying": f"{run}: all bytes received, checking the checksum",
                    "moving": f"{run}: checksum verified, moving the files into the data folder"}.get(state)
            if state == "downloading" and st.get("state") == "stalled":
                text = f"{run}: receiving data again"
            if text:
                lines.append(text)
            st["state"] = state
        restarts = entry.get("restarts") or []
        if len(restarts) > st.get("restarts", 0):
            lines.append(f"{run}: {restarts[-1]}")
            st["restarts"] = len(restarts)
        retries = int(entry.get("retries") or 0)
        if retries > st.get("retries", 0) and now - st.get("retry_t", 0.0) >= 60.0:
            lines.append(f"{run}: a connection problem, a chunk was retried ({retries} so far); nothing already downloaded is lost")
            st["retries"], st["retry_t"] = retries, now
        conn = entry.get("connections")
        if conn is not None and st.get("conn") is not None and conn < st["conn"]:
            lines.append(f"{run}: ENA asked for fewer connections: now {conn} (was {st['conn']})")
        if conn is not None:
            st["conn"] = conn
        if state == "downloading" and now - st.get("t", 0.0) >= self.interval and pct >= st.get("pct", 0.0) + self.step:
            lines.append(short_line(entry))
            st["t"], st["pct"] = now, pct
        return lines


# --- the state file --------------------------------------------------------------------------------------------------------------
def state_path(tmp):
    return tmp + ".state"


def save_state(tmp, state):
    path = state_path(tmp)
    scratch = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(scratch, "w", encoding="utf-8") as handle:
        json.dump(state, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(scratch, path)


def load_state(tmp):
    try:
        with open(state_path(tmp), encoding="utf-8") as handle:
            state = json.load(handle)
        if state.get("version") == 1 and isinstance(state.get("done"), list):
            return state
    except (OSError, ValueError, AttributeError):
        pass
    return None


def discard(tmp, why=""):
    """Delete the partial file and its state. The ONLY places that call this are a changed remote file, a state/size mismatch and a wrong final MD5."""
    for path in (tmp, state_path(tmp), tmp + ".aria2"):
        try:
            os.remove(path)
        except OSError:
            pass
    if why:
        log(f"discarded the partial download {os.path.basename(tmp)}: {why}")


# --- one HTTP request -----------------------------------------------------------------------------------------------------------
_CONTENT_RANGE = re.compile(r"^bytes\s+(\d+)-(\d+)/(\d+|\*)$")


def parse_retry_after(value):
    if not value:
        return 0.0
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
        return max(0.0, when.timestamp() - time.time())
    except (TypeError, ValueError):
        return 0.0


def open_range(url, start, end, timeout):
    """Open `url` for bytes start..end (end None = to the end). Raises Throttled / Fatal / OSError; returns the response."""
    request = urllib.request.Request(url, headers={"Range": f"bytes={start}-{'' if end is None else end}", "Accept-Encoding": "identity"})
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        code = exc.code
        if code in (429, 503, 403):
            # 403 is treated like a throttle, not as fatal: during testing ENA answered a plain ranged request with 403 Forbidden once and with 206 a few seconds later.
            raise Throttled(f"HTTP {code} from the server", parse_retry_after(exc.headers.get("Retry-After") if exc.headers else ""))
        if code == 416:
            raise RemoteChanged(f"the server says the requested range {start}-{end} is outside the file (HTTP 416): the file has changed")
        if code in (400, 401, 404, 410):
            raise Fatal(f"HTTP {code} {exc.reason} for {url}")
        raise OSError(f"HTTP {code} {exc.reason}")
    except ConnectionRefusedError as exc:
        raise Throttled(f"connection refused ({exc})", 0.0)


def check_response(response, start, end, total, want_status=206):
    """Validate one ranged response against what was asked; returns (etag, last_modified, total_from_header)."""
    status = getattr(response, "status", 200)
    if status == 200:
        raise RangeUnsupported("the server ignored the byte range (HTTP 200 instead of 206)")
    if status != want_status:
        raise OSError(f"unexpected HTTP status {status} for a range request")
    header = response.headers.get("Content-Range", "") if response.headers else ""
    match = _CONTENT_RANGE.match(header.strip())
    if not match:
        raise OSError(f"missing or unreadable Content-Range ({header!r})")
    got_start, got_end, got_total = int(match.group(1)), int(match.group(2)), match.group(3)
    if got_start != start or (end is not None and got_end != end):
        raise OSError(f"wrong Content-Range: asked for bytes {start}-{end}, the server answered {got_start}-{got_end}")
    if got_total != "*" and total and int(got_total) != int(total):
        raise RemoteChanged(f"the file size changed: the first answer said {total} bytes, now {got_total}")
    length = response.headers.get("Content-Length")
    if length and end is not None and int(length) != end - start + 1:
        raise OSError(f"wrong Content-Length {length} for bytes {start}-{end}")
    return response.headers.get("ETag") or "", response.headers.get("Last-Modified") or "", (int(got_total) if got_total != "*" else None)


def probe(url, timeout=60):
    """Ask for byte 0 only: (total, etag, last_modified), or raises RangeUnsupported when the server does not honour Range."""
    response = open_range(url, 0, 0, timeout)
    try:
        etag, modified, total = check_response(response, 0, 0, 0)
        response.read(1)
    finally:
        response.close()
    if not total:
        raise RangeUnsupported("the server does not report the file's total size")
    return total, etag, modified


# --- the chunked download --------------------------------------------------------------------------------------------------------
class Chunked:
    def __init__(self, url, tmp, total, budget, progress, name, cfg=None, partial=None, remote_total=None):
        self.url, self.tmp, self.total = url, tmp, total
        self.remote_total = remote_total or total      # the size of the file on the server (self.total is the part of it being fetched: all of it, or a prefix)
        self.budget, self.progress, self.name = budget, progress, name
        self.cfg = cfg or settings()
        self.chunk = self.cfg["chunk"]
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.error = None
        self.done = set()
        self.partial = partial if partial is not None else {}   # chunk -> bytes already written (kept across attempts of this process)
        self.etag = self.modified = ""
        self.changed = False

    def n_chunks(self):
        return -(-self.total // self.chunk)

    def bounds(self, index):
        start = index * self.chunk
        return start, min(start + self.chunk, self.total) - 1

    def _state(self):
        return {"version": 1, "url": self.url, "total": self.total, "remote_total": self.remote_total, "chunk": self.chunk, "etag": self.etag, "last_modified": self.modified,
                "done": sorted(self.done)}

    def prepare(self, probed):
        """Load or create the state; returns the number of bytes already finished."""
        tmp = self.tmp
        state = load_state(tmp)
        if state is None and not os.path.exists(tmp):
            self.partial.clear()
        total, etag, modified = probed
        have_file = os.path.exists(tmp)
        if state and not have_file:
            state = None                       # a state without its data file records nothing that exists
        if state and (state["url"] != self.url or int(state.get("remote_total", state["total"])) != self.remote_total):
            discard(tmp, "it belongs to a different URL or size than the one now requested")
            state, have_file = None, False
        if state and have_file and os.path.getsize(tmp) != int(state["total"]):
            discard(tmp, f"the partial file is {os.path.getsize(tmp)} bytes but the state records {state['total']}")
            state, have_file = None, False
        if state and int(state["total"]) != self.total:
            # A longer (or shorter) prefix of the same file is wanted than before: the whole chunks inside both lengths are still good, the old short last chunk is not.
            keep = min(int(state["total"]), self.total)
            state["done"] = [i for i in state["done"] if (int(i) + 1) * int(state["chunk"]) <= keep]
            state["total"] = self.total
        if state and ((state.get("etag") and etag and state["etag"] != etag) or (state.get("last_modified") and modified and state["last_modified"] != modified)):
            self.partial.clear()
            self.progress.reset(self.name, "the file on the server has changed since the partial download started (ETag or Last-Modified differ): starting this file again")
            discard(tmp, "the remote file changed")
            state, have_file = None, False
        if state is None and have_file:
            if os.path.exists(tmp + ".aria2"):
                discard(tmp, "it was started by aria2c, whose control file this downloader cannot read (set ENA_USE_ARIA2=1 to resume it with aria2c)")
                have_file = False
            else:
                size = os.path.getsize(tmp)
                if size > self.total:
                    discard(tmp, f"the partial file ({size} bytes) is larger than the file on the server ({self.total})")
                    have_file = False
        if state:
            self.chunk = int(state["chunk"])
            self.done = {int(i) for i in state["done"] if 0 <= int(i) < self.n_chunks()}
            self.etag, self.modified = state.get("etag", ""), state.get("last_modified", "")
        else:
            self.etag, self.modified = etag, modified
            if have_file:
                # No state: a file from a single-stream transfer (a contiguous prefix) or an old complete download waiting for its MD5. Whole chunks of the prefix count.
                size = os.path.getsize(tmp)
                self.done = set(range(self.n_chunks())) if size == self.total else set(range(size // self.chunk))
        mode = "r+b" if have_file else "wb"
        with open(tmp, mode) as handle:
            handle.truncate(self.total)
        save_state(tmp, self._state())
        return sum(self.bounds(i)[1] - self.bounds(i)[0] + 1 for i in self.done)

    def fetch_chunk(self, index):
        start, end = self.bounds(index)
        have = self.partial.get(index, 0)
        response = open_range(self.url, start + have, end, self.cfg["stall"])
        try:
            etag, modified, _ = check_response(response, start + have, end, self.remote_total)
            with self.lock:
                if (self.etag and etag and etag != self.etag) or (self.modified and modified and modified != self.modified):
                    raise RemoteChanged("the ETag or Last-Modified of the file changed during the download")
                if not self.etag and etag:
                    self.etag = etag
                if not self.modified and modified:
                    self.modified = modified
            remaining = end - (start + have) + 1
            with open(self.tmp, "r+b") as handle:
                handle.seek(start + have)
                while remaining > 0 and not self.stop.is_set():
                    block = response.read(min(BLOCK, remaining))
                    if not block:
                        break
                    handle.write(block)
                    remaining -= len(block)
                    self.partial[index] = self.partial.get(index, 0) + len(block)
                    self.progress.add(self.name, len(block))
                handle.flush()
                if remaining == 0:
                    os.fsync(handle.fileno())
            if self.stop.is_set() and remaining > 0:
                return False
            if remaining > 0:
                raise OSError(f"chunk {index} ended {remaining} bytes early")
        finally:
            response.close()
        return True

    def worker(self, queue, attempts):
        while not self.stop.is_set():
            with self.lock:
                if not queue:
                    return
                index = queue.popleft()
            wait = 0.0
            gained = False
            try:
                if not self.budget.acquire(self.name, self.cfg["per_file"], self.stop):
                    return
                try:
                    before = self.partial.get(index, 0)
                    try:
                        finished = self.fetch_chunk(index)
                    finally:
                        gained = self.partial.get(index, 0) > before
                finally:
                    self.budget.release(self.name)
                if not finished:
                    return
                with self.lock:
                    self.done.add(index)
                    self.partial.pop(index, None)
                    save_state(self.tmp, self._state())
                continue
            except RangeUnsupported as exc:
                self._fail(exc)
                return
            except RemoteChanged as exc:
                self.changed = True
                self._fail(exc)
                return
            except Fatal as exc:
                self._fail(exc)
                return
            except Throttled as exc:
                self.progress.retries += 1
                self.budget.reduce(str(exc))
                wait = min(self.cfg["retry_after_max"], max(exc.wait, self._backoff(attempts.get(index, 0) + 1)))
                log(f"{self.name}: the server asked for a pause ({exc}); waiting {wait:.0f} s, then retrying chunk {index + 1} of {self.n_chunks()}")
                attempts[index] = attempts.get(index, 0) + 1
            except (OSError, ValueError, http.client.HTTPException) as exc:
                self.progress.retries += 1
                attempts[index] = 0 if gained else attempts.get(index, 0) + 1
                if isinstance(exc, (socket.timeout, TimeoutError)) or "timed out" in str(exc):
                    exc = OSError(f"no bytes for {self.cfg['stall']:.0f} s (stalled connection abandoned)")
                wait = self._backoff(attempts[index])
                log(f"{self.name}: chunk {index + 1} of {self.n_chunks()} failed ({exc}); retry {attempts[index]} of {self.cfg['retries']} in {wait:.1f} s, "
                    f"{len(self.done)} chunks are safe on disk and kept")
            if attempts.get(index, 0) > self.cfg["retries"]:
                self._fail(DownloadError(f"chunk {index + 1} of {self.n_chunks()} of {self.name} failed {self.cfg['retries']} times in a row; "
                                         f"the {len(self.done)} finished chunks are kept and the next attempt resumes from them"))
                return
            with self.lock:
                queue.append(index)
            self.stop.wait(wait)

    def _backoff(self, attempt):
        base = self.cfg["backoff"]
        return min(self.cfg["backoff_max"], base * (2 ** max(0, attempt - 1))) * (0.5 + random.random()) if base else 0.0

    def _fail(self, exc):
        with self.lock:
            if self.error is None:
                self.error = exc
        self.stop.set()

    def run(self, probed):
        """Fetch every missing chunk. Returns True when the file is complete; raises on RangeUnsupported / RemoteChanged / DownloadError."""
        already = self.prepare(probed)
        if already:
            self.progress.add_file(self.name, self.total, already)
            log(f"{self.name}: {len(self.done)} of {self.n_chunks()} chunks ({human_bytes(already)}) were already on disk from an earlier attempt; fetching the rest")
        else:
            self.progress.add_file(self.name, self.total, 0)
        queue = deque(i for i in range(self.n_chunks()) if i not in self.done)
        attempts = {}
        try:
            n_workers = min(len(queue), self.budget.hard)
            threads = [threading.Thread(target=self.worker, args=(queue, attempts), daemon=True) for _ in range(n_workers)]
            for t in threads:
                t.start()
            for t in threads:
                while t.is_alive():
                    t.join(0.5)
        finally:
            pass
        if self.error is not None:
            raise self.error
        if len(self.done) != self.n_chunks():
            raise DownloadError(f"{self.name}: {self.n_chunks() - len(self.done)} chunks missing after the transfer")
        return True


def single_stream(url, tmp, total, progress, name, cfg=None, retries=5, limit=None):
    """One connection; resumes from the bytes already in `tmp` (HTTP Range) and starts again from zero only when the server cannot continue."""
    cfg = cfg or settings()
    delay = cfg["backoff"]
    first = True
    for attempt in range(1, retries + 1):
        try:
            have = os.path.getsize(tmp) if os.path.exists(tmp) else 0
            if total and have > total:
                os.remove(tmp)
                have = 0
            if total and have == total:
                if first:
                    progress.add_file(name, total, have)
                return
            if first:
                progress.add_file(name, total or 0, have)
                first = False
            mode = "ab"
            if have:
                response = None
                try:
                    response = open_range(url, have, None, cfg["stall"])
                    check_response(response, have, None, total)
                except RangeUnsupported:
                    if response is not None:
                        response.close()
                    progress.reset(name, "the server cannot resume a partial file: starting this file again from zero")
                    have, mode = 0, "wb"
                    response = urllib.request.urlopen(urllib.request.Request(url), timeout=cfg["stall"])
            else:
                response = urllib.request.urlopen(urllib.request.Request(url), timeout=cfg["stall"])
                mode = "wb"
            with response, open(tmp, mode) as handle:
                written = have if mode == "ab" else 0
                for block in iter(lambda: response.read(BLOCK), b""):
                    if limit is not None and written + len(block) > limit:
                        block = block[:limit - written]
                    handle.write(block)
                    written += len(block)
                    progress.add(name, len(block))
                    if limit is not None and written >= limit:
                        break
            size = os.path.getsize(tmp)
            if total and size < total:
                raise OSError(f"transfer ended early ({size} of {total} bytes); will resume")
            return
        except Fatal:
            raise
        except (OSError, ValueError, http.client.HTTPException) as exc:
            if attempt == retries:
                raise
            progress.retries += 1
            log(f"{name}: {exc}; retry {attempt} of {retries - 1} (the {os.path.getsize(tmp) if os.path.exists(tmp) else 0} bytes already on disk are kept)")
            time.sleep(delay * attempt)


# --- aria2c (opt-in) -------------------------------------------------------------------------------------------------------------
def aria2_available():
    return os.environ.get("ENA_USE_ARIA2", "0") == "1" and bool(shutil.which("aria2c"))


def aria2_fetch(url, tmp, total, connections, progress, name, timeout=None):
    """Fetch with aria2c (ENA_USE_ARIA2=1): resumable (--continue and its control file are kept), re-run on a non-zero exit, never deletes the partial file.
    Its progress is read from the control file (python/download_progress.py aria2_progress), which counts finished pieces only."""
    import download_progress as dp
    connections = max(1, min(16, connections))
    command = ["aria2c", f"--max-connection-per-server={connections}", f"--split={connections}", "--min-split-size=1M", "--continue=true", "--file-allocation=none",
               "--max-tries=10", "--retry-wait=5", "--timeout=60", "--connect-timeout=30", "--allow-overwrite=true", "--auto-file-renaming=false", "--quiet=true",
               "--dir", os.path.dirname(os.path.abspath(tmp)), "--out", os.path.basename(tmp), url]
    progress.add_file(name, total, 0)
    stop = threading.Event()

    def watch():
        last = 0
        while not stop.wait(2.0):
            got = dp.aria2_progress(tmp + ".aria2")
            done = got[0] if got else (os.path.getsize(tmp) if os.path.exists(tmp) and os.path.getsize(tmp) < total else 0)
            if done > last:
                progress.add(name, done - last)
                last = done

    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    try:
        for attempt in range(1, 4):
            code = subprocess.run(command, check=False, timeout=timeout).returncode
            if code == 0 and os.path.exists(tmp) and os.path.getsize(tmp) == total and not os.path.exists(tmp + ".aria2"):
                with progress.lock:
                    gap = total - progress.files[name]["have"]
                if gap > 0:
                    progress.add(name, gap)
                return True
            log(f"{name}: aria2c exited with {code}; run {attempt} of 3 (its partial file and control file are kept, the next run resumes)")
        return False
    finally:
        stop.set()


# --- whole-file download ---------------------------------------------------------------------------------------------------------
def md5_of(path, block=4 << 20):
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(block), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(url, tmp, expected_md5, expected_bytes, budget, progress, name, min_bytes=16 << 20, attempts=5, retry_delay=15.0, prefix_bytes=0):
    """Download url to `tmp` (a `.part` path), verify the MD5, return. With `prefix_bytes` only the first that many bytes are fetched (the read-depth cap, python/depth_cap.py): a prefix has
    no whole-file MD5, so none is checked and the caller validates what it makes from it. The partial file and its state stay on disk on failure; the caller moves tmp to its final name."""
    cfg = settings()
    total = int(expected_bytes) if expected_bytes else None
    state = load_state(tmp)
    if not prefix_bytes and state and state.get("verified_md5") == expected_md5 and os.path.exists(tmp) and os.path.getsize(tmp) == int(state["total"]):
        progress.add_file(name, int(state["total"]), int(state["total"]))
        log(f"{name}: the file was already downloaded and verified (md5 {expected_md5}); only moving it is left")
        return
    budget.register(name)
    try:
        return _fetch(url, tmp, expected_md5, total, cfg, budget, progress, name, min_bytes, attempts, retry_delay, int(prefix_bytes or 0))
    finally:
        budget.unregister(name)


def _fetch(url, tmp, expected_md5, total, cfg, budget, progress, name, min_bytes, attempts, retry_delay, prefix=0):
    refetched = False
    force_single = False
    partial_store = {}
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            budget.register(name)
            probed = None
            ranged = False
            if not force_single and (prefix or total is None or total >= min_bytes):
                try:
                    if not budget.acquire(name):
                        raise OSError("connection budget unavailable")
                    try:
                        probed = probe(url, timeout=cfg["stall"] + 15)
                    finally:
                        budget.release(name)
                    ranged = True
                except RangeUnsupported as exc:
                    log(f"{name}: {exc}; using one stream")
            if ranged and total and probed[0] != total:
                raise OSError(f"the server reports {probed[0]} bytes for {url} but ENA's file report says {total}")
            if ranged:
                grand = prefix or probed[0]
                done = False
                if aria2_available() and not prefix:
                    if aria2_fetch(url, tmp, grand, cfg["per_file"] or budget.share(), progress, name):
                        done = True
                if not done:
                    Chunked(url, tmp, grand, budget, progress, name, cfg, partial_store, remote_total=probed[0]).run(probed)
            else:
                # A partial file from a chunked transfer cannot be continued as one stream (its state says which chunks are real): drop that state only.
                if load_state(tmp) is not None:
                    discard(tmp, "the chunked partial file cannot be used for a single-stream transfer")
                single_stream(url, tmp, prefix or total, progress, name, cfg, limit=prefix or None)
            budget.unregister(name)          # checking the file uses no connection: the other file may have the whole budget
            if prefix:
                size = os.path.getsize(tmp)
                if size != prefix:
                    raise OSError(f"{name}: the prefix on disk is {size} bytes, expected {prefix}")
                progress.set_state(name, "done")
                return
            progress.set_state(name, "verifying")
            size = os.path.getsize(tmp)
            if total and size != total:
                raise OSError(f"{name}: the file on disk is {size} bytes, expected {total}")
            got = md5_of(tmp)
            if got != expected_md5:
                log(f"{name}: MD5 MISMATCH for the whole file (got {got}, ENA publishes {expected_md5}). ENA publishes only a whole-file checksum, so "
                    f"no individual chunk can be blamed. {'Discarding the file and fetching it again once, in the same parallel way.' if not refetched else 'This is the second time: giving up.'}")
                discard(tmp)
                if refetched:
                    raise ValueError(f"MD5 mismatch for {url}: {got} != {expected_md5} (after fetching the file twice)")
                refetched = True
                partial_store.clear()
                progress.reset(name, "the checksum did not match: the file is fetched again")
                continue
            state = load_state(tmp) or {"version": 1, "done": [], "total": size}
            state["verified_md5"] = expected_md5
            state["total"] = size
            save_state(tmp, state)
            return
        except RemoteChanged as exc:
            partial_store.clear()
            progress.reset(name, f"the file on the server changed ({exc}): starting it again from zero")
            discard(tmp, str(exc))
            last_error = exc
        except RangeUnsupported as exc:
            # The server stopped honouring Range part way: the chunked state is no use for one stream, so it is dropped and the file is read as one stream.
            partial_store.clear()
            force_single = True
            progress.reset(name, f"{exc}: reading this file as one stream")
            discard(tmp, "the server does not honour byte ranges")
            last_error = exc
        except Fatal as exc:
            raise
        except ValueError:
            raise
        except (OSError, DownloadError, http.client.HTTPException) as exc:
            last_error = exc
            if attempt == attempts:
                break
            log(f"{name}: attempt {attempt} of {attempts} failed: {exc}; the partial download is kept and the next attempt resumes from it")
            time.sleep(retry_delay * attempt)
    raise last_error or DownloadError(f"{name}: download failed")
