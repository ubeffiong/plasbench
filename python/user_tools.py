#!/usr/bin/env python3
"""User-added tools: declare a plasmid tool in one manifest and PlasBench installs, runs, scores and reports it.

A user tool is a folder holding ``plasbench-tool.ini`` (and, optionally, the scripts it names). PlasBench finds it on a
search path, first match wins:

    $PLASBENCH_TOOLS_PATH   (os.pathsep-separated folders; each holds one sub-folder per tool)
    ~/.plasbench/tools/
    <repo>/tools.d/

Set PLASBENCH_USER_TOOLS=off to ignore every user tool (built-ins are unaffected). The manifest maps PlasBench's own
inputs onto the tool's command line ([run] command with placeholders) and the tool's output onto PlasBench's prediction
files ([output]); docs/ADDING_TOOLS.md is the reference and tools.d/examples/ holds one worked manifest per case.

A tool may do several tasks ([tool] task = classification, binning_reconstruction): the command runs once per sample and
each task is a registry row of its own (the first listed keeps the tool's name, the others are <name>__<task>), converted
from the same output by the derivation rules in docs/ADDING_TOOLS.md. A tool may come from a URL (https only) or from a
folder on this computer ([install] method = url | local), and may write several output types ([output] format = auto,
or a comma list).

Command-line use (scripts/04_run_tools.sh, env/install_tools.sh and `plasbench tools` call it):

    user_tools.py list | validate [NAME] | show NAME | dump | names [--enabled LIST]
    user_tools.py run-spec NAME --sample S --contigs F --graph F --reads-1 F --reads-2 F --long-reads F --outdir D --threads N
    user_tools.py install-plan NAME   |   task-ids NAME   |   fetch NAME   (download or locate the tool's source; `plasbench install-tools` runs it)
    user_tools.py new NAME [--dir D] [--task a,b] [--source S] [--url U] [--sha256 H] [--local-path P] [--output-format F]
    user_tools.py add PATH [--dest D]

For a program (the window's form): parse_text(text), validate_text(text) -> {ok, problems, warnings, tasks, source, outputs},
and the constants TASKS, FORMATS, INSTALL_METHODS, TASK_HELP, FORMAT_HELP, SOURCE_HELP.
"""

import argparse
import configparser
import csv
import hashlib
import json
import os
import re
import shlex
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import user_tool_source as source_lib  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = "plasbench-tool.ini"
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
TASKS = ("binning_reconstruction", "sequence_reassembly", "classification")
LEGACY_TASKS = {"reconstruction": "binning_reconstruction"}   # the manifest value before the three-way split: it always meant binning
TASK_SHORT = {"binning_reconstruction": "binning", "sequence_reassembly": "reassembly", "classification": "classification"}
TRACKS = ("short_read", "long_read", "hybrid")
RUN_MODES = ("command", "import")
FORMATS = ("contig_bins", "contig_labels", "plasmid_fasta", "fasta_dir", "adapter", "auto")
INSTALL_METHODS = ("conda", "pip", "script", "url", "local", "none")
SOURCE_KINDS = ("archive", "git", "file")
LOCAL_MODES = ("link", "copy")
TASK_ID_SEPARATOR = "__"

TASK_HELP = {
    "binning_reconstruction": "Groups assembly contigs into plasmids (bins); scored with bin-level metrics such as completeness, purity and CPRR.",
    "sequence_reassembly": "Writes predicted plasmid sequence (a FASTA); scored on how well the sequence matches the true plasmids.",
    "classification": "Labels each contig plasmid or chromosome, optionally with a probability; scored per base with F1 and PR-AUC.",
}
FORMAT_HELP = {
    "contig_bins": "A table with one row per contig and the bin (plasmid) it belongs to; serves binning, and classification (a contig in any bin is plasmid).",
    "contig_labels": "A table with one row per contig and a plasmid/chromosome label and/or a probability; serves classification, and binning only as one flagged bin per plasmid contig.",
    "plasmid_fasta": "One FASTA of predicted plasmid sequence, each record its own plasmid; serves sequence reassembly only.",
    "fasta_dir": "A folder with one FASTA file per predicted plasmid; serves sequence reassembly only.",
    "adapter": "Your own script converts the tool's output into PlasBench's native files for the tasks named in adapter_tasks.",
    "auto": "PlasBench looks at the files listed in candidates and recognises each by its content; an ambiguous or unrecognisable output is an error, never a guess.",
}
SOURCE_HELP = {
    "conda": "Installs the named conda packages into the tool's own environment.",
    "pip": "Installs the named pip packages into the tool's own environment.",
    "script": "Runs an install script that ships beside the manifest.",
    "url": "Downloads the tool from an https URL (archive, git repository or single file) into the manifest's src/ folder, checking its sha256 when you give one.",
    "local": "Uses a tool already on this computer: a copy (recorded with a checksum, reproducible) or a link (used in place, can change under the benchmark).",
    "none": "Nothing to install: the command is already on PATH.",
}
# What PlasBench hands a tool. The value of each is the file (or folder, or number) for the sample being run.
PLACEHOLDERS = {
    "contigs": "the sample's assembly contigs FASTA",
    "graph": "the sample's assembly graph (GFA)",
    "reads_1": "trimmed short reads, mate 1 (FASTQ.gz)",
    "reads_2": "trimmed short reads, mate 2 (FASTQ.gz)",
    "long_reads": "the sample's long reads (FASTQ.gz)",
    "outdir": "an empty folder for this tool and sample; the tool writes its output here",
    "threads": "the thread count for this tool",
    "sample": "the sample id",
    "db": "the tool's database path ([database] path)",
    "tool_dir": "the folder holding this manifest (for scripts shipped with it)",
    "src": "the downloaded or located tool: a folder, or the file for a single-file source ([install] method = url or local)",
}
INPUT_PLACEHOLDERS = ("contigs", "graph", "reads_1", "reads_2", "long_reads", "db")
INSTALL_PLACEHOLDERS = ("src", "tool_dir", "threads")
# Keys each section accepts; anything else is a typo and is reported, never silently ignored.
FORMAT_KEYS = {"path", "delimiter", "header", "comment", "contig_column", "bin_column", "label_column", "plasmid_values",
               "score_column", "threshold", "contig_id_strip_regex", "contig_id_from", "adapter", "adapter_tasks",
               "fasta_glob", "bin_none_values"}
SCHEMA = {
    "tool": {"name", "display_name", "task", "analysis_track", "method_class", "description", "citation", "url",
             "version_command", "requires_independent_long_read_truth"},
    "install": {"method", "packages", "channels", "pip_packages", "python", "script", "env_name", "verify_command",
                "url", "sha256", "kind", "ref", "submodules", "build_command", "max_download_mb", "download_timeout_seconds",
                "path", "mode"},
    "database": {"uses_reference_database", "database", "release_date", "path", "note"},
    "run": {"mode", "command", "requires", "threads", "timeout_seconds", "dir", "pattern", "env"},
    "output": FORMAT_KEYS | {"format", "candidates"},
}
OUTPUT_SECTION_PREFIX = "output."
REQUIRED = {"tool": ("name", "task", "analysis_track"), "run": ("mode",), "output": ("format",)}
PATH_FORMATS = ("contig_bins", "contig_labels", "plasmid_fasta", "adapter")


class ManifestError(ValueError):
    """A manifest PlasBench cannot use; the message names the file and the fix."""


def builtin_tools():
    """Names PlasBench already defines (a user tool may not reuse one: results would be mixed under one name)."""
    names = set()
    for rel in ("config/tool_capabilities.tsv", "config/tool_installers.tsv"):
        path = ROOT / rel
        if path.is_file():
            with path.open(newline="", encoding="utf-8") as handle:
                names.update(row["tool"] for row in csv.DictReader(handle, delimiter="\t") if row.get("tool"))
    return names


def disabled():
    return os.environ.get("PLASBENCH_USER_TOOLS", "").strip().lower() in {"off", "0", "no", "false", "none"}


def search_path():
    paths = [Path(p).expanduser() for p in os.environ.get("PLASBENCH_TOOLS_PATH", "").split(os.pathsep) if p.strip()]
    paths.append(Path.home() / ".plasbench" / "tools")
    paths.append(ROOT / "tools.d")
    unique, seen = [], set()
    for path in paths:   # a folder named twice (PLASBENCH_TOOLS_PATH=~/.plasbench/tools) is searched once
        key = os.path.normcase(os.path.abspath(path))
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _split(value):
    return [v.strip() for v in re.split(r"[,\s]+", value or "") if v.strip()]


