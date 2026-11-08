#!/usr/bin/env python3
"""run_manifest.json must list selected candidates for BOTH layouts: the benchmark
(stage 6) one and the operational (stage 8) one. It once saw only the second."""

import os
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))

import write_manifest as wm  # noqa: E402


def main():
    ok = True

    def check(label, condition):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}")

    with tempfile.TemporaryDirectory() as tmp:
        results = Path(tmp)
        bench = results / "selected_candidates" / "s1"
        bench.mkdir(parents=True)
        (bench / "s1.selection_report.json").write_text("{}", encoding="utf-8")
        (bench / "s1.candidate.plasmid.fasta").write_text(">p\nA\n", encoding="utf-8")
        oper = results / "s2" / "selected_candidate"
        oper.mkdir(parents=True)
        (oper / "selection_report.json").write_text("{}", encoding="utf-8")
        (oper / "candidate.plasmid.fasta").write_text(">p\nA\n", encoding="utf-8")

        warnings = []
        found = wm.collect_selected_candidates(results, warnings)
        print("both layouts")
        check("the benchmark layout is listed", "s1" in found)
        check("the operational layout is listed", "s2" in found)
        check("the benchmark entry names its files", "s1.candidate.plasmid.fasta" in found["s1"]["files"])
        check("each entry carries a checksummed report", all("selection_report" in v for v in found.values()))
        check("no warnings for well-formed reports", not warnings)

        print("a sample present in both layouts is reported once")
        both = results / "s1" / "selected_candidate"
        both.mkdir(parents=True)
        (both / "selection_report.json").write_text("{}", encoding="utf-8")
        check("one entry for s1", list(wm.collect_selected_candidates(results, [])).count("s1") == 1)

        print("an empty results directory")
        with tempfile.TemporaryDirectory() as empty:
            check("is an empty mapping, not an error", wm.collect_selected_candidates(Path(empty), []) == {})

    print()
    if not ok:
        print("MANIFEST SELECTED-CANDIDATE TESTS FAILED")
        sys.exit(1)
    print("ALL MANIFEST SELECTED-CANDIDATE TESTS PASSED")


if __name__ == "__main__":
    main()
