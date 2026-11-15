#!/usr/bin/env python3
"""
freeze_prereg.py -- freeze and verify the pre-registered scoring parameters.

config/prereg.tsv lists every scoring decision fixed before results are seen
(docs/PREREGISTRATION.md): parameter, value, config_variable, spec_section,
revise_after_pilot, status (fixed | proposed | TO_FIX), note.

Status vocabulary: `fixed` (decided), `proposed` (a value is proposed, with its rationale in the note, and awaits the maintainer's confirmation) and `TO_FIX`
(no value yet). Proposed and TO_FIX rows are UNFIXED: a plan with any unfixed row is a DRAFT.

  --write    hash prereg.tsv (SHA-256) and write config/prereg.lock.json with the
             hash, the UTC freeze time, and the parameters still proposed or TO_FIX.
             A draft may be locked (so a run records which draft it used); --strict refuses
             to write the lock while any row is unfixed (the real freeze, after confirmation).
  --verify   recompute the hash and compare it with the lock; exit 1 when the
             lock is missing or stale, or (with --require-fixed or --strict) when any
             parameter is still proposed or TO_FIX. With --check-env, also report every
             parameter whose config_variable is set to a different value in
             the environment (a run that silently departs from the plan).
  --status   print one JSON line (sha256, locked, matches, to_fix, proposed, draft, env_mismatches)
             for the manifest and the HTML report; never fails.

04_run_tools.sh runs --verify --require-fixed --check-env before any tool when
REQUIRE_PREREG=1. Standard library only.
"""

import argparse
import csv
import datetime
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TSV = ROOT / "config" / "prereg.tsv"
DEFAULT_LOCK = ROOT / "config" / "prereg.lock.json"
STATUSES = ("fixed", "proposed", "TO_FIX")
UNSET = ("", "unset")


from plasbench_common import sha256  # noqa: E402,F401


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    for number, row in enumerate(rows, start=2):
        if not (row.get("parameter") or "").strip():
            raise ValueError(f"{path} row {number}: parameter is empty")
        if row.get("status") not in STATUSES:
            raise ValueError(f"{path} row {number}: status must be fixed, proposed or TO_FIX (got '{row.get('status')}')")
    names = [r["parameter"] for r in rows]
    duplicates = sorted(n for n, seen in Counter(names).items() if seen > 1)   # one counting pass
    if duplicates:
        raise ValueError(f"{path}: duplicate parameter(s) {', '.join(duplicates)}")
    return rows


def unfixed(rows):
    """(proposed, to_fix) parameter names: the rows that make the plan a draft."""
    return ([r["parameter"] for r in rows if r["status"] == "proposed"], [r["parameter"] for r in rows if r["status"] == "TO_FIX"])


def env_mismatches(rows, environ=None):
    environ = os.environ if environ is None else environ
    out = []
    for row in rows:
        var = (row.get("config_variable") or "").strip()
        if not var or var not in environ:
            continue
        planned, actual = (row.get("value") or "").strip(), environ[var].strip()
        if planned in UNSET and actual in UNSET:
            continue
        try:
            same = float(planned) == float(actual)
        except ValueError:
            same = planned == actual
        if not same:
            out.append({"parameter": row["parameter"], "config_variable": var, "planned": planned, "actual": actual})
    return out


def status(tsv, lock, environ=None):
    result = {"prereg_file": str(tsv), "sha256": "", "locked": False, "matches": False, "frozen_at": "",
              "parameters": 0, "to_fix": [], "proposed": [], "draft": False, "env_mismatches": [], "error": ""}
    try:
        rows = read_rows(tsv)
    except (OSError, ValueError) as exc:
        result["error"] = str(exc)
        return result
    proposed, to_fix = unfixed(rows)
    result.update(sha256=sha256(tsv), parameters=len(rows), to_fix=to_fix, proposed=proposed, draft=bool(proposed or to_fix),
                  env_mismatches=env_mismatches(rows, environ))
    if Path(lock).is_file():
        try:
            data = json.loads(Path(lock).read_text(encoding="utf-8"))
        except ValueError as exc:
            result["error"] = f"unreadable lock: {exc}"
            return result
        result.update(locked=True, frozen_at=data.get("frozen_at", ""), matches=data.get("sha256") == result["sha256"])
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--status", action="store_true")
    ap.add_argument("--prereg", default=str(DEFAULT_TSV))
    ap.add_argument("--lock", default=str(DEFAULT_LOCK))
    ap.add_argument("--require-fixed", action="store_true", help="--verify fails while any row is proposed or TO_FIX")
    ap.add_argument("--strict", action="store_true", help="--write refuses, and --verify fails, while any row is proposed or TO_FIX (a draft cannot be frozen as final)")
    ap.add_argument("--check-env", action="store_true", help="--verify fails when a config variable departs from the plan")
    args = ap.parse_args()

    if args.status:
        print(json.dumps(status(args.prereg, args.lock)))
        return
    try:
        rows = read_rows(args.prereg)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"ERROR: {exc}")
    digest = sha256(args.prereg)
    proposed, to_fix = unfixed(rows)
    open_rows = proposed + to_fix
    if args.write and args.strict and open_rows:
        raise SystemExit("ERROR: --strict: the plan is still a draft (" + str(len(open_rows)) + " row(s) proposed or TO_FIX: " + ", ".join(open_rows[:8])
                         + (" ..." if len(open_rows) > 8 else "") + "). Confirm each value in config/prereg.tsv (status fixed), then freeze.")
    if args.write:
        lock = {"sha256": digest, "frozen_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                "prereg_file": os.path.relpath(args.prereg, ROOT) if Path(args.prereg).resolve().is_relative_to(ROOT)
                else args.prereg, "parameters": len(rows), "to_fix": to_fix, "proposed": proposed, "draft": bool(open_rows)}
        Path(args.lock).write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
        print(f"[freeze_prereg] froze {len(rows)} parameter(s), sha256 {digest[:12]}..., "
              f"{len(proposed)} proposed and {len(to_fix)} TO_FIX -> {args.lock}"
              + (" (a DRAFT freeze: confirm the open rows, then freeze with --strict)" if open_rows else ""))
        return
    problems = []
    if not Path(args.lock).is_file():
        problems.append(f"no lock at {args.lock}; run freeze_prereg.py --write")
    else:
        locked = json.loads(Path(args.lock).read_text(encoding="utf-8")).get("sha256")
        if locked != digest:
            problems.append(f"{args.prereg} changed after it was frozen (lock {str(locked)[:12]}..., now {digest[:12]}...)")
    if (args.require_fixed or args.strict) and open_rows:
        problems.append("still proposed or TO_FIX (the plan is a draft): " + ", ".join(open_rows))
    if args.check_env:
        for m in env_mismatches(rows):
            problems.append(f"{m['config_variable']}={m['actual']} departs from the pre-registered "
                            f"{m['parameter']}={m['planned']}")
    if problems:
        for problem in problems:
            sys.stderr.write(f"[freeze_prereg] {problem}\n")
        raise SystemExit(1)
    print(f"[freeze_prereg] pre-registration verified: sha256 {digest[:12]}..., {len(rows)} parameter(s)")


if __name__ == "__main__":
    main()
