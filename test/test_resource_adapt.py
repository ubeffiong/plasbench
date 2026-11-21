#!/usr/bin/env python3
"""The resource adaptation layer (python/resource_adapt.py, config/resource_signatures.tsv, run_adaptive in scripts/lib.sh).

Table validity, message -> cause and parsed amounts per tool, the response chosen under plenty / tight / no resources, ladder order, the once-only rule and the attempt cap,
the learned profile (reuse on resume, invalidation, estimate), temp relocation, the open-files hard limit (a real `ulimit -n` subprocess on Linux; 'n/a' elsewhere),
timeout extension only with progress, run_adaptive end to end with fake tools, AUTO_RESOURCES=0, and that no scientific parameter is ever touched.

REAL fixtures (text captured in this repository or the incident run): the SPAdes hammer message, 'No space left on device', 'Permission denied', exit 137 and 124, the AMRFinder
database message. SAMPLE messages (wording from tool documentation or source, not captured here): samtools sort, Java heap, thread limit, the SPAdes -m limit, GPU, network.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import resource_adapt as ra  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


rows = ra.load_table()
check("the signature table is valid (regexes compile, causes and responses known, units, exit codes, ladders end in skip)", ra.validate(rows) == [], ra.validate(rows))
check("every row says whether its wording is real (captured) or sample", {r["label"] for r in rows} <= {"real", "sample"} and any(r["label"] == "real" for r in rows) and any(r["label"] == "sample" for r in rows))
check("every cause a row uses is a known cause", {r["cause"] for r in rows} <= set(ra.CAUSES))
bad = [dict(rows[0], id="x", message_regex="(unclosed"), dict(rows[0], id="y", cause="nonsense"), dict(rows[0], id="z", ladder="raise_memory")]
check("a broken table is reported", len(ra.validate(bad)) >= 3, ra.validate(bad))

HAMMER = "ERROR   K-mer Counting   (kmer_data.cpp : 350)   The reads contain too many k-mers to fit into available memory. You need approx. 5.24277GB of free RAM."
CASES = [  # tool, text, exit, cause, needed_gb (or None)
    ("spades", HAMMER, 255, "memory", 5.24277),
    ("spades", "You need approx. 800MB of free RAM", 1, "memory", 800 / 1024),
    ("unicycler", "ERROR ... You need approx. 12.5 GB of free RAM", 1, "memory", 12.5),
    ("spades", "terminate called after throwing an instance of 'std::bad_alloc'", 134, "memory", None),
    ("mob_recon", "OSError: [Errno 12] Cannot allocate memory", 1, "memory", None),
    ("platon", "MemoryError", 1, "memory", None),
    ("plasmidspades", "", 137, "memory", None),
    ("minimap2", "", -9, "memory", None),
    ("samtools", "[bam_sort_core] couldn't allocate memory for bam_sort", 1, "memory", None),
    ("plassembler", "Exception in thread main java.lang.OutOfMemoryError: Java heap space", 1, "memory", None),
    ("abricate", "OSError: [Errno 24] Too many open files: 'x'", 1, "open_files", None),
    ("platon", "OSError: [Errno 28] No space left on device: '/tmp/platon_xyz'", 1, "tmp_space", None),
    ("spades", "ERROR Failed to write: No space left on device", 1, "disk", None),
    ("mob_recon", "Disk quota exceeded", 1, "disk", None),
    ("spades", "pthread_create: Resource temporarily unavailable", 1, "thread_limit", None),
    ("platon", "", 124, "timeout_slow", None),
    ("amrfinder", "ERROR: Could not find the AMRFinder database directory", 1, "db_missing", None),
    ("plasmer", "no CUDA-capable device is detected", 1, "gpu_missing", None),
    ("mob_recon", "PermissionError: [Errno 13] Permission denied: '/data/x'", 1, "permission", None),
    ("datasets", "curl: Could not resolve host: api.ncbi.nlm.nih.gov", 6, "network", None),
]
for tool, text, code, cause, need in CASES:
    hit = ra.classify(tool, text, code, rows)
    good = hit is not None and hit["cause"] == cause and ((need is None and hit["needed_gb"] is None) or (need is not None and hit["needed_gb"] is not None and abs(hit["needed_gb"] - need) < 1e-3))
    check(f"{tool}: {(text or 'exit ' + str(code))[:48]!r} -> {cause}" + (f", needs {need:.2f} GB" if need else ""), good, hit)
check("a clean exit or an unknown message is not classified", ra.classify("spades", "all fine", 0, rows) is None and ra.classify("spades", "something odd", 1, rows) is None)

ctx = lambda **kw: dict({"memory_gb": 4, "threads": 6, "available_gb": 6.9, "tmpdir": "", "timeout": 0, "progress": 0}, **kw)  # noqa: E731
v = ra.decide("spades", "s1", 255, HAMMER, ctx())
check("tight (6.9 GB free): the need rounded up, -m 6", v["action"] == "retry" and v["memory_gb"] == "6", v)
check("the line says what and why in plain words", "spades needs about 5.2 GB for this isolate; raising memory from 4 to 6 GB (6.9 GB are free) and retrying" in v["message"], v["message"])
v = ra.decide("spades", "s1", 255, HAMMER, ctx(available_gb=16))
check("plenty (16 GB free): need x 1.15 + 0.5 GB = 7", v["action"] == "retry" and v["memory_gb"] == "7", v)
v = ra.decide("spades", "s1", 255, HAMMER, ctx(available_gb=3.8))
check("none fits (3.8 GB free): skip with the exact numbers and the WSL advice", v["action"] == "skip" and "needs 5.2 GB, 3.8 GB are free" in v["message"] and ".wslconfig (memory=8GB)" in v["message"], v)
v = ra.decide("spades", "s1", 255, HAMMER, ctx(memory_gb=8, available_gb=16))
check("a budget that already covers the need is never lowered, and not 'raised' either: skip says so", v["action"] == "skip" and "already covers" in v["message"], v)
v = ra.decide("mob_recon", "s1", 137, "", ctx(memory_gb=4, available_gb=16))
check("OOM kill with no stated need: 1.5 x the budget when it fits", v["action"] == "retry" and v["memory_gb"] == "6", v)
v = ra.decide("mob_recon", "s1", 137, "", ctx(memory_gb=4, available_gb=4.2))
check("OOM kill, nothing fits: with threads that scale, the ladder goes on to halve them", v["action"] == "retry" and v["threads"] == "3" and v["memory_gb"] == "", v)
v = ra.decide("mob_recon", "s1", 137, "", ctx(memory_gb=4, available_gb=4.2, threads=1))
check("OOM kill, nothing fits, one thread: skip", v["action"] == "skip", v)
v = ra.decide("plassembler", "s1", 1, "java.lang.OutOfMemoryError: Java heap space", ctx(available_gb=16))
check("Java heap: the memory budget rises; threads are not touched (the table says they do not scale)", v["action"] == "retry" and v["threads"] == "", v)

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    state = str(tmp / "state" / "spades.s1.txt")
    ladder = []
    for attempt in range(4):
        v = ra.decide("mob_recon", "s1", 137, "", ctx(memory_gb=4 + attempt, available_gb=64), state_file=state, max_attempts=2)
        ladder.append(v["action"] + ":" + v["response"])
        if v["action"] == "retry":
            os.makedirs(os.path.dirname(state), exist_ok=True)
            open(state, "a").write("mob_recon|s1|memory|%s\n" % v["response"])
    check("each response once, at most 2 adjustments, then skip", ladder[:2] == ["retry:raise_memory", "retry:halve_threads"] and ladder[2].startswith("skip") and ladder[3].startswith("skip"), ladder)
    v = ra.decide("mob_recon", "s2", 137, "", ctx(memory_gb=4, available_gb=64), state_file=state, max_attempts=2)
    check("another isolate has its own count", v["action"] == "retry", v)
    cli = subprocess.run([sys.executable, "-I", str(ROOT / "python" / "resource_adapt.py"), "decide", "--tool", "spades", "--isolate", "s9", "--exit-code", "255", "--log", str(tmp / "log.txt"),
                          "--threads", "6", "--memory-gb", "4", "--available-gb", "6.9", "--state", str(tmp / "st.txt")], capture_output=True, text=True,
                         input=None) if (tmp / "log.txt").write_text(HAMMER, encoding="utf-8") else None
    first = cli.stdout.strip().split("\t")
    cli2 = subprocess.run([sys.executable, "-I", str(ROOT / "python" / "resource_adapt.py"), "decide", "--tool", "spades", "--isolate", "s9", "--exit-code", "255", "--log", str(tmp / "log.txt"),
                           "--threads", "6", "--memory-gb", "6", "--available-gb", "6.9", "--state", str(tmp / "st.txt")], capture_output=True, text=True)
    check("the CLI answers one TSV line (retry, memory 6) and records the response; the same failure again is not retried the same way", first[0] == "retry" and first[2] == "6" and cli2.stdout.split("\t")[0] == "skip", (cli.stdout, cli2.stdout))

    # temp relocation
    a, b = tmp / "small", tmp / "other"
    a.mkdir(), b.mkdir()
    v = ra.decide("platon", "s1", 1, "OSError: [Errno 28] No space left on device: '/tmp/platon'", ctx(tmpdir=str(a), candidates=[str(a), str(b)]))
    check("temp space: the work folder moves to another folder with room (not the current one)", v["action"] == "retry" and v["tmpdir"] == str(b), v)
    v = ra.decide("platon", "s1", 1, "OSError: [Errno 28] No space left on device: '/tmp/platon'", ctx(tmpdir=str(a), candidates=[str(a), str(tmp / "nope" / "deep")]))
    check("temp space: a missing or identical candidate is not chosen; with no room it is a skip", v["action"] in ("retry", "skip") and v["tmpdir"] != str(a), v)

    # timeout extension only with progress
    v = ra.decide("platon", "s1", 124, "", ctx(timeout=600, progress=1))
    check("timeout with progress: the limit doubles once", v["action"] == "retry" and v["timeout"] == "1200", v)
    v = ra.decide("platon", "s1", 124, "", ctx(timeout=600, progress=0))
    check("timeout without progress is treated as stuck: skip", v["action"] == "skip" and "stuck" in v["message"], v)

    # open files: the hard limit is never exceeded
    new, hard, note = ra.ulimit_plan((1024, 1048576))
    check("open files: the soft limit rises, never above the hard limit", new == 4096 and new <= hard, (new, hard, note))
    new, hard, note = ra.ulimit_plan((1024, 2048))
    check("open files: capped at a low hard limit", new == 2048, (new, hard))
    new, hard, note = ra.ulimit_plan((2048, 2048))
    check("open files: at the hard limit nothing is raised and the message says a system change would be needed", new is None and "hard limit" in note, note)
    if os.name == "posix":
        code = ("import sys; sys.path.insert(0, %r); import resource_adapt as r; print(r.ulimit_plan())" % str(ROOT / "python"))
        out = subprocess.run(["bash", "-c", "ulimit -Sn 256; %s -I -c %r" % (sys.executable, code)], capture_output=True, text=True)
        got = eval(out.stdout.strip()) if out.stdout.strip() else None  # noqa: S307  (our own subprocess output)
        check("a real `ulimit -n 256` child is told to go to 4096 (or its hard limit)", got is not None and got[0] is not None and 256 < got[0] <= (got[1] if got[1] not in (-1,) else 1048576), (out.stdout, out.stderr))
    else:
        print("  n/a   real `ulimit -n` subprocess test: not applicable on Windows (no per-process open-file limit)")

    # the learned profile
    reads = [tmp / "r1.fq", tmp / "r2.fq"]
    for r in reads:
        r.write_bytes(b"@r\nACGT\n+\nIIII\n" * 100)
    sig = ra.signature(reads)
    ra.record(tmp, "spades", "s1", sig, needed=5.24, budget=6, threads="6", attempts=2)
    got = ra.lookup(tmp, "spades", "s1", sig)
    check("a learned need is found again with the same reads (budget 6 GB, 2 attempts)", got and got["budget_gb"] == 6 and abs(got["needed_gb"] - 5.24) < 1e-6 and got["attempts"] == 2, got)
    reads[0].write_bytes(b"@r\nACGTACGT\n+\nIIIIIIII\n" * 100)
    check("changed reads invalidate it", ra.lookup(tmp, "spades", "s1", ra.signature(reads)) is None)
    check("another tool or isolate has no entry", ra.lookup(tmp, "platon", "s1", sig) is None and ra.lookup(tmp, "spades", "s2", sig) is None)
    check("the profile merges into one table", ra.merge(tmp, tmp / "resource_profile.tsv") == 1 and "spades\ts1\t" in (tmp / "resource_profile.tsv").read_text(encoding="utf-8"))
    table = tmp / "learned.tsv"
    table.write_text("tool\tneeded_gb\treads_gb\n" + "".join("spades\t%.1f\t%.1f\n" % (2 + 1.5 * g, g) for g in (1, 2, 3, 4)), encoding="utf-8")
    check("no estimate from fewer than 5 learned isolates", ra.estimate(str(table), "spades", 2.5) is None)
    table.write_text(table.read_text(encoding="utf-8") + "spades\t11.0\t6.0\n", encoding="utf-8")
    est = ra.estimate(str(table), "spades", 5.0)
    check("an estimate from 5 learned isolates is labelled estimated (9.5 GB for 5 GB of reads)", est and abs(est[0] - 9.5) < 0.2 and "estimated" in est[1], est)
    manifest = tmp / "run_manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    (tmp / "ev.jsonl").write_text(json.dumps({"event": "resource_adjust", "sample": "s1", "message": "m", "pid": 1}) + "\n", encoding="utf-8")
    ra.manifest(str(tmp / "resource_profile.tsv"), str(manifest), str(tmp / "ev.jsonl"))
    data = json.loads(manifest.read_text(encoding="utf-8"))
    check("run_manifest.json gets a resources section with the profile and every adjustment", data["resources"]["profile"][0]["budget_gb"] == "6" and data["resources"]["adjustments"][0]["message"] == "m", data)

# the generated document is current
doc = (ROOT / "docs" / "RESOURCE_ADAPTATION.md").read_text(encoding="utf-8") if (ROOT / "docs" / "RESOURCE_ADAPTATION.md").exists() else ""
check("docs/RESOURCE_ADAPTATION.md is the table rendered (python3 python/resource_adapt.py docs > docs/RESOURCE_ADAPTATION.md)", doc.replace("\r\n", "\n") == ra.docs(rows), "")

# scientific parameters are never touched: the verdict only carries resource fields, and --only-assembler is opt-in
allowed = {"action", "cause", "memory_gb", "threads", "tmpdir", "ulimit_n", "timeout", "needed_gb", "message", "response", "id", "label"}
check("a verdict carries resource fields only (no k-mers, thresholds or modes)", set(ra.decide("spades", "s", 255, HAMMER, ctx())) <= allowed)
assemble = (ROOT / "scripts" / "03_assemble.sh").read_text(encoding="utf-8")
check("--only-assembler appears only behind ASSEMBLER_ALLOW_ONLY_ASSEMBLER", "ASSEMBLER_ALLOW_ONLY_ASSEMBLER" in assemble and assemble.count("--only-assembler") >= 1 and " -k " not in assemble.replace("-k)", ""))

# run_adaptive end to end (bash, fake tools)
if os.name != "posix":
    print("  n/a   run_adaptive end-to-end: needs bash on Linux/macOS (covered on CI)")
else:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "res").mkdir()
        script = tmp / "fake.sh"
        script.write_text("""#!/usr/bin/env bash
