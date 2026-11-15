#!/usr/bin/env python3
"""
metric_registry.py -- the one place that says what each metric is FOR.

config/metrics.tsv lists every metric PlasBench reports with the facts that are not the wording of its definition (that stays in the report's glossary, `GLOSSARY` in
build_html_report.py, and the two are cross-checked by test/test_metric_wiring.py):

  id              stable snake_case identifier
  term            the glossary term that defines it (blank when the metric has no glossary term; the scorecard name is its name then)
  rung            where it sits on the reconstruction evaluation ladder (RUNGS) or `efficiency` (cost, outside the ladder)
  tool_types      reconstruction | classification | all: whose output it can score
  required_inputs what must exist for it to be computed
  rankable        yes when it is an endpoint a ranking is built on, no when it is only reported
  evidence        published_definition (a published definition, re-implemented and tested) | project_defined (defined by PlasBench) | unvalidated (an alignment-derived
                  estimate with no independent check) | not_available (no data to compute it)
  source, column  the table and column that hold its value (leaderboard / scores / accuracy / ngoc / ...)
  scorecard_id    A1 ... E3 when it is one of the scorecard's metrics (config/scorecard.tsv)
  shown_in        the report section id where it appears
  limitations     what it does not show

The ladder (five rungs, each a different question; a tool can do well on one and badly on the next):
  detection, sequence recovery, binning, sequence reconstruction, biological validity.
A rung with no ranked or validated metric is a GAP the report states, not a rung that is fine.

`load()` validates the file (columns, unique ids, vocabularies) and raises ValueError naming the row. Standard library only.
"""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "config" / "metrics.tsv"
COLUMNS = ("id", "term", "rung", "tool_types", "required_inputs", "rankable", "evidence", "source", "column", "scorecard_id", "shown_in", "limitations")
RUNGS = (("detection", "Detection", "Did the tool identify plasmid-derived sequence?"),
         ("sequence_recovery", "Sequence recovery", "How much of each reference plasmid was recovered?"),
         ("binning", "Binning", "Were the right contigs put together into the right plasmid?"),
         ("sequence_reconstruction", "Sequence reconstruction", "Does the recovered plasmid match the reference in sequence and structure?"),
         ("biological_validity", "Biological validity", "Were resistance genes and other features kept, in the right plasmid?"))
EFFICIENCY = ("efficiency", "Computational efficiency", "What the answer cost in time and memory, and how reliably it was produced.")
RUNG_IDS = tuple(r[0] for r in RUNGS) + (EFFICIENCY[0],)
TOOL_TYPES = ("reconstruction", "classification", "all")
EVIDENCE = ("published_definition", "project_defined", "unvalidated", "not_available")
EVIDENCE_LABEL = {"published_definition": "published definition", "project_defined": "defined by PlasBench", "unvalidated": "unvalidated estimate", "not_available": "not available"}


def load(path=None):
    """The validated rows of config/metrics.tsv (dicts), in file order."""
    path = Path(path or DEFAULT)
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError(f"{path}: columns must be {', '.join(COLUMNS)}")
        rows = list(reader)
    seen = set()
    for number, row in enumerate(rows, start=2):
        name = row["id"].strip()
        if not name or not name.replace("_", "").isalnum() or name != name.lower():
            raise ValueError(f"{path} row {number}: id must be lower-case snake_case (got '{row['id']}')")
        if name in seen:
            raise ValueError(f"{path} row {number}: duplicate id {name}")
        seen.add(name)
        for column, allowed in (("rung", RUNG_IDS), ("tool_types", TOOL_TYPES), ("rankable", ("yes", "no")), ("evidence", EVIDENCE)):
            if row[column] not in allowed:
                raise ValueError(f"{path} row {number} ({name}): {column} must be one of {', '.join(allowed)} (got '{row[column]}')")
        for column in ("source", "column", "shown_in", "limitations", "required_inputs"):
            if not row[column].strip():
                raise ValueError(f"{path} row {number} ({name}): {column} is empty")
    return rows


def by_term(rows=None):
    """{glossary term: row} for the metrics that have a glossary term."""
    return {r["term"]: r for r in (rows if rows is not None else load()) if r["term"]}


def ladder(rows=None):
    """[(rung id, title, question, [rows])] for the five rungs, then the efficiency group, in order."""
    rows = rows if rows is not None else load()
    return [(rid, title, question, [r for r in rows if r["rung"] == rid]) for rid, title, question in list(RUNGS) + [EFFICIENCY]]


def gaps(rows=None):
    """The gaps of the ladder, stated plainly: (rung id, reason) for each rung with no metric that rests on a published definition and for each rung with
    no metric used for ranking."""
    out = []
    for rid, title, _question, members in ladder(rows)[:-1]:
        if not any(m["evidence"] == "published_definition" for m in members):
            out.append((rid, f"{title}: no metric rests on a published definition; every one is defined by PlasBench or is an unvalidated estimate"))
        if not any(m["rankable"] == "yes" for m in members):
            out.append((rid, f"{title}: no metric on this rung is used for ranking"))
    return out


if __name__ == "__main__":
    for rid, title, question, members in ladder():
        print(f"{title}: {question}")
        for m in members:
            print(f"  {m['id']:<26} {m['rankable']:<3} {m['evidence']}")
    for rid, text in gaps():
        print("GAP:", text)
