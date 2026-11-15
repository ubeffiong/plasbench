#!/usr/bin/env python3
"""A study repository tracks study-level tables and reports, never per-sample sequence or patient files.

The managed runs .gitignore keeps per-sample sub-folders (results/<sample>/), sequence and variant
files, sample data folders and files named for patient or clinical data out of git. The commit scan
backs it up when someone forces a file in, and an older study repository is upgraded to the new block.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from plasbench import gitops  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(f"  {'ok  ' if good else 'FAIL'}  {label}{'' if good else ' -> ' + str(detail)}")
    ok &= bool(good)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


if not gitops.find_git():
    print("git not installed: skipped")
    sys.exit(0)

with tempfile.TemporaryDirectory() as tmp:
    repo = Path(tmp) / "study"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@example.org")
    git(repo, "config", "user.name", "t")
    gitops.ensure_gitignore(repo, "runs")
    files = {
        "study.json": "{}\n",
        "results/benchmark.leaderboard.tsv": "tool\tf1\n",
        "results/benchmark.report.html": "<html></html>\n",
        "logs/run.log": "ok\n",
        "results/s1/pred.fasta": ">a\nACGT\n",
        "results/s1/scores.tsv": "sample\tf1\n",
        "data/s1/reads.fq": "@r\n",
        "metadata/patients.tsv": "x\n",
        "cases_clinical.tsv": "x\n",
        "calls.vcf.gz": "x\n",
    }
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    shown = {line[3:] for line in git(repo, "status", "--short", "-uall").stdout.splitlines()}
    check("study record, study-level tables, report and logs are tracked",
          {"study.json", "results/benchmark.leaderboard.tsv", "results/benchmark.report.html", "logs/run.log"} <= shown, shown)
    leaked = sorted(shown & {"results/s1/pred.fasta", "results/s1/scores.tsv", "data/s1/reads.fq",
                             "metadata/patients.tsv", "cases_clinical.tsv", "calls.vcf.gz"})
    check("per-sample folders, sequence, variant, sample-data and clinical files are ignored", not leaked, leaked)

    git(repo, "add", "-f", "results/s1/scores.tsv", "metadata/patients.tsv", "cases_clinical.tsv", "calls.vcf.gz")
    findings = gitops.scan_staged(repo)
    blocked = {f["path"] for f in findings if f["level"] == "block"}
    check("forcing those files in is still blocked by the commit scan",
          {"results/s1/scores.tsv", "metadata/patients.tsv", "cases_clinical.tsv", "calls.vcf.gz"} <= blocked, blocked)
    git(repo, "reset", "-q")

    sheet = repo / "results" / "benchmark.samples.tsv"
    sheet.write_text("sample\tpatient_id\tspecies\ns1\tP-0042\tE. coli\n", encoding="utf-8")
    git(repo, "add", "results/benchmark.samples.tsv")
    kinds = {f["kind"] for f in gitops.scan_staged(repo)}
    check("a patient_id column blocks the commit", "patient_data" in kinds, kinds)
    git(repo, "reset", "-q")

    (repo / ".gitignore").write_text("# --- PlasBench runs block (managed) ---\nold/\n# --- end PlasBench runs block ---\n",
                                     encoding="utf-8")
    check("a repository with the older block is upgraded", gitops.ensure_gitignore(repo, "runs") is True)
    check("the upgrade is applied once", gitops.ensure_gitignore(repo, "runs") is False)
    check("the upgraded block ignores per-sample folders", "results/*/" in (repo / ".gitignore").read_text(encoding="utf-8"))

print("ALL STUDY GIT DATA RULE TESTS PASSED" if ok else "STUDY GIT DATA RULE TESTS FAILED")
sys.exit(0 if ok else 1)
