#!/usr/bin/env python3
"""
label_schemes.py -- every truth replicon's label under the three labelling
schemes, and the truth file each scheme scores against.

The pre-registered primary scheme is Scheme 3, NCBI/database labels
(docs/PANEL_ALIGNMENT.md, decision E.15). The other two are sensitivity
analyses (python/rank_sensitivity.py re-ranks under each):

  ncbi            Scheme 3, primary. The label in truth.tsv as built by
                  make_truth.py from the NCBI sequence report, field
                  `assigned_molecule_location_type` (pinned below with the
                  report's SHA-256 and retrieval date). Scored file: truth.tsv.
  nonchromosomal  Scheme 1. The largest CHROMOSOME-labelled replicon stays
                  CHROMOSOME; every other replicon, including secondary
                  chromosomes and chromids, is PLASMID.
                  Scored file: truth.nonchromosomal.tsv.
  evidence        Scheme 2. label_truth_evidence.py's evidence-based labels;
                  AMBIGUOUS replicons (chromid-like, marker-free, rRNA-bearing,
                  short-read-only, multimeric) are excluded.
                  Scored file: truth.scored.tsv.

Rule for isolates without an NCBI record (local or in-house isolates, and
self_assembled_hybrid truth): Scheme 3 uses the label written by the truth
builder (build_hybrid_truth.py: circular and below the chromosome-length floor
=> PLASMID) or by the person who supplied truth.tsv. Such rows record
ncbi_label_field = not_applicable:<truth_source>, so a reader can separate them,
and they are never described as database-labelled.

Subcommands:
  build    one sample: write truth.nonchromosomal.tsv and label_schemes.tsv
  collect  all samples: concatenate into benchmark.label_schemes.tsv and write
           a per-scheme summary

Standard library only.
"""

import argparse
import csv
import datetime
import hashlib
import os
import sys
from pathlib import Path

SCHEMES = ("ncbi", "nonchromosomal", "evidence")
PRIMARY_SCHEME = "ncbi"
SCHEME_TRUTH_FILES = {"ncbi": "truth.tsv", "nonchromosomal": "truth.nonchromosomal.tsv",
                      "evidence": "truth.scored.tsv"}
NCBI_LABEL_FIELD = "assigned_molecule_location_type"
FIELDS = ["sample", "sequence_id", "length", "ncbi_label", "nonchromosomal_label", "evidence_label",
          "evidence_reason", "multimer", "schemes_agree", "ncbi_label_field", "ncbi_report_sha256",
          "ncbi_report_retrieved"]
SUMMARY_FIELDS = ["scheme", "role", "samples", "replicons", "plasmids", "plasmid_bp", "excluded_replicons",
                  "plasmids_differing_from_primary", "scored_file"]


def read_tsv(path):
    if not path or not os.path.isfile(path) or os.path.getsize(path) == 0:
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def truth_file_for(scheme):
    """The per-sample truth file a scheme scores against."""
    if scheme not in SCHEMES:
        raise ValueError(f"unknown TRUTH_LABEL_SCHEME '{scheme}' (expected one of {', '.join(SCHEMES)})")
    return SCHEME_TRUTH_FILES[scheme]


def nonchromosomal_labels(rows):
    """Scheme 1: the largest CHROMOSOME stays CHROMOSOME, everything else is PLASMID.
    With no CHROMOSOME-labelled row the largest replicon is taken as the chromosome."""
    chromosomes = [r for r in rows if (r.get("molecule_type") or "").upper() == "CHROMOSOME"]
    pool = chromosomes or rows
    if not pool:
        return {}
    main = max(pool, key=lambda r: (int(r.get("length") or 0), r["sequence_id"]))["sequence_id"]
    return {r["sequence_id"]: "CHROMOSOME" if r["sequence_id"] == main else "PLASMID" for r in rows}


