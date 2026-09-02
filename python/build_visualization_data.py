#!/usr/bin/env python3
"""Create bounded, reference-coordinate data for the offline visual explorer."""
import argparse
import csv
import json
import re
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


def read_fasta(path):
    records, name, sequence = {}, None, []
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if line.startswith(">"):
                if name is not None:
                    records[name] = "".join(sequence)
                name, sequence = line[1:].split()[0], []
            elif name is not None:
                sequence.append(line)
    if name is not None:
        records[name] = "".join(sequence)
    return records


def reverse_complement(sequence):
    return sequence.translate(str.maketrans("ACGTNacgtn", "TGCANtgcan"))[::-1]


def cigar(fields):
    for field in fields[12:]:
        if field.startswith("cg:Z:"):
            return field[5:]
    return ""


def local_alignment(block, reference, prediction, max_bp):
    """Return a bounded gapped alignment only when minimap2 supplied cg:Z."""
    if not block.get("cigar") or block["block_length"] > max_bp:
        return None
    query = prediction.get(block["record_id"], "")[block["query_start"]:block["query_end"]]
    if block["strand"] == "-":
        query = reverse_complement(query)
    target = reference.get(block["target"], "")[block["target_start"]:block["target_end"]]
    if not query or not target:
        return None
    left, right, qpos, tpos = [], [], 0, 0
    for size, op in re.findall(r"(\d+)([MID=X])", block["cigar"]):
        size = int(size)
        if op in "M=X":
            left.append(target[tpos:tpos + size]); right.append(query[qpos:qpos + size]); qpos += size; tpos += size
        elif op == "I":
            left.append("-" * size); right.append(query[qpos:qpos + size]); qpos += size
        elif op == "D":
            left.append(target[tpos:tpos + size]); right.append("-" * size); tpos += size
    ref_aligned, query_aligned = "".join(left), "".join(right)
    if not ref_aligned or len(ref_aligned) != len(query_aligned):
        return None
    return {"reference": ref_aligned, "prediction": query_aligned, "displayed_bp": len(ref_aligned),
            "meaning": "CIGAR-derived local alignment; shown only for bounded retained blocks."}


def structural_metrics(blocks):
    """Conservative arrangement diagnostics, not a validated misassembly call."""
    by_record = defaultdict(list)
    for block in blocks:
        if block["molecule_type"] == "PLASMID":
            by_record[block["record_id"]].append(block)
    breakpoints = reverse = multi_target = order_conflicts = 0
    for record_blocks in by_record.values():
        ordered = sorted(record_blocks, key=lambda item: item["query_start"])
        breakpoints += max(0, len(ordered) - 1)
        reverse += sum(item["strand"] == "-" for item in ordered)
        multi_target += int(len({item["target"] for item in ordered}) > 1)
        for left, right in zip(ordered, ordered[1:]):
            if left["target"] == right["target"] and left["strand"] == right["strand"] == "+" and right["target_start"] < left["target_start"]:
                order_conflicts += 1
    penalty = breakpoints + reverse + multi_target + order_conflicts
    return {"alignment_breakpoints": breakpoints, "reverse_orientation_blocks": reverse,
            "multi_truth_target_records": multi_target, "order_conflicts": order_conflicts,
            "structural_concordance_proxy": round(1 / (1 + penalty), 6),
            "meaning": "Diagnostic proxy from retained primary PAF blocks; not a validated structural-correctness score."}


def bin_assignment_flows(sample_dir, tool):
    """Expose score-bin assignments without inventing unobserved merge edges."""
    path = sample_dir / f"{tool}.bin_matches.tsv"
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [{"bin_id": row.get("bin_id", ""), "true_plasmid": row.get("true_plasmid", ""),
                 "aligned_bp": int(row.get("aligned_bp") or 0), "status": row.get("match_status", "")}
                for row in csv.DictReader(handle, delimiter="\t")]


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


