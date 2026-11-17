#!/usr/bin/env python3
"""The headline with and without the evidence-based truth exclusion (audit AU-051): python/truth_exclusion_sensitivity.py.

Hand calculation. One track, three tools. Mean F1 without the exclusion (the NCBI labels): A 0.80, B 0.70, C 0.50. With it (evidence labels): A 0.82, B 0.90, C 0.50.
  change: A +0.02, B +0.20, C 0.00; ranks without A 1, B 2, C 3; with B 1, A 2, C 3 -> B gains one rank, the top tool changes from A to B.
  B shares the MOB database with the truth markers (yes), A does not (no), C is unrecorded (unknown):
  mean change over tools sharing a database = +0.2000; over the others = (0.02 + 0.00) / 2 = +0.0100.
  Three replicons are AMBIGUOUS: two for carrying no marker, one for another reason -> 2 and 1.
It also checks the wiring: stage 6 runs it after the jobs that write its inputs, the report takes and shows it, it is a registered output and a CLI command."""
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import truth_exclusion_sensitivity as tes  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(f"  {'ok  ' if good else 'FAIL'}  {label}{'' if good else ' -> ' + str(detail)}")
    ok &= bool(good)


def write(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


RANK_HEAD = ["analysis_track", "variant", "tool", "mean_value", "n_samples", "rank", "baseline_rank", "rank_change", "kendall_tau_vs_baseline", "top_tool", "top_matches_baseline"]


def rank_rows(variant, values):
    return [["short_read", variant, tool, f"{value:.4f}", "10", "", "", "", "", "", ""] for tool, value in values.items()]


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    write(tmp / "rank.tsv", RANK_HEAD, rank_rows("baseline", {"A": 0.80, "B": 0.70, "C": 0.50}) + rank_rows("scheme:evidence", {"A": 0.82, "B": 0.90, "C": 0.50})
          + rank_rows("mapq=0", {"A": 0.1, "B": 0.1, "C": 0.1}))
    write(tmp / "overlap.tsv", ["tool", "marker_caller", "shared"], [["A", "abricate_replicon", "no"], ["A", "mob_typer", "no"], ["B", "abricate_replicon", "no"],
                                                                    ["B", "mob_typer", "yes"], ["C", "mob_typer", "unknown"]])
    write(tmp / "labels.tsv", ["sample", "sequence_id", "evidence_label", "evidence_reason"],
          [["s1", "p1", "AMBIGUOUS", "no plasmid marker (replicon, relaxase or plasmid-reference match)"], ["s1", "p2", "AMBIGUOUS", "no plasmid marker (replicon, relaxase or plasmid-reference match)"],
           ["s2", "c2", "AMBIGUOUS", "chromosome-labelled plasmid marker without rRNA genes (chromid-like)"], ["s2", "p3", "PLASMID", "plasmid marker present"]])
    out = tmp / "out.tsv"
    done = subprocess.run([sys.executable, str(ROOT / "python" / "truth_exclusion_sensitivity.py"), "--rank-robustness", str(tmp / "rank.tsv"), "--truth-marker-overlap", str(tmp / "overlap.tsv"),
                           "--label-schemes", str(tmp / "labels.tsv"), "--out", str(out)], capture_output=True, text=True)
    check("the script runs", done.returncode == 0, done.stderr)
    with open(out, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    tool = {r["tool"]: r for r in rows if r["row_kind"] == "tool"}
    group = {r["shares_truth_database"]: r for r in rows if r["row_kind"] == "group"}
    check("header is the documented columns", list(rows[0]) == tes.FIELDS, list(rows[0]))
    check("without / with / change are the hand values for A, B and C",
          [(tool[t]["mean_f1_without_exclusion"], tool[t]["mean_f1_with_exclusion"], tool[t]["delta_with_minus_without"]) for t in "ABC"]
          == [("0.8000", "0.8200", "+0.0200"), ("0.7000", "0.9000", "+0.2000"), ("0.5000", "0.5000", "+0.0000")], tool)
    check("ranks without and with the exclusion, and B gains one", [(tool[t]["rank_without_exclusion"], tool[t]["rank_with_exclusion"], tool[t]["rank_change"]) for t in "ABC"]
          == [("1", "2", "-1"), ("2", "1", "1"), ("3", "3", "0")], tool)
    check("the top tool changes from A to B", tool["A"]["top_without_exclusion"] == "A" and tool["A"]["top_with_exclusion"] == "B" and tool["A"]["top_changes"] == "yes")
    check("database sharing is the strongest recorded: A no, B yes, C unknown", [tool[t]["shares_truth_database"] for t in "ABC"] == ["no", "yes", "unknown"])
    check("mean change over tools sharing a database is +0.2000 and over the others +0.0100",
          group["yes_or_possible"]["delta_with_minus_without"] == "+0.2000" and group["no_or_unknown"]["delta_with_minus_without"] == "+0.0100", group)
    check("2 plasmids excluded for no marker, 1 replicon for another reason", tool["A"]["plasmids_excluded_marker_free"] == "2" and tool["A"]["replicons_excluded_other"] == "1")
    check("every row states the base-level-F1 limit", all("base-level F1 only" in r["scope"] for r in rows))
    check("the other variants (mapq=0) are ignored", all(r["mean_f1_without_exclusion"] != "0.1000" for r in rows))

    # With evidence as the primary scheme the baseline IS the with-exclusion ranking and scheme:ncbi the without.
    write(tmp / "rank2.tsv", RANK_HEAD, rank_rows("baseline", {"A": 0.82, "B": 0.90}) + rank_rows("scheme:ncbi", {"A": 0.80, "B": 0.70}))
    flipped = tes.build(tes.read_tsv(tmp / "rank2.tsv"), [], [], "evidence")
    check("with evidence as the primary scheme the roles swap", [r["mean_f1_without_exclusion"] for r in flipped if r["row_kind"] == "tool"] == ["0.8000", "0.7000"], flipped)
    check("without an overlap table every tool is unknown, not assumed independent", {r["shares_truth_database"] for r in flipped if r["row_kind"] == "tool"} == {"unknown"})

    # No scheme variant -> a refusal that says why, never an empty table
    write(tmp / "rank3.tsv", RANK_HEAD, rank_rows("baseline", {"A": 0.8}))
    done = subprocess.run([sys.executable, str(ROOT / "python" / "truth_exclusion_sensitivity.py"), "--rank-robustness", str(tmp / "rank3.tsv"), "--out", str(tmp / "o3.tsv")],
                          capture_output=True, text=True)
    check("a rank table with no scheme variant is refused with a reason", done.returncode != 0 and "no with/without comparison" in done.stderr and not (tmp / "o3.tsv").exists(), done.stderr)
    done = subprocess.run([sys.executable, str(ROOT / "python" / "truth_exclusion_sensitivity.py"), "--rank-robustness", str(tmp / "missing.tsv"), "--out", str(tmp / "o4.tsv")],
                          capture_output=True, text=True)
    check("a missing rank table is refused", done.returncode != 0 and "run rank_sensitivity.py first" in done.stderr)

# --- wiring --------------------------------------------------------------------------------------------
stage = (ROOT / "scripts" / "06_aggregate.sh").read_text(encoding="utf-8")
report = (ROOT / "python" / "build_html_report.py").read_text(encoding="utf-8")
surfaces = (ROOT / "python" / "report_surfaces.py").read_text(encoding="utf-8")
cli = (ROOT / "plasbench" / "cli.py").read_text(encoding="utf-8")
check("stage 6 runs it after the wait that follows rank_sensitivity, and hands the table to the report",
      stage.index("advisory_job job_candidate_multiplicity") < stage.index("\nwait\n[[ \"${RUN_TRUTH_EXCLUSION_SENSITIVITY:-1}\"")
      and stage.count("--truth-exclusion-sensitivity") == 1 and "benchmark.truth_exclusion_sensitivity.tsv" in stage)
check("the report takes --truth-exclusion-sensitivity and shows the table in the Truth labels tab with a Not run state",
      '"--truth-exclusion-sensitivity"' in report and "{marker_overlap_html}{exclusion_html}" in report and "no with/without-exclusion table was available" in report)
check("the report says the table is base-level F1 only", "Base-level F1 only" in report)
check("it is a registered output for the Artifact explorer", "benchmark.truth_exclusion_sensitivity.tsv" in surfaces)
check("it is a CLI command", '"truth-exclusion-sensitivity"' in cli)

print("ALL TRUTH EXCLUSION SENSITIVITY TESTS PASSED" if ok else "TRUTH EXCLUSION SENSITIVITY TESTS FAILED")
sys.exit(0 if ok else 1)
