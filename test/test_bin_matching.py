#!/usr/bin/env python3
"""Adversarial regression coverage for one-to-one plasmid-bin matching."""
import csv
import os
import subprocess
import sys
import tempfile


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "python", "score_bins.py")


def paf(query, target):
    return f"{query}\t100\t0\t100\t+\t{target}\t100\t0\t100\t100\t100\t60\n"


def run(alignments, memberships):
    with tempfile.TemporaryDirectory() as directory:
        truth = os.path.join(directory, "truth.tsv")
        with open(truth, "w") as handle:
            handle.write("sequence_id\tmolecule_type\tlength\n")
            handle.write("chromosome\tCHROMOSOME\t100\n")
            handle.write("p1\tPLASMID\t100\n")
            handle.write("p2\tPLASMID\t100\n")
        paf_path = os.path.join(directory, "alignments.paf")
        bins_path = os.path.join(directory, "bins.tsv")
        out = os.path.join(directory, "matches.tsv")
        summary_path = os.path.join(directory, "summary.tsv")
        open(paf_path, "w").write(alignments)
        open(bins_path, "w").write(memberships)
        subprocess.run([
            sys.executable, SCRIPT, "--truth", truth, "--paf", paf_path,
            "--bins", bins_path, "--out", out, "--summary", summary_path,
        ], check=True)
        summary = next(csv.DictReader(open(summary_path), delimiter="\t"))
        matches = list(csv.DictReader(open(out), delimiter="\t"))
    return summary, matches


def main():
    exact, _ = run(paf("a", "p1") + paf("b", "p2"), "bin_id\tsequence_id\nA\ta\nB\tb\n")
    assert exact["bin_f1"] == "1.0000"
    assert exact["split_events"] == "0" and exact["merge_events"] == "0"

    split, split_matches = run(paf("a", "p1") + paf("b", "p1"), "bin_id\tsequence_id\nA\ta\nB\tb\n")
    assert split["split_events"] == "1" and split["merge_events"] == "0"
    assert split["unmatched_bins"] == "1" and split["missed_plasmids"] == "1"
    assert sum(row["match_status"] == "matched" for row in split_matches) == 1

    # One predicted bin has contigs that fully recover two distinct plasmids.
    merge, merge_matches = run(paf("a", "p1") + paf("b", "p2"), "bin_id\tsequence_id\nA\ta\nA\tb\n")
    assert merge["merge_events"] == "1" and merge["split_events"] == "0"
    assert merge["matched_bins"] == "1" and merge["missed_plasmids"] == "1"
    assert sum(row["match_status"] == "missed_plasmid" for row in merge_matches) == 1

    # A chromosome-only bin is contamination, not plasmid recovery.
    contamination, contamination_matches = run(
        paf("a", "p1") + paf("chromosomal", "chromosome"),
        "bin_id\tsequence_id\nA\ta\nB\tchromosomal\n",
    )
    assert contamination["matched_bins"] == "1" and contamination["unmatched_bins"] == "1"
    assert contamination["missed_plasmids"] == "1"
    assert contamination["contaminated_bins"] == "1"
    assert any(row["bin_id"] == "B" and row["match_status"] == "unmatched_bin" for row in contamination_matches)

    # An unaligned predicted bin has the same explicit unmatched outcome.
    unmatched, unmatched_matches = run(paf("a", "p1"), "bin_id\tsequence_id\nA\ta\nB\tunmapped\n")
    assert unmatched["unmatched_bins"] == "1"
    assert any(row["bin_id"] == "B" and row["match_status"] == "unmatched_bin" for row in unmatched_matches)
    print("ALL BIN MATCHING TESTS PASSED")


if __name__ == "__main__":
    main()
