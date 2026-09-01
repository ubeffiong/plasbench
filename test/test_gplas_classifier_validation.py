#!/usr/bin/env python3
"""Regression checks for externally supplied gplas classifier tables."""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "python", "validate_gplas_classifier.py")

def main():
    with tempfile.TemporaryDirectory() as directory:
        graph = os.path.join(directory, "graph.gfa")
        table = os.path.join(directory, "classifier.tsv")
        open(graph, "w").write("S\ta\tAAAA\nS\tb\tCCCCC\n")
        open(table, "w").write("Prob_Chromosome\tProb_Plasmid\tPrediction\tContig_name\tContig_length\n1\t0\tChromosome\ta\t4\n0\t1\tPlasmid\tb\t5\n")
        subprocess.run([sys.executable, SCRIPT, "--graph", graph, "--classifier", table, "--min-contig-length", "4"], check=True)
        open(table, "w").write("Prob_Chromosome\tProb_Plasmid\tPrediction\tContig_name\tContig_length\n1\t0\tChromosome\ta\t4\n")
        result = subprocess.run([sys.executable, SCRIPT, "--graph", graph, "--classifier", table, "--min-contig-length", "4"], text=True, capture_output=True)
        assert result.returncode != 0 and "omits 1 eligible graph node" in result.stderr
    print("ALL GPLAS CLASSIFIER VALIDATION TESTS PASSED")

if __name__ == "__main__":
    main()
