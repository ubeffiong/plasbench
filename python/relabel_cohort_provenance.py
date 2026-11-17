#!/usr/bin/env python3
"""Recompute a cohort sheet's truth_assembly_strategy and truth_polish_reads from the sheet's own assembly_method and assembly_sequencing_technology columns.

The two labels are derived from NCBI free text by truth_provenance.classify_method. When that function is corrected (the 17 November audit found that it missed OXFORD_NANOPORE,
IlluminaMiSeq and the Illumina polishers Polypolish and Pilon), a cohort file written before the correction keeps the old labels. This script brings the sheet up to date and
rewrites the matching lock's sample_sheet_sha256, so `validate-cohort --verify-lock` still passes; the evidence records in the lock are not touched.

  relabel_cohort_provenance.py cohorts/public-v4.tsv            # report what would change
  relabel_cohort_provenance.py cohorts/public-v4.tsv --write    # rewrite the sheet and the lock hash

--check exits 1 when the sheet disagrees with classify_method (test_cohort_provenance_labels.py uses the same function). Standard library only.
"""
import argparse
import csv
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from truth_provenance import classify_method  # noqa: E402

TAB = chr(9)


def read_sheet(path):
    """(comment/header lines kept verbatim, header, rows) of a cohort sheet; the file's own line ending is returned."""
    raw = open(path, "rb").read().decode("utf-8")
    eol = "\r\n" if raw.count("\r\n") > 0.9 * raw.count("\n") else "\n"
    lines = raw.split(eol)
    trailing = lines[-1] == ""
    if trailing:
        lines = lines[:-1]
    return lines, eol, trailing


def relabel(path, write=False, quiet=False):
    lines, eol, trailing = read_sheet(path)
    header_index = next(i for i, l in enumerate(lines) if l.strip() and not l.lstrip().startswith("#"))
    header = lines[header_index].split(TAB)
    need = ("truth_assembly_strategy", "truth_polish_reads", "assembly_method", "assembly_sequencing_technology")
    if not all(c in header for c in need):
        return {"changed": 0, "rows": 0, "skipped": "the sheet has no " + "/".join(c for c in need if c not in header)}
    idx = {c: header.index(c) for c in need}
    changed, total, moves = 0, 0, {}
    for i in range(header_index + 1, len(lines)):
        if not lines[i].strip() or lines[i].lstrip().startswith("#"):
            continue
        cells = lines[i].split(TAB)
        cells += [""] * (len(header) - len(cells))
        total += 1
        method, tech = cells[idx["assembly_method"]], cells[idx["assembly_sequencing_technology"]]
        if not (method or tech):
            continue
        strategy, polish, _ = classify_method(method, tech)
        old = (cells[idx["truth_assembly_strategy"]], cells[idx["truth_polish_reads"]])
        if old != (strategy, polish):
            moves[(old, (strategy, polish))] = moves.get((old, (strategy, polish)), 0) + 1
            cells[idx["truth_assembly_strategy"]], cells[idx["truth_polish_reads"]] = strategy, polish
            lines[i] = TAB.join(cells)
            changed += 1
    if write and changed:
        text = eol.join(lines) + (eol if trailing else "")
        with open(path, "wb") as handle:
            handle.write(text.encode("utf-8"))
        lock = os.path.splitext(path)[0] + ".lock.json"
        if os.path.isfile(lock):
            record = json.load(open(lock, encoding="utf-8"))
            record["sample_sheet_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
            raw = open(lock, "rb").read().decode("utf-8")
            lock_eol = "\r\n" if raw.count("\r\n") > 0.9 * raw.count("\n") else "\n"
            # replace only the hash, so the evidence section keeps its exact bytes
            import re
            new = re.sub(r'("sample_sheet_sha256"\s*:\s*")[0-9a-f]{64}(")', lambda m: m.group(1) + record["sample_sheet_sha256"] + m.group(2), raw, count=1)
            with open(lock, "wb") as handle:
                handle.write(new.encode("utf-8"))
    if not quiet:
        for (old, new), n in sorted(moves.items(), key=lambda kv: -kv[1]):
            print(f"  {n:5d} rows: {old[0]}/{old[1]} -> {new[0]}/{new[1]}")
    return {"changed": changed, "rows": total, "moves": {f"{o[0]}/{o[1]} -> {n[0]}/{n[1]}": c for (o, n), c in moves.items()}}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sheet", nargs="+")
    ap.add_argument("--write", action="store_true", help="rewrite the sheet and the lock hash")
    ap.add_argument("--check", action="store_true", help="exit 1 when any sheet disagrees with classify_method")
    args = ap.parse_args()
    bad = 0
    for path in args.sheet:
        result = relabel(path, write=args.write)
        print(f"{path}: {result['changed']} of {result['rows']} rows " + ("rewritten" if args.write and result["changed"] else "differ" if result["changed"] else "agree")
              + (f" ({result['skipped']})" if result.get("skipped") else ""))
        bad += bool(result["changed"] and not args.write)
    return 1 if (args.check and bad) else 0


if __name__ == "__main__":
    sys.exit(main())
