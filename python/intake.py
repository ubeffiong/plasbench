#!/usr/bin/env python3
"""Bring your own isolates: get the sheet right, point at your folders, check that PlasBench can see and use what you have.

Four steps, each its own sub-command, each also a screen in `plasbench ui` -> "Your own isolates":

  template   write a sample sheet (or truth table) to fill in, with the rules as comments
  scan       look through the folder(s) you name and work out what is there: which read files
             are mates, which FASTA is each isolate's reference, which table holds the
             plasmid/chromosome labels. Nothing is copied or changed.
  stage      place what the scan found where the pipeline expects it and write the sample sheet
  check      the quick test: open every file the way the run will, and say pass / warn / fail

What it will guess, and what it will not
  It matches files to isolates by name and by folder (the two ways people organise data), says how
  sure it is, and lists every alternative it did not choose. It reads the organism off a reference
  header and marks it as a guess to confirm.
  It will NOT decide which sequences are plasmids. That is the ground truth every score rests on:
  an unlabelled sequence is written as REVIEW and the run refuses to start until a person has set it.
  A reference from a different strain, or a different species, is caught by the check (the reads
  are compared with the reference), because that is wrong in a way no file-name test can see.

Standard library only; it reuses the readers and validators the run itself uses, so passing the
check means the run will read the files the same way.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import gzip
import io
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from read_pairing import find_pairs, isolate_name  # noqa: E402
from plasbench_common import subprocess_timeout  # noqa: E402

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
FASTA_NAME = re.compile(r"\.(fa|fna|fasta|fas|fsa)(\.gz)?$", re.IGNORECASE)
GENERIC_STEMS = {"reads", "read", "sample", "fastq", "r", "raw", "seq", "sequence", "sequences", "illumina", "short", "data", "input"}
LONG_HINT = re.compile(r"(ont|nanopore|minion|promethion|pacbio|pb|hifi|ccs|long)", re.IGNORECASE)
DRAFT_HINT = re.compile(r"(contig|scaffold|NODE_|^k\d+_)", re.IGNORECASE)
REF_WORDS = re.compile(r"(reference|ref|assembly|complete|genome|hybrid|truth|closed|finished)", re.IGNORECASE)
TRUTH_NAMES = re.compile(r"(truth.*\.tsv|.*truth\.tsv)$", re.IGNORECASE)
LOCAL_COLUMNS = ("sample_id", "assembly_accession", "sra_run", "organism", "gram_group", "sample_origin", "collection_country", "source_study")


# --------------------------------------------------------------------------------------------- templates
def local_sheet_template() -> str:
    return """# PlasBench sample sheet for YOUR OWN isolates.   Save it as  config/local.tsv  (or anywhere; you choose it when you run).
# Rules:  lines starting with # are ignored   |   keep the header line   |   separate columns with a TAB, not spaces   |   one isolate per line
#
#  sample_id            A short name: letters, digits and . _ -  only (no spaces). It becomes the folder  data/<sample_id>/ .
#  assembly_accession   LOCAL  = you supply the complete reference yourself (a scored benchmark)
#                       NA     = reads only (reconstruct plasmids, no scoring: there is no truth to score against)
#  sra_run              The start of the read-file names: reads are  <sra_run>_1.fastq.gz  and  <sra_run>_2.fastq.gz .
#                       Use the same text as sample_id unless you have a reason not to. (It is NOT an SRA accession for your own data.)
#  organism             Genus and species, e.g. Escherichia coli. Some tools only run for organisms they have a database for.
#  gram_group           Gram-negative or Gram-positive. Optional; used to group results.
#  sample_origin, collection_country, source_study   Optional notes; shown in the report.
#
# Easier than typing it:  plasbench intake scan <your folder>  finds your files and  plasbench intake stage  writes this sheet for you.
# Delete the example line below before you use the sheet.
sample_id\tassembly_accession\tsra_run\torganism\tgram_group\tsample_origin\tcollection_country\tsource_study
EXAMPLE_isolate_001\tLOCAL\tEXAMPLE_isolate_001\tEscherichia coli\tGram-negative\tclinical\tNigeria\tmy_lab_2026
"""


def cohort_sheet_template(root: Path) -> str:
    header = "\t".join(["sample_id", "assembly_accession", "sra_run", "organism", "truth_technology", "truth_quality_tier", "biosample",
                        "bioproject", "sample_origin", "read_depth_x", "source_study", "gram_group", "collection_country"])
    accessions = root / "config" / "accessions.tsv"
    if accessions.is_file():
        for line in accessions.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                header = line.rstrip("\n")
                break
    return f"""# PlasBench sample sheet for a PUBLIC cohort: isolates that already have a complete genome AND a matching Illumina run at NCBI.
# Everything is downloaded for you. Use this only when your isolates are public; for your own sequencing use the "your own isolates" sheet.
# Rules: lines starting with # are ignored | keep the header | separate columns with a TAB | one isolate per line.
#  assembly_accession  the complete genome, e.g. GCF_012345678.1      sra_run  the Illumina run of the SAME isolate, e.g. SRR012345678
#  truth_technology    hybrid | long-read | short-read (how the complete genome was made)
#  truth_quality_tier  A, B or C: how well the reference is evidenced (see docs/COHORTS.md)
#  biosample, bioproject  must be the same for the genome and the reads: this is how the pairing is verified.
# Check it before running:  plasbench validate-cohort --samples <this file> --online
{header}
"""


def truth_table_template() -> str:
    return """# PlasBench truth table: which sequence of the complete reference is a plasmid and which is the chromosome.  Save as  data/<sample_id>/truth.tsv
