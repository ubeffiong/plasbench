#!/usr/bin/env python3
"""User tool manifests (python/user_tools.py): validation, discovery, registry merge, run specs and install plans."""

import csv
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

import user_tools as ut  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


GOOD = """[tool]
name = my_binner
display_name = My Binner
task = reconstruction
analysis_track = short_read
version_command = echo 1.2.3
[install]
method = conda
packages = mybinner=1.2
verify_command = mybinner --help
[database]
uses_reference_database = yes
release_date = 2024-03-01
path = /db/mybinner
[run]
mode = command
command = mybinner --in {contigs} --gfa {graph}
    --db {db} --out {outdir} -t {threads}
requires = contigs, graph
[output]
format = contig_bins
path = result/bins.tsv
"""


def write(folder, text, name="plasbench-tool.ini"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")
    return folder / name


def errors_of(text):
    with tempfile.TemporaryDirectory() as tmp:
        try:
            ut.UserTool(write(Path(tmp) / "t", text))
        except ut.ManifestError as exc:
            return str(exc)
    return ""


def main():
    os.environ.pop("PLASBENCH_USER_TOOLS", None)
    print("validation")
    check("a complete manifest is valid", errors_of(GOOD) == "", errors_of(GOOD))
    bad = errors_of(GOOD.replace("format = contig_bins", "format = bins\ncolour = red"))
    check("unknown keys and values are reported together", "unknown key 'colour'" in bad and "format must be one of" in bad, bad)
    bad = errors_of(GOOD.replace("requires = contigs, graph", "requires = contigs"))
    check("a placeholder the command uses but requires does not list is reported", "uses graph but requires" in bad, bad)
    bad = errors_of(GOOD.replace("{threads}", "{cores}"))
    check("an unknown placeholder is reported with the available ones", "{cores}" in bad and "{contigs}" in bad, bad)
    bad = errors_of(GOOD.replace("task = reconstruction", "task = classification"))
    check("contig_bins for a classifier is reported", "set [tool] task = reconstruction" in bad, bad)
    bad = errors_of(GOOD.replace("name = my_binner", "name = My-Binner"))
    check("a name that is not snake_case is reported", "lower-case" in bad, bad)
    bad = errors_of(GOOD.replace("release_date = 2024-03-01", "release_date = March 2024"))
    check("a database date not YYYY-MM-DD is reported", "YYYY-MM-DD" in bad, bad)
    bad = errors_of(GOOD.replace("mode = command", "mode = import"))
    check("import mode needs dir", "needs dir" in bad, bad)

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        first, second = base / "first", base / "second"
        write(first / "my_binner", GOOD)
        write(second / "my_binner", GOOD.replace("My Binner", "Other"))
        write(first / "broken", "[tool]\nname = broken\n")
        write(first / "platon", GOOD.replace("name = my_binner", "name = platon"))
        os.environ["PLASBENCH_TOOLS_PATH"] = os.pathsep.join([str(first), str(second)])
        ut._CACHE.clear()
        found = ut.discover()

        print("discovery")
        check("the first folder on the search path wins", found["my_binner"].display_name == "My Binner")
        check("a broken manifest is skipped, not fatal", "broken" not in found)
        check("a built-in name cannot be reused", "platon" not in found)
        try:
            ut.discover(strict=True)
            strict = ""
        except ut.ManifestError as exc:
            strict = str(exc)
        check("validate (strict) lists every problem", "broken" in strict and "built-in" in strict and "already defined" in strict, strict)
        check("names: 'all' and an explicit list", ut.enabled_names("all") == ["my_binner"] and ut.enabled_names("my_binner") == ["my_binner"])
        try:
            ut.enabled_names("my_binner,typo")
            typo = ""
        except ut.ManifestError as exc:
            typo = str(exc)
        check("an unknown selected name is an error naming it", "typo" in typo, typo)

        print("registry merge")
        caps = ROOT / "config" / "tool_capabilities.tsv"
        import tool_capabilities
        merged = tool_capabilities.read_capabilities(caps)
        row = merged.get("my_binner", {})
        check("the built-in capability registry gains the user tool", row.get("binning_capable") == "yes"
              and row.get("analysis_track") == "short_read" and row.get("source") == "user", row)
        check("built-in rows are unchanged", merged["platon"].get("source") is None)
        fixture = base / "fixture.tsv"
        with caps.open(encoding="utf-8") as src:
            fixture.write_text(src.read(), encoding="utf-8")
        check("a fixture registry elsewhere is left alone", "my_binner" not in tool_capabilities.read_capabilities(fixture))
        import tool_installer_registry as tir
        rows = tir.read_tsv(ROOT / "config" / "tool_installers.tsv")
        errors = tir.validate(rows, tir.capability_tools(caps))
        check("the installer registry stays valid with a user tool", errors == [], errors)
        from plasbench_common import display_tool_name
        check("display names come from the manifest", display_tool_name("my_binner") == "My Binner")
        check("built-in display names are unchanged", display_tool_name("mob_recon") == "MOB-recon")
        import flag_database_overlap as fdo
        db = {r["tool"]: r for r in fdo.read_rows(ROOT / "config" / "tool_database_releases.tsv")}
        check("the database release date feeds the leakage check", db.get("my_binner", {}).get("database_release_date") == "2024-03-01")
        import headline_design as hd
        design = hd.Design(capabilities=str(caps))
        check("the headline design places it in the reconstruction task", design.task_of.get("my_binner") == hd.TASK_RECONSTRUCTION)

        print("run spec and install plan")
        tool = found["my_binner"]
        data = base / "data"
        data.mkdir()
        (data / "contigs.fasta").write_text(">c1\nACGT\n", encoding="utf-8")
        inputs = {"contigs": str(data / "contigs.fasta"), "graph": str(data / "graph with space.gfa"), "reads_1": "",
                  "reads_2": "", "long_reads": ""}
        spec = tool.run_spec("s1", inputs, str(base / "out"), "4")
        check("a missing required input names it", "input graph unavailable" in spec["missing"] and not spec["command"], spec)
        (data / "graph with space.gfa").write_text("H\n", encoding="utf-8")
        spec = tool.run_spec("s1", inputs, str(base / "out"), "4")
        check("a missing database is reported", spec["missing"].startswith("database not found"), spec)
        os.environ["MYDB"] = str(data)
        tool.sections["database"]["path"] = "$MYDB"
        spec = tool.run_spec("s1", inputs, str(base / "out"), "4")
        check("the command is one line with every value shell-quoted",
              "\n" not in spec["command"] and "'" in spec["command"] and "graph with space.gfa'" in spec["command"]
              and spec["command"].endswith("-t 4"), spec["command"])
        check("the output path is under {outdir}", spec["output"].replace("\\", "/").endswith("out/result/bins.tsv"), spec["output"])
        plan = tool.install_plan()
        check("conda install plan: env, create with packages, verify",
              plan[0] == ["ENV", "plasbench-my_binner"] and plan[1][:5] == ["{CONDA}", "create", "-y", "-n", "plasbench-my_binner"]
              and "mybinner=1.2" in plan[1] and plan[-1] == ["VERIFY", "mybinner --help"], plan)

        print("scaffold and add")
        made = ut.scaffold("new_tool", base / "home")
        text = made.read_text(encoding="utf-8")
        check("the scaffold is a complete, valid manifest", errors_of(text) == "", errors_of(text))
        try:
            ut.scaffold("mob_recon", base / "home")
            clash = ""
        except ut.ManifestError as exc:
            clash = str(exc)
        check("scaffolding a built-in name is refused", "built-in" in clash)
        target = ut.add(first / "my_binner", base / "installed")
        check("add copies a validated tool folder", (target / "plasbench-tool.ini").is_file() and target.name == "my_binner")

        os.environ["PLASBENCH_USER_TOOLS"] = "off"
        ut._CACHE.clear()
        check("PLASBENCH_USER_TOOLS=off hides every user tool", "my_binner" not in tool_capabilities.read_capabilities(caps))
        os.environ.pop("PLASBENCH_USER_TOOLS")
        os.environ.pop("PLASBENCH_TOOLS_PATH")
        ut._CACHE.clear()

    print("bundled examples")
    examples = sorted((ROOT / "tools.d" / "examples").glob("*/plasbench-tool.ini"))
    check("tools.d/examples ships one manifest per output format",
          {ut.UserTool(m).get("output", "format") for m in examples if _valid_in_place(m)} == set(ut.FORMATS))
    for manifest in examples:
        check(f"example {manifest.parent.name} validates (with the files it ships)", _valid_in_place(manifest))
    check("examples are not on the search path (they are templates, never run)",
          not any(name.startswith("example") for name in ut.discover()))

    if FAILED:
        print("USER TOOL MANIFEST TESTS FAILED")
        return 1
    print("ALL USER TOOL MANIFEST TESTS PASSED")
    return 0


def _valid_in_place(manifest):
    try:
        ut.UserTool(manifest)
        return True
    except ut.ManifestError as exc:
        print(exc)
        return False


if __name__ == "__main__":
    sys.exit(main())
