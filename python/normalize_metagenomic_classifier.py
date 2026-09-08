#!/usr/bin/env python3
"""Normalize probability-bearing contig classifiers for the PlasBench meta track.

This is deliberately an import boundary, not an executor.  PlasBench does not
silently install or run legacy third-party runtimes.  The user runs a pinned
tool/container, then this command preserves the raw source and writes the
portable three-class contract consumed by ``metagenomics.py``.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path


FIELDS = ["contig_id", "predicted_class", "plasmid_probability", "chromosome_probability", "phage_probability", "uncertainty_status", "source_tool", "supported_classes"]


def normalize_id(value: str) -> str:
    """Match FASTA-style source headers to contig IDs without retaining prose."""
    return value.strip().lstrip(">").split()[0]


def number(value: str, label: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise ValueError(f"{label} is not numeric: {value!r}") from exc
    if not 0 <= result <= 1:
        raise ValueError(f"{label} must be between 0 and 1: {value!r}")
    return result


def read(path: Path, delimiter: str) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        if reader.fieldnames is None:
            raise ValueError(f"{path}: expected a header")
        return [{str(key): (value or "").strip() for key, value in row.items()} for row in reader]


def normalize_ppr_meta(rows: list[dict[str, str]], threshold: float) -> list[dict[str, object]]:
    required = {"Header", "phage_score", "chromosome_score", "plasmid_score", "Possible_source"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError("PPR-Meta input must have Header, phage_score, chromosome_score, plasmid_score, and Possible_source")
    result = []
    for row in rows:
        scores = {"plasmid": number(row["plasmid_score"], "plasmid_score"), "chromosome": number(row["chromosome_score"], "chromosome_score"), "virus": number(row["phage_score"], "phage_score")}
        best = max(scores, key=scores.get)
        uncertain = scores[best] < threshold or row["Possible_source"].strip().lower() == "uncertain"
        result.append({"contig_id": normalize_id(row["Header"]), "predicted_class": "uncertain" if uncertain else best, "plasmid_probability": scores["plasmid"], "chromosome_probability": scores["chromosome"], "phage_probability": scores["virus"], "uncertainty_status": "uncertain" if uncertain else "resolved", "source_tool": "ppr_meta", "supported_classes": "plasmid|chromosome|virus"})
    return result


def normalize_plasmidhunter(rows: list[dict[str, str]], threshold: float) -> list[dict[str, object]]:
    if not rows or "Probability of 1" not in rows[0]:
        raise ValueError("PlasmidHunter input must have a 'Probability of 1' column")
    result = []
    for row in rows:
        # pandas writes the contig id in an unnamed index column.  Accept a
        # named contig_id too so a user can make the source explicit.
        contig = row.get("contig_id") or row.get("") or row.get("Unnamed: 0") or next(iter(row.values()), "")
        plasmid = number(row["Probability of 1"], "Probability of 1")
        uncertain = max(plasmid, 1 - plasmid) < threshold
        result.append({"contig_id": normalize_id(contig), "predicted_class": "uncertain" if uncertain else ("plasmid" if plasmid >= 0.5 else "chromosome"), "plasmid_probability": plasmid, "chromosome_probability": round(1 - plasmid, 8), "phage_probability": 0.0, "uncertainty_status": "uncertain" if uncertain else "resolved", "source_tool": "plasmidhunter", "supported_classes": "plasmid|chromosome"})
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", choices=("ppr_meta", "plasmidhunter"), required=True)
    parser.add_argument("--input", type=Path, required=True, help="Raw classifier CSV/TSV output.")
    parser.add_argument("--out", type=Path, required=True, help="Normalized .classification.tsv output.")
    parser.add_argument("--threshold", type=float, default=0.5, help="Minimum winning probability for a resolved call.")
    args = parser.parse_args(argv)
    if not 0 <= args.threshold <= 1:
        parser.error("--threshold must be between 0 and 1")
    rows = read(args.input, "," if args.tool == "ppr_meta" else "\t")
    normalized = normalize_ppr_meta(rows, args.threshold) if args.tool == "ppr_meta" else normalize_plasmidhunter(rows, args.threshold)
    if any(not row["contig_id"] for row in normalized):
        raise ValueError("source output contains an empty contig identifier")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=FIELDS)
        writer.writeheader(); writer.writerows(normalized)
    print(f"[metagenomics] normalized {len(normalized)} {args.tool} calls to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
