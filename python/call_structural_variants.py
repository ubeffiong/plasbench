#!/usr/bin/env python3
"""Call structural discordances between predicted records and truth replicons.

This replaces a penalty proxy with typed, evidence-bearing calls derived from
the arrangement of alignment blocks along each predicted record.

Scope and honesty
-----------------
These are *alignment-derived calls*, not validated misassembly calls. A call
states that the predicted record's arrangement disagrees with the reference
under the stated thresholds. It does not establish which of the two is wrong:
a genuine biological rearrangement in the isolate, a reference error, and a
tool misassembly all produce the same alignment signature. Confirming a
misassembly requires evidence this module does not have -- read or graph
support spanning the junction -- so every call carries `validated: false` and
records the thresholds that produced it.

Event types
-----------
inter_replicon_junction  adjacent blocks of one record align to different truth
                         replicons: a chimeric contig joining separate molecules
inversion_junction       adjacent blocks flip alignment orientation
relocation               adjacent blocks keep orientation but reverse order on
                         the reference beyond the tolerance
reference_deletion       reference advances far more than the query
reference_insertion      query advances far more than the reference
tandem_duplication       one record covers the same reference interval twice

Collinearity
------------
`collinear_fraction` is the share of a record's aligned bases lying in its
longest strictly collinear chain of blocks. Unlike a 1/(1+penalty) score it has
units, a defensible meaning, and degrades smoothly.

Standard library only.
"""

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


DEFAULTS = {
    "min_block_length": 200,
    "min_mapq": 10,
    "indel_tolerance": 100,
    "min_event_bp": 200,
    "min_duplication_overlap": 200,
}


def truth_lengths(path):
    records = {}
    with open(path, encoding="utf-8") as handle:
        header = handle.readline().rstrip("\n").split("\t")
        index = {name: header.index(name) for name in ("sequence_id", "molecule_type", "length")}
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            records[fields[index["sequence_id"]]] = {
                "molecule_type": fields[index["molecule_type"]].upper(),
                "length": int(fields[index["length"]]),
            }
    return records


def read_paf(path, truth, thresholds):
    """Retain primary, confidently-mapped blocks against labelled references."""
    blocks = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 12 or fields[5] not in truth:
                continue
            try:
                block = {
                    "record_id": fields[0], "query_length": int(fields[1]),
                    "query_start": int(fields[2]), "query_end": int(fields[3]),
                    "strand": fields[4], "target": fields[5],
                    "target_start": int(fields[7]), "target_end": int(fields[8]),
                    "matches": int(fields[9]), "block_length": int(fields[10]),
                    "mapq": int(fields[11]),
                }
            except ValueError:
                continue
            if block["block_length"] < thresholds["min_block_length"]:
                continue
            if block["mapq"] < thresholds["min_mapq"]:
                continue
            block["molecule_type"] = truth[block["target"]]["molecule_type"]
            blocks.append(block)
    return blocks


def longest_collinear_run(blocks):
    """Longest chain of blocks that advances on both query and reference."""
    if not blocks:
        return 0
    best = current = blocks[0]["block_length"]
    for left, right in zip(blocks, blocks[1:]):
        collinear = (
            left["target"] == right["target"]
            and left["strand"] == right["strand"]
            and (right["target_start"] >= left["target_start"] if right["strand"] == "+"
                 else right["target_start"] <= left["target_start"])
        )
        current = current + right["block_length"] if collinear else right["block_length"]
        best = max(best, current)
    return best


def call_record(record_id, blocks, thresholds):
    """Classify adjacent-block discordances along one predicted record."""
    ordered = sorted(blocks, key=lambda item: (item["query_start"], item["query_end"]))
    events = []

    def add(kind, left, right, span, detail):
        events.append({
            "record_id": record_id, "event_type": kind, "span_bp": int(span),
            "query_start": left["query_end"], "query_end": right["query_start"],
            "left_target": left["target"], "left_target_end": left["target_end"],
            "right_target": right["target"], "right_target_start": right["target_start"],
            "left_strand": left["strand"], "right_strand": right["strand"],
            "min_mapq": min(left["mapq"], right["mapq"]), "detail": detail,
            "validated": False,
        })

    for left, right in zip(ordered, ordered[1:]):
        if left["target"] != right["target"]:
            add("inter_replicon_junction", left, right, right["block_length"],
                f"record joins {left['target']} and {right['target']}")
            continue
        if left["strand"] != right["strand"]:
            add("inversion_junction", left, right, right["block_length"],
                "alignment orientation flips within one record")
            continue
        query_gap = right["query_start"] - left["query_end"]
        target_gap = (right["target_start"] - left["target_end"] if left["strand"] == "+"
                      else left["target_start"] - right["target_end"])
        if target_gap < -thresholds["indel_tolerance"]:
            overlap = -target_gap
            if overlap >= thresholds["min_duplication_overlap"]:
                add("tandem_duplication", left, right, overlap,
                    f"reference interval covered twice by one record ({overlap} bp)")
            else:
                add("relocation", left, right, overlap, "reference order reverses between blocks")
            continue
        drift = target_gap - query_gap
        if drift >= max(thresholds["min_event_bp"], thresholds["indel_tolerance"]):
            add("reference_deletion", left, right, drift,
                f"reference advances {drift} bp more than the predicted record")
        elif -drift >= max(thresholds["min_event_bp"], thresholds["indel_tolerance"]):
            add("reference_insertion", left, right, -drift,
                f"predicted record advances {-drift} bp more than the reference")
    return events


