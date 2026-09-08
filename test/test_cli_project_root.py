#!/usr/bin/env python3
"""CLI commands that need pipeline files must fail early outside a release."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def main():
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run([sys.executable, "-m", "plasbench", "demo"], cwd=tmp,
                                env={**os.environ, "PYTHONPATH": str(ROOT)}, capture_output=True, text=True)
        assert result.returncode == 2, result
        assert "not a PlasBench release/source directory" in result.stderr, result.stderr
        assert "--project-root" in result.stderr, result.stderr
    valid = subprocess.run([sys.executable, "-m", "plasbench", "--project-root", str(ROOT), "install-tools", "validate"],
                           cwd=ROOT, capture_output=True, text=True)
    assert valid.returncode == 0, valid.stderr
    print("CLI rejects an arbitrary working directory early and accepts an explicit project root -> PASS")
    print("ALL CLI PROJECT ROOT TESTS PASSED")


if __name__ == "__main__":
    main()
