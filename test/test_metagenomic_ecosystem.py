#!/usr/bin/env python3
"""Regression coverage for ecosystem intake and synthetic-community controls."""
import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def write(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def main():
    with tempfile.TemporaryDirectory() as temporary:
        tmp = Path(temporary)
        intake = tmp / "intake.tsv"
        fields = ["candidate_id", "kind", "source_url", "license_review", "scope_fit", "truth_quality", "independence_review", "database_leakage_review", "output_contract", "dependency_status", "decision"]
        write(intake, fields, [{"candidate_id": "candidate", "kind": "tool", "source_url": "https://example.org/tool", "license_review": "approved", "scope_fit": "approved", "truth_quality": "not_applicable", "independence_review": "not_applicable", "database_leakage_review": "not_applicable", "output_contract": "approved", "dependency_status": "approved", "decision": "approved_for_evaluation"}])
        result = subprocess.run([sys.executable, "python/validate_metagenomic_intake.py", "--intake", str(intake)], cwd=ROOT, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        ref1, ref2 = tmp / "one.fasta", tmp / "two.fasta"
        ref1.write_text(">one\nACGT\n", encoding="utf-8"); ref2.write_text(">two\nTGCA\n", encoding="utf-8")
        members = tmp / "members.tsv"
        write(members, ["community_id", "sample_id", "reference_fasta", "abundance_percent", "coverage_x", "plasmid_copy_number", "community_complexity", "phage_burden", "contamination_level"], [{"community_id": "synthetic", "sample_id": "one", "reference_fasta": "one.fasta", "abundance_percent": "60", "coverage_x": "60", "plasmid_copy_number": "5", "community_complexity": "medium", "phage_burden": "low", "contamination_level": "low"}, {"community_id": "synthetic", "sample_id": "two", "reference_fasta": "two.fasta", "abundance_percent": "40", "coverage_x": "40", "plasmid_copy_number": "1", "community_complexity": "medium", "phage_burden": "low", "contamination_level": "low"}])
        out = tmp / "design"
        result = subprocess.run([sys.executable, "python/design_synthetic_communities.py", "--members", str(members), "--out-dir", str(out), "--seed", "7", "--simulator-version", "1.0", "--container-image", "registry/example", "--container-digest", "sha256:abc"], cwd=ROOT, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        manifest = out / "metagenomics.synthetic.tsv"
        assert manifest.is_file() and json.loads((out / "synthetic_community.provenance.json").read_text())["seed"] == 7
        audit = tmp / "audit.json"
        result = subprocess.run([sys.executable, "python/audit_metagenomic_cohort.py", "--manifest", str(manifest), "--out", str(audit)], cwd=ROOT, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert json.loads(audit.read_text())["communities"] == 1
        result = subprocess.run([sys.executable, "python/audit_metagenomic_cohort.py", "--manifest", str(manifest), "--out", str(audit), "--release-ready"], cwd=ROOT, capture_output=True, text=True)
        assert result.returncode != 0 and "synthetic" in result.stderr
    print("METAGENOMIC ECOSYSTEM INTAKE, SYNTHETIC DESIGN, AND AUDIT TEST PASSED")


if __name__ == "__main__":
    main()
