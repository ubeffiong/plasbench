#!/usr/bin/env python3
"""Regression check for bounded reference-coordinate visualization output."""
import json
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    sample = root / "results" / "sample1"
    sample.mkdir(parents=True)
    truth = root / "truth.tsv"
    truth.write_text("sequence_id\tmolecule_type\tlength\np1\tPLASMID\t1000\nchr\tCHROMOSOME\t2000\n", encoding="utf-8")
    reference = root / "reference.fna"
    reference.write_text(">p1\n" + "A" * 1000 + "\n>chr\n" + "C" * 2000 + "\n", encoding="utf-8")
    (sample / "pred_tool.plasmid.fasta").write_text(">q1\n" + "A" * 600 + "\n>q2\n" + "C" * 100 + "\n", encoding="utf-8")
    (sample / "tool.pred_vs_ref.paf").write_text(
        "q1\t600\t0\t600\t+\tp1\t1000\t100\t700\t590\t600\t60\tcg:Z:600M\n"
        "q2\t100\t0\t100\t-\tchr\t2000\t20\t120\t98\t100\t60\n", encoding="utf-8")
    out = sample / "visualization" / "alignment_blocks.json"
    subprocess.run(["python3", str(ROOT / "python" / "build_visualization_data.py"), "--truth", str(truth), "--reference", str(reference),
                    "--results-dir", str(root / "results"), "--sample", "sample1", "--max-blocks-per-tool", "10", "--out", str(out)], check=True)
    payload = json.loads(out.read_text(encoding="utf-8"))
    tool = payload["tools"]["tool"]
    assert payload["truth_plasmids"]["p1"]["length"] == 1000
    assert tool["plasmid_recovery"]["p1"]["covered_bp"] == 600
    assert tool["plasmid_recovery"]["p1"]["completeness"] == 0.6
    assert tool["chromosome_aligned_bp"] == 100
    assert tool["blocks"][0]["local_alignment"]["reference"] == "A" * 600
    assert "structural_concordance_proxy" in tool["structural_diagnostics"]

print("ALL VISUALIZATION DATA TESTS PASSED")
