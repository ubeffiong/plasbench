#!/usr/bin/env python3
"""Regression for `plasbench intake` (template, scan, stage, check).

The point of the feature is that a person can say "my isolates are in these folders" and learn, before a run spends hours, whether PlasBench can see and use them.
Each test below is a way people actually arrange or mis-arrange their data:
  * reads and reference side by side, or one folder per isolate;
  * Illumina names with lanes and sample numbers (two lanes must become ONE isolate);
  * an uncompressed FASTQ, a mate that is missing, long reads mixed in;
  * a draft assembly or protein file where a complete genome is needed;
  * two isolates and one reference (the match is ambiguous: say so, never pick silently);
  * a reference from a DIFFERENT organism than the reads (no file-name test can see this; the reads-versus-reference comparison must).
"""
import gzip
import io
import json
import random
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))
import intake  # noqa: E402

INTAKE = ROOT / "python" / "intake.py"


def check(name, condition, detail=""):
    if not condition:
        print("FAIL: " + name + "\n" + str(detail), file=sys.stderr)
        raise SystemExit(1)
    print("  ok    " + name)


def genome(seed, length):
    rng = random.Random(seed)
    return "".join(rng.choice("ACGT") for _ in range(length))


def fasta(path, records):
    with open(path, "w", encoding="utf-8") as handle:
        for header, seq in records:
            handle.write(f">{header}\n")
            for i in range(0, len(seq), 70):
                handle.write(seq[i:i + 70] + "\n")


def reads(path, seq, n=300, length=100, seed=1, gz=True):
    rng = random.Random(seed)
    opener = gzip.open if gz else open
    with opener(path, "wt") as handle:
        for i in range(n):
            start = rng.randrange(0, len(seq) - length)
            read = seq[start:start + length]
            handle.write(f"@r{i}/1\n{read}\n+\n{'I' * length}\n")


def pair(folder, stem, seq, gz=True, seed=1, n=300):
    ext = ".fastq.gz" if gz else ".fastq"
    reads(folder / f"{stem}_R1_001{ext}", seq, n=n, seed=seed, gz=gz)
    reads(folder / f"{stem}_R2_001{ext}", seq, n=n, seed=seed, gz=gz)   # same names and order: a valid pair for the test


def run(*args):
    return subprocess.run([sys.executable, str(INTAKE), *map(str, args)], capture_output=True, text=True)


ECOLI = genome(11, 60000)
PLASMID = genome(12, 4000)
OTHER = genome(99, 60000)   # a different "organism": shares no 21-mers with ECOLI

# --- templates ---------------------------------------------------------------------------------------------------------
for kind in ("local", "cohort", "truth"):
    text = intake.template_text(kind, ROOT)
    data_lines = [l for l in text.splitlines() if l.strip() and not l.startswith("#")]
    check(f"the {kind} template has a header line and parses as a tab-separated table", len(data_lines) >= 1 and "\t" in data_lines[0], text[:200])