# Rules: separate columns with a TAB | one line per sequence in the reference FASTA, none left out | sequence_id is the first word of the FASTA header
#  sequence_id    the id exactly as in the FASTA (case matters), without the leading >
#  molecule_type  PLASMID or CHROMOSOME. Nothing else is accepted; PlasBench never guesses this, because every score is judged against it.
#  length         bp. Optional, but if given it must match the FASTA.
# Never infer the type from size. If you are unsure of a sequence, do not benchmark that isolate until you are.
# `plasbench init-local` and `plasbench intake stage` write this file for you from the FASTA headers and leave REVIEW where a header does not say.
sequence_id\tmolecule_type\tlength
NZ_CP000001.1\tCHROMOSOME\t4641652
NZ_CP000002.1\tPLASMID\t98760
"""


TEMPLATES = {"local": ("local_samples.tsv", "Sample sheet for your own isolates"),
             "cohort": ("cohort_samples.tsv", "Sample sheet for a public NCBI cohort"),
             "truth": ("truth.tsv", "Truth table (plasmid or chromosome per sequence)")}


def template_text(kind: str, root: Path) -> str:
    if kind == "local":
        return local_sheet_template()
    if kind == "cohort":
        return cohort_sheet_template(root)
    if kind == "truth":
        return truth_table_template()
    raise ValueError(f"unknown template '{kind}' (choose from: {', '.join(TEMPLATES)})")


# --------------------------------------------------------------------------------------------- what to do about each message
# Every problem this module can report matches one rule below, so every error comes with a stable code, plain steps, and an honest statement of whether
# `plasbench intake check --fix` (or the "Fix what can be fixed" button) can repair it. docs/INPUT_GUIDE.md has one section per code; a test keeps the two in step.
# (code, pattern that recognises the message, one-line title, steps, repaired automatically?)
RULES = [
    ("reads-not-gzip", r"named \.gz but is not compressed|is not gzipped|not gzip-compressed.*(error|fail)", "A read file has a .gz name but is not compressed",
     "Compress it:  gzip -c file.fastq > file.fastq.gz  (then use the .gz). PlasBench does this for you with Fix.", True),
    ("reads-misnamed", r"reads are named .* but the run expects", "The read files have different names from the ones the sheet expects",
     "Either rename the files to <sra_run>_1.fastq.gz and <sra_run>_2.fastq.gz, or change the sra_run column to their shared start. PlasBench makes correctly named copies for you with Fix.", True),
    ("reads-missing", r"missing (forward|reverse) reads|is where the run looks|not found in", "A read file is missing",
     "Put both read files in data/<sample_id>/, named <sra_run>_1.fastq.gz and <sra_run>_2.fastq.gz, or run  plasbench intake stage <your folder>  to place them for you.", False),
    ("reads-empty", r"empty \(0 bytes\)|file is empty|holds no reads|contains no reads|no reads could be sampled", "A read file is empty",
     "The copy probably failed or was interrupted. Copy or download the file again and compare its size with the original.", False),
    ("reads-corrupt", r"not valid FASTQ|(fastq|fq|reads?).*(could not be read|truncated|corrupt)|truncated or corrupt|not FASTQ", "A read file is damaged or not FASTQ",
     "Test it with  gzip -t file.fastq.gz . If that reports an error, the file was cut short: copy or download it again. If it opens but is not FASTQ, it is the wrong file.", False),
    ("reads-mates", r"not mates in the same order|different numbers of reads", "Read 1 and read 2 do not match each other",
     "The two files must be the SAME library, same reads in the same order. Re-copy both from the sequencer's output. If they came from SRA, re-extract with  fasterq-dump --split-files <accession> . Do not pair files only because their names look alike.", False),
    ("reads-long", r"reads are long|short-read length", "These are long reads, not paired short reads",
     "The short-read route needs paired Illumina reads. Long reads (Nanopore/PacBio) are used in the self-built hybrid route; see the README, Route C. Do not rename them to _1/_2.", False),
    ("reads-unpaired", r"no mate|unpaired|single-end", "A read file has no mate",
     "PlasBench needs paired-end reads: one file for read 1 and one for read 2. Find the missing mate file, or leave this isolate out.", False),
    ("folder-missing", r"no directory|folder exists|folder is missing", "The isolate's folder does not exist",
     "Run  plasbench intake stage <your folder>  to create it and place the files, or create data/<sample_id>/ yourself and put the files in it.", False),
    ("reference-missing", r"missing reference\.fna|Reference is present|reference\.fna is missing", "A scored isolate has no reference",
     "Scoring needs the isolate's complete genome. Put it in the isolate's folder as reference.fna (or name it after the isolate and run stage again). If you have no complete genome, set assembly_accession to NA in the sheet: the isolate is then reconstructed but not scored.", False),
    ("reference-unreadable", r"Reference.*(does not start with|could not be read|no FASTA records|is empty|opens)|reference\.fna (is empty|has no FASTA)", "The reference file cannot be read as FASTA",
     "A FASTA file starts with a line beginning with >. Open the file in a text editor: if it is empty or starts with something else, it is the wrong file or a bad copy. Copy the correct genome FASTA again.", False),
    ("reference-duplicate-ids", r"repeats sequence id", "Two reference sequences have the same name",
     "Scores match tools' output to reference sequences by name, so names must be unique. Edit the FASTA headers so each sequence has its own first word, and keep truth.tsv in step.", False),
    ("reference-protein", r"looks like protein", "The reference holds protein, not DNA",
     "Use the genome FASTA (usually .fna), not the protein FASTA (.faa).", False),
    ("reference-draft", r"DRAFT|draft assembly", "The reference looks like a draft assembly",
     "A benchmark's truth must be a complete genome: the chromosome and each plasmid as one closed sequence. A set of contigs is not a ground truth, because a tool cannot be wrong about a plasmid you have not assembled. Use a hybrid or long-read assembly, or run this isolate reads-only.", False),
    ("reference-size", r"outside the usual", "The reference size is unusual",
     "A bacterial genome is normally 0.3-15 million bases. Check this is the right file (not a plasmid-only or phage file). If it is right, ignore this note.", False),
    ("reference-ambiguous", r"could be the reference of|Several FASTA files could be", "More than one reference could belong to this isolate",
     "PlasBench will not guess which genome belongs to which isolate. Name each reference after its isolate (for example KP01.fna for KP01) or put it in that isolate's own folder, then scan again.", False),
    ("reference-wrong-isolate", r"Reads come from this reference", "The reads do not match the reference",
     "Scores are only meaningful if the reference is the genome of the SAME isolate the reads came from. A close relative does not count. Find the reference that belongs to these reads (check sample names and the lab record). If you only have the reads, run the isolate reads-only (assembly_accession NA).", False),
    ("truth-review", r"REVIEW", "Some sequences are still marked REVIEW",
     "These sequences' headers do not say whether they are plasmid or chromosome, and PlasBench will not guess. Open 'Label sequences' (or edit data/<sample_id>/truth.tsv) and set each to PLASMID or CHROMOSOME, using what you know about the assembly.", False),
    ("truth-missing", r"no truth\.tsv and no sequence_report", "There is no truth table",
     "A truth table says which reference sequences are plasmids. PlasBench writes a draft from the FASTA headers (leaving REVIEW where the header does not say) when you press Fix.", True),
    ("truth-mismatch", r"is not in .*(reference|\.fna)|missing from the truth table|duplicate sequence_id|not PLASMID or CHROMOSOME|expected at least sequence_id|Truth table matches", "The truth table does not match the reference",
     "Every reference sequence needs exactly one row, with its id spelled exactly as in the FASTA (capitals matter) and the type PLASMID or CHROMOSOME. Fix repairs spelling-case, stray spaces and Windows line endings, and adds any missing sequence as REVIEW. Then set the REVIEW rows yourself.", True),
    ("truth-no-plasmid", r"no sequence is labelled PLASMID|truth has plasmids", "The truth has no plasmids",
     "Nothing can be recovered from an isolate with no plasmid, so recall is undefined for it. Keep it if it is a genuine plasmid-free control; otherwise check the labels.", False),
    ("sample-id-unsafe", r"not a usable sample id|Sample name is usable", "The sample name has characters that are not allowed",
     "Use letters, digits and . _ - only, with no spaces (it becomes a folder name). Rename the isolate in the list before staging.", False),
    ("sheet-example", r"example row", "The sheet still has the template's example row",
     "Delete the EXAMPLE_ line. Fix removes it for you.", True),
    ("long-reads-info", r"Long-read files were found", "Long-read files were found",
     "They are not staged here. The self-built hybrid route is set up by hand; see the README, Route C.", False),
]
RULE_CODES = tuple(r[0] for r in RULES)


def explain(text: str, fix: str = "") -> dict:
    """The code, the steps to take and whether Fix repairs it, for a message. The emitter's own more specific fix (if any) is kept and the general steps follow it."""
    for code, pattern, title, steps, auto in RULES:
        if re.search(pattern, text, re.IGNORECASE):
            return {"code": code, "title": title, "fix": (fix + "\n" + steps).strip() if fix and fix not in steps else steps, "auto": auto,
                    "guide": f"docs/INPUT_GUIDE.md#{code}"}
    return {"code": "other", "title": "", "auto": False, "guide": "docs/INPUT_GUIDE.md",
            "fix": fix or "Read the message, correct the file it names, then run  plasbench intake check  again. docs/INPUT_GUIDE.md lists the usual causes."}


# --------------------------------------------------------------------------------------------- file readers
def open_text(path: Path):
    """Text handle for a plain or gzipped file."""
    with open(path, "rb") as handle:
        gz = handle.read(2) == b"\x1f\x8b"
    return gzip.open(path, "rt", errors="replace") if gz else open(path, "r", encoding="utf-8", errors="replace")


def is_gzip(path: Path) -> bool:
    try:
        with open(path, "rb") as handle:
            return handle.read(2) == b"\x1f\x8b"
    except OSError:
        return False


def sniff_fastq(path: Path, limit: int = 400) -> dict:
    """Open the file the way the pipeline will and look at the first reads. Never raises."""
    info = {"path": str(path), "gz_name": path.name.lower().endswith(".gz"), "gz_content": is_gzip(path), "reads": 0, "median_len": None, "error": ""}
    try:
        size = path.stat().st_size
        info["size"] = size
        if size == 0:
            info["error"] = "the file is empty (0 bytes)"
            return info
        lengths = []
        with open_text(path) as handle:
            while len(lengths) < limit:
                head, seq, plus, qual = (handle.readline() for _ in range(4))
                if not head:
                    break
                if not head.startswith("@") or not plus.startswith("+") or len(seq.strip()) != len(qual.strip()):
                    info["error"] = f"read {len(lengths) + 1} is not valid FASTQ (needs @name, sequence, +, qualities of equal length)"
                    break
                lengths.append(len(seq.strip()))
        info["reads"] = len(lengths)
        if lengths:
            info["median_len"] = int(statistics.median(lengths))
        elif not info["error"]:
            info["error"] = "the file holds no reads"
    except (OSError, EOFError) as exc:
        info["error"] = f"could not be read ({exc}); a truncated or corrupt download looks like this"
    return info


def sniff_fasta(path: Path) -> dict:
    """Records, length, id uniqueness, whether it is nucleotide and whether it looks like a finished genome or a draft. Never raises."""
    info = {"path": str(path), "records": 0, "total_bp": 0, "largest": 0, "ids": [], "duplicates": [], "empty": [], "headers": {},
            "nucleotide_fraction": 1.0, "draft_like": False, "error": ""}
    try:
        current, length, acgtn, letters = None, 0, 0, 0
        with open_text(path) as handle:
            first = True
            for line in handle:
                if first:
                    first = False
                    if not line.startswith(">"):
                        info["error"] = "does not start with '>': this is not a FASTA file"
                        return info
                if line.startswith(">"):
                    if current is not None:
                        info["largest"] = max(info["largest"], length)
                        if length == 0:
                            info["empty"].append(current)
                    header = line[1:].strip()
                    parts = header.split(None, 1)
                    current = parts[0] if parts else ""
                    if current in info["headers"]:
                        info["duplicates"].append(current)
                    info["headers"][current] = parts[1] if len(parts) > 1 else ""
                    info["records"] += 1
                    length = 0
                else:
                    text = line.strip()
                    length += len(text)
                    info["total_bp"] += len(text)
                    if letters < 200000:
                        upper = text.upper()
                        letters += len(upper)
                        acgtn += sum(upper.count(c) for c in "ACGTNURYKMSWBDHV")
        if current is not None:
            info["largest"] = max(info["largest"], length)
            if length == 0:
                info["empty"].append(current)
        info["ids"] = list(info["headers"])
        info["nucleotide_fraction"] = acgtn / letters if letters else 1.0
        info["draft_like"] = info["records"] > 8 and sum(1 for i in info["ids"] if DRAFT_HINT.search(i)) >= 0.8 * info["records"]
    except (OSError, EOFError) as exc:
        info["error"] = f"could not be read ({exc})"
    return info


