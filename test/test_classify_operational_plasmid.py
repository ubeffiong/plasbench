#!/usr/bin/env python3
"""Regression for python/classify_operational_plasmid.py: the operational
(no-truth) novel-vs-known plasmid classifier, reimplementing COPLA's own
pattern (Mash distance to a small reference set, known-cluster-or-novel with
a confidence score) without COPLA's code or its graph-tool/SBM dependency.
No real mash binary is invoked; subprocess/shutil.which are monkeypatched,
matching compute_difficulty_features.py's own established convention.
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

import classify_operational_plasmid as cop  # noqa: E402


def write_fasta(path, records):
    with open(path, "w") as handle:
        for header, seq in records:
            handle.write(f">{header}\n{seq}\n")


def write_metadata(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["accession", "organism", "plasmid_name", "length_bp", "cluster_id", "cluster_member_count"])
        writer.writerows(rows)


def main():
    original_which, original_run = cop.shutil.which, cop.subprocess.run

    # --- read_fasta_ids: multi-record file, header order preserved. ---
    with tempfile.TemporaryDirectory() as tmp:
        fasta = Path(tmp) / "query.fasta"
        write_fasta(fasta, [("contig_1 extra text", "A" * 50), ("contig_2", "C" * 30)])
        assert cop.read_fasta_ids(fasta) == ["contig_1", "contig_2"]
    print("read_fasta_ids parses first-token record ids in file order -> PASS")

    # --- read_reference_metadata: parses the TSV keyed by accession. ---
    with tempfile.TemporaryDirectory() as tmp:
        meta_path = Path(tmp) / "reference_metadata.tsv"
        write_metadata(meta_path, [
            ["CP001.1", "Klebsiella pneumoniae", "pKPC-a", "100000", "CP001.1", "3"],
            ["CP002.1", "Escherichia coli", "pCTX-M", "80000", "CP002.1", "1"],
        ])
        meta = cop.read_reference_metadata(meta_path)
        assert meta["CP001.1"]["organism"] == "Klebsiella pneumoniae"
        assert meta["CP002.1"]["cluster_member_count"] == "1"
    print("read_reference_metadata parses accession -> metadata correctly -> PASS")

    reference_metadata = {
        "CP001.1": {"organism": "Klebsiella pneumoniae", "plasmid_name": "pKPC-a", "cluster_id": "CP001.1", "cluster_member_count": "3"},
        "CP002.1": {"organism": "Escherichia coli", "plasmid_name": "pCTX-M", "cluster_id": "CP002.1", "cluster_member_count": "1"},
    }

    # --- classify: within threshold, cluster big enough -> known_cluster. ---
    dist_rows = [("CP001.1", "contig_1", 0.02), ("CP002.1", "contig_1", 0.40)]
    result = cop.classify(["contig_1"], dist_rows, reference_metadata, threshold=0.05, min_cluster_members=2)
    assert result["contig_1"]["cluster_membership_status"] == "known_cluster"
    assert result["contig_1"]["best_reference_id"] == "CP001.1"
    assert float(result["contig_1"]["confidence_score"]) > 0.5
    print("classify: nearest reference within threshold, cluster big enough -> known_cluster -> PASS")

    # --- classify: within threshold but cluster too small -> novel. ---
    dist_rows = [("CP002.1", "contig_1", 0.01)]
    result = cop.classify(["contig_1"], dist_rows, reference_metadata, threshold=0.05, min_cluster_members=2)
    assert result["contig_1"]["cluster_membership_status"] == "novel"
    assert "too small" in result["contig_1"]["notes"]
    print("classify: within threshold but cluster below --min-cluster-members -> novel -> PASS")

    # --- classify: beyond threshold -> novel, confidence scales past 0. ---
    dist_rows = [("CP001.1", "contig_1", 0.20)]
    result = cop.classify(["contig_1"], dist_rows, reference_metadata, threshold=0.05, min_cluster_members=1)
    assert result["contig_1"]["cluster_membership_status"] == "novel"
    assert float(result["contig_1"]["confidence_score"]) > 0
    print("classify: nearest reference beyond threshold -> novel -> PASS")

    # --- classify: a query id with no distance row at all -> insufficient_reference. ---
    result = cop.classify(["contig_missing"], [("CP001.1", "contig_1", 0.02)], reference_metadata, 0.05, 1)
    assert result["contig_missing"]["cluster_membership_status"] == "insufficient_reference"
    assert result["contig_missing"]["mash_distance"] == ""
    print("classify: a query record mash produced no distance for -> insufficient_reference, not fabricated -> PASS")

    # --- classify: dist_rows is None entirely (mash never ran) -> every record insufficient_reference. ---
    result = cop.classify(["contig_1", "contig_2"], None, reference_metadata, 0.05, 1)
    assert all(r["cluster_membership_status"] == "insufficient_reference" for r in result.values())
    print("classify: mash never ran -> every record is insufficient_reference, none guessed -> PASS")

    # --- main(): empty/missing query -> header-only output, no crash. ---
    with tempfile.TemporaryDirectory() as tmp:
        empty_query = Path(tmp) / "empty.fasta"
        empty_query.write_text("")
        out = Path(tmp) / "out.tsv"
        old_argv = sys.argv
        try:
            sys.argv = ["classify_operational_plasmid.py", "--query", str(empty_query),
                       "--reference-sketch", str(Path(tmp) / "ref.msh"),
                       "--reference-metadata", str(Path(tmp) / "ref_meta.tsv"),
                       "--sample-id", "s1", "--out", str(out)]
            cop.main()
        finally:
            sys.argv = old_argv
        with open(out, newline="", encoding="utf-8") as handle:
            rows = list(csv.reader(handle, delimiter="\t"))
        assert rows == [cop.HEADER]
    print("main() with an empty/missing query writes a clean header-only output, never a crash -> PASS")

    # --- main(): mash not installed -> insufficient_reference rows, not a crash. ---
    with tempfile.TemporaryDirectory() as tmp:
        query = Path(tmp) / "query.fasta"
        write_fasta(query, [("contig_1", "A" * 100)])
        out = Path(tmp) / "out.tsv"
        cop.shutil.which = lambda name: None
        old_argv = sys.argv
        try:
            sys.argv = ["classify_operational_plasmid.py", "--query", str(query),
                       "--reference-sketch", str(Path(tmp) / "ref.msh"),
                       "--reference-metadata", str(Path(tmp) / "ref_meta.tsv"),
                       "--sample-id", "s1", "--out", str(out)]
            cop.main()
        finally:
            sys.argv = old_argv
            cop.shutil.which = original_which
        with open(out, newline="", encoding="utf-8") as handle:
            row = next(csv.DictReader(handle, delimiter="\t"))
        assert row["cluster_membership_status"] == "insufficient_reference"
        assert row["sample_id"] == "s1" and row["query_record_id"] == "contig_1"
    print("main() with mash not installed writes insufficient_reference rows, never fabricated -> PASS")

    # --- main(): real success path, fake mash produces a known-cluster call. ---
    with tempfile.TemporaryDirectory() as tmp:
        query = Path(tmp) / "query.fasta"
        write_fasta(query, [("contig_1", "A" * 100)])
        ref_sketch = Path(tmp) / "reference.msh"
        ref_sketch.write_bytes(b"fake-sketch")
        ref_meta = Path(tmp) / "reference_metadata.tsv"
        write_metadata(ref_meta, [["CP001.1", "Klebsiella pneumoniae", "pKPC-a", "100000", "CP001.1", "2"]])
        out = Path(tmp) / "out.tsv"

        cop.shutil.which = lambda name: "/usr/bin/mash" if name == "mash" else None

        def fake_run(command, **kwargs):
            if command[1] == "sketch":
                Path(command[command.index("-o") + 1] + ".msh").write_bytes(b"fake-query-sketch")
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            if command[1] == "dist":
                return subprocess.CompletedProcess(
                    command, 0, stdout="CP001.1\tcontig_1\t0.0100\t0.0\t100/100\n", stderr="")
            raise AssertionError(f"unexpected mash subcommand: {command}")

        cop.subprocess.run = fake_run
        old_argv = sys.argv
        try:
            sys.argv = ["classify_operational_plasmid.py", "--query", str(query),
                       "--reference-sketch", str(ref_sketch), "--reference-metadata", str(ref_meta),
                       "--sample-id", "s1", "--out", str(out)]
            cop.main()
        finally:
            sys.argv = old_argv
            cop.shutil.which = original_which
            cop.subprocess.run = original_run

        with open(out, newline="", encoding="utf-8") as handle:
            row = next(csv.DictReader(handle, delimiter="\t"))
        assert row["cluster_membership_status"] == "known_cluster", row
        assert row["best_reference_id"] == "CP001.1"
        assert row["mash_distance"] == "0.010000"
    print("main() end-to-end with a real (faked) mash run classifies correctly -> PASS")

    print("\nALL CLASSIFY OPERATIONAL PLASMID TESTS PASSED")


if __name__ == "__main__":
    main()
