#!/usr/bin/env python3
"""Map measured benchmark output into the reconstruction evidence explorer.

The explorer template is a vendored design. This module supplies its data
model from the run: alignment blocks (spans, strand, identity, mapping
quality), the structural caller, bin-to-truth matching, and reference
annotation.

Fields the pipeline does not measure are emitted as ``null`` so the interface
can say "not measured". Nothing here substitutes a zero for an absent
measurement -- a zero is a claim, and an unmeasured field is not one.

Per-segment read coverage is the one field the design shows that PlasBench
does not compute: scoring is projection-based over reference bases and never
builds a depth profile. It is null everywhere.
"""

import json
from collections import defaultdict

from build_enterprise_view import contig_rows


# Reference bases outside any CIGAR-bounded local alignment are unknown rather
# than absent, and the nucleotide view draws them as unresolved.
UNKNOWN_BASE = "."

# The curated feature vocabulary mapped onto the design's protein categories.
CATEGORY_BY_FEATURE = {
    "replicon": "Replication",
    "rep": "Replication",
    "mob": "Conjugation",
    "conjugation": "Conjugation",
    "relaxase": "Conjugation",
    "mpf": "Conjugation",
    "is": "Transposase",
    "insertion_sequence": "Transposase",
    "transposase": "Transposase",
    "partition": "Maintenance",
    "toxin_antitoxin": "Maintenance",
    "maintenance": "Maintenance",
    "amr": "AMR",
    "resistance": "AMR",
    "hypothetical": "Hypothetical",
    "unknown": "Hypothetical",
}

EMPTY_EVENTS = ("mismatches", "gaps", "inversions", "breakpoints")


def category_for(feature_type):
    """Assign a display category without inventing biology.

    The curated feature type decides when it is known. Otherwise the feature is
    reported as Other rather than guessed from its name.
    """
    key = (feature_type or "").strip().lower()
    if key in CATEGORY_BY_FEATURE:
        return CATEGORY_BY_FEATURE[key]
    for token, category in CATEGORY_BY_FEATURE.items():
        if key.startswith(token):
            return category
    return "Other"


def proteins_for(payload, plasmid):
    """Named features on one truth plasmid, from every annotation source."""
    out = []
    for row in payload.get("amr_features", []):
        if row.get("sequence_id") != plasmid:
            continue
        out.append({
            "name": row.get("label", "unnamed"),
            "product": row.get("product") or "antimicrobial resistance determinant",
            "category": "AMR",
            "start": int(row["start"]), "end": int(row["end"]),
            "strand": row.get("strand", "+"),
            "source": row.get("source", "curated AMR truth"),
        })
    for row in payload.get("context_features", []):
        if row.get("sequence_id") != plasmid:
            continue
        out.append({
            "name": row.get("label", "unnamed"),
            "product": row.get("product") or row.get("feature_type", "curated feature"),
            "category": category_for(row.get("feature_type")),
            "start": int(row["start"]), "end": int(row["end"]),
            "strand": row.get("strand", "+"),
            "source": row.get("source", "curated context"),
        })
    for row in payload.get("protein_features", []):
        if row.get("sequence_id") != plasmid:
            continue
        # The normalized protein schema names the vocabulary column "category";
        # curated context features name theirs "feature_type".
        out.append({
            "name": row.get("gene") or row.get("feature_id") or "unnamed",
            "product": row.get("product") or "coding sequence",
            "category": category_for(row.get("category") or row.get("feature_type")),
            "start": int(row["start"]), "end": int(row["end"]),
            "strand": row.get("strand", "+"),
            "source": row.get("source", "reference annotation"),
        })
    for item in out:
        item["length"] = item["end"] - item["start"]
    return sorted(out, key=lambda f: f["start"])


def protein_status(feature, segments):
    """Coordinate recovery of one feature, not amino-acid identity.

    A feature is complete when every base of its span falls inside a segment
    the method recovered, partial when some do, and missing when none do.
    """
    recovered = {"good", "low_identity", "inverted", "duplicated"}
    covered = 0
    for seg in segments:
        if seg["type"] not in recovered:
            continue
        low = max(seg["start"], feature["start"])
        high = min(seg["end"], feature["end"])
        if high > low:
            covered += high - low
    span = max(1, feature["end"] - feature["start"])
    if covered >= span:
        return "Complete"
    return "Partial" if covered else "Missing"


def sequences_for(payload, tool, plasmid, length):
    """Reference and predicted bases on reference coordinates.

    Only blocks carrying a ``cg:Z:`` CIGAR produce a bounded local alignment,
    so the strings stay unresolved outside those spans. The alternative -- a
    fabricated sequence -- would make the nucleotide view lie.
    """
    reference = [UNKNOWN_BASE] * length
    predicted = [UNKNOWN_BASE] * length
    resolved = 0
    for block in payload.get("tools", {}).get(tool, {}).get("blocks", []):
        if block["target"] != plasmid:
            continue
        alignment = block.get("local_alignment")
        if not alignment:
            continue
        cursor = block["target_start"]
        for ref_base, pred_base in zip(alignment["reference"], alignment["prediction"]):
            if cursor >= length:
                break
            if ref_base == "-":
                continue
            reference[cursor] = ref_base
            predicted[cursor] = pred_base
            resolved += 1
            cursor += 1
    return "".join(reference), "".join(predicted), resolved


