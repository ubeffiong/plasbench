#!/usr/bin/env python3
"""
Optional label evidence: several Abricate replicon databases, ISFinder BLAST annotation, and the repeat_rich tag.

Callers are faked (no abricate or blastn needed): annotate_reference's `run`, `shutil.which` and `tool_version` are patched.

ISFinder BLAST rows (qseqid sseqid pident length qstart qend sstart send slen), keeping identity >= 90 and aligned
length / IS length >= 0.80:
  p1  IS26   99.0  780 of 800  -> kept (0.975)
  p1  IS903  95.0  500 of 1000 -> dropped (0.50, a fragment)
  p1  ISEcp1 85.0  1200 of 1200 -> dropped (identity 85)
  p1  IS1    92.0  700 of 768, reverse strand (qstart 5000 > qend 4301) -> kept, coordinates normalised to 0-based 4300..5000
  zz  IS26   99.0  780 of 800  -> dropped (sequence not in the reference)

repeat_rich: a 10,000 bp plasmid carrying 3 insertion_sequence features is 3.0 per 10 kb; with the threshold at 2.0 it is
tagged repeat_rich. Before this change the tag compared against feature types "is" and "isescan" only, so the
insertion_sequence rows annotate_reference actually writes never counted.
"""

import argparse
import csv
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))

import annotate_reference as ar  # noqa: E402
import scenario_tags as st  # noqa: E402

TAB, NL = chr(9), chr(10)


def main():
    ok = True

    def check(label, condition):
        nonlocal ok
        ok &= bool(condition)
        print(f"  {'PASS' if condition else 'FAIL'}: {label}")

    print("ISFinder BLAST parsing")
    rows = NL.join([
        TAB.join(["p1", "IS26", "99.0", "780", "100", "879", "1", "780", "800"]),
        TAB.join(["p1", "IS903", "95.0", "500", "2000", "2499", "1", "500", "1000"]),
        TAB.join(["p1", "ISEcp1", "85.0", "1200", "3000", "4199", "1", "1200", "1200"]),
        TAB.join(["p1", "IS1", "92.0", "700", "5000", "4301", "1", "700", "768"]),
        TAB.join(["zz", "IS26", "99.0", "780", "100", "879", "1", "780", "800"]),
    ])
    feats = ar.parse_isfinder_blast(rows, {"p1"}, "blastn 2.x")
    check("two hits survive the identity and subject-coverage filter", [f["label"] for f in feats] == ["IS26", "IS1"])
    check("coordinates are 0-based half-open and orientation-free",
          (feats[0]["start"], feats[0]["end"]) == (99, 879) and (feats[1]["start"], feats[1]["end"]) == (4300, 5000))
    check("type and source are recorded", all(f["feature_type"] == "insertion_sequence" and f["source"] == "isfinder" for f in feats))

    print("annotate_reference with two replicon databases and ISFinder (callers faked)")
    tmp = tempfile.mkdtemp(prefix="annot_")
    reference = Path(tmp) / "ref.fna"
    reference.write_text(">p1" + NL + "A" * 6000 + NL + ">chr" + NL + "C" * 6000 + NL)
    isfinder = Path(tmp) / "isfinder.fna"
    isfinder.write_text(">IS26" + NL + "ACGT" + NL)
    abricate_output = {
        "plasmidfinder": TAB.join(["SEQUENCE", "START", "END", "GENE"]) + NL + TAB.join(["p1", "100", "400", "IncFII"]) + NL,
        "rep.mob.typer": TAB.join(["SEQUENCE", "START", "END", "GENE"]) + NL + TAB.join(["p1", "1000", "1300", "rep_cluster_2"]) + NL,
    }

    def fake_run(command, timeout):
        if command[0].endswith("abricate"):
            return abricate_output.get(command[command.index("--db") + 1], TAB.join(["SEQUENCE", "START", "END", "GENE"]) + NL), ""
        if command[0].endswith("blastn"):
            return rows, ""
        return None, "not faked"

    ar.shutil.which = lambda name: ("/fake/" + name) if name in ("abricate", "blastn") else None
    ar.run = fake_run
    ar.tool_version = lambda *a, **k: "fake 1.0"
    out, prov = Path(tmp) / "features.tsv", Path(tmp) / "prov.json"
    sys.argv = ["annotate_reference.py", "--reference", str(reference), "--out", str(out), "--provenance", str(prov),
                "--replicon-database", "plasmidfinder,rep.mob.typer", "--isfinder-fasta", str(isfinder)]
    ar.main()
    record = json.loads(prov.read_text())["callers"]
    check("the first replicon database keeps the name abricate_replicon", record["abricate_replicon"]["status"] == "ok")
    check("a second database is recorded under its own name", record["abricate_replicon_rep.mob.typer"]["status"] == "ok")
    check("ISFinder is recorded", record["isfinder"]["status"] == "ok" and record["isfinder"]["features"] == 2)
    with open(out, newline="") as handle:
        features = list(csv.DictReader(handle, delimiter=TAB))
    labels = {(f["feature_type"], f["label"]) for f in features}
    check("replicon features from both databases", ("replicon", "IncFII") in labels and ("replicon", "rep_cluster_2") in labels)
    check("the ISFinder IS26 hit is a feature", ("insertion_sequence", "IS26") in labels)

    print("ISFinder is not_evaluated, never absent, when its FASTA is not given")
    sys.argv = ["annotate_reference.py", "--reference", str(reference), "--out", str(out), "--provenance", str(prov)]
    ar.main()
    record = json.loads(prov.read_text())["callers"]
    check("no FASTA -> not_evaluated with the reason", record["isfinder"]["status"] == "not_evaluated"
          and "isfinder" in record["isfinder"]["reason"].lower())
    check("a single default database still works", record["abricate_replicon"]["status"] == "ok"
          and "abricate_replicon_rep.mob.typer" not in record)

    print("repeat_rich counts insertion_sequence features")
    data = Path(tmp) / "data" / "S1"
    data.mkdir(parents=True)
    (data / "truth.tsv").write_text(TAB.join(["sequence_id", "molecule_type", "length"]) + NL
                                    + TAB.join(["pl", "PLASMID", "10000"]) + NL + TAB.join(["chr", "CHROMOSOME", "50000"]) + NL)
    (data / "truth_features.tsv").write_text(
        TAB.join(["sequence_id", "start", "end", "feature_type", "label", "source", "version"]) + NL
        + NL.join(TAB.join(["pl", str(i * 1000), str(i * 1000 + 800), "insertion_sequence", "IS26", "isfinder", "v"])
                  for i in range(3)) + NL)
    args = argparse.Namespace(complex_plasmids=3, large_bp=100000, small_bp=5000, is_per_10kb=2.0, low_depth=10)
    tags = st.classify("S1", str(Path(tmp) / "data"), 50.0, args)
    check("3 IS on 10 kb is tagged repeat_rich (3.0 per 10 kb >= 2.0)", "repeat_rich" in tags["tags"])
    check("the density is reported", abs(tags["is_density_per_10kb"] - 3.0) < 1e-9)

    print()
    if not ok:
        print("ANNOTATION ADDITIONS TESTS FAILED")
        sys.exit(1)
    print("ALL ANNOTATION ADDITIONS TESTS PASSED")


if __name__ == "__main__":
    main()
