#!/usr/bin/env python3
"""
report_inputs.py -- the table of every file the report reads and how each one can be rebuilt (config/report_inputs.tsv).

The table is the human-edited companion of the registry in report_surfaces.py. One row per file pattern:

  pattern            path under the results folder, with {sample} {tool} {track} {any} placeholders
  level              per_sample | per_tool | aggregate
  written_by         the script(s) that write it (python/ or scripts/)
  stage              1 download, 2 truth, 3 assembly, 4 tools, 5 scoring, 6 aggregation
  needs              what a fresh run needs to write it (reads, assemblies, predictions, reference, database, network ...)
  regenerable_from   the cheaper inputs it can be rebuilt from, or what must be re-run
  regen_key          the --only key of `plasbench regenerate-visuals` that rebuilds it (blank: it cannot)
  role               required (a section cannot draw without it) | enriches (a section draws less without it)
  sections           report section ids that read it

  load()                     -> list of row dicts
  by_pattern()               -> {pattern: row}
  match(relative_path)       -> the row a results-relative path belongs to, or None
  problems()                 -> what is wrong with the table (missing registry rows, writers that do not exist, bad keys)
  render_markdown()          -> docs/REPORT_INPUTS.md

Standard library only. `python3 python/report_inputs.py --write-doc` rewrites the document; `--check` exits 1 when the table has problems or
the document is stale.
"""
import argparse
import csv
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TABLE = os.path.join(ROOT, "config", "report_inputs.tsv")
DOC = os.path.join(ROOT, "docs", "REPORT_INPUTS.md")
COLUMNS = ["pattern", "level", "written_by", "stage", "needs", "regenerable_from", "regen_key", "role", "sections"]
LEVELS = ("per_sample", "per_tool", "aggregate")
ROLES = ("required", "enriches")
REGEN_KEYS = ("truth", "truth-features", "paf", "alignments", "qc", "keep")
STAGES = {"1": "1 download", "2": "2 truth", "3": "3 assembly", "4": "4 tools", "5": "5 scoring", "6": "6 aggregation"}


def load(path=TABLE):
    with open(path, encoding="utf-8", newline="") as handle:
        lines = [line for line in handle if line.strip() and not line.startswith("#")]
    return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(lines, delimiter="\t")]


def by_pattern(rows=None):
    return {row["pattern"]: row for row in (rows if rows is not None else load())}


def _regex(pattern):
    out = ""
    for part in re.split(r"(\{[a-z0-9_]+\})", pattern):
        if part.startswith("{") and part.endswith("}"):
            out += "[^/]+" if part != "{any}" else ".+"
        else:
            out += re.escape(part)
    return re.compile("^" + out + "$")


def match(relative_path, rows=None):
    """The row that a results-relative path (forward slashes) belongs to, most specific first; None when it is in no row."""
    relative_path = relative_path.replace("\\", "/")
    best = None
    for row in (rows if rows is not None else load()):
        if _regex(row["pattern"]).match(relative_path):
            if best is None or len(row["pattern"]) > len(best["pattern"]):
                best = row
    return best


def writer_exists(token, root=ROOT):
    """A `written_by` token names a file under python/ or scripts/ (or a glob such as scripts/*.sh)."""
    token = token.strip()
    if not token:
        return False
    if "*" in token:
        return bool(glob.glob(os.path.join(root, token)))
    if token.endswith(".py"):
        return os.path.isfile(os.path.join(root, "python", token))
    if token.endswith(".sh"):
        return os.path.isfile(os.path.join(root, token if token.startswith("scripts/") else os.path.join("scripts", token)))
    return False


