#!/usr/bin/env python3
"""Deterministic test sharding for test/run_tests.sh.

Reads the registered test names (one per line, as `PB_LIST=1 bash test/run_tests.sh` prints them) on standard input and
prints the names that belong to shard SHARD of SHARDS. The assignment is a longest-processing-time greedy balance over
test/shard_weights.tsv (test name <TAB> seconds): heaviest first, each into the currently lightest shard, ties broken by
shard number and by test name, so the same inputs always give the same shards. A test with no weight gets the median weight
(1 when the table is empty), so a new test is run by some shard, never dropped. A name registered twice runs twice, in the
same shard.
"""
import argparse
import statistics
import sys
from pathlib import Path

DEFAULT_WEIGHTS = Path(__file__).resolve().parent / "shard_weights.tsv"


def read_weights(path):
    """test name -> seconds from a TSV; blank lines and lines starting with # are ignored."""
    weights = {}
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 2:
            raise ValueError(f"{path}:{number}: expected 'test<TAB>seconds', got {line!r}")
        weights[fields[0].strip()] = float(fields[1])
    return weights


def assign(names, weights, shards):
    """Map each distinct test name to a shard number in 1..shards."""
    if shards < 1:
        raise ValueError("shards must be at least 1")
    counts = {}
    for name in names:
        counts[name] = counts.get(name, 0) + 1
    default = statistics.median(weights.values()) if weights else 1.0
    cost = {name: weights.get(name, default) * count for name, count in counts.items()}
    load = [0.0] * shards
    out = {}
    for name in sorted(cost, key=lambda n: (-cost[n], n)):
        target = min(range(shards), key=lambda i: (load[i], i))
        load[target] += cost[name]
        out[name] = target + 1
    return out


def select(names, weights, shard, shards):
    if not 1 <= shard <= shards:
        raise ValueError(f"shard must be between 1 and {shards}, got {shard}")
    mine = assign(names, weights, shards)
    seen = []
    for name in names:
        if mine[name] == shard and name not in seen:
            seen.append(name)
    return seen


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--shard", type=int, required=True, help="this shard, 1..SHARDS")
    parser.add_argument("--shards", type=int, required=True)
    parser.add_argument("--weights", default=str(DEFAULT_WEIGHTS))
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(newline="\n")  # bash reads the names back: no CR on Windows
    names = [line.strip() for line in sys.stdin if line.strip()]
    for name in select(names, read_weights(args.weights), args.shard, args.shards):
        print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
