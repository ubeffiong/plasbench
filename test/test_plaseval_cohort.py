#!/usr/bin/env python3
"""The PlasEval-paper cohort (53 E. coli isolates) and its replication on the paper's own published bins.

Checks that the cohort sheet is consistent with the shipped data, that PlasBench's numbers on real bins are internally sound
(shares sum to the dissimilarity, values in range), and that the report page is produced. The comparison with the original
program on these bins needs a PlasEval checkout and is run by hand (docs/PLASEVAL_REPLICATION.md); it is not part of this test.
"""
import csv
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
import plaseval_replication as pr  # noqa: E402
import report_fig_binerrors as fig  # noqa: E402

COHORT = os.path.join(ROOT, "cohorts", "plaseval-ecoli53.tsv")
BINS = os.path.join(ROOT, "cohorts", "plaseval_ecoli53", "bins")
ok = True


def check(label, good, detail=""):
    global ok
    print(f"  {'ok  ' if good else 'FAIL'}  {label}{'' if good else ' -> ' + str(detail)}")
    ok &= bool(good)


def cohort_rows():
    with open(COHORT, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader((l for l in handle if l.strip() and not l.startswith("#")), delimiter="\t"))


rows = cohort_rows()
print("cohort sheet")
check("53 isolates, all Escherichia coli, one BioProject", len(rows) == 53 and {r["organism"] for r in rows} == {"Escherichia coli"}
      and {r["bioproject"] for r in rows} == {"PRJNA912639"})
check("sample ids and BioSamples are unique", len({r["sample_id"] for r in rows}) == 53 and len({r["biosample"] for r in rows}) == 53)
check("accessions have the right shape", all(r["assembly_accession"].startswith("GCA_") and r["sra_run"].startswith("SRR")
                                            and r["long_read_sra_run"].startswith("SRR") and r["biosample"].startswith("SAMN")
                                            for r in rows))
check("the short-read and long-read runs differ", all(r["sra_run"] != r["long_read_sra_run"] for r in rows))
check("truth provenance is recorded honestly: short-read-first, polished with the benchmark's reads",
      {r["truth_assembly_strategy"] for r in rows} == {"short_read_first_hybrid"}
      and {r["truth_polish_reads"] for r in rows} == {"same_as_benchmark"})
check("not claimed as tier A before review", {r["truth_quality_tier"] for r in rows} == {"B"})
check("every isolate has a folder of the paper's bins", set(pr.samples_in(BINS)) == {r["sample_id"] for r in rows})
counts_ok = True
for r in rows:
    truth, _ = pr.read_bins(os.path.join(BINS, r["sample_id"], "ground_truth_bins.tsv"))
    counts_ok &= len(truth) == int(r["assembly_plasmid_count"])
check("assembly_plasmid_count equals the plasmid bins of each isolate's ground truth", counts_ok)
check("184 plasmid bins in all (the paper's text says 190; recorded in the sheet header)",
      sum(int(r["assembly_plasmid_count"]) for r in rows) == 184)
done = subprocess.run([sys.executable, os.path.join(ROOT, "python", "validate_cohort.py"), "--samples", COHORT],
                      capture_output=True, text=True)
check("the cohort sheet passes the schema validator", done.returncode == 0 and "COHORT VALIDATION PASSED: 53" in done.stdout,
      done.stdout[-300:] + done.stderr[-300:])
check("the data licence and source are stated", "CC BY 4.0" in open(os.path.join(ROOT, "cohorts", "plaseval_ecoli53", "README.md"),
                                                                     encoding="utf-8").read())