def _split_commas(value):
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def _placeholders(template):
    return set(re.findall(r"\{([a-z_0-9]+)\}", template or ""))


def _task(value):
    return LEGACY_TASKS.get(value, value)


# -- what each task needs, from what the tool writes -------------------------------------------------------------------
# which tasks an output format can give a result for, native or derived (see derive_tasks); an adapter serves adapter_tasks, auto serves whatever the file turns out to be
_SERVING = {"contig_bins": ("binning_reconstruction", "classification"), "contig_labels": ("classification", "binning_reconstruction"),
            "plasmid_fasta": ("sequence_reassembly",), "fasta_dir": ("sequence_reassembly",)}


def derive_tasks(tasks, formats, adapter_tasks=(), strict=True):
    """[{"task", "status": native|derived|not_possible, "how"}] for each task, given the declared output formats.

    The derivation table (docs/ADDING_TOOLS.md): bins -> classification is derivable (a contig in any bin is plasmid);
    labels -> classification is native; labels -> binning only as one bin per plasmid contig, flagged as not a real
    grouping; a plasmid FASTA or folder is sequence_reassembly only and cannot be turned into classification or binning;
    an adapter serves exactly the tasks in adapter_tasks. `strict=False` (a manifest with one task and one format, the
    only shape that existed before) keeps accepting what it always accepted, with the reason as a note.
    """
    formats = list(formats)
    out = []
    for task in tasks:
        if "auto" in formats:
            out.append({"task": task, "status": "native",
                        "how": "decided for each sample from what the tool wrote (priority: "
                               + " > ".join(_priority(task)) + "); a sample whose output cannot serve this task is skipped with the reason"})
            continue
        out.append(_derive_one(task, set(formats), set(adapter_tasks), strict))
    return out


def _priority(task):
    return {"binning_reconstruction": ("contig_bins", "contig_labels"), "classification": ("contig_labels", "contig_bins"),
            "sequence_reassembly": ("plasmid_fasta", "fasta_dir")}[task]


def _derive_one(task, have, adapter_tasks, strict):
    def row(status, how):
        return {"task": task, "status": status, "how": how}
    if "adapter" in have and task in adapter_tasks:
        return row("native", "the adapter writes the native files for this task (it is called once per task with PLASBENCH_TASK set)")
    fasta = have & {"plasmid_fasta", "fasta_dir"}
    names = ", ".join(sorted(have)) or "no output"
    if task == "binning_reconstruction":
        if "contig_bins" in have:
            return row("native", "contig_bins gives the bins directly")
        if "contig_labels" in have:
            return row("derived", "contig_labels gives one bin per contig labelled plasmid; this is NOT a real grouping, so it is flagged and "
                                  "bin-level metrics carry little meaning")
        if fasta and not strict:
            return row("derived", "legacy single-format manifest: each FASTA record is written as its own bin (not a real grouping)")
        return row("not_possible", f"binning needs contig_bins (or contig_labels as a flagged fallback); declared: {names}. A plasmid FASTA does not "
                                   f"say which assembly contigs belong together. Fix: add contig_bins (or an adapter with adapter_tasks "
                                   f"including binning_reconstruction), or drop this task")
    if task == "classification":
        if "contig_labels" in have:
            return row("native", "contig_labels gives the plasmid/chromosome call (and probability) directly")
        if "contig_bins" in have:
            return row("derived", "a contig that is in any bin is called plasmid; there is no probability, so no PR curve")
        if fasta and not strict:
            return row("derived", "legacy single-format manifest: the predicted plasmid FASTA is scored as the plasmid call")
        return row("not_possible", f"classification needs contig_labels or contig_bins; declared: {names}. A plasmid FASTA has no contig ids to "
                                   f"label. Fix: add contig_labels or contig_bins, or an adapter with adapter_tasks including classification, "
                                   f"or drop this task")
    if fasta:
        return row("native", "the plasmid FASTA (or folder of FASTA files) is the sequence prediction")
    if have & {"contig_bins", "contig_labels"} and not strict:
        return row("derived", "legacy single-format manifest: the called contigs are scored as the sequence prediction")
    return row("not_possible", f"sequence reassembly needs plasmid_fasta or fasta_dir; declared: {names}. Contig tables do not contain new "
                               f"sequence. Fix: add plasmid_fasta or fasta_dir, or an adapter with adapter_tasks including "
                               f"sequence_reassembly, or drop this task")


