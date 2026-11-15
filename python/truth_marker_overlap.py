#!/usr/bin/env python3
"""
truth_marker_overlap.py -- which tools share a database with the evidence that labelled the truth?

The evidence-based truth labels (python/label_truth_evidence.py) use replicon and MOB-typing calls, and a plasmid reference match. A benchmarked tool that classifies
plasmids with the SAME database (MOB-suite's `mob_recon` and its `mob_typer` marker call, for example) can look good partly because truth and tool agree through shared
evidence, not because the tool is right. This table makes that visible: for every tool that uses a reference database, and every marker caller behind the truth labels,
is the database the same, possibly overlapping in content, not shared, or unknown?

Inputs (both shipped, both readable): config/truth_marker_databases.tsv (marker_caller, database, tool_database_pattern, overlap_kind, note) and
config/tool_database_releases.tsv (tool, uses_reference_database, database, ...). A tool's database text is matched against each caller's pattern:

  yes       the pattern matches and overlap_kind is same_database
  possible  the pattern matches and overlap_kind is possible_content_overlap (different database, content may overlap; not verified at sequence level)
  no        the tool uses a database and nothing matches, or it uses none
  unknown   the tool's database is not recorded (uses_reference_database unknown or the text is blank)

This is a name-level screen, NOT a sequence-level proof either way; the sequence-level evidence for leakage is database_containment.py. Advisory: it never changes a
score or a rank. Output: benchmark.truth_marker_overlap.tsv. Standard library only.
"""
import argparse
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ("tool", "uses_reference_database", "tool_database", "marker_caller", "marker_database", "shared", "overlap_kind", "note")


def read_tsv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader((line for line in handle if line.strip() and not line.lstrip().startswith("#")), delimiter="\t"))


def classify(tool_row, marker):
    uses = (tool_row.get("uses_reference_database") or "").strip().lower()
    text = (tool_row.get("database") or "").strip()
    if uses == "no":
        return "no"
    if uses not in ("yes",) or not text:
        return "unknown"
    try:
        matched = re.search(marker["tool_database_pattern"], text, re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"the tool_database_pattern of marker {marker.get('marker_caller', marker.get('caller', '?'))!r} is not a valid regular expression: {exc}")
    if matched:
        return "yes" if marker.get("overlap_kind") == "same_database" else "possible"
    return "no"


def overlap_table(releases, markers):
    rows = []
    for tool_row in releases:
        for marker in markers:
            shared = classify(tool_row, marker)
            rows.append({"tool": tool_row["tool"], "uses_reference_database": tool_row.get("uses_reference_database", ""), "tool_database": tool_row.get("database", ""),
                         "marker_caller": marker["marker_caller"], "marker_database": marker["database"], "shared": shared,
                         "overlap_kind": marker.get("overlap_kind", ""), "note": marker.get("note", "")})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--releases", default=str(ROOT / "config" / "tool_database_releases.tsv"))
    ap.add_argument("--markers", default=str(ROOT / "config" / "truth_marker_databases.tsv"))
    ap.add_argument("--out", required=True, help="benchmark.truth_marker_overlap.tsv")
    args = ap.parse_args()
    try:
        rows = overlap_table(read_tsv(args.releases), read_tsv(args.markers))
    except (OSError, KeyError, ValueError) as exc:
        raise SystemExit(f"ERROR: cannot read the database registries: {exc}")
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    shared = sorted({r["tool"] for r in rows if r["shared"] == "yes"})
    sys.stderr.write(f"[truth_marker_overlap] {len(rows)} (tool, marker caller) rows; tools sharing a database with the truth evidence: {', '.join(shared) or 'none'} -> {args.out}\n")


if __name__ == "__main__":
    main()
