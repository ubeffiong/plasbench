#!/usr/bin/env python3
"""The binning F1 and CPRR headlines with and without the evidence-based truth exclusion (audit AU-051, remainder): truth_exclusion_sensitivity.py --rescore-reconstruction.

Hand calculation. Truth: plasmids p1 and p2 (1000 bp each) and a chromosome. The evidence truth (truth.scored.tsv) drops p2 as marker-free.
  Tool A bins one contig, q1 = p1 (all of it), and misses p2. Under NCBI truth: lw recall 1000/2000 = 0.5, precision 1.0, F1 = 2/3, CPRR = 1/2.
     Under the evidence truth: recall 1.0, precision 1.0, F1 = 1.0, CPRR = 1/1. Change +0.3333 and +0.5000.
  Tool B bins q1 = p1 and q2 = p2. NCBI: F1 1.0, CPRR 1.0. Evidence: p2 is no truth sequence, so q2's bin maps to nothing: precision 1.0, recall 1.0 -> F1 1.0, CPRR 1.0. Change 0.
  Ranks by lw F1: without B 1, A 2; with a tie at 1.0 broken by name, A 1, B 2: the top tool changes. A shares a database with the truth markers (yes), B does not.
Also: a tool with no bins file is left out, a sample missing truth.scored.tsv is left out of BOTH sides, and with no usable sample the script says so and writes no table."""
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ok = True


def check(label, good, detail=""):
    global ok
    print(f"  {'ok  ' if good else 'FAIL'}  {label}{'' if good else ' -> ' + str(detail)}")
    ok &= bool(good)