# -- the manifest ------------------------------------------------------------------------------------------------------
class Manifest:
    """Parsed manifest sections with every derived fact; no file access except where `folder` is given."""

    def __init__(self, sections, folder=None, path=None):
        self.sections = sections
        self.folder = Path(folder) if folder else None
        self.path = Path(path) if path else None

    # -- convenience ------------------------------------------------------------------------------------------
    def get(self, section, key, default=""):
        return (self.sections.get(section, {}).get(key) or default).strip()

    def output_get(self, fmt, key, default=""):
        """A format's own [output.<fmt>] key, else the [output] key, else the default."""
        if fmt:
            own = self.sections.get(OUTPUT_SECTION_PREFIX + fmt, {}).get(key)
            if own is not None and own.strip():
                return own.strip()
        return self.get("output", key, default)

    @property
    def name(self):
        return self.get("tool", "name")

    @property
    def tasks(self):
        out = []
        for value in _split_commas(self.get("tool", "task")):
            if _task(value) not in out:
                out.append(_task(value))
        return out

    @property
    def task(self):
        """The primary task: the first one listed."""
        return (self.tasks or [""])[0]

    @property
    def track(self):
        return self.get("tool", "analysis_track")

    @property
    def display_name(self):
        return self.get("tool", "display_name") or self.name

    @property
    def env_name(self):
        return self.get("install", "env_name") or f"plasbench-{self.name}"

    @property
    def formats(self):
        out = []
        for value in _split_commas(self.get("output", "format")):
            if value not in out:
                out.append(value)
        return out

    @property
    def auto(self):
        return self.formats == ["auto"]

    @property
    def multi_output(self):
        """More than one output type, or auto: the stage hands the converter the output folder, not one file."""
        return self.auto or len(self.formats) > 1

    @property
    def strict(self):
        return len(self.tasks) > 1 or self.multi_output

    @property
    def method(self):
        return self.get("install", "method", "none")

    @property
    def adapter_tasks(self):
        listed = [_task(t) for t in _split_commas(self.output_get("adapter", "adapter_tasks"))]
        return listed or ([self.task] if self.task else [])

    def task_id(self, task):
        return self.name if task == self.task else f"{self.name}{TASK_ID_SEPARATOR}{task}"

    def task_display(self, task):
        return f"{self.display_name} ({TASK_SHORT.get(task, task)})" if len(self.tasks) > 1 else self.display_name

    def task_ids(self):
        """[(id, task)], primary first. Ids are <name> for the primary and <name>__<task> for the others."""
        return [(self.task_id(t), t) for t in self.tasks]

    def derivation(self):
        return derive_tasks(self.tasks, self.formats, self.adapter_tasks, self.strict)

    def source_summary(self):
        method = self.method
        info = {"method": method, "description": SOURCE_HELP.get(method, "")}
        if method == "url":
            url = self.get("install", "url")
            kind = self.get("install", "kind", "auto")
            info.update(url=url, kind=source_lib.detect_kind(url) if kind == "auto" else kind, ref=self.get("install", "ref"),
                        sha256=self.get("install", "sha256").lower(), sha256_pinned=bool(self.get("install", "sha256")),
                        build_command=self.get("install", "build_command"), installs_to="src/ beside the manifest")
        elif method == "local":
            info.update(path=self.get("install", "path"), mode=self.get("install", "mode", "copy"),
                        build_command=self.get("install", "build_command"))
        elif method == "conda":
            info["packages"] = _split(self.get("install", "packages"))
        elif method == "pip":
            info["packages"] = _split(self.get("install", "pip_packages"))
        elif method == "script":
            info["script"] = self.get("install", "script")
        return info

    def serves(self, fmt):
        """The declared tasks that output format `fmt` gives a result for (not_possible tasks are left out): what the window shows beside each output row."""
        status = {e["task"]: e["status"] for e in self.derivation()}
        out = []
        for task in self.tasks:
            if status.get(task, "not_possible") == "not_possible":
                continue
            if fmt == "auto" or task in _SERVING.get(fmt, ()) or (fmt == "adapter" and task in self.adapter_tasks)                     or (not self.strict and fmt in ("plasmid_fasta", "fasta_dir")):
                out.append(task)
        return out

    def output_summary(self):
        """[{"format", "path" | "candidates", "serves": [task, ...]}] in the order declared."""
        if self.auto:
            return [{"format": "auto", "candidates": _split_commas(self.get("output", "candidates")), "serves": self.serves("auto")}]
        return [{"format": f, "path": self.output_get(f, "path"), "serves": self.serves(f)} for f in self.formats]

    # -- where the tool's source lives ---------------------------------------------------------------------------
    def src_path(self):
        """{src}: where the downloaded or located tool is (or will be after install); None for other methods."""
        if self.folder is None:
            return None
        if self.method == "url":
            kind = self.get("install", "kind", "auto")
            url = self.get("install", "url")
            kind = source_lib.detect_kind(url) if kind == "auto" else kind
            base = self.folder / source_lib.SRC_DIR
            return base / source_lib.file_name_from_url(url) if kind == "file" else base
        if self.method == "local":
            target = source_lib.local_target(self.get("install", "path"))
            if self.get("install", "mode", "copy") == "link":
                return target
            base = self.folder / source_lib.SRC_DIR
            return base / target.name if target.is_file() or not target.exists() and target.suffix else base
        return None

    def src_dir(self):
        """The folder a build_command runs in: {src} itself when it is a folder, else the folder holding the file."""
        src = self.src_path()
        if src is None:
            return self.folder
        return src if src.is_dir() or (not src.exists() and not src.suffix) else src.parent

    def source_signature(self):
        """What identifies the tool's bytes, for the stage-4 fingerprint: a changed URL, pinned sha256, recorded download
        checksum or (for a link) the linked files re-runs the tool."""
        method = self.method
        if method not in ("url", "local") or self.folder is None:
            return ""
        recorded = source_lib.last_record(self.folder)
        parts = [method, self.get("install", "url"), self.get("install", "sha256").lower(), self.get("install", "ref"),
                 self.get("install", "path"), self.get("install", "mode", "copy"), self.get("install", "build_command"),
                 recorded.get("commit", ""), recorded.get("tree_sha256", "") or recorded.get("sha256", "")]
        if method == "local" and self.get("install", "mode", "copy") == "link":
            parts.append(source_lib.quick_signature(source_lib.local_target(self.get("install", "path"))))
        return "|".join(parts)

    def checksum(self):
        """Manifest plus every file shipped beside it (not the downloaded src/): any change re-runs the tool (stage 4 fingerprint)."""
        digest = hashlib.sha256()
        skip = {source_lib.SRC_DIR, ".download", source_lib.PROVENANCE}
        for item in sorted(p for p in self.folder.rglob("*") if p.is_file()):
            relative = item.relative_to(self.folder)
            if relative.parts[0] in skip:
                continue
            digest.update(str(relative).encode())
            digest.update(item.read_bytes())
        return digest.hexdigest()

    def resolve(self, value):
        """A path given in the manifest, relative to the manifest's folder."""
        value = os.path.expandvars(os.path.expanduser(value))
        return str(Path(value) if os.path.isabs(value) or self.folder is None else (self.folder / value))

    # -- validation -------------------------------------------------------------------------------------------
    def check(self, files=True):
        """(problems, warnings). `files` also checks the scripts the manifest names beside it (needs a folder)."""
        problems, warnings = [], []
        files = files and self.folder is not None
        formats = self.formats
        for section, keys in self.sections.items():
            if section.startswith(OUTPUT_SECTION_PREFIX):
                fmt = section[len(OUTPUT_SECTION_PREFIX):]
                if fmt not in FORMATS or fmt == "auto":
                    problems.append(f"unknown section [{section}] (a per-format section is [output.<format>] with a format from "
                                    f"{', '.join(f for f in FORMATS if f != 'auto')})")
                    continue
                if formats and "auto" not in formats and fmt not in formats:
                    problems.append(f"[{section}] is not listed in [output] format = {', '.join(formats)}; add {fmt} there or remove the section")
                for key in keys:
                    if key not in FORMAT_KEYS:
                        problems.append(f"[{section}] unknown key '{key}' (allowed: {', '.join(sorted(FORMAT_KEYS))})")
                continue
            if section not in SCHEMA:
                problems.append(f"unknown section [{section}] (allowed: {', '.join(SCHEMA)}, and [output.<format>])")
                continue
            for key in keys:
                if key not in SCHEMA[section]:
                    problems.append(f"[{section}] unknown key '{key}' (allowed: {', '.join(sorted(SCHEMA[section]))})")
        for section, keys in REQUIRED.items():
            for key in keys:
                if not self.get(section, key):
                    problems.append(f"[{section}] {key} is required")
        if self.name and not NAME_RE.match(self.name):
            problems.append(f"[tool] name '{self.name}' must be lower-case letters, digits and _, starting with a letter")
        if TASK_ID_SEPARATOR in self.name:
            problems.append(f"[tool] name '{self.name}' must not contain '{TASK_ID_SEPARATOR}' (reserved for the per-task ids <name>{TASK_ID_SEPARATOR}<task>)")
        raw_tasks = _split_commas(self.get("tool", "task"))
        for value in raw_tasks:
            if _task(value) not in TASKS:
                problems.append(f"[tool] task must be one of {', '.join(TASKS)} ('{value}' is not; a comma list is allowed for a tool that does "
                                f"several, e.g. task = classification, binning_reconstruction)")
        if len(raw_tasks) != len({_task(t) for t in raw_tasks}):
            warnings.append("[tool] task lists the same task twice; it is counted once")
        if self.track and self.track not in TRACKS:
            problems.append(f"[tool] analysis_track must be one of {', '.join(TRACKS)}")
        lr = self.get("tool", "requires_independent_long_read_truth", "auto")
        if lr not in ("auto", "yes", "no"):
            problems.append("[tool] requires_independent_long_read_truth must be yes, no or auto")
        self._check_install(problems, warnings, files)
        mode = self.get("run", "mode")
        if mode and mode not in RUN_MODES:
            problems.append(f"[run] mode must be one of {', '.join(RUN_MODES)}")
        if mode == "command":
            command = self.get("run", "command")
            if not command:
                problems.append("[run] mode = command needs command")
            unknown = _placeholders(command) - set(PLACEHOLDERS)
            if unknown:
                problems.append(f"[run] command uses unknown placeholder(s) {', '.join('{' + u + '}' for u in sorted(unknown))}; "
                                f"available: {', '.join('{' + p + '}' for p in PLACEHOLDERS)}")
            used_inputs = _placeholders(command) & set(INPUT_PLACEHOLDERS)
            declared = set(_split(self.get("run", "requires")))
            bad = declared - set(INPUT_PLACEHOLDERS)
            if bad:
                problems.append(f"[run] requires lists unknown input(s) {', '.join(sorted(bad))}")
            missing = used_inputs - declared - {"db"}
            if missing:
                problems.append(f"[run] command uses {', '.join(sorted(missing))} but requires does not list it")
            if "db" in _placeholders(command) and not self.get("database", "path"):
                problems.append("[run] command uses {db} but [database] path is not set")
            if "src" in _placeholders(command) and self.method not in ("url", "local"):
                problems.append("[run] command uses {src} but [install] method is not url or local; set method = url (with url) or "
                                "method = local (with path)")
            if self.method in ("url", "local") and "src" not in _placeholders(command) and "tool_dir" not in _placeholders(command):
                warnings.append("[run] command does not use {src}, so the downloaded/located tool is not referenced; call it as {src}/<program>")
        if mode == "import":
            if not self.get("run", "dir"):
                problems.append("[run] mode = import needs dir (the folder holding one output per sample)")
            if "{sample}" not in self.get("run", "pattern", "{sample}.tsv"):
                problems.append("[run] pattern must contain {sample}")
        for key in ("threads", "timeout_seconds"):
            value = self.get("run", key)
            if value and not value.isdigit():
                problems.append(f"[run] {key} must be a whole number")
        self._check_output(problems, warnings, files, mode)
        uses_db = self.get("database", "uses_reference_database", "no")
        if uses_db not in ("yes", "no"):
            problems.append("[database] uses_reference_database must be yes or no")
        date = self.get("database", "release_date")
        if date and not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            problems.append("[database] release_date must be YYYY-MM-DD")
        return problems, warnings

    def _check_install(self, problems, warnings, files):
        method = self.method
        if method not in INSTALL_METHODS:
            problems.append(f"[install] method must be one of {', '.join(INSTALL_METHODS)}")
        if method == "conda" and not _split(self.get("install", "packages")):
            problems.append("[install] method = conda needs packages")
        if method == "pip" and not _split(self.get("install", "pip_packages")):
            problems.append("[install] method = pip needs pip_packages")
        if method == "script":
            script = self.get("install", "script")
            if not script or (files and not Path(self.resolve(script)).is_file()):
                problems.append("[install] method = script needs script, a file in the tool's folder")
        for key in ("max_download_mb", "download_timeout_seconds"):
            value = self.get("install", key)
            if value and not value.isdigit():
                problems.append(f"[install] {key} must be a whole number")
        if method not in ("url", "local"):
            for key in ("url", "sha256", "kind", "ref", "submodules", "path", "mode", "build_command"):
                if self.get("install", key):
                    problems.append(f"[install] {key} only applies to method = url or local (method is {method})")
        build = self.get("install", "build_command")
        unknown = _placeholders(build) - set(INSTALL_PLACEHOLDERS)
        if unknown:
            problems.append(f"[install] build_command uses unknown placeholder(s) {', '.join('{' + u + '}' for u in sorted(unknown))}; "
                            f"available: {', '.join('{' + p + '}' for p in INSTALL_PLACEHOLDERS)}")
        if method == "url":
            url = self.get("install", "url")
            problems.extend(source_lib.url_problems(url))
            kind = self.get("install", "kind", "auto")
            if kind not in SOURCE_KINDS + ("auto",):
                problems.append(f"[install] kind must be one of {', '.join(SOURCE_KINDS)} (or auto: detected from the URL)")
            if url and not source_lib.url_problems(url):
                resolved = source_lib.detect_kind(url) if kind == "auto" else kind
                if resolved == "archive" and not urllib_path(url).lower().endswith(source_lib.ARCHIVE_SUFFIXES):
                    problems.append(f"[install] kind = archive but the URL does not end in {', '.join(source_lib.ARCHIVE_SUFFIXES)}")
                if resolved == "git" and self.get("install", "sha256"):
                    problems.append("[install] sha256 does not apply to a git source; pin the commit with ref instead")
                if resolved != "git" and self.get("install", "ref"):
                    problems.append("[install] ref only applies to a git source")
                if resolved == "git" and not self.get("install", "ref"):
                    warnings.append("[install] no ref for a git source: the default branch is cloned and its commit is recorded; pin ref (tag or commit) "
                                    "for a reproducible install")
            sha = self.get("install", "sha256")
            if sha and not source_lib.SHA256_RE.match(sha):
                problems.append("[install] sha256 must be 64 hexadecimal characters")
            if not sha and (kind != "git"):
                warnings.append("[install] no sha256: the download cannot be verified, only the observed checksum is recorded. Pin it "
                                "(sha256 = <64 hex>) so a changed or tampered file is refused")
            if self.get("install", "submodules") not in ("", "yes", "no"):
                problems.append("[install] submodules must be yes or no")
        if method == "local":
            path = self.get("install", "path")
            if not path:
                problems.append("[install] method = local needs path (a file or folder on this computer)")
            elif not source_lib.local_target(path).exists():
                warnings.append(f"[install] path {path} was not found on this computer right now; installing will fail until it exists")
            mode = self.get("install", "mode", "copy")
            if mode not in LOCAL_MODES:
                problems.append(f"[install] mode must be one of {', '.join(LOCAL_MODES)}")
            elif mode == "link":
                warnings.append("[install] mode = link uses the files in place, so the tool can change under the benchmark; use mode = copy for a reproducible run")

    def _check_output(self, problems, warnings, files, mode):
        formats = self.formats
        for value in formats:
            if value not in FORMATS:
                problems.append(f"[output] format must be one of {', '.join(FORMATS)} ('{value}' is not; a comma list is allowed for several types)")
        if "auto" in formats and len(formats) > 1:
            problems.append("[output] format = auto cannot be combined with other formats; list the formats, or use auto alone")
        known = [f for f in formats if f in FORMATS and f != "auto"]
        if self.auto:
            if not _split_commas(self.get("output", "candidates")):
                problems.append("[output] format = auto needs candidates (comma-separated file or folder patterns relative to {outdir}, "
                                "e.g. candidates = contig_report.txt, plasmid_*.fasta)")
        elif self.get("output", "candidates"):
            problems.append("[output] candidates only applies to format = auto")
        for fmt in known:
            if mode == "command" and fmt in PATH_FORMATS and not self.output_get(fmt, "path"):
                where = f"[output.{fmt}]" if len(known) > 1 else "[output]"
                problems.append(f"[output] format = {fmt} needs path ({where} path = where the tool writes it, relative to {{outdir}})")
            if fmt == "contig_labels" and not self.output_get(fmt, "label_column") and not self.output_get(fmt, "score_column"):
                problems.append("[output] format = contig_labels needs label_column or score_column")
            if fmt == "adapter":
                adapter = self.output_get(fmt, "adapter")
                if not adapter or (files and not Path(self.resolve(adapter)).is_file()):
                    problems.append("[output] format = adapter needs adapter, a script in the tool's folder")
        for value in _split_commas(self.output_get("adapter", "adapter_tasks")):
            if _task(value) not in self.tasks:
                problems.append(f"[output] adapter_tasks lists '{value}', which is not one of this tool's tasks ({', '.join(self.tasks)})")
        if self.get("output", "adapter_tasks") and "adapter" not in formats and not self.auto:
            problems.append("[output] adapter_tasks only applies to format = adapter")
        for section in [None] + known + (["contig_bins", "contig_labels", "plasmid_fasta", "fasta_dir", "adapter"] if self.auto else []):
            threshold = self.output_get(section, "threshold") if section else self.get("output", "threshold")
            if threshold:
                try:
                    float(threshold)
                except ValueError:
                    problems.append("[output] threshold must be a number")
            regex = self.output_get(section, "contig_id_strip_regex") if section else self.get("output", "contig_id_strip_regex")
            if regex:
                try:
                    re.compile(regex)
                except re.error as exc:
                    problems.append(f"[output] contig_id_strip_regex is not a valid regular expression: {exc}")
        if self.tasks and formats and all(f in FORMATS for f in formats) and all(t in TASKS for t in self.tasks):
            for entry in self.derivation():
                if entry["status"] == "not_possible":
                    problems.append(f"[tool] task {entry['task']} cannot be produced from the declared output: {entry['how']}")
                elif entry["status"] == "derived" and not self.strict:
                    warnings.append(f"task {entry['task']}: {entry['how']}")
                elif entry["status"] == "derived" and "NOT a real grouping" in entry["how"]:
                    warnings.append(f"task {entry['task']}: {entry['how']}")

    # -- registry rows ----------------------------------------------------------------------------------------
    def capability_row(self, task=None):
        task = task or self.task
        lr = self.get("tool", "requires_independent_long_read_truth", "auto")
        if lr == "auto":
            lr = "yes" if self.track in ("long_read", "hybrid") else "no"
        method_class = (self.get("tool", "method_class") or
                        {"binning_reconstruction": "binning", "sequence_reassembly": "reassembly"}.get(task, "classification"))
        description = self.get("tool", "description") or f"user-supplied tool ({self.path})"
        if task != self.task:
            description += f" [{TASK_SHORT.get(task, task)} view of {self.name}: the same run, output converted]"
        return {"tool": self.task_id(task) if task in self.tasks else self.name, "method_class": method_class,
                "binning_capable": "no" if task == "classification" else "yes",
                "evaluation_task": task or "classification",
                "primary_input": ",".join(_split(self.get("run", "requires"))) or "precomputed",
                "description": description, "analysis_track": self.track,
                "requires_independent_long_read_truth": lr, "source": "user"}

    def installer_row(self, tool_id=None):
        method = self.method
        return {"tool": tool_id or self.name, "profile": self.name, "install_mode": f"user_{method}",
                "automated": "yes" if method != "none" else "planned", "runtime": self.env_name,
                "database_mode": "manual" if self.get("database", "path") else "none",
                "verify_command": self.get("install", "verify_command"),
                "notes": f"user-supplied manifest {self.path}"}

    def database_row(self, tool_id=None):
        return {"tool": tool_id or self.name, "uses_reference_database": self.get("database", "uses_reference_database", "no"),
                "database": self.get("database", "database"), "database_release_date": self.get("database", "release_date"),
                "note": self.get("database", "note") or "declared in the user tool manifest"}

    def rows(self, kind):
        """The registry rows of `kind` ('capability_row', 'installer_row', 'database_row'): one per task id."""
        if kind == "capability_row":
            return [self.capability_row(task) for _, task in self.task_ids()]
        return [getattr(self, kind)(tool_id) for tool_id, _ in self.task_ids()]

    # -- running ----------------------------------------------------------------------------------------------
    def run_spec(self, sample, inputs, outdir, threads):
        """What stage 4 needs for one sample: the mode, a missing-input reason, the rendered command or the
        imported file, and where the output will be. Every substituted value is shell-quoted."""
        mode = self.get("run", "mode")
        src = self.src_path()
        signature = self.source_signature()
        install = self.method
        if install in ("url", "local") and not _split(self.get("install", "packages")) and not _split(self.get("install", "pip_packages")):
            install = "none"   # no environment was created for it: the command runs on PATH (plus {src})
        spec = {"mode": mode, "missing": "", "command": "", "output": "", "env": self.get("run", "env") or "auto",
                "env_name": self.env_name, "install": install,
                "timeout": self.get("run", "timeout_seconds"),
                "checksum": hashlib.sha256((self.checksum() + "|" + signature).encode()).hexdigest(),
                "task_ids": " ".join(f"{i}={t}" for i, t in self.task_ids()),
                "src": str(src) if src else "", "source": json.dumps(self.source_summary(), sort_keys=True)}
        values = dict(inputs)
        values.update({"outdir": outdir, "threads": str(self.get("run", "threads") or threads), "sample": sample,
                       "tool_dir": str(self.folder), "db": os.path.expandvars(self.get("database", "path")),
                       "src": str(src) if src else ""})
        if mode == "import":
            folder = Path(os.path.expandvars(os.path.expanduser(self.get("run", "dir"))))
            if self.multi_output:
                pattern = self.get("run", "pattern").replace("{sample}", sample)
                spec["output"] = str(folder / pattern) if pattern else str(folder)
            else:
                pattern = self.get("run", "pattern", "{sample}.tsv").replace("{sample}", sample)
                spec["output"] = str(folder / pattern)
            if not Path(spec["output"]).exists():
                spec["missing"] = f"output not found: {spec['output']}"
            return spec
        for need in _split(self.get("run", "requires")):
            value = values.get(need, "")
            if not value or not Path(value).exists():
                spec["missing"] = f"input {need} unavailable for this sample ({value or 'not produced'})"
                return spec
        if "{db}" in self.get("run", "command") and not Path(values["db"]).exists():
            spec["missing"] = f"database not found: {values['db'] or '[database] path unset'}"
            return spec
        if "{src}" in self.get("run", "command") and (src is None or not Path(src).exists()):
            spec["missing"] = (f"tool source not installed ({src}): run `plasbench install-tools {self.name}`; the manifest says it comes "
                               f"from {self.get('install', 'url') or self.get('install', 'path')}")
            return spec
        # A command continued over several manifest lines is one shell command line.
        template = " ".join(line.strip() for line in self.get("run", "command").splitlines() if line.strip())
        spec["command"] = re.sub(r"\{([a-z_0-9]+)\}", lambda m: shlex.quote(values.get(m.group(1), "")), template)
        if self.multi_output:
            spec["output"] = outdir   # the converter finds each output under it (per-format path, or candidates)
        else:
            fmt = (self.formats or [""])[0]
            path = self.output_get(fmt, "path")
            if fmt in ("fasta_dir",) and not path:
                spec["output"] = outdir
            else:
                spec["output"] = str(Path(outdir) / path.replace("{sample}", sample)) if path else outdir
        return spec

    def _install_env_steps(self, env):
        steps = []
        if _split(self.get("install", "packages")):
            channels = _split(self.get("install", "channels")) or ["conda-forge", "bioconda"]
            argv = ["{CONDA}", "create", "-y", "-n", env]
            for ch in channels:
                argv += ["-c", ch]
            steps.append(argv + _split(self.get("install", "packages")))
        elif _split(self.get("install", "pip_packages")):
            python = self.get("install", "python") or "3.10"
            steps.append(["{CONDA}", "create", "-y", "-n", env, "-c", "conda-forge", f"python={python}", "pip"])
        if _split(self.get("install", "pip_packages")):
            steps.append(["{CONDA}", "run", "-n", env, "python", "-m", "pip", "install"] + _split(self.get("install", "pip_packages")))
        return steps

    def _render_install(self, text):
        src = self.src_path()
        values = {"src": str(src) if src else "", "tool_dir": str(self.folder), "threads": "4"}
        return re.sub(r"\{(src|tool_dir|threads)\}", lambda m: shlex.quote(values[m.group(1)]), text)

    def install_plan(self):
        """The commands env/install_tools.sh runs, one per line (argv tab-separated), then the verification."""
        method = self.method
        env = self.env_name
        steps = [["ENV", env]]   # the environment the tool runs in; [install] method = none leaves it unused
        if method in ("conda", "pip"):
            steps += self._install_env_steps(env)
        elif method == "script":
            steps.append(["bash", self.resolve(self.get("install", "script")), env])
        elif method in ("url", "local"):
            steps += self._install_env_steps(env)
            steps.append(["python3", str(Path(__file__).resolve()), "fetch", self.name])
            build = self.get("install", "build_command")
            if build:
                steps.append(["BUILD", self._render_install(build), str(self.src_dir())])
        verify = self.get("install", "verify_command")
        if verify:
            steps.append(["VERIFY", self._render_install(verify) if method in ("url", "local") else verify])
        return steps

    def install_source(self, fetch=None, run=None, log=print):
        """Download or locate the tool's source now (method url or local). Returns the provenance record."""
        if self.method == "url":
            spec = {"name": self.name, "url": self.get("install", "url"), "sha256": self.get("install", "sha256"),
                    "kind": self.get("install", "kind", "auto"), "ref": self.get("install", "ref"),
                    "submodules": self.get("install", "submodules"), "build_command": self.get("install", "build_command"),
                    "max_download_mb": self.get("install", "max_download_mb"),
                    "timeout": self.get("install", "download_timeout_seconds")}
            kwargs = {key: value for key, value in (("fetch", fetch), ("run", run)) if value}
            return source_lib.install_url(spec, self.folder, log=log, **kwargs)
        if self.method == "local":
            spec = {"name": self.name, "path": self.get("install", "path"), "mode": self.get("install", "mode", "copy"),
                    "build_command": self.get("install", "build_command"), "max_download_mb": self.get("install", "max_download_mb")}
            return source_lib.install_local(spec, self.folder, log=log)
        raise source_lib.SourceError(f"{self.name}: [install] method = {self.method} has no source to fetch (only url and local do)")

    def run_record(self):
        """For run_manifest.json `user_tools`: tasks, ids, source (method, url/path, sha256, size) and the declared output types."""
        recorded = source_lib.last_record(self.folder) if self.folder else {}
        source = self.source_summary()
        source.update({k: recorded[k] for k in ("final_url", "size", "sha256", "tree_sha256", "commit", "local_path", "downloaded_utc",
                                                 "sha256_verified") if k in recorded})
        if recorded.get("sha256") and "sha256_observed" not in source:
            source["sha256_observed"] = recorded["sha256"]
        source["installed"] = bool(recorded)
        return {"tasks": self.tasks, "task_ids": dict(self.task_ids()), "source": source,
                "output_formats": self.formats, "outputs": self.output_summary(),
                "derivation": [{k: e[k] for k in ("task", "status", "how")} for e in self.derivation()]}


