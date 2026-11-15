#!/usr/bin/env python3
"""Promote a REVIEWED AMR truth draft to the curated truth_amr.tsv (plan B4): a deliberate human step, with a record of who took it.

derive_amr_truth.py writes `truth_amr.draft.tsv` from reference annotation and never `truth_amr.tsv`, because the AMR metrics need curated truth. This is
the one step that turns a draft into truth, and it refuses to run unattended:

  --reviewed-by NAME        required: who reviewed the draft gene by gene
  --confirm-reviewed        required: states that the review was done (a flag, not a default)
  --database-version V      required: the real AMR database version; the draft only holds the caller's version, which is not the same thing
  --force                   needed to overwrite an existing truth_amr.tsv

The output keeps every draft column, sets `evidence_tier` to `reviewed`, replaces `database_version`, and records `reviewed_by`, `reviewed_on` and the SHA-256
of the draft that was reviewed, so the file says where it came from. It is checked with validate_amr_truth.validate() before it is written; a draft that does
not validate is not promoted. Nothing here edits a gene: if the review changed a row, change the draft first.

Standard library only.
"""
import argparse
import csv
import datetime
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_amr_truth as vat  # noqa: E402

EXTRA = ("reviewed_by", "reviewed_on", "draft_sha256")


def promote(draft, truth, out, reviewed_by, database_version, confirmed, force=False, today=None):
    """Write `out` from `draft`; return the number of gene copies. Raises ValueError with the reason when it must not."""
    if not confirmed:
        raise ValueError("--confirm-reviewed is required: promotion states that the draft was reviewed gene by gene")
    if not (reviewed_by or "").strip():
        raise ValueError("--reviewed-by must name the reviewer")
    if not (database_version or "").strip():
        raise ValueError("--database-version must be the real AMR database version")
    if os.path.basename(out) != "truth_amr.tsv":
        raise ValueError("the promoted file must be named truth_amr.tsv (it is the file the scorer reads)")
    if os.path.exists(out) and not force:
        raise ValueError(f"{out} already exists; pass --force to replace it")
    with open(draft, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    with open(draft, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if not rows:
        raise ValueError("the draft has no gene copies to promote")
    for column in ("evidence_tier", "database_version"):
        if column not in fields:
            fields.append(column)
    fields += [c for c in EXTRA if c not in fields]
    when = (today or datetime.date.today()).isoformat()
    for row in rows:
        row.update(evidence_tier="reviewed", database_version=database_version.strip(), reviewed_by=reviewed_by.strip(), reviewed_on=when, draft_sha256=digest)
    temporary = out + ".tmp"
    with open(temporary, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    try:
        count = vat.validate(temporary, truth)
    except ValueError:
        os.remove(temporary)
        raise
    os.replace(temporary, out)
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--draft", required=True)
    parser.add_argument("--truth", required=True)
    parser.add_argument("--out")
    parser.add_argument("--reviewed-by", required=True)
    parser.add_argument("--database-version", required=True)
    parser.add_argument("--confirm-reviewed", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    out = args.out or os.path.join(os.path.dirname(os.path.abspath(args.draft)), "truth_amr.tsv")
    try:
        count = promote(args.draft, args.truth, out, args.reviewed_by, args.database_version, args.confirm_reviewed, args.force)
    except ValueError as exc:
        raise SystemExit(f"ERROR: {exc}")
    print(f"Promoted {count} gene copy/copies to {out} (reviewed by {args.reviewed_by}).")


if __name__ == "__main__":
    main()
