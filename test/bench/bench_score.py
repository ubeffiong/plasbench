"""Time score_plasmids.py and score_bins.py on synthetic PAF of increasing size.

usage: python bench_score.py <project>/python
"""
import os
import random
import subprocess
import sys
import tempfile
import time

py = sys.argv[1]
rng = random.Random(3)
print("contigs\tpaf_lines\tscore_plasmids_s\tscore_bins_s (one bin per contig)")
for n_contigs in (200, 2000, 20000):
    with tempfile.TemporaryDirectory() as d:
        truth, fasta, paf, bins = (os.path.join(d, n) for n in ("t.tsv", "p.fa", "a.paf", "b.tsv"))
        plasmids = {f"p{i}": rng.randint(5000, 200000) for i in range(6)}
        with open(truth, "w") as h:
            h.write("sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t5000000\n")
            for p, n in plasmids.items():
                h.write(f"{p}\tPLASMID\t{n}\n")
        with open(fasta, "w") as f, open(paf, "w") as a, open(bins, "w") as b:
            b.write("sequence_id\tbin_id\n")
            for i in range(n_contigs):
                length = rng.randint(500, 5000)
                f.write(f">c{i}\n{'A' * length}\n")
                target = rng.choice(list(plasmids)) if rng.random() < 0.7 else "chr"
                tlen = plasmids.get(target, 5000000)
                start = rng.randint(0, tlen - length)
                a.write(f"c{i}\t{length}\t0\t{length}\t+\t{target}\t{tlen}\t{start}\t{start + length}\t"
                        f"{length - 5}\t{length}\t60\n")
                b.write(f"c{i}\tB{i}\n")
        t0 = time.perf_counter()
        r = subprocess.run([sys.executable, os.path.join(py, "score_plasmids.py"), "--truth", truth, "--paf", paf,
                            "--pred-fasta", fasta, "--sample", "s", "--tool", "t", "--out",
                            os.path.join(d, "o.tsv")], capture_output=True, text=True)
        t1 = time.perf_counter()
        assert r.returncode == 0, r.stderr[-1500:]
        cell = "skipped (set BENCH_LARGE_BINS=1 to run)"
        if n_contigs <= 2000 or os.environ.get("BENCH_LARGE_BINS") == "1":
            r = subprocess.run([sys.executable, os.path.join(py, "score_bins.py"), "--truth", truth, "--paf", paf,
                                "--bins", bins, "--out", os.path.join(d, "m.tsv"),
                                "--summary", os.path.join(d, "s.tsv")], capture_output=True, text=True)
            assert r.returncode == 0, r.stderr[-1500:]
            cell = f"{time.perf_counter() - t1:.1f}"
        print(f"{n_contigs}\t{n_contigs}\t{t1 - t0:.2f}\t{cell}", flush=True)
