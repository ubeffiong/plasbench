#!/usr/bin/env python3
"""Scaffold one local isolate: file layout, truth-table template, sheet row.

Benchmarking your own reads means putting four files in the right place with
the right names, writing a truth table whose ids match the reference exactly,
and adding a sample-sheet row. Each of those is easy to get subtly wrong, and
a wrong truth table does not fail -- it silently changes the scores. This does
the mechanical parts and leaves exactly one judgement to the user.

Molecule types are filled in only where the FASTA header states them
("... plasmid pABC, complete sequence"). Anything else is written as REVIEW,
which `plasbench run` refuses to score until you replace it. Length and
sequence id are always taken from the reference, so they cannot disagree with
it.

The one thing this will not do is guess whether an unlabelled sequence is a
plasmid. That is the ground truth the whole benchmark rests on; a plausible
guess there would corrupt every number downstream.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import sys
from pathlib import Path

SHEET_COLUMNS = ("sample_id", "assembly_accession", "sra_run")
SAFE_SAMPLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def read_fasta_records(path: Path):
    """Yield (sequence_id, description, length) for each record."""
    seq_id = description = None
    length = 0
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith(">"):
                if seq_id is not None:
                    yield seq_id, description, length
                header = line[1:].strip()
                parts = header.split(None, 1)
                seq_id = parts[0] if parts else ""
                description = parts[1] if len(parts) > 1 else ""
                length = 0
            else:
                length += len(line.strip())
    if seq_id is not None:
        yield seq_id, description, length


def classify(description: str) -> str:
    """PLASMID / CHROMOSOME from an explicit header, else REVIEW."""
    text = description.lower()
    if "plasmid" in text:
        return "PLASMID"
    if "chromosome" in text or "complete genome" in text:
        return "CHROMOSOME"
    return "REVIEW"


def place(source: Path, destination: Path, mode: str) -> None:
    if destination.exists() and destination.samefile(source):
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        destination.unlink()
    if mode == "symlink":
        destination.symlink_to(source.resolve())
    elif mode == "hardlink":
        try:
            os.link(source, destination)
        except OSError:
            shutil.copy2(source, destination)
    else:
        shutil.copy2(source, destination)


def append_sheet_row(sheet: Path, sample: str, prefix: str, accession: str) -> str:
    """Add the sample's row, creating the sheet if needed. Returns a note."""
    existing = []
    if sheet.is_file():
        with open(sheet, newline="", encoding="utf-8") as handle:
            existing = [line for line in handle
                        if line.strip() and not line.lstrip().startswith("#")]
    if not existing:
        sheet.parent.mkdir(parents=True, exist_ok=True)
        with open(sheet, "w", newline="", encoding="utf-8") as handle:
            handle.write("\t".join(SHEET_COLUMNS) + "\n")
            handle.write(f"{sample}\t{accession}\t{prefix}\n")
        return f"created {sheet} with one row"
    for line in existing[1:]:
        if line.split("\t")[0].strip() == sample:
            return f"{sheet} already has a row for '{sample}'; left unchanged"
    with open(sheet, "a", newline="", encoding="utf-8") as handle:
        if not existing[-1].endswith("\n"):
            handle.write("\n")
        handle.write(f"{sample}\t{accession}\t{prefix}\n")
    return f"appended a row to {sheet}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", required=True, help="Sample id; becomes the directory name.")
    ap.add_argument("--reads-1", required=True, help="Forward reads (FASTQ, gzipped).")
    ap.add_argument("--reads-2", required=True, help="Reverse reads (FASTQ, gzipped).")
    ap.add_argument("--reference", help="Complete assembly FASTA for this isolate (the ground truth). "
                                        "Omit only for operational reconstruction, which is not scored.")
    ap.add_argument("--sequence-report", help="NCBI sequence_report.jsonl, if you have one. "
                                              "Supplying it means no truth table has to be written by hand.")
    ap.add_argument("--data-dir", default="data", help="Where sample directories live (default: data).")
    ap.add_argument("--samples", default="config/local.tsv", help="Sample sheet to create or append to.")
    ap.add_argument("--prefix", help="Read filename prefix (default: the sample id).")
    ap.add_argument("--accession", default="LOCAL",
                    help="assembly_accession column value (default: LOCAL; nothing is downloaded).")
    ap.add_argument("--link", choices=("copy", "symlink", "hardlink"), default="copy",
                    help="How to place the input files (default: copy).")
    ap.add_argument("--force", action="store_true", help="Overwrite an existing truth.tsv.")
    args = ap.parse_args()

    if not SAFE_SAMPLE.match(args.sample):
        sys.exit(f"ERROR: unsafe sample id '{args.sample}'. Use letters, digits, dot, dash "
                 "or underscore, starting with a letter or digit -- it becomes a directory name.")

    prefix = args.prefix or args.sample
    if prefix.endswith(("_1", "_2")):
        sys.exit(f"ERROR: --prefix '{prefix}' must not end in _1 or _2; "
                 "those are added for you.")

    reads1, reads2 = Path(args.reads_1), Path(args.reads_2)
    for path in (reads1, reads2):
        if not path.is_file():
            sys.exit(f"ERROR: no such file: {path}")
    if not (reads1.name.endswith(".gz") and reads2.name.endswith(".gz")):
        sys.exit("ERROR: reads must be gzipped (.fastq.gz). Compress them with: gzip <file>")
    if reads1.resolve() == reads2.resolve():
        sys.exit("ERROR: --reads-1 and --reads-2 are the same file; PlasBench needs paired reads.")

    sample_dir = Path(args.data_dir) / args.sample
    sample_dir.mkdir(parents=True, exist_ok=True)

    place(reads1, sample_dir / f"{prefix}_1.fastq.gz", args.link)
    place(reads2, sample_dir / f"{prefix}_2.fastq.gz", args.link)
    print(f"reads      -> {sample_dir}/{prefix}_1.fastq.gz , {prefix}_2.fastq.gz")

    review_rows = 0
    if args.reference:
        reference = Path(args.reference)
        if not reference.is_file():
            sys.exit(f"ERROR: no such file: {reference}")
        place(reference, sample_dir / "reference.fna", args.link)
        print(f"reference  -> {sample_dir}/reference.fna")

        if args.sequence_report:
            report = Path(args.sequence_report)
            if not report.is_file():
                sys.exit(f"ERROR: no such file: {report}")
            place(report, sample_dir / "sequence_report.jsonl", args.link)
            print(f"report     -> {sample_dir}/sequence_report.jsonl "
                  "(truth table will be built from this; nothing to edit)")
        else:
            truth = sample_dir / "truth.tsv"
            if truth.is_file() and not args.force:
                print(f"truth      -> {truth} already exists; left unchanged (use --force to rewrite)")
            else:
                records = list(read_fasta_records(reference))
                if not records:
                    sys.exit(f"ERROR: no FASTA records found in {reference}")
                with open(truth, "w", newline="", encoding="utf-8") as handle:
                    writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
                    writer.writerow(["sequence_id", "molecule_type", "length"])
                    for seq_id, description, length in records:
                        molecule = classify(description)
                        review_rows += molecule == "REVIEW"
                        writer.writerow([seq_id, molecule, length])
                print(f"truth      -> {truth} ({len(records)} sequence(s), "
                      f"{review_rows} needing review)")
    else:
        print("reference  -> not supplied; this sample can be reconstructed but NOT scored")

    print(append_sheet_row(Path(args.samples), args.sample, prefix, args.accession))

    print()
    if review_rows:
        print(f"ACTION REQUIRED: {review_rows} sequence(s) in {sample_dir}/truth.tsv say REVIEW.")
        print("Their FASTA headers did not state whether they are plasmid or chromosome, and")
        print("PlasBench will not guess -- that is the ground truth every score depends on.")
        print("Open the file and replace each REVIEW with PLASMID or CHROMOSOME:")
        print(f"    nano {sample_dir}/truth.tsv")
        print("The run refuses to start while any REVIEW remains.")
    else:
        print("Next:")
        print(f"    REQUIRE_CURATED_METADATA=0 plasbench run --samples {args.samples} --local-inputs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
