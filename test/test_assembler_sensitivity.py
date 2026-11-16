#!/usr/bin/env python3
"""assembler_sensitivity.py: re-rank the tools in runs that differ only in the assembly, on the isolates all runs share."""

import csv
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(HERE, "..", "python")
TAB, NL = chr(9), chr(10)
ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


def scores(path, a, b, samples=6, skip=()):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        w = csv.writer(handle, delimiter=TAB, lineterminator=NL)
        w.writerow(["sample", "tool", "analysis_track", "lw_bin_f1"])
        for i in range(samples):
            if i in skip:
                continue
            w.writerow([f"s{i}", "mob_recon", "short_read", a])
            w.writerow([f"s{i}", "gplas2_mob", "short_read", b])


def run(*args):
    return subprocess.run([sys.executable, os.path.join(PY, "assembler_sensitivity.py"), *args], capture_output=True, text=True)


def table(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter=TAB))


tmp = tempfile.mkdtemp()
p = lambda n: os.path.join(tmp, n)  # noqa: E731
scores(p("spades.tsv"), 0.9, 0.5)
scores(p("other_flip.tsv"), 0.4, 0.8)
scores(p("other_same.tsv"), 0.85, 0.45)
scores(p("other_missing.tsv"), 0.85, 0.45, skip=(0, 1))

d = run("--condition", f"spades={p('spades.tsv')}", "--condition", f"unicycler={p('other_flip.tsv')}", "--out-prefix", p("a"), "--html", p("a.html"))
rows = table(p("a.assembler_sensitivity.tsv"))
check("it runs and writes a row per condition", d.returncode == 0 and len(rows) == 2, d.stderr[-300:])
check("a flipped leader is called assembler-dependent", rows[1]["leader_changed"] == "yes" and rows[1]["verdict"].startswith("assembler-dependent"), rows[1])
check("Kendall tau is -1 when the order reverses", rows[1]["kendall_tau"] == "-1.000", rows[1]["kendall_tau"])
check("the reference condition is the first one given", rows[0]["condition"] == "spades" and rows[0]["leader_changed"] == "", rows[0])
page = open(p("a.html"), encoding="utf-8").read()
check("the HTML page states the verdict and the shared isolate count", "assembler-dependent" in page and "6 isolates shared" in page)

run("--condition", f"spades={p('spades.tsv')}", "--condition", f"other={p('other_same.tsv')}", "--out-prefix", p("b"))
check("the same order in both conditions is robust", table(p("b.assembler_sensitivity.tsv"))[0]["verdict"].startswith("robust"))

run("--condition", f"spades={p('spades.tsv')}", "--condition", f"other={p('other_missing.tsv')}", "--out-prefix", p("c"))
c = table(p("c.assembler_sensitivity.tsv"))
check("isolates missing from one condition are dropped from all, and the count says so", c and c[0]["isolates_compared"] == "4", c[:1])

one = run("--condition", f"spades={p('spades.tsv')}", "--out-prefix", p("d"))
check("one condition is refused, not called robust", one.returncode == 2 and "at least two" in one.stdout)
bad = run("--condition", "nofile", "--condition", f"x={p('spades.tsv')}", "--out-prefix", p("e"))
check("a malformed condition is a clear error", bad.returncode != 0 and "NAME=path" in (bad.stderr + bad.stdout))
same = run("--condition", f"x={p('spades.tsv')}", "--condition", f"x={p('other_same.tsv')}", "--out-prefix", p("f"))
check("duplicate condition names are refused", same.returncode != 0)

print("ALL ASSEMBLER SENSITIVITY TESTS PASSED" if ok else "ASSEMBLER SENSITIVITY TESTS FAILED")
sys.exit(0 if ok else 1)
