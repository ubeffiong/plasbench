"""Small helpers shared by the python/ scripts.

Most helpers here started as byte-identical duplicates (verified by AST comparison),
so moving a script onto them cannot change its behaviour. The readers in the
"validated readers" section are the exceptions: they carry the scorer's own input
validation, so a script moved onto one now rejects a table the scorer would reject,
instead of silently reading it a different way. Each such move is noted at the call
site. Scripts are run as `python python/<script>.py`, which puts this directory on
sys.path, so a plain `from plasbench_common import ...` works. Standard library only.
"""

import csv
import datetime as dt
import gzip
import hashlib
import os
import shutil
import sys


def subprocess_timeout(default=21600):
    """Seconds a helper subprocess (minimap2, mash, seqtk, a git call ...) may run before it is stopped, so a hung helper cannot hang a stage forever (AU-044).

    The default is generous (6 hours). PLASBENCH_SUBPROCESS_TIMEOUT_SECONDS overrides it; 0 or "off" removes the limit. subprocess raises TimeoutExpired, which names the command."""
    value = os.environ.get("PLASBENCH_SUBPROCESS_TIMEOUT_SECONDS", "").strip().lower()
    if not value:
        return default
    if value in ("0", "off", "none"):
        return None
    try:
        seconds = float(value)
    except ValueError:
        return default
    return seconds if seconds > 0 else None


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


# --- CPRR threshold robustness -------------------------------------------------
# One shared grid, so score_bins.py (which counts correct plasmids at each value)
# and aggregate_results.py (which reads those counts back) cannot drift apart.
# At each value t the coverage and bin-share criteria both require >= t; the
# identification, not-split and identity criteria stay at their configured values.
CPRR_SWEEP_THRESHOLDS = tuple(round(0.80 + 0.01 * i, 2) for i in range(20))   # 0.80 .. 0.99


def cprr_sweep_auc(rates, thresholds=CPRR_SWEEP_THRESHOLDS):
    """Normalised area under CPRR(t) over the sweep (trapezoid rule), in [0, 1].

    None when any rate is undefined, so a partial curve is never summarised.
    """
    if len(rates) != len(thresholds) or len(rates) < 2 or any(r is None for r in rates):
        return None
    area = sum((rates[i] + rates[i + 1]) / 2 * (thresholds[i + 1] - thresholds[i])
               for i in range(len(rates) - 1))
    return area / (thresholds[-1] - thresholds[0])


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
    "plasmidhunter": "PlasmidHunter", "plasmer": "Plasmer", "plasmidec": "PlasmidEC",
}


def with_user_tools(path, rows):
    """Add user-declared tools (python/user_tools.py) to rows read from one of PlasBench's own registry files
    (config/tool_capabilities.tsv, tool_installers.tsv, tool_database_releases.tsv). Any other file, or a
    PlasBench without user tools, is returned unchanged."""
    try:
        import user_tools
    except ImportError:
        return rows
    return user_tools.merge_rows(path, rows)


def display_tool_name(tool):
    """Reader-facing label for a stable adapter ID; the ID itself never changes. A user tool's manifest
    display_name is honoured."""
    if tool in TOOL_DISPLAY_NAMES:
        return TOOL_DISPLAY_NAMES[tool]
    try:
        import user_tools
        declared = user_tools.display_name(tool)
    except ImportError:
        declared = None
    return declared or str(tool).replace("_", " ").replace("-", " ").capitalize()


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


# --- validated readers and shared parsing ----------------------------------------

def open_maybe_gz(path, mode="rt"):
    """open(), or gzip.open() for a path ending in .gz."""
    return gzip.open(path, mode) if str(path).endswith(".gz") else open(path, mode)


