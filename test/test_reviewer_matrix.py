#!/usr/bin/env python3
"""docs/REVIEWER_ASSESSMENT_MATRIX: 215 questions, a valid status each, evidence for every claim, real component paths, and a summary that matches the table."""

import csv
import glob
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


with open(os.path.join(ROOT, "docs", "REVIEWER_ASSESSMENT_MATRIX.tsv"), newline="", encoding="utf-8") as handle:
    rows = list(csv.DictReader(handle, delimiter=chr(9)))
md = open(os.path.join(ROOT, "docs", "REVIEWER_ASSESSMENT_MATRIX.md"), encoding="utf-8").read()
faq = open(os.path.join(ROOT, "FAQ.md"), encoding="utf-8").read()
STATUSES = ("Satisfied", "Partially satisfied", "Needs validation", "Major gap", "Not applicable")

check("215 questions, numbered 1 to 215 once each", [int(r["question_id"]) for r in rows] == list(range(1, 216)))
check("every status is one of the five defined", all(r["status"] in STATUSES for r in rows), {r["status"] for r in rows} - set(STATUSES))
check("every row has a question, a component, evidence and what is still needed", all(r[k].strip() for r in rows for k in
      ("question", "plasbench_component", "evidence", "still_needed")))
check("every question is a question", all("?" in r["question"] for r in rows))

missing = []
for r in rows:
    for path in re.findall(r"((?:python|config|docs|env|cohorts|test|scripts)/[A-Za-z0-9_./*-]+)", r["plasbench_component"]):
        path = path.rstrip(".,:;")
        if not glob.glob(os.path.join(ROOT, path)):
            missing.append((r["question_id"], path))
check("every file named as a component exists", not missing, missing[:5])

check("nothing is marked Satisfied without saying what exercises it", all(r["evidence"].strip() for r in rows if r["status"] == "Satisfied"))
counts = Counter(r["status"] for r in rows)
totals = re.search(r"## Totals\s+\|[^\n]+\|\n\|[-|]+\|\n\|([^\n]+)\|", md)
shown = [int(x) for x in totals.group(1).split("|")] if totals else []
check("the totals in the summary match the table", shown == [counts.get(s, 0) for s in STATUSES], (shown, counts))
sections = {}
for r in rows:
    sections.setdefault(r["section"], Counter())[r["status"]] += 1
check("every section is listed in the summary with its counts", all(
    re.search(re.escape(s) + r" \| " + r" \| ".join(str(c.get(k, 0)) for k in STATUSES[:4]) + r" \|", md) for s, c in sections.items()))
check("the summary says it is a self-assessment, not independent review", "not an independent review" in md)
check("the one major gap is named", counts["Major gap"] == 1 and "Q127" in md)
check("the FAQ links the matrix and has the new answers", "REVIEWER_ASSESSMENT_MATRIX.md" in faq and all(f"### Q{n}." in faq for n in range(36, 43)))
check("every script the matrix relies on is mentioned in the FAQ", all(name in faq for name in
      ("ranking_stability.py", "assembler_sensitivity.py", "reference_evidence_audit.py")))
check("the FAQ's counts match the table", f"{counts['Satisfied']} satisfied" in faq and f"{counts['Partially satisfied']} partially satisfied" in faq
      and f"{counts['Needs validation']} need validation" in faq)

print("ALL REVIEWER MATRIX TESTS PASSED" if ok else "REVIEWER MATRIX TESTS FAILED")
sys.exit(0 if ok else 1)
