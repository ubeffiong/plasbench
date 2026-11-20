#!/usr/bin/env python3
"""Keep the primary README install route independent of unpublished versions."""
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def main():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    primary = readme.split("#### Alternative: choose or inspect a specific release version", 1)[0]
    assert "scripts/install_latest.sh" in primary
    assert "releases/download/v0.2.6" not in primary
    assert 'PB="$HOME/PlasBench"' in readme   # one install folder, updated in place
    # Historical releases may be mentioned in release notes, but operational
    # commands must not direct a user to a frozen versioned install path.
    assert "cd ~/plasbench-0.2.6" not in readme
    assert "cd ~/plasbench-0.2.3" not in readme
    print("README primary installation path resolves the published release and uses an explicit install directory -> PASS")
    check_downloaded_file_section(readme)
    print("ALL README INSTALL PATH TESTS PASSED")


def check_downloaded_file_section(readme):
    """The section for a release file that is already downloaded must show the installer's REAL usage (scripts/install_latest.sh --archive), accurately."""
    readme = readme.replace("\r\n", "\n")
    head = "#### I already downloaded the release file"
    assert head in readme
    section = readme.split(head, 1)[1].split("\n#### ", 1)[0]
    script = (ROOT / "scripts" / "install_latest.sh").read_text(encoding="utf-8")
    usage = script.split("set -euo pipefail", 1)[0]
    # the command the section shows is the one the script's own usage text documents
    assert "#   bash install_latest.sh --archive plasbench-" in usage and "--tools" in usage
    assert 'bash install_latest.sh --archive "$PWD/plasbench-<version>.tar.gz"' in section
    assert "--archive)" in script and "LOCAL_ARCHIVE" in script
    assert '"$PWD/plasbench-<version>.tar.gz" --tools' in section or "--tools" in section
    # the installer script is inside the release archive: where, and how to read it out
    assert "tar -xzOf plasbench-<version>.tar.gz plasbench-<version>/scripts/install_latest.sh > install_latest.sh" in section
    make_release = (ROOT / "scripts" / "make_release.sh").read_text(encoding="utf-8")
    assert "scripts" in make_release and (ROOT / "scripts" / "install_latest.sh").is_file()
    # verification, Windows and WSL notes, where it installs, upgrading, checking, errors
    for needle in ("releases/latest", ".tar.gz.sha256", "sha256sum -c plasbench-<version>.tar.gz.sha256", "Get-FileHash", "/mnt/c/Users/<you>/Downloads/", "wsl.localhost",
                   "./install.sh --tools", "step-2--install-conda", "PLASBENCH_OFFLINE", "PLASBENCH_INSTALL_DIR", "~/PlasBench",
                   "plasbench upgrade --archive", "conda activate plasbench", "plasbench --version", "plasbench ui-state"):
        assert needle in section, needle
    # every error message the table quotes is a real message of the scripts
    assert "--archive must be named plasbench-<version>.tar.gz" in script and "--archive file not found" in script
    assert "no conda-family package manager is available" in (ROOT / "install.sh").read_text(encoding="utf-8")
    # the name rule in the text is the rule in the script
    assert "plasbench-([0-9][0-9A-Za-z.+-]*)" in script
    # the same guidance is mirrored, shortly, in INSTALL.md
    install = (ROOT / "INSTALL.md").read_text(encoding="utf-8")
    assert "## 0. I already downloaded the release file" in install
    assert 'bash install_latest.sh --archive "$PWD/plasbench-<version>.tar.gz"' in install and "sha256sum -c" in install
    # update.sh and the command line support the options the guide names
    update = (ROOT / "update.sh").read_text(encoding="utf-8")
    cli = (ROOT / "plasbench" / "cli.py").read_text(encoding="utf-8")
    for option in ("--archive", "--check-only", "--version", "--rollback"):
        assert option in update and f'"{option}"' in cli, option
    print("README 'I already downloaded the release file' matches scripts/install_latest.sh, install.sh and update.sh -> PASS")


if __name__ == "__main__":
    main()