def organism_guess(headers: dict) -> str:
    """'Escherichia coli strain X plasmid pABC, complete sequence' -> 'Escherichia coli'. A guess from the header text; the user confirms it."""
    for description in headers.values():
        match = re.match(r"^([A-Z][a-z]+ [a-z][a-z.]+)\b", description or "")
        if match and match.group(1).split()[1] not in ("sp.", "strain", "plasmid", "chromosome"):
            return match.group(1)
    return ""


# --------------------------------------------------------------------------------------------- scan
def _tokens(text: str) -> set:
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if t}


def _match_score(isolate_id: str, stem: str, directory: Path, fasta: Path) -> tuple:
    """How well a FASTA file belongs to an isolate, and why. Higher is better; the reason is shown to the user."""
    name = FASTA_NAME.sub("", fasta.name)
    reasons, score = [], 0
    if name.lower() == isolate_id.lower() or name.lower() == stem.lower():
        score += 6
        reasons.append("file name is the isolate name")
    elif isolate_id.lower() in name.lower() or (len(stem) >= 3 and stem.lower() in name.lower()):
        score += 4
        reasons.append("file name contains the isolate name")
    elif _tokens(isolate_id) & _tokens(name) - {"1", "2", "r1", "r2", "reference", "ref", "assembly", "complete", "genome"}:
        score += 2
        reasons.append("file name shares a word with the isolate name")
    if fasta.parent.name.lower() == isolate_id.lower():
        score += 4
        reasons.append("it is in a folder named after the isolate")
    if fasta.parent == directory:
        score += 2
        reasons.append("same folder as the reads")
    elif directory in fasta.parents or fasta.parent in directory.parents:
        score += 1
        reasons.append("in a neighbouring folder")
    if REF_WORDS.search(name):
        score += 1
        reasons.append("named like a reference")
    return score, "; ".join(reasons)


def _truth_for(reference: Path, isolate_id: str):
    """(kind, path) of the label source next to a reference: an NCBI sequence report, or a truth table. Looked for beside the reference only."""
    folder = reference.parent
    stem = FASTA_NAME.sub("", reference.name)
    for candidate in (folder / f"{isolate_id}.sequence_report.jsonl", folder / f"{stem}.sequence_report.jsonl", folder / "sequence_report.jsonl"):
        if candidate.is_file():
            return "sequence_report", candidate
    tables = sorted(p for p in folder.glob("*.tsv") if TRUTH_NAMES.search(p.name))
    exact = [p for p in tables if isolate_id.lower() in p.name.lower() or stem.lower() in p.name.lower() or p.name.lower() == "truth.tsv"]
    for candidate in exact or (tables if len(tables) == 1 else []):
        return "truth_table", candidate
    return "", None


WINDOWS_DEVICE = re.compile(r"^(CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[0-9]|LPT[0-9])(\..*)?$", re.IGNORECASE)
META_HINT = re.compile(r"(metagenom|microbiome|stool|f(a)?ecal|faeces|feces|wastewater|sewage|soil|zymo|mock[_-]?community|community)", re.IGNORECASE)


def id_problem(sample_id: str) -> str:
    """'' when a sample id can be used as a folder name everywhere, else the reason (it becomes data/<sample_id>/ on Windows too)."""
    if not SAFE_ID.match(sample_id or ""):
        return f"'{sample_id}' is not a usable sample id (letters, digits . _ - only)"
    if WINDOWS_DEVICE.match(sample_id):
        return f"'{sample_id}' is a Windows device name (CON, NUL, COM1 ...) and cannot be a folder name; choose another sample id"
    return ""


