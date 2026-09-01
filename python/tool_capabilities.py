#!/usr/bin/env python3
"""Read the versioned PlasBench tool-capability registry."""

import csv
from pathlib import Path


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
            capabilities[tool] = row
    return capabilities


def default_registry(project_root):
    return Path(project_root) / "config" / "tool_capabilities.tsv"
