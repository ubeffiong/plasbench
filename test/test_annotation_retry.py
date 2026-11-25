#!/usr/bin/env python3
"""Annotation callers that hit their time limit (python/annotate_reference.py).

On a real laptop run mob_typer, AMRFinderPlus and barrnap were stopped at their limits on three of four isolates: the callers had been given 13 threads on 6 CPUs and the limits assumed a CPU each.
  - the limits grow with the oversubscription of the thread plan against the CPUs
  - a caller that still hits its limit is run ONCE more, alone, with twice the time; if it then finishes its evidence is kept and the record says it was retried
  - if the second attempt also times out it stays timed_out, with both attempts in the reason, and nothing is cached
  - a caller that failed for another reason, or was switched off, is not retried"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
import annotate_reference as ar  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


def feature(name):
    return {"sequence_id": "chr", "start": 1, "end": 5, "feature_type": "replicon", "label": name, "source": name, "version": "v"}


def run_main(tmp, behaviour, extra=None, env=None):
    seen = {"mob_typer": []}

    def mob(reference, timeout, sequences, threads=1):
        seen["mob_typer"].append((timeout, threads))
        return behaviour(len(seen["mob_typer"]), timeout)

    def other(name):
        return lambda *a, **k: ([], {"status": "ok", "features": 0})

    ar.call_mob_typer = mob
    ar.call_abricate = other("abricate")
    ar.call_amrfinder = other("amrfinder")
    ar.call_isescan = other("isescan")
    ar.call_isfinder = other("isfinder")
    ar.call_barrnap = other("barrnap")
    ref = tmp / "reference.fna"
    ref.write_text(">chr\n" + "ACGT" * 250 + "\n", encoding="utf-8")
    out, prov = tmp / "features.tsv", tmp / "prov.json"
    old = dict(os.environ)
    os.environ.pop("ANNOTATION_TIMEOUT_SECONDS", None)
    os.environ.update(env or {})
    sys.argv = ["annotate_reference.py", "--reference", str(ref), "--out", str(out), "--provenance", str(prov), "--threads", "64", "--cache-dir", ""] + (extra or [])
    try:
        ar.main()
    finally:
        os.environ.clear()
        os.environ.update(old)
    return seen, json.loads(prov.read_text(encoding="utf-8")), out.read_text(encoding="utf-8")


timed_out = {"status": "timed_out", "reason": "timed out after N s (ANNOTATION_TIMEOUT_SECONDS; the caller was stopped, its result is not used and not cached)"}

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    # first attempt times out, the second (alone, twice the time) finishes
    seen, record, table = run_main(tmp, lambda n, t: ([], dict(timed_out)) if n == 1 else ([feature("mob")], {"status": "ok", "features": 1}))
    first, second = seen["mob_typer"]
    check("the caller is run exactly twice", len(seen["mob_typer"]) == 2, seen)
    check("the second attempt has twice the time of the first", second[0] == 2 * first[0], seen)
    check("the second attempt is alone, with the whole thread budget up to 4 (the first had 1)", second[1] == 4 and first[1] == 1, seen)
    status = record["callers"]["mob_typer"]
    check("the record is ok, says it was retried and keeps the first attempt's reason", status["status"] == "ok" and status["retried"] is True and "timed out" in status["first_attempt"], status)
    check("the evidence from the second attempt is kept", "\tmob\t" in table, table)

    # both attempts time out: stays timed_out, honestly, with both attempts in the reason
    seen, record, table = run_main(tmp, lambda n, t: ([], dict(timed_out)))
    status = record["callers"]["mob_typer"]
    check("two timeouts: still timed_out, retried, nothing from it kept", status["status"] == "timed_out" and status["retried"] is True and "\tmob\t" not in table, status)
    check("... and the reason names both attempts", "timed out twice" in status["reason"] and "second attempt" in status["reason"], status["reason"])
    check("no third attempt", len(seen["mob_typer"]) == 2, seen)

    # a failure that is not a time limit is not retried
    seen, record, _ = run_main(tmp, lambda n, t: ([], {"status": "failed", "reason": "exited 1"}))
    check("a failed caller is not retried", len(seen["mob_typer"]) == 1 and record["callers"]["mob_typer"]["status"] == "failed", seen)

    # a switched-off caller is not run, so not retried
    seen, record, _ = run_main(tmp, lambda n, t: ([], dict(timed_out)), env={"ANNOTATE_WITH_MOB_TYPER": "0"})
    check("a switched-off caller is never run or retried", seen["mob_typer"] == [], seen)

    # no limit: no retry
    seen, record, _ = run_main(tmp, lambda n, t: ([], dict(timed_out)), extra=["--timeout", "0"])
    check("with no limit there is nothing to retry", len(seen["mob_typer"]) == 1, seen)

    # the limit grows with oversubscription: 64 threads on this machine's CPUs
    base = ar.annotation_timeouts(1000)["*"]
    seen, _, _ = run_main(tmp, lambda n, t: ([], {"status": "ok", "features": 0}))
    check("the limit is scaled up when the thread plan asks for more than the CPUs", seen["mob_typer"][0][0] >= base and (os.cpu_count() or 1) >= 64 or seen["mob_typer"][0][0] > base, (seen, base))

print("\nall annotation retry checks passed" if ok else "\nFAILED")
sys.exit(0 if ok else 1)
