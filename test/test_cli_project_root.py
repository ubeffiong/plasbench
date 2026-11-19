#!/usr/bin/env python3
"""CLI commands that need pipeline files must fail early outside a release."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def main():
    with tempfile.TemporaryDirectory() as tmp:
        # A program installed away from any PlasBench folder, a home with no record and no ~/PlasBench: nothing can be found, so the command stops with a SHORT error that names the fixes.
        site = Path(tmp) / "site"
        site.mkdir()
        shutil.copytree(ROOT / "plasbench", site / "plasbench", ignore=shutil.ignore_patterns("__pycache__"))
        env = {**os.environ, "PYTHONPATH": str(site), "HOME": tmp, "USERPROFILE": tmp}
        env.pop("PLASBENCH_HOME", None)
        result = subprocess.run([sys.executable, "-m", "plasbench", "demo"], cwd=tmp, env=env, capture_output=True, text=True)
        assert result.returncode == 2, result
        assert "could not find the PlasBench folder" in result.stderr, result.stderr
        assert "--project-root" in result.stderr and "PLASBENCH_HOME" in result.stderr and "cd into" in result.stderr, result.stderr
        assert "{demo," not in result.stderr and "usage:" not in result.stderr, "the error must not dump the command list: " + result.stderr
    valid = subprocess.run([sys.executable, "-m", "plasbench", "--project-root", str(ROOT), "install-tools", "validate"],
                           cwd=ROOT, capture_output=True, text=True)
    assert valid.returncode == 0, valid.stderr
    print("CLI rejects an arbitrary working directory early and accepts an explicit project root -> PASS")
    print("ALL CLI PROJECT ROOT TESTS PASSED")


if __name__ == "__main__":
    main()
