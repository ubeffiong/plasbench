#!/usr/bin/env python3
"""Regression for python/prepare_contribution.py: schema/dedup checks reused
from validate_cohort.py, the two new small checks (privacy/content screen,
metric sanity bounds), and the git-branch staging every successful run ends
with. NCBI evidence retrieval is monkeypatched (the same pattern
test_cohort_validation.py already uses for validate_cohort.fetch) so this
runs fully offline; prepare_contribution.py's own git operations are real,
local, and confined to a throwaway temp repo per scenario.
"""

import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))

import prepare_contribution  # noqa: E402


COHORT_FIELDS = ("sample_id", "assembly_accession", "sra_run", "organism", "truth_technology",
                 "truth_quality_tier", "biosample", "bioproject", "sample_origin", "read_depth_x",
                 "assembly_plasmid_count", "source_study")
SCORES_FIELDS = ("sample", "tool", "precision", "recall", "f1")
STATUS_FIELDS = ("sample", "tool", "status", "runtime_seconds", "peak_rss_kb")


def write_tsv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def git(args, cwd, check=True):
    return subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True)


def init_repo(tmp):
    root = Path(tmp)
    (root / "cohorts").mkdir()
    git(["init", "-q"], root)
    git(["config", "user.email", "test@example.com"], root)
    git(["config", "user.name", "Test"], root)
    existing = [{"sample_id": "existing_a", "assembly_accession": "GCF_000000001.1", "sra_run": "SRR0000001",
                 "organism": "Example bacterium", "truth_technology": "hybrid", "truth_quality_tier": "A",
                 "biosample": "SAMN000001", "bioproject": "PRJNA1", "sample_origin": "", "read_depth_x": "",
                 "assembly_plasmid_count": "", "source_study": "Existing_2020_study"}]
    write_tsv(root / "cohorts" / "demo.tsv", existing, COHORT_FIELDS)
    git(["add", "-A"], root)
    git(["commit", "-q", "-m", "seed"], root)
    base_branch = git(["rev-parse", "--abbrev-ref", "HEAD"], root).stdout.strip()
    return root, base_branch


def fake_verify_row_ok(row, email=None, api_key=None):
    return {"sample_id": row["sample_id"],
            "assembly": {"accession": row["assembly_accession"], "biosample": row["biosample"],
                         "derived_truth_technology": row["truth_technology"]},
            "run": {"run": row["sra_run"], "biosample": row["biosample"]}, "errors": []}


def call_main(root, argv):
    old_argv, old_cwd = sys.argv, os.getcwd()
    sys.argv = ["prepare_contribution.py", *argv]
    os.chdir(root)
    try:
        prepare_contribution.main()
        return True, ""
    except SystemExit as exc:
        return False, ("" if exc.code is None else str(exc.code))
    finally:
        sys.argv = old_argv
        os.chdir(old_cwd)


def new_row(sample_id, biosample, **overrides):
    row = {"sample_id": sample_id, "assembly_accession": "GCF_000000002.1", "sra_run": "SRR0000002",
           "organism": "Example bacterium", "truth_technology": "hybrid", "truth_quality_tier": "A",
           "biosample": biosample, "bioproject": "PRJNA2", "sample_origin": "", "read_depth_x": "",
           "assembly_plasmid_count": "", "source_study": "New_2024_study"}
    row.update(overrides)
    return row


