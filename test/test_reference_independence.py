#!/usr/bin/env python3
"""Reference quality and reference independence are separate (second review, section 4).

A tier 2 reference polished with the benchmark's own Illumina reads can be structurally sound and
still not independent of the data it scores. This test pins:
  - truth_provenance records reference_independence and reference_group beside the tier;
  - the pipeline default (HEADLINE_REFERENCE_INDEPENDENCE=independent) keeps such a reference out of
    the primary analysis, says why when that leaves nothing, and reports the composition;
  - 'any' restores the tier-only rule, and the library default keeps older callers unchanged;
  - older provenance tables (tier only, or base_level_metrics_valid only) are read sensibly;
  - aggregation writes benchmark.reference_independence.tsv with the difference and rank change from
    the independent group, and the report shows it.
"""
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import headline_design as hd  # noqa: E402
import truth_provenance as tp  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}: {name}" + (f" ({detail})" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


def write(path, text):
    Path(path).write_text(text, encoding="utf-8")
    return str(path)


def main():
    print("truth_provenance records independence beside the tier")
    check("polish none / independent -> independent", tp.independence("none") == tp.independence("independent") == "independent")
    check("same_as_benchmark -> same_read_polished", tp.independence("same_as_benchmark") == "same_read_polished")
    check("unknown stays unknown", tp.independence("unknown") == "unknown")
    check("groups", [tp.reference_group("1", "independent"), tp.reference_group("2", "same_read_polished"),
                     tp.reference_group("2", "unknown"), tp.reference_group("3", "independent")]
          == ["tier1_independent", "tier2_same_read_polished", "tier2_unknown_independence", "tier3"])
    row = tp.derive({"sample_id": "x", "truth_assembly_strategy": "long_read_first_hybrid", "truth_polish_reads": "same_as_benchmark",
                     "truth_quality_tier": "A"}, None)
    check("a same-read-polished long-read-first reference is tier 2 and dependent",
          row["reference_tier"] == "2" and row["reference_independence"] == "same_read_polished"
          and row["reference_group"] == "tier2_same_read_polished", row)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        sheet = write(tmp / "sheet.tsv", "sample_id\tbioproject\n" + "".join(f"s{i}\tPRJ{i}\n" for i in range(6)))
        prov = write(tmp / "prov.tsv", "sample\treference_tier\ttruth_polish_reads\n"
                     "s0\t1\tnone\ns1\t2\tindependent\ns2\t2\tsame_as_benchmark\ns3\t2\tsame_as_benchmark\ns4\t2\tunknown\ns5\t3\tsame_as_benchmark\n")
        rows = [{"sample": f"s{i}", "tool": "t"} for i in range(6)]

        print("the primary analysis")
        strict = hd.Design(sample_sheet=sheet, provenance=prov, reference_independence="independent")
        sel = strict.headline_selection(rows)
        check("independent rule: only independent tier 1-2 references", sorted(r["sample"] for r in sel.rows) == ["s0", "s1"], sel.rows)
        check("the label says so", "independent of the benchmark reads" in sel.basis, sel.basis)
        check("composition names every group", strict.composition(rows)
              == "tier1_independent 1; tier2_independent 1; tier2_same_read_polished 2; tier2_unknown_independence 1; tier3 1",
              strict.composition(rows))
        anyrule = hd.Design(sample_sheet=sheet, provenance=prov, reference_independence="any")
        check("any rule: the tier alone decides", sorted(r["sample"] for r in anyrule.headline_selection(rows).rows) == ["s0", "s1", "s2", "s3", "s4"])
        check("library default is the tier-only rule (older callers unchanged)", hd.Design(provenance=prov).reference_independence == "any")
        only_dependent = write(tmp / "dep.tsv", "sample\treference_tier\ttruth_polish_reads\ns2\t2\tsame_as_benchmark\n")
        sel = hd.Design(provenance=only_dependent, reference_independence="independent").headline_selection(rows)
        check("only dependent references: unavailable, and the reason points to the sensitivity table",
              sel.status == hd.PRIMARY_UNAVAILABLE and "independent of the benchmark reads" in sel.reason and "sensitivity" in sel.reason, sel.reason)
        try:
            hd.Design(reference_independence="sometimes")
            check("an unknown rule is an error", False)
        except ValueError:
            check("an unknown rule is an error", True)

        print("older provenance tables")
        old = write(tmp / "old.tsv", "sample\treference_tier\tbase_level_metrics_valid\ns0\t1\t\ns1\t2\tyes\ns2\t2\tno\n")
        design = hd.Design(provenance=old, reference_independence="independent")
        check("tier 1 with nothing else is independent", design.independence("s0") == hd.INDEPENDENT)
        check("base_level_metrics_valid=yes is independent", design.independence("s1") == hd.INDEPENDENT)
        check("base_level_metrics_valid=no is not shown independent", design.independence("s2") == hd.UNKNOWN_INDEPENDENCE)

        print("the sensitivity table")
        scored = []
        for i, (a, b) in enumerate(((0.9, 0.6), (0.8, 0.7), (0.5, 0.9), (0.5, 0.9), (0.6, 0.6), (0.2, 0.2))):
            scored += [{"sample": f"s{i}", "tool": "A", "f1": a}, {"sample": f"s{i}", "tool": "B", "f1": b}]
        table = {(r["tool"], r["reference_group"]): r for r in hd.independence_table("short_read", "classification", scored, "f1", strict)}
        check("independent group: A ranks first", table[("A", "independent")]["rank_in_group"] == 1 and table[("B", "independent")]["rank_in_group"] == 2)
        check("same-read group: B ranks first, a rank change of -1 for B",
              table[("B", "same_read_polished")]["rank_in_group"] == 1 and table[("B", "same_read_polished")]["rank_change_vs_independent"] == -1)
        check("difference from independent", abs(table[("A", "same_read_polished")]["difference_vs_independent"] - (0.5 - 0.85)) < 1e-9)
        check("eligible-any and tier 3 rows present", ("A", "eligible_any_independence") in table and ("A", "tier3") in table)
        check("no self-difference on the independent group", table[("A", "independent")]["difference_vs_independent"] is None)

        print("aggregation and report")
        out = tmp / "out"
        out.mkdir()
        scores = out / "scores.tsv"   # the report reads the benchmark.* tables beside the scores
        write(out / "benchmark.truth_provenance.tsv", Path(prov).read_text(encoding="utf-8"))
        with open(scores, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
            writer.writerow(["sample", "tool", "true_plasmid_bp", "TP_bp", "FP_bp", "FN_bp", "unmapped_pred_bp", "precision", "recall", "f1"])
            for r in scored:
                writer.writerow([r["sample"], r["tool"], 100, 80, 20, 20, 0, r["f1"], r["f1"], r["f1"]])
        prefix = str(out / "benchmark")
        done = subprocess.run([sys.executable, str(ROOT / "python" / "aggregate_results.py"), "--scores", str(scores), "--sample-sheet", sheet,
                               "--truth-provenance", prov, "--tool-status", str(tmp / "absent.tsv"), "--headline-min-clusters", "1",
                               "--out-prefix", prefix], capture_output=True, text=True)
        check("aggregation runs", done.returncode == 0, done.stderr[-400:])
        design_rows = list(csv.DictReader(open(prefix + ".headline_design.tsv", encoding="utf-8"), delimiter="\t"))
        check("the CLI default is the independent rule", design_rows and design_rows[0]["reference_independence_rule"] == "independent", design_rows)
        check("the headline design records the composition", "tier1_independent 1" in design_rows[0]["reference_composition"], design_rows)
        independence = list(csv.DictReader(open(prefix + ".reference_independence.tsv", encoding="utf-8"), delimiter="\t"))
        check("benchmark.reference_independence.tsv is written", {r["reference_group"] for r in independence} >= {"independent", "same_read_polished"}, independence[:2])
        check("the composition is printed", "headline references by tier and independence" in done.stdout)
        (out / "tool_status.tsv").write_text("sample\ttool\tstatus\toutput\treason\tseconds\trss_kb\n", encoding="utf-8")
        report = subprocess.run([sys.executable, str(ROOT / "python" / "build_html_report.py"), "--project-root", str(ROOT),
                                 "--scores", str(scores), "--tool-status", str(out / "tool_status.tsv"),
                                 "--leaderboard", prefix + ".leaderboard.tsv", "--out", str(out / "report.html")], capture_output=True, text=True)
        html = (out / "report.html").read_text(encoding="utf-8") if (out / "report.html").is_file() else ""
        check("the report shows the reference-independence sensitivity", "Reference-independence sensitivity" in html
              and "same read polished" in html and "References by tier and independence" in html, report.stderr[-400:])

    print("ALL REFERENCE INDEPENDENCE TESTS PASSED" if not FAILED else f"REFERENCE INDEPENDENCE TESTS FAILED: {FAILED}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
