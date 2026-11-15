#!/usr/bin/env python3
"""
The extended truth audits (plan A9): flags beside the finding, higher multimers, and the database overlap between the truth evidence and the tools.

Audit flags (python/audit_truth_labels.py), on a hand-built sample:
  - the largest chromosome with a marker -> integrated_plasmid_candidate; a secondary chromosome with a marker -> chromid_candidate; one without -> secondary_chromosome (>= 350 kb);
  - a PLASMID of at least 500 kb -> large_plasmid; two replicon labels -> multi_replicon_plasmid; no marker with both callers run -> marker_free_plasmid;
  - truth.corrections.tsv -> multimer_<k>x; the depth-anomaly summary -> collapsed_repeat_candidate / low_depth_region (only when its status is flagged);
  - the existing finding column is unchanged and `flags` is the last column; a clean sequence has no flag; the size thresholds are arguments.
Multimers (python/detect_dimers.py): a dimer is 2 copies, a trimer 3, a tetramer 4 (not 2), a non-repeat is not flagged, and a collapse keeps the first 1/k.
Overlap (python/truth_marker_overlap.py): MOB-suite tools share the MOB-typing database (yes), a PLSDB-derived database possibly overlaps the plasmid reference set, a tool with no
database is no, an unrecorded database is unknown.
Report and wiring: the audit table has a Flags column and lists a flagged-only row, the overlap table is in the Truth labels tab with a Not run state, stage 6 and the demo run it.
"""
import csv
import json
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import audit_truth_labels as atl  # noqa: E402
import detect_dimers as dd  # noqa: E402
import truth_marker_overlap as tmo  # noqa: E402


