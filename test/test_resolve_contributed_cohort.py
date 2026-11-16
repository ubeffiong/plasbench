#!/usr/bin/env python3
"""Resolver: real BioProject, run choice, pre-download QC grading and the final per-species choice (NCBI stubbed)."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
import resolve_contributed_cohort as rc  # noqa: E402

failures = []


def check(label, condition, detail=""):
    print(f"  {'PASS' if condition else 'FAIL'}: {label}{'' if condition else ' -- ' + str(detail)}")
    if not condition:
        failures.append(label)


THRESHOLDS = rc.read_thresholds(os.path.join(ROOT, "config", "short_read_qc_thresholds.tsv"))
ASSEMBLY = {"assembly_status": "Complete Genome", "datasets_assembly_level": "Complete Genome", "has_plasmid": True,
            "derived_truth_technology": "hybrid", "biosample": "SAMN1", "bioprojects": ["PRJNA224116", "PRJNA100"]}
RUNS = {}


def fake_assembly(accession, email=None, api_key=None):
    return dict(ASSEMBLY)


def fake_run(run, email=None, api_key=None):
    if run not in RUNS:
        raise ValueError(f"SRA run not found uniquely: {run}")
    return dict(RUNS[run], run=run)


rc.vc.assembly_metadata = fake_assembly
rc.vc.run_metadata = fake_run


def run_info(biosample="SAMN1", bioproject="PRJNA100", platform="ILLUMINA", layout="PAIRED", bases=500_000_000, spots=None):
    spots = spots or bases // 300      # 2 x 150 bp pairs
    return {"biosample": biosample, "bioproject": bioproject, "platform": platform, "layout": layout,
            "bases": str(bases), "spots": str(spots), "avg_length": "", "sample_name": "", }


ROW = {"sample_id": "escherichia_coli_samn1", "assembly_accession": "GCF_1.1", "organism": "Escherichia coli", "biosample": "SAMN1",
       "sra_run": "SRR1", "alternate_paired_runs": "SRR2;SRR3", "genome_size": "5000000", "truth_technology": "long_read",
       "selection_arm": "recent"}

print("grading against the shared QC thresholds")
check("depth under the reject limit is rejected", rc.grade(5, THRESHOLDS["estimated_depth_x"]) == "reject")
check("depth between reject and warn is a warning", rc.grade(20, THRESHOLDS["estimated_depth_x"]) == "warn")
check("depth over the warn limit passes", rc.grade(80, THRESHOLDS["estimated_depth_x"]) == "pass")
check("an unknown value is not graded as a pass", rc.grade(None, THRESHOLDS["estimated_depth_x"]) == "unknown")

print("run choice and BioProject")
RUNS.update({"SRR1": run_info(platform="OXFORD_NANOPORE"),                      # wrong platform
             "SRR2": run_info(bases=60_000_000),                                 # 12x depth: warn
             "SRR3": run_info(bases=900_000_000)})              # 180x: pass
sheet, out = rc.resolve(ROW, THRESHOLDS, None, None, 0)
check("the deepest passing run is chosen, the wrong-platform run is not", sheet and sheet["sra_run"] == "SRR3", out)
check("the others are kept as alternates", sheet["alternate_paired_runs"] == "SRR2")
check("the real BioProject replaces the umbrella", sheet["bioproject"] == "PRJNA100")
check("truth_technology is NCBI's derived value", sheet["truth_technology"] == "hybrid")
check("depth is bases over genome size", abs(float(sheet["est_depth_x"]) - 180.0) < 0.1, sheet["est_depth_x"])
check("the pre-download QC status is recorded", sheet["qc_precheck"] == "pass")
RUNS["SRR3"] = run_info(bases=60_000_000)
sheet, out = rc.resolve(ROW, THRESHOLDS, None, None, 0)
check("when only a thin run passes, the row is kept and flagged warn", sheet and sheet["qc_precheck"] == "warn" and "warn limit" in sheet["qc_precheck_notes"], out)
RUNS["SRR2"] = run_info(bases=10_000_000)
RUNS["SRR3"] = run_info(bases=10_000_000)
sheet, out = rc.resolve(ROW, THRESHOLDS, None, None, 0)
check("every run under the reject limit means the candidate is rejected with the reason", sheet is None and "no usable run" in out["reasons"], out)
RUNS.update({"SRR2": run_info(biosample="SAMN9"), "SRR3": run_info(bioproject="PRJNA999")})
sheet, out = rc.resolve(ROW, THRESHOLDS, None, None, 0)
check("a run from another BioSample or a BioProject the assembly lacks is rejected",
      sheet is None and "BioSample" in out["reasons"] and "BioProject" in out["reasons"], out)
RUNS["SRR3"] = run_info(layout="SINGLE")
ASSEMBLY["has_plasmid"] = False
sheet, out = rc.resolve(ROW, THRESHOLDS, None, None, 0)
check("an assembly with no plasmid replicons is rejected before any run is checked", sheet is None and "plasmid" in out["reasons"], out)

print("final choice: recent arm first, filled from the older arm, one row per BioProject")
rows = []
for i in range(8):
    rows.append({"sample_id": f"r{i}", "organism": "Escherichia coli", "selection_arm": "recent", "bioproject": f"PRJR{i}"})
for i in range(8):
    rows.append({"sample_id": f"o{i}", "organism": "Escherichia coli", "selection_arm": "older", "bioproject": f"PRJO{i}"})
rows.append({"sample_id": "dup", "organism": "Escherichia coli", "selection_arm": "older", "bioproject": "PRJR0"})
rows += [{"sample_id": f"k{i}", "organism": "Klebsiella pneumoniae", "selection_arm": "recent", "bioproject": f"PRJK{i}"} for i in range(3)]
chosen, report = rc.final_choice(rows, target=10, min_recent=5)
ids = [r["sample_id"] for r in chosen if r["organism"] == "Escherichia coli"]
check("a species is capped at the target", len(ids) == 10, ids)
check("it starts from the recent arm (min_recent rows) then fills older", ids[:5] == [f"r{i}" for i in range(5)] and all(i.startswith("o") for i in ids[5:]), ids)
check("a row repeating a BioProject is never chosen twice", "dup" not in ids and len({r["bioproject"] for r in chosen}) == len(chosen))
check("a species short of the target is reported, not padded", [r for r in report if r[0] == "Klebsiella pneumoniae"][0][2] == 3)
small, _ = rc.final_choice(rows[:8] + rows[16:], target=5, min_recent=5)
check("with no older rows the recent arm tops the species up", sum(1 for r in small if r["organism"] == "Escherichia coli") == 5)

print("ALL RESOLVE CONTRIBUTED COHORT TESTS PASSED" if not failures else "RESOLVE CONTRIBUTED COHORT TESTS FAILED: " + "; ".join(failures))
sys.exit(1 if failures else 0)