def urllib_path(url):
    from urllib.parse import urlparse
    return urlparse(url).path


class UserTool(Manifest):
    """One parsed, validated manifest read from a file."""

    def __init__(self, path):
        path = Path(path).resolve()
        parser = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=("#", ";"))
        parser.optionxform = str.lower
        try:
            read = parser.read(path, encoding="utf-8")
        except configparser.Error as exc:
            raise ManifestError(f"{path}: not a valid INI file: {exc}") from exc
        if not read:
            raise ManifestError(f"{path}: cannot be read")
        super().__init__({name: dict(parser.items(name)) for name in parser.sections()}, path.parent, path)
        problems, self.warnings = self.check(files=True)
        if problems:
            raise ManifestError(f"{path}:\n  - " + "\n  - ".join(problems))


# -- functions for a program (the window's form) -----------------------------------------------------------------------
def parse_text(text):
    """Manifest text -> {section: {key: value}} (keys lower-cased). Pure: no file is read or written. Raises ManifestError
    for text that is not an INI file."""
    parser = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=("#", ";"))
    parser.optionxform = str.lower
    try:
        parser.read_string(text)
    except configparser.Error as exc:
        raise ManifestError(f"not a valid INI file: {exc}") from exc
    return {name: dict(parser.items(name)) for name in parser.sections()}


