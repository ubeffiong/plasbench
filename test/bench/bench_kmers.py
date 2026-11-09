"""Time and peak memory of repeat_content.canonical_kmers + Counter on a random genome.

usage: python bench_kmers.py <project>/python <genome_mb>
"""
import random
import sys
import time
import tracemalloc
from collections import Counter

sys.path.insert(0, sys.argv[1])
from repeat_content import canonical_kmers  # noqa: E402

size = int(float(sys.argv[2]) * 1_000_000)
rng = random.Random(1)
seq = "".join(rng.choice("ACGT") for _ in range(size))
tracemalloc.start()
t0 = time.perf_counter()
counts = Counter(canonical_kmers(seq, 29))
dt = time.perf_counter() - t0
peak = tracemalloc.get_traced_memory()[1]
print(f"genome={size/1e6:.1f} Mb distinct_kmers={len(counts)} time_s={dt:.1f} "
      f"peak_traced_MB={peak/1e6:.0f} (timing inflated by tracemalloc)")
