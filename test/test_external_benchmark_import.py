#!/usr/bin/env python3
"""Regression: external evidence is archived, source-labelled and isolated."""
import csv
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "python" / "import_external_benchmark.py"


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp); book, out = tmp / "input.xlsx", tmp / "imported"
        with zipfile.ZipFile(book, "w") as z:
            z.writestr("xl/sharedStrings.xml", '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>tool</t></si><si><t>score</t></si><si><t>A</t></si></sst>')
            z.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1" t="s"><v>1</v></c></row><row r="2"><c r="A2" t="s"><v>2</v></c><c r="C2"><v>0.9</v></c></row></sheetData></worksheet>')
        subprocess.run([sys.executable, str(SCRIPT), "--predictions", str(book), "--out-dir", str(out), "--source-repository", "https://example.test/repo", "--source-revision", "abc123", "--citation", "Example 2026"], check=True)
        with open(out / "external_predictions.source_schema.tsv", newline="", encoding="utf-8") as handle: rows = list(csv.DictReader(handle, delimiter="\t"))
        assert rows == [{"tool":"A", "column_2":"", "score":"0.9"}], rows
        manifest = json.loads((out / "external_benchmark.manifest.json").read_text(encoding="utf-8"))
        assert manifest["metric_status"] == "external_source_schema_only" and manifest["files"][0]["sha256"]
        print("external XLSX is source-labelled, checksummed, and not normalized into native scores -> PASS")
    print("ALL EXTERNAL BENCHMARK IMPORT TESTS PASSED")


if __name__ == "__main__": main()
