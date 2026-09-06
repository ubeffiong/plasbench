#!/usr/bin/env python3
"""Validate a new-isolate contribution and stage it on a local git branch.

Zero new infrastructure: everything runs on the contributor's own machine.
This wraps checks that are almost entirely reuse of validate_cohort.py's own
rules (schema, NCBI-linked evidence, cross-cohort BioSample dedup) plus two
new, small checks (a privacy/content screen and metric sanity bounds), and
ends with a git branch containing the new cohort rows, appended scores,
an updated verification lock, and a regenerated ledger -- ready for the
contributor to `git push` and open a pull request themselves. Nothing is
pushed automatically, and every rejection lists its reasons; on any failure
nothing is written and no branch is created.
"""

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from build_accession_ledger import build_ledger, write_ledger
from validate_cohort import LOCK_SCHEMA_VERSION, read_ledger, read_rows, schema_errors, verify_row


# Hygiene for public-accession metadata, not a real secret-detection tool:
# reject an absolute local path, an environment-variable reference, a
# hostname/IP, or a raw sequencing/assembly file -- none of which belong in
# a cohort/scores row, which should only ever carry public accessions and
# benchmark metrics.
ABS_PATH = re.compile(r"[A-Za-z]:[\\/]|(?:^|[\\/])(?:home|Users|root)[\\/]")
ENV_VAR = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*|%[A-Za-z_][A-Za-z0-9_]*%")
HOSTNAME = re.compile(r"\b[A-Za-z0-9-]+\.(?:local|internal|lan|corp)\b|\b\d{1,3}(?:\.\d{1,3}){3}\b")
RAW_SEQ_FILE = re.compile(r"\.(?:fastq|fq|fasta|fa|fna)(?:\.gz)?$", re.IGNORECASE)
METRIC_FIELDS_01 = ("precision", "recall", "f1", "plasmid_recall", "amr_gene_recall", "circular_plasmid_recall")
RESOURCE_FIELDS_NONNEG = ("runtime_seconds", "peak_rss_kb")


def content_screen_errors(rows, label):
    errors = []
    for number, row in enumerate(rows, 1):
        for field, value in row.items():
            value = (value or "").strip()
            if not value:
                continue
            if RAW_SEQ_FILE.search(value):
                errors.append(f"{label} row {number}: field {field!r} names a raw sequence/assembly file ({value!r}); "
                              "never bundle or reference raw sequencing data, only public accessions")
            elif ABS_PATH.search(value):
                errors.append(f"{label} row {number}: field {field!r} contains an absolute local file path ({value!r})")
            elif ENV_VAR.search(value):
                errors.append(f"{label} row {number}: field {field!r} contains an environment-variable reference ({value!r})")
            elif HOSTNAME.search(value):
                errors.append(f"{label} row {number}: field {field!r} contains a hostname or IP address ({value!r})")
    return errors


def bounds_errors(rows, label, fields, low, high):
    errors = []
    for number, row in enumerate(rows, 1):
        for field in fields:
            value = (row.get(field) or "").strip()
            if not value:
                continue
            try:
                parsed = float(value)
            except ValueError:
                errors.append(f"{label} row {number}: {field}={value!r} is not numeric")
                continue
            if not (low <= parsed <= high if high is not None else parsed >= low):
                bound = f"[{low}, {high}]" if high is not None else f">= {low}"
                errors.append(f"{label} row {number}: {field}={parsed} is outside {bound}")
    return errors


def scoped_rows(rows, sample_ids, label):
    """Split rows into (in-scope, errors): every declared new sample_id must have
    at least one row, and no row may reference a sample outside the contribution
    -- silently dropping out-of-scope rows would either lose a promised sample's
    evidence or leak unrelated samples into the cohort's committed history."""
    errors = []
    in_scope = [row for row in rows if row.get("sample") in sample_ids]
    out_of_scope = sorted({row.get("sample") for row in rows if row.get("sample") not in sample_ids})
    if out_of_scope:
        errors.append(f"{label}: contains row(s) for sample(s) not in this contribution: {', '.join(out_of_scope)}")
    covered = {row.get("sample") for row in in_scope}
    missing = sorted(sample_ids - covered)
    if missing:
        errors.append(f"{label}: no row(s) found for new sample_id(s): {', '.join(missing)}")
    return in_scope, errors


