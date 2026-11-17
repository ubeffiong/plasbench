#!/usr/bin/env python3
"""The frozen short-read QC thresholds: every row frozen, the hash in docs/THRESHOLD_FREEZE.md matches the file, the pilot table is committed, and qc_pilot.py works (ENA stubbed)."""

import csv
import gzip
import hashlib
import io
import os
import random
import re
import sys
import tempfile
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
import qc_pilot as qp  # noqa: E402
import short_read_qc as qc  # noqa: E402

TAB, NL = chr(9), chr(10)
ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


rows, policy, sha = qc.read_thresholds(qc.DEFAULT_THRESHOLDS)
check("every threshold row is frozen and the file's policy is frozen", policy == "frozen" and all(r["status"] == "frozen" for r in rows), policy)
doc = open(os.path.join(ROOT, "docs", "THRESHOLD_FREEZE.md"), encoding="utf-8").read()
check("the hash recorded in docs/THRESHOLD_FREEZE.md is the file's hash (a change after freezing is noticed)", f"`{sha}`" in doc, sha)
check("the document says every row of the table and names the rows the pilot does not back", all(r["metric"] in doc for r in rows) and "gc_deviation" in doc and "not backed" in doc.lower())

pilot = list(csv.DictReader(open(os.path.join(ROOT, "docs", "validation", "short_read_qc_pilot.tsv"), encoding="utf-8"), delimiter=TAB))
measured = [r for r in pilot if r["status"] == "measured"]
check("the committed pilot table has 40 measured real runs and records the 20 that could not be fetched, with the reason",
      len(measured) == 40 and len(pilot) == 60 and all(r["note"] for r in pilot if r["status"] != "measured"), (len(measured), len(pilot)))
check("the pilot covers many species (the first rows of the balanced order, one each)", len({r["organism"] for r in measured}) >= 35, len({r["organism"] for r in measured}))
q30_warn = sum(1 for r in measured if float(r["q30_fraction"]) < 0.75)
adapters = sorted(float(r["adapter_fraction"]) for r in measured)
check("the numbers quoted in the thresholds file are the pilot's: 1 of 40 below the Q30 warn limit, 4 above 10% adapters, the largest above 50%",
      q30_warn == 1 and sum(1 for a in adapters if a > 0.10) == 4 and adapters[-1] > 0.5, (q30_warn, adapters[-4:]))

print("qc_pilot.py with the ENA stubbed")
rng = random.Random(3)


def fastq(n, tag):
    out = io.StringIO()
    for i in range(n):
        seq = "".join(rng.choice("ACGT") for _ in range(100))
        out.write(f"@r{i}/{tag}\n{seq}\n+\n{'I' * 100}\n")
    return out.getvalue()


R1, R2 = fastq(3000, 1), fastq(3000, 2)
gz1, gz2 = gzip.compress(R1.encode()), gzip.compress(R2.encode())


class Resp:
    def __init__(self, data): self.data = data
    def read(self): return self.data
    def __enter__(self): return self
    def __exit__(self, *a): return False


def fake_urlopen(request, timeout=0):
    url = request.full_url
    if "filereport" in url:
        return Resp((f"run_accession{TAB}fastq_ftp{TAB}fastq_bytes{TAB}read_count{TAB}base_count{NL}RUN1{TAB}h/RUN1_1.fastq.gz;h/RUN1_2.fastq.gz{TAB}1;1{TAB}3000{TAB}600000{NL}").encode())
    data = gz1 if "RUN1_1" in url else gz2
    end = int(request.headers.get("Range", "bytes=0-%d" % len(data)).split("-")[1]) + 1
    return Resp(data[:end])             # a range request returns a PREFIX: the gzip stream ends early, as it does on the ENA


original = urllib.request.urlopen
urllib.request.urlopen = fake_urlopen
try:
    with tempfile.TemporaryDirectory() as d:
        row = {"sample_id": "s1", "sra_run": "RUN1", "organism": "Escherichia coli"}
        cut = len(gz1) // 2
        got = qp.pilot_one(row, d, 2000, cut)
        check("a prefix of the gzip files gives a measured run with a complete number of pairs (a half-read record is dropped)",
              got["status"] == "measured" and 100 <= int(got["pairs_in_prefix"]) <= 2000, got)
        check("the per-read measures come from short_read_qc.py (quality 40, length 100, no mismatch)", float(got["mean_quality"]) == 40.0 and got["median_read_length"] == "100" and got["pair_mismatch_fraction"] == "0", got)
        check("the temporary FASTQ files are removed", not [f for f in os.listdir(d) if f.endswith(".fastq.gz")], os.listdir(d))
        check("a run with fewer than 1,000 complete pairs in the prefix is skipped, with the reason", qp.pilot_one(row, d, 2000, 4000)["status"] == "skipped")
finally:
    urllib.request.urlopen = original

print("ALL THRESHOLD FREEZE TESTS PASSED" if ok else "THRESHOLD FREEZE TESTS FAILED")
sys.exit(0 if ok else 1)
