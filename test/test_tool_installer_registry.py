#!/usr/bin/env python3
"""Registry must cover every real adapter and expose planned installs honestly."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "python" / "tool_installer_registry.py"


def main():
    checked = subprocess.run([sys.executable, str(SCRIPT), "validate"], cwd=ROOT, capture_output=True, text=True)
    assert checked.returncode == 0, checked.stderr
    listed = subprocess.run([sys.executable, str(SCRIPT), "list"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    assert "mob_recon" in listed and "plasgraph2" in listed and "\tplanned\t" in listed
    print("all real adapter capabilities are covered and planned runtimes remain explicit -> PASS")
    print("ALL TOOL INSTALLER REGISTRY TESTS PASSED")


if __name__ == "__main__": main()
