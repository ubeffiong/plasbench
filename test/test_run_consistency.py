#!/usr/bin/env python3
"""run_consistency.py and aggregate_results.py: tables that disagree, stale rows, malformed numbers and synthetic-with-real runs stop the ranking with a message."""

import csv
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(HERE, "..", "python")
sys.path.insert(0, PY)
import run_consistency as rc  # noqa: E402
import data_nature as dn  # noqa: E402

TAB, NL = chr(9), chr(10)
ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


def write(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        w = csv.writer(handle, delimiter=TAB, lineterminator=NL)
        w.writerow(header)
        w.writerows(rows)


SCORE_HEAD = ["sample", "tool", "analysis_track", "true_plasmid_bp", "TP_bp", "FP_bp", "FN_bp", "precision", "recall", "f1", "plasmid_recall", "true_plasmid_count"]
STATUS_HEAD = ["sample", "tool", "status", "prediction_fasta", "reason", "runtime_seconds", "peak_rss_kb"]
SAMPLES = ["s1", "s2", "s3", "s4", "s5", "s6"]
TOOLS = ["toolA", "toolB"]


def score_row(sample, tool, f1="0.8"):
    return [sample, tool, "short_read", "1000", "800", "100", "200", "0.9", "0.8", f1, "1.0", "1"]


def status_row(sample, tool, status="completed"):
    return [sample, tool, status, "", "", "10", "1000"]


def build(directory, drop=(), extra_scores=(), extra_status=(), samples=SAMPLES):
    scores = [score_row(s, t) for s in samples for t in TOOLS if (s, t) not in drop] + list(extra_scores)
    status = [status_row(s, t) for s in samples for t in TOOLS] + list(extra_status)
    write(os.path.join(directory, "scores.tsv"), SCORE_HEAD, scores)
    write(os.path.join(directory, "tool_status.tsv"), STATUS_HEAD, status)
    write(os.path.join(directory, "score_failures.tsv"), ["sample", "tool", "stage", "reason"], [])
    write(os.path.join(directory, "samples.tsv"), ["sample_id", "organism", "sample_origin", "source_study"],
          [[s, "Escherichia coli", "clinical", f"study{i}"] for i, s in enumerate(samples)])


def aggregate(directory, env=None, extra=()):
    cmd = [sys.executable, os.path.join(PY, "aggregate_results.py"), "--scores", os.path.join(directory, "scores.tsv"), "--out-prefix", os.path.join(directory, "benchmark"),
           "--tool-status", os.path.join(directory, "tool_status.tsv"), "--sample-sheet", os.path.join(directory, "samples.tsv"), *extra]
    return subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, **(env or {})})


