#!/usr/bin/env python3
"""audit_truth_labels.py flags label/annotation disagreement and never over-claims."""
import csv
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "python", "audit_truth_labels.py")

TRUTH = ("sequence_id\tmolecule_type\tlength\n"
         "chr\tCHROMOSOME\t5000\nchromid\tCHROMOSOME\t900\n"
         "pA\tPLASMID\t1000\npB\tPLASMID\t800\n")
FEATURES = ("sequence_id\tstart\tend\tfeature_type\tlabel\tsource\tversion\n"
            "chromid\t1\t900\treplicon\tIncFIB\tabricate\t1\n"
            "pA\t1\t1000\treplicon\tIncX1\tabricate\t1\n")


def provenance(*ok):
    names = ("mob_typer", "abricate_replicon")
    return json.dumps({"callers": {n: {"status": "ok" if n in ok else "not_evaluated"}
                                   for n in names}})


def build(data, sample, features=True, prov=None):
    sdir = os.path.join(data, sample)
    os.makedirs(sdir)
    open(os.path.join(sdir, "truth.tsv"), "w").write(TRUTH)
    if features:
        open(os.path.join(sdir, "truth_features.tsv"), "w").write(FEATURES)
    if prov is not None:
        open(os.path.join(sdir, "annotation_provenance.json"), "w").write(prov)


def main():
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        data = os.path.join(tmp, "data")
        os.makedirs(data)
        build(data, "full", prov=provenance("mob_typer", "abricate_replicon"))
        build(data, "partial", prov=provenance("abricate_replicon"))
        build(data, "noprov")
        out = os.path.join(tmp, "audit.tsv")
        proc = subprocess.run([sys.executable, SCRIPT, "--data-dir", data, "--out", out],
                              text=True, capture_output=True)
        ok &= proc.returncode == 0
        with open(out, newline="") as handle:
            rows = {(r["sample"], r["sequence_id"]): r["finding"]
                    for r in csv.DictReader(handle, delimiter="\t")}

        checks = {
            # both callers ran: every disagreement is reported
            ("full", "chromid"): "chromosome_with_plasmid_markers",
            ("full", "pB"): "plasmid_without_markers",
            ("full", "pA"): "consistent",
            ("full", "chr"): "consistent",
            # only one marker class evaluated: absence on a plasmid is NOT a finding
            ("partial", "pB"): "not_evaluated",
            ("partial", "chromid"): "chromosome_with_plasmid_markers",
            # no provenance: an empty result cannot be read as absence
            ("noprov", "pB"): "not_evaluated",
            ("noprov", "chr"): "not_evaluated",
        }
        for key, want in checks.items():
            got = rows.get(key)
            print(f"  {key[0]}/{key[1]} -> {got} (expected {want}) {'PASS' if got == want else 'FAIL'}")
            ok &= got == want
        flagged_msg = "need review" in proc.stderr
        print(f"  flagged sequences are announced as advisory -> {flagged_msg}")
        ok &= flagged_msg
        ok &= not os.path.exists(os.path.join(data, "full", "truth.tsv.bak"))
        # A missing data directory is reported, not a traceback, and still writes a header-only table.
        missing_out = os.path.join(tmp, "missing.tsv")
        gone = subprocess.run([sys.executable, SCRIPT, "--data-dir", os.path.join(tmp, "nope"),
                               "--out", missing_out], text=True, capture_output=True)
        clean = gone.returncode == 0 and "Traceback" not in gone.stderr and "not found" in gone.stderr
        clean &= os.path.isfile(missing_out) and len(open(missing_out).read().splitlines()) == 1
        print(f"  missing data directory is handled without a traceback -> {clean}")
        ok &= clean
    print("ALL AUDIT TRUTH LABEL TESTS PASSED" if ok else "AUDIT TRUTH LABEL TESTS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