def summarise(blocks, events, thresholds):
    aligned = sum(block["block_length"] for block in blocks)
    by_record = defaultdict(list)
    for block in blocks:
        by_record[block["record_id"]].append(block)
    collinear = sum(longest_collinear_run(sorted(items, key=lambda x: x["query_start"]))
                    for items in by_record.values())
    counts = defaultdict(int)
    for event in events:
        counts[event["event_type"]] += 1
    return {
        "aligned_bp": aligned,
        "collinear_bp": collinear,
        "collinear_fraction": round(collinear / aligned, 6) if aligned else 0.0,
        "records": len(by_record),
        "events_total": len(events),
        **{key: counts.get(key, 0) for key in (
            "inter_replicon_junction", "inversion_junction", "relocation",
            "reference_deletion", "reference_insertion", "tandem_duplication")},
        "validated": False,
        "meaning": ("Alignment-derived structural discordance between prediction and reference. "
                    "It does not distinguish tool misassembly from genuine biological "
                    "rearrangement or reference error, and is not read- or graph-validated."),
        "thresholds": dict(thresholds),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--truth", required=True, type=Path)
    parser.add_argument("--results-dir", required=True, type=Path)
    parser.add_argument("--sample", required=True)
    parser.add_argument("--events-out", required=True, type=Path)
    parser.add_argument("--summary-out", required=True, type=Path)
    parser.add_argument("--json-out", type=Path, help="Optional payload for the HTML explorer.")
    for key, value in DEFAULTS.items():
        parser.add_argument(f"--{key.replace('_', '-')}", type=int, default=value)
    args = parser.parse_args()
    thresholds = {key: getattr(args, key) for key in DEFAULTS}

    truth = truth_lengths(args.truth)
    sample_dir = args.results_dir / args.sample
    all_events, summaries, payload = [], [], {}
    for paf in sorted(sample_dir.glob("*.pred_vs_ref.paf")):
        tool = paf.name.replace(".pred_vs_ref.paf", "")
        blocks = read_paf(paf, truth, thresholds)
        by_record = defaultdict(list)
        for block in blocks:
            by_record[block["record_id"]].append(block)
        events = []
        for record_id, items in sorted(by_record.items()):
            events.extend(call_record(record_id, items, thresholds))
        for event in events:
            all_events.append({"tool": tool, **event})
        summary = summarise(blocks, events, thresholds)
        summaries.append({"tool": tool, **{k: v for k, v in summary.items()
                                           if k not in ("thresholds",)}})
        payload[tool] = {"summary": summary, "events": events}

    args.events_out.parent.mkdir(parents=True, exist_ok=True)
    event_fields = ["tool", "record_id", "event_type", "span_bp", "query_start", "query_end",
                    "left_target", "left_target_end", "right_target", "right_target_start",
                    "left_strand", "right_strand", "min_mapq", "validated", "detail"]
    with args.events_out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=event_fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_events)
    summary_fields = ["tool", "aligned_bp", "collinear_bp", "collinear_fraction", "records",
                      "events_total", "inter_replicon_junction", "inversion_junction", "relocation",
                      "reference_deletion", "reference_insertion", "tandem_duplication",
                      "validated", "meaning"]
    args.summary_out.parent.mkdir(parents=True, exist_ok=True)
    with args.summary_out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=summary_fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(summaries)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(
            {"schema_version": "1.0", "sample": args.sample, "thresholds": thresholds,
             "validated": False, "tools": payload}, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Structural calls for {args.sample}: {len(all_events)} event(s) across {len(summaries)} tool(s)")


if __name__ == "__main__":
    main()
