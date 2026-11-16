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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from read_pairing import pair_fastq_files  # noqa: E402

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


def place(source, destination: Path, mode: str) -> None:
    """Put `source` at `destination`. `source` may be a list of files (one isolate sequenced over several lanes): they are joined in order. Gzip files can be
    concatenated byte for byte, and the result is one valid gzip file, so nothing is decompressed."""
    if isinstance(source, (list, tuple)):
        if len(source) == 1:
            source = source[0]
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() or destination.is_symlink():
                destination.unlink()
            with open(destination, "wb") as out:
                for part in source:
                    with open(part, "rb") as handle:
                        shutil.copyfileobj(handle, out, 1 << 20)
            return
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


def append_sheet_row(sheet: Path, sample: str, prefix: str, accession: str, extra: dict | None = None) -> str:
    """Add the sample's row, creating the sheet if needed. Returns a note.

    `extra` holds optional columns (organism, gram_group, ...). They are written under the sheet's own header names; a column the sheet does not have yet is
    added to the header (earlier rows get an empty value), so a sheet made by `init-local` and a sheet downloaded from the template both accept them.
    The template's EXAMPLE_ row is dropped the first time a real isolate is added.
    """
    values = {"sample_id": sample, "assembly_accession": accession, "sra_run": prefix}
    values.update({k: v for k, v in (extra or {}).items() if v})
    lines = []
    if sheet.is_file():
        with open(sheet, newline="", encoding="utf-8") as handle:
            lines = [line.rstrip("\r\n") for line in handle]
    data = [(i, line) for i, line in enumerate(lines) if line.strip() and not line.lstrip().startswith("#")]
    if not data:
        sheet.parent.mkdir(parents=True, exist_ok=True)
        header = list(SHEET_COLUMNS) + [k for k in values if k not in SHEET_COLUMNS]
        out = [line for line in lines if line.lstrip().startswith("#")]
        out += ["\t".join(header), "\t".join(values.get(c, "") for c in header)]
        with open(sheet, "w", newline="", encoding="utf-8") as handle:
            handle.write("\n".join(out) + "\n")
        return f"created {sheet} with one row"
    header_at, header_line = data[0]
    header = header_line.split("\t")
    for _, line in data[1:]:
        if line.split("\t")[0].strip() == sample:
            return f"{sheet} already has a row for '{sample}'; left unchanged"
    new_columns = [k for k in values if k not in header]
    keep = []
    for i, line in enumerate(lines):
        if i == header_at:
            keep.append("\t".join(header + new_columns))
        elif (i, line) in data[1:]:
            if line.split("\t")[0].startswith("EXAMPLE_"):
                continue   # the template's illustration, not an isolate
            keep.append(line + "\t" * len(new_columns) if line.strip() else line)
        else:
            keep.append(line)
    header = header + new_columns
    keep.append("\t".join(values.get(c, "") for c in header))
    with open(sheet, "w", newline="", encoding="utf-8") as handle:
        handle.write("\n".join(keep) + "\n")
    return f"appended a row to {sheet}"


def stage_isolate(sample, prefix, reads1, reads2, reference_arg, report_arg, data_dir, samples, accession, link, force, truth_arg=None, extra=None) -> int:
    """Place one isolate's files, write its truth table when there is none, and add its sheet row. Returns how many truth rows still say REVIEW.

    Shared by `plasbench init-local` (one isolate you name) and `plasbench intake stage` (every isolate found in a folder), so both place files the same way.
    `reads1`/`reads2` may each be one file or a list of lane files to join."""
    sample_dir = Path(data_dir) / sample
    sample_dir.mkdir(parents=True, exist_ok=True)

    place(reads1, sample_dir / f"{prefix}_1.fastq.gz", link)
    place(reads2, sample_dir / f"{prefix}_2.fastq.gz", link)
    print(f"reads      -> {sample_dir}/{prefix}_1.fastq.gz , {prefix}_2.fastq.gz")

    review_rows = 0
    if reference_arg:
        reference = Path(reference_arg)
        if not reference.is_file():
            raise SystemExit(f"ERROR: no such file: {reference}")
        place(reference, sample_dir / "reference.fna", link)
        print(f"reference  -> {sample_dir}/reference.fna")

        if report_arg:
            report = Path(report_arg)
            if not report.is_file():
                raise SystemExit(f"ERROR: no such file: {report}")
            place(report, sample_dir / "sequence_report.jsonl", link)
            print(f"report     -> {sample_dir}/sequence_report.jsonl "
                  "(truth table will be built from this; nothing to edit)")
        elif truth_arg:
            place(Path(truth_arg), sample_dir / "truth.tsv", link)
            print(f"truth      -> {sample_dir}/truth.tsv (your own table, copied as it is; check it with `plasbench intake check`)")
        else:
            truth = sample_dir / "truth.tsv"
            if truth.is_file() and not force:
                print(f"truth      -> {truth} already exists; left unchanged (use --force to rewrite)")
            else:
                records = list(read_fasta_records(reference))
                if not records:
                    raise SystemExit(f"ERROR: no FASTA records found in {reference}")
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

    print(append_sheet_row(Path(samples), sample, prefix, accession, extra))
    return review_rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", required=True, help="Sample id; becomes the directory name.")
    ap.add_argument("--reads-1", help="Forward reads (FASTQ, gzipped; .fastq.gz or .fq.gz).")
    ap.add_argument("--reads-2", help="Reverse reads (FASTQ, gzipped).")
    ap.add_argument("--reads-dir", help="Instead of --reads-1/--reads-2: a directory holding one pair named "
                                        "_1/_2, _R1/_R2 or _R1_001/_R2_001 (.fastq.gz or .fq.gz). With several "
                                        "pairs, the one named like --prefix or --sample is used.")
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

    if args.reads_dir:
        if args.reads_1 or args.reads_2:
            sys.exit("ERROR: give either --reads-dir or --reads-1/--reads-2, not both.")
        if not Path(args.reads_dir).is_dir():
            sys.exit(f"ERROR: no such directory: {args.reads_dir}")
        pairs = pair_fastq_files(args.reads_dir)
        chosen = [p for p in pairs if p[0] in (prefix, args.sample)] or (pairs if len(pairs) == 1 else [])
        if not chosen:
            names = ", ".join(p[0] for p in pairs) or "none"
            sys.exit(f"ERROR: could not pick one read pair in {args.reads_dir} (pairs found: {names}). "
                     "Name one with --prefix or --sample, or pass --reads-1/--reads-2.")
        _, reads1, reads2 = chosen[0]
    elif args.reads_1 and args.reads_2:
        reads1, reads2 = Path(args.reads_1), Path(args.reads_2)
    else:
        sys.exit("ERROR: give --reads-1 and --reads-2, or --reads-dir.")
    for path in (reads1, reads2):
        if not path.is_file():
            sys.exit(f"ERROR: no such file: {path}")
    if not (reads1.name.endswith(".gz") and reads2.name.endswith(".gz")):
        sys.exit("ERROR: reads must be gzipped (.fastq.gz). Compress them with: gzip <file>")
    if reads1.resolve() == reads2.resolve():
        sys.exit("ERROR: --reads-1 and --reads-2 are the same file; PlasBench needs paired reads.")

    review_rows = stage_isolate(args.sample, prefix, reads1, reads2, args.reference, args.sequence_report,
                                Path(args.data_dir), Path(args.samples), args.accession, args.link, args.force)
    sample_dir = Path(args.data_dir) / args.sample

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
