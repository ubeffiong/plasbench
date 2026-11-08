#!/usr/bin/env python3
"""ENA fallback for short reads (python/fetch_ena_reads.py), offline: the portal
report and the FASTQ downloads are served from memory. A paired run is written
under <run>_1/_2.fastq.gz with a provenance file; an MD5 mismatch fails and
leaves no file under the final name; a single-end run is refused."""
import hashlib
import io
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import fetch_ena_reads as fer  # noqa: E402

R1, R2 = b"@r1\nACGT\n+\nIIII\n" * 10, b"@r1\nTGCA\n+\nIIII\n" * 10


class Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def server(layout="PAIRED", md5_1=None):
    m1, m2 = md5_1 or hashlib.md5(R1).hexdigest(), hashlib.md5(R2).hexdigest()
    shown = "PAIRED" if layout == "FLAKY" else layout
    report = ("run_accession\tfastq_ftp\tfastq_md5\tfastq_bytes\tlibrary_layout\n"
              f"SRR1\tftp.sra.ebi.ac.uk/x/SRR1_1.fastq.gz;ftp.sra.ebi.ac.uk/x/SRR1_2.fastq.gz\t{m1};{m2}\t"
              f"{len(R1)};{len(R2)}\t{shown}\n")

    calls = {"r1": 0}

    def urlopen(url, timeout=None):
        url = getattr(url, "full_url", url)
        if "filereport" in url:
            return Response(report.encode())
        return Response(R1 if url.endswith("_1.fastq.gz") else R2)

    def flaky(request, timeout=None):
        """Read 1 is cut off half way the first time, then served from the Range offset."""
        url = getattr(request, "full_url", request)
        if url.endswith("_1.fastq.gz"):
            calls["r1"] += 1
            if calls["r1"] == 1:
                return Response(R1[: len(R1) // 2])
            start = int(request.get_header("Range").split("=")[1].rstrip("-"))
            response = Response(R1[start:])
            response.status = 206
            return response
        return urlopen(request, timeout)
    return flaky if layout == "FLAKY" else urlopen


def run(tmp, urlopen):
    with mock.patch.object(fer.urllib.request, "urlopen", urlopen), mock.patch.object(fer.time, "sleep"), \
            mock.patch.object(sys, "argv", ["fetch_ena_reads.py", "--run", "SRR1", "--out-dir", str(tmp)]):
        fer.main()


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        run(tmp, server())
        assert (tmp / "SRR1_1.fastq.gz").read_bytes() == R1 and (tmp / "SRR1_2.fastq.gz").read_bytes() == R2
        prov = json.loads((tmp / "SRR1.ena_provenance.json").read_text())
        assert prov["source"] == "ENA" and len(prov["files"]) == 2
        print("  PASS: paired run downloaded, MD5-verified, provenance written")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        run(tmp, server(layout="FLAKY"))
        assert (tmp / "SRR1_1.fastq.gz").read_bytes() == R1
        print("  PASS: a transfer cut off half way resumes from the partial file (HTTP Range) and verifies")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        try:
            run(tmp, server(md5_1="0" * 32))
            raise AssertionError("MD5 mismatch accepted")
        except ValueError as exc:
            assert "MD5 mismatch" in str(exc)
        assert not (tmp / "SRR1_1.fastq.gz").exists() and not list(tmp.glob("*.part"))
        print("  PASS: an MD5 mismatch fails after retries and leaves no file under the final name")
    with tempfile.TemporaryDirectory() as tmp:
        try:
            run(Path(tmp), server(layout="SINGLE"))
            raise AssertionError("single-end run accepted")
        except SystemExit as exc:
            assert "not a paired run" in str(exc)
        print("  PASS: a single-end run is refused")
    print("ALL ENA FETCH TESTS PASSED")


if __name__ == "__main__":
    main()
