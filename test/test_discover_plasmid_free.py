#!/usr/bin/env python3
"""discover_plasmid_free.py: single-replicon screening, paired-run choice, per-species and per-BioProject caps, the sheet and the audit."""

import csv
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))
import discover_plasmid_free as dpf  # noqa: E402

failures = []


def check(label, condition, detail=""):
    print(f"  {'PASS' if condition else 'FAIL'}: {label}{'' if condition else ' -- ' + str(detail)}")
    if not condition:
        failures.append(label)


def report(acc, components=1, chromosomes=1, tech="Oxford Nanopore; Illumina", biosample="SAMN1", project="PRJ1", level="Complete Genome", method="Flye v2.9"):
    return {"accession": acc, "organism": {"organism_name": "Escherichia coli str. X"},
            "assembly_stats": {"number_of_component_sequences": components, "total_number_of_chromosomes": chromosomes, "total_sequence_length": "5000000"},
            "assembly_info": {"assembly_level": level, "biosample": {"accession": biosample} if biosample else {}, "bioproject_accession": project, "sequencing_tech": tech,
                              "assembly_method": method, "release_date": "2024-01-01", "bioproject_lineage": [{"bioprojects": [{"accession": project}, {"accession": "PRJPARENT"}]}]}}


print("screening")
cand, why = dpf.screen(report("GCF_1.1"))
check("a single-replicon complete genome with a long-read platform is a candidate", cand and cand["technology"] == "hybrid" and cand["biosample"] == "SAMN1", (cand, why))
check("a genome with a plasmid (2 components) is not", dpf.screen(report("GCF_2.1", components=2))[1].startswith("has more than one replicon"))
check("a draft (not Complete Genome) is not", dpf.screen(report("GCF_3.1", level="Scaffold"))[1] == "not a Complete Genome")
check("no long-read platform recorded is not", "no long-read" in dpf.screen(report("GCF_4.1", tech="Illumina HiSeq"))[1])
check("no BioSample is not", dpf.screen(report("GCF_5.1", biosample=""))[1] == "no BioSample")
check("the assembly's BioProject lineage is kept for pairing", {"PRJ1", "PRJPARENT"} <= dpf.screen(report("GCF_6.1"))[0]["projects"])

print("choosing the run")
runs = [{"Run": "SRR1", "Platform": "ILLUMINA", "LibraryLayout": "PAIRED", "BioProject": "PRJ1", "bases": str(500_000_000)},      # 100x
        {"Run": "SRR2", "Platform": "ILLUMINA", "LibraryLayout": "PAIRED", "BioProject": "PRJ1", "bases": str(250_000_000)},      # 50x
        {"Run": "SRR3", "Platform": "ILLUMINA", "LibraryLayout": "SINGLE", "BioProject": "PRJ1", "bases": str(500_000_000)},
        {"Run": "SRR4", "Platform": "OXFORD_NANOPORE", "LibraryLayout": "SINGLE", "BioProject": "PRJ1", "bases": str(500_000_000)},
        {"Run": "SRR5", "Platform": "ILLUMINA", "LibraryLayout": "PAIRED", "BioProject": "PRJOTHER", "bases": str(500_000_000)},
        {"Run": "SRR6", "Platform": "ILLUMINA", "LibraryLayout": "PAIRED", "BioProject": "PRJ1", "bases": str(50_000_000)}]            # 10x: too shallow
run, depth, alternates = dpf.best_run(runs, {"PRJ1"}, 5_000_000)
check("the run closest to 100x wins; single-end, nanopore, other-study and shallow runs are ignored", run == "SRR1" and abs(depth - 100) < 1e-6 and alternates == ["SRR2"], (run, alternates))
check("no usable run gives none", dpf.best_run(runs[2:5], {"PRJ1"}, 5_000_000)[0] is None)


class FakeNcbi:
    def __init__(self):
        self.reports = {}
        self.runs = {}

    def complete_genomes(self, taxon, max_pages):
        return iter(self.reports.get(taxon, []))

    def runs_for_biosample(self, biosample):
        return self.runs.get(biosample, [])


print("selection and caps")
fake = FakeNcbi()
fake.reports[1] = [report(f"GCF_{i}.1", biosample=f"SAMN{i}", project=f"PRJ{i % 2}") for i in range(10)] + [report("GCF_99.1", components=3, biosample="SAMN99")]
for i in range(10):
    fake.runs[f"SAMN{i}"] = [{"Run": f"SRR{i}", "Platform": "ILLUMINA", "LibraryLayout": "PAIRED", "BioProject": f"PRJ{i % 2}", "bases": str(500_000_000)}]
fake.runs["SAMN3"] = []   # one without reads
audit = []
chosen = dpf.discover(fake, [("Escherichia coli", 1)], per_species=6, per_bioproject=3, max_pages=1, audit=audit)
check("at most 3 per BioProject and 6 per species (here 2 BioProjects x 3)", len(chosen) == 6 and max(__import__("collections").Counter(c["bioproject"] for c in chosen).values()) == 3, len(chosen))
check("an isolate with no paired run is audited with the reason, not chosen", any(a["biosample"] == "SAMN3" and "no paired Illumina run" in a["reason"] and a["outcome"] == "left out" for a in audit) or all(c["biosample"] != "SAMN3" for c in chosen))
check("a multi-replicon genome is audited as left out", any(a["accession"] == "GCF_99.1" and a["outcome"] == "left out" for a in audit))
again = dpf.discover(fake, [("Escherichia coli", 1)], per_species=6, per_bioproject=3, max_pages=1, audit=[])
check("the choice is deterministic", [c["accession"] for c in again] == [c["accession"] for c in chosen])

