#!/usr/bin/env python3
"""Create bounded, reference-coordinate data for the offline visual explorer."""
import argparse
import json
from collections import defaultdict
from pathlib import Path


def truth_records(path):
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


def merge(intervals):
    merged = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return merged


def read_amr(path, truth):
    if not path or not path.is_file():
        return []
    features = []
    with path.open(encoding="utf-8") as handle:
        header = handle.readline().rstrip("\n").split("\t")
        required = {"sequence_id", "start", "end"}
        if not required.issubset(header):
            return []
        index = {key: header.index(key) for key in required}
        name_index = header.index("gene_name") if "gene_name" in header else None
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            sequence = fields[index["sequence_id"]]
            if sequence in truth and truth[sequence]["molecule_type"] == "PLASMID":
                features.append({"sequence_id": sequence, "start": int(fields[index["start"]]), "end": int(fields[index["end"]]),
                                 "label": fields[name_index] if name_index is not None else "AMR gene"})
    return features


def paf_blocks(path, truth):
    blocks = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 12 or fields[5] not in truth:
                continue
            try:
                block = {"record_id": fields[0], "query_length": int(fields[1]), "query_start": int(fields[2]), "query_end": int(fields[3]),
                         "strand": fields[4], "target": fields[5], "target_start": int(fields[7]), "target_end": int(fields[8]),
                         "matches": int(fields[9]), "block_length": int(fields[10]), "mapq": int(fields[11])}
            except ValueError:
                continue
            block["molecule_type"] = truth[block["target"]]["molecule_type"]
            blocks.append(block)
    return blocks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--truth", required=True, type=Path)
    parser.add_argument("--results-dir", required=True, type=Path)
    parser.add_argument("--sample", required=True)
    parser.add_argument("--amr-truth", type=Path)
    parser.add_argument("--max-blocks-per-tool", type=int, default=2000)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    truth = truth_records(args.truth)
    plasmids = {key: value for key, value in truth.items() if value["molecule_type"] == "PLASMID"}
    sample_dir = args.results_dir / args.sample
    tool_data, all_blocks = {}, []
    for paf in sorted(sample_dir.glob("*.pred_vs_ref.paf")):
        tool = paf.name.replace(".pred_vs_ref.paf", "")
        blocks = paf_blocks(paf, truth)
        retained = sorted(blocks, key=lambda row: (-row["block_length"], row["target"], row["target_start"], row["record_id"]))[:args.max_blocks_per_tool]
        truncated = max(0, len(blocks) - len(retained))
        coverage = defaultdict(list)
        for block in retained:
            if block["molecule_type"] == "PLASMID":
                coverage[block["target"]].append((block["target_start"], block["target_end"]))
        recovery = {plasmid: {"covered_intervals": merge(coverage[plasmid]),
                               "covered_bp": sum(end - start for start, end in merge(coverage[plasmid])),
                               "completeness": round(sum(end - start for start, end in merge(coverage[plasmid])) / details["length"], 6)}
                    for plasmid, details in plasmids.items()}
        chromosome_bp = sum(max(0, block["target_end"] - block["target_start"]) for block in retained if block["molecule_type"] == "CHROMOSOME")
        tool_data[tool] = {"blocks": retained, "blocks_omitted": truncated, "plasmid_recovery": recovery,
                           "chromosome_aligned_bp": chromosome_bp}
        all_blocks.extend(retained)
    payload = {"schema_version": "1.0", "sample": args.sample, "coordinate_system": "0-based half-open reference coordinates",
               "display_limit": {"max_blocks_per_tool": args.max_blocks_per_tool,
                                 "meaning": "Only the largest primary alignment blocks are displayed when the cap is exceeded."},
               "truth_plasmids": plasmids, "amr_features": read_amr(args.amr_truth, truth), "tools": tool_data}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Wrote visualization data: {args.out} ({len(all_blocks)} displayed alignment blocks)")


if __name__ == "__main__":
    main()
