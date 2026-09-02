#!/usr/bin/env python3
"""Derive replicon, MOB, IS, and AMR annotations for a reference by calling
installed annotation tools, so context features stop depending on hand curation.

Design
------
PlasBench does not reimplement annotation. It shells out to whichever callers
are installed, normalises their output into one feature table, and records the
tool and database version behind every feature. A caller that is absent is
reported as `not_evaluated` for its feature class -- never as an absence of the
feature, which would silently understate recovery.

Supported callers (all optional):
  mob_typer     replicon and relaxase/MOB typing        -> replicon, mob
  abricate      AMR / plasmid-replicon databases        -> amr, replicon
  amrfinder     NCBI AMRFinderPlus                      -> amr
  isescan       insertion sequences                     -> insertion_sequence

Output is the `feature_truth` TSV the visualization already consumes:
sequence_id, start, end, feature_type, label, source, version
Coordinates are 0-based half-open on the reference, matching the scorer.

Standard library only; the callers themselves are external.
"""

import argparse
import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path


FIELDS = ("sequence_id", "start", "end", "feature_type", "label", "source", "version")
CALLERS = ("mob_typer", "abricate", "amrfinder", "isescan")


def tool_version(executable, flags=("--version", "-v", "version")):
    for flag in flags:
        try:
            result = subprocess.run([executable, flag], text=True, capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            continue
        output = (result.stdout or result.stderr).strip().splitlines()
        if output:
            return output[0].strip()
    return "unreported"


def run(command, timeout):
    """Return stdout, or None when the caller fails; never raise into the run."""
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"{command[0]} did not complete: {exc}"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        return None, f"{command[0]} exited {result.returncode}: {detail[0] if detail else 'no output'}"
    return result.stdout, ""


def parse_tabular(text, mapping, feature_type, source, version, sequence_filter=None):
    """Normalise a headed TSV into feature rows using a column mapping."""
    features = []
    reader = csv.DictReader(text.splitlines(), delimiter="\t")
    for row in reader:
        try:
            sequence = (row.get(mapping["sequence"]) or "").split()[0]
            start = int(float(row.get(mapping["start"]) or 0))
            end = int(float(row.get(mapping["end"]) or 0))
        except (ValueError, IndexError):
            continue
        if not sequence or end <= start:
            continue
        if sequence_filter and sequence not in sequence_filter:
            continue
        label = (row.get(mapping["label"]) or "").strip() or feature_type
        # Callers report 1-based inclusive coordinates; the scorer is 0-based half-open.
        features.append({"sequence_id": sequence, "start": max(0, start - 1), "end": end,
                         "feature_type": feature_type, "label": label,
                         "source": source, "version": version})
    return features


def call_abricate(reference, database, timeout, sequences):
    executable = shutil.which("abricate")
    if not executable:
        return [], {"status": "not_evaluated", "reason": "abricate is not installed"}
    version = tool_version(executable)
    text, error = run([executable, "--nopath", "--db", database, str(reference)], timeout)
    if text is None:
        return [], {"status": "failed", "reason": error, "version": version}
    kind = "replicon" if database in ("plasmidfinder", "PlasmidFinder") else "amr"
    features = parse_tabular(text, {"sequence": "SEQUENCE", "start": "START", "end": "END",
                                    "label": "GENE"}, kind, f"abricate:{database}", version, sequences)
    return features, {"status": "ok", "version": version, "database": database, "features": len(features)}


def call_amrfinder(reference, timeout, sequences):
    executable = shutil.which("amrfinder")
    if not executable:
        return [], {"status": "not_evaluated", "reason": "amrfinder is not installed"}
    version = tool_version(executable)
    text, error = run([executable, "-n", str(reference)], timeout)
    if text is None:
        return [], {"status": "failed", "reason": error, "version": version}
    features = parse_tabular(text, {"sequence": "Contig id", "start": "Start", "end": "Stop",
                                    "label": "Element symbol"}, "amr", "amrfinderplus", version, sequences)
    if not features:
        # AMRFinderPlus renamed these columns between releases.
        features = parse_tabular(text, {"sequence": "Contig id", "start": "Start", "end": "Stop",
                                        "label": "Gene symbol"}, "amr", "amrfinderplus", version, sequences)
    return features, {"status": "ok", "version": version, "features": len(features)}


def call_isescan(reference, timeout, sequences, workdir):
    executable = shutil.which("isescan.py") or shutil.which("isescan")
    if not executable:
        return [], {"status": "not_evaluated", "reason": "isescan is not installed"}
    version = tool_version(executable)
    _, error = run([executable, "--seqfile", str(reference), "--output", str(workdir), "--nthread", "1"], timeout)
    if error:
        return [], {"status": "failed", "reason": error, "version": version}
    features = []
    for path in Path(workdir).rglob("*.csv"):
        features.extend(parse_tabular(path.read_text(encoding="utf-8").replace(",", "\t"),
                                      {"sequence": "seqID", "start": "isBegin", "end": "isEnd",
                                       "label": "family"}, "insertion_sequence", "isescan",
                                      version, sequences))
    return features, {"status": "ok", "version": version, "features": len(features)}


def call_mob_typer(reference, timeout, sequences):
    """MOB-typer reports per-sequence typing, not coordinates."""
    executable = shutil.which("mob_typer")
    if not executable:
        return [], {"status": "not_evaluated", "reason": "mob_typer is not installed"}
    version = tool_version(executable)
    out = Path(reference).with_suffix(".mobtyper.txt")
    text, error = run([executable, "--multi", "--infile", str(reference), "--out_file", str(out)], timeout)
    if text is None and not out.is_file():
        return [], {"status": "failed", "reason": error, "version": version}
    if not out.is_file():
        return [], {"status": "failed", "reason": "mob_typer produced no report", "version": version}
    features = []
    with out.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            sequence = (row.get("sample_id") or "").split()[0]
            if not sequence or (sequences and sequence not in sequences):
                continue
            length = sequences.get(sequence) if sequences else None
            for column, kind in (("rep_type(s)", "replicon"), ("relaxase_type(s)", "mob")):
                for label in (row.get(column) or "").split(","):
                    label = label.strip()
                    if label and label != "-":
                        # Typing is per-replicon, so the feature spans the sequence.
                        features.append({"sequence_id": sequence, "start": 0, "end": length or 1,
                                         "feature_type": kind, "label": label,
                                         "source": "mob_typer", "version": version})
    return features, {"status": "ok", "version": version, "features": len(features),
                      "note": "MOB-typer types whole replicons; features span the sequence."}


def reference_sequences(path):
    lengths, name, total = {}, None, 0
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.startswith(">"):
                if name:
                    lengths[name] = total
                name, total = line[1:].strip().split()[0], 0
            else:
                total += len(line.strip())
    if name:
        lengths[name] = total
    return lengths


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path, help="feature_truth TSV")
    parser.add_argument("--provenance", type=Path, help="JSON record of caller status and versions")
    parser.add_argument("--amr-database", default="ncbi", help="abricate AMR database (default: ncbi)")
    parser.add_argument("--replicon-database", default="plasmidfinder")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--workdir", type=Path)
    args = parser.parse_args()
    if not args.reference.is_file():
        raise SystemExit(f"ERROR: reference not found: {args.reference}")

    sequences = reference_sequences(args.reference)
    workdir = args.workdir or args.out.parent / "annotation_work"
    workdir.mkdir(parents=True, exist_ok=True)

    features, provenance = [], {}
    for name, call in (
        ("mob_typer", lambda: call_mob_typer(args.reference, args.timeout, sequences)),
        ("abricate_amr", lambda: call_abricate(args.reference, args.amr_database, args.timeout, sequences)),
        ("abricate_replicon", lambda: call_abricate(args.reference, args.replicon_database, args.timeout, sequences)),
        ("amrfinder", lambda: call_amrfinder(args.reference, args.timeout, sequences)),
        ("isescan", lambda: call_isescan(args.reference, args.timeout, sequences, workdir)),
    ):
        found, status = call()
        features.extend(found)
        provenance[name] = status

    # Deduplicate identical calls from overlapping databases, keeping provenance.
    seen, unique = set(), []
    for feature in sorted(features, key=lambda f: (f["sequence_id"], f["start"], f["end"],
                                                   f["feature_type"], f["label"], f["source"])):
        key = (feature["sequence_id"], feature["start"], feature["end"],
               feature["feature_type"], feature["label"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(feature)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(unique)

    evaluated = [name for name, status in provenance.items() if status.get("status") == "ok"]
    missing = [name for name, status in provenance.items() if status.get("status") == "not_evaluated"]
    record = {"schema_version": "1.0", "reference": str(args.reference),
              "features_written": len(unique), "callers": provenance,
              "feature_classes_not_evaluated": missing,
              "meaning": ("Absent callers yield 'not evaluated' for their feature class. "
                          "A missing feature class is not evidence that the feature is absent.")}
    if args.provenance:
        args.provenance.parent.mkdir(parents=True, exist_ok=True)
        args.provenance.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Annotated {args.reference.name}: {len(unique)} feature(s); "
          f"ran {', '.join(evaluated) or 'no caller'}; not evaluated: {', '.join(missing) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
