#!/usr/bin/env python3
"""scenario_tags.py: scenario classification rules and per-scenario performance."""
import csv
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "python", "scenario_tags.py")


def sample(data, name, plasmids, features=None):
    os.makedirs(os.path.join(data, name))
    with open(os.path.join(data, name, "truth.tsv"), "w") as fh:
        fh.write("sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t500000\n")
        for i, length in enumerate(plasmids):
            fh.write(f"p{i}\tPLASMID\t{length}\n")
    if features is not None:
        with open(os.path.join(data, name, "truth_features.tsv"), "w") as fh:
            fh.write("sequence_id\tstart\tend\tfeature_type\tlabel\n")
            for seq, kind in features:
                fh.write(f"{seq}\t1\t100\t{kind}\tx\n")


def main():
    ok = True

    def check(label, good):
        nonlocal ok
        print(f"  {label}: {'PASS' if good else 'FAIL'}")
        ok &= bool(good)

    with tempfile.TemporaryDirectory() as tmp:
        data = os.path.join(tmp, "data")
        sample(data, "free", [])
        sample(data, "simple", [40_000])
        sample(data, "annot", [40_000], [("p0", "replicon")])
        sample(data, "multi", [40_000, 30_000, 20_000])
        sample(data, "large", [150_000])
        sample(data, "repeat", [40_000], [("p0", "is")] * 5)            # 5 IS in 4 x 10 kb = 1.25 per 10 kb
        sample(data, "lowdepth", [40_000], [("p0", "amr")])
        sample(data, "cryptic", [3_000, 40_000])
        scores, sheet = os.path.join(tmp, "scores.tsv"), os.path.join(tmp, "sheet.tsv")
        names = ["free", "simple", "annot", "multi", "large", "repeat", "lowdepth", "cryptic"]
        with open(scores, "w") as fh:
            fh.write("sample\ttool\tanalysis_track\tf1\tprecision\trecall\tplasmid_recall\n")
            for n in names:
                fh.write(f"{n}\tA\tshort_read\t0.9\t0.9\t0.9\t1.0\n{n}\tB\tshort_read\t0.5\t0.5\t0.5\t0.0\n")
        with open(sheet, "w") as fh:
            fh.write("sample_id\tread_depth_x\n" + "".join(f"{n}\t{10 if n == 'lowdepth' else 80}\n" for n in names))
        out, perf = os.path.join(tmp, "scen.tsv"), os.path.join(tmp, "perf.tsv")
        done = subprocess.run([sys.executable, SCRIPT, "--scores", scores, "--data-dir", data, "--sample-sheet", sheet,
                               "--out", out, "--performance-out", perf], capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        scen = {r["sample"]: r for r in csv.DictReader(open(out, newline=""), delimiter="\t")}
        want = {"free": "plasmid_free", "simple": "simple", "annot": "annotated", "multi": "complex",
                "large": "complex", "repeat": "complex", "lowdepth": "challenging", "cryptic": "simple"}
        for name, label in want.items():
            check(f"{name} is {label}", scen[name]["scenario"] == label)
        check("cryptic small plasmid is tagged but does not change the scenario", "cryptic_small" in scen["cryptic"]["tags"])
        check("repeat-rich needs IS annotation and reports its density",
              "repeat_rich" in scen["repeat"]["tags"] and abs(float(scen["repeat"]["is_density_per_10kb"]) - 1.25) < 1e-3)
        check("no annotation: IS density is blank (not evaluated), never zero", scen["simple"]["is_density_per_10kb"] == "")
        check("low depth is tagged alongside its annotation",
              "low_depth" in scen["lowdepth"]["tags"] and "annotated" in scen["lowdepth"]["tags"])
        rows = list(csv.DictReader(open(perf, newline=""), delimiter="\t"))
        complex_a = [r for r in rows if r["scenario"] == "complex" and r["tool"] == "A"][0]
        check("per-scenario table: 3 complex isolates, mean F1 0.9, and not underpowered at n=3",
              complex_a["n_samples"] == "3" and complex_a["mean_f1"] == "0.9000" and complex_a["underpowered"] == "false")
        free_b = [r for r in rows if r["scenario"] == "plasmid_free" and r["tool"] == "B"][0]
        check("a one-isolate scenario is flagged underpowered", free_b["underpowered"] == "true")
    print("ALL SCENARIO TAG TESTS PASSED" if ok else "SCENARIO TAG TESTS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
