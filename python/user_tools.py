#!/usr/bin/env python3
"""User-added tools: declare a plasmid tool in one manifest and PlasBench installs, runs, scores and reports it.

A user tool is a folder holding ``plasbench-tool.ini`` (and, optionally, the scripts it names). PlasBench finds it on a
search path, first match wins:

    $PLASBENCH_TOOLS_PATH   (os.pathsep-separated folders; each holds one sub-folder per tool)
    ~/.plasbench/tools/
    <repo>/tools.d/

Set PLASBENCH_USER_TOOLS=off to ignore every user tool (built-ins are unaffected). The manifest maps PlasBench's own
inputs onto the tool's command line ([run] command with placeholders) and the tool's output onto PlasBench's prediction
files ([output]); docs/ADDING_TOOLS.md is the reference and tools.d/examples/ holds one worked manifest per format.

Command-line use (scripts/04_run_tools.sh, env/install_tools.sh and `plasbench tools` call it):

    user_tools.py list | validate [NAME] | show NAME | dump | names [--enabled LIST]
    user_tools.py run-spec NAME --sample S --contigs F --graph F --reads-1 F --reads-2 F --long-reads F --outdir D --threads N
    user_tools.py install-plan NAME
    user_tools.py new NAME [--dir D]   |   add PATH [--dest D]
"""

import argparse
import configparser
import csv
import hashlib
import os
import re
import shlex
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = "plasbench-tool.ini"
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
TASKS = ("reconstruction", "classification")
TRACKS = ("short_read", "long_read", "hybrid")
RUN_MODES = ("command", "import")
FORMATS = ("contig_bins", "contig_labels", "plasmid_fasta", "fasta_dir", "adapter")
INSTALL_METHODS = ("conda", "pip", "script", "none")
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
}
INPUT_PLACEHOLDERS = ("contigs", "graph", "reads_1", "reads_2", "long_reads", "db")
# Keys each section accepts; anything else is a typo and is reported, never silently ignored.
SCHEMA = {
    "tool": {"name", "display_name", "task", "analysis_track", "method_class", "description", "citation", "url",
             "version_command", "requires_independent_long_read_truth"},
    "install": {"method", "packages", "channels", "pip_packages", "python", "script", "env_name", "verify_command"},
    "database": {"uses_reference_database", "database", "release_date", "path", "note"},
    "run": {"mode", "command", "requires", "threads", "timeout_seconds", "dir", "pattern", "env"},
    "output": {"format", "path", "delimiter", "header", "comment", "contig_column", "bin_column", "label_column",
               "plasmid_values", "score_column", "threshold", "contig_id_strip_regex", "contig_id_from", "adapter",
               "fasta_glob"},
}
REQUIRED = {"tool": ("name", "task", "analysis_track"), "run": ("mode",), "output": ("format",)}


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


def _placeholders(template):
    return set(re.findall(r"\{([a-z_0-9]+)\}", template or ""))


