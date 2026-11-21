#!/usr/bin/env python3
"""annotate_reference.py runs its callers at the same time, gives ISEScan the thread allowance, and keeps the
provenance in the same order as before (so its output does not change)."""

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))
import annotate_reference as ar  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def main():
    tmp = Path(tempfile.mkdtemp())
    ref = tmp / "reference.fna"
    ref.write_text(">chr\nACGTACGTACGT\n>p1\nACGTAC\n", encoding="utf-8")
    seen = {}

    def slow(name, extra=None):
        def call(*args, **kw):
            seen[name] = kw.get("threads", args[-1] if args and isinstance(args[-1], int) else None)
            time.sleep(0.6)
            return [], {"status": "ok", "features": 0}
        return call

    ar.call_mob_typer = slow("mob_typer")
    ar.call_abricate = slow("abricate")
    ar.call_amrfinder = slow("amrfinder")
    ar.call_isescan = slow("isescan")
    ar.call_isfinder = slow("isfinder")
    ar.call_barrnap = slow("barrnap")
    sys.argv = ["annotate_reference.py", "--reference", str(ref), "--out", str(tmp / "f.tsv"),
                "--provenance", str(tmp / "p.json"), "--threads", "16"]
    start = time.time()
    ar.main()
    took = time.time() - start
    check(f"seven callers of 0.6 s each finish together ({took:.1f} s, one after another would be 4.2 s)", took < 2.5, took)
    order = list(json.loads((tmp / "p.json").read_text(encoding="utf-8"))["callers"])
    check("every caller's result is recorded", sorted(order) == sorted(["mob_typer", "abricate_amr", "abricate_replicon",
                                                                        "amrfinder", "isescan", "isfinder", "barrnap"]), order)
    check("ISEScan gets the whole thread allowance", seen.get("isescan") == 16, seen)
    # ---- one switch per caller: a caller switched off is not run and is recorded as not evaluated with the reason ----
    import os
    ran = []
    for attr in ("call_mob_typer", "call_abricate", "call_amrfinder", "call_isescan", "call_isfinder", "call_barrnap"):
        setattr(ar, attr, (lambda n: (lambda *a, **k: (ran.append(n) or ([], {"status": "ok", "features": 0}))))(attr))
    os.environ.update({"ANNOTATE_WITH_ABRICATE": "0", "ANNOTATE_WITH_ISESCAN": "off"})
    try:
        sys.argv = ["annotate_reference.py", "--reference", str(ref), "--out", str(tmp / "f2.tsv"), "--provenance", str(tmp / "p2.json"), "--threads", "4", "--cache-dir", ""]
        ar.main()
    finally:
        os.environ.pop("ANNOTATE_WITH_ABRICATE", None)
        os.environ.pop("ANNOTATE_WITH_ISESCAN", None)
    prov = json.loads((tmp / "p2.json").read_text(encoding="utf-8"))["callers"]
    check("a caller switched off is not run", "call_abricate" not in ran and "call_isescan" not in ran and "call_amrfinder" in ran and "call_barrnap" in ran, ran)
    check("... and is recorded as not evaluated, with the switch named (never as 'no feature found')",
          prov["abricate_amr"]["status"] == "not_evaluated" and "ANNOTATE_WITH_ABRICATE=0" in prov["abricate_amr"]["reason"]
          and prov["isescan"]["status"] == "not_evaluated" and prov["amrfinder"]["status"] == "ok", prov)
    check("callers_switched_off reads 0, no, off and false and ignores everything else", ar.callers_switched_off({"ANNOTATE_WITH_BARRNAP": "No", "ANNOTATE_WITH_MOB_TYPER": "1", "ANNOTATE_WITH_AMRFINDER": "false", "ANNOTATE_WITH_ABRICATE": "maybe"}) == ["amrfinder", "barrnap"])
    print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all parallel-annotation checks passed'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
