#!/usr/bin/env python3
"""plasbench net-bench: how fast does ENA deliver to THIS computer with 1, 4, 8 and 16 connections, and what should ENA_MAX_CONNECTIONS be?

It fetches small byte ranges (about 32 MiB per setting, each setting time-boxed, default 20 s) from the start region of a known public ENA FASTQ file and prints MB/s per setting.
Nothing is written to disk and nothing is kept. Single measurements are noisy (on one link a test gave 0.61 MB/s with 4 connections but 3.10 MB/s with 8, and 4.25 with 16),
so run it twice and trust a pattern, not one number. The recommendation is the smallest setting that reaches 90% of the best rate seen; it never recommends more than 16 connections.

  plasbench net-bench [--run SRR36114699] [--url URL] [--mib 32] [--seconds 20] [--settings 1,4,8,16] [--json]

It needs ENA (checked like every online command: `plasbench net`). With --url, or with ENA_PORTAL_URL set (a mirror or a test server), no internet check is made.
Standard library only; Python 3.9 compatible.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ena_download  # noqa: E402
import fetch_ena_reads  # noqa: E402
from plasbench_common import net_explain, net_require  # noqa: E402

DEFAULT_RUN = "SRR36114699"        # a public Streptomyces run; each mate is 4.7 GB, far larger than any range read here
HARD_MAX = 16


def resolve_url(run):
    report = fetch_ena_reads.file_report(run)
    urls = [u for u in (report.get("fastq_ftp") or "").split(";") if u.endswith("_1.fastq.gz")]
    if not urls:
        raise ValueError(f"ENA lists no _1.fastq.gz file for {run}")
    return "https://" + urls[0] if not urls[0].startswith("http") else urls[0]


def measure(url, connections, total_bytes, seconds, offset):
    """Fetch `total_bytes` split over `connections` ranges starting at `offset`, stopping at the time limit. Returns (bytes received, seconds, errors)."""
    share = max(1 << 20, total_bytes // connections)
    received, errors = [0], []
    lock = threading.Lock()
    deadline = time.time() + seconds
    started = time.time()

    def work(index):
        start = offset + index * share
        try:
            response = ena_download.open_range(url, start, start + share - 1, 15)
        except OSError as exc:
            with lock:
                errors.append(str(exc))
            return
        try:
            while time.time() < deadline:
                block = response.read(64 * 1024)
                if not block:
                    break
                with lock:
                    received[0] += len(block)
        except (OSError, ValueError) as exc:
            with lock:
                errors.append(str(exc))
        finally:
            response.close()

    threads = [threading.Thread(target=work, args=(i,), daemon=True) for i in range(connections)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(seconds + 20)
    return received[0], max(1e-6, time.time() - started), errors


def recommend(results):
    """results: [{connections, mb_per_s}] -> the smallest setting within 90% of the best."""
    good = [r for r in results if r["mb_per_s"] > 0]
    if not good:
        return None
    best = max(r["mb_per_s"] for r in good)
    return min((r for r in good if r["mb_per_s"] >= 0.9 * best), key=lambda r: r["connections"])["connections"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", default=DEFAULT_RUN, help="ENA run whose first FASTQ file is read (default %(default)s)")
    ap.add_argument("--url", help="a file URL that honours Range, instead of looking one up")
    ap.add_argument("--mib", type=float, default=32.0, help="MiB fetched per setting (default 32)")
    ap.add_argument("--seconds", type=float, default=20.0, help="time limit per setting (default 20)")
    ap.add_argument("--settings", default="1,4,8,16", help="connection counts to try (default 1,4,8,16; at most 16)")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    args = ap.parse_args(argv)
    counts = sorted({max(1, min(HARD_MAX, int(x))) for x in args.settings.split(",") if x.strip().isdigit()})
    if not counts:
        ap.error("--settings needs numbers such as 1,4,8,16")
    if not args.url and not os.environ.get("ENA_PORTAL_URL"):
        net_require(["ena"], action="The ENA speed test", code=3)
    try:
        url = args.url or resolve_url(args.run)
        total, _etag, _mod = ena_download.probe(url, timeout=20)
    except (OSError, ValueError, ena_download.RangeUnsupported) as exc:
        print(f"net-bench: cannot read {args.url or args.run} from ENA: {net_explain(exc, 'ena', 'The ENA speed test')}", file=sys.stderr)
        return 3
    want = int(args.mib * (1 << 20))
    results = []
    if not args.json:
        print(f"net-bench: {url}")
        print(f"  {args.mib:g} MiB per setting, at most {args.seconds:g} s each; nothing is saved to disk")
    for n, k in enumerate(counts):
        offset = (k * 64 + n * 8) * (1 << 20) % max(1, total - want - (1 << 20)) if total > 2 * want else 0
        got, seconds, errors = measure(url, k, want, args.seconds, offset)
        row = {"connections": k, "bytes": got, "seconds": round(seconds, 2), "mb_per_s": round(got / seconds / 1e6, 2), "errors": len(errors)}
        results.append(row)
        if not args.json:
            note = f"  ({len(errors)} connection error(s): {errors[0][:80]})" if errors else ""
            print(f"  {k:>2} connection{'s' if k != 1 else ' '}: {row['mb_per_s']:>6.2f} MB/s{note}")
    best = recommend(results)
    out = {"url": url, "results": results, "recommended_connections": best, "noise_warning": "Single measurements are noisy: run `plasbench net-bench` twice and trust a pattern, not one number."}
    if args.json:
        print(json.dumps(out, indent=1))
        return 0
    if best is None:
        print("  No setting delivered any data; check `plasbench net`.")
        return 3
    mates = max(1, best // 2)
    print()
    print(f"  Recommended: ENA_MAX_CONNECTIONS={best} (the total for both mates; the default is 16, the maximum 24)"
          + ("" if best >= 16 else f", and leave ENA_DOWNLOAD_CONNECTIONS empty or set it to {mates}"))
    if len(results) > 1 and results[-1]["mb_per_s"] > 1.15 * results[0]["mb_per_s"] and best == results[-1]["connections"]:
        print("  The rate was still rising at the largest setting; this link is limited per connection, not in total, so the default of 16 is a sensible place to stay.")
    elif len(results) > 1 and best <= 4:
        print("  More connections did not help: the link itself (or something between you and ENA) is the limit.")
    print("  " + out["noise_warning"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
