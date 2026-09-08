#!/usr/bin/env python3
"""Regression: candidate datasets preserve missing bin labels honestly."""
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "python" / "build_candidate_quality_dataset.py"


def write(path, fields, values):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t"); writer.writeheader(); writer.writerows(values)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp); scores, samples, results = tmp / "scores.tsv", tmp / "samples.tsv", tmp / "results"
        write(scores, ["sample", "tool", "f1", "precision", "recall", "analysis_track"], [{"sample":"s1","tool":"mob","f1":"0.9","precision":"0.8","recall":"1","analysis_track":"short_read"}])
        write(samples, ["sample_id", "organism", "source_study"], [{"sample_id":"s1","organism":"E. coli","source_study":"P1"}])
        write(results / "s1" / "mob" / "pred_mob.bins.tsv", ["bin", "contig"], [{"bin":"b1","contig":"c1"}, {"bin":"b2","contig":"c2"}])
        subprocess.run([sys.executable, str(SCRIPT), "--scores", str(scores), "--sample-sheet", str(samples), "--results-dir", str(results), "--out-prefix", str(tmp / "benchmark")], check=True)
        with open(tmp / "benchmark.candidate_labels.tsv", newline="", encoding="utf-8") as handle: labels = list(csv.DictReader(handle, delimiter="\t"))
        assert {row["candidate_id"] for row in labels} == {"b1", "b2"}
        assert all(row["label_scope"] == "unavailable_for_bin" and not row["f1"] for row in labels)
        print("bin candidates retain no fabricated tool-level labels -> PASS")
    print("ALL CANDIDATE QUALITY DATASET TESTS PASSED")


if __name__ == "__main__": main()
