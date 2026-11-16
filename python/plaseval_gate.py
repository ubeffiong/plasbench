#!/usr/bin/env python3
"""Comparison gate: does PlasBench agree with the original PlasEval program on this run's bins?

PlasBench reimplements PlasEval's best-match scores and repeat-aware dissimilarity from the paper (no PlasEval code is used).
This gate checks that reimplementation against the original program on the bins of the run in hand, so the agreement is
measured on real data wherever the original is available (a high-end computer, a CI machine) and never has to be taken on trust.

How it works (stage 6 calls `results`; nothing here changes a score or a ranking):
  * Stage 5 already exports each tool's predicted bins and the truth bins in PlasEval's own file format
    (`<sample>/<tool>.plaseval.pred_bins.tsv` and `.truth_bins.tsv`), on the same filtered contigs PlasBench scored.
  * The gate runs the original program's `comp` (dissimilarity) and `eval` (best-match precision, recall, F1) on every pair
    and compares them with the values in scores.tsv.
  * Verdict: PASS (every compared pair agrees within the tolerance), FAIL (at least one disagrees), PARTIAL (the rest agree but
    some pairs could not be compared: timeout or failure), NOT_RUN (the original was not found) or NO_DATA (no exported bins).
    A PlasBench search that reached its call cap is an upper bound: it may exceed the original, never fall below it.

The original is found through PLASEVAL_SRC (the src/ folder of a PlasEval checkout) or, if unset, in the usual places
(`$DATA_DIR/tools/PlasEval/src`, `~/.local/share/plasbench/tools/PlasEval/src`, `~/PlasEval/src`). PlasEval has no licence file,
so PlasBench never ships or copies it: you clone it yourself (docs/PLASEVAL_REPLICATION.md).

  python3 python/plaseval_gate.py results --results-dir results --out-prefix results/benchmark.plaseval_gate [--mode auto|on|off]
"""
import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

TAB, NL = chr(9), chr(10)
FIELDS = ["sample", "tool", "status", "plasbench_dissimilarity", "original_dissimilarity", "abs_difference", "repeat_search",
          "plasbench_f1_bp", "original_f1_bp", "bestmatch_max_difference", "original_seconds", "note"]
EXIT_FAILED, EXIT_NOT_RUN = 3, 4


def find_original(explicit=None, data_dir=None):
    """The src/ folder of a PlasEval checkout, or None."""
    candidates = [explicit, os.environ.get("PLASEVAL_SRC")]
    for base in (data_dir, os.environ.get("DATA_DIR"), os.path.join(os.path.expanduser("~"), ".local", "share", "plasbench")):
        if base:
            candidates.append(os.path.join(base, "tools", "PlasEval", "src"))
    candidates.append(os.path.join(os.path.expanduser("~"), "PlasEval", "src"))
    for path in candidates:
        if path and os.path.isfile(os.path.join(path, "plaseval.py")):
            return os.path.abspath(path)
    return None


