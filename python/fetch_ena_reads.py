#!/usr/bin/env python3
"""
fetch_ena_reads.py -- download a paired-end run's FASTQ from ENA, the European
mirror of the same INSDC record, when the SRA Toolkit cannot (stage 1 fallback).

The run accession (SRR/ERR/DRR) is looked up in the ENA portal file report; the
two published FASTQ files are fetched over HTTPS and each is checked against the
MD5 that ENA publishes for it. A run that is not PAIRED, has no FASTQ, or fails
the checksum is an error; nothing partial is left behind under the final names.

Writes <out-dir>/<run>_1.fastq.gz and <run>_2.fastq.gz, and a one-line
provenance JSON (<out-dir>/<run>.ena_provenance.json) with the URLs, sizes and
MD5s. Standard library only.

Speed: the two mates download at the same time, and a file of at least
ENA_SEGMENT_MIN_BYTES (default 16 MiB) is split into ENA_DOWNLOAD_CONNECTIONS
(default 4) byte ranges fetched in parallel (HTTP Range), or handed to aria2c when it
is installed (ENA_USE_ARIA2=0 disables that). Any problem with the parallel transfer
(no Range support, a short segment, aria2c failing) falls back to the resumable
single-stream transfer; every file is MD5-verified either way.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

CONNECTIONS = max(1, int(os.environ.get("ENA_DOWNLOAD_CONNECTIONS", "4") or 4))
SEGMENT_MIN_BYTES = int(os.environ.get("ENA_SEGMENT_MIN_BYTES", str(16 << 20)) or (16 << 20))

PORTAL = "https://www.ebi.ac.uk/ena/portal/api/filereport"
FIELDS = "run_accession,fastq_ftp,fastq_md5,fastq_bytes,library_layout"


def file_report(run, timeout=60):
    query = urllib.parse.urlencode({"accession": run, "result": "read_run", "fields": FIELDS, "format": "tsv"})
    with urllib.request.urlopen(f"{PORTAL}?{query}", timeout=timeout) as response:
        lines = response.read().decode("utf-8").strip().splitlines()
    if len(lines) < 2:
        raise ValueError(f"ENA has no read_run record for {run}")
    header, values = lines[0].split("\t"), lines[1].split("\t")
    return dict(zip(header, values))


class _RangeUnsupported(OSError):
    """The server answered a byte-range request with the whole file."""


def segmented_download(url, tmp, total, connections=CONNECTIONS, timeout=120):
    """Fetch bytes [0, total) of url into tmp as `connections` parallel byte ranges.

    The file is preallocated and each range is written at its own offset, so the parts
    never need to be concatenated. Raises (and the caller falls back to one stream) if
    the server ignores Range or a segment comes back short.
    """
    step = -(-total // connections)                      # ceiling division
    ranges = [(start, min(start + step, total) - 1) for start in range(0, total, step)]
    with open(tmp, "wb") as handle:
        handle.truncate(total)

    def fetch(bounds):
        start, end = bounds
        request = urllib.request.Request(url)
        request.add_header("Range", f"bytes={start}-{end}")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if getattr(response, "status", 200) != 206:
                raise _RangeUnsupported(f"{url}: server ignored the byte range")
            with open(tmp, "r+b") as handle:
                handle.seek(start)
                remaining = end - start + 1
                for block in iter(lambda: response.read(1 << 20), b""):
                    handle.write(block[:remaining])
                    remaining -= len(block)
            if remaining > 0:
                raise OSError(f"{url}: segment {start}-{end} ended {remaining} bytes early")

    with ThreadPoolExecutor(max_workers=len(ranges)) as pool:
        list(pool.map(fetch, ranges))


def aria2_download(url, tmp, connections=CONNECTIONS):
    """Fetch url to tmp with aria2c's segmented downloader; False when unavailable."""
    if os.environ.get("ENA_USE_ARIA2", "1") == "0" or not shutil.which("aria2c"):
        return False
    command = ["aria2c", f"--max-connection-per-server={connections}", f"--split={connections}",
               "--min-split-size=1M", "--allow-overwrite=true", "--auto-file-renaming=false",
               "--quiet=true", "--dir", os.path.dirname(os.path.abspath(tmp)), "--out", os.path.basename(tmp), url]
    return subprocess.run(command, check=False).returncode == 0


