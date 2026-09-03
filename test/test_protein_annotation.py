#!/usr/bin/env python3
"""Regression tests for normalized, cacheable protein annotation input."""
import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ANNOTATE = ROOT / "python" / "annotate_proteins.py"


with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    fasta = root / "plasmid.fasta"
    fasta.write_text(">p1\n" + "ATG" * 120 + "\n", encoding="utf-8")
    gff = root / "input.gff3"
    gff.write_text("##gff-version 3\np1\tBakta\tCDS\t10\t210\t.\t+\t0\tID=cds1;gene=blaX;product=beta-lactamase;Dbxref=AMRFinder:abc\n", encoding="utf-8")
    out, provenance, cache = root / "proteins.tsv", root / "provenance.json", root / "cache"
    command = [sys.executable, str(ANNOTATE), "--fasta", str(fasta), "--out", str(out), "--provenance", str(provenance),
               "--engine", "none", "--reuse-gff", str(gff), "--cache-dir", str(cache)]
    subprocess.run(command, check=True)
    row = next(csv.DictReader(out.open(encoding="utf-8"), delimiter="\t"))
    assert row["gene"] == "blaX" and row["category"] == "amr", row
    first = json.loads(provenance.read_text(encoding="utf-8"))
    assert first["status"] == "ok" and first["sequence_sha256"], first
    subprocess.run(command, check=True)
    second = json.loads(provenance.read_text(encoding="utf-8"))
    assert second["cache"] == "reused", second

print("ALL PROTEIN ANNOTATION TESTS PASSED")