class UserTool:
    """One parsed, validated manifest."""

    def __init__(self, path):
        self.path = Path(path).resolve()
        self.folder = self.path.parent
        parser = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=("#", ";"))
        parser.optionxform = str.lower
        try:
            read = parser.read(self.path, encoding="utf-8")
        except configparser.Error as exc:
            raise ManifestError(f"{self.path}: not a valid INI file: {exc}") from exc
        if not read:
            raise ManifestError(f"{self.path}: cannot be read")
        self.sections = {name: dict(parser.items(name)) for name in parser.sections()}
        self._validate()

    # -- convenience ------------------------------------------------------------------------------------------
    def get(self, section, key, default=""):
        return (self.sections.get(section, {}).get(key) or default).strip()

    @property
    def name(self):
        return self.get("tool", "name")

    @property
    def task(self):
        return self.get("tool", "task")

    @property
    def track(self):
        return self.get("tool", "analysis_track")

    @property
    def display_name(self):
        return self.get("tool", "display_name") or self.name

    @property
    def env_name(self):
        return self.get("install", "env_name") or f"plasbench-{self.name}"

    def checksum(self):
        """Manifest plus every file shipped beside it: any change re-runs the tool (stage 4 fingerprint)."""
        digest = hashlib.sha256()
        for item in sorted(p for p in self.folder.rglob("*") if p.is_file()):
            digest.update(str(item.relative_to(self.folder)).encode())
            digest.update(item.read_bytes())
        return digest.hexdigest()

    def resolve(self, value):
        """A path given in the manifest, relative to the manifest's folder."""
        value = os.path.expandvars(os.path.expanduser(value))
        return str(Path(value) if os.path.isabs(value) else (self.folder / value))

    # -- validation -------------------------------------------------------------------------------------------
    def _validate(self):
        where = str(self.path)
        problems = []
        for section, keys in self.sections.items():
            if section not in SCHEMA:
                problems.append(f"unknown section [{section}] (allowed: {', '.join(SCHEMA)})")
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
        if self.task and self.task not in TASKS:
            problems.append(f"[tool] task must be one of {', '.join(TASKS)}")
        if self.track and self.track not in TRACKS:
            problems.append(f"[tool] analysis_track must be one of {', '.join(TRACKS)}")
        lr = self.get("tool", "requires_independent_long_read_truth", "auto")
        if lr not in ("auto", "yes", "no"):
            problems.append("[tool] requires_independent_long_read_truth must be yes, no or auto")
        method = self.get("install", "method", "none")
        if method not in INSTALL_METHODS:
            problems.append(f"[install] method must be one of {', '.join(INSTALL_METHODS)}")
        if method == "conda" and not _split(self.get("install", "packages")):
            problems.append("[install] method = conda needs packages")
        if method == "pip" and not _split(self.get("install", "pip_packages")):
            problems.append("[install] method = pip needs pip_packages")
        if method == "script":
            script = self.get("install", "script")
            if not script or not Path(self.resolve(script)).is_file():
                problems.append("[install] method = script needs script, a file in the tool's folder")
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
        if mode == "import":
            if not self.get("run", "dir"):
                problems.append("[run] mode = import needs dir (the folder holding one output per sample)")
            if "{sample}" not in self.get("run", "pattern", "{sample}.tsv"):
                problems.append("[run] pattern must contain {sample}")
        for key in ("threads", "timeout_seconds"):
            value = self.get("run", key)
            if value and not value.isdigit():
                problems.append(f"[run] {key} must be a whole number")
        fmt = self.get("output", "format")
        if fmt and fmt not in FORMATS:
            problems.append(f"[output] format must be one of {', '.join(FORMATS)}")
        if fmt == "contig_bins" and self.task == "classification":
            problems.append("[output] format = contig_bins groups contigs into plasmids: set [tool] task = reconstruction "
                            "(or use contig_labels for a classifier)")
        if fmt in ("contig_bins", "contig_labels", "plasmid_fasta", "adapter") and mode == "command" and not self.get("output", "path"):
            problems.append(f"[output] format = {fmt} needs path (where the tool writes it, relative to {{outdir}})")
        if fmt == "contig_labels" and not self.get("output", "label_column") and not self.get("output", "score_column"):
            problems.append("[output] format = contig_labels needs label_column or score_column")
        if fmt == "adapter":
            adapter = self.get("output", "adapter")
            if not adapter or not Path(self.resolve(adapter)).is_file():
                problems.append("[output] format = adapter needs adapter, a script in the tool's folder")
        threshold = self.get("output", "threshold")
        if threshold:
            try:
                float(threshold)
            except ValueError:
                problems.append("[output] threshold must be a number")
        regex = self.get("output", "contig_id_strip_regex")
        if regex:
            try:
                re.compile(regex)
            except re.error as exc:
                problems.append(f"[output] contig_id_strip_regex is not a valid regular expression: {exc}")
        uses_db = self.get("database", "uses_reference_database", "no")
        if uses_db not in ("yes", "no"):
            problems.append("[database] uses_reference_database must be yes or no")
        date = self.get("database", "release_date")
        if date and not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            problems.append("[database] release_date must be YYYY-MM-DD")
        if problems:
            raise ManifestError(f"{where}:\n  - " + "\n  - ".join(problems))

    # -- registry rows ----------------------------------------------------------------------------------------
    def capability_row(self):
        lr = self.get("tool", "requires_independent_long_read_truth", "auto")
        if lr == "auto":
            lr = "yes" if self.track in ("long_read", "hybrid") else "no"
        return {"tool": self.name,
                "method_class": self.get("tool", "method_class") or ("binning" if self.task == "reconstruction" else "classification"),
                "binning_capable": "yes" if self.task == "reconstruction" else "no",
                "primary_input": ",".join(_split(self.get("run", "requires"))) or "precomputed",
                "description": self.get("tool", "description") or f"user-supplied tool ({self.path})",
                "analysis_track": self.track,
                "requires_independent_long_read_truth": lr,
                "source": "user"}

    def installer_row(self):
        method = self.get("install", "method", "none")
        return {"tool": self.name, "profile": self.name, "install_mode": f"user_{method}",
                "automated": "yes" if method != "none" else "planned", "runtime": self.env_name,
                "database_mode": "manual" if self.get("database", "path") else "none",
                "verify_command": self.get("install", "verify_command"),
                "notes": f"user-supplied manifest {self.path}"}

    def database_row(self):
        return {"tool": self.name, "uses_reference_database": self.get("database", "uses_reference_database", "no"),
                "database": self.get("database", "database"), "database_release_date": self.get("database", "release_date"),
                "note": self.get("database", "note") or "declared in the user tool manifest"}

    # -- running ----------------------------------------------------------------------------------------------
    def run_spec(self, sample, inputs, outdir, threads):
        """What stage 4 needs for one sample: the mode, a missing-input reason, the rendered command or the
        imported file, and where the output will be. Every substituted value is shell-quoted."""
        mode = self.get("run", "mode")
        spec = {"mode": mode, "missing": "", "command": "", "output": "", "env": self.get("run", "env") or "auto",
                "env_name": self.env_name, "install": self.get("install", "method", "none"),
                "timeout": self.get("run", "timeout_seconds"), "checksum": self.checksum()}
        values = dict(inputs)
        values.update({"outdir": outdir, "threads": str(self.get("run", "threads") or threads), "sample": sample,
                       "tool_dir": str(self.folder), "db": os.path.expandvars(self.get("database", "path"))})
        if mode == "import":
            pattern = self.get("run", "pattern", "{sample}.tsv").replace("{sample}", sample)
            folder = os.path.expandvars(os.path.expanduser(self.get("run", "dir")))
            spec["output"] = str(Path(folder) / pattern)
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
        # A command continued over several manifest lines is one shell command line.
        template = " ".join(line.strip() for line in self.get("run", "command").splitlines() if line.strip())
        spec["command"] = re.sub(r"\{([a-z_0-9]+)\}", lambda m: shlex.quote(values.get(m.group(1), "")), template)
        fmt = self.get("output", "format")
        if fmt in ("fasta_dir",) and not self.get("output", "path"):
            spec["output"] = outdir
        else:
            spec["output"] = str(Path(outdir) / self.get("output", "path").replace("{sample}", sample)) if self.get("output", "path") else outdir
        return spec

    def install_plan(self):
        """The commands env/install_tools.sh runs, one per line (argv tab-separated), then the verification."""
        method = self.get("install", "method", "none")
        env = self.env_name
        steps = [["ENV", env]]   # the environment the tool runs in; [install] method = none leaves it unused
        if method == "conda":
            channels = _split(self.get("install", "channels")) or ["conda-forge", "bioconda"]
            argv = ["{CONDA}", "create", "-y", "-n", env]
            for ch in channels:
                argv += ["-c", ch]
            steps.append(argv + _split(self.get("install", "packages")))
            if _split(self.get("install", "pip_packages")):
                steps.append(["{CONDA}", "run", "-n", env, "python", "-m", "pip", "install"] + _split(self.get("install", "pip_packages")))
        elif method == "pip":
            python = self.get("install", "python") or "3.10"
            steps.append(["{CONDA}", "create", "-y", "-n", env, "-c", "conda-forge", f"python={python}", "pip"])
            steps.append(["{CONDA}", "run", "-n", env, "python", "-m", "pip", "install"] + _split(self.get("install", "pip_packages")))
        elif method == "script":
            steps.append(["bash", self.resolve(self.get("install", "script")), env])
        verify = self.get("install", "verify_command")
        if verify:
            steps.append(["VERIFY", verify])
        return steps


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