def validate_text(text, folder=None):
    """Check manifest text without touching the disk (no download, no command). Returns
    {"ok", "problems", "warnings", "tasks": [{"task","id","display_name","status","how"}], "source", "outputs"}.
    Files the manifest names beside itself (script, adapter) are only checked when `folder` is given."""
    empty = {"ok": False, "problems": [], "warnings": [], "tasks": [], "source": {}, "outputs": []}
    try:
        manifest = Manifest(parse_text(text), folder)
    except ManifestError as exc:
        return dict(empty, problems=[str(exc)])
    problems, warnings = manifest.check(files=folder is not None)
    if manifest.name in builtin_tools():
        problems.append(f"[tool] name '{manifest.name}' is a built-in PlasBench tool; choose another name")
    if folder is None:
        for key, what in (("script", "[install] script"),):
            if manifest.get("install", key):
                warnings.append(f"{what} = {manifest.get('install', key)} must be saved beside the manifest")
        if manifest.get("output", "adapter") or manifest.get("output.adapter", "adapter"):
            warnings.append("[output] adapter must be saved beside the manifest")
    tasks = []
    if manifest.tasks and manifest.formats and all(f in FORMATS for f in manifest.formats) and all(t in TASKS for t in manifest.tasks):
        ids = dict((t, i) for i, t in manifest.task_ids())
        tasks = [dict(entry, id=ids.get(entry["task"], ""), display_name=manifest.task_display(entry["task"]))
                 for entry in manifest.derivation()]
    return {"ok": not problems, "problems": problems, "warnings": warnings, "tasks": tasks,
            "source": manifest.source_summary(), "outputs": manifest.output_summary()}


