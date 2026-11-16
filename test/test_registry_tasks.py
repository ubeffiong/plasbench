#!/usr/bin/env python3
"""The shipped capability registry declares every tool's evaluation task explicitly, and the fallback for a row that does not is strict (third review, P0).

  - every built-in row has an explicit, valid evaluation_task (nothing is derived at run time);
  - plasmidSPAdes, plassembler and the Hybracter modes are sequence_reassembly; MOB-recon is binning_reconstruction; Platon is classification;
  - the derivation for a row without the field: a reassembler is never a classifier (even with binning_capable=no), contradictions are errors, and a derived task is reported on stderr;
  - the explicit task and binning_capable cannot contradict each other.
"""
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import tool_capabilities as tc  # noqa: E402


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    with open(ROOT / "config" / "tool_capabilities.tsv", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    check("the registry has an evaluation_task column", "evaluation_task" in rows[0])
    check("every built-in tool declares a valid evaluation_task explicitly", all((r.get("evaluation_task") or "") in tc.EVALUATION_TASKS for r in rows),
          [r["tool"] for r in rows if (r.get("evaluation_task") or "") not in tc.EVALUATION_TASKS])
    by_tool = {r["tool"]: tc.evaluation_task(r) for r in rows}
    expected = {"plasmidspades": "sequence_reassembly", "plassembler": "sequence_reassembly", "hybracter_long": "sequence_reassembly", "hybracter_hybrid": "sequence_reassembly",
                "mob_recon": "binning_reconstruction", "gplas2_mob": "binning_reconstruction", "platon": "classification", "genomad": "classification"}
    check("PlasmidSPAdes is sequence_reassembly (not a classifier); the other anchors are as documented", all(by_tool[t] == v for t, v in expected.items()),
          {t: by_tool[t] for t in expected})
    check("the registry as read by the pipeline agrees", all(tc.read_capabilities(ROOT / "config" / "tool_capabilities.tsv")[t]["evaluation_task"] == v for t, v in expected.items()))

    print("the derivation for a row without the field")
    check("reassembly with binning_capable=no is sequence_reassembly (the old fallback made it a classifier)",
          tc.derived_task({"tool": "x", "method_class": "reassembly", "binning_capable": "no"}) == "sequence_reassembly")
    check("binning_capable=yes is binning_reconstruction", tc.derived_task({"tool": "x", "method_class": "binning", "binning_capable": "yes"}) == "binning_reconstruction")
    check("no bins and a classifier class is classification", tc.derived_task({"tool": "x", "method_class": "ml_classification", "binning_capable": "no"}) == "classification")
    for label, row in (("a classifier that is bin-scored", {"tool": "x", "method_class": "classification", "binning_capable": "yes"}),
                       ("a binner that is not bin-scored", {"tool": "x", "method_class": "binning", "binning_capable": "no"})):
        try:
            tc.derived_task(row)
            check(f"{label} is an error", False)
        except ValueError as error:
            check(f"{label} is an error that says to state the task", "evaluation_task" in str(error))
    with tempfile.TemporaryDirectory() as tmp:
        old = Path(tmp) / "old.tsv"
        old.write_text("tool\tmethod_class\tbinning_capable\tanalysis_track\trequires_independent_long_read_truth\n"
                       "spades_like\treassembly\tno\tshort_read\tno\n", encoding="utf-8")
        done = subprocess.run([sys.executable, str(ROOT / "python" / "tool_capabilities.py"), "--registry", str(old), "--tool", "spades_like", "--evaluation-task"], capture_output=True, text=True)
        check("an older registry row is derived, and the derivation is reported on stderr",
              done.stdout.strip() == "sequence_reassembly" and "declares no evaluation_task" in done.stderr, (done.stdout, done.stderr))
        bad = Path(tmp) / "bad.tsv"
        bad.write_text("tool\tmethod_class\tbinning_capable\tanalysis_track\trequires_independent_long_read_truth\tevaluation_task\n"
                       "x\tclassification\tno\tshort_read\tno\tbinning_reconstruction\n", encoding="utf-8")
        try:
            tc.read_capabilities(bad)
            check("an explicit task that contradicts binning_capable is rejected", False)
        except ValueError as error:
            check("an explicit task that contradicts binning_capable is rejected", "contradicts" in str(error))
    print("ALL REGISTRY TASK TESTS PASSED" if ok else "REGISTRY TASK TESTS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
