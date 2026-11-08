#!/usr/bin/env python3
"""python/copy_number.py.

Fixture: assembly has chromosome contig (20 kb, depth 50, in no bin) and plasmid contig (5 kb, depth 150)
in bin b1 -> pcn_pred = 150 / 50 = 3.0. Truth: chr depth 40, p1 depth 120 -> pcn_truth 120 / 40 = 3.0
-> log2 0. A bin at depth 300 -> 6.0 / 3.0 = 2 -> log2 1.
Unicycler form: header `1 length=20000 depth=50.00x`, `2 length=5000 depth=150.00x`.
Length-weighted mean of a bin with 1000 bp @100 and 3000 bp @200: (100000 + 600000)/4000 = 175.
Weighted median [(50, 20000), (10, 1000)] = 50.
"""
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import copy_number as cn  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))
    if not cond:
        FAILED.append(name)


def fa(records):
    return "".join(f">{h}\n{'A' * n}\n" for h, n in records)


def one(tmp, name, fasta, bins, tdepth="good", matches=True):
    tmp.mkdir(exist_ok=True)
    (tmp / "truth.tsv").write_text("sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t100000\np1\tPLASMID\t5000\n")
    (tmp / "contigs.fasta").write_text(fasta)
    (tmp / "bins.tsv").write_text("sequence_id\tbin_id\n" + "".join(f"{s}\t{b}\n" for s, b in bins))
    (tmp / "m.tsv").write_text("bin_id\ttrue_plasmid\taligned_bp\ttruth_completeness\tbin_purity\t"
                               "chromosome_aligned_bp\trepeat_ambiguity_bp\tcontamination_fraction\tmatch_status\n"
                               + "b1\tp1\t5000\t1\t1\t0\t0\t0\tmatched\n" * matches)
    if tdepth == "good":
        (tmp / "depth.tsv").write_text("sequence_id\tlength\tmean_depth\treads\nchr\t100000\t40.00\t9\np1\t5000\t120.00\t3\n")
    else:  # genome-wide observed_depth.tsv shape
        (tmp / "depth.tsv").write_text("reference_bp\tread_bases\tobserved_depth_x\n105000\t4200000\t40.000000\n")
    return cn.compute_rows("s", "T", "short_read", tmp / "truth.tsv", tmp / "bins.tsv", tmp / "contigs.fasta",
                           tmp / "depth.tsv", matches=tmp / "m.tsv")


