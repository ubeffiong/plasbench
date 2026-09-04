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
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num_bytes) < 1024 or unit == "TB":
            return f"{num_bytes:.1f} {unit}" if unit != "B" else f"{num_bytes:.0f} B"
        num_bytes /= 1024
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

    if pending_refs == 0 and pending_reads == 0:
        print(f"All {len(rows)} sample(s) are already downloaded; nothing to fetch.")
        return 0

    reference_bytes = pending_refs * REFERENCE_BYTES
    reads_mid = known_bases * BYTES_PER_BASE
    reads_low = known_bases * BYTES_PER_BASE_LOW
    reads_high = known_bases * BYTES_PER_BASE_HIGH

    print(f"About to download from NCBI:")
    print(f"  reference assemblies : {pending_refs:>4}  ~{human(reference_bytes)}")
    if known_bases:
        print(f"  Illumina read sets   : {pending_reads:>4}  ~{human(reads_mid)}"
              f"  ({human(reads_low)} - {human(reads_high)})")
        print(f"  ESTIMATED TOTAL      :       ~{human(reference_bytes + reads_mid)}")
    else:
        print(f"  Illumina read sets   : {pending_reads:>4}  size unknown")
    if unknown:
        shown = ", ".join(unknown[:4]) + (" ..." if len(unknown) > 4 else "")
        print(f"  NOTE: no base count for {len(unknown)} sample(s) ({shown});")
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
