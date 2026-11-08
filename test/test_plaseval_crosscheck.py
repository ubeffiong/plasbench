#!/usr/bin/env python3
"""
Optional cross-check of python/bin_agreement.py against the original PlasEval program.

PlasEval (github.com/cchauve/PlasEval) is run from a checkout you point at; nothing from it is copied into PlasBench.
Set
    PLASEVAL_SRC     directory holding plaseval.py (the repository's src/ folder)
    PLASEVAL_PYTHON  a Python with PlasEval's requirements installed (default: this interpreter)
Without PLASEVAL_SRC the test prints SKIP and exits 0 (CI has no PlasEval).

Cases are generated here from small plasmid-bin definitions, and, when the checkout has them, also from PlasEval's own
example bin files (read in place). For each pair of predicted and truth bins both programs run on the same contigs:

  eval   overall best-match precision, recall and F1, contig-weighted and base-weighted      must agree to 4 decimals
  comp   normalised dissimilarity at alpha 0.5                                                must agree to 4 decimals
         (compared only when no contig appears in more than one bin on either side: this module drops repeated contigs
         where PlasEval pairs them by branch and bound, which is a documented difference)

PlasBench's input is a contig label table, so each PlasEval-format pair is converted: contigs in a truth bin are PLASMID
contigs listing every truth plasmid they belong to; a contig only in the prediction is a CHROMOSOME contig (a false positive).
"""

import csv
import itertools
import os
import subprocess
import sys
import tempfile
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "python", "bin_agreement.py")
TAB, NL = chr(9), chr(10)
SRC = os.environ.get("PLASEVAL_SRC")
PYTHON = os.environ.get("PLASEVAL_PYTHON", sys.executable)

# (name, predicted bins, truth bins), each bin plasmid -> list of (contig, length); unique contigs unless noted.
CASES = [
    ("identical", {"P1": [("a", 2000), ("b", 1500)], "P2": [("c", 3000)]},
                  {"T1": [("a", 2000), ("b", 1500)], "T2": [("c", 3000)]}),
    ("pure split", {"P1": [("a", 2000), ("b", 1500), ("c", 3000)]},
                   {"T1": [("a", 2000), ("b", 1500)], "T2": [("c", 3000)]}),
    ("pure join", {"P1": [("a", 2000), ("b", 1500)], "P2": [("c", 3000)]},
                  {"T1": [("a", 2000), ("b", 1500), ("c", 3000)]}),
    ("extra and missing", {"P1": [("a", 2000), ("x", 4000)]},
                          {"T1": [("a", 2000), ("m", 2500)]}),
    ("mixed", {"P1": [("a", 2000), ("b", 1500), ("x", 1200)], "P2": [("c", 3000), ("d", 800)], "P3": [("e", 5000)]},
              {"T1": [("a", 2000), ("c", 3000)], "T2": [("b", 1500), ("d", 800), ("e", 5000)], "T3": [("m", 2200)]}),
    ("disjoint", {"P1": [("x", 2000)]}, {"T1": [("a", 2000)]}),
    ("repeat in truth (eval only)", {"P1": [("a", 2000), ("r", 900)], "P2": [("b", 1500)]},
                                    {"T1": [("a", 2000), ("r", 900)], "T2": [("b", 1500), ("r", 900)]}),
]


def write_plaseval(path, bins):
    with open(path, "w", newline="") as handle:
        handle.write(TAB.join(["plasmid", "contig", "contig_len"]) + NL)
        for plasmid, contigs in bins.items():
            for contig, length in contigs:
                handle.write(TAB.join([plasmid, str(contig), str(length)]) + NL)


def read_plaseval(path):
    bins = OrderedDict()
    # PlasEval example files are whitespace separated, not strictly tab separated.
    with open(path) as handle:
        lines = [line.split() for line in handle if line.strip()]
    for plasmid, contig, length in lines[1:]:
        bins.setdefault(plasmid, [])
        if (contig, int(length)) not in bins[plasmid]:
            bins[plasmid].append((contig, int(length)))
    return bins


def labels_for(pred, truth, path):
    lengths, member = {}, {}
    for bins in (pred, truth):
        for contigs in bins.values():
            for contig, length in contigs:
                lengths[contig] = length
    for plasmid, contigs in truth.items():
        for contig, _ in contigs:
            member.setdefault(contig, []).append(plasmid)
    with open(path, "w", newline="") as handle:
        w = csv.writer(handle, delimiter=TAB, lineterminator=NL)
        w.writerow(["contig", "length", "label", "plasmid_fraction", "chromosome_fraction", "best_plasmid", "reason", "plasmids"])
        for contig, length in lengths.items():
            plasmids = sorted(member.get(contig, []))
            w.writerow([contig, length, "PLASMID" if plasmids else "CHROMOSOME", "1.0" if plasmids else "0.0",
                        "0.0" if plasmids else "1.0", plasmids[0] if plasmids else "", "", ",".join(plasmids)])


def pred_bins_file(pred, path):
    with open(path, "w", newline="") as handle:
        handle.write(TAB.join(["bin_id", "sequence_id"]) + NL)
        for plasmid, contigs in pred.items():
            for contig, _ in contigs:
                handle.write(TAB.join([plasmid, str(contig)]) + NL)


