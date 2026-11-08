#!/usr/bin/env python3
"""compare_runs.py: reproducible, score-stable, variable and incomplete, by construction."""
import csv
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "python", "compare_runs.py")


def make_run(tmp, name, rows, fastas):
    run = os.path.join(tmp, name)
    os.makedirs(run)
    with open(os.path.join(run, "scores.tsv"), "w") as fh:
        fh.write("sample\ttool\tanalysis_track\tf1\tprecision\trecall\n")
        for sample, tool, f1 in rows:
            fh.write(f"{sample}\t{tool}\tshort_read\t{f1}\t0.9\t0.9\n")
    for (sample, tool), body in fastas.items():
        os.makedirs(os.path.join(run, sample), exist_ok=True)
        open(os.path.join(run, sample, f"pred_{tool}.plasmid.fasta"), "w").write(body)
    return run


def main():
    ok = True

    def check(label, good):
        nonlocal ok
        print(f"  {label}: {'PASS' if good else 'FAIL'}")
        ok &= bool(good)

    with tempfile.TemporaryDirectory() as tmp:
        same = ">a\nACGT\n>b\nTTTT\n"
        reordered = ">b\nTTTT\n>a\nACGT\n"
        different = ">a\nACGA\n>b\nTTTT\n"
        r1 = make_run(tmp, "r1", [("s1", "steady", 0.8), ("s1", "wobbly", 0.8), ("s1", "seqvar", 0.8), ("s2", "wobbly", 0.7),
                                  ("s1", "partial", 0.5)],
                      {("s1", "steady"): same, ("s1", "seqvar"): same})
        r2 = make_run(tmp, "r2", [("s1", "steady", 0.8), ("s1", "wobbly", 0.75), ("s1", "seqvar", 0.8), ("s2", "wobbly", 0.7)],
                      {("s1", "steady"): reordered, ("s1", "seqvar"): different})
        pairs, tools = os.path.join(tmp, "pairs.tsv"), os.path.join(tmp, "tools.tsv")
        done = subprocess.run([sys.executable, SCRIPT, "--run", r1, "--run", r2, "--out", pairs, "--tool-out", tools],
                              capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        by_pair = {(r["sample"], r["tool"]): r for r in csv.DictReader(open(pairs, newline=""), delimiter="\t")}
        by_tool = {r["tool"]: r for r in csv.DictReader(open(tools, newline=""), delimiter="\t")}

        check("same scores and the same sequences in a different order: identical",
              by_pair[("s1", "steady")]["status"] == "identical"
              and by_pair[("s1", "steady")]["identical_predictions"] == "true")
        check("a score that moved 0.8 -> 0.75 is variable and the range is reported",
              by_pair[("s1", "wobbly")]["status"] == "variable" and abs(float(by_pair[("s1", "wobbly")]["f1_range"]) - 0.05) < 1e-9)
        check("same score but a different sequence: score_stable, not reproducible",
              by_pair[("s1", "seqvar")]["status"] == "score_stable"
              and by_pair[("s1", "seqvar")]["identical_predictions"] == "false")
        check("a pair missing from one run is incomplete, not dropped", by_pair[("s1", "partial")]["status"] == "incomplete")
        check("tool verdicts: steady reproducible, seqvar score_stable, wobbly variable",
              by_tool["steady"]["verdict"] == "reproducible" and by_tool["seqvar"]["verdict"] == "score_stable"
              and by_tool["wobbly"]["verdict"] == "variable")
        check("wobbly reproduced 1 of 2 pairs", abs(float(by_tool["wobbly"]["fraction_identical_scores"]) - 0.5) < 1e-9)

        # Tolerance turns a tiny numeric wobble into stable.
        done = subprocess.run([sys.executable, SCRIPT, "--run", r1, "--run", r2, "--out", pairs, "--tool-out", tools,
                               "--tolerance", "0.06"], capture_output=True, text=True)
        stable = {r["tool"]: r for r in csv.DictReader(open(tools, newline=""), delimiter="\t")}
        check("with tolerance 0.06 the 0.05 wobble no longer counts as variable", stable["wobbly"]["verdict"] != "variable")

        one = subprocess.run([sys.executable, SCRIPT, "--run", r1, "--out", pairs, "--tool-out", tools],
                             capture_output=True, text=True)
        check("a single run is refused: it proves nothing", one.returncode != 0 and "at least two" in one.stderr)
    print("ALL COMPARE RUNS TESTS PASSED" if ok else "COMPARE RUNS TESTS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
