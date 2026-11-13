#!/usr/bin/env python3
"""Convert a user tool's output into PlasBench's prediction files, driven by its manifest's [output] mapping.

Writes, next to --out-fasta (pred_<tool>.plasmid.fasta):
  pred_<tool>.plasmid.fasta     the hard plasmid call (always; may be empty: "predicted nothing")
  pred_<tool>.bins.tsv          bin_id<TAB>sequence_id, for task = reconstruction (adapters/BINS.md)
  pred_<tool>.candidates.fasta  every scored contig, and
  pred_<tool>.scores.tsv        record_id<TAB>probability, when the output has a score column (adapters/SCORES.md)
  pred_<tool>.<tool>.provenance.json   what was read, how ids were mapped, and anything resolved on the way

Formats ([output] format):
  contig_bins    a table: one row per contig with its bin (contig_column, bin_column)
  contig_labels  a table: one row per contig with a label and/or a score (label_column + plasmid_values,
                 score_column + threshold)
  plasmid_fasta  one FASTA of predicted plasmid sequence (each record its own bin)
  fasta_dir      a folder with one FASTA per predicted plasmid (each file a bin; fasta_glob picks the files)
  adapter        the tool's own script: `<adapter> <tool output> <assembly contigs> <out fasta>`

Exit 1 (stage 4 records the sample as skipped, with the reason) when the output does not belong to this assembly:
contig ids that are not in it after the manifest's id mapping. A contig listed in several bins is assigned to the
first one and the rest are recorded in the provenance, as for PlasBin-flow (python/plasbin_flow_adapter.py).
"""

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plasbench_common import iter_fasta  # noqa: E402
import user_tools  # noqa: E402

DELIMITERS = {"tab": "\t", "\\t": "\t", "comma": ",", ",": ",", "semicolon": ";", ";": ";", "space": None,
              "whitespace": None, "": "\t"}


class OutputError(ValueError):
    pass


def write_fasta(path, records):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for name, seq in records:
            handle.write(f">{name}\n")
            for i in range(0, len(seq), 80):
                handle.write(seq[i:i + 80] + "\n")


def read_assembly(path):
    seqs = {}
    for name, _, seq in iter_fasta(path):
        if name in seqs:
            raise OutputError(f"duplicate contig id in the assembly FASTA: {name}")
        seqs[name] = seq
    return seqs


class Mapping:
    """The [output] section, with the defaults documented in docs/ADDING_TOOLS.md."""

    def __init__(self, tool):
        get = lambda key, default="": tool.get("output", key, default)  # noqa: E731
        self.tool = tool
        self.format = get("format")
        self.delimiter = DELIMITERS.get(get("delimiter", "tab").lower(), get("delimiter"))
        self.header = get("header", "yes").lower() in ("yes", "true", "1")
        self.comment = get("comment", "#")
        self.contig_column = get("contig_column", "1")
        self.bin_column = get("bin_column", "2")
        self.label_column = get("label_column")
        self.plasmid_values = {v.strip().lower() for v in get("plasmid_values", "plasmid").split(",") if v.strip()}
        self.score_column = get("score_column")
        self.threshold = float(get("threshold", "0.5"))
        self.strip = re.compile(get("contig_id_strip_regex")) if get("contig_id_strip_regex") else None
        self.first_token = get("contig_id_from", "").lower() == "first_token"
        self.fasta_glob = get("fasta_glob", "*.fa,*.fasta,*.fna,*.fa.gz,*.fasta.gz,*.fna.gz")

    def contig_id(self, raw):
        value = raw.strip()
        if self.first_token:
            value = value.split()[0] if value.split() else value
        if self.strip:
            value = self.strip.sub("", value)
        return value

    def rows(self, path):
        """Yield dict-like accessors over the table, honouring header, delimiter and comment lines."""
        with open(path, encoding="utf-8", errors="replace", newline="") as handle:
            lines = [l.rstrip("\r\n") for l in handle if l.strip()]
        header = []
        if self.header and lines:
            # A header may itself start with the comment mark ("#contig<TAB>bin", as PlasBin-flow writes it).
            first = lines.pop(0)
            header = self._split(first[len(self.comment):] if self.comment and first.startswith(self.comment) else first)
        body = [self._split(l) for l in lines if not (self.comment and l.lstrip().startswith(self.comment))]
        return header, body

    def _split(self, line):
        if self.delimiter is None:
            return line.split()
        return next(csv.reader([line], delimiter=self.delimiter))

    def column(self, header, spec, what):
        if not spec:
            return None
        if spec.isdigit():
            index = int(spec) - 1
            if index < 0:
                raise OutputError(f"[output] {what} = {spec}: columns are numbered from 1")
            return index
        lowered = [h.strip().lower() for h in header]
        if spec.strip().lower() in lowered:
            return lowered.index(spec.strip().lower())
        raise OutputError(f"[output] {what} = '{spec}' is not a column of the tool output "
                          f"(columns: {', '.join(header) or 'no header; give a 1-based number'})")


