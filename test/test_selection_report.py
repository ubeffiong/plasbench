#!/usr/bin/env python3
"""Selection report: builder, the Cohorts page data, and the pop-up (rendered with node when it is installed)."""

import csv
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "python"))
failures = []


def check(label, condition, detail=""):
    print(f"  {'PASS' if condition else 'FAIL'}: {label}{'' if condition else ' -- ' + str(detail)}")
    if not condition:
        failures.append(label)


def write_tsv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    pool_dir = tmp / "pool"
    pool_dir.mkdir()
    pool_fields = ["assembly_accession", "organism_name"]
    pool = [{"assembly_accession": f"GCF_{i}.1", "organism_name": "Escherichia coli" if i < 6 else "Klebsiella pneumoniae"} for i in range(8)]
    with gzip.open(pool_dir / "assemblies.tsv.gz", "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=pool_fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(pool)
    imp, res = tmp / "imp", tmp / "res"
    imp.mkdir()
    res.mkdir()
    cand_fields = ["organism", "assembly_accession"]
    write_tsv(imp / "candidates.tsv", [{"organism": "Escherichia coli", "assembly_accession": f"GCF_{i}.1"} for i in range(5)]
              + [{"organism": "Klebsiella pneumoniae", "assembly_accession": "GCF_6.1"}], cand_fields)
    write_tsv(imp / "rejected.tsv", [{"assembly_accession": "GCF_5.1", "reason": "truth is not long-read-first (short_read_first_hybrid)"},
                                      {"assembly_accession": "GCF_7.1", "reason": "BioSample already released by an earlier cohort"}],
              ["assembly_accession", "reason"])
    pre = [{"sample_id": f"s{i}", "organism": "Escherichia coli", "status": "pass", "reasons": ""} for i in range(3)]
    pre += [{"sample_id": "s3", "organism": "Escherichia coli", "status": "reject", "reasons": "no usable run: SRR1: run BioProject PRJNA1 is not one of the assembly's ['PRJNA2']"},
            {"sample_id": "s4", "organism": "Escherichia coli", "status": "reject", "reasons": "no usable run: SRR2: platform OXFORD_NANOPORE is not ILLUMINA"},
            {"sample_id": "s5", "organism": "Klebsiella pneumoniae", "status": "warn", "reasons": "estimated depth 20.0 is below the warn limit 30"}]
    write_tsv(res / "precheck.tsv", pre, ["sample_id", "organism", "status", "reasons"])
    sheet_rows = [{"sample_id": f"s{i}", "organism": "Escherichia coli", "selection_arm": "recent" if i == 0 else "older", "panel_subset": "core",
                   "truth_assembly_strategy": "long_read_first_hybrid", "truth_technology": "hybrid", "truth_polish_reads": "same_as_benchmark",
                   "assembly_sequencing_technology": "Illumina NovaSeq; Oxford Nanopore MinION", "assembly_method": "Flye v. 2.9",
                   "est_depth_x": str(40 + 60 * i), "est_read_pairs": "2000000", "est_mean_read_length": "150", "qc_precheck": "pass",
                   "assembly_plasmid_count": str(i + 1), "genome_size": "5000000", "region": "Africa", "isolation_source_category": "Human clinical",
                   "truth_release_date": "2025-03-0%d" % (i + 1), "bioproject": f"PRJ{i}", "biosample": f"SAMN{i}"} for i in range(3)]
    sheet = tmp / "public-vx.tsv"
    fields = list(sheet_rows[0].keys())
    write_tsv(sheet, sheet_rows, fields)
    out = tmp / "public-vx.selection.json"
    done = subprocess.run([sys.executable, str(ROOT / "python" / "build_selection_report.py"), "--name", "public-vx", "--sheet", str(sheet),
                           "--pool-dir", str(pool_dir), "--importer-dir", str(imp), "--resolver-dir", str(res),
                           "--importer-command", "import_contributed_cohort.py --allow-short-read-first --all-members --arm auto --date-basis earliest_public",
                           "--resolver-command", "resolve_contributed_cohort.py --target-per-species 0 --preferred-max-depth 300",
                           "--thresholds", str(ROOT / "config" / "short_read_qc_thresholds.tsv"), "--out", str(out)], capture_output=True, text=True)
    check("the builder runs", done.returncode == 0, done.stderr)
    report = json.loads(out.read_text(encoding="utf-8"))

    print("the numbers come from the files")
    funnel = {f["stage"]: f["n"] for f in report["funnel"]}
    check("available is the pool size", funnel["In the contributed pool"] == 8)
    check("passed filters is the importer's candidates", funnel["Passed the offline filters"] == 6)
    check("verified counts pass and warn only", funnel["Verified at NCBI"] == 4, funnel)
    check("selected is the sheet", funnel["Selected into public-vx"] == 3)
    off = {x["reason"]: x["n"] for x in report["failures"]["offline"]}
    check("offline failures are grouped into plain-language reasons",
          off.get("Truth was built short-read-first (excluded unless short-read-first truths are allowed)") == 1
          and off.get("The BioSample is already in an earlier cohort (public-v1 to v3)") == 1, off)
    ncbi = {x["reason"]: x["n"] for x in report["failures"]["ncbi"]}
    check("NCBI failures are grouped, with the run's ids stripped",
          ncbi.get("The SRA run's BioProject is not one of the assembly's BioProjects (not a verified pair)") == 1
          and ncbi.get("The SRA run is not Illumina") == 1, ncbi)
    sp = {x["species"]: x for x in report["species"]}
    check("per-species funnel", sp["Escherichia coli"]["pool"] == 6 and sp["Escherichia coli"]["selected"] == 3
          and sp["Escherichia coli"]["recent"] == 1 and sp["Klebsiella pneumoniae"]["verified"] == 1, sp)
    reads = report["selected"]["reads"]
    check("depth summary is from the selected rows", reads["depth_x"]["min"] == 40 and reads["depth_x"]["max"] == 160 and reads["depth_x"]["median"] == 100, reads["depth_x"])
    check("reference technology is grouped into platform families", report["selected"]["reference_sequencing"][0]["value"] == "Oxford Nanopore + Illumina")
    check("the assembler is reduced to its name", report["selected"]["reference_assembler"][0]["value"] == "Flye")
    check("criteria reflect the flags that were used", any(c["id"] == "members" and "Every passing isolate" in c["rule"] for c in report["criteria"])
          and any(c["id"] == "strategy" and "Short-read-first" in c["rule"] for c in report["criteria"]))
    check("pool files are pinned by checksum", report["source"]["pool_files"][0]["sha256"] and report["source"]["pool_rows"] == 8)
    check("limits are stated", len(report["limits"]) >= 5 and any("No tool has been run" in x for x in report["limits"]))

    print("the Cohorts page")
    from plasbench import cohort_info
    root = tmp / "proj"
    (root / "cohorts").mkdir(parents=True)
    shutil.copy(sheet, root / "cohorts" / "public-vx.tsv")
    shutil.copy(out, root / "cohorts" / "public-vx.selection.json")
    info = cohort_info.info(root, "public-vx")
    check("cohort_info carries the selection report", info["selection"] and info["selection"]["cohort"] == "public-vx")
    (root / "cohorts" / "plain.tsv").write_text("sample_id\tassembly_accession\tsra_run\torganism\nx\tGCF_1.1\tSRR1\tEscherichia coli\n", encoding="utf-8")
    check("a cohort with no report has selection None", cohort_info.info(root, "plain")["selection"] is None)
    (root / "cohorts" / "broken.tsv").write_text("sample_id\nx\n", encoding="utf-8")
    (root / "cohorts" / "broken.selection.json").write_text("{not json", encoding="utf-8")
    check("an unreadable report is ignored, not an error", cohort_info.info(root, "broken")["selection"] is None)
    from plasbench import webui
    flags = {c["name"]: c["selection"] for c in webui.Project(root).cohorts()}
    check("the cohort list flags which cohorts have a report", flags == {"broken": True, "plain": False, "public-vx": True}, flags)

    print("the pop-up")
    node = shutil.which("node")
    if node:
        rendered = subprocess.run([node, str(ROOT / "test" / "selection_report_render.js"), str(ROOT / "plasbench" / "data" / "ui.html"), str(out)],
                                  capture_output=True, text=True)
        check("the pop-up renders every section with no undefined / NaN", "RENDER OK" in rendered.stdout, rendered.stdout[-400:] + rendered.stderr[-400:])
    else:
        print("  SKIP: node is not installed, so the pop-up was not rendered")
    html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    check("the Cohorts page has the link in the list and in the details", html.count("selectionReport(") >= 3)

print("ALL SELECTION REPORT TESTS PASSED" if not failures else "SELECTION REPORT TESTS FAILED: " + "; ".join(failures))
sys.exit(1 if failures else 0)
