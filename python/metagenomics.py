#!/usr/bin/env python3
"""Validate, score, and report graph-aware metagenomic plasmid predictions.

This module intentionally has no dependency on the isolate FASTA scorer.  A
metagenome contains several organisms, strains, and often viruses; treating it
as a large isolate would turn biologically distinct mistakes into misleading
chromosome/plasmid false positives.  Tool adapters therefore exchange explicit
contig/bin membership tables and this module scores them only when a declared
community truth table is present.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import math
import hashlib
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_REQUIRED = {"community_id", "sample_id", "information_regime", "truth_status"}
MANIFEST_OPTIONAL = {
    "reads_1", "reads_2", "assembly_fasta", "assembly_graph_gfa", "graph_paths",
    "truth_contigs_tsv", "truth_bins_tsv", "long_read_links", "hic_links",
    "source_country", "source_environment", "notes",
    # Provenance is intentionally optional for a schema-only example, but a
    # released cohort must populate these values before it is recommendation-eligible.
    "dataset_class", "dataset_license", "truth_provenance", "independence_status",
    "database_overlap_status", "read_depth_x", "host_depletion_reference",
    "assembler", "assembler_parameters", "tool_mode", "comparability_group",
    "database_identity", "container_image", "container_digest", "runtime_seconds",
    "peak_rss_mb", "prediction_threshold", "mobilome_gff", "mobilome_report",
    # Upstream processing changes what every downstream tool receives. Keep
    # it in the schema so an assembly advantage is not misattributed to a
    # plasmid-recovery method.
    "input_read_technology", "preprocessing_profile", "assembly_profile",
    "assembly_profile_version", "coassembly_id", "source_study",
    "host_assignment_evidence", "community_complexity", "phage_burden",
    "contamination_level", "reference_cluster_id",
}
REGIMES = {"single_sample", "multisample", "graph_aware", "long_read_supported"}
TRUTH_STATUSES = {"synthetic", "mock", "verified", "unavailable"}
PREDICTION_REQUIRED = {
    "predicted_bin_id", "contig_id", "graph_path", "orientation", "path_confidence",
    "plasmid_score", "ambiguity_status", "source_tool",
}
CLASSIFICATION_REQUIRED = {
    "contig_id", "predicted_class", "plasmid_probability",
    "chromosome_probability", "phage_probability", "uncertainty_status", "source_tool",
}
CLASSIFICATION_OPTIONAL = {"supported_classes"}
TRUTH_REQUIRED = {"contig_id", "truth_bin_id", "biological_class"}
BIOLOGICAL_CLASSES = {"plasmid", "chromosome", "virus", "unknown"}
PREDICTED_CLASSES = {"plasmid", "chromosome", "virus", "uncertain"}
SAFE_HOST_EVIDENCE = {"none", "long_read", "hic", "methylation", "validated_coabundance", "mixed", "unknown"}


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None:
            raise ValueError(f"{path}: expected a TSV header")
        return [{key: (value or "").strip() for key, value in row.items()} for row in reader]


def write_tsv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def resolve(manifest: Path, value: str) -> Path | None:
    if not value:
        return None
    candidate = Path(value).expanduser()
    return candidate if candidate.is_absolute() else manifest.parent / candidate


def validate_manifest(path: Path, require_truth: bool = False, release_ready: bool = False) -> tuple[list[dict[str, str]], list[str]]:
    rows = read_tsv(path)
    errors: list[str] = []
    if not rows:
        return rows, [f"{path}: has no community rows"]
    columns = set(rows[0])
    missing = MANIFEST_REQUIRED - columns
    if missing:
        errors.append(f"{path}: missing required columns: {', '.join(sorted(missing))}")
        return rows, errors
    seen: set[tuple[str, str]] = set()
    community_regimes: dict[str, str] = {}
    for index, row in enumerate(rows, start=2):
        key = (row["community_id"], row["sample_id"])
        if not all(key):
            errors.append(f"row {index}: community_id and sample_id are required")
        elif key in seen:
            errors.append(f"row {index}: duplicate community/sample pair {key[0]}/{key[1]}")
        seen.add(key)
        regime = row["information_regime"]
        if regime not in REGIMES:
            errors.append(f"row {index}: information_regime must be one of {', '.join(sorted(REGIMES))}")
        previous = community_regimes.setdefault(row["community_id"], regime)
        if previous != regime:
            errors.append(f"row {index}: a community cannot mix information regimes ({previous}, {regime})")
        if row["truth_status"] not in TRUTH_STATUSES:
            errors.append(f"row {index}: truth_status must be one of {', '.join(sorted(TRUTH_STATUSES))}")
        for name in ("reads_1", "reads_2", "assembly_fasta", "assembly_graph_gfa", "graph_paths", "truth_contigs_tsv", "truth_bins_tsv", "mobilome_gff", "mobilome_report"):
            value = row.get(name, "")
            if value and not resolve(path, value).is_file():
                errors.append(f"row {index}: {name} does not exist: {value}")
        design_only = row["truth_status"] == "synthetic" and row.get("dataset_class") == "synthetic_community" and row.get("preprocessing_profile") == "not_materialised"
        if regime in {"graph_aware", "multisample"} and not row.get("assembly_graph_gfa") and not design_only:
            errors.append(f"row {index}: {regime} requires assembly_graph_gfa")
        if require_truth and row["truth_status"] != "unavailable":
            if not row.get("truth_contigs_tsv"):
                errors.append(f"row {index}: truth_contigs_tsv is required for truth scoring")
        for name in ("read_depth_x", "runtime_seconds", "peak_rss_mb", "prediction_threshold"):
            if row.get(name, ""):
                try:
                    value = float(row[name])
                    if value < 0 or (name == "prediction_threshold" and value > 1):
                        raise ValueError
                except ValueError:
                    errors.append(f"row {index}: {name} must be a non-negative number" + (" in [0,1]" if name == "prediction_threshold" else ""))
        if row.get("container_digest") and not row.get("container_image"):
            errors.append(f"row {index}: container_digest requires container_image")
        if row.get("host_assignment_evidence", "") and row["host_assignment_evidence"] not in SAFE_HOST_EVIDENCE:
            errors.append(f"row {index}: host_assignment_evidence must be one of {', '.join(sorted(SAFE_HOST_EVIDENCE))}")
        if row.get("coassembly_id") and regime == "single_sample":
            errors.append(f"row {index}: coassembly_id is only valid for a multi-sample or graph-aware community")
        for name in ("community_complexity", "phage_burden", "contamination_level"):
            if row.get(name, "") and row[name] not in {"low", "medium", "high", "unknown"}:
                errors.append(f"row {index}: {name} must be low, medium, high, or unknown")
        if release_ready and row["truth_status"] != "unavailable":
            required_release_metadata = ("dataset_class", "dataset_license", "truth_provenance", "independence_status", "database_overlap_status", "tool_mode", "comparability_group", "database_identity")
            missing_release = [name for name in required_release_metadata if not row.get(name, "")]
            if missing_release:
                errors.append(f"row {index}: release-ready cohort lacks: {', '.join(missing_release)}")
            if row.get("dataset_class") == "mock_high_depth":
                errors.append(f"row {index}: mock_high_depth data cannot be release-ready for routine operational recommendations")
    return rows, errors


def validate_prediction(path: Path) -> list[dict[str, str]]:
    rows = read_tsv(path)
    if not rows:
        raise ValueError(f"{path}: prediction table is empty")
    missing = PREDICTION_REQUIRED - set(rows[0])
    if missing:
        raise ValueError(f"{path}: missing prediction columns: {', '.join(sorted(missing))}")
    bins: set[str] = set()
    contigs: set[str] = set()
    for index, row in enumerate(rows, start=2):
        if not row["predicted_bin_id"] or not row["contig_id"]:
            raise ValueError(f"{path}: row {index} needs predicted_bin_id and contig_id")
        if row["orientation"] not in {"+", "-", "?"}:
            raise ValueError(f"{path}: row {index} orientation must be +, -, or ?")
        if row["ambiguity_status"] not in {"resolved", "ambiguous", "abstained", "unknown"}:
            raise ValueError(f"{path}: row {index} has invalid ambiguity_status")
        try:
            score = float(row["plasmid_score"])
            confidence = float(row["path_confidence"])
        except ValueError as exc:
            raise ValueError(f"{path}: row {index} scores must be numeric") from exc
        if not 0 <= score <= 1 or not 0 <= confidence <= 1:
            raise ValueError(f"{path}: row {index} scores must be between 0 and 1")
        pair = (row["predicted_bin_id"], row["contig_id"])
        if pair in bins:
            raise ValueError(f"{path}: row {index} duplicates bin/contig membership")
        bins.add(pair)
        contigs.add(row["contig_id"])
    return rows


def validate_classification(path: Path) -> list[dict[str, str]]:
    """Validate a classifier table without pretending every call is a bin."""
    rows = read_tsv(path)
    if not rows:
        raise ValueError(f"{path}: classification table is empty")
    missing = CLASSIFICATION_REQUIRED - set(rows[0])
    if missing:
        raise ValueError(f"{path}: missing classification columns: {', '.join(sorted(missing))}")
    seen: set[str] = set()
    for index, row in enumerate(rows, start=2):
        contig = row["contig_id"]
        if not contig or contig in seen:
            raise ValueError(f"{path}: row {index} has a missing or duplicate contig_id")
        seen.add(contig)
        if row["predicted_class"] not in PREDICTED_CLASSES:
            raise ValueError(f"{path}: row {index} has invalid predicted_class")
        if row["uncertainty_status"] not in {"resolved", "uncertain", "abstained", "unknown"}:
            raise ValueError(f"{path}: row {index} has invalid uncertainty_status")
        try:
            scores = [float(row[key]) for key in ("plasmid_probability", "chromosome_probability", "phage_probability")]
        except ValueError as exc:
            raise ValueError(f"{path}: row {index} probabilities must be numeric") from exc
        if any(score < 0 or score > 1 for score in scores):
            raise ValueError(f"{path}: row {index} probabilities must be between 0 and 1")
        supported = set(filter(None, row.get("supported_classes", "plasmid|chromosome|virus").split("|")))
        if not supported or not supported.issubset({"plasmid", "chromosome", "virus"}):
            raise ValueError(f"{path}: row {index} has invalid supported_classes")
    return rows


def validate_truth(path: Path) -> dict[str, dict[str, str]]:
    rows = read_tsv(path)
    if not rows:
        raise ValueError(f"{path}: truth table is empty")
    missing = TRUTH_REQUIRED - set(rows[0])
    if missing:
        raise ValueError(f"{path}: missing truth columns: {', '.join(sorted(missing))}")
    truth: dict[str, dict[str, str]] = {}
    for index, row in enumerate(rows, start=2):
        if row["contig_id"] in truth:
            raise ValueError(f"{path}: row {index} duplicates contig_id {row['contig_id']}")
        if row["biological_class"] not in BIOLOGICAL_CLASSES:
            raise ValueError(f"{path}: row {index} has invalid biological_class")
        truth[row["contig_id"]] = row
    return truth


def hungarian_max(weights: list[list[float]]) -> list[tuple[int, int]]:
    """Maximum-weight one-to-one matching using the Hungarian algorithm."""
    if not weights or not weights[0]:
        return []
    n, m = len(weights), len(weights[0])
    size = max(n, m)
    maximum = max((value for row in weights for value in row), default=0.0)
    cost = [[maximum - (weights[i][j] if i < n and j < m else 0.0) for j in range(size)] for i in range(size)]
    u, v = [0.0] * (size + 1), [0.0] * (size + 1)
    p, way = [0] * (size + 1), [0] * (size + 1)
    for i in range(1, size + 1):
        p[0], j0 = i, 0
        minv, used = [math.inf] * (size + 1), [False] * (size + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], math.inf, 0
            for j in range(1, size + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]: minv[j], way[j] = cur, j0
                    if minv[j] < delta: delta, j1 = minv[j], j
            for j in range(size + 1):
                if used[j]: u[p[j]] += delta; v[j] -= delta
                else: minv[j] -= delta
            j0 = j1
            if p[j0] == 0: break
        while True:
            j1, p[j0], j0 = j0, p[way[j0]], way[j0]
            if j0 == 0: break
    return [(p[j] - 1, j - 1) for j in range(1, size + 1) if p[j] and p[j] - 1 < n and j - 1 < m and weights[p[j] - 1][j - 1] > 0]


def score_prediction(predictions: list[dict[str, str]], truth: dict[str, dict[str, str]], community: str, tool: str) -> tuple[list[dict[str, object]], dict[str, object]]:
    bins: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in predictions: bins[row["predicted_bin_id"]].append(row)
    plasmids = sorted({value["truth_bin_id"] for value in truth.values() if value["biological_class"] == "plasmid" and value["truth_bin_id"]})
    bin_ids = sorted(bins)
    overlaps = [[sum(1 for row in bins[bin_id] if truth.get(row["contig_id"], {}).get("truth_bin_id") == plasmid and truth.get(row["contig_id"], {}).get("biological_class") == "plasmid") for plasmid in plasmids] for bin_id in bin_ids]
    matches = {bin_ids[i]: plasmids[j] for i, j in hungarian_max(overlaps)}
    bin_rows: list[dict[str, object]] = []
    total_tp = total_pred = total_truth = 0
    for bin_id in bin_ids:
        entries = bins[bin_id]
        matched = matches.get(bin_id, "")
        truth_plasmid = sum(1 for row in entries if truth.get(row["contig_id"], {}).get("truth_bin_id") == matched and truth.get(row["contig_id"], {}).get("biological_class") == "plasmid")
        chrom = sum(1 for row in entries if truth.get(row["contig_id"], {}).get("biological_class") == "chromosome")
        virus = sum(1 for row in entries if truth.get(row["contig_id"], {}).get("biological_class") == "virus")
        unknown = sum(1 for row in entries if row["contig_id"] not in truth)
        precision = truth_plasmid / len(entries) if entries else 0.0
        truth_size = sum(1 for row in truth.values() if row.get("truth_bin_id") == matched and row.get("biological_class") == "plasmid")
        recall = truth_plasmid / truth_size if truth_size else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        ambiguous = sum(row["ambiguity_status"] == "ambiguous" for row in entries)
        abstained = sum(row["ambiguity_status"] == "abstained" for row in entries)
        bin_rows.append({"community_id": community, "tool": tool, "predicted_bin_id": bin_id, "matched_truth_bin_id": matched or "unmatched", "contigs": len(entries), "true_plasmid_contigs": truth_plasmid, "chromosome_contigs": chrom, "virus_contigs": virus, "unknown_contigs": unknown, "bin_precision": round(precision, 6), "bin_recall": round(recall, 6), "bin_f1": round(f1, 6), "chromosome_contamination_fraction": round(chrom / len(entries), 6), "virus_contamination_fraction": round(virus / len(entries), 6), "ambiguous_contigs": ambiguous, "abstained_contigs": abstained, "mean_path_confidence": round(sum(float(row["path_confidence"]) for row in entries) / len(entries), 6), "declared_graph_paths": " | ".join(row["graph_path"] for row in entries if row["graph_path"]) or "not supplied"})
        total_tp += truth_plasmid; total_pred += len(entries)
    total_truth = sum(1 for row in truth.values() if row["biological_class"] == "plasmid")
    precision = total_tp / total_pred if total_pred else 0.0
    recall = total_tp / total_truth if total_truth else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return bin_rows, {"community_id": community, "tool": tool, "predicted_bins": len(bin_ids), "truth_plasmid_bins": len(plasmids), "matched_bins": len(matches), "bin_precision": round(precision, 6), "bin_recall": round(recall, 6), "bin_f1": round(f1, 6), "split_truth_bins": sum(sum(1 for row in bins.values() if any(truth.get(x["contig_id"], {}).get("truth_bin_id") == plasmid for x in row)) > 1 for plasmid in plasmids), "merge_predicted_bins": sum(sum(1 for plasmid in plasmids if any(truth.get(x["contig_id"], {}).get("truth_bin_id") == plasmid for x in entries)) > 1 for entries in bins.values()), "unmatched_predicted_bins": sum(bin_id not in matches for bin_id in bin_ids), "chromosome_contamination_fraction": round(sum(int(row["chromosome_contigs"]) for row in bin_rows) / total_pred, 6) if total_pred else 0.0, "virus_contamination_fraction": round(sum(int(row["virus_contigs"]) for row in bin_rows) / total_pred, 6) if total_pred else 0.0, "ambiguous_contigs": sum(int(row["ambiguous_contigs"]) for row in bin_rows), "abstained_contigs": sum(int(row["abstained_contigs"]) for row in bin_rows)}


def score_classification(predictions: list[dict[str, str]], truth: dict[str, dict[str, str]], community: str, tool: str) -> dict[str, object]:
    """Score three biological classes and retain uncertainty as a first-class outcome."""
    labels = ("plasmid", "chromosome", "virus")
    supported = set(filter(None, predictions[0].get("supported_classes", "plasmid|chromosome|virus").split("|"))) if predictions else set()
    assessed = [label for label in labels if label in supported and any(value.get("biological_class") == label for value in truth.values())]
    result: dict[str, object] = {"community_id": community, "tool": tool, "evaluation_type": "classification", "supported_classes": "|".join(sorted(supported)), "assessed_classes": "|".join(assessed) or "none", "classified_contigs": len(predictions), "uncertain_calls": sum(row["predicted_class"] == "uncertain" or row["uncertainty_status"] != "resolved" for row in predictions)}
    f1s: list[float] = []
    for label in labels:
        tp = sum(row["predicted_class"] == label and truth.get(row["contig_id"], {}).get("biological_class") == label for row in predictions)
        fp = sum(row["predicted_class"] == label and truth.get(row["contig_id"], {}).get("biological_class") != label for row in predictions)
        fn = sum(value.get("biological_class") == label and not any(row["contig_id"] == contig and row["predicted_class"] == label for row in predictions) for contig, value in truth.items())
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        result.update({f"{label}_precision": round(precision, 6), f"{label}_recall": round(recall, 6), f"{label}_f1": round(f1, 6), f"{label}_truth_contigs": sum(value.get("biological_class") == label for value in truth.values())})
        if label in assessed:
            f1s.append(f1)
    result["macro_f1"] = round(sum(f1s) / len(f1s), 6) if f1s else ""
    result["uncertain_call_fraction"] = round(int(result["uncertain_calls"]) / len(predictions), 6) if predictions else 0.0
    return result


def file_identity(path: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path.resolve()), "sha256": digest.hexdigest(), "bytes": path.stat().st_size}


def build_report(results_dir: Path, manifest_rows: list[dict[str, str]]) -> Path:
    """Build a self-contained, community-specific dashboard.

    It deliberately parallels the isolate dashboard's discoverability and
    artifact access, but never borrows its reference-coordinate or operational
    recommendation claims.
    """
    inputs = {
        "reconstruction": results_dir / "metagenomics.summary.tsv",
        "bins": results_dir / "metagenomics.bin_metrics.tsv",
        "classification": results_dir / "metagenomics.classification_metrics.tsv",
        "evidence": results_dir / "metagenomics.mobilome_evidence.tsv",
    }
    data = {key: read_tsv(path) if path.is_file() else [] for key, path in inputs.items()}
    context_fields = ("information_regime", "truth_status", "input_read_technology", "preprocessing_profile",
                      "assembly_profile", "assembly_profile_version", "coassembly_id", "source_study",
                      "community_complexity", "phage_burden", "contamination_level", "host_assignment_evidence",
                      "reference_cluster_id")
    context = {row["community_id"]: {key: row.get(key, "") for key in context_fields} for row in manifest_rows}
    artifacts = []
    for path in sorted(results_dir.rglob("*")):
        if path.is_file() and path.name != "metagenomics.report.html":
            artifacts.append({"path": path.relative_to(results_dir).as_posix(), "bytes": path.stat().st_size})
    # This payload comes from cohort and tool artifacts. Escape HTML-significant
    # characters so a metadata value cannot terminate the self-contained script.
    payload = json.dumps({**data, "context": context, "artifacts": artifacts}, separators=(",", ":"))
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    document = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PlasBench metagenomic community dashboard</title><style>
:root{{--ink:#172d27;--muted:#5f7169;--paper:#f4f7f4;--card:#fff;--line:#d8e2db;--green:#176347;--mint:#e4f1e9;--amber:#a8660b;--red:#a63d32;--blue:#28619a}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 Georgia,serif}}header{{background:linear-gradient(120deg,#123b31,#176347 64%,#2f8061);color:#fff;padding:48px max(24px,calc((100vw - 1360px)/2))}}header h1,h2,h3,button,select,input,th,.nav,.metric{{font-family:Arial,sans-serif}}header h1{{margin:0;font-size:clamp(28px,5vw,48px);letter-spacing:-.04em}}header p{{margin:7px 0 0;color:#d8eee3}}main{{max-width:1360px;margin:auto;padding:25px}}.nav{{position:sticky;top:0;z-index:5;display:flex;gap:4px;padding:7px;background:#fff;border:1px solid var(--line);overflow:auto}}.nav a{{padding:7px 11px;white-space:nowrap;color:var(--muted);font:bold 12px Arial;text-decoration:none}}section{{margin:30px 0;scroll-margin-top:60px}}h2{{font-size:22px;margin:0 0 4px}}.lead,.muted{{color:var(--muted)}}.notice{{border-left:6px solid var(--amber);background:#fff4da;padding:16px 20px;margin:20px 0}}.metrics{{display:grid;grid-template-columns:repeat(5,minmax(145px,1fr));gap:11px}}.metric,.panel,.chart{{background:var(--card);border:1px solid var(--line);padding:15px;overflow:auto}}.metric{{border-top:4px solid var(--green)}}.metric small{{display:block;font:10px Arial;color:var(--muted);letter-spacing:.08em;text-transform:uppercase}}.metric strong{{display:block;font-size:27px;margin-top:4px}}.controls{{display:flex;flex-wrap:wrap;gap:10px;align-items:end;margin:14px 0}}label{{font:12px Arial;color:var(--muted);display:grid;gap:4px}}select,input,button{{padding:7px;border:1px solid var(--line);background:#fff}}button{{font-weight:bold;cursor:pointer}}table{{border-collapse:collapse;width:100%;min-width:740px;font:12px Arial}}th{{padding:9px;text-align:left;background:#ebf2ed;cursor:pointer;text-transform:uppercase;font-size:10px;letter-spacing:.05em}}td{{padding:8px;border-top:1px solid var(--line);white-space:nowrap}}tr:hover td{{background:#f4faf6}}.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}.bar-row{{display:grid;grid-template-columns:150px 1fr 56px;gap:8px;align-items:center;font:12px Arial;margin:8px 0}}.bar{{height:16px;background:#e8eeea;overflow:hidden}}.bar i{{display:block;height:100%;background:var(--green)}}.heatmap td{{text-align:center;font-weight:bold;cursor:pointer}}.heatmap td.na{{background:#edf0ee;color:#78837d}}.legend{{display:flex;gap:14px;flex-wrap:wrap;font:12px Arial;margin:9px 0}}.legend i{{width:12px;height:12px;display:inline-block;margin-right:4px}}.composition{{height:18px;display:flex;background:#e8eeea;min-width:200px}}.composition i{{display:block;height:100%}}.composition .p{{background:#1b7b56}}.composition .c{{background:#b34a3c}}.composition .v{{background:#3d75ab}}.composition .u{{background:#a96b0c}}.detail{{min-height:80px;white-space:pre-wrap;font:13px ui-monospace,monospace;background:#11241e;color:#e1f4e7;padding:14px}}.download{{display:inline-block;background:var(--green);color:#fff!important;padding:7px 10px;text-decoration:none;font:bold 12px Arial}}.file-list{{columns:2;column-gap:24px;padding-left:18px;font:13px Arial}}.file-list li{{break-inside:avoid;padding:3px}}.file-list a{{color:var(--green)}}@media(max-width:850px){{.metrics{{grid-template-columns:repeat(2,1fr)}}.grid2{{grid-template-columns:1fr}}main{{padding:16px}}.file-list{{columns:1}}}}</style></head><body><header><small>PlasBench · Separate metagenomic track</small><h1>Community plasmid evidence dashboard</h1><p>Truth-backed reconstruction and classification are compared only within the same information regime and evaluation type.</p></header><main><nav class="nav"><a href="#overview">Overview</a><a href="#performance">Performance</a><a href="#matrix">Community matrix</a><a href="#bins">Bin drilldown</a><a href="#evidence">Evidence</a><a href="#context">Provenance</a><a href="#files">Files</a><a href="#guide">Interpretation</a></nav><div class="notice"><strong>Decision boundary:</strong> a candidate bin is not a host assignment, closed plasmid, or clinical confirmation. Mobilome annotations are contextual evidence only. Host linkage needs independent long-read, Hi-C, methylation, or validated co-abundance evidence.</div><section id="overview"><h2>Run overview</h2><p class="lead">Filter every interactive view below. CSV export contains exactly the currently visible reconstruction/classification observations.</p><div class="controls"><label>Information regime<select id="regime"><option value="">All</option></select></label><label>Tool<select id="tool"><option value="">All</option></select></label><label>Evaluation<select id="kind"><option value="">All</option><option value="reconstruction">Reconstruction</option><option value="classification">Classification</option></select></label><button id="export" type="button">Export filtered CSV</button><span id="count" class="muted"></span></div><div id="metrics" class="metrics"></div></section><section id="performance"><h2>Method performance</h2><p class="lead">Bars report mean values across the filtered truth-backed results. Reconstruction and classification are intentionally not pooled into one rank.</p><div class="grid2"><div class="chart"><h3>Reconstruction: mean bin F1 by tool</h3><div id="reconstruction-bars"></div></div><div class="chart"><h3>Classification: mean macro F1 by tool</h3><div id="classification-bars"></div></div></div></section><section id="matrix"><h2>Community × tool matrix</h2><p class="lead">Click a cell to set the drilldown. Green is higher F1; grey means no comparable truth-backed result, not poor performance.</p><div class="legend"><span><i style="background:#edf0ee"></i>No result</span><span><i style="background:#dbeee2"></i>Lower score</span><span><i style="background:#176347"></i>Higher score</span></div><div class="panel" id="heatmap"></div></section><section id="bins"><h2>Bin and classification drilldown</h2><div class="controls"><label>Community<select id="community"></select></label><label>Selected tool<select id="detail-tool"></select></label></div><div id="selection-note" class="muted"></div><div class="panel"><h3>Predicted-bin composition</h3><div id="bin-table"></div></div><div class="panel"><h3>Three-class calls</h3><div id="class-table"></div></div><h3>Selected record</h3><div id="detail" class="detail">Select a matrix cell or choose a community and tool.</div></section><section id="evidence"><h2>Mobilome evidence timeline</h2><p class="lead">Supporting annotations may include plasmid, phage, ICE/IME, insertion-sequence, AMR, virulence, and BGC features. They never alter benchmark truth scores.</p><div class="panel" id="evidence-table"></div></section><section id="context"><h2>Community and upstream-processing provenance</h2><p class="lead">Preprocessing and assembly settings explain what each method received; they are not method-quality metrics.</p><div class="panel" id="context-table"></div></section><section id="files"><h2>Artifact explorer</h2><p class="lead">Download normalized scores, evidence, manifests, and adapter artifacts directly from this result directory.</p><ul id="files-list" class="file-list"></ul></section><section id="guide"><h2>Reading this report</h2><div class="grid2"><div class="panel"><h3>Reconstruction</h3><p><strong>Bin precision</strong> is the fraction of a predicted bin belonging to its globally matched truth plasmid. <strong>Bin recall</strong> is the recovered fraction of that truth plasmid. Split/merge and chromosome/virus contamination remain visible rather than being hidden by F1.</p></div><div class="panel"><h3>Classification</h3><p><strong>Macro F1</strong> averages the biological classes actually supported by the classifier. A two-class classifier is never credited for phage/virus performance it does not provide. Uncertain calls are retained.</p></div><div class="panel"><h3>Operational evidence</h3><p>For truth-unavailable communities, PlasBench preserves outputs and contextual evidence for review but does not rank tools, recommend methods, or assert host linkage.</p></div><div class="panel"><h3>Comparability</h3><p>Do not compare results across different information regimes, assemblies, read technologies, database releases, or unreviewed truth sources as if they were one leaderboard.</p></div></div></section></main><script>const DATA={payload};const $=id=>document.getElementById(id),esc=x=>String(x??'').replace(/[&<>\"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]),num=x=>Number(x||0),mean=(a,k)=>a.length?a.reduce((s,x)=>s+num(x[k]),0)/a.length:NaN,opts=(id,values)=>$(id).innerHTML='<option value="">All</option>'+values.map(v=>`<option value="${{esc(v)}}">${{esc(v)}}</option>`).join('');const all=[...DATA.reconstruction.map(x=>({{...x,evaluation:'reconstruction',metric:'bin_f1'}})),...DATA.classification.map(x=>({{...x,evaluation:'classification',metric:'macro_f1'}}))];opts('regime',[...new Set(Object.values(DATA.context).map(x=>x.information_regime).filter(Boolean))].sort());opts('tool',[...new Set(all.map(x=>x.tool))].sort());opts('community',Object.keys(DATA.context).sort());function table(rows,keys){if(!rows.length)return '<p class="muted">No comparable records for this filter.</p>';keys=keys||Object.keys(rows[0]);return '<table><thead><tr>'+keys.map(k=>`<th>${{esc(k.replaceAll('_',' '))}}</th>`).join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+keys.map(k=>`<td>${{esc(r[k])}}</td>`).join('')+'</tr>').join('')+'</tbody></table>'}function filtered(){{let r=$('regime').value,t=$('tool').value,k=$('kind').value;return all.filter(x=>(!r||DATA.context[x.community_id]?.information_regime===r)&&(!t||x.tool===t)&&(!k||x.evaluation===k))}}function bars(rows,key,target){{let groups={{}};rows.forEach(x=>{{if(x.evaluation===key)(groups[x.tool]??=[]).push(x)}});let ranked=Object.entries(groups).map(([tool,a])=>({{tool,value:mean(a,target)}})).sort((a,b)=>b.value-a.value);$(key+'-bars').innerHTML=ranked.length?ranked.map(x=>`<div class="bar-row"><span>${{esc(x.tool)}}</span><span class="bar"><i style="width:${{Math.max(0,Math.min(100,x.value*100))}}%"></i></span><strong>${{x.value.toFixed(3)}}</strong></div>`).join(''):'<p class="muted">No comparable results.</p>'}}function matrix(rows){{let comm=[...new Set(rows.map(x=>x.community_id))].sort(),tools=[...new Set(rows.map(x=>x.tool))].sort();let map=new Map(rows.map(x=>[x.community_id+'|'+x.tool,x]));$('heatmap').innerHTML=comm.length?'<table class="heatmap"><thead><tr><th>Community</th>'+tools.map(t=>`<th>${{esc(t)}}</th>`).join('')+'</tr></thead><tbody>'+comm.map(c=>'<tr><th>'+esc(c)+'</th>'+tools.map(t=>{{let x=map.get(c+'|'+t),v=x?num(x.metric==='bin_f1'?x.bin_f1:x.macro_f1):null;return `<td class="${{v===null?'na':''}}" data-c="${{esc(c)}}" data-t="${{esc(t)}}" style="background:${{v===null?'':`hsl(${{142}},${{Math.round(35+v*35)}}%,${{Math.round(96-v*55)}}%)`}}">${{v===null?'—':v.toFixed(2)}}</td>`}}).join('')+'</tr>').join('')+'</tbody></table>':'<p class="muted">No truth-backed observations.</p>';document.querySelectorAll('#heatmap td[data-c]').forEach(x=>x.onclick=()=>{{$('community').value=x.dataset.c;$('detail-tool').value=x.dataset.t;drill()}})}function drill(){{let c=$('community').value,t=$('detail-tool').value;$('selection-note').textContent=c&&t?`Showing ${{c}} / ${{t}}.`:'';let bins=DATA.bins.filter(x=>x.community_id===c&&x.tool===t);$('bin-table').innerHTML=table(bins.map(x=>({{...x,composition:`P ${{x.true_plasmid_contigs}} · C ${{x.chromosome_contigs}} · V ${{x.virus_contigs}} · U ${{x.unknown_contigs}}`}})),['predicted_bin_id','matched_truth_bin_id','contigs','bin_precision','bin_recall','bin_f1','chromosome_contamination_fraction','virus_contamination_fraction','composition']);let calls=DATA.classification.filter(x=>x.community_id===c&&x.tool===t);$('class-table').innerHTML=table(calls,['supported_classes','assessed_classes','macro_f1','plasmid_f1','chromosome_f1','virus_f1','uncertain_call_fraction','classified_contigs']);let row=all.find(x=>x.community_id===c&&x.tool===t);$('detail').textContent=row?JSON.stringify(row,null,2):'No comparable truth-backed metric for this selection. Check provenance and raw artifacts.'}}function render(){{let rows=filtered(),rec=rows.filter(x=>x.evaluation==='reconstruction'),cls=rows.filter(x=>x.evaluation==='classification');$('count').textContent=`${{rows.length}} visible comparable observation(s)`;$('metrics').innerHTML=[['Reconstruction results',rec.length],['Mean bin F1',Number.isNaN(mean(rec,'bin_f1'))?'n/a':mean(rec,'bin_f1').toFixed(3)],['Classification results',cls.length],['Mean macro F1',Number.isNaN(mean(cls,'macro_f1'))?'n/a':mean(cls,'macro_f1').toFixed(3)],['Evidence features',DATA.evidence.length]].map(x=>`<article class="metric"><small>${{x[0]}}</small><strong>${{x[1]}}</strong></article>`).join('');bars(rows,'reconstruction','bin_f1');bars(rows,'classification','macro_f1');matrix(rows);$('evidence-table').innerHTML=table(DATA.evidence.filter(x=>!$('regime').value||DATA.context[x.community_id]?.information_regime===$('regime').value));let ctx=Object.entries(DATA.context).map(([community_id,x])=>({{community_id,...x}})).filter(x=>!$('regime').value||x.information_regime===$('regime').value);$('context-table').innerHTML=table(ctx);$('files-list').innerHTML=DATA.artifacts.map(x=>`<li><a href="${{esc(x.path)}}" download>${{esc(x.path)}}</a> <small>${{(x.bytes/1024).toFixed(1)}} KiB</small></li>`).join('')||'<li>No generated artifacts yet.</li>';drill()}}['regime','tool','kind'].forEach(id=>$(id).onchange=render);$('community').onchange=drill;$('detail-tool').onchange=drill;$('export').onclick=()=>{{let rows=filtered(),keys=['community_id','tool','evaluation','information_regime','truth_status','bin_f1','macro_f1'];let text=keys.join(',')+'\\n'+rows.map(r=>keys.map(k=>JSON.stringify(r[k]??'')).join(',')).join('\\n')+'\\n';let a=document.createElement('a');a.href=URL.createObjectURL(new Blob([text],{{type:'text/csv'}}));a.download='plasbench-metagenomics-filtered.csv';a.click();URL.revokeObjectURL(a.href)}};render();</script></body></html>'''
    # The template is intentionally a normal string: the JavaScript uses many
    # braces, and only the escaped JSON payload is substituted at the end.
    # Expand template escapes before inserting JSON so cohort metadata is preserved verbatim.
    document = document.replace("{{", "{").replace("}}", "}").replace("{payload}", payload)
    document = document.replace(
        "<title>PlasBench metagenomic community dashboard</title>",
        "<title>PlasBench: A Reproducible, Evidence-Calibrated Benchmarking Framework for Plasmid Reconstruction Tools · Metagenomic dashboard</title>",
    )
    # The detailed drilldown has its own tool selector; populate it from the
    # same declared result universe as the top-level filter.
    document = document.replace("opts('tool',[...new Set(all.map(x=>x.tool))].sort());", "opts('tool',[...new Set(all.map(x=>x.tool))].sort());opts('detail-tool',[...new Set(all.map(x=>x.tool))].sort());")
    report = results_dir / "metagenomics.report.html"
    report.write_text(document, encoding="utf-8")
    return report


def run_score(manifest: Path, predictions_dir: Path, out_dir: Path) -> int:
    rows, errors = validate_manifest(manifest, require_truth=True)
    if errors:
        print("METAGENOMIC MANIFEST INVALID:", file=sys.stderr); print("\n".join(f"  - {error}" for error in errors), file=sys.stderr); return 2
    summaries: list[dict[str, object]] = []; bin_rows: list[dict[str, object]] = []; classifications: list[dict[str, object]] = []
    truth_backed_communities = 0
    normalized_prediction_files = 0
    for community in sorted({row["community_id"] for row in rows}):
        community_rows = [row for row in rows if row["community_id"] == community]
        statuses = {row["truth_status"] for row in community_rows}
        if statuses == {"unavailable"}:
            print(f"[metagenomics] {community}: truth unavailable; preserved but not ranked")
            continue
        truth_backed_communities += 1
        truth: dict[str, dict[str, str]] = {}
        for row in community_rows:
            truth_path = resolve(manifest, row.get("truth_contigs_tsv", ""))
            if truth_path:
                for contig_id, value in validate_truth(truth_path).items():
                    if contig_id in truth and truth[contig_id] != value:
                        raise ValueError(f"{community}: conflicting truth labels for contig {contig_id} across community tables")
                    truth[contig_id] = value
        for pred_path in sorted(predictions_dir.glob(f"*/{community}.bins.tsv")):
            normalized_prediction_files += 1
            prediction = validate_prediction(pred_path)
            tool = pred_path.parent.name
            details, summary = score_prediction(prediction, truth, community, tool)
            summary["information_regime"] = community_rows[0]["information_regime"]
            summary["truth_status"] = ",".join(sorted(statuses))
            summaries.append(summary); bin_rows.extend(details)
            print(f"[metagenomics] scored {community}/{tool}: bin F1={summary['bin_f1']}")
        for pred_path in sorted(predictions_dir.glob(f"*/{community}.classification.tsv")):
            normalized_prediction_files += 1
            prediction = validate_classification(pred_path)
            tool = pred_path.parent.name
            classification = score_classification(prediction, truth, community, tool)
            classification["information_regime"] = community_rows[0]["information_regime"]
            classification["truth_status"] = ",".join(sorted(statuses))
            classifications.append(classification)
            print(f"[metagenomics] scored {community}/{tool}: classifier macro F1={classification['macro_f1']}")
    if truth_backed_communities and not normalized_prediction_files:
        print("METAGENOMIC SCORING FAILED: no normalized prediction tables were found for any truth-backed community.", file=sys.stderr)
        print("Expected <predictions-dir>/<tool>/<community>.bins.tsv or .classification.tsv; use normalize-meta-classifier for supported classifier output.", file=sys.stderr)
        return 2
    summary_fields = ["community_id", "tool", "information_regime", "truth_status", "predicted_bins", "truth_plasmid_bins", "matched_bins", "bin_precision", "bin_recall", "bin_f1", "split_truth_bins", "merge_predicted_bins", "unmatched_predicted_bins", "chromosome_contamination_fraction", "virus_contamination_fraction", "ambiguous_contigs", "abstained_contigs"]
    bin_fields = ["community_id", "tool", "predicted_bin_id", "matched_truth_bin_id", "contigs", "true_plasmid_contigs", "chromosome_contigs", "virus_contigs", "unknown_contigs", "bin_precision", "bin_recall", "bin_f1", "chromosome_contamination_fraction", "virus_contamination_fraction", "ambiguous_contigs", "abstained_contigs", "mean_path_confidence", "declared_graph_paths"]
    write_tsv(out_dir / "metagenomics.summary.tsv", summaries, summary_fields)
    write_tsv(out_dir / "metagenomics.bin_metrics.tsv", bin_rows, bin_fields)
    classification_fields = ["community_id", "tool", "evaluation_type", "information_regime", "truth_status", "supported_classes", "assessed_classes", "classified_contigs", "uncertain_calls", "uncertain_call_fraction", "macro_f1", "plasmid_precision", "plasmid_recall", "plasmid_f1", "plasmid_truth_contigs", "chromosome_precision", "chromosome_recall", "chromosome_f1", "chromosome_truth_contigs", "virus_precision", "virus_recall", "virus_f1", "virus_truth_contigs"]
    write_tsv(out_dir / "metagenomics.classification_metrics.tsv", classifications, classification_fields)
    inputs = [file_identity(manifest)]
    for row in rows:
        for field in ("truth_contigs_tsv", "truth_bins_tsv", "mobilome_gff", "mobilome_report"):
            value = resolve(manifest, row.get(field, ""))
            if value and value.is_file() and str(value.resolve()) not in {entry["path"] for entry in inputs}:
                inputs.append(file_identity(value))
    manifest_data = {"schema_version": 2, "mode": "metagenomics", "created_at": datetime.now(timezone.utc).isoformat(), "input_manifest": str(manifest.resolve()), "input_identities": inputs, "prediction_directory": str(predictions_dir.resolve()), "communities": sorted({row["community_id"] for row in rows}), "community_metadata": rows, "scored_reconstruction_results": len(summaries), "scored_classification_results": len(classifications), "safeguards": ["No isolate score reuse", "Rank only within information regime and evaluation type", "No host-linkage inference", "Mobilome evidence is not truth", "No recommendation from unvalidated/mock-only evidence"]}
    (out_dir / "metagenomics.run_manifest.json").write_text(json.dumps(manifest_data, indent=2) + "\n", encoding="utf-8")
    report = build_report(out_dir, rows)
    print(f"[metagenomics] report ready: {report.resolve()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Graph-aware metagenomic plasmid benchmark.")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="Validate a community manifest and declared files.")
    validate.add_argument("--manifest", type=Path, required=True)
    validate.add_argument("--release-ready", action="store_true", help="Require provenance fields needed before a public, truth-backed release.")
    score = sub.add_parser("score", help="Score normalized tool bin tables against declared community truth.")
    score.add_argument("--manifest", type=Path, required=True); score.add_argument("--predictions-dir", type=Path, required=True); score.add_argument("--out-dir", type=Path, required=True)
    report = sub.add_parser("report", help="Rebuild the dedicated metagenomics HTML report.")
    report.add_argument("--manifest", type=Path, required=True); report.add_argument("--results-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "validate":
        _, errors = validate_manifest(args.manifest, release_ready=args.release_ready)
        if errors:
            print("METAGENOMIC MANIFEST INVALID:", file=sys.stderr); print("\n".join(f"  - {error}" for error in errors), file=sys.stderr); return 2
        print("METAGENOMIC MANIFEST VALID"); return 0
    if args.command == "score":
        try:
            return run_score(args.manifest, args.predictions_dir, args.out_dir)
        except (OSError, ValueError) as exc:
            print(f"METAGENOMIC SCORING FAILED: {exc}", file=sys.stderr)
            return 2
    rows, errors = validate_manifest(args.manifest)
    if errors:
        print("METAGENOMIC MANIFEST INVALID:", file=sys.stderr); print("\n".join(f"  - {error}" for error in errors), file=sys.stderr); return 2
    print(build_report(args.results_dir, rows)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