def problems(rows=None, root=ROOT):
    """A list of plain-language problems; empty when the table covers the registry and every writer exists."""
    sys.path.insert(0, HERE)
    import report_surfaces
    rows = rows if rows is not None else load()
    found = []
    seen = set()
    for row in rows:
        if row["pattern"] in seen:
            found.append(f"{row['pattern']}: listed twice")
        seen.add(row["pattern"])
        if row["level"] not in LEVELS:
            found.append(f"{row['pattern']}: level '{row['level']}' is not one of {LEVELS}")
        if row["role"] not in ROLES:
            found.append(f"{row['pattern']}: role '{row['role']}' is not one of {ROLES}")
        if row["regen_key"] and row["regen_key"] not in REGEN_KEYS:
            found.append(f"{row['pattern']}: regen_key '{row['regen_key']}' is not one of {REGEN_KEYS}")
        if row["stage"] not in STAGES:
            found.append(f"{row['pattern']}: stage '{row['stage']}' is not one of {sorted(STAGES)}")
        for column in ("needs", "regenerable_from", "written_by"):
            if not row[column]:
                found.append(f"{row['pattern']}: {column} is empty")
        for token in [t for t in row["written_by"].split(" / ") if t.strip()]:
            if not writer_exists(token, root):
                found.append(f"{row['pattern']}: writer '{token}' does not exist under python/ or scripts/")
    registry = [entry["pattern"] for entry in report_surfaces._file_entries()]
    for pattern in registry:
        if pattern not in seen:
            found.append(f"{pattern}: read by the report (report_surfaces.py) but not in config/report_inputs.tsv")
    for pattern in sorted(seen - set(registry)):
        found.append(f"{pattern}: in config/report_inputs.tsv but not in the report_surfaces.py registry")
    return found


def render_markdown(rows=None):
    rows = rows if rows is not None else load()
    out = ["# Report inputs: what each part of the report reads, who writes it, and what it can be rebuilt from",
           "",
           "Generated from [`config/report_inputs.tsv`](../config/report_inputs.tsv) by `python3 python/report_inputs.py --write-doc`; edit the table, not this page.",
           "The table has one row for every file the report reads (the registry in `python/report_surfaces.py`); a test fails when a file is read but not listed, or when a writer named here does not exist.",
           "",
           "`plasbench check-results RESULTS_DIR` says which sections of a given folder can draw; `plasbench regenerate-visuals RESULTS_DIR` rebuilds the files marked below with a `--only` key.",
           "",
           "- **required**: the section cannot draw without the file. **enriches**: it draws less without it.",
           "- **--only key**: the part of `plasbench regenerate-visuals` that rebuilds the file from cheaper inputs. `keep` copies a small table from the data folder into the results folder. A blank key means the file can only be rebuilt by re-running a stage (see the column).",
           ""]
    for level, title in (("per_sample", "Per sample"), ("per_tool", "Per sample and tool"), ("aggregate", "Per run (results folder top level)")):
        part = [r for r in rows if r["level"] == level]
        out += [f"## {title} ({len(part)} files)", "", "| File | Written by | Stage | Needs | Rebuild from | --only | Role | Sections |", "|---|---|---|---|---|---|---|---|"]
        for r in part:
            cells = [f"`{r['pattern']}`", r["written_by"], STAGES.get(r["stage"], r["stage"]), r["needs"], r["regenerable_from"],
                     f"`{r['regen_key']}`" if r["regen_key"] else "none", r["role"], ", ".join(f"`{s}`" for s in r["sections"].split(",") if s) or "none"]
            out.append("| " + " | ".join(c.replace("|", "/") for c in cells) + " |")
        out.append("")
    out += ["## Figure sections from branches that are not merged yet", "",
            "`fig-presence` (presence/absence matrix), `fig-facets` (plasmid-level facets) and `fig-fingerprint` (fingerprints at plasmid level) are listed against `visualization/alignment_blocks.json` in the table. "
            "When those branches merge, add their other inputs to the table; the test then holds the table to the registry.", ""]
    return "\n".join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--write-doc", action="store_true", help="rewrite docs/REPORT_INPUTS.md")
    parser.add_argument("--check", action="store_true", help="exit 1 on problems or a stale document")
    args = parser.parse_args(argv)
    rows = load()
    bad = problems(rows)
    for line in bad:
        print("PROBLEM:", line)
    text = render_markdown(rows)
    if args.write_doc:
        with open(DOC, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        print(f"Wrote {DOC} ({len(rows)} rows)")
    if args.check:
        try:
            stale = open(DOC, encoding="utf-8", newline="").read() != text
        except OSError:
            stale = True
        if stale:
            print("docs/REPORT_INPUTS.md is stale: run python3 python/report_inputs.py --write-doc")
        return 1 if bad or stale else 0
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