# -- discovery -----------------------------------------------------------------------------------------------------------
def discover(paths=None, strict=False):
    """name -> UserTool. A broken manifest is reported on stderr and skipped (or raised with strict=True); a name
    that a built-in or an earlier folder on the search path already uses is rejected."""
    tools, errors = {}, []
    if disabled():
        return tools
    builtins = builtin_tools()
    for base in (paths or search_path()):
        if not base.is_dir():
            continue
        for folder in sorted(p for p in base.iterdir() if p.is_dir()):
            manifest = folder / MANIFEST
            if not manifest.is_file():
                continue
            try:
                tool = UserTool(manifest)
            except ManifestError as exc:
                errors.append(str(exc))
                continue
            if tool.name in builtins:
                errors.append(f"{manifest}: name '{tool.name}' is a built-in PlasBench tool; choose another name")
            elif tool.name in tools:
                errors.append(f"{manifest}: '{tool.name}' is already defined by {tools[tool.name].path} (earlier on the search path)")
            else:
                tools[tool.name] = tool
    if errors:
        if strict:
            raise ManifestError("\n".join(errors))
        for message in errors:
            print(f"[user tools] WARNING: skipped {message}", file=sys.stderr)
    return tools


_CACHE = {}


def cached():
    """Discovered tools, once per process (registry readers call this repeatedly)."""
    key = (os.environ.get("PLASBENCH_TOOLS_PATH", ""), disabled())
    if key not in _CACHE:
        _CACHE[key] = discover()
    return _CACHE[key]


def by_id(tools=None):
    """tool id -> (UserTool, task): <name> and <name>__<task> for every task of every tool."""
    out = {}
    for tool in (cached() if tools is None else tools).values():
        for tool_id, task in tool.task_ids():
            out[tool_id] = (tool, task)
    return out


def resolve_id(name, tools=None):
    """The (UserTool, task) a registry id names, or (None, None)."""
    return by_id(tools).get(name, (None, None))


BUILTIN_REGISTRIES = {"tool_capabilities.tsv": "capability_row", "tool_installers.tsv": "installer_row",
                      "tool_database_releases.tsv": "database_row"}


def merge_rows(path, rows):
    """Registry readers call this with the rows they read. Only PlasBench's own registry files (config/<name>)
    gain the user tools' rows (one per task of each tool); a test fixture or any other file is returned unchanged.
    Accepts a list of dicts or a dict tool -> row and returns the same shape."""
    try:
        path = Path(path).resolve()
    except (TypeError, OSError):
        return rows
    kind = BUILTIN_REGISTRIES.get(path.name)
    if kind is None or path.parent != (ROOT / "config").resolve():
        return rows
    extra = [row for _, tool in sorted(cached().items()) for row in tool.rows(kind)]
    if isinstance(rows, dict):
        merged = dict(rows)
        for row in extra:
            merged.setdefault(row["tool"], row)
        return merged
    known = {r.get("tool") for r in rows}
    return list(rows) + [r for r in extra if r["tool"] not in known]


def display_name(tool):
    """Reader-facing name of a registry id; a multi-task tool's rows carry the task: 'My Tool (classification)'."""
    found, task = resolve_id(tool)
    return found.task_display(task) if found else None


def enabled_names(selection):
    """USER_TOOLS / --tool: 'all', or a comma/space list of tool names (a per-task id <name>__<task> selects its tool).
    Unknown names are an error (a typo must not silently run nothing). Returns tool names, each once."""
    tools = cached()
    wanted = _split(selection)
    if not wanted:
        return []
    if wanted == ["all"]:
        return sorted(tools)
    ids = by_id(tools)
    unknown = [w for w in wanted if w not in ids]
    if unknown:
        raise ManifestError(f"unknown user tool(s): {', '.join(unknown)}. Installed: {', '.join(sorted(tools)) or 'none'} "
                            f"(see `plasbench tools list`)")
    out = []
    for w in wanted:
        name = ids[w][0].name
        if name not in out:
            out.append(name)
    return out


def chosen_outputs(results_dir, tool):
    """{tool id: {output format: samples}} from the per-sample provenance files the converter wrote."""
    summary = {}
    base = Path(results_dir)
    if not base.is_dir():
        return summary
    for tool_id, _ in tool.task_ids():
        counts = {}
        for path in base.glob(f"*/pred_{tool_id}.{tool_id}.provenance.json"):
            try:
                fmt = json.loads(path.read_text(encoding="utf-8")).get("chosen_format") or "unknown"
            except (OSError, ValueError):
                continue
            counts[fmt] = counts.get(fmt, 0) + 1
        summary[tool_id] = counts
    return summary


# -- scaffolding -----------------------------------------------------------------------------------------------------------
SOURCES = ("installed", "conda", "pip", "url", "local", "script")

FORMAT_TEMPLATES = {
    "contig_bins": ("path = bins.tsv                      # relative to {{outdir}}\n"
                    "delimiter = tab\nheader = yes\ncontig_column = contig               # column name, or 1-based number\n"
                    "bin_column = bin\n# bin_none_values = -, NA              # bin cells that mean 'in no bin' (a chromosome contig)\n"),
    "contig_labels": ("path = labels.tsv                    # relative to {{outdir}}\n"
                      "delimiter = tab\nheader = yes\ncontig_column = contig\n"
                      "label_column = prediction            # plasmid_values = plasmid, 1   (cells that mean plasmid)\n"
                      "score_column = probability           # optional, in [0, 1]; adds the PR curve. threshold = 0.5 when there is no label_column\n"),
    "plasmid_fasta": "path = plasmids.fasta                # relative to {{outdir}}; each record is one predicted plasmid\n",
    "fasta_dir": "path = plasmids                       # a folder; each FASTA file in it is one predicted plasmid\nfasta_glob = *.fasta, *.fa\n",
    "adapter": ("path = result.json                    # the tool's own output; passed to the adapter\n"
               "adapter = adapt.py                   # called as: adapt.py <tool output> <assembly contigs> <pred_<tool>.plasmid.fasta>, once per task\n"
               "# adapter_tasks = classification, binning_reconstruction   # tasks whose native files the adapter writes (PLASBENCH_TASK says which)\n"),
}

