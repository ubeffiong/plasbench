#!/usr/bin/env python3
"""Regression for read_pairing.pair_fastq_files and its use by init-local / validate."""
import gzip
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))
from read_pairing import pair_fastq_files  # noqa: E402

INIT = ROOT / "python" / "init_local_sample.py"
VALIDATE = ROOT / "python" / "validate_local_inputs.py"


def check(name, ok, detail=""):
    if not ok:
        print("FAIL: " + name + "\n" + detail, file=sys.stderr)
        raise SystemExit(1)
    print("  " + name + " ? True")


def gz(path, text="@r1\nACGT\n+\nIIII\n"):
    with gzip.open(path, "wt") as handle:
        handle.write(text)


with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    names = ["a_1.fastq.gz", "a_2.fastq.gz", "b_R1.fastq.gz", "b_R2.fastq.gz",
             "c_S1_L001_R1_001.fastq.gz", "c_S1_L001_R2_001.fastq.gz", "e_1.fq.gz", "e_2.fq.gz",
             "lonely_R1.fastq.gz", "mixed_1.fastq.gz", "mixed_2.fq.gz", "notes.txt"]
    for name in names:
        gz(d / name)
    warned = []
    pairs = pair_fastq_files(d, warn=warned.append)
    got = {s: (r1.name, r2.name) for s, r1, r2 in pairs}
    check("_1/_2", got.get("a") == ("a_1.fastq.gz", "a_2.fastq.gz"))
    check("_R1/_R2", got.get("b") == ("b_R1.fastq.gz", "b_R2.fastq.gz"))
    check("_R1_001 with lane keeps lane in sample",
          got.get("c_S1_L001") == ("c_S1_L001_R1_001.fastq.gz", "c_S1_L001_R2_001.fastq.gz"))
    check(".fq.gz", got.get("e") == ("e_1.fq.gz", "e_2.fq.gz"))
    check("unpaired R1 warned and skipped",
          "lonely" not in got and any("lonely_R1" in w for w in warned))
    check("mixed extensions do not pair", "mixed" not in got and len(warned) == 3)
    check("exactly the valid pairs", sorted(got) == ["a", "b", "c_S1_L001", "e"])

# existing convention: validator passes with no pairing problem
with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    sample = d / "data" / "S1"
    sample.mkdir(parents=True)
    gz(sample / "RUN1_1.fastq.gz")
    gz(sample / "RUN1_2.fastq.gz")
    sheet = d / "s.tsv"
    sheet.write_text("sample_id\tassembly_accession\tsra_run\nS1\t\tRUN1\n")
    r = subprocess.run([sys.executable, str(VALIDATE), "--samples", str(sheet), "--data-dir",
                        str(d / "data")], capture_output=True, text=True)
    check("standard names still validate", r.returncode == 0, r.stderr)

# non-standard names: validator names the fix; init-local --reads-dir restages them
with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    src = d / "incoming"
    src.mkdir()
    gz(src / "RUN1_S1_L001_R1_001.fastq.gz")
    gz(src / "RUN1_S1_L001_R2_001.fastq.gz")
    gz(src / "stray_R1.fastq.gz")
    gz(src / "stray_R2.fastq.gz")
    data = d / "data"
    (data / "S1").mkdir(parents=True)
    for f in src.glob("RUN1*"):
        (data / "S1" / f.name).write_bytes(f.read_bytes())
    sheet = d / "s.tsv"
    sheet.write_text("sample_id\tassembly_accession\tsra_run\nS1\t\tRUN1\n")
    r = subprocess.run([sys.executable, str(VALIDATE), "--samples", str(sheet), "--data-dir", str(data)],
                       capture_output=True, text=True)
    check("non-standard pair reported with fix", r.returncode == 2 and "init-local" in r.stderr
          and "RUN1_S1_L001_R1_001" in r.stderr, r.stderr)
    r = subprocess.run([sys.executable, str(INIT), "--sample", "S2", "--reads-dir", str(src),
                        "--prefix", "RUN1_S1_L001", "--data-dir", str(data),
                        "--samples", str(d / "local.tsv")], capture_output=True, text=True)
    check("init-local --reads-dir succeeds", r.returncode == 0, r.stderr + r.stdout)
    check("restaged under standard names", (data / "S2" / "RUN1_S1_L001_1.fastq.gz").is_file()
          and (data / "S2" / "RUN1_S1_L001_2.fastq.gz").is_file())
    r = subprocess.run([sys.executable, str(INIT), "--sample", "S3", "--reads-dir", str(src),
                        "--data-dir", str(data), "--samples", str(d / "local.tsv")],
                       capture_output=True, text=True)
    check("ambiguous --reads-dir refused", r.returncode != 0 and "could not pick" in r.stderr)
print("LOCAL READ PAIRING TEST PASSED")