def main():
    check("spades header", cn.parse_header("NODE_1_length_5000_cov_150.5") == (5000, 150.5))
    check("unicycler header", cn.parse_header("2 length=5000 depth=150.00x circular=true") == (5000, 150.0))
    check("no depth header", cn.parse_header("contig_7") is None)
    check("strip suffixes", cn.normalise_id("NODE_1_length_5_cov_2'") == "NODE_1_length_5_cov_2"
          and cn.normalise_id("ctg1_R") == "ctg1")
    check("weighted median", cn.weighted_median([(50, 20000), (10, 1000)]) == 50)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        spades = fa([("NODE_1_length_20000_cov_50.0", 20000), ("NODE_2_length_5000_cov_150.0", 5000)])
        r = one(tmp / "a", "a", spades, [("NODE_2_length_5000_cov_150.0", "b1")])
        check("spades pcn 3 / truth 3 / log2 0", len(r) == 1 and r[0]["status"] == "ok" and r[0]["pcn_pred"] == "3.0000"
              and r[0]["pcn_truth"] == "3.0000" and float(r[0]["log2_ratio"]) == 0, r)
        # reverse-strand suffix in the bins file still resolves
        r = one(tmp / "a2", "a", spades, [("NODE_2_length_5000_cov_150.0'", "b1")])
        check("reverse suffix resolved", r[0]["pcn_pred"] == "3.0000", r)

        uni = fa([("1 length=20000 depth=50.00x circular=true", 20000), ("2 length=5000 depth=150.00x", 5000)])
        r = one(tmp / "b", "b", uni, [("2", "b1")])
        check("unicycler pcn", r[0]["pcn_pred"] == "3.0000" and r[0]["status"] == "ok", r)

        hi = fa([("NODE_1_length_20000_cov_50.0", 20000), ("NODE_2_length_5000_cov_300.0", 5000)])
        r = one(tmp / "c", "c", hi, [("NODE_2_length_5000_cov_300.0", "b1")])
        check("depth 300 -> pcn 6, log2 1", r[0]["pcn_pred"] == "6.0000" and float(r[0]["log2_ratio"]) == 1.0, r)

        plain = fa([("c1", 20000), ("c2", 5000)])
        r = one(tmp / "d", "d", plain, [("c2", "b1")])
        check("no depth headers status", r[0]["status"] == "no_depth_headers", r)

        r = one(tmp / "e", "e", spades, [("NODE_2_length_5000_cov_150.0", "b1")], tdepth="genome")
        check("genome-wide depth -> no_truth_depth", r[0]["status"] == "no_truth_depth" and r[0]["pcn_pred"] == "3.0000", r)

        r = one(tmp / "f", "f", spades, [("reassembled_seq_1", "b1")])
        check("reassembled tool not applicable", r[0]["status"] == "not_applicable_not_assembly_contigs", r)

        r = one(tmp / "g", "g", fa([("NODE_2_length_5000_cov_150.0", 5000)]), [("NODE_2_length_5000_cov_150.0", "b1")])
        check("no chromosome estimate", r[0]["status"] == "no_chromosome_estimate", r)

        r = cn.compute_rows("s", "T", "short_read", tmp / "a" / "truth.tsv", tmp / "none.tsv", tmp / "a" / "contigs.fasta",
                            tmp / "a" / "depth.tsv")
        check("no bins status", r[0]["status"] == "no_bins", r)

        # PAF-based matching
        d = tmp / "a"
        (d / "t.paf").write_text("NODE_2_length_5000_cov_150.0\t5000\t0\t5000\t+\tp1\t5000\t0\t5000\t5000\t5000\t60\n")
        r = cn.compute_rows("s", "T", "short_read", d / "truth.tsv", d / "bins.tsv", d / "contigs.fasta", d / "depth.tsv",
                            paf=d / "t.paf")
        check("paf matching", len(r) == 1 and r[0]["true_plasmid"] == "p1" and r[0]["log2_ratio"].startswith("0"), r)

        # CLI, shard write, merge, summary
        res = tmp / "res" / "s"
        res.mkdir(parents=True)
        for tool, bins in (("T1", "NODE_2_length_5000_cov_150.0"), ("T2", "NODE_2_length_5000_cov_150.0")):
            out = res / f"{tool}.copy_number.tsv"
            p = subprocess.run([sys.executable, str(ROOT / "python" / "copy_number.py"), "--truth", str(d / "truth.tsv"),
                                "--bins", str(d / "bins.tsv"), "--matches", str(d / "m.tsv"),
                                "--contigs-fasta", str(d / "contigs.fasta"), "--truth-depth", str(d / "depth.tsv"),
                                "--sample", "s", "--tool", tool, "--analysis-track", "short_read", "--out", str(out)],
                               capture_output=True, text=True)
            check(f"cli {tool}", p.returncode == 0, p.stderr)
        merged = tmp / "merged.tsv"
        p = subprocess.run([sys.executable, str(ROOT / "python" / "copy_number.py"), "merge", "--results-dir",
                            str(tmp / "res"), "--out", str(merged)], capture_output=True, text=True)
        with open(merged, newline="", encoding="utf-8") as h:
            mrows = list(csv.DictReader(h, delimiter="\t"))
        check("merge two shards", p.returncode == 0 and [x["tool"] for x in mrows] == ["T1", "T2"], p.stderr)
        mrows[1]["log2_ratio"] = "1.0"   # factor 2 > 1.5
        mrows.append(dict(mrows[0], status="no_depth_headers"))
        s = cn.summarize(mrows)
        check("summary", s["T1"]["median_abs_log2_ratio"] == 0 and s["T1"]["fraction_within_1.5x"] == 1.0
              and s["T2"]["median_abs_log2_ratio"] == 1.0 and s["T2"]["fraction_within_1.5x"] == 0.0
              and s["T1"]["n"] == 1, s)
    if FAILED:
        print(f"{len(FAILED)} FAILED")
        sys.exit(1)
    print("all passed")


if __name__ == "__main__":
    main()