def write(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        if header:
            writer.writerow(header)
        writer.writerows(rows)


def paf(contig, target, tlen=1000):
    return [[contig, 1000, 0, 1000, "+", target, tlen, 0, 1000, 1000, 1000, 60]]


TRUTH = ["sequence_id", "molecule_type", "length"]
RANK = ["analysis_track", "variant", "tool", "mean_value", "n_samples", "rank", "baseline_rank", "rank_change", "kendall_tau_vs_baseline", "top_tool", "top_matches_baseline"]


def run(tmp, results):
    return subprocess.run([sys.executable, str(ROOT / "python" / "truth_exclusion_sensitivity.py"), "--rank-robustness", str(tmp / "rank.tsv"),
                           "--truth-marker-overlap", str(tmp / "overlap.tsv"), "--out", str(tmp / "out.tsv"), "--rescore-reconstruction", str(results)],
                          capture_output=True, text=True)


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    results = tmp / "results"
    write(tmp / "rank.tsv", RANK, [["long_read", "baseline", "A", "0.5", "2", "", "", "", "", "", ""], ["long_read", "baseline", "B", "0.9", "2", "", "", "", "", "", ""],
                                   ["long_read", "baseline", "C", "0.1", "2", "", "", "", "", "", ""],
                                   ["long_read", "scheme:evidence", "A", "0.9", "2", "", "", "", "", "", ""], ["long_read", "scheme:evidence", "B", "0.9", "2", "", "", "", "", "", ""],
                                   ["long_read", "scheme:evidence", "C", "0.1", "2", "", "", "", "", "", ""]])
    write(tmp / "overlap.tsv", ["tool", "marker_caller", "shared"], [["A", "mob_typer", "yes"], ["B", "mob_typer", "no"]])
    for sample in ("s1", "s2"):
        d = results / sample
        write(d / "truth.tsv", TRUTH, [["p1", "PLASMID", 1000], ["p2", "PLASMID", 1000], ["chr", "CHROMOSOME", 5000]])
        write(d / "truth.scored.tsv", TRUTH, [["p1", "PLASMID", 1000], ["chr", "CHROMOSOME", 5000]])
        write(d / "A.pred_vs_ref.paf", None, paf("q1", "p1"))
        write(d / "pred_A.bins.tsv", ["sequence_id", "bin_id"], [["q1", "b1"]])
        write(d / "B.pred_vs_ref.paf", None, paf("q1", "p1") + paf("q2", "p2"))
        write(d / "pred_B.bins.tsv", ["sequence_id", "bin_id"], [["q1", "b1"], ["q2", "b2"]])
        write(d / "C.pred_vs_ref.paf", None, paf("q1", "p1"))   # tool C writes no bins file: not covered
    # s3 has no truth.scored.tsv: left out of both sides
    d = results / "s3"
    write(d / "truth.tsv", TRUTH, [["p1", "PLASMID", 1000], ["chr", "CHROMOSOME", 5000]])
    write(d / "A.pred_vs_ref.paf", None, paf("q1", "p1"))
    write(d / "pred_A.bins.tsv", ["sequence_id", "bin_id"], [["q1", "b1"]])
    done = run(tmp, results)
    check("the script runs", done.returncode == 0, done.stderr)
    out = tmp / "benchmark.truth_exclusion_sensitivity_reconstruction.tsv"
    check("the reconstruction table is written next to --out", out.is_file(), done.stderr)
    with open(out, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    tool = {(r["tool"], r["metric"]): r for r in rows if r["row_kind"] == "tool"}
    check("tool C (no bins) is not in the table", not any(t == "C" for t, _ in tool), sorted(tool))
    a, b = tool[("A", "lw_bin_f1")], tool[("B", "lw_bin_f1")]
    check("A lw_bin_f1: 0.6667 -> 1.0000 (+0.3333), over the 2 samples with both truths", (a["mean_without_exclusion"], a["mean_with_exclusion"], a["delta_with_minus_without"], a["n_samples"]) == ("0.6667", "1.0000", "+0.3333", "2"), a)
    check("B lw_bin_f1 unchanged at 1.0000", (b["mean_without_exclusion"], b["mean_with_exclusion"], b["delta_with_minus_without"]) == ("1.0000", "1.0000", "+0.0000"), b)
    ca = tool[("A", "cprr")]
    check("A CPRR: 0.5000 -> 1.0000 (+0.5000)", (ca["mean_without_exclusion"], ca["mean_with_exclusion"], ca["delta_with_minus_without"]) == ("0.5000", "1.0000", "+0.5000"), ca)
    check("ranks: A 2 -> 1, B 1 -> 2 by lw_bin_f1", (a["rank_without_exclusion"], a["rank_with_exclusion"], b["rank_without_exclusion"], b["rank_with_exclusion"]) == ("2", "1", "1", "2"), (a, b))
    check("A shares a truth database, B does not", (a["shares_truth_database"], b["shares_truth_database"]) == ("yes", "no"))
    group = {(r["shares_truth_database"], r["metric"]): r for r in rows if r["row_kind"] == "group"}
    check("the group rows average the change (+0.3333 sharing, +0.0000 not)", (group[("yes_or_possible", "lw_bin_f1")]["delta_with_minus_without"], group[("no_or_unknown", "lw_bin_f1")]["delta_with_minus_without"]) == ("+0.3333", "+0.0000"), group)
    check("every row carries the re-score scope", all("not a new pipeline run" in r["scope"] for r in rows))
    # no usable sample: say so, write nothing
    out.unlink()
    empty = tmp / "empty"
    empty.mkdir()
    done = run(tmp, empty)
    check("no usable sample: the script still exits 0, states that nothing was re-scored and writes no table", done.returncode == 0 and "NOT re-scored" in done.stderr and not out.exists(), done.stderr)

script = (ROOT / "scripts" / "06_aggregate.sh").read_text(encoding="utf-8")
check("stage 6 asks for the reconstruction re-score", "--rescore-reconstruction" in script)
print("ALL TRUTH EXCLUSION RECONSTRUCTION TESTS PASSED" if ok else "SOME TRUTH EXCLUSION RECONSTRUCTION TESTS FAILED")
sys.exit(0 if ok else 1)
