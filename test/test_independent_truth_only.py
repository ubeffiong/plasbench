#!/usr/bin/env python3
"""plasbench run --independent-truth-only: only isolates whose truth does not use the benchmark's own reads."""

import csv
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "python"))
from plasbench import sheet_limit  # noqa: E402
from truth_provenance import classify_method, independence  # noqa: E402

TAB, NL = chr(9), chr(10)
ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


def sheet(path, rows, columns=("sample_id", "organism", "bioproject", "truth_assembly_strategy", "truth_polish_reads")):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        w = csv.writer(handle, delimiter=TAB, lineterminator=NL)
        w.writerow(columns)
        w.writerows(rows)


ROWS = [
    ["a", "Escherichia coli", "P1", "long_read_only", "none"],
    ["b", "Escherichia coli", "P2", "long_read_first_hybrid", "independent"],
    ["c", "Escherichia coli", "P3", "long_read_first_hybrid", "same_as_benchmark"],
    ["d", "Klebsiella pneumoniae", "P4", "short_read_first_hybrid", "same_as_benchmark"],
    ["e", "Klebsiella pneumoniae", "P5", "unknown", "unknown"],
    ["f", "Klebsiella pneumoniae", "P6", "long_read_only", "none"],
]

with tempfile.TemporaryDirectory() as d:
    tmp = Path(d)
    sheet(tmp / "s.tsv", ROWS)
    got = sheet_limit.independent_truth_only(tmp / "s.tsv", tmp / "out")
    kept = [r[0] for r in csv.reader(open(got.path, encoding="utf-8").read().splitlines()[2:], delimiter=TAB)]
    check("only long-read isolates polished with no or independent reads are kept", kept == ["a", "b", "f"], kept)
    check("it reports how many of how many", (got.kept, got.total) == (3, 6), (got.kept, got.total))
    check("the copy is named for the sheet and says where it came from", got.path.name == "s.independent.tsv" and open(got.path).readline().startswith("# PlasBench --independent-truth-only"))
    check("the source sheet is untouched", len(open(tmp / "s.tsv").read().splitlines()) == 7)
    check("the selection is exactly truth_provenance.independence()", all((independence(r[3], r[4])[0] == "independent") == (r[0] in kept) for r in ROWS))

    sheet(tmp / "plain.tsv", [["a", "Escherichia coli"]], columns=("sample_id", "organism"))
    try:
        sheet_limit.independent_truth_only(tmp / "plain.tsv", tmp / "out")
        check("a sheet without the provenance columns is refused", False, "no error")
    except ValueError as exc:
        check("a sheet without the provenance columns is refused, with the way out", "collect-truth-provenance" in str(exc), str(exc))

    sheet(tmp / "none.tsv", [ROWS[2], ROWS[3]])
    try:
        sheet_limit.independent_truth_only(tmp / "none.tsv", tmp / "out")
        check("a sheet with no independent isolate is an error, not an empty run", False, "no error")
    except ValueError as exc:
        check("a sheet with no independent isolate is an error, not an empty run", "no isolate" in str(exc), str(exc))

    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    done = subprocess.run([sys.executable, "-m", "plasbench", "run", "--samples", str(tmp / "s.tsv"), "--independent-truth-only", "--results-dir", str(tmp / "r"),
                           "--write-script", str(tmp / "r.sh")], cwd=ROOT, capture_output=True, text=True, env=env)
    check("the run option exists and says what it kept", done.returncode == 0 and "running 3 of 6 isolates" in done.stdout, done.stdout + done.stderr)
    done = subprocess.run([sys.executable, "-m", "plasbench", "run", "--samples", str(tmp / "s.tsv"), "--independent-truth-only", "--max-isolates", "2",
                           "--results-dir", str(tmp / "r2"), "--write-script", str(tmp / "r2.sh")], cwd=ROOT, capture_output=True, text=True, env=env)
    check("combined with --max-isolates, N is taken from the independent isolates only", done.returncode == 0 and "running 2 of 3 isolates" in done.stdout, done.stdout + done.stderr)

public = ROOT / "cohorts" / "public-v4.tsv"
with tempfile.TemporaryDirectory() as d:
    got = sheet_limit.independent_truth_only(public, d)
    # derived from the sheet's own assembly_method / technology text with the independent rule, not a pinned number (a correct fix to classify_method changes the count)
    expected = 0
    with open(public, encoding="utf-8") as handle:
        for row in csv.DictReader((l for l in handle if l.strip() and not l.startswith("#")), delimiter=TAB):
            if row.get("assembly_method") or row.get("assembly_sequencing_technology"):
                s, p, _ = classify_method(row["assembly_method"], row["assembly_sequencing_technology"])
                expected += independence(s, p)[0] == "independent"
    check("public-v4: the independent-truth subset is what classify_method says of every row, and it is 15% of the cohort", got.kept == expected and got.total == 7227 and 0.10 < got.kept / got.total < 0.20, (got.kept, expected, got.total))

print("ALL INDEPENDENT TRUTH TESTS PASSED" if ok else "INDEPENDENT TRUTH TESTS FAILED")
sys.exit(0 if ok else 1)
