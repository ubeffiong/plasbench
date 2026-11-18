#!/usr/bin/env python3
"""The accession ledger is not a cohort: `plasbench run --cohort accepted_accessions` stops once, clearly, before a study folder exists.

Before, it failed in stage 0 with one 'uncurated sample-sheet row N' line per isolate (20 identical lines for --max-isolates 20) and a study folder had already been made."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from plasbench import sheetcheck  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


LEDGER = "biosample\tsample_id\tassembly_accession\tsra_run\tsource_cohort\n" + "".join(
    f"SAMD{i:08d}\tisolate_{i}\tGCF_{i:09d}.1\tDRR{i:06d}\tpublic-v4\n" for i in range(25))
CURATED = ("sample_id\tassembly_accession\tsra_run\torganism\ttruth_technology\ttruth_quality_tier\tbiosample\tbioproject\n"
           "a_1\tGCF_1.1\tSRR1\tEscherichia coli\tlong_read\tA\tSAMN1\tPRJNA1\n")

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    cohorts = tmp / "cohorts"
    cohorts.mkdir()
    (cohorts / "accepted_accessions.tsv").write_text(LEDGER)
    (cohorts / "public-v4.tsv").write_text("# a comment line first\n" + CURATED)
    (cohorts / "metagenomics-real-v1.tsv").write_text("sample_id\tcommunity\nm1\tmock\n")
    (cohorts / "odd.tsv").write_text("sample_id\tnotes\nx\ty\n")

    # --- the helper -----------------------------------------------------------------------------------------------------------------------
    check("the ledger is recognised", sheetcheck.is_ledger(sheetcheck.header(cohorts / "accepted_accessions.tsv")))
    check("a curated sheet is not the ledger and has every required column", not sheetcheck.is_ledger(sheetcheck.header(cohorts / "public-v4.tsv"))
          and sheetcheck.is_benchmark_sheet(cohorts / "public-v4.tsv"))
    check("a leading # comment line is skipped when reading the header", sheetcheck.header(cohorts / "public-v4.tsv")[0] == "sample_id")
    listed = sheetcheck.cohort_sheets(cohorts)
    check("only real benchmark sheets are listed (no ledger, no metagenomic table, no odd file)", listed == ["public-v4"], listed)
    message = sheetcheck.refusal(cohorts / "accepted_accessions.tsv", listed)
    check("the refusal says it is the ledger, names the columns a run needs and points to a real cohort",
          "accession ledger" in message and "organism" in message and "bioproject" in message and "public-v4" in message, message)
    check("a sheet with the wrong columns gets a different, plain message", "not a benchmark sheet" in sheetcheck.refusal(cohorts / "odd.tsv", listed)
          and "accession ledger" not in sheetcheck.refusal(cohorts / "odd.tsv", listed))
    check("a good sheet gets no refusal", sheetcheck.refusal(cohorts / "public-v4.tsv", listed) == "")
    check("an unreadable file is reported, not a crash", "not readable" in sheetcheck.refusal(cohorts / "missing.tsv"))

    # --- the command: refused once, before a study folder is made ---------------------------------------------------------------------------
    project = tmp / "project"
    shutil.copytree(ROOT / "scripts", project / "scripts")
    shutil.copytree(ROOT / "config", project / "config")
    (project / "cohorts").mkdir()
    for f in cohorts.iterdir():
        shutil.copy(f, project / "cohorts" / f.name)
    env = {k: v for k, v in os.environ.items() if k not in ("REQUIRE_CURATED_METADATA", "RESULTS_DIR")}
    run = subprocess.run([sys.executable, "-m", "plasbench", "--project-root", str(project), "run", "--cohort", "accepted_accessions", "--max-isolates", "20"],
                         capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=120)
    check("the command stops with a usage error (exit 2)", run.returncode == 2, (run.returncode, run.stderr[-300:]))
    check("the message is the ledger explanation, once", run.stderr.count("accession ledger") == 1 and "public-v4" in run.stderr, run.stderr[-500:])
    check("no per-row 'uncurated sample-sheet row' lines", "uncurated sample-sheet row" not in run.stderr + run.stdout)
    check("no study folder was created", not (project / "studies").exists(), list((project).glob("*")))
    unknown = subprocess.run([sys.executable, "-m", "plasbench", "--project-root", str(project), "run", "--cohort", "nope"],
                             capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=120)
    message_line = next((l for l in unknown.stderr.splitlines() if "no such cohort" in l), "")   # the usage banner also names commands
    check("an unknown cohort lists only the real benchmark sheets", message_line.endswith("available: public-v4") and "accepted_accessions" not in message_line
          and "metagenomics" not in message_line, message_line)
    ledger_samples = subprocess.run([sys.executable, "-m", "plasbench", "--project-root", str(project), "run", "--samples", str(cohorts / "accepted_accessions.tsv")],
                                    capture_output=True, text=True, cwd=str(ROOT), env=env, timeout=120)
    check("--samples with the ledger is refused the same way", ledger_samples.returncode == 2 and "accession ledger" in ledger_samples.stderr, ledger_samples.stderr[-300:])

    # --- stage 0: the awk check groups its errors ---------------------------------------------------------------------------------------------
    if shutil.which("bash"):
        sheet = tmp / "ledger_as_samples.tsv"
        sheet.write_text(LEDGER)
        bash = subprocess.run(["bash", "-c", f'source "{(ROOT / "scripts" / "lib.sh").as_posix()}" >/dev/null 2>&1; validate_sample_sheet "{sheet.as_posix()}"'],
                              capture_output=True, text=True, timeout=120)
        err = bash.stderr
        rows = [line for line in err.splitlines() if "uncurated sample-sheet row" in line]
        if "sample sheet not found" in err or "command not found" in err:
            print("  skip  bash cannot read this path form here; the stage-0 grouping was not exercised")
        else:
            check("stage 0 names only the first three uncurated rows", len(rows) == 3, rows)
            check("stage 0 counts the rest in one line (22 more of 25)", "and 22 more uncurated rows (25 of 25" in err, err[-400:])
            check("stage 0 explains that the file is probably not a cohort sheet", "probably not a cohort sheet" in err and "public-v4" in err, err[-400:])
            check("stage 0 still fails", bash.returncode != 0)
    else:
        print("  skip  bash not found; the stage-0 grouping was not exercised")

print("ALL SHEET CHECK TESTS PASSED" if ok else "SHEET CHECK TESTS FAILED")
sys.exit(0 if ok else 1)