print("replication on the paper's bins (first five isolates)")
tmp = tempfile.mkdtemp(prefix="plaseval_rep_")
try:
    subset = os.path.join(tmp, "bins")
    os.makedirs(subset)
    for sample in pr.samples_in(BINS)[:5]:
        shutil.copytree(os.path.join(BINS, sample), os.path.join(subset, sample))
    out = os.path.join(tmp, "out")
    code = pr.main(["--bins-dir", subset, "--out-dir", out, "--no-original"])
    check("the harness runs", code == 0)
    with open(os.path.join(out, "plaseval_replication.scores.tsv"), newline="", encoding="utf-8") as handle:
        scores = list(csv.DictReader(handle, delimiter="\t"))
    check("one row per isolate and tool (5 x 4)", len(scores) == 20 and {r["tool"] for r in scores} == set(pr.TOOL_FILES))
    check("every row was computed", {r["dissim_status"] for r in scores} == {"ok"} and {r["bestmatch_status"] for r in scores} == {"ok"})
    check("dissimilarity and best-match scores are in range",
          all(0 <= float(r["bin_dissimilarity"]) <= 1 and 0 <= float(r["bestmatch_f1_bp"]) <= 1 for r in scores))
    check("the four shares add up to the dissimilarity on real bins",
          all(abs(sum(fig.parts_of(r).values()) - float(r["bin_dissimilarity"])) < 1e-4 for r in scores))
    check("the length exponents 0 and 1 are recorded", all(r["bin_dissimilarity_alpha0"] and r["bin_dissimilarity_alpha1"] for r in scores))
    check("the first isolate's truth has nine plasmids, as in the cohort sheet",
          {r["n_truth_plasmids"] for r in scores if r["sample"] == "EC_0012_3S1_D"} == {"9"})
    check("repeated contigs occur in this real data and are searched", any(int(r["dissim_repeat_families"]) > 0 for r in scores))
    with open(os.path.join(out, "benchmark.tool_agreement.tsv"), newline="", encoding="utf-8") as handle:
        matrix = list(csv.DictReader(handle, delimiter="\t"))
    check("tool-by-tool and tool-by-truth agreement are written (6 pairs + 4 truth rows)", len(matrix) == 10)
    page = open(os.path.join(out, "plaseval_replication.html"), encoding="utf-8").read()
    check("the report page has the charts, the data credit and says the original was not run",
          "Error profile by tool." in page and "Zenodo 10.5281/zenodo.10785150" in page and "was not run on these bins" in page
          and page.count("<svg") >= 6)
    print("rebuilding the page from a run's saved tables")
    progress = os.path.join(out, "plaseval_replication.original_progress.tsv")
    with open(os.path.join(out, "plaseval_replication.scores.tsv"), newline="", encoding="utf-8") as handle:
        first = list(csv.DictReader(handle, delimiter=chr(9)))
    T, N = chr(9), chr(10)
    with open(progress, "w", encoding="utf-8") as handle:
        handle.write(T.join(["sample", "tool", "original_dissimilarity", "status"]) + N)
        for i, r in enumerate(first):
            if i == 0:
                handle.write(T.join([r["sample"], r["tool"], "", "timeout"]) + N)                        # the original timed out on this pair
            else:
                handle.write(T.join([r["sample"], r["tool"], f"{float(r['bin_dissimilarity']):.6f}", "ok"]) + N)   # and agreed on the rest
    out2 = os.path.join(tmp, "rebuilt")
    code = pr.main(["--out-dir", out2, "--from-tsv", out, "--bins-dir", subset])
    page2 = open(os.path.join(out2, "plaseval_replication.html"), encoding="utf-8").read()
    check("--from-tsv rebuilds the page and merges the streamed original results", code == 0 and "Comparison with the original PlasEval program: PARTIAL" in page2
          and "19 of 20 isolate-tool pairs were compared" in page2, page2[page2.find("Comparison with"):][:300])
    check("the pair the original did not finish is listed, not filled in", "Pairs the original program did not finish" in page2 and "timeout" in page2)
    check("the rebuilt page draws the PlasBench-against-original scatter", "PlasBench against the original program" in page2)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("ALL PLASEVAL COHORT TESTS PASSED" if ok else "PLASEVAL COHORT TESTS FAILED")
sys.exit(0 if ok else 1)