TEMPLATE_HEAD = """# PlasBench user tool manifest. Reference: docs/ADDING_TOOLS.md; examples: tools.d/examples/.
[tool]
name = {name}
display_name = {display}
# What the tool does. One value, or a comma list for a tool that does several (the command still runs ONCE per sample; the first
# listed is the primary task, and each task appears in its own leaderboard as '<display name> (<task>)'):
#   binning_reconstruction  groups contigs into plasmids (bins)        sequence_reassembly  writes predicted plasmid sequence (FASTA)
#   classification          labels contigs plasmid / chromosome
# What each task needs from the output is in the derivation table of docs/ADDING_TOOLS.md; plasbench tools validate says exactly what is missing.
task = {task}
analysis_track = short_read          # short_read | long_read | hybrid
description = What the tool does, in one line.
citation =
version_command = mytool --version

[install]
"""

INSTALL_TEMPLATES = {
    "installed": ("method = none                        # already on PATH: nothing to install\n"),
    "conda": ("method = conda                       # conda | pip | script | url | local | none (already on PATH)\n"
              "packages = mytool\nchannels = conda-forge, bioconda\nverify_command = mytool --help\n"),
    "pip": "method = pip\npip_packages = mytool==1.0\npython = 3.10\nverify_command = mytool --help\n",
    "script": ("method = script                      # an install script shipped beside this manifest\n"
               "script = install.sh                  # called as: install.sh <environment name>\nverify_command = mytool --help\n"),
    "url": ("method = url                         # download it: https ONLY (http, ftp and file are refused); nothing is downloaded until you install\n"
            "url = {url}\n"
            "sha256 = {sha256}\n"
            "# sha256 pins the exact file: a different download is refused. Without it a warning is shown and the observed checksum is recorded.\n"
            "# kind = archive                     # archive (.zip .tar.gz .tgz .tar.xz .tar.bz2) | git | file; detected from the URL when left out\n"
            "# ref = v1.2.0                       # git only: tag, branch or commit (no submodules unless submodules = yes)\n"
            "# build_command = make -j 4          # optional; runs inside the downloaded folder (use {{src}} for it)\n"
            "# max_download_mb = 2048             # refuse a larger download\n"
            "verify_command = {{src}}/mytool --help   # runs after install; {{src}} is the downloaded folder\n"),
    "local": ("method = local                       # the tool is already on this computer\n"
              "path = {local_path}\n"
              "# A file or a folder; '~' and Windows paths (C:\\Tools\\mytool) work. mode = copy (the default) keeps a copy and records its\n"
              "# checksum, so the benchmark is reproducible; mode = link uses it in place (it can change under the benchmark).\n"
              "mode = copy\n"
              "# build_command = make                # optional; runs inside the folder (use {{src}} for it)\n"
              "verify_command = {{src}}/mytool --help\n"),
}

TEMPLATE_TAIL = """
[database]
uses_reference_database = no         # yes if it searches a plasmid database (enables the leakage check)
release_date =                       # YYYY-MM-DD of that database
path =                               # used as {{db}} in the command

[run]
mode = command                       # command (PlasBench runs it) | import (you ran it already)
# Placeholders: {{contigs}} {{graph}} {{reads_1}} {{reads_2}} {{long_reads}} {{outdir}} {{threads}} {{sample}} {{db}} {{tool_dir}}
# and {{src}} = the downloaded or located tool (method = url or local).
command = {command}
requires = contigs                   # inputs the command needs; a sample without one is skipped with the reason
# mode = import instead: dir = /path/to/outputs   pattern = {{sample}}.tsv

[output]
"""

AUTO_OUTPUT = """# format = auto: PlasBench recognises each candidate by its CONTENT (a FASTA file = plasmid_fasta; a folder of FASTA files =
# fasta_dir; a table with a contig column and a bin/cluster column = contig_bins; with a label or probability column =
# contig_labels) and uses, per task, the best one: binning <- contig_bins, then contig_labels; classification <- contig_labels,
# then contig_bins; reassembly <- plasmid_fasta / fasta_dir. Two candidates that could serve the same task equally, or nothing
# recognisable, is an error that lists what was seen, never a guess. The choice is recorded for every sample.
format = auto
candidates = contig_report.txt, plasmid_*.fasta      # files or folders, relative to {{outdir}}
# Optional hints that win over detection: [output.contig_bins] contig_column = ..., [output.contig_labels] plasmid_values = ...
# contig_id_from = first_token       # keep the first word of the tool's contig ids
# contig_id_strip_regex = _length_.*$
"""


def _template(name, display, tasks, source, url, sha256, local_path, output_format):
    out_formats = [f for f in _split_commas(output_format) if f]
    command = "mytool --input {contigs} --out {outdir} --threads {threads}"
    if source in ("url", "local"):
        command = "{src}/mytool --input {contigs} --out {outdir} --threads {threads}"
    text = TEMPLATE_HEAD.format(name=name, display=display, task=", ".join(tasks))
    text += INSTALL_TEMPLATES[source].format(url=url or "https://example.org/mytool-1.0.tar.gz", sha256=sha256 or "",
                                             local_path=local_path or "~/tools/mytool")
    text += TEMPLATE_TAIL.format(command=command)
    if out_formats == ["auto"]:
        text += AUTO_OUTPUT.replace("{{outdir}}", "{outdir}")
    elif len(out_formats) <= 1:
        fmt = (out_formats or ["contig_bins"])[0]
        text += (f"format = {fmt}                 # contig_bins | contig_labels | plasmid_fasta | fasta_dir | adapter | auto; "
                 f"a comma list for several types (then one [output.<format>] section each)\n"
                 + FORMAT_TEMPLATES[fmt].replace("{{outdir}}", "{outdir}")
                 + ("# contig_id_from = first_token       # keep the first word of the tool's contig ids\n"
                    "# contig_id_strip_regex = _length_.*$\n" if fmt in ("contig_bins", "contig_labels") else ""))
    else:
        text += (f"format = {', '.join(out_formats)}   # several output types: each has its own [output.<format>] section below;\n"
                 "# for each task PlasBench uses the best one it can (see the derivation table in docs/ADDING_TOOLS.md)\n")
        for fmt in out_formats:
            text += f"\n[output.{fmt}]\n" + FORMAT_TEMPLATES[fmt].replace("{{outdir}}", "{outdir}")
    return text


