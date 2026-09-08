#!/usr/bin/env python3
"""Regression for python/audit_three_class_scoring.py (Phase E, Part 14 --
a one-off research script, never wired into the pipeline): parses geNomad's
own verified virus_summary.tsv shape (a `coordinates` column that is 'NA'
for a non-integrated virus, or a real "<start>-<end>" string for an
integrated provirus; a `seq_name` column following
"<host_id>|provirus_<start>_<end>"), cross-references each integrated call's
host sequence against truth.tsv's own molecule_type, and never fabricates a
finding when geNomad is unavailable or found nothing. No real geNomad
binary is invoked; shutil.which/subprocess.run are monkeypatched, matching
this project's established convention for testing code that shells out to
bioinformatics tools.
"""
import csv
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))

import audit_three_class_scoring as audit  # noqa: E402


def write_truth(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["sequence_id", "molecule_type", "length"])
        writer.writerows(rows)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # --- parse_provirus_calls: real integrated calls only, 'NA' rows
        # (non-integrated viruses, e.g. a free plasmid-like phage) skipped. ---
        summary = tmp / "s1_virus_summary.tsv"
        summary.write_text(
            "seq_name\ttopology\tcoordinates\tlength\n"
            "plas1|provirus_100_500\tProvirus\t100-500\t401\n"
            "free_virus_1\tDTR\tNA\t8000\n"
            "chr1|provirus_2000_2500\tProvirus\t2000-2500\t501\n"
        )
        calls = audit.parse_provirus_calls(summary)
        assert calls == [("plas1", 100, 500), ("chr1", 2000, 2500)], calls
        print("parse_provirus_calls extracts only INTEGRATED calls, skipping 'NA' (non-integrated) rows -> PASS")

        # --- read_truth: sequence_id -> (molecule_type, length). ---
        truth = tmp / "truth.tsv"
        write_truth(truth, [("chr1", "CHROMOSOME", "5000000"), ("plas1", "PLASMID", "50000")])
        labels = audit.read_truth(truth)
        assert labels == {"chr1": ("CHROMOSOME", 5000000), "plas1": ("PLASMID", 50000)}, labels
        print("read_truth parses sequence_id -> (molecule_type, length) correctly -> PASS")

    original_which = audit.shutil.which
    original_run = audit.subprocess.run
    try:
        # --- main(): a missing --reference/--truth path fails loudly (sys.exit(1)
        # with a clear message), never an unhandled FileNotFoundError traceback. ---
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            old_argv = sys.argv
            try:
                sys.argv = ["audit_three_class_scoring.py", "--reference", str(tmp / "no_such_reference.fna"),
                           "--truth", str(tmp / "no_such_truth.tsv"), "--sample", "s1",
                           "--genomad-db", "db", "--out", str(tmp / "out.tsv")]
                try:
                    audit.main()
                    raise AssertionError("expected SystemExit for a missing --reference path")
                except SystemExit as exc:
                    assert exc.code == 1
            finally:
                sys.argv = old_argv
        print("main() with a missing --reference/--truth path fails loudly (sys.exit(1)), never a raw traceback -> PASS")

        # --- main(): genomad missing -> a clean header-only output, never a
        # fabricated 'no provirus found' claim. ---
        audit.shutil.which = lambda name: None
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            reference = tmp / "reference.fna"
            reference.write_text(">chr1\nACGT\n>plas1\nACGT\n")
            truth = tmp / "truth.tsv"
            write_truth(truth, [("chr1", "CHROMOSOME", "4"), ("plas1", "PLASMID", "4")])
            out = tmp / "out.tsv"
            old_argv = sys.argv
            try:
                sys.argv = ["audit_three_class_scoring.py", "--reference", str(reference), "--truth", str(truth),
                           "--sample", "s1", "--genomad-db", str(tmp / "db"), "--out", str(out)]
                audit.main()
            finally:
                sys.argv = old_argv
            with open(out, newline="", encoding="utf-8") as handle:
                data_rows = list(csv.reader(handle, delimiter="\t"))
            assert len(data_rows) == 1  # header only
        print("main() with genomad not installed writes a clean header-only output, never a fabricated finding -> PASS")

        # --- main(): full end-to-end, real provirus calls cross-referenced
        # against truth, fraction-of-host-sequence computed correctly. ---
        audit.shutil.which = lambda name: "/usr/bin/genomad" if name == "genomad" else None

        def fake_run(command, **kwargs):
            # command shape: [genomad, "end-to-end", "--threads", N, fasta, out_dir, db]
            idx = command.index("end-to-end")
            fasta = Path(command[idx + 3])
            out_dir = Path(command[idx + 4])
            db = command[idx + 5]
            # Regression pin: run_genomad() must append the fixed "genomad_db"
            # leaf subdirectory to the caller's --genomad-db value itself,
            # exactly like scripts/04_run_tools.sh's own run_genomad() does
            # with "$GENOMAD_DB/genomad_db" -- a caller passing the SAME
            # GENOMAD_DB config value must reach the real database, not its
            # parent directory (a real bug this test specifically catches).
            assert db == str(Path("configured_genomad_db_parent") / "genomad_db"), db
            prefix = fasta.stem
            summary_dir = out_dir / f"{prefix}_summary"
            summary_dir.mkdir(parents=True, exist_ok=True)
            (summary_dir / f"{prefix}_virus_summary.tsv").write_text(
                "seq_name\ttopology\tcoordinates\tlength\n"
                "plas1|provirus_1_25000\tProvirus\t1-25000\t25000\n"
                "chr1|provirus_100_600\tProvirus\t100-600\t501\n"
                "unknown_seq|provirus_1_100\tProvirus\t1-100\t100\n"
            )
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        audit.subprocess.run = fake_run
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            reference = tmp / "reference.fna"
            reference.write_text(">chr1\n" + "A" * 10 + "\n>plas1\n" + "C" * 10 + "\n")
            truth = tmp / "truth.tsv"
            write_truth(truth, [("chr1", "CHROMOSOME", "1000000"), ("plas1", "PLASMID", "50000")])
            out = tmp / "out.tsv"
            old_argv = sys.argv
            try:
                sys.argv = ["audit_three_class_scoring.py", "--reference", str(reference), "--truth", str(truth),
                           "--sample", "s1", "--genomad-db", "configured_genomad_db_parent",
                           "--out", str(out), "--threads", "2"]
                audit.main()
            finally:
                sys.argv = old_argv
            with open(out, newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
        by_host = {r["host_sequence_id"]: r for r in rows}
        assert set(by_host) == {"plas1", "chr1"}, by_host  # unknown_seq (absent from truth) excluded
        assert by_host["plas1"]["molecule_type"] == "PLASMID"
        assert by_host["plas1"]["provirus_length_bp"] == "25000"
        assert by_host["plas1"]["fraction_of_host_sequence"] == "0.5000", by_host["plas1"]
        assert by_host["chr1"]["molecule_type"] == "CHROMOSOME"
        assert by_host["chr1"]["fraction_of_host_sequence"] == "0.0005", by_host["chr1"]
        print("main() cross-references real provirus calls against truth, computing molecule_type and fraction-of-host correctly -> PASS")
        print("a provirus call on a sequence absent from truth.tsv is excluded, not fabricated as a finding -> PASS")
    finally:
        audit.shutil.which = original_which
        audit.subprocess.run = original_run

    print("\nALL THREE-CLASS SCORING AUDIT TESTS PASSED")


if __name__ == "__main__":
    main()
