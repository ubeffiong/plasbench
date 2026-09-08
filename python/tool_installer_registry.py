#!/usr/bin/env python3
"""Inspect and validate the install contract for every supported adapter."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


DEMO_SUFFIX = "_like"
REQUIRED_COLUMNS = {
    "tool", "profile", "install_mode", "automated", "runtime",
    "database_mode", "verify_command", "notes",
}


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None or not REQUIRED_COLUMNS.issubset(reader.fieldnames):
            raise ValueError(f"{path} is missing required installer columns")
        return [{key: (value or "").strip() for key, value in row.items()} for row in reader]


def capability_tools(path: Path) -> set[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None or "tool" not in reader.fieldnames:
            raise ValueError(f"{path} has no tool column")
        return {str(row["tool"]).strip() for row in reader if str(row["tool"]).strip() and not str(row["tool"]).strip().endswith(DEMO_SUFFIX)}


def validate(rows: list[dict[str, str]], capabilities: set[str]) -> list[str]:
    errors: list[str] = []
    by_tool: dict[str, dict[str, str]] = {}
    for row in rows:
        tool = row["tool"]
        if tool in by_tool:
            errors.append(f"duplicate installer row for {tool}")
        by_tool[tool] = row
        if row["automated"] not in {"yes", "planned"}:
            errors.append(f"{tool}: automated must be yes or planned")
        if row["database_mode"] not in {"none", "automated", "manual"}:
            errors.append(f"{tool}: invalid database_mode {row['database_mode']!r}")
        if not row["profile"] or not row["verify_command"]:
            errors.append(f"{tool}: profile and verify_command are required")
    missing = sorted(capabilities - set(by_tool))
    extra = sorted(set(by_tool) - capabilities)
    errors.extend(f"missing installer contract for supported tool {tool}" for tool in missing)
    errors.extend(f"installer contract has no supported adapter: {tool}" for tool in extra)
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("list", "plan", "validate"))
    parser.add_argument("--registry", type=Path, default=Path("config/tool_installers.tsv"))
    parser.add_argument("--metagenomic-registry", type=Path, default=Path("config/metagenomic_tool_installers.tsv"),
                        help="Optional non-isolate adapter registry displayed with installation plans.")
    parser.add_argument("--capabilities", type=Path, default=Path("config/tool_capabilities.tsv"))
    args = parser.parse_args(argv)
    try:
        rows = read_tsv(args.registry)
        errors = validate(rows, capability_tools(args.capabilities))
        meta_rows = read_tsv(args.metagenomic_registry) if args.metagenomic_registry.is_file() else []
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.action == "validate":
        if errors:
            print("INSTALLER REGISTRY INVALID:", file=sys.stderr)
            print("\n".join(f"  - {error}" for error in errors), file=sys.stderr)
            return 1
        print(f"INSTALLER REGISTRY VALID: {len(rows)} isolate adapters and {len(meta_rows)} metagenomic contracts covered")
        return 0
    if errors:
        print("WARNING: registry has validation errors; run 'install-tools validate' before installing.", file=sys.stderr)
    writer = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
    writer.writerow(("tool", "profile", "install_mode", "automated", "runtime", "database_mode", "verify_command", "notes"))
    for row in rows:
        writer.writerow(tuple(row[column] for column in ("tool", "profile", "install_mode", "automated", "runtime", "database_mode", "verify_command", "notes")))
    for row in meta_rows:
        writer.writerow(tuple(row[column] for column in ("tool", "profile", "install_mode", "automated", "runtime", "database_mode", "verify_command", "notes")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
