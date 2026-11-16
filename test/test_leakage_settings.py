#!/usr/bin/env python3
"""Configurable leakage screen: LEAKAGE_CUTOFF_POLICY / LEAKAGE_CUTOFF_DATE / LEAKAGE_DATE_BASIS."""

import csv
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "python", "flag_database_overlap.py")
sys.path.insert(0, os.path.join(ROOT, "python"))
failures = []


def check(label, condition, detail=""):
    print(f"  {'PASS' if condition else 'FAIL'}: {label}{'' if condition else ' -- ' + str(detail)}")
    if not condition:
        failures.append(label)


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def screen(tmp, *args, env=None):
    out = os.path.join(tmp, "overlap.tsv")
    done = subprocess.run([sys.executable, SCRIPT, "--sample-sheet", os.path.join(tmp, "sheet.tsv"),
                           "--registry", os.path.join(tmp, "reg.tsv"), "--scores", os.path.join(tmp, "scores.tsv"),
                           "--out", out, *args], capture_output=True, text=True, env={**os.environ, **(env or {})})
    if done.returncode:
        return None, done.stderr
    with open(out, encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t")), done.stderr


with tempfile.TemporaryDirectory() as tmp:
    # a: assembled 2025-03, reads public 2019   b: assembled and read 2025   c: assembled 2018, no read year
    write(os.path.join(tmp, "sheet.tsv"),
          "sample_id\ttruth_release_date\tfirst_read_year\n"
          "a\t2025-03-01\t2019\nb\t2025-03-01\t2025\nc\t2018-01-01\t\n")
    write(os.path.join(tmp, "reg.tsv"),
          "tool\tuses_reference_database\tdatabase_release_date\n"
          "dbtool\tyes\t2022-06-01\nnodb\tno\t\n")
    write(os.path.join(tmp, "scores.tsv"),
          "sample\ttool\n" + "".join(f"{s}\t{t}\n" for s in "abc" for t in ("dbtool", "nodb", "unlisted")))

    def status(rows, sample, tool):
        return next(r["overlap_status"] for r in rows if r["sample"] == sample and r["tool"] == tool)

    print("defaults reproduce the date-of-assembly screen for sheets without first_read_year")
    rows, err = screen(tmp, "--date-basis", "assembly")
    check("assembly basis: 2025 genome is after the 2022 database", status(rows, "a", "dbtool") == "after_database", err)
    check("assembly basis: 2018 genome is possible overlap", status(rows, "c", "dbtool") == "possible_overlap")
    check("the output records basis and policy", rows[0]["date_basis"] == "assembly" and rows[0]["cutoff_policy"] == "per_tool")

    print("earliest_public counts early reads")
    rows, _ = screen(tmp)
    check("a genome assembled in 2025 whose reads were public in 2019 is possible overlap", status(rows, "a", "dbtool") == "possible_overlap")
    check("a genome with no read year falls back to its assembly date", status(rows, "c", "dbtool") == "possible_overlap")
    check("a 2025 genome with 2025 reads is still after the database", status(rows, "b", "dbtool") == "after_database")
    rows, _ = screen(tmp, "--date-basis", "read")
    check("read basis with no read year is unknown, never silently the assembly date", status(rows, "c", "dbtool") == "unknown")

    print("fixed_date policy")
    rows, err = screen(tmp, "--policy", "fixed_date", "--cutoff-date", "2025-01-01", "--date-basis", "assembly")
    check("2025-03 assembly is after the fixed 2025-01-01 cutoff", status(rows, "b", "dbtool") == "after_database", err)
    check("2018 assembly is possible overlap against it", status(rows, "c", "dbtool") == "possible_overlap")
    check("a tool the registry says uses no database stays no_reference_database", status(rows, "a", "nodb") == "no_reference_database")
    check("an unlisted tool is screened against the cutoff (cautious)", status(rows, "c", "unlisted") == "possible_overlap")
    check("the fixed cutoff replaces the tool's own database date", rows[0]["database_release_date"] == "2025-01-01" and rows[0]["cutoff_policy"] == "fixed_date")
    rows, err = screen(tmp, "--policy", "fixed_date")
    check("fixed_date without a cutoff date is an error, not a silent default", rows is None and "LEAKAGE_CUTOFF_DATE" in err, err)
    rows, err = screen(tmp, "--policy", "fixed_date", "--cutoff-date", "soon")
    check("an unparsable cutoff date is an error", rows is None, err)

    print("environment settings (what plasbench ui writes to config/local.env) are honoured")
    rows, err = screen(tmp, env={"LEAKAGE_CUTOFF_POLICY": "fixed_date", "LEAKAGE_CUTOFF_DATE": "2025-01-01",
                                 "LEAKAGE_DATE_BASIS": "assembly"})
    check("env sets policy, cutoff and basis", rows is not None and rows[0]["cutoff_policy"] == "fixed_date"
          and rows[0]["date_basis"] == "assembly" and status(rows, "b", "dbtool") == "after_database", err)

    print("report wording")
    import shutil
    import report_question_bank as qb
    shutil.copy(os.path.join(tmp, "overlap.tsv"), os.path.join(tmp, "benchmark.database_overlap.tsv"))
    note = qb.leakage_policy_note(tmp)
    check("the report names the policy, basis and counts", "fixed cutoff 2025-01-01" in note and "assembly release date" in note and "possible overlap" in note, note)
    check("no screen file, no note", qb.leakage_policy_note(os.path.join(tmp, "missing")) == "")

print("settings are declared where the UI reads them")
config = open(os.path.join(ROOT, "config", "config.sh"), encoding="utf-8").read()
for key, default in (("LEAKAGE_CUTOFF_POLICY", "per_tool"), ("LEAKAGE_CUTOFF_DATE", ""), ("LEAKAGE_DATE_BASIS", "earliest_public")):
    check(f"{key} defaults to {default!r} in config.sh", f'export {key}="${{{key}:-{default}}}"' in config)
manifest = open(os.path.join(ROOT, "python", "write_manifest.py"), encoding="utf-8").read()
check("the manifest records all three", all(k in manifest for k in ("LEAKAGE_CUTOFF_POLICY", "LEAKAGE_CUTOFF_DATE", "LEAKAGE_DATE_BASIS")))
stage = open(os.path.join(ROOT, "scripts", "06_aggregate.sh"), encoding="utf-8").read()
check("stage 6 passes them to the screen", all(k in stage for k in ("LEAKAGE_CUTOFF_POLICY", "LEAKAGE_CUTOFF_DATE", "LEAKAGE_DATE_BASIS")))

print("ALL LEAKAGE SETTINGS TESTS PASSED" if not failures else "LEAKAGE SETTINGS TESTS FAILED: " + "; ".join(failures))
sys.exit(1 if failures else 0)
