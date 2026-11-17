#!/usr/bin/env python3
"""A short-read QC pilot on real reads: the first part of each run's paired FASTQ files, measured with short_read_qc.py.

Freezing the QC thresholds needs the distribution of the QC metrics on real reads of the intended kind. This takes the first --pairs read pairs of each of N runs from
the ENA mirror (an HTTP range request for a small prefix of each mate, not the whole file), writes a valid FASTQ pair of exactly that many reads, and runs
short_read_qc.py on it. Per-read measures (mean quality, Q20/Q30, read length, adapters, N, duplication, pair synchrony, GC) are valid on a prefix; read pairs and depth
are not (the prefix is short by construction), so those two come from the run's ENA read and base counts instead.

  qc_pilot.py --cohort cohorts/public-v4.tsv --n 40 --out-dir pilot_qc --summary qc_pilot_summary.tsv

The runs are the first N rows of the cohort in its balanced order (species take turns; recent and older genomes alternate), chosen by position, never by any tool's result.
Standard library only; network access to the ENA is needed.
"""
import argparse
import concurrent.futures
import csv
import gzip
import json
import os
import subprocess
import sys
import urllib.request
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
TAB, NL = chr(9), chr(10)
UA = {"User-Agent": "PlasBench QC pilot (range requests, small prefixes)"}


def read_rows(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return list(csv.DictReader((l for l in handle if l.strip() and not l.startswith("#")), delimiter=TAB))


def filereport(run):
    url = ("https://www.ebi.ac.uk/ena/portal/api/filereport?accession=" + run
           + "&result=read_run&fields=run_accession,fastq_ftp,fastq_bytes,read_count,base_count&format=tsv")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as response:
        lines = response.read().decode().splitlines()
    return dict(zip(lines[0].split(TAB), lines[1].split(TAB))) if len(lines) > 1 else {}


def prefix_records(url, nbytes, wanted):
    """Complete 4-line FASTQ records from the first nbytes of a gzip file (at most `wanted`)."""
    request = urllib.request.Request("https://" + url, headers=dict(UA, Range=f"bytes=0-{nbytes - 1}"))
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
    text = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(data).decode("ascii", "replace").split(NL)
    records = [text[i:i + 4] for i in range(0, len(text) - 4, 4)]
    return [r for r in records if len(r) == 4 and r[0].startswith("@") and r[2].startswith("+")][:wanted]


def pilot_one(row, out_dir, pairs, nbytes):
    run = row["sra_run"]
    info = filereport(run)
    urls = (info.get("fastq_ftp") or "").split(";")
    if len(urls) != 2:
        return {"sample": row["sample_id"], "run": run, "status": "skipped", "note": "not a plain two-file paired run at the ENA"}
    first = prefix_records(urls[0], nbytes, pairs)
    second = prefix_records(urls[1], nbytes, pairs)
    n = min(len(first), len(second))
    if n < 1000:
        return {"sample": row["sample_id"], "run": run, "status": "skipped", "note": f"only {n} complete pairs in the prefix"}
    r1, r2 = os.path.join(out_dir, run + "_1.fastq.gz"), os.path.join(out_dir, run + "_2.fastq.gz")
    for path, records in ((r1, first[:n]), (r2, second[:n])):
        with gzip.open(path, "wt", encoding="ascii") as handle:
            handle.write("".join(NL.join(r) + NL for r in records))
    qc = os.path.join(out_dir, run + ".qc.tsv")
    done = subprocess.run([sys.executable, os.path.join(HERE, "short_read_qc.py"), "qc", "--sample", row["sample_id"], "--r1", r1, "--r2", r2, "--out", qc,
                           "--max-pairs", str(n)], capture_output=True, text=True)
    for path in (r1, r2):
        os.remove(path)
    if done.returncode != 0 or not os.path.exists(qc):
        return {"sample": row["sample_id"], "run": run, "status": "skipped", "note": "short_read_qc failed: " + (done.stderr or done.stdout)[-120:]}
    result = read_rows(qc)[0]
    result.update(run=run, status="measured", organism=row.get("organism", ""), pairs_in_prefix=str(n), ena_read_count=info.get("read_count", ""),
                  ena_base_count=info.get("base_count", ""), note="")
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cohort", required=True)
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--pairs", type=int, default=60000)
    ap.add_argument("--prefix-mb", type=float, default=14.0, help="how much of each mate to fetch (about 60,000 pairs of 2 x 150 bp)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--summary", required=True)
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    rows = read_rows(args.cohort)[:args.n]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(pilot_one, row, args.out_dir, args.pairs, int(args.prefix_mb * 1024 * 1024)): row for row in rows}
        for future in concurrent.futures.as_completed(futures):
            row = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append({"sample": row["sample_id"], "run": row["sra_run"], "status": "skipped", "note": f"{type(exc).__name__}: {exc}"[:150]})
            sys.stderr.write(f"[qc_pilot] {len(results)}/{len(rows)} {results[-1]['sample']} {results[-1]['status']}{': ' + results[-1].get('note', '') if results[-1].get('note') else ''}\n")
    fields = ["sample", "run", "organism", "status", "note", "pairs_in_prefix", "ena_read_count", "ena_base_count", "qc_status", "reasons", "median_read_length", "mean_quality",
              "q20_fraction", "q30_fraction", "gc_percent", "n_fraction", "adapter_fraction", "duplication_fraction", "pair_mismatch_fraction"]
    with open(args.summary, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=TAB, lineterminator=NL, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sorted(results, key=lambda r: r["sample"]))
    print(json.dumps({"measured": sum(r["status"] == "measured" for r in results), "skipped": sum(r["status"] != "measured" for r in results)}))


if __name__ == "__main__":
    main()
