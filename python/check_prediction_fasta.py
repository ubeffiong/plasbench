#!/usr/bin/env python3
"""Stage-4 well-formedness check of a tool's prediction FASTA (audit AU-035).

Exit 0 when the file is empty (a tool that found no plasmid) or every record is well formed; exit 1 and one line on stdout saying why otherwise:
sequence before the first '>' header, a '>' with no name, a sequence line with characters that are not residues, a NUL byte, or an unreadable
(for example truncated gzip) file. Before this a malformed prediction was only discovered when stage 5 tried to score it, after every tool had run.
"""
import re
import sys

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from plasbench_common import open_maybe_gz  # noqa: E402

RESIDUES = re.compile(r"^[A-Za-z*.\-]+$")


def problem(path):
    try:
        with open_maybe_gz(path, "rt") as handle:
            seen_header = False
            for number, raw in enumerate(handle, 1):
                line = raw.strip()
                if not line:
                    continue
                if "\x00" in line:
                    return f"line {number} holds a NUL byte (binary data, not FASTA)"
                if line.startswith(">"):
                    if not line[1:].strip():
                        return f"line {number} is a header with no name"
                    seen_header = True
                elif not seen_header:
                    return f"line {number} is sequence before the first '>' header"
                elif not RESIDUES.match(line):
                    return f"line {number} holds characters that are not sequence residues"
    except (OSError, EOFError, UnicodeDecodeError, ValueError) as error:
        return f"unreadable ({type(error).__name__}: {error})"
    return ""


if __name__ == "__main__":
    reason = problem(sys.argv[1])
    if reason:
        print(reason)
        sys.exit(1)
