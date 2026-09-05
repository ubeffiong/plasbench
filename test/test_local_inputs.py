#!/usr/bin/env python3
"""Regression for `plasbench init-local` and the local-input validators.

Supplying your own reads means staging files by hand and writing a truth table,
and almost every way that goes wrong is silent. A mistyped sequence id scores as
a plasmid nobody recovered; an omitted sequence lets chromosomal contamination
go uncounted; an unrecognised molecule_type is scored as CHROMOSOME; a FASTQ
that is not really gzipped fails hours later inside a tool. These tests pin the
behaviour that turns each of those into an error before any tool runs.
"""
import gzip
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT = ROOT / "python" / "init_local_sample.py"
VALIDATE_TRUTH = ROOT / "python" / "validate_truth_table.py"
VALIDATE_INPUTS = ROOT / "python" / "validate_local_inputs.py"

REFERENCE = (
    ">NZ_CP01.1 Escherichia coli strain X chromosome, complete genome\n" + "ACGT" * 250 + "\n"
    ">NZ_CP02.1 Escherichia coli strain X plasmid pABC, complete sequence\n" + "ACGT" * 50 + "\n"
    ">contig_3\n" + "ACGT" * 25 + "\n"
)
FASTQ_RECORD = "@r1\nACGT\n+\nIIII\n"


def check(name, condition, detail=""):
    if not condition:
        print("FAIL: " + name + "\n" + detail, file=sys.stderr)
        raise SystemExit(1)
    print("  " + name + " ? True")


def validate_truth(truth, reference, *extra):
    return subprocess.run([sys.executable, str(VALIDATE_TRUTH), "--truth", str(truth),
                           "--reference", str(reference), *extra],
                          capture_output=True, text=True)


def validate_inputs(sheet, data_dir):
    return subprocess.run([sys.executable, str(VALIDATE_INPUTS), "--samples", str(sheet),
                           "--data-dir", str(data_dir)], capture_output=True, text=True)


def write_gzip(path, text):
    with gzip.open(path, "wt") as handle:
        handle.write(text)


# --- init-local scaffolding, and the truth-table template it writes -----------
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    (tmp / "assembly.fasta").write_text(REFERENCE, encoding="utf-8")
    for name in ("r1.fastq.gz", "r2.fastq.gz"):
        write_gzip(tmp / name, FASTQ_RECORD)

    result = subprocess.run(
        [sys.executable, str(INIT), "--sample", "iso1",
         "--reads-1", str(tmp / "r1.fastq.gz"), "--reads-2", str(tmp / "r2.fastq.gz"),
         "--reference", str(tmp / "assembly.fasta"),
         "--data-dir", str(tmp / "data"), "--samples", str(tmp / "sheet.tsv")],
        capture_output=True, text=True)
    check("init-local succeeds", result.returncode == 0, result.stderr)

    sample_dir = tmp / "data" / "iso1"
    check("reads are placed with the _1/_2 names the pipeline expects",
          (sample_dir / "iso1_1.fastq.gz").is_file() and (sample_dir / "iso1_2.fastq.gz").is_file())
    check("reference is placed as reference.fna", (sample_dir / "reference.fna").is_file())

    truth = sample_dir / "truth.tsv"
    rows = {}
    for line in truth.read_text(encoding="utf-8").splitlines()[1:]:
        fields = line.split("\t")
        rows[fields[0]] = fields[1]
    check("a header saying 'chromosome' is labelled CHROMOSOME",
          rows["NZ_CP01.1"] == "CHROMOSOME", str(rows))
    check("a header saying 'plasmid' is labelled PLASMID",
          rows["NZ_CP02.1"] == "PLASMID", str(rows))
    check("an unlabelled sequence is REVIEW, never guessed",
          rows["contig_3"] == "REVIEW", str(rows))
    check("the user is told action is required",
          "ACTION REQUIRED" in result.stdout, result.stdout)

    sheet_text = (tmp / "sheet.tsv").read_text(encoding="utf-8")
    check("a sample-sheet row is written", "iso1\tLOCAL\tiso1" in sheet_text, sheet_text)

    subprocess.run([sys.executable, str(INIT), "--sample", "iso2",
                    "--reads-1", str(tmp / "r1.fastq.gz"), "--reads-2", str(tmp / "r2.fastq.gz"),
                    "--data-dir", str(tmp / "data"), "--samples", str(tmp / "sheet.tsv")],
                   capture_output=True, text=True)
    sheet_text = (tmp / "sheet.tsv").read_text(encoding="utf-8")
    check("a second sample appends and keeps the first",
          "iso1\t" in sheet_text and "iso2\t" in sheet_text, sheet_text)

    # --- truth-table validation ---------------------------------------------
    reference = sample_dir / "reference.fna"
    check("an unedited REVIEW is rejected", validate_truth(truth, reference).returncode == 2)

    good = ("sequence_id\tmolecule_type\tlength\n"
            "NZ_CP01.1\tCHROMOSOME\t1000\n"
            "NZ_CP02.1\tPLASMID\t200\n"
            "contig_3\tPLASMID\t100\n")
    truth.write_text(good, encoding="utf-8")
    out = validate_truth(truth, reference, "--check-lengths")
    check("a correct table passes, lengths included", out.returncode == 0, out.stderr)

    truth.write_text(good.replace("NZ_CP02.1", "nz_cp02.1"), encoding="utf-8")
    out = validate_truth(truth, reference)
    check("a wrong-case id is rejected and the right one suggested",
          out.returncode == 2 and "Did you mean 'NZ_CP02.1'" in out.stderr, out.stderr)

    truth.write_text(good.replace("contig_3\tPLASMID\t100\n", ""), encoding="utf-8")
    out = validate_truth(truth, reference)
    check("a reference sequence missing from the table is rejected",
          out.returncode == 2 and "missing from the truth table" in out.stderr, out.stderr)

    truth.write_text(good.replace("\tPLASMID\t200", "\tplasmids\t200"), encoding="utf-8")
    out = validate_truth(truth, reference)
    check("an unrecognised molecule_type is rejected, not silently CHROMOSOME",
          out.returncode == 2 and "not PLASMID or CHROMOSOME" in out.stderr, out.stderr)

    truth.write_text(good.replace("\t", " "), encoding="utf-8")
    out = validate_truth(truth, reference)
    check("spaces instead of tabs are rejected with that named as the cause",
          out.returncode == 2 and "must be a TAB" in out.stderr, out.stderr)

    truth.write_text(good.replace("\t1000", "\t999999"), encoding="utf-8")
    out = validate_truth(truth, reference, "--check-lengths")
    check("a length that disagrees with the reference is rejected",
          out.returncode == 2 and "does not match" in out.stderr, out.stderr)

