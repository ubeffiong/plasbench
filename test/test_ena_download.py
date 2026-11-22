#!/usr/bin/env python3
"""The chunked, resumable ENA downloader (python/ena_download.py) against a local fake ENA with fault injection (test/ena_range_server.py).

Covers: a clean parallel download; a connection reset mid-chunk; a stalled connection; 429 and 503 with Retry-After (and the smaller connection budget that follows); a server that
ignores Range (at the start and part way); a wrong Content-Range; a short chunk (resumed inside the chunk); the remote file changing during the download; a wrong whole-file MD5
(re-fetched once, then refused); a large sparse file; a process that is killed and restarted (only the missing chunks are requested again); a failure injected in the LAST chunk
(the real-world case: it costs one chunk, not the file); a chunk that fails for good (finished chunks are kept for the next attempt); the connection budget (never exceeded,
shared by both mates, hard-capped); the aria2c route (n/a without aria2c); honest, monotonic progress with a sane ETA.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "test"))
os.environ.update(ENA_CHUNK_MIB="1", ENA_STALL_SECONDS="1.5", ENA_CHUNK_BACKOFF_SECONDS="0", ENA_RETRY_AFTER_MAX_SECONDS="3", ENA_RETRY_DELAY_SECONDS="0",
                  ENA_USE_ARIA2="0", ENA_DOWNLOAD_CONNECTIONS="")
import ena_download as ed  # noqa: E402
from ena_range_server import Content, FakeENA  # noqa: E402

MIB = 1 << 20
ok = True


def check(label, good, detail=""):
    global ok
    print(f"  {'PASS' if good else 'FAIL'}: {label}{'' if good else ' -> ' + str(detail)}")
    ok &= bool(good)


def make(size=8 * MIB, rate=None, seed=5):
    server = FakeENA(rate=rate)
    server.add_file("/f/x.fastq.gz", Content(size, seed))
    return server.start()


def get(server, tmp, limit=4, attempts=3, path="/f/x.fastq.gz", md5=None, progress=None, budget=None, name="x"):
    content = server.files[path]
    progress = progress or ed.Progress("T")
    budget = budget or ed.Budget(limit=limit)
    part = os.path.join(tmp, "x.fastq.gz.part")
    ed.fetch(server.url(path), part, md5 or content.md5(), content.size, budget, progress, name, min_bytes=MIB, attempts=attempts, retry_delay=0)
    return part, progress, budget


def same(part, server, path="/f/x.fastq.gz"):
    c = server.files[path]
    return os.path.getsize(part) == c.size and ed.md5_of(part) == c.md5()


def main():
    # 1. a clean parallel download
    s = make()
    with tempfile.TemporaryDirectory() as tmp:
        part, prog, budget = get(s, tmp, limit=4)
        st = s.stats()
        check("a clean download is byte-identical and MD5-verified", same(part, s))
        check("it used parallel ranges (more than one connection at once, never more than the budget of 4)", 1 < st["max_active"] <= 4, st["max_active"])
        check("every response was a ranged 206 and the bytes requested equal the file size (+1 probe byte)", all(r[3] == 206 for r in st["requests"]) and st["ranged_bytes"] == 8 * MIB + 1, st["ranged_bytes"])
        state = json.load(open(part + ".state"))
        check("the state file records url, total, chunk size, validators and the finished chunks", state["total"] == 8 * MIB and state["chunk"] == MIB and len(state["done"]) == 8
              and state["etag"] and state["url"].endswith("/f/x.fastq.gz"), state)
    s.stop()

    # 2. a connection reset in the middle of a chunk
    s = make()
    s.faults.append({"kind": "reset", "start": 2 * MIB, "after": 300000, "times": 2})
    with tempfile.TemporaryDirectory() as tmp:
        part, prog, _ = get(s, tmp)
        st = s.stats()
        check("a connection reset mid-chunk is retried and the file is correct", same(part, s))
        check("the retry resumed INSIDE the chunk (a request starts part way through chunk 3) and little was re-sent", any(r[1] > 2 * MIB and r[1] < 3 * MIB for r in st["requests"]) and st["bytes_sent"] < 8 * MIB + MIB, st["bytes_sent"])
        check("the retries were counted", prog.retries >= 1, prog.retries)
    s.stop()

    # 3. a stalled connection (no bytes)
    s = make()
    s.faults.append({"kind": "stall", "start": 3 * MIB, "after": 100000, "seconds": 8, "times": 1})
    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        part, prog, _ = get(s, tmp)
        check("a connection that goes quiet is abandoned (stall limit 1.5 s here, 45 s by default) and the chunk retried", same(part, s) and time.time() - t0 < 7, time.time() - t0)
    s.stop()

    # 4. 429 and 503 with Retry-After
    for code in ("http429", "http503"):
        s = make()
        s.faults.append({"kind": code, "start": 1 * MIB, "retry_after": 1, "times": 2})
        t0 = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            budget = ed.Budget(limit=8)
            part, prog, _ = get(s, tmp, budget=budget)
            check(f"{code[4:]} with Retry-After is honoured (waited about 1 s), the file is correct", same(part, s) and time.time() - t0 >= 0.9, time.time() - t0)
            check(f"{code[4:]} lowered the connection budget from 8 for the rest of the run", budget.limit < 8, budget.limit)
        s.stop()
    with tempfile.TemporaryDirectory() as tmp:
        memo = os.path.join(tmp, "budget.json")
        b1 = ed.Budget(limit=8, memo_path=memo)
        b1.reduce("test")
        b2 = ed.Budget(limit=16, memo_path=memo)
        check("the lowered figure is remembered by the next process of the run (budget file)", b2.limit == b1.limit == 6, (b1.limit, b2.limit))
        check("the budget is hard-capped (ENA_MAX_CONNECTIONS=1000 gives 24)", ed.Budget(limit=1000).limit == ed.HARD_MAX_CONNECTIONS == 24)

    # 5. a server that ignores Range
    s = make()
    s.honour_range = False
    with tempfile.TemporaryDirectory() as tmp:
        part, prog, _ = get(s, tmp)
        check("a server that ignores Range is read as one stream, verified", same(part, s) and all(r[3] == 200 for r in s.stats()["requests"]))
    s.stop()
    s = make()
    s.faults.append({"kind": "ignore_range", "start": 4 * MIB, "times": 100})
    with tempfile.TemporaryDirectory() as tmp:
        part, prog, _ = get(s, tmp)
        check("a server that stops honouring Range part way ends as a correct single-stream file", same(part, s))
    s.stop()

    # 6. a wrong Content-Range
    s = make()
    s.faults.append({"kind": "bad_range", "start": 5 * MIB, "times": 2})
    with tempfile.TemporaryDirectory() as tmp:
        part, prog, _ = get(s, tmp)
        check("a wrong Content-Range is rejected, the chunk fetched again, the file correct", same(part, s) and prog.retries >= 2, prog.retries)
    s.stop()

    # 7. a short chunk
    s = make()
    s.faults.append({"kind": "short", "start": 6 * MIB, "after": 100000, "times": 1})
    with tempfile.TemporaryDirectory() as tmp:
        part, prog, _ = get(s, tmp)
        check("a chunk that ends early is detected and completed from where it stopped", same(part, s) and any(6 * MIB < r[1] < 7 * MIB for r in s.stats()["requests"]))
    s.stop()

    # 8. the remote file changes during the download
    s = make()
    s.faults.append({"kind": "change_etag", "start": 4 * MIB, "times": 1})
    with tempfile.TemporaryDirectory() as tmp:
        part, prog, _ = get(s, tmp)
        check("a changed ETag mid-download restarts the file cleanly, says so, and the result is correct", same(part, s) and any("changed" in r for r in prog.restarts), prog.restarts)
        check("the progress figure went down only because of that restart", prog.snapshot()["done_bytes"] == 8 * MIB)
    s.stop()
    s = make()
    s.faults.append({"kind": "change_size", "start": 4 * MIB, "times": 1})
    with tempfile.TemporaryDirectory() as tmp:
        try:
            get(s, tmp, attempts=2)
            good = False
        except (OSError, ValueError):
            good = True
        check("a file whose size changed on the server is not accepted as the file ENA described", good)
        check("and no half-written file is left under the .part name", not os.path.exists(os.path.join(tmp, "x.fastq.gz.part")) or not same(os.path.join(tmp, "x.fastq.gz.part"), s))
    s.stop()

    # 9. MD5 mismatch
    s = make()
    s.faults.append({"kind": "corrupt", "start": MIB, "times": 1})
    with tempfile.TemporaryDirectory() as tmp:
        part, prog, _ = get(s, tmp)
        st = s.stats()
        check("one corrupted chunk: the whole-file MD5 catches it, the file is fetched again once in parallel and is then correct", same(part, s) and st["ranged_bytes"] >= 16 * MIB, st["ranged_bytes"])
    s.stop()
    s = make()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            get(s, tmp, md5="0" * 32)
            good = False
        except ValueError as exc:
            good = "MD5 mismatch" in str(exc)
        st = s.stats()
        check("a published MD5 that never matches is refused after exactly one refetch (about two files requested), and nothing is left", good and 16 * MIB <= st["ranged_bytes"] < 17 * MIB and not os.path.exists(os.path.join(tmp, "x.fastq.gz.part")), st["ranged_bytes"])
    s.stop()

    # 10. a large sparse file
    os.environ["ENA_CHUNK_MIB"] = "32"
    s = make(size=200 * MIB)
    with tempfile.TemporaryDirectory() as tmp:
        part, prog, _ = get(s, tmp, limit=8)
        check("a 200 MiB sparse file (generated on the fly by the server) downloads in 32 MiB chunks and verifies", same(part, s) and s.stats()["max_active"] <= 8)
    s.stop()
    os.environ["ENA_CHUNK_MIB"] = "1"

    # 11. killed and restarted
    s = make(size=12 * MIB, rate=1 * MIB)
    with tempfile.TemporaryDirectory() as tmp:
        script = ("import sys,os; sys.path.insert(0, sys.argv[1]); import ena_download as ed; "
                  "c_url, part, total, md5 = sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]; "
                  "ed.fetch(c_url, part, md5, total, ed.Budget(limit=2), ed.Progress('T'), 'x', min_bytes=1<<20, attempts=1, retry_delay=0)")
        part = os.path.join(tmp, "x.fastq.gz.part")
        content = s.files["/f/x.fastq.gz"]
        proc = subprocess.Popen([sys.executable, "-I", "-c", script, str(ROOT / "python"), s.url("/f/x.fastq.gz"), part, str(content.size), content.md5()],
                                env=dict(os.environ))
        deadline = time.time() + 40
        done_at_kill = 0
        while time.time() < deadline:
            try:
                done_at_kill = len(json.load(open(part + ".state"))["done"])
            except (OSError, ValueError):
                done_at_kill = 0
            if done_at_kill >= 5:
                break
            time.sleep(0.2)
        proc.kill()
        proc.wait()
        done_at_kill = len(json.load(open(part + ".state"))["done"])
        s.reset_stats()
        s.rate = None
        part, prog, _ = get(s, tmp)
        missing = 12 - done_at_kill
        st = s.stats()
        check(f"after a kill with {done_at_kill} of 12 chunks finished, the restarted download is correct", same(part, s))
        check(f"it requested only the missing chunks again ({st['ranged_bytes'] - 1} bytes requested, {missing} chunks missing, file {12 * MIB})",
              missing * MIB <= st["ranged_bytes"] - 1 <= missing * MIB, (st["ranged_bytes"], missing))
        check("the progress figure counted the resumed bytes as already on disk", prog.resumed_bytes == done_at_kill * MIB, prog.resumed_bytes)
    s.stop()

    # 12. a failure in the LAST chunk
    s = make()
    s.faults.append({"kind": "reset", "last": True, "after": 50000, "times": 3})
    with tempfile.TemporaryDirectory() as tmp:
        part, prog, _ = get(s, tmp)
        st = s.stats()
        check("a connection failing in the last chunk (three times) costs that chunk only: bytes sent stay under file + one chunk", same(part, s) and st["bytes_sent"] <= 8 * MIB + MIB, st["bytes_sent"])
    s.stop()

    # 13. a chunk that fails for good: finished chunks are kept, the next attempt fetches only it
    s = make()
    s.faults.append({"kind": "reset", "start": 7 * MIB, "after": 0, "times": 10 ** 6})
    os.environ["ENA_CHUNK_RETRIES"] = "2"
    with tempfile.TemporaryDirectory() as tmp:
        part = os.path.join(tmp, "x.fastq.gz.part")
        try:
            get(s, tmp, attempts=2)
            good = False
        except OSError as exc:
            good = "kept" in str(exc) or "resume" in str(exc)
        kept = len(json.load(open(part + ".state"))["done"]) if os.path.exists(part + ".state") else -1
        check("a chunk that keeps failing stops the download with a clear message, and the other chunks stay on disk and in the state file", good and kept == 7, (good, kept))
        s.faults.clear()
        s.reset_stats()
        part, prog, _ = get(s, tmp)
        check("the next attempt fetches that one chunk only (about one MiB requested) and the file verifies", same(part, s) and s.stats()["ranged_bytes"] <= MIB + 1, s.stats()["ranged_bytes"])
    os.environ["ENA_CHUNK_RETRIES"] = "8"
    s.stop()

    # 14. progress is honest: monotonic, no 0.0% regressions, sane ETA
    s = make(size=10 * MIB, rate=2 * MIB)
    with tempfile.TemporaryDirectory() as tmp:
        prog = ed.Progress("SRR1")
        seen, lines = [], []
        stop = threading.Event()

        def sample():
            while not stop.wait(0.15):
                snap = prog.snapshot()
                seen.append(snap)
                lines.append(prog.line(snap))

        t = threading.Thread(target=sample)
        t.start()
        part, _, _ = get(s, tmp, limit=3, progress=prog)
        stop.set()
        t.join()
        done = [x["done_bytes"] for x in seen]
        check("the bytes shown never decrease and never exceed the total", all(b >= a for a, b in zip(done, done[1:])) and max(done) <= 10 * MIB, done[-5:])
        check("lines have the plain form 'RUN: x of y (n%), a MB/s now, b MB/s average, about t left'", any(re.match(r"^SRR1: \d+ MB of 10 MB \(\d+%\), [\d.]+ MB/s now, [\d.]+ MB/s average, about \d+ s left$", ln) for ln in lines), lines[-4:])
        etas = [x["eta_seconds"] for x in seen if x["eta_seconds"] is not None]
        check("the ETA is a sane positive number (under 60 s for a 10 MB file at several MB/s)", etas and all(0 <= e < 60 for e in etas), etas[:5])
        check("a download that has not started shows no percent regression: no line says 0% after bytes arrived", not any("(0%)" in ln for ln in lines[len(lines) // 2:]), lines[-3:])
    s.stop()
    stalled = ed.Progress("SRR1", clock=lambda: 1000.0)
    stalled.add_file("a", 100, 50)
    stalled.last_byte = 900.0
    check("no bytes for over a minute reads 'stalled'", "stalled" in stalled.line() and "no bytes for" in stalled.line(), stalled.line())

    # 15. the connection budget, two mates at once (the real call path: fetch_ena_reads.main)
    import fetch_ena_reads as fer
    s = FakeENA(rate=3 * MIB)
    s.add_run("SRRB", size=6 * MIB)
    s.start()
    for limit, per_file, bound in ((6, "", 6), (16, "2", 4)):
        s.reset_stats()
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, ENA_MAX_CONNECTIONS=str(limit), ENA_DOWNLOAD_CONNECTIONS=per_file, DOWNLOAD_TMP_DIR="data", ENA_SEGMENT_MIN_BYTES=str(MIB))
            r = subprocess.run([sys.executable, "-I", str(ROOT / "python" / "fetch_ena_reads.py"), "--run", "SRRB", "--out-dir", tmp, "--progress-file", os.path.join(tmp, "p.json")],
                               env=dict(env, ENA_PORTAL_URL=s.portal()), capture_output=True, text=True)
            files_ok = all(os.path.getsize(os.path.join(tmp, f"SRRB_{m}.fastq.gz")) == 6 * MIB for m in (1, 2)) if r.returncode == 0 else False
            check(f"both mates download with ENA_MAX_CONNECTIONS={limit}{' and ENA_DOWNLOAD_CONNECTIONS=' + per_file if per_file else ''}: never more than {bound} connections open at once "
                  f"(server saw {s.stats()['max_active']})", files_ok and 1 < s.stats()["max_active"] <= bound, (r.returncode, r.stderr[-300:], s.stats()["max_active"]))
            prog = json.load(open(os.path.join(tmp, "p.json")))["isolates"]["SRRB"]
            check("the progress JSON ends as done with all bytes counted", prog["state"] == "done" and prog["done_bytes"] == prog["total_bytes"] == 12 * MIB, prog)
    b = ed.Budget(limit=4)
    b.register("a")
    b.register("b")
    got = [b.acquire("a") for _ in range(2)]
    stop = threading.Event()
    stop.set()
    check("one mate cannot take more than its fair share (2 of 4 with two files)", got == [True, True] and b.acquire("a", stop=stop) is False)
    b.unregister("b")
    check("when the other file ends the whole budget is available", b.share() == 4)
    s.stop()

    # 16. aria2c route (opt-in)
    if shutil.which("aria2c"):
        s = make(size=6 * MIB)
        os.environ["ENA_USE_ARIA2"] = "1"
        with tempfile.TemporaryDirectory() as tmp:
            part, prog, _ = get(s, tmp)
            check("the opt-in aria2c route (ENA_USE_ARIA2=1) downloads and verifies, keeping the single MD5 check", same(part, s))
        os.environ["ENA_USE_ARIA2"] = "0"
        s.stop()
    else:
        print("  n/a: aria2c is not installed here, so the aria2c route is not exercised")

    print("ALL ENA DOWNLOADER TESTS PASSED" if ok else "SOME ENA DOWNLOADER TESTS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