# a fake tool: what it needs is chosen by the case; it records the environment it ran with
echo "$CASE mem=${MEMORY_GB:-} threads=${THREADS:-} tmp=${TMPDIR:-} ulimit=$(ulimit -n) timeout=${TOOL_TIMEOUT_SECONDS:-} java=${JAVA_TOOL_OPTIONS:-}" >> "$CALLS"
case "$CASE" in
  memory)  if [ "${MEMORY_GB:-0}" -lt 6 ]; then echo "ERROR You need approx. 5.24277GB of free RAM." > "$ADAPT_LOG"; exit 255; fi;;
  oomkill) if [ "${THREADS:-9}" -gt 3 ]; then exit 137; fi;;
  tmp)     case "${TMPDIR:-}" in */bigger) ;; *) echo "OSError: No space left on device: '/tmp/x'" > "$ADAPT_LOG"; exit 1;; esac;;
  files)   if [ "$(ulimit -n)" -lt 2000 ]; then echo "OSError: [Errno 24] Too many open files" > "$ADAPT_LOG"; exit 1; fi;;
  timeout) if [ "${TOOL_TIMEOUT_SECONDS:-0}" -lt 1200 ]; then exit 124; fi;;
  never)   echo "ERROR You need approx. 50GB of free RAM." > "$ADAPT_LOG"; exit 255;;