def scan(roots, depth: int = 3, sample_reads: bool = True, accept=None, references=None) -> dict:
    """Find isolates under the folders. Returns a plain dict (JSON-able): isolates, leftovers and notes. Changes nothing on disk.

    `accept(path) -> reason` (optional) is asked about every file BEFORE it is opened; a file with a reason is left out and listed under `refused` (the AI help uses it to keep the scan
    inside the folder the person chose: no links, no hidden or device names). `references` maps an isolate id to the FASTA the PERSON chose as its reference (`--reference ID=FILE`);
    it replaces the name-based guess for that isolate."""
    roots = [Path(r).expanduser() for r in roots]
    references = {k: str(Path(v)) for k, v in (references or {}).items()}
    notes, missing = [], [str(r) for r in roots if not r.exists()]
    roots = [r for r in roots if r.exists()]
    for m in missing:
        notes.append(f"{m} does not exist or cannot be seen from here")
    pairs, singles = find_pairs(roots, depth)
    refused = []

    def _ok(path) -> bool:
        if accept is None:
            return True
        why = accept(Path(path))
        if why:
            refused.append({"path": str(path), "reason": why})
        return not why

    if accept is not None:
        pairs = [p for p in pairs if _ok(p["r1"]) & _ok(p["r2"])]
        singles = [p for p in singles if _ok(p)]

    fasta_files, seen = [], set()
    for root in roots:
        if root.is_file():
            candidates = [root]
        else:
            base = len(root.parts)
            candidates = []
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and len(Path(dirpath).parts) - base < depth)
                candidates.extend(Path(dirpath) / n for n in sorted(filenames))
        for path in candidates:
            if FASTA_NAME.search(path.name) and path not in seen:
                seen.add(path)
                if _ok(path):
                    fasta_files.append(path)

    # one isolate = the read pairs of one folder that share an isolate name (several lanes are one isolate)
    groups: dict = {}
    for pair in pairs:
        stem = pair["stem"]
        name = isolate_name(stem)
        folder = pair["r1"].parent
        if name.lower() in GENERIC_STEMS and SAFE_ID.match(folder.name or ""):
            name = folder.name
        groups.setdefault((str(folder), name), []).append(pair)
    names = [name for (_, name) in groups]
    isolates = []
    for (folder, name), group in sorted(groups.items()):
        group.sort(key=lambda p: p["r1"].name)
        isolate_id = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._-") or "isolate"
        if names.count(name) > 1:   # the same name in two folders: the folder tells them apart
            isolate_id = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{Path(folder).name}_{name}").strip("._-")
        isolates.append({"id": isolate_id, "folder": folder, "stem": group[0]["stem"], "pairs": group})
    ids = [i["id"] for i in isolates]
    for item in isolates:
        if ids.count(item["id"]) > 1:
            item["id"] = f"{item['id']}_{abs(hash(item['folder'])) % 1000}"

    claimed: dict = {}
    for item in isolates:
        directory = Path(item["folder"])
        scored = sorted(((_match_score(item["id"], item["stem"], directory, f), f) for f in fasta_files), key=lambda x: -x[0][0])
        item["_scored"] = [(s, f) for s, f in scored if s[0] > 0]
    # a lone isolate with a lone FASTA belongs together even when the names say nothing
    for item in isolates:
        issues, top = [], item["_scored"]
        chosen, how = None, ""
        item["candidates"] = [str(f) for _, f in top[:6]]
        forced = references.get(item["id"])
        if forced is not None:
            match = [f for f in fasta_files if str(f) == forced or os.path.normcase(str(f.resolve())) == os.path.normcase(str(Path(forced).resolve()))]
            if match:
                chosen, how = match[0], "chosen by you"
            else:
                issues.append(("error", f"The reference chosen for {item['id']} ({Path(forced).name}) is not one of the FASTA files found here.", "Choose one of the FASTA files the scan lists."))
        elif top:
            best = top[0]
            runner = top[1] if len(top) > 1 else None
            if best[0][0] >= 4 and (runner is None or best[0][0] - runner[0][0] >= 2):
                chosen, how = best[1], f"confident: {best[0][1]}"
            elif best[0][0] >= 2 and (runner is None or best[0][0] - runner[0][0] >= 2):
                chosen, how = best[1], f"likely: {best[0][1]}"
            else:
                issues.append(("warn", f"Several FASTA files could be the reference for {item['id']} and none is clearly the right one: "
                               + ", ".join(f.name for _, f in top[:4]) + ". Rename one after the isolate or put it in the isolate's folder.", ""))
        elif len(isolates) == 1 and len(fasta_files) == 1:
            chosen, how = fasta_files[0], "likely: the only isolate and the only FASTA file found"
        item["reference_how"] = how
        item["reference"] = chosen
        if chosen is not None:
            claimed.setdefault(str(chosen), []).append(item["id"])
        item["issues"] = issues
    # a FASTA that is the best match for several isolates belongs to none of them until a person says which: giving it to all would score every isolate
    # against a genome that is at most one of theirs, and giving it to the first would be a coin toss
    by_id = {i["id"]: i for i in isolates}
    for item in isolates:
        if item["reference"] is not None and len(claimed[str(item["reference"])]) > 1:
            owners = claimed[str(item["reference"])]
            if any(by_id[o]["reference_how"] == "chosen by you" for o in owners) and item["reference_how"] != "chosen by you":
                item["issues"].append(("info", f"{Path(item['reference']).name} was chosen as the reference of another isolate, so it is not used for {item['id']}.", ""))
                item["reference"], item["reference_how"] = None, ""
                continue
            if item["reference_how"] == "chosen by you" and sum(1 for o in owners if by_id[o]["reference_how"] == "chosen by you") == 1:
                continue
            item["issues"].append(("error", f"{Path(item['reference']).name} could be the reference of {len(owners)} isolates "
                                   f"({', '.join(owners)}) and its name does not say which.",
                                   "Name each reference after its isolate (for example <isolate>.fna) or put it in the isolate's own folder."))
            item["reference"], item["reference_how"] = None, ""

    out = []
    for item in isolates:
        isolate_id, issues = item["id"], item["issues"]
        pairs_here = item["pairs"]
        gz_ok = all(p["gz"] for p in pairs_here)
        rec = {"id": isolate_id, "folder": item["folder"], "lanes": len(pairs_here),
               "r1": [str(p["r1"]) for p in pairs_here], "r2": [str(p["r2"]) for p in pairs_here],
               "reads_gzipped": gz_ok, "prefix": isolate_id, "reads": {}, "reference": None, "reference_how": item["reference_how"],
               "truth": {"kind": "", "path": ""}, "organism_guess": "", "mode": "reads-only", "candidates": item.get("candidates", [])}
        if id_problem(isolate_id):
            issues.append(("error", id_problem(isolate_id) + ".", "Rename it in the list."))
        if len(pairs_here) > 1:
            issues.append(("info", f"{len(pairs_here)} lanes found; they will be joined in name order into one read pair.", ""))
        if not gz_ok:
            issues.append(("info", "Some read files are not gzip-compressed; they will be compressed as they are staged.", ""))
        if sample_reads:
            first1, first2 = pairs_here[0]["r1"], pairs_here[0]["r2"]
            s1, s2 = sniff_fastq(first1), sniff_fastq(first2)
            rec["reads"] = {"r1": s1, "r2": s2}
            for side, s in (("forward", s1), ("reverse", s2)):
                if s["error"]:
                    issues.append(("error", f"The {side} reads {Path(s['path']).name}: {s['error']}.", ""))
                elif s["gz_name"] and not s["gz_content"]:
                    issues.append(("error", f"{Path(s['path']).name} is named .gz but is not compressed.", "Compress it with: gzip -c file > file.gz"))
            medians = [s["median_len"] for s in (s1, s2) if s.get("median_len")]
            if medians and max(medians) > 1000:
                issues.append(("warn", f"These reads are long (median {max(medians)} bp). PlasBench's short-read route needs paired Illumina reads; "
                               "long reads belong to the hybrid route.", "See the README, 'Self-built hybrid truth'."))
        if item["reference"] is not None:
            ref = Path(item["reference"])
            f = sniff_fasta(ref)
            rec["reference"] = {"path": str(ref), "records": f["records"], "total_bp": f["total_bp"], "largest": f["largest"],
                                "gzipped": ref.name.lower().endswith(".gz"), "error": f["error"]}
            rec["mode"] = "scored"
            rec["organism_guess"] = organism_guess(f["headers"])
            if f["error"]:
                issues.append(("error", f"Reference {ref.name}: {f['error']}.", ""))
            else:
                if f["duplicates"]:
                    issues.append(("error", f"Reference {ref.name} repeats sequence id(s): {', '.join(sorted(set(f['duplicates']))[:5])}.", "Ids must be unique."))
                if f["nucleotide_fraction"] < 0.9:
                    issues.append(("error", f"Reference {ref.name} looks like protein, not DNA.", "Use the genome FASTA (.fna), not the proteins."))
                if f["draft_like"]:
                    issues.append(("warn", f"Reference {ref.name} looks like a DRAFT assembly ({f['records']} contigs). A benchmark needs a COMPLETE genome "
                                   "(chromosome and plasmids as separate closed sequences); a draft is not a ground truth.", "Use a hybrid/long-read assembly."))
                elif not 0.3e6 <= f["total_bp"] <= 15e6:
                    issues.append(("warn", f"Reference {ref.name} is {f['total_bp']:,} bp, outside the usual 0.3-15 Mb for a bacterial genome. Is this the right file?", ""))
                if f["empty"]:
                    issues.append(("warn", f"Reference header(s) with no sequence: {', '.join(f['empty'][:5])}.", ""))
            kind, truth = _truth_for(ref, isolate_id)
            if truth is not None and not _ok(truth):
                kind, truth = "", None
            rec["truth"] = {"kind": kind, "path": str(truth) if truth else ""}
            if not kind:
                issues.append(("info", "No truth table or sequence report found beside the reference. A draft table will be written from the FASTA headers; "
                               "any sequence whose header does not say plasmid or chromosome is left as REVIEW for you to decide.", ""))
        else:
            issues.append(("info", "No reference found: this isolate can be reconstructed but NOT scored. If you have its complete genome, put it in the isolate's folder, "
                           "named after the isolate.", ""))
        rec["issues"] = [{"level": lv, "text": tx, **explain(tx, fx)} for lv, tx, fx in issues]
        levels = [i["level"] for i in rec["issues"]]
        rec["status"] = "blocked" if "error" in levels else ("attention" if "warn" in levels else "ready")
        out.append(rec)

    used = {str(i["reference"]) for i in isolates if i["reference"] is not None}
    long_reads = [p for p in singles if LONG_HINT.search(p.name)]
    leftovers = {"fasta_unmatched": [str(p) for p in fasta_files if str(p) not in used],
                 "long_read_files": [str(p) for p in long_reads],
                 "unpaired_fastq": [str(p) for p in singles if p not in long_reads]}
    if leftovers["long_read_files"]:
        notes.append("Long-read files were found. They are not staged here (the self-built hybrid route is set up by hand: README 'Route C').")
    if leftovers["unpaired_fastq"]:
        notes.append("FASTQ files with no mate were ignored: PlasBench needs paired-end reads (one file for read 1 and one for read 2).")
    meta = sorted({part for r in roots for p in list(fasta_files) + [x for pr in pairs for x in (pr["r1"], pr["r2"])] + list(singles)
                   for part in _rel_parts(p, r) if META_HINT.search(part)})
    if meta:
        notes.append("Some names suggest metagenomic (community) data (" + ", ".join(meta[:3]) + "). This intake is for single isolates. If these are community samples, they take "
                     "a different route: plasbench run --mode metagenomics with a community manifest (docs/METAGENOMICS.md).")
    if not out:
        notes.append("No paired read files were found. Paired reads are named like  name_1.fastq.gz / name_2.fastq.gz  or  name_R1.fastq.gz / name_R2.fastq.gz.")
    return {"roots": [str(r) for r in roots], "isolates": out, "leftovers": leftovers, "notes": notes, "refused": refused[:200],
            "summary": {"isolates": len(out), "scored": sum(1 for i in out if i["mode"] == "scored"), "ready": sum(1 for i in out if i["status"] == "ready"),
                        "attention": sum(1 for i in out if i["status"] == "attention"), "blocked": sum(1 for i in out if i["status"] == "blocked")}}


def _rel_parts(path, root) -> list:
    try:
        return list(Path(path).relative_to(root).parts)
    except ValueError:
        return [Path(path).name]


# --------------------------------------------------------------------------------------------- stage
def _gzip_to(path: Path, directory: Path) -> Path:
    target = directory / (path.name + ".gz")
    with open(path, "rb") as src, gzip.open(target, "wb") as dst:
        while True:
            chunk = src.read(1 << 20)
            if not chunk:
                break
            dst.write(chunk)
    return target


def _gunzip_to(path: Path, directory: Path) -> Path:
    target = directory / re.sub(r"\.gz$", "", path.name, flags=re.IGNORECASE)
    with gzip.open(path, "rb") as src, open(target, "wb") as dst:
        while True:
            chunk = src.read(1 << 20)
            if not chunk:
                break
            dst.write(chunk)
    return target


def _draft_preview(reference: Path) -> dict:
    """How many sequences the drafted truth table will have and how many of them stay REVIEW: the same classify() on the same headers stage_isolate reads."""
    import init_local_sample as init
    rows = review = 0
    try:
        with open_text(reference) as handle:
            for line in handle:
                if line.startswith(">"):
                    parts = line[1:].strip().split(None, 1)
                    rows += 1
                    review += init.classify(parts[1] if len(parts) > 1 else "") == "REVIEW"
    except (OSError, EOFError):
        pass
    return {"sequences": rows, "review": review}


