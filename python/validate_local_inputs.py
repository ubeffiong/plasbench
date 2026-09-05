#!/usr/bin/env python3
"""Check every local input before a run spends hours on it.

`--local-inputs` means the files a user staged by hand ARE the experiment. The
existing check only asks whether they exist, and existence is the least
interesting thing about them: a FASTQ that is not gzipped, reads whose members
do not pair, a reference that is empty or has duplicate ids, a truth table whose
ids do not match the reference -- none of those are missing files, and none of
them announce themselves. Some surface hours later as a confusing tool crash,
and the worst do not surface at all: they change the leaderboard quietly.

Every problem reported here names the file, says what is wrong in plain terms,
and gives the command that fixes it. Warnings describe things that are legal but
usually mistakes; they do not stop the run.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import sys
from pathlib import Path

GZIP_MAGIC = b"\x1f\x8b"


def read_sheet(path: Path):
    with open(path, newline="", encoding="utf-8") as handle:
        stream = (line for line in handle
                  if line.strip() and not line.lstrip().startswith("#"))
        return list(csv.DictReader(stream, delimiter="\t"))


def first_reads(path: Path, count: int):
    """First `count` read names from a gzipped FASTQ, or None if unreadable."""
    names = []
    try:
        with gzip.open(path, "rt", errors="replace") as handle:
            for index, line in enumerate(handle):
                if index % 4 == 0:
                    name = line.strip().lstrip("@").split()[0]
                    names.append(name[:-2] if name.endswith(("/1", "/2")) else name)
                    if len(names) >= count:
                        break
    except (OSError, EOFError):
        return None
    return names


def count_reads(path: Path, limit: int):
    """Number of records, or limit+1 once that many have been seen.

    Counting stops at `limit` so a multi-gigabyte FASTQ is not fully
    decompressed just to be counted: knowing both files exceed the cap is
    enough to compare them.
    """
    seen = 0
    try:
        with gzip.open(path, "rt", errors="replace") as handle:
            for index, _ in enumerate(handle):
                if index % 4 == 0:
                    seen += 1
                    if seen > limit:
                        return seen
    except (OSError, EOFError):
        return None
    return seen


def fasta_ids(path: Path):
    ids, duplicates, empty = [], [], []
    current, length = None, 0
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith(">"):
                if current is not None and length == 0:
                    empty.append(current)
                parts = line[1:].strip().split(None, 1)
                current = parts[0] if parts else ""
                if current in ids:
                    duplicates.append(current)
                ids.append(current)
                length = 0
            else:
                length += len(line.strip())
    if current is not None and length == 0:
        empty.append(current)
    return ids, duplicates, empty


def check_sample(row, data_dir: Path, problems, warnings):
    sample = (row.get("sample_id") or "").strip()
    sra = (row.get("sra_run") or "").strip()
    accession = (row.get("assembly_accession") or "").strip()
    sdir = data_dir / sample
    where = f"[{sample}]"

    if not sdir.is_dir():
        problems.append(f"{where} no directory {sdir}\n"
                        f"      Create it and put this sample's files there, or let PlasBench do it:\n"
                        f"      plasbench init-local --sample {sample} --reads-1 R1.fastq.gz "
                        f"--reads-2 R2.fastq.gz --reference assembly.fasta")
        return

    # --- reads -------------------------------------------------------------
    r1, r2 = sdir / f"{sra}_1.fastq.gz", sdir / f"{sra}_2.fastq.gz"
    for path, side in ((r1, "forward"), (r2, "reverse")):
        if not path.is_file():
            found = sorted(p.name for p in sdir.glob("*.fastq.gz"))
            hint = (f"      The directory has: {', '.join(found)}\n"
                    f"      The sheet's sra_run column is '{sra}', so PlasBench expects "
                    f"'{sra}_1.fastq.gz' and '{sra}_2.fastq.gz'.\n"
                    f"      Either rename the files, or set sra_run to their shared prefix."
                    if found else
                    "      Put the paired, gzipped FASTQ files in this directory.")
            problems.append(f"{where} missing {side} reads: {path.name}\n{hint}")
            continue
        if path.stat().st_size == 0:
            problems.append(f"{where} {path.name} is empty (0 bytes)")
            continue
        with open(path, "rb") as handle:
            if handle.read(2) != GZIP_MAGIC:
                problems.append(f"{where} {path.name} is not gzipped, despite the .gz name.\n"
                                f"      Compress it:  gzip -c {path.name} > {path.name}.tmp && "
                                f"mv {path.name}.tmp {path.name}")

    if r1.is_file() and r2.is_file() and r1.stat().st_size and r2.stat().st_size:
        sample_size = 1000
        names1, names2 = first_reads(r1, sample_size), first_reads(r2, sample_size)
        if names1 is None or names2 is None:
            problems.append(f"{where} could not read {r1.name} or {r2.name} as gzipped FASTQ; "
                            "the file may be truncated or corrupt")
        elif not names1 or not names2:
            empty_file = r1.name if not names1 else r2.name
            problems.append(f"{where} {empty_file} contains no reads")
        else:
            # Every read must have a mate, in the same order. A truncated or
            # mismatched mate file is not a missing file and raises no error on
            # its own: the assembler just produces a worse assembly, and the
            # benchmark then measures that instead of the tools.
            mismatches = [(x, y) for x, y in zip(names1, names2) if x != y]
            if mismatches:
                first_x, first_y = mismatches[0]
                problems.append(
                    f"{where} {r1.name} and {r2.name} are not mates in the same order. "
                    f"{len(mismatches)} of the first {min(len(names1), len(names2))} read "
                    f"names differ, starting with " + repr(mismatches[0][0]) + " vs "
                    + repr(mismatches[0][1]) + ".\n"
                    "      PlasBench needs matched paired-end reads. If these came from SRA, "
                    "re-extract them with:\n"
                    "      fasterq-dump --split-files <accession>")

            # Counting is capped so a large pair costs a bounded read.
            cap = 200000
            count1, count2 = count_reads(r1, cap), count_reads(r2, cap)
            both_over_cap = count1 is not None and count2 is not None and count1 > cap and count2 > cap
            if count1 is not None and count2 is not None and count1 != count2 and not both_over_cap:
                shown1 = str(count1) if count1 <= cap else "more than " + str(cap)
                shown2 = str(count2) if count2 <= cap else "more than " + str(cap)
                problems.append(
                    f"{where} the two read files hold different numbers of reads "
                    f"({r1.name}: {shown1}, {r2.name}: {shown2}).\n"
                    "      Paired-end input needs one mate per read; a mismatch usually means "
                    "one file was truncated in transfer.")
        if r1.resolve() == r2.resolve():
            problems.append(f"{where} the forward and reverse files are the same file")

    # --- reference and truth ----------------------------------------------
    reference, truth = sdir / "reference.fna", sdir / "truth.tsv"
    report = sdir / "sequence_report.jsonl"
    if not accession:
        return  # operational sample: reads only, nothing to score against

    if not reference.is_file():
        problems.append(f"{where} missing reference.fna\n"
                        f"      Benchmarking scores tools against a known answer, so the complete\n"
                        f"      assembly of this isolate is required. Copy it in as:\n"
                        f"      {sdir}/reference.fna\n"
                        f"      For reconstruction WITHOUT scoring, leave assembly_accession empty "
                        f"in the sheet instead.")
        return
    if reference.stat().st_size == 0:
        problems.append(f"{where} reference.fna is empty")
        return

    ids, duplicates, empty = fasta_ids(reference)
    if not ids:
        problems.append(f"{where} reference.fna has no FASTA records (no '>' header lines)")
        return
    if duplicates:
        problems.append(f"{where} reference.fna repeats sequence id(s): {', '.join(sorted(set(duplicates)))}\n"
                        "      Ids must be unique; scoring maps predictions onto them by name.")
    if empty:
        warnings.append(f"{where} reference.fna has header(s) with no sequence: {', '.join(empty)}")

    if not truth.is_file() and not report.is_file():
        listing = "\n".join(f"        {seq_id}" for seq_id in ids[:8])
        more = f"\n        ... and {len(ids) - 8} more" if len(ids) > 8 else ""
        problems.append(
            f"{where} no truth.tsv and no sequence_report.jsonl\n"
            f"      PlasBench needs to know which of these sequences are plasmids:\n{listing}{more}\n"
            f"      Generate a template you then edit:\n"
            f"      plasbench init-local --sample {sample} --reads-1 {r1.name} "
            f"--reads-2 {r2.name} --reference reference.fna --force")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--samples", required=True)
    ap.add_argument("--data-dir", required=True)
    args = ap.parse_args()

    rows = read_sheet(Path(args.samples))
    if not rows:
        print(f"ERROR: no sample rows in {args.samples}", file=sys.stderr)
        return 2

    problems, warnings = [], []
    for row in rows:
        if (row.get("sample_id") or "").strip():
            check_sample(row, Path(args.data_dir), problems, warnings)

    for warning in warnings:
        print(f"  WARNING: {warning}", file=sys.stderr)

    if problems:
        print(f"\nLOCAL INPUTS NOT USABLE -- {len(problems)} problem(s) found "
              f"before anything was run:\n", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print("\n  Nothing has been downloaded, assembled or scored. Fix the items above\n"
              "  and re-run the same command. See section 5 of the README for the full\n"
              "  layout, or run:  plasbench init-local --help\n", file=sys.stderr)
        return 2

    print(f"local inputs verified: {len(rows)} sample(s) ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
