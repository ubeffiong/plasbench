#!/usr/bin/env python3
"""python/download_progress.py: the progress line the download stage logs, so a long quiet download does not look stalled.

The aria2 control-file layout was read from a real transfer (a 9.5 GB paired run, 18 November 2026): the total length in the control file equalled the
.part file's size, and the percentages moved between two looks. The fixture below writes that layout and the numbers of that transfer.
"""
import os
import struct
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))
import download_progress as dp  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


PIECE = 1 << 20


def control(total, done_pieces, piece=PIECE, info_hash=b""):
    """An aria2 control file with the first `done_pieces` pieces complete (plus an in-flight section, which the reader ignores)."""
    pieces = -(-total // piece)
    bits = bytearray((pieces + 7) // 8)
    for i in done_pieces:
        bits[i >> 3] |= 0x80 >> (i & 7)
    return (struct.pack(">HII", 1, 0, len(info_hash)) + info_hash + struct.pack(">I", piece) + struct.pack(">QQ", total, 0)
            + struct.pack(">I", len(bits)) + bytes(bits) + struct.pack(">I", 0))


with tempfile.TemporaryDirectory() as tmp:
    # --- the real transfer's numbers: mate 1 73.4% of 4,739,735,467 bytes, mate 2 64.7% of 4,738,498,753 -------------------------------------
    t1, t2 = 4739735467, 4738498753
    p1, p2 = -(-t1 // PIECE), -(-t2 // PIECE)
    d1, d2 = int(0.734 * p1), int(0.647 * p2)
    open(os.path.join(tmp, "SRR1_1.fastq.gz.part.aria2"), "wb").write(control(t1, range(d1)))
    open(os.path.join(tmp, "SRR1_2.fastq.gz.part.aria2"), "wb").write(control(t2, range(d2)))
    for name, size in (("SRR1_1.fastq.gz.part", t1), ("SRR1_2.fastq.gz.part", t2)):
        with open(os.path.join(tmp, name), "wb") as handle:     # preallocated at full size, like aria2c: the size must not be read as progress
            handle.truncate(size)
    got1 = dp.aria2_progress(os.path.join(tmp, "SRR1_1.fastq.gz.part.aria2"))
    check("the control file's total length is read", got1 and got1[1] == t1, got1)
    check("done bytes are the completed pieces", got1 and got1[0] == d1 * PIECE, got1)
    line = dp.describe(tmp, "SRR1")
    check("the line shows both mates' percentages and the GB done of total", "mate 1 73.4%" in line and "mate 2 64.7%" in line and "of 9.5 GB" in line, line)
    check("a preallocated .part file is not mistaken for a finished download", "complete" not in line, line)

    # --- the last piece is short ----------------------------------------------------------------------------------------------------------
    last_only = control(10 * PIECE + 100, [10])
    path = os.path.join(tmp, "last.aria2")
    open(path, "wb").write(last_only)
    check("a short last piece counts its real length", dp.aria2_progress(path) == (100, 10 * PIECE + 100), dp.aria2_progress(path))

    # --- no control file: the .part file grows --------------------------------------------------------------------------------------------
    grow = os.path.join(tmp, "grow")
    os.makedirs(grow)
    open(os.path.join(grow, "SRR2_1.fastq.gz.part"), "wb").write(b"x" * 3000)
    open(os.path.join(grow, "SRR2_2.fastq.gz.part"), "wb").write(b"x" * 1000)
    line = dp.describe(grow, "SRR2", total_bytes=10000)
    check("a growing .part file reports bytes so far against the known total", "so far" in line and "of 0.0 GB" in line or "GB" in line, line)
    check("nothing written yet is said plainly", dp.describe(os.path.join(tmp, "empty"), "SRR3") == "SRR3: starting (nothing written yet)")

    # --- finished -------------------------------------------------------------------------------------------------------------------------
    done = os.path.join(tmp, "done")
    os.makedirs(done)
    for mate in ("1", "2"):
        open(os.path.join(done, f"SRR4_{mate}.fastq.gz"), "wb").write(b"y" * 500)
    check("a finished pair is reported complete", "mate 1 complete" in dp.describe(done, "SRR4") and "mate 2 complete" in dp.describe(done, "SRR4"), dp.describe(done, "SRR4"))

    # --- damaged or foreign control files never raise -------------------------------------------------------------------------------------
    junk = os.path.join(tmp, "junk.aria2")
    for blob in (b"", b"\x00" * 5, b"not an aria2 file at all", control(5 * PIECE, [0, 1])[:20]):
        open(junk, "wb").write(blob)
        check(f"a damaged control file ({len(blob)} bytes) returns None, not an exception", dp.aria2_progress(junk) is None, dp.aria2_progress(junk))
    check("a missing control file returns None", dp.aria2_progress(os.path.join(tmp, "nope.aria2")) is None)

    # --- the command line: always exit 0 -------------------------------------------------------------------------------------------------
    cli = subprocess.run([sys.executable, os.path.join(ROOT, "python", "download_progress.py"), "--data-dir", tmp, "--run", "SRR1"], capture_output=True, text=True)
    check("the command prints the line and exits 0", cli.returncode == 0 and "mate 1 73.4%" in cli.stdout, (cli.returncode, cli.stdout, cli.stderr))
    cli = subprocess.run([sys.executable, os.path.join(ROOT, "python", "download_progress.py"), "--data-dir", os.path.join(tmp, "absent"), "--run", "SRR9"], capture_output=True, text=True)
    check("a missing folder still exits 0", cli.returncode == 0, (cli.returncode, cli.stderr))

print("ALL DOWNLOAD PROGRESS TESTS PASSED" if ok else "DOWNLOAD PROGRESS TESTS FAILED")
sys.exit(0 if ok else 1)
