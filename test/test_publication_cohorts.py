#!/usr/bin/env python3
"""Publication cohorts: the builder (truth matching, audit, mixed cohort), the shipped published tables, and the cohort details."""

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "python"))
import build_publication_cohorts as bpc  # noqa: E402

failures = []


def check(label, condition, detail=""):
    print(f"  {'PASS' if condition else 'FAIL'}: {label}{'' if condition else ' -- ' + str(detail)}")
    if not condition:
        failures.append(label)


def write(path, header, rows, comments=()):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        for line in comments:
            handle.write("# " + line + "\n")
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def read(path):
    with open(path, encoding="utf-8") as handle:
        return list(csv.DictReader((l for l in handle if l.strip() and not l.startswith("#")), delimiter="\t"))


print("truth matching")
check("a record titled plasmid, or a short untitled one, is a plasmid; a chromosome is not", bpc.is_plasmid_record({"title": "x plasmid pA", "length": 5}) and bpc.is_plasmid_record({"title": "x unnamed1, complete sequence", "length": 90000})
      and not bpc.is_plasmid_record({"title": "x chromosome", "length": 5000000}) and not bpc.is_plasmid_record({"title": "x", "length": 5000000}))
check("RefSeq NZ_ prefix and version are ignored", bpc.accession_set("NZ_CP001.2;CP002.1, NC_000003.1") == {"CP001", "CP002", "000003"})
P = {"CP1", "CP2"}
check("exact", bpc.match_kind(P, {"CP1", "CP2"}) == "exact")
check("superset: the assembly has more plasmids than the paper used", bpc.match_kind(P, {"CP1", "CP2", "CP3"}) == "superset")
check("subset: the assembly lacks one the paper used", bpc.match_kind(P, {"CP1"}) == "subset")
check("overlap without containment", bpc.match_kind(P, {"CP1", "CP9"}) == "overlap")
check("none shared", bpc.match_kind(P, {"CP9"}) == "none")
check("nothing to check against is unchecked, not exact", bpc.match_kind(P, set()) == "unchecked")