def parallel_attempt(url, tmp, total, timeout):
    """One parallel transfer of a large file; on any failure tmp is removed and False returned."""
    if not total or total < SEGMENT_MIN_BYTES or CONNECTIONS < 2 or os.path.exists(tmp):
        return False
    try:
        if aria2_download(url, tmp):
            done = os.path.getsize(tmp) == total
        else:
            segmented_download(url, tmp, total, timeout=timeout)
            done = True
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"[fetch_ena_reads] parallel transfer unavailable ({exc}); using one stream\n")
        done = False
    if not done and os.path.exists(tmp):
        os.remove(tmp)
    return done


def download(url, path, expected_md5, expected_bytes=None, retries=5, timeout=120):
    """Fetch url to path, verifying MD5. A large file is first fetched as parallel byte
    ranges (parallel_attempt); a transfer that ends early resumes from the bytes already
    on disk (HTTP Range) on the next attempt; a completed file whose MD5 is wrong is
    discarded and fetched again from the start."""
    tmp = path + ".part"
    total = int(expected_bytes) if expected_bytes else None
    parallel_attempt(url, tmp, total, timeout)   # a complete tmp skips straight to the MD5 check below
    for attempt in range(1, retries + 1):
        try:
            have = os.path.getsize(tmp) if os.path.exists(tmp) else 0
            if total and have > total:
                os.remove(tmp)
                have = 0
            request = urllib.request.Request(url)
            if have and (not total or have < total):
                request.add_header("Range", f"bytes={have}-")
            if not total or have < total:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    if have and getattr(response, "status", 206) != 206:
                        have = 0  # server ignored the range: start again
                    with open(tmp, "ab" if have else "wb") as handle:
                        for block in iter(lambda: response.read(1 << 20), b""):
                            handle.write(block)
            size = os.path.getsize(tmp)
            if total and size < total:
                raise OSError(f"transfer ended early for {url} ({size} of {total} bytes); will resume")
            digest = hashlib.md5()
            with open(tmp, "rb") as handle:
                for block in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(block)
            if digest.hexdigest() != expected_md5:
                os.remove(tmp)
                raise ValueError(f"MD5 mismatch for {url}: {digest.hexdigest()} != {expected_md5}")
            os.replace(tmp, path)
            return
        except (OSError, ValueError) as exc:
            if attempt == retries:
                if os.path.exists(tmp):
                    os.remove(tmp)
                raise
            sys.stderr.write(f"[fetch_ena_reads] {exc}; retry {attempt}/{retries - 1}\n")
            time.sleep(15 * attempt)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True, help="SRR/ERR/DRR run accession")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    try:
        report = file_report(args.run)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"ERROR: ENA lookup failed for {args.run}: {exc}")
    urls = [u for u in (report.get("fastq_ftp") or "").split(";") if u]
    md5s = (report.get("fastq_md5") or "").split(";")
    sizes = (report.get("fastq_bytes") or "").split(";")
    pairs = [(u, m, b) for u, m, b in zip(urls, md5s, sizes + [""] * len(urls))
             if u.endswith("_1.fastq.gz") or u.endswith("_2.fastq.gz")]
    if report.get("library_layout") != "PAIRED" or len(pairs) != 2:
        raise SystemExit(f"ERROR: {args.run} is not a paired run with _1/_2 FASTQ in ENA "
                         f"(layout {report.get('library_layout')}, files {len(urls)})")
    os.makedirs(args.out_dir, exist_ok=True)
    provenance = {"run": args.run, "source": "ENA", "files": []}

    def fetch_mate(entry):
        url, md5, size = entry
        mate = "1" if url.endswith("_1.fastq.gz") else "2"
        path = os.path.join(args.out_dir, f"{args.run}_{mate}.fastq.gz")
        download("https://" + url if not url.startswith("http") else url, path, md5, size)
        sys.stderr.write(f"[fetch_ena_reads] {args.run}_{mate}.fastq.gz verified (md5 {md5})\n")
        return {"url": url, "md5": md5, "bytes": size, "path": os.path.basename(path)}

    # Both mates at once (independent files); results come back in mate order, and the
    # first failure is raised after the other transfer finishes or fails.
    with ThreadPoolExecutor(max_workers=2) as pool:
        provenance["files"] = list(pool.map(fetch_mate, sorted(pairs)))
    with open(os.path.join(args.out_dir, f"{args.run}.ena_provenance.json"), "w", encoding="utf-8") as handle:
        json.dump(provenance, handle, indent=2)


if __name__ == "__main__":
    main()
