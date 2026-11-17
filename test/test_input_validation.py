#!/usr/bin/env python3
"""Damaged input tables (AU-012) and the shared-sample cliff (AU-013).

AU-012: aggregation and the report builder accepted a blank metric, a NaN, a status that contradicts the scores and a deleted column, and produced a plausible
but wrong ranking or a raw traceback. Each mutation below must now give a clear error or a visible banner:
  * blank f1 on a plasmid-bearing run       -> blank_metric (shown in the consistency table and as a banner above the ranking)
  * NaN / inf in a score column             -> non_finite_value error (read as blank only with ALLOW_INCONSISTENT_RUNS=1, and counted)
  * status failed/skipped but a score row   -> status_contradicts_score error
  * deleted metric column                   -> missing_column error
  * the report builder: a missing column or a non-numeric value is one clear message; a leaderboard paired with other scores is refused.
AU-013: with one tool missing from most samples, or two tools with disjoint samples, the ranking is flagged on the leaderboard row, in the markdown and in the report
banner, naming the tools that shrink the shared set; the numbers stay available.
"""
import csv
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
PY = os.path.join(ROOT, "python")
sys.path.insert(0, PY)
import run_consistency as rc  # noqa: E402
import aggregate_results as agg  # noqa: E402
import build_html_report as bhr  # noqa: E402

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


def read(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter=TAB))


SCORE_HEAD = ["sample", "tool", "analysis_track", "true_plasmid_bp", "TP_bp", "FP_bp", "FN_bp", "precision", "recall", "f1", "plasmid_recall", "true_plasmid_count"]
STATUS_HEAD = ["sample", "tool", "status", "prediction_fasta", "reason", "runtime_seconds", "peak_rss_kb"]
SAMPLES = ["s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8"]


def score_row(sample, tool, f1="0.8"):
    return [sample, tool, "short_read", "1000", "800", "100", "200", "0.9", "0.8", f1, "1.0", "1"]


def build(directory, scores, tools, samples=SAMPLES, status_override=None, head=SCORE_HEAD, status_rows=None):
    status = status_rows if status_rows is not None else [[s, t, (status_override or {}).get((s, t), "completed"), "", "", "10", "1000"] for s in samples for t in tools]
    write(os.path.join(directory, "scores.tsv"), head, scores)
    write(os.path.join(directory, "tool_status.tsv"), STATUS_HEAD, status)
    write(os.path.join(directory, "score_failures.tsv"), ["sample", "tool", "stage", "reason"], [])
    write(os.path.join(directory, "samples.tsv"), ["sample_id", "organism", "sample_origin", "source_study"],
          [[s, "Escherichia coli", "clinical", f"study{i}"] for i, s in enumerate(samples)])


def aggregate(directory, env=None):
    cmd = [sys.executable, os.path.join(PY, "aggregate_results.py"), "--scores", os.path.join(directory, "scores.tsv"), "--out-prefix", os.path.join(directory, "benchmark"),
           "--tool-status", os.path.join(directory, "tool_status.tsv"), "--sample-sheet", os.path.join(directory, "samples.tsv")]
    return subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, **(env or {})})


def report_cmd(directory):
    return [sys.executable, os.path.join(PY, "build_html_report.py"), "--project-root", ROOT, "--scores", os.path.join(directory, "scores.tsv"),
            "--tool-status", os.path.join(directory, "tool_status.tsv"), "--leaderboard", os.path.join(directory, "benchmark.leaderboard.tsv"),
            "--out", os.path.join(directory, "r.html")]


TOOLS = ["toolA", "toolB"]
BASE = [score_row(s, t, f"0.{7 + i % 3}") for i, s in enumerate(SAMPLES) for t in TOOLS]

