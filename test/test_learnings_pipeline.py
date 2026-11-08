#!/usr/bin/env python3
"""
End to end across the modules added from PlasEval, plsMD and GAEMR, through their real command lines and the report:

  contig_classification label -> bin_agreement eval/dissim/merge/matrix -> assembly_adequacy merge
  -> copy_number (+ merge) -> report_learnings.inject

Synthetic isolate. Truth: P1 3000 bp, P2 2000 bp, chromosome 60000 bp. Contigs (SPAdes headers carry the depth):
  c_p1   2000 bp cov 150  aligns P1 0..2000        c_p1b 1500 bp cov 150  aligns P1 1500..3000
  c_p2   1200 bp cov 300  aligns P2 0..1200        c_chr1 20000 bp cov 50 and c_chr2 12000 bp cov 50 align the chromosome
  c_short 500 bp (SHORT)
Tool "toolA" bins: A = {c_p1, c_p1b}, B = {c_p2, c_chr2}.  Tool "toolB" bins: {c_p1, c_p1b, c_p2} in one bin.

Hand-computed:
  best-match, toolB (bp): one bin of 4700 bp whose best truth match is P1 (3500) -> precision 0.7447, recall 1.0.
  best-match, toolA (bp): predicted length 3500 + 13200 = 16700, matched 3500 + 1200 = 4700 -> precision 0.2814;
    truth plasmid contig length 3500 + 1200 = 4700, all matched -> recall 1.0; F1 = 0.4393.
  assembly adequacy: P1 covered 0..3000 = 3000, P2 covered 1200 of 2000 -> 4200 / 5000 = 0.84 < 0.90 -> adequate "no".
  copy number, bin A -> P1: tool 150 / chromosome estimate 50 = 3.0; truth 120 / 40 = 3.0 -> log2 ratio 0.
  tool agreement (alpha 0.5): toolA and toolB bins differ, so their dissimilarity is between 0 and 1 and the matrix lists the pair.
"""

import csv
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(HERE, "..", "python")
sys.path.insert(0, PY)

import report_learnings as rl  # noqa: E402

TAB, NL = chr(9), chr(10)


def run(script, *args):
    done = subprocess.run([sys.executable, os.path.join(PY, script), *args], capture_output=True, text=True)
    if done.returncode:
        raise SystemExit(f"{script} {' '.join(args)} failed: {done.stderr[-800:]}")
    return done


