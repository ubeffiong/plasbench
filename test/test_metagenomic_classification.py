#!/usr/bin/env python3
"""Regression coverage for three-class classifier normalization and scoring."""
import csv
import gzip
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
META = ROOT / "python" / "metagenomics.py"
NORMALIZE = ROOT / "python" / "normalize_metagenomic_classifier.py"
IMPORT = ROOT / "python" / "import_mobilome_evidence.py"


def write(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        raw = tmp / "ppr.csv"
        raw.write_text("Header,Length,phage_score,chromosome_score,plasmid_score,Possible_source\np,1000,0.05,0.05,0.90,plasmid\nc,1000,0.05,0.90,0.05,chromosome\nv,1000,0.90,0.05,0.05,phage\nu,1000,0.34,0.33,0.33,uncertain\n", encoding="utf-8")
        pred = tmp / "predictions" / "ppr_meta" / "community.classification.tsv"
        result = subprocess.run([sys.executable, str(NORMALIZE), "--tool", "ppr_meta", "--input", str(raw), "--out", str(pred), "--threshold", "0.7"], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        normalized = list(csv.DictReader(pred.open(), delimiter="\t"))
        assert normalized[-1]["predicted_class"] == "uncertain"
        assert normalized[0]["supported_classes"] == "plasmid|chromosome|virus"
        truth = tmp / "truth.tsv"
        write(truth, ["contig_id", "truth_bin_id", "biological_class"], [
            {"contig_id": "p", "truth_bin_id": "p1", "biological_class": "plasmid"},
            {"contig_id": "c", "truth_bin_id": "c1", "biological_class": "chromosome"},
            {"contig_id": "v", "truth_bin_id": "v1", "biological_class": "virus"},
            {"contig_id": "u", "truth_bin_id": "u1", "biological_class": "unknown"},
        ])
        gff = tmp / "mobilome.gff.gz"
        with gzip.open(gff, "wt", encoding="utf-8") as handle:
            handle.write("##gff-version 3\np\tMAP\tAMR_gene\t1\t100\t.\t+\t.\tID=amr1;product=beta-lactam resistance\n")
        evidence = tmp / "out" / "metagenomics.mobilome_evidence.tsv"
        result = subprocess.run([sys.executable, str(IMPORT), "--gff", str(gff), "--community", "community", "--sample", "s1", "--out", str(evidence)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        evidence_rows = list(csv.DictReader(evidence.open(), delimiter="\t"))
        assert evidence_rows[0]["evidence_role"] == "amr_context"
        manifest = tmp / "manifest.tsv"
        write(manifest, ["community_id", "sample_id", "information_regime", "truth_status", "truth_contigs_tsv", "dataset_class", "database_overlap_status", "mobilome_gff"], [{"community_id": "community", "sample_id": "s1", "information_regime": "single_sample", "truth_status": "synthetic", "truth_contigs_tsv": "truth.tsv", "dataset_class": "synthetic", "database_overlap_status": "none", "mobilome_gff": "mobilome.gff.gz"}])
        out = tmp / "out"
        result = subprocess.run([sys.executable, str(META), "score", "--manifest", str(manifest), "--predictions-dir", str(tmp / "predictions"), "--out-dir", str(out)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        metrics = list(csv.DictReader((out / "metagenomics.classification_metrics.tsv").open(), delimiter="\t"))
        assert len(metrics) == 1 and metrics[0]["macro_f1"] == "1.0", metrics
        report = (out / "metagenomics.report.html").read_text(encoding="utf-8")
        assert "Classification: mean macro F1 by tool" in report
        assert "Mobilome evidence timeline" in report
        assert "three-class calls".lower() in report.lower()
        run_manifest = (out / "metagenomics.run_manifest.json").read_text(encoding="utf-8")
        assert "database_overlap_status" in run_manifest and "sha256" in run_manifest
        release = subprocess.run([sys.executable, str(META), "validate", "--manifest", str(manifest), "--release-ready"], capture_output=True, text=True)
        assert release.returncode != 0 and "release-ready cohort lacks" in release.stderr
        hunter = tmp / "hunter.tsv"
        hunter.write_text("\tPrediction (0: chromosome, 1: plasmid)\tProbability of 0\tProbability of 1\n>p description\t1\t0.1\t0.9\n", encoding="utf-8")
        hunter_out = tmp / "hunter.classification.tsv"
        result = subprocess.run([sys.executable, str(NORMALIZE), "--tool", "plasmidhunter", "--input", str(hunter), "--out", str(hunter_out), "--threshold", "0.7"], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        hunter_rows = list(csv.DictReader(hunter_out.open(), delimiter="\t"))
        assert hunter_rows[0]["contig_id"] == "p" and hunter_rows[0]["supported_classes"] == "plasmid|chromosome"
    print("METAGENOMIC CLASSIFICATION AND EVIDENCE TEST PASSED")


if __name__ == "__main__": main()
