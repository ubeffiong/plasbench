#!/usr/bin/env python3
"""Warnings are yellow and errors red: in the window's console (Job output, Session log, Terminal) and in a terminal.

- the window's line classifier, run with node when it is installed, on real log lines (including a tolerated
  "WARNING: SPAdes failed", success lines that mention a failure, and zero counts)
- scripts/lib.sh colours warn/die only for a terminal, never in a log file, and honours NO_COLOR and PLASBENCH_COLOR
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


CASES = [
    ("[2026-11-14 21:40:00] WARNING: SPAdes failed for acinetobacter_baumannii_008; excluded from tool runs", "warn"),
    ("[2026-11-14 21:40:00] ERROR: truth table for s2 is not usable; fix it and re-run", "err"),
    ("Traceback (most recent call last):", "err"),
    ("FileNotFoundError: [Errno 2] No such file or directory: '/data'", "err"),
    ("spades.py: No space left on device", "err"),
    ("bash: line 1: plasbench: command not found", "err"),
    ("[exit 127]", "err"),
    ("mob_recon: skipped for S1 (command unavailable)", "warn"),
    ("cancelled by you", "warn"),
    ("MAX_PARALLEL_SAMPLES=1 tolerates one failed sample and still assembles its siblings -> PASS", "ok"),
    ("  ok    a failed multi-line command is commented out on every line", "ok"),
    (" 1. tool_a   score=0.800 (scored=1, completed=0, failed=0, skipped=0)", ""),
    ("[2026-11-14 21:36:10]   fastp trimming (escherichia_coli_017) ...", ""),
    ("truth table verified for escherichia_coli_036: 7 sequence(s), 6 plasmid, 1 chromosome", ""),
]


def main():
    page = (ROOT / "plasbench" / "data" / "ui.html").read_text(encoding="utf-8")
    check("errors are red and warnings amber in the console palette (tokens; test_terminal_colour.py checks their contrast)",
          ".tcbox:not([data-tc=off]) .ln.lv-err{color:var(--tc-err)" in page and ".tcbox[data-tc=full] .ln.lv-warn{color:var(--tc-warn)}" in page)
    check("the Terminal tab colours command output", 'tcRender(out + "\\n", b)' in page)
    check("the page has no stray control characters", not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", page))
    node = shutil.which("node")
    if node:
        heads = [l for l in page.split("\n") if l.startswith(("const RX_OK", "const RX_ERR", "const RX_WARN", "const RX_TAG"))]
        body = page[page.index("function lineLevel(l) {"):]
        body = body[:body.index("\n}\n") + 3]
        js = "\n".join(heads) + "\n" + body + f"\nconsole.log(JSON.stringify({json.dumps([c for c, _ in CASES])}.map(lineLevel)));\n"
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as h:
            h.write(js)
        out = subprocess.run([node, h.name], capture_output=True, text=True)
        os.unlink(h.name)
        got = json.loads(out.stdout) if out.returncode == 0 else []
        wrong = [(c[:60], want, g) for (c, want), g in zip(CASES, got) if want != g]
        check("each real log line gets the right colour", got and not wrong, wrong or out.stderr[-300:])
    else:
        print("  skip  node not installed: line classifier not run")

    bash = shutil.which("bash")
    if bash:
        lib = (ROOT / "scripts" / "lib.sh").as_posix()

        def run(env_extra):
            env = {k: v for k, v in os.environ.items() if k not in ("NO_COLOR", "PLASBENCH_COLOR")}
            env.update(env_extra)
            p = subprocess.run([bash, "-c", f'source "{lib}"; warn "w"; (die "e")'], capture_output=True, env=env)
            return p.stderr.decode()
        forced = run({"PLASBENCH_COLOR": "always"})
        check("a warning prints yellow and an error red in a terminal",
              "\x1b[33m" in forced and "WARNING: w" in forced and "\x1b[1;31m" in forced and "ERROR: e" in forced, repr(forced))
        check("nothing is coloured in a log file (not a terminal)", "\x1b[" not in run({}), repr(run({})))
        check("PLASBENCH_COLOR=never turns it off", "\x1b[" not in run({"PLASBENCH_COLOR": "never"}))
    print(f"\n{'FAILED: ' + ', '.join(FAILED) if FAILED else 'all console-colour checks passed'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
