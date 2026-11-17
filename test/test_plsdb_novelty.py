#!/usr/bin/env python3
"""plsdb_novelty.py: known / related / novel classes against PLSDB, recovery by class, novelty as a driver, the report section."""

import csv
import json
import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))
import database_containment as dc  # noqa: E402
import performance_drivers as pdv  # noqa: E402
import plsdb_novelty as pn  # noqa: E402
import report_learnings as rl  # noqa: E402

failures = []


def check(label, condition, detail=""):
    print(f"  {'PASS' if condition else 'FAIL'}: {label}{'' if condition else ' -- ' + str(detail)}")
    if not condition:
        failures.append(label)


def write_tsv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


print("classification")
check("a close relative (coverage 0.9, identity 0.97) is known", pn.classify(0.9, 0.97, 0.8, 0.95, 0.3) == "known")
check("high coverage but low identity is not known: related", pn.classify(0.9, 0.90, 0.8, 0.95, 0.3) == "related")
check("a shared module (coverage 0.4) is related", pn.classify(0.4, 0.99, 0.8, 0.95, 0.3) == "related")
check("little shared sequence is novel", pn.classify(0.1, 0.99, 0.8, 0.95, 0.3) == "novel")
check("no alignment at all is novel", pn.classify(0.0, 0.0, 0.8, 0.95, 0.3) == "novel")

