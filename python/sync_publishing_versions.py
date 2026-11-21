#!/usr/bin/env python3
"""Bring the version written in the publishing files up to the version in pyproject.toml (run it in the version-bump commit of a release).

  python3 python/sync_publishing_versions.py            rewrites docs/publishing/biotools.json and workflows/cwl/*.cwl
  python3 python/sync_publishing_versions.py --check    exits 1 when a file names another version (test/test_publishing.py checks the same things)

What it does NOT do: the Bioconda recipe's SHA-256 (it can only be known after the release archive exists: put the value from plasbench-<version>.tar.gz.sha256 into
recipes/bioconda/meta.yaml once the release is published) and the Galaxy wrappers' version token (galaxy/macros.xml, bumped by hand and kept by test_doc_versions.py).
Standard library only."""
from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def version() -> str:
    return re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M).group(1)


def rewrite(text: str, old: str, new: str, kind: str) -> str:
    if kind == "json":
        return text.replace(f'"version": ["{old}"]', f'"version": ["{new}"]').replace(f"/v{old}", f"/v{new}").replace(f"plasbench-{old}.tar.gz", f"plasbench-{new}.tar.gz") \
                   .replace(f'"version": "{old}"', f'"version": "{new}"').replace(f"plasbench:v{old}", f"plasbench:v{new}")
    return text.replace(f"plasbench:v{old}", f"plasbench:v{new}").replace(f'version: ["{old}"]', f'version: ["{new}"]')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    new = version()
    targets = [(ROOT / "docs" / "publishing" / "biotools.json", "json")] + [(p, "cwl") for p in sorted((ROOT / "workflows" / "cwl").glob("*.cwl"))]
    stale = []
    for path, kind in targets:
        text = io.open(path, encoding="utf-8", newline="").read()
        found = set(re.findall(r"plasbench:v(\d+\.\d+\.\d+)", text)) | (set(re.findall(r'"version": \["([^"]+)"\]', text)) if kind == "json" else set())
        for old in sorted(found - {new}):
            if args.check:
                stale.append(f"{path.relative_to(ROOT)} names {old}, not {new}")
            else:
                text = rewrite(text, old, new, kind)
        if not args.check:
            io.open(path, "w", encoding="utf-8", newline="").write(text)
    for line in stale:
        print(line, file=sys.stderr)
    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
