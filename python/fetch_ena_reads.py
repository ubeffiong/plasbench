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
"""

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request

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


def download(url, path, expected_md5, expected_bytes=None, retries=3, timeout=120):
    for attempt in range(1, retries + 1):
        tmp = path + ".part"
        digest = hashlib.md5()
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response, open(tmp, "wb") as handle:
                for block in iter(lambda: response.read(1 << 20), b""):
                    handle.write(block)
                    digest.update(block)
            if digest.hexdigest() != expected_md5:
                raise ValueError(f"MD5 mismatch for {url}: {digest.hexdigest()} != {expected_md5}")
            if expected_bytes and os.path.getsize(tmp) != int(expected_bytes):
                raise ValueError(f"size mismatch for {url}")
            os.replace(tmp, path)
            return
        except (OSError, ValueError) as exc:
            if os.path.exists(tmp):
                os.remove(tmp)
            if attempt == retries:
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
    for url, md5, size in sorted(pairs):
        mate = "1" if url.endswith("_1.fastq.gz") else "2"
        path = os.path.join(args.out_dir, f"{args.run}_{mate}.fastq.gz")
        download("https://" + url if not url.startswith("http") else url, path, md5, size)
        provenance["files"].append({"url": url, "md5": md5, "bytes": size, "path": os.path.basename(path)})
        sys.stderr.write(f"[fetch_ena_reads] {args.run}_{mate}.fastq.gz verified (md5 {md5})\n")
    with open(os.path.join(args.out_dir, f"{args.run}.ena_provenance.json"), "w", encoding="utf-8") as handle:
        json.dump(provenance, handle, indent=2)


if __name__ == "__main__":
    main()
