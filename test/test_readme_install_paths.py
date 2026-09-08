#!/usr/bin/env python3
"""Keep the primary README install route independent of unpublished versions."""
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def main():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    primary = readme.split("#### Alternative: choose or inspect a specific release version", 1)[0]
    assert "scripts/install_latest.sh" in primary
    assert "releases/download/v0.2.6" not in primary
    assert 'PB="/path/printed/by-install_latest.sh"' in readme
    # Historical releases may be mentioned in release notes, but operational
    # commands must not direct a user to a frozen versioned install path.
    assert "cd ~/plasbench-0.2.6" not in readme
    assert "cd ~/plasbench-0.2.3" not in readme
    print("README primary installation path resolves the published release and uses an explicit install directory -> PASS")
    print("ALL README INSTALL PATH TESTS PASSED")


if __name__ == "__main__":
    main()
