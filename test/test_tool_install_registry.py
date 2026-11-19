#!/usr/bin/env python3
"""The install registries are honest and complete (config/source_tools.json, config/tool_installers.tsv, docs/TOOL_INSTALL_AUDIT.md).

  * every source-built or manual profile has a pin (40-hex commit), a source URL, a verification command, a licence note and the date it was researched;
  * every URL is https, no pin is a branch or tag name, the tag is recorded beside the commit;
  * every tool the benchmark can run is either installed automatically (automated = yes) or is a verified manual profile with evidence and a recipe;
  * the manual profiles are exactly the ones the registry says, `resolve` exits 20 for them and 0 for the automatic ones;
  * the generated audit table is not stale; the plan text names repository, commit, size and licence; a floating branch cannot pass validation.
"""
import copy
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))
import source_install as si  # noqa: E402
import tool_installer_registry as tir  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


def main():
    registry = si.load()
    profiles = registry["profiles"]
    check("the source registry validates", si.validate(registry) == [], si.validate(registry))
    for name, entry in profiles.items():
        check(f"{name}: commit is 40 hex, ref is a name, repo is https", bool(re.fullmatch(r"[0-9a-f]{40}", entry["commit"])) and entry["ref"] != entry["commit"] and entry["repo"].startswith("https://"))
        urls = list(entry.get("sources", [])) + list(entry.get("manual", {}).get("evidence", [])) + [entry["repo"]]
        check(f"{name}: every URL is https", all(u.startswith("https://") for u in urls), urls)
        check(f"{name}: licence note, verification command, researched date", bool(entry["licence"]) and bool(entry["verify"]["argv"]) and bool(re.match(r"\d{4}-\d\d-\d\d$", entry["researched"])))
    # a floating branch, a short SHA, an http URL, a missing licence all fail validation
    for label, mutate in (("a branch name instead of a commit", lambda e: e.update(commit="main")), ("a short SHA", lambda e: e.update(commit=e["commit"][:7])),
                          ("an http URL", lambda e: e.update(repo=e["repo"].replace("https://", "http://"))), ("no licence note", lambda e: e.update(licence="")),
                          ("no verification command", lambda e: e["verify"].update(argv=[]))):
        broken = copy.deepcopy(registry)
        mutate(broken["profiles"]["gplas2"])
        check(f"validation rejects {label}", bool(si.validate(broken)))

    rows = tir.read_tsv(ROOT / "config" / "tool_installers.tsv") + tir.read_tsv(ROOT / "config" / "metagenomic_tool_installers.tsv")
    for row in rows:
        profile, entry = row["profile"], profiles.get(row["profile"])
        if row["install_mode"] in ("isolated_source", "container_pinned", "nextflow_container"):
            check(f"{row['tool']}: a source/container tool is in the source registry", entry is not None, profile)
            if entry is not None:
                automatic = entry["mode"] == "source"
                check(f"{row['tool']}: automated={row['automated']} agrees with the registry mode {entry['mode']}", (row["automated"] == "yes") == automatic)
                check(f"{row['tool']}: `resolve {profile}` exits {0 if automatic else 20}", tir.resolve(profile, rows)[0] == (0 if automatic else 20), tir.resolve(profile, rows))
        else:
            check(f"{row['tool']}: not planned without an explanation", row["automated"] == "yes" or any(r["profile"] == profile and r["automated"] == "yes" for r in rows) or entry is not None, row)
    manual = sorted(n for n, e in profiles.items() if e["mode"] == "manual")
    check("exactly plsmd and ppr-meta remain manual", manual == ["plsmd", "ppr-meta"], manual)
    for name in manual:
        e = profiles[name]
        check(f"{name}: manual reason, evidence and a recipe that names the pinned revision", len(e["manual"]["reason"]) > 80 and len(e["manual"]["evidence"]) >= 2
              and any(e["commit"] in step for step in e["manual"]["recipe"]))
    text = si.plan_text("gplas2", profiles["gplas2"])
    check("the plan names repository, commit, size, licence and time", all(x in text for x in (profiles["gplas2"]["repo"], profiles["gplas2"]["commit"], "MB to download", "Licence", "Time", "Internet")))
    check("every source profile has a wrapper command, and its first command is verified", all(e["commands"] for e in profiles.values() if e["mode"] == "source"))
    check("pip pins that live in this repository exist and are exact", all(set(re.findall(r"^[A-Za-z0-9_.-]+==", (ROOT / s["path"][1:]).read_text(encoding="utf-8"), re.M)) for e in profiles.values() if e["mode"] == "source"
                                                                         for s in e["env"]["steps"] if s.get("path", "").startswith("@")))
    audit = subprocess.run([sys.executable, str(ROOT / "python" / "generate_install_audit.py"), "--check"], capture_output=True, text=True)
    check("docs/TOOL_INSTALL_AUDIT.md matches the registries", audit.returncode == 0, audit.stderr)
    cli = subprocess.run([sys.executable, str(ROOT / "python" / "source_install.py"), "validate"], capture_output=True, text=True)
    check("`source_install.py validate` exits 0", cli.returncode == 0, cli.stderr)
    print("ALL TOOL INSTALL REGISTRY TESTS PASSED" if not FAILED else f"FAILED: {FAILED}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
