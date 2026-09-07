#!/usr/bin/env python3
"""Regression for python/build_hybrid_truth.py: the new capability that
builds a truth reference in-house via hybrid assembly (Unicycler), for
cohort sources that deposit raw reads but never submitted a formal Complete
Genome assembly. Confirms: (1) chromosome/plasmid labeling comes ONLY from
Unicycler's own circular=/length topology, never a gene-content classifier;
(2) a non-circular contig, or an ambiguous multi-chromosome-sized result,
is REJECTED rather than guessed at, mirroring every other "never guess"
curation step in this project; (3) end-to-end, via a faked `unicycler`
subprocess call (no real Unicycler run, no real read files needed), the
accepted case writes reference.fna/truth.tsv/truth_provenance.json in
make_truth.py's exact 3-column truth.tsv shape, and the rejected case
writes none of them.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))

import build_hybrid_truth as bht  # noqa: E402


def write_fasta(path, records):
    """records: [(header_without_gt, sequence)]."""
    with open(path, "w") as handle:
        for header, sequence in records:
            handle.write(f">{header}\n{sequence}\n")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        # --- read_fasta_records: basic parsing, first whitespace token as id. ---
        fasta = Path(tmp) / "asm.fasta"
        write_fasta(fasta, [
            ("1 length=3000000 depth=1.00x circular=true", "A" * 3_000_000),
            ("2 length=50000 depth=2.00x circular=true", "C" * 50_000),
        ])
        records = bht.read_fasta_records(fasta)
        assert [r[1] for r in records] == ["1", "2"], records
        assert records[0][2] == 3_000_000 and records[1][2] == 50_000, records
        print("read_fasta_records parses headers/lengths, first token as id -> PASS")

        # --- classify_contigs: clean chromosome + plasmid case. ---
        labels, chrom_id, reason = bht.classify_contigs(records, min_chromosome_length=1_500_000)
        assert reason is None and chrom_id == "1", (labels, chrom_id, reason)
        assert labels == {"1": "CHROMOSOME", "2": "PLASMID"}, labels
        print("one large circular contig -> CHROMOSOME, smaller circular contig -> PLASMID -> PASS")

        # --- classify_contigs: a non-circular contig rejects the whole assembly. ---
        non_circular_records = [
            ("1 length=3000000 circular=true", "1", 3_000_000),
            ("2 length=50000", "2", 50_000),  # no circular=true at all
        ]
        labels, chrom_id, reason = bht.classify_contigs(non_circular_records, min_chromosome_length=1_500_000)
        assert labels is None and chrom_id is None
        assert "non-circular contig" in reason and "2" in reason, reason
        print("a non-circular contig rejects the assembly outright, not a partial truth -> PASS")

        # --- classify_contigs: no contig reaches the chromosome-length bar. ---
        small_records = [("1 length=50000 circular=true", "1", 50_000)]
        labels, chrom_id, reason = bht.classify_contigs(small_records, min_chromosome_length=1_500_000)
        assert labels is None
        assert "no circular contig reaches --min-chromosome-length" in reason, reason
        print("no contig clearing the chromosome-length bar is rejected, not guessed at -> PASS")

        # --- classify_contigs: two contigs both clear the chromosome bar -- ambiguous. ---
        ambiguous_records = [
            ("1 length=3000000 circular=true", "1", 3_000_000),
            ("2 length=2000000 circular=true", "2", 2_000_000),
        ]
        labels, chrom_id, reason = bht.classify_contigs(ambiguous_records, min_chromosome_length=1_500_000)
        assert labels is None
        assert "ambiguous" in reason and "1" in reason and "2" in reason, reason
        print("two circular contigs both clearing the chromosome bar is ambiguous, never guessed -> PASS")

        # --- file_fingerprint: stable identity from real files, skips missing ones. ---
        r1 = Path(tmp) / "r1.fastq.gz"; r1.write_bytes(b"fake-short-read-data")
        fp1 = bht.file_fingerprint([str(r1), str(Path(tmp) / "does_not_exist.fastq.gz")])
        fp2 = bht.file_fingerprint([str(r1)])
        assert len(fp1["input_files"]) == 1 and fp1["identity_sha256"] == fp2["identity_sha256"]
        print("file_fingerprint records real input files and skips missing ones -> PASS")

        # --- End-to-end main(): fake unicycler subprocess, accepted case. ---
        # main() resolves the binary via shutil.which() first (so it can pass
        # subprocess.run a real path rather than relying on its bare-name
        # lookup, which is not PATHEXT-aware on Windows) -- faked here too,
        # since the point of this test is main()'s own logic, not a real
        # PATH-based binary lookup.
        original_run = bht.subprocess.run
        original_which = bht.shutil.which
        bht.shutil.which = lambda name: "unicycler" if name == "unicycler" else original_which(name)

        def fake_run_accept(command, capture_output=True, text=True, timeout=None):
            out_dir = Path(command[command.index("-o") + 1])
            out_dir.mkdir(parents=True, exist_ok=True)
            write_fasta(out_dir / "assembly.fasta", [
                ("1 length=3000000 depth=1.00x circular=true", "A" * 3_000_000),
                ("2 length=50000 depth=2.00x circular=true", "C" * 50_000),
            ])
            return subprocess.CompletedProcess(command, 0, stdout="unicycler ok", stderr="")

        long_reads = Path(tmp) / "long.fastq.gz"; long_reads.write_bytes(b"fake-long")
        r2 = Path(tmp) / "r2.fastq.gz"; r2.write_bytes(b"fake-short-read-data-2")
        out_ref = Path(tmp) / "reference.fna"
        out_truth = Path(tmp) / "truth.tsv"
        out_prov = Path(tmp) / "truth_provenance.json"

        bht.subprocess.run = fake_run_accept
        old_argv = sys.argv
        try:
            sys.argv = ["build_hybrid_truth.py", "--long-reads", str(long_reads), "--r1", str(r1), "--r2", str(r2),
                       "--out-reference", str(out_ref), "--out-truth", str(out_truth),
                       "--out-provenance", str(out_prov), "--min-chromosome-length", "1500000"]
            bht.main()
        finally:
            sys.argv = old_argv
            bht.subprocess.run = original_run

        assert out_ref.is_file() and out_truth.is_file() and out_prov.is_file()
        truth_lines = out_truth.read_text().strip().splitlines()
        assert truth_lines[0] == "sequence_id\tmolecule_type\tlength"
        assert "1\tCHROMOSOME\t3000000" in truth_lines
        assert "2\tPLASMID\t50000" in truth_lines
        provenance = json.loads(out_prov.read_text())
        assert provenance["method"] == "self_assembled_hybrid" and provenance["assembler"] == "unicycler"
        assert provenance["chromosome_id"] == "1"
        print("main() accepted case writes reference.fna/truth.tsv (3-column shape)/truth_provenance.json -> PASS")

        # --- End-to-end main(): fake unicycler subprocess, rejected case --
        # a non-circular contig -- writes NONE of the three output files. ---
        def fake_run_reject(command, capture_output=True, text=True, timeout=None):
            out_dir = Path(command[command.index("-o") + 1])
            out_dir.mkdir(parents=True, exist_ok=True)
            write_fasta(out_dir / "assembly.fasta", [
                ("1 length=3000000 depth=1.00x circular=true", "A" * 3_000_000),
                ("2 length=50000 depth=2.00x", "C" * 50_000),  # no circular=true
            ])
            return subprocess.CompletedProcess(command, 0, stdout="unicycler ok", stderr="")

        out_ref2 = Path(tmp) / "reference2.fna"
        out_truth2 = Path(tmp) / "truth2.tsv"
        out_prov2 = Path(tmp) / "truth_provenance2.json"
        bht.subprocess.run = fake_run_reject
        exited = False
        try:
            sys.argv = ["build_hybrid_truth.py", "--long-reads", str(long_reads), "--r1", str(r1), "--r2", str(r2),
                       "--out-reference", str(out_ref2), "--out-truth", str(out_truth2),
                       "--out-provenance", str(out_prov2), "--min-chromosome-length", "1500000"]
            bht.main()
        except SystemExit as exc:
            exited = exc.code != 0
        finally:
            sys.argv = old_argv
            bht.subprocess.run = original_run
            bht.shutil.which = original_which

        assert exited, "a non-circular contig in the assembly must exit non-zero"
        assert not out_ref2.exists() and not out_truth2.exists() and not out_prov2.exists(), (
            "a rejected assembly must write none of its output files -- never a partial truth"
        )
        print("main() rejected case exits non-zero and writes no output files at all -> PASS")

    print("\nALL BUILD HYBRID TRUTH TESTS PASSED")


if __name__ == "__main__":
    main()