BUILTIN_REGISTRIES = {"tool_capabilities.tsv": "capability_row", "tool_installers.tsv": "installer_row",
                      "tool_database_releases.tsv": "database_row"}


def merge_rows(path, rows):
    """Registry readers call this with the rows they read. Only PlasBench's own registry files (config/<name>)
    gain the user tools' rows; a test fixture or any other file is returned unchanged. Accepts a list of dicts
    or a dict tool -> row and returns the same shape."""
    try:
        path = Path(path).resolve()
    except (TypeError, OSError):
        return rows
    kind = BUILTIN_REGISTRIES.get(path.name)
    if kind is None or path.parent != (ROOT / "config").resolve():
        return rows
    extra = [getattr(tool, kind)() for _, tool in sorted(cached().items())]
    if isinstance(rows, dict):
        merged = dict(rows)
        for row in extra:
            merged.setdefault(row["tool"], row)
        return merged
    known = {r.get("tool") for r in rows}
    return list(rows) + [r for r in extra if r["tool"] not in known]


def display_name(tool):
    found = cached().get(tool)
    return found.display_name if found else None


def enabled_names(selection):
    """USER_TOOLS / --tool: 'all', or a comma/space list. Unknown names are an error (a typo must not silently run
    nothing)."""
    tools = cached()
    wanted = _split(selection)
    if not wanted:
        return []
    if wanted == ["all"]:
        return sorted(tools)
    unknown = [w for w in wanted if w not in tools]
    if unknown:
        raise ManifestError(f"unknown user tool(s): {', '.join(unknown)}. Installed: {', '.join(sorted(tools)) or 'none'} "
                            f"(see `plasbench tools list`)")
    return wanted


