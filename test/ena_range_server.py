#!/usr/bin/env python3
"""A fake ENA for the downloader tests: threaded, honours HTTP Range, counts what it serves and injects faults on demand.

    server = FakeENA(); server.add_file("/f/x.fastq.gz", Content(8 << 20, seed=1)); server.start()
    server.faults.append({"kind": "reset", "start": 0, "times": 1})     # cut the connection of the chunk that starts at byte 0, once
    server.url("/f/x.fastq.gz"); server.stats()  -> requests, ranged_bytes, bytes_sent, max_active

Fault kinds (dict keys: kind, times (default 1), start (the first byte of the requested range), last (True = only the range that ends at the end of the file), path,
after (bytes sent before the fault acts, default 0), seconds (stall length), retry_after):
  reset            send `after` bytes, then close the connection hard
  stall            send `after` bytes, then send nothing for `seconds`
  http429 / http503 / http403   answer with that status and a Retry-After header (`retry_after`, seconds)
  ignore_range     answer 200 with the whole file
  bad_range        answer 206 with a Content-Range that is not the one asked for
  short            declare the right length, send `after` bytes less and close
  change_etag      from now on the file has a new ETag (and the answer carries it)
  change_size      from now on the file is one byte longer
  corrupt          flip one byte of what is sent (the file's MD5 then differs from the one published)

`Content` is a deterministic, mostly sparse byte stream (a few random bytes per MiB, the rest zeros), generated on the fly, so a file of hundreds of MiB costs the server no memory.
Standard library only.
"""
import hashlib
import http.server
import random
import re
import threading
import time
import urllib.parse

NL_ = chr(10)


class Content:
    """size bytes, deterministic from seed; read(start, end) returns bytes without holding the file in memory."""

    def __init__(self, size, seed=1, dense=False):
        self.size, self.seed, self.dense = size, seed, dense
        self.version = 0
        self._md5 = None

    def block(self, index):
        rng = random.Random(self.seed * 1_000_003 + index)
        if self.dense:
            return rng.randbytes(1 << 20)
        data = bytearray(1 << 20)
        for _ in range(16):
            data[rng.randrange(1 << 20)] = rng.randrange(1, 256)
        return bytes(data)

    def read(self, start, end):
        out = bytearray()
        for index in range(start >> 20, (end >> 20) + 1):
            blk = self.block(index)
            lo = max(start, index << 20) - (index << 20)
            hi = min(end, ((index + 1) << 20) - 1) - (index << 20)
            out += blk[lo:hi + 1]
        return bytes(out)

    def md5(self):
        if self._md5 is None:
            digest = hashlib.md5()
            for start in range(0, self.size, 4 << 20):
                digest.update(self.read(start, min(self.size, start + (4 << 20)) - 1))
            self._md5 = digest.hexdigest()
        return self._md5


class BytesContent:
    """A file held in memory (the gzip FASTQ of a capped-download test); same interface as Content."""

    def __init__(self, data):
        self.data, self.size, self._md5 = data, len(data), hashlib.md5(data).hexdigest()

    def read(self, start, end):
        return self.data[start:end + 1]

    def md5(self):
        return self._md5


def fastq_gz(run, mate, pairs, read_len=100, seed=1):
    """Deterministic gzip FASTQ: `pairs` records named <run>.<n>/<mate>, random bases, so the compressed size grows with the read count."""
    import gzip
    import io
    rng = random.Random(seed * 7919 + mate)
    out = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=out, compresslevel=6, mtime=0) as handle:
        for n in range(1, pairs + 1):
            seq = "".join(rng.choice("ACGT") for _ in range(read_len))
            qual = "".join(rng.choice("<>?@ABCDEFGHI") for _ in range(read_len))
            handle.write(f"@{run}.{n}/{mate}{NL_}{seq}{NL_}+{NL_}{qual}{NL_}".encode())
    return out.getvalue()