print("the sheet")
with tempfile.TemporaryDirectory() as tmp:
    out, aud = Path(tmp) / "neg.tsv", Path(tmp) / "audit.tsv"
    rows = dpf.write_outputs(chosen, audit, str(out), str(aud), 6, 3)
    text = out.read_text(encoding="utf-8")
    sheet = list(csv.DictReader((l for l in text.splitlines() if l and not l.startswith("#")), delimiter="\t"))
    check("every row has zero plasmids, a paired run, tier B and the plasmid-free control type", len(sheet) == 6 and all(r["assembly_plasmid_count"] == "0" and r["sra_run"].startswith("SRR") and r["truth_quality_tier"] == "B" and r["control_type"] == "plasmid_free" for r in sheet))
    check("source_study is blank (the validator would grade a named study tier A)", all(r["source_study"] == "" for r in sheet))
    check("every row says what the evidence does and does not show", all("not independently verified" in r["plasmid_free_evidence"] for r in sheet))
    check("the header comments state the limit", "not that the strain has none" in text)
    check("the audit lists every candidate", len(list(csv.DictReader(open(aud, encoding="utf-8"), delimiter="\t"))) == len(audit) and len(audit) >= 11)
    check("all declared columns are present", set(dpf.COLUMNS) <= set(sheet[0]))

print("the validator: a negative control is the opposite of every other row")
import validate_cohort as vc  # noqa: E402

_asm, _run, _sleep = vc.assembly_metadata, vc.run_metadata, vc.time.sleep
vc.time.sleep = lambda *a, **k: None


def fake_assembly(has_plasmid):
    return lambda acc, email=None, key=None: {"assembly_status": "Complete Genome", "datasets_assembly_level": "Complete Genome", "has_plasmid": has_plasmid, "biosample": "SAMN1",
                                              "bioprojects": ["PRJ1"], "derived_truth_technology": "hybrid", "sequencing_tech": "ONT; Illumina"}


vc.run_metadata = lambda run, email=None, key=None: {"run": run, "biosample": "SAMN1", "bioproject": "PRJ1", "platform": "ILLUMINA", "layout": "PAIRED", "bases": "1", "spots": "1", "avg_length": "150", "sample_name": "s"}
row = {"sample_id": "x", "assembly_accession": "GCF_1.1", "sra_run": "SRR1", "biosample": "SAMN1", "bioproject": "PRJ1", "truth_technology": "hybrid", "truth_quality_tier": "B",
       "source_study": "", "assembly_plasmid_count": "0", "control_type": "plasmid_free"}
try:
    vc.assembly_metadata = fake_assembly(False)
    errs = vc.verify_row(dict(row))["errors"]
    check("a plasmid-free control whose assembly declares no plasmid passes", not errs, errs)
    vc.assembly_metadata = fake_assembly(True)
    errs = vc.verify_row(dict(row))["errors"]
    check("a control whose assembly declares a plasmid is rejected", any("declares plasmid replicons" in e for e in errs), errs)
    vc.assembly_metadata = fake_assembly(False)
    errs = vc.verify_row(dict(row, assembly_plasmid_count="2"))["errors"]
    check("a control with a nonzero plasmid count is rejected", any("assembly_plasmid_count 0" in e for e in errs), errs)
    errs = vc.verify_row({k: v for k, v in row.items() if k != "control_type"})["errors"]
    check("an ordinary row with no plasmid declared is still rejected", any("does not declare plasmid replicons" in e for e in errs), errs)
finally:
    vc.assembly_metadata, vc.run_metadata, vc.time.sleep = _asm, _run, _sleep

print("the shipped negative-control cohort")
sheet_path = ROOT / "cohorts" / "negative-controls-v1.tsv"
if sheet_path.is_file():
    import subprocess
    shipped = list(csv.DictReader((l for l in sheet_path.read_text(encoding="utf-8").splitlines() if l and not l.startswith("#")), delimiter="\t"))
    check("every shipped control has zero plasmids, a run, tier B and the stated limit", len(shipped) > 50 and all(r["assembly_plasmid_count"] == "0" and r["sra_run"] and r["truth_quality_tier"] == "B"
          and r["control_type"] == "plasmid_free" and "not independently verified" in r["plasmid_free_evidence"] for r in shipped), len(shipped))
    check("the controls span several species and many studies", len({r["organism"] for r in shipped}) >= 8 and len({r["bioproject"] for r in shipped}) >= 40)
    others = set()
    for other in (ROOT / "cohorts").glob("*.tsv"):
        if other.name in ("negative-controls-v1.tsv", "accepted_accessions.tsv") or other.name.startswith("metagenomics"):
            continue
        others |= {r.get("biosample") for r in csv.DictReader((l for l in other.read_text(encoding="utf-8").splitlines() if l and not l.startswith("#")), delimiter="\t")}
    check("no control reuses a BioSample of another cohort", not ({r["biosample"] for r in shipped} & others), list({r["biosample"] for r in shipped} & others)[:3])
    done = subprocess.run([sys.executable, str(ROOT / "python" / "validate_cohort.py"), "--samples", str(sheet_path), "--verify-lock", str(ROOT / "cohorts" / "negative-controls-v1.lock.json")],
                          capture_output=True, text=True)
    check("the lock verifies", "COHORT LOCK VERIFIED" in done.stdout, done.stdout[-200:] + done.stderr[-200:])
else:
    check("the negative-control cohort is shipped", False)

print("ALL DISCOVER PLASMID-FREE TESTS PASSED" if not failures else "DISCOVER PLASMID-FREE TESTS FAILED: " + "; ".join(failures))
sys.exit(1 if failures else 0)