TEMPLATE = """# PlasBench user tool manifest. Reference: docs/ADDING_TOOLS.md; examples: tools.d/examples/.
[tool]
name = {name}
display_name = {display}
# reconstruction = groups contigs into plasmids (bins); classification = labels contigs plasmid/chromosome
task = reconstruction
analysis_track = short_read          # short_read | long_read | hybrid
description = What the tool does, in one line.
citation =
version_command = mytool --version

[install]
method = conda                       # conda | pip | script | none (already on PATH)
packages = mytool
channels = conda-forge, bioconda
verify_command = mytool --help

[database]
uses_reference_database = no         # yes if it searches a plasmid database (enables the leakage check)
release_date =                       # YYYY-MM-DD of that database
path =                               # used as {{db}} in the command

[run]
mode = command                       # command (PlasBench runs it) | import (you ran it already)
# Placeholders: {{contigs}} {{graph}} {{reads_1}} {{reads_2}} {{long_reads}} {{outdir}} {{threads}} {{sample}} {{db}} {{tool_dir}}
command = mytool --input {{contigs}} --out {{outdir}} --threads {{threads}}
requires = contigs                   # inputs the command needs; a sample without one is skipped with the reason
# mode = import instead: dir = /path/to/outputs   pattern = {{sample}}.tsv

[output]
format = contig_bins                 # contig_bins | contig_labels | plasmid_fasta | fasta_dir | adapter
path = bins.tsv                      # relative to {{outdir}}
delimiter = tab
header = yes
contig_column = contig               # column name, or 1-based number
bin_column = bin
# contig_labels: label_column, plasmid_values = plasmid, score_column, threshold = 0.5
# contig_id_from = first_token       # keep the first word of the tool's contig ids
# contig_id_strip_regex = _length_.*$
"""


def scaffold(name, dest):
    if not NAME_RE.match(name):
        raise ManifestError(f"name '{name}' must be lower-case letters, digits and _, starting with a letter")
    if name in builtin_tools():
        raise ManifestError(f"'{name}' is a built-in PlasBench tool; choose another name")
    folder = Path(dest).expanduser() / name
    if (folder / MANIFEST).exists():
        raise ManifestError(f"{folder / MANIFEST} already exists")
    folder.mkdir(parents=True, exist_ok=True)
    display = name.replace("_", " ").title()
    (folder / MANIFEST).write_text(TEMPLATE.format(name=name, display=display), encoding="utf-8")
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
    c = sub.add_parser("new", help="write a commented manifest to fill in")
    c.add_argument("name")
    c.add_argument("--dir", default=str(Path.home() / ".plasbench" / "tools"))
    a = sub.add_parser("add", help="validate a tool folder and copy it onto the search path")
    a.add_argument("path")
    a.add_argument("--dest", default=str(Path.home() / ".plasbench" / "tools"))
    args = parser.parse_args(argv)

    try:
        if args.command == "new":
            print(f"Wrote {scaffold(args.name, args.dir)}\nEdit it, then: plasbench tools validate {args.name}")
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
                print(f"ok  {name}  ({tools[name].path})")
            if not tools:
                print("no user tools found on: " + ", ".join(str(p) for p in search_path()))
            return 0
        tools = discover()
        if args.command == "list":
            print("tool\tdisplay_name\ttask\ttrack\tmode\tformat\tinstall\tmanifest")
            for name, tool in sorted(tools.items()):
                print("\t".join((name, tool.display_name, tool.task, tool.track, tool.get("run", "mode"),
                                 tool.get("output", "format"), tool.get("install", "method", "none"), str(tool.path))))
            return 0
        if args.command == "dump":
            for name, tool in sorted(tools.items()):
                row = tool.capability_row()
                print("\t".join((name, row["binning_capable"], row["analysis_track"],
                                 row["requires_independent_long_read_truth"])))
            return 0
        if args.command == "names":
            print("\n".join(enabled_names(args.enabled)))
            return 0
        tool = tools.get(args.name)
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
    except ManifestError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
