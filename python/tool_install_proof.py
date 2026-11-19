#!/usr/bin/env python3
"""Prove, on a clean Linux runner, that every tool PlasBench installs really installs (.github/workflows/tool-install-proof.yml).

  profiles [--only a,b]        the profiles to prove, one per line, or as the JSON matrix the workflow reads (--json)
  run PROFILE --out FILE       run the project's own `plasbench install-tools PROFILE --yes`, then the profile's verification, and write one JSON result
  aggregate DIR [--summary F]  one table of every result (pass / fail / expected-manual); exit 1 when a profile that should install did not
  check                        the proof table covers every profile install_tools.sh can install (a test runs this in the ordinary CI)

config/install_proof.json is the table. A profile is `expect: install` (default) or `expect: manual` (it must exit 20 with a reason: pass only then), and lists the
commands that prove the installed tools start (`verify`, each run on the tool's own PATH). The registry's own verify_command (config/tool_installers.tsv) is run too.
A verification is never relaxed to get a green run: a profile that cannot be proven on a runner is recorded with the reason in `expect`, and shows in the table.
Standard library only.
"""
import argparse
import csv
import glob
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "install_proof.json"
INSTALLERS = ROOT / "config" / "tool_installers.tsv"
META_INSTALLERS = ROOT / "config" / "metagenomic_tool_installers.tsv"
INSTALL_SH = ROOT / "env" / "install_tools.sh"
EXIT_MANUAL = 20
LOG_LINES = 200


def load_config():
    with open(CONFIG, encoding="utf-8") as handle:
        return json.load(handle)


def installer_rows():
    rows = []
    for path in (INSTALLERS, META_INSTALLERS):
        if path.is_file():
            with open(path, newline="", encoding="utf-8") as handle:
                rows += list(csv.DictReader(handle, delimiter="\t"))
    return rows


def installable_profiles():
    """Every profile name env/install_tools.sh can install by name: the `case` branches, the `all` list and the registry's profiles."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    names = set(re.findall(r"^ ([a-z0-9][a-z0-9_-]*)\)", text, re.M))
    names -= {"all", "locked", "list", "plan", "validate"}
    match = re.search(r'ALL_PROFILES="([^"]+)"', text)
    if match:
        names |= set(match.group(1).split())
    names |= {row["profile"] for row in installer_rows() if row.get("profile") and row.get("install_mode") != "builtin"}
    return sorted(names)


def check():
    """The proof table and the installer agree. Returns a list of problems (empty: consistent)."""
    config = load_config()
    table = set(config["profiles"])
    problems = []
    for name in installable_profiles():
        if name not in table:
            problems.append(f"profile '{name}' can be installed by env/install_tools.sh but has no entry in config/install_proof.json (add it, with its verification, or mark it expect: manual with the reason)")
    for name, entry in config["profiles"].items():
        if entry.get("expect", "install") not in ("install", "manual", "skip"):
            problems.append(f"{name}: expect must be install, manual or skip")
        if entry.get("expect") in ("manual", "skip") and not entry.get("reason"):
            problems.append(f"{name}: expect = {entry.get('expect')} needs a reason (shown in the proof table)")
        if entry.get("expect", "install") == "install" and not (entry.get("verify") or [r for r in installer_rows() if r.get("profile") == name and r.get("verify_command")]):
            problems.append(f"{name}: an installed profile needs at least one verification command")
    return problems


def verification_commands(profile, entry):
    commands = list(entry.get("verify", []))
    for row in installer_rows():
        if row.get("profile") == profile and row.get("verify_command") and row["verify_command"] not in commands and row.get("install_mode") != "builtin":
            commands.append(row["verify_command"])
    return commands


def main_prefix(env_name):
    """The prefix of the main environment, as the installer resolves it."""
    conda = os.environ.get("CONDA_EXE") or "conda"
    try:
        base = subprocess.run([conda, "info", "--base"], capture_output=True, text=True, timeout=120).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        base = ""
    for root in (base, os.path.expanduser("~/miniforge3"), os.path.expanduser("~/micromamba")):
        if root and os.path.isdir(os.path.join(root, "envs", env_name)):
            return os.path.join(root, "envs", env_name)
    return ""


def tail(text, lines=LOG_LINES):
    return "\n".join(text.splitlines()[-lines:])


def provenance_of(profile, prefix):
    """Provenance files the installer wrote for this profile: the source-install record (plasbench-install.json) and the wrappers' header lines."""
    found = {}
    if not prefix:
        return found
    parent = Path(prefix).parent
    for path in glob.glob(str(parent / "**" / "plasbench-install.json"), recursive=True):
        try:
            record = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if profile in (record.get("profile"), record.get("name")) or profile in path:
            found[path] = {k: record[k] for k in ("profile", "ref", "commit", "pinned_commit", "installed_utc", "revision", "verified") if k in record}
    return found