with tempfile.TemporaryDirectory() as d:
    # ---- the clean table aggregates, with a fingerprint and no warning -------------------------------------------------------------------------------
    build(d, BASE, TOOLS)
    r = aggregate(d)
    check("clean tables aggregate", r.returncode == 0, r.stderr[-300:])
    check("aggregation records the fingerprint of the scores it ranked", os.path.isfile(os.path.join(d, "benchmark.input_fingerprint.json")))
    board = read(os.path.join(d, "benchmark.leaderboard.tsv"))
    check("the leaderboard has the shared-set columns, empty when the set is fine",
          all(c in board[0] for c in ("n_shared_samples", "ranking_warning", "shared_set_shrunk_by")) and all(b["ranking_warning"] == "" for b in board), board[0])

    # ---- mutation 1: a blank metric on a plasmid-bearing run ----------------------------------------------------------------------------------------
    blank = [list(row) for row in BASE]
    blank[3][9] = ""      # s2 / toolB: f1 blank although the run has a true plasmid
    build(d, blank, TOOLS)
    r = aggregate(d)
    found = read(os.path.join(d, "benchmark.input_consistency.tsv"))
    check("a blank f1 on a scored run is recorded as blank_metric (not silently averaged away)",
          r.returncode == 0 and any(f["kind"] == "blank_metric" and f["sample"] == "s2" and f["tool"] == "toolB" for f in found), (r.returncode, found, r.stderr[-200:]))
    banner = bhr.consistency_banner(Path(d))
    check("the report banner shows it above the ranking", "missing from the score table" in banner and "blank metric" in banner, banner)

    # ---- mutation 2: NaN and inf ------------------------------------------------------------------------------------------------------------------------
    for token in ("nan", "inf", "-inf"):
        bad = [list(row) for row in BASE]
        bad[2][9] = token
        build(d, bad, TOOLS)
        r = aggregate(d)
        check(f"{token} in a score column stops the aggregation with a message", r.returncode != 0 and "non_finite_value" in (r.stderr + r.stdout), (r.returncode, r.stderr[-200:]))
        r = aggregate(d, env={"ALLOW_INCONSISTENT_RUNS": "1"})
        cells = [c for row in read(os.path.join(d, "benchmark.leaderboard.tsv")) for c in row.values()]
        non_finite = [c for c in cells if c.strip().lower() in ("nan", "inf", "-inf", "+inf", "infinity")]
        check(f"{token}: with the override it is read as blank, counted, and never reaches the leaderboard",
              r.returncode == 0 and not non_finite and "NaN or infinite" in r.stdout, (r.returncode, non_finite, r.stdout[:300]))
        check(f"{token}: the banner says the tables disagree", "tables disagree" in bhr.consistency_banner(Path(d)))

    # read_scores itself: never a float('nan') in a row, always counted
    build(d, [list(BASE[0]), score_row("s9", "toolA", "nan")], TOOLS)
    rows = agg.read_scores(os.path.join(d, "scores.tsv"))
    check("read_scores turns NaN into None and counts it", rows[1]["f1"] is None and agg.read_scores.nonfinite == 1, rows[1])

    # ---- mutation 3: status failed/skipped but the tool still has scores -----------------------------------------------------------------------------
    for state in ("failed", "skipped"):
        build(d, BASE, TOOLS, status_override={("s3", "toolB"): state})
        r = aggregate(d)
        check(f"a run with status {state} that still has a score row stops the aggregation",
              r.returncode != 0 and "status_contradicts_score" in (r.stderr + r.stdout) and "s3/toolB" in (r.stderr + r.stdout), (r.returncode, r.stderr[-300:]))

    # ---- mutation 4: a deleted metric column ---------------------------------------------------------------------------------------------------------
    drop = SCORE_HEAD.index("f1")
    head = SCORE_HEAD[:drop] + SCORE_HEAD[drop + 1:]
    build(d, [row[:drop] + row[drop + 1:] for row in BASE], TOOLS, head=head)
    r = aggregate(d)
    check("a deleted f1 column stops the aggregation with missing_column", r.returncode != 0 and "missing_column" in (r.stderr + r.stdout), (r.returncode, r.stderr[-300:]))

    # ---- the report builder: clear errors, not tracebacks ---------------------------------------------------------------------------------------------
    build(d, BASE, TOOLS)
    check("setup: aggregation of the clean table", aggregate(d).returncode == 0)
    board_path = os.path.join(d, "benchmark.leaderboard.tsv")
    original = open(board_path, newline="").read()

    lines = original.split(chr(10))
    header = lines[0].split(TAB)
    cut = header.index("mean_f1")
    open(board_path, "w", newline="").write(chr(10).join(TAB.join(c for i, c in enumerate(line.split(TAB)) if i != cut) for line in lines))
    r = subprocess.run(report_cmd(d), capture_output=True, text=True)
    check("a leaderboard without mean_f1: one clear message naming the column, no traceback",
          r.returncode != 0 and "mean_f1" in r.stderr and "Traceback" not in r.stderr and "cannot be built" in r.stderr, r.stderr[-400:])

    mangled = [line.split(TAB) for line in lines]
    mangled[1][cut] = "abc"
    open(board_path, "w", newline="").write(chr(10).join(TAB.join(c) for c in mangled))
    r = subprocess.run(report_cmd(d), capture_output=True, text=True)
    check("a non-numeric leaderboard value: one clear message naming file, line and value, no traceback",
          r.returncode != 0 and "'abc'" in r.stderr and "line 2" in r.stderr and "Traceback" not in r.stderr, r.stderr[-400:])
    open(board_path, "w", newline="").write(original)

    scores_path = os.path.join(d, "scores.tsv")
    original_scores = open(scores_path, newline="").read()
    sl = original_scores.split(chr(10))
    scut = SCORE_HEAD.index("f1")
    open(scores_path, "w", newline="").write(chr(10).join(TAB.join(c for i, c in enumerate(line.split(TAB)) if i != scut) for line in sl))
    r = subprocess.run(report_cmd(d), capture_output=True, text=True)
    check("a score table without f1: one clear message, no traceback", r.returncode != 0 and "'f1'" in r.stderr and "Traceback" not in r.stderr, r.stderr[-400:])

    # scores from another run than the leaderboard's: refused (fingerprint), unless explicitly allowed
    open(scores_path, "w", newline="").write(chr(10).join(sl[:-3]) + chr(10))        # two rows fewer
    r = subprocess.run(report_cmd(d), capture_output=True, text=True)
    check("a leaderboard paired with a different score table is refused, saying why",
          r.returncode != 0 and "not from the same run" in r.stderr and "Traceback" not in r.stderr, r.stderr[-400:])
    other = [list(row) for row in BASE if row[1] == "toolA"]
    build(d, other, ["toolA"])        # same tool names ... but the leaderboard names toolB too
    open(board_path, "w", newline="").write(original)
    r = subprocess.run(report_cmd(d), capture_output=True, text=True)
    check("a leaderboard ranking a tool that is in neither the scores nor the status table is refused",
          r.returncode != 0 and "toolB" in r.stderr and "same run" in r.stderr, r.stderr[-400:])

    # validate_inputs accepts matching inputs
    build(d, BASE, TOOLS)
    aggregate(d)
    try:
        bhr.validate_inputs({"scores": bhr.read_tsv(os.path.join(d, "scores.tsv")), "tool status": bhr.read_tsv(os.path.join(d, "tool_status.tsv")),
                             "leaderboard": bhr.read_tsv(os.path.join(d, "benchmark.leaderboard.tsv"))},
                            {"scores": os.path.join(d, "scores.tsv"), "tool status": "tool_status.tsv", "leaderboard": "lb",
                             "fingerprint": os.path.join(d, "benchmark.input_fingerprint.json")})
        accepted = True
    except SystemExit as exc:
        accepted = str(exc)
    check("matching inputs are accepted", accepted is True, accepted)