SHEET_NEEDS = ("sample_id", "assembly_accession", "sra_run")


def validate_sheet_text(text: str) -> list:
    """What stage 0 (scripts/lib.sh validate_sample_sheet, with REQUIRE_CURATED_METADATA=0 as for a sheet of your own isolates) and the local-input check would refuse in a
    sheet, from its text. [] when the run would accept it. Used on a sheet BEFORE it is written."""
    body = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    if not body:
        return ["the sheet has no header line"]
    header = [h.strip() for h in body[0].split("\t")]
    out = [f"the header has no {c} column (columns must be separated by a TAB)" for c in SHEET_NEEDS if c not in header]
    if out:
        return out
    rows = list(csv.DictReader(body, delimiter="\t"))
    seen = set()
    for n, r in enumerate(rows, start=2):
        sid = (r.get("sample_id") or "").strip()
        if not sid or not (r.get("assembly_accession") or "").strip() or not (r.get("sra_run") or "").strip():
            out.append(f"row {n}: sample_id, assembly_accession and sra_run must all be filled")
            continue
        if id_problem(sid):
            out.append(f"row {n}: " + id_problem(sid))
        if sid in seen:
            out.append(f"row {n}: duplicate sample_id '{sid}'")
        seen.add(sid)
        if sid.startswith("EXAMPLE_"):
            out.append(f"row {n}: the template's example row is still there")
    if not rows:
        out.append("the sheet has no sample rows")
    return out


def plan_stage(found: dict, data_dir: Path, samples: Path, only=None, rename=None, organism=None, link: str = "copy", include_blocked: bool = False) -> dict:
    """What `stage` will do, decided once, here: per isolate whether it is staged (or why not) and every file it will place, and the sample sheet as it will be afterwards
    (checked with validate_sheet_text). `stage` executes exactly this plan; `stage --dry-run` and the AI help show it, so there is one source of truth. Writes nothing."""
    import init_local_sample as init
    rename, organism, only = rename or {}, organism or {}, set(only) if only else None
    data_dir, samples = Path(data_dir), Path(samples)
    entries, lines, used = [], init.read_sheet_lines(samples), set()
    before = "\n".join(lines) + ("\n" if lines else "")
    for item in found["isolates"]:
        old = item["id"]
        if only is not None and old not in only:
            continue
        new = rename.get(old, old)
        target = data_dir / new
        e = {"id": new, "from": old, "stage": False, "skip": "", "status": item["status"], "dir": str(target), "ops": [], "needs_review": 0}
        entries.append(e)
        if id_problem(new):
            e["skip"] = id_problem(new)
            continue
        if new.lower() in used:
            e["skip"] = f"skipped: another isolate of this plan is already called '{new}'. Choose another name for this isolate."
            continue
        if item["status"] == "blocked" and not include_blocked:
            e["skip"] = "skipped: " + "; ".join(i["text"] for i in item["issues"] if i["level"] == "error")
            continue
        existing = target / f"{new}_1.fastq.gz"
        if existing.exists() and not any(Path(r).resolve() == existing.resolve() for r in item["r1"]):
            e["skip"] = f"skipped: {target} already holds different reads for '{new}'. Choose another name for this isolate."
            continue
        used.add(new.lower())
        for n, key in ((1, "r1"), (2, "r2")):
            to = target / f"{new}_{n}.fastq.gz"
            sources = [str(p) for p in item[key]]
            compress = [not is_gzip(Path(p)) for p in sources]
            how = ("join %d lanes" % len(sources) if len(sources) > 1 else link) + (" after compressing" if any(compress) else "")
            e["ops"].append({"kind": "reads", "mate": n, "from": sources, "to": str(to), "how": how, "compress": compress, "replaces": to.exists()})
        reference = item["reference"]["path"] if item["reference"] else None
        kind, truth = item["truth"]["kind"], item["truth"]["path"]
        if reference:
            to = target / "reference.fna"
            e["ops"].append({"kind": "reference", "from": [reference], "to": str(to), "how": "decompress" if item["reference"]["gzipped"] else link,
                             "replaces": to.exists()})
            if kind == "sequence_report":
                to = target / "sequence_report.jsonl"
                e["ops"].append({"kind": "truth", "from": [truth], "to": str(to), "how": "NCBI sequence report: the labels are built from it", "replaces": to.exists()})
            elif kind == "truth_table":
                to = target / "truth.tsv"
                e["ops"].append({"kind": "truth", "from": [truth], "to": str(to), "how": "your truth table, copied as it is", "replaces": to.exists()})
            elif (target / "truth.tsv").is_file():
                e["ops"].append({"kind": "truth", "from": [], "to": str(target / "truth.tsv"), "how": "already there: left unchanged", "replaces": False})
            else:
                d = _draft_preview(Path(reference))
                e["needs_review"] = d["review"]
                e["ops"].append({"kind": "truth", "from": [], "to": str(target / "truth.tsv"), "replaces": False,
                                 "how": f"draft from the FASTA headers: {d['sequences']} sequence(s), {d['review']} left as REVIEW for you to decide", **d})
        accession = "LOCAL" if reference else "NA"
        extra = {"organism": organism.get(old) or item.get("organism_guess", "")} if reference or organism.get(old) else None
        lines, _changed, note = init.sheet_after(lines, new, new, accession, extra)
        values = {"sample_id": new, "assembly_accession": accession, "sra_run": new}
        values.update({k: v for k, v in (extra or {}).items() if v})
        e["ops"].append({"kind": "sheet_row", "from": [], "to": str(samples), "how": note, "values": values, "replaces": False})
        e["exec"] = {"r1": [str(p) for p in item["r1"]], "r2": [str(p) for p in item["r2"]], "reference": reference,
                     "reference_gz": bool(item["reference"] and item["reference"]["gzipped"]), "truth_kind": kind, "truth": truth, "accession": accession, "extra": extra}
        e["stage"] = True
    after = "\n".join(lines) + ("\n" if lines else "")
    staged = [e for e in entries if e["stage"]]
    return {"isolates": entries, "data_dir": str(data_dir), "samples": str(samples), "link": link, "sheet_before": before, "sheet_after": after,
            "sheet_exists": samples.is_file(), "sheet_problems": validate_sheet_text(after) if staged else [], "staged": len(staged),
            "needs_review": sum(e["needs_review"] for e in staged)}


def plan_lines(plan: dict) -> list:
    """The plan in plain lines (what `stage --dry-run` prints)."""
    out = []
    for e in plan["isolates"]:
        if not e["stage"]:
            out.append(f"SKIP    {e['id']}: {e['skip']}")
            continue
        out.append(f"STAGE   {e['id']}" + (f"  (renamed from {e['from']})" if e["from"] != e["id"] else ""))
        for op in e["ops"]:
            src = " + ".join(Path(f).name for f in op["from"])
            out.append(f"    {op['kind']:<10} {src + ' -> ' if src else ''}{op['to']}  [{op['how']}]" + ("  (replaces the file there)" if op.get("replaces") else ""))
    for p in plan["sheet_problems"]:
        out.append(f"SHEET   problem: {p}")
    return out


def stage(found: dict, data_dir: Path, samples: Path, only=None, rename=None, organism=None, link: str = "copy", include_blocked: bool = False, plan: dict = None) -> dict:
    """Place every selected isolate with the same code `plasbench init-local` uses, and write the sheet: exactly the operations of plan_stage(). Returns what happened, per isolate."""
    import init_local_sample as init
    plan = plan or plan_stage(found, data_dir, samples, only, rename, organism, link, include_blocked)
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for e in plan["isolates"]:
            entry = {"id": e["id"], "from": e["from"], "ok": False, "messages": [], "needs_review": 0}
            results.append(entry)
            if not e["stage"]:
                entry["messages"].append(e["skip"])
                continue
            x, new = e["exec"], e["id"]
            work = tmp / new
            work.mkdir(parents=True, exist_ok=True)
            side = {1: [], 2: []}
            for n, key in ((1, "r1"), (2, "r2")):
                for path in x[key]:
                    path = Path(path)
                    side[n].append(path if is_gzip(path) else _gzip_to(path, work))
            reference = x["reference"]
            if reference and x["reference_gz"]:
                reference = str(_gunzip_to(Path(reference), work))
            kind, truth = x["truth_kind"], x["truth"]
            captured = io.StringIO()
            try:
                with contextlib.redirect_stdout(captured):
                    entry["needs_review"] = init.stage_isolate(
                        new, new, side[1], side[2], reference, truth if kind == "sequence_report" else None, Path(plan["data_dir"]), Path(plan["samples"]),
                        x["accession"], plan["link"], False, truth if kind == "truth_table" else None, extra=x["extra"])
                entry["ok"] = True
            except SystemExit as exc:
                entry["messages"].append(str(exc))
            entry["messages"].extend(line.strip() for line in captured.getvalue().splitlines() if line.strip())
    return {"staged": [r for r in results if r["ok"]], "results": results, "data_dir": str(plan["data_dir"]), "samples": str(plan["samples"]),
            "needs_review": sum(r["needs_review"] for r in results)}


