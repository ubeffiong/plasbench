#!/usr/bin/env python3
"""Pair paired-end FASTQ files in a directory by common naming conventions.

Recognised mate suffixes (case-sensitive, gzipped only):

    <name>_1.fastq.gz      / <name>_2.fastq.gz        (SRA / PlasBench default)
    <name>_R1.fastq.gz     / <name>_R2.fastq.gz
    <name>_R1_001.fastq.gz / <name>_R2_001.fastq.gz   (Illumina bcl2fastq)

each also with `.fq.gz`. Any lane part stays in <name>
(`S1_L001_R1_001.fastq.gz` -> sample `S1_L001`), so each lane is its own pair.
Both mates must use the same style and extension. A mate without a partner is
reported through `warn` and skipped.

Standard library only.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

MATE = re.compile(r"^(?P<sample>.+?)_(?P<r>R?)(?P<mate>[12])(?P<tail>_001)?\.(?P<ext>fastq|fq)\.gz$")


# The same idea, loosened for FINDING files rather than staging them: any of `_ . -` before the mate number, either extension case, and an uncompressed
# file is still recognised (so it can be reported as "not gzipped" instead of being silently invisible).
MATE_ANY = re.compile(r"^(?P<sample>.+?)[_.-](?P<r>R?)(?P<mate>[12])(?P<tail>[_.-]001)?\.(?P<ext>fastq|fq)(?P<gz>\.gz)?$", re.IGNORECASE)
LANE = re.compile(r"[_.-]L\d{3}(?=$|[_.-])")          # Illumina lane: S1_L001
SAMPLE_NO = re.compile(r"[_.-]S\d{1,3}(?=$|[_.-])")  # Illumina sample number: S1_S1


def isolate_name(stem: str) -> str:
    """The isolate behind a read-pair stem: lane and Illumina sample-number parts removed, so S1_S1_L001 and S1_S1_L002 are one isolate, S1."""
    name = LANE.sub("", stem)
    name = SAMPLE_NO.sub("", name) if SAMPLE_NO.search(name) and name != stem else name
    return name.strip("_.-") or stem


def find_pairs(roots, max_depth: int = 3):
    """Find read pairs anywhere under `roots`. Returns (pairs, singles): pairs are dicts {stem, r1, r2, gz}, singles are files with no mate.

    Unlike pair_fastq_files this walks sub-folders (to `max_depth`), keeps uncompressed files, and never raises on an unreadable folder.
    """
    groups: dict = {}
    singles = []
    seen = set()
    for root in roots:
        root = Path(root)
        if root.is_file():
            files = [root]
        else:
            files = []
            base_depth = len(root.parts)
            for dirpath, dirnames, filenames in os.walk(root):
                depth = len(Path(dirpath).parts) - base_depth
                dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and depth < max_depth)
                files.extend(Path(dirpath) / name for name in sorted(filenames))
        for path in files:
            if path in seen:
                continue
            match = MATE_ANY.match(path.name)
            if not match:
                if re.search(r"\.(fastq|fq)(\.gz)?$", path.name, re.IGNORECASE):
                    singles.append(path)
                    seen.add(path)
                continue
            seen.add(path)
            key = (str(path.parent), match["sample"], match["r"].upper(), match["tail"] or "", match["ext"].lower(), bool(match["gz"]))
            groups.setdefault(key, {})[match["mate"]] = path
    pairs = []
    for key, mates in sorted(groups.items()):
        if "1" in mates and "2" in mates:
            pairs.append({"stem": key[1], "r1": mates["1"], "r2": mates["2"], "gz": key[5]})
        else:
            singles.append(mates.get("1") or mates.get("2"))
    return pairs, singles


def _warn_stderr(message: str) -> None:
    print(f"  WARNING: {message}", file=sys.stderr)


def pair_fastq_files(directory, warn=_warn_stderr):
    """Return a sorted list of (sample, r1_path, r2_path) found in `directory`."""
    groups: dict = {}
    for path in sorted(Path(directory).iterdir()):
        match = MATE.match(path.name)
        if not path.is_file() or not match:
            continue
        key = (match["sample"], match["r"], match["tail"] or "", match["ext"])
        groups.setdefault(key, {})[match["mate"]] = path
    pairs = []
    for (sample, _, _, _), mates in sorted(groups.items()):
        if "1" in mates and "2" in mates:
            pairs.append((sample, mates["1"], mates["2"]))
        else:
            lone = mates.get("1") or mates.get("2")
            warn(f"{lone.name} has no matching mate file; skipped")
    return pairs


if __name__ == "__main__":
    for sample, r1, r2 in pair_fastq_files(sys.argv[1] if len(sys.argv) > 1 else "."):
        print(f"{sample}\t{r1}\t{r2}")
