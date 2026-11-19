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
        rows = [{key: (value or "").strip() for key, value in row.items()} for row in reader]
    return _with_user_tools(path, rows)


def _with_user_tools(path: Path, rows):
    """User-declared tools (python/user_tools.py) join the built-in registries; any other file is unchanged."""
    try:
        import user_tools
    except ImportError:
        return rows
    return user_tools.merge_rows(path, rows)


def capability_tools(path: Path) -> set[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None or "tool" not in reader.fieldnames:
            raise ValueError(f"{path} has no tool column")
        rows = _with_user_tools(path, list(reader))
    return {str(row["tool"]).strip() for row in rows if str(row["tool"]).strip() and not str(row["tool"]).strip().endswith(DEMO_SUFFIX)}


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


# Exit codes of `plasbench install-tools` (documented in INSTALL.md and FAQ.md). Anything not listed keeps its usual meaning (1 = the install
# failed, 2 = a wrong option or an unknown name, 137 = killed for memory).
EXIT_MANUAL = 20      # nothing failed: this profile is installed by hand; the notice says how
EXIT_NOTHING_TO_DO = 10   # internal to `resolve`: a built-in profile; env/install_tools.sh turns it into exit 0

# Profiles env/install_tools.sh installs through its own case branch although no registry row names them.
SCRIPT_PROFILES = ("core", "assembly", "mobsuite", "locked", "metagenomics", "simulate", "quast", "long-read", "utilities",
                   "reference-annotation", "annotation", "annotation-prokka", "gplas", "all")
ACTIONS = ("list", "plan", "validate")
INSTALL_POINTER = "INSTALL.md, section 3, 'Manual-install profiles (exit code 20)'"


def profile_kinds(rows: list[dict[str, str]]) -> dict[str, str]:
    """profile -> automatic | manual | builtin, from the registry rows. A profile is manual when no row of it installs automatically."""
    by_profile: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_profile.setdefault(row["profile"], []).append(row)
    kinds = {}
    for profile, group in by_profile.items():
        if all(r["install_mode"] == "builtin" for r in group):
            kinds[profile] = "builtin"
        elif any(r["automated"] == "yes" for r in group):
            kinds[profile] = "automatic"
        else:
            kinds[profile] = "manual"
    for profile in SCRIPT_PROFILES:
        kinds.setdefault(profile, "automatic")
    return kinds


def resolve(name: str, rows: list[dict[str, str]]) -> tuple[int, str]:
    """What `install-tools NAME` will do, without doing it: (exit code, message). 0 = an installer runs, 10 = nothing to install, 20 = manual,
    2 = not a known name (with the nearest names). A name that is no profile and is not close to one is left to conda as a package name."""
    import difflib
    kinds = profile_kinds(rows)
    tools = {r["tool"]: r["profile"] for r in rows}
    if name in ACTIONS:
        return 0, ""
    if name in tools and name not in kinds:     # a tool name given instead of its profile
        name = tools[name]
    kind = kinds.get(name)
    if kind == "builtin":
        return EXIT_NOTHING_TO_DO, (f"[PlasBench] {name}: nothing to install. These tools are built into PlasBench "
                                    "(they need no program or database of their own; see `plasbench install-tools plan` for what each one needs).")
    if kind == "manual":
        notes = sorted({r["notes"] for r in rows if r["profile"] == name and r["notes"]})
        tool_names = ", ".join(sorted(r["tool"] for r in rows if r["profile"] == name))
        lines = [f"[PlasBench] {name} needs a manual install. Nothing failed; PlasBench does not install this one for you (exit code {EXIT_MANUAL}).",
                 f"  Tools it provides: {tool_names}"]
        lines += [f"  Why: {note}" for note in notes]
        lines += ["  Next steps:",
                  "    1. Read the notes above and run `plasbench install-tools plan` (it shows the verification command for each tool).",
                  f"    2. Install it by hand, pinned to a revision you have checked: {INSTALL_POINTER}.",
                  "    3. Check it is found: `plasbench check`, then enable the tool in Settings."]
        return EXIT_MANUAL, "\n".join(lines)
    if kind is not None:
        return 0, ""
    known = sorted(set(kinds) | set(tools))
    near = difflib.get_close_matches(name, known, n=3, cutoff=0.75)
    if near:
        return 2, (f"[PlasBench] '{name}' is not a PlasBench install profile. Did you mean: {', '.join(near)}?\n"
                   "  `plasbench install-tools list` shows every profile. (A name that is not close to a profile is treated as a conda package name.)")
    return 0, ""


def needs_network(name: str, rows: list[dict[str, str]]) -> bool:
    """Will `install-tools NAME` go online? Only when an installer would run (resolve says 0) and NAME is not an inspection action: a built-in profile (nothing to
    install), a manual one (exit 20: the notice is printed and nothing is fetched) and a near-miss name (exit 2) must not be refused for lack of internet.
    The command-line pre-flight (plasbench/cli.py) and the window's gating (plasbench/netgate.py) both ask this."""
    return name not in ACTIONS and resolve(name, rows)[0] == 0


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=ACTIONS + ("resolve",))
    parser.add_argument("name", nargs="?", help="resolve: the profile or tool name to classify (prints what install-tools would do; installs nothing)")
    parser.add_argument("--registry", type=Path, default=root / "config" / "tool_installers.tsv")
    parser.add_argument("--metagenomic-registry", type=Path, default=root / "config" / "metagenomic_tool_installers.tsv",
                        help="Optional non-isolate adapter registry displayed with installation plans.")
    parser.add_argument("--capabilities", type=Path, default=root / "config" / "tool_capabilities.tsv")
    args = parser.parse_args(argv)
    if args.action == "resolve":
        if not args.name:
            print("ERROR: resolve needs a profile name", file=sys.stderr)
            return 2
        try:
            rows = read_tsv(args.registry)
            if args.metagenomic_registry.is_file():
                rows += read_tsv(args.metagenomic_registry)
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        code, message = resolve(args.name, rows)
        if message:
            print(message, file=sys.stderr if code == 2 else sys.stdout)
        return code
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