def read_features(path, truth):
    """Read optional curator-supplied contextual features with provenance."""
    if not path or not path.is_file():
        return []
    required = {"sequence_id", "start", "end", "feature_type", "label", "source", "version"}
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not required.issubset(reader.fieldnames or []):
            return []
        features = []
        for row in reader:
            sequence = row["sequence_id"]
            if sequence not in truth or truth[sequence]["molecule_type"] != "PLASMID":
                continue
            try:
                start, end = int(row["start"]), int(row["end"])
            except ValueError:
                continue
            features.append({"sequence_id": sequence, "start": max(0, start), "end": min(truth[sequence]["length"], end),
                             "feature_type": row["feature_type"], "label": row["label"], "source": row["source"], "version": row["version"]})
        return features


def read_circular(path, truth):
    if not path or not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return [row.get("sequence_id") for row in reader if row.get("sequence_id") in truth and truth[row["sequence_id"]]["molecule_type"] == "PLASMID"]


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
                         "matches": int(fields[9]), "block_length": int(fields[10]), "mapq": int(fields[11]), "cigar": cigar(fields)}
            except ValueError:
                continue
            block["molecule_type"] = truth[block["target"]]["molecule_type"]
            blocks.append(block)
    return blocks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--truth", required=True, type=Path)
    parser.add_argument("--reference", type=Path, help="Reference FASTA; enables bounded CIGAR local alignments.")
    parser.add_argument("--results-dir", required=True, type=Path)
    parser.add_argument("--sample", required=True)
    parser.add_argument("--amr-truth", type=Path)
    parser.add_argument("--feature-truth", type=Path, help="Optional curated feature TSV with source/version provenance.")
    parser.add_argument("--circular-truth", type=Path)
    parser.add_argument("--max-blocks-per-tool", type=int, default=2000)
    parser.add_argument("--max-nucleotide-bp", type=int, default=2000)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--structural-out", type=Path)
    args = parser.parse_args()
    truth = truth_records(args.truth)
    reference = read_fasta(args.reference) if args.reference and args.reference.is_file() else {}
    plasmids = {key: value for key, value in truth.items() if value["molecule_type"] == "PLASMID"}
    sample_dir = args.results_dir / args.sample
    tool_data, all_blocks = {}, []
    for paf in sorted(sample_dir.glob("*.pred_vs_ref.paf")):
        tool = paf.name.replace(".pred_vs_ref.paf", "")
        blocks = paf_blocks(paf, truth)
        retained = sorted(blocks, key=lambda row: (-row["block_length"], row["target"], row["target_start"], row["record_id"]))[:args.max_blocks_per_tool]
        prediction_path = sample_dir / f"pred_{tool}.plasmid.fasta"
        prediction = read_fasta(prediction_path) if prediction_path.is_file() else {}
        for block in retained:
            alignment = local_alignment(block, reference, prediction, args.max_nucleotide_bp)
            if alignment:
                block["local_alignment"] = alignment
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
                           "chromosome_aligned_bp": chromosome_bp, "structural_diagnostics": structural_metrics(retained)}
        tool_data[tool]["bin_assignment_flows"] = bin_assignment_flows(sample_dir, tool)
        all_blocks.extend(retained)
    payload = {"schema_version": "1.0", "sample": args.sample, "coordinate_system": "0-based half-open reference coordinates",
               "display_limit": {"max_blocks_per_tool": args.max_blocks_per_tool,
                                 "meaning": "Only the largest primary alignment blocks are displayed when the cap is exceeded."},
               "truth_plasmids": plasmids, "circular_truth_plasmids": read_circular(args.circular_truth, truth),
               "amr_features": read_amr(args.amr_truth, truth), "context_features": read_features(args.feature_truth, truth), "tools": tool_data}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    if args.structural_out:
        args.structural_out.parent.mkdir(parents=True, exist_ok=True)
        with args.structural_out.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["tool", "alignment_breakpoints", "reverse_orientation_blocks", "multi_truth_target_records", "order_conflicts", "structural_concordance_proxy", "meaning"], delimiter="\t")
            writer.writeheader()
            for tool, values in sorted(tool_data.items()):
                writer.writerow({"tool": tool, **values["structural_diagnostics"]})
    print(f"Wrote visualization data: {args.out} ({len(all_blocks)} displayed alignment blocks)")


if __name__ == "__main__":
    main()