def main():
    # prepare_contribution.py shells out to git for real -- on a machine
    # without it (a bare `pip install` of the released tarball, per
    # README.md's explicit curl-not-git-clone install path, is never
    # guaranteed to have git present), this test cannot exercise the git
    # branch it stages. Skip cleanly rather than crash with a raw
    # FileNotFoundError, matching test_report_javascript.py's precedent for
    # an optional external tool.
    if not shutil.which("git"):
        print("ALL PREPARE-CONTRIBUTION TESTS PASSED (git not found: skipped)")
        return

    original_verify_row = prepare_contribution.verify_row
    prepare_contribution.verify_row = fake_verify_row_ok
    try:
        # Input TSVs live in a separate temp directory, outside the git repo
        # under test: they are the contributor's own local files, not part of
        # the repo's working tree, and must not trip the clean-working-tree
        # guard as stray untracked files.
        with tempfile.TemporaryDirectory(prefix="contrib_") as tmp, \
             tempfile.TemporaryDirectory(prefix="contrib_inputs_") as inputs_tmp:
            root, base_branch = init_repo(tmp)
            cohorts_dir = root / "cohorts"
            inputs = Path(inputs_tmp)

            # --- happy path: a clean new isolate produces a correct branch ---
            write_tsv(inputs / "new_rows.tsv", [new_row("new_a", "SAMN000002")], COHORT_FIELDS)
            write_tsv(inputs / "scores.tsv",
                      [{"sample": "new_a", "tool": "mob_recon", "precision": "0.90", "recall": "0.80", "f1": "0.85"}],
                      SCORES_FIELDS)
            write_tsv(inputs / "status.tsv",
                      [{"sample": "new_a", "tool": "mob_recon", "status": "completed",
                        "runtime_seconds": "120", "peak_rss_kb": "500000"}],
                      STATUS_FIELDS)
            ok, message = call_main(root, [
                "--cohort", "demo", "--new-rows", str(inputs / "new_rows.tsv"),
                "--scores", str(inputs / "scores.tsv"), "--tool-status", str(inputs / "status.tsv"),
                "--cohorts-dir", str(cohorts_dir),
            ])
            assert ok, f"expected a clean contribution to succeed, got: {message}"
            assert git(["rev-parse", "--verify", "--quiet", "refs/heads/contrib/new_a"], root, check=False).returncode == 0, \
                "expected branch contrib/new_a to exist"
            current_branch = git(["rev-parse", "--abbrev-ref", "HEAD"], root).stdout.strip()
            assert current_branch == "contrib/new_a", f"expected to be left on contrib/new_a, got {current_branch}"
            assert git(["status", "--porcelain"], root).stdout.strip() == "", "contribution branch must be committed, not left dirty"
            with open(cohorts_dir / "demo.tsv", encoding="utf-8") as handle:
                ids = [row["sample_id"] for row in csv.DictReader(handle, delimiter="\t")]
            assert ids == ["existing_a", "new_a"], f"expected new_a appended to demo.tsv, got {ids}"
            with open(cohorts_dir / "demo.scores.tsv", encoding="utf-8") as handle:
                scores_rows = list(csv.DictReader(handle, delimiter="\t"))
            assert len(scores_rows) == 1 and scores_rows[0]["sample"] == "new_a"
            with open(cohorts_dir / "demo.tool_status.tsv", encoding="utf-8") as handle:
                status_rows = list(csv.DictReader(handle, delimiter="\t"))
            assert len(status_rows) == 1 and status_rows[0]["sample"] == "new_a"
            lock = json.loads((cohorts_dir / "demo.lock.json").read_text(encoding="utf-8"))
            assert any(record["sample_id"] == "new_a" for record in lock["evidence"])
            with open(cohorts_dir / "accepted_accessions.tsv", encoding="utf-8") as handle:
                ledger_rows = {row["biosample"]: row for row in csv.DictReader(handle, delimiter="\t")}
            assert "SAMN000002" in ledger_rows and ledger_rows["SAMN000002"]["source_cohort"] == "demo"
            log = git(["log", "-1", "--oneline"], root).stdout
            assert "new_a" in log
            print("clean new isolate -> correct branch, appended files, lock, and ledger -> PASS")

            # Merge (not just checkout) back to base_branch: the ledger/lock/scores
            # files exist only in the contribution's own commit, and a plain
            # checkout across branches would delete files the target branch's
            # history never had -- exactly what a merged PR would do for real.
            git(["checkout", "-q", base_branch], root)
            git(["merge", "-q", "--ff-only", "contrib/new_a"], root)

            # --- duplicate BioSample (already in the ledger from the contribution
            # just committed, under a different sample_id/accession -- the exact
            # "resubmitted assembly, same physical isolate" case) is rejected ---
            write_tsv(inputs / "dup_rows.tsv", [new_row("new_b", "SAMN000002", assembly_accession="GCF_000000003.1")], COHORT_FIELDS)
            write_tsv(inputs / "dup_scores.tsv",
                      [{"sample": "new_b", "tool": "mob_recon", "precision": "0.9", "recall": "0.8", "f1": "0.85"}],
                      SCORES_FIELDS)
            ok, message = call_main(root, [
                "--cohort", "demo", "--new-rows", str(inputs / "dup_rows.tsv"),
                "--scores", str(inputs / "dup_scores.tsv"), "--cohorts-dir", str(cohorts_dir),
            ])
            assert not ok, "expected a re-submitted BioSample to be rejected"
            assert "already in cohort" in message, message
            assert git(["rev-parse", "--verify", "--quiet", "refs/heads/contrib/new_b"], root, check=False).returncode != 0, \
                "a rejected contribution must not leave a branch behind"
            print("duplicate BioSample (resubmitted under a new accession) -> rejected with the right reason -> PASS")

            # --- a metric outside [0, 1] is rejected ---
            write_tsv(inputs / "bounds_rows.tsv", [new_row("new_c", "SAMN000003")], COHORT_FIELDS)
            write_tsv(inputs / "bounds_scores.tsv",
                      [{"sample": "new_c", "tool": "mob_recon", "precision": "0.9", "recall": "0.8", "f1": "1.5"}],
                      SCORES_FIELDS)
            ok, message = call_main(root, [
                "--cohort", "demo", "--new-rows", str(inputs / "bounds_rows.tsv"),
                "--scores", str(inputs / "bounds_scores.tsv"), "--cohorts-dir", str(cohorts_dir),
            ])
            assert not ok and "outside" in message, message
            print("an out-of-[0,1] metric is rejected -> PASS")

            # --- a negative runtime is rejected ---
            write_tsv(inputs / "neg_status.tsv",
                      [{"sample": "new_c", "tool": "mob_recon", "status": "completed",
                        "runtime_seconds": "-5", "peak_rss_kb": "1000"}], STATUS_FIELDS)
            write_tsv(inputs / "ok_scores.tsv",
                      [{"sample": "new_c", "tool": "mob_recon", "precision": "0.9", "recall": "0.8", "f1": "0.85"}],
                      SCORES_FIELDS)
            ok, message = call_main(root, [
                "--cohort", "demo", "--new-rows", str(inputs / "bounds_rows.tsv"),
                "--scores", str(inputs / "ok_scores.tsv"), "--tool-status", str(inputs / "neg_status.tsv"),
                "--cohorts-dir", str(cohorts_dir),
            ])
            assert not ok and "outside" in message, message
            print("a negative runtime_seconds is rejected -> PASS")

            # --- privacy/content screen: an absolute local path in a free-text field ---
            write_tsv(inputs / "path_rows.tsv",
                      [new_row("new_d", "SAMN000004", source_study="see C:\\Users\\alice\\notes.txt")], COHORT_FIELDS)
            write_tsv(inputs / "path_scores.tsv",
                      [{"sample": "new_d", "tool": "mob_recon", "precision": "0.9", "recall": "0.8", "f1": "0.85"}],
                      SCORES_FIELDS)
            ok, message = call_main(root, [
                "--cohort", "demo", "--new-rows", str(inputs / "path_rows.tsv"),
                "--scores", str(inputs / "path_scores.tsv"), "--cohorts-dir", str(cohorts_dir),
            ])
            assert not ok and "absolute local file path" in message, message
            print("an absolute local file path in a free-text field is rejected -> PASS")

            # --- privacy/content screen: a raw sequence file named in a field ---
            write_tsv(inputs / "seq_rows.tsv",
                      [new_row("new_e", "SAMN000005", source_study="reads_1.fastq.gz")], COHORT_FIELDS)
            write_tsv(inputs / "seq_scores.tsv",
                      [{"sample": "new_e", "tool": "mob_recon", "precision": "0.9", "recall": "0.8", "f1": "0.85"}],
                      SCORES_FIELDS)
            ok, message = call_main(root, [
                "--cohort", "demo", "--new-rows", str(inputs / "seq_rows.tsv"),
                "--scores", str(inputs / "seq_scores.tsv"), "--cohorts-dir", str(cohorts_dir),
            ])
            assert not ok and "raw sequence/assembly file" in message, message
            print("a raw sequence/assembly filename in a field is rejected -> PASS")

            # --- passing a FASTQ itself as --scores is rejected immediately ---
            (inputs / "reads.fastq.gz").write_text("not real data", encoding="utf-8")
            ok, message = call_main(root, [
                "--cohort", "demo", "--new-rows", str(inputs / "new_rows.tsv"),
                "--scores", str(inputs / "reads.fastq.gz"), "--cohorts-dir", str(cohorts_dir),
            ])
            assert not ok
            print("passing a raw FASTQ path as --scores is rejected -> PASS")

            # --- scores.tsv missing a declared new sample_id is rejected ---
            write_tsv(inputs / "cov_rows.tsv",
                      [new_row("new_f", "SAMN000006"), new_row("new_g", "SAMN000007")], COHORT_FIELDS)
            write_tsv(inputs / "cov_scores.tsv",
                      [{"sample": "new_f", "tool": "mob_recon", "precision": "0.9", "recall": "0.8", "f1": "0.85"}],
                      SCORES_FIELDS)
            ok, message = call_main(root, [
                "--cohort", "demo", "--new-rows", str(inputs / "cov_rows.tsv"),
                "--scores", str(inputs / "cov_scores.tsv"), "--cohorts-dir", str(cohorts_dir),
                "--branch-label", "batch_fg",
            ])
            assert not ok and "no row(s) found for new sample_id(s): new_g" in message, message
            print("scores.tsv missing coverage for a declared sample_id is rejected -> PASS")

            # --- scores.tsv containing an out-of-scope sample is rejected ---
            write_tsv(inputs / "scope_scores.tsv",
                      [{"sample": "new_f", "tool": "mob_recon", "precision": "0.9", "recall": "0.8", "f1": "0.85"},
                       {"sample": "unrelated_sample", "tool": "mob_recon", "precision": "0.9", "recall": "0.8", "f1": "0.85"}],
                      SCORES_FIELDS)
            write_tsv(inputs / "single_row.tsv", [new_row("new_f", "SAMN000006")], COHORT_FIELDS)
            ok, message = call_main(root, [
                "--cohort", "demo", "--new-rows", str(inputs / "single_row.tsv"),
                "--scores", str(inputs / "scope_scores.tsv"), "--cohorts-dir", str(cohorts_dir),
            ])
            assert not ok and "not in this contribution" in message, message
            print("scores.tsv row for a sample outside the contribution is rejected -> PASS")

            # --- an uncommitted working tree blocks a contribution ---
            write_tsv(inputs / "single_f_scores.tsv",
                      [{"sample": "new_f", "tool": "mob_recon", "precision": "0.9", "recall": "0.8", "f1": "0.85"}],
                      SCORES_FIELDS)
            (cohorts_dir / "demo.tsv").write_text(
                (cohorts_dir / "demo.tsv").read_text(encoding="utf-8") + "# scratch\n", encoding="utf-8")
            ok, message = call_main(root, [
                "--cohort", "demo", "--new-rows", str(inputs / "single_row.tsv"),
                "--scores", str(inputs / "single_f_scores.tsv"), "--cohorts-dir", str(cohorts_dir),
            ])
            assert not ok and "uncommitted changes" in message, message
            git(["checkout", "--", "cohorts/demo.tsv"], root)
            print("an uncommitted working tree blocks a contribution -> PASS")

            # --- not a git checkout at all ---
            with tempfile.TemporaryDirectory(prefix="nogit_") as tmp2:
                nogit_root = Path(tmp2)
                (nogit_root / "cohorts").mkdir()
                write_tsv(nogit_root / "cohorts" / "demo.tsv", [], COHORT_FIELDS)
                ok, message = call_main(nogit_root, [
                    "--cohort", "demo", "--new-rows", str(inputs / "single_row.tsv"),
                    "--scores", str(inputs / "single_f_scores.tsv"), "--cohorts-dir", str(nogit_root / "cohorts"),
                ])
                assert not ok and "requires a git checkout" in message, message
            print("running outside a git checkout is rejected -> PASS")

        print("ALL PREPARE-CONTRIBUTION TESTS PASSED")
    finally:
        prepare_contribution.verify_row = original_verify_row


if __name__ == "__main__":
    main()
