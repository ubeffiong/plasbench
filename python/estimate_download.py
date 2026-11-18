#!/usr/bin/env python3
"""Estimate what stage 1 is about to download, before it downloads it.

A cohort run fetches reference assemblies and Illumina reads from NCBI. On a
32-sample cohort that is tens of gigabytes and several hours, and a user is
entitled to see the number before it starts rather than discover it from a disk
that filled up.

Sizes come from the cohort's verification lock when one is present, which
records the exact base count NCBI reports for every run. Compressed FASTQ size
is estimated from that base count using a factor measured on real PlasBench
downloads: seven isolates spanning 0.18-0.67 Gbases gave 0.50-0.68 bytes per
base, mean 0.615. The reference bundle (genome, sequence report, GFF) averaged
12.1 MB per sample across the same isolates.

The estimate is deliberately labelled as one. Without a lock there is no base
count to work from, and the script says so rather than inventing a total.

Samples whose files are already on disk are excluded, so the figure reflects
what this run will actually fetch.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

# Measured on real downloads; see the module docstring.
BYTES_PER_BASE = 0.615
BYTES_PER_BASE_LOW = 0.50
BYTES_PER_BASE_HIGH = 0.68
REFERENCE_BYTES = 12_100_000


def human(num_bytes: float) -> str:
    """Decimal units (1 GB = 1e9 bytes), the ones ENA, NCBI and drive makers use, and the ones the download log prints: one run is '9.5 GB' everywhere."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num_bytes) < 1000 or unit == "TB":
            return f"{num_bytes:.1f} {unit}" if unit != "B" else f"{num_bytes:.0f} B"
        num_bytes /= 1000
    return f"{num_bytes:.1f} TB"


def read_rows(path: Path):
    with open(path, newline="", encoding="utf-8") as handle:
        stream = (line for line in handle
                  if line.strip() and not line.lstrip().startswith("#"))
        return list(csv.DictReader(stream, delimiter="\t"))


def lock_bases(sheet: Path) -> dict:
    """Base counts per sample from the sheet's sibling .lock.json, if present."""
    candidates = [sheet.with_suffix(".lock.json"),
                  sheet.parent / (sheet.stem + ".lock.json")]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        out = {}
        for entry in data.get("evidence", []):
            run = entry.get("run") or {}
            try:
                out[entry.get("sample_id", "")] = int(run.get("bases") or 0)
            except (TypeError, ValueError):
                pass
        if out:
            return out
    return {}


def ena_sizes(runs: dict, report=None, workers: int = 8, deadline: float = 40.0):
    """{sample: total FASTQ bytes} from ENA's file report for the runs the lock has no base count for, plus the samples ENA gave no size for.

    A bare cohort sheet (a first-N copy, your own isolates) has no lock, so every read set used to print 'size unknown' and a single 9.5 GB run could hide in a
    20-isolate 'quick' test. ENA reports each file's exact compressed size, so this asks it, a few runs at a time, within `deadline` seconds in all.
    `report(run, timeout)` returns ENA's record for one run; it defaults to python/fetch_ena_reads.file_report.
    """
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed
    if report is None:
        from fetch_ena_reads import file_report as report
    found, missing = {}, []
    start = time.time()

    def one(sample, run):
        record = report(run, timeout=15)
        sizes = [x for x in (record.get("fastq_bytes") or "").split(";") if x.strip()]
        if not sizes or not all(x.strip().isdigit() for x in sizes):
            raise ValueError("no sizes")
        return sample, sum(int(x) for x in sizes)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(one, s, r): s for s, r in runs.items()}
        try:
            for future in as_completed(futures, timeout=max(1.0, deadline)):
                try:
                    sample, total = future.result()
                    found[sample] = total
                except Exception:  # noqa: BLE001 - a lookup that fails only leaves that sample's size unknown
                    missing.append(futures[future])
        except Exception:  # noqa: BLE001 - the overall deadline: whatever has not answered is unknown
            for future, sample in futures.items():
                if not future.done():
                    future.cancel()
                    missing.append(sample)
    return found, sorted(set(missing) | (set(runs) - set(found)))


def lookup_enabled() -> bool:
    """ENA lookups are skipped with ENA_SIZE_LOOKUP=0 and with READ_SOURCE=sra (which never uses ENA)."""
    import os
    return os.environ.get("ENA_SIZE_LOOKUP", "1") != "0" and os.environ.get("READ_SOURCE", "auto") != "sra"


