#!/usr/bin/env python3
"""Tool and database provenance (plan E2 and E3): which database version and source stand behind each tool, and how far the tool has been validated.

Two registries already exist and are only read here, never copied:

  config/tool_database_releases.tsv  per tool: the database, its release date and (appended in v0.4.0) `database_version`, `source_url`,
                                     `database_checksum_sha256`. A blank is "not recorded", never a guess: a checksum is only ever filled in from a
                                     real download (`database_provenance.py checksum PATH` prints it).
  config/tool_capabilities.tsv       per tool: method class and (appended in v0.4.0) `validation_status` and `validation_evidence`.

Provenance status, computed (never stored, so it cannot go stale):
  not_applicable  the tool has no reference database (uses_reference_database = no)
  recorded        version, source URL, release date and checksum are all recorded IN THE REGISTRY. It does not say that this run used that database: the run's own database
                  identity (`identity_in_run`, a hash of file names, sizes and times, not of contents) is a different quantity and is not compared with the checksum
  partly          some of them are recorded
  unrecorded      none are

Validation tiers (validation_status), strongest first:
  real_binary_checked  the scheduled workflow (.github/workflows/real-tools.yml) ran the REAL tool on a known input and its output validated; the evidence
                       is a record file under test/real_tools/records/
  adapter_tested       the adapter is tested against recorded or stand-in tool output (the evidence is that test); the real binary is not checked
  untested             an adapter or recipe exists with no test: a new tool starts here, and test_tool_validation_tiers.py fails when a tool is added at
                       this tier without being acknowledged, so an adapter is not quietly shipped unvalidated
  not_applicable       not a third-party tool (PlasBench's own baselines and the synthetic demo methods)

Subcommands
  collect    write benchmark.database_provenance.tsv (one row per tool: tier, database, version, source, release date, checksum, the database identity
             of THIS run from run_manifest.json when the pipeline recorded one, status, what is missing, whether the tool ran)
  checksum   print the SHA-256 of a file, or of a directory (over the sorted relative paths and file contents), to paste into the registry

Standard library only.
"""
import argparse
import csv
import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import flag_database_overlap as fdo  # noqa: E402  (the reader of the database registry, with user tools merged)
import tool_capabilities as tc  # noqa: E402

ROOT = HERE.parent
VALIDATION = ("real_binary_checked", "adapter_tested", "untested", "not_applicable")
FIELDS = ["tool", "validation_status", "validation_evidence", "database", "database_version", "source_url", "database_release_date", "checksum_sha256",
          "identity_in_run", "provenance_status", "missing", "used_in_run"]
# the databases the manifest identifies by path (write_manifest.py: directory_identity); the key is the manifest's, the tool is the one that reads it
MANIFEST_KEY = {"platon": "platon", "genomad": "genomad", "plasme": "plasme"}
PROVENANCE_COLUMNS = (("database_version", "version"), ("source_url", "source"), ("database_release_date", "release date"), ("database_checksum_sha256", "checksum"))


def provenance_status(row):
    """(status, [missing column labels]) for one registry row."""
    if (row.get("uses_reference_database") or "").strip().lower() == "no":
        return "not_applicable", []
    missing = [label for column, label in PROVENANCE_COLUMNS if not (row.get(column) or "").strip()]
    if len(missing) == len(PROVENANCE_COLUMNS):
        return "unrecorded", missing
    return ("recorded" if not missing else "partly"), missing


def rows(registry_rows, capabilities, run_tools=None, manifest=None):
    """One provenance row per tool of either registry. `run_tools` is the set of tools in this run's tool_status (None = unknown)."""
    by_db = {r.get("tool"): r for r in registry_rows}
    manifest_db = (manifest or {}).get("databases") or {}
    out = []
    for tool in sorted(set(by_db) | set(capabilities)):
        db = by_db.get(tool, {})
        cap = capabilities.get(tool, {})
        status, missing = provenance_status(db) if db else ("unrecorded", [label for _c, label in PROVENANCE_COLUMNS])
        key = MANIFEST_KEY.get(tool)
        identity = (manifest_db.get(key) or {}).get("identity_sha256", "") if key else ""
        out.append({"tool": tool, "validation_status": cap.get("validation_status") or "untested", "validation_evidence": cap.get("validation_evidence") or "",
                    "database": db.get("database", ""), "database_version": db.get("database_version", ""), "source_url": db.get("source_url", ""),
                    "database_release_date": db.get("database_release_date", ""), "checksum_sha256": db.get("database_checksum_sha256", ""),
                    "identity_in_run": identity, "provenance_status": status, "missing": ", ".join(missing),
                    "used_in_run": "" if run_tools is None else ("yes" if tool in run_tools else "no")})
    return out


def registry_summary(project_root=ROOT):
    """{tool: {version, source_url, checksum_sha256, status, validation}} for run_manifest.json: the registries as they were when the run was made."""
    root = Path(project_root)
    db_rows = fdo.read_rows(root / "config" / "tool_database_releases.tsv")
    caps = tc.read_capabilities(root / "config" / "tool_capabilities.tsv")
    return {r["tool"]: {"database_version": r["database_version"], "source_url": r["source_url"], "checksum_sha256": r["checksum_sha256"],
                        "provenance_status": r["provenance_status"], "validation_status": r["validation_status"]} for r in rows(db_rows, caps)}


def tree_checksum(path):
    """SHA-256 of a file, or of a directory over its sorted relative paths and file contents (not mtimes: the same content gives the same value anywhere)."""
    path = Path(path)
    digest = hashlib.sha256()
    if path.is_file():
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        return digest.hexdigest()
    if not path.is_dir():
        raise ValueError(f"{path} is neither a file nor a directory")
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        digest.update(str(item.relative_to(path)).replace(os.sep, "/").encode() + b"\0")
        with open(item, "rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
    return digest.hexdigest()


def read_status_tools(path):
    if not path or not Path(path).is_file():
        return None
    with open(path, newline="", encoding="utf-8") as handle:
        return {r.get("tool") for r in csv.DictReader(handle, delimiter="\t") if r.get("tool")}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--registry", default=str(ROOT / "config" / "tool_database_releases.tsv"))
    c.add_argument("--capabilities", default=str(ROOT / "config" / "tool_capabilities.tsv"))
    c.add_argument("--manifest")
    c.add_argument("--tool-status")
    c.add_argument("--out", required=True)
    k = sub.add_parser("checksum")
    k.add_argument("path")
    args = parser.parse_args()
    if args.command == "checksum":
        try:
            print(tree_checksum(args.path))
        except ValueError as exc:
            raise SystemExit(f"ERROR: {exc}")
        return
    manifest = {}
    if args.manifest and Path(args.manifest).is_file():
        try:
            manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {}
    table = rows(fdo.read_rows(args.registry), tc.read_capabilities(args.capabilities), read_status_tools(args.tool_status), manifest)
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(table)
    counts = {}
    for r in table:
        counts[r["provenance_status"]] = counts.get(r["provenance_status"], 0) + 1
    sys.stderr.write(f"[database_provenance] {len(table)} tool(s): " + ", ".join(f"{n} {s}" for s, n in sorted(counts.items())) + f" -> {args.out}\n")


if __name__ == "__main__":
    main()