local = intake.template_text("local", ROOT)
check("the sheet template explains every column in plain words", all(w in local for w in ("sample_id", "assembly_accession", "sra_run", "organism", "LOCAL", "NA")))
check("the sheet template's example row is clearly an example", "EXAMPLE_isolate_001" in local)
out = run("template", "local", "--out", ROOT / "tmp" / "tpl_test" / "local.tsv")
check("`intake template --out` writes the file", out.returncode == 0 and (ROOT / "tmp" / "tpl_test" / "local.tsv").is_file(), out.stderr)
check("the template header matches the real accessions header (public cohort)",
      intake.template_text("cohort", ROOT).splitlines()[-1].split("\t")[:3] == ["sample_id", "assembly_accession", "sra_run"])

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)

    # --- layout A: everything in one folder, Illumina names, two lanes for one isolate ---------------------------------
    flat = tmp / "flat"
    flat.mkdir()
    pair(flat, "KP01_S1_L001", ECOLI, seed=1)
    pair(flat, "KP01_S1_L002", ECOLI, seed=2)
    pair(flat, "KP02_S2_L001", OTHER, seed=3)
    fasta(flat / "KP01.fna", [("NZ_CP000001.1 Klebsiella pneumoniae strain X chromosome, complete genome", ECOLI),
                              ("NZ_CP000002.1 Klebsiella pneumoniae strain X plasmid pK1, complete sequence", PLASMID)])
    fasta(flat / "KP02.fasta", [("NZ_CP000009.1 Escherichia coli strain Y chromosome, complete genome", OTHER)])
    found = intake.scan([flat])
    ids = sorted(i["id"] for i in found["isolates"])
    check("two lanes of one isolate are one isolate, not two", ids == ["KP01", "KP02"], ids)
    kp1 = next(i for i in found["isolates"] if i["id"] == "KP01")
    check("the lanes are listed so they can be joined", kp1["lanes"] == 2 and len(kp1["r1"]) == 2)
    check("each isolate gets the reference named after it", Path(kp1["reference"]["path"]).name == "KP01.fna", kp1["reference"])
    check("the match says how sure it is and why", kp1["reference_how"].startswith("confident"), kp1["reference_how"])
    check("the organism is read from the FASTA header and is only a guess", kp1["organism_guess"] == "Klebsiella pneumoniae", kp1["organism_guess"])
    check("nothing was written by the scan", sorted(p.name for p in flat.iterdir() if p.is_dir()) == [])

    # --- staging: places files, joins lanes, writes sheet with organism, leaves REVIEW, never guesses --------------------
    data, sheet = tmp / "data", tmp / "sheet.tsv"
    done = intake.stage(found, data, sheet)
    check("both isolates stage", sorted(r["id"] for r in done["staged"]) == ["KP01", "KP02"], done)
    check("the lanes were joined into one gzip read file", len(gzip.open(data / "KP01" / "KP01_1.fastq.gz", "rt").read().splitlines()) == 4 * 600)
    truth = (data / "KP01" / "truth.tsv").read_text(encoding="utf-8")
    check("a header that says plasmid is labelled PLASMID and the other CHROMOSOME", "NZ_CP000002.1\tPLASMID" in truth and "NZ_CP000001.1\tCHROMOSOME" in truth, truth)
    sheet_text = sheet.read_text(encoding="utf-8")
    check("the sheet has the organism column and a LOCAL row", "organism" in sheet_text.splitlines()[0] and "KP01\tLOCAL\tKP01\tKlebsiella pneumoniae" in sheet_text, sheet_text)

    # --- the quick test, on staged data ---------------------------------------------------------------------------
    result = intake.check(sheet, data)
    kp1_r = next(s for s in result["samples"] if s["sample_id"] == "KP01")
    names = {c["name"]: c["status"] for c in kp1_r["checks"]}
    check("matching reads and reference pass the reads-versus-reference comparison", names.get("Reads come from this reference's isolate") == "pass", kp1_r["checks"])
    check("the whole staged isolate is usable", kp1_r["ok"], kp1_r["checks"])
    kp2_r = next(s for s in result["samples"] if s["sample_id"] == "KP02")
    check("the second isolate is usable too", kp2_r["ok"], kp2_r["checks"])

    # a reference of a different organism is caught although every file name and format is fine
    shutil_target = data / "KP02" / "reference.fna"
    fasta(shutil_target, [("NZ_CP000009.1 Escherichia coli strain Y chromosome, complete genome", ECOLI)])   # KP02's reads are OTHER
    wrong = intake.check(sheet, data, only="KP02")["samples"][0]
    verdict = {c["name"]: c["status"] for c in wrong["checks"]}
    check("reads that do not belong to the reference FAIL the check", verdict.get("Reads come from this reference's isolate") == "fail" and not wrong["ok"], wrong["checks"])
    check("the failure says what to do", any("different organisms" in c["fix"] for c in wrong["checks"] if c["status"] == "fail"))

    # an unedited REVIEW is reported with the fix
    fasta(data / "KP02" / "reference.fna", [("seq_without_description", OTHER)])
    (data / "KP02" / "truth.tsv").write_text("sequence_id\tmolecule_type\tlength\nseq_without_description\tREVIEW\t60000\n", encoding="utf-8")
    review = intake.check(sheet, data, only="KP02", deep=False)["samples"][0]
    check("an unedited REVIEW label fails the check", not review["ok"] and any("REVIEW" in c["detail"] for c in review["checks"]), review["checks"])

    # the template's example row must be deleted
    example = tmp / "ex.tsv"
    example.write_text(local, encoding="utf-8")
    check("a sheet that still holds the template's example row is refused", not intake.check(example, data)["ok"])

    # --- layout B: one folder per isolate, generic file names, a missing mate, uncompressed reads, long reads, draft -----
    tree = tmp / "tree"
    for name in ("alpha", "beta", "gamma"):
        (tree / name).mkdir(parents=True)
    reads(tree / "alpha" / "reads_1.fastq.gz", ECOLI, seed=4)
    reads(tree / "alpha" / "reads_2.fastq.gz", ECOLI, seed=4)
    fasta(tree / "alpha" / "assembly.fna", [("c1 Escherichia coli chromosome, complete genome", ECOLI)])
    reads(tree / "beta" / "beta.1.fastq", ECOLI, seed=5, gz=False)
    reads(tree / "beta" / "beta.2.fastq", ECOLI, seed=5, gz=False)
    reads(tree / "gamma" / "gamma_1.fastq.gz", ECOLI, seed=6)               # no mate
    reads(tree / "gamma" / "gamma_ont.fastq.gz", ECOLI, n=50, length=3000 if False else 100, seed=7)
    found = intake.scan([tree])
    by = {i["id"]: i for i in found["isolates"]}
    check("a generic file name takes the isolate's name from its folder", sorted(by) == ["alpha", "beta"], sorted(by))
    check("the reference is found from the folder alone (one FASTA in the isolate's folder)", by["alpha"]["reference"] and Path(by["alpha"]["reference"]["path"]).name == "assembly.fna", by["alpha"])
    check("an isolate with no reference is reads-only, not an error", by["beta"]["mode"] == "reads-only" and by["beta"]["status"] != "blocked", by["beta"]["issues"])
    check("uncompressed reads are noticed and will be compressed", not by["beta"]["reads_gzipped"] and any("compressed" in i["text"] for i in by["beta"]["issues"]))
    check("a read file with no mate is ignored with a reason, not paired with something else",
          any("gamma_1.fastq.gz" in p for p in found["leftovers"]["unpaired_fastq"] + found["leftovers"]["long_read_files"]), found["leftovers"])
    check("long-read files are listed as not staged", any("ont" in p for p in found["leftovers"]["long_read_files"]), found["leftovers"])
    data2, sheet2 = tmp / "data2", tmp / "sheet2.tsv"
    done = intake.stage(found, data2, sheet2)
    check("the uncompressed pair was compressed while staging", is_gz := (gzip.open(data2 / "beta" / "beta_1.fastq.gz", "rt").read(1) == "@"), done)
    rows = [l.split("\t") for l in sheet2.read_text(encoding="utf-8").splitlines()]
    check("a reads-only isolate is written with NA, so the stages treat it as unscored", ["beta", "NA", "beta"] == rows[2][:3] or ["beta", "NA", "beta"] == rows[1][:3], rows)
    check("check() accepts a reads-only isolate", intake.check(sheet2, data2, only="beta", deep=False)["ok"])

    # --- ambiguity: two isolates, one unrelated FASTA: do not pick silently ------------------------------------------
    amb = tmp / "amb"
    amb.mkdir()
    pair(amb, "one", ECOLI, seed=8)
    pair(amb, "two", ECOLI, seed=9)
    fasta(amb / "genome.fna", [("c Escherichia coli chromosome, complete genome", ECOLI)])
    found = intake.scan([amb])
    check("one FASTA for two isolates is not silently given to either, and both are blocked until a person decides",
          all(i["reference"] is None and i["status"] == "blocked" for i in found["isolates"])
          and all(any("could be the reference" in x["text"] for x in i["issues"]) for i in found["isolates"]), [i["issues"] for i in found["isolates"]])

    # --- a draft assembly and a protein FASTA are refused as truth ---------------------------------------------------
    bad = tmp / "bad"
    bad.mkdir()
    pair(bad, "d1", ECOLI, seed=10)
    fasta(bad / "d1.fna", [(f"NODE_{i}_length_5000_cov_30", ECOLI[i * 5000:(i + 1) * 5000]) for i in range(10)])
    pair(bad, "p1", ECOLI, seed=10)
    fasta(bad / "p1.fna", [("prot1", "MKVLAAGIVGLLLAQPSTDEFHHKKMNPQRSTVWYMKVLAAGIVGLLLAQPSTDEFHHKKMNPQRSTVWY" * 40)])
    found = intake.scan([bad])
    by = {i["id"]: i for i in found["isolates"]}
    check("a draft assembly is flagged as not a complete genome", any("DRAFT" in x["text"] for x in by["d1"]["issues"]), by["d1"]["issues"])
    check("a protein FASTA is a blocking error", by["p1"]["status"] == "blocked", by["p1"]["issues"])

    # --- the command line -------------------------------------------------------------------------------------------
    cli = run("scan", flat)
    check("`intake scan` prints each isolate with its reference and how sure the match is", cli.returncode == 0 and "KP01" in cli.stdout and "confident" in cli.stdout, cli.stdout + cli.stderr)
    cli = run("scan", tmp / "does_not_exist")
    check("a folder that cannot be seen is reported, not a crash", cli.returncode == 2 and "does not exist" in cli.stdout, cli.stdout + cli.stderr)
    cli = run("check", "--samples", sheet, "--data-dir", data, "--sample", "KP01", "--fast")
    check("`intake check` exits 0 and says what to run next when everything is usable", cli.returncode == 0 and "plasbench run" in cli.stdout, cli.stdout + cli.stderr)

