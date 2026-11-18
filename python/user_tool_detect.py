#!/usr/bin/env python3
"""Recognise what a user tool wrote, by CONTENT, for `[output] format = auto` (docs/ADDING_TOOLS.md, "Auto-detect").

detect(path) looks at one file or folder and returns what it is, deterministically and without guessing:

    FASTA file                                   -> plasmid_fasta
    folder holding FASTA files                   -> fasta_dir (non-FASTA files in it are ignored and reported)
    delimited table (comma, tab or semicolon;    -> contig_bins   when it has a contig-id column and a bin/cluster column
      a header may start with '#', comment       -> contig_labels when it has a contig-id column and a label or a
      lines before it are skipped)                  probability column (a table with both serves both)
    anything else (empty, binary, no usable columns)  -> nothing; `why` says what was seen

choose(candidates, task) picks, per task, the best detected output by a fixed priority (PRIORITY below). Two candidates
that could serve the same task equally are an AmbiguityError listing them; nothing usable is a NothingRecognised error
listing what was seen. Neither is ever resolved by a silent guess.
"""

import csv
import gzip
import io
import re
from pathlib import Path

FASTA_SUFFIXES = (".fa", ".fasta", ".fna", ".fa.gz", ".fasta.gz", ".fna.gz")
SAMPLE_BYTES = 262144
HEADER_COMMENT = "#"

# Column vocabularies (compared lower-case, with spaces and dashes read as underscores). The order is the priority.
CONTIG_NAMES = ("contig_id", "contig", "contigid", "contig_name", "sequence_id", "seq_id", "seqid", "sequence_name",
                "sequence", "seq_name", "seq", "node", "node_id", "record_id", "record", "query", "name", "id")
BIN_NAMES = ("bin", "bin_id", "plasmid_bin", "primary_cluster_id", "cluster", "cluster_id", "plasmid_id", "plasmid_name",
             "plasmid_cluster", "group", "component", "predicted_plasmid", "plasmid")
LABEL_NAMES = ("label", "prediction", "predicted", "predicted_label", "class", "classification", "call", "result",
               "molecule_type", "type", "is_plasmid", "plasmid_prediction", "prediction_label")
SCORE_NAMES = ("plasmid_probability", "plasmid_prob", "probability", "prob", "p_plasmid", "plasmid_score", "score",
               "confidence", "posterior")
PLASMID_VALUES = {"plasmid", "plasmids", "plasmidic", "1", "true", "yes", "p", "plasmid_derived"}
CHROMOSOME_VALUES = {"chromosome", "chromosomal", "chrom", "chr", "0", "false", "no", "c", "non_plasmid", "nonplasmid",
                     "non-plasmid", "genome", "bacterial", "unclassified", "unknown", "ambiguous", "uncertain", "other"}
NO_BIN_VALUES = ("-", "na", "n/a", "nan", "none", "null", "unbinned", "unassigned")

# Which output serves which task, best first. A table that serves labels and bins counts once per role.
PRIORITY = {
    "binning_reconstruction": ("contig_bins", "contig_labels"),
    "classification": ("contig_labels", "contig_bins"),
    "sequence_reassembly": ("plasmid_fasta", "fasta_dir"),
}
# A lower-priority format reached by derivation rather than natively (docs/ADDING_TOOLS.md, derivation table).
DERIVED = {("binning_reconstruction", "contig_labels"): "one bin per contig labelled plasmid (not a real grouping)",
           ("classification", "contig_bins"): "a contig that is in any bin is plasmid"}


class DetectError(ValueError):
    """Base: the message names the candidates and what was seen."""


class AmbiguityError(DetectError):
    pass


class NothingRecognised(DetectError):
    pass


def _norm(name):
    return re.sub(r"[\s\-]+", "_", name.strip().lstrip(HEADER_COMMENT).strip().lower())


def _read_head(path):
    raw = open(path, "rb").read(SAMPLE_BYTES + 1)
    if raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.open(path, "rb").read(SAMPLE_BYTES + 1)
        except (OSError, EOFError):
            return None, "a damaged gzip file"
    if b"\x00" in raw[:4096]:
        return None, "a binary file"
    return raw.decode("utf-8", errors="replace"), ""


def is_fasta_name(name):
    return name.lower().endswith(FASTA_SUFFIXES)


def _delimiter(lines):
    """The delimiter whose field count is the same (and above one) on most lines; tab, comma, semicolon in that order."""
    best, best_score = None, 0
    for delim in ("\t", ",", ";"):
        counts = [len(next(csv.reader([l], delimiter=delim))) for l in lines[:25]]
        if not counts:
            continue
        mode = max(set(counts), key=lambda c: (counts.count(c), c))
        if mode < 2:
            continue
        score = counts.count(mode) * 100 + mode
        if score > best_score:
            best, best_score = delim, score
    return best


def _first_match(columns, vocabulary):
    for wanted in vocabulary:
        for index, column in enumerate(columns):
            if _norm(column) == wanted:
                return index
    return None


def _is_number(text):
    try:
        float(text)
        return True
    except ValueError:
        return False


