"""The deterministic parts of the guided flows of the AI help (set up a run, fix a sample sheet, add a tool).

These work WITHOUT a model: the steps and the checks are code. A model, when there is one, only explains and suggests parameters. Each function returns data for a card or a
file plan (the same plan format as plasbench/ai_files.py, so the same dry run, Apply and Undo apply); nothing here writes anything.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from . import ai_files, ai_folder
from .ai_folder import FolderError, clean

SYNONYMS = ai_folder.SYNONYMS


def safe_id(name: str) -> str:
    s = ai_files._norm_id(name)
    return s if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", s or "") else ""


def suggest_setup(scan: dict, study: str = "") -> dict:
    """A file plan that lays out every complete, gzip-compressed read pair as data/<id>/<id>_1.fastq.gz and _2.fastq.gz and writes config/my_isolates.tsv for them (reads only:
    assembly_accession NA, so the run reconstructs plasmids without scoring; a truth reference can be added later). Returns {"ops", "skipped": [reasons], "samples": n}."""
    ops, skipped, rows, used = [], [], [], set()
    for p in scan.get("pairs", []):
        if not (p["r1"] and p["r2"]):
            continue
        sid = safe_id(p["sample"])
        if not sid:
            skipped.append("%s: the name cannot be made into a safe sample id" % clean(p["sample"], 40))
            continue
        if sid.lower() in used:
            skipped.append("%s: another sample already has this id" % sid)
            continue
        if not (p["r1"]["rel"].lower().endswith(".gz") and p["r2"]["rel"].lower().endswith(".gz")):
            skipped.append("%s: the reads are not compressed (.gz); compress them first (PlasBench expects .fastq.gz)" % sid)
            continue
        used.add(sid.lower())
        ops.append({"op": "mkdir", "path": "data/%s" % sid})
        ops.append({"op": "copy", "from": p["r1"]["rel"], "to": "data/%s/%s_1.fastq.gz" % (sid, sid)})
        ops.append({"op": "copy", "from": p["r2"]["rel"], "to": "data/%s/%s_2.fastq.gz" % (sid, sid)})
        rows.append([sid, "NA", sid, "", ""])
    if rows:
        ops.append({"op": "write_sheet", "path": "config/my_isolates.tsv", "columns": ["sample_id", "assembly_accession", "sra_run", "organism", "gram_group"], "rows": rows})
    if len(ops) > ai_files.MAX_OPS:
        skipped.append("only the first %d operations are planned (about %d samples); apply, then run the flow again for the rest" % (ai_files.MAX_OPS, ai_files.MAX_OPS // 3))
        ops = ops[:ai_files.MAX_OPS - 1]
        ops = [o for o in ops if o["op"] != "write_sheet"]
        keep = {o["to"].split("/")[1] for o in ops if o["op"] == "copy"}
        rows = [r for r in rows if r[0] in keep]
        ops.append({"op": "write_sheet", "path": "config/my_isolates.tsv", "columns": ["sample_id", "assembly_accession", "sra_run", "organism", "gram_group"], "rows": rows})
    return {"ops": ops, "skipped": skipped, "samples": len(rows)}


def suggest_sheet_fix(grant: "ai_folder.Grant", rel: str) -> dict:
    """The mechanical repairs for one sheet, as a patch_sheet operation: tab delimiter, column names PlasBench knows under another name, unsafe sample ids made safe. Nothing is
    invented: a missing value is left for the person. Returns {"ops": [...], "problems": [...found], "unfixable": [...]}."""
    p = grant.resolve(rel, must_exist=True)
    text, _bom = ai_files._read_text(p)
    comments, rows, delim = ai_files._parse_table(text)
    found = [x["text"] for x in ai_folder.validate_sheet(rows, delim)]
    edits, unfixable = [], []
    head = [h.strip() for h in rows[0]]
    if delim != "\t":
        edits.append({"type": "fix_delimiter"})
    for h in head:
        t = SYNONYMS.get(h.lower().replace(" ", "_"))
        if t and h != t and t not in head and t not in [e.get("to") for e in edits]:
            edits.append({"type": "rename_column", "from": h, "to": t})
    final = [next((e["to"] for e in edits if e.get("from") == h), h) for h in head]
    if "sample_id" in final:
        i = final.index("sample_id")
        if any(i < len(r) and r[i].strip() and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", r[i].strip()) for r in rows[1:]):
            edits.append({"type": "normalise_ids"})
    for need in ("sample_id", "assembly_accession", "sra_run"):
        if need not in final:
            unfixable.append("the column %s is missing and cannot be invented: add it, or use Set up a run from my folder" % need)
    ops = [{"op": "patch_sheet", "path": rel, "edits": edits}] if edits else []
    if not edits and found:
        unfixable.append("the remaining problems need values only you know (see the list)")
    return {"ops": ops, "problems": found[:25], "unfixable": unfixable}


def tool_manifest(project, answers: dict) -> dict:
    """The manifest `plasbench tools new` would write (the same text builder), validated with the same validator, without writing anything. {"text", "ok", "problems"}."""
    ut = project.user_tools()
    name = str(answers.get("name") or "")
    tasks = answers.get("tasks") if isinstance(answers.get("tasks"), list) else [answers.get("tasks") or "binning_reconstruction"]
    source = str(answers.get("source") or "conda")
    url = str(answers.get("url") or "")
    fmt = str(answers.get("output_format") or "")
    try:
        if not ut.NAME_RE.match(name):
            raise ut.ManifestError("name '%s' must be lower-case letters, digits and _, starting with a letter" % clean(name, 30))
        if name in ut.builtin_tools():
            raise ut.ManifestError("'%s' is a built-in PlasBench tool; choose another name" % name)
        tasks = [ut._task(t) for t in tasks if t]
        for t in tasks:
            if t not in ut.TASKS:
                raise ut.ManifestError("task '%s' must be one of %s" % (clean(t, 30), ", ".join(ut.TASKS)))
        if source not in ut.SOURCES:
            raise ut.ManifestError("source '%s' must be one of %s" % (clean(source, 20), ", ".join(ut.SOURCES)))
        if source == "url" and url:
            probs = ut.source_lib.url_problems(url)
            if probs:
                raise ut.ManifestError("; ".join(probs))
        formats = [f.strip() for f in ut._split_commas(fmt) if f.strip()]
        for f in formats:
            if f not in ut.FORMATS:
                raise ut.ManifestError("output format '%s' must be one of %s" % (clean(f, 20), ", ".join(ut.FORMATS)))
        if not formats:
            formats = ["contig_bins"] if "binning_reconstruction" in tasks else ["contig_labels"] if "classification" in tasks else []
            if "sequence_reassembly" in tasks:
                formats.append("plasmid_fasta")
        text = ut._template(name, name.replace("_", " ").title(), tasks, source, url, "", "", ",".join(formats))
        result = ut.validate_text(text)
    except ut.ManifestError as exc:
        return {"text": "", "ok": False, "problems": [str(exc)]}
    problems = [str(x) for x in (result.get("problems") or [])]
    warnings = [str(x) for x in (result.get("warnings") or [])]
    return {"text": text, "ok": not problems, "problems": problems[:20], "warnings": warnings[:10], "name": name}
