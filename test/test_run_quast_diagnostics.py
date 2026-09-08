#!/usr/bin/env python3
"""Regression for python/run_quast_diagnostics.py: runs QUAST three ways
(combined all-plasmids reference, one run PER individual truth plasmid,
chromosome-only reference) against the SAME query FASTA, parses report.tsv
by ROW-LABEL string match (never fixed row position -- QUAST only emits
fields applicable to a run, in a documented but non-fixed order), and
passes --min-contig 0 explicitly (QUAST's own default of 500bp would
silently drop short plasmid contigs). No real QUAST binary is invoked;
shutil.which/subprocess.run are monkeypatched, matching this project's
established convention for testing code that shells out to bioinformatics
tools.
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

import run_quast_diagnostics as rqd  # noqa: E402


def write_fasta(path, records):
    with open(path, "w") as handle:
        for header, seq in records:
            handle.write(f">{header}\n{seq}\n")


def write_truth(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["sequence_id", "molecule_type", "length"])
        writer.writerows(rows)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        reference = tmp / "reference.fna"
        write_fasta(reference, [("chr1", "A" * 100), ("plas1", "C" * 50), ("plas2", "G" * 20)])
        truth = tmp / "truth.tsv"
        write_truth(truth, [("chr1", "CHROMOSOME", "100"), ("plas1", "PLASMID", "50"), ("plas2", "PLASMID", "20")])

        # --- split_individual_plasmids: one file per PLASMID, chromosome excluded. ---
        with tempfile.TemporaryDirectory() as split_tmp:
            labels = rqd.read_truth(truth)
            written = rqd.split_individual_plasmids(reference, labels, split_tmp)
            assert [seq_id for seq_id, _ in written] == ["plas1", "plas2"], written
            assert Path(written[0][1]).read_text() == ">plas1\n" + "C" * 50 + "\n"
            assert Path(written[1][1]).read_text() == ">plas2\n" + "G" * 20 + "\n"
        print("split_individual_plasmids writes one file per truth PLASMID, chromosome excluded -> PASS")

        # --- parse_report: row-label lookup, ignores the 'Assembly' header row. ---
        report = tmp / "report.tsv"
        report.write_text(
            "Assembly\tquery\n"
            "# contigs\t3\n"
            "Genome fraction (%)\t87.500\n"
            "# misassemblies\t2\n"
            "Duplication ratio\t1.050\n"
        )
        values = rqd.parse_report(report)
        assert values["Genome fraction (%)"] == "87.500", values
        assert values["# misassemblies"] == "2", values
        assert values["Duplication ratio"] == "1.050", values
        assert "Assembly" not in values, values
        print("parse_report reads QUAST's report.tsv by row label, not fixed position -> PASS")

    original_which = rqd.shutil.which
    original_run = rqd.subprocess.run
    try:
        # --- main(): quast.py missing -> writes a clean empty (header-only)
        # output, never a crash or a fabricated row. ---
        rqd.shutil.which = lambda name: None
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            reference = tmp / "reference.fna"
            write_fasta(reference, [("chr1", "A" * 100), ("plas1", "C" * 50)])
            truth = tmp / "truth.tsv"
            write_truth(truth, [("chr1", "CHROMOSOME", "100"), ("plas1", "PLASMID", "50")])
            query = tmp / "pred.fasta"
            write_fasta(query, [("pred1", "C" * 50)])
            out = tmp / "out.tsv"
            old_argv = sys.argv
            try:
                sys.argv = ["run_quast_diagnostics.py", "--query", str(query), "--reference", str(reference),
                           "--truth", str(truth), "--sample", "s1", "--tool", "t1", "--out", str(out)]
                rqd.main()
            finally:
                sys.argv = old_argv
            with open(out, newline="", encoding="utf-8") as handle:
                data_rows = list(csv.reader(handle, delimiter="\t"))
            assert data_rows == [["sample", "tool", "reference_type", "reference_id",
                                   "genome_fraction_pct", "misassembly_count", "duplication_ratio"]], data_rows
        print("main() with quast.py not installed writes a clean header-only output, not a crash -> PASS")

        # --- main(): empty query (tool predicted nothing) -> header-only
        # output, QUAST never even invoked. ---
        rqd.shutil.which = lambda name: "/usr/bin/quast.py" if name == "quast.py" else None
        called = []
        rqd.subprocess.run = lambda *a, **k: called.append(a) or subprocess.CompletedProcess(a, 0)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            reference = tmp / "reference.fna"
            write_fasta(reference, [("chr1", "A" * 100), ("plas1", "C" * 50)])
            truth = tmp / "truth.tsv"
            write_truth(truth, [("chr1", "CHROMOSOME", "100"), ("plas1", "PLASMID", "50")])
            query = tmp / "pred.fasta"
            query.touch()  # empty: this tool predicted nothing
            out = tmp / "out.tsv"
            old_argv = sys.argv
            try:
                sys.argv = ["run_quast_diagnostics.py", "--query", str(query), "--reference", str(reference),
                           "--truth", str(truth), "--sample", "s1", "--tool", "t1", "--out", str(out)]
                rqd.main()
            finally:
                sys.argv = old_argv
            assert called == [], "QUAST must never be invoked for an empty (predicted-nothing) query"
            with open(out, newline="", encoding="utf-8") as handle:
                data_rows = list(csv.reader(handle, delimiter="\t"))
            assert len(data_rows) == 1  # header only
        print("main() with an empty query (tool predicted nothing) never invokes QUAST at all -> PASS")

        # --- main(): full end-to-end, real 3-way comparison (combined,
        # per-plasmid individual x2, chromosome), --min-contig 0 always
        # passed, each reference type gets its own real report.tsv values. ---
        rqd.shutil.which = lambda name: "/usr/bin/quast.py" if name == "quast.py" else None
        captured_commands = []

        def fake_run(command, **kwargs):
            captured_commands.append(command)
            out_dir = Path(command[command.index("-o") + 1])
            out_dir.mkdir(parents=True, exist_ok=True)
            ref = command[command.index("-r") + 1]
            # Distinguish which reference this call was for by its filename,
            # so each gets a distinguishable, real report.tsv value.
            frac = "100.000" if "plas1" in ref else ("50.000" if "plas2" in ref else "10.000")
            (out_dir / "report.tsv").write_text(
                f"Assembly\tquery\n# contigs\t1\nGenome fraction (%)\t{frac}\n"
                f"# misassemblies\t0\nDuplication ratio\t1.000\n"
            )
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        rqd.subprocess.run = fake_run
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            reference = tmp / "reference.fna"
            write_fasta(reference, [("chr1", "A" * 100), ("plas1", "C" * 50), ("plas2", "G" * 20)])
            truth = tmp / "truth.tsv"
            write_truth(truth, [("chr1", "CHROMOSOME", "100"), ("plas1", "PLASMID", "50"), ("plas2", "PLASMID", "20")])
            query = tmp / "pred.fasta"
            write_fasta(query, [("pred1", "C" * 50)])
            out = tmp / "out.tsv"
            old_argv = sys.argv
            try:
                sys.argv = ["run_quast_diagnostics.py", "--query", str(query), "--reference", str(reference),
                           "--truth", str(truth), "--sample", "s1", "--tool", "t1", "--out", str(out), "--threads", "2"]
                rqd.main()
            finally:
                sys.argv = old_argv
            with open(out, newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
        reference_types = {(r["reference_type"], r["reference_id"]) for r in rows}
        assert reference_types == {
            ("combined", "all_plasmids"), ("individual", "plas1"), ("individual", "plas2"),
            ("chromosome", "chromosome"),
        }, reference_types
        assert all(cmd[cmd.index("--min-contig") + 1] == "0" for cmd in captured_commands), captured_commands
        assert all("--sample" not in cmd for cmd in captured_commands)  # quast.py itself never sees PlasBench-specific flags
        print("main() runs the full 3-way comparison (combined/individual x2/chromosome), always with --min-contig 0 -> PASS")
    finally:
        rqd.shutil.which = original_which
        rqd.subprocess.run = original_run

    print("\nALL QUAST DIAGNOSTICS TESTS PASSED")


if __name__ == "__main__":
    main()
