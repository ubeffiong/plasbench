#!/usr/bin/env python3
"""python/plasbench_common.py replaced independent copies of scientific helpers
(interval coverage, single-linkage, tool names, Mash settings). These checks pin
the shared versions against the semantics of the code they replaced, so a future
edit cannot make two scorers disagree again."""
import os
import random
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))
import plasbench_common as pc  # noqa: E402


def reference_merge(intervals):
    """The original per-script implementation: overlapping or touching intervals merge."""
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def bases(intervals):
    covered = set()
    for start, end in intervals:
        covered.update(range(start, end))
    return covered


def test_intervals(rng):
    for _ in range(3000):
        a = [(s, s + rng.choice([0, 1, 3, 20, 100])) for s in (rng.randint(0, 200) for _ in range(rng.randint(0, 20)))]
        b = [(s, s + rng.choice([0, 1, 3, 20, 100])) for s in (rng.randint(0, 200) for _ in range(rng.randint(0, 20)))]
        snapshot = list(a)
        merged_a, merged_b = pc.merge_intervals(a), pc.merge_intervals(b)
        assert a == snapshot, "merge_intervals must not modify its input"
        assert merged_a == reference_merge(a)
        # Independent oracle: base-by-base set arithmetic.
        assert sum(e - s for s, e in merged_a) == len(bases(a))
        assert pc.interval_overlap_bp(merged_a, merged_b) == len(bases(a) & bases(b))
    assert pc.merge_intervals([(0, 5), (5, 9)]) == [[0, 9]], "touching intervals merge"
    assert pc.merge_intervals([]) == []


def test_union_find(rng):
    for _ in range(500):
        items = [f"n{i}" for i in range(rng.randint(1, 30))]
        pairs = [(rng.choice(items), rng.choice(items)) for _ in range(rng.randint(0, 40))]
        clusters = pc.UnionFind(items)
        for a, b in pairs:
            clusters.union(a, b)
        # Oracle: connected components by repeated relabelling; the root is the smallest member.
        label = {i: i for i in items}
        changed = True
        while changed:
            changed = False
            for a, b in pairs:
                low = min(label[a], label[b])
                if label[a] != low or label[b] != low:
                    label[a] = label[b] = low
                    changed = True
        assert {i: clusters.find(i) for i in items} == label
    unknown = pc.UnionFind()
    unknown.union("x", "a")
    assert unknown.find("x") == "a", "items are added on first use; smallest member is the root"


def test_names_and_mash():
    # Names the enterprise view used to spell differently from the main report.
    for tool, label in {"genomad": "geNomad", "plasme": "PLASMe", "plasgraph2": "plASgraph2"}.items():
        assert pc.display_tool_name(tool) == label
    assert pc.display_tool_name("mob_recon") == "MOB-recon"
    assert pc.display_tool_name("some_new-tool") == "Some new tool"
    assert pc.MASH_SKETCH_SIZE == 10000
    for threshold in (0.0005, 0.05, 0.2):
        assert pc.mash_dist_limit(threshold) > threshold, "never drops a pair kept at <= threshold"
        assert pc.mash_dist_limit(threshold) < threshold * 1.01 + 1e-6, "still a real filter"


def test_readers():
    with tempfile.TemporaryDirectory() as tmp:
        fasta = os.path.join(tmp, "x.fa")
        with open(fasta, "w") as handle:
            handle.write(">a desc\nACGT\nAC\n>b\nAAA\n>a again\nTT\n")
        assert pc.fasta_lengths(fasta) == {"a": 2, "b": 3}, "lenient: a repeated id keeps the last length"
        truth = os.path.join(tmp, "truth.tsv")
        with open(truth, "w") as handle:
            handle.write("sequence_id\tmolecule_type\tlength\nchr1\tCHROMOSOME\t900\np1\tplasmid\t100\np2\tPLASMID\t50\n")
        assert pc.read_plasmid_lengths(truth) == {"p1": 100, "p2": 50}
        assert pc.number("1.5") == 1.5 and pc.number("x") is None and pc.number(None) is None


def main():
    rng = random.Random(20261108)
    test_intervals(rng)
    test_union_find(rng)
    test_names_and_mash()
    test_readers()
    print("plasbench_common: intervals, union-find, names, mash settings, readers -> PASS")


if __name__ == "__main__":
    main()