with tempfile.TemporaryDirectory() as d:
    build(d)
    base = aggregate(d)
    check("consistent tables aggregate normally", base.returncode == 0, base.stderr[-400:])
    check("the consistency table is written, empty", os.path.isfile(os.path.join(d, "benchmark.input_consistency.tsv"))
          and len(open(os.path.join(d, "benchmark.input_consistency.tsv")).read().splitlines()) == 1)

    findings = rc.check(os.path.join(d, "scores.tsv"), os.path.join(d, "tool_status.tsv"), os.path.join(d, "score_failures.tsv"), os.path.join(d, "samples.tsv"))
    check("no findings for consistent tables", findings == [], findings)

    # a completed run with no score row and no recorded failure
    build(d, drop={("s3", "toolB")})
    r = aggregate(d)
    check("a completed run with no score row stops the aggregation", r.returncode != 0 and "completed_without_score" in (r.stderr + r.stdout) and "s3/toolB" in (r.stderr + r.stdout),
          (r.returncode, r.stderr[-300:]))
    check("the message says how to override", "ALLOW_INCONSISTENT_RUNS=1" in r.stderr)
    r = aggregate(d, env={"ALLOW_INCONSISTENT_RUNS": "1"})
    check("the override ranks anyway and records the finding", r.returncode == 0 and "completed_without_score" in open(os.path.join(d, "benchmark.input_consistency.tsv")).read(), r.stderr[-300:])

    # recorded scoring failure is not a finding
    write(os.path.join(d, "score_failures.tsv"), ["sample", "tool", "stage", "reason"], [["s3", "toolB", "score", "paf failed"]])
    check("a recorded scoring failure is not an inconsistency", rc.check(os.path.join(d, "scores.tsv"), os.path.join(d, "tool_status.tsv"), os.path.join(d, "score_failures.tsv")) == [])

    # a failed run is not a finding either
    build(d, drop={("s3", "toolB")}, extra_status=[])
    rows = list(csv.reader(open(os.path.join(d, "tool_status.tsv")), delimiter=TAB))
    rows = [[*r[:2], "failed", *r[3:]] if r[:2] == ["s3", "toolB"] else r for r in rows]
    write(os.path.join(d, "tool_status.tsv"), rows[0], rows[1:])
    check("a failed run with no score row is not an inconsistency", rc.check(os.path.join(d, "scores.tsv"), os.path.join(d, "tool_status.tsv")) == [])

    # stale duplicate and foreign rows
    build(d, extra_scores=[score_row("s1", "toolA", "0.1"), score_row("old_sample", "toolA")])
    kinds = sorted({f["kind"] for f in rc.check(os.path.join(d, "scores.tsv"), os.path.join(d, "tool_status.tsv"), None, os.path.join(d, "samples.tsv"))})
    check("a duplicate run, a row with no status and a sample outside the sheet are all found", kinds == ["duplicate_run", "score_without_status", "unknown_sample"], kinds)
    r = aggregate(d)
    check("the stale rows stop the aggregation", r.returncode != 0 and "duplicate_run" in r.stderr, r.stderr[-300:])

    # a sample missing from the sheet is a warning only (the sheet in use is often not the run's own)
    build(d)
    write(os.path.join(d, "samples.tsv"), ["sample_id", "organism", "sample_origin", "source_study"], [["s1", "Escherichia coli", "clinical", "study0"]])
    r = aggregate(d)
    check("samples missing from the sheet warn but do not stop the aggregation", r.returncode == 0 and "unknown_sample" in open(os.path.join(d, "benchmark.input_consistency.tsv")).read(), r.stderr[-300:])

    # malformed numbers
    build(d)
    text = open(os.path.join(d, "scores.tsv")).read().replace(TAB + "0.8" + TAB + "1.0" + TAB + "1" + NL, TAB + "NaNx" + TAB + "1.0" + TAB + "1" + NL, 1)
    open(os.path.join(d, "scores.tsv"), "w").write(text)
    r = aggregate(d)
    check("a malformed number gives a message with the file and line, not a traceback", r.returncode != 0 and "malformed" in r.stderr and "line" in r.stderr and "Traceback" not in r.stderr, r.stderr[-400:])
    build(d)
    lines = open(os.path.join(d, "scores.tsv")).read().splitlines()
    lines[3] = TAB.join(lines[3].split(TAB)[:5])
    open(os.path.join(d, "scores.tsv"), "w").write(NL.join(lines) + NL)
    r = aggregate(d)
    check("a truncated row gives the same message", r.returncode != 0 and "malformed" in r.stderr and "Traceback" not in r.stderr, r.stderr[-400:])

    # synthetic with real
    build(d)
    rows = list(csv.reader(open(os.path.join(d, "samples.tsv")), delimiter=TAB))
    rows = [[*r[:2], "synthetic", r[3]] if r[0] == "s1" else r for r in rows]
    write(os.path.join(d, "samples.tsv"), rows[0], rows[1:])
    r = aggregate(d)
    check("a run that mixes synthetic and real samples is refused", r.returncode != 0 and "mixes synthetic" in r.stderr, r.stderr[-300:])

sheet = {"a": {"sample_origin": "synthetic"}, "b": {"sample_origin": "clinical"}, "c": {"truth_source": "demo_synthetic"}}
check("synthetic is read from the origin or the truth source", dn.classify(["a", "b", "c", "zz"], sheet) == (["a", "c"], ["b", "zz"]))
check("an unknown sample is never assumed synthetic", not dn.is_synthetic(sheet.get("zz")))
check("only-synthetic is allowed and recognised", dn.all_synthetic(["a", "c"], sheet) and not dn.all_synthetic(["a", "b"], sheet))
check("simulated reads from a real assembly are a separate, badged kind", not dn.is_synthetic({"truth_source": "simulated", "sample_origin": "clinical"}))
check("a banner exists and says demonstration data", "Demonstration data" in dn.BANNER)

print("ALL RUN CONSISTENCY TESTS PASSED" if ok else "RUN CONSISTENCY TESTS FAILED")
sys.exit(0 if ok else 1)
