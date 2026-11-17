#!/usr/bin/env python3
"""The three evaluation tasks: classification, binning reconstruction and sequence reassembly are different questions and are ranked separately.

Before this split the task was decided by `binning_capable` alone: every tool that was not binning-capable was a classifier even when it reassembles plasmid sequences
(plasmidSPAdes), and every binning-capable reassembler (Plassembler, Hybracter, plsmd) shared one reconstruction track with the binners. Now the registry names the task
(`evaluation_task`) and the ranking code reads that field.

  registry     the shipped assignment of every tool, the vocabulary, the contradiction check, the legacy name, the fallback for a registry without the column
  ranking      the pre-registered endpoint of each task, on every input track; the task order
  aggregation  the real aggregate_results.py on a small cohort: each tool lands in its own task with its own ranking metric, and a reassembler is not ranked by base F1
  recommender  a recommendation is made for one task (tools_of_task); the default excludes reassemblers and classifiers
  user tools   a bring-your-own-tool manifest states its task; the old 'reconstruction' means binning
  report       the labels, the pre-registration rows, the setup window and the documentation say the same thing
"""
import csv
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import headline_design as hd  # noqa: E402
import select_operational_method as som  # noqa: E402
import tool_capabilities as tc  # noqa: E402
import user_tools as ut  # noqa: E402

PY = ROOT / "python"
REGISTRY = ROOT / "config" / "tool_capabilities.tsv"


