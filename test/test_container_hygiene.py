#!/usr/bin/env python3
"""Guard against accidentally copying local credentials into a container image."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    patterns = {
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    required = {".ncbi.env", ".env", ".env.*", "*.pem", "*.key"}
    missing = sorted(required - patterns)
    assert not missing, f".dockerignore must exclude credentials: {', '.join(missing)}"
    print("ALL CONTAINER HYGIENE TESTS PASSED")


if __name__ == "__main__":
    main()
