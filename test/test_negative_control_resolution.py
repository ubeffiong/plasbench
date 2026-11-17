#!/usr/bin/env python3
"""Negative controls: the resolver requires a plasmid-free single chromosome, and validate_cohort agrees with a declared plasmid count of 0 (NCBI stubbed)."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
import resolve_contributed_cohort as rc  # noqa: E402
import validate_cohort as vc  # noqa: E402

failures = []


def check(label, condition, detail=""):
    print(f"  {'PASS' if condition else 'FAIL'}: {label}{'' if condition else ' -- ' + str(detail)}")
    if not condition:
        failures.append(label)


THRESHOLDS = rc.read_thresholds(os.path.join(ROOT, "config", "short_read_qc_thresholds.tsv"))
ASSEMBLY = {"assembly_status": "Complete Genome", "datasets_assembly_level": "Complete Genome", "has_plasmid": False,
            "derived_truth_technology": "hybrid", "biosample": "SAMN1", "bioprojects": ["PRJNA100"]}
RUN = {"biosample": "SAMN1", "bioproject": "PRJNA100", "platform": "ILLUMINA", "layout": "PAIRED", "bases": "900000000", "spots": "3000000", "avg_length": "", "sample_name": ""}
SIZE = {"value": (4_600_000, 1)}

rc.vc.assembly_metadata = lambda accession, email=None, api_key=None: dict(ASSEMBLY)
rc.vc.run_metadata = lambda run, email=None, api_key=None: dict(RUN, run=run)
rc.single_replicon = lambda accession, api_key=None: SIZE["value"]

ROW = {"sample_id": "escherichia_coli_1", "assembly_accession": "GCF_1.1", "organism": "Escherichia coli", "biosample": "SAMN1", "sra_run": "SRR1",
       "alternate_paired_runs": "", "truth_technology": "hybrid", "assembly_plasmid_count": "0"}

print("the resolver in negative-control mode")
sheet, out = rc.resolve(ROW, THRESHOLDS, None, None, 0, negative_controls=True)
check("a plasmid-free single chromosome with a good paired run is accepted", sheet is not None and out["status"] in ("pass", "warn"), out)
check("depth is estimated from the genome size it found itself", sheet and abs(float(sheet["est_depth_x"]) - 900_000_000 / 4_600_000) < 0.1, sheet and sheet["est_depth_x"])
ASSEMBLY["has_plasmid"] = True
sheet, out = rc.resolve(ROW, THRESHOLDS, None, None, 0, negative_controls=True)
check("an assembly that declares plasmids is rejected as not a negative control", sheet is None and "not a negative control" in out["reasons"], out)
ASSEMBLY["has_plasmid"] = False
SIZE["value"] = (4_900_000, 3)
sheet, out = rc.resolve(ROW, THRESHOLDS, None, None, 0, negative_controls=True)
check("more than one sequence is rejected even if the record declares no plasmid", sheet is None and "3 sequences" in out["reasons"], out)
SIZE["value"] = (80_000, 1)
sheet, out = rc.resolve(ROW, THRESHOLDS, None, None, 0, negative_controls=True)
check("a single sequence too short to be a chromosome is rejected (a lone plasmid record)", sheet is None and "too short" in out["reasons"], out)
SIZE["value"] = (None, None)
sheet, out = rc.resolve(ROW, THRESHOLDS, None, None, 0, negative_controls=True)
check("an unreadable size is a rejection, not a pass", sheet is None and "unknown number" in out["reasons"], out)
SIZE["value"] = (4_600_000, 1)
sheet, out = rc.resolve(ROW, THRESHOLDS, None, None, 0)
check("without the flag a plasmid-free assembly is still rejected (normal cohorts need plasmids)", sheet is None and "does not declare plasmid replicons" in out["reasons"], out)

print("validate_cohort agrees with a declared count of 0")
vc.assembly_metadata = lambda accession, email=None, api_key=None: dict(ASSEMBLY, accession=accession)
vc.run_metadata = lambda run, email=None, api_key=None: dict(RUN, run=run)
vc.time.sleep = lambda s: None
VROW = {"sample_id": "e1", "assembly_accession": "GCF_1.1", "sra_run": "SRR1", "organism": "Escherichia coli", "truth_technology": "hybrid", "truth_quality_tier": "B",
        "biosample": "SAMN1", "bioproject": "PRJNA100", "source_study": "NCBI_discovery_negative_control_pending_review", "assembly_plasmid_count": "0"}
errors = vc.verify_row(VROW)["errors"]
check("a plasmid-free assembly passes for a row that declares assembly_plasmid_count 0", errors == [], errors)
ASSEMBLY["has_plasmid"] = True
errors = vc.verify_row(VROW)["errors"]
check("an assembly with plasmids fails for a row that declares count 0", any("declares assembly_plasmid_count 0" in e for e in errors), errors)
ASSEMBLY["has_plasmid"] = False
errors = vc.verify_row(dict(VROW, assembly_plasmid_count="2"))["errors"]
check("a row that does not declare 0 still needs plasmids", any("does not declare plasmid replicons" in e for e in errors), errors)

print("ALL NEGATIVE CONTROL RESOLUTION TESTS PASSED" if not failures else "NEGATIVE CONTROL RESOLUTION TESTS FAILED: " + "; ".join(failures))
sys.exit(1 if failures else 0)
