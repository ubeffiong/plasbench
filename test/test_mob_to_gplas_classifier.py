#!/usr/bin/env python3
"""Regression checks for deterministic MOB-to-gplas seed conversion."""
import csv
import json
import os
import subprocess
import sys
import tempfile


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "python", "mob_to_gplas_classifier.py")


def main():
    with tempfile.TemporaryDirectory() as directory:
        graph = os.path.join(directory, "assembly.gfa")
        mob = os.path.join(directory, "mob")
        os.mkdir(mob)
        open(graph, "w").write("H\tVN:Z:1.0\nS\tcontig_a\tAAAA\nS\tcontig_b\tCCCCC\nS\tshort\tTT\n")
        open(os.path.join(mob, "plasmid_1.fasta"), "w").write(">contig_a description\nAAAA\n")
        out = os.path.join(directory, "classifier.tsv")
        provenance = os.path.join(directory, "classifier.json")
        subprocess.run([sys.executable, SCRIPT, "--graph", graph, "--mob-output", mob,
                        "--out", out, "--provenance", provenance, "--min-contig-length", "4"], check=True)
        rows = list(csv.DictReader(open(out), delimiter="\t"))
        assert [row["Contig_name"] for row in rows] == ["contig_a", "contig_b"]
        assert rows[0]["Prediction"] == "Plasmid" and rows[0]["Prob_Plasmid"] == "1.0"
        assert rows[1]["Prediction"] == "Chromosome" and rows[1]["Prob_Chromosome"] == "1.0"
        evidence = json.load(open(provenance))
        assert evidence["method"] == "mob_recon_hard_label_transfer"
        assert evidence["matched_graph_plasmid_nodes"] == 1 and evidence["graph"]["eligible_nodes"] == 2

        open(os.path.join(mob, "plasmid_1.fasta"), "w").write(">not_a_graph_node\nAAAA\n")
        invalid = subprocess.run([sys.executable, SCRIPT, "--graph", graph, "--mob-output", mob,
                                  "--out", out, "--provenance", provenance, "--min-contig-length", "4"],
                                 text=True, capture_output=True)
        assert invalid.returncode != 0 and "do not match graph nodes" in invalid.stderr
    print("ALL MOB-TO-GPLAS CLASSIFIER TESTS PASSED")


if __name__ == "__main__":
    main()