def tool_segments(records, length):
    """One reference-coordinate track per method.

    Per-record segments keep their measured classification. Reference spans no
    record reaches are missing from this method's reconstruction.
    """
    segments = []
    for record in records:
        for seg in record["segments"]:
            item = dict(seg)
            item["record"] = record["id"]
            segments.append(item)
    segments.sort(key=lambda s: (s["start"], s["end"]))

    covered = []
    for seg in segments:
        if seg["type"] == "missing":
            continue
        if covered and seg["start"] <= covered[-1][1]:
            covered[-1][1] = max(covered[-1][1], seg["end"])
        else:
            covered.append([seg["start"], seg["end"]])

    gaps, cursor = [], 0
    for low, high in covered:
        if low > cursor:
            gaps.append({"start": cursor, "end": low, "type": "missing",
                         "len": low - cursor, "record": None})
        cursor = max(cursor, high)
    if cursor < length:
        gaps.append({"start": cursor, "end": length, "type": "missing",
                     "len": length - cursor, "record": None})

    merged = [s for s in segments if s["type"] != "missing"] + gaps
    merged.sort(key=lambda s: (s["start"], s["end"]))
    return merged


def events_for(calls, tool, plasmid, records, segments):
    """Structural navigation targets, all alignment-derived and unvalidated.

    Gaps are read from the method's merged track rather than from individual
    records: the reference intervals worth navigating to are usually the ones
    that fall between two records, which no single record can report.
    """
    out = {key: [] for key in EMPTY_EVENTS}
    entry = (calls or {}).get("tools", {}).get(tool, {})
    for event in entry.get("events", []):
        if plasmid not in (event.get("left_target"), event.get("right_target")):
            continue
        kind = event["event_type"]
        position = int(event.get("left_target_end") or event.get("right_target_start") or 0)
        span = int(event.get("span_bp", 0) or 0)
        detail = event.get("detail", "")
        item = {"pos": position, "tool": tool,
                "desc": (kind.replace("_", " ") + ": " + detail).strip(": "),
                "validated": bool(event.get("validated", False))}
        if kind == "inversion_junction":
            out["inversions"].append(dict(item, start=position, end=position + span))
        elif kind in ("reference_deletion", "reference_insertion"):
            out["gaps"].append(dict(item, start=position, end=position + span))
        else:
            out["breakpoints"].append(item)

    for seg in segments:
        where = " in " + seg["record"] if seg.get("record") else ""
        if seg["type"] == "inverted":
            out["inversions"].append({
                "pos": seg["start"], "start": seg["start"], "end": seg["end"],
                "tool": tool, "validated": False,
                "desc": "reverse-strand alignment" + where})
        elif seg["type"] in ("missing", "unsupported_join"):
            out["gaps"].append({
                "pos": seg["start"], "start": seg["start"], "end": seg["end"],
                "tool": tool, "validated": False,
                "desc": "{0} across {1:,} bp{2}".format(
                    seg["type"].replace("_", " "), seg["end"] - seg["start"], where)})

    for record in records:
        # Mismatch columns come from the bounded local alignment, so they exist
        # only where a CIGAR was available. Cap the list: navigation needs
        # somewhere to jump, not every column in a long record.
        for offset in (record.get("mismatchOffsets") or [])[:200]:
            out["mismatches"].append({
                "pos": record["alignmentStart"] + offset, "tool": tool, "validated": False,
                "desc": "base mismatch in " + record["id"]})
    return out


def split_merge_for(payload, truth_plasmids):
    """Truth-to-bin relationships, measured by bin scoring.

    Split and merge are properties of one method's binning, so the fan-out is
    counted per method. Pooling every method's bins would make each plasmid
    look split simply because several methods each produced a bin for it.
    """
    truth_links = defaultdict(lambda: defaultdict(set))
    bin_links = defaultdict(set)
    rows = []
    for tool, entry in payload.get("tools", {}).items():
        for flow in entry.get("bin_assignment_flows", []):
            plasmid = flow.get("true_plasmid") or ""
            if not plasmid:
                continue
            rows.append((tool, flow["bin_id"], plasmid, int(flow.get("aligned_bp", 0) or 0)))
            truth_links[tool][plasmid].add(flow["bin_id"])
            bin_links[flow["bin_id"]].add(plasmid)

    links = []
    for tool, bin_id, plasmid, aligned in rows:
        merged = len(bin_links[bin_id]) > 1
        split = len(truth_links[tool][plasmid]) > 1
        if merged and split:
            kind = "complex"
        elif merged:
            kind = "merge"
        elif split:
            kind = "split"
        else:
            kind = "1:1"
        length = truth_plasmids.get(plasmid, {}).get("length", 0)
        links.append({"truth": plasmid, "pred": bin_id, "tool": tool, "type": kind,
                      "weight": round(aligned / length, 4) if length else 0.0,
                      "aligned_bp": aligned})
    return {
        "truth": [{"id": name, "length": meta.get("length", 0)}
                  for name, meta in sorted(truth_plasmids.items())],
        "predicted": [{"id": name, "matches": sorted(bin_links[name])}
                      for name in sorted(bin_links)],
        "links": links,
    }


