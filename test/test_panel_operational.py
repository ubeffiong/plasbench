#!/usr/bin/env python3
"""Panel operational items: the assembly QC gate (D13) and the recommendation
floor (D11).

Gate fixture: a clean assembly (two 20 kb contigs at 50% GC) passes; a mixed one
(20 kb at 30% GC and 20 kb at 70% GC) has a 0.40 GC spread > 0.12 -> flagged;
an assembly of short contigs only is not_evaluable for GC; a 9 Mb assembly is
flagged for size.
Floor: a scope whose best tool has mean F1 0.30 gets no primary recommendation
and the reason says so; at 0.0 floor the same tool is recommended.
"""
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import assembly_qc_gate as gate  # noqa: E402


def seq(n, gc):
    g = int(n * gc)
    return "G" * (g // 2) + "C" * (g - g // 2) + "A" * ((n - g) // 2) + "T" * (n - g - (n - g) // 2)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for name, records in (("clean", [seq(20000, 0.5), seq(20000, 0.5)]),
                              ("mixed", [seq(20000, 0.3), seq(20000, 0.7)]),
                              ("short", [seq(5000, 0.5)] * 3)):
            (tmp / name).mkdir()
            (tmp / name / "contigs.fasta").write_text("".join(f">c{i}\n{s}\n" for i, s in enumerate(records)))
        out = tmp / "qc.tsv"
        subprocess.run([sys.executable, str(ROOT / "python" / "assembly_qc_gate.py"), "--data-dir", str(tmp),
                        "--out", str(out)], check=True, capture_output=True)
        with open(out, newline="") as handle:
            rows = {r["sample"]: r for r in csv.DictReader(handle, delimiter="\t")}
        assert rows["clean"]["status"] == "pass", rows["clean"]
        assert rows["mixed"]["status"] == "flagged" and "gc_spread 0.400" in rows["mixed"]["reasons"], rows["mixed"]
        assert rows["short"]["status"] == "not_evaluable", rows["short"]
        big = gate.assess("big", str(tmp / "clean" / "contigs.fasta"), max_size_mb=0.03, max_gc_spread=0.12,
                          min_contig_length=10000)
        assert big["status"] == "flagged" and big["reasons"].startswith("assembly_size"), big
        print("  PASS: clean passes, two-GC mixture flagged (spread 0.40), short-only not_evaluable, size flagged")

    import select_operational_method as som
    from collections import Counter
    rows = [som.annotate({"sample": sample, "tool": "weak", "analysis_track": "short_read", "f1": "0.30",
                          "precision": "0.3", "recall": "0.3"}, {}) for sample in ("s1", "s2", "s3")]
    statuses = {"weak": {"counts": Counter(), "runtime_seconds": [], "peak_rss_kb": []}}
    with tempfile.TemporaryDirectory() as tmp:
        try:
            recs, written = som.write_recommendations(rows, statuses, 3, Path(tmp) / "r.tsv", 1, 0.1,
                                                      min_expected_score=0.40)
        except Exception as exc:  # the row shape is shared with selection tests; surface a clear error
            raise AssertionError(f"write_recommendations rejected the fixture: {exc}")
        assert recs[("overall", "all")] is None, recs
        overall = next(r for r in written if r["scope"] == "overall" and r["tool"] == "weak")
        assert overall["recommendation"] == "none" and "no tool expected" in overall["reason"], overall
        recs, _ = som.write_recommendations(rows, statuses, 3, Path(tmp) / "r2.tsv", 1, 0.1, min_expected_score=0.0)
        assert recs[("overall", "all")] == "weak", recs
    print("  PASS: best expected F1 0.30 < 0.40 -> no recommendation, reason stated; floor 0 -> recommended")
    print("ALL PANEL OPERATIONAL TESTS PASSED")


if __name__ == "__main__":
    main()