# --- staged-input validation --------------------------------------------------
# Existence is the weakest possible check. These are the ways a staged input is
# present but unusable, each of which otherwise fails hours later or silently.
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    data = tmp / "data"
    (data / "iso1").mkdir(parents=True)
    sheet = tmp / "sheet.tsv"
    sheet.write_text("sample_id\tassembly_accession\tsra_run\niso1\tLOCAL\tmyreads\n",
                     encoding="utf-8")

    out = validate_inputs(sheet, data)
    check("missing reads are reported before anything runs",
          out.returncode == 2 and "missing forward reads" in out.stderr, out.stderr)

    (data / "iso1" / "myreads_1.fastq.gz").write_bytes(b"this is not gzipped")
    write_gzip(data / "iso1" / "myreads_2.fastq.gz", FASTQ_RECORD)
    out = validate_inputs(sheet, data)
    check("a .gz file that is not gzipped is caught, with the fix command",
          out.returncode == 2 and "is not gzipped" in out.stderr and "gzip -c" in out.stderr,
          out.stderr)

    write_gzip(data / "iso1" / "myreads_1.fastq.gz", FASTQ_RECORD)
    out = validate_inputs(sheet, data)
    check("a missing reference is explained, with the no-scoring alternative",
          out.returncode == 2 and "missing reference.fna" in out.stderr
          and "leave assembly_accession empty" in out.stderr, out.stderr)

    (data / "iso1" / "reference.fna").write_text(">chr1 a\nACGTACGT\n>chr1 b\nACGT\n",
                                                 encoding="utf-8")
    out = validate_inputs(sheet, data)
    check("duplicate sequence ids in the reference are rejected",
          out.returncode == 2 and "repeats sequence id" in out.stderr, out.stderr)

    (data / "iso1" / "reference.fna").write_text(">chr1 a\nACGTACGT\n>pA b\nACGT\n",
                                                 encoding="utf-8")
    out = validate_inputs(sheet, data)
    check("a missing truth table lists the sequences and offers init-local",
          out.returncode == 2 and "no truth.tsv" in out.stderr
          and "plasbench init-local" in out.stderr, out.stderr)

    (data / "iso1" / "truth.tsv").write_text(
        "sequence_id\tmolecule_type\tlength\nchr1\tCHROMOSOME\t8\npA\tPLASMID\t4\n",
        encoding="utf-8")
    out = validate_inputs(sheet, data)
    check("a correctly staged sample passes", out.returncode == 0, out.stderr)

    # An operational sample declares no accession, so it needs no reference.
    (data / "iso2").mkdir()
    write_gzip(data / "iso2" / "op_1.fastq.gz", FASTQ_RECORD)
    write_gzip(data / "iso2" / "op_2.fastq.gz", FASTQ_RECORD)
    sheet.write_text(sheet.read_text(encoding="utf-8") + "iso2\t\top\n", encoding="utf-8")
    out = validate_inputs(sheet, data)
    check("an operational sample needs no reference", out.returncode == 0, out.stderr)

print("ALL LOCAL INPUT TESTS PASSED")
