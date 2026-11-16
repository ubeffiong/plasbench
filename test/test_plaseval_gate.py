#!/usr/bin/env python3
"""The PlasEval comparison gate: every verdict, the strict exit codes, discovery of the original, and the report card.

The original program is replaced by a stand-in that computes PlasBench's own values (so it agrees) plus an optional offset (so it
disagrees), sleeps (a timeout) or exits non-zero (a failure). The real original is exercised by test_plaseval_crosscheck.py.
"""
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
import bin_agreement as ba  # noqa: E402
import plaseval_gate as gate  # noqa: E402
import plaseval_replication as pr  # noqa: E402
import report_learnings  # noqa: E402

GATE = os.path.join(ROOT, "python", "plaseval_gate.py")
TAB = chr(9)
ok = True

STAND_IN = r'''
import os, sys, time
sys.path.insert(0, os.environ["PB_PYTHON_DIR"])
import bin_agreement as ba
import plaseval_replication as pr
args = sys.argv[1:]
mode = args[0]
opt = {args[i]: args[i + 1] for i in range(1, len(args) - 1, 2)}
pred_path = opt.get("--l") or opt.get("--pred")
truth_path = opt.get("--r") or opt.get("--gt")
if "toolB" in pred_path:
    behaviour = os.environ.get("FAKE_B", "agree")
else:
    behaviour = os.environ.get("FAKE_A", "agree")
if behaviour == "sleep":
    time.sleep(30)
if behaviour == "fail":
    sys.exit(2)
offset = 0.05 if behaviour == "offset" else 0.0
pred, pl = pr.read_bins(pred_path)
truth, tl = pr.read_bins(truth_path)
lengths = dict(tl); lengths.update(pl)
labels = pr.labels_for(truth, None, lengths)
alpha = float(opt.get("--p", "0.5"))
if mode == "comp":
    d = ba.dissimilarity(ba._filter_pred(pred, labels, 0), ba.truth_bins(labels, 0), lengths, alpha)
    with open(opt["--out_file"], "w") as f:
        f.write("Dissimilarity\t0\t%f\n" % (d["dissim"] + offset))
else:
    e = ba.eval_bestmatch(pred, labels)
    with open(opt["--out_file"], "w") as f:
        for name, key in (("Precision", "precision"), ("Recall", "recall"), ("F1", "f1")):
            f.write("Overall\t%s\t0\t%f\t%f\n" % (name, e[key + "_count"], e[key + "_bp"]))
'''

BINS = {"truth": {"T1": [("a", 2000), ("b", 1500)], "T2": [("c", 3000), ("d", 800)]},
        "toolA": {"P1": [("a", 2000), ("b", 1500), ("x", 900)], "P2": [("c", 3000)]},
        "toolB": {"P1": [("a", 2000)], "P2": [("b", 1500), ("c", 3000), ("d", 800)]}}


def check(label, good, detail=""):
    global ok
    print(f"  {'ok  ' if good else 'FAIL'}  {label}{'' if good else ' -> ' + str(detail)}")
    ok &= bool(good)


def write_bins(path, bins):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        handle.write(TAB.join(["plasmid", "contig", "contig_len"]) + "\n")
        for plasmid, contigs in bins.items():
            for contig, length in contigs:
                handle.write(TAB.join([plasmid, contig, str(length)]) + "\n")


def make_results(tmp, tools=("toolA", "toolB"), capped=None):
    results = os.path.join(tmp, "results")
    folder = os.path.join(results, "S1")
    os.makedirs(folder)
    rows = []
    for tool in tools:
        write_bins(os.path.join(folder, f"{tool}.plaseval.pred_bins.tsv"), BINS[tool])
        write_bins(os.path.join(folder, f"{tool}.plaseval.truth_bins.tsv"), BINS["truth"])
        pred, pl = pr.read_bins(os.path.join(folder, f"{tool}.plaseval.pred_bins.tsv"))
        truth, tl = pr.read_bins(os.path.join(folder, f"{tool}.plaseval.truth_bins.tsv"))
        lengths = dict(tl)
        lengths.update(pl)
        labels = pr.labels_for(truth, None, lengths)
        e = ba.eval_bestmatch(pred, labels)
        d = ba.dissim_row(pred, labels, 0.5)
        row = {"sample": "S1", "tool": tool, "dissim_status": "ok", "bin_dissimilarity": ba._fmt(d["dissim"]),
               "dissim_repeat_search": "capped" if capped == tool else "none"}
        row.update({f"bestmatch_{k}": ba._fmt(e[k]) for k in ("precision_count", "recall_count", "f1_count", "precision_bp",
                                                               "recall_bp", "f1_bp")})
        rows.append(row)
    with open(os.path.join(results, "scores.tsv"), "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter=TAB, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return results


def run_gate(results, src=None, mode="auto", extra=(), env=None, timeout=2):
    args = [sys.executable, GATE, "results", "--results-dir", results, "--out-prefix", os.path.join(results, "benchmark.plaseval_gate"),
            "--mode", mode, "--timeout", str(timeout), "--workers", "2", *extra]
    if src:
        args += ["--plaseval-src", src]
    environment = dict(os.environ, PB_PYTHON_DIR=os.path.join(ROOT, "python"), **(env or {}))
    environment.pop("PLASEVAL_SRC", None)
    environment["HOME"] = results     # keep discovery away from a real checkout in the home folder
    environment["USERPROFILE"] = results
    environment["DATA_DIR"] = os.path.join(results, "nodata")
    done = subprocess.run(args, capture_output=True, text=True, env=environment)
    summary = json.load(open(os.path.join(results, "benchmark.plaseval_gate.json"), encoding="utf-8"))
    with open(os.path.join(results, "benchmark.plaseval_gate.tsv"), newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter=TAB))
    return done, summary, rows