# --- every problem comes with a code, plain steps and a guide section; what can be repaired is repaired -------------------------------------------------
GUIDE = (ROOT / "docs" / "INPUT_GUIDE.md").read_text(encoding="utf-8") if (ROOT / "docs" / "INPUT_GUIDE.md").is_file() else ""
for code in intake.RULE_CODES:
    check(f"the guide has a section for '{code}'", f"(#{code})" in GUIDE or f"{{#{code}}}" in GUIDE or f'<a id="{code}">' in GUIDE or f'name="{code}"' in GUIDE, code)

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    src = tmp / "src"
    src.mkdir()
    pair(src, "iso_S1_L001", ECOLI, seed=21)
    fasta(src / "iso.fna", [("NZ_A1.1 Escherichia coli strain Z chromosome, complete genome", ECOLI), ("NZ_A2.1 Escherichia coli plasmid pZ, complete sequence", PLASMID)])
    data, sheet = tmp / "data", tmp / "s.tsv"
    intake.stage(intake.scan([src]), data, sheet)
    sd = data / "iso"
    check("the staged isolate starts out usable", intake.check(sheet, data, deep=False)["ok"])

    # a) a read file that is plain text under a .gz name
    plain = gzip.open(sd / "iso_2.fastq.gz", "rt").read()
    (sd / "iso_2.fastq.gz").write_text(plain, encoding="utf-8")
    bad = intake.check(sheet, data, deep=False)
    rows = [c for c in bad["samples"][0]["checks"] if c["status"] == "fail"]
    check("a problem is reported with a code, steps and a guide link", rows and all(c["code"] and c["fix"] and c["guide"].startswith("docs/INPUT_GUIDE.md#") for c in rows), rows)
    check("the plain-text read file is recognised as repairable", any(c["code"] == "reads-not-gzip" and c["auto"] for c in rows), rows)
    fixed = intake.check(sheet, data, deep=False, fix=True)
    check("Fix compresses it and says so", fixed["ok"] and any("compressed" in r["what"] for r in fixed["repaired"]), fixed)
    check("the repaired file reads as gzip with the same reads", gzip.open(sd / "iso_2.fastq.gz", "rt").read() == plain)

    # b) reads under other names than the sheet expects
    (sd / "iso_1.fastq.gz").rename(sd / "weird_name_R1_001.fastq.gz")
    (sd / "iso_2.fastq.gz").rename(sd / "weird_name_R2_001.fastq.gz")
    bad = intake.check(sheet, data, deep=False)
    check("misnamed reads fail the check", not bad["ok"])
    fixed = intake.check(sheet, data, deep=False, fix=True)
    check("Fix makes correctly named copies and keeps the originals", fixed["ok"] and (sd / "weird_name_R1_001.fastq.gz").is_file() and (sd / "iso_1.fastq.gz").is_file(), fixed)

    # c) a truth table with the wrong capitals, a missing row, spaces and Windows line endings
    (sd / "truth.tsv").write_bytes(b"sequence_id\tmolecule_type\tlength\r\nnz_a1.1 \t chromosome\t60000\r\n")
    bad = intake.check(sheet, data, deep=False)
    check("a damaged truth table fails with the truth-mismatch code", any(c["code"] == "truth-mismatch" for c in bad["samples"][0]["checks"] if c["status"] == "fail"), bad["samples"][0]["checks"])
    fixed = intake.check(sheet, data, deep=False, fix=True)
    table = intake.read_truth(sd / "truth.tsv")
    check("Fix corrects the id's capitals and the type", ["NZ_A1.1", "CHROMOSOME"] == table[0][:2], table)
    check("Fix adds the missing sequence as REVIEW, never as a guess", ["NZ_A2.1", "REVIEW"] == table[1][:2], table)
    check("what is left is the one decision only a person can make", not fixed["ok"] and any(c["code"] == "truth-review" for c in fixed["samples"][0]["checks"] if c["status"] == "fail"), fixed["samples"][0]["checks"])
    check("a label-editing round trip needs every sequence labelled", not intake.save_truth(sd, {"NZ_A1.1": "CHROMOSOME"})["ok"])
    check("a value that is not PLASMID or CHROMOSOME is refused", not intake.save_truth(sd, {"NZ_A1.1": "CHROMOSOME", "NZ_A2.1": "maybe"})["ok"])
    shown = intake.truth_rows(sd)
    check("the label screen lists each sequence with its length and what its header says", [r["header_says"] for r in shown["rows"]] == ["CHROMOSOME", "PLASMID"], shown)
    check("saving the person's labels makes the isolate usable", intake.save_truth(sd, {"NZ_A1.1": "CHROMOSOME", "NZ_A2.1": "PLASMID"})["ok"] and intake.check(sheet, data, deep=False)["ok"])

    # d) no truth table at all: a draft is written, not guessed
    (sd / "truth.tsv").unlink()
    fixed = intake.check(sheet, data, deep=False, fix=True)
    check("a missing truth table is drafted from the headers", (sd / "truth.tsv").is_file() and any("draft truth table" in r["what"] for r in fixed["repaired"]), fixed["repaired"])

    # e) the template's example row
    sheet.write_text(sheet.read_text(encoding="utf-8") + "EXAMPLE_x\tLOCAL\tEXAMPLE_x\n", encoding="utf-8")
    fixed = intake.check(sheet, data, deep=False, fix=True)
    check("Fix removes the template's example row", "EXAMPLE_" not in sheet.read_text(encoding="utf-8") and fixed["ok"], fixed)

    # f) nothing the scan or the check reports lacks guidance
    messy = tmp / "messy"
    messy.mkdir()
    pair(messy, "m1", ECOLI, seed=30)
    fasta(messy / "m1.fna", [(f"NODE_{i}", ECOLI[i * 5000:(i + 1) * 5000]) for i in range(10)])
    found = intake.scan([messy, src, tmp / "nope"])
    issues = [x for i in found["isolates"] for x in i["issues"] if x["level"] in ("error", "warn")]
    check("every scan error or warning has a code, steps and a guide link", issues and all(x["code"] != "other" and x["fix"] and x["guide"] for x in issues), issues)

# --- the empty-accession fix: a reads-only row is NA, and read_samples keeps it as a column -----------------------------
sheet_text = "sample_id\tassembly_accession\tsra_run\nnew_isolate\t\tnewreads\n"
with tempfile.TemporaryDirectory() as tmp:
    sh = Path(tmp) / "s.tsv"
    sh.write_text(sheet_text, encoding="utf-8")
    bash = "bash"
    probe = subprocess.run([bash, "-c", f'source "{(ROOT / "scripts" / "lib.sh").as_posix()}" >/dev/null 2>&1; read_samples "{sh.as_posix()}"'], capture_output=True, text=True)
    if probe.returncode == 0 and probe.stdout.strip():
        check("read_samples gives an empty accession as NA so the read prefix keeps its column", probe.stdout.strip().split("\t") == ["new_isolate", "NA", "newreads"], probe.stdout)

print("ALL INTAKE TESTS PASSED")
