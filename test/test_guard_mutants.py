#!/usr/bin/env python3
"""Tests for the guards that mutation testing showed were unprotected (audit AU-022, second part):
the synthetic/real refusal (data_nature.refuse_mixed and its call in aggregate_results.py), secret scanning
on commit (plasbench/gitops.py) and the true-positive clamp in score_plasmids.score().

Each assertion is the behaviour one hand mutation would break; the mutations tried are listed in
docs/AUDIT_2026_11_17_STATUS.md next to the AU-022 row."""
import csv
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / "python"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(PY))
import data_nature  # noqa: E402
import score_plasmids  # noqa: E402
from plasbench import gitops  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(f"  {'ok  ' if good else 'FAIL'}  {label}{'' if good else ' -> ' + str(detail)}")
    ok &= bool(good)


# --- 1. synthetic / real refusal, the function -------------------------------------------------
sheet = {"demo1": {"sample_origin": "synthetic"}, "demo2": {"truth_source": "demo_synthetic"}, "real1": {"sample_origin": "clinical"}}


def refused(samples, allow=False):
    try:
        data_nature.refuse_mixed(samples, sheet, allow)
    except SystemExit as exc:
        return str(exc)
    return None


message = refused({"demo1", "real1"})
check("a synthetic and a real sample together are refused", message is not None and "mixes synthetic" in message, message)
check("the refusal names both groups", message is not None and "synthetic: demo1" in message and "real: real1" in message, message)
check("a sample missing from the sheet counts as real, so synthetic + unknown is refused", refused({"demo1", "nowhere"}) is not None)
check("two kinds of synthetic marking together are not a mix", refused({"demo1", "demo2"}) is None)
check("real only is allowed", refused({"real1", "nowhere"}) is None)
check("allow=True overrides the refusal", refused({"demo1", "real1"}, allow=True) is None)
check("the override still reports what it found",
      data_nature.refuse_mixed({"demo1", "real1"}, sheet, True) == (["demo1"], ["real1"]))
check("without synthetic samples the result is (no synthetic, all real)", data_nature.refuse_mixed({"real1"}, sheet) == ([], ["real1"]))

# --- 2. the same refusal as aggregate_results.py applies it -------------------------------------
SCORE_HEAD = ["sample", "tool", "analysis_track", "true_plasmid_bp", "TP_bp", "FP_bp", "FN_bp", "precision", "recall", "f1", "plasmid_recall", "true_plasmid_count"]
STATUS_HEAD = ["sample", "tool", "status", "prediction_fasta", "reason", "runtime_seconds", "peak_rss_kb"]
SAMPLES = ["s1", "s2", "s3", "s4", "s5", "s6"]
TOOLS = ["toolA", "toolB"]


