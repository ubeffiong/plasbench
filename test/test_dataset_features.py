#!/usr/bin/env python3
"""The dataset-characterisation table (plan C1): composition, the truth-free boundary, and the demo wiring."""
import csv
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import characterise_dataset as cd  # noqa: E402
import recommendation_model as rm  # noqa: E402


def write(path, header, rows):
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(header)
        writer.writerows(rows)


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    print("the truth-free boundary")
    check("no truth-free column is one the recommender forbids", not (set(cd.TRUTH_FREE) & rm.TRUTH_DERIVED_FIELDS), set(cd.TRUTH_FREE) & rm.TRUTH_DERIVED_FIELDS)
    allowed = set(rm.CONTINUOUS_FIELDS) | set(rm.CATEGORICAL_FIELDS)
    check("every recommender input that is a dataset feature is marked truth-free", all(f in cd.TRUTH_FREE for f in allowed if f in cd.COLUMNS), [f for f in allowed if f in cd.COLUMNS and f not in cd.TRUTH_FREE])
    check("the truth count of plasmids is marked as needing the reference", "plasmid_count" in cd.TRUTH_DERIVED and "plasmid_count" not in cd.TRUTH_FREE)
    sources = {name: src for name, basis, src, _l in cd.FEATURES if basis == "truth_free"}
    check("no truth-free column is read from a reference-derived file (only the sample sheet, the isolate's own contigs and its reads)", set(sources.values()) <= cd.TRUTH_FREE_SOURCES,
          {k: v for k, v in sources.items() if v not in cd.TRUTH_FREE_SOURCES})
    check("the reference's statistics file is not a source of any truth-free column", "assembly_stats.tsv" not in set(sources.values()))
    with tempfile.TemporaryDirectory() as t2:
        sheet = Path(t2) / "samples.tsv"
        sheet.write_text("# a comment line before the header\n# another\nsample_id\torganism\ns1\tE. coli\n")
        check("the sample sheet may carry comment lines (the shipped template does)", [r["sample_id"] for r in cd.read_rows(sheet)] == ["s1"])

    print("composition")
    with tempfile.TemporaryDirectory() as tmp:
        sdir = Path(tmp) / "s1"
        sdir.mkdir()
        write(sdir / "assembly_stats.tsv", ["sample_id", "assembly_size_bp", "contig_count", "n50", "gc_percent", "plasmid_count"], [["s1", "9999999", "77", "1", "11.0", "3"]])
        (sdir / "contigs.fasta").write_text(">c1\n" + "GGCC" * 100 + "AATT" * 100 + "\n>c2\n" + "GC" * 50 + "\n")
        write(sdir / "observed_read_quality.tsv", ["total_bases", "mean_phred_quality"], [["1000", "18.2"]])
        write(sdir / "truth_repeat_content.tsv", ["sample", "sequence_id", "molecule_type", "length", "n_kmers", "internal_repeat_fraction", "chromosome_shared_fraction",
                                                  "shared_with_other_plasmids_fraction", "repeat_rich", "status"],
              [["s1", "chr", "CHROMOSOME", "4000000", "", "", "", "", "", "chromosome_skipped"],
               ["s1", "p1", "PLASMID", "50000", "1", "0.10", "0.02", "0", "true", "ok"], ["s1", "p2", "PLASMID", "20000", "1", "0.30", "0.01", "0", "false", "ok"]])
        row = cd.characterise("s1", sdir, {"organism": "E. coli", "gram_group": "Gram-negative", "read_depth_x": "80"})
        check("the isolate's OWN assembly is measured (contigs.fasta), not the reference's stats", (row["input_n50"], row["input_contig_count"], row["input_assembly_size_bp"]) == ("800", "2", "900")
              and abs(float(row["input_gc_percent"]) - 100 * 500 / 900) < 0.01, row)
        check("quality and organism are read; the plasmid count still comes from the reference's table, as truth-derived", row["mean_read_quality"] == "18.2" and row["organism"] == "E. coli" and row["plasmid_count"] == "3", row)
        check("the worst plasmid repeat values and the repeat-rich count", row["max_internal_repeat_fraction"] == "0.3000" and row["repeat_rich_plasmids"] == "1", row)
        check("what no file gave stays blank, not zero", row["gfa_dead_end_count"] == "" and row["plasmid_chromosome_mash_distance"] == "")
        empty = cd.characterise("s2", Path(tmp) / "none", {})
        check("an isolate with no files is all blank", all(v == "" for k, v in empty.items() if k != "sample"))

    print("the demo")
    demo = ROOT / "results_demo"
    table, report = demo / "benchmark.dataset_features.tsv", demo / "benchmark.report.html"
    if not table.is_file() or not report.is_file():
        print("  SKIP: no results_demo (run test/run_demo.sh first)")
    else:
        with open(table, newline="") as handle:
            header = next(csv.reader(handle, delimiter="\t"))
        check("the demo table has every column", header == cd.COLUMNS, header)
        page = report.read_text(encoding="utf-8")
        check("the report shows it in the isolate-difficulty section with each basis", "Dataset characteristics" in page and "knowable without a reference" in page and "needs the reference: benchmark only" in page)
    print()
    if not ok:
        print("DATASET FEATURE TESTS FAILED")
        sys.exit(1)
    print("ALL DATASET FEATURE TESTS PASSED")


if __name__ == "__main__":
    main()
