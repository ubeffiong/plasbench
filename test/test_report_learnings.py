#!/usr/bin/env python3
"""
The report sections for the PlasEval / plsMD / GAEMR additions: always present, populated when their tables exist,
and an explicit "Not run" with the reason when they do not.

Hand-checked values on the populated case:
  copy number rows log2 = 0.0 and 1.0  -> mean |log2| 0.5, fraction within a factor 1.5 (|log2| <= 0.585) = 0.5
  best-match F1 (bp) 0.8 and 0.6       -> mean 0.7
  plasmid adequacy 0.80 below the 0.90 gate -> the section says the assembly is flagged
"""

import csv
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))

import report_learnings as rl  # noqa: E402

PAGE = "<main><nav><a href='#recommendations'>Recommendations</a></nav><section id='recommendations'>x</section></main>"
TAB = chr(9)


def write(path, header, rows):
    with open(path, "w", newline="") as handle:
        w = csv.writer(handle, delimiter=TAB, lineterminator=chr(10))
        w.writerow(header)
        w.writerows(rows)


def main():
    ok = True

    def check(label, condition):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}")

    print("an empty results directory: every section present, each says why it did not run")
    with tempfile.TemporaryDirectory() as tmp:
        scores = os.path.join(tmp, "scores.tsv")
        write(scores, ["sample", "tool", "analysis_track", "f1"], [])
        page = rl.inject(PAGE, tmp, scores)
        for sid, _ in rl.SECTIONS:
            check(f"section {sid} present and linked", f"id='{sid}'" in page and f"href='#{sid}'" in page)
        check("sections sit before Recommendations", page.index("id='learn-agreement'") < page.index("id='recommendations'"))
        check("not-run notes are shown for the tables", page.count("Not run") >= 3)
        check("plsMD says it was not run", "plsMD was not run" in page)
        check("depth anomalies say they are off by default", "off by default" in page)

    print("a populated results directory shows the values")
    with tempfile.TemporaryDirectory() as tmp:
        scores = os.path.join(tmp, "scores.tsv")
        write(scores, ["sample", "tool", "analysis_track", "f1", "lw_bin_f1", "bestmatch_status", "bestmatch_f1_bp",
                       "bestmatch_f1_count", "bestmatch_contigs_excluded", "dissim_status", "bin_dissimilarity",
                       "dissim_split_cost", "dissim_join_cost"],
              [["s1", "mob_recon", "short_read", "0.9", "0.8", "ok", "0.8", "0.7", "2", "ok", "0.1", "0.05", "0.05"],
               ["s2", "mob_recon", "short_read", "0.7", "0.6", "ok", "0.6", "0.5", "1", "ok", "0.3", "0.2", "0.1"],
               ["s1", "plsmd", "short_read", "0.95", "0.9", "not_applicable_not_assembly_contigs", "", "", "", "not_applicable_not_assembly_contigs", "", "", ""]])
        write(os.path.join(tmp, "benchmark.tool_agreement.tsv"), ["tool_a", "tool_b", "n_samples", "mean_dissimilarity"],
              [["mob_recon", "platon", "2", "0.4321"]])
        write(os.path.join(tmp, "benchmark.assembly_adequacy.tsv"),
              ["sample", "assembly_status", "plasmid_adequacy", "adequate", "n_contigs", "assembly_n50", "n_chimeric",
               "chimeric_fraction", "unplaced_fraction", "reason"],
              [["s1", "ok", "0.8000", "no", "40", "150000", "1", "0.0100", "0.0200", "below 0.90"]])
        write(os.path.join(tmp, "benchmark.copy_number.tsv"),
              ["sample", "tool", "analysis_track", "true_plasmid", "bin_id", "pcn_pred", "pcn_truth", "log2_ratio", "status"],
              [["s1", "mob_recon", "short_read", "p1", "b1", "3", "3", "0.0", "ok"],
               ["s1", "mob_recon", "short_read", "p2", "b2", "6", "3", "1.0", "ok"],
               ["s2", "mob_recon", "short_read", "p1", "b1", "", "", "", "no_depth_headers"]])
        write(os.path.join(tmp, "benchmark.repeat_content.tsv"),
              ["sample", "sequence_id", "molecule_type", "length", "n_kmers", "internal_repeat_fraction",
               "chromosome_shared_fraction", "shared_with_other_plasmids_fraction", "repeat_rich", "status"],
              [["s1", "p1", "PLASMID", "50000", "49000", "0.12", "0.01", "0", "yes", "ok"]])
        page = rl.inject(PAGE, tmp, scores)
        check("best-match F1 (bp) mean 0.7000", ">0.7000<" in page)
        check("the not-applicable reassembly tool is listed with its reason",
              "not_applicable_not_assembly_contigs" in page)
        check("tool agreement row shown", ">0.4321<" in page)
        check("the flagged assembly is explained", "contain less of the truth plasmids" in page)
        check("copy number: mean |log2| 0.500 and 0.500 within a factor 1.5", page.count(">0.500<") >= 2)
        check("copy number: the unscored plasmid is named in a note", "no_depth_headers" in page)
        check("repeat-rich plasmid counted", "1 of 1 truth plasmids are repeat-rich" in page)
        check("plsMD section carries its database caveat and scores",
              "PLSDB" in page and ">0.9500<" in page)
        check("no 'Not run' for the populated tables", "Not run: benchmark.copy_number" not in page
              and "Not run: benchmark.assembly_adequacy" not in page)

    print()
    if not ok:
        print("REPORT LEARNINGS TESTS FAILED")
        sys.exit(1)
    print("ALL REPORT LEARNINGS TESTS PASSED")


if __name__ == "__main__":
    main()
