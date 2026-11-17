#!/usr/bin/env python3
"""Do the run tables agree before anything is ranked?

A leaderboard is only as honest as the tables under it. This checks that scores.tsv, tool_status.tsv, score_failures.tsv and the sample sheet describe the
same runs, and reports every disagreement, because each one changes a ranking without any error:

  duplicate_run            the same sample and tool scored twice (an old run left in the folder); the averages mix both
  completed_without_score  a run finished, but it has no score row and no recorded scoring failure; the tool is then ranked on fewer samples
  score_without_status     a score row for a sample the status table does not list for a tool it does list (a stale or foreign row)
  tool_without_status      a tool with scores but no status rows at all (the status table does not cover it): a WARNING
  unknown_sample           a score row for a sample that is not in the sample sheet (a WARNING: the sheet in use is often a different file from the run's own)
  missing_column           scores.tsv lacks a column every ranking needs (sample, tool, f1, precision, recall): the tool would be ranked on nothing, or every value read as absent
  non_finite_value         a NaN or infinite number in a score column (read as blank, so the mean silently covers fewer runs)
  status_contradicts_score the status table says a run failed or was skipped, yet a score row exists for it (the table the ranking trusts disagrees with itself)
  blank_metric             a plasmid-bearing run with a blank ranking metric (f1): a WARNING that is always shown above the ranking, because that run drops out of the mean

Duplicate, completed_without_score, score_without_status, missing_column, non_finite_value and status_contradicts_score are errors: aggregation stops unless ALLOW_INCONSISTENT_RUNS=1 (--allow-inconsistent-runs), in which case the findings are written to
benchmark.input_consistency.tsv and the report puts a banner above the leaderboard. A run that failed, timed out or was skipped is not a finding: those
are scored zero or left out by the ranking rules and shown in Run health.
"""
import csv
import math
import os
import sys
from collections import Counter

SHOULD_HAVE_SCORE = {"completed", "reused"}
SHOULD_NOT_HAVE_SCORE = {"failed", "skipped"}
FIELDS = ["kind", "severity", "sample", "tool", "detail"]
WARNING_KINDS = {"unknown_sample", "tool_without_status", "blank_metric"}
# Warnings the report shows above the ranking anyway (the others only go to the console and the table): a blank ranking metric shrinks a mean.
BANNER_WARNING_KINDS = {"blank_metric"}
REQUIRED_COLUMNS = ("sample", "tool", "f1", "precision", "recall")
NOT_NUMERIC = {"sample", "tool", "analysis_track"}


def _rows(path):
    if not path or not os.path.isfile(path):
        return None
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _number(text):
    """float for a numeric cell, None for a blank or non-numeric one."""
    try:
        return float(text) if text not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _scores_header(path):
    if not path or not os.path.isfile(path):
        return None
    with open(path, newline="", encoding="utf-8") as handle:
        return handle.readline().rstrip("\r\n").split("\t")