def write(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def build(directory, origins):
    write(directory / "scores.tsv", SCORE_HEAD,
          [[s, t, "short_read", "1000", "800", "100", "200", "0.9", "0.8", "0.8", "1.0", "1"] for s in SAMPLES for t in TOOLS])
    write(directory / "tool_status.tsv", STATUS_HEAD, [[s, t, "completed", "", "", "10", "1000"] for s in SAMPLES for t in TOOLS])
    write(directory / "score_failures.tsv", ["sample", "tool", "stage", "reason"], [])
    write(directory / "samples.tsv", ["sample_id", "organism", "sample_origin", "source_study"],
          [[s, "Escherichia coli", origins[s], f"study{i}"] for i, s in enumerate(SAMPLES)])


def aggregate(directory, env=None):
    cmd = [sys.executable, str(PY / "aggregate_results.py"), "--scores", str(directory / "scores.tsv"), "--out-prefix", str(directory / "benchmark"),
           "--tool-status", str(directory / "tool_status.tsv"), "--sample-sheet", str(directory / "samples.tsv")]
    environment = {k: v for k, v in os.environ.items() if k != "ALLOW_SYNTHETIC_WITH_REAL"}
    return subprocess.run(cmd, capture_output=True, text=True, env={**environment, **(env or {})})


with tempfile.TemporaryDirectory() as tmp:
    d = Path(tmp)
    mixed = {s: ("synthetic" if s == "s1" else "clinical") for s in SAMPLES}
    build(d, mixed)
    r = aggregate(d)
    check("aggregate_results refuses a run that mixes synthetic and real samples", r.returncode != 0 and "mixes synthetic" in r.stderr, (r.returncode, r.stderr[-300:]))
    check("a refused run writes no leaderboard", not (d / "benchmark.leaderboard.tsv").exists())
    r = aggregate(d, env={"ALLOW_SYNTHETIC_WITH_REAL": "1"})
    check("ALLOW_SYNTHETIC_WITH_REAL=1 lets the same run through", r.returncode == 0, r.stderr[-300:])
    r = aggregate(d, env={"ALLOW_SYNTHETIC_WITH_REAL": "0"})
    check("ALLOW_SYNTHETIC_WITH_REAL=0 does not override", r.returncode != 0 and "mixes synthetic" in r.stderr, r.stderr[-300:])
    build(d, {s: "synthetic" for s in SAMPLES})
    r = aggregate(d)
    check("an all-synthetic run is allowed", r.returncode == 0, r.stderr[-300:])
    build(d, {s: "clinical" for s in SAMPLES})
    r = aggregate(d)
    check("an all-real run is allowed", r.returncode == 0, r.stderr[-300:])

# --- 3. secret scanning on commit -----------------------------------------------------------------
SECRET = "api_key = 'abcdefghijklmnopqrstuvwxyz012345'\n"
if not gitops.find_git():
    print("  SKIP  git not installed: commit-scan checks skipped")
else:
    def git(repo, *args):
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)

    def new_repo(parent, name):
        repo = Path(parent) / name
        repo.mkdir()
        git(repo, "init", "-q")
        git(repo, "config", "user.email", "t@example.org")
        git(repo, "config", "user.name", "t")
        git(repo, "config", "commit.gpgsign", "false")
        return repo

    def attempt(repo, rel, text, override=""):
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        git(repo, "add", "-f", rel)
        try:
            return gitops.commit(repo, f"add {rel}", override=override), None
        except gitops.GitError as exc:
            return None, str(exc)

    with tempfile.TemporaryDirectory() as tmp:
        repo = new_repo(tmp, "r")
        done, error = attempt(repo, "src/notes.py", "x = 1\n")
        check("a harmless file commits", done is not None and not done["overridden"], error)

        done, error = attempt(repo, "src/settings.py", SECRET)
        check("a credential assigned in plain text blocks the commit", done is None and error and "commit blocked" in error and "src/settings.py" in error, error)
        check("a blocked commit leaves HEAD where it was", git(repo, "log", "--oneline").stdout.count("\n") == 1)

        done, error = attempt(repo, "src/settings.py", SECRET, override="please")
        check("a wrong confirmation sentence does not override", done is None and error and "commit blocked" in error, error)
        done, error = attempt(repo, "src/settings.py", SECRET, override=gitops.OVERRIDE_SENTENCE)
        check("the exact confirmation sentence overrides, and the commit says so", done is not None and done["overridden"] is True, error)

        repo = new_repo(tmp, "keys")
        done, error = attempt(repo, "deploy.txt", "key: AKIAABCDEFGHIJKLMNOP\n")
        check("an AWS key in a text file blocks the commit", done is None and error and "AWS access key" in error, error)
        done, error = attempt(repo, "id_rsa.txt", "-----BEGIN RSA PRIVATE KEY-----\nabc\n")
        check("a private key block blocks the commit", done is None and error and "private key" in error, error)
        git(repo, "reset", "-q")
        done, error = attempt(repo, "config/local.env", "NCBI_API_KEY=0123456789abcdef0123456789abcdef01\n")
        check("a secrets file by name blocks the commit", done is None and error and "config/local.env" in error, error)

        repo = new_repo(tmp, "byname")
        done, error = attempt(repo, "secrets.yaml", "harmless: 1\n")
        check("a secrets file is blocked by its NAME even when its content looks harmless",
              done is None and error and "local settings or secrets file" in error, error)
        repo = new_repo(tmp, "assigned")
        done, error = attempt(repo, "db.cfg", "[db]\npassword = hunter2hunter2\n")
        check("a short plain-text password (too short for a token pattern) is caught by the assignment scan",
              done is None and error and "password, token or key assigned in plain text" in error, error)

        repo = new_repo(tmp, "fixtures")
        done, error = attempt(repo, "settings.py", "api_key = os.environ['KEY']\npassword = 'changeme'\n")
        check("placeholders and environment look-ups are not mistaken for secrets", done is not None, error)

        repo = new_repo(tmp, "empty")
        try:
            gitops.commit(repo, "nothing")
            raised = None
        except gitops.GitError as exc:
            raised = str(exc)
        check("committing with nothing staged is refused before any scan", raised is not None and "nothing is staged" in raised, raised)

# --- 4. the true-positive clamp in score() ----------------------------------------------------------
truth = {"pA": ("PLASMID", 1000), "chr": ("CHROMOSOME", 5000)}
tp, fp, fn = score_plasmids.score(truth, 1000, {"pA": [(0, 1000)], "chr": [(0, 100)]})
check("score(): full plasmid coverage and a 100 bp chromosome hit give TP 1000, FP 100, FN 0", (tp, fp, fn) == (1000, 100, 0), (tp, fp, fn))
tp, fp, fn = score_plasmids.score(truth, 1000, {"pA": [(0, 1500)]})
check("score(): coverage running past the record length is clamped, TP = 1000 not 1500", tp == 1000 and fn == 0, (tp, fp, fn))
tp, fp, fn = score_plasmids.score(truth, 1000, {"pA": [(0, 600), (400, 1500)], "chr": [(0, 9000)]})
check("score(): the chromosome side is clamped to its length too (FP 5000, not 9000)", (tp, fp, fn) == (1000, 5000, 0), (tp, fp, fn))
tp, fp, fn = score_plasmids.score(truth, 900, {"pA": [(0, 1000)]})
check("score(): FN never goes negative when TP exceeds the declared plasmid total", fn == 0 and tp == 1000, (tp, fp, fn))
tp, fp, fn = score_plasmids.score(truth, 1000, {"pA": [(0, 400)]})
check("score(): partial coverage leaves FN = total - TP", (tp, fn) == (400, 600), (tp, fp, fn))
tp, fp, fn = score_plasmids.score(truth, 1000, {"pA": [(0, 400), (300, 700)]})
check("score(): overlapping intervals count their union once (TP 700)", tp == 700 and fn == 300, (tp, fp, fn))

print("ALL GUARD MUTANT TESTS PASSED" if ok else "GUARD MUTANT TESTS FAILED")
sys.exit(0 if ok else 1)
