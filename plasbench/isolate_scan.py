"""Find isolates in ONE folder tree: paired reads, the reference genome, sequence reports and truth tables.

`plasbench init-local` needs explicit --reads-1/--reads-2/--reference paths. This module looks through a folder (with sub-folders, related and unrelated files
mixed) and proposes those paths, with a confidence and the reasons, and says plainly what it could not decide. It NEVER modifies the folder, never decompresses
a whole file, never raises on an unreadable folder, and never guesses silently: an ambiguity or a missing piece is an issue on the sample.

Standard library only. `scan()` reads; `stage()` writes, through the same function init-local uses (python/init_local_sample.stage_isolate).

Recognition rules (see docs/USER_GUIDE.md, "Add isolates from a folder"):
  reads       FASTQ pairs named _R1/_R2, _1/_2, .1/.2, -1/-2, _R1_001/_R2_001 (any case; .fastq/.fq, .gz or not). Illumina lanes (_L001) of one isolate are
              listed as lanes and flagged (they are joined by gzip concatenation only after you confirm). A mate without a partner is an error.
  reference   a FASTA (.fa/.fasta/.fna/.fas, plain) that is not assembler output; ranked by header accession patterns, words in the header, folder/file names,
              size and record count, and by how closely it is tied to the sample (same folder, isolate folder, file name contains the sample id).
  not a ref   contigs/scaffolds/assembly(.graph) files, files in assembler folders (spades, unicycler, flye ...), FASTA headers like NODE_1_length_ or depth=.
"""
from __future__ import annotations

import gzip
import json
import os
import re
import sys
import threading
import zlib
from pathlib import Path

SAFE_SAMPLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
FASTQ_RE = re.compile(r"\.(fastq|fq)(\.gz)?$", re.IGNORECASE)
FASTA_RE = re.compile(r"\.(fa|fasta|fna|fas)(\.gz)?$", re.IGNORECASE)
GENBANK_RE = re.compile(r"\.(gb|gbk|gbff)(\.gz)?$", re.IGNORECASE)
MATE_RE = re.compile(r"^(?P<stem>.+?)[_.-](?P<r>R?)(?P<mate>[12])(?P<tail>[_.-]001)?\.(?P<ext>fastq|fq)(?P<gz>\.gz)?$", re.IGNORECASE)
LANE_RE = re.compile(r"[_.-]L(\d{3})(?=$|[_.-])", re.IGNORECASE)
SAMPLE_NO_RE = re.compile(r"^(?P<name>.+?)[_.-]S\d{1,3}$", re.IGNORECASE)
GENERIC = {"reads", "read", "sample", "raw", "fastq", "data", "r", "illumina", "seq", "sequence", "input", ""}
READ_DIRS = {"reads", "fastq", "fastqs", "raw", "rawdata", "raw_data", "illumina", "short_reads", "shortreads", "fq", "data", "trimmed", "clean"}
SKIP_DIRS = {"__pycache__", "node_modules", "results", "logs", "log", "predictions", "$recycle.bin", "system volume information"}
TOOL_DIRS = {"spades", "unicycler", "flye", "shovill", "skesa", "megahit", "canu", "raven", "plassembler", "plasmidspades", "hybracter", "trycycler",
             "quast", "prokka", "bakta", "mob_suite", "mobsuite", "platon", "plasflow", "miniasm", "velvet"}
TOOL_FILE_RE = re.compile(r"(^|[_.-])(contigs?|scaffolds?)([_.-]|\.)|assembly[_-]?graph|final[_.-]assembly", re.IGNORECASE)
ASSEMBLY_NAME_RE = re.compile(r"(^|[_.-])assembly\.(fa|fasta|fna)$", re.IGNORECASE)
TOOL_HEADER_RE = re.compile(r"^(NODE_\d+_length_|contig[_-]?\d|scaffold|edge_\d|utg\d|tig\d|k\d+_\d+)|\bdepth=\d", re.IGNORECASE)
ACCESSION_RE = re.compile(r"^(NZ_|NC_|NW_|CP\d|CM\d|LR\d|LT\d|AP\d|AE\d|CU\d|FO\d|HG\d|FM\d|AL\d)")
REF_WORDS = {"reference", "ref", "truth", "complete", "closed", "hybrid", "gold", "finished", "curated", "genome", "chromosome", "plasmid", "plasmids"}
TRIM_WORDS = {"trim", "trimmed", "clean", "cleaned", "filtered", "fastp", "qc", "dedup", "val", "paired", "subsampled", "sub"}
LONG_WORDS = {"nanopore", "ont", "pacbio", "hifi", "long", "minion", "pb"}
GROUPS = {
    "alignments": {".bam", ".sam", ".cram", ".bai", ".csi"},
    "documents": {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".md", ".rtf", ".odt"},
    "spreadsheets and tables": {".xls", ".xlsx", ".csv", ".tsv", ".ods"},
    "logs and text": {".log", ".txt", ".out", ".err"},
    "images and web": {".png", ".jpg", ".jpeg", ".svg", ".html", ".htm", ".gif"},
    "archives": {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z"},
    "annotations": {".gff", ".gff3", ".gtf", ".vcf", ".bed", ".faa", ".json", ".jsonl"},
}
READ_CODES = {"missing_reads_1", "missing_reads_2", "lanes", "multiple_read_pairs", "mate_style", "reads_unreadable", "reads_not_gzipped", "reads_bad_gzip", "mates_not_matching",
              "long_reads_as_pair", "same_file", "cloud_placeholder"}
REF_CODES = {"ambiguous_reference", "no_reference", "reference_looks_like_draft", "reference_small", "reference_shared", "reference_gzipped", "other_reference_candidates",
             "truth_without_reference"}
SNIFF_FASTA_BYTES =4 << 20
SNIFF_FASTQ_BYTES = 64 << 10
_FILE_ATTRIBUTE_OFFLINE, _RECALL_OPEN, _RECALL_DATA = 0x1000, 0x40000, 0x400000


def _tokens(text: str) -> list:
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t]