def check(scores_path, status_path=None, failures_path=None, sample_sheet=None):
    """Findings (list of dicts) for the run tables. The status and sample-sheet checks run only when those tables were given."""
    scores = _rows(scores_path) or []
    status = _rows(status_path)
    failures = _rows(failures_path) or []
    sheet = _rows(sample_sheet)
    found = []
    header = _scores_header(scores_path)
    if header is not None:
        for column in REQUIRED_COLUMNS:
            if column not in header:
                found.append(("missing_column", "", "", f"scores.tsv has no '{column}' column, so every value of it would read as absent (columns found: {', '.join(header[:8])}...)"))
    nonfinite = Counter()
    for r in scores:
        for column, value in r.items():
            if column in NOT_NUMERIC or value in (None, ""):
                continue
            number = _number(value)
            if number is not None and not math.isfinite(number):
                nonfinite[(r.get("sample", ""), r.get("tool", ""), column)] += 1
    for (sample, tool, column), n in sorted(nonfinite.items()):
        found.append(("non_finite_value", sample, tool, f"{column} is NaN or infinite; it is treated as blank, so the mean covers one run fewer"))
    for r in scores:
        count = _number(r.get("true_plasmid_count"))
        if count and count > 0 and r.get("f1", "x") == "" and (_number(r.get("true_plasmid_bp")) or 1) > 0:
            found.append(("blank_metric", r.get("sample", ""), r.get("tool", ""), "f1 is blank on a run with true plasmids, so this run is left out of the tool's mean"))
    keys = [(r.get("sample", ""), r.get("tool", "")) for r in scores]
    for (sample, tool), n in sorted(Counter(keys).items()):
        if n > 1:
            found.append(("duplicate_run", sample, tool, f"{n} score rows for this run; the averages mix them"))
    scored = set(keys)
    if status is not None:
        status_keys = {(r.get("sample", ""), r.get("tool", "")) for r in status}
        recorded = {(r.get("sample", ""), r.get("tool", "")) for r in failures}
        for r in status:
            key = (r.get("sample", ""), r.get("tool", ""))
            if r.get("status") in SHOULD_HAVE_SCORE and key not in scored and key not in recorded:
                found.append(("completed_without_score", key[0], key[1], f"status '{r.get('status')}' but no score row and no scoring failure recorded"))
        for r in status:
            key = (r.get("sample", ""), r.get("tool", ""))
            if r.get("status") in SHOULD_NOT_HAVE_SCORE and key in scored:
                found.append(("status_contradicts_score", key[0], key[1], f"status '{r.get('status')}' but a score row exists for this run (a stale score, or a wrong status)"))
        status_tools = {t for _, t in status_keys}
        for sample, tool in sorted(scored - status_keys):
            if tool in status_tools:
                found.append(("score_without_status", sample, tool, "a score row for a run the status table does not list, though it lists this tool"))
        for tool in sorted({t for _, t in scored} - status_tools):
            found.append(("tool_without_status", "", tool, "scores exist but the status table has no row for this tool"))
    if sheet:
        known = {r.get("sample_id") or r.get("sample") for r in sheet}
        known.discard(None)
        if known:
            for sample in sorted({s for s, _ in scored} - known):
                found.append(("unknown_sample", sample, "", "not in the sample sheet"))
    return [dict(zip(FIELDS, (kind, "warning" if kind in WARNING_KINDS else "error", sample, tool, detail))) for kind, sample, tool, detail in found]


def write(path, findings):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(findings)


def fingerprint(scores_path):
    """{'scores_rows', 'scores_sha256'} of a score table: the row count and a hash of the sorted (sample, tool, f1) cells.

    aggregate_results.py records it beside the leaderboard (benchmark.input_fingerprint.json); build_html_report.py recomputes it from the scores it was given and
    refuses to pair a leaderboard with scores from another run. Only three columns are hashed, so a column added later by an advisory step does not matter."""
    import hashlib
    rows = _rows(scores_path) or []
    cells = sorted((r.get("sample", ""), r.get("tool", ""), r.get("f1", "")) for r in rows)
    digest = hashlib.sha256("\n".join("\t".join(c) for c in cells).encode("utf-8")).hexdigest()
    return {"scores_rows": len(rows), "scores_sha256": digest}


def banner_findings(findings):
    """The findings the report shows above the ranking: every error, and the warnings that change a mean (blank_metric)."""
    return [f for f in findings if f.get("severity", "error") == "error" or f.get("kind") in BANNER_WARNING_KINDS]


def summary(findings, limit=8):
    lines = [f"  {f['kind']}: {f['sample']}{'/' + f['tool'] if f['tool'] else ''}: {f['detail']}" for f in findings[:limit]]
    if len(findings) > limit:
        lines.append(f"  ... and {len(findings) - limit} more (benchmark.input_consistency.tsv)")
    return "\n".join(lines)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scores", required=True)
    ap.add_argument("--tool-status")
    ap.add_argument("--score-failures")
    ap.add_argument("--sample-sheet")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    findings = check(args.scores, args.tool_status, args.score_failures, args.sample_sheet)
    if args.out:
        write(args.out, findings)
    print(summary(findings) if findings else "run tables agree")
    return 1 if any(f["severity"] == "error" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
