#!/usr/bin/env python3
"""Tandem-dimer truth (python/detect_dimers.py): a plasmid stored as M+M is
detected, collapsed to M in the reference and truth.tsv (original kept), and
second-copy AMR rows are dropped; a non-dimer is untouched; without --collapse
the dimer is flagged and becomes AMBIGUOUS under the evidence scheme."""
import csv
import random
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "python" / "detect_dimers.py"


def seq(n, rng):
    return "".join(rng.choice("ACGT") for _ in range(n))


def rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def fasta_lengths(path):
    lengths, name = {}, None
    for line in Path(path).read_text().splitlines():
        if line.startswith(">"):
            name = line[1:].split()[0]
            lengths[name] = 0
        else:
            lengths[name] += len(line.strip())
    return lengths


def setup(tmp, rng):
    monomer = seq(2000, rng)
    mutated = list(monomer)
    for i in range(0, 2000, 100):  # 20 substitutions -> 99% identity between copies
        mutated[i] = "A" if mutated[i] != "A" else "C"
    ref = Path(tmp) / "reference.fna"
    ref.write_text(f">chr\n{seq(6000, rng)}\n>dimer\n{monomer}{''.join(mutated)}\n>single\n{seq(3000, rng)}\n")
    truth = Path(tmp) / "truth.tsv"
    truth.write_text("sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t6000\ndimer\tPLASMID\t4000\n"
                     "single\tPLASMID\t3000\n")
    amr = Path(tmp) / "truth_amr.tsv"
    amr.write_text("gene\tsequence_id\tstart\tend\nblaA\tdimer\t100\t900\nblaA\tdimer\t2100\t2900\n")
    return ref, truth, amr


def main():
    rng = random.Random(7)
    with tempfile.TemporaryDirectory() as tmp:
        ref, truth, amr = setup(tmp, rng)
        out = Path(tmp) / "truth.corrections.tsv"
        subprocess.run([sys.executable, str(SCRIPT), "--reference", str(ref), "--truth", str(truth),
                        "--amr-truth", str(amr), "--out", str(out), "--collapse", "--no-minimap2"], check=True)
        corrections = rows(out)
        assert [c["sequence_id"] for c in corrections] == ["dimer"], corrections
        assert corrections[0]["action"] == "collapsed" and corrections[0]["corrected_length"] == "2000"
        assert abs(float(corrections[0]["identity"]) - 0.99) < 1e-9
        assert fasta_lengths(ref) == {"chr": 6000, "dimer": 2000, "single": 3000}
        assert {r["sequence_id"]: r["length"] for r in rows(truth)}["dimer"] == "2000"
        assert (Path(tmp) / "reference.precollapse.fna").is_file()
        assert len(rows(amr)) == 1 and rows(amr)[0]["start"] == "100"
        print("  PASS: 99%-identical M+M detected, collapsed to M; truth length, reference and AMR rows updated")

    with tempfile.TemporaryDirectory() as tmp:
        ref, truth, amr = setup(tmp, random.Random(7))
        out = Path(tmp) / "truth.corrections.tsv"
        subprocess.run([sys.executable, str(SCRIPT), "--reference", str(ref), "--truth", str(truth),
                        "--out", str(out), "--no-minimap2"], check=True)
        assert rows(out)[0]["action"] == "flagged"
        assert fasta_lengths(ref)["dimer"] == 4000
        # The evidence labeller turns a flagged dimer into AMBIGUOUS.
        feats = Path(tmp) / "features.tsv"
        feats.write_text("sequence_id\tfeature_class\tfeature\tstart\tend\n")
        labels, scored = Path(tmp) / "labels.tsv", Path(tmp) / "scored.tsv"
        subprocess.run([sys.executable, str(ROOT / "python" / "label_truth_evidence.py"), "--truth", str(truth),
                        "--reference", str(ref), "--multimers", str(out),
                        "--labels-out", str(labels), "--scored-truth-out", str(scored)], check=True)
        final = {r["sequence_id"]: r["final_label"] for r in rows(labels)}
        assert final["dimer"] == "AMBIGUOUS" and final["single"] == "PLASMID", final
        assert "dimer" not in {r["sequence_id"] for r in rows(scored)}
        print("  PASS: without --collapse the dimer is flagged, the reference untouched, and it is AMBIGUOUS "
              "under the evidence scheme")
    print("ALL DIMER TESTS PASSED")


if __name__ == "__main__":
    main()
