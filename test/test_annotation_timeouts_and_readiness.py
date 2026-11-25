#!/usr/bin/env python3
"""Annotation callers that fail or hang: readiness probes, per-caller time limits, the reason in one line, and nothing failed is cached.

The incident: AMRFinderPlus (database never installed) 'finished in 0 s (failed)' and ISEScan ran 663 s and 'failed' (fastcluster 1.3.0 built for NumPy 2 beside NumPy 1.26,
`ValueError: NoneType copy mode not allowed`), while `plasbench check` said `[ok] amrfinder` and `[ok] isescan.py`. Fake tools only; offline; POSIX shell for the fakes.
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
import tool_readiness as tr  # noqa: E402

ok = True


def put(path, text):
    """Write text with LF line endings (Path.write_text(newline=) needs Python 3.10)."""
    with open(str(path), "w") as handle:
        handle.write(text)


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


def fake(directory, name, body):
    path = Path(directory) / name
    put(path, "#!/usr/bin/env bash\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


if os.name != "posix":
    print("skipped: needs a POSIX shell for the fake tools")
    sys.exit(0)

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    bin_ = tmp / "bin"
    bin_.mkdir()
    old_path = os.environ.get("PATH", "")
    ref = tmp / "reference.fna"
    ref.write_text(">chr\n" + "ACGT" * 500 + "\n>plasmid1\n" + "GGCC" * 100 + "\n", encoding="utf-8")

    # ---- AMRFinderPlus: with and without its database -------------------------------------------------------------------------------
    fake(bin_, "amrfinder", 'case "$1" in\n--version) echo 3.12.8;;\n--database_version) if [ -e "$AMR_DB_OK" ]; then echo "Software version: 3.12.8"; echo "Database version: 2024-01-31.1"; '
                            'else echo "Running: amrfinder --database_version" >&2; echo "ERROR: Could not find the AMRFinder database directory" >&2; exit 1; fi;;\n*) echo "Contig id";;\nesac')
    os.environ["PATH"] = f"{bin_}{os.pathsep}{old_path}"
    os.environ["AMR_DB_OK"] = str(tmp / "dbok")
    status, detail, fix = tr.amrfinder()
    check("AMRFinder without its database is MISS, not ok", status == "miss", (status, detail))
    check("the message says the database is not installed and the fix is amrfinder -u", "database not installed" in detail and "amrfinder -u" in fix, (detail, fix))
    check("the echoed 'Running:' line is never the reason", "Running:" not in detail, detail)
    (tmp / "dbok").write_text("x")
    status, detail, fix = tr.amrfinder()
    check("with the database it is ok and names the database version", status == "ok" and "2024-01-31.1" in detail, (status, detail))
    (tmp / "dbok").unlink()

    # ---- abricate --list ------------------------------------------------------------------------------------------------------------
    fake(bin_, "abricate", 'if [ "$1" = "--list" ]; then printf "DATABASE\\tSEQUENCES\\tDATE\\nncbi\\t10\\t2024\\nplasmidfinder\\t5\\t2024\\n"; else echo "SEQUENCE"; fi')
    check("abricate with the expected databases is ok", tr.abricate(("ncbi", "plasmidfinder"))[0] == "ok")
    status, detail, fix = tr.abricate(("ncbi", "card2"))
    check("abricate lacking a database names it", status == "miss" and "card2" in detail, detail)

    # ---- ISEScan: its interpreter cannot do the clustering step ---------------------------------------------------------------------
    badpy = fake(bin_, "badpython", 'echo "ValueError: NoneType copy mode not allowed." >&2; exit 1')
    path = bin_ / "isescan.py"
    put(path, f"#!{badpy}\nprint('x')\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    status, detail, fix = tr.isescan()
    check("ISEScan whose clustering step fails is MISS before any 11-minute run", status == "miss" and "NoneType copy mode" in detail and "fastcluster<1.3" in fix, (status, detail, fix))
    path.unlink()

    # ---- annotate_reference.py end to end: a failing caller, a hanging caller -------------------------------------------------------------
    fake(bin_, "isescan.py", 'case "$*" in *--seqfile*) sleep 30;; *) echo "isescan 1.7.3";; esac')
    fake(bin_, "mob_typer", 'echo "usage error" >&2; echo "more detail" >&2; echo "Traceback (most recent call last):" >&2; echo "ValueError: boom" >&2; exit 1')
    for tool in ("barrnap", "blastn"):
        fake(bin_, tool, "exit 0")
    cache = tmp / "cache"
    out = tmp / "features.tsv"
    prov = tmp / "prov.json"
    env = dict(os.environ, PATH=f"{bin_}{os.pathsep}{old_path}", ANNOTATION_TIMEOUT_SECONDS="3", PLASBENCH_TOOL_READINESS="off", AMR_DB_OK=str(tmp / "dbok"))
    t0 = time.time()
    done = subprocess.run([sys.executable, "-I", str(ROOT / "python" / "annotate_reference.py"), "--reference", str(ref), "--out", str(out), "--provenance", str(prov),
                           "--threads", "2", "--cache-dir", str(cache), "--workdir", str(tmp / "work")], capture_output=True, text=True, env=env, timeout=120)
    took = time.time() - t0
    check("the run completes (a failing caller never stops it)", done.returncode == 0, done.stderr[-400:])
    record = json.loads(prov.read_text(encoding="utf-8"))["callers"]
    check("the hanging ISEScan is stopped and recorded timed_out", record["isescan"]["status"] == "timed_out" and record["isescan"].get("retried") is True and "timed out twice" in record["isescan"]["reason"]
          and "timed out after 3 s" in record["isescan"]["reason"] and "timed out after 6 s" in record["isescan"]["reason"], record["isescan"])   # deliberately changed: a hanging caller is retried ONCE (alone, twice the time) before it is recorded
    check("the log line says timed_out with the reason", "isescan finished" in done.stdout and "(timed_out, 0 feature(s)): timed out after 3 s" in done.stdout and "isescan timed out twice" in done.stdout, done.stdout)   # first attempt line, then the plain "timed out twice" line
    check("a failing caller says WHY in one line, from the END of its stderr (not 'Traceback ...' alone)",
          record["mob_typer"]["status"] == "failed" and "ValueError: boom" in record["mob_typer"]["reason"], record["mob_typer"])
    check("a failed/timed-out annotation is never cached", not cache.exists() or not list(cache.glob("*.tsv")), list(cache.glob("*")) if cache.exists() else "")
    check("the caller was stopped at its limit, not waited for (30 s sleep, 3 s limit)", took < 25, took)

    # ---- timeouts scale with the genome and can be switched off -----------------------------------------------------------------------
    check("default limit: max(300, 150 s per Mbp); 4 Mbp -> 600 s, ISEScan 1800 s", ar.annotation_timeouts(4_000_000, {}) == {"*": 600, "isescan": 1800}, ar.annotation_timeouts(4_000_000, {}))
    check("a small genome still gets 300 s (ISEScan 900 s)", ar.annotation_timeouts(1_000_000, {}) == {"*": 300, "isescan": 900})
    check("ANNOTATION_TIMEOUT_SECONDS=off removes the limit", ar.annotation_timeouts(4_000_000, {"ANNOTATION_TIMEOUT_SECONDS": "off"}) == {} and ar.timeout_for({}, "isescan") is None)
    check("a number applies to every caller", ar.timeout_for(ar.annotation_timeouts(4_000_000, {"ANNOTATION_TIMEOUT_SECONDS": "90"}), "isescan") == 90)
    check("typical durations are scaled by genome size", abs(ar.typical_seconds("isescan", 8_000_000) - 2800) < 1 and ar.typical_seconds("abricate_amr", 4_000_000) == 40)   # re-based on measurements 2026-11-22
    check("the failure reason helper drops the echoed command line", "Running:" not in ar._reason(["amrfinder"], 1, "Running: amrfinder -n x\nERROR: no database\n", ""), "")
    os.environ["PATH"] = old_path

print("ALL ANNOTATION READINESS AND TIMEOUT TESTS PASSED" if ok else "ANNOTATION READINESS AND TIMEOUT TESTS FAILED")
sys.exit(0 if ok else 1)