def split_table(lines, delimiter, header=True, comment=HEADER_COMMENT):
    """(header fields, body rows) for non-blank text lines: comment lines are skipped, except a first line starting
    with the comment mark that has as many fields as the data under it, which is the header ('#contig<TAB>bin')."""
    split = (lambda l: l.split()) if delimiter is None else (lambda l: next(csv.reader([l], delimiter=delimiter)))
    lines = [l.rstrip("\r\n") for l in lines if l.strip()]
    head, body = [], list(lines)
    if comment:
        data = [l for l in lines if not l.lstrip().startswith(comment)]
        first_comment = lines and lines[0].lstrip().startswith(comment)
        if header and first_comment and data and len(split(lines[0].lstrip()[len(comment):])) == len(split(data[0])) >= 2:
            head, body = split(lines[0].lstrip()[len(comment):]), data
            return head, [split(l) for l in body]
        body = data
    if header and body:
        head, body = split(body[0]), body[1:]
    return head, [split(l) for l in body]


def _describe_table(text):
    """A dict describing a recognised table, or {"why": reason} when it is not one."""
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return {"why": "the file is empty"}
    # The sample may end mid-line: drop the last line when the text was cut.
    if len(text) >= SAMPLE_BYTES and len(lines) > 1:
        lines = lines[:-1]
    body_lines = [l for l in lines if not l.lstrip().startswith(HEADER_COMMENT)]
    sniff = body_lines or [l.lstrip()[1:] for l in lines]
    delim = _delimiter(sniff)
    if delim is None:
        shown = lines[0][:60].replace("\t", "<TAB>")
        return {"why": f"not a FASTA file and not a delimited table with two or more columns (first line: '{shown}')"}
    head, rows = split_table(lines, delim, header=True)
    names = [_norm(h) for h in head]
    has_header = any(n in CONTIG_NAMES for n in names)   # a header always names the contig-id column
    if not has_header and len(rows) >= 1 and not any(_is_number(c) for c in head) and any(_is_number(c) for c in rows[0]):
        return {"why": f"a table, but no contig-id column (columns: {', '.join(head)}; expected one of "
                       f"{', '.join(CONTIG_NAMES[:6])}...)"}
    columns = head
    if not has_header:
        head, rows = split_table(lines, delim, header=False)
        columns = [f"column{i + 1}" for i in range(max((len(r) for r in rows), default=0))]
        head = columns
    result = {"delimiter": delim, "header": has_header, "columns": list(columns), "rows": len(rows)}
    contig = _first_match(columns, CONTIG_NAMES) if has_header else 0
    if contig is None:
        return {"why": f"a table, but no contig-id column (columns: {', '.join(columns)}; expected one of "
                       f"{', '.join(CONTIG_NAMES[:6])}...)"}
    others = [i for i in range(len(columns)) if i != contig]

    def values(i):
        return [r[i].strip() for r in rows if i < len(r) and r[i].strip()]

    bin_i = label_i = score_i = None
    if has_header:
        bin_i = _first_match([columns[i] if i != contig else "" for i in range(len(columns))], BIN_NAMES)
        label_i = _first_match([columns[i] if i != contig else "" for i in range(len(columns))], LABEL_NAMES)
        score_i = _first_match([columns[i] if i != contig else "" for i in range(len(columns))], SCORE_NAMES)
        # A column named 'plasmid' is a label when its values are class names, a bin otherwise.
        if bin_i is not None and _norm(columns[bin_i]) == "plasmid":
            vals = {v.lower() for v in values(bin_i)}
            if vals and vals <= (PLASMID_VALUES | CHROMOSOME_VALUES):
                label_i, bin_i = (label_i if label_i is not None else bin_i), None
        if score_i is not None:
            vals = values(score_i)
            if not vals or not all(_is_number(v) and 0.0 <= float(v) <= 1.0 for v in vals):
                score_i = None
        if label_i is not None:
            vals = {v.lower() for v in values(label_i)}
            if vals and not (vals & (PLASMID_VALUES | CHROMOSOME_VALUES)):
                label_i = None   # e.g. a free-text 'type' column: not a plasmid/chromosome call
    elif len(others) == 1:
        vals = values(others[0])
        low = {v.lower() for v in vals}
        if vals and all(_is_number(v) and 0.0 <= float(v) <= 1.0 for v in vals) and low - {"0", "1"}:
            score_i = others[0]
        elif low and low <= (PLASMID_VALUES | CHROMOSOME_VALUES):
            label_i = others[0]
        elif vals:
            bin_i = others[0]
    if bin_i is None and label_i is None and score_i is None:
        return {"why": f"a table with a contig-id column ({columns[contig]}) but no bin/cluster, label or probability "
                       f"column (columns: {', '.join(columns)})"}
    spec = (lambda i: columns[i] if has_header else str(i + 1))  # noqa: E731
    roles = []
    if bin_i is not None:
        roles.append({"format": "contig_bins", "contig_column": spec(contig), "bin_column": spec(bin_i),
                      "bin_none_values": ",".join(NO_BIN_VALUES)})
    if label_i is not None or score_i is not None:
        role = {"format": "contig_labels", "contig_column": spec(contig)}
        if label_i is not None:
            present = {v for v in values(label_i)}
            role["label_column"] = spec(label_i)
            role["plasmid_values"] = ",".join(sorted(v for v in present if v.lower() in PLASMID_VALUES)) or "plasmid"
        if score_i is not None:
            role["score_column"] = spec(score_i)
        roles.append(role)
    result.update(roles=roles, kind=roles[0]["format"],
                  why="table with columns " + ", ".join(columns) + " -> "
                  + " and ".join(r["format"] for r in roles))
    return result


