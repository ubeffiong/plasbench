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


def plasmid_rows(payload, tool, collinear=None):
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
    truth_proteins = defaultdict(list)
    for feature in (payload.get("protein_features") or []):
        truth_proteins[feature.get("sequence_id")].append(feature)
    predicted_proteins = data.get("protein_features") or []

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
        # Records supporting this plasmid that also land elsewhere: a merge when
        # they reach another truth plasmid, contamination when they reach the
        # chromosome, ambiguity when the same span maps more than one way.
        elsewhere = {}
        for block in data["blocks"]:
            if block["record_id"] in set(records):
                elsewhere.setdefault(block["record_id"], set()).add(
                    "chromosome" if block["molecule_type"] == "CHROMOSOME" else block["target"])
        chromosome_records = [r for r, t_ in elsewhere.items() if "chromosome" in t_]
        cross_plasmid = [r for r, t_ in elsewhere.items() if (t_ - {plasmid, "chromosome"})]
        ambiguous_records = [r for r, t_ in elsewhere.items() if len(t_) > 2]
        rows.append({
            "id": plasmid,
            "length": info.get("length", 0),
            "circular": plasmid in circular,
            "replicon": replicons.get(plasmid) or "not evaluated",
            "amrGenes": features.get(plasmid, []),
            "proteins": truth_proteins.get(plasmid, []),
            "projectedProteins": [p for p in predicted_proteins if p.get("sequence_id") == plasmid],
            "recoveryPct": round(completeness * 100, 2),
            "purityPct": round(purity * 100, 2) if purity is not None else None,
            "structuralConcordance": None,
            "recoveryClass": classify(
                completeness, len(records), purity=purity,
                merged=bool(cross_plasmid), chromosomal=bool(chromosome_records),
                collinear=collinear, ambiguous=bool(ambiguous_records)),
            "bestTool": tool,
            "contigs": len(records),
        })
    return sorted(rows, key=lambda r: -r["recoveryPct"])


def classify(completeness, records, purity=None, merged=False, chromosomal=False,
             collinear=None, ambiguous=False):
    """Assign one of the nine documented recovery classes.

    Thresholds are display bands for triage, not acceptance criteria. Purity,
    merge and contamination evidence outrank completeness: a plasmid can be
    fully covered and still be reconstructed wrongly, which a completeness-only
    label would hide.
    """
    if ambiguous:
        return "ambiguous"
    if chromosomal:
        return "chromosomal_contam"
    if merged:
        return "merged"
    if completeness >= 0.90:
        # Structural disagreement matters most where coverage looks complete.
        if collinear is not None and collinear < 0.75:
            return "complete_discordant"
        if completeness >= 0.99:
            return "complete_concordant"
        return "near_complete"
    if completeness >= 0.5:
        return "fragmented" if records > 2 else "partial"
    if completeness > 0:
        return "partial"
    return "not_recovered"


def protein_completeness(payload, tool):
    """Coordinate-complete named CDS fraction, or None when unmeasured."""
    if not payload or tool not in payload.get("tools", {}):
        return None
    truth = payload.get("protein_features") or []
    predicted = payload["tools"][tool].get("protein_features") or []
    if not truth or not predicted:
        return None
    complete = 0
    for feature in truth:
        projections = [p.get("projection_fraction", 0) for p in predicted
                       if p.get("sequence_id") == feature.get("sequence_id")
                       and p.get("end", 0) > feature.get("start", 0)
                       and p.get("start", 0) < feature.get("end", 0)]
        complete += bool(projections and max(projections) >= 0.95)
    return complete / len(truth)


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
        segments, cursor, seen_spans = [], items[0]["target_start"], []
        others = elsewhere[record] - {plasmid}
        previous = None
        for block in items:
            if block["target_start"] > cursor:
                # A reference gap is "missing" when the prediction also stops, and an
                # unsupported join when the predicted record runs straight across it:
                # the record asserts adjacency the reference does not support.
                contiguous_query = (previous is not None
                                    and abs(block["query_start"] - previous["query_end"]) <= 50)
                segments.append({"start": cursor, "end": block["target_start"],
                                 "type": "unsupported_join" if contiguous_query else "missing",
                                 "len": block["target_start"] - cursor})
            span = (block["target_start"], block["target_end"])
            # Named apart from the record-level percentage above: reusing that
            # name overwrote it, and every record then reported its last block's
            # identity fraction as if it were the record's percentage.
            block_identity = block["matches"] / block["block_length"] if block["block_length"] else 1.0
            # Most specific evidence first. "ambiguous" must precede "wrong_plasmid":
            # a record reaching several other targets cannot be assigned to one.
            if any(s[0] < span[1] and span[0] < s[1] for s in seen_spans):
                kind = "duplicated"
            elif block["strand"] == "-":
                kind = "inverted"
            elif len(others) > 1:
                kind = "ambiguous"
            elif "chromosome" in others:
                kind = "chromosomal"
            elif others:
                kind = "wrong_plasmid"
            elif block_identity < 0.90:
                kind = "low_identity"
            else:
                kind = "good"
            seen_spans.append(span)
            segments.append({"start": block["target_start"], "end": block["target_end"],
                             "type": kind, "len": block["target_end"] - block["target_start"],
                             "identity": round(block_identity * 100, 2)})
            cursor = max(cursor, block["target_end"])
            previous = block
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
                "origin": meta_row.get("sample_origin") or "not recorded",
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
                "proteinCompleteness": protein_completeness(payload, tool),
                # Already produced by scoring and bin diagnostics; surfaced so the
                # matrix can rank on contamination and fragmentation, not only F1.
                "contamination": (fp / (tp + fp)) if (tp + fp) else None,
                "unmapped": number(row.get("unmapped_pred_bp")),
                "splitEvents": number(row.get("split_events")),
                "mergeEvents": number(row.get("merge_events")),
                "amrRecall": number(row.get("amr_gene_recall")),
                "repliconRecall": number(row.get("replicon_recall")),
            }
            if f1 is not None and f1 > best_score:
                best, best_score = tool, f1
        reference_tool = best or (tools[0] if tools else None)
        plasmid_data[sample] = (plasmid_rows(payload, reference_tool,
                                            structural.get((sample, reference_tool)))
                                if reference_tool else [])
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
        "origins": sorted({dataset[s]["meta"]["origin"] for s in samples}),
        "tiers": sorted({dataset[s]["meta"]["tier"] for s in samples}),
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
