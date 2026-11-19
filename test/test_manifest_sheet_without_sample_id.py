#!/usr/bin/env python3
"""python/write_manifest.py writes a manifest even when the sample sheet is not a benchmark sheet.

Stage 6 on a copy of results_real_cohort1 (a results-only folder) crashed with KeyError 'sample_id': the sheet it was given had no sample_id column (an accession
ledger). A manifest must be written without truth checksums, with a warning that says why. Standard library only.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def run(sheet_bytes, tmp, name):
    sheet = tmp / f"{name}.tsv"
    sheet.write_bytes(sheet_bytes)
    out = tmp / f"{name}.json"
    done = subprocess.run([sys.executable, str(ROOT / "python" / "write_manifest.py"), "--project-root", str(ROOT), "--sample-sheet", str(sheet), "--data-dir", str(tmp / "data"),
                           "--results-dir", str(tmp / "results"), "--out", str(out)], capture_output=True, text=True, encoding="utf-8")
    return done, out


def main():
    tmp = Path(tempfile.mkdtemp())
    (tmp / "results").mkdir()
    (tmp / "data" / "A").mkdir(parents=True)
    (tmp / "data" / "A" / "truth.tsv").write_text("x\n", encoding="utf-8")
    done, out = run(b"accession\torganism\r\nSRR1\tE. coli\r\n", tmp, "ledger")
    check("a sheet with no sample_id column does not crash", done.returncode == 0, done.stderr[-300:])
    if out.is_file():
        manifest = json.loads(out.read_text(encoding="utf-8"))
        text = json.dumps(manifest)
        check("the manifest says why no truth checksums were recorded", "no sample_id column" in text)
    else:
        check("the manifest was written", False)
    done, out = run(b"sample_id\torganism\r\nA\tE. coli\r\nB\tE. coli\r\n", tmp, "real")
    check("a real sheet (CRLF) still records the truth table of the sample that has one", done.returncode == 0 and out.is_file() and '"A"' in out.read_text(encoding="utf-8"), done.stderr[-300:])
    done, out = run(b"", tmp, "empty")
    check("an empty sheet does not crash", done.returncode == 0, done.stderr[-300:])
    print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL PASS")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
