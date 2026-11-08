#!/usr/bin/env python3
"""Every row of the evidence ledger in docs/INDEPENDENT_REVIEW.md still points at real code.

Each row names `path:line` and a symbol; the symbol must appear on that line, so a moved or
renamed line fails here instead of leaving the review citing the wrong code.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROW = re.compile(r"^\| (E\d+) \| .*? \| `([^`:]+):(\d+)` \| `([^`]+)` \|\s*$")


def main():
    with open(os.path.join(ROOT, "docs", "INDEPENDENT_REVIEW.md"), encoding="utf-8") as handle:
        rows = [ROW.match(line) for line in handle]
    rows = [match for match in rows if match]
    ok = len(rows) >= 40
    print(f"  ledger has {len(rows)} rows: {'PASS' if ok else 'FAIL'}")
    for match in rows:
        ident, path, number, symbol = match.groups()
        full = os.path.join(ROOT, path)
        if not os.path.isfile(full):
            print(f"  {ident}: FAIL missing file {path}")
            ok = False
            continue
        with open(full, encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
        index = int(number)
        good = index <= len(lines) and symbol in lines[index - 1]
        if not good:
            found = [n for n, text in enumerate(lines, 1) if symbol in text][:3]
            print(f"  {ident}: FAIL {path}:{number} lacks `{symbol}` (found at {found})")
            ok = False
    print("ALL REVIEW LEDGER TESTS PASSED" if ok else "REVIEW LEDGER TESTS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
