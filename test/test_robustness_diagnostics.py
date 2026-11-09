#!/usr/bin/env python3
"""Regression checks for the robustness diagnostics.

1. Cluster-aware statistics: identical to per-sample resampling without
   clusters; wider intervals when isolates share a BioProject effect.
2. Recall ceiling: scorable_truth.py windows/intervals and score_plasmids.py
   --scorable-truth produce the expected ceiling and adjusted recall.
3. Strict precision charges unmapped predicted bases.
4. Database overlap: dates from the sheet or assembly_data_report.jsonl are
   classified correctly, and aggregation reports / excludes them.
5. The HTML report renders the robustness section.
"""

import csv
import json
import os
import random
import statistics
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(HERE, "..", "python")
sys.path.insert(0, PY)
import aggregate_results  # noqa: E402


def run(args):
    return subprocess.run([sys.executable] + args, check=True, capture_output=True, text=True)


def write(path, text):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        handle.write(text)


def read(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def check(ok, label, condition, detail=""):
    print(f"  {label} -> {condition}{(' ' + detail) if detail else ''}")
    return ok and bool(condition)


def reference_bootstrap(values, iterations=1000):
    rng = random.Random(20260831)
    means = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(iterations))
    return means[int(0.025 * iterations)], means[int(0.975 * iterations) - 1]


def reference_permutation(differences, iterations=10000):
    observed = abs(statistics.mean(differences))
    rng = random.Random(20260901)
    extreme = sum(abs(statistics.mean(x if rng.randrange(2) else -x for x in differences)) >= observed
                  for _ in range(iterations))
    return (extreme + 1) / (iterations + 1)


def main():
    ok = True
    rng = random.Random(3)

    # 1. Cluster-aware statistics.
    values = [rng.random() for _ in range(15)]
    diffs = [rng.uniform(-0.2, 0.3) for _ in range(12)]
    ok = check(ok, "no clusters == per-sample bootstrap", aggregate_results.bootstrap_ci(values) == reference_bootstrap(values))
    ok = check(ok, "no clusters == per-sample permutation",
               aggregate_results.paired_permutation_pvalue(diffs) == reference_permutation(diffs))
    clustered, groups = [], []
    for group in range(6):
        effect = rng.uniform(0.4, 1.0)
        for _ in range(5):
            clustered.append(effect + rng.gauss(0, 0.02))
            groups.append(f"bp{group}")
    plain = aggregate_results.bootstrap_ci(clustered)
    by_cluster = aggregate_results.bootstrap_ci(clustered, groups=groups)
    ok = check(ok, "cluster bootstrap is wider", (by_cluster[1] - by_cluster[0]) > (plain[1] - plain[0]),
               f"({plain[1] - plain[0]:.3f} -> {by_cluster[1] - by_cluster[0]:.3f})")
    ok = check(ok, "fewer than 5 clusters -> no interval",
               aggregate_results.bootstrap_ci(clustered[:20], groups=groups[:20]) == (None, None))

    with tempfile.TemporaryDirectory(prefix="robustness_") as tmp:
        try:
            os.chdir(tmp)
            ok = scenario(ok)
        finally:
            os.chdir(HERE)

    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


