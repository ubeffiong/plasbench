#!/usr/bin/env python3
"""The read-depth cap (python/depth_cap.py, READ_DEPTH_CAP_X): only the first N read pairs of a very deep short-read run are fetched.

Against the fake ENA (test/ena_range_server.py) with real gzip FASTQ: the prefix arrives with whole records, both mates hold exactly the target number of pairs, the bytes fetched are a
fraction of the files, the plan and the one-line message are right, the provenance JSON records the method and its limits; below the cap (and with no reference size, a long-read or
unpaired run, or the cap off) the whole files are fetched and MD5-checked as before; a prefix that ends mid-record is extended; a damaged or unpaired result is refused.
"""
import gzip
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "test"))
import depth_cap as dc  # noqa: E402
from ena_range_server import FakeENA  # noqa: E402

ok = True
MIB = 1 << 20
NL = chr(10)


def check(label, good, detail=""):
    global ok
    print(f"  {'PASS' if good else 'FAIL'}: {label}{'' if good else ' -> ' + str(detail)}")
    ok &= bool(good)


def records(path):
    with gzip.open(path, "rb") as handle:
        lines = handle.read().split(b"\n")
    assert lines[-1] == b""
    lines.pop()
    assert len(lines) % 4 == 0
    return [tuple(lines[i:i + 4]) for i in range(0, len(lines), 4)]