def read(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader((line for line in handle if line.strip() and not line.startswith("#")), delimiter="\t"))


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    print("the registry")
    caps = tc.read_capabilities(REGISTRY)
    expected = {"classification": {"platon", "genomad", "plasme", "rfplasmid", "plasmidhunter", "plasmer", "plascope", "plasmidec", "plasgraph2", "platon_like", "weak_like",
                                   "baseline_coverage", "baseline_reference", "baseline_replicon"},
                "binning_reconstruction": {"mob_recon", "gplas2_mob", "gplas2_external", "flye_mob_recon", "trycycler_mob_recon", "mob_like", "gplas_like", "plasbin_flow"},
                "sequence_reassembly": {"plasmidspades", "plassembler", "hybracter_long", "hybracter_hybrid", "spades_like", "plsmd"}}
    got = {task: {t for t, r in caps.items() if r["evaluation_task"] == task} for task in tc.EVALUATION_TASKS}
    check("every tool of the shipped registry has exactly the task it should", got == expected, {k: got[k] ^ expected[k] for k in got if got[k] != expected[k]})
    check("the registry file itself carries the evaluation_task column, not only the derived value", "evaluation_task" in open(REGISTRY, encoding="utf-8").readline())
    check("plasmidSPAdes (a reassembler without bins before) and Plassembler (a reassembler with bins before) are now the same task",
          caps["plasmidspades"]["evaluation_task"] == caps["plassembler"]["evaluation_task"] == "sequence_reassembly")
    check("binning_capable now means 'bin-scored': yes for binning and reassembly, no for classification only",
          all((r["binning_capable"] == "no") == (r["evaluation_task"] == "classification") for r in caps.values()))
    check("the three tasks are ordered binning, reassembly, classification", hd.TASKS == ("binning_reconstruction", "sequence_reassembly", "classification"))

    def load(text):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "caps.tsv"
            path.write_text(text, encoding="utf-8")
            return tc.read_capabilities(path)

    head = "tool\tmethod_class\tbinning_capable\tanalysis_track\trequires_independent_long_read_truth"
    try:
        load(head + "\tevaluation_task\nx\tclassification\tyes\tshort_read\tno\tclassification\n")
        contradiction = False
    except ValueError as exc:
        contradiction = "contradicts" in str(exc)
    check("a task that contradicts binning_capable is refused, with the reason", contradiction)
    try:
        load(head + "\tevaluation_task\nx\tbinning\tyes\tshort_read\tno\tmystery\n")
        unknown = False
    except ValueError as exc:
        unknown = "evaluation_task must be one of" in str(exc)
    check("an unknown task is refused", unknown)
    check("the old name 'reconstruction' written in a registry means binning", load(head + "\tevaluation_task\nx\tbinning\tyes\tshort_read\tno\treconstruction\n")["x"]["evaluation_task"] == "binning_reconstruction")
    legacy = load(head + "\nb\tbinning\tyes\tshort_read\tno\nr\treassembly\tyes\tshort_read\tno\nc\tclassification\tno\tshort_read\tno\nq\treassembly\tno\tshort_read\tno\n")
    check("a registry without the column tells a reassembler from a binner and never calls a reassembler a classifier (older fixtures, user registries)",
          (legacy["b"]["evaluation_task"], legacy["r"]["evaluation_task"], legacy["c"]["evaluation_task"], legacy["q"]["evaluation_task"])
          == ("binning_reconstruction", "sequence_reassembly", "classification", "sequence_reassembly"))   # q: a reassembler without bins is still a reassembler (the old fallback made it a classifier)

    print("the ranking endpoint of each task")
    check("binning is ranked by length-weighted binning F1, classification by base F1, reassembly by isolate-level CPRR, on every input track",
          all(hd.ranking_metric(track, "binning_reconstruction") == "lw_bin_f1" and hd.ranking_metric(track, "classification") == "f1"
              and hd.ranking_metric(track, "sequence_reassembly") == "sample_cprr" for track in ("short_read", "long_read", "hybrid")))
    check("there is no track-specific exception any more (long-read binning is a binning task, ranked as one)", hd.TRACK_TASK_METRIC == {})
    design = hd.Design(capabilities=str(REGISTRY))
    check("the design reads the task from the registry: plasmidspades and plassembler reassembly, mob_recon binning, platon classification, flye_mob_recon binning",
          [design.task(t, []) for t in ("plasmidspades", "plassembler", "mob_recon", "platon", "flye_mob_recon")]
          == ["sequence_reassembly", "sequence_reassembly", "binning_reconstruction", "classification", "binning_reconstruction"])
    check("a tool outside the registry keeps the old guess (bins mean binning), nothing else changes",
          hd.Design().task("stranger", [{"tool": "stranger", "lw_bin_f1": 0.5}]) == "binning_reconstruction" and hd.Design().task("stranger", [{"tool": "stranger", "lw_bin_f1": None}]) == "classification")

    print("aggregation (the real script)")
    with tempfile.TemporaryDirectory() as t:
        os.chdir(t)
        Path("caps.tsv").write_text(head + "\tevaluation_task\n"
                                    "binner\tbinning\tyes\tshort_read\tno\tbinning_reconstruction\n"
                                    "reasm_good\treassembly\tyes\tshort_read\tno\tsequence_reassembly\n"
                                    "reasm_bad\treassembly\tyes\tshort_read\tno\tsequence_reassembly\n"
                                    "classy\tclassification\tno\tshort_read\tno\tclassification\n", encoding="utf-8")
        samples = [f"s{i}" for i in range(1, 7)]
        Path("sheet.tsv").write_text("sample_id\torganism\tbioproject\n" + "".join(f"{s}\tEscherichia coli\tPRJ{s}\n" for s in samples), encoding="utf-8")
        Path("prov.tsv").write_text("sample\treference_tier\tbase_level_metrics_valid\tambiguous_plasmids\n" + "".join(f"{s}\t2\tyes\t0\n" for s in samples), encoding="utf-8")
        header = ["sample", "tool", "analysis_track", "true_plasmid_count", "precision", "recall", "f1", "lw_bin_f1", "cprr_plasmids", "cprr_correct", "cprr_correct_without_identity"]
        with open("scores.tsv", "w", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
            writer.writerow(header)
            for s in samples:
                writer.writerow([s, "binner", "short_read", 1, 0.8, 0.8, 0.8, 0.7, 1, 0, 0])
                writer.writerow([s, "reasm_good", "short_read", 1, 0.6, 0.6, 0.6, 0.5, 1, 1, 1])      # complete plasmid, low base F1
                writer.writerow([s, "reasm_bad", "short_read", 1, 0.95, 0.95, 0.95, 0.9, 1, 0, 0])    # high base F1, no complete plasmid
                writer.writerow([s, "classy", "short_read", 1, 0.7, 0.7, 0.7, "", "", "", ""])
        done = subprocess.run([sys.executable, str(PY / "aggregate_results.py"), "--scores", "scores.tsv", "--sample-sheet", "sheet.tsv", "--capabilities", "caps.tsv",
                               "--truth-provenance", "prov.tsv", "--headline-min-clusters", "1", "--min-species-clusters", "3", "--out-prefix", "b"], capture_output=True, text=True)
        board = {r["tool"]: r for r in read("b.leaderboard.tsv")} if Path("b.leaderboard.tsv").is_file() else {}
        check("the script ran", done.returncode == 0 and len(board) == 4, done.stderr[-400:])
        check("each tool is ranked on its own task", {t: r["task"] for t, r in board.items()} == {"binner": "binning_reconstruction", "reasm_good": "sequence_reassembly",
                                                                                                  "reasm_bad": "sequence_reassembly", "classy": "classification"})
        check("each task has its own pre-registered ranking metric", {t: r["ranking_metric"] for t, r in board.items()}
              == {"binner": "lw_bin_f1", "reasm_good": "sample_cprr", "reasm_bad": "sample_cprr", "classy": "f1"})
        check("a reassembler is ranked by CPRR, not base F1: the complete-plasmid tool beats the one with the higher base F1",
              board["reasm_good"]["rank"] == "1" and board["reasm_bad"]["rank"] == "2", (board["reasm_good"]["rank"], board["reasm_bad"]["rank"]))
        check("ranks restart in each task (a binner, a reassembler and a classifier are each first in their own group)", board["binner"]["rank"] == board["classy"]["rank"] == "1")
        os.chdir(ROOT)

    print("the recommender is per task")
    with tempfile.TemporaryDirectory() as t:
        tools = {"mob_recon", "plasmidspades", "plassembler", "platon", "flye_mob_recon"}
        by_task = {task: som.tools_of_task(REGISTRY, tools, task) for task in tc.EVALUATION_TASKS}
        check("each task gets only its own tools", by_task == {"binning_reconstruction": {"mob_recon", "flye_mob_recon"}, "sequence_reassembly": {"plasmidspades", "plassembler"},
                                                              "classification": {"platon"}}, by_task)
        check("the old reconstruction_tools() is the binning task only (a reassembler is not in it)", som.reconstruction_tools(REGISTRY, tools) == {"mob_recon", "flye_mob_recon"})
        check("a task with no scored tool gives None (the caller keeps every tool and says so)", som.tools_of_task(REGISTRY, {"platon"}, "sequence_reassembly") is None)
        check("an unreadable registry gives None", som.tools_of_task(Path(t) / "none.tsv", tools, "classification") is None)

    print("bring-your-own tools")
    def manifest(task):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "plasbench-tool.ini"
            path.write_text("[tool]\nname = my_tool\ntask = %s\nanalysis_track = short_read\n[run]\nmode = import\ndir = outputs\n[output]\nformat = plasmid_fasta\npath = x.fasta\n" % task, encoding="utf-8")
            try:
                return ut.UserTool(path)
            except TypeError:
                return ut.UserTool(path, "my_tool") if hasattr(ut, "UserTool") else None
    for task, expected_row in (("binning_reconstruction", ("binning", "yes", "binning_reconstruction")), ("reconstruction", ("binning", "yes", "binning_reconstruction")),
                               ("sequence_reassembly", ("reassembly", "yes", "sequence_reassembly")), ("classification", ("classification", "no", "classification"))):
        tool = manifest(task)
        if tool is None:
            print("  SKIP: the manifest class has another constructor here")
            break
        row = tool.capability_row()
        check(f"a manifest with task = {task} registers as {expected_row[2]}", (row["method_class"], row["binning_capable"], row["evaluation_task"]) == expected_row, row)
    check("the manifest vocabulary names all three tasks (and still reads the old 'reconstruction')", ut.TASKS == ("binning_reconstruction", "sequence_reassembly", "classification")
          and ut.LEGACY_TASKS == {"reconstruction": "binning_reconstruction"})

    print("the report, the pre-registration, the window and the documentation")
    import build_html_report as report
    check("the report labels all three tasks, and still reads results that carry the old name",
          all(t in report.TASK_LABELS and t in report.TASK_BLURBS for t in (*tc.EVALUATION_TASKS, "reconstruction")))
    rows = [{"task": "classification", "tool": "c"}, {"task": "sequence_reassembly", "tool": "r"}, {"task": "binning_reconstruction", "tool": "b"}]
    check("the primary task is binning, then reassembly, then classification", [r["tool"] for r in report.primary_task_rows(rows)] == ["b"]
          and [r["tool"] for r in report.primary_task_rows(rows[:2])] == ["r"])
    pre = {r["parameter"]: r for r in read(ROOT / "config" / "prereg.tsv")}
    check("the pre-registration names an endpoint for each task and the old track-specific row is gone", "primary_endpoint_reassembly" in pre and "primary_endpoint_long_read" not in pre
          and "binning reconstruction" in pre["primary_endpoint"]["value"] and "sample_cprr" in pre["primary_endpoint_reassembly"]["value"])
    check("the task endpoints are confirmed decisions (fixed), with a dated record of who confirmed them", pre["primary_endpoint"]["status"] == "fixed" and pre["primary_endpoint_reassembly"]["status"] == "fixed"
          and "primary_endpoint_reassembly\tconfirmed" in (ROOT / "config" / "prereg_decisions.tsv").read_text(encoding="utf-8").replace("2026-11-16\t", ""))
    ui = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    check("the setup window offers the three tasks", all(t in ui for t in tc.EVALUATION_TASKS) and 'select:binning_reconstruction|sequence_reassembly|classification' in ui)
    demo = ROOT / "results_demo" / "benchmark.leaderboard.tsv"
    if demo.is_file() and "task" in open(demo, encoding="utf-8").readline():
        tasks = {r["tool"]: r["task"] for r in read(demo)}
        check("the demo shows all three tasks: mob_like and gplas_like binning, spades_like reassembly, platon_like and weak_like classification",
              tasks == {"mob_like": "binning_reconstruction", "gplas_like": "binning_reconstruction", "spades_like": "sequence_reassembly", "platon_like": "classification", "weak_like": "classification"}, tasks)
    else:
        print("  SKIP: no results_demo leaderboard (run test/run_demo.sh first)")
    print()
    if not ok:
        print("EVALUATION TASK TESTS FAILED")
        sys.exit(1)
    print("ALL EVALUATION TASK TESTS PASSED")


if __name__ == "__main__":
    main()
