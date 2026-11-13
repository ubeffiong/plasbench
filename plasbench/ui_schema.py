"""Describe the whole PlasBench command line as JSON, for the setup window (plasbench/webui.py).

The window renders one form per command from this description, generated from the very parser `plasbench` uses
(plasbench.cli.build_parser), so every command and option is available in the window and none can drift out of date.
`validate_argv` re-parses a command line the window built before it is run, with the same parser.
"""
from __future__ import annotations

import argparse
import contextlib
import io
from pathlib import Path

from .cli import build_parser

# Where each command appears in the window. A command missing here still appears, under "More commands".
CATEGORIES = [
    ("setup", "Set up", "Install, check and update PlasBench and its tools.",
     ["ui", "check", "install-conda", "install-tools", "tools", "upgrade", "test"]),
    ("benchmark", "Benchmark", "Run benchmarks on cohorts or your own isolates.",
     ["demo", "run", "init-local", "report", "reconstruct", "select-candidates", "select-unknown"]),
    ("sweeps", "Depth and quality sweeps", "How far sequencing can be cut before recovery degrades.",
     ["depth-ladder", "depth-report", "read-quality-ladder", "read-quality-report"]),
    ("cohorts", "Cohorts and truth", "Find, curate and validate isolates and their reference truth.",
     ["discover-cohort", "discover-design-cohort", "review-candidates", "curate-cohort", "validate-cohort",
      "build-ledger", "collect-truth-provenance", "derive-amr-truth", "audit-truth-labels", "prepare-contribution"]),
    ("results", "Results and analysis", "Reports, PDFs and standalone analyses of a completed run.",
     ["open-report", "report-pdf", "analysis", "candidate-dataset", "import-external-benchmark",
      "validate-orthogonal-evidence"]),
    ("meta", "Metagenomics track", "The separate graph-aware metagenomic track.",
     ["metagenomics", "audit-meta-cohort", "design-meta-synthetic", "validate-meta-intake", "materialize-meta-bmock12",
      "normalize-meta-classifier", "import-mobilome-evidence"]),
    ("help", "Help", "Guides and the concept note.", ["docs", "concept-note"]),
]
# Shorthand spellings argparse registers as separate choices; the window shows each command once.
ALIASES = {"meta": "metagenomics", "beta": "metagenomics"}


def _jsonable(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)


def _kind(action):
    if isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
        return "flag"
    if isinstance(action, argparse._AppendAction) or action.nargs in ("+", "*") or isinstance(action.nargs, int) and action.nargs > 1:
        return "list"
    if action.choices:
        return "choice"
    type_name = getattr(action.type, "__name__", "") if action.type else ""
    if type_name in ("int",):
        return "int"
    if type_name in ("float",):
        return "float"
    # Whole name parts only: "profile" contains "file" but is not a path.
    parts = set(action.dest.lower().split("_"))
    if type_name in ("Path", "project_root") or parts & PATH_WORDS:
        return "path"
    return "text"


PATH_WORDS = {"dir", "path", "file", "out", "sheet", "samples", "manifest", "fasta", "tsv", "report", "scores", "script",
              "ledger", "lock", "evidence", "predictions", "candidates", "contigs", "reference", "truth", "db", "reads"}


def _arg(action, group):
    kind = _kind(action)
    default = action.default
    if default is argparse.SUPPRESS:
        default = None
    if kind == "flag":
        default = bool(default) if isinstance(action, argparse._StoreFalseAction) else False
    return {
        "dest": action.dest,
        "flags": list(action.option_strings),
        "positional": not action.option_strings,
        "kind": kind,
        "help": (action.help or "").replace("%(default)s", str(default)) if action.help != argparse.SUPPRESS else "",
        "choices": _jsonable(list(action.choices)) if action.choices and not isinstance(action, argparse._SubParsersAction) else None,
        "default": _jsonable(default),
        "required": bool(action.required) if action.option_strings else action.nargs not in ("?", "*"),
        "nargs": action.nargs if isinstance(action.nargs, (int, str)) else None,
        "metavar": action.metavar if isinstance(action.metavar, str) else None,
        "negates": isinstance(action, argparse._StoreFalseAction),
        "group": group,
    }


def _describe(parser, name, help_text=""):
    args, subcommands = [], []
    for group in parser._action_groups:
        title = group.title or ""
        title = "" if title in ("positional arguments", "options", "optional arguments") else title
        for action in group._group_actions:
            if isinstance(action, (argparse._HelpAction, argparse._VersionAction)):
                continue
            if isinstance(action, argparse._SubParsersAction):
                helps = {c.dest: c.help for c in action._choices_actions}
                seen = set()
                for sub_name, sub_parser in action.choices.items():
                    if id(sub_parser) in seen:
                        continue
                    seen.add(id(sub_parser))
                    subcommands.append(_describe(sub_parser, sub_name, helps.get(sub_name, "")))
                continue
            args.append(_arg(action, title))
    return {"name": name, "help": help_text or "", "description": parser.description or "",
            "epilog": parser.epilog or "", "args": args, "subcommands": subcommands}


def schema():
    """{"commands": [...], "categories": [...]} for the window."""
    parser = build_parser()
    top = _describe(parser, "plasbench", parser.description or "")
    commands = [c for c in top["subcommands"] if c["name"] not in ALIASES]
    names = {c["name"] for c in commands}
    placed = set()
    categories = []
    for key, title, blurb, members in CATEGORIES:
        present = [m for m in members if m in names]
        placed.update(present)
        categories.append({"id": key, "title": title, "blurb": blurb, "commands": present})
    rest = sorted(names - placed)
    if rest:
        categories.append({"id": "more", "title": "More commands", "blurb": "Other commands.", "commands": rest})
    globals_ = [a for a in top["args"] if a["dest"] != "command"]
    return {"commands": commands, "categories": categories, "global_args": globals_, "aliases": ALIASES}


def validate_argv(argv):
    """Parse a command line exactly as `plasbench` would. Returns (ok, message)."""
    parser = build_parser()
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            parser.parse_args(list(argv))
    except SystemExit as exc:
        if exc.code in (0, None):
            return True, ""
        message = err.getvalue().strip().splitlines()
        return False, message[-1] if message else "invalid command line"
    return True, ""