def fetch(server, run, tmp, ref_bases=None, extra_env=None, extra_args=()):
    ref = os.path.join(tmp, "reference.fna")
    if ref_bases:
        with open(ref, "w") as handle:
            handle.write(">chr1" + NL + ("ACGT" * (ref_bases // 4)) + NL)
    env = dict(os.environ, ENA_PORTAL_URL=server.portal(), ENA_CHUNK_MIB="1", ENA_SEGMENT_MIN_BYTES=str(MIB), ENA_CHUNK_BACKOFF_SECONDS="0", ENA_RETRY_DELAY_SECONDS="0",
               DOWNLOAD_TMP_DIR="data", ENA_USE_ARIA2="0", ENA_STALL_SECONDS="5", **(extra_env or {}))
    out = os.path.join(tmp, "data")
    cmd = [sys.executable, "-I", str(ROOT / "python" / "fetch_ena_reads.py"), "--run", run, "--out-dir", out, *extra_args]
    if ref_bases:
        cmd += ["--reference", ref]
    return subprocess.run(cmd, env=env, capture_output=True, text=True), out


def main():
    # pure functions
    check("READ_DEPTH_CAP_X: empty = 150, off/0 = whole files, a number is itself", dc.parse_cap("") == 150 and dc.parse_cap("off") == 0 and dc.parse_cap("0") == 0 and dc.parse_cap("80") == 80)
    rep = {"library_layout": "PAIRED", "read_count": "5000000", "base_count": "3000000000", "instrument_platform": "ILLUMINA"}
    p = dc.plan(150, 8_800_000, rep, [4_740_000_000, 4_740_000_000])
    check("a 340x run with a 150x cap: target pairs = ceil(150 x reference / bases per pair)", p["capped"] and p["target_pairs"] == -(-150 * 8_800_000 // 600), p)
    check("the estimated depth after the cap is about the cap", abs(p["est_depth"] - 150) < 0.01, p.get("est_depth"))
    line = dc.describe("SRR36114699", p)
    check("deep run: the plain one-line message", line.startswith("SRR36114699: 9.5 GB available, 150x cap needs about ") and "fetching the first 2.2 M pairs (the full set stays on ENA)" in line, line)
    check("the capped download is a small fraction of the 9.5 GB", p["fetch_bytes"] < 0.5 * p["full_bytes"], p["fetch_bytes"])
    none = dc.plan(150, 0, rep, [1, 1])
    check("no reference size: whole files, and it says why", not none["capped"] and "reference size" in none["reason"])
    check("single-end, long-read and cap-off runs are never capped", not dc.plan(150, 8_800_000, dict(rep, library_layout="SINGLE"), [1, 1])["capped"]
          and not dc.plan(150, 8_800_000, dict(rep, instrument_platform="OXFORD_NANOPORE"), [1, 1])["capped"] and not dc.plan(0, 8_800_000, rep, [1, 1])["capped"]
          and not dc.plan(150, 8_800_000, dict(rep, read_count="200000", base_count="1900000000"), [1, 1])["capped"])
    check("a run within the cap is fetched whole", not dc.plan(150, 8_800_000, dict(rep, base_count="500000000"), [1, 1])["capped"])

    # an end-to-end capped download
    s = FakeENA()
    s.add_fastq_run("SRRC", pairs=80000, read_len=100)
    s.start()
    full = sum(s.files[p].size for p in ("/f/SRRC_1.fastq.gz", "/f/SRRC_2.fastq.gz"))
    with tempfile.TemporaryDirectory() as tmp:
        # reference of 10 kb; 80000 pairs x 200 bases = 16 Mb = 1600x; cap 100 -> 5000 pairs
        r, out = fetch(s, "SRRC", tmp, ref_bases=10000, extra_env={"READ_DEPTH_CAP_X": "100"})
        check("capped fetch succeeds", r.returncode == 0, r.stderr[-600:])
        a, b = records(os.path.join(out, "SRRC_1.fastq.gz")), records(os.path.join(out, "SRRC_2.fastq.gz"))
        check("both mates hold exactly the 5000 target pairs", len(a) == len(b) == 5000, (len(a), len(b)))
        check("the reads are the FIRST 5000 of the file, whole records, names pair up", a[0][0] == b"@SRRC.1/1" and a[-1][0] == b"@SRRC.5000/1" and b[-1][0] == b"@SRRC.5000/2"
              and all(len(x[1]) == len(x[3]) == 100 and x[2] == b"+" for x in a))
        st = s.stats()
        check(f"only a fraction of the data was requested ({st['ranged_bytes']} of {full} bytes)", st["ranged_bytes"] < 0.5 * full, st["ranged_bytes"])
        prov = json.load(open(os.path.join(out, "SRRC.ena_provenance.json")))
        cap = prov["read_depth_cap"]
        check("provenance: cap, target pairs, bytes fetched, urls, method, the whole-file MD5 caveat, reference size, depths", cap["applied"] and cap["cap_x"] == 100 and cap["target_pairs"] == 5000
              and cap["bytes_fetched"] < full and len(cap["source_urls"]) == 2 and "whole-file md5 not checked" in cap["integrity"] and cap["reference_bases"] == 10000
              and 99 <= cap["estimated_depth"] <= 101 and 1599 <= cap["depth_available"] <= 1601 and "not a random sample" in cap["method"] and "scoring" in cap["scoring_note"], cap)
        left = [f for f in os.listdir(out) if f.endswith(".part") or ".prefix" in f or ".cap" in f]
        check("no .part, .prefix or .cap files are left in the data folder", not left, left)
        plan_r = subprocess.run([sys.executable, "-I", str(ROOT / "python" / "fetch_ena_reads.py"), "--run", "SRRC", "--plan", "--reference", os.path.join(tmp, "reference.fna"), "--depth-cap", "100"],
                                env=dict(os.environ, ENA_PORTAL_URL=s.portal()), capture_output=True, text=True)
        f = plan_r.stdout.strip().split(chr(9))
        check("--plan prints capped bytes, full bytes, 1 and the plain line (the size gate and the estimate use it)", len(f) == 4 and int(f[0]) < int(f[1]) == full and f[2] == "1" and "100x cap needs about" in f[3],
              plan_r.stdout + plan_r.stderr)

    # the prefix ends before enough reads: it is extended
    with tempfile.TemporaryDirectory() as tmp:
        s.reset_stats()
        r, out = fetch(s, "SRRC", tmp, ref_bases=10000, extra_env={"READ_DEPTH_CAP_X": "100", "PLASBENCH_CAP_SAFETY": "0.4", "PLASBENCH_CAP_MARGIN": "0"})
        a = records(os.path.join(out, "SRRC_1.fastq.gz")) if r.returncode == 0 else []
        check("a prefix that ends mid-record or too early is extended until the target is reached", r.returncode == 0 and len(a) == 5000 and "fetching a longer prefix" in r.stderr, r.stderr[-500:])

    # whole files: below the cap, no reference, cap off
    for label, ref, env, expect in (("below the cap", 1_000_000, {"READ_DEPTH_CAP_X": "100"}, "within the"), ("no reference size", None, {"READ_DEPTH_CAP_X": "100"}, "reference size"),
                                    ("the cap off", 10000, {"READ_DEPTH_CAP_X": "off"}, "off")):
        with tempfile.TemporaryDirectory() as tmp:
            s.reset_stats()
            r, out = fetch(s, "SRRC", tmp, ref_bases=ref, extra_env=env)
            prov = json.load(open(os.path.join(out, "SRRC.ena_provenance.json"))) if r.returncode == 0 else {"read_depth_cap": {"applied": True, "reason": ""}}
            whole = r.returncode == 0 and len(records(os.path.join(out, "SRRC_1.fastq.gz"))) == 80000
            check(f"{label}: whole files, MD5-verified as before, provenance says not capped ({expect})", whole and not prov["read_depth_cap"]["applied"]
                  and expect in prov["read_depth_cap"]["reason"] and "verified (md5" in r.stderr, (r.stderr[-300:], prov.get("read_depth_cap")))
    s.stop()
    s = FakeENA()
    s.add_fastq_run("SRRL", pairs=3000, read_len=100, platform="OXFORD_NANOPORE")
    s.start()
    with tempfile.TemporaryDirectory() as tmp:
        r, out = fetch(s, "SRRL", tmp, ref_bases=1000, extra_env={"READ_DEPTH_CAP_X": "10"})
        check("a long-read run is left whole whatever the cap", r.returncode == 0 and len(records(os.path.join(out, "SRRL_1.fastq.gz"))) == 3000, r.stderr[-300:])
    s.stop()

    # cutting and checking
    s = FakeENA()
    s.add_fastq_run("SRRD", pairs=1000)
    data = s.files["/f/SRRD_1.fastq.gz"].data
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = os.path.join(tmp, "p.gz"), os.path.join(tmp, "c.gz")
        Path(src).write_bytes(data[:len(data) // 3])           # a prefix that stops inside a record
        try:
            dc.cut_prefix(src, dst, 1000)
            good = False
        except dc.NeedMore as exc:
            good = 0 < exc.records < 1000
        check("a truncated prefix reports how many complete records it holds", good)
        info = dc.cut_prefix(src, dst, 100)
        check("a cut inside a truncated prefix keeps only complete records", info["records"] == 100 and len(records(dst)) == 100)
        again = os.path.join(tmp, "c2.gz")
        dc.cut_prefix(src, again, 100)
        check("the recompressed output is deterministic (no timestamp or name, like gzip -n)", Path(dst).read_bytes() == Path(again).read_bytes())
        bad = os.path.join(tmp, "bad.gz")
        raw = gzip.decompress(data).split(b"\n")
        raw[5] = raw[5][:-1]                                     # a sequence one base shorter than its quality
        Path(bad).write_bytes(gzip.compress(b"\n".join(raw)))
        try:
            dc.cut_prefix(bad, dst, 10)
            good = False
        except ValueError as exc:
            good = "valid FASTQ" in str(exc)
        check("a record whose sequence and quality differ in length is refused", good)
        broken = os.path.join(tmp, "broken.gz")
        Path(broken).write_bytes(data[:200] + bytes(b ^ 0xFF for b in data[200:2000]))
        try:
            dc.cut_prefix(broken, dst, 10)
            good = False
        except (ValueError, dc.NeedMore):
            good = True
        check("a damaged deflate stream is refused", good)
    a = {"records": 5, "first_name": "R.1", "last_name": "R.5"}
    try:
        dc.check_pair(a, dict(a, last_name="R.6"), 5)
        good = False
    except ValueError as exc:
        good = "do not pair" in str(exc)
    try:
        dc.check_pair(a, dict(a, records=4), 5)
        good = False
    except ValueError as exc:
        good = good and "expected 5" in str(exc)
    check("mates with different counts or names that do not pair are refused", good)
    print("ALL DEPTH CAP TESTS PASSED" if ok else "SOME DEPTH CAP TESTS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
