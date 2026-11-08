#!/usr/bin/env python3
"""Regression checks for three leaderboard fairness bugs.

1. A tool that predicts nothing on a plasmid-bearing isolate must score F1 = 0
   there, not an empty F1 that drops the sample from its mean.
2. Tools are ranked on shared samples; a failed tool run on a plasmid-bearing
   sample counts as F1 = 0 for that tool instead of shrinking everyone's set.
3. The combined leaderboard ranks within each analysis track, never across.
"""

import csv
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCORE = os.path.join(HERE, "..", "python", "score_plasmids.py")
AGGREGATE = os.path.join(HERE, "..", "python", "aggregate_results.py")


def write(path, text):
    with open(path, "w", newline="") as handle:
        handle.write(text)


def score(tmp, sample, tool, paf, fasta, out, track="short_read"):
    subprocess.run([sys.executable, SCORE, "--truth", os.path.join(tmp, "truth.tsv"),
                    "--paf", paf, "--pred-fasta", fasta, "--sample", sample, "--tool", tool,
                    "--analysis-track", track, "--out", out],
                   check=True, capture_output=True, text=True)


def read(path):
    with open(path, newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def main():
    ok = True
    with tempfile.TemporaryDirectory(prefix="ranking_fairness_") as tmp:
        write(os.path.join(tmp, "truth.tsv"),
              "sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t5000\np1\tPLASMID\t1000\n")
        empty_fa, empty_paf = os.path.join(tmp, "empty.fa"), os.path.join(tmp, "empty.paf")
        write(empty_fa, "")
        write(empty_paf, "")
        good_fa, good_paf = os.path.join(tmp, "good.fa"), os.path.join(tmp, "good.paf")
        write(good_fa, ">c1\n" + "A" * 1000 + "\n")
        write(good_paf, "c1\t1000\t0\t1000\t+\tp1\t1000\t0\t1000\t1000\t1000\t60\n")
        scores = os.path.join(tmp, "scores.tsv")
        samples = [f"s{i}" for i in range(1, 6)]

        for sample in samples:
            score(tmp, sample, "steady", good_paf, good_fa, scores)
        score(tmp, "s1", "lazy", good_paf, good_fa, scores)
        for sample in samples[1:]:
            score(tmp, sample, "lazy", empty_paf, empty_fa, scores)
        score(tmp, "s1", "crashy", good_paf, good_fa, scores)
        for sample in samples:
            score(tmp, sample, "longtool", good_paf, good_fa, scores, track="long_read")

        # 1. Empty prediction on a plasmid-bearing isolate -> F1 0, precision empty.
        lazy_s2 = next(r for r in read(scores) if r["tool"] == "lazy" and r["sample"] == "s2")
        check = lazy_s2["f1"] == "0.0000" and lazy_s2["precision"] == "" and lazy_s2["recall"] == "0.0000"
        print(f"  empty prediction -> f1={lazy_s2['f1']!r} precision={lazy_s2['precision']!r} -> {check}")
        ok &= check

        status = os.path.join(tmp, "tool_status.tsv")
        lines = ["sample\ttool\tstatus"] + [f"{s}\tsteady\tcompleted" for s in samples]
        lines += [f"{s}\tlazy\tcompleted" for s in samples] + ["s1\tcrashy\tcompleted"]
        lines += [f"{s}\tcrashy\tfailed" for s in samples[1:]]
        write(status, "\n".join(lines) + "\n")
        prefix = os.path.join(tmp, "bench")
        subprocess.run([sys.executable, AGGREGATE, "--scores", scores, "--out-prefix", prefix,
                        "--tool-status", status], check=True, capture_output=True, text=True)
        board = read(prefix + ".leaderboard.tsv")
        short = {r["tool"]: r for r in board if r["analysis_track"] == "short_read"}

        # 2a. The abstaining tool's mean F1 reflects its zeros.
        check = short["lazy"]["mean_f1"] == "0.2000" and short["steady"]["mean_f1"] == "1.0000"
        print(f"  abstaining tool ranked on its zeros -> lazy={short['lazy']['mean_f1']} "
              f"steady={short['steady']['mean_f1']} -> {check}")
        ok &= check
        # 2b. Failed runs count as 0 and do not shrink the shared ranking set.
        check = (short["crashy"]["mean_f1"] == "0.2000"
                 and short["crashy"]["n_failures_scored_zero"] == "4"
                 and all(r["n_ranking_samples"] == "5" for r in short.values()))
        print(f"  failed runs scored 0, ranking set intact -> crashy={short['crashy']['mean_f1']} "
              f"zeros={short['crashy']['n_failures_scored_zero']} -> {check}")
        ok &= check
        check = short["steady"]["rank"] == "1"
        print(f"  perfect tool ranks first -> rank={short['steady']['rank']} -> {check}")
        ok &= check

        # 2c. Without a status file a missing sample shrinks the shared set instead.
        prefix2 = os.path.join(tmp, "bench_nostatus")
        subprocess.run([sys.executable, AGGREGATE, "--scores", scores, "--out-prefix", prefix2],
                       check=True, capture_output=True, text=True)
        short2 = [r for r in read(prefix2 + ".leaderboard.tsv") if r["analysis_track"] == "short_read"]
        check = all(r["n_ranking_samples"] == "1" and r["ranking_basis"] == "shared_samples" for r in short2)
        print(f"  no status -> ranked on shared samples only -> {check}")
        ok &= check

        # 3. Combined file ranks within track; long-read tool is rank 1 of its own track.
        long_rows = [r for r in board if r["analysis_track"] == "long_read"]
        check = (len(long_rows) == 1 and long_rows[0]["rank"] == "1"
                 and sorted(r["rank"] for r in short.values()) == ["1", "2", "3"])
        print(f"  combined leaderboard ranks within track -> {check}")
        ok &= check
        comparisons = read(prefix + ".paired_comparisons.tsv")
        check = all("longtool" not in (c["tool_a"], c["tool_b"]) for c in comparisons) and \
            all(c["analysis_track"] == "short_read" for c in comparisons)
        print(f"  no cross-track paired comparisons -> {check}")
        ok &= check

    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
