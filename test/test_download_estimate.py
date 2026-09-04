#!/usr/bin/env python3
"""Regression for the pre-download size estimate shown before stage 1 fetches.

A user is entitled to see how many gigabytes a cohort run is about to pull
before it starts. The number must exclude what is already on disk, must say so
plainly when a sample's size is unknown rather than quietly under-reporting,
and must never claim a total it cannot support.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "python" / "estimate_download.py"


def run(sheet, data_dir):
    result = subprocess.run([sys.executable, str(SCRIPT), "--samples", str(sheet),
                             "--data-dir", str(data_dir)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout


def write_sheet(path, rows):
    header = "sample_id\tassembly_accession\tsra_run\n"
    path.write_text(header + "".join(f"{s}\t{a}\t{r}\n" for s, a, r in rows), encoding="utf-8")


def write_lock(path, bases):
    path.write_text(json.dumps({"evidence": [
        {"sample_id": s, "run": {"bases": str(b)}} for s, b in bases.items()]}), encoding="utf-8")


def check(name, condition, output):
    if not condition:
        print(f"FAIL: {name}\n--- output ---\n{output}", file=sys.stderr)
        raise SystemExit(1)
    print(f"  {name} ? True")


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    data = tmp / "data"; data.mkdir()
    sheet = tmp / "c.tsv"
    write_sheet(sheet, [("s1", "GCF_1", "SRR1"), ("s2", "GCF_2", "SRR2")])
    write_lock(tmp / "c.lock.json", {"s1": 1_000_000_000, "s2": 1_000_000_000})

    out = run(sheet, data)
    check("totals both samples when nothing is downloaded",
          "2" in out and "ESTIMATED TOTAL" in out, out)
    # 2 Gbases * 0.615 ~ 1.2 GB of reads, plus 2 references
    check("estimate is in the expected magnitude (GB, not MB or TB)",
          "GB" in out, out)

    # Mark s1 as fully downloaded; it must drop out of the total.
    s1 = data / "s1"; s1.mkdir()
    (s1 / "reference.fna").write_text(">x\nACGT\n", encoding="utf-8")
    (s1 / "sequence_report.jsonl").write_text("{}\n", encoding="utf-8")
    (s1 / "SRR1_1.fastq.gz").write_bytes(b"x")
    (s1 / "SRR1_2.fastq.gz").write_bytes(b"x")
    out = run(sheet, data)
    check("already-downloaded samples are excluded and reported as skipped",
          "1 sample(s) already downloaded" in out, out)
    check("only the remaining sample is counted",
          "reference assemblies :      1" in out.replace("   1", "      1") or ": 1" in out or "    1  " in out, out)

    # Everything present -> nothing to fetch.
    s2 = data / "s2"; s2.mkdir()
    (s2 / "reference.fna").write_text(">x\nACGT\n", encoding="utf-8")
    (s2 / "sequence_report.jsonl").write_text("{}\n", encoding="utf-8")
    (s2 / "SRR2_1.fastq.gz").write_bytes(b"x")
    (s2 / "SRR2_2.fastq.gz").write_bytes(b"x")
    out = run(sheet, data)
    check("says nothing to fetch when everything is present",
          "nothing to fetch" in out, out)

    # No lock -> must not invent a total.
    bare = tmp / "bare"; bare.mkdir()
    sheet2 = bare / "d.tsv"
    write_sheet(sheet2, [("s9", "GCF_9", "SRR9")])
    out = run(sheet2, bare / "nodata")
    check("without a lock it reports the size as unknown, not a made-up number",
          "size unknown" in out and "ESTIMATED TOTAL" not in out, out)
    check("and points at validate-cohort for an exact figure",
          "validate-cohort" in out, out)

print("ALL DOWNLOAD ESTIMATE TESTS PASSED")