rng = random.Random(3)
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    data, res = tmp / "data", tmp / "res"
    sheet_rows, plan = [], {}
    n_studies, per_study = 12, 3
    for s in range(n_studies):
        for k in range(per_study):
            sample = f"s{s}_{k}"
            sheet_rows.append([sample, "Escherichia coli", f"PRJ{s}", "100", "older"])
            truth_rows, fasta, per_plasmid = [], [], []
            for q in range(3):
                seq_id = f"{sample}_p{q}"
                klass = ("known", "related", "novel")[q]
                plan[(sample, seq_id)] = klass
                truth_rows.append([seq_id, "PLASMID"])
                fasta.append(f">{seq_id}\n{'ACGT' * 50}\n")
                base = {"known": 0.9, "related": 0.7, "novel": 0.5}[klass]
                comp = min(1.0, max(0.0, base + rng.gauss(0, 0.05)))
                per_plasmid.append([sample, "tool_x", "short_read", seq_id, "200", "0", f"{comp:.4f}", "1" if comp >= 0.9 else "0"])
            truth_rows.append([f"{sample}_chr", "CHROMOSOME"])
            fasta.append(f">{sample}_chr\n{'TTGA' * 400}\n")
            write_tsv(data / sample / "truth.tsv", ["sequence_id", "molecule_type"], truth_rows)
            (data / sample).mkdir(parents=True, exist_ok=True)
            (data / sample / "reference.fna").write_text("".join(fasta), encoding="utf-8")
            write_tsv(res / sample / "tool_x.per_plasmid.tsv", ["sample", "tool", "analysis_track", "sequence_id", "length", "covered_bp", "completeness", "recovered"], per_plasmid)
    sheet = tmp / "sheet.tsv"
    write_tsv(sheet, ["sample_id", "organism", "bioproject", "read_depth_x", "selection_arm"], sheet_rows)
    plsdb = tmp / "plsdb" / "sequences.fasta"
    plsdb.parent.mkdir()
    plsdb.write_text(">NZ_X\nACGT\n", encoding="utf-8")
    (plsdb.parent / "sequences.provenance.json").write_text(json.dumps({"url": "file://x", "utc_date": "2025-01-31", "sha256": "ab" * 32}), encoding="utf-8")

    seen = {}

    def fake_containment(query_fasta, database_fasta, threads, preset="asm5"):
        seen["preset"] = preset
        ids = [l[1:].strip() for l in open(query_fasta, encoding="utf-8") if l.startswith(">")]
        out = {}
        for i, qid in enumerate(ids):
            # the queries come in sample order, three plasmids per sample: known, related, novel
            out[qid] = [("NZ_K", 0.95, 0.99), ("NZ_R", 0.45, 0.97), ("NZ_N", 0.05, 0.9)][i % 3]
        return out

    real = dc.containment
    dc.containment = fake_containment
    try:
        samples = [r[0] for r in sheet_rows]
        rows, recovery, summary = pn.run(str(data), str(res), samples, str(plsdb), str(sheet), str(res / "benchmark.plsdb_novelty"), bootstrap=300)
    finally:
        dc.containment = real

    print("the novelty table")
    got = {(r["sample"], r["sequence_id"]): r["novelty"] for r in rows}
    check("every truth plasmid is classed, chromosomes are not queried", len(rows) == n_studies * per_study * 3 and all("_chr" not in r["sequence_id"] for r in rows), len(rows))
    check("the classes are the ones the aligner implied", got == plan)
    check("the alignment uses the divergence-tolerant preset asm20", seen.get("preset") == "asm20", seen)
    check("class counts are in the summary", summary["classes"] == {"known": 36, "related": 36, "novel": 36}, summary["classes"])
    check("PLSDB provenance (release date, checksum) is carried", summary["plsdb_provenance"]["utc_date"] == "2025-01-31")
    check("the caveats say novelty is relative to the release and never changes a score", any("relative to the PLSDB release" in c for c in summary["caveats"]) and any("never changes" in c for c in summary["caveats"]))

    print("recovery by novelty")
    by = {r["novelty"]: r for r in recovery}
    check("known plasmids are recovered best, novel worst", by["known"]["mean_completeness"] > by["related"]["mean_completeness"] > by["novel"]["mean_completeness"],
          {k: v["mean_completeness"] for k, v in by.items()})
    check("the novel gap to known is near 0.4 with an interval that excludes 0", 0.3 < by["novel"]["gap_to_known"] < 0.5 and by["novel"]["gap_ci_low"] > 0 and by["novel"]["status"] == "gap supported", by["novel"])
    check("the reference class has no gap", by["known"]["gap_to_known"] is None and by["known"]["status"] == "reference")
    check("studies are counted", by["novel"]["n_studies"] == n_studies)

    print("files")
    for suffix in (".tsv", "_recovery.tsv", ".json"):
        check(f"benchmark.plsdb_novelty{suffix} is written", (res / f"benchmark.plsdb_novelty{suffix}").is_file())

    print("novelty is a driver in the regression")
    class Args:
        min_plasmids = 30
        min_clusters = 5
        bootstrap = 200
        seed = 5

    out = pdv.run(str(res), str(data), str(sheet), str(res / "none.tsv"), str(res / "drivers"), Args, str(res / "benchmark.plsdb_novelty.tsv"))
    terms = {t["term"]: t for t in out[0]["terms"]}
    check("PLSDB novel and related are terms against known", "PLSDB novel" in terms and "PLSDB related" in terms and terms["PLSDB novel"]["reference"] == "known", list(terms))
    check("the novel effect is negative and supported", terms["PLSDB novel"]["estimate"] < -0.3 and terms["PLSDB novel"]["status"] == "supported", terms["PLSDB novel"])
    out_none = pdv.run(str(res), str(data), str(sheet), str(res / "none.tsv"), str(res / "drivers2"), Args)
    check("without a novelty table the driver is simply absent", all(t["driver"] != "plsdb_novelty" for t in out_none[0]["terms"]) or not out_none[0]["terms"])

    print("the report section")
    page = "<section id='recommendations'></section><a href='#recommendations'>Recommendations</a>"
    html = rl.inject(page, str(res), str(res / "scores.tsv"))
    check("the novelty section is injected with the counts, the release and the gap", "id='learn-novelty'" in html and "36 known" in html and "2025-01-31" in html and "gap supported" in html)
    check("the drivers section is injected", "id='learn-drivers'" in html and "PLSDB novel" in html)
    empty = rl.novelty_section(None, None)
    check("without the analysis the section says Not run and why", "Not run" in empty and "PLSDB_FASTA" in empty)

print("ALL PLSDB NOVELTY TESTS PASSED" if not failures else "PLSDB NOVELTY TESTS FAILED: " + "; ".join(failures))
sys.exit(1 if failures else 0)
