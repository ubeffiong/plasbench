#!/usr/bin/env python3
"""Adversarial metagenomic fixtures: unsupported classes and bad truth joins."""
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
META = ROOT / "python" / "metagenomics.py"


def write(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def main():
    with tempfile.TemporaryDirectory() as temporary:
        tmp = Path(temporary)
        truth = tmp / "truth.tsv"
        write(truth, ["contig_id", "truth_bin_id", "biological_class"], [
            {"contig_id": "p", "truth_bin_id": "p1", "biological_class": "plasmid"},
            {"contig_id": "c", "truth_bin_id": "c1", "biological_class": "chromosome"},
            {"contig_id": "v", "truth_bin_id": "v1", "biological_class": "virus"},
        ])
        manifest = tmp / "manifest.tsv"
        write(manifest, ["community_id", "sample_id", "information_regime", "truth_status", "truth_contigs_tsv"], [{"community_id": "c", "sample_id": "s", "information_regime": "single_sample", "truth_status": "synthetic", "truth_contigs_tsv": "truth.tsv"}])
        classifier = tmp / "pred" / "two_class" / "c.classification.tsv"
        fields = ["contig_id", "predicted_class", "plasmid_probability", "chromosome_probability", "phage_probability", "uncertainty_status", "source_tool", "supported_classes"]
        write(classifier, fields, [
            {"contig_id": "p", "predicted_class": "plasmid", "plasmid_probability": "0.9", "chromosome_probability": "0.1", "phage_probability": "0", "uncertainty_status": "resolved", "source_tool": "two_class", "supported_classes": "plasmid|chromosome"},
            {"contig_id": "c", "predicted_class": "chromosome", "plasmid_probability": "0.1", "chromosome_probability": "0.9", "phage_probability": "0", "uncertainty_status": "resolved", "source_tool": "two_class", "supported_classes": "plasmid|chromosome"},
            {"contig_id": "v", "predicted_class": "uncertain", "plasmid_probability": "0.5", "chromosome_probability": "0.5", "phage_probability": "0", "uncertainty_status": "uncertain", "source_tool": "two_class", "supported_classes": "plasmid|chromosome"},
        ])
        out = tmp / "out"
        result = subprocess.run([sys.executable, str(META), "score", "--manifest", str(manifest), "--predictions-dir", str(tmp / "pred"), "--out-dir", str(out)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        row = next(csv.DictReader((out / "metagenomics.classification_metrics.tsv").open(), delimiter="\t"))
        assert row["assessed_classes"] == "plasmid|chromosome" and row["macro_f1"] == "1.0", row
        # A community table that contradicts the same contig label must fail,
        # rather than silently using the final table encountered.
        other = tmp / "other.tsv"
        write(other, ["contig_id", "truth_bin_id", "biological_class"], [{"contig_id": "p", "truth_bin_id": "different", "biological_class": "plasmid"}])
        write(manifest, ["community_id", "sample_id", "information_regime", "truth_status", "truth_contigs_tsv"], [
            {"community_id": "c", "sample_id": "s1", "information_regime": "single_sample", "truth_status": "synthetic", "truth_contigs_tsv": "truth.tsv"},
            {"community_id": "c", "sample_id": "s2", "information_regime": "single_sample", "truth_status": "synthetic", "truth_contigs_tsv": "other.tsv"},
        ])
        result = subprocess.run([sys.executable, str(META), "score", "--manifest", str(manifest), "--predictions-dir", str(tmp / "pred"), "--out-dir", str(tmp / "conflict")], capture_output=True, text=True)
        assert result.returncode != 0 and "conflicting truth labels" in result.stderr
        # One graph-aware fixture deliberately splits p1, merges p1/p2, adds
        # chromosome/phage contamination, and leaves a bin unmatched.
        graph = tmp / "assembly.gfa"; graph.write_text("H\tVN:Z:1.0\n", encoding="utf-8")
        graph_truth = tmp / "graph_truth.tsv"
        write(graph_truth, ["contig_id", "truth_bin_id", "biological_class"], [
            {"contig_id": "p1", "truth_bin_id": "p1", "biological_class": "plasmid"},
            {"contig_id": "p2", "truth_bin_id": "p2", "biological_class": "plasmid"},
            {"contig_id": "c", "truth_bin_id": "c1", "biological_class": "chromosome"},
            {"contig_id": "v", "truth_bin_id": "v1", "biological_class": "virus"},
        ])
        write(manifest, ["community_id", "sample_id", "information_regime", "truth_status", "truth_contigs_tsv", "assembly_graph_gfa"], [{"community_id": "g", "sample_id": "s", "information_regime": "graph_aware", "truth_status": "synthetic", "truth_contigs_tsv": "graph_truth.tsv", "assembly_graph_gfa": "assembly.gfa"}])
        bins = tmp / "pred" / "graph" / "g.bins.tsv"
        bin_fields = ["predicted_bin_id", "contig_id", "graph_path", "orientation", "path_confidence", "plasmid_score", "ambiguity_status", "source_tool"]
        write(bins, bin_fields, [
            {"predicted_bin_id": "b1", "contig_id": "p1", "graph_path": "p1+", "orientation": "+", "path_confidence": "0.9", "plasmid_score": "0.9", "ambiguity_status": "resolved", "source_tool": "graph"},
            {"predicted_bin_id": "b2", "contig_id": "p1", "graph_path": "p1+", "orientation": "+", "path_confidence": "0.7", "plasmid_score": "0.8", "ambiguity_status": "ambiguous", "source_tool": "graph"},
            {"predicted_bin_id": "b2", "contig_id": "p2", "graph_path": "p2+", "orientation": "+", "path_confidence": "0.7", "plasmid_score": "0.8", "ambiguity_status": "ambiguous", "source_tool": "graph"},
            {"predicted_bin_id": "b2", "contig_id": "c", "graph_path": "c+", "orientation": "+", "path_confidence": "0.4", "plasmid_score": "0.7", "ambiguity_status": "ambiguous", "source_tool": "graph"},
            {"predicted_bin_id": "b2", "contig_id": "v", "graph_path": "v+", "orientation": "+", "path_confidence": "0.4", "plasmid_score": "0.7", "ambiguity_status": "ambiguous", "source_tool": "graph"},
            {"predicted_bin_id": "b3", "contig_id": "not_in_truth", "graph_path": "x+", "orientation": "+", "path_confidence": "0.2", "plasmid_score": "0.2", "ambiguity_status": "abstained", "source_tool": "graph"},
        ])
        result = subprocess.run([sys.executable, str(META), "score", "--manifest", str(manifest), "--predictions-dir", str(tmp / "pred"), "--out-dir", str(tmp / "adversarial")], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        summaries = list(csv.DictReader((tmp / "adversarial" / "metagenomics.summary.tsv").open(), delimiter="\t"))
        graph_row = next(row for row in summaries if row["tool"] == "graph")
        assert int(graph_row["split_truth_bins"]) == 1
        assert int(graph_row["unmatched_predicted_bins"]) == 1
        assert float(graph_row["chromosome_contamination_fraction"]) > 0
        assert float(graph_row["virus_contamination_fraction"]) > 0
    print("METAGENOMIC ADVERSARIAL TESTS PASSED")


if __name__ == "__main__": main()