# --------------------------------------------------------------------------------------------- repair
def read_truth(path: Path):
    """Rows of a truth table as [id, type, length-or-''] lists (header and comments dropped)."""
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = [f.strip() for f in line.split("\t")]
        if fields and fields[0] == "sequence_id":
            continue
        rows.append((fields + ["", "", ""])[:3])
    return rows


def write_truth(path: Path, rows) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["sequence_id", "molecule_type", "length"])
        writer.writerows(rows)


def truth_rows(sample_dir: Path) -> dict:
    """What the 'Label sequences' screen shows: every reference sequence with its length, its FASTA header and the label it has now ('' when none, REVIEW when undecided)."""
    reference = Path(sample_dir) / "reference.fna"
    if not reference.is_file():
        raise FileNotFoundError(f"{reference} does not exist")
    f = sniff_fasta(reference)
    if f["error"]:
        raise ValueError(f["error"])
    lengths = {}
    current = None
    with open_text(reference) as handle:
        for line in handle:
            if line.startswith(">"):
                parts = line[1:].strip().split(None, 1)
                current = parts[0] if parts else ""
                lengths[current] = 0
            elif current is not None:
                lengths[current] += len(line.strip())
    truth = Path(sample_dir) / "truth.tsv"
    labels = {r[0]: r[1].upper() for r in read_truth(truth)} if truth.is_file() else {}
    return {"sample_dir": str(sample_dir), "has_report": (Path(sample_dir) / "sequence_report.jsonl").is_file(),
            "rows": [{"sequence_id": i, "length": lengths.get(i, 0), "header": f["headers"].get(i, ""), "label": labels.get(i, ""),
                      "header_says": _header_label(f["headers"].get(i, ""))} for i in f["ids"]]}


def _header_label(description: str) -> str:
    import init_local_sample as init
    label = init.classify(description)
    return "" if label == "REVIEW" else label


def save_truth(sample_dir: Path, labels: dict) -> dict:
    """Write the truth table from labels the PERSON chose. Every reference sequence needs PLASMID or CHROMOSOME; anything else is refused, nothing is inferred."""
    shown = truth_rows(sample_dir)
    ids = [r["sequence_id"] for r in shown["rows"]]
    problems = []
    for seq_id in ids:
        value = str(labels.get(seq_id, "")).strip().upper()
        if value not in ("PLASMID", "CHROMOSOME"):
            problems.append(f"'{seq_id}' has no label: choose PLASMID or CHROMOSOME")
    extra = [k for k in labels if k not in ids]
    if extra:
        problems.append("not in the reference: " + ", ".join(map(str, extra[:5])))
    if problems:
        return {"ok": False, "problems": problems}
    lengths = {r["sequence_id"]: r["length"] for r in shown["rows"]}
    write_truth(Path(sample_dir) / "truth.tsv", [[i, str(labels[i]).strip().upper(), lengths[i]] for i in ids])
    return {"ok": True, "problems": [], "path": str(Path(sample_dir) / "truth.tsv")}


def repair_sample(row: dict, data_dir: Path, sheet: Path) -> list:
    """Repair what can be repaired without a judgement call, and say exactly what was done. Never decides plasmid or chromosome, never edits the user's originals
    (read files are copied or rewritten only inside the isolate's own staged folder), never touches a sheet row except the template's example."""
    import init_local_sample as init
    import validate_local_inputs as vli
    done = []
    sample = (row.get("sample_id") or "").strip()
    sra = (row.get("sra_run") or "").strip()
    accession = (row.get("assembly_accession") or "").strip()
    sdir = Path(data_dir) / sample
    if not sdir.is_dir():
        return done

    # 1. read files with the right names but not compressed
    for mate in (1, 2):
        path = sdir / f"{sra}_{mate}.fastq.gz"
        if path.is_file() and path.stat().st_size and not is_gzip(path):
            with open(path, "rb") as handle:
                head = handle.read(1)
            if head == b"@":
                plain = path.with_name(path.name + ".plain")
                path.replace(plain)
                with open(plain, "rb") as src, gzip.open(path, "wb") as dst:
                    shutil_copy(src, dst)
                plain.unlink()
                done.append(f"compressed {path.name} (it had a .gz name but held plain text)")

    # 2. a read pair that is there under other names: make correctly named copies
    r1, r2 = sdir / f"{sra}_1.fastq.gz", sdir / f"{sra}_2.fastq.gz"
    if not (r1.is_file() and r2.is_file()):
        pairs, _ = find_pairs([sdir], 1)
        chosen = [x for x in pairs if x["stem"] == sra] or (pairs if len(pairs) == 1 else [])
        if chosen:
            a, b = chosen[0]["r1"], chosen[0]["r2"]
            for source, target in ((a, r1), (b, r2)):
                if is_gzip(source):
                    shutil_copyfile(source, target)
                else:
                    gz = _gzip_to(source, sdir)
                    gz.replace(target)
            done.append(f"made {r1.name} and {r2.name} from {a.name} and {b.name} (the originals are kept)")

    # 3. truth table
    reference, truth, report = sdir / "reference.fna", sdir / "truth.tsv", sdir / "sequence_report.jsonl"
    scored = accession not in ("", "NA")
    if scored and reference.is_file() and not sniff_fasta(reference)["error"]:
        f = sniff_fasta(reference)
        if not truth.is_file() and not report.is_file():
            rows, review = [], 0
            for seq_id, description, length in init.read_fasta_records(reference):
                label = init.classify(description)
                review += label == "REVIEW"
                rows.append([seq_id, label, length])
            write_truth(truth, rows)
            done.append(f"wrote a draft truth table for {len(rows)} sequence(s); {review} marked REVIEW for you to decide")
        elif truth.is_file():
            rows = read_truth(truth)
            before = [list(r) for r in rows]
            ids = set(f["ids"])
            lower = {}
            for i in f["ids"]:
                lower.setdefault(i.lower(), []).append(i)
            for r in rows:
                if r[0] not in ids and len(lower.get(r[0].lower(), [])) == 1:
                    done.append(f"truth table: '{r[0]}' corrected to '{lower[r[0].lower()][0]}' (capital letters must match the FASTA)")
                    r[0] = lower[r[0].lower()][0]
                r[1] = r[1].upper()
            seen = {r[0] for r in rows}
            lengths = {}
            current = None
            with open_text(reference) as handle:
                for line in handle:
                    if line.startswith(">"):
                        parts = line[1:].strip().split(None, 1)
                        current = parts[0] if parts else ""
                        lengths[current] = 0
                    elif current is not None:
                        lengths[current] += len(line.strip())
            for seq_id in f["ids"]:
                if seq_id not in seen:
                    rows.append([seq_id, "REVIEW", lengths.get(seq_id, 0)])
                    done.append(f"truth table: '{seq_id}' was missing; added it as REVIEW (you decide what it is)")
            raw = truth.read_text(encoding="utf-8", errors="replace")
            if rows != before or "\r" in raw or any(l != l.strip() for l in raw.splitlines() if l.strip()):
                write_truth(truth, rows)
                if rows == before:
                    done.append("truth table: removed stray spaces and Windows line endings")

    # 4. the template's example row
    if sheet.is_file():
        lines = sheet.read_text(encoding="utf-8").splitlines()
        kept = [l for l in lines if not l.split("\t")[0].startswith("EXAMPLE_")]
        if len(kept) != len(lines):
            with open(sheet, "w", encoding="utf-8", newline="\n") as _fh:
                _fh.write("\n".join(kept) + "\n")
            done.append("removed the template's EXAMPLE_ row from the sheet")
    return done


def shutil_copy(src, dst) -> None:
    while True:
        chunk = src.read(1 << 20)
        if not chunk:
            break
        dst.write(chunk)


def shutil_copyfile(source: Path, target: Path) -> None:
    with open(source, "rb") as src, open(target, "wb") as dst:
        shutil_copy(src, dst)


# --------------------------------------------------------------------------------------------- check
def _fastq_sequences(path: Path, count: int):
    out = []
    try:
        with open_text(path) as handle:
            for index, line in enumerate(handle):
                if index % 4 == 1:
                    out.append(line.strip().upper())
                    if len(out) >= count:
                        break
    except (OSError, EOFError):
        pass
    return out


COMP = str.maketrans("ACGT", "TGCA")


