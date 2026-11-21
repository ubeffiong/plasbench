#!/usr/bin/env python3
"""Say WHY a package install failed when the cause is a read-only environment, in the style of assembler_diagnosis.py.

Inside the PlasBench container the image's conda environments (/opt/conda/envs/*) are read-only for the user the container runs as; PlasBench installs extras into
the persistent extras folder (PLASBENCH_EXTRA_HOME). If an install still tries to write there, the solver's output says "Permission denied" / "Could not open
lockfile"; this names the cause, the path it tried to write and the fix.

  python3 -I python/install_diagnosis.py LOGFILE [--extras PATH]      prints the diagnosis (exit 1 when it is a read-only failure, 0 when not)

`diagnose(text, extras="", in_container=None)` returns None or {cause: "read_only_environment", path, title, advice}. Standard library only; Python 3.9 compatible.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

PATTERNS = [
    r"could not open lockfile '(?P<p1>[^']+)'",
    r"permission denied[^\n]*?['\"](?P<p2>/[^'\"\n]+)['\"]",
    r"cannot move '(?P<p3>[^']+)'[^\n]*permission denied",
    r"trying to remove ['\"](?P<p4>[^'\"\n]+)['\"][^\n]*permission denied",
    r"(?P<p5>/[^\s:'\"]+)[^\n]*permission denied",
    r"permission denied",
]


def in_container(environ=None, exists=os.path.exists) -> bool:
    environ = os.environ if environ is None else environ
    return str(environ.get("PLASBENCH_IN_DOCKER", "")).strip() == "1" or exists("/.dockerenv") or exists("/run/.containerenv")


def diagnose(text: str, extras: str = "", container=None, environ=None):
    container = in_container(environ) if container is None else container
    for pattern in PATTERNS:
        m = re.search(pattern, text or "", re.I)
        if not m:
            continue
        path = next((v for v in m.groupdict().values() if v), "")
        where = extras or "~/.plasbench/docker/<version>/extras"
        if container:
            title = "the image's conda environment is read-only"
            advice = (f"PlasBench installs extras into {where} (a folder on the host that is mounted into every container); this install tried to write to "
                      f"{path or 'the image environment'}. Update PlasBench and the image (plasbench runtime check), then run the install again. Nothing in the image was changed.")
        else:
            title = "the environment is read-only for your user"
            advice = (f"The install tried to write to {path or 'an environment you do not own'}. Use an environment you own (bash env/setup_conda.sh), "
                      "or ask whoever owns this one to install the tool.")
        return {"cause": "read_only_environment", "path": path, "title": title, "advice": advice}
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("logfile")
    ap.add_argument("--extras", default=os.environ.get("PLASBENCH_EXTRA_HOME", ""))
    args = ap.parse_args(argv)
    try:
        text = open(args.logfile, encoding="utf-8", errors="replace").read()
    except OSError as exc:
        print(f"ERROR: cannot read {args.logfile}: {exc}", file=sys.stderr)
        return 2
    found = diagnose(text, args.extras)
    if not found:
        return 0
    print(f"ERROR: {found['title']}. {found['advice']}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
