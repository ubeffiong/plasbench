#!/usr/bin/env python3
"""Regression for python/simulate_reads.py: builds InSilicoSeq's
--coverage_file with the SAME requested depth for every reference contig
(chromosome and plasmid(s) alike -- a documented simplifying assumption),
locates the exact "<prefix>_R1.fastq.gz"/"<prefix>_R2.fastq.gz" filenames
--compress actually produces (verified from InSilicoSeq's own source, not
guessed), pipes badread's stdout through gzip (matching
make_depth_ladder.py's own Popen-piping convention), and fails loudly (not
silently) when either tool is missing or exits non-zero. No real external
binaries are invoked; subprocess/shutil.which are monkeypatched, matching
this project's established convention for testing code that shells out to
bioinformatics tools.
"""
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))

import simulate_reads as sr  # noqa: E402


def write_fasta(path, records):
    with open(path, "w") as handle:
        for header, seq in records:
            handle.write(f">{header}\n{seq}\n")


def fake_which(installed):
    return lambda name: f"/usr/bin/{name}" if name in installed else None


def main():
    with tempfile.TemporaryDirectory() as tmp:
        fasta = Path(tmp) / "reference.fna"
        write_fasta(fasta, [("chr1", "A" * 100), ("plas1", "C" * 50)])

        # --- read_fasta_ids: real parsing. ---
        records = sr.read_fasta_ids(fasta)
        assert records == [("chr1", 100), ("plas1", 50)], records
        print("read_fasta_ids parses seq_id/length preserving file order -> PASS")

    original_which = sr.shutil.which
    original_run = sr.subprocess.run
    original_popen = sr.subprocess.Popen
    try:
        # --- main(): iss missing -> hard failure, never a silent skip. ---
        sr.shutil.which = fake_which([])
        with tempfile.TemporaryDirectory() as tmp:
            fasta = Path(tmp) / "reference.fna"
            write_fasta(fasta, [("chr1", "A" * 100)])
            old_argv = sys.argv
            try:
                sys.argv = ["simulate_reads.py", "--reference", str(fasta), "--out-r1", str(Path(tmp) / "r1.fastq.gz"),
                           "--out-r2", str(Path(tmp) / "r2.fastq.gz"), "--out-long", str(Path(tmp) / "long.fastq.gz"),
                           "--out-provenance", str(Path(tmp) / "prov.json"), "--seed", "1",
                           "--short-depth", "30", "--long-depth", "20"]
                try:
                    sr.main()
                    raise AssertionError("expected SystemExit when iss is missing")
                except SystemExit as exc:
                    assert exc.code == 1
            finally:
                sys.argv = old_argv
        print("main() with iss (InSilicoSeq) not installed exits non-zero, not a silent skip -> PASS")

        # --- main(): badread missing -> hard failure. ---
        sr.shutil.which = fake_which(["iss"])
        with tempfile.TemporaryDirectory() as tmp:
            fasta = Path(tmp) / "reference.fna"
            write_fasta(fasta, [("chr1", "A" * 100)])
            old_argv = sys.argv
            try:
                sys.argv = ["simulate_reads.py", "--reference", str(fasta), "--out-r1", str(Path(tmp) / "r1.fastq.gz"),
                           "--out-r2", str(Path(tmp) / "r2.fastq.gz"), "--out-long", str(Path(tmp) / "long.fastq.gz"),
                           "--out-provenance", str(Path(tmp) / "prov.json"), "--seed", "1",
                           "--short-depth", "30", "--long-depth", "20"]
                try:
                    sr.main()
                    raise AssertionError("expected SystemExit when badread is missing")
                except SystemExit as exc:
                    assert exc.code == 1
            finally:
                sys.argv = old_argv
        print("main() with badread not installed exits non-zero, not a silent skip -> PASS")

        # --- simulate_short_reads: builds a coverage_file with the SAME
        # depth for every contig, and locates the real "_R1.fastq.gz"/
        # "_R2.fastq.gz" filenames --compress actually produces. ---
        sr.shutil.which = fake_which(["iss", "badread"])
        with tempfile.TemporaryDirectory() as tmp:
            fasta = Path(tmp) / "reference.fna"
            write_fasta(fasta, [("chr1", "A" * 100), ("plas1", "C" * 50)])
            records = sr.read_fasta_ids(fasta)
            work_dir = Path(tmp) / "work"; work_dir.mkdir()
            captured_coverage = {}

            def fake_run_iss(command, **kwargs):
                assert command[0] == "iss" and command[1] == "generate"
                coverage_path = Path(command[command.index("--coverage_file") + 1])
                captured_coverage["rows"] = coverage_path.read_text().strip().splitlines()
                prefix = command[command.index("--output") + 1]
                Path(f"{prefix}_R1.fastq.gz").write_bytes(b"r1")
                Path(f"{prefix}_R2.fastq.gz").write_bytes(b"r2")
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            sr.subprocess.run = fake_run_iss
            result, _ = sr.simulate_short_reads("iss", fasta, records, 60, "novaseq", 42, 4, work_dir)
            assert result is not None, "expected a (r1, r2) result"
            r1, r2 = result
            assert r1.read_bytes() == b"r1" and r2.read_bytes() == b"r2"
            assert captured_coverage["rows"] == ["chr1\t60", "plas1\t60"], captured_coverage["rows"]
        print("simulate_short_reads writes a uniform-depth coverage_file and finds the real _R1/_R2.fastq.gz output -> PASS")

        # --- simulate_short_reads: iss exits non-zero -> None, not a crash. ---
        with tempfile.TemporaryDirectory() as tmp:
            fasta = Path(tmp) / "reference.fna"
            write_fasta(fasta, [("chr1", "A" * 100)])
            records = sr.read_fasta_ids(fasta)
            work_dir = Path(tmp) / "work"; work_dir.mkdir()
            sr.subprocess.run = lambda command, **kwargs: subprocess.CompletedProcess(command, 1, stdout="", stderr="boom")
            result, _ = sr.simulate_short_reads("iss", fasta, records, 60, "novaseq", 42, 4, work_dir)
            assert result is None
        print("simulate_short_reads returns None (not a crash) when iss generate exits non-zero -> PASS")

        # --- simulate_long_reads: badread's stdout piped through gzip;
        # success writes the target file. ---
        with tempfile.TemporaryDirectory() as tmp:
            out_long = Path(tmp) / "long.fastq.gz"

            class FakeBadread:
                def __init__(self):
                    self.stdout = io.BytesIO()
                    self.returncode = 0
                def communicate(self):
                    return (None, b"")

            def fake_popen(command, **kwargs):
                assert command[0] == "badread" and command[1] == "simulate"
                assert "--length" not in command, "badread must NOT be forced to a fixed read length"
                return FakeBadread()

            def fake_run_gzip(command, **kwargs):
                assert command == ["gzip", "-c"]
                kwargs["stdout"].write(b"fake-compressed-long-reads")
                return subprocess.CompletedProcess(command, 0)

            sr.subprocess.Popen = fake_popen
            sr.subprocess.run = fake_run_gzip
            ok, command = sr.simulate_long_reads("badread", "reference.fna", 40, "nanopore2020", "nanopore2020", 7, out_long)
            assert ok is True
            assert out_long.read_bytes() == b"fake-compressed-long-reads"
            assert "40x" in command, command
        print("simulate_long_reads pipes badread through gzip, omits a fixed --length, and writes the output -> PASS")

        # --- simulate_long_reads: badread exits non-zero -> False, output
        # file removed, not left as a truncated/corrupt partial file. ---
        with tempfile.TemporaryDirectory() as tmp:
            out_long = Path(tmp) / "long.fastq.gz"

            class FailingBadread:
                def __init__(self):
                    self.stdout = io.BytesIO()
                    self.returncode = 1
                def communicate(self):
                    return (None, b"badread error")

            sr.subprocess.Popen = lambda command, **kwargs: FailingBadread()
            sr.subprocess.run = lambda command, **kwargs: kwargs["stdout"].write(b"partial") or subprocess.CompletedProcess(command, 0)
            ok, _ = sr.simulate_long_reads("badread", "reference.fna", 40, "nanopore2020", "nanopore2020", 7, out_long)
            assert ok is False
            assert not out_long.exists(), "a failed badread run must not leave a partial output file behind"
        print("simulate_long_reads removes the output file (not a silent partial) when badread fails -> PASS")
    finally:
        sr.shutil.which = original_which
        sr.subprocess.run = original_run
        sr.subprocess.Popen = original_popen

    print("\nALL SIMULATE READS TESTS PASSED")


if __name__ == "__main__":
    main()
