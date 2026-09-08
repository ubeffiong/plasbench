#!/usr/bin/env python3
"""Regression test for the checksum-pinned BMock12 truth materializer."""
import csv
import gzip
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))
from materialize_bmock12_truth import write_truth  # noqa: E402


def md5(path):
    return hashlib.md5(path.read_bytes()).hexdigest()


def main():
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        fasta, graph, gold = tmp / "scaffolds.fasta.gz", tmp / "assembly.gfa.gz", tmp / "gold.gsa"
        with gzip.open(fasta, "wt", encoding="utf-8") as handle:
            handle.write(">NODE_1\nACGT\n")
        with gzip.open(graph, "wt", encoding="utf-8") as handle:
            handle.write("H\tVN:Z:1.0\n")
        gold.write_text("@Version:0.9.1\n@@SEQUENCEID\tBINID\t_LENGTH\nNODE_1\tgenome_a\t4\n", encoding="utf-8")
        sources = tmp / "sources.tsv"
        with sources.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, delimiter="\t", fieldnames=("cohort_id", "artifact_id", "role", "filename", "url", "md5"))
            writer.writeheader()
            for name, role, path in (("scaffolds", "assembly_fasta_gz", fasta), ("graph", "assembly_graph_gz", graph), ("gold", "gold_standard", gold)):
                writer.writerow({"cohort_id": "bmock12", "artifact_id": name, "role": role, "filename": path.name, "url": path.as_uri(), "md5": md5(path)})
        out = tmp / "out"
        command = [sys.executable, "python/materialize_bmock12_truth.py", "--out-dir", str(out), "--source-manifest", str(sources)]
        first = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        assert first.returncode == 0, first.stderr
        truth = out / "bmock12" / "truth_contigs.tsv"
        manifest = out / "bmock12" / "metagenomics-bmock12-verified.tsv"
        assert "NODE_1\tgenome_a\tchromosome" in truth.read_text(encoding="utf-8")
        validated = subprocess.run([sys.executable, "python/metagenomics.py", "validate", "--manifest", str(manifest)], cwd=ROOT, capture_output=True, text=True)
        assert validated.returncode == 0, validated.stderr
        predictions = tmp / "predictions" / "classifier"
        predictions.mkdir(parents=True)
        (predictions / "bmock12_illumina.classification.tsv").write_text(
            "contig_id\tpredicted_class\tplasmid_probability\tchromosome_probability\tphage_probability\tuncertainty_status\tsource_tool\tsupported_classes\n"
            "NODE_1\tchromosome\t0.01\t0.99\t0\tresolved\tfixture\tplasmid|chromosome\n",
            encoding="utf-8",
        )
        scored = subprocess.run([sys.executable, "python/metagenomics.py", "score", "--manifest", str(manifest), "--predictions-dir", str(tmp / "predictions"), "--out-dir", str(tmp / "results")], cwd=ROOT, capture_output=True, text=True)
        assert scored.returncode == 0, scored.stderr
        summary = (tmp / "results" / "metagenomics.classification_metrics.tsv").read_text(encoding="utf-8")
        assert "bmock12_illumina\tclassifier" in summary and "\t1.0\t" in summary
        second = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        assert second.returncode == 0 and "reuse verified" in second.stdout
        duplicate = tmp / "duplicate.gsa"
        duplicate.write_text("contig_a\tbin_a\ncontig_a\tbin_b\n", encoding="utf-8")
        try:
            write_truth(duplicate, tmp / "should-not-exist.tsv")
        except ValueError as error:
            assert "duplicate contig membership" in str(error)
        else:
            raise AssertionError("duplicate gold-standard memberships must be rejected")
    print("BMOCK12 PHYSICAL GOLD-STANDARD MATERIALIZATION TEST PASSED")


if __name__ == "__main__":
    main()
