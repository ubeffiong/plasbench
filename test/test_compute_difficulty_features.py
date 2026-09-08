#!/usr/bin/env python3
"""Regression for python/compute_difficulty_features.py: three independently
optional, truth-derived difficulty descriptors (dead-end count, plasmid-vs-
chromosome depth ratio, plasmid-vs-chromosome Mash distance). Each must be
empty (never a guessed or zero value) when its prerequisite is missing --
no assembly graph, no reads, or the external tool not installed. No real
external binaries are invoked; subprocess/shutil.which are monkeypatched,
matching this session's own established convention for testing code that
shells out to bioinformatics tools.
"""
import csv
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))

import compute_difficulty_features as cdf  # noqa: E402


def write_truth(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["sequence_id", "molecule_type", "length"])
        writer.writerows(rows)


def write_fasta(path, records):
    with open(path, "w") as handle:
        for header, seq in records:
            handle.write(f">{header}\n{seq}\n")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        truth = Path(tmp) / "truth.tsv"
        write_truth(truth, [("chr1", "CHROMOSOME", "5000000"), ("plas1", "PLASMID", "50000"),
                            ("plas2", "PLASMID", "20000")])
        labels = cdf.read_truth(truth)
        assert labels == {"chr1": "CHROMOSOME", "plas1": "PLASMID", "plas2": "PLASMID"}
        print("read_truth parses sequence_id -> molecule_type correctly -> PASS")

        # --- split_reference_by_label: correct partition, real content. ---
        fasta = Path(tmp) / "ref.fasta"
        write_fasta(fasta, [("chr1", "A" * 100), ("plas1", "C" * 50), ("plas2", "G" * 20)])
        chrom_path, plasmid_path = cdf.split_reference_by_label(fasta, labels, tmp)
        assert chrom_path is not None and plasmid_path is not None
        assert ">chr1" in chrom_path.read_text() and ">plas1" not in chrom_path.read_text()
        assert ">plas1" in plasmid_path.read_text() and ">plas2" in plasmid_path.read_text()
        print("split_reference_by_label partitions chromosome/plasmid content correctly -> PASS")

        # --- split_reference_by_label: a plasmid-free isolate -> plasmid path is None. ---
        no_plasmid_truth = Path(tmp) / "truth_no_plasmid.tsv"
        write_truth(no_plasmid_truth, [("chr1", "CHROMOSOME", "5000000")])
        no_plasmid_fasta = Path(tmp) / "ref_no_plasmid.fasta"
        write_fasta(no_plasmid_fasta, [("chr1", "A" * 100)])
        chrom_only, plasmid_none = cdf.split_reference_by_label(
            no_plasmid_fasta, cdf.read_truth(no_plasmid_truth), tmp)
        assert chrom_only is not None and plasmid_none is None
        print("a plasmid-free isolate's split correctly yields plasmid_path=None, not an empty file misread as present -> PASS")

    # --- dead_end_count: no --graph given -> empty, never a guess. ---
    original_which = cdf.shutil.which
    try:
        cdf.shutil.which = lambda name: "/usr/bin/deadends" if name == "deadends" else original_which(name)
        assert cdf.dead_end_count("") == ""
        print("dead_end_count with no graph path is empty, even if the tool is installed -> PASS")

        # --- dead_end_count: a graph PATH that does not exist -> empty,
        # even with the tool installed (never trust an unchecked path). ---
        cdf.shutil.which = lambda name: "/usr/bin/deadends" if name == "deadends" else None
        assert cdf.dead_end_count("no_such_graph.gfa") == ""
        print("dead_end_count with a non-existent graph file is empty, not passed to the tool blindly -> PASS")

        with tempfile.TemporaryDirectory() as gtmp:
            real_graph = Path(gtmp) / "assembly_graph.gfa"
            real_graph.write_text("S\t1\tACGT\n")

            # --- dead_end_count: tool not installed -> empty. ---
            cdf.shutil.which = lambda name: None
            assert cdf.dead_end_count(str(real_graph)) == ""
            print("dead_end_count with the tool not installed is empty, not a crash -> PASS")

            # --- dead_end_count: tool installed and graph given -> real value. ---
            cdf.shutil.which = lambda name: "/usr/bin/deadends" if name == "deadends" else None
            original_run = cdf.subprocess.run
            cdf.subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="7\n", stderr="")
            assert cdf.dead_end_count(str(real_graph)) == "7"
            print("dead_end_count returns the tool's real reported count -> PASS")

            # --- dead_end_count: non-numeric/garbage stdout is rejected, not passed through. ---
            cdf.subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="not a number\n", stderr="")
            assert cdf.dead_end_count(str(real_graph)) == ""
            print("dead_end_count rejects non-numeric tool output rather than passing it through -> PASS")
    finally:
        cdf.shutil.which = original_which
        cdf.subprocess.run = original_run

    # --- depth_ratio: missing reads -> empty without even checking for tools. ---
    assert cdf.depth_ratio("ref.fasta", "truth.tsv", "", "", 4) == ""
    print("depth_ratio with no reads given is empty -> PASS")

    # --- depth_ratio: real read files, but tools missing -> empty. ---
    with tempfile.TemporaryDirectory() as rtmp:
        r1, r2 = Path(rtmp) / "r1.fq.gz", Path(rtmp) / "r2.fq.gz"
        r1.write_bytes(b"fake"); r2.write_bytes(b"fake")
        cdf.shutil.which = lambda name: None
        try:
            assert cdf.depth_ratio("ref.fasta", "truth.tsv", str(r1), str(r2), 4) == ""
            print("depth_ratio with real reads but minimap2/samtools not installed is empty -> PASS")
        finally:
            cdf.shutil.which = original_which

    # --- depth_ratio: reads given but the files don't actually exist -> empty. ---
    assert cdf.depth_ratio("ref.fasta", "truth.tsv", "no_such_r1.fq.gz", "no_such_r2.fq.gz", 4) == ""
    print("depth_ratio with non-existent read files is empty, not passed to minimap2 blindly -> PASS")

    # --- depth_ratio: real success path, both tools installed -- the
    # median-depth-ratio computation itself, not just the missing-
    # prerequisite short-circuits above. ---
    original_popen = cdf.subprocess.Popen
    with tempfile.TemporaryDirectory() as rtmp:
        r1, r2 = Path(rtmp) / "r1.fq.gz", Path(rtmp) / "r2.fq.gz"
        r1.write_bytes(b"fake"); r2.write_bytes(b"fake")
        truth = Path(rtmp) / "truth.tsv"
        write_truth(truth, [("chr1", "CHROMOSOME", "5000000"), ("plas1", "PLASMID", "50000")])

        cdf.shutil.which = lambda name: f"/usr/bin/{name}" if name in ("minimap2", "samtools") else None

        class FakeAlign:
            def __init__(self):
                self.stdout = io.BytesIO()
                self.returncode = 0
            def wait(self, timeout=None):
                return 0

        def fake_popen(command, **kwargs):
            assert command[0] == "/usr/bin/minimap2"
            return FakeAlign()

        def fake_run(command, **kwargs):
            if command[1] == "sort":
                bam = Path(command[command.index("-o") + 1])
                bam.write_bytes(b"fake-bam")
                return subprocess.CompletedProcess(command, 0)
            if command[1] == "index":
                return subprocess.CompletedProcess(command, 0)
            if command[1] == "coverage":
                # #rname/meandepth columns, looked up by header name -- chr1
                # at 40x, plas1 at 10x -> ratio 10/40 = 0.25.
                stdout = "#rname\tstartpos\tendpos\tnumreads\tcovbases\tcoverage\tmeandepth\tmeanbaseq\tmeanmapq\n" \
                         "chr1\t1\t5000000\t100\t5000000\t100.0\t40.0000\t35.0\t60.0\n" \
                         "plas1\t1\t50000\t10\t50000\t100.0\t10.0000\t35.0\t60.0\n"
                return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")
            raise AssertionError(f"unexpected samtools subcommand: {command}")

        cdf.subprocess.Popen = fake_popen
        cdf.subprocess.run = fake_run
        try:
            ratio = cdf.depth_ratio("ref.fasta", str(truth), str(r1), str(r2), 4)
            assert ratio == "0.2500", ratio
            print("depth_ratio computes the real median plasmid/chromosome depth ratio from samtools coverage -> PASS")
        finally:
            cdf.shutil.which = original_which
            cdf.subprocess.run = original_run
            cdf.subprocess.Popen = original_popen

    # --- mash_distance: tool missing -> empty. ---
    cdf.shutil.which = lambda name: None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            assert cdf.mash_distance("ref.fasta", "truth.tsv", tmp) == ""
        print("mash_distance with mash not installed is empty -> PASS")
    finally:
        cdf.shutil.which = original_which

    # --- mash_distance: real values, minimum across multiple plasmids. ---
    with tempfile.TemporaryDirectory() as tmp:
        truth = Path(tmp) / "truth.tsv"
        write_truth(truth, [("chr1", "CHROMOSOME", "100"), ("plas1", "PLASMID", "50"), ("plas2", "PLASMID", "20")])
        fasta = Path(tmp) / "ref.fasta"
        write_fasta(fasta, [("chr1", "A" * 100), ("plas1", "C" * 50), ("plas2", "G" * 20)])
        cdf.shutil.which = lambda name: "/usr/bin/mash" if name == "mash" else None

        def fake_run(command, **kwargs):
            if command[1] == "sketch":
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            if command[1] == "dist":
                # Two rows: plas1 is closer (lower distance, the harder case) than plas2.
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout="chromosome.fasta\tplasmid.fasta/plas1\t0.0500\t0.0\t100/100\n"
                           "chromosome.fasta\tplasmid.fasta/plas2\t0.3000\t0.0\t50/100\n",
                    stderr="",
                )
            raise AssertionError(f"unexpected mash subcommand: {command}")

        cdf.subprocess.run = fake_run
        try:
            distance = cdf.mash_distance(fasta, truth, tmp)
            assert distance == "0.050000", distance
            print("mash_distance reports the MINIMUM distance across multiple plasmids (the harder case) -> PASS")
        finally:
            cdf.shutil.which = original_which
            cdf.subprocess.run = original_run

    # --- mash_distance: plasmid-free isolate -> empty, not a crash. ---
    with tempfile.TemporaryDirectory() as tmp:
        truth = Path(tmp) / "truth.tsv"
        write_truth(truth, [("chr1", "CHROMOSOME", "100")])
        fasta = Path(tmp) / "ref.fasta"
        write_fasta(fasta, [("chr1", "A" * 100)])
        cdf.shutil.which = lambda name: "/usr/bin/mash" if name == "mash" else None
        try:
            assert cdf.mash_distance(fasta, truth, tmp) == ""
            print("mash_distance on a plasmid-free isolate is empty, not a crash -> PASS")
        finally:
            cdf.shutil.which = original_which

    # --- main(): end-to-end, all three fields populated, written as a clean TSV. ---
    with tempfile.TemporaryDirectory() as tmp:
        truth = Path(tmp) / "truth.tsv"
        write_truth(truth, [("chr1", "CHROMOSOME", "100"), ("plas1", "PLASMID", "50")])
        fasta = Path(tmp) / "s1" / "reference.fna"
        fasta.parent.mkdir()
        write_fasta(fasta, [("chr1", "A" * 100), ("plas1", "C" * 50)])
        out = Path(tmp) / "difficulty_features.tsv"

        cdf.shutil.which = lambda name: None  # nothing installed -- every field stays empty
        old_argv = sys.argv
        try:
            sys.argv = ["compute_difficulty_features.py", "--fasta", str(fasta), "--truth", str(truth),
                       "--out", str(out)]
            cdf.main()
        finally:
            sys.argv = old_argv
            cdf.shutil.which = original_which

        with open(out, newline="", encoding="utf-8") as handle:
            row = next(csv.DictReader(handle, delimiter="\t"))
        assert row["sample_id"] == "s1", row
        assert row["gfa_dead_end_count"] == "" and row["plasmid_chromosome_depth_ratio"] == "" \
            and row["plasmid_chromosome_mash_distance"] == ""
        print("main() writes a clean TSV with empty fields (nothing installed), sample_id inferred from the path -> PASS")

    print("\nALL DIFFICULTY FEATURES TESTS PASSED")


if __name__ == "__main__":
    main()
