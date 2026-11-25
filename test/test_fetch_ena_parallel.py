#!/usr/bin/env python3
"""Parallel ENA downloads through python/fetch_ena_reads.py (the whole command) against the fake ENA (test/ena_range_server.py).

Both mates arrive MD5-verified through ranged chunks; a server that ignores Range still yields correct files (single stream); a corrupted chunk is caught by the whole-file MD5 and the
file is fetched again. (Rewritten with the chunked downloader: the old version drove the removed all-or-nothing segment code. The fault-injection cases are in test_ena_download.py.)
`serve()`, `fetch()` and `verify()` are reused by test/bench/bench_downloads.py.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "test"))
from ena_range_server import FakeENA  # noqa: E402

MIB = 1 << 20


def serve(size=8 * MIB, run="SRR1", rate=None):
    server = FakeENA(rate=rate)
    server.add_run(run, size=size)
    return server.start()


def fetch(python_dir, server, out_dir, run="SRR1", extra_env=None):
    env = dict(os.environ, ENA_PORTAL_URL=server.portal(), ENA_SEGMENT_MIN_BYTES=str(MIB), ENA_CHUNK_MIB="1", ENA_USE_ARIA2="0", ENA_CHUNK_BACKOFF_SECONDS="0",
               ENA_RETRY_DELAY_SECONDS="0", DOWNLOAD_TMP_DIR="data", **(extra_env or {}))
    r = subprocess.run([sys.executable, "-I", str(Path(python_dir) / "fetch_ena_reads.py"), "--run", run, "--out-dir", str(out_dir)], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]
    return r


def verify(server, out_dir, run="SRR1"):
    for m in (1, 2):
        path = f"/f/{run}_{m}.fastq.gz"
        got = Path(out_dir, f"{run}_{m}.fastq.gz")
        assert got.stat().st_size == server.files[path].size, f"mate {m} has the wrong size"
        import hashlib
        assert hashlib.md5(got.read_bytes()).hexdigest() == server.files[path].md5(), f"mate {m} differs"


def main():
    server = serve()
    with tempfile.TemporaryDirectory() as tmp:
        fetch(ROOT / "python", server, tmp)
        verify(server, tmp)
        st = server.stats()
        assert all(r[3] == 206 for r in st["requests"]) and len({r[1] for r in st["requests"]}) > 2, st["requests"]
        assert st["max_active"] > 2, st["max_active"]
    print("  PASS: both mates arrive MD5-verified as ranged chunks over several connections")
    server.honour_range = False
    server.reset_stats()
    with tempfile.TemporaryDirectory() as tmp:
        fetch(ROOT / "python", server, tmp)
        verify(server, tmp)
    server.honour_range = True
    print("  PASS: a server that ignores Range gives one stream per file, still verified")
    server.faults.append({"kind": "corrupt", "start": MIB, "times": 1})
    with tempfile.TemporaryDirectory() as tmp:
        fetch(ROOT / "python", server, tmp)
        verify(server, tmp)
    print("  PASS: a corrupted chunk fails the MD5 check and the file is fetched again")
    server.stop()
    print("ALL PARALLEL ENA FETCH TESTS PASSED")


if __name__ == "__main__":
    main()
