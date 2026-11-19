#!/usr/bin/env python3
"""python/assembler_diagnosis.py names the cause of an assembler failure from its log, and never invents one.

NOTE ON THE FIXTURES: every log below is a SAMPLE WRITTEN FROM KNOWLEDGE of the message formats SPAdes, plasmidSPAdes, Unicycler, fastp, minimap2, aria2 and the C
library print. None was captured from a failing run on this machine (no real SPAdes failure was reproduced). Where the exact wording differs between releases, the
fixture uses the commonly seen form; the rules match on the stable fragment of the message (for example 'No space left on device'), not on a whole line.
"""
import ast
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))
import assembler_diagnosis as ad  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


SPADES_HEAD = """Command line: /opt/conda/bin/spades.py\t-1\t/data/s1/SRR1_1.trim.fastq.gz\t-2\t/data/s1/SRR1_2.trim.fastq.gz\t-o\t/data/s1/assembly\t--threads\t20\t--memory\t5

System information:
  SPAdes version: 3.15.5
  Python version: 3.10.8
  OS: Linux-5.15.133.1-microsoft-standard-WSL2-x86_64-with-glibc2.35

Output dir: /data/s1/assembly
Mode: read error correction and assembling
Threads: 20
Memory limit (in Gb): 5

== Error ==  system call for: "['/opt/conda/bin/spades-hammer', '/data/s1/assembly/corrected/configs/config.info']" finished abnormally, OS return value: 1
In case you have troubles running SPAdes, you can write to spades.support@cab.spbu.ru
"""

# (cause, log text, exit code, expected retry kind, expected environmental)
CASES = [
    ("disk_full", "  0:00:03.412    94M / 94M   ERROR   General                 (kmer_index_builder.hpp   :  88)   Failed to write: No space left on device\n" + SPADES_HEAD, 1, "", True),
    ("disk_full", "OSError: [Errno 28] No space left on device: '/data/s1/assembly/spades.log'\n", 1, "", True),
    ("disk_full", "Disk quota exceeded\n", 1, "", True),
    ("disk_full", "[ERROR] aria2c: errorCode=9 not enough disk space available\n", 9, "", True),
    ("read_only_or_permission", "OSError: [Errno 30] Read-only file system: '/mnt/c/study/data/s1/assembly'\n", 1, "", True),
    ("read_only_or_permission", "FileNotFoundError: [Errno 2] No usable temporary directory found in ['/tmp', '/var/tmp', '/usr/tmp', '/data']\n", 1, "", True),
    ("read_only_or_permission", "PermissionError: [Errno 13] Permission denied: '/data/s1/assembly'\n", 1, "", True),
    ("memory_limit_exceeded", "  0:12:31.002   5G / 5G    ERROR   General  (memory_limit.hpp : 61)  Memory limit exceeded: 5 Gb\n" + SPADES_HEAD, 1, "memory", False),
    ("out_of_memory", "terminate called after throwing an instance of 'std::bad_alloc'\n  what():  std::bad_alloc\n", 134, "memory", False),
    ("out_of_memory", "[  912.3] Out of memory: Killed process 4411 (spades-core) total-vm:9011208kB\n", 137, "memory", False),
    ("out_of_memory", "MemoryError\n", 1, "memory", False),
    ("too_many_threads", "terminate called after throwing an instance of 'std::system_error'\n  what():  Resource temporarily unavailable\n", 134, "", True),
    ("too_many_threads", "RuntimeError: can't start new thread\n", 1, "", True),
    ("illegal_instruction", "Illegal instruction (core dumped)\n", 132, "", True),
    ("segmentation_fault", "Segmentation fault (core dumped)\n", 139, "", False),
    ("python_environment", "Traceback (most recent call last):\n  File \"/opt/conda/bin/spades.py\", line 31, in <module>\n    import support\n"
                           "  File \"/opt/conda/share/spades/spades_pipeline/support.py\", line 20, in <module>\n    from distutils import dir_util\n"
                           "ModuleNotFoundError: No module named 'distutils'\n", 1, "", True),
    ("python_environment", "  File \"spades.py\", line 12\n    print f\"x\"\nSyntaxError: invalid syntax\n", 1, "", True),
    ("truncated_reads", "gzip: /data/s1/SRR1_1.trim.fastq.gz: unexpected end of file\n", 1, "reads", False),
    ("truncated_reads", "EOFError: Compressed file ended before the end-of-stream marker was reached\n", 1, "reads", False),
    ("mate_mismatch", "ERROR: read pairs mismatch: different number of reads in R1 and R2\n", 1, "reads", False),
    ("kmer_or_read_length", "== Error ==  k-mer size 127 is too large for the maximum read length 35; use -k 21,33\n", 1, "", False),
    ("empty_or_too_few_reads", "== Error ==  no reads were found: the input file is empty\n", 1, "", False),
    ("missing_input_file", "== Error ==  file with reads doesn't exist: /data/s1/SRR1_1.trim.fastq.gz\n", 1, "", False),
    ("stale_output_directory", "== Error ==  the output_dir is not empty and --continue was not given; cannot be continued with different options\n", 1, "stale", False),
    ("tool_missing", "bash: spades.py: command not found\n", 127, "", True),
    ("download_network", "[ERROR] aria2c: errorCode=6 network problem\n", 6, "", False),
]