def run_mine(tmp, pred, truth):
    labels, bins = os.path.join(tmp, "labels.tsv"), os.path.join(tmp, "pred.bins.tsv")
    labels_for(pred, truth, labels)
    pred_bins_file(pred, bins)
    out_eval, out_dis = os.path.join(tmp, "m_eval.tsv"), os.path.join(tmp, "m_dis.tsv")
    for cmd, out, extra in (("eval", out_eval, []), ("dissim", out_dis, ["--alpha", "0.5"])):
        done = subprocess.run([sys.executable, SCRIPT, cmd, "--labels", labels, "--bins", bins, "--sample", "S", "--tool", "T",
                               "--out", out, *extra], capture_output=True, text=True)
        if done.returncode:
            raise SystemExit(done.stderr)
    with open(out_eval, newline="") as handle:
        e = next(csv.DictReader(handle, delimiter=TAB))
    with open(out_dis, newline="") as handle:
        d = next(csv.DictReader(handle, delimiter=TAB))
    return e, d


def run_theirs(tmp, pred, truth):
    p, t = os.path.join(tmp, "p.tsv"), os.path.join(tmp, "t.tsv")
    write_plaseval(p, pred)
    write_plaseval(t, truth)
    out_e, log_e = os.path.join(tmp, "pe_eval.out"), os.path.join(tmp, "pe_eval.log")
    out_c, log_c = os.path.join(tmp, "pe_comp.out"), os.path.join(tmp, "pe_comp.log")
    script = os.path.join(SRC, "plaseval.py")
    for args in (["eval", "--pred", p, "--gt", t, "--out_file", out_e, "--log_file", log_e],
                 ["comp", "--l", p, "--r", t, "--p", "0.5", "--out_file", out_c, "--log_file", log_c]):
        done = subprocess.run([PYTHON, script, *args], capture_output=True, text=True, cwd=SRC)
        if done.returncode:
            raise SystemExit("PlasEval failed: " + done.stderr[-600:])
    overall = {}
    with open(out_e) as handle:
        for line in handle:
            f = line.rstrip(NL).split(TAB)
            if f[0] == "Overall":
                overall[f[1]] = (float(f[3]), float(f[4]))
    dissimilarity = None
    with open(out_c) as handle:
        for line in handle:
            f = line.rstrip(NL).split(TAB)
            if f[0] == "Dissimilarity":
                dissimilarity = float(f[2])
    return overall, dissimilarity


def has_repeats(bins):
    seen = [c for contigs in bins.values() for c, _ in contigs]
    return len(seen) != len(set(seen))


def main():
    if not SRC or not os.path.isfile(os.path.join(SRC, "plaseval.py")):
        print("SKIP: set PLASEVAL_SRC to a PlasEval checkout's src/ directory to run the cross-check")
        return
    ok = True
    compared = 0

    def check(label, condition):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}")

    cases = list(CASES)
    example = os.path.join(SRC, "..", "examples", "input")
    if os.path.isdir(example):
        preds = sorted(f for f in os.listdir(example) if f.startswith("pred_bins"))
        gts = sorted(f for f in os.listdir(example) if f.startswith("gt_bins"))
        for pf, gf in itertools.product(preds, gts):
            cases.append((f"PlasEval example {pf} vs {gf}", read_plaseval(os.path.join(example, pf)),
                          read_plaseval(os.path.join(example, gf))))
    for name, pred, truth in cases:
        tmp = tempfile.mkdtemp(prefix="pecheck_")
        e, d = run_mine(tmp, pred, truth)
        overall, dissimilarity = run_theirs(tmp, pred, truth)
        mine_eval = {"Precision": (float(e["bestmatch_precision_count"]), float(e["bestmatch_precision_bp"])),
                     "Recall": (float(e["bestmatch_recall_count"]), float(e["bestmatch_recall_bp"])),
                     "F1": (float(e["bestmatch_f1_count"]), float(e["bestmatch_f1_bp"]))}
        agree = all(abs(mine_eval[k][i] - overall[k][i]) < 1e-3 for k in mine_eval for i in (0, 1))
        check(f"{name}: best-match P/R/F1 (count and bp) agree", agree)
        if not agree:
            print("    mine:", mine_eval, " PlasEval:", overall)
        if has_repeats(pred) or has_repeats(truth):
            print(f"  note: {name}: repeated contigs, dissimilarity not compared (documented difference)")
        else:
            close = abs(float(d["bin_dissimilarity"]) - dissimilarity) < 1e-3
            check(f"{name}: normalised dissimilarity agrees ({float(d['bin_dissimilarity']):.4f} vs {dissimilarity:.4f})", close)
            compared += 1

    print(f"  dissimilarity compared on {compared} case(s) without repeated contigs")
    print()
    if not ok:
        print("PLASEVAL CROSS-CHECK FAILED")
        sys.exit(1)
    print("PLASEVAL CROSS-CHECK PASSED")


if __name__ == "__main__":
    main()