tmp = tempfile.mkdtemp(prefix="gate_test_")
try:
    src = os.path.join(tmp, "orig", "src")
    os.makedirs(src)
    with open(os.path.join(src, "plaseval.py"), "w", encoding="utf-8") as handle:
        handle.write(STAND_IN)

    print("original not available")
    r = make_results(os.path.join(tmp, "a"))
    done, s, rows = run_gate(r)
    check("auto: NOT_RUN, exit 0, and the reason says how to get the original", done.returncode == 0 and s["status"] == "NOT_RUN"
          and "PLASEVAL_SRC" in s["reason"] and rows == [], (done.returncode, s))
    done, s, _ = run_gate(make_results(os.path.join(tmp, "a2")), mode="on")
    check("on: a missing original stops the run (exit 4)", done.returncode == gate.EXIT_NOT_RUN and s["status"] == "NOT_RUN", done.returncode)
    done, s, _ = run_gate(make_results(os.path.join(tmp, "a3")), src=src, mode="off")
    check("off: skipped even when the original exists", done.returncode == 0 and s["status"] == "NOT_RUN" and "switched off" in s["reason"])

    print("agreement")
    r = make_results(os.path.join(tmp, "b"))
    done, s, rows = run_gate(r, src)
    check("PASS when the original gives the same numbers", s["status"] == "PASS" and s["pairs"] == 2 and done.returncode == 0, s)
    check("each pair is marked agree with a zero difference", {x["status"] for x in rows} == {"agree"}
          and all(float(x["abs_difference"]) < 1e-9 and float(x["bestmatch_max_difference"]) < 1e-9 for x in rows), rows)
    check("the verdict records the tolerance and the original's location", s["tolerance"] == 0.001 and s["original_src"].endswith("src"))

    print("disagreement")
    r = make_results(os.path.join(tmp, "c"))
    done, s, rows = run_gate(r, src, env={"FAKE_A": "offset"})
    check("FAIL when one pair differs by more than the tolerance", s["status"] == "FAIL" and s["counts"].get("disagree") == 1, s)
    check("the disagreeing pair is named, the other agrees", {(x["tool"], x["status"]) for x in rows} == {("toolA", "disagree"), ("toolB", "agree")})
    check("auto does not stop the run on a FAIL", done.returncode == 0)
    done, s, _ = run_gate(make_results(os.path.join(tmp, "c2")), src, env={"FAKE_A": "offset"}, extra=["--strict"])
    check("--strict exits 3 on a FAIL", done.returncode == gate.EXIT_FAILED, done.returncode)
    done, s, _ = run_gate(make_results(os.path.join(tmp, "c3")), src, mode="on", env={"FAKE_A": "offset"})
    check("mode on exits 3 on a FAIL", done.returncode == gate.EXIT_FAILED, done.returncode)
    done, s, _ = run_gate(make_results(os.path.join(tmp, "c4")), src, extra=["--tolerance", "0.2"], env={"FAKE_A": "offset"})
    check("a wider tolerance accepts a 0.05 difference", s["status"] == "PASS", s)

    print("pairs that cannot be compared")
    done, s, rows = run_gate(make_results(os.path.join(tmp, "d")), src, env={"FAKE_B": "sleep"}, timeout=1)
    check("PARTIAL: the pair that finished agrees, the timeout is not called a disagreement",
          s["status"] == "PARTIAL" and s["counts"].get("not_compared") == 1 and s["counts"].get("agree") == 1, s)
    done, s, rows = run_gate(make_results(os.path.join(tmp, "d2")), src, env={"FAKE_A": "fail", "FAKE_B": "fail"})
    check("every pair failing is NOT_RUN, never a PASS", s["status"] == "NOT_RUN" and "could not be run" in s["reason"], s)

    print("capped repeat search")
    r = make_results(os.path.join(tmp, "e"), capped="toolA")
    scores = list(csv.DictReader(open(os.path.join(r, "scores.tsv"), encoding="utf-8"), delimiter=TAB))
    scores[0]["bin_dissimilarity"] = f"{float(scores[0]['bin_dissimilarity']) + 0.05:.6f}"      # an upper bound above the optimum
    with open(os.path.join(r, "scores.tsv"), "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(scores[0]), delimiter=TAB, lineterminator="\n")
        writer.writeheader()
        writer.writerows(scores)
    done, s, rows = run_gate(r, src)
    check("a capped PlasBench value above the original is an upper bound, not a failure",
          s["status"] == "PASS" and {x["status"] for x in rows} == {"capped_upper_bound", "agree"}, (s, [x["status"] for x in rows]))
    scores[0]["bin_dissimilarity"] = f"{float(scores[0]['bin_dissimilarity']) - 0.10:.6f}"      # below the optimum: impossible
    with open(os.path.join(r, "scores.tsv"), "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(scores[0]), delimiter=TAB, lineterminator="\n")
        writer.writeheader()
        writer.writerows(scores)
    done, s, rows = run_gate(r, src)
    check("a capped value BELOW the original cannot happen, so it is a FAIL", s["status"] == "FAIL", s)

    print("no data and discovery")
    empty = os.path.join(tmp, "f", "results")
    os.makedirs(empty)
    done, s, _ = run_gate(empty, src)
    check("NO_DATA when no bins were exported", s["status"] == "NO_DATA" and done.returncode == 0, s)
    found = os.path.join(tmp, "home", ".local", "share", "plasbench", "tools", "PlasEval", "src")
    os.makedirs(found)
    open(os.path.join(found, "plaseval.py"), "w").close()
    saved = {k: os.environ.pop(k, None) for k in ("PLASEVAL_SRC", "DATA_DIR")}
    try:
        check("the original is found under DATA_DIR/tools/PlasEval/src", gate.find_original(None, os.path.join(tmp, "home", ".local", "share", "plasbench"))
              == os.path.abspath(found))
        check("an explicit path wins and a folder without plaseval.py is ignored",
              gate.find_original(src) == os.path.abspath(src) and gate.find_original(os.path.join(tmp, "nothing"),
                                                                                    os.path.join(tmp, "nowhere")) in (None,) + ((
                  os.path.abspath(os.path.join(os.path.expanduser("~"), "PlasEval", "src")),) if os.path.isfile(os.path.join(
                      os.path.expanduser("~"), "PlasEval", "src", "plaseval.py")) else ()))
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v

    print("report card")
    good = report_learnings.gate_card(({"status": "PASS", "tolerance": 0.001, "pairs": 4, "counts": {"agree": 4}, "max_abs_difference": 0.0,
                                        "original_commit": "8238356", "reason": ""}, []))
    check("PASS card says both programs agree and names the original's commit", "PASS" in good and "8238356" in good and "agree" in good
          and "insight caution" not in good, good)
    bad = report_learnings.gate_card(({"status": "FAIL", "tolerance": 0.001, "pairs": 2, "counts": {"disagree": 1, "agree": 1},
                                       "max_abs_difference": 0.05, "original_commit": "", "reason": ""},
                                      [{"status": "disagree", "sample": "S<1>", "tool": "t", "plasbench_dissimilarity": "0.3",
                                        "original_dissimilarity": "0.35"}]))
    check("FAIL card is a caution, names the pair and escapes markup", "insight caution" in bad and "S&lt;1&gt;" in bad and "unverified" in bad, bad)
    check("NOT_RUN card gives the reason", "Not run: the original program was not found" in report_learnings.gate_card(
        ({"status": "NOT_RUN", "tolerance": 0.001, "pairs": 0, "counts": {}, "max_abs_difference": None, "original_commit": "",
          "reason": "the original program was not found"}, [])))
    check("no verdict file says so instead of staying silent", "no verdict was written" in report_learnings.gate_card(None))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("ALL PLASEVAL GATE TESTS PASSED" if ok else "PLASEVAL GATE TESTS FAILED")
sys.exit(0 if ok else 1)