def build(visualizations, structural, versions):
    """Assemble the explorer payload for every sample that has display data."""
    samples = []
    for sample in sorted(visualizations):
        payload = visualizations[sample]
        if not payload:
            continue
        calls = (structural or {}).get(sample)
        truth = {name: meta for name, meta in payload.get("truth_plasmids", {}).items()
                 if meta.get("molecule_type") == "PLASMID"}
        circular = set(payload.get("circular_truth_plasmids", []) or [])
        plasmids = []
        for name, meta in sorted(truth.items()):
            length = int(meta.get("length", 0))
            if not length:
                continue
            features = proteins_for(payload, name)
            replicon = next((f["name"] for f in features if f["category"] == "Replication"), None)
            tracks = []
            events = {key: [] for key in EMPTY_EVENTS}
            for tool in sorted(payload.get("tools", {})):
                records = contig_rows(payload, tool, name)
                if not records:
                    continue
                segments = tool_segments(records, length)
                reference, predicted, resolved = sequences_for(payload, tool, name, length)
                blocks = [b for b in payload["tools"][tool]["blocks"] if b["target"] == name]
                mapqs = [b["mapq"] for b in blocks if b.get("mapq") is not None]
                matched = sum(b["matches"] for b in blocks)
                spanned = sum(b["block_length"] for b in blocks)
                for feature in features:
                    feature.setdefault("statusByTool", {})
                    feature["statusByTool"][tool] = protein_status(feature, segments)
                tracks.append({
                    "id": tool,
                    "label": tool,
                    "version": versions.get(tool, "not recorded"),
                    "segments": segments,
                    "contigs": [{"id": r["id"], "start": r["alignmentStart"],
                                 "end": r["alignmentEnd"], "status": r["status"],
                                 "identity": r["identity"], "blocks": r["blocks"],
                                 "mismatches": r["mismatches"]} for r in records],
                    "predictedSequence": predicted,
                    "referenceSequence": reference,
                    "resolvedBases": resolved,
                    "identity": round(matched / spanned * 100, 2) if spanned else None,
                    "mapQ": round(sum(mapqs) / len(mapqs), 1) if mapqs else None,
                    # Read depth is never computed: scoring projects onto
                    # reference bases and never builds a depth profile.
                    "coverage": None,
                })
                found = events_for(calls, tool, name, records, segments)
                for key in events:
                    events[key].extend(found[key])
            if not tracks:
                continue
            for feature in features:
                statuses = set((feature.get("statusByTool") or {}).values())
                if statuses == {"Complete"}:
                    feature["status"] = "Complete"
                elif statuses == {"Missing"}:
                    feature["status"] = "Missing"
                else:
                    feature["status"] = "Partial"
            # Best completeness any method reached on this plasmid. Purity is
            # measured per predicted bin, not per truth plasmid, so it has no
            # value at this scope and is reported as not measured.
            completeness = [payload["tools"][t]["plasmid_recovery"].get(name, {}).get("completeness")
                            for t in payload.get("tools", {})
                            if name in payload["tools"][t].get("plasmid_recovery", {})]
            completeness = [c for c in completeness if c is not None]
            plasmids.append({
                "id": name,
                "length": length,
                "circular": (name in circular) if circular else None,
                "replicon": replicon,
                "recovery": max(completeness) if completeness else None,
                "purity": None,
                "sequence": tracks[0]["referenceSequence"],
                "proteins": features,
                "tools": tracks,
                "events": {k: sorted(v, key=lambda e: e["pos"]) for k, v in events.items()},
            })
        if plasmids:
            samples.append({"id": sample, "plasmids": plasmids,
                            "split_merge": split_merge_for(payload, truth)})
    return {"schema_version": "1", "samples": samples,
            "unmeasured": {"coverage": "read depth is not computed by projection scoring"}}


def render(template_path, data, fonts_html):
    """Inject the measured payload into the vendored design."""
    page = template_path.read_text(encoding="utf-8")
    body = json.dumps(data, separators=(",", ":"), sort_keys=True)
    page = page.replace("__PB_EXPLORER__", body, 1)
    page = page.replace("__PB_FONTS__", fonts_html, 1)
    return page