def run_profile(profile, out, env_name):
    config = load_config()
    entry = config["profiles"].get(profile)
    if entry is None:
        print(f"{profile}: not in config/install_proof.json", file=sys.stderr)
        return 2
    expect = entry.get("expect", "install")
    result = {"profile": profile, "expect": expect, "reason": entry.get("reason", ""), "exit_code": None, "duration_seconds": 0, "status": "fail",
              "verification": [], "version": "", "provenance": {}, "log_tail": "", "problem": ""}
    if expect == "skip":
        result.update(status="expected-skip", problem=entry["reason"])
        Path(out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return 0
    started = time.time()
    log_path = Path(out).with_suffix(".log")
    command = [sys.executable, "-m", "plasbench", "install-tools", "--env", env_name, "--yes", profile]
    with open(log_path, "w", encoding="utf-8") as log:
        done = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, text=True, timeout=int(entry.get("timeout_minutes", 55)) * 60)
    result["exit_code"] = done.returncode
    result["duration_seconds"] = round(time.time() - started)
    text = log_path.read_text(encoding="utf-8", errors="replace")
    result["log_tail"] = tail(text)
    prefix = main_prefix(env_name)
    if expect == "manual":
        ok = done.returncode == EXIT_MANUAL and re.search(r"manual|cannot be installed automatically|verified limit", text, re.I) is not None
        result["status"] = "expected-manual" if ok else "fail"
        if not ok:
            result["problem"] = f"expected exit {EXIT_MANUAL} with a reason; got exit {done.returncode}"
        result["problem"] = result["problem"] or entry.get("reason", "")
    elif done.returncode != 0:
        result["problem"] = f"install-tools exited {done.returncode}"
    else:
        env = dict(os.environ, PATH=os.path.join(prefix, "bin") + os.pathsep + os.environ.get("PATH", "")) if prefix else dict(os.environ)
        bad = 0
        for verify in verification_commands(profile, entry):
            try:
                check_run = subprocess.run(["bash", "-c", verify], capture_output=True, text=True, timeout=300, env=env, cwd=ROOT)
                first = (check_run.stdout + check_run.stderr).strip().splitlines()
                first = first[0][:200] if first else ""
                code = check_run.returncode
            except subprocess.TimeoutExpired:
                first, code = "timed out after 300 s", 124
            result["verification"].append({"command": verify, "exit_code": code, "first_line": first})
            bad += code != 0
        pending = [v for v in result["verification"] if v["exit_code"] == 0]
        result["version"] = pending[0]["first_line"] if pending else ""
        result["status"] = "pass" if not bad and result["verification"] else "fail"
        if bad:
            result["problem"] = "verification failed: " + "; ".join(f"`{v['command']}` exit {v['exit_code']}" for v in result["verification"] if v["exit_code"] != 0)
        elif not result["verification"]:
            result["problem"] = "no verification command ran"
    result["provenance"] = provenance_of(profile, prefix)
    Path(out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{profile}: {result['status']} (exit {result['exit_code']}, {result['duration_seconds']} s)")
    return 0


def aggregate(folder, summary=None):
    config = load_config()
    results = {}
    for path in sorted(Path(folder).rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(data, dict) and "profile" in data and "status" in data:
            results[data["profile"]] = data
    expected = [p for p in config["profiles"] if os.environ.get("PROOF_ONLY") in (None, "") or p in os.environ["PROOF_ONLY"].split(",")]
    lines = ["| Profile | Result | Exit | Minutes | Version / revision | Verified commands | Note |", "| --- | --- | --- | --- | --- | --- | --- |"]
    failed = []
    for profile in expected:
        data = results.get(profile)
        if data is None:
            lines.append(f"| {profile} | FAIL | | | | | no result was uploaded (the job did not finish) |")
            failed.append(profile)
            continue
        status = {"pass": "pass", "expected-manual": "expected-manual", "expected-skip": "expected-skip"}.get(data["status"], "FAIL")
        verified = ", ".join(f"`{v['command'].split()[0]}`" for v in data.get("verification", []) if v["exit_code"] == 0)
        revision = data.get("version", "")
        for path, record in data.get("provenance", {}).items():
            revision = (record.get("commit") or record.get("pinned_commit") or revision)[:40]
        note = (data.get("problem") or data.get("reason") or "").replace("|", "/").replace("\n", " ")[:300]
        lines.append(f"| {profile} | {status} | {data.get('exit_code')} | {round((data.get('duration_seconds') or 0) / 60, 1)} | {str(revision).replace('|', '/')[:60]} | {verified} | {note} |")
        if status == "FAIL":
            failed.append(profile)
    counts = {k: sum(1 for p in expected if (results.get(p) or {}).get("status") == k) for k in ("pass", "expected-manual", "expected-skip")}
    head = f"**{counts['pass']} installed and verified, {counts['expected-manual']} expected manual (exit 20 with a reason), {counts['expected-skip']} expected skip, {len(failed)} failed** of {len(expected)} profiles."
    text = "## Tool installation proof\n\n" + head + "\n\n" + "\n".join(lines) + "\n"
    print(text)
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(text)
    Path(folder, "summary.md").write_text(text, encoding="utf-8")
    if failed:
        print("FAILED PROFILES: " + ", ".join(failed), file=sys.stderr)
        return 1
    return 0


RESULT = ROOT / "config" / "install_proof_result.json"


def record(folder, run_url, date):
    """Keep what a proof run showed (docs/TOOL_INSTALL_AUDIT.md's 'CI proof' column is generated from it): per profile the status, minutes and version, with the run's URL and date."""
    profiles = {}
    for path in sorted(Path(folder).rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(data, dict) and "profile" in data and "status" in data:
            profiles[data["profile"]] = {"status": data["status"], "minutes": round((data.get("duration_seconds") or 0) / 60, 1), "version": data.get("version", ""),
                                         "problem": data.get("problem", "")}
    with open(RESULT, "w", encoding="utf-8", newline="\n") as handle:
        json.dump({"run_url": run_url, "date": date, "profiles": profiles}, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(f"recorded {len(profiles)} profiles from {run_url}")
    return 0


def matrix(only):
    config = load_config()
    names = [p for p in config["profiles"] if not only or p in only]
    return names


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("profiles")
    p.add_argument("--only", default="")
    p.add_argument("--json", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("profile")
    r.add_argument("--out", required=True)
    r.add_argument("--env", default="plasbench")
    a = sub.add_parser("aggregate")
    a.add_argument("folder")
    a.add_argument("--summary", default=os.environ.get("GITHUB_STEP_SUMMARY", ""))
    rec = sub.add_parser("record")
    rec.add_argument("folder")
    rec.add_argument("--run-url", required=True)
    rec.add_argument("--date", required=True)
    sub.add_parser("check")
    args = parser.parse_args(argv)
    if args.command == "profiles":
        only = [x for x in re.split(r"[,\s]+", args.only.strip()) if x and x.lower() != "all"]
        unknown = [x for x in only if x not in load_config()["profiles"]]
        if unknown:
            print("unknown profile(s): " + ", ".join(unknown), file=sys.stderr)
            return 2
        names = matrix(only)
        print(json.dumps(names) if args.json else "\n".join(names))
        return 0
    if args.command == "run":
        return run_profile(args.profile, args.out, args.env)
    if args.command == "record":
        return record(args.folder, args.run_url, args.date)
    if args.command == "aggregate":
        return aggregate(args.folder, args.summary or None)
    problems = check()
    for problem in problems:
        print("ERROR: " + problem, file=sys.stderr)
    print("the proof table covers every installable profile" if not problems else "")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