def _name_matches(sample_id: str, text: str) -> bool:
    """True when the sample id appears in `text` as whole tokens (S1 matches S1_ref but not S10_ref; Sample_01 matches sample01)."""
    want = "".join(_tokens(sample_id))
    toks = _tokens(text)
    if not want:
        return False
    for i in range(len(toks)):
        joined = ""
        for j in range(i, min(i + 5, len(toks))):
            joined += toks[j]
            if joined == want:
                return True
            if len(joined) > len(want):
                break
    return False


def sanitise_id(raw: str) -> str:
    """Make a sample id that init-local accepts: letters, digits . _ - ; starts with a letter or digit; does not end in _1/_2."""
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", raw.strip())
    text = re.sub(r"_+", "_", text).lstrip("._-").rstrip("._-")
    text = text or "isolate"
    if re.search(r"_[12]$", text):
        text += "_iso"
    return text


def _issue(code, level, message):
    return {"code": code, "level": level, "message": message}


def _is_placeholder(st) -> bool:
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & (_FILE_ATTRIBUTE_OFFLINE | _RECALL_OPEN | _RECALL_DATA))


# ------------------------------------------------------------------------------------------------- walking
def _walk(root: Path, max_depth, max_files, follow_symlinks, progress, cancel, skipped, warnings):
    """Yield (path, stat) for each file; counts skipped things. Never raises."""
    seen_dirs = set()
    stack = [(root, 0)]
    files = dirs = 0

    def warn(text):
        if len(warnings) < 60:
            warnings.append(text)

    def bump(reason, n=1):
        skipped[reason] = skipped.get(reason, 0) + n

    while stack:
        if cancel is not None and cancel.is_set():
            return
        folder, depth = stack.pop()
        try:
            real = os.path.realpath(folder)
            if real in seen_dirs:
                bump("symlink_loop")
                continue
            seen_dirs.add(real)
            entries = sorted(os.scandir(folder), key=lambda e: e.name)
        except OSError as exc:
            bump("unreadable_folder")
            warn(f"could not read folder {folder}: {exc.strerror or exc}")
            continue
        dirs += 1
        subdirs = []
        for entry in entries:
            try:
                name = entry.name
                if entry.is_symlink() and entry.is_dir():
                    if not follow_symlinks:
                        bump("symlink_folder")
                        continue
                    is_dir = True
                else:
                    is_dir = entry.is_dir(follow_symlinks=False)
                if is_dir:
                    if name.startswith("."):
                        bump("hidden_folder")
                    elif name.lower() in SKIP_DIRS:
                        bump("ignored_folder:" + name.lower())
                    elif depth >= max_depth:
                        bump("too_deep_folder")
                    else:
                        subdirs.append(Path(entry.path))
                    continue
                if name.startswith("."):
                    bump("hidden_file")
                    continue
                st = entry.stat()
                files += 1
                if files > max_files:
                    bump("max_files_reached")
                    warn(f"stopped after {max_files} files: narrow the folder or raise the limit")
                    return
                if progress is not None and files % 500 == 0:
                    progress({"files": files, "folders": dirs, "current": str(folder)})
                yield Path(entry.path), st
            except OSError as exc:
                bump("unreadable_file")
                warn(f"could not inspect {entry.path}: {exc.strerror or exc}")
        for sub in reversed(subdirs):
            stack.append((sub, depth + 1))
    if progress is not None:
        progress({"files": files, "folders": dirs, "current": ""})


# ------------------------------------------------------------------------------------------------- sniffing
def _read_head(path: Path, limit: int) -> bytes:
    """The first `limit` DECOMPRESSED bytes (never the whole file). Raises OSError/EOFError/zlib.error on a bad file."""
    with open(path, "rb") as raw:
        magic = raw.read(2)
        raw.seek(0)
        if magic == b"\x1f\x8b":
            with gzip.GzipFile(fileobj=raw) as handle:
                return handle.read(limit)
        return raw.read(limit)