print("the builder on a fixture")
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    ledgers = tmp / "ledgers"
    cohorts = tmp / "cohorts"
    ledger_cols = ["sample_id", "assembly_accession", "sra_run", "organism", "biosample", "source_study", "paper_identifier", "truth_chromosome_accession", "truth_plasmid_accessions"]
    write(ledgers / "mobsuite_benchmark_candidates.tsv", ledger_cols, [
        ["a", "", "R1", "E. coli", "SAMN1", "MOB", "R1", "CH1", "CP1.1;CP2.1"],
        ["b", "", "R2", "E. coli", "SAMN2", "MOB", "R2", "CH2", "CP3.1"],
        ["c", "", "R3", "E. coli", "SAMN3", "MOB", "R3", "CH3", "CP4.1;CP5.1"],
        ["d", "", "R4", "K. pneumoniae", "SAMN4", "MOB", "R4", "CH4", "CP6.1"],
        ["e", "", "R5", "K. pneumoniae", "SAMN5", "MOB", "R5", "CH5", "CP7.1"]], ["# candidate ledger"])
    write(ledgers / "plsmd2026_filtered_candidates.tsv", ledger_cols, [["a2", "", "R1", "E. coli", "SAMN1", "PLSMD", "R1", "CH1", "CP1.1;CP2.1"]])
    v4_cols = ["sample_id", "assembly_accession", "sra_run", "organism", "biosample", "truth_quality_tier", "plasmid_accessions", "source_study"]
    write(cohorts / "public-v4.tsv", v4_cols, [
        ["a", "GCF_1", "SRR1", "E. coli", "SAMN1", "B", "NZ_CP1.1;NZ_CP2.1", "v4"],
        ["b", "GCF_2", "SRR2", "E. coli", "SAMN2", "B", "NZ_CP3.1;NZ_CP30.1", "v4"],
        ["c", "GCF_3", "SRR3", "E. coli", "SAMN3", "B", "NZ_CP4.1", "v4"],
        ["d", "GCF_4", "SRR4", "K. pneumoniae", "SAMN4", "B", "NZ_CP99.1", "v4"]])
    args = type("A", (), {"cohorts_dir": str(cohorts), "ledger_dir": str(ledgers), "resolved": [], "online": False, "truth_cache": ""})()
    header, per_study, audit = bpc.build(args)
    mob = {r["biosample"]: r for r in per_study["mobsuite"]["rows"]}
    check("exact, superset and subset isolates are included with their truth_match", {k: v["truth_match"] for k, v in mob.items()} == {"SAMN1": "exact", "SAMN2": "superset", "SAMN3": "subset"}, {k: v["truth_match"] for k, v in mob.items()})
    check("an assembly sharing no plasmid with the paper's truth is left out", "SAMN4" not in mob)
    outcomes = {a["biosample"]: a for a in audit if a["study"] == "mobsuite"}
    check("the audit says why: plasmids differ", "none of the assembly's plasmids" in outcomes["SAMN4"]["reason"], outcomes["SAMN4"])
    check("the audit says why: not found", outcomes["SAMN5"]["outcome"] == "left out" and "not in public-v4" in outcomes["SAMN5"]["reason"], outcomes["SAMN5"])
    check("every candidate is accounted for", len(outcomes) == 5)
    check("the verified public-v4 row is carried over unchanged", mob["SAMN1"]["assembly_accession"] == "GCF_1" and mob["SAMN1"]["sra_run"] == "SRR1")
    check("the published sample and study are recorded", mob["SAMN1"]["published_sample"] == "R1" and mob["SAMN1"]["published_studies"] == "mobsuite")

    print("a resolved row, checked online (stand-in) and offline")
    resolved_dir = tmp / "res"
    write(resolved_dir / "resolved.tsv", ["sample_id", "assembly_accession", "sra_run", "organism", "biosample", "bioproject", "truth_technology"], [["e", "GCA_5", "SRR5", "K. pneumoniae", "SAMN5", "PRJ5", "hybrid"]])
    args.resolved = [f"mobsuite={resolved_dir / 'resolved.tsv'}"]
    _, per_study2, audit2 = bpc.build(args)
    left = [a for a in audit2 if a["biosample"] == "SAMN5"][0]
    check("offline, a resolved row whose truth cannot be checked is left out, not trusted", left["outcome"] == "left out" and "could not be checked" in left["reason"], left)

    class FakeEntrez:
        def assembly_info(self, accession):
            return {"assembly_method": "Flye v2.9", "sequencing_tech": "Oxford Nanopore; Illumina"}

        def assembly_records(self, accession):
            return [{"accession": "CP7.1", "title": "Klebsiella pneumoniae plasmid pX, complete sequence", "length": 90000},
                    {"accession": "CH5.1", "title": "Klebsiella pneumoniae strain K chromosome, complete genome", "length": 5300000},
                    {"accession": "CH6.1", "title": "Klebsiella pneumoniae strain K", "length": 5300000}]

    original = bpc.Entrez
    bpc.Entrez = lambda *a, **k: FakeEntrez()
    args.online = True
    _, per_study3, audit3 = bpc.build(args)
    bpc.Entrez = original
    row = [r for r in per_study3["mobsuite"]["rows"] if r["biosample"] == "SAMN5"]
    check("online, the chromosome record is excluded and the plasmids are matched: exact", row and row[0]["truth_match"] == "exact" and row[0]["truth_quality_tier"] == "B" and row[0]["truth_technology"] == "hybrid", row)

    print("the files")
    out = tmp / "out"
    done = subprocess.run([sys.executable, str(ROOT / "python" / "build_publication_cohorts.py"), "--cohorts-dir", str(cohorts), "--ledger-dir", str(ledgers), "--out-dir", str(out),
                           "--audit", str(out / "audit.tsv")], capture_output=True, text=True)
    check("the command runs", done.returncode == 0, done.stdout + done.stderr)
    check("one cohort per study and the mixed cohort", (out / "pub-mobsuite.tsv").is_file() and (out / "pub-plsmd-filtered.tsv").is_file() and (out / "publication-v1.tsv").is_file())
    mixed = read(out / "publication-v1.tsv")
    by = {r["biosample"]: r for r in mixed}
    check("an isolate in two studies appears once in the mixed cohort, listing both", len(mixed) == len({r["biosample"] for r in mixed}) and by["SAMN1"]["published_studies"] == "mobsuite;plsmd_filtered", by.get("SAMN1"))
    meta = json.loads((out / "pub-mobsuite.publication.json").read_text(encoding="utf-8"))
    check("the meta has the funnel, truth match counts and the compare command", meta["funnel"][0]["n"] == 5 and meta["funnel"][-1]["n"] == 3 and meta["compare_command"].startswith("plasbench compare-published") and meta["schema_version"] == 1, meta)
    check("the header comments say it is tier B and how to compare", "tier B" in (out / "pub-mobsuite.tsv").read_text(encoding="utf-8").split("\n")[2])
    check("the audit lists every candidate", len(read(out / "audit.tsv")) >= 5)

print("the validator and experiments with several runs")
import validate_cohort as vc  # noqa: E402

_ncbi_json, _fetch = vc.ncbi_json, vc.fetch
vc.ncbi_json = lambda *a, **k: {"esearchresult": {"idlist": ["1"]}}
vc.fetch = lambda *a, **k: ("Run,BioSample,BioProject,SampleName,Platform,LibraryLayout,bases,spots,avgLength\n"
                            "SRR1,SAMN1,PRJ1,s,ILLUMINA,PAIRED,100,10,150\nSRR2,SAMN1,PRJ1,s,ILLUMINA,PAIRED,200,20,150\n")
try:
    check("run-info of an experiment with two runs gives the requested run's row", vc.run_metadata("SRR2")["spots"] == "20")
    try:
        vc.run_metadata("SRR3")
        check("a run that is not in the experiment is still refused", False)
    except ValueError as exc:
        check("a run that is not in the experiment is still refused", "could not retrieve run-info row for SRR3" in str(exc))
