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
    # proposed values: the plan is a DRAFT until they are confirmed (A5)
    with tempfile.TemporaryDirectory() as tmp:
        tsv, lock = Path(tmp) / "prereg.tsv", Path(tmp) / "prereg.lock.json"
        tsv.write_text(HEADER + "alpha\t0.95\tPERFECT_THRESHOLD\t7\tyes\tfixed\t\n"
                       "beta\t7200\t\t9\tyes\tproposed\trationale\n"
                       "gamma\tunset\t\t9\tyes\tTO_FIX\tno value yet\n", encoding="utf-8")
        status = json.loads(run("--status", "--prereg", str(tsv), "--lock", str(lock)).stdout)
        assert status["proposed"] == ["beta"] and status["to_fix"] == ["gamma"] and status["draft"] is True and not status["error"], status
        print("  PASS: --status lists proposed and TO_FIX rows separately and reports a draft")
        draft = run("--write", "--prereg", str(tsv), "--lock", str(lock))
        assert draft.returncode == 0 and "DRAFT freeze" in draft.stdout, draft.stdout + draft.stderr
        data = json.loads(lock.read_text())
        assert data["proposed"] == ["beta"] and data["to_fix"] == ["gamma"] and data["draft"] is True
        print("  PASS: a draft can be locked (the lock records the proposed and TO_FIX rows and draft=true)")
        lock.unlink()
        strict = run("--write", "--strict", "--prereg", str(tsv), "--lock", str(lock))
        assert strict.returncode == 1 and "still a draft" in strict.stderr and "beta" in strict.stderr and not lock.exists(), strict.stderr
        print("  PASS: --write --strict refuses to freeze a draft and writes no lock")
        run("--write", "--prereg", str(tsv), "--lock", str(lock))
        assert run("--verify", "--require-fixed", "--prereg", str(tsv), "--lock", str(lock)).returncode == 1
        bad = run("--verify", "--strict", "--prereg", str(tsv), "--lock", str(lock))
        assert bad.returncode == 1 and "proposed or TO_FIX" in bad.stderr and "beta" in bad.stderr, bad.stderr
        print("  PASS: --require-fixed and --verify --strict fail on a proposed row")
        tsv.write_text(HEADER + "alpha\t0.95\tPERFECT_THRESHOLD\t7\tyes\tfixed\t\nbeta\t7200\t\t9\tyes\tfixed\tconfirmed\n", encoding="utf-8")
        final = run("--write", "--strict", "--prereg", str(tsv), "--lock", str(lock))
        assert final.returncode == 0, final.stderr
        assert run("--verify", "--strict", "--require-fixed", "--prereg", str(tsv), "--lock", str(lock)).returncode == 0
        status = json.loads(run("--status", "--prereg", str(tsv), "--lock", str(lock)).stdout)
        assert status["draft"] is False and status["proposed"] == [] and status["to_fix"] == []
        print("  PASS: once every row is fixed, --strict freezes and verifies, and the status is no longer a draft")

    shipped = freeze_prereg.read_rows(ROOT / "config" / "prereg.tsv")
    names = {r["parameter"]: r for r in shipped}
    assert names["tool_timeout_seconds"]["status"] == "proposed" and names["tool_timeout_seconds"]["value"] == "7200"
    assert "rationale" in names["tool_timeout_seconds"]["note"].lower() or "proposed" in names["tool_timeout_seconds"]["note"].lower()
    assert names["scorecard_bands_A4_C2"]["status"] == "TO_FIX"
    assert names["min_alignment_length"]["status"] == "fixed" and names["min_alignment_length"]["value"] == "200"
    assert not [r for r in shipped if r["status"] == "TO_FIX" and r["parameter"] != "scorecard_bands_A4_C2" and (r["note"] or "").startswith("Proposed default")], "a proposed default must be status proposed"
    print("  PASS: the shipped plan proposes the tool timeout (7200 s) with its rationale, keeps A4/C2 TO_FIX, pre-registers min_alignment_length")

    import report_scoring_spec as spec
    html = str(spec.prereg_section({"preregistration": {"sha256": "ab" * 32, "locked": True, "matches": True, "frozen_at": "2026-01-01", "parameters": 3,
                                                        "to_fix": ["gamma"], "proposed": ["beta"], "draft": True, "env_mismatches": []}}))
    assert "a DRAFT: 2 value(s)" in html and "Proposed, awaiting confirmation" in html and "beta" in html and "gamma" in html, html
    final_html = str(spec.prereg_section({"preregistration": {"sha256": "ab" * 32, "locked": True, "matches": True, "frozen_at": "x", "parameters": 3,
                                                              "to_fix": [], "proposed": [], "draft": False, "env_mismatches": []}}))
    assert "frozen and unchanged" in final_html and "DRAFT" not in final_html
    print("  PASS: the report's Pre-registration tab shows the draft state and the proposed rows; a confirmed plan shows no draft")
    print("ALL PREREG TESTS PASSED")


if __name__ == "__main__":
    main()