# ---- AU-013: the shared-sample rule ------------------------------------------------------------------------------------------------------------------------
def shared_case(extra_tool_samples, tools=("toolA", "toolB", "toolC"), a_samples=SAMPLES, b_samples=SAMPLES, env=None):
    with tempfile.TemporaryDirectory() as d:
        scores = [score_row(s, "toolA", "0.9") for s in a_samples] + [score_row(s, "toolB", "0.8") for s in b_samples]
        if "toolC" in tools:
            scores += [score_row(s, "toolC", "0.7") for s in extra_tool_samples]
        status = [[s, "toolA", "completed", "", "", "1", "1"] for s in a_samples] + [[s, "toolB", "completed", "", "", "1", "1"] for s in b_samples]
        if "toolC" in tools:
            status += [[s, "toolC", "completed", "", "", "1", "1"] for s in extra_tool_samples]
        build(d, scores, tools, status_rows=status)
        r = aggregate(d, env)
        board = read(os.path.join(d, "benchmark.leaderboard.tsv"))
        md = open(os.path.join(d, "benchmark.leaderboard.md"), encoding="utf-8", errors="replace").read()
        return r, board, md


r, board, md = shared_case(["s1"])
check("A/B/C: a third tool scored on one sample shrinks the shared set to 1: every row is flagged", r.returncode == 0 and all(b["ranking_warning"] for b in board), (r.returncode, r.stderr[-200:], board[:1]))
check("the flag names the tool that shrinks the set and the size of the set", board and "toolC" in board[0]["shared_set_shrunk_by"] and board[0]["n_shared_samples"] == "1", board[:1])
check("the markdown leaderboard carries the warning", "RANKING WARNING" in md and "toolC" in md, md[:400])
check("the numbers stay available (own-sample mean F1 is still written)", all(b["mean_f1_all_scored"] for b in board), board[0])
check("the aggregation prints it", "SHARED-SAMPLE RULE" in r.stdout, r.stdout[-300:])

