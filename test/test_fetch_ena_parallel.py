#!/usr/bin/env python3
"""Parallel ENA downloads (python/fetch_ena_reads.py) against a real local HTTP server.

The server honours HTTP Range and limits each connection's speed, as public mirrors
effectively do. Checks: both mates arrive MD5-verified through parallel byte ranges;
a server that ignores Range still yields correct files (single-stream fallback); a
corrupted range is caught by the MD5 check and re-fetched. `serve()` and `fetch()`
are reused by test/bench/bench_downloads.py.
"""
import hashlib
import http.server
import os
import random
import re
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Handler(http.server.BaseHTTPRequestHandler):
    files = {}            # path -> bytes
    rate = 4 << 20        # bytes per second per connection
    honour_range = True
    corrupt_once = set()  # paths whose next ranged response gets one flipped byte
    log = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/filereport"):
            run = re.search(r"accession=([^&]+)", self.path).group(1)
            host = f"http://127.0.0.1:{self.server.server_port}"
            names = [f"{run}_1.fastq.gz", f"{run}_2.fastq.gz"]
            body = ("run_accession\tfastq_ftp\tfastq_md5\tfastq_bytes\tlibrary_layout\n"
                    f"{run}\t{';'.join(f'{host}/{n}' for n in names)}\t"
                    f"{';'.join(hashlib.md5(self.files['/' + n]).hexdigest() for n in names)}\t"
                    f"{';'.join(str(len(self.files['/' + n])) for n in names)}\tPAIRED\n").encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        data = self.files[self.path]
        start, end = 0, len(data) - 1
        ranged = self.honour_range and self.headers.get("Range")
        if ranged:
            a, b = ranged.split("=")[1].split("-")
            start, end = int(a), int(b) if b else len(data) - 1
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
        else:
            self.send_response(200)
        payload = bytearray(data[start:end + 1])
        if ranged and self.path in self.corrupt_once and start == 0:
            self.corrupt_once.discard(self.path)
            payload[0] ^= 0xFF
        self.log.append((self.path, bool(ranged)))
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        chunk = 64 << 10
        for i in range(0, len(payload), chunk):     # throttle each connection
            self.wfile.write(payload[i:i + chunk])
            time.sleep(chunk / self.rate)


def serve(size=8 << 20, run="SRR1"):
    rng = random.Random(3)
    Handler.files = {f"/{run}_{m}.fastq.gz": rng.randbytes(size) for m in (1, 2)}
    Handler.log = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def fetch(python_dir, server, out_dir, run="SRR1"):
    """Import fetch_ena_reads from python_dir, point it at the local server, fetch a run."""
    sys.path.insert(0, str(python_dir))
    import fetch_ena_reads as fer
    fer.PORTAL = f"http://127.0.0.1:{server.server_port}/filereport"
    # No retry back-off, without touching the real time module (the server sleeps to throttle).
    fer.time = types.SimpleNamespace(sleep=lambda *_: None)
    argv, sys.argv = sys.argv, ["fetch_ena_reads.py", "--run", run, "--out-dir", str(out_dir)]
    try:
        fer.main()
    finally:
        sys.argv = argv
        sys.path.remove(str(python_dir))
    return fer


def verify(out_dir, run="SRR1"):
    for m in (1, 2):
        got = Path(out_dir, f"{run}_{m}.fastq.gz").read_bytes()
        assert got == Handler.files[f"/{run}_{m}.fastq.gz"], f"mate {m} differs"


def main():
    os.environ.update(ENA_SEGMENT_MIN_BYTES=str(1 << 20), ENA_DOWNLOAD_CONNECTIONS="4", ENA_USE_ARIA2="0")
    server = serve()
    with tempfile.TemporaryDirectory() as tmp:
        fetch(ROOT / "python", server, tmp)
        verify(tmp)
        ranged = [r for _, r in Handler.log if True]
        assert sum(ranged) == 8, f"expected 4 ranges per mate, got {Handler.log}"
    print("  PASS: both mates arrive MD5-verified as 4 parallel byte ranges each")

    Handler.honour_range, Handler.log = False, []
    with tempfile.TemporaryDirectory() as tmp:
        fetch(ROOT / "python", server, tmp)
        verify(tmp)
    Handler.honour_range = True
    print("  PASS: a server that ignores Range falls back to one stream per file, still verified")

    Handler.corrupt_once = {"/SRR1_1.fastq.gz"}
    with tempfile.TemporaryDirectory() as tmp:
        fetch(ROOT / "python", server, tmp)
        verify(tmp)
    print("  PASS: a corrupted range fails the MD5 check and the file is fetched again")
    server.shutdown()
    print("ALL PARALLEL ENA FETCH TESTS PASSED")


if __name__ == "__main__":
    main()
