#!/usr/bin/env python3
"""Regression checks for the pre-specified research design.

1. Endpoints: length-weighted binning F1 and per-plasmid CPRR (score_bins.py).
2. Reference standard: truth provenance -> tiers (truth_provenance.py).
3. Evidence-based replicon labels with an AMBIGUOUS class (label_truth_evidence.py).
4. Clonal groups (clonal_groups.py).
5. Headline: task tracks, tier filter, species macro-average, CPRR identity
   rule, negative-control guard (aggregate_results.py + headline_design.py).
6. Cohort composition warnings and provenance vocabulary (validate_cohort.py).
"""

import csv
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(HERE, "..", "python")


def run(args, check=True):
    return subprocess.run([sys.executable] + args, check=check, capture_output=True, text=True)


def write(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        handle.write(text)


def read(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def check(ok, label, condition, detail=""):
    print(f"  {label} -> {bool(condition)}{(' ' + detail) if detail else ''}")
    return ok and bool(condition)


def endpoints(ok):
    write("truth.tsv", "sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t100000\np1\tPLASMID\t10000\n"
                       "p2\tPLASMID\t2000\n")
    write("bins.tsv", "sequence_id\tbin_id\nc1\tB1\nc2\tB2\nc3\tB2\n")
    # p1: whole, but 98% identity (fails only the identity criterion);
    # p2: half, in a bin contaminated with chromosome.
    write("a.paf", "c1\t10000\t0\t10000\t+\tp1\t10000\t0\t10000\t9800\t10000\t60\n"
                   "c2\t1000\t0\t1000\t+\tp2\t2000\t0\t1000\t1000\t1000\t60\n"
                   "c3\t500\t0\t500\t+\tchr\t100000\t0\t500\t500\t500\t60\n")
    run([os.path.join(PY, "score_bins.py"), "--truth", "truth.tsv", "--paf", "a.paf", "--bins", "bins.tsv",
         "--out", "m.tsv", "--summary", "s.tsv", "--cprr-out", "c.tsv"])
    summary = read("s.tsv")[0]
    ok = check(ok, "length-weighted bin precision 11000/11500", summary["lw_bin_precision"] == "0.9565")
    ok = check(ok, "length-weighted bin recall 11000/12000", summary["lw_bin_recall"] == "0.9167")
    ok = check(ok, "count-based bin_f1 kept (0.5)", summary["bin_f1"] == "0.5000")
    cprr = {r["true_plasmid"]: r for r in read("c.tsv")}
    ok = check(ok, "p1 correct without identity, fails identity",
               cprr["p1"]["correct_without_identity"] == "yes" and cprr["p1"]["correct"] == "no")
    ok = check(ok, "p2 not correctly reconstructed", cprr["p2"]["correct_without_identity"] == "no")
    ok = check(ok, "summary CPRR counts", (summary["cprr_plasmids"], summary["cprr_correct"],
                                           summary["cprr_correct_without_identity"]) == ("2", "0", "1"))
    return ok


def provenance(ok):
    def report(sample, method, tech):
        write(os.path.join("data", sample, "assembly_data_report.jsonl"),
              json.dumps({"assemblyInfo": {"assemblyMethod": method, "sequencingTech": tech}}) + "\n")

    report("flye_ill", "Flye v. 2.9; Polypolish", "Oxford Nanopore MinION; Illumina NovaSeq")
    report("unicyc", "Unicycler v. 0.4.8", "Illumina MiSeq; Oxford Nanopore GridION")
    report("lr_only", "Trycycler v. 0.5", "Oxford Nanopore PromethION")
    write(os.path.join("data", "lr_only", "truth_labels.tsv"),
          "sequence_id\tsource_label\tfinal_label\tevidence_status\tmarker_free\n"
          "c\tCHROMOSOME\tCHROMOSOME\tevaluated\t\np\tPLASMID\tAMBIGUOUS\tevaluated\tyes\n")
    write("sheet.tsv", "sample_id\ttruth_source\ttruth_quality_tier\ttruth_polish_reads\n"
                       "flye_ill\tncbi_deposited\tA\t\nunicyc\tncbi_deposited\tA\t\nlr_only\tncbi_deposited\tA\t\n"
                       "selfbuilt\tself_assembled_hybrid\tB\t\nnone\tncbi_deposited\tA\t\n")
    run([os.path.join(PY, "truth_provenance.py"), "--sample-sheet", "sheet.tsv", "--data-dir", "data",
         "--out", "prov.tsv"])
    p = {r["sample"]: r for r in read("prov.tsv")}
    ok = check(ok, "Flye + Illumina -> long-read-first, same reads, tier 2",
               (p["flye_ill"]["truth_assembly_strategy"], p["flye_ill"]["truth_polish_reads"],
                p["flye_ill"]["reference_tier"], p["flye_ill"]["base_level_metrics_valid"])
               == ("long_read_first_hybrid", "same_as_benchmark", "2", "no"))
    ok = check(ok, "Unicycler -> short-read-first, tier 3",
               (p["unicyc"]["truth_assembly_strategy"], p["unicyc"]["reference_tier"]) == ("short_read_first_hybrid", "3"))
    ok = check(ok, "Trycycler, no Illumina, tier A, evidence-checked -> tier 1",
               (p["lr_only"]["reference_tier"], p["lr_only"]["base_level_metrics_valid"],
                p["lr_only"]["ambiguous_plasmids"], p["lr_only"]["marker_free_plasmids"]) == ("1", "yes", "1", "1"))
    ok = check(ok, "self-built hybrid truth -> tier 3", p["selfbuilt"]["reference_tier"] == "3")
    ok = check(ok, "no metadata -> unknown, tier 3",
               (p["none"]["truth_assembly_strategy"], p["none"]["reference_tier"]) == ("unknown", "3"))
    write("sheet_bad.tsv", "sample_id\ttruth_assembly_strategy\nx\tguesswork\n")
    bad = run([os.path.join(PY, "truth_provenance.py"), "--sample-sheet", "sheet_bad.tsv", "--out", "x.tsv"], check=False)
    ok = check(ok, "invalid strategy value is rejected", bad.returncode != 0)
    return ok


def labels(ok):
    write("ref.fa", ">chr\nAAAA\n>chr2\nAAAA\n>p1\nAAAA\n>p2\nAAAA\n>p3\nAAAA\n>p4\nAAAA\n")
    write("t.tsv", "sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t5000000\nchr2\tCHROMOSOME\t1000000\n"
                   "p1\tPLASMID\t90000\np2\tPLASMID\t4000\np3\tPLASMID\t60000\np4\tPLASMID\t3000\n")
    write("feat.tsv", "sequence_id\tstart\tend\tfeature_type\tlabel\tsource\tversion\n"
                      "chr\t0\t1500\trRNA\t16S_rRNA\tbarrnap\t1\np1\t0\t90000\treplicon\tIncFII\tmob_typer\t1\n"
                      "p3\t0\t60000\tmob\tMOBP\tmob_typer\t1\np3\t100\t1600\trRNA\t16S_rRNA\tbarrnap\t1\n"
                      "p4\t0\t3000\treplicon\tCol440I\tmob_typer\t1\n")
    write("prov.json", json.dumps({"callers": {"mob_typer": {"status": "ok"}, "barrnap": {"status": "ok"}}}))
    write("lr.tsv", "sequence_id\tlength\tmean_depth\treads\nchr\t5000000\t60\t1\nchr2\t1000000\t55\t1\n"
                    "p1\t90000\t70\t1\np2\t4000\t40\t1\np3\t60000\t50\t1\np4\t3000\t1.5\t1\n")
    run([os.path.join(PY, "label_truth_evidence.py"), "--truth", "t.tsv", "--reference", "ref.fa",
         "--features", "feat.tsv", "--annotation-provenance", "prov.json", "--long-read-depth", "lr.tsv",
         "--labels-out", "labels.tsv", "--scored-truth-out", "scored.tsv"])
    lab = {r["sequence_id"]: r for r in read("labels.tsv")}
    ok = check(ok, "chromosome with rRNA stays CHROMOSOME", lab["chr"]["final_label"] == "CHROMOSOME")
    ok = check(ok, "secondary chromosome without rRNA -> AMBIGUOUS (chromid-like)", lab["chr2"]["final_label"] == "AMBIGUOUS")
    ok = check(ok, "plasmid with replicon -> PLASMID", lab["p1"]["final_label"] == "PLASMID")
    ok = check(ok, "marker-free plasmid -> AMBIGUOUS, marker_free=yes",
               lab["p2"]["final_label"] == "AMBIGUOUS" and lab["p2"]["marker_free"] == "yes")
    ok = check(ok, "plasmid carrying rRNA -> AMBIGUOUS", lab["p3"]["final_label"] == "AMBIGUOUS")
    ok = check(ok, "low long-read depth -> AMBIGUOUS", lab["p4"]["final_label"] == "AMBIGUOUS")
    scored = {r["sequence_id"]: r["molecule_type"] for r in read("scored.tsv")}
    ok = check(ok, "scored truth keeps only confirmed replicons", scored == {"chr": "CHROMOSOME", "p1": "PLASMID"})
    write("prov_none.json", json.dumps({"callers": {"mob_typer": {"status": "not_evaluated"}}}))
    run([os.path.join(PY, "label_truth_evidence.py"), "--truth", "t.tsv", "--reference", "ref.fa",
         "--annotation-provenance", "prov_none.json", "--labels-out", "labels2.tsv", "--scored-truth-out", "scored2.tsv"])
    ok = check(ok, "no evidence -> source labels kept, nothing excluded",
               len(read("scored2.tsv")) == 6 and all(r["evidence_status"] == "not_evaluated" for r in read("labels2.tsv")))
    return ok


def clonal(ok):
    write("csheet.tsv", "sample_id\tclonal_group\na\tST131\nb\tST131\nc\t\n")
    run([os.path.join(PY, "clonal_groups.py"), "--sample-sheet", "csheet.tsv", "--out", "clonal.tsv"])
    g = {r["sample"]: r["clonal_group"] for r in read("clonal.tsv")}
    ok = check(ok, "declared clonal groups are shared", g["a"] == g["b"] == "declared:ST131" and g["c"] == "isolate:c")
    return ok


def headline(ok):
    # 2 species x 3 independent isolates each, plus one tier-3 sample and one
    # zero-plasmid sample whose plasmid was evidence-labelled AMBIGUOUS.
    samples = [("e1", "Escherichia coli"), ("e2", "Escherichia coli"), ("e3", "Escherichia coli"),
               ("k1", "Klebsiella pneumoniae"), ("k2", "Klebsiella pneumoniae"), ("k3", "Klebsiella pneumoniae"),
               ("t3", "Escherichia coli"), ("z0", "Escherichia coli")]
    write("hsheet.tsv", "sample_id\torganism\tbioproject\n" + "".join(f"{s}\t{o}\tPRJ{s}\n" for s, o in samples))
    write("hprov.tsv", "sample\treference_tier\tbase_level_metrics_valid\tambiguous_plasmids\n"
                       + "".join(f"{s}\t{'3' if s == 't3' else '2'}\t{'yes' if s.startswith('e') else 'no'}\t"
                                 f"{'1' if s == 'z0' else '0'}\n" for s, _ in samples))
    write("caps.tsv", "tool\tmethod_class\tbinning_capable\tanalysis_track\n"
                      "binner\tbinning\tyes\tshort_read\nbinner2\tbinning\tyes\tshort_read\n"
                      "classy\tclassification\tno\tshort_read\n")
    header = ["sample", "tool", "analysis_track", "true_plasmid_count", "precision", "recall", "f1",
              "lw_bin_f1", "cprr_plasmids", "cprr_correct", "cprr_correct_without_identity",
              "isolate_specificity", "chromosome_fp_bp"]
    rows = []
    # binner: E. coli 0.9, Klebsiella 0.5 on lw_bin_f1; base F1 deliberately inverted (0.6).
    # binner2: E. coli 0.6, Klebsiella 0.7 -> pooled 0.65 < binner 0.70, macro 0.65 < 0.70.
    for s, organism in samples:
        if s == "z0":
            for tool in ("binner", "binner2", "classy"):
                rows.append([s, tool, "short_read", 0, "", "", "", "", "", "", "", "0.99", 100])
            continue
        ecoli = organism.startswith("Escherichia")
        rows.append([s, "binner", "short_read", 1, 0.6, 0.6, 0.6, 0.9 if ecoli else 0.5, 1, 0, 1, "", ""])
        rows.append([s, "binner2", "short_read", 1, 0.9, 0.9, 0.9, 0.6 if ecoli else 0.7, 1, 1, 1, "", ""])
        rows.append([s, "classy", "short_read", 1, 0.8, 0.8, 0.8, "", "", "", "", "", ""])
    # t3 is tier 3: its very poor binner score must not reach the headline.
    t3_binner = next(row for row in rows if row[0] == "t3" and row[1] == "binner")
    t3_binner[7] = 0.0
    with open("hscores.tsv", "w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    run([os.path.join(PY, "aggregate_results.py"), "--scores", "hscores.tsv", "--sample-sheet", "hsheet.tsv",
         "--capabilities", "caps.tsv", "--truth-provenance", "hprov.tsv", "--min-species-clusters", "3",
         "--out-prefix", "h"])
    board = {r["tool"]: r for r in read("h.leaderboard.tsv")}
    ok = check(ok, "tasks assigned from the capability registry",
               board["binner"]["task"] == "reconstruction" and board["classy"]["task"] == "classification")
    ok = check(ok, "reconstruction ranked by lw_bin_f1 (not base F1)",
               board["binner"]["rank"] == "1" and board["binner"]["ranking_metric"] == "lw_bin_f1",
               f"(binner {board['binner']['ranking_score']}, binner2 {board['binner2']['ranking_score']})")
    ok = check(ok, "species macro-average over 2 species, tier 3 excluded",
               board["binner"]["ranking_score"] == "0.7000" and board["binner"]["n_headline_species"] == "2"
               and "species macro-average" in board["binner"]["ranking_species_basis"])
    ok = check(ok, "classification ranked separately by base F1",
               board["classy"]["rank"] == "1" and board["classy"]["ranking_metric"] == "f1")
    # CPRR: binner2 correct=1 everywhere, so 6/6 regardless of identity rule.
    # binner: correct=0, without-identity=1; identity valid only for E. coli
    # (3 samples) -> E. coli 0/3 + Klebsiella 3/3 = 3/6.
    ok = check(ok, "CPRR drops identity only where truth was polished with benchmark reads",
               board["binner"]["cprr"] == "0.5000" and board["binner2"]["cprr"] == "1.0000")
    ok = check(ok, "ambiguous-plasmid sample is not a negative control", board["binner"]["n_zero_plasmid_isolates"] == "0")
    species = read("h.species.tsv")
    ok = check(ok, "species table written", any(r["species"] == "Klebsiella pneumoniae" and r["in_headline"] == "yes"
                                                 for r in species))
    tiers = read("h.reference_tiers.tsv")
    ok = check(ok, "tier sensitivity table includes tier 3", any(r["reference_tier"] == "3" for r in tiers))
    return ok


def cohort(ok):
    write("cohort.tsv", "sample_id\torganism\ttruth_assembly_strategy\nx\tEscherichia coli\tlong_read_only\n")
    result = run([os.path.join(PY, "validate_cohort.py"), "--samples", "cohort.tsv"], check=False)
    ok = check(ok, "composition warnings are advisory",
               "COHORT COMPOSITION WARNING" in result.stderr)
    write("cohort_bad.tsv", "sample_id\torganism\ttruth_polish_reads\nx\tEscherichia coli\tmaybe\n")
    bad = run([os.path.join(PY, "validate_cohort.py"), "--samples", "cohort_bad.tsv"], check=False)
    ok = check(ok, "invalid truth_polish_reads fails validation",
               bad.returncode != 0 and "truth_polish_reads" in (bad.stdout + bad.stderr))
    return ok


def main():
    ok = True
    with tempfile.TemporaryDirectory(prefix="research_design_") as tmp:
        try:
            os.chdir(tmp)
            for step in (endpoints, provenance, labels, clonal, headline, cohort):
                print(f"[{step.__name__}]")
                ok = step(ok)
        finally:
            os.chdir(HERE)
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
