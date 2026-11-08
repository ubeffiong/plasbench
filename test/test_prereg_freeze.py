#!/usr/bin/env python3
"""Pre-registration freeze (python/freeze_prereg.py): --write locks the SHA-256,
--verify passes on an unchanged file and fails after an edit, --require-fixed
fails while a TO_FIX row remains, --check-env catches a departing config
variable, and the shipped config/prereg.tsv parses with every config_variable
defined in config/config.sh."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "python" / "freeze_prereg.py"
sys.path.insert(0, str(ROOT / "python"))
import freeze_prereg  # noqa: E402

HEADER = "parameter\tvalue\tconfig_variable\tspec_section\trevise_after_pilot\tstatus\tnote\n"


def run(*args, env=None):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                          env={**os.environ, **(env or {})})


def main():
    rows = freeze_prereg.read_rows(ROOT / "config" / "prereg.tsv")
    config = (ROOT / "config" / "config.sh").read_text(encoding="utf-8")
    for row in rows:
        var = (row.get("config_variable") or "").strip()
        assert not var or f"export {var}=" in config, f"{var} is not defined in config/config.sh"
    assert any(r["parameter"] == "primary_label_scheme" and r["value"] == "ncbi" for r in rows)
    assert any(r["parameter"] == "failed_tool_score" and r["value"] == "0" for r in rows)
    print(f"  PASS: shipped prereg.tsv parses ({len(rows)} parameters); every config_variable exists in config.sh")

    with tempfile.TemporaryDirectory() as tmp:
        tsv, lock = Path(tmp) / "prereg.tsv", Path(tmp) / "prereg.lock.json"
        tsv.write_text(HEADER + "alpha\t0.95\tPERFECT_THRESHOLD\t7\tyes\tfixed\t\n"
                       "beta\t3\t\t9\tyes\tTO_FIX\tprovisional\n", encoding="utf-8")
        assert run("--verify", "--prereg", str(tsv), "--lock", str(lock)).returncode == 1
        out = run("--write", "--prereg", str(tsv), "--lock", str(lock))
        assert out.returncode == 0, out.stderr
        data = json.loads(lock.read_text())
        assert data["to_fix"] == ["beta"] and len(data["sha256"]) == 64
        assert run("--verify", "--prereg", str(tsv), "--lock", str(lock)).returncode == 0
        print("  PASS: no lock -> verify fails; --write locks sha256 and TO_FIX list; verify passes")

        assert run("--verify", "--require-fixed", "--prereg", str(tsv), "--lock", str(lock)).returncode == 1
        print("  PASS: --require-fixed fails while a TO_FIX row remains")

        bad = run("--verify", "--check-env", "--prereg", str(tsv), "--lock", str(lock), env={"PERFECT_THRESHOLD": "0.90"})
        assert bad.returncode == 1 and "departs" in bad.stderr, bad.stderr
        same = run("--verify", "--check-env", "--prereg", str(tsv), "--lock", str(lock), env={"PERFECT_THRESHOLD": "0.950"})
        assert same.returncode == 0, same.stderr
        print("  PASS: --check-env flags PERFECT_THRESHOLD=0.90 vs planned 0.95; 0.950 is the same number")

        tsv.write_text(tsv.read_text() + "gamma\t1\t\t7\tno\tfixed\t\n", encoding="utf-8")
        stale = run("--verify", "--prereg", str(tsv), "--lock", str(lock))
        assert stale.returncode == 1 and "changed after it was frozen" in stale.stderr
        status = json.loads(run("--status", "--prereg", str(tsv), "--lock", str(lock)).stdout)
        assert status["locked"] and not status["matches"] and status["parameters"] == 3
        print("  PASS: editing after the freeze fails verify; --status reports locked but not matching")

        tsv.write_text(HEADER + "x\t1\t\t7\tno\tmaybe\t\n", encoding="utf-8")
        assert run("--write", "--prereg", str(tsv), "--lock", str(lock)).returncode == 1
        print("  PASS: an invalid status is rejected")
    print("ALL PREREG TESTS PASSED")


if __name__ == "__main__":
    main()
