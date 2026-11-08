#!/usr/bin/env python3
"""Regression checks for the metric-rubric additions.

1. Contig labels (SHORT / PLASMID / CHROMOSOME / AMBIGUOUS / UNPLACED) and
   assembly-covered plasmid length.
2. Contig-level count-based and length-weighted precision/recall/F1/MCC; tools
   that output reassembled sequences are not applicable.
3. bp-weighted ARI and assembly-aware binning recall in score_bins.py.
4. Aggregation: micro (pooled) F1 beside macro, contig/ARI means, recovery of
   truth plasmids inside vs outside a tool's database.
5. HTML: metric-framework and database-membership sections.
"""

import csv
import math
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(HERE, "..", "python")
sys.path.insert(0, PY)


def run(args, check=True):
    return subprocess.run([sys.executable] + args, check=check, capture_output=True, text=True)


def write(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        handle.write(text)


def read(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def check(ok, label, condition, detail=""):
    print(f"  {label} -> {bool(condition)}{(' ' + detail) if detail else ''}")
    return ok and bool(condition)


def contig_checks(ok):
    write("truth.tsv", "sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t100000\np1\tPLASMID\t20000\n")
    contigs = {"cP1": 8000, "cP2": 4000, "cC1": 30000, "cC2": 20000, "cIS": 2000, "cU": 3000, "tiny": 400}
    write("contigs.fa", "".join(f">{name}\n{'A' * length}\n" for name, length in contigs.items()))
    write("c.paf", "".join([
        "cP1\t8000\t0\t8000\t+\tp1\t20000\t0\t8000\t8000\t8000\t60\n",
        "cP2\t4000\t0\t4000\t+\tp1\t20000\t10000\t14000\t3990\t4000\t60\n",
        "cC1\t30000\t0\t30000\t+\tchr\t100000\t0\t30000\t30000\t30000\t60\n",
        "cC2\t20000\t0\t20000\t+\tchr\t100000\t40000\t60000\t20000\t20000\t60\n",
        "cIS\t2000\t0\t2000\t+\tchr\t100000\t90000\t92000\t2000\t2000\t0\n",
        "cIS\t2000\t0\t2000\t+\tp1\t20000\t18000\t20000\t2000\t2000\t0\n",
        "cU\t3000\t0\t1000\t+\tchr\t100000\t70000\t71000\t1000\t1000\t60\n",
    ]))
    run([os.path.join(PY, "contig_classification.py"), "label", "--contigs", "contigs.fa", "--paf", "c.paf",
         "--truth", "truth.tsv", "--labels-out", "labels.tsv", "--coverage-out", "cov.tsv"])
    labels = {r["contig"]: r["label"] for r in read("labels.tsv")}
    ok = check(ok, "labels follow the stated rules", labels == {
        "cP1": "PLASMID", "cP2": "PLASMID", "cC1": "CHROMOSOME", "cC2": "CHROMOSOME",
        "cIS": "AMBIGUOUS", "cU": "UNPLACED", "tiny": "SHORT"}, str(labels))
    covered = read("cov.tsv")[0]
    ok = check(ok, "assembly covers 12 kb of the 20 kb plasmid", covered["assembly_covered_bp"] == "12000")

    # Tool calls cP1 (correct), cC2 (wrong, 20 kb) and misses cP2.
    write("pred.fa", ">cP1\nA\n>cC2\nA\n>cIS\nA\n")
    run([os.path.join(PY, "contig_classification.py"), "score", "--labels", "labels.tsv", "--pred-fasta", "pred.fa",
         "--out", "score.tsv"])
    s = read("score.tsv")[0]
    ok = check(ok, "count-based: TP1 FP1 FN1 TN1", (s["contig_tp"], s["contig_fp"], s["contig_fn"], s["contig_tn"])
               == ("1", "1", "1", "1"))
    ok = check(ok, "count-based precision/recall/F1 0.5, MCC 0",
               (s["contig_precision_count"], s["contig_f1_count"], s["contig_mcc_count"]) == ("0.5000", "0.5000", "0.0000"))
    tp, fp, fn, tn = 8000, 20000, 4000, 30000
    mcc = (tp * tn - fp * fn) / math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    ok = check(ok, "length-weighted MCC from base counts", s["contig_mcc_bp"] == f"{mcc:.4f}", s["contig_mcc_bp"])
    ok = check(ok, "excluded contigs counted, AMBIGUOUS call ignored",
               (s["contigs_short"], s["contigs_ambiguous"], s["contigs_unplaced"], s["contigs_evaluable"]) == ("1", "1", "1", "4"))
    write("reassembled.fa", ">plasmid_1_circular\nACGT\n")
    run([os.path.join(PY, "contig_classification.py"), "score", "--labels", "labels.tsv",
         "--pred-fasta", "reassembled.fa", "--out", "na.tsv"])
    ok = check(ok, "reassembled sequences are not applicable, not zero",
               read("na.tsv")[0]["contig_classification_status"].startswith("not_applicable")
               and read("na.tsv")[0]["contig_f1_count"] == "")
    return ok


def binning_checks(ok):
    from score_bins import adjusted_rand
    plasmids = {"p1": 1000, "p2": 1000}
    ok = check(ok, "ARI 1 for perfect bins", adjusted_rand({("B1", "p1"): 1000, ("B2", "p2"): 1000}, plasmids, {}) == 1.0)
    ok = check(ok, "ARI 0 when two plasmids are merged",
               abs(adjusted_rand({("B1", "p1"): 1000, ("B1", "p2"): 1000}, plasmids, {})) < 1e-9)
    write("btruth.tsv", "sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t100000\np1\tPLASMID\t20000\n")
    write("bins.tsv", "sequence_id\tbin_id\nc1\tB1\n")
    write("b.paf", "c1\t10000\t0\t10000\t+\tp1\t20000\t0\t10000\t10000\t10000\t60\n")
    write("bcov.tsv", "sequence_id\tlength\tassembly_covered_bp\np1\t20000\t10000\n")
    run([os.path.join(PY, "score_bins.py"), "--truth", "btruth.tsv", "--paf", "b.paf", "--bins", "bins.tsv",
         "--out", "bm.tsv", "--summary", "bs.tsv", "--assembly-coverage", "bcov.tsv"])
    summary = read("bs.tsv")[0]
    ok = check(ok, "recall 0.5 against the full plasmid, 1.0 against what the assembly covers",
               summary["lw_bin_recall"] == "0.5000" and summary["lw_bin_recall_assembly_aware"] == "1.0000")
    ok = check(ok, "ARI reported in the bin summary", summary["bin_ari"] != "")
    return ok


def aggregate_checks(ok):
    header = ["sample", "tool", "analysis_track", "true_plasmid_count", "precision", "recall", "f1", "TP_bp", "FP_bp",
              "FN_bp", "contig_f1_bp", "contig_mcc_bp", "bin_ari"]
    # A small isolate scored badly and a large one scored well: the macro mean
    # weighs them equally, the micro (pooled-base) average weighs by size.
    rows = [["s1", "mob_recon", "short_read", 1, 1.0, 0.1, 0.1818, 1000, 0, 9000, 0.7, 0.6, 0.8],
            ["s2", "mob_recon", "short_read", 1, 1.0, 1.0, 1.0, 100000, 0, 0, 0.9, 0.8, 0.6]]
    os.makedirs("results/s1", exist_ok=True)
    os.makedirs("results/s2", exist_ok=True)
    with open("results/scores.tsv", "w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    write("results/s1/mob_recon.per_plasmid.tsv", "sample\ttool\tanalysis_track\tsequence_id\tlength\tcovered_bp\t"
          "completeness\trecovered\ns1\tmob_recon\tshort_read\tpA\t1000\t900\t0.9000\t1\n")
    write("results/s2/mob_recon.per_plasmid.tsv", "sample\ttool\tanalysis_track\tsequence_id\tlength\tcovered_bp\t"
          "completeness\trecovered\ns2\tmob_recon\tshort_read\tpB\t1000\t300\t0.3000\t0\n")
    write("results/containment.tsv", "sample\tsequence_id\tlength\ttools\tdatabase\tbest_record\tcoverage\tidentity\t"
          "in_database\ns1\tpA\t1000\tmob_recon,flye_mob_recon\tdb.fas\tNZ_1\t0.99\t0.999\tyes\n"
          "s2\tpB\t1000\tmob_recon,flye_mob_recon\tdb.fas\t\t0.10\t0.90\tno\n")
    run([os.path.join(PY, "aggregate_results.py"), "--scores", "results/scores.tsv",
         "--database-containment", "results/containment.tsv", "--out-prefix", "results/benchmark"])
    board = {r["tool"]: r for r in read("results/benchmark.leaderboard.tsv")}["mob_recon"]
    micro = 2 * 101000 / (2 * 101000 + 0 + 9000)
    ok = check(ok, "micro F1 pools bases and differs from the macro mean",
               board["micro_f1"] == f"{micro:.4f}" and board["mean_f1"] == "0.5909" and board["micro_f1"] != board["mean_f1"],
               f"(micro {board['micro_f1']}, macro {board['mean_f1']})")
    ok = check(ok, "contig and ARI means aggregated",
               board["mean_contig_mcc_bp"] == "0.7000" and board["mean_bin_ari"] == "0.7000")
    ok = check(ok, "recovery split by database membership",
               (board["n_plasmids_in_tool_database"], board["mean_recovery_in_tool_database"],
                board["mean_recovery_not_in_tool_database"]) == ("1", "0.9000", "0.3000"))

    import report_question_bank as rq
    page = "<nav><a href='#recommendations'>Recommendations</a></nav><section id='recommendations'></section>"
    html_out = rq.inject(page, "results", read("results/benchmark.leaderboard.tsv"))
    ok = check(ok, "metric framework and database sections render with nav links",
               "id='metric-framework'" in html_out and "id='database-membership'" in html_out
               and "href='#metric-framework'" in html_out and "+0.600" in html_out)
    return ok


def containment_checks(ok):
    if not shutil.which("minimap2"):
        print("  database containment: minimap2 not installed here, skipped (exercised on Linux)")
        return ok
    seq = "ACGTTGCAAGGCTTAGCCATGGATCC" * 300
    write("data/s1/reference.fna", f">chr\n{'T' * 5000}\n>pX\n{seq}\n")
    write("data/s1/truth.tsv", f"sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t5000\npX\tPLASMID\t{len(seq)}\n")
    write("db.fas", f">NZ_known\n{seq}\n")
    run([os.path.join(PY, "database_containment.py"), "--data-dir", "data", "--samples", "s1",
         "--database", "mob_recon=db.fas", "--out", "cont.tsv"])
    rows = read("cont.tsv")
    ok = check(ok, "identical plasmid found in the database", rows and rows[0]["in_database"] == "yes")
    return ok


def main():
    ok = True
    with tempfile.TemporaryDirectory(prefix="metric_rubric_") as tmp:
        try:
            os.chdir(tmp)
            for step in (contig_checks, binning_checks, aggregate_checks, containment_checks):
                print(f"[{step.__name__}]")
                ok = step(ok)
        finally:
            os.chdir(HERE)
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