def cell(row, index, what, line):
    if index is None:
        return None
    if index >= len(row):
        raise OutputError(f"line {line}: no column {index + 1} for {what} (the row has {len(row)})")
    return row[index].strip()


def resolve_ids(names, assembly, mapping):
    missing = sorted({n for n in names if n not in assembly})
    if missing:
        shown = ", ".join(missing[:8]) + (f" (+{len(missing) - 8} more)" if len(missing) > 8 else "")
        raise OutputError("contig id(s) in the tool output are not in this assembly (a different assembly, or the "
                          f"ids need [output] contig_id_from / contig_id_strip_regex): {shown}")


def from_contig_bins(path, assembly, mapping, prov):
    header, body = mapping.rows(path)
    ci = mapping.column(header, mapping.contig_column, "contig_column")
    bi = mapping.column(header, mapping.bin_column, "bin_column")
    pairs = [(mapping.contig_id(cell(r, ci, "contig_column", n)), cell(r, bi, "bin_column", n))
             for n, r in enumerate(body, start=2 if mapping.header else 1)]
    pairs = [(c, b) for c, b in pairs if c and b]
    resolve_ids([c for c, _ in pairs], assembly, mapping)
    assigned, multi, rows = {}, {}, []
    for contig, bin_id in pairs:
        if contig in assigned:
            if bin_id != assigned[contig]:
                multi.setdefault(contig, [assigned[contig]])
                if bin_id not in multi[contig]:
                    multi[contig].append(bin_id)
            continue
        assigned[contig] = bin_id
        rows.append((bin_id, contig))
    prov.update(bins=len({b for b, _ in rows}), contigs=len(rows), contigs_in_multiple_bins=multi)
    return [(c, assembly[c]) for _, c in rows], rows, None


def from_contig_labels(path, assembly, mapping, prov, reconstruction):
    header, body = mapping.rows(path)
    ci = mapping.column(header, mapping.contig_column, "contig_column")
    li = mapping.column(header, mapping.label_column, "label_column")
    si = mapping.column(header, mapping.score_column, "score_column")
    calls, scores, seen = [], {}, set()
    for n, row in enumerate(body, start=2 if mapping.header else 1):
        contig = mapping.contig_id(cell(row, ci, "contig_column", n) or "")
        if not contig or contig in seen:
            continue
        seen.add(contig)
        score = None
        if si is not None:
            raw = cell(row, si, "score_column", n)
            try:
                score = float(raw)
            except (TypeError, ValueError):
                raise OutputError(f"line {n}: score '{raw}' is not a number")
            if not 0.0 <= score <= 1.0:
                raise OutputError(f"line {n}: score {score} is outside [0, 1]; rescale it or drop score_column")
            scores[contig] = score
        if li is not None:
            is_plasmid = (cell(row, li, "label_column", n) or "").lower() in mapping.plasmid_values
        else:
            is_plasmid = score is not None and score >= mapping.threshold
        if is_plasmid:
            calls.append(contig)
    resolve_ids(seen, assembly, mapping)
    bins = [(f"{c}", c) for c in calls] if reconstruction else []
    prov.update(contigs_labelled=len(seen), plasmid_calls=len(calls),
                rule=("label in " + ",".join(sorted(mapping.plasmid_values))) if li is not None
                else f"score >= {mapping.threshold}")
    return [(c, assembly[c]) for c in calls], bins, scores or None


def _unique(name, used):
    candidate, k = name, 2
    while candidate in used:
        candidate, k = f"{name}_{k}", k + 1
    used.add(candidate)
    return candidate


def from_plasmid_fasta(path, mapping, prov):
    used, records, bins, renamed = set(), [], [], 0
    for name, _, seq in iter_fasta(path):
        if not seq:
            continue
        rid = _unique(mapping.contig_id(name) or "record", used)
        renamed += rid != name
        records.append((rid, seq))
        bins.append((rid, rid))
    prov.update(records=len(records), renamed=renamed)
    return records, bins, None


def from_fasta_dir(path, mapping, prov):
    folder = Path(path)
    if not folder.is_dir():
        raise OutputError(f"{path} is not a folder (format = fasta_dir)")
    files = sorted({f for pattern in mapping.fasta_glob.split(",") for f in folder.glob(pattern.strip()) if f.is_file()})
    used, records, bins = set(), [], []
    for f in files:
        stem = re.sub(r"\.(fa|fasta|fna)(\.gz)?$", "", f.name)
        for name, _, seq in iter_fasta(f):
            if not seq:
                continue
            rid = _unique(f"{stem}__{mapping.contig_id(name) or 'record'}", used)
            records.append((rid, seq))
            bins.append((stem, rid))
    prov.update(files=[f.name for f in files], records=len(records))
    return records, bins, None