def ena_unreachable() -> str:
    """'' when ENA can be asked for sizes; otherwise one plain sentence saying why not (offline, DNS broken, ENA down).

    The size lookup is only advice, so being offline is a note in the estimate, never an error. A mirror set with ENA_PORTAL_URL is not probed."""
    import os
    if os.environ.get("ENA_PORTAL_URL"):
        return ""
    try:
        from plasbench_common import netcheck_module
        module = netcheck_module()
        if module is None:
            return ""
        module.require("ena", action="The ENA size lookup")
    except Exception as exc:  # noqa: BLE001 - NoInternet carries the sentence; anything else must not break the estimate
        return str(exc) if exc.__class__.__name__ == "NoInternet" else ""
    return ""


def already_have(data_dir: Path, sample: str, sra: str):
    """(reference_present, reads_present) for one sample."""
    sdir = data_dir / sample
    reference = (sdir / "reference.fna").is_file() and (sdir / "sequence_report.jsonl").is_file()
    reads = bool(sra) and (sdir / f"{sra}_1.fastq.gz").is_file() and (sdir / f"{sra}_2.fastq.gz").is_file()
    return reference, reads


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--samples", required=True)
    ap.add_argument("--data-dir", required=True)
    args = ap.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parent))   # fetch_ena_reads, for the size lookup

    sheet = Path(args.samples)
    data_dir = Path(args.data_dir)
    rows = read_rows(sheet)
    if not rows:
        print("No samples in the sheet; nothing to download.")
        return 0

    bases = lock_bases(sheet)
    pending_refs = pending_reads = 0
    known_bases = 0
    unknown = []
    unknown_runs = {}
    skipped = 0

    for row in rows:
        sample = (row.get("sample_id") or "").strip()
        sra = (row.get("sra_run") or "").strip()
        accession = (row.get("assembly_accession") or "").strip()
        if not sample:
            continue
        have_ref, have_reads = already_have(data_dir, sample, sra)
        if have_ref and (have_reads or not sra):
            skipped += 1
            continue
        if accession and not have_ref:
            pending_refs += 1
        if sra and not have_reads:
            pending_reads += 1
            if bases.get(sample):
                known_bases += bases[sample]
            else:
                unknown.append(sample)
                unknown_runs[sample] = sra

    if pending_refs == 0 and pending_reads == 0:
        print(f"All {len(rows)} sample(s) are already downloaded; nothing to fetch.")
        return 0

    # No base count for some samples (a sheet without a lock): ask ENA for each run's exact compressed size.
    exact, largest = 0, None
    offline_note = ena_unreachable() if unknown_runs and lookup_enabled() else ""
    if unknown_runs and lookup_enabled() and not offline_note:
        found, unknown_after = ena_sizes(unknown_runs)
        exact = sum(found.values())
        if found:
            top = max(found, key=found.get)
            largest = (top, unknown_runs[top], found[top])
        unknown = unknown_after
    reference_bytes = pending_refs * REFERENCE_BYTES
    reads_mid = known_bases * BYTES_PER_BASE + exact
    reads_low = known_bases * BYTES_PER_BASE_LOW + exact
    reads_high = known_bases * BYTES_PER_BASE_HIGH + exact

    print(f"About to download from NCBI:")
    print(f"  reference assemblies : {pending_refs:>4}  ~{human(reference_bytes)}")
    if known_bases or exact:
        spread = f"  ({human(reads_low)} - {human(reads_high)})" if known_bases else "  (exact sizes from ENA)"
        print(f"  Illumina read sets   : {pending_reads:>4}  ~{human(reads_mid)}{spread}")
        print(f"  ESTIMATED TOTAL      :       ~{human(reference_bytes + reads_mid)}")
    else:
        print(f"  Illumina read sets   : {pending_reads:>4}  size unknown")
    if largest:
        print(f"  LARGEST READ SET     : {largest[1]} ({largest[0]}) {human(largest[2])} compressed"
              + ("  <- very large: slow to download, ~3x on disk, heavy to assemble (MAX_RUN_DOWNLOAD_GB skips such isolates)" if largest[2] > 5e9 else ""))
    if offline_note:
        print("  NOTE: ENA read sizes were not looked up, so the total above leaves them out.")
        print(f"        {offline_note}")
    if unknown:
        shown = ", ".join(unknown[:4]) + (" ..." if len(unknown) > 4 else "")
        print(f"  NOTE: no size for {len(unknown)} sample(s) ({shown});")
        print(f"        their reads are NOT included in the total above.")
        print(f"        Run 'plasbench validate-cohort --samples {sheet} --online "
              f"--write-lock {sheet.with_suffix('.lock.json')}' for an exact figure.")
    if skipped:
        print(f"  ({skipped} sample(s) already downloaded and will be skipped)")
    print()
    print("  Read sizes are estimated from NCBI base counts; the real total will")
    print("  differ somewhat. Assemblies, trimmed reads and tool output need disk")
    print("  on top of this -- budget roughly 3x the download size.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
