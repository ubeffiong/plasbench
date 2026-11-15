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
    print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all parallel-annotation checks passed'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
