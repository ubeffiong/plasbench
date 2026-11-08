#!/usr/bin/env python3
"""truth_depth_anomalies.py: windowing, robust anomaly regions, clustering, status rows."""
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "python", "truth_depth_anomalies.py")
sys.path.insert(0, os.path.join(ROOT, "python"))
import truth_depth_anomalies as td  # noqa: E402

TRUTH = [{"sequence_id": "chr", "molecule_type": "CHROMOSOME", "length": "1000"},
         {"sequence_id": "p", "molecule_type": "PLASMID", "length": "1000"}]


def table(rep, values, size=10):
    return [(rep, i * size + 1, (i + 1) * size, v) for i, v in enumerate(values)]


class Anomalies(unittest.TestCase):
    def run_p(self, values, **kw):
        tbl = table("p", values) + table("chr", [100] * 100)
        return td.detect(tbl, TRUTH, "S", **kw)

    def test_high_block(self):
        vals = [100] * 100
        for i in range(40, 45):
            vals[i] = 300
        regions, summary = self.run_p(vals)
        self.assertEqual(len(regions), 1)
        r = regions[0]
        self.assertEqual((r["direction"], r["start"], r["end"], r["n_windows"]), ("high", 401, 450, 5))
        self.assertEqual(float(r["fold_change"]), 3.0)
        s = [x for x in summary if x["sequence_id"] == "p"][0]
        self.assertEqual((s["n_high_regions"], s["n_low_regions"], s["anomalous_bp"]), (1, 0, 50))
        self.assertEqual(s["status"], "flagged")  # 50/1000 = 0.05 >= 0.02
        self.assertEqual(float(s["depth_ratio_to_chromosome"]), 1.0)

    def test_low_block(self):
        vals = [100] * 100
        for i in range(10, 15):
            vals[i] = 10
        regions, _ = self.run_p(vals)
        self.assertEqual([(r["direction"], float(r["mean_depth"])) for r in regions], [("low", 10.0)])

    def test_clustering_merges_close_windows(self):
        vals = [100] * 100
        vals[20] = vals[26] = 300  # windows 201-210 and 261-270: 50 bp apart
        regions, _ = self.run_p(vals)
        self.assertEqual(len(regions), 1)
        self.assertEqual((regions[0]["start"], regions[0]["end"], regions[0]["n_windows"]), (201, 270, 2))
        vals = [100] * 100
        vals[20] = vals[40] = 300  # far apart: separate
        regions, _ = self.run_p(vals)
        self.assertEqual(len(regions), 2)

    def test_opposite_directions_not_merged(self):
        vals = [100] * 100
        vals[20], vals[21] = 300, 5
        regions, _ = self.run_p(vals)
        self.assertEqual(sorted(r["direction"] for r in regions), ["high", "low"])

    def test_mad_zero_fallback(self):
        med, spread = td.robust_spread([100] * 95 + [300] * 5)
        self.assertEqual(med, 100)
        self.assertGreater(spread, 0)  # SD fallback, not 1.4826*0
        self.assertEqual(td.robust_spread([100] * 10)[1], 0)

    def test_perfectly_flat_has_no_regions(self):
        regions, summary = self.run_p([100] * 100)
        self.assertEqual(regions, [])
        self.assertEqual([s["status"] for s in summary], ["ok", "ok"])

    def test_insufficient_windows(self):
        tbl = table("p", [100] * 5) + table("chr", [100] * 100)
        _, summary = td.detect(tbl, TRUTH, "S")
        self.assertEqual({s["sequence_id"]: s["status"] for s in summary}["p"], "insufficient_windows")

    def test_missing_input_status_rows(self):
        regions, summary = td.detect(None, TRUTH, "S")
        self.assertEqual(regions, [])
        self.assertEqual({s["status"] for s in summary}, {"missing_input"})
        with tempfile.TemporaryDirectory() as d:
            tp = os.path.join(d, "truth.tsv")
            with open(tp, "w") as h:
                h.write("sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t10\n")
            out, sm = os.path.join(d, "r.tsv"), os.path.join(d, "s.tsv")
            res = subprocess.run([sys.executable, SCRIPT, "--depth-table", os.path.join(d, "nope.tsv"),
                                  "--truth", tp, "--sample", "S", "--out", out, "--summary-out", sm],
                                 capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertIn("missing_input", open(sm, encoding="utf-8").read())

    def test_windows_subcommand_and_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            dp = os.path.join(d, "depth.tsv")
            with open(dp, "w") as h:
                for pos in range(1, 1051):  # 1050 bp: last window is 50 bp
                    h.write(f"p\t{pos}\t{300 if 3000 < pos * 1 else 100}\n")
            wt = os.path.join(d, "win.tsv")
            subprocess.run([sys.executable, SCRIPT, "windows", "--depth-tsv", dp, "--out", wt,
                            "--window", "100"], check=True)
            lines = open(wt, encoding="utf-8").read().splitlines()
            self.assertEqual(lines[0], "replicon\tstart\tend\tmean_depth")
            self.assertEqual(len(lines) - 1, 11)
            self.assertTrue(lines[-1].startswith("p\t1001\t1050\t"))
            rows = td.read_window_table(wt)
            self.assertEqual(rows[0], ("p", 1, 100, 100.0))

    def test_ratio_function(self):
        tbl = table("p", [50] * 20) + table("chr", [100] * 20)
        ratios = td.plasmid_to_chromosome_depth_ratio(tbl, {"p": "PLASMID", "chr": "CHROMOSOME"})
        self.assertEqual(ratios, {"p": 0.5})
        self.assertEqual(td.plasmid_to_chromosome_depth_ratio(tbl[:20], {"p": "PLASMID"}), {"p": None})


if __name__ == "__main__":
    unittest.main()
