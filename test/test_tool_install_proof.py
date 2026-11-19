#!/usr/bin/env python3
"""python/tool_install_proof.py and config/install_proof.json (the table behind .github/workflows/tool-install-proof.yml).

The proof workflow installs every profile on a Linux runner; this test, which runs in the ordinary CI, keeps its table honest:
  - every profile env/install_tools.sh can install (its case branches, the `all` list and the registries' profiles) has an entry, so a new tool cannot be added
    without being proven;
  - an installed profile has at least one verification command; a manual or skipped profile has its reason;
  - the matrix helper rejects an unknown profile and lists the rest;
  - the aggregate table counts pass / expected-manual / expected-skip / failed, names a missing result as a failure, and exits 1 when a profile that should install did not.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))
import tool_install_proof as proof  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("  ok    " if ok else "  FAIL  ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILED.append(name)


check("the proof table covers every installable profile", proof.check() == [], proof.check())
config = proof.load_config()
names = proof.installable_profiles()
check("the installer's profiles are found (conda profiles, source-pinned profiles and the manual ones)",
      {"core", "assembly", "mobsuite", "reconstruction", "utilities", "plsmd", "ppr-meta"} <= set(names), names)
check("plsmd and ppr-meta are expected-manual and say why", all(config["profiles"][n].get("expect") == "manual" and len(config["profiles"][n]["reason"]) > 40 for n in ("plsmd", "ppr-meta")))
check("every installed profile has a verification", all(proof.verification_commands(n, e) for n, e in config["profiles"].items() if e.get("expect", "install") == "install"))
check("no profile is skipped without a reason", all(e.get("reason") for e in config["profiles"].values() if e.get("expect") in ("manual", "skip")))

done = subprocess.run([sys.executable, str(ROOT / "python" / "tool_install_proof.py"), "profiles", "--only", "core,nosuch"], capture_output=True, text=True)
check("an unknown profile in the workflow input is refused with its name", done.returncode == 2 and "nosuch" in done.stderr, done.stderr)
done = subprocess.run([sys.executable, str(ROOT / "python" / "tool_install_proof.py"), "profiles", "--only", "core,assembly", "--json"], capture_output=True, text=True)
check("the matrix of a chosen subset is a JSON list", json.loads(done.stdout) == ["core", "assembly"], done.stdout)
done = subprocess.run([sys.executable, str(ROOT / "python" / "tool_install_proof.py"), "profiles", "--only", "all", "--json"], capture_output=True, text=True)
check("'all' is every profile in the table", json.loads(done.stdout) == list(config["profiles"]))

with tempfile.TemporaryDirectory() as tmp:
    folder = Path(tmp)

    def result(profile, status, exit_code=0, **extra):
        data = dict({"profile": profile, "status": status, "exit_code": exit_code, "duration_seconds": 90, "verification": [{"command": "x --version", "exit_code": 0, "first_line": "1.0"}],
                     "version": "1.0", "provenance": {}, "problem": "", "reason": ""}, **extra)
        (folder / f"{profile}.json").write_text(json.dumps(data), encoding="utf-8")

    only = ["core", "assembly", "plsmd", "ppr-meta", "utilities"]
    import os
    os.environ["PROOF_ONLY"] = ",".join(only)
    result("core", "pass"); result("assembly", "pass"); result("plsmd", "expected-manual", 20, reason="docker only"); result("ppr-meta", "expected-manual", 20, reason="matlab"); result("utilities", "pass")
    summary = folder / "summary.txt"
    code = proof.aggregate(str(folder), str(summary))
    text = summary.read_text(encoding="utf-8")
    check("all pass or expected-manual: the aggregate succeeds and counts them", code == 0 and "3 installed and verified, 2 expected manual" in text and "0 failed" in text, text)
    result("assembly", "fail", 1, problem="unicycler did not solve")
    code = proof.aggregate(str(folder), str(summary))
    check("a profile that should install and did not fails the aggregate, with its problem in the table", code == 1 and "| assembly | FAIL |" in summary.read_text(encoding="utf-8") and "did not solve" in summary.read_text(encoding="utf-8"))
    result("assembly", "pass"); (folder / "utilities.json").unlink()
    code = proof.aggregate(str(folder), str(summary))
    check("a profile whose job uploaded no result is a failure, never silently absent", code == 1 and "no result was uploaded" in summary.read_text(encoding="utf-8"))
    result("utilities", "pass"); result("plsmd", "fail", 0, problem="expected exit 20")
    check("an expected-manual profile that installed (or exited otherwise) is a failure to be explained", proof.aggregate(str(folder), str(summary)) == 1)
import source_install as si  # noqa: E402
layout = si.Layout(Path("/m/envs/plasbench"), "plasbench", "x")
text = si.wrapper_text("nextflow", {"kind": "env_bin", "path": "nextflow", "unset_env": ["JAVA_CMD"], "set_env": {"JAVA_HOME": "{install}", "P": "{src}"}}, {"commit": "c" * 40}, layout, "x").replace(chr(92), "/")
check("a wrapper unsets and sets the environment its tool needs (a runner's JAVA_HOME, glibc's execstack tunable, a namespace package's PYTHONPATH)",
      "unset JAVA_CMD" in text and 'JAVA_HOME="/m/envs/plasbench-x"' in text and "export JAVA_HOME" in text and '/plasbench-src"' in text and text.index("unset JAVA_CMD") < text.index("exec "), text)
check("the registry still validates with those fields", si.validate(si.load()) == [], si.validate(si.load()))
import tempfile as _t
hdr = bytearray(64); hdr[:4] = bytes([127]) + b"ELF"; hdr[4] = 2; hdr[5] = 1
hdr[32:40] = (64).to_bytes(8, "little"); hdr[54:56] = (56).to_bytes(2, "little"); hdr[56:58] = (1).to_bytes(2, "little")
ph = bytearray(56); ph[:4] = si.PT_GNU_STACK.to_bytes(4, "little"); ph[4:8] = (7).to_bytes(4, "little")
with _t.TemporaryDirectory() as _d:
    so = Path(_d) / "libx.so"
    so.write_bytes(bytes(hdr + ph))
    changed, again = si.clear_execstack(so), si.clear_execstack(so)
    check("clear_execstack clears only the X flag of PT_GNU_STACK (rw- stays), once", changed and not again and int.from_bytes(so.read_bytes()[68:72], "little") == 6)
    txt = Path(_d) / "notelf.so"; txt.write_text("hello")
    check("a file that is not an ELF64 is left alone", si.clear_execstack(txt) is False and txt.read_text() == "hello")
print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL PASS")
sys.exit(1 if FAILED else 0)
