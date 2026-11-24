#!/usr/bin/env python3
"""Fair annotation time limits and one retry before `timed_out`.

A real 6-CPU run gave the callers 13 threads; mob_typer, AMRFinderPlus and barrnap hit their wall-clock limits and their results were lost. Now (python/annotate_reference.py):
a DEFAULT limit is scaled by how oversubscribed the callers are (threads asked / CPUs, never below 1; an explicit ANNOTATION_TIMEOUT_SECONDS is taken literally), the
limit counts awake time only, and a caller stopped at its limit is run ONCE more, alone, with all the isolate's threads and twice the limit. A retried success is a normal
result and the annotation is cached; a second timeout stays timed_out (never cached). ANNOTATION_RETRY_TIMED_OUT=0 turns the retry off. Fake tools only; offline.
"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import annotate_reference as ar  # noqa: E402

ok = True


def put(path, text):
    with open(str(path), "w") as handle:
        handle.write(text)


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


# ---- the arithmetic (any OS) ---------------------------------------------------------------------------------------------------------
check("6 CPUs, callers asking 1+1+1+2+4+1+1 = 11 threads: factor 11/6", abs(ar.contention_factor(6, [1, 1, 1, 2, 4, 1, 1]) - 11 / 6) < 1e-9)
check("never below 1 (fewer threads asked than CPUs)", ar.contention_factor(16, [1, 1, 2]) == 1.0)
check("scaled limits round up and keep their keys", ar.fair_timeouts({"*": 600, "isescan": 1800}, 1.5) == {"*": 900, "isescan": 2700})
check("factor 1 leaves the limits alone; no limits stay no limits", ar.fair_timeouts({"*": 600}, 1.0) == {"*": 600} and ar.fair_timeouts({}, 3.0) == {})
check("the retry is on by default and can be switched off", ar.retry_enabled({}) and not ar.retry_enabled({"ANNOTATION_RETRY_TIMED_OUT": "0"}))

if os.name != "posix":
    print("skipped the end-to-end part: needs a POSIX shell for the fake tools")
    print("ALL ANNOTATION FAIR-LIMIT TESTS PASSED" if ok else "ANNOTATION FAIR-LIMIT TESTS FAILED")
    sys.exit(0 if ok else 1)


def fake(directory, name, body):
    path = Path(directory) / name
    put(path, "#!/usr/bin/env bash\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    bin_ = tmp / "bin"
    bin_.mkdir()
    ref = tmp / "reference.fna"
    put(ref, ">chr\n" + "ACGT" * 500 + "\n>plasmid1\n" + "GGCC" * 100 + "\n")
    once = tmp / "barrnap.ran"
    # barrnap hangs the first time (as if starved of CPU) and answers at once the second time
    fake(bin_, "barrnap", f'case "$1" in --version) echo "barrnap 0.9";; *) if [ -e "{once}" ]; then printf "##gff-version 3\\nchr\\tbarrnap:0.9\\trRNA\\t10\\t200\\t0\\t+\\t.\\tName=16S_rRNA;product=16S\\n"; '
                      f'else : > "{once}"; sleep 30; fi;; esac')
    fake(bin_, "mob_typer", 'case "$*" in *--version*) echo "mob_typer 3.1.9";; *) out=""; while [ $# -gt 0 ]; do [ "$1" = "--out_file" ] && out="$2"; shift; done; '
                            'printf "sample_id\\trep_type(s)\\n" > "$out";; esac')
    fake(bin_, "blastn", "exit 0")
    base_env = dict(os.environ, PATH=f"{bin_}{os.pathsep}{os.environ.get('PATH', '')}", ANNOTATION_TIMEOUT_SECONDS="3", PLASBENCH_TOOL_READINESS="off",
                    ANNOTATE_WITH_ISESCAN="0", ANNOTATE_WITH_AMRFINDER="0", ANNOTATE_WITH_ABRICATE="0")

    def annotate(tag, **extra):
        out, prov, cache = tmp / f"{tag}.tsv", tmp / f"{tag}.json", tmp / f"cache-{tag}"
        t0 = time.time()
        done = subprocess.run([sys.executable, "-I", str(ROOT / "python" / "annotate_reference.py"), "--reference", str(ref), "--out", str(out), "--provenance", str(prov),
                               "--threads", "2", "--cache-dir", str(cache), "--workdir", str(tmp / f"work-{tag}")],
                              capture_output=True, text=True, env=dict(base_env, **extra), timeout=120)
        rec = json.loads(prov.read_text(encoding="utf-8")) if prov.exists() else {}
        return done, rec, out, cache, time.time() - t0

    done, rec, out, cache, took = annotate("retry")
    bar = rec.get("callers", {}).get("barrnap", {})
    check("the run completes", done.returncode == 0, done.stderr[-400:])
    check("barrnap timed out once, then succeeded on the retry: a normal result", bar.get("status") == "ok" and bar.get("attempts") == 2 and "timed out" in bar.get("first_attempt", ""), bar)
    check("the retried caller's features are in the table", "16S" in out.read_text(encoding="utf-8"), out.read_text(encoding="utf-8"))
    check("the log says it tried once more, alone", "trying it once more alone with 2 thread(s)" in done.stdout, done.stdout)
    check("a retried success is cached like any other result", cache.exists() and list(cache.rglob("*.tsv")), list(cache.rglob("*")) if cache.exists() else "no cache folder")
    check("the retry waited for the answer, not for the 30 s sleep", took < 40, took)

    once.unlink()
    done, rec, out, cache, took = annotate("noretry", ANNOTATION_RETRY_TIMED_OUT="0")
    bar = rec.get("callers", {}).get("barrnap", {})
    check("ANNOTATION_RETRY_TIMED_OUT=0: one attempt, recorded timed_out", bar.get("status") == "timed_out" and "attempts" not in bar, bar)
    check("a timed-out annotation is not cached", not cache.exists() or not list(cache.rglob("*.tsv")), list(cache.rglob("*")) if cache.exists() else "")

    # default limits (no ANNOTATION_TIMEOUT_SECONDS) are scaled by the contention factor and the log says so
    once.unlink()
    put(once, "")
    env = dict(base_env, ANNOTATE_WITH_ABRICATE="1")
    env.pop("ANNOTATION_TIMEOUT_SECONDS")
    fake(bin_, "abricate", 'case "$1" in --version) echo "abricate 1.0.1";; *) echo "#FILE\tSEQUENCE\tSTART\tEND\tGENE";; esac')
    done = subprocess.run([sys.executable, "-I", str(ROOT / "python" / "annotate_reference.py"), "--reference", str(ref), "--out", str(tmp / "d.tsv"),
                           "--threads", "1", "--workdir", str(tmp / "work-d")], capture_output=True, text=True, env=env, timeout=120)
    check("default limits are scaled when the callers ask for more threads than the isolate has", "time limits are scaled by" in done.stdout, done.stdout)

print("ALL ANNOTATION FAIR-LIMIT TESTS PASSED" if ok else "ANNOTATION FAIR-LIMIT TESTS FAILED")
sys.exit(0 if ok else 1)
