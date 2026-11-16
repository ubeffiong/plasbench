#!/usr/bin/env python3
"""`plasbench run --max-isolates N`: the first N isolates, the cohort file untouched, the window's field wired."""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from plasbench import sheet_limit  # noqa: E402

failures = []


def check(label, condition, detail=""):
    print(f"  {'PASS' if condition else 'FAIL'}: {label}{'' if condition else ' -- ' + str(detail)}")
    if not condition:
        failures.append(label)


SHEET = ("# a cohort header comment\n"
         "sample_id\tassembly_accession\tsra_run\tx\n"
         "a1\tGCF_1.1\tSRR1\t1\n"
         "\n"
         "# a comment in the middle\n"
         "a2\tGCF_2.1\tSRR2\t2\n"
         "a3\tGCF_3.1\tSRR3\t3\n"
         "a4\tGCF_4.1\tSRR4\t4\n")

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    sheet = tmp / "cohort.tsv"
    sheet.write_text(SHEET, encoding="utf-8", newline="")
    before = sheet.read_bytes()

    print("the first N rows, in file order")
    limited = sheet_limit.limit_sheet(sheet, 2, tmp / "res")
    rows = [l for l in limited.path.read_text(encoding="utf-8").splitlines() if l and not l.startswith("#")]
    check("a copy with the header and the first 2 data rows", rows == ["sample_id\tassembly_accession\tsra_run\tx", "a1\tGCF_1.1\tSRR1\t1", "a2\tGCF_2.1\tSRR2\t2"], rows)
    check("it says where it came from", limited.path.read_text(encoding="utf-8").startswith("# PlasBench --max-isolates 2: 2 of 4 isolates of cohort.tsv, the first rows, in file order"))
    check("total and kept are reported", (limited.total, limited.kept) == (4, 2))
    check("comments and blank lines are not counted as isolates", sheet_limit.limit_sheet(sheet, 3, tmp / "res").total == 4)
    check("the cohort file is not changed", sheet.read_bytes() == before)
    check("the copy keeps the .tsv name pattern", limited.path.name == "cohort.first_2.tsv")

    print("nothing to cut")
    same = sheet_limit.limit_sheet(sheet, 4, tmp / "res2")
    check("N equal to the cohort size changes nothing", same.path is None and (same.total, same.kept) == (4, 4))
    check("N larger than the cohort runs them all", sheet_limit.limit_sheet(sheet, 50, tmp / "res2").path is None)
    check("no copy is written when nothing is cut", not (tmp / "res2").exists())

    print("bad input")
    for label, call in (("N of 0 is refused", lambda: sheet_limit.limit_sheet(sheet, 0, tmp)),
                        ("a missing sheet is refused", lambda: sheet_limit.limit_sheet(tmp / "nope.tsv", 2, tmp)),
                        ("a sheet with no header is refused", lambda: sheet_limit.limit_sheet(sheet.write_text("# only comments\n") and sheet, 2, tmp))):
        try:
            call()
            check(label, False)
        except ValueError:
            check(label, True)

    print("the command line")
    sheet.write_text(SHEET, encoding="utf-8", newline="")
    script = tmp / "run.sh"
    env = dict(os.environ, PLASBENCH_WORKSPACE=str(tmp / "ws"))
    done = subprocess.run([sys.executable, "-m", "plasbench", "run", "--samples", str(sheet), "--max-isolates", "2",
                           "--results-dir", str(tmp / "out"), "--write-script", str(script)], cwd=ROOT, capture_output=True, text=True, env=env)
    check("run --max-isolates writes a script", done.returncode == 0 and script.is_file(), done.stdout[-300:] + done.stderr[-300:])
    text = script.read_text(encoding="utf-8") if script.is_file() else ""
    match = re.search(r"SAMPLE_SHEET=(\S+)", text)
    check("the script points SAMPLE_SHEET at the limited copy", bool(match) and match.group(1).endswith("cohort.first_2.tsv"), text[-300:])
    check("the limited copy has the 2 rows", match and len([l for l in Path(match.group(1)).read_text(encoding="utf-8").splitlines() if l.startswith("a")]) == 2)
    check("the announcement names the numbers", "2 of 4" in done.stdout and "file order" in done.stdout, done.stdout)
    done = subprocess.run([sys.executable, "-m", "plasbench", "run", "--samples", str(sheet), "--max-isolates", "0",
                           "--results-dir", str(tmp / "out"), "--write-script", str(script)], cwd=ROOT, capture_output=True, text=True, env=env)
    check("--max-isolates 0 is a usage error", done.returncode != 0 and "positive" in done.stderr, done.stderr[-200:])
    done = subprocess.run([sys.executable, "-m", "plasbench", "run", "--samples", str(sheet), "--max-isolates", "10",
                           "--results-dir", str(tmp / "out"), "--write-script", str(script)], cwd=ROOT, capture_output=True, text=True, env=env)
    check("a limit above the cohort size runs all of it and says so", done.returncode == 0 and "has only 4" in done.stdout, done.stdout[-200:])