def run_adapter(tool, output, contigs, out_fasta):
    script = tool.resolve(tool.get("output", "adapter"))
    launcher = ["bash"] if script.endswith(".sh") else [sys.executable] if script.endswith(".py") else []
    result = subprocess.run(launcher + [script, output, contigs, out_fasta])
    if result.returncode != 0:
        raise OutputError(f"the tool's adapter {script} exited {result.returncode}")
    if not Path(out_fasta).is_file():
        raise OutputError(f"the tool's adapter {script} did not write {out_fasta}")


def digest(path):
    p = Path(path)
    if p.is_file():
        return hashlib.sha256(p.read_bytes()).hexdigest()
    if p.is_dir():
        h = hashlib.sha256()
        for f in sorted(x for x in p.rglob("*") if x.is_file()):
            h.update(f.name.encode())
            h.update(f.read_bytes())
        return h.hexdigest()
    return None


def convert(tool, output, contigs, out_fasta):
    mapping = Mapping(tool)
    stem = out_fasta[:-len(".plasmid.fasta")] if out_fasta.endswith(".plasmid.fasta") else out_fasta
    for suffix in (".bins.tsv", ".candidates.fasta", ".scores.tsv"):
        if os.path.exists(stem + suffix):
            os.remove(stem + suffix)
    prov = {"tool": tool.name, "manifest": str(tool.path), "format": mapping.format, "output": str(output),
            "output_sha256": digest(output)}
    if not Path(output).exists():
        raise OutputError(f"the tool did not write {output} ([output] path)")
    if mapping.format == "adapter":
        run_adapter(tool, str(output), contigs, out_fasta)
        prov["adapter"] = tool.get("output", "adapter")
        return prov
    reconstruction = tool.task == "reconstruction"
    if mapping.format == "contig_bins":
        records, bins, scores = from_contig_bins(output, read_assembly(contigs), mapping, prov)
    elif mapping.format == "contig_labels":
        assembly = read_assembly(contigs)
        records, bins, scores = from_contig_labels(output, assembly, mapping, prov, reconstruction)
        if scores:
            write_fasta(stem + ".candidates.fasta", [(c, assembly[c]) for c in scores])
            with open(stem + ".scores.tsv", "w", encoding="utf-8", newline="\n") as handle:
                handle.write("record_id\tprobability\n")
                for contig, score in scores.items():
                    handle.write(f"{contig}\t{score:g}\n")
    elif mapping.format == "plasmid_fasta":
        records, bins, scores = from_plasmid_fasta(output, mapping, prov)
    elif mapping.format == "fasta_dir":
        records, bins, scores = from_fasta_dir(output, mapping, prov)
    else:
        raise OutputError(f"unknown [output] format '{mapping.format}'")
    write_fasta(out_fasta, records)
    if reconstruction:
        with open(stem + ".bins.tsv", "w", encoding="utf-8", newline="\n") as handle:
            handle.write("bin_id\tsequence_id\n")
            for bin_id, record in bins:
                handle.write(f"{bin_id}\t{record}\n")
    prov.update(predicted_records=len(records), predicted_bp=sum(len(s) for _, s in records))
    return prov


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tool", required=True)
    parser.add_argument("--output", required=True, help="the tool's output file or folder")
    parser.add_argument("--contigs", required=True, help="the assembly the tool was run on")
    parser.add_argument("--out-fasta", required=True, help="results/<sample>/pred_<tool>.plasmid.fasta")
    args = parser.parse_args(argv)
    tools = user_tools.discover()
    tool = tools.get(args.tool)
    if tool is None:
        print(f"[user_tool_adapter] ERROR: no user tool named '{args.tool}'", file=sys.stderr)
        return 2
    try:
        prov = convert(tool, args.output, args.contigs, args.out_fasta)
    except (OutputError, OSError) as exc:
        print(f"[user_tool_adapter] {tool.name}: {exc}", file=sys.stderr)
        return 1
    stem = args.out_fasta[:-len(".plasmid.fasta")] if args.out_fasta.endswith(".plasmid.fasta") else args.out_fasta
    with open(f"{stem}.{tool.name}.provenance.json", "w", encoding="utf-8", newline="\n") as handle:
        json.dump(prov, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(f"[user_tool_adapter] {tool.name}: {prov.get('predicted_records', '?')} record(s) -> {args.out_fasta}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