def reference_concordance(reads: Path, reference: Path, reads_n: int = 3000, k: int = 21, budget: float = 45.0) -> dict:
    """What share of a sample of the reads is found in the reference, by 21-mers. Reads from the isolate that the reference describes match almost completely
    (they differ only by sequencing error); reads from another strain match partly and from another species hardly at all. Costs seconds, needs no aligner."""
    started = time.time()
    seqs = [s[:100] for s in _fastq_sequences(reads, reads_n) if len(s) >= k + 10]
    if not seqs:
        return {"checked": 0, "matching": None, "note": "no reads could be sampled"}
    wanted = {}
    per_read = []
    for s in seqs:
        kmers = [s[i:i + k] for i in range(0, len(s) - k + 1)]
        kmers = [m for m in kmers if "N" not in m]
        per_read.append(kmers)
        for m in kmers:
            wanted[m] = False
            wanted[m.translate(COMP)[::-1]] = False
    hits, scanned, partial = set(), 0, False
    with open_text(reference) as handle:
        buffer = []

        def sweep(sequence):
            nonlocal scanned
            for i in range(0, len(sequence) - k + 1):
                m = sequence[i:i + k]
                if m in wanted:
                    hits.add(m)
            scanned += len(sequence)

        for line in handle:
            if line.startswith(">"):
                if buffer:
                    sweep("".join(buffer).upper())
                    buffer = []
                if time.time() - started > budget:
                    partial = True
                    break
            else:
                buffer.append(line.strip())
        if buffer and not partial:
            sweep("".join(buffer).upper())
    matching = 0
    for kmers in per_read:
        if not kmers:
            continue
        found = sum(1 for m in kmers if m in hits or m.translate(COMP)[::-1] in hits)
        matching += found / len(kmers) >= 0.5
    return {"checked": len(per_read), "matching": matching / len(per_read), "scanned_bp": scanned, "partial": partial,
            "seconds": round(time.time() - started, 1)}


def _row(status: str, name: str, detail: str = "", fix: str = "") -> dict:
    if status in ("fail", "warn"):
        info = explain(f"{name} {detail}", fix)
        return {"status": status, "name": name, "detail": detail, "fix": info["fix"], "code": info["code"], "auto": info["auto"], "guide": info["guide"]}
    return {"status": status, "name": name, "detail": detail, "fix": fix, "code": "", "auto": False, "guide": ""}


def check_sample(row: dict, data_dir: Path, sheet: Path, deep: bool = True, root: Path = None) -> dict:
    """The quick test for one sheet row: open each file the way the run will and say pass / warn / fail for each thing the run depends on."""
    import validate_local_inputs as vli
    sample = (row.get("sample_id") or "").strip()
    sra = (row.get("sra_run") or "").strip()
    accession = (row.get("assembly_accession") or "").strip()
    sdir = Path(data_dir) / sample
    checks, mode = [], ("reads-only" if accession in ("", "NA") else "scored")
    checks.append(_row("pass" if SAFE_ID.match(sample) else "fail", "Sample name is usable", sample,
                       "" if SAFE_ID.match(sample) else "Letters, digits . _ - only; it becomes a folder name."))
    problems, warnings = [], []
    vli.check_sample(row, Path(data_dir), problems, warnings)
    r1, r2 = sdir / f"{sra}_1.fastq.gz", sdir / f"{sra}_2.fastq.gz"
    s1, s2 = sniff_fastq(r1) if r1.is_file() else None, sniff_fastq(r2) if r2.is_file() else None
    if s1 and s2 and not s1["error"] and not s2["error"]:
        checks.append(_row("pass", "Both read files open and look like FASTQ",
                           f"{s1['reads']}+ reads sampled, median length {s1['median_len']} bp (forward) and {s2['median_len']} bp (reverse)"))
        if max(s1["median_len"], s2["median_len"]) > 1000:
            checks.append(_row("fail", "Reads are short-read length", f"median {max(s1['median_len'], s2['median_len'])} bp",
                               "The short-read route needs paired Illumina reads. Long reads use the hybrid route (README, Route C)."))
    elif not sdir.is_dir():
        checks.append(_row("fail", "The isolate's folder exists", f"{sdir} is missing", "Run  plasbench intake stage  (or init-local) first."))
    else:
        for n, s, path in ((1, s1, r1), (2, s2, r2)):
            if s is None:
                checks.append(_row("fail", f"Read file {n} is where the run looks", f"{path.name} not found in {sdir}", "Stage it again, or fix sra_run in the sheet."))
            elif s["error"]:
                checks.append(_row("fail", f"Read file {n} opens", f"{path.name}: {s['error']}"))
    for text in problems:
        first, *rest = text.split("\n")
        checks.append(_row("fail", "Input files", re.sub(r"^\[[^\]]*\]\s*", "", first), "\n".join(x.strip() for x in rest)))
    for text in warnings:
        checks.append(_row("warn", "Input files", re.sub(r"^\[[^\]]*\]\s*", "", text)))
    if not problems and s1 and s2:
        checks.append(_row("pass", "Mates pair up (same read names, same order, same count)", "first 1000 reads compared"))
    reference, truth, report = sdir / "reference.fna", sdir / "truth.tsv", sdir / "sequence_report.jsonl"
    if mode == "scored" and reference.is_file():
        f = sniff_fasta(reference)
        if f["error"]:
            checks.append(_row("fail", "Reference opens", f["error"]))
        else:
            checks.append(_row("pass", "Reference opens", f"{f['records']} sequence(s), {f['total_bp']:,} bp, largest {f['largest']:,} bp"))
            if f["draft_like"]:
                checks.append(_row("warn", "Reference is a finished genome", f"{f['records']} contig-like records: this looks like a draft assembly",
                                   "A benchmark's truth should be complete, closed sequences."))
        if truth.is_file() and not f["error"]:
            script = Path(__file__).resolve().parent / "validate_truth_table.py"
            done = subprocess.run([sys.executable, str(script), "--truth", str(truth), "--reference", str(reference), "--sample", sample],
                                  capture_output=True, text=True, timeout=subprocess_timeout())
            if done.returncode == 0:
                rows = [l.split("\t") for l in truth.read_text(encoding="utf-8").splitlines()[1:] if l.strip() and not l.startswith("#")]
                plasmids = sum(1 for r in rows if len(r) > 1 and r[1].strip().upper() == "PLASMID")
                checks.append(_row("pass", "Truth table matches the reference", f"{len(rows)} sequences labelled, {plasmids} plasmid(s)"))
                if plasmids == 0:
                    checks.append(_row("warn", "The truth has plasmids to find", "no sequence is labelled PLASMID: nothing can be recovered, so recall is undefined for this isolate"))
            else:
                lines = [l.strip() for l in (done.stderr + done.stdout).splitlines() if l.strip() and not l.startswith("ERROR: ") or l.startswith("  -")]
                checks.append(_row("fail", "Truth table matches the reference", " | ".join(lines[:4]) or "the truth table was rejected",
                                   "Open data/%s/truth.tsv and fix each line listed; REVIEW must become PLASMID or CHROMOSOME." % sample))
        elif report.is_file():
            checks.append(_row("pass", "Truth comes from an NCBI sequence report", "labels are built from it during the run"))
        if deep and s1 and not s1["error"] and not f["error"]:
            c = reference_concordance(r1, reference)
            if c["matching"] is None:
                checks.append(_row("warn", "Reads come from this reference's isolate", c.get("note", "")))
            else:
                share = f"{c['matching']:.0%} of {c['checked']} sampled reads are found in the reference ({c['seconds']} s)"
                if c["matching"] >= 0.8:
                    checks.append(_row("pass", "Reads come from this reference's isolate", share))
                elif c["matching"] >= 0.3:
                    checks.append(_row("warn", "Reads come from this reference's isolate", share,
                                       "Only part of the reads match. Expected when the reference is a close relative, or the sample is mixed. "
                                       "A scored benchmark needs the SAME isolate."))
                else:
                    checks.append(_row("fail", "Reads come from this reference's isolate", share,
                                       "The reads and the reference look like different organisms or strains. Scores would be meaningless: use the reference of this isolate."))
    elif mode == "scored":
        checks.append(_row("fail", "Reference is present", f"{reference} is missing", "Stage the isolate with its reference, or set assembly_accession to NA to reconstruct without scoring."))
    else:
        checks.append(_row("info", "Reads-only isolate", "no reference: it will be reconstructed, not scored"))
    levels = [c["status"] for c in checks]
    return {"sample_id": sample, "mode": mode, "checks": checks, "ok": "fail" not in levels, "warnings": levels.count("warn")}


def check(samples: Path, data_dir: Path, only: str = "", deep: bool = True, root: Path = None, fix: bool = False) -> dict:
    """Quick test of every row of a sheet (or one): can PlasBench see these files and use them. Reads a bounded part of each file."""
    import validate_local_inputs as vli
    samples = Path(samples)
    if not samples.is_file():
        return {"ok": False, "error": f"sample sheet not found: {samples}", "samples": []}
    rows = [r for r in vli.read_sheet(samples) if (r.get("sample_id") or "").strip() and (not only or r["sample_id"].strip() == only)]
    if not rows:
        return {"ok": False, "error": f"no sample rows in {samples}" + (f" for '{only}'" if only else ""), "samples": []}
    repaired = []
    if fix:
        for r in rows:
            for what in repair_sample(r, Path(data_dir), samples):
                repaired.append({"sample_id": r["sample_id"].strip(), "what": what})
        rows = [r for r in vli.read_sheet(samples) if (r.get("sample_id") or "").strip() and (not only or r["sample_id"].strip() == only)]
    results = [check_sample(r, Path(data_dir), samples, deep, root) for r in rows]
    placeholder = [r["sample_id"] for r in rows if r["sample_id"].startswith("EXAMPLE")]
    return {"ok": all(r["ok"] for r in results) and not placeholder, "samples": results, "sheet": str(samples), "data_dir": str(data_dir), "repaired": repaired,
            "fixable": sum(1 for r in results for c in r["checks"] if c["status"] in ("fail", "warn") and c["auto"]),
            "error": f"the sheet still has the template's example row ({', '.join(placeholder)}): delete it" if placeholder else "",
            **({"error_info": explain("template's example row")} if placeholder else {})}


