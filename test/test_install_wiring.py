#!/usr/bin/env python3
"""Every external tool the code calls is wired into the install pipeline, and the routes agree.

A tool can be used in code yet missing from the installer (samtools and mash were in the
environment file and the lock but in no install profile and no setup check; barrnap was in the
environment file but not the lock). This test makes that drift fail:

  1. Every external binary named in the code (shutil.which("x"), `need x`, `command -v x`) is in
     the table below, so a NEW tool cannot be added without deciding how it is installed.
  2. For each tool in the table the declared routes exist: the conda environment file, the lock,
     an install_tools.sh profile, and a scripts/00_setup.sh check.
  3. The routes agree with each other: every profile that 00_setup.sh or the `all` loop names exists.
  4. INSTALL.md documents the profiles that install the shared utilities and annotation callers.

KNOWN_GAPS lists a gap that cannot be closed in software here (the lock must be regenerated with
conda, which is not available on every machine). It is strict: when the gap is closed the test
fails until the entry is removed, so the list cannot go stale.
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


# Tools the operating system provides; not installed by PlasBench.
SYSTEM = {"python3", "bash", "git", "gzip", "tar", "curl", "sha256sum", "wslview", "wslpath", "timeout"}

# binary -> (conda package, routes that must exist). env = environment.yml, lock = the conda lock,
# profile = an env/install_tools.sh profile installs it, check = scripts/00_setup.sh checks it.
ALL4 = {"env", "lock", "profile", "check"}
TABLE = {
    "minimap2": ("minimap2", ALL4),
    "samtools": ("samtools", ALL4),
    "mash": ("mash", ALL4),
    "barrnap": ("barrnap", ALL4),
    "abricate": ("abricate", {"profile", "check"}),
    "amrfinder": ("ncbi-amrfinderplus", {"profile", "check"}),
    "isescan.py": ("isescan", {"profile", "check"}),
    "isescan": ("isescan", {"profile"}),
    # mob_suite has its own pinned environment (env/install_tools.sh mobsuite), never environment.yml.
    "mob_typer": ("mob_suite", {"profile", "check"}),
    "mob_recon": ("mob_suite", {"profile"}),
    "spades.py": ("spades", {"env", "profile", "check"}),
    "unicycler": ("unicycler", {"env", "profile", "check"}),
    "fastp": ("fastp", {"env", "profile", "check"}),
    "datasets": ("ncbi-datasets-cli", {"env", "profile", "check"}),
    "prefetch": ("sra-tools", {"env", "profile", "check"}),
    "fasterq-dump": ("sra-tools", {"env", "profile", "check"}),
    "quast.py": ("quast", {"profile", "check"}),
    "genomad": ("genomad", {"profile"}),
    "flye": ("flye", {"profile"}),
    "trycycler": ("trycycler", {"profile"}),
    "medaka_consensus": ("medaka", {"profile"}),
    "plassembler": ("plassembler", {"profile"}),
    "hybracter": ("hybracter", {"profile"}),
    "iss": ("insilicoseq", {"profile"}),
    "badread": ("badread", {"profile"}),
}
# Used by code but deliberately not installed through PlasBench. Each says why.
MANUAL = {
    "deadends": "no bioconda package; INSTALL.md documents the manual build",
    "blastn": "only the one-off compare_scoring_methods.py cross-check uses it, and it states its own requirement",
    "timeout": "GNU coreutils; scripts/04_run_tools.sh uses it only when TOOL_TIMEOUT_SECONDS is set and checks for it first",
    "aria2c": "optional accelerator; fetch_ena_reads.py uses it only when it is on PATH (shutil.which) and otherwise "
              "downloads byte ranges itself, so nothing needs installing",
}
# Gaps that cannot be closed in software here. Strict: remove the entry when the gap is fixed.
KNOWN_GAPS = {
    ("barrnap", "lock"): "barrnap is in env/environment.yml but not env/environment.lock.yml; regenerate the "
                         "lock with env/lock_environment.sh on a machine with conda",
}


def environment_packages():
    names = set()
    for line in read("env", "environment.yml").splitlines():
        match = re.match(r"\s*-\s*([A-Za-z0-9_.+-]+)", line.split("#")[0])
        if match:
            names.add(match.group(1))
    return names


def lock_packages():
    names = set()
    for line in read("env", "environment.lock.yml").splitlines():
        if line.startswith("https://"):
            file_name = line.split("#")[0].rsplit("/", 1)[-1]
            file_name = re.sub(r"\.(conda|tar\.bz2)$", "", file_name)
            names.add(file_name.rsplit("-", 2)[0])
    return names


def profiles():
    """profile label -> set of conda packages its PKGS=(...) installs; plus the `all` loop members."""
    text = read("env", "install_tools.sh")
    install_block = text.split('case "$PROFILE" in', 2)[-1]
    labels, current = {}, None
    for line in install_block.splitlines():
        label = re.match(r"^ ?([a-z0-9][a-z0-9-]*)\)", line)
        if label:
            current = label.group(1)
            labels.setdefault(current, set())
        for packages in re.findall(r"PKGS=\(([^)]*)\)", line):
            if current:
                labels[current].update(packages.split())
    loop = re.search(r"for installed_profile in ([^;]+);", text)
    return labels, (loop.group(1).split() if loop else [])


def setup_checks():
    checks = {}
    for binary, profile in re.findall(r'^\s*check_tool\s+(\S+)\s+("[^"]*"|\S+)', read("scripts", "00_setup.sh"), re.M):
        checks[binary] = profile.strip('"')
    return checks


def code_tools():
    found = set()
    for path in glob.glob(os.path.join(ROOT, "python", "*.py")) + glob.glob(os.path.join(ROOT, "plasbench", "*.py")):
        with open(path, encoding="utf-8") as handle:
            found.update(re.findall(r'shutil\.which\("([^"]+)"\)', handle.read()))
    for path in glob.glob(os.path.join(ROOT, "scripts", "*.sh")) + glob.glob(os.path.join(ROOT, "adapters", "*.sh")):
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                code = line.split("#")[0]
                found.update(re.findall(r"^\s*need\s+([A-Za-z0-9_.-]+)\s*$", code))
                found.update(re.findall(r"command -v ([A-Za-z0-9_.-]+)", code))
    return found


def main():
    ok = True

    def check(label, good, detail=""):
        nonlocal ok
        print(f"  {label}: {'PASS' if good else 'FAIL'}{(' ' + detail) if (detail and not good) else ''}")
        ok &= bool(good)

    env, lock = environment_packages(), lock_packages()
    labels, all_loop = profiles()
    installed_by_profile = set().union(*labels.values()) if labels else set()
    checks = setup_checks()
    install_doc = read("INSTALL.md")

    # 1. no external tool in the code is left undeclared
    accounted = set(TABLE) | SYSTEM | set(MANUAL)
    undeclared = sorted(code_tools() - accounted)
    check("every external binary the code calls is accounted for in this table", not undeclared,
          f"-> undeclared: {undeclared}. Decide how each is installed (env/install_tools.sh profile, "
          "scripts/00_setup.sh check, INSTALL.md) and add it to TABLE or MANUAL.")

    # 2. the declared routes exist
    gaps_seen = set()
    for binary, (package, routes) in sorted(TABLE.items()):
        present = {"env": package in env, "lock": package in lock,
                   "profile": package in installed_by_profile, "check": binary in checks}
        for route in sorted(routes):
            if present[route]:
                continue
            if (binary, route) in KNOWN_GAPS:
                gaps_seen.add((binary, route))
                continue
            check(f"{binary} ({package}) is declared in the {route} route", False,
                  f"-> missing from {route}")
    check("no unexpected missing route for any tool", True)
    for key in sorted(KNOWN_GAPS):
        check(f"known gap {key} still exists (remove it from KNOWN_GAPS once fixed)", key in gaps_seen,
              f"-> this gap is now closed: delete {key} from KNOWN_GAPS. {KNOWN_GAPS[key]}")

    # 3. the routes agree with each other
    referenced = {profile for profile in checks.values() if profile}
    missing_profiles = sorted(referenced - set(labels))
    check("every profile named by a 00_setup.sh check exists in install_tools.sh", not missing_profiles,
          f"-> {missing_profiles}")
    bad_loop = sorted(set(all_loop) - set(labels))
    check("every profile in the `all` loop exists", not bad_loop, f"-> {bad_loop}")
    for profile in ("utilities", "reference-annotation"):
        check(f"the `{profile}` profile is part of `all`", profile in all_loop)
    check("`utilities` installs mash, samtools and barrnap", {"mash", "samtools", "barrnap"} <= labels.get("utilities", set()))
    check("`reference-annotation` installs the annotation callers",
          {"abricate", "ncbi-amrfinderplus", "isescan", "mob_suite"} <= labels.get("reference-annotation", set()))
    check("mash is checked outside the opt-in difficulty block (it silently changes clonal grouping)",
          "mash" in checks and checks["mash"] == "utilities")
    check("the false 'samtools is checked elsewhere' comment is gone",
          "minimap2/samtools are unconditionally required elsewhere" not in read("scripts", "00_setup.sh"))

    # 4. the docs say how to install them
    for needle in ("plasbench install-tools utilities", "plasbench install-tools reference-annotation", "amrfinder -u",
                   "`barrnap`", "`mash`"):
        check(f"INSTALL.md documents {needle}", needle in install_doc)
    check("INSTALL.md still documents the manual deadends build", "deadends" in install_doc and "cargo build" in install_doc)
    print("ALL INSTALL WIRING TESTS PASSED" if ok else "INSTALL WIRING TESTS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
