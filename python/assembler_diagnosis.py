#!/usr/bin/env python3
"""Say WHY an assembler (or a read-preparation tool) failed, from the tail of its log, and what to do about it.

Stage 3 used to report only "SPAdes failed ... see logs/<sample>.spades.log". The cause is almost always in that log, in words a person can act on
(the disk is full, the memory limit was reached, the reads are truncated), so this reads the log and names it:

  python3 -I python/assembler_diagnosis.py LOGFILE [--exit-code N] [--tool spades] [--sample ID] [--threads N] [--memory-gb N]
                                           [--available-gb N] [--free-gb N] [--format tsv|json|text]

`diagnose(log_text, context)` returns {cause, title, confidence, evidence_lines, advice, retryable, retry, environmental}:

  cause           a short stable id (disk_full, out_of_memory, ... unknown)
  confidence      high (the log says it in words), medium (the exit status or a symptom points to it), low (nothing recognised: unknown)
  evidence_lines  the log lines the verdict rests on (never invented; for unknown, the last 15 lines)
  advice          what to do, with the commands to check
  retryable       True when one automatic retry with changed settings is worthwhile (retry names the kind: memory, stale, reads)
  environmental   True when the cause belongs to the machine, not the isolate: it would fail the same way for every sample, so stage 3 stops early

The rules are a table (RULES), tried in order, so the priority is visible and a new message is one row. Nothing is guessed: a log that matches no rule is
reported as `unknown` with confidence low and its last lines. Standard library only; Python 3.9 compatible.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys

TAIL_LINES = 15
MAX_EVIDENCE = 4

# Each rule: (cause, title, confidence, patterns, retry, environmental, advice).  A rule matches when ANY pattern matches a line of the log.
# {free}, {tmp}, {threads}, {memory}, {available}, {sample}, {log} are filled from the context when it knows them.
RULES = [
    ("disk_full", "the disk is full", "high",
     [r"no space left on device", r"disk quota exceeded", r"\bENOSPC\b", r"\[Errno 28\]", r"not enough disk space", r"errorCode=9\b",
      r"failed to write.*(space|disk)", r"No space left"],
     None, True,
     "Free disk space where the study and the temporary folder are ({free}), then run the same command again; finished work is reused. Check with: df -h . {tmp}. "
     "On WSL the Ubuntu virtual disk lives on the Windows drive that holds it (usually C:): when that drive is full, Ubuntu reports a full disk even if df shows room. "
     "Move the study folder or the WSL disk to a drive with space, or empty the Windows drive."),
    ("read_only_or_permission", "a folder is read-only or not writable", "high",
     [r"read-only file system", r"\[Errno 30\]", r"permission denied", r"\[Errno 13\]", r"operation not permitted",
      r"No usable temporary directory", r"cannot create temp"],
     None, True,
     "A folder PlasBench must write to cannot be written: the study folder, the data folder or the temporary folder ({tmp}). Check with: ls -ld <folder>; touch <folder>/x. "
     "A study folder under /mnt (Windows) can be read-only or locked by a sync program; use a folder inside Ubuntu (for example under your home) or set TMPDIR to a writable folder."),
    ("spades_needs_memory", "SPAdes says exactly how much memory it needs and the budget was lower", "high",
     [r"You need approx\.?\s*[0-9.]+\s*(GB|G|MB|TB).*RAM", r"reads contain too many k-?mers to fit into (the )?available memory",
      r"too many k-?mers to fit"],
     "memory_need", False,
     "SPAdes stopped because its memory budget was too small: it needs about {need} GB of free memory for these reads (it was given {memory} GB; {available} GB is free now). "
     "PlasBench retries once with the budget SPAdes asked for (plus a margin) when that fits in the free memory; otherwise it stops and says so. To fix it yourself: raise MEMORY_GB "
     "(plasbench run --memory-gb N) to at least {need_up}, close other programs, give Ubuntu more memory (WSL: memory= in C:\\Users\\<you>\\.wslconfig, then wsl --shutdown), "
     "or use a smaller read set (a smaller --max-isolates, or skip this isolate). Check with: free -h."),
    ("memory_limit_exceeded", "SPAdes reached its own memory limit (-m)", "high",
     [r"memory limit.*(exceed|reached|too low)", r"exceeded.*memory limit", r"not enough memory"],
     "memory", False,
     "SPAdes was told to stop at {memory} GB and needed more. PlasBench retries once with fewer threads and a budget that fits the memory that is free now. If that fails too, "
     "free memory, lower THREADS, or raise the memory the computer gives Ubuntu (WSL: memory= in C:\\Users\\<you>\\.wslconfig, then wsl --shutdown). Check with: free -h."),
    ("out_of_memory", "the computer ran out of memory", "high",
     [r"std::bad_alloc", r"cannot allocate memory", r"out of memory", r"oom-killer", r"killed process \d+", r"MemoryError", r"memory allocation (failed|error)",
      r"bad_alloc"],
     "memory", False,
     "The assembler ran out of memory (it asked for {memory} GB with {threads} threads; {available} GB was free). PlasBench retries once with fewer threads and a smaller budget. "
     "Otherwise free memory or lower THREADS and ASSEMBLY_MEMORY_GB. Check with: free -h. On WSL raise memory= in C:\\Users\\<you>\\.wslconfig and run wsl --shutdown."),
    ("too_many_threads", "the system refused to start more threads", "high",
     [r"pthread_create", r"can'?t start new thread", r"cannot create (a )?thread", r"Resource temporarily unavailable", r"too many open files",
      r"std::system_error"],
     None, True,
     "{threads} threads were requested and the system refused to start them (a thread, process or file limit). Lower THREADS (plasbench run --threads N) to the number of CPUs you have. "
     "Check with: nproc; ulimit -a."),
    ("illegal_instruction", "the program uses a CPU feature this computer does not have", "high",
     [r"illegal instruction", r"\bSIGILL\b"],
     None, True,
     "The assembler binary was built for a newer CPU than this one (or emulated). Re-install it from conda on this computer (plasbench install-tools), or run on a different machine."),
    ("segmentation_fault", "the program crashed (segmentation fault)", "high",
     [r"segmentation fault", r"\bSIGSEGV\b", r"core dumped"],
     None, False,
     "The assembler crashed. This is usually a damaged read file or a broken install. Re-check the reads (gzip -t <reads>) and re-install the tool (plasbench install-tools); "
     "if it repeats on every isolate the install is the cause."),
    ("python_environment", "the assembler's Python is broken or too new/old for it", "high",
     [r"ModuleNotFoundError", r"No module named", r"ImportError", r"SyntaxError", r"distutils", r"AttributeError: module", r"Traceback \(most recent call last\)"],
     None, True,
     "The assembler is a Python program and it failed inside Python, before assembling anything: its environment is incompatible (for example SPAdes 3.15.x needs distutils, which "
     "Python 3.12 removed). Check with: spades.py --test. Re-create the tools with plasbench install-tools, or use a newer SPAdes (version 4 or later from bioconda)."),
    ("truncated_reads", "a read file is truncated or corrupt", "high",
     [r"unexpected end of file", r"not in gzip format", r"invalid compressed data", r"crc error", r"Compressed file ended before", r"premature end",
      r"file (is )?truncated", r"is not a gzip"],
     "reads", False,
     "A read file ended early or is damaged (an interrupted download). PlasBench re-checks it against the download checksum. If it is bad, delete it and download again: "
     "remove {sample}'s *_1.fastq.gz and *_2.fastq.gz (and downloads.sha256) from the data folder and run the same plasbench run command again; stage 1 fetches them afresh."),
    ("mate_mismatch", "the two read files do not pair up", "high",
     [r"(different|unequal|mismatch\w*)\b.*\b(number|count)\b.*\b(reads|mates|records)", r"\b(reads|mates)\b.*(do not|don't) match",
      r"read ?names? (do not|don't) match", r"number of reads in .* differ", r"paired reads? .*mismatch", r"R1 and R2 .*(differ|match|same)"],
     "reads", False,
     "The forward and reverse read files hold different numbers of reads or different read names. Re-download both; if the sequencing run itself is unpaired, mark it so in the sheet."),
    ("kmer_or_read_length", "the reads are too short for the assembler's k-mer sizes", "high",
     [r"k-?mer.*(too large|larger than|must be (smaller|less|odd)|exceeds)", r"read length.*(too short|shorter)", r"reads? (are|is) too short",
      r"Failed to estimate maximum read length", r"maximum read length"],
     None, False,
     "The reads are shorter than the assembler needs. Trimming may have cut them (check MIN_READ_LEN and FASTP_EXTRA) or this run is not ordinary short-read data. "
     "Check with: zcat <trimmed reads> | head -8."),
    ("empty_or_too_few_reads", "there are no reads, or too few, to assemble", "high",
     [r"no reads", r"too few reads", r"input file is empty", r"empty (input|file|fastq|reads)", r"0 reads", r"reads? (file )?(is|are) empty",
      r"is empty"],
     None, False,
     "The trimmed read file is empty or has too few reads. The trimming step removed everything (a quality or length filter too strict for these reads) or the download is empty. "
     "Check with: ls -l <data>/{sample}/ and zcat <reads> | wc -l, and the fastp report in the same folder."),
    ("missing_input_file", "a file the assembler needs is missing", "high",
     [r"no such file or directory", r"can'?t open (the )?file", r"cannot open", r"does not exist", r"doesn't exist", r"file not found"],
     None, False,
     "A file the assembler was given is missing or unreadable (reads, or its own output folder). Check that the data folder still holds the reads (a moved or deleted study, a drive that "
     "is not mounted) and run stage 1 again."),
    ("stale_output_directory", "an output folder from an earlier attempt blocks the restart", "high",
     [r"output[_ ]dir(ectory)? .*(is not empty|already exists|should exist|not found)", r"--continue.*(not|cannot|can't)", r"--restart-from",
      r"options? .*(differ|incompatible|mismatch).*(previous|earlier)", r"cannot be continued", r"can'?t continue"],
     "stale", False,
     "An unfinished output folder from an earlier attempt for this isolate is in the way. PlasBench removes that isolate's own assembly folder and tries once more; nothing else is touched."),
    ("tool_missing", "the assembler or a helper program was not found", "high",
     [r"command not found", r"not found in path", r"executable .* not found", r"cannot find (spades|the assembler)", r"could not find (spades|bwa|samtools|racon|pilon|makeblastdb)"],
     None, True,
     "A program the assembler calls is not installed or not on PATH. Run: plasbench install-tools, then plasbench run again."),
    ("download_network", "a download failed (network)", "medium",
     [r"errorCode=(1|2|6|7|19|22|23|24)\b", r"connection (timed out|reset|refused)", r"could not resolve host", r"name or service not known"],
     None, False,
     "A download needed by this step failed because of the network. Check the connection and run the same command again; downloads resume."),
]

KILL_SIGNALS = {9: "SIGKILL", 6: "SIGABRT", 4: "SIGILL", 11: "SIGSEGV", 15: "SIGTERM"}
RETURN_VALUE = re.compile(r"(?:OS return value|err(?:or)? code|return code|exit(?:ed)? (?:with )?(?:code|status))[: ]+(-?\d+)", re.I)


# Lines every SPAdes run ends with (citation, thanks, where to report): never evidence of a failure.
FOOTER = re.compile(r"doi\.org/|thank you for using|please,? cite|in case of any problems|in case you have troubles|spades\.support@|"
                    r"github\.com/ablab|bioinf\.spbau|you can write to|provide us with params\.txt|^\s*SPAdes pipeline finished|"
                    r"^\s*={3,}\s*SPAdes pipeline|log can be found|^\s*-{3,}\s*$|^\s*\*+\s*$|^\s*(Citation|Cite)", re.I)
ERROR_MARK = re.compile(r"ERROR|error|Error|== Error ==|FATAL|Exception|failed|finished abnormally|terminate called|Assertion", )
NEED_RE = re.compile(r"You need approx\.?\s*([0-9]+(?:\.[0-9]+)?)\s*(TB|GB|G|MB|M)?", re.I)


def memory_need_gb(log_text):
    """The memory SPAdes says it needs (`You need approx. 5.24277GB of free RAM`) in GB, or None when the log does not say."""
    found = None
    for m in NEED_RE.finditer(log_text or ""):
        value = float(m.group(1))
        unit = (m.group(2) or "GB").upper()
        found = value * {"TB": 1024.0, "GB": 1.0, "G": 1.0, "MB": 1 / 1024.0, "M": 1 / 1024.0}[unit]
    return found


def _fill(text, context):
    values = {"free": "%s GB free" % context["free_gb"] if context.get("free_gb") is not None else "check df -h",
              "tmp": context.get("tmpdir") or "$TMPDIR", "threads": context.get("threads") or "?",
              "memory": context.get("memory_gb") or "?", "available": context.get("available_gb") if context.get("available_gb") is not None else "?",
              "sample": context.get("sample") or "the isolate", "log": context.get("log") or "the log",
              "need": ("%.2f" % context["need_gb"]) if context.get("need_gb") else "more",
              "need_up": ("%d GB" % math.ceil(context["need_gb"] * 1.15)) if context.get("need_gb") else "what SPAdes asks for"}
    try:
        return text.format(**values)
    except (KeyError, IndexError, ValueError):
        return text


def _exit_code(lines, context):
    """The assembler's own exit status: the context's, else the last 'return value' SPAdes printed."""
    code = context.get("exit_code")
    try:
        return int(code)
    except (TypeError, ValueError):
        pass
    found = None
    for line in lines:
        m = RETURN_VALUE.search(line)
        if m:
            found = int(m.group(1))
    return found


def diagnose(log_text, context=None):
    """The verdict for one failed step. `context` may hold exit_code, tool, sample, threads, memory_gb, available_gb, free_gb, tmpdir, log."""
    context = dict(context or {})
    lines = [ln.rstrip("\r") for ln in (log_text or "").splitlines()]
    lines = [ln for ln in lines if ln.strip()]
    footer_free = [ln for ln in lines if not FOOTER.search(ln)]
    context.setdefault("need_gb", memory_need_gb(log_text))
    lines_all, lines = lines, footer_free
    for cause, title, confidence, patterns, retry, environmental, advice in RULES:
        compiled = [re.compile(p, re.I) for p in patterns]
        hits = [ln.strip()[:300] for ln in lines if any(c.search(ln) for c in compiled)]
        if hits:
            # A Python traceback line alone is generic: only claim a Python-environment cause when a specific import/syntax line is also there.
            if cause == "python_environment" and not any(re.search(r"ModuleNotFoundError|No module named|ImportError|SyntaxError|distutils|AttributeError: module", h) for h in hits):
                continue
            # "Resource temporarily unavailable" and "std::system_error" are thread-limit symptoms only together with a thread/process request.
            return _result(cause, title, confidence, hits[-MAX_EVIDENCE:], retry, environmental, _fill(advice, context))
    code = _exit_code(lines_all, context)
    if code in (137, -9, 9):
        return _result("out_of_memory", "the process was killed (SIGKILL), most often for lack of memory", "medium",
                       [f"exit status {code} (SIGKILL); the log names no other cause"], "memory", False, _fill(RULES[3][6], context))
    if code in (132, -4, 4):
        return _result("illegal_instruction", "the program uses a CPU feature this computer does not have", "medium",
                       [f"exit status {code} (SIGILL)"], None, True, _fill(RULES[5][6], context))
    if code in (139, -11, 11):
        return _result("segmentation_fault", "the program crashed (segmentation fault)", "medium",
                       [f"exit status {code} (SIGSEGV)"], None, False, _fill(RULES[6][6], context))
    free = context.get("free_gb")
    if free is not None and free < 0.2:
        return _result("disk_full", "the disk is full", "medium",
                       [f"only {free} GB was free where the study is when the failure was seen; the log names no other cause"], None, True, _fill(RULES[0][6], context))
    marked = [ln for ln in lines if ERROR_MARK.search(ln)]
    tail = [ln.strip()[:300] for ln in (marked[-MAX_EVIDENCE:] if marked else lines[-TAIL_LINES:])]
    note = "" if lines else " (the log is empty: the program failed before writing anything; a missing or broken install, or a full disk, do that)"
    advice = ("The cause is not one PlasBench recognises" + note + ". Read the end of the log: tail -30 " + (context.get("log") or "logs/<sample>.spades.log")
              + ". Check free space (df -h) and memory (free -h). If it fails for every isolate, run plasbench diagnose and report the log tail at "
                "https://github.com/ubeffiong/plasbench/issues.")
    return _result("unknown", "the cause is not recognised", "low", tail or ([f"exit status {code}"] if code is not None else []), None, False, advice)


def _result(cause, title, confidence, evidence, retry, environmental, advice):
    return {"cause": cause, "title": title, "confidence": confidence, "evidence_lines": list(evidence), "advice": advice,
            "retryable": retry is not None, "retry": retry or "", "environmental": bool(environmental)}


def shell_line(result):
    """One tab-separated line for the shell: cause, confidence, retry kind, environmental (1/0), title, evidence line, advice. No field is ever empty."""
    def clean(value):
        value = re.sub(r"[\t\r\n]+", " ", str(value)).strip()
        return value or "-"
    evidence = result["evidence_lines"][-1] if result["evidence_lines"] else "-"
    return "\t".join(clean(v) for v in (result["cause"], result["confidence"], result["retry"], "1" if result["environmental"] else "0", result["title"], evidence, result["advice"]))


def read_tail(path, max_bytes=200000):
    try:
        with open(path, "rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            return handle.read().decode("utf-8", "replace")
    except OSError:
        return ""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("logfile")
    ap.add_argument("--exit-code")
    ap.add_argument("--tool", default="spades")
    ap.add_argument("--sample", default="")
    ap.add_argument("--threads")
    ap.add_argument("--memory-gb")
    ap.add_argument("--available-gb")
    ap.add_argument("--free-gb", type=float)
    ap.add_argument("--tmpdir", default="")
    ap.add_argument("--format", choices=("tsv", "json", "text", "need"), default="text")
    args = ap.parse_args(argv)
    context = {"exit_code": args.exit_code, "tool": args.tool, "sample": args.sample, "threads": args.threads, "memory_gb": args.memory_gb,
               "available_gb": args.available_gb, "free_gb": args.free_gb, "tmpdir": args.tmpdir, "log": args.logfile}
    text = read_tail(args.logfile)
    if args.format == "need":
        need = memory_need_gb(text)
        print("-" if need is None else "%.3f" % need)
        return 0
    result = diagnose(text, context)
    if args.format == "json":
        print(json.dumps(result, indent=2))
    elif args.format == "tsv":
        print(shell_line(result))
    else:
        print(f"{result['title']} ({result['cause']}, confidence {result['confidence']})")
        for line in result["evidence_lines"]:
            print(f"  log: {line}")
        print(f"What to do: {result['advice']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
