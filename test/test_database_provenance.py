#!/usr/bin/env python3
"""Tool and database provenance (plan E2): status, the table, the checksum, the manifest record and the report."""
import csv
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import database_provenance as dp  # noqa: E402


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    print("status")
    full = {"uses_reference_database": "yes", "database_version": "2.0", "source_url": "u", "database_release_date": "2020-01-01", "database_checksum_sha256": "ab" * 32}
    check("everything recorded", dp.provenance_status(full) == ("recorded", []))
    check("some recorded is partly, and names what is missing", dp.provenance_status({**full, "database_checksum_sha256": ""}) == ("partly", ["checksum"]))
    check("nothing recorded", dp.provenance_status({"uses_reference_database": "yes"})[0] == "unrecorded")
    check("no database is not applicable", dp.provenance_status({"uses_reference_database": "no"}) == ("not_applicable", []))

    print("rows")
    table = dp.rows([{"tool": "platon", "uses_reference_database": "yes", "database": "d", "database_version": "1.5"}, {"tool": "x", "uses_reference_database": "no"}],
                    {"platon": {"validation_status": "adapter_tested", "validation_evidence": "t"}, "x": {}, "y": {"validation_status": "untested"}},
                    run_tools={"platon"}, manifest={"databases": {"platon": {"identity_sha256": "idid"}}})
    by = {r["tool"]: r for r in table}
    check("a row per tool of either registry", set(by) == {"platon", "x", "y"})
    check("the tier, the database and this run's identity are joined", by["platon"]["validation_status"] == "adapter_tested" and by["platon"]["database_version"] == "1.5" and by["platon"]["identity_in_run"] == "idid")
    check("a tool with no tier is untested, a tool absent from the database registry is unrecorded", by["x"]["validation_status"] == "untested" and by["y"]["provenance_status"] == "unrecorded")
    check("used_in_run says whether the tool ran", by["platon"]["used_in_run"] == "yes" and by["x"]["used_in_run"] == "no")

    print("the registry")
    with open(ROOT / "config" / "tool_database_releases.tsv", newline="", encoding="utf-8") as handle:
        reg = list(csv.DictReader(handle, delimiter="\t"))
    check("the registry has the new columns", all(c in reg[0] for c in ("database_version", "source_url", "database_checksum_sha256")))
    check("no checksum is recorded that was not computed from a download (all blank until filled)", all(not r["database_checksum_sha256"] for r in reg))
    check("a recorded version has a source", all(r["source_url"] or not r["database_version"] or "bundled" in r["database_version"] for r in reg),
          [r["tool"] for r in reg if r["database_version"] and not r["source_url"] and "bundled" not in r["database_version"]])
    summary = dp.registry_summary(ROOT)
    check("the manifest summary covers the tools and names their status", summary["platon"]["provenance_status"] == "partly" and summary["mob_like"]["validation_status"] == "not_applicable", summary.get("platon"))

    print("checksum")
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / "a").mkdir()
        (t / "a" / "f.txt").write_text("hello")
        (t / "b").mkdir()
        (t / "b" / "f.txt").write_text("hello")
        check("the same content gives the same checksum in two places", dp.tree_checksum(t / "a") == dp.tree_checksum(t / "b"))
        (t / "b" / "f.txt").write_text("hellp")
        check("different content differs", dp.tree_checksum(t / "a") != dp.tree_checksum(t / "b"))
        check("a file's checksum is its SHA-256", dp.tree_checksum(t / "a" / "f.txt") == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824")
        try:
            dp.tree_checksum(t / "none")
            check("a missing path is an error", False)
        except ValueError:
            check("a missing path is an error", True)

    print("the demo")
    demo = ROOT / "results_demo"
    table_path, report = demo / "benchmark.database_provenance.tsv", demo / "benchmark.report.html"
    if not table_path.is_file() or not report.is_file():
        print("  SKIP: no results_demo (run test/run_demo.sh first)")
    else:
        with open(table_path, newline="") as handle:
            header = next(csv.reader(handle, delimiter="\t"))
        check("the demo table has every column", header == dp.FIELDS, header)
        page = report.read_text(encoding="utf-8")
        check("the report shows the provenance table with the validation tier and what is not recorded", "Tool and database provenance" in page and "adapter tested" in page and "not recorded" in page)
    import write_manifest as wm
    recorded = wm.database_registry(ROOT)
    check("the manifest writer records the registries: every tool with its provenance status and validation tier (the demo's own manifest is synthetic, made by the demo generator)",
          "unavailable" not in recorded and recorded["platon"]["provenance_status"] == "partly" and recorded["platon"]["validation_status"] == "adapter_tested", list(recorded)[:3])
    check("a malformed registry is reported in the manifest, not raised", "unavailable" in wm.database_registry(ROOT / "no_such_project"))
    print()
    if not ok:
        print("DATABASE PROVENANCE TESTS FAILED")
        sys.exit(1)
    print("ALL DATABASE PROVENANCE TESTS PASSED")


if __name__ == "__main__":
    main()
