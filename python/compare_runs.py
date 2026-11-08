#!/usr/bin/env python3
"""Reproducibility: do repeated runs of the same benchmark give the same answer?

A benchmark that cannot reproduce itself cannot be trusted, and nondeterministic tools
(random seeds, thread-order effects in assemblers) are common. Give this script two or more
results directories from repeated runs of the same cohort and it reports, per (sample, tool):

  identical_scores        the F1, precision and recall are equal across the runs
  f1_range / f1_sd        spread of F1 across the runs
  identical_predictions   the predicted-plasmid FASTA has the same records and sequences in
                          every run (blank when a run has no FASTA to compare)

and per tool the share of (sample, tool) pairs that reproduced exactly and the largest F1 range
seen, with a verdict: `reproducible` (everything identical), `score_stable` (scores identical
within --tolerance but the sequences differ) or `variable`. A pair present in only some runs is
reported as `incomplete`, never silently dropped. With a single run nothing can be concluded and
the script says so.

Each run directory holds scores.tsv and, optionally, <sample>/pred_<tool>.plasmid.fasta. Output
is descriptive and never changes any ranking. Standard library only.
"""
import argparse
import csv
import hashlib
import os
import statistics
import sys
from collections import defaultdict
from plasbench_common import number  # noqa: E402

PAIR_FIELDS = ("analysis_track", "sample", "tool", "n_runs", "identical_scores", "f1_min", "f1_max", "f1_range",
               "f1_sd", "identical_predictions", "status")
TOOL_FIELDS = ("analysis_track", "tool", "n_pairs", "n_incomplete", "fraction_identical_scores",
               "fraction_identical_predictions", "max_f1_range", "verdict")
METRICS = ("f1", "precision", "recall")


def read_scores(run_dir):
    path = os.path.join(run_dir, "scores.tsv")
    rows = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            rows[(row.get("analysis_track") or "short_read", row["sample"], row["tool"])] = row
    return rows


def fasta_digest(run_dir, sample, tool):
    """Digest of the set of (record id, sequence) pairs, order-insensitive; None if absent."""
    path = os.path.join(run_dir, sample, f"pred_{tool}.plasmid.fasta")
    if not os.path.isfile(path):
        return None
    records, name, seq = [], None, []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.startswith(">"):
                if name is not None:
                    records.append((name, "".join(seq).upper()))
                name, seq = line[1:].split()[0] if line[1:].split() else "", []
            else:
                seq.append(line.strip())
    if name is not None:
        records.append((name, "".join(seq).upper()))
    digest = hashlib.sha256()
    for record in sorted(records):
        digest.update(repr(record).encode())
    return digest.hexdigest()


def compare(runs, tolerance):
    scores = [read_scores(r) for r in runs]
    keys = set().union(*[set(s) for s in scores])
    pairs = []
    for key in sorted(keys):
        track, sample, tool = key
        present = [s[key] for s in scores if key in s]
        row = {"analysis_track": track, "sample": sample, "tool": tool, "n_runs": len(present)}
        if len(present) < len(runs):
            row["status"] = "incomplete"
            pairs.append(row)
            continue
        same = True
        for metric in METRICS:
            values = [number(r.get(metric)) for r in present]
            if any(v is None for v in values):
                same &= all(v is None for v in values)
            else:
                same &= (max(values) - min(values)) <= tolerance
        f1 = [v for v in (number(r.get("f1")) for r in present) if v is not None]
        row["identical_scores"] = "true" if same else "false"
        if f1:
            row.update(f1_min=min(f1), f1_max=max(f1), f1_range=max(f1) - min(f1),
                       f1_sd=statistics.pstdev(f1) if len(f1) > 1 else 0.0)
        digests = [fasta_digest(r, sample, tool) for r in runs]
        if all(d is not None for d in digests):
            row["identical_predictions"] = "true" if len(set(digests)) == 1 else "false"
        row["status"] = "identical" if same and row.get("identical_predictions", "true") == "true" else (
            "score_stable" if same else "variable")
        pairs.append(row)
    return pairs


def summarise(pairs):
    grouped = defaultdict(list)
    for p in pairs:
        grouped[(p["analysis_track"], p["tool"])].append(p)
    rows = []
    for (track, tool), items in sorted(grouped.items()):
        complete = [p for p in items if p["status"] != "incomplete"]
        row = {"analysis_track": track, "tool": tool, "n_pairs": len(complete),
               "n_incomplete": len(items) - len(complete)}
        if complete:
            row["fraction_identical_scores"] = sum(p["identical_scores"] == "true" for p in complete) / len(complete)
            preds = [p for p in complete if p.get("identical_predictions")]
            if preds:
                row["fraction_identical_predictions"] = sum(p["identical_predictions"] == "true" for p in preds) / len(preds)
            ranges = [p["f1_range"] for p in complete if p.get("f1_range") is not None]
            row["max_f1_range"] = max(ranges) if ranges else None
            statuses = {p["status"] for p in complete}
            row["verdict"] = ("reproducible" if statuses == {"identical"} else
                              "score_stable" if "variable" not in statuses else "variable")
        rows.append(row)
    return rows


def fmt(value):
    return "" if value is None else (f"{value:.6f}" if isinstance(value, float) else str(value))


def write(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: fmt(row.get(k)) for k in fields})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="append", required=True, help="results directory of one run; give at least two")
    ap.add_argument("--out", required=True, help="per (sample, tool) table")
    ap.add_argument("--tool-out", required=True, help="per tool table")
    ap.add_argument("--tolerance", type=float, default=0.0, help="largest score difference still called identical")
    args = ap.parse_args()
    if len(args.run) < 2:
        raise SystemExit("ERROR: reproducibility needs at least two runs (--run DIR --run DIR); one run proves nothing")
    pairs = compare(args.run, args.tolerance)
    write(args.out, PAIR_FIELDS, pairs)
    tools = summarise(pairs)
    write(args.tool_out, TOOL_FIELDS, tools)
    for row in tools:
        sys.stderr.write(f"[compare_runs] {row['tool']}: {row.get('verdict', 'no complete pairs')}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
