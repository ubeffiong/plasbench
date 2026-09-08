#!/usr/bin/env python3
"""Import MAP-style mobilome annotations as non-scoring PlasBench evidence."""
from __future__ import annotations

import argparse
import csv
import gzip
from pathlib import Path
from urllib.parse import unquote


FIELDS = ["community_id", "sample_id", "contig_id", "feature_type", "start", "end", "strand", "feature_id", "product", "evidence_source", "evidence_role", "raw_attributes"]


def attributes(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in value.split(";"):
        if "=" in item:
            key, raw = item.split("=", 1)
            result[key] = unquote(raw)
    return result


def evidence_role(feature_type: str, attrs: dict[str, str]) -> str:
    text = " ".join([feature_type, *attrs.values()]).lower()
    if "plasmid" in text: return "plasmid_context"
    if "phage" in text or "virus" in text or "prophage" in text: return "phage_context"
    if any(item in text for item in ("integron", "integrase", "ice", "ime", "transpos", "insertion sequence")): return "mobile_element_context"
    if any(item in text for item in ("amr", "resistance", "beta-lactam", "carbapenem", "antibiotic")): return "amr_context"
    if "virulence" in text or "toxin" in text: return "virulence_context"
    if "biosynthetic" in text or "bgc" in text: return "bgc_context"
    return "functional_context"


def gff_rows(path: Path, community: str, sample: str) -> list[dict[str, str]]:
    opener = gzip.open if path.suffix == ".gz" else open
    rows = []
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"): continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 9: continue
            contig, source, feature, start, end, _, strand, _, raw = parts
            attrs = attributes(raw)
            rows.append({"community_id": community, "sample_id": sample, "contig_id": contig, "feature_type": feature, "start": start, "end": end, "strand": strand, "feature_id": attrs.get("ID", attrs.get("Name", "")), "product": attrs.get("product", attrs.get("Name", attrs.get("description", ""))), "evidence_source": source or "MAP", "evidence_role": evidence_role(feature, attrs), "raw_attributes": raw})
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gff", type=Path, required=True, help="MAP sample_mobilome.gff.gz or compatible GFF3.")
    parser.add_argument("--community", required=True)
    parser.add_argument("--sample", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    rows = gff_rows(args.gff, args.community, args.sample)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_header = not args.out.exists() or args.out.stat().st_size == 0
    with args.out.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=FIELDS)
        if write_header: writer.writeheader()
        writer.writerows(rows)
    print(f"[metagenomics] imported {len(rows)} mobilome evidence features to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