def sniff_fastq(path: Path) -> dict:
    info = {"ok": False, "gz_magic": False, "reads": 0, "median_len": None, "first_name": "", "error": ""}
    try:
        with open(path, "rb") as raw:
            info["gz_magic"] = raw.read(2) == b"\x1f\x8b"
        if path.stat().st_size == 0:
            info["error"] = "the file is empty (0 bytes)"
            return info
        data = _read_head(path, SNIFF_FASTQ_BYTES).decode("utf-8", "replace").split("\n")
    except (OSError, EOFError, zlib.error) as exc:
        info["error"] = f"could not be read ({exc}); a truncated or corrupt copy looks like this"
        return info
    lengths = []
    for i in range(0, len(data) - 3, 4):
        head, seq, plus, qual = data[i:i + 4]
        if not head.startswith("@") or not plus.startswith("+") or len(seq.strip()) != len(qual.strip()):
            info["error"] = f"read {len(lengths) + 1} is not valid FASTQ (needs @name, sequence, +, equal-length qualities)"
            return info
        if not lengths:
            info["first_name"] = re.sub(r"[/ ].*$", "", head[1:].strip())
        lengths.append(len(seq.strip()))
    if not lengths:
        info["error"] = "the file holds no complete read in its first part"
        return info
    lengths.sort()
    info.update(ok=True, reads=len(lengths), median_len=lengths[len(lengths) // 2])
    return info


def sniff_fasta(path: Path, size: int) -> dict:
    info = {"ok": False, "records": 0, "capped": False, "total_bp": size, "headers": [], "error": "", "nucleotide": True, "lengths": []}
    try:
        text = _read_head(path, SNIFF_FASTA_BYTES).decode("utf-8", "replace")
    except (OSError, EOFError, zlib.error) as exc:
        info["error"] = f"could not be read ({exc})"
        return info
    if not text.startswith(">"):
        info["error"] = "does not start with '>': not a FASTA file"
        return info
    info["capped"] = len(text.encode("utf-8", "ignore")) >= SNIFF_FASTA_BYTES
    letters = acgt = 0
    length = 0
    total = 0
    for line in text.split("\n"):
        if line.startswith(">"):
            if info["records"]:
                info["lengths"].append(length)
            info["records"] += 1
            if len(info["headers"]) < 6:
                info["headers"].append(line[1:].strip())
            length = 0
        else:
            s = line.strip()
            length += len(s)
            total += len(s)
            if letters < 200000:
                letters += len(s)
                u = s.upper()
                acgt += sum(u.count(c) for c in "ACGTNURYKMSWBDHV")
    if info["records"]:
        info["lengths"].append(length)
    info["nucleotide"] = (acgt / letters) > 0.9 if letters else False
    if not info["capped"]:
        info["total_bp"] = total
    info["ok"] = True
    return info


def _sniff_text_head(path: Path, n: int = 4096) -> str:
    try:
        with open(path, "rb") as handle:
            return handle.read(n).decode("utf-8", "replace")
    except OSError:
        return ""


# ------------------------------------------------------------------------------------------------- scan
def scan(root, max_depth: int = 6, max_files: int = 200000, follow_symlinks: bool = False, progress=None, cancel=None) -> dict:
    """Look through `root` and return {samples, unrecognised, skipped, warnings, ...}. Changes nothing on disk."""
    root = Path(root).expanduser()
    skipped: dict = {}
    warnings: list = []
    out = {"root": str(root), "samples": [], "unrecognised": [], "skipped": skipped, "warnings": warnings, "cancelled": False,
           "files_seen": 0, "max_depth": max_depth, "max_files": max_files}
    if not root.exists():
        warnings.append(f"{root} does not exist or cannot be seen from here")
        return out
    if root.is_file():
        warnings.append(f"{root} is a file; choose the folder that holds your files")
        return out

    fastq, fasta, reports, truths = [], [], [], []
    other: dict = {}
    placeholders = []
    count = 0
    for path, st in _walk(root, max_depth, max_files, follow_symlinks, progress, cancel, skipped, warnings):
        count += 1
        name = path.name
        low = name.lower()
        entry = {"path": path, "size": st.st_size, "placeholder": _is_placeholder(st)}
        if entry["placeholder"]:
            skipped["cloud_placeholder"] = skipped.get("cloud_placeholder", 0) + 1
            placeholders.append(str(path))
        if FASTQ_RE.search(name):
            fastq.append(entry)
        elif FASTA_RE.search(name):
            fasta.append(entry)
        elif low == "sequence_report.jsonl" or low.endswith(".sequence_report.jsonl") or low.endswith("_sequence_report.jsonl"):
            reports.append(entry)
        elif re.search(r"truth.*\.tsv$", low):
            truths.append(entry)
        elif GENBANK_RE.search(name):
            other.setdefault("GenBank files (init-local needs a FASTA reference)", []).append(str(path))
        else:
            ext = path.suffix.lower()
            label = next((g for g, exts in GROUPS.items() if ext in exts), "other files")
            other.setdefault(label, []).append(str(path))
    out["files_seen"] = count
    if cancel is not None and cancel.is_set():
        out["cancelled"] = True
        warnings.append("the scan was cancelled; what follows is incomplete")

    unrec: dict = {k: list(v) for k, v in other.items()}

    def note(kind, p):
        unrec.setdefault(kind, []).append(str(p))

    # ---- reads: group mates, then lanes
    groups: dict = {}
    singles = []
    for e in fastq:
        m = MATE_RE.match(e["path"].name)
        if not m:
            singles.append(e)
            continue
        key = (str(e["path"].parent), m["stem"], m["r"].upper(), m["tail"] or "", m["ext"].lower(), bool(m["gz"]))
        groups.setdefault(key, {}).setdefault(m["mate"], []).append(e)
    pairs = []   # {dir, stem, r1: entry|None, r2: entry|None, notes}
    leftovers = []
    for key, mates in sorted(groups.items()):
        r1, r2 = mates.get("1", []), mates.get("2", [])
        if r1 and r2 and len(r1) == 1 and len(r2) == 1:
            pairs.append({"dir": key[0], "stem": key[1], "r1": r1[0], "r2": r2[0], "note": ""})
        else:
            for e in r1 + r2:
                leftovers.append((key, e))
    # re-pair mates whose naming style differs (_R1 with _2) inside one folder and stem
    by = {}
    for key, e in leftovers:
        mate = MATE_RE.match(e["path"].name)["mate"]
        by.setdefault((key[0], key[1]), {}).setdefault(mate, []).append(e)
    for (d, stem), mates in sorted(by.items()):
        if len(mates.get("1", [])) == 1 and len(mates.get("2", [])) == 1:
            pairs.append({"dir": d, "stem": stem, "r1": mates["1"][0], "r2": mates["2"][0], "note": "the two mates are named in different styles"})
        else:
            for mate, es in mates.items():
                for e in es:
                    pairs.append({"dir": d, "stem": stem, "r1": e if mate == "1" else None, "r2": e if mate == "2" else None, "note": ""})

    def isolate_name(stem, folder):
        name = LANE_RE.sub("", stem)
        m = SAMPLE_NO_RE.match(name)
        if m and name != stem:
            name = m["name"]
        name = name.strip("_.-")
        if name.lower() in GENERIC or not name:
            name = Path(folder).name or "isolate"
        return name

    sample_groups: dict = {}
    for p in pairs:
        raw = isolate_name(p["stem"], p["dir"])
        p["raw"] = raw
        sample_groups.setdefault((p["dir"], raw.lower()), []).append(p)

    samples = []
    for (d, _low), plist in sorted(sample_groups.items()):
        plist.sort(key=lambda x: x["stem"])
        samples.append(_make_sample(d, plist, root))

    # ---- attach unpaired/long reads
    for e in singles:
        placed = False
        for s in samples:
            if str(e["path"].parent) == s["_dir"] or _name_matches(s["sample_id"], e["path"].stem):
                s.setdefault("reads_single", []).append(str(e["path"]))
                placed = True
                break
        if not placed:
            note("unpaired or long reads (not used by init-local)", e["path"])
    for s in samples:
        if s.get("reads_single"):
            s["issues"].append(_issue("long_reads_unused", "info", f"{len(s['reads_single'])} unpaired/long-read FASTQ file(s) in this isolate's folder are not used: init-local takes paired Illumina reads only"))

    _assign_ids(samples)

    # ---- classify FASTAs
    candidates = []
    for e in fasta:
        info = _classify_fasta(e, root)
        if info["tool_output"]:
            note("assembler output (contigs, scaffolds ...): not a reference", e["path"])
        elif info["error"] and not info["ok"]:
            note("FASTA that could not be used: " + info["error"], e["path"])
        else:
            candidates.append(info)
    rep_c = [{"path": e["path"], "placeholder": e["placeholder"]} for e in reports]
    truth_c = []
    for e in truths:
        head = _sniff_text_head(e["path"], 512).split("\n", 1)[0].lower()
        if "sequence_id" in head and "molecule_type" in head:
            truth_c.append({"path": e["path"], "placeholder": e["placeholder"]})
        else:
            note("tables named truth* without sequence_id/molecule_type columns", e["path"])

    per_home: dict = {}
    for s in samples:
        per_home[s["_home"]] = per_home.get(s["_home"], 0) + 1
    used_ref: dict = {}
    for s in samples:
        _attach_files(s, candidates, rep_c, truth_c, per_home, len(samples), root)
        if s["reference"]:
            used_ref.setdefault(s["reference"], []).append(s["sample_id"])
    for ref, ids in used_ref.items():
        if len(ids) > 1:
            for s in samples:
                if s["sample_id"] in ids:
                    s["issues"].append(_issue("reference_shared", "warn", f"the same reference is chosen for {', '.join(ids)}: check that they are the same strain"))
    _sniff_reads(samples, placeholders)
    for s in samples:
        _finish(s)

    matched_refs = {s["reference"] for s in samples if s["reference"]} | {a["path"] for s in samples for a in s["alternatives"]["reference"]}
    for c in candidates:
        if str(c["path"]) not in matched_refs:
            note("reference-like FASTA not matched to any sample", c["path"])
    for s in samples:
        for k in ("_dir", "_home"):
            s.pop(k, None)
    out["samples"] = samples
    out["unrecognised"] = [{"kind": k, "count": len(v), "examples": sorted(v)[:5]} for k, v in sorted(unrec.items())]
    return out


def _make_sample(d, plist, root):
    pair_options = []
    for p in plist:
        pair_options.append(p)
    # lanes: pairs of one isolate that differ by an Illumina lane token
    lane_pairs = [p for p in plist if LANE_RE.search(p["stem"]) and p["r1"] and p["r2"]]
    notes = []
    chosen = []
    alt_pairs = []
    if lane_pairs and len(lane_pairs) == len(plist):
        chosen = lane_pairs
    else:
        complete = [p for p in plist if p["r1"] and p["r2"]]
        pool = complete or plist
        pool = sorted(pool, key=lambda p: (any(t in TRIM_WORDS for t in _tokens(p["stem"])), p["stem"]))
        chosen = [pool[0]]
        alt_pairs = [p for p in plist if p is not pool[0]]
    first = chosen[0]
    s = {"sample_id": "", "source_id": first["raw"], "reads_1": str(first["r1"]["path"]) if first["r1"] else None,
         "reads_2": str(first["r2"]["path"]) if first["r2"] else None, "reference": None, "sequence_report": None, "truth_hint": None,
         "confidence": "high", "issues": [], "alternatives": {"reference": [], "reads": [], "sequence_report": [], "truth": []},
         "why": {"reads": [], "reference": [], "sequence_report": [], "truth": []}, "lanes": [], "_dir": d}
    if len(chosen) > 1:
        s["lanes"] = [{"reads_1": str(p["r1"]["path"]), "reads_2": str(p["r2"]["path"])} for p in chosen]
        s["issues"].append(_issue("lanes", "warn", f"{len(chosen)} lanes of the same isolate found; they would be joined by gzip concatenation (nothing is decompressed). "
                                                  "Confirm that they are one library, or add the isolate by hand."))
        s["why"]["reads"].append(f"{len(chosen)} read pairs differ only by an Illumina lane (_L00N), so they are treated as lanes of one isolate")
    else:
        s["why"]["reads"].append("one read pair found" + (" (" + first["note"] + ")" if first["note"] else ""))
    if first["note"]:
        s["issues"].append(_issue("mate_style", "warn", f"the mates of {first['stem']} are named in different styles: check they belong together"))
    if not first["r2"]:
        s["issues"].append(_issue("missing_reads_2", "error", f"only the forward reads ({Path(s['reads_1']).name}) were found; the reverse mate is missing"))
    if not first["r1"]:
        s["issues"].append(_issue("missing_reads_1", "error", f"only the reverse reads ({Path(s['reads_2']).name}) were found; the forward mate is missing"))
    for p in alt_pairs:
        s["alternatives"]["reads"].append({"reads_1": str(p["r1"]["path"]) if p["r1"] else None, "reads_2": str(p["r2"]["path"]) if p["r2"] else None})
    if alt_pairs:
        s["issues"].append(_issue("multiple_read_pairs", "warn", f"{len(alt_pairs) + 1} read pairs share the isolate name '{first['raw']}' in this folder "
                                                                  "(for example raw and trimmed); the one without trim/clean/filter words was chosen: check it"))
    # home folder
    rel_parts = []
    try:
        rel_parts = list(Path(d).relative_to(root).parts)
    except ValueError:
        pass
    home = Path(d)
    for i in range(len(rel_parts)):
        cand = Path(root).joinpath(*rel_parts[:i + 1])
        if _name_matches(first["raw"], cand.name):
            home = cand
            break
    else:
        if Path(d).name.lower() in READ_DIRS and Path(d) != Path(root):
            home = Path(d).parent
    s["_home"] = str(home)
    s["_alt_pairs"] = alt_pairs
    return s


def _assign_ids(samples):
    taken: dict = {}
    for s in samples:
        base = sanitise_id(s["source_id"])
        sid = base
        folder_prefix = sanitise_id(Path(s["_dir"]).name)
        if sid.lower() in taken:
            sid = sanitise_id(f"{folder_prefix}_{base}")
            s["issues"].append(_issue("duplicate_id", "warn", f"another isolate is also called '{base}' (ids are compared ignoring capitals, as Windows folders are); renamed '{sid}'"))
        n = 2
        while sid.lower() in taken:
            sid = f"{base}_{n}"
            n += 1
        taken[sid.lower()] = True
        if sid != s["source_id"] and not any(i["code"] == "duplicate_id" for i in s["issues"]):
            s["issues"].append(_issue("id_sanitised", "info", f"the name '{s['source_id']}' was changed to '{sid}' (only letters, digits, . _ - are allowed in a sample id)"))
        s["sample_id"] = sid


def _classify_fasta(e, root) -> dict:
    path = e["path"]
    info = {"path": path, "size": e["size"], "placeholder": e["placeholder"], "tool_output": False, "ok": False, "error": "", "records": 0, "capped": False,
            "headers": [], "evidence": 0, "reasons": [], "gz": path.name.lower().endswith(".gz")}
    name = path.name
    try:
        parts = [p.lower() for p in path.parent.relative_to(root).parts]
    except ValueError:
        parts = []
    tool_dir = next((p for p in parts if p in TOOL_DIRS), None)
    if TOOL_FILE_RE.search(name):
        info["tool_output"] = True
        info["why_tool"] = "named like assembler output (contigs/scaffolds/assembly graph)"
        return info
    if ASSEMBLY_NAME_RE.search(name) and tool_dir:
        info["tool_output"] = True
        info["why_tool"] = f"named assembly.fasta inside a '{tool_dir}' folder"
        return info
    if tool_dir:
        info["tool_output"] = True
        info["why_tool"] = f"inside a '{tool_dir}' output folder"
        return info
    if e["placeholder"]:
        info["error"] = "online-only cloud file (not downloaded); not opened"
        info["ok"] = True
        info["issue"] = "cloud"
        return info
    if info["gz"]:
        info["ok"] = True
        info["evidence"] -= 4
        info["reasons"].append("gzipped FASTA: init-local needs a plain FASTA, gunzip it first")
        info["issue"] = "gz"
        return info
    sn = sniff_fasta(path, e["size"])
    if not sn["ok"]:
        info["error"] = sn["error"]
        return info
    info.update(records=sn["records"], capped=sn["capped"], headers=sn["headers"], ok=True, total_bp=sn["total_bp"])
    if not sn["nucleotide"]:
        info["ok"] = False
        info["error"] = "not a nucleotide FASTA (protein?)"
        return info
    if any(TOOL_HEADER_RE.search(h) for h in sn["headers"]):
        info["tool_output"] = True
        info["why_tool"] = "FASTA headers look like assembler output (NODE_..., depth=..., contig_N)"
        return info
    ev, why = 0, info["reasons"]
    if any(ACCESSION_RE.match(h.split()[0]) for h in sn["headers"] if h.split()):
        ev += 3
        why.append("a header carries an NCBI accession (NZ_/NC_/CP...)")
    if any(re.search(r"complete (genome|sequence)|plasmid|chromosome", h, re.IGNORECASE) for h in sn["headers"]):
        ev += 2
        why.append("a header says complete genome/sequence, plasmid or chromosome")
    if 1 <= sn["records"] <= 30 and not sn["capped"]:
        ev += 1
        why.append(f"{sn['records']} sequence(s): the size of a finished genome")
    if sn["records"] > 50 or (sn["capped"] and sn["records"] > 30):
        ev -= 4
        why.append(f"{sn['records']}{'+' if sn['capped'] else ''} sequences: looks like a draft assembly, not a closed genome")
        info["draft"] = True
    if e["size"] < 20000:
        ev -= 2
        why.append("under 20 kb: too small for a bacterial genome (a lone plasmid?)")
        info["small"] = True
    folder_words = {t for p in path.parent.parts[-3:] for t in _tokens(p)}
    if folder_words & REF_WORDS:
        ev += 2
        why.append("a folder name says reference/truth/complete/closed/hybrid")
    if set(_tokens(path.stem)) & REF_WORDS:
        ev += 2
        why.append("the file name says reference/truth/complete/genome/hybrid")
    if ASSEMBLY_NAME_RE.search(name):
        ev -= 2
        why.append("named assembly.fasta, which is also what assemblers write")
    info["evidence"] = ev
    return info


def _attach_files(s, candidates, reports, truths, per_home, nsamples, root):
    home = Path(s["_home"])
    dirpath = Path(s["_dir"])
    solo = per_home.get(s["_home"], 0) == 1

    def relation(path: Path):
        score, why = 0, []
        if solo:
            if path.parent == dirpath:
                score += 4
                why.append("in the same folder as the reads")
            elif home in path.parents or path.parent == home:
                score += 3
                why.append(f"inside the isolate's folder '{home.name}'")
        if _name_matches(s["sample_id"], path.stem) or _name_matches(s["source_id"], path.stem):
            score += 4
            why.append(f"the file name contains the sample name '{s['source_id']}'")
        if not score and nsamples == 1:
            score = 1
            why.append("the only sample and the only such file in the folder tree")
        return score, why

    ranked = []
    for c in candidates:
        rel, why = relation(c["path"])
        if rel:
            ranked.append((c["evidence"] + rel, rel, c, why))
    ranked.sort(key=lambda t: (-t[0], str(t[2]["path"])))
    if ranked:
        best = ranked[0]
        c = best[2]
        s["reference"] = str(c["path"])
        s["why"]["reference"] = best[3] + c["reasons"] + [f"score {best[0]}"]
        for t in ranked[1:]:
            s["alternatives"]["reference"].append({"path": str(t[2]["path"]), "score": t[0], "reasons": t[3] + t[2]["reasons"]})
        margin = best[0] - ranked[1][0] if len(ranked) > 1 else None
        weak = best[1] < 3 or c["evidence"] < 3
        if margin is None:
            s["_ref_conf"] = "medium" if weak else "high"
        elif margin >= 3:
            s["_ref_conf"] = "medium"
            s["issues"].append(_issue("other_reference_candidates", "info", f"{len(ranked) - 1} other possible reference file(s); '{Path(s['reference']).name}' scored clearly higher"))
        else:
            s["_ref_conf"] = "low"
            s["issues"].append(_issue("ambiguous_reference", "warn", f"{len(ranked)} FASTA files could be the reference and none is clearly the best; '{Path(s['reference']).name}' "
                                                                      "was chosen only by a narrow margin. Pick the right one."))
        if c.get("placeholder"):
            s["issues"].append(_issue("cloud_placeholder", "error", f"{Path(s['reference']).name} is an online-only cloud file; make it available offline first"))
        if c.get("issue") == "gz":
            s["issues"].append(_issue("reference_gzipped", "error", "the reference is gzipped; init-local needs a plain FASTA (gunzip it)"))
        if c.get("draft"):
            s["issues"].append(_issue("reference_looks_like_draft", "warn", "the chosen reference has very many sequences: it looks like a draft assembly, not a complete genome"))
        if c.get("small"):
            s["issues"].append(_issue("reference_small", "warn", "the chosen reference is under 20 kb: a complete genome of a bacterium is megabases long"))
    else:
        s["_ref_conf"] = None
        s["issues"].append(_issue("no_reference", "warn", "no reference FASTA could be tied to this isolate: it can be reconstructed but not scored"))

    for kind, pool, key in (("sequence_report", reports, "sequence_report"), ("truth", truths, "truth_hint")):
        rk = sorted(((relation(c["path"]), c) for c in pool), key=lambda t: (-t[0][0], str(t[1]["path"])))
        rk = [t for t in rk if t[0][0]]
        if not rk:
            continue
        (sc, why), c = rk[0]
        s[key] = str(c["path"])
        s["why"][kind] = why
        for (sc2, why2), c2 in rk[1:]:
            s["alternatives"][kind].append({"path": str(c2["path"]), "score": sc2, "reasons": why2})
        if len(rk) > 1 and rk[1][0][0] == sc:
            s["issues"].append(_issue("ambiguous_" + kind, "warn", f"several {kind.replace('_', ' ')} files fit this isolate equally; check '{Path(s[key]).name}'"))
    if s["sequence_report"] and s["truth_hint"]:
        s["issues"].append(_issue("truth_ignored", "info", "both a sequence report and a truth table were found; the sequence report is used (init-local builds the truth from it)"))
    if (s["sequence_report"] or s["truth_hint"]) and not s["reference"]:
        s["issues"].append(_issue("truth_without_reference", "warn", "a truth file was found but no reference FASTA: it cannot be used without the reference"))


def _sniff_reads(samples, placeholders):
    ph = set(placeholders)
    for s in samples:
        files = [f for f in (s["reads_1"], s["reads_2"]) if f] + [x for lane in s["lanes"][1:] for x in (lane["reads_1"], lane["reads_2"])]
        names = {}
        for f in files:
            if f in ph:
                s["issues"].append(_issue("cloud_placeholder", "error", f"{Path(f).name} is an online-only cloud file; make it available offline first"))
                continue
            sn = sniff_fastq(Path(f))
            if not sn["ok"]:
                s["issues"].append(_issue("reads_unreadable", "error", f"{Path(f).name}: {sn['error']}"))
                continue
            if not f.lower().endswith(".gz"):
                s["issues"].append(_issue("reads_not_gzipped", "error", f"{Path(f).name} is not gzipped; PlasBench needs .fastq.gz (gzip it)"))
            elif not sn["gz_magic"]:
                s["issues"].append(_issue("reads_bad_gzip", "error", f"{Path(f).name} is named .gz but is not gzip data"))
            names[f] = sn
        if s["reads_1"] and s["reads_2"] and s["reads_1"] in names and s["reads_2"] in names:
            a, b = names[s["reads_1"]], names[s["reads_2"]]
            if a["first_name"] and b["first_name"] and a["first_name"] != b["first_name"]:
                s["issues"].append(_issue("mates_not_matching", "warn", "the first read of the two mates has a different name: they may not be from the same library"))
            if a["median_len"] and a["median_len"] > 1000:
                s["issues"].append(_issue("long_reads_as_pair", "warn", f"the reads are long (median {a['median_len']} bp): this looks like long-read data, not Illumina"))
        if s["reads_1"] and s["reads_1"] == s["reads_2"]:
            s["issues"].append(_issue("same_file", "error", "forward and reverse reads are the same file"))


def _finish(s):
    levels = {i["level"] for i in s["issues"]}
    codes = {i["code"] for i in s["issues"]}
    if "error" in levels:
        s["status"] = "blocked"
    elif "warn" in levels:
        s["status"] = "review"
    else:
        s["status"] = "ready"
    conf = s.pop("_ref_conf", None)
    c = "high"
    if conf is None or conf == "medium" or "lanes" in codes:
        c = "medium"
    if conf == "low" or codes & {"ambiguous_reference", "multiple_read_pairs", "duplicate_id", "reference_shared", "mate_style"} or s["status"] == "blocked":
        c = "low"
    s["confidence"] = c
    s.pop("_alt_pairs", None)


# ------------------------------------------------------------------------------------------------- writing
def _init_module(root=None):
    python_dir = str((Path(root) if root else Path(__file__).resolve().parents[1]) / "python")
    if python_dir not in sys.path:
        sys.path.insert(0, python_dir)
    import init_local_sample
    return init_local_sample


def resolve_selection(sample: dict, choice: dict | None) -> dict:
    """Apply a user's edits (a different reference, read pair or id) to a scanned sample. Only files the scan itself listed for this sample are accepted."""
    choice = choice or {}
    out = dict(sample)
    out["lanes"] = list(sample.get("lanes") or [])
    refs = {sample["reference"]} | {a["path"] for a in sample["alternatives"]["reference"]} if sample["reference"] else {a["path"] for a in sample["alternatives"]["reference"]}
    if "reference" in choice:
        ref = choice["reference"] or None
        if ref and ref not in refs:
            raise ValueError("that reference was not found by the scan for this isolate")
        out["reference"] = ref
        if ref != sample["reference"]:
            out["issues"] = [i for i in out["issues"] if i["code"] not in REF_CODES]
    pairs = {sample["reads_1"]: (sample["reads_1"], sample["reads_2"])}
    for a in sample["alternatives"]["reads"]:
        pairs[a["reads_1"]] = (a["reads_1"], a["reads_2"])
    if choice.get("reads_1") and choice["reads_1"] != sample["reads_1"]:
        if choice["reads_1"] not in pairs:
            raise ValueError("those reads were not found by the scan for this isolate")
        out["reads_1"], out["reads_2"] = pairs[choice["reads_1"]]
        out["lanes"] = []
        # the user chose these reads by hand: the notes about the scan's own choice no longer apply, but the new files are checked
        out["issues"] = [i for i in out["issues"] if i["code"] not in READ_CODES]
        for f in (out["reads_1"], out["reads_2"]):
            if not f:
                out["issues"].append(_issue("missing_reads_2", "error", "the chosen read pair is incomplete"))
                continue
            sn = sniff_fastq(Path(f))
            if not sn["ok"]:
                out["issues"].append(_issue("reads_unreadable", "error", f"{Path(f).name}: {sn['error']}"))
            elif not f.lower().endswith(".gz"):
                out["issues"].append(_issue("reads_not_gzipped", "error", f"{Path(f).name} is not gzipped"))
    for key in ("sequence_report",):
        if key in choice:
            allowed = {sample.get(key)} | {a["path"] for a in sample["alternatives"][key]}
            if choice[key] and choice[key] not in allowed:
                raise ValueError(f"that {key.replace('_', ' ')} was not found by the scan for this isolate")
            out[key] = choice[key] or None
    new_id = str(choice.get("new_id") or "").strip()
    if new_id:
        out["sample_id"] = new_id
    return out


def stage(samples, data_dir, sheet, link="copy", confirm=False, selections=None, root=None, include=None) -> dict:
    """Place each ready sample (and, with confirm, each sample that only needs review) through init-local's own function. Blocked samples are never placed.

    `selections` maps sample_id -> edits (see resolve_selection). `include` (a set of sample ids) limits what is placed. Returns {results, staged, data_dir, samples}."""
    import contextlib
    import io
    init = _init_module(root)
    results = []
    selections = selections or {}
    for original in samples:
        sid0 = original["sample_id"]
        if include is not None and sid0 not in include:
            continue
        entry = {"sample_id": sid0, "ok": False, "messages": [], "needs_review": 0}
        results.append(entry)
        try:
            s = resolve_selection(original, selections.get(sid0))
        except ValueError as exc:
            entry["messages"].append(str(exc))
            continue
        sid = s["sample_id"]
        entry["sample_id"] = sid
        if not SAFE_SAMPLE.match(sid) or re.search(r"_[12]$", sid):
            entry["messages"].append(f"'{sid}' is not a usable sample id (letters, digits . _ - only; not ending in _1 or _2)")
            continue
        errs = [i["message"] for i in s["issues"] if i["level"] == "error"]
        if errs or not s.get("reads_1") or not s.get("reads_2"):
            entry["messages"].append("skipped: " + ("; ".join(errs) or "reads are incomplete"))
            continue
        if any(i["level"] == "warn" for i in s["issues"]) and not confirm:
            entry["messages"].append("skipped: needs your review first (" + "; ".join(i["message"] for i in s["issues"] if i["level"] == "warn")[:300] + ")")
            continue
        for f in [s["reads_1"], s["reads_2"], s.get("reference"), s.get("sequence_report"), s.get("truth_hint")]:
            if f and not Path(f).is_file():
                entry["messages"].append(f"skipped: {f} is no longer there")
                break
        else:
            existing = Path(data_dir) / sid / f"{sid}_1.fastq.gz"
            if existing.exists() and not existing.samefile(s["reads_1"]) and not s.get("lanes"):
                entry["messages"].append(f"skipped: {existing.parent} already holds different reads for '{sid}'")
                continue
            if s.get("lanes"):
                r1 = [Path(x["reads_1"]) for x in s["lanes"]]
                r2 = [Path(x["reads_2"]) for x in s["lanes"]]
            else:
                r1, r2 = Path(s["reads_1"]), Path(s["reads_2"])
            captured = io.StringIO()
            try:
                with contextlib.redirect_stdout(captured):
                    entry["needs_review"] = init.stage_isolate(
                        sid, sid, r1, r2, s.get("reference"), s.get("sequence_report") if s.get("reference") else None, Path(data_dir), Path(sheet),
                        "LOCAL" if s.get("reference") else "NA", link, False,
                        s.get("truth_hint") if (s.get("reference") and not s.get("sequence_report")) else None)
                entry["ok"] = True
            except (SystemExit, OSError) as exc:
                entry["messages"].append(str(exc))
            entry["messages"].extend(line.strip() for line in captured.getvalue().splitlines() if line.strip())
    return {"results": results, "staged": [r for r in results if r["ok"]], "data_dir": str(data_dir), "samples": str(sheet),
            "needs_review": sum(r["needs_review"] for r in results)}


def summary_rows(result: dict) -> list:
    """Plain rows for a table: sample, reads 1/2, reference, confidence, status, issues."""
    rows = []
    for s in result["samples"]:
        rows.append({"sample": s["sample_id"], "reads_1": s["reads_1"] or "", "reads_2": s["reads_2"] or "", "reference": s["reference"] or "",
                     "confidence": s["confidence"], "status": s["status"],
                     "issues": [i["message"] for i in s["issues"] if i["level"] != "info"]})
    return rows


class Scans:
    """Background scans for the window: start, poll, cancel. Bounded; scanning only reads."""
    def __init__(self, keep=8):
        self.keep, self.items, self.lock = keep, {}, threading.Lock()

    def start(self, folder, max_depth=6, max_files=200000) -> str:
        import uuid
        sid = uuid.uuid4().hex[:12]
        item = {"id": sid, "state": "running", "progress": {"files": 0, "folders": 0, "current": ""}, "result": None, "error": "", "cancel": threading.Event()}
        with self.lock:
            while len(self.items) >= self.keep:
                self.items.pop(next(iter(self.items)))
            self.items[sid] = item

        def work():
            try:
                res = scan(folder, max_depth, max_files, False, lambda p: item["progress"].update(p), item["cancel"])
                item["result"] = res
                item["state"] = "cancelled" if res.get("cancelled") else "done"
            except Exception as exc:  # noqa: BLE001  the window shows it
                item["error"] = f"{type(exc).__name__}: {exc}"
                item["state"] = "error"
        threading.Thread(target=work, daemon=True).start()
        return sid

    def get(self, sid) -> dict:
        item = self.items.get(sid)
        if not item:
            raise KeyError("no such scan")
        return item

    def status(self, sid) -> dict:
        item = self.get(sid)
        out = {"id": sid, "state": item["state"], "progress": dict(item["progress"]), "error": item["error"]}
        if item["state"] in ("done", "cancelled"):
            out["result"] = item["result"]
        return out

    def cancel(self, sid) -> dict:
        item = self.get(sid)
        item["cancel"].set()
        return {"id": sid, "state": item["state"]}


def dump(result) -> str:
    return json.dumps(result, indent=2, sort_keys=True)
