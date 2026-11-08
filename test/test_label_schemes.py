#!/usr/bin/env python3
"""Label schemes (python/label_schemes.py): Scheme 3 (ncbi) is primary, Scheme 1
makes every non-main replicon a plasmid, the evidence scheme follows
truth_labels.tsv; the NCBI field and report checksum are pinned; isolates without
a report are marked not_applicable; collect writes the per-scheme summary."""
import csv
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "python" / "label_schemes.py"
sys.path.insert(0, str(ROOT / "python"))
import label_schemes  # noqa: E402


def write(path, text):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf-8")


def rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def main():
    assert label_schemes.truth_file_for("ncbi") == "truth.tsv"
    assert label_schemes.truth_file_for("evidence") == "truth.scored.tsv"
    try:
        label_schemes.truth_file_for("bogus")
        raise AssertionError("unknown scheme accepted")
    except ValueError:
        pass
    print("  PASS: scheme -> truth file mapping, unknown scheme rejected")

    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        # S1: main chromosome, chromid labelled CHROMOSOME, one plasmid with evidence AMBIGUOUS.
        write(data / "S1" / "truth.tsv", "sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t5000000\n"
              "chromid\tCHROMOSOME\t1000000\np1\tPLASMID\t50000\n")
        write(data / "S1" / "sequence_report.jsonl", '{"genbankAccession":"chr"}\n')
        write(data / "S1" / "truth_labels.tsv", "sequence_id\tfinal_label\treason\nchr\tCHROMOSOME\tok\n"
              "chromid\tAMBIGUOUS\tchromid-like\np1\tPLASMID\tmarker\n")
        write(data / "S1" / "truth.corrections.tsv", "sequence_id\tmultimer\taction\np1\tyes\tcollapsed\n")
        subprocess.run([sys.executable, str(SCRIPT), "build", "--sample", "S1",
                        "--truth", str(data / "S1" / "truth.tsv"), "--report", str(data / "S1" / "sequence_report.jsonl"),
                        "--evidence-labels", str(data / "S1" / "truth_labels.tsv"),
                        "--multimers", str(data / "S1" / "truth.corrections.tsv"),
                        "--nonchromosomal-out", str(data / "S1" / "truth.nonchromosomal.tsv"),
                        "--out", str(data / "S1" / "label_schemes.tsv")], check=True)
        table = {r["sequence_id"]: r for r in rows(data / "S1" / "label_schemes.tsv")}
        assert table["chromid"]["ncbi_label"] == "CHROMOSOME"
        assert table["chromid"]["nonchromosomal_label"] == "PLASMID"
        assert table["chromid"]["evidence_label"] == "AMBIGUOUS"
        assert table["chromid"]["schemes_agree"] == "no" and table["chr"]["schemes_agree"] == "yes"
        assert table["p1"]["multimer"] == "collapsed"
        sha = hashlib.sha256((data / "S1" / "sequence_report.jsonl").read_bytes()).hexdigest()
        assert table["chr"]["ncbi_label_field"] == "assigned_molecule_location_type"
        assert table["chr"]["ncbi_report_sha256"] == sha and table["chr"]["ncbi_report_retrieved"]
        scheme1 = {r["sequence_id"]: r["molecule_type"] for r in rows(data / "S1" / "truth.nonchromosomal.tsv")}
        assert scheme1 == {"chr": "CHROMOSOME", "chromid": "PLASMID", "p1": "PLASMID"}, scheme1
        print("  PASS: three labels per replicon; chromid differs; NCBI field and report SHA-256 pinned")

        # S2: in-house isolate, no report, no evidence labels.
        write(data / "S2" / "truth.tsv", "sequence_id\tmolecule_type\tlength\nc\tCHROMOSOME\t4000000\n"
              "q\tPLASMID\t3000\n")
        subprocess.run([sys.executable, str(SCRIPT), "build", "--sample", "S2", "--truth", str(data / "S2" / "truth.tsv"),
                        "--report", str(data / "S2" / "missing.jsonl"), "--truth-source", "self_assembled_hybrid",
                        "--nonchromosomal-out", str(data / "S2" / "truth.nonchromosomal.tsv"),
                        "--out", str(data / "S2" / "label_schemes.tsv")], check=True)
        s2 = rows(data / "S2" / "label_schemes.tsv")
        assert all(r["ncbi_label_field"] == "not_applicable:self_assembled_hybrid" for r in s2)
        assert all(r["evidence_label"] == "not_evaluated" for r in s2)
        print("  PASS: an in-house isolate is marked not_applicable:<truth_source>, never database-labelled")

        out, summary = Path(tmp) / "b.label_schemes.tsv", Path(tmp) / "b.summary.tsv"
        subprocess.run([sys.executable, str(SCRIPT), "collect", "--data-dir", str(data), "--out", str(out),
                        "--summary-out", str(summary)], check=True)
        assert len(rows(out)) == 5
        by_scheme = {r["scheme"]: r for r in rows(summary)}
        assert by_scheme["ncbi"]["role"] == "primary" and by_scheme["ncbi"]["plasmids"] == "2"
        assert by_scheme["nonchromosomal"]["plasmids"] == "3"
        assert by_scheme["nonchromosomal"]["plasmids_differing_from_primary"] == "1"
        assert by_scheme["evidence"]["excluded_replicons"] == "1"
        print("  PASS: collect -> per-scheme summary (primary ncbi; Scheme 1 adds the chromid; evidence excludes 1)")
    print("ALL LABEL SCHEME TESTS PASSED")


if __name__ == "__main__":
    main()
