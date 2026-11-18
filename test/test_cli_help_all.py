#!/usr/bin/env python3
"""`plasbench <command> --help` works for every command (and every global option).

argparse %-formats each help string, so a bare '%' ('about 15% of the cohort') makes `--help` crash with 'TypeError: %o format: an integer is
required, not dict'. `plasbench run --help` did exactly that, on every Python version, until the string said '15%%'. This formats the full help of the
top-level parser and of every subcommand in-process, which is where that error is raised.
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from plasbench.cli import build_parser  # noqa: E402

ok = True


def check(label, good, detail=""):
    global ok
    print(("  ok    " if good else "  FAIL  ") + label + ("" if good else f" -> {detail}"))
    ok = ok and bool(good)


parser = build_parser()
failures = []
count = 0


def walk(p, name):
    global count
    try:
        text = p.format_help()
        count += 1
        if not text.strip():
            failures.append((name, "empty help"))
    except Exception as exc:  # noqa: BLE001
        failures.append((name, f"{type(exc).__name__}: {exc}"))
    for action in p._actions:
        if isinstance(action, argparse._SubParsersAction):
            seen = set()
            for sub_name, sub in action.choices.items():
                if id(sub) in seen:        # aliases register the same parser twice
                    continue
                seen.add(id(sub))
                walk(sub, f"{name} {sub_name}".strip())


walk(parser, "plasbench")
check(f"the help of every command formats without an error ({count} parsers)", not failures, failures[:5])
check("there are many commands (the walk is not vacuous)", count > 40, count)
run_help = parser.parse_known_args(["run"])  # the parser itself still parses
text = next(sub for a in parser._actions if isinstance(a, argparse._SubParsersAction) for n, sub in a.choices.items() if n == "run").format_help()
check("`run --help` explains the two report flags in plain words", "never stop at the end of the run" in text.replace("\n", " ").lower().replace("  ", " ")
      or "without asking" in text.replace("\n", " "), text[-400:])

print("ALL CLI HELP TESTS PASSED" if ok else "CLI HELP TESTS FAILED")
sys.exit(0 if ok else 1)