def main():
    # --- one fixture per cause (and variants) -----------------------------------------------------------------------------------------
    for cause, text, code, retry, env in CASES:
        r = ad.diagnose(text, {"exit_code": code})
        check(f"{cause}: recognised ({text.strip().splitlines()[0][:50]})", r["cause"] == cause, r["cause"])
        check(f"{cause}: evidence is taken from the log", r["evidence_lines"] and all(any(e in ln for ln in text.splitlines()) for e in r["evidence_lines"]), r["evidence_lines"])
        check(f"{cause}: retry kind {retry or 'none'} and environmental {env}", r["retry"] == retry and r["retryable"] == bool(retry) and r["environmental"] == env, (r["retry"], r["environmental"]))
        check(f"{cause}: there is advice", len(r["advice"]) > 30 and "{" not in r["advice"], r["advice"])
    # --- priority: the disk message wins over the generic wrapper error that follows it -------------------------------------------------
    r = ad.diagnose(SPADES_HEAD + "No space left on device\n", {})
    check("a disk message beats the generic 'finished abnormally' line", r["cause"] == "disk_full", r["cause"])
    # --- exit status alone (nothing in the log) -----------------------------------------------------------------------------------------
    r = ad.diagnose("== Error ==  system call for: \"['/x/spades-core']\" finished abnormally, OS return value: -9\n", {})
    check("'OS return value: -9' with nothing else is a SIGKILL, medium confidence, memory retry", r["cause"] == "out_of_memory" and r["confidence"] == "medium" and r["retry"] == "memory", r)
    r = ad.diagnose("", {"exit_code": 137})
    check("an empty log with exit 137 is a kill, medium confidence", r["cause"] == "out_of_memory" and r["confidence"] == "medium", r)
    r = ad.diagnose("", {"exit_code": 1, "free_gb": 0.0})
    check("an empty log and no free disk when it failed: disk_full, medium", r["cause"] == "disk_full" and r["confidence"] == "medium", r)
    # --- unknown: never invent ---------------------------------------------------------------------------------------------------------
    lines = [f"line {i}" for i in range(40)]
    r = ad.diagnose("\n".join(lines), {"exit_code": 1})
    check("an unrecognised log is 'unknown' with confidence low", r["cause"] == "unknown" and r["confidence"] == "low" and not r["retryable"], r)
    check("unknown quotes the last 15 lines", r["evidence_lines"] == lines[-15:], r["evidence_lines"])
    r = ad.diagnose("", {"exit_code": 1})
    check("an empty log with an ordinary failure is unknown and says the log is empty", r["cause"] == "unknown" and "log is empty" in r["advice"], r)
    r = ad.diagnose("0:00:01  General  INFO  Starting\n0:00:02  General  INFO  Reads: 100 reads processed\n", {"exit_code": 1})
    check("ordinary progress lines (including '100 reads') are not mistaken for a cause", r["cause"] == "unknown", r)
    r = ad.diagnose("Traceback (most recent call last):\n  File \"x.py\", line 1\nKeyError: 'a'\n", {"exit_code": 1})
    check("a Python traceback alone is not called an environment problem", r["cause"] == "unknown", r["cause"])
    # --- context fills the advice -----------------------------------------------------------------------------------------------------
    r = ad.diagnose("terminate called after throwing an instance of 'std::bad_alloc'\n", {"threads": 20, "memory_gb": 5, "available_gb": 7})
    check("the advice carries the threads, budget and available memory", "20 threads" in r["advice"] and "5 GB" in r["advice"] and "7 GB" in r["advice"], r["advice"])
    # --- shell line: never an empty field (read with a tab IFS would shift them) ----------------------------------------------------------------
    for case in (ad.diagnose("", {}), ad.diagnose("No space left on device", {})):
        parts = ad.shell_line(case).split("\t")
        check("the shell line has 7 non-empty tab-separated fields", len(parts) == 7 and all(parts), parts)
    # --- command line -----------------------------------------------------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "s1.spades.log"
        log.write_text("gzip: x.gz: unexpected end of file\n", encoding="utf-8")
        out = subprocess.run([sys.executable, "-I", str(ROOT / "python" / "assembler_diagnosis.py"), str(log), "--format", "json", "--exit-code", "1"], capture_output=True, text=True)
        check("python -I assembler_diagnosis.py FILE --format json works", out.returncode == 0 and json.loads(out.stdout)["cause"] == "truncated_reads", out.stderr)
        out = subprocess.run([sys.executable, "-I", str(ROOT / "python" / "assembler_diagnosis.py"), str(Path(tmp) / "missing.log"), "--format", "tsv"], capture_output=True, text=True)
        check("a missing log file is handled (unknown, not a crash)", out.returncode == 0 and out.stdout.startswith("unknown\t"), out.stdout + out.stderr)
    # --- Python 3.9 compatibility of every new module ----------------------------------------------------------------------------------------
    new_files = ["python/assembler_diagnosis.py", "python/preflight_resources.py"]
    for rel in new_files:
        src = (ROOT / rel).read_text(encoding="utf-8")
        tree = ast.parse(src, feature_version=(3, 9))
        check(f"{rel} parses as Python 3.9", tree is not None)
        check(f"{rel} has 'from __future__ import annotations'", "from __future__ import annotations" in src)
        check(f"{rel} uses no match statement, no 'except*', no zip(strict=), no removeprefix-free 3.10 API",
              not re.search(r"^\s*match\s+\S+.*:\s*$", src, re.M) and "except*" not in src and "strict=" not in src and "pairwise(" not in src)
        check(f"{rel} does not call write_text/read_text with newline=", not re.search(r"(write_text|read_text)\([^)]*newline=", src))
    print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all assembler-diagnosis checks passed'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