def detect(path):
    """What one file or folder is. Always returns a dict with 'path', 'kind' (or None) and 'why'."""
    path = Path(path)
    out = {"path": str(path), "kind": None, "roles": [], "why": ""}
    if path.is_dir():
        fastas = sorted(f for f in path.iterdir() if f.is_file() and is_fasta_name(f.name))
        others = sorted(f.name for f in path.iterdir() if f.is_file() and not is_fasta_name(f.name))
        if fastas:
            out.update(kind="fasta_dir", roles=[{"format": "fasta_dir"}], files=[f.name for f in fastas],
                       why=f"folder with {len(fastas)} FASTA file(s)"
                       + (f"; ignored non-FASTA: {', '.join(others[:6])}" if others else ""))
        else:
            out["why"] = "a folder with no FASTA files" + (f" (it holds: {', '.join(others[:8])})" if others else " (it is empty)")
        return out
    if not path.is_file():
        out["why"] = "does not exist"
        return out
    if path.stat().st_size == 0:
        out["why"] = "the file is empty"
        return out
    text, problem = _read_head(path)
    if text is None:
        out["why"] = f"{problem}; not a FASTA file or a table"
        return out
    stripped = text.lstrip()
    if stripped.startswith(">"):
        out.update(kind="plasmid_fasta", roles=[{"format": "plasmid_fasta"}],
                   why=f"FASTA file ({stripped.count(chr(10) + '>') + 1}+ record(s))")
        return out
    table = _describe_table(text)
    if "roles" in table:
        out.update(kind=table["kind"], roles=table["roles"], table=table, why=table["why"])
    else:
        out["why"] = table["why"]
    return out


def detect_all(base, patterns):
    """Resolve each candidate glob under `base`; one detection per matched path. A glob that matches several FASTA files
    (and nothing else) is one fasta_dir-style group. Returns (detections, unmatched patterns)."""
    base = Path(base)
    found, unmatched, seen = [], [], set()
    for pattern in patterns:
        matches = sorted(base.glob(pattern)) if pattern else []
        if not matches:
            unmatched.append(pattern)
            continue
        files = [m for m in matches if m.is_file() and is_fasta_name(m.name)]
        if len(files) > 1 and len(files) == len(matches):
            key = tuple(str(m) for m in files)
            if key not in seen:
                seen.add(key)
                found.append({"path": str(files[0].parent), "pattern": pattern, "kind": "fasta_dir",
                              "roles": [{"format": "fasta_dir"}], "files": [f.name for f in files],
                              "why": f"{len(files)} FASTA files matched by {pattern}", "group": [str(f) for f in files]})
            continue
        for m in matches:
            if str(m) in seen:
                continue
            seen.add(str(m))
            d = detect(m)
            d["pattern"] = pattern
            found.append(d)
    return found, unmatched


def _rel(base, path):
    try:
        return str(Path(path).relative_to(base)).replace("\\", "/")
    except ValueError:
        return str(path)


def seen_report(base, detections, unmatched):
    lines = [f"  {_rel(base, d['path'])}: {d['why'] or 'not recognised'}" for d in detections]
    lines += [f"  (no file matches '{p}')" for p in unmatched]
    return "\n".join(lines) or "  (no candidates declared)"


def choose(base, detections, unmatched, task, allow=("contig_bins", "contig_labels", "plasmid_fasta", "fasta_dir")):
    """The (detection, role, derived-note) that serves `task`, by PRIORITY. Raises AmbiguityError when two different
    candidates tie for the best available format, NothingRecognised when none serves the task."""
    for fmt in PRIORITY[task]:
        if fmt not in allow:
            continue
        serving = [(d, r) for d in detections for r in d.get("roles", []) if r["format"] == fmt]
        if len(serving) > 1:
            names = ", ".join(f"{_rel(base, d['path'])} ({d['why']})" for d, _ in serving)
            raise AmbiguityError(
                f"task {task}: {len(serving)} candidates could each serve as {fmt}: {names}. Narrow `candidates` to "
                f"one of them, or list the formats explicitly with [output.{fmt}] path = ...")
        if serving:
            det, role = serving[0]
            return det, role, DERIVED.get((task, fmt), "")
    raise NothingRecognised(
        f"task {task}: none of the candidates is a usable output (needs "
        + " or ".join(PRIORITY[task]) + "). Seen:\n" + seen_report(base, detections, unmatched))
