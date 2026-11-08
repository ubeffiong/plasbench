#!/usr/bin/env python3
"""Leave-taxon-out and the locked holdout (python/leave_taxon_out.py).

Genera Escherichia, Klebsiella, Salmonella (2 isolates each, genus from the first
word of organism), plus one isolate with no organism and two split=holdout
isolates. Tool X scores 0.9 everywhere, Y 0.5: the single best is X in every fold,
so regret is 0 and near-optimal 1.0. The organism-less isolate is reported as
not_used_as_fold; holdout isolates are locked until --confirm-holdout, which
evaluates them once and refuses a second time.
"""
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "python" / "leave_taxon_out.py"


def run(tmp, *extra):
    return subprocess.run([sys.executable, str(SCRIPT), "--scores", str(tmp / "scores.tsv"), "--samples",
                           str(tmp / "samples.tsv"), "--out-prefix", str(tmp / "b"), "--min-train-samples", "2", *extra],
                          capture_output=True, text=True)


def rows(tmp):
    with open(tmp / "b.leave_taxon_out.tsv", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        sheet, scores = "sample_id\torganism\tsplit\n", "sample\ttool\tf1\n"
        samples = [("e1", "Escherichia coli", ""), ("e2", "Escherichia coli", ""), ("k1", "Klebsiella pneumoniae", ""),
                   ("k2", "Klebsiella pneumoniae", ""), ("s1", "Salmonella enterica", ""),
                   ("s2", "Salmonella enterica", ""), ("u1", "", ""), ("h1", "Escherichia coli", "holdout"),
                   ("h2", "Klebsiella pneumoniae", "holdout")]
        for sample, organism, split in samples:
            sheet += f"{sample}\t{organism}\t{split}\n"
            scores += f"{sample}\tX\t0.9\n{sample}\tY\t0.5\n"
        (tmp / "samples.tsv").write_text(sheet)
        (tmp / "scores.tsv").write_text(scores)

        assert run(tmp).returncode == 0
        out = rows(tmp)
        genus = {r["held_out_group"]: r for r in out if r["level"] == "genus"}
        assert set(genus) == {"Escherichia", "Klebsiella", "Salmonella", "not_recorded"}, genus
        assert genus["Klebsiella"]["status"] == "assessed" and genus["Klebsiella"]["mean_regret"] == "0.0000"
        assert genus["Klebsiella"]["near_optimal_rate"] == "1.0000" and genus["Klebsiella"]["n_isolates"] == "2"
        assert genus["not_recorded"]["status"] == "not_used_as_fold" and genus["not_recorded"]["n_isolates"] == "1"
        phylum = [r for r in out if r["level"] == "phylum"]
        assert phylum[0]["status"] == "not_assessed"
        holdout = next(r for r in out if r["level"] == "holdout")
        assert holdout["status"] == "locked" and holdout["n_isolates"] == "2"
        print("  PASS: one fold per genus (holdout excluded), no-taxon isolate counted not dropped, holdout locked")

        first = run(tmp, "--confirm-holdout")
        assert first.returncode == 0, first.stderr
        holdout = next(r for r in rows(tmp) if r["level"] == "holdout")
        assert holdout["status"] == "assessed" and holdout["n_isolates"] == "2", holdout
        assert (tmp / "b.holdout_evaluated.json").is_file()
        second = run(tmp, "--confirm-holdout")
        assert second.returncode != 0 and "evaluated once" in second.stderr, second.stderr
        print("  PASS: --confirm-holdout evaluates the holdout once and refuses a second run")
    print("ALL LEAVE-TAXON-OUT TESTS PASSED")


if __name__ == "__main__":
    main()