def iter_fasta(path, wanted=None):
    """Yield (name, header, sequence) per FASTA record, streaming; gzip-aware.

    header is the text after '>' with surrounding whitespace removed; name is its
    first token ("" for an empty header). Blank lines and any sequence before the
    first header are ignored, as every earlier per-script reader did.

    wanted: an optional set of names. Other records are skipped as they stream past,
    without their sequence lines ever being joined, so a caller that needs a few
    records out of a genome never holds the rest in memory.
    """
    name = header = None
    keep = False
    chunks = []
    with open_maybe_gz(path, "rt") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            if line.startswith(">"):
                if keep:
                    yield name, header, "".join(chunks)
                header = line[1:].strip()
                tokens = header.split()
                name, chunks = (tokens[0] if tokens else ""), []
                keep = wanted is None or name in wanted
            elif keep:
                chunks.append(line)
    if keep:
        yield name, header, "".join(chunks)


def read_truth_table(path):
    """The scorer's validated truth reader: (sequence_id -> (molecule_type, length),
    total plasmid bp, total chromosome bp).

    Exits with an error for a missing column, a molecule type other than
    PLASMID/CHROMOSOME, a non-positive length or a duplicate id, so every script
    reading truth.tsv agrees with score_plasmids.py about what the table means.
    """
    truth = {}
    total_plasmid = 0
    total_chromosome = 0
    with open(path) as fh:
        header = fh.readline().rstrip("\n").split("\t")
        # Be tolerant of column order as long as names are present.
        try:
            i_id = header.index("sequence_id")
            i_type = header.index("molecule_type")
            i_len = header.index("length")
        except ValueError:
            sys.exit(
                "ERROR: truth file must have a header row with columns "
                "'sequence_id', 'molecule_type', 'length'."
            )
        for line in fh:
            if not line.strip():
                continue
            f = line.rstrip("\n").split("\t")
            seq_id = f[i_id]
            mol = f[i_type].strip().upper()
            length = int(f[i_len])
            if mol not in ("PLASMID", "CHROMOSOME"):
                sys.exit(f"ERROR: molecule_type must be PLASMID/CHROMOSOME, got '{mol}'")
            if length <= 0:
                sys.exit(f"ERROR: truth sequence '{seq_id}' has non-positive length {length}.")
            if seq_id in truth:
                sys.exit(f"ERROR: duplicate sequence_id '{seq_id}' in truth file.")
            truth[seq_id] = (mol, length)
            if mol == "PLASMID":
                total_plasmid += length
            else:
                total_chromosome += length
    return truth, total_plasmid, total_chromosome


def read_truth_split(path):
    """Validated truth as (plasmid id -> length, chromosome id -> length)."""
    truth, _, _ = read_truth_table(path)
    plasmids = {k: n for k, (mol, n) in truth.items() if mol == "PLASMID"}
    chromosomes = {k: n for k, (mol, n) in truth.items() if mol == "CHROMOSOME"}
    return plasmids, chromosomes