finally:
    vc.ncbi_json, vc.fetch = _ncbi_json, _fetch

print("the shipped published tables")
pub = ROOT / "cohorts" / "published"
for study, plasmids in (("plsmd2026", 513),):
    rows = read(pub / f"{study}.published.tsv")
    meta = json.loads((pub / f"{study}.meta.json").read_text(encoding="utf-8"))
    check(f"{study}: 3 tools x {plasmids} plasmids", len(rows) == 3 * plasmids, len(rows))
    check(f"{study}: every row has a BioSample", all(r["biosample"] for r in rows))
    filtered = [float(r["value"]) for r in rows if r["tool"] == "plsMD" and r["subset"] == "filtered"]
    check("plsMD filtered: 244 plasmids and mean recall 93.07 percent (the paper's reported value)", len(filtered) == 244 and abs(sum(filtered) / 244 - 0.9307) < 5e-4, (len(filtered), sum(filtered) / max(len(filtered), 1)))
    ledger = {r["biosample"] for n in ("plsmd2026_filtered", "plsmd2026_novel") for r in read(ROOT / "cohorts" / "candidates" / f"{n}_candidates.tsv")}
    check("every published BioSample is in a candidate ledger", {r["biosample"] for r in rows} <= ledger)
    check("source checksum and retrieval date are recorded", len(meta["source"]["sha256"]) == 64 and meta["source"]["retrieved"])
tx = read(pub / "teixeira2025.published.tsv")
txmeta = json.loads((pub / "teixeira2025.meta.json").read_text(encoding="utf-8"))
check("teixeira2025: 13 tools x 250 isolates plus PlasBin-Flow, 6 metrics each", len({r["tool"] for r in tx}) == 13 and len({r["biosample"] for r in tx}) == 250, (len({r["tool"] for r in tx}), len({r["biosample"] for r in tx})))
check("teixeira2025: the metadata says the numbers are computed, not the paper's printed ones", "computed" in txmeta["what_it_is"].lower() and any("not the figures printed" in c for c in txmeta["caveats"]))
registry = {r["tool"] for r in read(ROOT / "config" / "tool_capabilities.tsv")}
for study in ("plsmd2026", "teixeira2025"):
    mapped = {v for v in json.loads((pub / f"{study}.meta.json").read_text(encoding="utf-8"))["tool_map"].values() if v}
    check(f"{study}: every mapped PlasBench tool exists in the tool registry", mapped <= registry, mapped - registry)
    metas = json.loads((pub / f"{study}.meta.json").read_text(encoding="utf-8"))["metrics"]
    check(f"{study}: every metric names its comparability, tolerance and PlasBench source", all(m.get("comparability") and m.get("tolerance") and m.get("plasbench_source") for m in metas))

print("the shipped publication cohorts")
for name in ("pub-mobsuite", "pub-plsmd-filtered", "pub-plsmd-novel", "publication-v1"):
    sheet = ROOT / "cohorts" / f"{name}.tsv"
    if not sheet.is_file():
        check(f"{name} is shipped", False)
        continue
    rows = read(sheet)
    meta = json.loads((ROOT / "cohorts" / f"{name}.publication.json").read_text(encoding="utf-8"))
    check(f"{name}: {len(rows)} isolates, as its meta says", len(rows) == meta["isolates"] and len({r["biosample"] for r in rows}) == len(rows))
    check(f"{name}: no isolate whose plasmids differ from the paper's", all(r["truth_match"] in ("exact", "superset", "subset", "inferred") for r in rows), {r["truth_match"] for r in rows})
    check(f"{name}: tier B and an assembly and run for every row", all(r["truth_quality_tier"] == "B" and r["assembly_accession"] and r["sra_run"] for r in rows))
    lock = ROOT / "cohorts" / f"{name}.lock.json"
    if lock.is_file():
        done = subprocess.run([sys.executable, str(ROOT / "python" / "validate_cohort.py"), "--samples", str(sheet), "--verify-lock", str(lock)], capture_output=True, text=True)
        check(f"{name}: the lock verifies", "COHORT LOCK VERIFIED" in done.stdout, done.stdout[-200:] + done.stderr[-200:])
    else:
        check(f"{name} has a lock", False)

print("the window")
from plasbench import cohort_info  # noqa: E402

info = cohort_info.info(ROOT, "pub-plsmd-filtered") if (ROOT / "cohorts" / "pub-plsmd-filtered.tsv").is_file() else None
check("cohort details carry the publication block with the shipped outcome table", info is not None and info.get("publication") and info["publication"]["published_tables"] == ["plsmd2026"], info and info.get("publication"))
html = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
check("the window shows the publication card and the compare command", "function publicationCard(d)" in html and "publicationCard(d)}" in html and "compare_command" in html)

print("ALL PUBLICATION COHORT TESTS PASSED" if not failures else "PUBLICATION COHORT TESTS FAILED: " + "; ".join(failures))
sys.exit(1 if failures else 0)
