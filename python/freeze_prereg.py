#!/usr/bin/env python3
"""
freeze_prereg.py -- freeze and verify the pre-registered scoring parameters.

config/prereg.tsv lists every scoring decision fixed before results are seen
(docs/PREREGISTRATION.md): parameter, value, config_variable, spec_section,
revise_after_pilot, status (fixed | TO_FIX), note.

  --write    hash prereg.tsv (SHA-256) and write config/prereg.lock.json with the
             hash, the UTC freeze time, and the parameters still TO_FIX.
  --verify   recompute the hash and compare it with the lock; exit 1 when the
             lock is missing or stale, or (with --require-fixed) when any
             parameter is still TO_FIX. With --check-env, also report every
             parameter whose config_variable is set to a different value in
             the environment (a run that silently departs from the plan).
  --status   print one JSON line (sha256, locked, matches, to_fix, env_mismatches)
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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TSV = ROOT / "config" / "prereg.tsv"
DEFAULT_LOCK = ROOT / "config" / "prereg.lock.json"
STATUSES = ("fixed", "TO_FIX")
UNSET = ("", "unset")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    for number, row in enumerate(rows, start=2):
        if not (row.get("parameter") or "").strip():
            raise ValueError(f"{path} row {number}: parameter is empty")
        if row.get("status") not in STATUSES:
            raise ValueError(f"{path} row {number}: status must be fixed or TO_FIX (got '{row.get('status')}')")
    names = [r["parameter"] for r in rows]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ValueError(f"{path}: duplicate parameter(s) {', '.join(duplicates)}")
    return rows


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
              "parameters": 0, "to_fix": [], "env_mismatches": [], "error": ""}
    try:
        rows = read_rows(tsv)
    except (OSError, ValueError) as exc:
        result["error"] = str(exc)
        return result
    result.update(sha256=sha256(tsv), parameters=len(rows),
                  to_fix=[r["parameter"] for r in rows if r["status"] == "TO_FIX"],
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
    ap.add_argument("--require-fixed", action="store_true", help="--verify fails while any row is TO_FIX")
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
    to_fix = [r["parameter"] for r in rows if r["status"] == "TO_FIX"]
    if args.write:
        lock = {"sha256": digest, "frozen_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                "prereg_file": os.path.relpath(args.prereg, ROOT) if Path(args.prereg).resolve().is_relative_to(ROOT)
                else args.prereg, "parameters": len(rows), "to_fix": to_fix}
        Path(args.lock).write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
        print(f"[freeze_prereg] froze {len(rows)} parameter(s), sha256 {digest[:12]}..., "
              f"{len(to_fix)} still TO_FIX -> {args.lock}")
        return
    problems = []
    if not Path(args.lock).is_file():
        problems.append(f"no lock at {args.lock}; run freeze_prereg.py --write")
    else:
        locked = json.loads(Path(args.lock).read_text(encoding="utf-8")).get("sha256")
        if locked != digest:
            problems.append(f"{args.prereg} changed after it was frozen (lock {str(locked)[:12]}..., now {digest[:12]}...)")
    if args.require_fixed and to_fix:
        problems.append("still TO_FIX: " + ", ".join(to_fix))
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
