#!/usr/bin/env python3
"""End-to-end regression for the separated metagenomic graph/bin score path."""
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "python" / "metagenomics.py"


def write(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def main():
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        truth = temp / "truth.tsv"
        write(truth, ["contig_id", "truth_bin_id", "biological_class"], [
            {"contig_id": "p1a", "truth_bin_id": "p1", "biological_class": "plasmid"},
            {"contig_id": "p1b", "truth_bin_id": "p1", "biological_class": "plasmid"},
            {"contig_id": "p2", "truth_bin_id": "p2", "biological_class": "plasmid"},
            {"contig_id": "chr", "truth_bin_id": "chr", "biological_class": "chromosome"},
            {"contig_id": "phage", "truth_bin_id": "v1", "biological_class": "virus"},
        ])
        manifest = temp / "communities.tsv"
        write(manifest, ["community_id", "sample_id", "information_regime", "truth_status", "truth_contigs_tsv"], [
            {"community_id": "community", "sample_id": "A", "information_regime": "single_sample", "truth_status": "synthetic", "truth_contigs_tsv": "truth.tsv"},
        ])
        pred = temp / "predictions" / "graph_tool" / "community.bins.tsv"
        fields = ["predicted_bin_id", "contig_id", "graph_path", "orientation", "path_confidence", "plasmid_score", "ambiguity_status", "source_tool"]
        write(pred, fields, [
            {"predicted_bin_id": "a", "contig_id": "p1a", "graph_path": "p1a+", "orientation": "+", "path_confidence": "0.9", "plasmid_score": "0.9", "ambiguity_status": "resolved", "source_tool": "graph_tool"},
            {"predicted_bin_id": "a", "contig_id": "p1b", "graph_path": "p1b+", "orientation": "+", "path_confidence": "0.8", "plasmid_score": "0.9", "ambiguity_status": "resolved", "source_tool": "graph_tool"},
            {"predicted_bin_id": "b", "contig_id": "p2", "graph_path": "p2+", "orientation": "+", "path_confidence": "0.7", "plasmid_score": "0.8", "ambiguity_status": "ambiguous", "source_tool": "graph_tool"},
            {"predicted_bin_id": "b", "contig_id": "chr", "graph_path": "chr+", "orientation": "+", "path_confidence": "0.3", "plasmid_score": "0.7", "ambiguity_status": "ambiguous", "source_tool": "graph_tool"},
        ])
        validate = subprocess.run([sys.executable, str(SCRIPT), "validate", "--manifest", str(manifest)], capture_output=True, text=True)
        assert validate.returncode == 0 and "VALID" in validate.stdout, validate.stderr
        empty_score = subprocess.run([sys.executable, str(SCRIPT), "score", "--manifest", str(manifest), "--predictions-dir", str(temp / "empty-predictions"), "--out-dir", str(temp / "empty-out")], capture_output=True, text=True)
        assert empty_score.returncode == 2 and "no normalized prediction tables" in empty_score.stderr
        out = temp / "out"
        score = subprocess.run([sys.executable, str(SCRIPT), "score", "--manifest", str(manifest), "--predictions-dir", str(temp / "predictions"), "--out-dir", str(out)], capture_output=True, text=True)
        assert score.returncode == 0, score.stderr
        assert (out / "metagenomics.report.html").is_file()
        rows = list(csv.DictReader((out / "metagenomics.summary.tsv").open(), delimiter="\t"))
        assert len(rows) == 1 and rows[0]["matched_bins"] == "2", rows
        assert float(rows[0]["chromosome_contamination_fraction"]) > 0
        report = (out / "metagenomics.report.html").read_text(encoding="utf-8")
        assert "candidate bin is not a host assignment" in report
        assert "Community × tool matrix" in report
        assert "Artifact explorer" in report and "Export filtered CSV" in report
        assert "Community and upstream-processing provenance" in report
    print("METAGENOMICS SCORE AND REPORT TEST PASSED")


if __name__ == "__main__": main()
