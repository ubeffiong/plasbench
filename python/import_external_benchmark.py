#!/usr/bin/env python3
"""Archive external benchmark evidence without merging it into PlasBench scores.

This importer accepts TSV/CSV or a basic .xlsx worksheet, copies source files,
records SHA-256 digests, and writes a source-labelled evidence manifest. It
does not pretend that published, heterogeneous metrics are native PlasBench
scores; explicit metric harmonisation is a separate reviewed step.
"""
import argparse
import csv
import hashlib
import json
import shutil
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path


def column_index(reference):
    """Return a zero-based XLSX column index from an A1 cell reference."""
    value = 0
    for char in reference:
        if char.isalpha(): value = value * 26 + ord(char.upper()) - 64
        else: break
    return max(0, value - 1)


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""): h.update(block)
    return h.hexdigest()


def read_delimited(path):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t" if path.suffix.lower() == ".tsv" else ","))


def read_xlsx(path):
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(path) as book:
        shared = []
        if "xl/sharedStrings.xml" in book.namelist():
            root = ET.fromstring(book.read("xl/sharedStrings.xml"))
            shared = ["".join(node.itertext()) for node in root.findall(f"{ns}si")]
        sheets = [name for name in book.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")]
        if not sheets: raise ValueError("workbook has no worksheet")
        grid = []
        for row in ET.fromstring(book.read(sorted(sheets)[0])).iter(f"{ns}row"):
            values = []
            for cell in row.findall(f"{ns}c"):
                index = column_index(cell.get("r", "A1"))
                while len(values) <= index: values.append("")
                value = cell.findtext(f"{ns}v", default="")
                values[index] = shared[int(value)] if cell.get("t") == "s" and value else value
            grid.append(values)
    if not grid: return []
    headers = [value.strip() or f"column_{i + 1}" for i, value in enumerate(grid[0])]
    return [dict(zip(headers, row + [""] * (len(headers) - len(row)))) for row in grid[1:] if any(row)]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--predictions", required=True, type=Path, help="Published TSV, CSV, or XLSX predictions/metrics table.")
    ap.add_argument("--ani", type=Path, help="Optional ANI table retained as provenance evidence.")
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--source-repository", required=True)
    ap.add_argument("--source-revision", required=True, help="Immutable tag or commit, never a floating branch name.")
    ap.add_argument("--citation", required=True)
    args = ap.parse_args()
    if not args.predictions.is_file(): raise SystemExit(f"ERROR: missing predictions file: {args.predictions}")
    out = args.out_dir; raw = out / "raw"; raw.mkdir(parents=True, exist_ok=True)
    copied = []
    for source in (args.predictions, args.ani):
        if source:
            if not source.is_file(): raise SystemExit(f"ERROR: missing evidence file: {source}")
            destination = raw / source.name; shutil.copy2(source, destination)
            copied.append({"path": str(destination.relative_to(out)), "sha256": digest(destination)})
    parsed = read_xlsx(args.predictions) if args.predictions.suffix.lower() == ".xlsx" else read_delimited(args.predictions)
    if not parsed: raise SystemExit("ERROR: predictions table has no data rows")
    normalized = out / "external_predictions.source_schema.tsv"
    fields = sorted({key for row in parsed for key in row})
    with open(normalized, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t"); writer.writeheader(); writer.writerows(parsed)
    manifest = {"schema_version": "1.0", "source_repository": args.source_repository, "source_revision": args.source_revision,
                "citation": args.citation, "metric_status": "external_source_schema_only",
                "interpretation": "These rows are preserved for historical comparison and data-quality review. They are not merged into native PlasBench leaderboards or recommendation-model training until a reviewed metric mapping and compatible truth definition are supplied.",
                "records": len(parsed), "files": copied}
    (out / "external_benchmark.manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Imported {len(parsed)} external records into {out}; native leaderboard unchanged.")


if __name__ == "__main__":
    main()
