"""Small helpers shared by the python/ scripts.

Only byte-identical duplicates live here (verified by AST comparison), so moving a
script onto these cannot change its behaviour. Scripts are run as
`python python/<script>.py`, which puts this directory on sys.path, so a plain
`from plasbench_common import ...` works. Standard library only.
"""

import csv
import hashlib
import os
import shutil


def number(value):
    """float(value), or None when it is missing or not numeric."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def sha256(path):
    """Hex SHA-256 of a file, read in 1 MiB blocks."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def link_or_copy(source, destination):
    """Symlink destination -> source (pathlib.Path args); copy when links are not allowed."""
    try:
        destination.symlink_to(source.resolve())
    except OSError:
        shutil.copy2(source, destination)


def read_tsv(path):
    """Rows of a TSV as dicts; [] when path is empty or not a file."""
    if not path or not os.path.isfile(path):
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


# --- intervals ---------------------------------------------------------------
# One definition of "bases covered", used by every scorer. Intervals are
# half-open [start, end); intervals that overlap OR touch (start <= previous end)
# are merged. A boundary-semantics difference between scorers would silently
# change TP/FP, so test/test_plasbench_common.py pins these against the originals.

def merge_intervals(intervals):
    """Sorted, merged list of [start, end] (new lists; the input is not modified)."""
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def interval_overlap_bp(left, right):
    """Bases shared by two already-merged (sorted, disjoint) interval lists."""
    i = j = total = 0
    while i < len(left) and j < len(right):
        total += max(0, min(left[i][1], right[j][1]) - max(left[i][0], right[j][0]))
        if left[i][1] <= right[j][1]:
            i += 1
        else:
            j += 1
    return total


# --- single-linkage clustering ----------------------------------------------

class UnionFind:
    """Union-find whose root is always the smallest member, so a cluster id is
    deterministic and stable (no counter or ordering concern). Unknown items are
    added on first use."""

    def __init__(self, items=()):
        self.parent = {item: item for item in items}

    def find(self, item):
        parent = self.parent
        parent.setdefault(item, item)
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(self, a, b):
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            self.parent[max(root_a, root_b)] = min(root_a, root_b)


# --- Mash ----------------------------------------------------------------------
# The sketch size is a scientific parameter: a query sketched at a different size
# than the reference silently lowers sensitivity, so every Mash user shares this.
MASH_SKETCH_SIZE = 10000


def mash_dist_limit(threshold):
    """Value for `mash dist -d` that never drops a pair a caller keeps at `<= threshold`.

    mash filters on the full-precision distance but prints a rounded one, and callers
    compare the printed value to the threshold; the small margin keeps pairs that
    round down onto the threshold. Callers must still apply their own exact filter.
    """
    return threshold * 1.001 + 1e-9


# --- display names ---------------------------------------------------------------
TOOL_DISPLAY_NAMES = {
    "mob_recon": "MOB-recon", "plasmidspades": "plasmidSPAdes",
    "gplas2_mob": "gplas2-MOB", "gplas2_external": "gplas2 external",
    "mob_like": "MOB-like", "platon_like": "Platon-like",
    "spades_like": "SPAdes-like", "gplas_like": "gplas-like",
    "weak_like": "Weak-like", "genomad": "geNomad", "plasme": "PLASMe",
    "plasgraph2": "plASgraph2", "rfplasmid": "RFPlasmid", "plascope": "PlaScope",
    "plasmidhunter": "PlasmidHunter", "plasmer": "Plasmer",
}


def display_tool_name(tool):
    """Reader-facing label for a stable adapter ID; the ID itself never changes."""
    return TOOL_DISPLAY_NAMES.get(tool, str(tool).replace("_", " ").replace("-", " ").capitalize())


# --- FASTA / truth ---------------------------------------------------------------

def fasta_lengths(path):
    """Record id (first header token) -> sequence length, lenient.

    A repeated id keeps the last length and a bare '>' gets id ''. The strict
    scorer (score_plasmids.read_fasta_lengths) rejects both on purpose and stays
    separate; make_truth / build_hybrid_truth / init_local_sample / baseline_predictors
    return other shapes (ordered lists, descriptions, gzip, sequences) and are
    deliberately not folded in here.
    """
    lengths, seq_id, total = {}, None, 0
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith(">"):
                if seq_id is not None:
                    lengths[seq_id] = total
                parts = line[1:].strip().split(None, 1)
                seq_id = parts[0] if parts else ""
                total = 0
            else:
                total += len(line.strip())
    if seq_id is not None:
        lengths[seq_id] = total
    return lengths


def read_plasmid_lengths(path):
    """sequence_id -> length for the PLASMID rows of a truth.tsv."""
    plasmids = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row["molecule_type"].upper() == "PLASMID":
                plasmids[row["sequence_id"]] = int(row["length"])
    return plasmids