def main():
    ok = True

    def check(label, condition, detail=""):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}" + (f"  {detail}" if detail and not condition else ""))

    print("the audit flags")
    with tempfile.TemporaryDirectory() as tmp:
        sample = Path(tmp) / "s1"
        sample.mkdir()
        (sample / "truth.tsv").write_text(
            "sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t4000000\nchr2\tCHROMOSOME\t900000\nchr3\tCHROMOSOME\t400000\nchr4\tCHROMOSOME\t100000\n"
            "big\tPLASMID\t700000\nfused\tPLASMID\t60000\nnone\tPLASMID\t30000\nsmall\tPLASMID\t5000\ntri\tPLASMID\t9000\ncollapsed\tPLASMID\t12000\n")
        (sample / "truth_features.tsv").write_text(
            "sequence_id\tstart\tend\tfeature_type\tlabel\tsource\tversion\n"
            "chr\t1\t10\treplicon\tIncX\tabricate\t1\nchr2\t1\t10\tmob\tMOBF\tmob_typer\t1\nbig\t1\t10\treplicon\tIncA\tabricate\t1\n"
            "fused\t1\t10\treplicon\tIncFIB\tabricate\t1\nfused\t20\t30\treplicon\tIncFII\tabricate\t1\nsmall\t1\t10\treplicon\tIncQ\tabricate\t1\n"
            "tri\t1\t10\treplicon\tIncN\tabricate\t1\ncollapsed\t1\t10\tmob\tMOBP\tmob_typer\t1\n")
        (sample / "annotation_provenance.json").write_text(json.dumps({"callers": {"mob_typer": {"status": "ok"}, "abricate_replicon": {"status": "ok"}}}))
        (sample / "truth.corrections.tsv").write_text("sequence_id\toriginal_length\tcorrected_length\tidentity\thalf_coverage\tmethod\tmultimer\taction\tcopies\ntri\t9000\t3000\t1.0\t1.0\thamming\tyes\tflagged\t3\n")
        (sample / "truth_depth_anomaly_summary.tsv").write_text(
            "sample\tsequence_id\tmolecule_type\tn_windows\tn_high_regions\tn_low_regions\tstatus\ncollapsed\tcollapsed\tPLASMID\t40\t2\t1\tflagged\n"
            "small\tsmall\tPLASMID\t40\t3\t0\tok\n".replace("n_high_regions\tn_low_regions", "n_high_regions\tn_low_regions"))
        rows = {r["sequence_id"]: r for r in atl.audit_sample("s1", sample)}
        flags = {k: set(v["flags"].split(";")) - {""} for k, v in rows.items()}
        check("the largest chromosome with a marker is an integrated-plasmid candidate", flags["chr"] == {"integrated_plasmid_candidate"}, flags["chr"])
        check("a secondary chromosome with a marker is a chromid candidate", flags["chr2"] == {"chromid_candidate"}, flags["chr2"])
        check("a secondary chromosome of 400 kb with no marker is flagged secondary_chromosome; a 100 kb one is not", flags["chr3"] == {"secondary_chromosome"} and flags["chr4"] == set())
        check("a 700 kb PLASMID is a large plasmid", "large_plasmid" in flags["big"], flags["big"])
        check("two replicon labels: multi_replicon_plasmid", flags["fused"] == {"multi_replicon_plasmid"}, flags["fused"])
        check("no marker with both callers run: marker_free_plasmid, and the finding is unchanged", flags["none"] == {"marker_free_plasmid"} and rows["none"]["finding"] == "plasmid_without_markers")
        check("a clean plasmid has no flag", flags["small"] == set(), flags["small"])
        check("a corrected multimer is flagged with its copy number", "multimer_3x" in flags["tri"], flags["tri"])
        check("depth anomalies: high regions mean a collapsed-repeat candidate, low regions a low-depth region; an 'ok' summary flags nothing",
              {"collapsed_repeat_candidate", "low_depth_region"} <= flags["collapsed"] and "collapsed_repeat_candidate" not in flags["small"], (flags["collapsed"], flags["small"]))
        check("the finding column is still the old vocabulary and flags is the last column", atl.FIELDS[-1] == "flags" and atl.FIELDS[:7] == ("sample", "sequence_id", "molecule_type", "length", "replicon_labels", "mob_labels", "finding"))
        tight = {r["sequence_id"]: r for r in atl.audit_sample("s1", sample, chromid_min_bp=1000000, large_plasmid_bp=10 ** 9)}
        check("the size thresholds are arguments", "secondary_chromosome" not in tight["chr3"]["flags"] and "large_plasmid" not in tight["big"]["flags"])

    print("multimers")
    rng = random.Random(5)
    unit = "".join(rng.choice("ACGT") for _ in range(400))
    for copies in (2, 3, 4, 5):
        got = dd.test_multimer(unit * copies, 0.95, 0.9, use_minimap2=False)
        check(f"{copies} identical tandem copies are reported as {copies} copies (a tetramer is not called a dimer)", got[0] == copies, got)
    other = "".join(rng.choice("ACGT") for _ in range(1200))
    check("a sequence with no repeat is not a multimer", dd.test_multimer(other, 0.95, 0.9, use_minimap2=False)[0] == 1)
    check("a sequence too short to test says so", dd.test_multimer("ACGT" * 20, 0.95, 0.9, use_minimap2=False)[3] == "too_short")
    with tempfile.TemporaryDirectory() as tmp:
        ref = Path(tmp) / "reference.fna"
        ref.write_text(f">chr\n{''.join(rng.choice('ACGT') for _ in range(3000))}\n>tri\n{unit * 3}\n")
        truth = Path(tmp) / "truth.tsv"
        truth.write_text("sequence_id\tmolecule_type\tlength\nchr\tCHROMOSOME\t3000\ntri\tPLASMID\t1200\n")
        out = Path(tmp) / "truth.corrections.tsv"
        done = subprocess.run([sys.executable, str(ROOT / "python" / "detect_dimers.py"), "--reference", str(ref), "--truth", str(truth), "--out", str(out), "--collapse", "--no-minimap2"],
                              capture_output=True, text=True)
        rows = list(csv.DictReader(open(out, newline="", encoding="utf-8"), delimiter="\t"))
        lengths = {r["sequence_id"]: int(r["length"]) for r in csv.DictReader(open(truth, newline="", encoding="utf-8"), delimiter="\t")}
        check("the command records the copies, collapses a trimer to its first third and updates the truth length",
              done.returncode == 0 and rows[0]["copies"] == "3" and rows[0]["corrected_length"] == "400" and lengths["tri"] == 400 and rows[0]["multimer"] == "yes", (rows, done.stderr[-200:]))

    print("the database overlap")
    releases = [{"tool": "mob_recon", "uses_reference_database": "yes", "database": "MOB-suite database v2.0.0 (Zenodo)"},
                {"tool": "plassembler", "uses_reference_database": "yes", "database": "Plassembler database (PLSDB-derived)"},
                {"tool": "denovo", "uses_reference_database": "no", "database": "none"},
                {"tool": "mystery", "uses_reference_database": "unknown", "database": ""},
                {"tool": "genomad", "uses_reference_database": "yes", "database": "geNomad database v1.9"}]
    markers = tmo.read_tsv(ROOT / "config" / "truth_marker_databases.tsv")
    table = {(r["tool"], r["marker_caller"]): r["shared"] for r in tmo.overlap_table(releases, markers)}
    check("MOB-suite tools share the MOB-typing database", table[("mob_recon", "mob_typer")] == "yes" and table[("mob_recon", "abricate_replicon")] == "no")
    check("a PLSDB-derived database possibly overlaps the plasmid reference set", table[("plassembler", "plasmid_reference_match")] == "possible")
    check("a tool with no database is 'no'; an unrecorded database is 'unknown'; an unrelated database is 'no'",
          table[("denovo", "mob_typer")] == "no" and table[("mystery", "mob_typer")] == "unknown" and table[("genomad", "mob_typer")] == "no")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "overlap.tsv"
        done = subprocess.run([sys.executable, str(ROOT / "python" / "truth_marker_overlap.py"), "--out", str(out)], capture_output=True, text=True)
        rows = list(csv.DictReader(open(out, newline="", encoding="utf-8"), delimiter="\t"))
        shipped = {(r["tool"], r["marker_caller"]): r["shared"] for r in rows}
        check("the shipped registries: mob_recon shares the MOB-suite evidence, and the table has every column",
              done.returncode == 0 and shipped.get(("mob_recon", "mob_typer")) == "yes" and list(rows[0]) == list(tmo.FIELDS), done.stderr[-200:])

    print("the report and the wiring")
    import build_html_report as report  # noqa: E402
    source = (ROOT / "python" / "build_html_report.py").read_text(encoding="utf-8")
    check("the audit table has a Flags column and the overlap table sits in the Truth labels tab", "<th>Finding</th><th>Flags</th>" in source and "{marker_overlap_html}</section>" in source
          and "Marker databases shared with benchmarked tools" in source and "Not run: no marker-overlap table" in source)
    check("the report takes --truth-marker-overlap", "--truth-marker-overlap" in source and "Chromid candidate" in report.GLOSSARY)
    stage = (ROOT / "scripts" / "06_aggregate.sh").read_text(encoding="utf-8")
    demo = (ROOT / "test" / "run_demo.sh").read_text(encoding="utf-8")
    check("stage 6 and the demo build the overlap table and pass it to the report", "truth_marker_overlap.py" in stage and "--truth-marker-overlap" in stage
          and "truth_marker_overlap.py" in demo and "--truth-marker-overlap" in demo)
    config = (ROOT / "config" / "config.sh").read_text(encoding="utf-8")
    check("the size thresholds are config variables and pre-registered", 'export CHROMID_MIN_BP="${CHROMID_MIN_BP:-350000}"' in config and 'export LARGE_PLASMID_BP="${LARGE_PLASMID_BP:-500000}"' in config
          and "chromid_min_bp" in (ROOT / "config" / "prereg.tsv").read_text(encoding="utf-8"))
    check("the new table is registered for the Artifact explorer", "benchmark.truth_marker_overlap.tsv" in (ROOT / "python" / "report_surfaces.py").read_text(encoding="utf-8"))

    print()
    if not ok:
        print("TRUTH AUDITS TESTS FAILED")
        sys.exit(1)
    print("ALL TRUTH AUDITS TESTS PASSED")


if __name__ == "__main__":
    main()
