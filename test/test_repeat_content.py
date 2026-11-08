#!/usr/bin/env python3
"""repeat_content.py: canonical k-mer repeat and sharing fractions, hand-checked."""
import os
import random
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
import repeat_content as rc  # noqa: E402

K = 15
COMP = str.maketrans("ACGT", "TGCA")


def rnd(n, seed):
    r = random.Random(seed)
    return "".join(r.choice("ACGT") for _ in range(n))


def revcomp(s):
    return s.translate(COMP)[::-1]


def run(records, truth, **kw):
    with tempfile.TemporaryDirectory() as d:
        fa = os.path.join(d, "ref.fna")
        with open(fa, "w", encoding="utf-8") as h:
            for name, seq in records:
                h.write(f">{name} desc\n{seq}\n")
        rows = [{"sequence_id": s, "molecule_type": m, "length": str(len(dict(records).get(s, "")))}
                for s, m in truth]
        out = rc.compute(fa, rows, "S", k=K, **kw)
    return {r["sequence_id"]: r for r in out}


class RepeatContent(unittest.TestCase):
    def test_direct_repeat_hand_count(self):
        a = rnd(60, 1)
        p = a + a + rnd(40, 2) + rnd(40, 3)
        self.assertEqual(len(p), 200)
        r = run([("p", p)], [("p", "PLASMID")])["p"]
        # 200-15+1 = 186 positions; the 46 k-mers of each 60 bp half occur twice => 92
        self.assertEqual(r["n_kmers"], 186)
        self.assertAlmostEqual(float(r["internal_repeat_fraction"]), 92 / 186, places=5)
        self.assertEqual(r["repeat_rich"], "yes")
        self.assertEqual(r["status"], "no_chromosome")

    def test_inverted_repeat_canonical(self):
        a = rnd(60, 4)
        p = a + rnd(80, 5) + revcomp(a)
        r = run([("p", p)], [("p", "PLASMID")])["p"]
        self.assertAlmostEqual(float(r["internal_repeat_fraction"]), 92 / 186, places=5)

    def test_chromosome_sharing(self):
        seg = rnd(50, 6)
        p = rnd(75, 7) + seg + rnd(75, 8)
        chrom = rnd(500, 9) + revcomp(seg) + rnd(500, 10)  # reverse strand still counts
        res = run([("p", p), ("c", chrom)], [("p", "PLASMID"), ("c", "CHROMOSOME")])
        self.assertAlmostEqual(float(res["p"]["chromosome_shared_fraction"]), 36 / 186, places=5)
        self.assertEqual(res["p"]["status"], "ok")
        self.assertEqual(res["p"]["repeat_rich"], "yes")
        self.assertEqual(res["c"]["chromosome_shared_fraction"], "")
        self.assertEqual(float(res["c"]["internal_repeat_fraction"]), 0.0)

    def test_shared_with_other_plasmids(self):
        seg = rnd(40, 11)
        res = run([("p1", rnd(60, 12) + seg + rnd(60, 13)), ("p2", rnd(70, 100) + seg + rnd(50, 1100))],
                  [("p1", "PLASMID"), ("p2", "PLASMID")])
        self.assertAlmostEqual(float(res["p1"]["shared_with_other_plasmids_fraction"]), 26 / 146, places=5)

    def test_non_acgt_skipped(self):
        p = rnd(50, 16) + "N" + rnd(49, 17)
        r = run([("p", p)], [("p", "PLASMID")])["p"]
        self.assertEqual(r["n_kmers"], 100 - K + 1 - K)

    def test_no_plasmids(self):
        res = run([("c", rnd(300, 18))], [("c", "CHROMOSOME")])
        self.assertEqual(res["c"]["status"], "ok")
        self.assertEqual(res["c"]["repeat_rich"], "no")

    def test_chromosome_skipped_and_missing(self):
        res = run([("c", rnd(300, 19))], [("c", "CHROMOSOME"), ("x", "PLASMID")], max_chromosome_bp=100)
        self.assertEqual(res["c"]["status"], "chromosome_skipped")
        self.assertEqual(res["x"]["status"], "missing_sequence")

    def test_summary_merge(self):
        with tempfile.TemporaryDirectory() as d:
            for s, hdr in (("a", "x\ty"), ("b", "x\ty"), ("c", "x\ty")):
                if s == "c":
                    continue  # absent shard is simply not written
                os.makedirs(os.path.join(d, s))
                with open(os.path.join(d, s, "truth_repeat_content.tsv"), "w") as h:
                    h.write(f"{hdr}\n{s}\t1\n")
            out = os.path.join(d, "m.tsv")
            self.assertEqual(rc.summarize(d, out), 2)
            os.makedirs(os.path.join(d, "z"))
            with open(os.path.join(d, "z", "truth_repeat_content.tsv"), "w") as h:
                h.write("q\tr\n1\t2\n")
            with self.assertRaises(SystemExit):
                rc.summarize(d, out)


if __name__ == "__main__":
    unittest.main()
