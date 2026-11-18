#!/usr/bin/env python3
"""Convert a user tool's output into PlasBench's prediction files, driven by its manifest's [output] mapping.

Writes, next to --out-fasta (pred_<tool>.plasmid.fasta):
  pred_<tool>.plasmid.fasta     the hard plasmid call (always; may be empty: "predicted nothing")
  pred_<tool>.bins.tsv          bin_id<TAB>sequence_id, for task = reconstruction (adapters/BINS.md)
  pred_<tool>.candidates.fasta  every scored contig, and
  pred_<tool>.scores.tsv        record_id<TAB>probability, when the output has a score column (adapters/SCORES.md)
  pred_<tool>.<tool>.provenance.json   what was read, how ids were mapped, and anything resolved on the way

A tool with several tasks or several output types is converted once per task row (--task, --id): the command ran once, and each
row picks the best output it can from what the tool wrote (docs/ADDING_TOOLS.md, derivation table), recording the choice in the
provenance file. `format = auto` recognises each candidate by content (python/user_tool_detect.py).

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
from plasbench_common import iter_fasta, subprocess_timeout  # noqa: E402
import user_tools  # noqa: E402
import user_tool_detect as detect  # noqa: E402

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
    """One format's mapping: [output.<format>] hints, then what auto-detection found (`found`), then [output], then the
    defaults documented in docs/ADDING_TOOLS.md."""

    def __init__(self, tool, fmt=None, found=None):
        found = found or {}

        def get(key, default=""):
            own = tool.sections.get(user_tools.OUTPUT_SECTION_PREFIX + (fmt or ""), {}).get(key)
            if own is not None and own.strip():
                return own.strip()
            if key in found:
                return str(found[key])
            return tool.get("output", key, default)
        self.tool = tool
        self.format = fmt or get("format")
        raw_delimiter = get("delimiter", "tab")
        self.delimiter = DELIMITERS.get(raw_delimiter.lower(), raw_delimiter)
        self.header = get("header", "yes").lower() in ("yes", "true", "1")
        self.comment = get("comment", "#")
        self.contig_column = get("contig_column", "1")
        self.bin_column = get("bin_column", "2")
        self.bin_none = {v.strip().lower() for v in get("bin_none_values", "").split(",") if v.strip()}
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
        """(header, body) of the table, honouring header, delimiter and comment lines."""
        with open(path, encoding="utf-8", errors="replace", newline="") as handle:
            lines = [l.rstrip("\r\n") for l in handle if l.strip()]
        return detect.split_table(lines, self.delimiter, self.header, self.comment)

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
    pairs = [(c, b) for c, b in pairs if c and b and b.lower() not in mapping.bin_none]
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


def from_fasta_dir(path, mapping, prov, group=None):
    folder = Path(path)
    if group:   # auto-detection matched several FASTA files with one pattern: they are the folder's files
        files = sorted(Path(g) for g in group)
    else:
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


def run_adapter(tool, output, contigs, out_fasta, task):
    script = tool.resolve(tool.output_get("adapter", "adapter"))
    launcher = ["bash"] if script.endswith(".sh") else [sys.executable] if script.endswith(".py") else []
    result = subprocess.run(launcher + [script, output, contigs, out_fasta], timeout=subprocess_timeout(),
                            env=dict(os.environ, PLASBENCH_TASK=task))
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


def select_output(tool, output, task, sample):
    """Which of the tool's outputs serves `task`: {"format", "path", "found", "group", "note", "seen"}. One explicit format
    is used as the stage located it (the behaviour before several formats existed); several explicit formats, or
    auto, pick by the documented priority and fail with the reason when nothing serves the task."""
    formats = tool.formats
    if not tool.multi_output:
        return {"format": formats[0], "path": str(output), "found": {}, "group": None,
                "note": detect.DERIVED.get((task, formats[0]), ""), "seen": []}
    base = Path(output)
    if tool.auto:
        patterns = [p.replace("{sample}", sample) for p in user_tools._split_commas(tool.get("output", "candidates"))]
        found, unmatched = detect.detect_all(base, patterns)
        seen = [{"path": detect._rel(base, d["path"]), "kind": d["kind"], "why": d["why"]} for d in found]
        try:
            det, role, derived = detect.choose(base, found, unmatched, task)
        except detect.DetectError as exc:
            raise OutputError(str(exc)) from exc
        return {"format": role["format"], "path": det["path"], "found": role, "group": det.get("group"),
                "note": derived, "seen": seen + [{"path": p, "kind": None, "why": "no file matches"} for p in unmatched]}
    declared = [f for f in formats if f != "adapter"]
    order = (["adapter"] if "adapter" in formats and task in tool.adapter_tasks else []) \
        + [f for f in detect.PRIORITY[task] if f in declared]
    tried = []
    for fmt in order:
        own = tool.output_get(fmt, "path").replace("{sample}", sample)
        path = base / own if own else base
        if path.exists():
            return {"format": fmt, "path": str(path), "found": {}, "group": None,
                    "note": detect.DERIVED.get((task, fmt), ""), "seen": [{"path": str(path), "kind": fmt, "why": "declared"}]}
        tried.append(f"{fmt}: {path}")
    if not order:
        raise OutputError(f"task {task} cannot be produced from the declared output types ({', '.join(formats)})")
    raise OutputError(f"task {task}: none of the declared outputs was written by the tool (looked for {'; '.join(tried)})")


def convert(tool, output, contigs, out_fasta, task=None, tool_id=None, sample=""):
    task = task or tool.task
    tool_id = tool_id or tool.name
    stem = out_fasta[:-len(".plasmid.fasta")] if out_fasta.endswith(".plasmid.fasta") else out_fasta
    for suffix in (".bins.tsv", ".candidates.fasta", ".scores.tsv"):
        if os.path.exists(stem + suffix):
            os.remove(stem + suffix)
    if not Path(output).exists():
        raise OutputError(f"the tool did not write {output} ([output] path)")
    choice = select_output(tool, output, task, sample)
    fmt, path = choice["format"], choice["path"]
    mapping = Mapping(tool, fmt, choice["found"])
    prov = {"tool": tool.name, "id": tool_id, "task": task, "manifest": str(tool.path), "format": fmt,
            "chosen_format": fmt, "chosen_path": detect._rel(output, path) if tool.multi_output else str(path),
            "output": str(path), "output_sha256": digest(path), "candidates_seen": choice["seen"]}
    if choice["note"]:
        prov["derived"] = choice["note"]
    if tool.multi_output:
        prov["summary"] = f"{task} <- {fmt} ({prov['chosen_path']})" + (f"; {choice['note']}" if choice["note"] else "")
    if fmt == "adapter":
        run_adapter(tool, str(path), contigs, out_fasta, task)
        prov["adapter"] = tool.output_get("adapter", "adapter")
        return prov
    reconstruction = task in ("binning_reconstruction", "sequence_reassembly")
    if fmt == "contig_bins":
        records, bins, scores = from_contig_bins(path, read_assembly(contigs), mapping, prov)
    elif fmt == "contig_labels":
        assembly = read_assembly(contigs)
        records, bins, scores = from_contig_labels(path, assembly, mapping, prov, reconstruction)
        if reconstruction:
            prov["bins_flagged"] = "one bin per contig labelled plasmid: not a real grouping of contigs into plasmids"
        if scores:
            write_fasta(stem + ".candidates.fasta", [(c, assembly[c]) for c in scores])
            with open(stem + ".scores.tsv", "w", encoding="utf-8", newline="\n") as handle:
                handle.write("record_id\tprobability\n")
                for contig, score in scores.items():
                    handle.write(f"{contig}\t{score:g}\n")
    elif fmt == "plasmid_fasta":
        records, bins, scores = from_plasmid_fasta(path, mapping, prov)
    elif fmt == "fasta_dir":
        records, bins, scores = from_fasta_dir(path, mapping, prov, choice["group"])
    else:
        raise OutputError(f"unknown [output] format '{fmt}'")
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
    parser.add_argument("--out-fasta", required=True, help="results/<sample>/pred_<id>.plasmid.fasta")
    parser.add_argument("--task", default="", help="the task of this row (default: the tool's primary task)")
    parser.add_argument("--id", default="", help="the row's registry id (default: the tool's name; <name>__<task> for the other tasks)")
    parser.add_argument("--sample", default="", help="the sample id (for {sample} in an output path)")
    args = parser.parse_args(argv)
    tools = user_tools.discover()
    tool, id_task = user_tools.resolve_id(args.tool, tools)
    if tool is None:
        print(f"[user_tool_adapter] ERROR: no user tool named '{args.tool}'", file=sys.stderr)
        return 2
    task = args.task or id_task or tool.task
    tool_id = args.id or tool.task_id(task)
    if task not in tool.tasks:
        print(f"[user_tool_adapter] ERROR: {tool.name} does not declare task {task} (it declares {', '.join(tool.tasks)})", file=sys.stderr)
        return 2
    try:
        prov = convert(tool, args.output, args.contigs, args.out_fasta, task, tool_id, args.sample)
    except (OutputError, OSError, detect.DetectError) as exc:
        print(f"[user_tool_adapter] {tool_id}: {exc}", file=sys.stderr)
        return 1
    stem = args.out_fasta[:-len(".plasmid.fasta")] if args.out_fasta.endswith(".plasmid.fasta") else args.out_fasta
    with open(f"{stem}.{tool_id}.provenance.json", "w", encoding="utf-8", newline="\n") as handle:
        json.dump(prov, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(f"[user_tool_adapter] {tool_id}: {prov.get('predicted_records', '?')} record(s) -> {args.out_fasta}", file=sys.stderr)
    print(prov.get("summary") or f"{task} <- {prov['chosen_format']}")   # one line the stage records in tool_status
    return 0


if __name__ == "__main__":
    sys.exit(main())