def scaffold(name, dest, tasks=None, source="conda", url="", sha256="", local_path="", output_format=""):
    if not NAME_RE.match(name):
        raise ManifestError(f"name '{name}' must be lower-case letters, digits and _, starting with a letter")
    if TASK_ID_SEPARATOR in name:
        raise ManifestError(f"name '{name}' must not contain '{TASK_ID_SEPARATOR}'")
    if name in builtin_tools():
        raise ManifestError(f"'{name}' is a built-in PlasBench tool; choose another name")
    tasks = [_task(t) for t in (tasks if isinstance(tasks, (list, tuple)) else _split_commas(tasks or "")) if t] or ["binning_reconstruction"]
    for task in tasks:
        if task not in TASKS:
            raise ManifestError(f"task '{task}' must be one of {', '.join(TASKS)}")
    if source not in SOURCES:
        raise ManifestError(f"source '{source}' must be one of {', '.join(SOURCES)}")
    problems = source_lib.url_problems(url) if (source == "url" and url) else []
    if problems:
        raise ManifestError("; ".join(problems))
    formats = [f.strip() for f in _split_commas(output_format)]
    for fmt in formats:
        if fmt not in FORMATS:
            raise ManifestError(f"output format '{fmt}' must be one of {', '.join(FORMATS)} (a comma list, or auto)")
    if "auto" in formats and len(formats) > 1:
        raise ManifestError("--output-format auto cannot be combined with other formats")
    if not formats:   # the default output covers what the tasks need
        formats = ["contig_bins"] if "binning_reconstruction" in tasks else ["contig_labels"] if "classification" in tasks else []
        if "sequence_reassembly" in tasks:
            formats.append("plasmid_fasta")
    folder = Path(dest).expanduser() / name
    if (folder / MANIFEST).exists():
        raise ManifestError(f"{folder / MANIFEST} already exists")
    folder.mkdir(parents=True, exist_ok=True)
    display = name.replace("_", " ").title()
    text = _template(name, display, tasks, source, url, sha256, local_path, ",".join(formats))
    (folder / MANIFEST).write_text(text, encoding="utf-8", newline="\n")
    if source == "script" and not (folder / "install.sh").exists():
        (folder / "install.sh").write_text("#!/usr/bin/env bash\n# Called as: install.sh <environment name>\nset -euo pipefail\n"
                                           "echo \"install $1 here\"\n", encoding="utf-8", newline="\n")
    if "adapter" in formats and not (folder / "adapt.py").exists():
        (folder / "adapt.py").write_text("#!/usr/bin/env python3\n\"\"\"Called as: adapt.py <tool output> <assembly contigs> <out fasta>.\n"
                                         "Write the predicted plasmid FASTA to <out fasta> (and bins.tsv / scores.tsv beside it, see adapters/).\n"
                                         "PLASBENCH_TASK names the task being converted.\"\"\"\nimport sys\n", encoding="utf-8", newline="\n")
    return folder / MANIFEST


def add(source, dest):
    """Copy a tool folder (or a lone manifest) onto the user search path after validating it."""
    source = Path(source).expanduser().resolve()
    manifest = source if source.is_file() else source / MANIFEST
    tool = UserTool(manifest)
    if tool.name in builtin_tools():
        raise ManifestError(f"'{tool.name}' is a built-in PlasBench tool; rename it in [tool] name")
    target = Path(dest).expanduser() / tool.name
    if target.exists():
        shutil.rmtree(target)
    if source.is_file():
        target.mkdir(parents=True)
        shutil.copy2(manifest, target / MANIFEST)
    else:
        shutil.copytree(source, target)
    return target


def print_validation(tool):
    print(f"ok  {tool.name}  ({tool.path})")
    ids = dict((t, i) for i, t in tool.task_ids())
    for entry in tool.derivation():
        print(f"    task {entry['task']} [{ids[entry['task']]}]: {entry['status']} - {entry['how']}")
    source = tool.source_summary()
    detail = {"url": f"{source.get('url')} ({source.get('kind')}, sha256 {'pinned' if source.get('sha256_pinned') else 'NOT pinned'})",
              "local": f"{source.get('path')} ({source.get('mode')})"}.get(source["method"], "")
    print(f"    source: {source['method']}{' - ' + detail if detail else ''}: {source['description']}")
    print("    output: " + "; ".join(f"{o['format']}" + (f" {o['path']}" if o.get("path") else "")
                                      + (f" {', '.join(o['candidates'])}" if o.get("candidates") else "") for o in tool.output_summary()))
    for warning in tool.warnings:
        print(f"    warning: {warning}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="every user tool PlasBench can see")
    v = sub.add_parser("validate", help="check manifests; exit 1 on any problem")
    v.add_argument("name", nargs="?")
    s = sub.add_parser("show", help="one tool's manifest, as PlasBench reads it")
    s.add_argument("name")
    sub.add_parser("dump", help="capability rows (tab-separated) for scripts/lib.sh")
    n = sub.add_parser("names", help="names selected by a USER_TOOLS value")
    n.add_argument("--enabled", default="all")
    r = sub.add_parser("run-spec", help="key<TAB>value lines stage 4 runs a tool from")
    r.add_argument("name")
    r.add_argument("--sample", required=True)
    for key in INPUT_PLACEHOLDERS[:-1]:
        r.add_argument("--" + key.replace("_", "-"), default="")
    r.add_argument("--outdir", required=True)
    r.add_argument("--threads", default="1")
    i = sub.add_parser("install-plan", help="install steps for env/install_tools.sh")
    i.add_argument("name")
    t = sub.add_parser("task-ids", help="the registry ids of a tool, one per task (<name>, <name>__<task>)")
    t.add_argument("name")
    f = sub.add_parser("fetch", help="download (url) or locate (local) a tool's source now; plasbench install-tools runs this")
    f.add_argument("name")
    c = sub.add_parser("new", help="write a commented manifest to fill in")
    c.add_argument("name")
    c.add_argument("--dir", default=str(Path.home() / ".plasbench" / "tools"))
    c.add_argument("--task", default="binning_reconstruction", help="one task or a comma list: " + ", ".join(TASKS))
    c.add_argument("--source", default="conda", choices=SOURCES, help="where the tool comes from (installed = already on PATH)")
    c.add_argument("--url", default="", help="with --source url: an https URL (archive, git repository or file)")
    c.add_argument("--sha256", default="", help="with --source url: the file's sha256")
    c.add_argument("--local-path", default="", help="with --source local: a file or folder on this computer")
    c.add_argument("--output-format", default="", help="one format, a comma list, or auto: " + ", ".join(FORMATS))
    a = sub.add_parser("add", help="validate a tool folder and copy it onto the search path")
    a.add_argument("path")
    a.add_argument("--dest", default=str(Path.home() / ".plasbench" / "tools"))
    args = parser.parse_args(argv)

    try:
        if args.command == "new":
            made = scaffold(args.name, args.dir, args.task, args.source, args.url, args.sha256, args.local_path, args.output_format)
            print(f"Wrote {made}\nEdit it, then: plasbench tools validate {args.name}")
            return 0
        if args.command == "add":
            target = add(args.path, args.dest)
            print(f"Added {target}\nInstall it with: plasbench install-tools {UserTool(target / MANIFEST).name}")
            return 0
        if args.command == "validate":
            tools = discover(strict=True)
            if args.name and args.name not in tools:
                raise ManifestError(f"no user tool named '{args.name}' on the search path: "
                                    + ", ".join(str(p) for p in search_path()))
            for name in ([args.name] if args.name else sorted(tools)):
                print_validation(tools[name])
            if not tools:
                print("no user tools found on: " + ", ".join(str(p) for p in search_path()))
            return 0
        tools = discover()
        if args.command == "list":
            print("tool\tdisplay_name\ttask\ttrack\tmode\tformat\tinstall\tmanifest")
            for name, tool in sorted(tools.items()):
                print("\t".join((name, tool.display_name, ",".join(tool.tasks), tool.track, tool.get("run", "mode"),
                                 ",".join(tool.formats), tool.method, str(tool.path))))
            return 0
        if args.command == "dump":
            for name, tool in sorted(tools.items()):
                for row in tool.rows("capability_row"):
                    print("\t".join((row["tool"], row["binning_capable"], row["analysis_track"],
                                     row["requires_independent_long_read_truth"])))
            return 0
        if args.command == "names":
            print("\n".join(enabled_names(args.enabled)))
            return 0
        tool, _ = resolve_id(args.name, tools)
        if tool is None:
            raise ManifestError(f"no user tool named '{args.name}' (see `plasbench tools list`)")
        if args.command == "show":
            for section, keys in tool.sections.items():
                print(f"[{section}]")
                for key, value in keys.items():
                    print(f"{key} = {value}")
                print()
            return 0
        if args.command == "run-spec":
            inputs = {k: getattr(args, k) for k in INPUT_PLACEHOLDERS[:-1]}
            for key, value in tool.run_spec(args.sample, inputs, args.outdir, args.threads).items():
                print(f"{key}\t{value}")
            return 0
        if args.command == "install-plan":
            for step in tool.install_plan():
                print("\t".join(step))
            return 0
        if args.command == "task-ids":
            print("\n".join(i for i, _ in tool.task_ids()))
            return 0
        if args.command == "fetch":
            entry = tool.install_source(log=lambda m: print(m, file=sys.stderr))
            print(f"installed source for {tool.name}: {entry.get('src')} "
                  f"(sha256 {entry.get('sha256') or entry.get('commit') or 'n/a'}; recorded in {tool.folder / source_lib.PROVENANCE})")
            return 0
    except (ManifestError, source_lib.SourceError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
