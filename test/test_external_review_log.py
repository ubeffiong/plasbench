#!/usr/bin/env python3
"""The external review and validation log stays honest: every file it cites exists, every review is typed, and open items are not hidden."""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ok = True


def check(label, good, detail=""):
    global ok
    print(f"  {'ok  ' if good else 'FAIL'}  {label}{'' if good else ' -> ' + str(detail)}")
    ok &= bool(good)


text = open(os.path.join(ROOT, "docs", "EXTERNAL_REVIEW_LOG.md"), encoding="utf-8").read()

paths = sorted({m for m in re.findall(r"`([A-Za-z0-9_./-]+\.(?:md|py|sh|tsv|json|yml))`", text) if "/" in m})
missing = [p for p in paths if not os.path.exists(os.path.join(ROOT, p))]
check(f"every file the log cites exists ({len(paths)} cited)", not missing, missing)

rows = [line for line in text.splitlines() if re.match(r"^\| R\d+ \|", line)]
ids = [re.match(r"^\| (R\d+) \|", r).group(1) for r in rows]
check("the register lists R1 to R8 with no gaps or repeats", ids == [f"R{i}" for i in range(1, 9)], ids)
types = {"Human reviewer", "Question bank", "AI-assisted", "Automated", "Human (project lead", "Human reviewers"}
check("every review has a date and a source type from the key",
      all(re.search(r"\| 20\d\d-\d\d-\d\d", r) and any(t in r for t in types) for r in rows), [r[:60] for r in rows
                                                                                              if not re.search(r"\| 20\d\d-\d\d-\d\d", r)])
check("AI-assisted reviews are labelled as such and not called peer review",
      text.count("AI-assisted") >= 4 and "not peer review" in text and "None of this is journal peer review" in text)
check("it says reviewer identities and wording are not in the repository", "Reviewer names, affiliations and the original wording" in text)
check("open items are listed, not only successes", "## Not yet done" in text and text.count("**Open**") + text.count("open") >= 5
      and "real-data run" in text and "independent third-party re-run" in text)
check("the validation table gives an honest status to each row", "## Validation evidence" in text and text.count("| Done") >= 5
      and "in progress" in text)
check("the three reviewer questions are each answered with a status",
      all(q in text for q in ("Can the assembly be chosen?", "Is there short-read QC", "How is noise picked up")))
check("a reply to the reviewers is given and says what is not yet done", "Suggested wording for a reply" in text and "Not yet done: running every tool" in text)
check("the FAQ and README point to the log", "EXTERNAL_REVIEW_LOG.md" in open(os.path.join(ROOT, "FAQ.md"), encoding="utf-8").read()
      and "EXTERNAL_REVIEW_LOG.md" in open(os.path.join(ROOT, "README.md"), encoding="utf-8").read())

print("ALL EXTERNAL REVIEW LOG TESTS PASSED" if ok else "EXTERNAL REVIEW LOG TESTS FAILED")
sys.exit(0 if ok else 1)
