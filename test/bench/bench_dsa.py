"""Time the data-structure hot spots on fixed synthetic inputs, for any copy of python/.

Each case prints its wall time and a SHA-256 of its output, so two code versions can
be compared for speed AND for identical results.
usage: python test/bench/bench_dsa.py <python_dir> [case ...]
"""
import hashlib
import json
import os
import random
import sys
import tempfile
import time

PY = os.path.abspath(sys.argv[1])
sys.path.insert(0, PY)
ONLY = set(sys.argv[2:])


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:12]


def timed(name, fn, repeat=3):
    if ONLY and name not in ONLY:
        return
    best, out = None, None
    for _ in range(repeat):
        t0 = time.perf_counter()
        out = fn()
        dt = time.perf_counter() - t0
        best = dt if best is None else min(best, dt)
    print(f"{name:<34}{best:10.3f} s   output {digest(out)}", flush=True)




# 1. Bin agreement: per-bin best matches with a one-bin-per-contig tool (bin-heavy).
def case_bin_agreement():
    import bin_agreement as ba
    labels = {}
    for i in range(3000):
        plasmid = f"p{i % 40}" if i % 3 else None
        labels[f"c{i}"] = {"label": "PLASMID" if plasmid else "CHROMOSOME", "length": 1000 + i % 7 * 100,
                           "plasmids": [plasmid] if plasmid else []}
    pred = {f"b{i}": [f"c{i}"] for i in range(3000) if i % 3}
    return ba.per_bin_rows(pred, labels)


# 2. Bins table with many repeated rows inside large bins (dedup on read).
def case_read_bins():
    import bin_agreement as ba
    path = os.path.join(tempfile.mkdtemp(), "bins.tsv")
    with open(path, "w") as h:
        h.write("bin_id\tsequence_id\n")
        for i in range(60000):
            h.write(f"B{i % 3}\tc{i % 20000}\n")
    return {k: v for k, v in ba.read_bins(path).items()}


# 3. Probability calibration over many scored records.
def case_calibration():
    rng = random.Random(11)  # each case seeds its own inputs
    import score_plasmids as sp
    truth = {"chr": ("CHROMOSOME", 5_000_000), "p1": ("PLASMID", 200_000)}
    covered, probabilities = {"chr": [], "p1": []}, {}
    for i in range(20000):
        q = f"q{i}"
        target = "p1" if i % 4 else "chr"
        start = rng.randint(0, 150_000)
        covered[target].append((q, start, start + rng.randint(200, 3000)))
        probabilities[q] = round(rng.random(), 3) if i % 50 else 1.0
    return sp.calibration(covered, probabilities, truth)


# 4. Sampled canonical k-mers (alignment-free contig labels), 1 Mb with some Ns.
_seq_rng = random.Random(4)
SEQ = "".join(_seq_rng.choice("ACGT") if _seq_rng.random() > 0.0005 else "N" for _ in range(1_000_000))


def case_sampled_kmers():
    import contig_crosscheck as cc
    return sorted(cc.sampled_kmers(SEQ, 21, 50))


# 5. Matching with many bins that touch no plasmid (filtered before solving).
def case_matching_sparse():
    from score_bins import maximum_weight
    bins = [f"b{i:05d}" for i in range(5000)]
    plasmids = [f"p{j}" for j in range(30)]
    edges = {(b, plasmids[i % 30]): 1000 + i for i, b in enumerate(bins) if i % 25 == 0}
    return maximum_weight(edges, bins, plasmids)


# 6. Display cap: top-k alignment blocks out of many.
def case_top_blocks():
    rng = random.Random(11)  # each case seeds its own inputs
    import build_visualization_data as bv
    blocks = [{"block_length": rng.randint(1, 10 ** 6), "target": f"t{i % 5}", "target_start": i,
               "record_id": f"r{i}"} for i in range(200000)]
    if hasattr(bv, "top_blocks"):
        return bv.top_blocks(blocks, 500)
    return sorted(blocks, key=lambda row: (-row["block_length"], row["target"], row["target_start"],
                                           row["record_id"]))[:500]


# 7. Leaderboard statistics: stratified permutation + bootstrap for one tool pair.
def case_resampling():
    rng = random.Random(11)  # each case seeds its own inputs
    import headline_design as hd
    diffs = [round(rng.gauss(0.03, 0.12), 4) for _ in range(150)]
    groups = [f"g{i // 2}" for i in range(150)]
    strata = [("E", "K", "A")[i % 3] for i in range(150)]
    return hd.pair_statistics(diffs, groups, strata)


# 8. Peak memory of reading only the truth plasmids out of a whole reference.
def memory_reference_plasmids():
    if ONLY and "reference plasmids (peak MiB)" not in ONLY:
        return
    import tracemalloc
    import database_containment as dc
    path = os.path.join(tempfile.mkdtemp(), "reference.fna")
    seq_rng = random.Random(8)
    with open(path, "w") as h:
        for name, size in (("chr", 5_000_000), ("p1", 120_000), ("p2", 60_000), ("p3", 8_000)):
            h.write(f">{name}\n")
            seq = "".join(seq_rng.choice("ACGT") for _ in range(size))
            for i in range(0, size, 80):
                h.write(seq[i:i + 80] + "\n")
    wanted = {"p1", "p2", "p3"}
    tracemalloc.start()
    try:
        records = dc.read_fasta(path, wanted)
    except TypeError:                          # older reader: everything, then filter
        records = {k: v for k, v in dc.read_fasta(path).items() if k in wanted}
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    print(f"{'reference plasmids (peak MiB)':<34}{peak / (1 << 20):10.1f} MiB output {digest(records)}", flush=True)


for name, fn in [("bin_agreement.per_bin_rows", case_bin_agreement), ("bin_agreement.read_bins", case_read_bins),
                 ("score_plasmids.calibration", case_calibration), ("contig_crosscheck.sampled_kmers", case_sampled_kmers),
                 ("score_bins.maximum_weight sparse", case_matching_sparse),
                 ("visualization top-k blocks", case_top_blocks), ("resampling pair statistics", case_resampling)]:
    timed(name, fn, repeat=1 if name == "resampling pair statistics" else 3)
memory_reference_plasmids()
