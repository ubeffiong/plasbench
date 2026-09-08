#!/usr/bin/env python3
"""Regression for optional evidence validation and its claim boundary."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "python" / "validate_orthogonal_evidence.py"


def main():
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        evidence = temp / "evidence.tsv"
        evidence.write_text("sample_id\tevidence_type\tevidence_status\tevidence_reference\tnotes\n"
                            "s1\ttargeted_pcr\tsupportive\tDOI:10.1/example\tcontext only\n"
                            "s1\tconjugation\tconfirmed\tLAB-123\ttransfer assay\n", encoding="utf-8")
        out = temp / "summary.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "--evidence", str(evidence), "--out", str(out)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        summary = json.loads(out.read_text(encoding="utf-8"))
        assert summary["records"] == 2 and "does not change benchmark scores" in summary["claim_boundary"]
        broken = temp / "broken.tsv"
        broken.write_text("sample_id\tevidence_type\tevidence_status\tevidence_reference\ns1\tmade_up\tconfirmed\tX\n", encoding="utf-8")
        bad = subprocess.run([sys.executable, str(SCRIPT), "--evidence", str(broken)], capture_output=True, text=True)
        assert bad.returncode != 0 and "unsupported evidence_type" in bad.stderr
    print("ORTHOGONAL EVIDENCE VALIDATION TEST PASSED")


if __name__ == "__main__": main()
