#!/usr/bin/env python3
"""The ranking-robustness and truth-label-audit report sections: content, escaping, empty states."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_report_replicon_quast import build, write_fixtures  # noqa: E402


def main():
    with tempfile.TemporaryDirectory() as d:
        paths = write_fixtures(d)
        html = build(paths, os.path.join(d, "empty.html"))
        assert "id='rank-robustness'" in html and "No ranking-robustness table" in html
        assert "id='truth-label-audit'" in html and "no audit table was available" in html
        assert "href='#rank-robustness'" in html and "href='#truth-label-audit'" in html

        robust = os.path.join(d, "r.tsv")
        with open(robust, "w") as fh:
            fh.write("analysis_track\tvariant\ttool\tmean_value\tn_samples\trank\tbaseline_rank\trank_change\t"
                     "kendall_tau_vs_baseline\ttop_tool\ttop_matches_baseline\n"
                     "short_read\tmapq_30\ttoolA\t0.9\t3\t1\t1\t0\t0.8333\ttoolA\ttrue\n"
                     "short_read\tmapq_30\ttoolB\t0.8\t3\t2\t2\t0\t0.8333\ttoolA\ttrue\n"      # same variant: one row
                     "short_read\tstrict<F1>\ttoolA\t0.7\t3\t2\t1\t1\t0.1000\ttoolB\tfalse\n")
        audit = os.path.join(d, "a.tsv")
        with open(audit, "w") as fh:
            fh.write("sample\tsequence_id\tmolecule_type\tlength\treplicon_labels\tmob_labels\tfinding\n"
                     "s1\tchromid<1>\tCHROMOSOME\t900\tIncFIB\t\tchromosome_with_plasmid_markers\n"
                     "s1\tpB\tPLASMID\t800\t\t\tplasmid_without_markers\n"
                     "s1\tpA\tPLASMID\t1000\tIncX1\t\tconsistent\n"
                     "s2\tchr\tCHROMOSOME\t5000\t\t\tnot_evaluated\n")
        html = build(paths, os.path.join(d, "full.html"), "--rank-robustness", robust,
                     "--truth-label-audit", audit)
        assert html.count("<td>mapq_30</td>") == 1, "one row per track and variant"
        assert "strict&lt;F1&gt;" in html and "strict<F1>" not in html
        assert "<td>0.1000</td><td>toolB</td><td>false</td>" in html
        assert "chromid&lt;1&gt;" in html and "chromid<1>" not in html
        assert "plasmid_without_markers" in html and "<td>pA</td>" not in html, "consistent rows are not listed"
        assert "consistent: 1" in html and "not_evaluated: 1" in html
        assert "No ranking-robustness table" not in html
    print("ALL REPORT ROBUSTNESS/AUDIT TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
