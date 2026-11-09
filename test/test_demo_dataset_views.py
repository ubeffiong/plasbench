#!/usr/bin/env python3
"""The synthetic demo cohort must feed every report view with real values.

Generates the cohort to a temp dir (no stages run) and checks: strand-bearing truth
proteins in both orientations across the report's gene classes incl. metal resistance,
an origin-wrapping gene on a circular plasmid, one repeat-rich plasmid with regions
(repeat content measured by the same function the truth QC stage uses), per-tool
predicted proteins whose projection fractions straddle 0.9, and the pre-existing files.
Plain script: exits non-zero on the first failed check group.
"""
import csv
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))
FAILED = []


def check(name, ok):
    print(("  ok: " if ok else "  FAIL: ") + name)
    if not ok:
        FAILED.append(name)


def tsv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def main():
    import report_maps as rm
    import repeat_content
    out = tempfile.mkdtemp(prefix="demo_views_")
    subprocess.run([sys.executable, os.path.join(HERE, "demo_dataset.py"), "--out-dir", out],
                   check=True, capture_output=True, env={**os.environ, "PYTHONIOENCODING": "utf-8"})

    print("existing files")
    for name in ("samples.tsv", "tool_status.tsv", "run_manifest.json"):
        check(name, os.path.isfile(os.path.join(out, name)))
    for name in ("truth.tsv", "truth_amr.tsv", "truth_circular.tsv", "truth_features.tsv", "truth_proteins.tsv",
                 "reference.fna", "reference.full.fna", "contigs.fasta", "contigs_vs_ref.paf",
                 "mob_like.pred_vs_ref.paf", "pred_mob_like.plasmid.fasta", "pred_mob_like.bins.tsv"):
        check(f"ecoli_a/{name}", os.path.isfile(os.path.join(out, "ecoli_a", name)))

    print("strands, classes, metal resistance")
    classes_by_strand = {}
    all_rows = []
    for sample in sorted(os.listdir(out)):
        path = os.path.join(out, sample, "truth_proteins.tsv")
        if os.path.isfile(path):
            for row in tsv(path):
                row["sample"] = sample
                all_rows.append(row)
    check("every protein strand is + or -", all(r["strand"] in ("+", "-") for r in all_rows))
    for r in all_rows:
        cls = rm.classify_gene(r["category"], r["gene"], r["product"])
        classes_by_strand.setdefault(r["sample"] + "/" + r["sequence_id"], set()).add((cls, r["strand"]))
    rich = [k for k, v in classes_by_strand.items() if {s for _, s in v} == {"+", "-"}]
    check("at least two plasmids carry both strands", len(rich) >= 2)
    seen = {rm.classify_gene(r["category"], r["gene"], r["product"]) for r in all_rows}
    for cls in ("replication", "amr", "mobile", "transfer", "integrase", "metal", "maintenance"):
        check(f"class {cls} present", cls in seen)
    names = {r["gene"] for r in all_rows}
    check("AMR genes bla/aac/tet present", any(n.startswith("bla") for n in names)
          and any(n.startswith("aac") for n in names) and any(n.startswith("tet") for n in names))
    check("transfer genes traA/traI/mobA present", {"traA", "traI", "mobA"} <= names)
    metal = [r for r in all_rows if r["category"] == "metal_resistance"]
    check("metal resistance genes present", {"pcoA", "silE", "merA", "cusA", "arsB"} <= {r["gene"] for r in metal})

    print("origin wrap")
    lengths = {r["sequence_id"]: int(r["length"]) for r in tsv(os.path.join(out, "ecoli_a", "truth.tsv"))}
    circular = {r["sequence_id"] for r in tsv(os.path.join(out, "ecoli_a", "truth_circular.tsv"))}
    wraps = [r for r in all_rows if int(r["start"]) > int(r["end"])]
    check("one gene has start > end", len(wraps) == 1)
    w = wraps[0]
    check("it is on a circular plasmid", w["sequence_id"] in circular)
    pieces = rm.sv.split_wrapped(int(w["start"]), int(w["end"]), lengths[w["sequence_id"]])
    check("it is drawn as two pieces meeting at the origin",
          len(pieces) == 2 and any(e == lengths[w["sequence_id"]] for _, e in pieces) and any(s == 0 for s, _ in pieces))

    print("repeat-rich plasmid")
    flagged = []
    for sample in sorted(os.listdir(out)):
        sdir = os.path.join(out, sample)
        if not os.path.isdir(sdir):
            continue
        rows = repeat_content.compute(os.path.join(sdir, "reference.fna"),
                                      repeat_content.read_truth(os.path.join(sdir, "truth.tsv")), sample)
        flagged += [(sample, r["sequence_id"]) for r in rows if r["repeat_rich"] == "yes"]
    check("exactly one plasmid is repeat-rich by the stage's own measure", len(flagged) == 1)
    sample, pid = flagged[0]
    regions = tsv(os.path.join(out, sample, "truth_repeat_regions.tsv"))
    check("repeat-rich plasmid has regions", len([r for r in regions if r["sequence_id"] == pid]) >= 2)
    check("regions are inside the plasmid", all(0 <= int(r["start"]) < int(r["end"]) <= lengths_of(out, sample)[pid]
                                                for r in regions))

    print("predicted proteins (annotation concordance)")
    import json
    straddle = {}
    for sample in ("ecoli_a", "kpneu_a"):
        sdir = os.path.join(out, sample)
        for tool in ("mob_like", "platon_like", "spades_like", "gplas_like", "weak_like"):
            path = os.path.join(sdir, f"{tool}.proteins.tsv")
            check(f"{sample}/{tool}.proteins.tsv parses", os.path.isfile(path) and len(tsv(path)) > 0)
    # project through the real builder so the fractions are the ones the scorecard reads
    for sample in ("kpneu_a",):
        sdir = os.path.join(out, sample)
        viz = os.path.join(sdir, "visualization", "alignment_blocks.json")
        os.makedirs(os.path.dirname(viz), exist_ok=True)
        subprocess.run([sys.executable, os.path.join(HERE, "..", "python", "build_visualization_data.py"),
                        "--truth", os.path.join(sdir, "truth.tsv"), "--results-dir", out, "--sample", sample,
                        "--reference", os.path.join(sdir, "reference.fna"),
                        "--protein-truth", os.path.join(sdir, "truth_proteins.tsv"),
                        "--circular-truth", os.path.join(sdir, "truth_circular.tsv"), "--out", viz],
                       check=True, capture_output=True)
        data = json.load(open(viz, encoding="utf-8"))
        for tool, payload in data["tools"].items():
            fr = [f["projection_fraction"] for f in payload["protein_features"]]
            straddle[tool] = (any(x >= 0.9 for x in fr), any(x < 0.9 for x in fr))
    check("some tool has projection fractions on both sides of 0.9", any(a and b for a, b in straddle.values()))
    check("tools differ in their fractions", len(set(straddle.values())) > 1 or len(straddle) > 1)
    check("mob_like projects every gene fully", straddle.get("mob_like") == (True, False))

    print("failed method")
    status = tsv(os.path.join(out, "tool_status.tsv"))
    check("the failed method has no proteins file", not os.path.exists(os.path.join(out, "abauma_b", "weak_like.proteins.tsv")))
    check("tool_status carries runtimes for completed runs",
          all(r["runtime_seconds"] for r in status if r["status"] == "completed"))

    print("FAILED: " + ", ".join(FAILED) if FAILED else "all checks passed")
    return 1 if FAILED else 0


def lengths_of(out, sample):
    return {r["sequence_id"]: int(r["length"]) for r in tsv(os.path.join(out, sample, "truth.tsv"))}


if __name__ == "__main__":
    sys.exit(main())
