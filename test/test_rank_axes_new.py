#!/usr/bin/env python3
"""New rank-sensitivity axes (python/rank_sensitivity.py): label schemes, min contig
length, micro averaging, public/in-house and grade-C exclusion.

Fixture (two isolates, identical): truth chr 10 kb CHROMOSOME, chromid 2 kb
CHROMOSOME, p1 1 kb PLASMID. Tool A predicts p1 only; tool B predicts p1 and the
chromid, plus a 400 bp record on the chromosome.
  ncbi (primary)   A: F1 1.0;  B: TP 1000, FP 2400 -> F1 0.4545   -> A first
  nonchromosomal   chromid becomes a plasmid: A recall 1/3 -> F1 0.5;
                   B: TP 3000, FP 400 -> F1 0.9375                 -> B first, tau -1
  min_contig=500   B's 400 bp record ignored: B TP 1000, FP 2000 -> 0.5
s1 has a sequence report (public), s2 does not (in-house); s2 is grade C.
"""
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        results, data = tmp / "results", tmp / "data"
        scores = "sample\ttool\tanalysis_track\tf1\tmcc\n"
        for sample in ("s1", "s2"):
            d, r = data / sample, results / sample
            d.mkdir(parents=True)
            r.mkdir(parents=True)
            (d / "truth.tsv").write_text("sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t10000\n"
                                         "chromid\tCHROMOSOME\t2000\np1\tPLASMID\t1000\n")
            (d / "truth.nonchromosomal.tsv").write_text("sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t10000\n"
                                                        "chromid\tPLASMID\t2000\np1\tPLASMID\t1000\n")
            if sample == "s1":
                (d / "sequence_report.jsonl").write_text("{}\n")
            (r / "pred_A.plasmid.fasta").write_text(">a1\n" + "A" * 1000 + "\n")
            (r / "A.pred_vs_ref.paf").write_text("a1\t1000\t0\t1000\t+\tp1\t1000\t0\t1000\t1000\t1000\t60\n")
            (r / "pred_B.plasmid.fasta").write_text(">b1\n" + "A" * 1000 + "\n>b2\n" + "A" * 2000 + "\n>b3\n" + "A" * 400 + "\n")
            (r / "B.pred_vs_ref.paf").write_text("b1\t1000\t0\t1000\t+\tp1\t1000\t0\t1000\t1000\t1000\t60\n"
                                                 "b2\t2000\t0\t2000\t+\tchromid\t2000\t0\t2000\t2000\t2000\t60\n"
                                                 "b3\t400\t0\t400\t+\tchr\t10000\t0\t400\t400\t400\t60\n")
            scores += f"{sample}\tA\tshort_read\t1.0000\t0.9\n{sample}\tB\tshort_read\t0.4545\t0.5\n"
        (results / "scores.tsv").write_text(scores)
        (tmp / "prov.tsv").write_text("sample\ttruth_quality_grade\ns1\tB\ns2\tC\n")
        out = subprocess.run([sys.executable, str(ROOT / "python" / "rank_sensitivity.py"), "--scores",
                              str(results / "scores.tsv"), "--results-dir", str(results), "--data-dir", str(data),
                              "--out-prefix", str(tmp / "b"), "--truth-provenance", str(tmp / "prov.tsv"),
                              "--min-alignment-mapq", "0", "--min-alignment-identity", "0",
                              "--min-alignment-query-coverage", "0", "--min-alignment-length", "1"],
                             capture_output=True, text=True)
        assert out.returncode == 0, out.stderr + out.stdout
        with open(tmp / "b.rank_robustness.tsv", newline="") as handle:
            table = list(csv.DictReader(handle, delimiter="\t"))
        get = lambda variant, tool: next(r for r in table if r["variant"] == variant and r["tool"] == tool)  # noqa: E731
        assert get("baseline", "A")["rank"] == "1" and get("baseline", "B")["mean_value"] == "0.4545"
        assert get("scheme:nonchromosomal", "B")["rank"] == "1"
        assert get("scheme:nonchromosomal", "B")["mean_value"] == "0.9375"
        assert get("scheme:nonchromosomal", "A")["kendall_tau_vs_baseline"] == "-1.000"
        print("  PASS: Scheme 1 (non-chromosomal) re-scores against truth.nonchromosomal.tsv and flips the ranking")
        assert get("min_contig=500", "B")["mean_value"] == "0.5000"
        assert get("micro_f1", "B")["mean_value"] == "0.4545"
        assert get("public_only", "A")["n_samples"] == "1" and get("in_house_only", "A")["n_samples"] == "1"
        assert get("grade_c_excluded", "A")["n_samples"] == "1"
        assert get("metric:mcc", "A")["rank"] == "1"
        print("  PASS: min_contig=500, micro_f1, public_only, in_house_only, grade_c_excluded and metric:mcc axes")
        assert not any(r["variant"] == "scheme:evidence" for r in table)
        print("  PASS: no truth.scored.tsv -> no evidence-scheme variant (absent, not fabricated)")
    print("ALL NEW RANK AXES TESTS PASSED")


if __name__ == "__main__":
    main()
