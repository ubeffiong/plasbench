#!/usr/bin/env python3
"""OPT-IN real-network test (PLASBENCH_NET_TESTS=1): the chunked downloader against real ENA, with an 8 MiB prefix of a public FASTQ file.

Fetches the first 8 MiB of the first mate of a public run (default SRR36114699; PLASBENCH_NET_RUN overrides) in 1 MiB chunks over several connections, with ONE simulated mid-chunk
connection drop (the first response of one chunk is cut after 300 kB), then checks: the prefix has the size asked for, starts with the gzip magic, decodes into whole FASTQ records
(python/depth_cap.py cut_prefix), the drop was retried inside the chunk, and a second call fetches nothing (resume from the state file). Without PLASBENCH_NET_TESTS=1 it prints
"n/a" and exits 0: the regular suite never touches the internet. Total traffic about 8 MiB.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

MIB = 1 << 20


def main():
    if os.environ.get("PLASBENCH_NET_TESTS") != "1":
        print("  n/a: set PLASBENCH_NET_TESTS=1 to run the real-network ENA test (about 8 MiB)")
        print("ALL ENA REAL NETWORK TESTS PASSED (n/a)")
        return
    os.environ.update(ENA_CHUNK_MIB="1", ENA_CHUNK_BACKOFF_SECONDS="0.2", ENA_STALL_SECONDS="30")
    import depth_cap
    import ena_download as ed
    import fetch_ena_reads as fer
    run = os.environ.get("PLASBENCH_NET_RUN", "SRR36114699")
    report = fer.file_report(run)
    url = [u for u in report["fastq_ftp"].split(";") if u.endswith("_1.fastq.gz")][0]
    url = "https://" + url if not url.startswith("http") else url
    size = int(report["fastq_bytes"].split(";")[0])
    md5 = report["fastq_md5"].split(";")[0]
    print(f"  using {url} ({size} bytes); fetching a {8} MiB prefix")

    real_open, dropped = ed.open_range, []

    class Cut:
        """A real response that fails with a connection reset after 300 kB, once."""

        def __init__(self, response):
            self.response, self.seen = response, 0
            self.headers, self.status = response.headers, response.status

        def read(self, n=-1):
            if self.seen >= 300_000:
                raise ConnectionResetError("simulated mid-chunk drop")
            block = self.response.read(n)
            self.seen += len(block)
            return block

        def close(self):
            self.response.close()

    def flaky(u, start, end, timeout):
        response = real_open(u, start, end, timeout)
        if start == 2 * MIB and not dropped:
            dropped.append(start)
            return Cut(response)
        return response

    ok = True
    ed.open_range = flaky
    try:
        with tempfile.TemporaryDirectory() as tmp:
            part = os.path.join(tmp, "x.fastq.gz.prefix.part")
            progress = ed.Progress("NET")
            ed.fetch(url, part, md5, size, ed.Budget(limit=4), progress, "x", attempts=3, retry_delay=1, prefix_bytes=8 * MIB)
            data = Path(part).read_bytes()
            checks = [("the prefix has exactly the 8 MiB asked for", len(data) == 8 * MIB), ("it starts with the gzip magic", data[:2] == b"\x1f\x8b"),
                      ("the simulated mid-chunk drop happened and was retried inside the chunk", bool(dropped) and progress.retries >= 1)]
            out = os.path.join(tmp, "cut.gz")
            info = depth_cap.cut_prefix(part, out, 2000)
            checks.append(("the prefix decodes into whole, valid FASTQ records (2000 kept)", info["records"] == 2000))
            ed.open_range = real_open
            before = progress.received
            ed.fetch(url, part, md5, size, ed.Budget(limit=4), progress, "x", attempts=1, retry_delay=0, prefix_bytes=8 * MIB)
            checks.append(("a second call resumes from the state file and fetches no data", progress.received == before and len(Path(part).read_bytes()) == 8 * MIB))
            for label, good in checks:
                print(f"  {'PASS' if good else 'FAIL'}: {label}")
                ok &= good
    finally:
        ed.open_range = real_open
    print("ALL ENA REAL NETWORK TESTS PASSED" if ok else "SOME ENA REAL NETWORK TESTS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