# --------------------------------------------------------------------------------------------- command line
def print_scan(found: dict) -> None:
    print(f"Looked in: {', '.join(found['roots']) or '(nothing)'}")
    for note in found["notes"]:
        print(f"  note: {note}")
    for item in found["isolates"]:
        tag = {"ready": "READY", "attention": "CHECK", "blocked": "BLOCKED"}[item["status"]]
        ref = item["reference"]
        print(f"\n[{tag}] {item['id']}  ({item['mode']})")
        print(f"    reads      {item['lanes']} lane(s): {Path(item['r1'][0]).name} + {Path(item['r2'][0]).name}  in {item['folder']}")
        print(f"    reference  " + (f"{Path(ref['path']).name}  ({ref['records']} sequence(s), {ref['total_bp']:,} bp)  -- {item['reference_how']}" if ref else "none"))
        if item["truth"]["kind"]:
            print(f"    labels     {item['truth']['kind'].replace('_', ' ')}: {Path(item['truth']['path']).name}")
        if item["organism_guess"]:
            print(f"    organism   {item['organism_guess']} (read from the FASTA header; confirm it)")
        for issue in item["issues"]:
            print(f"    {issue['level'].upper():5} {issue['text']}")
            if issue["level"] in ("error", "warn") and issue["fix"]:
                print("          what to do: " + issue["fix"].replace("\n", "\n                      "))
                print(f"          guide: {issue['guide']}" + ("   (Fix can repair this once staged: intake check --fix)" if issue["auto"] else ""))
    left = found["leftovers"]
    for key, label in (("fasta_unmatched", "FASTA files not matched to any isolate"), ("long_read_files", "long-read files (not staged)"), ("unpaired_fastq", "unpaired FASTQ files (ignored)")):
        if left[key]:
            print(f"\n{label}:")
            for path in left[key][:12]:
                print(f"    {path}")
    s = found["summary"]
    print(f"\n{s['isolates']} isolate(s): {s['ready']} ready, {s['attention']} to check, {s['blocked']} blocked.  Next:  plasbench intake stage <same folders>")


def print_check(result: dict) -> int:
    if result.get("error"):
        print(f"ERROR: {result['error']}")
    for item in result.get("repaired", []):
        print(f"  repaired [{item['sample_id']}] {item['what']}")
    for sample in result["samples"]:
        print(f"\n{sample['sample_id']}  ({sample['mode']})  -> {'OK' if sample['ok'] else 'NOT USABLE'}")
        for c in sample["checks"]:
            mark = {"pass": "pass", "warn": "WARN", "fail": "FAIL", "info": "info"}[c["status"]]
            print(f"    [{mark}] {c['name']}" + (f": {c['detail']}" if c["detail"] else ""))
            if c["fix"]:
                print("           what to do: " + c["fix"].replace("\n", "\n                       "))
            if c.get("auto"):
                print("           (Fix can repair this: add --fix)")
            if c.get("guide"):
                print(f"           guide: {c['guide']}")
    good = result["ok"]
    print("\n" + ("All isolates can be read and used. Next:  REQUIRE_CURATED_METADATA=0 plasbench run --samples %s --local-inputs" % result["sheet"]
                  if good else "Not ready: follow the 'what to do' under each FAIL, then run this check again" + (" (or add --fix to repair the ones marked)" if result.get("fixable") else "") + ". Nothing has been run."))
    return 0 if good else 2


def main(argv=None) -> int:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="action", required=True)
    t = sub.add_parser("template", help="Write a sheet or table to fill in.")
    t.add_argument("kind", choices=sorted(TEMPLATES), help="local = your own isolates; cohort = a public NCBI cohort; truth = a truth table")
    t.add_argument("--out", help="Where to write it (default: print to the screen).")
    for name, text in (("scan", "Find isolates in the folder(s). Changes nothing."), ("stage", "Place what the scan found and write the sample sheet.")):
        s = sub.add_parser(name, help=text)
        s.add_argument("folders", nargs="+", help="Folder(s) (or files) to look in. Sub-folders are searched.")
        s.add_argument("--depth", type=int, default=3, help="How many folder levels down to look (default 3).")
        s.add_argument("--json", action="store_true", help="Machine-readable output.")
        s.add_argument("--reference", action="append", default=[], metavar="ID=FILE",
                       help="Use FILE as the reference of isolate ID instead of the name-based guess (repeatable; for when two FASTA files could belong to it).")
        if name == "stage":
            s.add_argument("--data-dir", default=str(root / "data"))
            s.add_argument("--samples", default=str(root / "config" / "local.tsv"))
            s.add_argument("--only", action="append", help="Stage only this isolate id (repeatable).")
            s.add_argument("--rename", action="append", default=[], metavar="OLD=NEW", help="Use a different sample id (repeatable).")
            s.add_argument("--organism", action="append", default=[], metavar="ID=NAME", help="Organism for an isolate, e.g. iso1='Escherichia coli' (repeatable).")
            s.add_argument("--link", choices=("copy", "symlink", "hardlink"), default="copy")
            s.add_argument("--include-blocked", action="store_true", help="Stage isolates the scan marked BLOCKED anyway.")
            s.add_argument("--dry-run", action="store_true", help="Show exactly what would be placed where, and the sample sheet as it would be; change nothing.")
    c = sub.add_parser("check", help="The quick test: can PlasBench read these files and use them?")
    c.add_argument("--samples", default=str(root / "config" / "local.tsv"))
    c.add_argument("--data-dir", default=str(root / "data"))
    c.add_argument("--sample", default="", help="Check only this sample id.")
    c.add_argument("--fast", action="store_true", help="Skip the reads-versus-reference comparison.")
    c.add_argument("--fix", action="store_true", help="First repair what can be repaired safely (compression, file names, a missing or untidy truth table, the example row). "
                                                      "Never decides plasmid or chromosome; never changes your original files.")
    c.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.action == "template":
        text = template_text(args.kind, root)
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "w", encoding="utf-8", newline="\n") as _fh:
                _fh.write(text)
            print(f"wrote {out}\nFill it in, keeping the header line and the TAB between columns. Guide: docs/INPUT_GUIDE.md")
        else:
            sys.stdout.write(text)
        return 0
    references = dict(x.split("=", 1) for x in getattr(args, "reference", []) if "=" in x)
    if args.action == "scan":
        found = scan(args.folders, args.depth, references=references)
        print(json.dumps(found, indent=1)) if args.json else print_scan(found)
        return 0 if found["isolates"] else 2
    if args.action == "stage":
        found = scan(args.folders, args.depth, references=references)
        if not found["isolates"]:
            print_scan(found)
            return 2
        rename = dict(x.split("=", 1) for x in args.rename if "=" in x)
        organism = dict(x.split("=", 1) for x in args.organism if "=" in x)
        plan = plan_stage(found, Path(args.data_dir), Path(args.samples), args.only, rename, organism, args.link, args.include_blocked)
        if args.dry_run:
            if args.json:
                print(json.dumps(plan, indent=1))
            else:
                print("\n".join(plan_lines(plan)))
                print(f"\nSample sheet {plan['samples']} would become:\n" + plan["sheet_after"])
                print("Nothing was changed (--dry-run).")
            return 0 if plan["staged"] and not plan["sheet_problems"] else 2
        done = stage(found, Path(args.data_dir), Path(args.samples), plan=plan)
        if args.json:
            print(json.dumps(done, indent=1))
        else:
            for r in done["results"]:
                print(f"{'staged ' if r['ok'] else 'SKIPPED'} {r['id']}")
                for m in r["messages"]:
                    print(f"    {m}")
            print(f"\nSample sheet: {done['samples']}")
            if done["needs_review"]:
                print(f"ACTION REQUIRED: {done['needs_review']} sequence(s) are marked REVIEW in a truth.tsv: set each to PLASMID or CHROMOSOME (PlasBench will not guess).")
            print(f"Next:  plasbench intake check --samples {done['samples']}")
        return 0 if done["staged"] else 2
    result = check(Path(args.samples), Path(args.data_dir), args.sample, deep=not args.fast, root=root, fix=args.fix)
    if args.json:
        print(json.dumps(result, indent=1))
        return 0 if result["ok"] else 2
    return print_check(result)


if __name__ == "__main__":
    sys.exit(main())