def checkout_commit(src):
    try:
        done = subprocess.run(["git", "-C", os.path.join(src, ".."), "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              timeout=20)
        return done.stdout.strip() if done.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _run(src, python, args, timeout):
    try:
        done = subprocess.run([python, os.path.join(src, "plaseval.py"), *args], capture_output=True, text=True, cwd=src, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except OSError as exc:
        return None, f"failed: {exc}"
    if done.returncode:
        return None, "failed: " + (done.stderr or done.stdout)[-200:].strip().replace(NL, " ")
    return done, "ok"


def original_dissimilarity(src, python, pred, truth, alpha, timeout, max_calls=10000000):
    """The original program's normalised dissimilarity for one pair: (value, status)."""
    with tempfile.TemporaryDirectory(prefix="pe_gate_") as tmp:
        out, log = os.path.join(tmp, "comp.out"), os.path.join(tmp, "comp.log")
        done, status = _run(src, python, ["comp", "--l", pred, "--r", truth, "--p", str(alpha), "--max_calls", str(max_calls),
                                          "--out_file", out, "--log_file", log], timeout)
        if done is None:
            return None, status
        with open(out, encoding="utf-8") as handle:
            for row in handle:
                f = row.rstrip(NL).split(TAB)
                if f[0] == "Dissimilarity":
                    return float(f[2]), "ok"
    return None, "failed: no Dissimilarity line"


def original_bestmatch(src, python, pred, truth, timeout):
    """The original program's overall best-match scores: ({'Precision': (count, bp), ...}, status)."""
    with tempfile.TemporaryDirectory(prefix="pe_gate_") as tmp:
        out, log = os.path.join(tmp, "eval.out"), os.path.join(tmp, "eval.log")
        done, status = _run(src, python, ["eval", "--pred", pred, "--gt", truth, "--out_file", out, "--log_file", log], timeout)
        if done is None:
            return None, status
        overall = {}
        with open(out, encoding="utf-8") as handle:
            for row in handle:
                f = row.rstrip(NL).split(TAB)
                if f[0] == "Overall":
                    overall[f[1]] = (float(f[3]), float(f[4]))
    return (overall, "ok") if overall else (None, "failed: no Overall lines")


def number(value):
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def compare_pair(src, python, pred, truth, ours, alpha, timeout, tolerance, max_calls=10000000):
    """One isolate-tool pair. `ours` is its scores.tsv row. Returns a gate row."""
    row = {k: "" for k in FIELDS}
    row.update(sample=ours.get("sample", ""), tool=ours.get("tool", ""), plasbench_dissimilarity=ours.get("bin_dissimilarity", ""),
               repeat_search=ours.get("dissim_repeat_search", ""), plasbench_f1_bp=ours.get("bestmatch_f1_bp", ""))
    started = time.time()
    value, status = original_dissimilarity(src, python, pred, truth, alpha, timeout, max_calls)
    mine = number(ours.get("bin_dissimilarity"))
    notes = []
    verdict = status if status != "ok" else "agree"
    if value is not None and mine is not None:
        row["original_dissimilarity"] = f"{value:.6f}"
        row["abs_difference"] = f"{abs(value - mine):.6f}"
        if abs(value - mine) >= tolerance:
            if ours.get("dissim_repeat_search") == "capped" and mine > value:
                verdict = "capped_upper_bound"
                notes.append("PlasBench's repeat search reached its cap: its value is an upper bound")
            else:
                verdict = "disagree"
                notes.append("dissimilarity differs by more than the tolerance")
    overall, eval_status = original_bestmatch(src, python, pred, truth, timeout)
    if overall is not None:
        theirs = {"Precision": ("bestmatch_precision_count", "bestmatch_precision_bp"), "Recall": ("bestmatch_recall_count", "bestmatch_recall_bp"),
                  "F1": ("bestmatch_f1_count", "bestmatch_f1_bp")}
        worst = 0.0
        for key, (c_col, b_col) in theirs.items():
            for value_pair, col in zip(overall.get(key, (None, None)), (c_col, b_col)):
                mine_value = number(ours.get(col))
                if value_pair is not None and mine_value is not None:
                    worst = max(worst, abs(value_pair - mine_value))
        row["bestmatch_max_difference"] = f"{worst:.6f}"
        row["original_f1_bp"] = f"{overall['F1'][1]:.6f}" if "F1" in overall else ""
        if worst >= tolerance:
            verdict = "disagree"
            notes.append("best-match precision, recall or F1 differs by more than the tolerance")
    elif verdict == "agree":
        verdict = eval_status
    row["status"] = verdict
    row["original_seconds"] = f"{time.time() - started:.1f}"
    row["note"] = "; ".join(notes)
    return row


def summarise(rows, tolerance, alpha, src, mode, reason=""):
    counts = {}
    for r in rows:
        key = "not_compared" if r["status"] in ("timeout",) or r["status"].startswith("failed") else r["status"]
        counts[key] = counts.get(key, 0) + 1
    diffs = [float(r["abs_difference"]) for r in rows if r["abs_difference"] != ""]
    if src is None:
        status = "NOT_RUN"
    elif not rows:
        status = "NO_DATA"
    elif counts.get("disagree"):
        status = "FAIL"
    elif counts.get("not_compared") and not counts.get("agree", 0) + counts.get("capped_upper_bound", 0):
        status = "NOT_RUN"
        reason = reason or "the original program could not be run on any pair"
    elif counts.get("not_compared"):
        status = "PARTIAL"
    else:
        status = "PASS"
    return {"status": status, "mode": mode, "tolerance": tolerance, "alpha": alpha, "pairs": len(rows), "counts": counts,
            "max_abs_difference": max(diffs) if diffs else None, "original_src": src or "",
            "original_commit": checkout_commit(src) if src else "", "reason": reason}


def read_tsv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader((line for line in handle if line.strip() and not line.startswith("#")), delimiter=TAB))


def write_outputs(prefix, rows, summary):
    with open(prefix + ".tsv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter=TAB, lineterminator=NL)
        writer.writeheader()
        writer.writerows(rows)
    with open(prefix + ".json", "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=1)
        handle.write(NL)


def cmd_results(a):
    mode = a.mode
    scores_path = a.scores or os.path.join(a.results_dir, "scores.tsv")
    src = None if mode == "off" else find_original(a.plaseval_src, a.data_dir)
    rows, reason = [], ""
    if mode == "off":
        reason = "the gate is switched off (RUN_PLASEVAL_GATE=off)"
    elif src is None:
        reason = ("the original PlasEval program was not found: set PLASEVAL_SRC to the src/ folder of a PlasEval checkout "
                  "(git clone https://github.com/acme92/PlasEval), see docs/PLASEVAL_REPLICATION.md")
    elif os.path.isfile(scores_path):
        scores = {(r.get("sample"), r.get("tool")): r for r in read_tsv(scores_path) if (r.get("dissim_status") or "") == "ok"}
        jobs = []
        for sample in sorted(d for d in os.listdir(a.results_dir) if os.path.isdir(os.path.join(a.results_dir, d))):
            folder = os.path.join(a.results_dir, sample)
            for name in sorted(os.listdir(folder)):
                if not name.endswith(".plaseval.pred_bins.tsv"):
                    continue
                tool = name[:-len(".plaseval.pred_bins.tsv")]
                truth = os.path.join(folder, tool + ".plaseval.truth_bins.tsv")
                if (sample, tool) in scores and os.path.isfile(truth):
                    jobs.append((os.path.join(folder, name), truth, scores[(sample, tool)]))
        with ThreadPoolExecutor(max_workers=max(1, a.workers)) as pool:
            rows = list(pool.map(lambda j: compare_pair(src, a.plaseval_python, j[0], j[1], j[2], a.alpha, a.timeout, a.tolerance,
                                                        a.max_calls), jobs))
    summary = summarise(rows, a.tolerance, a.alpha, src, mode, reason)
    write_outputs(a.out_prefix, rows, summary)
    shown = f"{summary['status']}: {summary['pairs']} pair(s)" + (f", max difference {summary['max_abs_difference']:.6f}"
                                                                   if summary["max_abs_difference"] is not None else "")
    print(f"PlasEval gate {shown}" + (f" ({reason})" if reason else ""))
    for r in rows:
        if r["status"] in ("disagree",):
            print(f"  DISAGREE {r['sample']} / {r['tool']}: PlasBench {r['plasbench_dissimilarity']} vs original "
                  f"{r['original_dissimilarity']} ({r['note']})")
    if summary["status"] == "FAIL" and (a.strict or mode == "on"):
        return EXIT_FAILED
    if summary["status"] == "NOT_RUN" and mode == "on":
        return EXIT_NOT_RUN
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("results", help="compare scores.tsv with the original program on a results directory")
    p.add_argument("--results-dir", required=True)
    p.add_argument("--scores")
    p.add_argument("--out-prefix", required=True)
    p.add_argument("--data-dir")
    p.add_argument("--mode", choices=("auto", "on", "off"), default="auto",
                   help="auto: compare when the original is found; on: also fail when it is missing or disagrees; off: skip")
    p.add_argument("--plaseval-src")
    p.add_argument("--plaseval-python", default=sys.executable)
    p.add_argument("--alpha", type=float, default=0.5)
    p.add_argument("--tolerance", type=float, default=1e-3)
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--max-calls", type=int, default=10000000)
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--strict", action="store_true", help="exit non-zero when a pair disagrees")
    p.set_defaults(fn=cmd_results)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