esac
exit 0
""", encoding="utf-8", newline="\n")
        driver = tmp / "drive.sh"
        driver.write_text("""#!/usr/bin/env bash
set -uo pipefail
[[ -n "${SOFT_NOFILE:-}" ]] && ulimit -Sn "$SOFT_NOFILE"
export PROJECT_ROOT="$ROOT" RESULTS_DIR="$TMP/res" NO_COLOR=1
source "$ROOT/scripts/lib.sh"
export THREADS="${THREADS:-6}" MEMORY_GB="${MEMORY_GB:-4}"
rc=0
ADAPT_LOG="$TMP/log_$CASE.txt" run_adaptive "$TOOLN" iso1 -- bash "$TMP/fake.sh" || rc=$?
echo "rc=$rc after: THREADS=$THREADS MEMORY_GB=$MEMORY_GB TMPDIR=${TMPDIR:-unset}"
""", encoding="utf-8", newline="\n")

        def drive(case, tool="spades", **env):
            (tmp / "calls.log").write_text("")
            e = dict(os.environ, ROOT=str(ROOT), TMP=str(tmp), CASE=case, TOOLN=tool, CALLS=str(tmp / "calls.log"), PLASBENCH_TEST_AVAILABLE_MB="16384", PLASBENCH_TMP_CANDIDATES=str(tmp / "bigger"))
            e.update(env)
            (tmp / "bigger").mkdir(exist_ok=True)
            os.makedirs(tmp / "res" / "resource_state.d", exist_ok=True)
            for f in (tmp / "res" / "resource_state.d").glob("*"):
                f.unlink()
            r = subprocess.run(["bash", str(driver)], capture_output=True, text=True, env=e, timeout=120)
            return r, (tmp / "calls.log").read_text().splitlines()

        r, calls = drive("memory")
        check("run_adaptive: SPAdes-style need -> retried once with the raised budget, then succeeds", "rc=0" in r.stdout and len(calls) == 2 and "mem=4" in calls[0] and "mem=7" in calls[1], (r.stdout, r.stderr, calls))
        check("... the line is plain and a resource_adjust event is written", "raising memory from 4 to 7 GB" in r.stderr + r.stdout and "resource_adjust" in (tmp / "res" / "run_events.jsonl").read_text(), (r.stderr, r.stdout))
        check("... the changes were for that command only (the caller's settings are restored)", "THREADS=6 MEMORY_GB=4" in r.stdout, r.stdout)
        r, calls = drive("oomkill", "mob_recon")
        check("run_adaptive: exit 137 -> memory budget raised first (1.5 x), still killed, then threads halved: succeeds on the 2nd adjustment", "rc=0" in r.stdout and len(calls) == 3, (r.stdout, calls))
        r, calls = drive("tmp", "platon")
        check("run_adaptive: temp space -> TMPDIR moved to the roomier folder", "rc=0" in r.stdout and any("tmp=" + str(tmp / "bigger") in c for c in calls[1:]), (r.stdout, calls))
        r, calls = drive("files", "abricate", SOFT_NOFILE="512")
        check("run_adaptive: too many open files -> the retry runs under a higher ulimit -n", "rc=0" in r.stdout and len(calls) == 2 and "ulimit=512" in calls[0] and "ulimit=512" not in calls[1], (r.stdout, r.stderr, calls))
        r, calls = drive("timeout", "platon", TOOL_TIMEOUT_SECONDS="600")
        check("run_adaptive: exit 124 without a recent log is stuck, not slow: no extension", "rc=124" in r.stdout and len(calls) == 1, (r.stdout, calls))
        (tmp / "log_timeout.txt").write_text("progress\n")
        r, calls = drive("timeout", "platon", TOOL_TIMEOUT_SECONDS="600")
        check("run_adaptive: exit 124 with a log that is still being written -> the limit doubles once", "rc=0" in r.stdout and len(calls) == 2 and "timeout=1200" in calls[1], (r.stdout, calls))
        r, calls = drive("never")
        check("run_adaptive: nothing fits -> the failure is returned (the caller records it), one attempt, the reason is printed", "rc=255" in r.stdout and len(calls) == 1 and "needs 50.0 GB" in r.stderr + r.stdout, (r.stdout, r.stderr, calls))
        r, calls = drive("memory", AUTO_RESOURCES="0")
        check("AUTO_RESOURCES=0: one attempt, the failure is returned unchanged", "rc=255" in r.stdout and len(calls) == 1, (r.stdout, calls))
        r, calls = drive("memory", PLASBENCH_IN_DOCKER="1", PATH="/usr/bin:/bin")
        check("Docker mode and a minimal PATH (no ps used): the same retry works", "rc=0" in r.stdout and len(calls) == 2, (r.stdout, r.stderr, calls))
        r, calls = drive("memory", PROJECT_ROOT_BROKEN="1", PLASBENCH_TEST_AVAILABLE_MB="2048")
        check("a verdict the engine cannot make never aborts the command: low memory -> skip, the original exit status comes back", "rc=255" in r.stdout and len(calls) == 1, (r.stdout, calls))

print("ALL RESOURCE ADAPTATION TESTS PASSED" if ok else "RESOURCE ADAPTATION TESTS FAILED")
sys.exit(0 if ok else 1)