def append_rows(path, fields, rows):
    is_new = not path.is_file()
    with open(path, "a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        if is_new:
            writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def existing_header(path):
    if not path.is_file():
        return None
    with open(path, newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle, delimiter="\t"), None)


def git(args, root, check=True):
    return subprocess.run(["git", *args], cwd=root, check=check, capture_output=True, text=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cohort", required=True, help="Target cohort name, e.g. public-v2 (must already exist as cohorts/<NAME>.tsv).")
    parser.add_argument("--new-rows", type=Path, required=True, help="TSV of new cohort rows; columns must be a subset of cohorts/<NAME>.tsv's own header, including every required column.")
    parser.add_argument("--scores", type=Path, required=True, help="Your own locally-produced scores.tsv containing row(s) for the new sample_id(s), and nothing else.")
    parser.add_argument("--tool-status", type=Path, help="Optional locally-produced tool_status.tsv for the new sample_id(s).")
    parser.add_argument("--cohorts-dir", type=Path, default=Path("cohorts"))
    parser.add_argument("--branch-label", help="contrib/<label> branch name; required when --new-rows has more than one sample.")
    parser.add_argument("--email", help="Contact email sent to NCBI E-utilities.")
    parser.add_argument("--api-key", help="NCBI API key; defaults to NCBI_API_KEY when omitted.")
    args = parser.parse_args()

    errors = []
    cohorts_dir = args.cohorts_dir
    cohort_path = cohorts_dir / f"{args.cohort}.tsv"
    lock_path = cohorts_dir / f"{args.cohort}.lock.json"
    scores_out_path = cohorts_dir / f"{args.cohort}.scores.tsv"
    tool_status_out_path = cohorts_dir / f"{args.cohort}.tool_status.tsv"
    ledger_path = cohorts_dir / "accepted_accessions.tsv"
    if not cohort_path.is_file():
        raise SystemExit(f"ERROR: no such cohort {args.cohort!r} ({cohort_path} not found)")

    for path in (args.new_rows, args.scores, args.tool_status):
        if path and RAW_SEQ_FILE.search(path.name):
            raise SystemExit(f"ERROR: {path} looks like a raw sequence/assembly file, not a TSV; refusing to read it")

    cohort_rows, cohort_fields = read_rows(cohort_path)
    new_rows, new_fields = read_rows(args.new_rows)
    unknown = [field for field in new_fields if field not in cohort_fields]
    if unknown:
        errors.append(f"--new-rows has column(s) not present in {cohort_path}: {', '.join(unknown)}")
    else:
        existing_ids = {row["sample_id"] for row in cohort_rows}
        collisions = sorted({row.get("sample_id") for row in new_rows} & existing_ids)
        if collisions:
            errors.append(f"sample_id already present in {cohort_path}: {', '.join(collisions)}")
        errors.extend(schema_errors(new_rows, new_fields, ledger=read_ledger(ledger_path)))

    sample_ids = {row.get("sample_id") for row in new_rows if row.get("sample_id")}
    if not sample_ids:
        raise SystemExit("ERROR: --new-rows contains no usable sample_id(s)")
    if len(sample_ids) > 1 and not args.branch_label:
        raise SystemExit("ERROR: --branch-label is required when contributing more than one sample")
    branch_label = args.branch_label or next(iter(sample_ids))

    scores_rows, scores_fields = read_rows(args.scores)
    in_scope_scores, scope_errors = scoped_rows(scores_rows, sample_ids, "--scores")
    errors.extend(scope_errors)
    existing_scores_header = existing_header(scores_out_path)
    if existing_scores_header and existing_scores_header != scores_fields:
        errors.append(f"--scores header does not match existing {scores_out_path}'s header")
    errors.extend(bounds_errors(in_scope_scores, "--scores", METRIC_FIELDS_01, 0.0, 1.0))

    tool_status_rows, tool_status_fields, in_scope_status = [], [], []
    if args.tool_status:
        tool_status_rows, tool_status_fields = read_rows(args.tool_status)
        in_scope_status, scope_errors = scoped_rows(tool_status_rows, sample_ids, "--tool-status")
        errors.extend(scope_errors)
        existing_status_header = existing_header(tool_status_out_path)
        if existing_status_header and existing_status_header != tool_status_fields:
            errors.append(f"--tool-status header does not match existing {tool_status_out_path}'s header")
        errors.extend(bounds_errors(in_scope_status, "--tool-status", RESOURCE_FIELDS_NONNEG, 0.0, None))

    errors.extend(content_screen_errors(new_rows, "--new-rows"))
    errors.extend(content_screen_errors(in_scope_scores, "--scores"))
    errors.extend(content_screen_errors(in_scope_status, "--tool-status"))

    evidence = []
    if not errors:
        for row in new_rows:
            result = verify_row(row, args.email, args.api_key)
            evidence.append(result)
            errors.extend(f"{row['sample_id']}: {message}" for message in result["errors"])

    if errors:
        raise SystemExit("CONTRIBUTION REJECTED\n" + "\n".join(errors))

    root = Path.cwd()
    toplevel = git(["rev-parse", "--show-toplevel"], root, check=False)
    if toplevel.returncode != 0:
        raise SystemExit("ERROR: prepare-contribution requires a git checkout (no .git found)")
    status = git(["status", "--porcelain"], root).stdout
    if status.strip():
        raise SystemExit(
            "ERROR: working tree has uncommitted changes; commit or stash them first so this "
            "contribution's commit contains only the contribution itself.\n" + status
        )
    branch_name = f"contrib/{branch_label}"
    if git(["rev-parse", "--verify", "--quiet", f"refs/heads/{branch_name}"], root, check=False).returncode == 0:
        raise SystemExit(f"ERROR: branch {branch_name} already exists")

    git(["checkout", "-b", branch_name], root)

    append_rows(cohort_path, cohort_fields, new_rows)
    append_rows(scores_out_path, scores_fields, in_scope_scores)
    changed = [cohort_path, scores_out_path]
    if in_scope_status:
        append_rows(tool_status_out_path, tool_status_fields, in_scope_status)
        changed.append(tool_status_out_path)

    old_lock = json.loads(lock_path.read_text(encoding="utf-8")) if lock_path.is_file() else {"evidence": []}
    merged_sheet_sha256 = hashlib.sha256(cohort_path.read_bytes()).hexdigest()
    lock_path.write_text(json.dumps({
        "schema_version": LOCK_SCHEMA_VERSION, "sample_sheet": cohort_path.name,
        "sample_sheet_sha256": merged_sheet_sha256,
        "evidence": (old_lock.get("evidence") or []) + evidence,
    }, indent=2) + "\n", encoding="utf-8")
    changed.append(lock_path)

    by_biosample, _ = build_ledger(cohorts_dir)
    write_ledger(by_biosample, ledger_path)
    changed.append(ledger_path)

    git(["add", *(str(path) for path in changed)], root)
    git(["commit", "-m", f"Add contribution: {branch_label} ({len(sample_ids)} isolate(s)) to {args.cohort}"], root)

    print(f"CONTRIBUTION PREPARED: branch {branch_name}")
    print(f"  {len(sample_ids)} new sample(s): {', '.join(sorted(sample_ids))}")
    for path in changed:
        print(f"  updated: {path}")
    print("\nNothing has been pushed. Review the commit, then:")
    print(f"  git push -u origin {branch_name}")
    print("  and open a pull request.")


if __name__ == "__main__":
    main()