r, board, md = shared_case([], tools=("toolA", "toolB"))
check("A/B without the absent tool: no warning", r.returncode == 0 and all(b["ranking_warning"] == "" for b in board), board[:1])

r, board, md = shared_case([], tools=("toolA", "toolB"), a_samples=SAMPLES[:4], b_samples=SAMPLES[4:])
check("two tools on disjoint samples: flagged as not comparable, never a silent own-sample ranking",
      r.returncode == 0 and all("no sample is shared" in b["ranking_warning"] for b in board) and board[0]["n_shared_samples"] == "0", (r.returncode, r.stderr[-200:], board[:1]))

r, board, md = shared_case(SAMPLES[:5])
check("a third tool on 5 of 8 samples (shared 5 >= half of 8 and >= 5): not flagged", r.returncode == 0 and all(b["ranking_warning"] == "" for b in board), board[:1])
r, board, md = shared_case(SAMPLES[:3])
check("a third tool on 3 of 8 samples (shared 3 < half of 8): flagged", r.returncode == 0 and all(b["ranking_warning"] for b in board), board[:1])
r, board, md = shared_case(["s1"], env={"SHARED_MIN_FRACTION": "0.1", "SHARED_MIN_SAMPLES": "1"})
check("the limits are configurable (SHARED_MIN_FRACTION / SHARED_MIN_SAMPLES)", r.returncode == 0 and all(b["ranking_warning"] == "" for b in board), board[:1])

banner = bhr.shared_set_banner([{"analysis_track": "short_read", "task": "classification", "ranking_warning": "only 1 sample(s) are shared", "shared_set_shrunk_by": "toolC (1 sample(s))"}])
check("the report banner lists the warning and the shrinking tool", "shared-set-banner" in banner and "toolC" in banner and "only 1 sample" in banner, banner)
check("no banner when no row is flagged", bhr.shared_set_banner([{"tool": "x", "ranking_warning": ""}]) == "")

print()
print("ALL INPUT VALIDATION TESTS PASSED" if ok else "SOME INPUT VALIDATION TESTS FAILED")
sys.exit(0 if ok else 1)
