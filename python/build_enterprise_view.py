#!/usr/bin/env python3
"""Map measured PlasBench results into the enterprise dashboard's data model.

The dashboard layout, styling, and interactions are vendored verbatim in
`assets/enterprise/template.html`. Upstream, that prototype generated its own
numbers with Math.random(); this module replaces that generator with measured
results and nothing else. Where a value was never measured the field is emitted
as null so the view can say "not measured" rather than display a plausible
number that no run produced.

Standard library only.
"""

import csv
import json
from collections import defaultdict
from pathlib import Path


STATUSES = ["completed", "reused", "warning", "failed", "skipped"]


def read_tsv(path):
    if not Path(path).is_file():
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def number(value, scale=1.0):
    try:
        return float(value) * scale
    except (TypeError, ValueError):
        return None


def tool_catalogue(tools, capabilities, versions):
    catalogue = []
    for tool in sorted(tools):
        row = capabilities.get(tool, {})
        catalogue.append({
            "id": tool,
            "label": tool,
            "version": versions.get(tool, "not recorded"),
            "type": row.get("method_class", "unspecified"),
            "binningCapable": row.get("binning_capable", "no") == "yes",
        })
    return catalogue


def plasmid_rows(payload, tool):
    """Per-truth-plasmid recovery for one method, from retained alignment blocks."""
    if not payload or tool not in payload.get("tools", {}):
        return []
    data = payload["tools"][tool]
    circular = set(payload.get("circular_truth_plasmids") or [])
    features = defaultdict(list)
    for feature in (payload.get("amr_features") or []):
        features[feature["sequence_id"]].append(feature.get("label", "AMR"))
    replicons = {}
    for feature in (payload.get("context_features") or []):
        if feature.get("feature_type") == "replicon":
            replicons.setdefault(feature["sequence_id"], feature.get("label", ""))

    rows = []
    for plasmid, info in payload.get("truth_plasmids", {}).items():
        recovery = data.get("plasmid_recovery", {}).get(plasmid, {})
        completeness = recovery.get("completeness") or 0.0
        records = sorted({b["record_id"] for b in data["blocks"] if b["target"] == plasmid})
        # Purity is measured against the records that support this plasmid: bases
        # they place elsewhere are the impurity. It is not a modelled quantity.
        supporting = [b for b in data["blocks"] if b["record_id"] in set(records)]
        on_target = sum(b["target_end"] - b["target_start"] for b in supporting if b["target"] == plasmid)
        total = sum(b["target_end"] - b["target_start"] for b in supporting)
        purity = (on_target / total) if total else None
        rows.append({
            "id": plasmid,
            "length": info.get("length", 0),
            "circular": plasmid in circular,
            "replicon": replicons.get(plasmid) or "not evaluated",
            "amrGenes": features.get(plasmid, []),
            "recoveryPct": round(completeness * 100, 2),
            "purityPct": round(purity * 100, 2) if purity is not None else None,
            "structuralConcordance": None,
            "recoveryClass": classify(completeness, len(records)),
            "bestTool": tool,
            "contigs": len(records),
        })
    return sorted(rows, key=lambda r: -r["recoveryPct"])


def classify(completeness, records):
    if completeness >= 0.99:
        return "complete_concordant"
    if completeness >= 0.90:
        return "near_complete"
    if completeness >= 0.5:
        return "fragmented" if records > 2 else "partial"
    if completeness > 0:
        return "partial"
    return "not_recovered"


def contig_rows(payload, tool, plasmid):
    """Predicted records supporting one truth plasmid, with measured evidence."""
    if not payload or tool not in payload.get("tools", {}):
        return []
    blocks = [b for b in payload["tools"][tool]["blocks"] if b["target"] == plasmid]
    by_record = defaultdict(list)
    for block in blocks:
        by_record[block["record_id"]].append(block)
    elsewhere = defaultdict(set)
    for block in payload["tools"][tool]["blocks"]:
        elsewhere[block["record_id"]].add(
            "chromosome" if block["molecule_type"] == "CHROMOSOME" else block["target"])

    rows = []
    for record, items in sorted(by_record.items()):
        items.sort(key=lambda b: b["target_start"])
        aligned = sum(b["target_end"] - b["target_start"] for b in items)
        matches = sum(b["matches"] for b in items)
        length = sum(b["block_length"] for b in items)
        identity = (matches / length * 100) if length else None
        inverted = any(b["strand"] == "-" for b in items)
        contaminated = bool(elsewhere[record] - {plasmid})
        alignment = next((b.get("local_alignment") for b in items if b.get("local_alignment")), None)
        sequence, mismatches, offsets = "", None, []
        if alignment:
            sequence = alignment["prediction"]
            reference = alignment["reference"]
            offsets = [i for i, (a, b) in enumerate(zip(reference, sequence)) if a != b]
            mismatches = len(offsets)
        # Segment track: one block per alignment, plus the uncovered spans between.
        segments, cursor = [], items[0]["target_start"]
        for block in items:
            if block["target_start"] > cursor:
                segments.append({"start": cursor, "end": block["target_start"],
                                 "type": "missing", "len": block["target_start"] - cursor})
            kind = "inverted" if block["strand"] == "-" else "good"
            segments.append({"start": block["target_start"], "end": block["target_end"],
                             "type": kind, "len": block["target_end"] - block["target_start"]})
            cursor = max(cursor, block["target_end"])
        rows.append({
            "id": record,
            "length": items[0]["query_length"],
            "recovery": round(aligned / items[0]["query_length"] * 100, 2) if items[0]["query_length"] else None,
            "identity": round(identity, 2) if identity is not None else None,
            "alignmentStart": items[0]["target_start"],
            "alignmentEnd": items[-1]["target_end"],
            "hasInversion": inverted,
            "hasContam": contaminated,
            "gaps": max(0, len(items) - 1),
            "mismatches": mismatches,
            "status": "warning" if (inverted or contaminated) else "good",
            "segments": segments,
            "sequence": sequence,
            "mismatchOffsets": offsets,
            "blocks": len(items),
        })
    return rows


