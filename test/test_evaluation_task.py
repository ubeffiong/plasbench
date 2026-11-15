#!/usr/bin/env python3
"""Every tool is ranked in the task its output contract declares (second review, section 3).

A tool that produces no bins used to be ranked as a contig classifier, so plasmidSPAdes, a
reassembler, was ranked against Platon. config/tool_capabilities.tsv now declares
evaluation_task (binning_reconstruction | sequence_reassembly | classification) and
headline_design ranks from it. This test pins the registry, the mapping, the fallback for an
older registry or a user manifest, and that the three tasks never share a leaderboard.
"""
import csv
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
import headline_design as hd  # noqa: E402
import aggregate_results as ag  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}: {name}" + (f" ({detail})" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


def registry():
    with open(os.path.join(ROOT, "config", "tool_capabilities.tsv"), encoding="utf-8") as fh:
        return list(csv.DictReader((l for l in fh if l.strip() and not l.startswith("#")), delimiter="\t"))


def main():
    rows = registry()
    print("the registry declares a task for every tool")
    check("every row has a valid evaluation_task",
          all(r.get("evaluation_task") in hd.EVALUATION_TASKS for r in rows),
          [r["tool"] for r in rows if r.get("evaluation_task") not in hd.EVALUATION_TASKS])
    check("binning_reconstruction and sequence_reassembly tools are bin-scored (a reassembler's records are its own bins)",
          all(r["binning_capable"] == "yes" for r in rows if r["evaluation_task"] != "classification"))
    check("classification tools declare no bins", all(r["binning_capable"] == "no" for r in rows if r["evaluation_task"] == "classification"))
    check("every row says what its output unit is",
          all(r.get("output_unit") in ("plasmid_bins", "plasmid_records", "enriched_contigs", "contig_labels") for r in rows))
    by_tool = {r["tool"]: r for r in rows}
    check("plasmidSPAdes is a reassembler, not a classifier", hd.evaluation_task(by_tool["plasmidspades"]) == hd.TASK_REASSEMBLY)
    check("Platon is a classifier", hd.evaluation_task(by_tool["platon"]) == hd.TASK_CLASSIFICATION)
    check("MOB-recon is binning and reconstruction", hd.evaluation_task(by_tool["mob_recon"]) == hd.TASK_RECONSTRUCTION)
    check("a one-plasmid-per-record tool (Plassembler) is sequence reassembly and says its output unit",
          hd.evaluation_task(by_tool["plassembler"]) == hd.TASK_REASSEMBLY and by_tool["plassembler"]["output_unit"] == "plasmid_records")

    print("rows without the column (older registry, user tool)")
    check("binning_capable=yes -> reconstruction", hd.evaluation_task({"binning_capable": "yes"}) == hd.TASK_RECONSTRUCTION)
    check("reassembly class that declares bins -> reassembly (bin-scored)",
          hd.evaluation_task({"binning_capable": "yes", "method_class": "reassembly"}) == hd.TASK_REASSEMBLY)
    check("anything else -> classification", hd.evaluation_task({"binning_capable": "no", "method_class": "ml_classification"}) == hd.TASK_CLASSIFICATION)
    try:
        hd.evaluation_task({"tool": "x", "evaluation_task": "binning"})
        check("an unknown declared task is an error", False)
    except ValueError:
        check("an unknown declared task is an error", True)

    print("ranking keeps the three tasks apart")
    with tempfile.TemporaryDirectory() as d:
        caps = os.path.join(d, "caps.tsv")
        with open(caps, "w", encoding="utf-8") as fh:
            fh.write("tool\tmethod_class\tbinning_capable\tanalysis_track\tevaluation_task\n"
                     "binner\tbinning\tyes\tshort_read\tbinning_reconstruction\n"
                     "reasm\treassembly\tyes\tshort_read\tsequence_reassembly\n"
                     "clf\tclassification\tno\tshort_read\tclassification\n")
        design = hd.Design(capabilities=caps)
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from test_aggregate_failures import row, status_counts  # the shared score-row fixture
        score_rows = []
        for sample in ("s1", "s2"):
            for tool, f1 in (("binner", 0.9), ("reasm", 0.8), ("clf", 0.7)):
                r = row(sample, tool, f1)
                r["lw_bin_f1"] = 0.85 if tool in ("binner", "reasm") else None
                r["sample_cprr"] = 0.5 if tool == "reasm" else None
                score_rows.append(r)
        check("design tasks", [design.task(t, score_rows) for t in ("binner", "reasm", "clf")]
              == [hd.TASK_RECONSTRUCTION, hd.TASK_REASSEMBLY, hd.TASK_CLASSIFICATION])
        groups = {(t, k) for t, k, *_ in ag.ranked_tracks(score_rows, status_counts(), design=design)}
        check("three separate leaderboards", groups == {("short_read", "binning_reconstruction"), ("short_read", "sequence_reassembly"),
                                                       ("short_read", "classification")}, groups)
        check("a reassembler is ranked by isolate-level CPRR, a binner by binning F1, a classifier by base F1",
              [hd.ranking_metric("short_read", t) for t in (hd.TASK_REASSEMBLY, hd.TASK_BINNING, hd.TASK_CLASSIFICATION)] == ["sample_cprr", "lw_bin_f1", "f1"])

    print("metrics say which tasks they can score")
    import metric_registry as mr
    metrics = {r["id"]: r for r in mr.load()}
    check("the registry's task vocabulary is the ranking's", set(mr.TASK_TYPES) == set(hd.TASKS))
    check("binning metrics apply to the bin-scored tasks (binning and reassembly) and never to a classifier",
          all(mr.applies_to(metrics[m], t) for m in ("lw_bin_f1", "bin_f1", "cprr", "amr_prr") for t in ("reconstruction", "reassembly"))
          and all(not mr.applies_to(metrics[m], "classification") for m in ("lw_bin_f1", "bin_f1", "cprr", "amr_prr")))
    check("base-level F1 applies to every task", all(mr.applies_to(metrics["base_f1"], t) for t in mr.TASK_TYPES))
    check("AMR placement applies to every task (sequence attribution for classifiers and reassemblers)", mr.applies_to(metrics["amr_placement"], "reassembly"))
    with tempfile.TemporaryDirectory() as d:
        bad = os.path.join(d, "metrics.tsv")
        with open(os.path.join(ROOT, "config", "metrics.tsv"), encoding="utf-8") as fh:
            text = fh.read()
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write(text.replace("\tall\t", "\tbinning+all\t", 1))   # 'binning' is not a task
        try:
            mr.load(bad)
            check("an unknown task in tool_types is rejected", False)
        except ValueError:
            check("an unknown task in tool_types is rejected", True)

    print("ALL EVALUATION TASK TESTS PASSED" if not FAILED else f"EVALUATION TASK TESTS FAILED: {FAILED}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