class FakeENA:
    def __init__(self, rate=None):
        self.files = {}
        self.etags = {}
        self.sizes = {}
        self.runs = {}
        self.meta = {}
        self.faults = []
        self.honour_range = True
        self.rate = rate                       # bytes per second per connection (None = unlimited)
        self.lock = threading.Lock()
        self.log = []                          # (path, start, end, status)
        self.ranged_bytes = 0
        self.bytes_sent = 0
        self.active = 0
        self.max_active = 0
        self.nth = {}
        self.server = None

    def add_file(self, path, content):
        self.files[path] = content
        self.etags[path] = f'"{hashlib.md5(path.encode()).hexdigest()[:12]}-0"'
        self.sizes[path] = content.size

    def add_run(self, run, size=2 << 20, seed=1, layout="PAIRED", md5_wrong=False):
        """Register run_1/run_2 files and make the portal file report describe them."""
        paths = []
        for mate in (1, 2):
            path = f"/f/{run}_{mate}.fastq.gz"
            self.add_file(path, Content(size, seed + mate))
            paths.append(path)
        self.runs[run] = (paths, md5_wrong, layout)
        return paths

    def add_fastq_run(self, run, pairs, read_len=100, seed=1, platform="ILLUMINA", layout="PAIRED"):
        """A real paired gzip FASTQ run (for the read-depth cap); the file report carries read_count, base_count and instrument_platform."""
        paths = []
        for mate in (1, 2):
            path = f"/f/{run}_{mate}.fastq.gz"
            self.add_file(path, BytesContent(fastq_gz(run, mate, pairs, read_len, seed)))
            paths.append(path)
        self.runs[run] = (paths, False, layout)
        self.meta[run] = {"read_count": pairs, "base_count": pairs * read_len * 2, "instrument_platform": platform}
        return paths

    def start(self):
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):  # noqa: N802
                outer.handle(self)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()

    @property
    def port(self):
        return self.server.server_address[1]

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def portal(self):
        return f"http://127.0.0.1:{self.port}/filereport"

    def stats(self):
        with self.lock:
            return {"requests": list(self.log), "ranged_bytes": self.ranged_bytes, "bytes_sent": self.bytes_sent, "max_active": self.max_active}

    def reset_stats(self):
        with self.lock:
            self.log, self.ranged_bytes, self.bytes_sent, self.max_active = [], 0, 0, 0

    # -- request handling -----------------------------------------------------------------------------------------------------------
    def pick_fault(self, path, start, end):
        with self.lock:
            size = self.sizes.get(path, 0)
            for fault in self.faults:
                if fault.get("times", 1) <= 0:
                    continue
                if fault.get("path") and fault["path"] != path:
                    continue
                if fault.get("start") is not None and fault["start"] != start:
                    continue
                if fault.get("last") and end != size - 1:
                    continue
                fault["times"] = fault.get("times", 1) - 1
                return fault
        return None

    def handle(self, h):
        parsed = urllib.parse.urlparse(h.path)
        if parsed.path.endswith("/filereport"):
            return self.report(h, parsed)
        path = parsed.path
        if path not in self.files:
            h.send_response(404)
            h.send_header("Content-Length", "0")
            h.end_headers()
            return
        content = self.files[path]
        size = self.sizes[path]
        rng = h.headers.get("Range")
        start, end, ranged = 0, size - 1, False
        if rng and self.honour_range:
            m = re.match(r"bytes=(\d+)-(\d*)", rng)
            start, end, ranged = int(m.group(1)), (int(m.group(2)) if m.group(2) else size - 1), True
            end = min(end, size - 1)
        fault = self.pick_fault(path, start, end) if ranged or rng else None
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            self.respond(h, path, content, size, start, end, ranged, fault)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            with self.lock:
                self.active -= 1

    def respond(self, h, path, content, size, start, end, ranged, fault):
        kind = fault["kind"] if fault else ""
        if kind in ("http429", "http503", "http403"):
            h.send_response(int(kind[4:]))
            h.send_header("Retry-After", str(fault.get("retry_after", 1)))
            h.send_header("Content-Length", "0")
            h.end_headers()
            self._log(path, start, end, int(kind[4:]), 0)
            return
        if kind == "change_etag":
            self.etags[path] = '"changed-%d"' % time.time_ns()
        if kind == "change_size":
            self.sizes[path] = size + 1
            content.size = size + 1
            size = size + 1
            if not ranged:
                end = size - 1
        if kind == "ignore_range":
            ranged, start, end = False, 0, size - 1
        length = end - start + 1
        h.send_response(206 if ranged else 200)
        h.send_header("ETag", self.etags[path])
        h.send_header("Accept-Ranges", "bytes")
        if ranged:
            if kind == "bad_range":
                h.send_header("Content-Range", f"bytes {start + 1}-{end + 1}/{size}")
            else:
                h.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        h.send_header("Content-Length", str(length))
        h.end_headers()
        self._log(path, start, end, 206 if ranged else 200, length if ranged else 0)
        limit = length
        after = fault.get("after", 0) if fault else 0
        if kind == "short":
            limit = max(0, length - fault.get("after", 1))
        sent = 0
        piece = 64 << 10
        pos = start
        while sent < limit:
            if kind in ("reset", "stall") and sent >= after:
                if kind == "reset":
                    try:
                        h.connection.shutdown(2)
                    except OSError:
                        pass
                    h.close_connection = True
                    return
                time.sleep(fault.get("seconds", 5))
                h.close_connection = True
                return
            n = min(piece, limit - sent, (after - sent) if kind in ("reset", "stall") and after > sent else piece)
            data = content.read(pos, pos + n - 1)
            if kind == "corrupt" and sent == 0:
                data = bytes([data[0] ^ 0xFF]) + data[1:]
            h.wfile.write(data)
            with self.lock:
                self.bytes_sent += n
            sent += n
            pos += n
            if self.rate and sent < limit:
                time.sleep(n / self.rate)
        if kind == "short":
            h.close_connection = True

    def _log(self, path, start, end, status, ranged_len):
        with self.lock:
            self.log.append((path, start, end, status))
            self.ranged_bytes += ranged_len

    def report(self, h, parsed):
        run = urllib.parse.parse_qs(parsed.query).get("accession", [""])[0]
        host = f"127.0.0.1:{self.port}"
        if run not in self.runs:
            body = "run_accession\tfastq_ftp\tfastq_md5\tfastq_bytes\tlibrary_layout\n"
        else:
            paths, wrong, layout = self.runs[run]
            md5s = [self.files[p].md5() if not (wrong and i == 0) else "0" * 32 for i, p in enumerate(paths)]
            meta = self.meta.get(run, {})
            body = ("run_accession\tfastq_ftp\tfastq_md5\tfastq_bytes\tlibrary_layout\tread_count\tbase_count\tinstrument_platform\n"
                    f"{run}\t{';'.join('http://' + host + p for p in paths)}\t{';'.join(md5s)}\t{';'.join(str(self.sizes[p]) for p in paths)}\t{layout}\t"
                    f"{meta.get('read_count', '')}\t{meta.get('base_count', '')}\t{meta.get('instrument_platform', '')}\n")
        data = body.encode()
        h.send_response(200)
        h.send_header("Content-Length", str(len(data)))
        h.end_headers()
        h.wfile.write(data)
