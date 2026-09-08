#!/usr/bin/env python3
"""Regression for python/compare_scoring_methods.py (Phase E, Part 15 -- a
one-off research script, never wired into the pipeline): reproduces
C-Connor/PlasmidToolBenchMarking's own VERIFIED blastn command exactly
(flags, query/subject roles, outfmt column list -- confirmed by direct
fetch of modules/BlastContigs/main.nf, not assumed from a generic BLASTN
shape), reads PlasBench's own REAL minimap2-based F1 directly from an
existing scores.tsv row (never re-derives it), and computes a clearly-
documented good-faith BLASTN hit-length proxy F1 (capped per truth
sequence, since that repo's own chosen outfmt has no alignment
coordinates to interval-merge exactly). No real blastn binary is invoked;
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

import compare_scoring_methods as csm  # noqa: E402


def write_truth(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["sequence_id", "molecule_type", "length"])
        writer.writerows(rows)


def write_scores(path, rows):
    fieldnames = ["sample", "tool", "f1"]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # --- read_minimap2_f1: reads the REAL existing scores.tsv row,
        # never re-derives it. ---
        scores = tmp / "scores.tsv"
        write_scores(scores, [{"sample": "s1", "tool": "platon", "f1": "0.8234"},
                               {"sample": "s1", "tool": "genomad", "f1": ""}])
        assert csm.read_minimap2_f1(scores, "s1", "platon") == 0.8234
        assert csm.read_minimap2_f1(scores, "s1", "genomad") is None  # undefined f1 -> None, never 0
        assert csm.read_minimap2_f1(scores, "s1", "not_a_tool") is None
        print("read_minimap2_f1 reads the real existing scores.tsv row, treating an undefined f1 as None -> PASS")

        # --- blastn_f1: TP capped per truth sequence (redundant/overlapping
        # HSPs must not inflate recall past the sequence's own length). ---
        truth = {"plas1": ("PLASMID", 1000), "chr1": ("CHROMOSOME", 5000)}
        # Two overlapping hits to plas1 summing to 1500bp of raw length --
        # must cap at 1000 (plas1's own real length), not report tp=1500.
        hits = "q1\t1000\t900\t1000\tplas1\t1000\t900\t100.0\t90.0\nq2\t600\t500\tplas1\t1000\t600\t100.0\t60.0\n"
        # (Using the real 7-column outfmt shape: qseqid qlen sseqid slen length pident qcovhsp)
        hits = "q1\t1000\tplas1\t1000\t900\t100.0\t90.0\nq2\t600\tplas1\t1000\t600\t100.0\t60.0\n"
        f1 = csm.blastn_f1(hits, truth)
        assert f1 == 1.0, f1  # tp capped at 1000 == total_plasmid (1000), fp=0 -> precision=recall=1.0
        print("blastn_f1 caps TP per truth sequence, never inflating recall past the sequence's real length -> PASS")

        # --- blastn_f1: a hit to a truth CHROMOSOME sequence counts as FP,
        # correctly depressing precision. ---
        hits = "q1\t1000\tplas1\t1000\t1000\t100.0\t100.0\nq2\t500\tchr1\t5000\t500\t100.0\t100.0\n"
        f1 = csm.blastn_f1(hits, truth)
        # tp=1000, fp=500, fn=0 -> precision=1000/1500=0.6667, recall=1.0 -> f1=2*0.6667*1/(1.6667)=0.8
        assert abs(f1 - 0.8) < 1e-3, f1
        print("blastn_f1 counts a hit to a truth CHROMOSOME sequence as a false positive -> PASS")

        # --- blastn_f1: a hit to a sequence absent from truth.tsv is
        # neither TP nor FP (matching score_plasmids.py's own off-truth
        # treatment), and no true plasmid at all -> f1 is None, not 0. ---
        hits = "q1\t1000\tunknown_contig\t1000\t1000\t100.0\t100.0\n"
        assert csm.blastn_f1(hits, {"chr1": ("CHROMOSOME", 5000)}) is None
        print("blastn_f1 is undefined (None, never 0) when there is no true plasmid to recall at all -> PASS")

    original_which = csm.shutil.which
    original_run = csm.subprocess.run
    try:
        # --- main(): blastn missing -> minimap2_f1 still reported (read
        # from the real scores.tsv), blastn_f1_proxy left blank. ---
        csm.shutil.which = lambda name: None
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            reference = tmp / "reference.fna"
            reference.write_text(">plas1\n" + "A" * 1000 + "\n")
            truth = tmp / "truth.tsv"
            write_truth(truth, [("plas1", "PLASMID", "1000")])
            pred = tmp / "pred.fasta"
            pred.write_text(">q1\n" + "A" * 1000 + "\n")
            scores = tmp / "scores.tsv"
            write_scores(scores, [{"sample": "s1", "tool": "platon", "f1": "0.9000"}])
            out = tmp / "out.tsv"
            old_argv = sys.argv
            try:
                sys.argv = ["compare_scoring_methods.py", "--sample", "s1", "--tool", "platon",
                           "--reference", str(reference), "--truth", str(truth), "--pred-fasta", str(pred),
                           "--scores", str(scores), "--out", str(out)]
                csm.main()
            finally:
                sys.argv = old_argv
            with open(out, newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            assert rows[0]["minimap2_f1"] == "0.9000", rows
            assert rows[0]["blastn_f1_proxy"] == "", rows
            assert rows[0]["absolute_difference"] == "", rows
        print("main() with blastn not installed still reports the real minimap2_f1, leaving the blastn proxy blank -> PASS")

        # --- main(): full end-to-end with a working fake blastn, exact
        # command flags verified. ---
        csm.shutil.which = lambda name: "/usr/bin/blastn" if name == "blastn" else None
        captured_commands = []

        def fake_run(command, **kwargs):
            captured_commands.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="q1\t1000\tplas1\t1000\t1000\t100.0\t100.0\n", stderr="")

        csm.subprocess.run = fake_run
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            reference = tmp / "reference.fna"
            reference.write_text(">plas1\n" + "A" * 1000 + "\n")
            truth = tmp / "truth.tsv"
            write_truth(truth, [("plas1", "PLASMID", "1000")])
            pred = tmp / "pred.fasta"
            pred.write_text(">q1\n" + "A" * 1000 + "\n")
            scores = tmp / "scores.tsv"
            write_scores(scores, [{"sample": "s1", "tool": "platon", "f1": "0.9000"}])
            out = tmp / "out.tsv"
            old_argv = sys.argv
            try:
                sys.argv = ["compare_scoring_methods.py", "--sample", "s1", "--tool", "platon",
                           "--reference", str(reference), "--truth", str(truth), "--pred-fasta", str(pred),
                           "--scores", str(scores), "--out", str(out)]
                csm.main()
            finally:
                sys.argv = old_argv
            with open(out, newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
        assert rows[0]["minimap2_f1"] == "0.9000", rows
        assert rows[0]["blastn_f1_proxy"] == "1.0000", rows
        assert rows[0]["absolute_difference"] == "0.1000", rows
        command = captured_commands[0]
        for flag, value in [("-perc_identity", "80"), ("-evalue", "1E-20"), ("-culling_limit", "1"),
                            ("-max_target_seqs", "10000"), ("-dust", "no")]:
            assert command[command.index(flag) + 1] == value, (flag, command)
        assert command[command.index("-outfmt") + 1] == "6 qseqid qlen sseqid slen length pident qcovhsp", command
        assert command[command.index("-query") + 1] == str(pred), command
        assert command[command.index("-subject") + 1] == str(reference), command
        print("main() runs the exact verified blastn command (flags, outfmt, query/subject roles) and reports both scores -> PASS")
    finally:
        csm.shutil.which = original_which
        csm.subprocess.run = original_run

    print("\nALL COMPARE SCORING METHODS TESTS PASSED")


if __name__ == "__main__":
    main()