def build(scores, status, leaderboard, metadata, capabilities, versions, visualizations, structural,
          tool_version="version not recorded"):
    samples = sorted({row["sample"] for row in scores})
    tools = sorted({row["tool"] for row in scores})
    state = {(r.get("sample"), r.get("tool")): r for r in status}

    dataset, plasmid_data, contig_data = {}, {}, {}
    for sample in samples:
        payload = visualizations.get(sample)
        meta_row = metadata.get(sample, {})
        truth = (payload or {}).get("truth_plasmids", {})
        total_bp = sum(v.get("length", 0) for v in truth.values())
        dataset[sample] = {
            "meta": {
                "organism": meta_row.get("organism") or "not recorded",
                "technology": meta_row.get("truth_technology") or "not recorded",
                "depth": number(meta_row.get("read_depth_x")),
                "plasmids": len(truth),
                "totalSize": round(total_bp / 1000, 2) if total_bp else None,
                "circular": bool((payload or {}).get("circular_truth_plasmids")),
                "amrPresent": bool((payload or {}).get("amr_features")),
                "cohort": meta_row.get("bioproject") or "not recorded",
                "tier": meta_row.get("truth_quality_tier") or "",
            },
            "metrics": {},
        }
        best, best_score = None, -1.0
        for tool in tools:
            row = next((r for r in scores if r["sample"] == sample and r["tool"] == tool), None)
            profile = state.get((sample, tool), {})
            if row is None:
                dataset[sample]["metrics"][tool] = {
                    "status": profile.get("status", "skipped"), "basePrecision": None,
                    "baseRecall": None, "baseF1": None, "completeness": None, "purity": None,
                    "plasmidsRecovered": None, "structuralConcordance": None,
                    "runtime": number(profile.get("runtime_seconds"), 1 / 60),
                    "memory": number(profile.get("peak_rss_kb"), 1 / (1024 * 1024)),
                }
                continue
            tp, fp = number(row.get("TP_bp")) or 0.0, number(row.get("FP_bp")) or 0.0
            f1 = number(row.get("f1"))
            recovered = number(row.get("recovered_plasmid_count"))
            dataset[sample]["metrics"][tool] = {
                "basePrecision": number(row.get("precision")),
                "baseRecall": number(row.get("recall")),
                "baseF1": f1,
                "completeness": number(row.get("recall")),
                "purity": (tp / (tp + fp)) if (tp + fp) else None,
                "plasmidsRecovered": int(recovered) if recovered is not None else None,
                "structuralConcordance": structural.get((sample, tool)),
                "runtime": number(profile.get("runtime_seconds"), 1 / 60),
                "memory": number(profile.get("peak_rss_kb"), 1 / (1024 * 1024)),
                "status": profile.get("status", "scored"),
            }
            if f1 is not None and f1 > best_score:
                best, best_score = tool, f1
        reference_tool = best or (tools[0] if tools else None)
        plasmid_data[sample] = plasmid_rows(payload, reference_tool) if reference_tool else []
        for tool in tools:
            for plasmid in (payload or {}).get("truth_plasmids", {}):
                rows = contig_rows(payload, tool, plasmid)
                if rows:
                    contig_data[f"{sample}|{tool}|{plasmid}"] = rows

    return {
        "tools": tool_catalogue(tools, capabilities, versions),
        "sampleIds": samples,
        "sampleMeta": {s: dataset[s]["meta"] for s in samples},
        "dataset": dataset,
        "plasmidData": plasmid_data,
        "contigData": contig_data,
        "statuses": STATUSES,
        "organisms": sorted({dataset[s]["meta"]["organism"] for s in samples}),
        "technologies": sorted({dataset[s]["meta"]["technology"] for s in samples}),
        "replicons": sorted({p["replicon"] for rows in plasmid_data.values() for p in rows}),
        "amrGenes": sorted({g for rows in plasmid_data.values() for p in rows for g in p["amrGenes"]}),
        "provenance": {"source": "measured PlasBench run", "simulated": False,
                       "toolVersion": tool_version,
                       "note": "Fields with no measurement are null and render as 'not measured'."},
    }


def render(template_path, data, fonts_html):
    template = Path(template_path).read_text(encoding="utf-8")
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    return template.replace("__PB_DATA__", payload).replace("__PB_FONTS__", fonts_html)
