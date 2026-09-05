#!/usr/bin/env python3
"""Check a truth table against the reference it describes, before scoring uses it.

Stage 2 keeps a truth.tsv that already exists, which is what lets a user supply
their own. Nothing checked it, and every failure mode here is silent rather than
loud:

  * a sequence id that does not exist in the reference is scored as a plasmid
    that no tool recovered, pushing recall down for reasons that have nothing to
    do with the tools;
  * a reference sequence missing from the table is scored as neither plasmid nor
    chromosome, so real chromosomal contamination goes uncounted and precision
    goes up;
  * an unrecognised molecule_type -- including a REVIEW placeholder left behind
    by `plasbench init-local` -- is treated as CHROMOSOME, quietly turning a
    plasmid into background.

Each of those changes the leaderboard without any error appearing. Catching them
here costs milliseconds; catching them after a multi-hour run costs the run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

VALID_TYPES = {"PLASMID", "CHROMOSOME"}


def fasta_lengths(path: Path) -> dict:
    lengths: dict = {}
    seq_id = None
    total = 0
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith(">"):
                if seq_id is not None:
                    lengths[seq_id] = total
                parts = line[1:].strip().split(None, 1)
                seq_id = parts[0] if parts else ""
                total = 0
            else:
                total += len(line.strip())
    if seq_id is not None:
        lengths[seq_id] = total
    return lengths


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--sample", default="")
    ap.add_argument("--check-lengths", action="store_true",
                    help="Also require the length column to match the reference.")
    ap.add_argument("--fix", action="store_true",
                    help="Rewrite the file with surrounding whitespace trimmed and CRLF "
                         "line endings normalised. Only unambiguous repairs; never changes "
                         "a molecule_type or a sequence id.")
    args = ap.parse_args()

    truth_path, reference_path = Path(args.truth), Path(args.reference)
    label = f" for {args.sample}" if args.sample else ""

    rows = []
    with open(truth_path, "r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            fields = line.rstrip("\n").split("\t")
            if number == 1 and fields and fields[0].strip() == "sequence_id":
                continue
            rows.append((number, fields))

    problems = []
    if not rows:
        problems.append(f"{truth_path} has no data rows")

    reference = fasta_lengths(reference_path)
    if not reference:
        problems.append(f"{reference_path} has no FASTA records")

    whitespace = []
    seen = set()
    review = 0
    for number, fields in rows:
        if len(fields) < 2:
            problems.append(f"line {number}: expected at least sequence_id and molecule_type, "
                            f"tab-separated; got {len(fields)} column(s). "
                            "A space-indented file will look like this -- the separator must be a TAB.")
            continue
        raw_id, raw_molecule = fields[0], fields[1]
        seq_id, molecule = raw_id.strip(), raw_molecule.strip().upper()
        # Surrounding whitespace is not cosmetic here. This validator strips it,
        # but the pipeline does not: a sequence id of "chr1 " never matches the
        # FASTA, so tolerating it silently would report a file as sound and then
        # behave differently during the run.
        if raw_id != raw_id.strip() or raw_molecule != raw_molecule.strip():
            whitespace.append(number)
        seen.add(seq_id)
        if molecule == "REVIEW":
            review += 1
            problems.append(f"line {number}: '{seq_id}' still says REVIEW. Replace it with "
                            "PLASMID or CHROMOSOME -- PlasBench will not guess.")
        elif molecule not in VALID_TYPES:
            problems.append(f"line {number}: molecule_type '{fields[1].strip()}' for '{seq_id}' "
                            "is not PLASMID or CHROMOSOME. Anything else would be silently "
                            "scored as CHROMOSOME.")
        if seq_id not in reference:
            near = [candidate for candidate in reference if candidate.lower() == seq_id.lower()]
            hint = f" Did you mean '{near[0]}'? Ids are case-sensitive." if near else \
                   " Use the first word of the FASTA header, without '>'."
            problems.append(f"line {number}: '{seq_id}' is not in {reference_path.name}.{hint}")
        elif args.check_lengths and len(fields) >= 3 and fields[2].strip():
            try:
                declared = int(fields[2])
            except ValueError:
                problems.append(f"line {number}: length '{fields[2]}' for '{seq_id}' is not a number")
            else:
                if declared != reference[seq_id]:
                    problems.append(f"line {number}: length {declared} for '{seq_id}' does not match "
                                    f"the reference ({reference[seq_id]} bp)")

    for seq_id in reference:
        if seq_id not in seen:
            problems.append(f"'{seq_id}' is in {reference_path.name} but missing from the truth table. "
                            "Every reference sequence must be labelled, or contamination into it "
                            "goes uncounted.")

    if whitespace and args.fix:
        repaired = []
        for raw_line in truth_path.read_text(encoding="utf-8").splitlines():
            fields = raw_line.split(chr(9))
            repaired.append(chr(9).join(field.strip() for field in fields))
        truth_path.write_text(chr(10).join(repaired) + chr(10),
                              encoding="utf-8", newline=chr(10))
        print(f"fixed: trimmed whitespace on {len(whitespace)} line(s) of {truth_path}")
        print("Re-run the same command to verify the result.")
        return 0
    if whitespace:
        rows_shown = ", ".join(str(n) for n in whitespace[:6])
        more = " ..." if len(whitespace) > 6 else ""
        problems.append(
            f"line(s) {rows_shown}{more}: field(s) have leading or trailing spaces. "
            "PlasBench matches sequence ids exactly, so 'chr1 ' never matches 'chr1'. "
            f"Repair it with:  python3 python/validate_truth_table.py --truth {truth_path} "
            f"--reference {reference_path} --fix")

    if problems:
        print(f"TRUTH TABLE INVALID{label}: {truth_path}", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        if review:
            print(f"\n  Edit it with:  nano {truth_path}", file=sys.stderr)
        return 2

    plasmids = sum(1 for _, fields in rows if fields[1].strip().upper() == "PLASMID")
    print(f"truth table verified{label}: {len(rows)} sequence(s), "
          f"{plasmids} plasmid, {len(rows) - plasmids} chromosome")
    return 0


if __name__ == "__main__":
    sys.exit(main())
