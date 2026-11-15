#!/usr/bin/env python3
"""Read the versioned PlasBench tool-capability registry."""

import argparse
import csv
from pathlib import Path

ANALYSIS_TRACKS = ("short_read", "long_read", "hybrid")
# The three evaluation tasks: three different scientific questions, ranked separately and never against each other.
#   classification          labels sequence as plasmid-derived or not                      -> base-level F1
#   binning_reconstruction  groups EXISTING contigs into individual plasmids                -> length-weighted binning F1
#   sequence_reassembly     produces plasmid SEQUENCES (new records, not the input contigs) -> isolate-level CPRR
EVALUATION_TASKS = ("classification", "binning_reconstruction", "sequence_reassembly")
BIN_SCORED_TASKS = ("binning_reconstruction", "sequence_reassembly")   # their output is per-plasmid units: scored with the bin metrics (binning_capable = yes)
LEGACY_TASKS = {"reconstruction": "binning_reconstruction"}              # the name before the three-way split


def derived_task(row):
    """The task of a registry row that does not name one (an older registry, a test fixture): the answer it always gave, now with reassemblers told apart."""
    if (row.get("binning_capable") or "").strip().lower() != "yes":
        return "classification"
    return "sequence_reassembly" if (row.get("method_class") or "").strip() == "reassembly" else "binning_reconstruction"


def evaluation_task(row):
    """The evaluation task of a registry row: its explicit evaluation_task, else derived_task(). THIS decides where a tool is ranked; binning_capable does not."""
    explicit = (row.get("evaluation_task") or "").strip()
    explicit = LEGACY_TASKS.get(explicit, explicit)
    if explicit and explicit not in EVALUATION_TASKS:
        raise ValueError(f"{row.get('tool', '?')}: evaluation_task must be one of {sorted(EVALUATION_TASKS)}, got {explicit!r}")
    return explicit or derived_task(row)
# How far a tool has been validated (python/database_provenance.py explains each tier; test/test_tool_validation_tiers.py enforces them).
VALIDATION_TIERS = ("real_binary_checked", "adapter_tested", "untested", "not_applicable")


def read_capabilities(path):
    """Return tool -> declared capabilities, rejecting ambiguous registry rows."""
    capabilities = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            tool = row.get("tool", "")
            if not tool or tool in capabilities:
                raise ValueError(f"invalid or duplicate capability row: {tool!r}")
            if row.get("binning_capable") not in {"yes", "no"}:
                raise ValueError(f"{tool}: binning_capable must be yes/no")
            task = evaluation_task(row)
            if task not in EVALUATION_TASKS:
                raise ValueError(f"{tool}: evaluation_task must be one of {EVALUATION_TASKS}")
            if (row.get("evaluation_task") or "").strip() and (task == "classification") != (row.get("binning_capable") == "no"):
                raise ValueError(f"{tool}: evaluation_task {task} contradicts binning_capable={row.get('binning_capable')} "
                                 "(a classification tool is not bin-scored; a binning or reassembly tool is)")
            row["evaluation_task"] = task
            if row.get("analysis_track") not in ANALYSIS_TRACKS:
                raise ValueError(f"{tool}: analysis_track must be one of {ANALYSIS_TRACKS}")
            if row.get("requires_independent_long_read_truth") not in {"yes", "no"}:
                raise ValueError(f"{tool}: requires_independent_long_read_truth must be yes/no")
            if row.get("validation_status", "untested") not in VALIDATION_TIERS:
                raise ValueError(f"{tool}: validation_status must be one of {VALIDATION_TIERS}")
            capabilities[tool] = row
    try:   # user-declared tools join the built-in registry (python/user_tools.py); fixtures are untouched
        import user_tools
    except ImportError:
        return capabilities
    return user_tools.merge_rows(path, capabilities)


def default_registry(project_root):
    return Path(project_root) / "config" / "tool_capabilities.tsv"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--tool", help="the tool to query (not needed with --dump)")
    parser.add_argument("--dump", action="store_true",
                        help="validate the whole registry and print one line per tool: "
                             "tool, binning_capable, analysis_track, requires_independent_long_read_truth "
                             "(tab-separated; read once by scripts/lib.sh load_capabilities)")
    parser.add_argument("--binning-capable", action="store_true")
    parser.add_argument("--evaluation-task", action="store_true", help="print the tool's evaluation_task (classification, binning_reconstruction or sequence_reassembly)")
    parser.add_argument("--analysis-track", action="store_true",
                        help="print the tool's declared analysis_track instead of binning_capable")
    parser.add_argument("--requires-independent-long-read-truth", action="store_true",
                        help="exit 0 only if the tool's requires_independent_long_read_truth is yes")
    args = parser.parse_args()
    try:
        capabilities = read_capabilities(args.registry)
    except ValueError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    if args.dump:
        for tool, row in capabilities.items():
            print("\t".join((tool, row["binning_capable"], row["analysis_track"],
                             row["requires_independent_long_read_truth"], row["evaluation_task"])))
        return
    if not args.tool:
        parser.error("--tool is required unless --dump is given")
    row = capabilities.get(args.tool)
    if row is None:
        raise SystemExit(f"ERROR: tool not declared in capability registry: {args.tool}")
    if args.evaluation_task:
        print(row["evaluation_task"])
        return
    if args.analysis_track:
        print(row["analysis_track"])
        return
    if args.requires_independent_long_read_truth:
        if row["requires_independent_long_read_truth"] != "yes":
            raise SystemExit(1)
        print(row["requires_independent_long_read_truth"])
        return
    if args.binning_capable and row["binning_capable"] != "yes":
        raise SystemExit(1)
    print(row["binning_capable"])


if __name__ == "__main__":
    main()