print("a balanced N: spread across species, studies and recent / older")
from plasbench_common import balanced_order  # noqa: E402


def organism_sheet(path):
    lines = ["sample_id\tassembly_accession\tsra_run\torganism\tselection_arm\tbioproject\ttruth_assembly_strategy"]
    n = 0
    for species, count in (("Escherichia coli", 40), ("Klebsiella pneumoniae", 30), ("Salmonella enterica", 25), ("Rare species", 3)):
        for i in range(count):
            n += 1
            lines.append(f"s{n}\tGCF_{n}.1\tSRR{n}\t{species}\t{'recent' if i % 3 == 0 else 'older'}\tPRJ{species[:2]}{i // 2}\t"
                         f"{'long_read_first_hybrid' if i % 5 else 'short_read_first_hybrid'}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")


with tempfile.TemporaryDirectory() as tmp2:
    tmp2 = Path(tmp2)
    big = tmp2 / "big.tsv"
    organism_sheet(big)
    import csv as _csv


    def rows_of(path):
        with open(path, encoding="utf-8") as handle:
            return list(_csv.DictReader((l for l in handle if not l.startswith("#")), delimiter="\t"))

    balanced = sheet_limit.limit_sheet(big, 12, tmp2 / "o1")
    got = rows_of(balanced.path)
    species = {}
    for r in got:
        species[r["organism"]] = species.get(r["organism"], 0) + 1
    check("12 of 98 take 4 from each main species, not 12 of the first species", species == {"Escherichia coli": 4, "Klebsiella pneumoniae": 4, "Salmonella enterica": 4}, species)
    check("recent and older alternate", sorted(r["selection_arm"] for r in got).count("recent") == 6)
    check("each isolate comes from a different study before any study repeats", len({r["bioproject"] for r in got}) == 12)
    check("long-read-first truths come before the others", all(r["truth_assembly_strategy"] == "long_read_first_hybrid" for r in got))
    check("the copy says it is balanced", balanced.path.name == "big.balanced_12.tsv" and "balanced selection" in balanced.path.read_text(encoding="utf-8").splitlines()[0])
    check("the same N gives the same rows again", [r["sample_id"] for r in rows_of(sheet_limit.limit_sheet(big, 12, tmp2 / "o2").path)] == [r["sample_id"] for r in got])
    as_file = sheet_limit.limit_sheet(big, 12, tmp2 / "o3", order="file")
    check("order=file still takes the first rows", {r["organism"] for r in rows_of(as_file.path)} == {"Escherichia coli"} and as_file.path.name == "big.first_12.tsv")
    every_n = all(len({rows_of(sheet_limit.limit_sheet(big, n, tmp2 / f"n{n}").path)[i]["organism"] for i in range(n)}) >= min(n, 3) for n in (3, 6, 9))
    check("small N still spans the main species", every_n)
    all_rows = rows_of(big)
    order = balanced_order(all_rows)
    check("the order is a permutation of every row", sorted(order) == list(range(len(all_rows))))
    reordered = [all_rows[i] for i in order]
    check("an already-ordered sheet is unchanged by ordering it again", [reordered[i]["sample_id"] for i in balanced_order(reordered)] == [r["sample_id"] for r in reordered])
    check("the rare species comes after the main species", [r["organism"] for r in reordered[-3:]] == ["Rare species"] * 3)
    shuffled = list(reversed(all_rows))
    check("the order does not depend on the sheet's own order", [shuffled[i]["sample_id"] for i in balanced_order(shuffled)] == [r["sample_id"] for r in reordered])
    done = subprocess.run([sys.executable, "-m", "plasbench", "run", "--samples", str(big), "--max-isolates", "12", "--results-dir", str(tmp2 / "cli"),
                           "--write-script", str(tmp2 / "r.sh")], cwd=ROOT, capture_output=True, text=True, env=env)
    check("run --max-isolates is balanced by default and says so", done.returncode == 0 and "a balanced selection" in done.stdout, done.stdout + done.stderr)
    done = subprocess.run([sys.executable, "-m", "plasbench", "run", "--samples", str(big), "--max-isolates", "12", "--isolate-order", "file",
                           "--results-dir", str(tmp2 / "cli2"), "--write-script", str(tmp2 / "r2.sh")], cwd=ROOT, capture_output=True, text=True, env=env)
    check("--isolate-order file takes the first rows", done.returncode == 0 and "first rows, in file order" in done.stdout, done.stdout + done.stderr)

print("the window")
html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
check("New benchmark has the field for a cohort or a sheet", 'data-dest="max_isolates"' in html and "Run only" in html and "balanced (recommended)" in html)
check("the review step states the limit", "${V.max_isolates} only," in html)
from plasbench import ui_schema  # noqa: E402
run = next((c for c in ui_schema.schema()["commands"] if c["name"] == "run"), None)
check("the generated command form knows --max-isolates", run is not None and any(a["dest"] == "max_isolates" for a in run["args"]))

print("ALL SHEET LIMIT TESTS PASSED" if not failures else "SHEET LIMIT TESTS FAILED: " + "; ".join(failures))
sys.exit(1 if failures else 0)
