#!/usr/bin/env python3
"""Regression for python/flag_cohort_outliers.py: a planted N50 outlier is
flagged and its neighbors are not; a MAD==0 field is noted, not divided by
zero; a too-small cohort withholds detection rather than guessing. This is
advisory-only -- it must never exclude or block anything, only annotate."""

import csv
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SCRIPT = os.path.join(ROOT, "python", "flag_cohort_outliers.py")


def write(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def write_stats(data_dir, sample_id, assembly_size_bp=500000, contig_count=3, n50=100000, gc_percent=50.0, plasmid_count=2):
    sdir = os.path.join(data_dir, sample_id)
    os.makedirs(sdir, exist_ok=True)
    write(os.path.join(sdir, "assembly_stats.tsv"),
          "sample_id\tassembly_size_bp\tcontig_count\tn50\tgc_percent\tplasmid_count\n"
          f"{sample_id}\t{assembly_size_bp}\t{contig_count}\t{n50}\t{gc_percent}\t{plasmid_count}\n")


def run(data_dir, sheet, out, min_cohort_size=8, zscore_threshold=3.5):
    subprocess.run([sys.executable, SCRIPT, "--stats-dir", data_dir, "--samples", sheet, "--out", out,
                    "--min-cohort-size", str(min_cohort_size), "--zscore-threshold", str(zscore_threshold)],
                   check=True, capture_output=True, text=True)
    with open(out, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_sheet(tmp, sample_ids):
    path = os.path.join(tmp, "sheet.tsv")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("sample_id\tassembly_accession\tsra_run\n")
        for sample_id in sample_ids:
            handle.write(f"{sample_id}\tGCF_{sample_id}.1\tSRR{sample_id}\n")
    return path


def main():
    with tempfile.TemporaryDirectory(prefix="cohort_qc_") as tmp:
        data_dir = os.path.join(tmp, "data")
        sample_ids = [f"s{i}" for i in range(1, 8)]
        for i, sample_id in enumerate(sample_ids, start=1):
            write_stats(data_dir, sample_id, n50=100000 + i * 500)
        write_stats(data_dir, "s8", n50=5000)  # deliberately planted outlier
        sample_ids.append("s8")
        sheet = write_sheet(tmp, sample_ids)

        rows = run(data_dir, sheet, os.path.join(tmp, "flags.tsv"), min_cohort_size=8)
        n50_rows = {row["sample_id"]: row for row in rows if row["field"] == "n50"}
        assert n50_rows["s8"]["flagged"] == "true", "expected the planted N50 outlier to be flagged"
        for sample_id in sample_ids[:-1]:
            assert n50_rows[sample_id]["flagged"] == "false", f"expected {sample_id}'s n50 not to be flagged"
        assert "outlier" in n50_rows["s8"]["note"].lower()
        print("a planted N50 outlier is flagged; its neighbors are not -> PASS")

        # MAD == 0: every sample has identical gc_percent.
        gc_rows = [row for row in rows if row["field"] == "gc_percent" and row["cohort_mad"] == "0"]
        assert len(gc_rows) == 1, "expected exactly one MAD==0 note row for gc_percent"
        assert gc_rows[0]["sample_id"] == "" and gc_rows[0]["flagged"] == "false"
        assert "not meaningful" in gc_rows[0]["note"]
        print("a MAD==0 field is noted explicitly, not divided by zero or silently omitted -> PASS")

        # Never blocks/excludes: every one of the 8 samples appears in the one
        # field that actually varies (n50); the other fields are constant
        # across this fixture (MAD==0), which is covered separately above.
        present = {row["sample_id"] for row in rows if row["field"] == "n50"}
        assert present == set(sample_ids), f"expected every sample present for n50, got {present}"
        print("every sample is annotated, never excluded (advisory only) -> PASS")

    with tempfile.TemporaryDirectory(prefix="cohort_qc_small_") as tmp:
        data_dir = os.path.join(tmp, "data")
        sample_ids = [f"s{i}" for i in range(1, 6)]  # 5 < default min-cohort-size 8
        for sample_id in sample_ids:
            write_stats(data_dir, sample_id)
        sheet = write_sheet(tmp, sample_ids)
        rows = run(data_dir, sheet, os.path.join(tmp, "flags.tsv"), min_cohort_size=8)
        assert len(rows) == 1, f"expected exactly one withholding row, got {len(rows)}"
        assert rows[0]["sample_id"] == "" and rows[0]["flagged"] == "false"
        assert "5 sample" in rows[0]["note"] and "8 required" in rows[0]["note"]
        print("a too-small cohort withholds outlier detection rather than guessing -> PASS")

    print("ALL FLAG COHORT OUTLIERS TESTS PASSED")


if __name__ == "__main__":
    main()
