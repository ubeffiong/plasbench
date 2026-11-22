#!/usr/bin/env python3
"""ISESCAN_SCOPE (python/annotate_reference.py): ISEScan searches only the replicons the truth table labels PLASMID (default) or every sequence.

  - ISEScan gets a FASTA with only the plasmid records, byte for byte; ids and coordinates are those of the reference (ISEScan reports per sequence)
  - the chromosome is recorded as not searched, never as zero insertion sequences (provenance carries scope, searched and not-searched ids, and a 'not evaluated' label)
  - the annotation cache never mixes scopes (or two labelings of the same reference); scope 'all' keeps its earlier key
  - a missing or mismatching truth table falls back to searching everything, with the reason recorded; no plasmid in the truth means nothing to search
  - features on the plasmids are the same with either scope (a fake ISEScan that reports per sequence)"""
import csv
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import annotate_reference as ar  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


FASTA = ">chr1 chromosome\nACGTACGTAC\nGTACGT\n>pl1 plasmid one\nTTTTCCCCGG\n>pl2\nGGGGAAAA\n"
TRUTH = "sequence_id\tmolecule_type\tlength\nchr1\tCHROMOSOME\t16\npl1\tPLASMID\t10\npl2\tPLASMID\t8\n"

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    ref, truth = tmp / "reference.fna", tmp / "truth.tsv"
    ref.write_bytes(FASTA.encode("utf-8"))
    truth.write_bytes(TRUTH.encode("utf-8"))
    seqs = ar.reference_sequences(ref)

    plan = ar.isescan_plan("plasmids", truth, seqs)
    check("plasmids scope: the two plasmids are searched, the chromosome is not",
          plan["effective"] == "plasmids" and plan["searched"] == ["pl1", "pl2"] and plan["not_searched"] == ["chr1"], plan)
    check("all scope searches everything", ar.isescan_plan("all", truth, seqs)["searched"] == ["chr1", "pl1", "pl2"])
    check("no truth table: everything is searched and the reason says so", ar.isescan_plan("plasmids", tmp / "nope.tsv", seqs)["effective"] == "all"
          and "no readable truth table" in ar.isescan_plan("plasmids", tmp / "nope.tsv", seqs)["reason"])
    other = tmp / "other.tsv"
    other.write_text("sequence_id\tmolecule_type\tlength\nzzz\tPLASMID\t5\n", encoding="utf-8")
    check("a truth table that names none of the sequences: everything is searched", ar.isescan_plan("plasmids", other, seqs)["effective"] == "all")
    none = tmp / "none.tsv"
    none.write_text("sequence_id\tmolecule_type\tlength\nchr1\tCHROMOSOME\t16\npl1\tCHROMOSOME\t10\npl2\tCHROMOSOME\t8\n", encoding="utf-8")
    p0 = ar.isescan_plan("plasmids", none, seqs)
    check("no plasmid in the truth: nothing to search (not an error)", p0["effective"] == "plasmids" and p0["searched"] == [], p0)

    # cache keys
    fp = {"isescan": "isescan 1.7.3"}
    key_all = ar.cache_key(ref, fp)
    fp_pl = dict(fp, isescan_scope=ar.scope_label(plan))
    key_pl = ar.cache_key(ref, fp_pl)
    relabelled = ar.isescan_plan("plasmids", truth, seqs)
    relabelled["searched"] = ["pl1"]
    key_pl2 = ar.cache_key(ref, dict(fp, isescan_scope=ar.scope_label(relabelled)))
    check("the cache key differs between plasmid-only and all", key_all != key_pl)
    check("... and between two different sets of searched plasmids", key_pl != key_pl2)
    check("scope label for 'all' is 'all' (and main() adds nothing to the fingerprint then, so older cache entries stay valid)", ar.scope_label(ar.isescan_plan("all", truth, seqs)) == "all")

    # the subset FASTA, byte for byte
    sub = tmp / "sub.fna"
    ar.write_subset_fasta(ref, ["pl1", "pl2"], sub)
    check("the subset FASTA holds exactly the plasmid records", sub.read_text(encoding="utf-8") == ">pl1 plasmid one\nTTTTCCCCGG\n>pl2\nGGGGAAAA\n", sub.read_text(encoding="utf-8"))

    # a fake ISEScan that reports per sequence: same plasmid features with either scope
    calls = []

    def fake_run(command, timeout):
        calls.append(command)
        seqfile, outdir = command[command.index("--seqfile") + 1], Path(command[command.index("--output") + 1])
        names = [line[1:].split()[0] for line in Path(seqfile).read_text(encoding="utf-8").splitlines() if line.startswith(">")]
        outdir.mkdir(parents=True, exist_ok=True)
        with open(outdir / "result.csv", "w", encoding="utf-8", newline="") as handle:
            handle.write("seqID,family,isBegin,isEnd\n")
            for name in names:
                handle.write(f"{name},IS3,2,5\n")
        return "", ""

    ar.run = fake_run
    ar.shutil.which = lambda name: "/fake/isescan.py" if name.startswith("isescan") else None
    ar.tool_version = lambda *a, **k: "isescan 1.7.3"
    ar.tool_readiness.check = lambda name: ("ok", "", "")
    feats_pl, status_pl = ar.call_isescan(ref, 10, seqs, tmp / "w1", 2, ar.isescan_plan("plasmids", truth, seqs))
    feats_all, status_all = ar.call_isescan(ref, 10, seqs, tmp / "w2", 2, ar.isescan_plan("all", truth, seqs))
    names = lambda feats: sorted((f["sequence_id"], f["start"], f["end"], f["label"]) for f in feats)  # noqa: E731
    check("with the plasmid scope ISEScan was given the subset FASTA, not the reference", Path(calls[0][calls[0].index("--seqfile") + 1]).name == "isescan_plasmids.fna", calls[0])
    check("the features on the plasmids are identical with either scope", names(feats_pl) == [x for x in names(feats_all) if x[0] != "chr1"] and len(feats_pl) == 2, (names(feats_pl), names(feats_all)))
    check("the plasmid scope reports no chromosome feature, and says the chromosome was not searched",
          all(f["sequence_id"] != "chr1" for f in feats_pl) and status_pl["chromosome_searched"] is False and status_pl["sequences_not_searched"] == ["chr1"], status_pl)
    check("scope 'all' records that the chromosome was searched", status_all["chromosome_searched"] is True and status_all["scope"] == "all", status_all)
    # a stale result of an earlier scope in the same work folder is never read back
    stale = tmp / "w1" / "isescan_plasmids"
    (stale / "old").mkdir(parents=True, exist_ok=True)
    (stale / "old" / "old.csv").write_text("seqID,family,isBegin,isEnd\nchr1,IS9,1,3\n", encoding="utf-8")
    feats_again, _ = ar.call_isescan(ref, 10, seqs, tmp / "w1", 2, ar.isescan_plan("plasmids", truth, seqs))
    check("results left in the work folder by an earlier run are not read back", all(f["label"] != "IS9" for f in feats_again), names(feats_again))
    feats_none, status_none = ar.call_isescan(ref, 10, seqs, tmp / "w3", 2, p0)
    check("no plasmid: ISEScan is not started, the status is ok with 0 features and the note", feats_none == [] and status_none["status"] == "ok" and "nothing to search" in status_none["note"], status_none)

    # main(): provenance and the 'not evaluated' label
    ar.call_isescan.__defaults__  # noqa: B018 (the real function is used again below)
    out, prov = tmp / "truth_features.tsv", tmp / "prov.json"
    for name in ("call_mob_typer", "call_abricate", "call_amrfinder", "call_isfinder", "call_barrnap"):
        setattr(ar, name, lambda *a, **k: ([], {"status": "ok", "features": 0}))
    sys.argv = ["annotate_reference.py", "--reference", str(ref), "--out", str(out), "--provenance", str(prov), "--truth", str(truth), "--threads", "4", "--cache-dir", ""]
    os.environ.pop("ISESCAN_SCOPE", None)
    ar.main()
    record = json.loads(prov.read_text(encoding="utf-8"))
    nes = record.get("not_evaluated_sequences", {}).get("insertion_sequence", {})
    check("provenance: insertion sequences on the chromosome are labelled 'not evaluated (chromosome not searched)'",
          nes.get("label") == "not evaluated (chromosome not searched)" and nes.get("sequences") == ["chr1"], record)
    rows = list(csv.DictReader(out.open(encoding="utf-8"), delimiter="\t"))
    check("the feature table has no chromosome insertion-sequence row (never a zero count)", all(r["sequence_id"] != "chr1" for r in rows) and len(rows) == 2, rows)

    # the settings
    config = (ROOT / "config" / "config.sh").read_text(encoding="utf-8")
    check("ISESCAN_SCOPE defaults to plasmids in config.sh", 'ISESCAN_SCOPE="${ISESCAN_SCOPE:-plasmids}"' in config)
    check("the thread plan leaves CPUs for the short callers", ar.thread_plan(6) == (1, 2, 4) and ar.thread_plan(1) == (1, 1, 1) and ar.thread_plan(16)[2] == 14, ar.thread_plan(6))

print("\nall ISEScan scope checks passed" if ok else "\nFAILED")
sys.exit(0 if ok else 1)
