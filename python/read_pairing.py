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

import re
import sys
from pathlib import Path

MATE = re.compile(r"^(?P<sample>.+?)_(?P<r>R?)(?P<mate>[12])(?P<tail>_001)?\.(?P<ext>fastq|fq)\.gz$")


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
