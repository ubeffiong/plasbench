#!/usr/bin/env python3
"""One authoritative version (second review, section 13A).

pyproject.toml is the source. The package, the citation file and the Scientific Guide must carry the same version, and the
changelog must have an entry for it, so a guide that still says 0.1.5 while describing a later implementation cannot ship again.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAILED = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}: {name}" + (f" ({detail})" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


def main():
    version = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M).group(1)
    print(f"pyproject.toml says {version}")
    init = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "plasbench" / "__init__.py").read_text(encoding="utf-8")).group(1)
    check("plasbench/__init__.py", init == version, init)
    citation = re.search(r'^version:\s*"?([^"\n]+)"?', (ROOT / "CITATION.cff").read_text(encoding="utf-8"), re.M).group(1)
    check("CITATION.cff", citation == version, citation)
    guide = re.search(r"describes PlasBench at version ([0-9][0-9.]*[0-9])", (ROOT / "docs" / "SCIENTIFIC_GUIDE.md").read_text(encoding="utf-8"))
    check("the Scientific Guide names the same version", guide is not None and guide.group(1) == version, guide.group(1) if guide else "no version sentence")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    check("the changelog has an entry for it", f"## [{version}]" in changelog)
    print("ALL DOC VERSION TESTS PASSED" if not FAILED else f"DOC VERSION TESTS FAILED: {FAILED}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