def scenario(ok):
    # 2. Recall ceiling.
    write("truth.tsv", "sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t6000\np1\tPLASMID\t2000\n")
    write("ref.fa", ">chr\n" + "C" * 6000 + "\n>p1\n" + "G" * 2000 + "\n")
    run([os.path.join(PY, "scorable_truth.py"), "windows", "--reference", "ref.fa", "--truth", "truth.tsv",
         "--out", "win.fa", "--window", "500", "--step", "250"])
    names = [line[1:].strip() for line in open("win.fa") if line.startswith(">")]
    ok = check(ok, "7 windows tile a 2 kb plasmid", len(names) == 7)
    with open("win.paf", "w") as handle:
        for name in names:
            seq, coords = name.rsplit("__plasbench_window__", 1)
            start, end = map(int, coords.split("_"))
            mapq = 0 if start >= 1500 else 60   # last window sits in a shared repeat
            handle.write(f"{name}\t{end - start}\t0\t{end - start}\t+\t{seq}\t2000\t{start}\t{end}\t"
                         f"{end - start}\t{end - start}\t{mapq}\n")
    run([os.path.join(PY, "scorable_truth.py"), "intervals", "--paf", "win.paf", "--truth", "truth.tsv",
         "--out", "scorable.tsv", "--min-alignment-mapq", "20"])
    scorable = read("scorable.tsv")
    ok = check(ok, "scorable interval p1:0-1750",
               [(r["sequence_id"], r["start"], r["end"]) for r in scorable] == [("p1", "0", "1750")])
    write("pred.fa", ">c1\n" + "A" * 1500 + "\n>junk\n" + "A" * 500 + "\n")
    write("pred.paf", "c1\t1500\t0\t1500\t+\tp1\t2000\t0\t1500\t1500\t1500\t60\n")
    run([os.path.join(PY, "score_plasmids.py"), "--truth", "truth.tsv", "--paf", "pred.paf",
         "--pred-fasta", "pred.fa", "--sample", "s1", "--tool", "t", "--scorable-truth", "scorable.tsv",
         "--out", "scores.tsv"])
    row = read("scores.tsv")[0]
    ok = check(ok, "recall_ceiling 0.8750", row["recall_ceiling"] == "0.8750")
    ok = check(ok, "ceiling_adjusted_recall 0.8571", row["ceiling_adjusted_recall"] == "0.8571")
    ok = check(ok, "F1 unchanged by ceiling", row["f1"] == "0.8571")
    # 3. Strict precision: 1500 TP / (1500 + 0 FP + 500 unmapped).
    ok = check(ok, "strict_precision 0.7500 vs precision 1.0000",
               row["strict_precision"] == "0.7500" and row["precision"] == "1.0000")

    # 4. Database overlap.
    os.makedirs(os.path.join("data", "s2"))
    write(os.path.join("data", "s2", "assembly_data_report.jsonl"),
          json.dumps({"accession": "GCF_2", "assemblyInfo": {"releaseDate": "2023-03-01"}}) + "\n")
    write("sheet.tsv", "sample_id\tbioproject\ttruth_release_date\ns1\tPRJ1\t2019-01-01\ns2\tPRJ2\t\ns3\tPRJ3\t\n")
    write("reg.tsv", "tool\tuses_reference_database\tdatabase\tdatabase_release_date\tnote\n"
                     "dbt\tyes\tdb\t2021-01-01\t\nasm\tno\tnone\t\t\nnodate\tyes\tdb\t\t\n")
    rows = ["sample\ttool\tf1"]
    for sample, f1s in (("s1", (0.95, 0.80, 0.9)), ("s2", (0.85, 0.82, 0.9)), ("s3", (0.80, 0.81, 0.9))):
        for tool, f1 in zip(("dbt", "asm", "nodate"), f1s):
            rows.append(f"{sample}\t{tool}\t{f1}")
    write("mini_scores.tsv", "\n".join(rows) + "\n")
    run([os.path.join(PY, "flag_database_overlap.py"), "--sample-sheet", "sheet.tsv", "--registry", "reg.tsv",
         "--scores", "mini_scores.tsv", "--data-dir", "data", "--out", "overlap.tsv"])
    flags = {(r["sample"], r["tool"]): r["overlap_status"] for r in read("overlap.tsv")}
    ok = check(ok, "sheet date before DB -> possible_overlap", flags[("s1", "dbt")] == "possible_overlap")
    ok = check(ok, "jsonl date after DB -> after_database", flags[("s2", "dbt")] == "after_database")
    ok = check(ok, "no date -> unknown", flags[("s3", "dbt")] == "unknown")
    ok = check(ok, "tool without DB -> no_reference_database", flags[("s1", "asm")] == "no_reference_database")
    ok = check(ok, "DB date not filled -> unknown", flags[("s1", "nodate")] == "unknown")

    header = ["sample", "tool", "analysis_track", "true_plasmid_count", "precision", "recall", "f1"]
    with open("agg_scores.tsv", "w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        for sample, tool_f1 in (("s1", 0.95), ("s2", 0.85), ("s3", 0.80)):
            writer.writerow([sample, "dbt", "short_read", 1, tool_f1, tool_f1, tool_f1])
            writer.writerow([sample, "asm", "short_read", 1, 0.8, 0.8, 0.8])
    run([os.path.join(PY, "aggregate_results.py"), "--scores", "agg_scores.tsv", "--sample-sheet", "sheet.tsv",
         "--database-overlap", "overlap.tsv", "--out-prefix", "b"])
    board = {r["tool"]: r for r in read("b.leaderboard.tsv")}
    ok = check(ok, "leaderboard counts overlap", board["dbt"]["n_possible_db_overlap"] == "1"
               and board["dbt"]["n_after_database"] == "1" and board["dbt"]["mean_f1_after_database"] == "0.8500")
    run([os.path.join(PY, "aggregate_results.py"), "--scores", "agg_scores.tsv", "--sample-sheet", "sheet.tsv",
         "--database-overlap", "overlap.tsv", "--exclude-database-overlap", "--out-prefix", "bx"])
    excluded = {r["tool"]: r for r in read("bx.leaderboard.tsv")}
    ok = check(ok, "exclusion drops overlapping sample from ranking",
               excluded["dbt"]["n_ranking_samples"] == "2" and excluded["dbt"]["mean_f1"] == "0.8250")

    # 5. Report renders the section.
    # The report needs full score_plasmids.py rows; reuse section 2's output.
    run([os.path.join(PY, "aggregate_results.py"), "--scores", "scores.tsv", "--out-prefix", "full"])
    run([os.path.join(PY, "build_html_report.py"), "--project-root", os.path.join(HERE, ".."),
         "--scores", "scores.tsv", "--tool-status", "missing_status.tsv", "--leaderboard", "full.leaderboard.tsv",
         "--comparisons", "full.paired_comparisons.tsv", "--out", "report.html"])
    page = open("report.html", encoding="utf-8").read()
    ok = check(ok, "report has robustness section and nav link",
               "<section id='robustness'" in page and "href='#robustness'" in page)   # the container carries a class now
    return ok


if __name__ == "__main__":
    main()
