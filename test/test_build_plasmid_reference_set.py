#!/usr/bin/env python3
"""Regression for python/build_plasmid_reference_set.py: the one-time build
step for classify_operational_plasmid.py's curated reference set. No real
network call or mash binary is invoked; validate_cohort.fetch() and
subprocess/shutil.which are monkeypatched, matching this project's
established convention for testing code that shells out or calls NCBI.
"""
import csv
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))

import build_plasmid_reference_set as bprs  # noqa: E402


def write_curated(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["accession", "organism", "plasmid_name", "description"])
        writer.writerows(rows)


def main():
    # --- fasta_lengths: real length accounting across multi-line records. ---
    with tempfile.TemporaryDirectory() as tmp:
        fasta = Path(tmp) / "reference.fasta"
        fasta.write_text(">CP001.1 desc one\nACGT\nACGT\n>CP002.1 desc two\nACGTACGTAC\n")
        lengths = bprs.fasta_lengths(fasta)
        assert lengths == {"CP001.1": 8, "CP002.1": 10}, lengths
    print("fasta_lengths accounts real per-record lengths across multi-line FASTA -> PASS")

    # --- single_linkage_clusters: two close plasmids merge, one distant stays its own cluster. ---
    accessions = ["CP001.1", "CP002.1", "CP003.1"]
    distances = [
        ("CP001.1", "CP002.1", 0.02), ("CP002.1", "CP001.1", 0.02),
        ("CP001.1", "CP003.1", 0.40), ("CP003.1", "CP001.1", 0.40),
        ("CP002.1", "CP003.1", 0.40), ("CP003.1", "CP002.1", 0.40),
    ]
    clusters = bprs.single_linkage_clusters(accessions, distances, threshold=0.05)
    assert clusters["CP001.1"] == clusters["CP002.1"], clusters
    assert clusters["CP001.1"][1] == 2, clusters
    assert clusters["CP003.1"][0] == "CP003.1" and clusters["CP003.1"][1] == 1, clusters
    print("single_linkage_clusters merges within-threshold pairs, leaves a distant one as its own singleton -> PASS")

    # --- single_linkage_clusters: transitive chain (A-B close, B-C close, A-C far) still merges all three. ---
    distances_chain = [
        ("CP001.1", "CP002.1", 0.02), ("CP002.1", "CP001.1", 0.02),
        ("CP002.1", "CP003.1", 0.02), ("CP003.1", "CP002.1", 0.02),
        ("CP001.1", "CP003.1", 0.40), ("CP003.1", "CP001.1", 0.40),
    ]
    clusters = bprs.single_linkage_clusters(accessions, distances_chain, threshold=0.05)
    assert clusters["CP001.1"][0] == clusters["CP002.1"][0] == clusters["CP003.1"][0]
    assert clusters["CP001.1"][1] == 3
    print("single_linkage_clusters merges transitively across a chain of close pairs -> PASS")

    # --- main(): end-to-end with a faked network fetch and a faked mash. ---
    with tempfile.TemporaryDirectory() as tmp:
        curated = Path(tmp) / "curated_accessions.tsv"
        write_curated(curated, [
            ["CP001.1", "Klebsiella pneumoniae", "pKPC-a", "carbapenemase-carrying reference"],
            ["CP002.1", "Escherichia coli", "pCTX-M", "ESBL reference"],
        ])
        out_dir = Path(tmp) / "out"

        fake_records = {
            "CP001.1": ">CP001.1 Klebsiella pneumoniae plasmid pKPC-a, complete sequence\nACGTACGTACGT\n",
            "CP002.1": ">CP002.1 Escherichia coli plasmid pCTX-M, complete sequence\nTTGGTTGGTTGGTTGG\n",
        }

        def fake_fetch(request, timeout=60, retries=4, label=""):
            for accession, text in fake_records.items():
                if f"id={accession}" in request.full_url:
                    return text.encode("utf-8")
            raise AssertionError(f"unexpected fetch request: {request.full_url}")

        original_fetch = bprs.fetch
        original_which = bprs.shutil.which
        original_run = bprs.subprocess.run
        bprs.fetch = fake_fetch
        bprs.shutil.which = lambda name: "/usr/bin/mash" if name == "mash" else None

        def fake_run(command, **kwargs):
            if command[1] == "sketch":
                Path(command[command.index("-o") + 1] + ".msh").write_bytes(b"fake-sketch")
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            if command[1] == "dist":
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout="CP001.1\tCP001.1\t0.0000\t0.0\t100/100\n"
                           "CP001.1\tCP002.1\t0.4000\t0.0\t20/100\n"
                           "CP002.1\tCP001.1\t0.4000\t0.0\t20/100\n"
                           "CP002.1\tCP002.1\t0.0000\t0.0\t100/100\n",
                    stderr="",
                )
            raise AssertionError(f"unexpected mash subcommand: {command}")

        bprs.subprocess.run = fake_run
        old_argv = sys.argv
        try:
            sys.argv = ["build_plasmid_reference_set.py", "--accessions", str(curated), "--out-dir", str(out_dir)]
            bprs.main()
        finally:
            sys.argv = old_argv
            bprs.fetch = original_fetch
            bprs.shutil.which = original_which
            bprs.subprocess.run = original_run

        reference_fasta = (out_dir / "reference.fasta").read_text()
        assert ">CP001.1" in reference_fasta and ">CP002.1" in reference_fasta
        with open(out_dir / "reference_metadata.tsv", newline="", encoding="utf-8") as handle:
            meta_rows = {row["accession"]: row for row in csv.DictReader(handle, delimiter="\t")}
        assert meta_rows["CP001.1"]["organism"] == "Klebsiella pneumoniae"
        assert meta_rows["CP001.1"]["length_bp"] == "12"
        assert meta_rows["CP001.1"]["cluster_id"] == "CP001.1" and meta_rows["CP001.1"]["cluster_member_count"] == "1"
        provenance = json.loads((out_dir / "reference_set_provenance.json").read_text())
        assert provenance["accession_count"] == 2
        assert "CP001.1" in provenance["queries_used"]
    print("main() end-to-end (faked NCBI fetch + faked mash) writes reference.fasta/.msh/metadata/provenance -> PASS")

    print("\nALL BUILD PLASMID REFERENCE SET TESTS PASSED")


if __name__ == "__main__":
    main()
