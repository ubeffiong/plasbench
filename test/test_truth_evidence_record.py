#!/usr/bin/env python3
"""
Each reference carries a structured evidence record (python/truth_provenance.py): six fields, declared / inferred / unknown, from which the tier is derived.

  - sample-sheet columns are recorded as declared; read support and replicon evidence are inferred from truth_labels.tsv; the technology is inferred from NCBI metadata;
  - a value outside a field's vocabulary is an error naming the column; unknown values never demote a Tier-1 reference; an explicit adverse value caps it at Tier 2 and says why;
  - evidence_recorded counts the known fields, evidence_sources says declared / inferred / unknown per field;
  - the original provenance columns keep their order and the new ones are appended (older readers are unaffected);
  - the report shows an Evidence recorded column; the demo declares some evidence and the demo script builds the provenance table before it aggregates.
"""
import csv
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import truth_provenance as tp  # noqa: E402

ORIGINAL = ["sample", "truth_assembly_strategy", "truth_polish_reads", "provenance_source", "base_level_metrics_valid", "labels_evidence_checked", "reference_tier",
            "tier_reason", "provenance_reason", "ambiguous_plasmids", "marker_free_plasmids", "truth_quality_grade", "grade_reason"]


def labels(data, sample, rows):
    folder = Path(data) / sample
    folder.mkdir(parents=True, exist_ok=True)
    cols = ["sequence_id", "length", "source_label", "final_label", "evidence_status", "plasmid_markers", "plasmid_reference_match", "rrna_genes", "long_read_depth", "marker_free", "reason"]
    with open(folder / "truth_labels.tsv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=cols, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow({**{c: "" for c in cols}, **row})


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    base = {"sample_id": "s1", "truth_assembly_strategy": "long_read_only", "truth_polish_reads": "none", "truth_quality_tier": "A"}
    plasmid = {"sequence_id": "p1", "source_label": "PLASMID", "final_label": "PLASMID", "evidence_status": "evaluated", "plasmid_markers": "IncF", "long_read_depth": "30.0", "marker_free": "no"}
    chrom = {"sequence_id": "c1", "source_label": "CHROMOSOME", "final_label": "CHROMOSOME", "evidence_status": "evaluated"}

    print("the record")
    with tempfile.TemporaryDirectory() as data:
        labels(data, "s1", [chrom, plasmid])
        record = tp.derive({**base, "truth_circularity_evidence": "independent", "truth_structural_integrity": "resolved", "truth_independent_validation": "pcr",
                            "truth_technology": "long_read"}, data)
        check("declared fields are recorded as declared", record["circularity_evidence"] == "independent" and record["structural_integrity"] == "resolved"
              and record["independent_validation"] == "pcr" and record["assembly_technology"] == "long_read" and "circularity_evidence: declared" in record["evidence_sources"])
        check("read support and replicon evidence are inferred from truth_labels.tsv", record["read_support"] == "supported" and record["replicon_evidence"] == "markers_all"
              and "read_support: inferred" in record["evidence_sources"] and "replicon_evidence: inferred" in record["evidence_sources"], record)
        check("evidence_recorded counts the known fields", record["evidence_recorded"] == "6 of 6", record["evidence_recorded"])
        check("a fully evidenced long-read-first reference is Tier 1", record["reference_tier"] == "1", record["tier_reason"])
    with tempfile.TemporaryDirectory() as data:
        record = tp.derive(base, data)
        check("with nothing recorded every field is unknown and counted as such", record["evidence_recorded"] == "0 of 6" and all(record[f] == "unknown" for f in tp.EVIDENCE_FIELDS))
        check("unknown evidence never demotes: the same reference stays out of a worse tier for it", record["reference_tier"] in ("1", "2") and "evidence:" not in record["tier_reason"], record["tier_reason"])
    with tempfile.TemporaryDirectory() as data:
        labels(data, "s1", [chrom, plasmid])
        record = tp.derive({**base, "truth_read_support": "none"}, data)
        check("an explicit adverse value (read support none) caps Tier 1 at Tier 2 and says why", record["reference_tier"] == "2" and "evidence: read support none" in record["tier_reason"], record["tier_reason"])
        record = tp.derive({**base, "truth_structural_integrity": "unresolved_repeats"}, data)
        check("unresolved repeats also cap it at Tier 2", record["reference_tier"] == "2" and "structural integrity unresolved repeats" in record["tier_reason"], record["tier_reason"])
    with tempfile.TemporaryDirectory() as data:
        labels(data, "s1", [chrom, plasmid, {**plasmid, "sequence_id": "p2", "plasmid_markers": "", "marker_free": "yes", "long_read_depth": ""}])
        record = tp.derive(base, data)
        check("a marker-free plasmid makes replicon evidence partial, a plasmid without a depth makes read support partial",
              record["replicon_evidence"] == "markers_partial" and record["read_support"] == "partial", record)
    with tempfile.TemporaryDirectory() as data:
        folder = Path(data) / "s1"
        folder.mkdir()
        (folder / "assembly_data_report.jsonl").write_text(json.dumps({"assemblyInfo": {"assemblyMethod": "Flye v2.9", "sequencingTech": "Oxford Nanopore MinION; Illumina NovaSeq"}}) + "\n", encoding="utf-8")
        record = tp.derive({"sample_id": "s1", "truth_quality_tier": "A"}, data)
        check("the technology is inferred from the NCBI sequencing technology (long and short reads: hybrid)",
              record["assembly_technology"] == "hybrid" and "assembly_technology: inferred" in record["evidence_sources"], record["evidence_sources"])

    print("vocabularies and column order")
    for column, bad in (("truth_circularity_evidence", "maybe"), ("truth_read_support", "lots"), ("truth_structural_integrity", "fine"), ("truth_independent_validation", "vibes")):
        try:
            tp.derive({**base, column: bad}, None)
            named = False
        except ValueError as error:
            named = column in str(error)
        check(f"{column}: an unknown value is an error that names the column", named)
    check("the original provenance columns keep their order; the evidence columns are appended", tp.FIELDS[:len(ORIGINAL)] == ORIGINAL and tp.FIELDS[-10:-4] == list(tp.EVIDENCE_FIELDS)
          and tp.FIELDS[-2:] == ["reference_independence", "reference_group"]   # appended after the evidence columns (second review)
          and tp.FIELDS[-4:-2] == ["evidence_recorded", "evidence_sources"], tp.FIELDS)

    print("the command, the report and the demo")
    with tempfile.TemporaryDirectory() as tmp:
        sheet = Path(tmp) / "samples.tsv"
        sheet.write_text("sample_id\ttruth_assembly_strategy\ttruth_polish_reads\ttruth_quality_tier\ttruth_circularity_evidence\ns1\tlong_read_only\tnone\tA\treported\n", encoding="utf-8")
        out = Path(tmp) / "prov.tsv"
        subprocess.run([sys.executable, str(ROOT / "python" / "truth_provenance.py"), "--sample-sheet", str(sheet), "--data-dir", tmp, "--out", str(out)], check=True, capture_output=True)
        row = next(csv.DictReader(open(out, newline="", encoding="utf-8"), delimiter="\t"))
        check("the written table has the evidence columns", row["circularity_evidence"] == "reported" and row["evidence_recorded"] == "1 of 6" and "evidence_sources" in row, row)
    import build_html_report as report  # noqa: E402
    line = report.provenance_evidence({"evidence_recorded": "2 of 6", "read_support": "supported", "circularity_evidence": "reported", "structural_integrity": "unknown"})
    check("the report line names the count and each recorded field but not the unknown ones", line.startswith("2 of 6:") and "read support supported" in line and "circularity evidence reported" in line
          and "structural" not in line, line)
    check("a provenance row from an older run reads 'not recorded'", report.provenance_evidence({"sample": "x"}) == "not recorded")
    demo = (ROOT / "test" / "demo_dataset.py").read_text(encoding="utf-8")
    script = (ROOT / "test" / "run_demo.sh").read_text(encoding="utf-8")
    check("the demo declares some evidence", "truth_circularity_evidence" in demo and "truth_read_support" in demo and "truth_structural_integrity" in demo)
    check("the demo builds the provenance table before it aggregates and passes it to the aggregation",
          script.index("truth_provenance.py") < script.index("aggregate_results.py") and '--truth-provenance "$DEMO/benchmark.truth_provenance.tsv" --out-prefix' in script)

    print()
    if not ok:
        print("TRUTH EVIDENCE RECORD TESTS FAILED")
        sys.exit(1)
    print("ALL TRUTH EVIDENCE RECORD TESTS PASSED")


if __name__ == "__main__":
    main()
