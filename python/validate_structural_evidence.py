#!/usr/bin/env python3
"""Validate source-backed structural evidence without inferring biological closure."""
import argparse, csv, json
from pathlib import Path

REQUIRED = {"record_id", "evidence_type", "evidence_value", "evidence_source", "evidence_version"}
ALLOWED = {"closure", "replicon", "mob", "amr_context", "ml_probability"}
CLOSURE_SOURCES = {"long_read", "hybrid_assembly", "assembly_graph"}

def fasta_ids(path):
    return {line[1:].strip().split()[0] for line in path.read_text(encoding="utf-8").splitlines() if line.startswith(">")}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True); parser.add_argument("--pred-fasta", type=Path, required=True); parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(); pred_ids = fasta_ids(args.pred_fasta); errors, items, closure = [], [], []
    with args.evidence.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t"); fields = set(reader.fieldnames or [])
        if not REQUIRED.issubset(fields): errors.append("missing required columns: " + ", ".join(sorted(REQUIRED - fields)))
        for number, row in enumerate(reader, start=2):
            if row.get("record_id", "") not in pred_ids: errors.append(f"row {number}: record_id is absent from prediction FASTA")
            kind = row.get("evidence_type", "")
            if kind not in ALLOWED: errors.append(f"row {number}: unsupported evidence_type {kind!r}")
            if not row.get("evidence_source") or not row.get("evidence_version"): errors.append(f"row {number}: evidence_source and evidence_version are required")
            item = {key: row.get(key, "") for key in sorted(REQUIRED)}; item["closure_validated"] = False
            if kind == "closure":
                try: supported = int(row.get("supporting_reads", "")) > 0
                except ValueError: supported = False
                item["closure_validated"] = row.get("evidence_value", "").lower() in {"closed", "circular"} and row.get("evidence_source", "") in CLOSURE_SOURCES and supported
                if item["closure_validated"]: closure.append(item)
                else: errors.append(f"row {number}: closure needs closed/circular value, positive supporting_reads, and an accepted source")
            items.append(item)
    report = {"status": "validated" if not errors else "invalid", "errors": errors, "items": items, "validated_closure_items": closure, "meaning": "Validated closure evidence is source-backed provenance, not independent biological confirmation by PlasBench."}
    args.out.parent.mkdir(parents=True, exist_ok=True); args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if errors: raise SystemExit("Structural evidence invalid: " + "; ".join(errors))
    print(f"Validated structural evidence: {args.out}")

if __name__ == "__main__": main()
