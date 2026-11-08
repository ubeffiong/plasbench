#!/usr/bin/env python3
"""
flag_database_overlap.py -- flag sample x tool pairs where the truth genome
may already be inside the tool's own reference database or training data.

Most plasmid tools score contigs against a database of known plasmids
(MOB-suite, Platon, Plassembler/PLSDB) or a model trained on them (geNomad,
RFPlasmid, plASgraph2, ...). Those databases are built from public complete
genomes -- the same RefSeq/GenBank Complete Genome assemblies PlasBench uses
as truth. When a truth assembly was public before a tool's database was
built, the tool may be "recognising" plasmids it has already seen, which
inflates its score relative to genuinely new isolates.

This is a date-based screen, not proof of inclusion: an assembly released
before the database MAY be in it ("possible_overlap"); one released after it
cannot be ("after_database"). Dates come from:
  * truth release date: the sample sheet's truth_release_date column if
    present, else NCBI's assembly_data_report.jsonl (assemblyInfo.releaseDate)
    saved by stage 1 under DATA_DIR/<sample>/;
  * database release date: config/tool_database_releases.tsv, which the user
    fills with the release date of the database version actually installed.

Output TSV columns: sample, tool, truth_release_date, database_release_date,
overlap_status (possible_overlap | after_database | no_reference_database |
unknown), reason.

Standard library only.
"""

import argparse
import csv
import datetime as dt
import glob
import json
import os
import sys


def parse_date(text):
    """YYYY-MM-DD (optionally followed by a time, as NCBI writes it), else None."""
    text = (text or "").strip().replace("/", "-")
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        return None


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        lines = (line for line in handle if line.strip() and not line.lstrip().startswith("#"))
        return list(csv.DictReader(lines, delimiter="\t"))


def assembly_release_date(data_dir, sample):
    """releaseDate from the NCBI assembly_data_report.jsonl saved for a sample."""
    if not data_dir:
        return None
    sample_dir = os.path.join(data_dir, sample)
    candidates = [os.path.join(sample_dir, "assembly_data_report.jsonl")]
    candidates += sorted(glob.glob(os.path.join(sample_dir, "ncbi", "**", "assembly_data_report.jsonl"),
                                   recursive=True))
    for path in candidates:
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                info = record.get("assemblyInfo") or record.get("assembly_info") or {}
                date = parse_date(info.get("releaseDate") or info.get("release_date") or "")
                if date:
                    return date
    return None


def classify(truth_date, uses_db, db_date):
    uses_db = (uses_db or "").strip().lower()
    if uses_db == "no":
        return "no_reference_database", "tool uses no reference plasmid database or trained model"
    if uses_db not in ("yes", "unknown"):
        return "unknown", "tool not listed in the database registry"
    if db_date is None:
        return "unknown", "database_release_date not filled in config/tool_database_releases.tsv"
    if truth_date is None:
        return "unknown", "truth assembly release date not available"
    if truth_date <= db_date:
        return "possible_overlap", "truth assembly was public before the tool's database release"
    return "after_database", "truth assembly was released after the tool's database"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample-sheet", required=True)
    ap.add_argument("--registry", required=True, help="config/tool_database_releases.tsv")
    ap.add_argument("--scores", required=True, help="scores.tsv; defines which sample x tool pairs to flag")
    ap.add_argument("--data-dir", help="DATA_DIR holding <sample>/assembly_data_report.jsonl")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    registry = {row["tool"]: row for row in read_rows(args.registry) if row.get("tool")}
    sheet = {row["sample_id"]: row for row in read_rows(args.sample_sheet) if row.get("sample_id")}
    pairs = sorted({(row["sample"], row["tool"]) for row in read_rows(args.scores)
                    if row.get("sample") and row.get("tool")})

    truth_dates = {}
    for sample in sorted({sample for sample, _ in pairs}):
        row = sheet.get(sample, {})
        truth_dates[sample] = parse_date(row.get("truth_release_date", "")) or \
            assembly_release_date(args.data_dir, sample)

    counts = {}
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["sample", "tool", "truth_release_date", "database_release_date", "overlap_status", "reason"])
        for sample, tool in pairs:
            entry = registry.get(tool, {})
            db_date = parse_date(entry.get("database_release_date", ""))
            status, reason = classify(truth_dates.get(sample), entry.get("uses_reference_database"), db_date)
            counts[status] = counts.get(status, 0) + 1
            writer.writerow([sample, tool, truth_dates.get(sample) or "", db_date or "", status, reason])
    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "no scored pairs"
    sys.stderr.write(f"[flag_database_overlap] {summary} -> {args.out}\n")


if __name__ == "__main__":
    main()