def read_bin_membership(path):
    """sequence_id -> bin_id from a bins TSV; every row needs both, and each sequence one bin.

    The bin scorer's rule: a contig in two bins, or a row missing an id, is an
    invalid bins table (ValueError), not something to resolve silently.
    """
    membership = {}
    with open(path, encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if not row.get("bin_id") or not row.get("sequence_id") or row["sequence_id"] in membership:
                raise ValueError("bins TSV requires unique sequence_id and nonempty bin_id")
            membership[row["sequence_id"]] = row["bin_id"]
    return membership


def union_length(intervals):
    """Covered length of the union of [start, stop) intervals; empty or reversed ones count 0."""
    total, end = 0, -1
    for start, stop in sorted((start, stop) for start, stop in intervals if stop > start):
        total += max(0, stop - max(end, start))
        end = max(end, stop)
    return total


# --- leakage dates --------------------------------------------------------------------------------
# One definition of "when did this genome become public", shared by the cohort importer
# (--released-after) and python/flag_database_overlap.py, so the two cannot disagree. The
# contributed pool records the assembly release as a full date but the first read release only as a
# YEAR, so a read year is read as 1 January of that year: the earliest the reads can have been public,
# which is the conservative direction for a leakage screen.
LEAKAGE_DATE_BASES = ("earliest_public", "assembly", "read")


def parse_iso_date(text):
    """YYYY-MM-DD (optionally followed by a time, as NCBI writes it; '/' accepted), else None."""
    text = (text or "").strip().replace("/", "-")
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        return None


def leakage_release_date(assembly_date, read_year, basis="earliest_public"):
    """ISO date text for the chosen basis, or '' when that basis has no usable value.

    assembly | read | earliest_public (the earlier of the two, so a genome whose reads were public long
    before the assembly counts as old). A basis that is missing one input falls back to the other only
    for earliest_public, never silently for assembly or read.
    """
    if basis not in LEAKAGE_DATE_BASES:
        raise ValueError(f"unknown leakage date basis {basis!r}; expected one of {LEAKAGE_DATE_BASES}")
    assembled = parse_iso_date(assembly_date)
    year = str(read_year or "").strip()
    read = parse_iso_date(f"{year}-01-01") if year.isdigit() and len(year) == 4 else None
    if basis == "assembly":
        chosen = assembled
    elif basis == "read":
        chosen = read
    else:
        known = [date for date in (assembled, read) if date]
        chosen = min(known) if known else None
    return chosen.isoformat() if chosen else ""


# --- balanced isolate order -------------------------------------------------------------------------
# A cohort sheet is read top to bottom, so `plasbench run --max-isolates N` (the first N) is only a fair
# miniature of the cohort when every prefix is spread across species, studies and the recent / older arms.
# balanced_order() gives that order. It depends only on the rows' own values (never on file order), so
# the same cohort always gives the same order, and an already-ordered sheet is unchanged by it.
BALANCE_MAIN_MIN = 10     # a species with at least this many isolates is a "main" species: it takes part in the rotation first


def balanced_order(rows, seed=20260916, main_min=BALANCE_MAIN_MIN):
    """Indices of `rows` (dicts) in balanced order.

    Species rotate (main species, those with at least main_min isolates, largest first; then the small ones); inside a species the rows alternate
    between the `selection_arm` values (recent first), prefer long-read-first truths, and take one isolate per
    study (cluster_key / bioproject) before taking a second from any study.
    """
    def species_of(row):
        return " ".join((row.get("organism") or "").split()[:2]) or "unknown"

    def study_of(row):
        return row.get("cluster_key") or row.get("bioproject") or row.get("sample_id") or ""

    def tie(row):
        return hashlib.sha256(f"{seed}:{row.get('assembly_accession') or row.get('sample_id') or ''}".encode()).hexdigest()

    by_species = {}
    for index, row in enumerate(rows):
        by_species.setdefault(species_of(row), []).append(index)

    def species_queue(indices):
        seen = {}
        keyed = []
        for index in sorted(indices, key=lambda i: tie(rows[i])):
            row = rows[index]
            study = study_of(row)
            seen[study] = seen.get(study, -1) + 1
            long_first = row.get("truth_assembly_strategy") in ("long_read_first_hybrid", "long_read_only")
            keyed.append(((0 if long_first else 1, seen[study]), index))
        keyed.sort(key=lambda item: item[0])
        arms = {}
        for _, index in keyed:
            arms.setdefault(rows[index].get("selection_arm") or "", []).append(index)
        names = sorted(arms, key=lambda name: (name != "recent", name))
        merged, cursors = [], {name: 0 for name in names}
        while len(merged) < len(indices):
            for name in names:
                if cursors[name] < len(arms[name]):
                    merged.append(arms[name][cursors[name]])
                    cursors[name] += 1
        return merged

    queues = {species: species_queue(indices) for species, indices in by_species.items()}
    main = sorted((s for s in queues if len(queues[s]) >= main_min), key=lambda s: (-len(queues[s]), s))
    minor = sorted((s for s in queues if s not in main), key=lambda s: (-len(queues[s]), s))
    order = []
    for group in (main, minor):
        position = 0
        while any(position < len(queues[s]) for s in group):
            for species in group:
                if position < len(queues[species]):
                    order.append(queues[species][position])
            position += 1
    return order