def report_pin(report):
    """(sha256, retrieval date) of the NCBI sequence report, or blanks."""
    if not report or not os.path.isfile(report):
        return "", ""
    digest = hashlib.sha256()
    with open(report, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    retrieved = datetime.datetime.fromtimestamp(os.path.getmtime(report), datetime.timezone.utc).date().isoformat()
    return digest.hexdigest(), retrieved


def build(args):
    truth = read_tsv(args.truth)
    if not truth:
        raise SystemExit(f"ERROR: no rows in {args.truth}")
    evidence = {r["sequence_id"]: r for r in read_tsv(args.evidence_labels)}
    # detect_dimers.py truth.corrections.tsv: action "collapsed" (scored as the
    # monomer) or "flagged" (left as the dimer; AMBIGUOUS under the evidence scheme).
    multimers = {r["sequence_id"]: r.get("action") or "flagged" for r in read_tsv(args.multimers)
                 if (r.get("multimer") or "") == "yes"}
    scheme1 = nonchromosomal_labels(truth)
    sha, retrieved = report_pin(args.report)
    has_report = bool(sha)
    field = NCBI_LABEL_FIELD if has_report else f"not_applicable:{args.truth_source or 'supplied_truth'}"

    with open(args.nonchromosomal_out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["sequence_id", "molecule_type", "length"])
        for row in truth:
            writer.writerow([row["sequence_id"], scheme1[row["sequence_id"]], row["length"]])

    out = []
    for row in truth:
        sid = row["sequence_id"]
        ncbi = (row.get("molecule_type") or "").upper()
        ev = evidence.get(sid)
        ev_label = (ev.get("final_label") or "") if ev else "not_evaluated"
        labels = {ncbi, scheme1[sid]} | ({ev_label} if ev else set())
        out.append({
            "sample": args.sample, "sequence_id": sid, "length": row.get("length", ""),
            "ncbi_label": ncbi, "nonchromosomal_label": scheme1[sid], "evidence_label": ev_label,
            "evidence_reason": (ev.get("reason") or "") if ev else "",
            "multimer": multimers.get(sid, "no"),
            "schemes_agree": "yes" if len(labels) == 1 else "no",
            "ncbi_label_field": field, "ncbi_report_sha256": sha, "ncbi_report_retrieved": retrieved,
        })
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(out)
    differing = sum(r["schemes_agree"] == "no" for r in out)
    sys.stderr.write(f"[label_schemes] {args.sample}: {len(out)} replicon(s), {differing} labelled "
                     f"differently across schemes\n")


def summarise(rows, primary=PRIMARY_SCHEME):
    """One row per scheme: replicons and plasmid bp it scores, and how many
    plasmid calls differ from the primary scheme."""
    column = {"ncbi": "ncbi_label", "nonchromosomal": "nonchromosomal_label", "evidence": "evidence_label"}
    out = []
    for scheme in SCHEMES:
        col = column[scheme]
        usable = [r for r in rows if r.get(col) in ("PLASMID", "CHROMOSOME")]
        if scheme == "evidence" and not usable:
            continue
        plasmids = [r for r in usable if r[col] == "PLASMID"]
        primary_col = column[primary]
        differing = sum((r.get(col) == "PLASMID") != (r.get(primary_col) == "PLASMID")
                        for r in rows if r.get(col) in ("PLASMID", "CHROMOSOME", "AMBIGUOUS"))
        out.append({
            "scheme": scheme, "role": "primary" if scheme == primary else "sensitivity",
            "samples": len({r["sample"] for r in usable}), "replicons": len(usable),
            "plasmids": len(plasmids), "plasmid_bp": sum(int(r.get("length") or 0) for r in plasmids),
            "excluded_replicons": sum(r.get(col) == "AMBIGUOUS" for r in rows),
            "plasmids_differing_from_primary": differing if scheme != primary else 0,
            "scored_file": SCHEME_TRUTH_FILES[scheme],
        })
    return out


def collect(args):
    rows = []
    for path in sorted(Path(args.data_dir).glob("*/label_schemes.tsv")):
        rows.extend(read_tsv(str(path)))
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n",
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    summary = summarise(rows, args.primary)
    if args.summary_out:
        with open(args.summary_out, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(summary)
    sys.stderr.write(f"[label_schemes] {len(rows)} replicon(s) from "
                     f"{len({r['sample'] for r in rows})} sample(s) -> {args.out}\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="one sample")
    b.add_argument("--sample", required=True)
    b.add_argument("--truth", required=True, help="truth.tsv (Scheme 3 labels)")
    b.add_argument("--report", help="NCBI sequence_report.jsonl the labels came from (pinned by SHA-256)")
    b.add_argument("--truth-source", default="", help="samples.tsv truth_source, for isolates without a report")
    b.add_argument("--evidence-labels", help="label_truth_evidence.py truth_labels.tsv")
    b.add_argument("--multimers", help="detect_dimers.py truth.corrections.tsv")
    b.add_argument("--nonchromosomal-out", required=True)
    b.add_argument("--out", required=True)
    c = sub.add_parser("collect", help="all samples")
    c.add_argument("--data-dir", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--summary-out")
    c.add_argument("--primary", default=PRIMARY_SCHEME, choices=SCHEMES)
    t = sub.add_parser("truth-file", help="print the truth filename a scheme scores against")
    t.add_argument("scheme")
    args = ap.parse_args()
    if args.command == "build":
        build(args)
    elif args.command == "collect":
        collect(args)
    else:
        try:
            print(truth_file_for(args.scheme))
        except ValueError as exc:
            raise SystemExit(f"ERROR: {exc}")


if __name__ == "__main__":
    main()
