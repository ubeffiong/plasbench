#!/usr/bin/env python3
"""plasbench/isolate_scan.py and `plasbench scan-isolates`: find isolates in a folder tree, on realistic messy fixtures.

Each case asserts the exact selection, confidence and issues, and that scanning never touches a file.
"""
import gzip
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "python"))
from plasbench import isolate_scan as sc  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def fq(path, n=6, mate=1, length=40):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(f"@r{i}/{mate}\n{'ACGT' * (length // 4)}\n+\n{'I' * length}\n" for i in range(n))
    if str(path).lower().endswith(".gz"):
        with gzip.open(path, "wt") as h:
            h.write(text)
    else:
        path.write_text(text)


def fa(path, headers=("NZ_CP000001.1 Escherichia coli strain X chromosome, complete genome",), bp=25000, seed=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    import random
    rnd = random.Random(seed)
    path.write_text("".join(f">{h}\n" + "".join(rnd.choice("ACGT") for _ in range(bp)) + "\n" for h in headers))


def pair(d, stem, ext="fastq.gz", style="_R{}"):
    fq(d / f"{stem}{style.format(1)}.{ext}", mate=1)
    fq(d / f"{stem}{style.format(2)}.{ext}", mate=2)


def codes(s):
    return {i["code"] for i in s["issues"]}


def by_id(res):
    return {s["sample_id"]: s for s in res["samples"]}


def snapshot(root):
    return {str(p): (p.stat().st_mtime_ns, p.stat().st_size) for p in Path(root).rglob("*") if p.is_file() and not p.is_symlink()}


def main():
    tmp = Path(tempfile.mkdtemp())

    print("clean per-sample folders, Illumina names")
    a = tmp / "a"
    pair(a / "KP01", "KP01", style="_R{}_001")
    fa(a / "KP01" / "KP01.fasta")
    pair(a / "KP02", "KP02", style="_{}")
    fa(a / "KP02" / "reference" / "genome.fna", seed=2)
    (a / "KP02" / "notes.pdf").write_text("x")
    (a / "KP02" / "aln.bam").write_text("x")
    before = snapshot(a)
    res = sc.scan(a)
    ids = by_id(res)
    check("two samples found", sorted(ids) == ["KP01", "KP02"], sorted(ids))
    k1 = ids["KP01"]
    check("KP01 reads and reference chosen, high confidence, ready", k1["reads_1"].endswith("KP01_R1_001.fastq.gz") and k1["reads_2"].endswith("KP01_R2_001.fastq.gz")
          and k1["reference"].endswith("KP01.fasta") and k1["confidence"] == "high" and k1["status"] == "ready", (k1["confidence"], k1["issues"]))
    k2 = ids["KP02"]
    check("KP02 reference in a reference/ sub-folder is found with reasons", k2["reference"].endswith("genome.fna") and any("reference" in w for w in k2["why"]["reference"]), k2["why"])
    kinds = {u["kind"]: u["count"] for u in res["unrecognised"]}
    check("unrelated files are reported with counts", kinds.get("documents") == 1 and kinds.get("alignments") == 1, kinds)
    check("scanning changed nothing (mtimes, sizes, file list)", snapshot(a) == before)

    print("lanes, SRA, dotted mates, case differences")
    b = tmp / "b"
    for lane in ("L001", "L002"):
        pair(b, f"Iso7_S3_{lane}", style="_R{}_001")
    pair(b, "SRR1234567", style="_{}")
    pair(b, "Wound.A", style=".{}", ext="fq.gz")
    pair(b, "UPPER", ext="FASTQ.GZ", style="_R{}")
    res = sc.scan(b)
    ids = by_id(res)
    check("lanes become one isolate, listed and flagged (never merged silently)", "Iso7" in ids and len(ids["Iso7"]["lanes"]) == 2 and "lanes" in codes(ids["Iso7"])
          and ids["Iso7"]["status"] == "review", ids.get("Iso7"))
    check("SRA style, dotted mates and upper-case extensions are paired", {"SRR1234567", "Wound.A", "UPPER"} <= set(ids), sorted(ids))
    check("no reference is an issue, not a guess", all("no_reference" in codes(s) for s in ids.values()) and ids["UPPER"]["reference"] is None)

    print("assembler output is not a reference")
    c = tmp / "c"
    pair(c / "S9", "S9")
    fa(c / "S9" / "spades" / "contigs.fasta", headers=[f"NODE_{i}_length_900_cov_5.2" for i in range(1, 4)])
    fa(c / "S9" / "unicycler" / "assembly.fasta", headers=["1 length=3000 depth=1.00x circular=true"])
    fa(c / "S9" / "S9.assembly.fasta", headers=["1 length=3000 depth=1.00x"], seed=5)
    res = sc.scan(c)
    s9 = by_id(res)["S9"]
    check("contigs/assembly files are not taken as the reference", s9["reference"] is None and "no_reference" in codes(s9), (s9["reference"], s9["issues"]))
    check("they are listed as assembler output", any("assembler output" in u["kind"] and u["count"] == 3 for u in res["unrecognised"]), res["unrecognised"])

    print("two candidate references")
    d = tmp / "d"
    pair(d / "E5", "E5")
    fa(d / "E5" / "E5_complete_reference.fasta", seed=1)
    fa(d / "E5" / "other.fasta", headers=("seq1",), seed=2)
    s = by_id(sc.scan(d))["E5"]
    check("the better-evidenced FASTA wins, the other is an alternative", s["reference"].endswith("E5_complete_reference.fasta") and len(s["alternatives"]["reference"]) == 1
          and s["confidence"] == "medium" and "ambiguous_reference" not in codes(s), (s["reference"], s["confidence"], codes(s)))
    d2 = tmp / "d2"
    pair(d2 / "E6", "E6")
    fa(d2 / "E6" / "one.fasta", seed=1)
    fa(d2 / "E6" / "two.fasta", seed=2)
    s = by_id(sc.scan(d2))["E6"]
    check("two equal candidates: an ambiguity issue, low confidence, both listed", "ambiguous_reference" in codes(s) and s["confidence"] == "low" and s["status"] == "review"
          and len(s["alternatives"]["reference"]) == 1, (codes(s), s["confidence"]))

    print("missing mate, shared folder, id sanitising, duplicates")
    e = tmp / "e"
    fq(e / "Lone_R1.fastq.gz")
    pair(e, "Sample 1 (a)", style="_R{}")
    pair(e / "x", "same")
    pair(e / "y", "Same")
    fa(e / "Sample 1 (a)_ref.fasta")
    pair(e, "Other", style="_R{}")
    res = sc.scan(e)
    ids = by_id(res)
    lone = ids["Lone"]
    check("a missing R2 is a blocking error", lone["reads_2"] is None and "missing_reads_2" in codes(lone) and lone["status"] == "blocked", lone["issues"])
    check("an unsafe id is sanitised and says so", "Sample_1_a" in ids and "id_sanitised" in codes(ids["Sample_1_a"]), sorted(ids))
    check("the reference in a shared folder is tied by name to the right sample only", ids["Sample_1_a"]["reference"].endswith("_ref.fasta") and ids["Other"]["reference"] is None)
    dup = [s for s in res["samples"] if s["source_id"].lower() == "same"]
    check("ids differing only in case are de-duplicated (Windows is case-insensitive)", len(dup) == 2 and len({s["sample_id"].lower() for s in dup}) == 2
          and any("duplicate_id" in codes(s) for s in dup), [s["sample_id"] for s in dup])

    print("hidden, ignored, deep, unreadable, cap, symlink loop")
    f = tmp / "f"
    pair(f / "S1", "S1")
    pair(f / ".git", "hidden")
    pair(f / "results", "old")
    (f / "node_modules").mkdir()
    pair(f / "d1" / "d2" / "d3" / "d4", "deep")
    res = sc.scan(f, max_depth=2)
    sk = res["skipped"]
    check("hidden and ignored folders are skipped and counted", sk.get("hidden_folder") == 1 and sk.get("ignored_folder:results") == 1 and sk.get("ignored_folder:node_modules") == 1, sk)
    check("depth limit is honoured and counted", set(by_id(res)) == {"S1"} and sk.get("too_deep_folder", 0) >= 1, (sorted(by_id(res)), sk))
    g = tmp / "g"
    for i in range(30):
        (g / f"n{i}.txt").parent.mkdir(parents=True, exist_ok=True)
        (g / f"n{i}.txt").write_text("x")
    res = sc.scan(g, max_files=10)
    check("the file cap stops the walk, with a warning, without raising", res["skipped"].get("max_files_reached") == 1 and any("stopped after 10" in w for w in res["warnings"]), res["skipped"])
    if hasattr(os, "symlink"):
        h = tmp / "h"
        pair(h / "S1", "S1")
        try:
            os.symlink(h, h / "S1" / "loop", target_is_directory=True)
            res = sc.scan(h, follow_symlinks=True)
            check("a symlink loop is detected, not followed forever", res["skipped"].get("symlink_loop", 0) >= 1 and "S1" in by_id(res), res["skipped"])
            res = sc.scan(h)
            check("symlinked folders are skipped by default and counted", res["skipped"].get("symlink_folder") == 1)
        except OSError:
            print("  skip  symlinks not permitted here")
    if os.name != "nt" and os.geteuid() != 0:
        u = tmp / "u"
        pair(u / "S1", "S1")
        (u / "locked").mkdir()
        (u / "locked").chmod(0)
        res = sc.scan(u)
        (u / "locked").chmod(0o755)
        check("an unreadable folder is collected as a warning, never raised", res["skipped"].get("unreadable_folder") == 1 and res["warnings"], res["skipped"])
    else:
        print("  skip  unreadable-folder case needs a non-root POSIX user")

    print("progress and cancel")
    seen = []
    sc.scan(g, progress=seen.append)
    check("progress callback fires and ends with the totals", seen and seen[-1]["files"] == 30, seen[-1:] if seen else seen)
    import threading
    ev = threading.Event()
    ev.set()
    res = sc.scan(g, cancel=ev)
    check("a cancelled scan says so", res["cancelled"] and res["files_seen"] == 0)

    print("bad reads")
    bad = tmp / "bad"
    (bad / "T").mkdir(parents=True)
    (bad / "T" / "T_R1.fastq.gz").write_bytes(b"not gzip")
    fq(bad / "T" / "T_R2.fastq.gz")
    (bad / "Z").mkdir()
    (bad / "Z" / "Z_R1.fastq.gz").write_bytes(b"")
    fq(bad / "Z" / "Z_R2.fastq.gz")
    ids = by_id(sc.scan(bad))
    check("a corrupt or empty read file is a blocking error", "reads_unreadable" in codes(ids["T"]) and "reads_unreadable" in codes(ids["Z"]) and ids["T"]["status"] == "blocked")

    print("write path: same code as init-local, sheet passes sheetcheck")
    data, sheet = tmp / "data", tmp / "sheet.tsv"
    res = sc.scan(a)
    out = sc.stage(res["samples"], data, sheet, link="copy")
    check("both ready samples were placed", len(out["staged"]) == 2, out)
    check("the files are where init-local puts them", (data / "KP01" / "KP01_1.fastq.gz").is_file() and (data / "KP01" / "reference.fna").is_file() and (data / "KP01" / "truth.tsv").is_file())
    from plasbench import sheetcheck
    cols = sheetcheck.header(sheet)
    check("the sheet is a sample sheet", sheetcheck.looks_like_sample_sheet(cols) and "sample_id" in cols, cols)
    out2 = sc.stage(sc.scan(b)["samples"], tmp / "data2", tmp / "sheet2.tsv")
    check("samples needing review are not placed without confirmation", not out2["staged"] and all("needs your review" in " ".join(r["messages"]) for r in out2["results"]), out2["results"][:1])
    out3 = sc.stage(sc.scan(b)["samples"], tmp / "data3", tmp / "sheet3.tsv", confirm=True, include={"SRR1234567"})
    check("with confirmation a review sample is placed", len(out3["staged"]) == 1)
    lanes = [s for s in sc.scan(b)["samples"] if s["sample_id"] == "Iso7"]
    out4 = sc.stage(lanes, tmp / "data4", tmp / "sheet4.tsv", confirm=True)
    joined = tmp / "data4" / "Iso7" / "Iso7_1.fastq.gz"
    with gzip.open(joined, "rt") as h:
        check("confirmed lanes are joined as one valid gzip (12 reads)", sum(1 for _ in h) == 48 and len(out4["staged"]) == 1)
    out5 = sc.stage(sc.scan(a)["samples"], data, sheet, selections={"KP01": {"reference": "/etc/passwd"}})
    check("a reference the scan did not list is refused", any("not found by the scan" in " ".join(r["messages"]) for r in out5["results"]))
    out6 = sc.stage(sc.scan(a)["samples"], tmp / "d6", tmp / "s6.tsv", selections={"KP01": {"new_id": "../evil"}}, include={"KP01"})
    check("an unsafe edited id is refused", not out6["staged"] and not (tmp / "evil").exists())

    print("CLI")
    cli = [sys.executable, "-m", "plasbench"]
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    r = subprocess.run(cli + ["--project-root", str(ROOT), "scan-isolates", str(a), "--json"], capture_output=True, text=True, env=env)
    js = json.loads(r.stdout)
    check("scan-isolates --json: exit 0 when every sample is complete, with the documented shape", r.returncode == 0 and {"samples", "unrecognised", "skipped", "warnings"} <= set(js), (r.returncode, r.stderr[-300:]))
    r = subprocess.run(cli + ["--project-root", str(ROOT), "scan-isolates", str(b)], capture_output=True, text=True, env=env)
    check("scan-isolates: exit 3 when some sample needs attention, and a table is printed", r.returncode == 3 and "Iso7" in r.stdout and "confidence" in r.stdout.lower(), (r.returncode, r.stdout[-300:]))
    w = tmp / "cliw"
    r = subprocess.run(cli + ["--project-root", str(ROOT), "scan-isolates", str(a), "--write-sheet", str(w / "l.tsv"), "--data-dir", str(w / "d"), "--yes"], capture_output=True, text=True, env=env)
    check("--write-sheet places the samples and writes the sheet", r.returncode == 0 and (w / "l.tsv").is_file() and (w / "d" / "KP02" / "reference.fna").is_file(), (r.returncode, r.stdout[-300:], r.stderr[-300:]))
    r = subprocess.run(cli + ["--project-root", str(ROOT), "scan-isolates", str(tmp / "nonexistent"), "--json"], capture_output=True, text=True, env=env)
    check("a missing folder is a warning and exit 3, never a traceback", r.returncode == 3 and "Traceback" not in r.stderr, (r.returncode, r.stderr[-200:]))

    print("ALL ISOLATE SCAN TESTS PASSED" if not FAILED else f"FAILED: {FAILED}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