def write(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as handle:
        w = csv.writer(handle, delimiter=TAB, lineterminator=NL)
        w.writerow(header)
        w.writerows(rows)


def read(path):
    with open(path, newline="") as handle:
        return list(csv.DictReader(handle, delimiter=TAB))


def main():
    ok = True

    def check(label, condition):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}")

    tmp = tempfile.mkdtemp(prefix="learnings_")
    data, results = os.path.join(tmp, "data", "S1"), os.path.join(tmp, "results", "S1")
    os.makedirs(data)
    os.makedirs(results)
    write(os.path.join(data, "truth.tsv"), ["sequence_id", "molecule_type", "length"],
          [["P1", "PLASMID", 3000], ["P2", "PLASMID", 2000], ["chr", "CHROMOSOME", 60000]])
    contigs = [("c_p1", 2000, 150.0), ("c_p1b", 1500, 150.0), ("c_p2", 1200, 300.0), ("c_chr1", 20000, 50.0),
               ("c_chr2", 12000, 50.0), ("c_short", 500, 80.0)]
    with open(os.path.join(data, "contigs.fasta"), "w") as handle:
        for i, (name, length, cov) in enumerate(contigs, 1):
            handle.write(f">{name}_NODE_{i}_length_{length}_cov_{cov}{NL}{'A' * length}{NL}")
    # SPAdes-style ids so depth parses; the labelling and bins use the same ids.
    ids = {name: f"{name}_NODE_{i}_length_{length}_cov_{cov}" for i, (name, length, cov) in enumerate(contigs, 1)}

    def paf(contig, qend, target, tlen, ts, te):
        n = te - ts
        length = dict((c[0], c[1]) for c in contigs)[contig]
        return TAB.join(map(str, [ids[contig], length, 0, qend, "+", target, tlen, ts, te, n, n, 60])) + NL

    with open(os.path.join(tmp, "contigs.paf"), "w") as handle:
        handle.write(paf("c_p1", 2000, "P1", 3000, 0, 2000) + paf("c_p1b", 1500, "P1", 3000, 1500, 3000)
                     + paf("c_p2", 1200, "P2", 2000, 0, 1200) + paf("c_chr1", 20000, "chr", 60000, 0, 20000)
                     + paf("c_chr2", 12000, "chr", 60000, 20000, 32000) + paf("c_short", 500, "chr", 60000, 0, 500))
    run("contig_classification.py", "label", "--contigs", os.path.join(data, "contigs.fasta"),
        "--paf", os.path.join(tmp, "contigs.paf"), "--truth", os.path.join(data, "truth.tsv"),
        "--labels-out", os.path.join(data, "contig_labels.tsv"),
        "--coverage-out", os.path.join(data, "plasmid_assembly_coverage.tsv"))
    labels = {r["contig"]: r["label"] for r in read(os.path.join(data, "contig_labels.tsv"))}
    print("labels from the real labelling step")
    check("plasmid contigs, chromosome contigs and the short contig are labelled",
          labels[ids["c_p1"]] == "PLASMID" and labels[ids["c_chr1"]] == "CHROMOSOME" and labels[ids["c_short"]] == "SHORT")

    write(os.path.join(results, "pred_toolA.bins.tsv"), ["bin_id", "sequence_id"],
          [["A", ids["c_p1"]], ["A", ids["c_p1b"]], ["B", ids["c_p2"]], ["B", ids["c_chr2"]]])
    write(os.path.join(results, "pred_toolB.bins.tsv"), ["bin_id", "sequence_id"],
          [["X", ids["c_p1"]], ["X", ids["c_p1b"]], ["X", ids["c_p2"]]])
    write(os.path.join(results, "toolA.bin_matches.tsv"),
          ["bin_id", "true_plasmid", "aligned_bp", "truth_completeness", "bin_purity", "chromosome_aligned_bp",
           "repeat_ambiguity_bp", "contamination_fraction", "match_status"],
          [["A", "P1", 3000, "1.0", "1.0", 0, 0, "0", "matched"], ["B", "P2", 1200, "0.6", "0.1", 12000, 0, "0.9", "matched"]])
    write(os.path.join(data, "truth_long_read_depth.tsv"), ["sequence_id", "length", "mean_depth", "reads"],
          [["P1", 3000, 120.0, 100], ["P2", 2000, 240.0, 100], ["chr", 60000, 40.0, 1000]])
    write(os.path.join(tmp, "scores.tsv"), ["sample", "tool", "analysis_track", "f1"],
          [["S1", "toolA", "short_read", "0.7"], ["S1", "toolB", "short_read", "0.8"]])

    labels_path = os.path.join(data, "contig_labels.tsv")
    for tool in ("toolA", "toolB"):
        bins = os.path.join(results, f"pred_{tool}.bins.tsv")
        run("bin_agreement.py", "eval", "--labels", labels_path, "--bins", bins, "--sample", "S1", "--tool", tool,
            "--out", os.path.join(results, f"{tool}.bestmatch.tsv"))
        run("bin_agreement.py", "dissim", "--labels", labels_path, "--bins", bins, "--sample", "S1", "--tool", tool,
            "--out", os.path.join(results, f"{tool}.dissim.tsv"), "--export-prefix", os.path.join(results, f"{tool}.plaseval"))
    run("bin_agreement.py", "merge", "--scores", os.path.join(tmp, "scores.tsv"), "--results-dir", os.path.join(tmp, "results"))
    run("bin_agreement.py", "matrix", "--results-dir", os.path.join(tmp, "results"), "--data-dir", os.path.join(tmp, "data"),
        "--out", os.path.join(tmp, "results", "benchmark.tool_agreement.tsv"))
    scores = {r["tool"]: r for r in read(os.path.join(tmp, "scores.tsv"))}
    print("bin agreement, merged into scores.tsv")
    a = scores["toolA"]
    check("toolA best-match precision (bp) 0.2814", abs(float(a["bestmatch_precision_bp"]) - 4700 / 16700) < 1e-3)
    check("toolA best-match recall (bp) 1.0", abs(float(a["bestmatch_recall_bp"]) - 1.0) < 1e-9)
    check("toolA best-match F1 (bp) 0.4393", abs(float(a["bestmatch_f1_bp"]) - 0.4393) < 1e-3)
    b_row = scores["toolB"]
    check("toolB put both plasmids in one bin: best-match recall stays 1.0 (not one-to-one) but precision is 3500/4700",
          abs(float(b_row["bestmatch_recall_bp"]) - 1.0) < 1e-9 and abs(float(b_row["bestmatch_precision_bp"]) - 3500 / 4700) < 1e-3)
    check("dissimilarity is in (0, 1] for toolA", 0 < float(a["bin_dissimilarity"]) <= 1)
    check("PlasEval-format export written", os.path.isfile(os.path.join(results, "toolA.plaseval.pred_bins.tsv")))
    matrix = read(os.path.join(tmp, "results", "benchmark.tool_agreement.tsv"))
    check("the agreement matrix lists the tool pair", any({r["tool_a"], r["tool_b"]} == {"toolA", "toolB"} for r in matrix))

    run("assembly_adequacy.py", "merge", "--data-dir", os.path.join(tmp, "data"),
        "--out", os.path.join(tmp, "results", "benchmark.assembly_adequacy.tsv"))
    adequacy = read(os.path.join(tmp, "results", "benchmark.assembly_adequacy.tsv"))[0]
    print("assembly adequacy")
    check("plasmid adequacy 0.84", abs(float(adequacy["plasmid_adequacy"]) - 0.84) < 1e-3)
    check("flagged as not adequate at the 0.90 gate", adequacy["adequate"] == "no")

    run("copy_number.py", "--truth", os.path.join(data, "truth.tsv"), "--bins", os.path.join(results, "pred_toolA.bins.tsv"),
        "--matches", os.path.join(results, "toolA.bin_matches.tsv"), "--contigs-fasta", os.path.join(data, "contigs.fasta"),
        "--truth-depth", os.path.join(data, "truth_long_read_depth.tsv"), "--sample", "S1", "--tool", "toolA",
        "--analysis-track", "short_read", "--out", os.path.join(results, "toolA.copy_number.tsv"))
    run("copy_number.py", "merge", "--results-dir", os.path.join(tmp, "results"),
        "--out", os.path.join(tmp, "results", "benchmark.copy_number.tsv"))
    rows = {r["true_plasmid"]: r for r in read(os.path.join(tmp, "results", "benchmark.copy_number.tsv"))}
    print("copy number")
    check("bin A -> P1 copy number 3.0 against truth 3.0, log2 ratio 0",
          rows["P1"]["status"] == "ok" and abs(float(rows["P1"]["pcn_pred"]) - 3.0) < 1e-6
          and abs(float(rows["P1"]["pcn_truth"]) - 3.0) < 1e-6 and abs(float(rows["P1"]["log2_ratio"])) < 1e-6)

    print("the report shows all of it")
    page = rl.inject("<nav><a href='#recommendations'>Recommendations</a></nav><section id='recommendations'>x</section>",
                     os.path.join(tmp, "results"), os.path.join(tmp, "scores.tsv"))
    check("agreement values appear", ">0.4393<" in page)
    check("the adequacy flag appears", "contain less of the truth plasmids" in page)
    check("the copy-number table has a matched plasmid", "Matched plasmids" in page and "Not run: benchmark.copy_number" not in page)

    print()
    if not ok:
        print("LEARNINGS PIPELINE TESTS FAILED")
        sys.exit(1)
    print("ALL LEARNINGS PIPELINE TESTS PASSED")


if __name__ == "__main__":
    main()
